<script setup>
// 新建 / 编辑草稿 / PMC 补录修改：同一张表单页（采购申请和购买申请共用）。
//   新建、草稿：  /approval/procurement/new[?draft=单号]   /approval/direct-purchase/new[?draft=单号]
//   PMC 补录修改：/approval/procurement/:name/pmc-edit（只有 PMC 在 PMC 节点能改物料明细、预计交期、主题、申请说明）
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { buildApprovalCenterPayload, organizationPreflightMessage, validateProcurementRequestForm } from '../../lib/procurementWorkflow.js';
import {
  FIXED_ASSET_CATEGORIES, REQUEST_PROCUREMENT, blankForm, blankLine, expenseCategoryOf, formBlockers, formFromRow,
  money, pmcLines, routePreviewParams, summarizeLines, validateRequestForm,
} from '../../lib/procurementView.js';
import '../../styles/navUi.css';
import { backLocation, carryQuery, fromValue, originLabel } from '../../lib/navContext.js';
import { useLeaveConfirm } from '../../lib/leaveConfirm.js';
import { canMaintainCatalog } from './access.js';
import { apiGet, apiPost, errText } from './procData.js';
import { useProc } from './context.js';
import ProcLineEditor from './ProcLineEditor.vue';
import ProcCatalogTools from './ProcCatalogTools.vue';
import ProcDocuments from './ProcDocuments.vue';

const ctx = useProc();
const route = useRoute();
const router = useRouter();
const isPmc = route.name === 'procurement-pmc-edit';
const isProcurement = ctx.isProcurement;
const form = reactive(blankForm());
const draftName = ref(isPmc ? '' : String(route.query.draft || ''));
const requestRow = ref(null);
const loading = ref(true);
const saving = ref(false);
const problem = ref('');
const categories = ref([]);
const suggestions = reactive({});
const routeSteps = ref([]);
const routeNote = ref('');
const catalogOpen = ref(false);
const lineBox = ref(null);
const expenseCategory = computed(() => expenseCategoryOf(form, ctx.departments));
let previewTimer = null;

// 表单有没有改过：打开 / 保存之后的快照对比现在的内容；改过再离开（取消、面包屑、侧栏、后退、关标签页）要确认。
const baseline = ref('');
const fingerprint = () => JSON.stringify({ form, draft: draftName.value });
const isDirty = () => !loading.value && baseline.value !== '' && fingerprint() !== baseline.value;
function markClean() {
  baseline.value = fingerprint();
}
useLeaveConfirm(isDirty);

// 往回走：从列表来的回到同一个范围 / 阶段 / 搜索词的列表，从首页 / 别的页面来的回到那里，其他入口回到首页。
const cameFromList = computed(() => fromValue(route.query) === 'list');
const originText = computed(() => {
  const from = fromValue(route.query);
  return from && from !== 'list' ? (originLabel(route.query) || '上一页') : '';
});
function goBack() {
  ctx.flash();
  router.push(backLocation(ctx.basePath, route.query));
}

const orgWarning = computed(() => (isPmc ? '' : organizationPreflightMessage(ctx.requestType, ctx.options?.context || {})));
const summary = computed(() => summarizeLines(form.business_lines, ctx.requestType));
const blockers = computed(() => (isPmc ? pmcBlockers() : formBlockers(form, ctx.requestType)));
const canCatalog = computed(() => isProcurement && (canMaintainCatalog() || ctx.canManageCatalog));
const title = computed(() => {
  if (isPmc) return `PMC 补录 / 修改：${requestRow.value?.subject || route.params.name}`;
  return `${draftName.value ? '编辑草稿' : '新建'}${ctx.label}`;
});
const applicantName = computed(() => ctx.applicants.find((item) => item.name === form.applicant_employee)?.employee_name
  || ctx.options?.current_applicant?.employee_name || '未关联员工');
const purchaserName = computed(() => ctx.purchasers.find((item) => item.name === form.purchaser_user)?.full_name || '未配置');

function projectLabel(project) {
  const code = project?.rd_project_code || project?.project_code || project?.name || '';
  const name = project?.project_name || project?.name || '';
  const owner = project?.project_owner_name || project?.project_owner || '未配置负责人';
  return `${code}${name && name !== code ? ` · ${name}` : ''} · 负责人：${owner}`;
}

// PMC 页面只校验 PMC 能改的东西：主题、预计交期、物料明细。
function pmcBlockers() {
  const list = [];
  if (!String(form.subject || '').trim()) list.push('主题未填');
  if (!String(form.expected_delivery_date || '').trim()) list.push('预计交期未填');
  const lineProblem = validateProcurementRequestForm(form, REQUEST_PROCUREMENT);
  if (lineProblem) list.push(lineProblem);
  return list;
}

async function loadCategories() {
  if (!isProcurement) return;
  try {
    categories.value = (await apiGet('procurement_materials.list_categories', { limit: 2000 })) || [];
  } catch (error) {
    ctx.flash('', errText(error, '物料分类加载失败'));
  }
}

async function suggestFor(line) {
  if (!isPmc || !line || line.material_code) return;
  try {
    suggestions[line._uid] = await apiGet('procurement_materials.suggest_material', {
      item_name: line.item_name, specification: line.specification, product_desc: line.product_desc,
      brand: line.brand, category_code: line.category_code, limit: 5,
    });
  } catch (error) {
    ctx.flash('', errText(error, '物料重复建议生成失败'));
  }
}

async function init() {
  loading.value = true;
  try {
    if (isPmc) {
      const name = String(route.params.name || '');
      const rows = await apiGet('oa_entry.list_requests', { view: 'all', request_type: REQUEST_PROCUREMENT, name, limit: 1 });
      const row = rows?.[0];
      if (!row) { problem.value = 'missing'; return; }
      requestRow.value = row;
      if (!row.can_modify_procurement_request) { problem.value = 'forbidden'; return; }
      Object.assign(form, formFromRow(row));
      routeSteps.value = (row.steps || []).map((step) => step.label);
      loadCategories();
      for (const line of form.business_lines) await suggestFor(line);
    } else if (draftName.value) {
      const rows = await apiGet('oa_entry.list_requests', { view: 'mine', request_type: ctx.requestType, name: draftName.value, limit: 1 });
      const row = rows?.[0];
      if (!row || row.workflow_status !== '草稿') { problem.value = 'draft'; return; }
      requestRow.value = row;
      Object.assign(form, formFromRow(row));
      loadCategories();
    } else {
      loadCategories();
    }
  } catch (error) {
    ctx.flash('', errText(error, '页面加载失败'));
  } finally {
    loading.value = false;
    markClean();
  }
}

onMounted(init);
onBeforeUnmount(() => clearTimeout(previewTimer));

// 申请人 / 采购经办人的默认值：选项接口晚到时再补。
watch(() => [ctx.applicants, ctx.purchasers, loading.value], () => {
  if (loading.value || isPmc || !isProcurement) return;
  const wasClean = !isDirty();
  if (!form.applicant_employee && ctx.applicants.length) form.applicant_employee = ctx.applicants.find((item) => item.name === ctx.currentEmployee)?.name || ctx.applicants[0].name;
  if (!form.purchaser_user && ctx.purchasers.length) form.purchaser_user = ctx.purchasers[0].name;
  // 默认值是系统填的，不算用户改过。
  if (wasClean) markClean();
}, { immediate: true, deep: true });

async function loadRoute() {
  try {
    const result = await apiGet('oa_entry.preview_route', routePreviewParams(form, ctx.requestType, ctx.projects));
    routeSteps.value = (result?.steps || []).map((step) => step.label);
    routeNote.value = '';
  } catch (error) {
    routeSteps.value = [];
    routeNote.value = errText(error, '');
  }
}

watch(() => [form.purchase_method, form.project, form.procurement_scope, form.applicant_employee, loading.value], () => {
  if (loading.value || isPmc) return;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(loadRoute, 300);
}, { immediate: true });

// 改了表单，上一次的错误提示就过期了（成功提示保留）。
watch(form, () => {
  if (!loading.value && !saving.value && ctx.banner.err) ctx.flash(ctx.banner.ok, '');
}, { deep: true });

function addLine() {
  if (form.business_lines.length < 100) form.business_lines.push(blankLine());
}

async function persist() {
  const result = await apiPost('oa_entry.save_approval_center_draft', {
    request_type: ctx.requestType, payload: JSON.stringify(buildApprovalCenterPayload(form, ctx.requestType)), name: draftName.value || undefined,
  });
  draftName.value = result.name;
  markClean();
  return result.name;
}

async function saveDraft() {
  saving.value = true;
  ctx.flash();
  try {
    const name = await persist();
    await router.replace({ name: route.name, query: { draft: name, ...carryQuery(route.query) } });
    ctx.flash(`草稿 ${name} 已保存`);
  } catch (error) {
    ctx.flash('', errText(error, '保存失败'));
  } finally {
    saving.value = false;
  }
}

async function submit() {
  ctx.flash();
  if (orgWarning.value) { ctx.flash('', orgWarning.value); return; }
  const message = validateRequestForm(form, ctx.requestType);
  if (message) { ctx.flash('', message); return; }
  saving.value = true;
  try {
    const name = await persist();
    await apiPost('oa_entry.submit_approval_center_draft', { name });
    ctx.go({ request: name }, `${name} 已提交审批`);
  } catch (error) {
    ctx.flash('', errText(error, '提交失败'));
  } finally {
    saving.value = false;
  }
}

async function savePmc() {
  const message = pmcBlockers()[0];
  if (message) { ctx.flash('', message); return; }
  saving.value = true;
  ctx.flash();
  try {
    const name = requestRow.value.name;
    await apiPost('oa_entry.modify_procurement_request', {
      name, business_lines: JSON.stringify(pmcLines(form.business_lines)), expected_delivery_date: form.expected_delivery_date,
      reason: form.reason, subject: form.subject,
    });
    markClean();
    ctx.go({ request: name, ...carryQuery(route.query) }, `${name} 已保存 PMC 修改并抄送相关人员`);
  } catch (error) {
    ctx.flash('', errText(error, 'PMC 修改保存失败'));
  } finally {
    saving.value = false;
  }
}

// 取消：回到来的地方（列表的同一份筛选 / 首页 / 看板 / 单据详情），不再一律回首页；改过没保存会先问一声。
function cancel() {
  if (isPmc) ctx.go({ request: requestRow.value?.name || String(route.params.name || ''), ...carryQuery(route.query) });
  else goBack();
}

function lineTotal(line) {
  return Number(line.quantity || 0) * Number(line.unit_price || 0);
}
</script>

<template>
  <div class="pr-form-page">
    <div class="ph">
      <div>
        <div class="crumb">
          <button v-if="originText && !isPmc" type="button" class="link nav-back" @click="goBack">← 返回{{ originText }}</button>
          <button type="button" class="link" @click="ctx.go({})">{{ ctx.label }}</button> ›
          <template v-if="cameFromList && !isPmc"><button type="button" class="link" @click="goBack">列表</button> › </template>
          <template v-if="isPmc"><button type="button" class="link" @click="ctx.go({ request: String(route.params.name), ...carryQuery(route.query) })">{{ route.params.name }}</button> › PMC 补录/修改</template>
          <template v-else>{{ draftName ? `编辑草稿 ${draftName}` : '新建' }}</template>
        </div>
        <h3>{{ title }}</h3>
      </div>
      <span v-if="isPmc" class="pill p-brand pr-pmc-tag">只有 PMC 在 PMC 节点能改：物料明细、预计交期、主题、申请说明；其他字段只读。物料流水号由系统生成，不能改</span>
    </div>

    <div v-if="problem === 'missing'" class="panel empty">采购申请不存在或已被删除。<button type="button" class="link" @click="ctx.go({})">返回采购申请</button></div>
    <div v-else-if="problem === 'forbidden'" class="panel empty">当前账号没有 PMC 编辑权限：只有动态指定的 PMC 账号，且申请处于 PMC 节点时，才能补充或修改物料。<button type="button" class="link" @click="ctx.go({ request: String(route.params.name) })">返回单据</button></div>
    <div v-else-if="problem === 'draft'" class="panel empty">找不到草稿 {{ draftName }}，可能已提交或已被删除。<button type="button" class="link" @click="ctx.go({})">返回{{ ctx.label }}</button></div>
    <div v-else-if="loading" class="panel empty" aria-live="polite">正在加载…</div>
    <template v-else>
      <div v-if="orgWarning" class="banner err" role="alert">{{ orgWarning }}</div>
      <div class="new-grid">
        <div>
          <section class="panel">
            <div class="pt">基本信息</div>

            <div v-if="!isProcurement" class="f pr-method-wrap">
              <label>购买方式</label>
              <div class="pr-methods">
                <button type="button" :class="['pr-method', { on: form.purchase_method === '京东购买' }]" :aria-pressed="form.purchase_method === '京东购买'" @click="form.purchase_method = '京东购买'">
                  <b>京东购买</b><span class="muted">审批：人事经理 + 演示员工113经理 会签</span>
                </button>
                <button type="button" :class="['pr-method', { on: form.purchase_method === '其他购买' }]" :aria-pressed="form.purchase_method === '其他购买'" @click="form.purchase_method = '其他购买'">
                  <b>其他购买</b><span class="muted">审批：直属部门主管 → 演示员工113经理</span>
                </button>
              </div>
            </div>

            <div class="pr-form-grid">
              <div class="f s2"><label>主题<b>*</b></label><input v-model="form.subject" maxlength="140" /></div>
              <div class="f">
                <label>紧急程度</label>
                <div class="pr-toggle" role="group" aria-label="紧急程度">
                  <button type="button" :aria-pressed="form.urgency === '一般'" :disabled="isPmc" @click="form.urgency = '一般'">一般</button>
                  <button type="button" class="hot" :aria-pressed="form.urgency === '加急'" :disabled="isPmc" @click="form.urgency = '加急'">加急</button>
                </div>
              </div>
              <div class="f"><label>预计交期<b>*</b></label><input v-model="form.expected_delivery_date" type="date" /></div>

              <template v-if="isProcurement">
                <div v-if="ctx.canSubmitForOthers" class="f">
                  <label>申请人</label>
                  <select v-model="form.applicant_employee" :disabled="isPmc"><option v-for="employee in ctx.applicants" :key="employee.name" :value="employee.name">{{ employee.employee_name }} · {{ employee.department || '未分配部门' }}</option></select>
                  <div class="h">有代提权限才能改</div>
                </div>
                <div v-else class="f"><label>申请人</label><div class="pr-static">{{ applicantName }}</div></div>
                <div class="f"><label>采购经办人</label><div class="pr-static">{{ purchaserName }}</div></div>
              </template>

              <div class="f">
                <label>资产属性</label>
                <div class="pr-toggle" role="group" aria-label="资产属性">
                  <button type="button" :aria-pressed="form.asset_nature === '非固定资产'" :disabled="isPmc" @click="form.asset_nature = '非固定资产'">非固定资产</button>
                  <button type="button" :aria-pressed="form.asset_nature === '固定资产'" :disabled="isPmc" @click="form.asset_nature = '固定资产'">固定资产</button>
                </div>
              </div>
              <div v-if="!isProcurement && form.asset_nature === '固定资产'" class="f">
                <label>固定资产类别<b>*</b></label>
                <select v-model="form.fixed_asset_category"><option value="">请选择</option><option v-for="item in FIXED_ASSET_CATEGORIES" :key="item" :value="item">{{ item }}</option></select>
              </div>

              <template v-if="isProcurement">
                <div class="f">
                  <label>采购范围</label>
                  <div class="pr-toggle" role="group" aria-label="采购范围">
                    <button type="button" :aria-pressed="form.procurement_scope === '项目采购'" :disabled="isPmc" @click="form.procurement_scope = '项目采购'">项目采购</button>
                    <button type="button" :aria-pressed="form.procurement_scope === '非项目采购'" :disabled="isPmc" @click="form.procurement_scope = '非项目采购'">非项目</button>
                  </div>
                </div>
                <div v-if="form.procurement_scope === '项目采购'" class="f s2">
                  <label>所属项目<b>*</b></label>
                  <select v-model="form.project" :disabled="isPmc"><option value="">请选择项目</option><option v-for="project in ctx.projects" :key="project.name" :value="project.name">{{ projectLabel(project) }}</option></select>
                  <div class="h">项目采购的费用一律记研发费用。</div>
                </div>
                <div v-else class="f s2">
                  <label>所属部门<b>*</b></label>
                  <select v-model="form.non_project_department" :disabled="isPmc"><option value="">请选择部门</option><option v-for="item in ctx.departments" :key="item.name" :value="item.name">{{ item.label }}</option></select>
                  <div class="h">费用类别跟着部门的性质走：研发部门记研发费用，制造部记生产成本，销售和客服记销售费用，其余记管理费用。</div>
                </div>
                <div class="f">
                  <label>费用类别</label>
                  <input :value="expenseCategory" readonly placeholder="选好项目或部门后自动带出" aria-label="费用类别" />
                </div>
              </template>
              <div v-else class="f s2">
                <label>所属项目</label>
                <select v-model="form.project"><option value="">非项目购买</option><option v-for="project in ctx.projects" :key="project.name" :value="project.name">{{ projectLabel(project) }}</option></select>
              </div>

              <div class="f pr-wide"><label>申请说明</label><textarea v-model="form.reason" rows="2" maxlength="1000"></textarea></div>
            </div>
          </section>

          <section class="panel">
            <div class="pt">
              <span>{{ isProcurement ? '物料明细' : '购买明细' }} <span class="muted">{{ form.business_lines.length }} 项 · 最多 100 项<template v-if="isProcurement"> · 编号至少选到三级分类</template></span>
                <template v-if="canCatalog"><span class="muted pr-catalog-link"> PMC / 采购经理：<button type="button" class="link" @click="catalogOpen = !catalogOpen">{{ catalogOpen ? '收起目录维护' : '新增分类 · 新增正式物料' }}</button></span></template>
              </span>
              <button type="button" class="btn sm" @click="addLine">＋ 添加一行</button>
            </div>
            <ProcCatalogTools v-if="canCatalog && catalogOpen" @category-saved="loadCategories" />

            <ProcLineEditor
              v-if="isProcurement" ref="lineBox" :lines="form.business_lines" :categories="categories" :mode="isPmc ? 'pmc' : 'new'"
              :suggestions="suggestions" @suggest="suggestFor" @error="ctx.flash('', errText($event, '物料库查询失败'))"
            />
            <div v-else class="pr-lines">
              <div class="pr-scroll">
                <div class="pr-lines-inner pr-pl">
                  <div class="pr-row pr-lhead"><span>#</span><span>购买物品 *</span><span>规格型号</span><span>产品说明</span><span>数量 *</span><span>单位 *</span><span>预计单价</span><span class="r">小计</span><span>备注</span><span></span></div>
                  <div v-for="(line, index) in form.business_lines" :key="line._uid" class="pr-line">
                    <div class="pr-row">
                      <span class="muted pr-no">{{ index + 1 }}</span>
                      <input v-model="line.item_name" placeholder="填写购买物品" aria-label="购买物品" />
                      <input v-model="line.specification" placeholder="可选" aria-label="规格型号" />
                      <input v-model="line.product_desc" placeholder="可选" aria-label="产品说明" />
                      <input v-model.number="line.quantity" type="number" min="0.0001" step="0.0001" class="r" aria-label="数量" />
                      <input v-model="line.unit" aria-label="单位" />
                      <input v-model.number="line.unit_price" type="number" min="0" step="0.01" class="r" placeholder="可选" aria-label="预计单价" />
                      <span class="r num strong">{{ lineTotal(line) > 0 ? `¥ ${money(lineTotal(line))}` : '—' }}</span>
                      <input v-model="line.remarks" placeholder="选填" aria-label="备注" />
                      <button type="button" class="pr-x" :disabled="form.business_lines.length < 2" aria-label="删除这一行" @click="form.business_lines.splice(index, 1)">×</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>

        <aside class="pr-side">
          <section class="panel summary">
            <span class="muted">{{ isProcurement ? '这张申请' : '预计金额' }}</span>
            <span class="big">{{ isProcurement ? `${summary.total} 项物料` : `¥ ${money(summary.amount)}` }}</span>
            <div v-if="isProcurement" class="summary-lines">
              <div><span class="muted">已绑定编号</span><span>{{ summary.bound }} 项</span></div>
              <div><span class="muted">交给 PMC 补充</span><span :class="{ warn: summary.pending }">{{ summary.pending }} 项</span></div>
            </div>
            <div class="summary-block">
              <span class="muted">{{ isPmc ? '审批路线' : `提交后的审批路线${isProcurement ? '' : `（${form.purchase_method}）`}` }}</span>
              <ol class="pr-route">
                <li v-for="(label, index) in routeSteps" :key="index"><i>{{ index + 1 }}</i>{{ label }}</li>
              </ol>
              <span v-if="!routeSteps.length" class="muted">{{ routeNote || '选好后这里显示审批路线' }}</span>
            </div>
            <div v-if="!isPmc" class="summary-block">
              <span class="muted">还差</span>
              <span v-for="item in blockers" :key="item" class="todo-item">· {{ item }}</span>
              <span v-if="!blockers.length" class="ok-text">可以提交</span>
            </div>
            <div v-else class="summary-block">
              <span v-for="item in blockers" :key="item" class="todo-item">· {{ item }}</span>
              <span class="muted">保存后会通知申请人、直属主管、项目主管，并留下修改前后的对比记录。前面已经通过的审批不会重来。</span>
            </div>
            <div v-if="!isProcurement" class="summary-block"><span class="muted">批下来之后</span><span>在"报销"里选它，凭发票报销；或在"付款"里选它，公司付款后补票。</span></div>
          </section>

          <div class="pr-buttons">
            <template v-if="!isPmc">
              <button type="button" class="btn pri lg" :disabled="saving || Boolean(orgWarning)" @click="submit">{{ saving ? '处理中…' : '提交审批' }}</button>
              <div class="pr-buttons-row">
                <button type="button" class="btn" :disabled="saving" @click="saveDraft">保存草稿</button>
                <button type="button" class="btn" :disabled="saving" @click="cancel">取消</button>
              </div>
            </template>
            <template v-else>
              <button type="button" class="btn pri lg" :disabled="saving" @click="savePmc">{{ saving ? '处理中…' : '保存修改' }}</button>
              <button type="button" class="btn" :disabled="saving" @click="cancel">取消，回到单据</button>
            </template>
          </div>

          <ProcDocuments v-if="draftName || isPmc" :request="isPmc ? String(route.params.name) : draftName" :row="requestRow" />
        </aside>
      </div>
    </template>
  </div>
</template>
