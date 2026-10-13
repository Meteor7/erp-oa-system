<script setup>
// 采购申请 / 购买申请详情：顶部是状态和按钮（按角色和单据状态变化），左边需求信息、物料明细、执行明细，
// 右边审批进度、关联单据、需求附件、操作记录。采购申请多一条采购链阶段条和执行明细；购买申请没有这两块。
import { computed, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../../styles/navUi.css';
import MaterialExecutionProgress from '../MaterialExecutionProgress.vue';
import ProcDocuments from './ProcDocuments.vue';
import {
  REQUEST_DIRECT, approvalButtonLabel, approveBlocker, canActOn, canMaintainLines, canNudge, canWithdrawRow, chainRoute, chainStrip,
  currentStepKey, detailBanner, formatDateTime, money, pmcButtonLabel, projectText, quantityText, relatedDocuments,
  requestFacts, stageOf, statusOf, stepTimeline, unboundLines,
} from '../../lib/procurementView.js';
import { amountText, paymentPoLink } from '../../lib/priceView.js';
import { eventLabel } from '../../lib/operationLog.js';
import { backLocation, carryQuery, fromValue, originLabel } from '../../lib/navContext.js';
import { canCreatePr, canOpenBoard, isInsider } from './access.js';
import { apiGet, apiPost, errText, loadPurchaseOrders, settle } from './procData.js';
import { useProc } from './context.js';
import PipelineBar from './PipelineBar.vue';

const ctx = useProc();
const route = useRoute();
const router = useRouter();
const name = computed(() => String(route.query.request || ''));
// 往回走：从列表来的回到同一个范围 / 阶段 / 搜索词的列表；从首页、看板来的回到那个页面；其他入口回到默认列表。
const cameFromList = computed(() => fromValue(route.query) === 'list');
const originText = computed(() => {
  const from = fromValue(route.query);
  return from && from !== 'list' ? (originLabel(route.query) || '上一页') : '';
});
function goBack() {
  ctx.flash();
  router.push(backLocation(route.path, route.query));
}
function backToList() {
  ctx.flash();
  router.push(cameFromList.value ? backLocation(route.path, route.query) : { path: ctx.basePath, query: { view: 'list' } });
}
const row = ref(null);
const loading = ref(false);
const ownDraft = ref(false);
const poRows = ref([]);
const acted = reactive({});
const lineOpen = reactive({});
const note = ref('');
const rejectReason = ref('');
const rejectTarget = ref('applicant');
const withdrawOpen = ref(false);
const withdrawNote = ref('');
const docs = ref(null);
const insider = isInsider();

async function loadPo(current) {
  const wanted = new Set(current?.procurement_chain?.po_numbers || []);
  if (!insider || !wanted.size) { poRows.value = []; return; }
  poRows.value = (await loadPurchaseOrders()).filter((po) => wanted.has(po.name));
}

async function load({ silent = false } = {}) {
  if (!name.value) return;
  if (!silent) loading.value = true;
  try {
    const rows = await apiGet('oa_entry.list_requests', { view: 'all', request_type: ctx.requestType, name: name.value, limit: 1 });
    const found = rows?.[0] || null;
    row.value = found;
    if (found?.workflow_status === '草稿') {
      // 草稿能不能继续编辑只看是不是自己的（代人提交时申请人和提交人不是同一个人）。
      ownDraft.value = (await settle(() => apiGet('oa_entry.list_requests', { view: 'mine', request_type: ctx.requestType, name: name.value, limit: 1 }))).length > 0;
    } else ownDraft.value = false;
    const targets = found?.rejection_targets || [];
    if (!targets.some((item) => item.target === rejectTarget.value)) rejectTarget.value = targets.some((item) => item.target === 'applicant') ? 'applicant' : (targets[0]?.target || 'applicant');
    loadPo(found);
    docs.value?.reload?.();
  } catch (error) {
    ctx.flash('', errText(error, '无法加载申请详情'));
  } finally {
    loading.value = false;
  }
}

watch(name, () => { withdrawOpen.value = false; note.value = ''; rejectReason.value = ''; load(); }, { immediate: true });
defineExpose({ reload: load });

const isProcurement = computed(() => row.value?.request_type !== REQUEST_DIRECT);
const lines = computed(() => row.value?.business_lines || []);
const status = computed(() => (row.value ? statusOf(row.value) : { label: '', tone: 'p-gray' }));
const stage = computed(() => (row.value ? stageOf(row.value) : { index: -1 }));
const strip = computed(() => (isProcurement.value && row.value ? chainStrip(row.value) : []));
const canApprove = computed(() => canActOn(row.value, acted, 'can_approve'));
const canReject = computed(() => canActOn(row.value, acted, 'can_reject'));
const blocker = computed(() => (canApprove.value ? approveBlocker(row.value) : ''));
const canWithdraw = computed(() => canWithdrawRow(row.value, ctx.currentEmployee));
const canPmc = computed(() => canMaintainLines(row.value));
const canResume = computed(() => row.value?.workflow_status === '草稿' && ownDraft.value);
const unbound = computed(() => (isProcurement.value ? unboundLines(lines.value).length : 0));
const timeline = computed(() => stepTimeline(row.value || {}, ctx.nameOf));
const facts = computed(() => requestFacts(row.value, { projectName: ctx.projectName, nameOf: ctx.nameOf, purchasers: ctx.purchasers }));
const banner = computed(() => detailBanner(row.value, { canAct: canApprove.value || canReject.value, canWithdraw: canWithdraw.value, insider }));
const related = computed(() => (isProcurement.value && row.value ? relatedDocuments(row.value, { canBoard: canOpenBoard() }) : []));
const showExec = computed(() => isProcurement.value && stage.value.index >= 1);
const directTotal = computed(() => lines.value.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0));
const log = computed(() => [...(row.value?.operation_log || [])].reverse());
// 催一下：申请人 / 项目负责人对等了 3 天以上的申请，提醒当前审批人（后端按同一套规则再校验、一天一次）。
const nudgeable = computed(() => canNudge(row.value, { user: ctx.currentUser, employee: ctx.currentEmployee }));
// 项目负责人看别人提的申请：只读，不能审批也不能改；这里写明白，免得以为是按钮丢了。
const ownerReadOnly = computed(() => Boolean(row.value && ctx.currentUser && String(row.value.project_owner || '').toLowerCase() === ctx.currentUser.toLowerCase()
  && String(row.value.owner || '').toLowerCase() !== ctx.currentUser.toLowerCase() && row.value.employee !== ctx.currentEmployee
  && !canApprove.value && !canReject.value));
const targets = computed(() => row.value?.rejection_targets || []);

// 下一步要去哪里办：PMC 去物料看板提 PR；采购 / 副总去价格审批单（只有行标志允许的人才看到）。
const chainAction = computed(() => {
  const current = row.value;
  const key = current?.procurement_chain?.stage;
  if (!isProcurement.value || stage.value.index < 1 || stage.value.index > 3) return null;
  if (key === 'await_pr') return canCreatePr() ? { label: '去物料看板提 PR', to: chainRoute(current) } : null;
  if (!current.can_view_procurement_price) return null;
  return key === 'quote' ? { label: '处理询价 / 比价', to: chainRoute(current) } : { label: '打开价格审批单', to: chainRoute(current) };
});

// PMC、生产主管看不到金额（PO 上带 amounts_hidden，金额是 null）：显示“—”，不算成 0
function poAmount(po) {
  if (po.amounts_hidden) return null;
  const own = (po.lines || []).filter((line) => line.source_request === row.value?.name);
  return own.length ? own.reduce((sum, line) => sum + Number(line.amount || 0), 0) : Number(po.total_amount || 0);
}
const poCash = (po, value) => amountText(value, po.amounts_hidden);

async function act(action) {
  const current = row.value;
  if (!current || ctx.busy) return;
  if (action === 'reject' && !rejectReason.value.trim()) { ctx.flash('', '请填写驳回原因'); return; }
  if (action === 'approve' && blocker.value) { ctx.flash('', blocker.value); return; }
  ctx.setBusy(true);
  ctx.flash();
  try {
    const params = {
      name: current.name, action, note: action === 'reject' ? rejectReason.value.trim() : note.value.trim(),
      expected_step_key: current.current_step_key || '',
    };
    if (action === 'reject') params.reject_target = rejectTarget.value;
    await apiPost('oa_entry.action_request', params);
    // 同一个节点上操作过以后，刷新前先在本地把按钮藏起来。
    acted[current.name] = currentStepKey(current);
    note.value = '';
    rejectReason.value = '';
    ctx.flash(action === 'reject' ? `${current.name} 已定向驳回` : `${current.name} 已审批通过`);
    await load({ silent: true });
  } catch (error) {
    ctx.flash('', errText(error, '审批操作失败'));
    await load({ silent: true });
  } finally {
    ctx.setBusy(false);
  }
}

async function withdraw() {
  const current = row.value;
  if (!current || ctx.busy) return;
  ctx.setBusy(true);
  ctx.flash();
  try {
    await apiPost('oa_entry.withdraw_request', { name: current.name, note: withdrawNote.value.trim() });
    withdrawOpen.value = false;
    withdrawNote.value = '';
    ctx.flash(`${current.name} 已撤回，可编辑后重新提交`);
    await load({ silent: true });
  } catch (error) {
    ctx.flash('', errText(error, '撤回申请失败'));
    await load({ silent: true });
  } finally {
    ctx.setBusy(false);
  }
}

async function nudge() {
  const current = row.value;
  if (!current || ctx.busy) return;
  ctx.setBusy(true);
  ctx.flash();
  try {
    const result = await apiPost('request_nudge.nudge_request', { name: current.name });
    ctx.flash(`已提醒当前审批人（${result?.sent || 0} 位），申请已等 ${result?.waited_days ?? ''} 天`);
  } catch (error) {
    ctx.flash('', errText(error, '催办失败'));
  } finally {
    ctx.setBusy(false);
  }
}

function resume() {
  ctx.goNew({ draft: row.value.name, ...carryQuery(route.query) });
}

function toggleLine(index) {
  lineOpen[index] = !lineOpen[index];
}
</script>

<template>
  <div class="pr-detail">
    <div class="crumb">
      <button v-if="originText" type="button" class="link nav-back" @click="goBack">← 返回{{ originText }}</button>
      <button type="button" class="link" @click="ctx.go({})">{{ ctx.label }}</button> ›
      <button type="button" class="link" @click="backToList">列表</button> ›
      {{ name }}
    </div>
    <div v-if="loading && !row" class="panel empty" aria-live="polite">正在加载…</div>
    <div v-else-if="!row" class="panel empty">找不到{{ ctx.label }} {{ name }}，可能已被删除或没有查看权限</div>
    <template v-else>
      <section class="panel pr-head">
        <div class="detail-head">
          <div class="grow-col">
            <div class="title-line">
              <h3>{{ row.subject || '（无主题）' }}</h3>
              <span :class="['pill', status.tone]">{{ status.label }}</span>
              <span v-if="row.urgency === '加急'" class="pill p-red">加急</span>
            </div>
            <div class="muted">{{ row.name }} · {{ row.employee_name || '—' }} · {{ row.department || '—' }} · {{ projectText(row, ctx.projectName) }} · {{ formatDateTime(row.creation) }} 提交</div>
          </div>
          <div class="amount-block">
            <span class="muted">{{ isProcurement ? '物料' : '预计金额' }}</span>
            <b>{{ isProcurement ? `${lines.length} 项` : `¥ ${money(row.amount || directTotal)}` }}</b>
          </div>
          <div class="head-buttons">
            <button v-if="canPmc" type="button" class="btn" @click="ctx.goPmcEdit(row.name)">{{ pmcButtonLabel(row) }}</button>
            <button v-if="canWithdraw && !withdrawOpen" type="button" class="btn danger" :disabled="ctx.busy" @click="withdrawOpen = true">撤回申请</button>
            <button v-if="canResume" type="button" class="btn pri" @click="resume">编辑并重新提交</button>
            <button v-if="canReject" type="button" class="btn danger" :disabled="ctx.busy" @click="act('reject')">驳回</button>
            <button v-if="canApprove" type="button" class="btn pri lg" :disabled="ctx.busy || Boolean(blocker)" :title="blocker" @click="act('approve')">{{ approvalButtonLabel(row) }}</button>
          </div>
        </div>

        <div :class="['pr-banner', banner.tone]" role="status">
          <span>{{ banner.text }}</span>
          <router-link v-if="chainAction" :to="chainAction.to" class="btn sm">{{ chainAction.label }}</router-link>
          <button v-if="nudgeable" type="button" class="btn sm" :disabled="ctx.busy" @click="nudge">催一下</button>
        </div>
        <div v-if="ownerReadOnly" class="pr-banner pr-ownerhint" role="note"><span>你是这个项目的项目负责人，可以看到这张申请的进度（只读）；价格、供应商不显示。</span></div>
        <PipelineBar :row="row" where foot-only />

        <div v-if="withdrawOpen" class="pr-inline-form">
          <input v-model="withdrawNote" placeholder="撤回原因（可选）" aria-label="撤回原因" maxlength="500" @keydown.enter.prevent="withdraw" />
          <button type="button" class="btn sm danger" :disabled="ctx.busy" @click="withdraw">确认撤回</button>
          <button type="button" class="btn sm" @click="withdrawOpen = false">取消</button>
        </div>

        <div v-if="canApprove || canReject" class="pr-act">
          <label class="f">
            <span class="pr-label">审批意见（可选）</span>
            <input v-model="note" maxlength="500" placeholder="同意时可留言" />
          </label>
          <label v-if="canReject" class="f">
            <span class="pr-label">驳回到</span>
            <select v-model="rejectTarget"><option v-for="target in targets" :key="target.target" :value="target.target">{{ target.label }}</option></select>
          </label>
          <label v-if="canReject" class="f">
            <span class="pr-label">驳回原因（驳回时必填）</span>
            <input v-model="rejectReason" maxlength="500" placeholder="写清楚要改什么" />
          </label>
          <div v-if="blocker" class="pr-blocker">{{ blocker }}</div>
        </div>

        <div v-if="strip.length" class="pr-strip" role="list" aria-label="采购进度">
          <div v-for="item in strip" :key="item.key" :class="['pr-strip-step', item.state]" role="listitem">
            <div class="pr-strip-top"><i>{{ item.mark }}</i><span></span></div>
            <b>{{ item.label }}</b>
            <span class="muted">{{ item.sub || ' ' }}</span>
          </div>
        </div>
      </section>

      <div class="detail-grid">
        <div>
          <section class="panel">
            <div class="pt"><span>需求信息</span></div>
            <div class="kv pr-facts">
              <div v-for="fact in facts" :key="fact.k" :class="{ wide: fact.wide }"><span>{{ fact.k }}</span><b :class="['pr-fact', { warn: fact.hot }]">{{ fact.v }}</b></div>
            </div>
          </section>

          <section v-if="isProcurement" class="panel flush">
            <div class="pt pr-pad">
              <span>物料明细 <span class="muted">{{ lines.length }} 项 · 单价在询价后由采购录入，需求阶段不填</span></span>
              <span v-if="unbound" class="pill p-sun">{{ unbound }} 项待 PMC 绑定物料编号</span>
            </div>
            <div class="tbl">
              <table class="pr-table">
                <thead><tr><th>#</th><th>物料编号 / 流水号</th><th>名称 / 规格</th><th>品牌</th><th class="r">数量</th><th>编号状态</th></tr></thead>
                <tbody v-for="(line, index) in lines" :key="line.name || index">
                  <tr class="row-sel" @click="toggleLine(index)">
                    <td class="muted">{{ index + 1 }}</td>
                    <td>
                      <div :class="['num', { warn: !line.material_code }]">{{ line.material_code || line.category_code || '待 PMC 补充' }}</div>
                      <div class="muted num">{{ line.material_serial || '提交后自动生成' }}</div>
                    </td>
                    <td><b>{{ line.item_name || '—' }}</b><div class="muted">{{ line.specification || '—' }}</div></td>
                    <td>{{ line.brand || '（待补）' }}</td>
                    <td class="r num">{{ quantityText(line.quantity) }} {{ line.unit }}</td>
                    <td>
                      <span :class="['pill', line.material_code ? 'p-jade' : 'p-sun']">{{ line.material_code ? '已绑定' : '待 PMC 绑定' }}</span>
                      <button type="button" class="link pr-more-btn" :aria-expanded="Boolean(lineOpen[index])" @click.stop="toggleLine(index)">{{ lineOpen[index] ? '收起' : '详情' }}</button>
                    </td>
                  </tr>
                  <tr v-if="lineOpen[index]" class="pr-line-more">
                    <td></td>
                    <td colspan="5">
                      <div class="pr-more-grid">
                        <div><span>产品描述</span>{{ line.product_desc || '—' }}</div>
                        <div><span>英文名称</span>{{ line.product_name || '—' }}</div>
                        <div><span>英文描述</span>{{ line.product_desc_en || '—' }}</div>
                        <div><span>英文品牌</span>{{ line.brand_en || '—' }}</div>
                        <div><span>备注</span>{{ line.remarks || '—' }}</div>
                        <div v-if="line.category_path"><span>分类路径</span>{{ line.category_path }}</div>
                      </div>
                    </td>
                  </tr>
                </tbody>
                <tbody v-if="!lines.length"><tr><td colspan="6" class="empty">该申请没有明细</td></tr></tbody>
              </table>
            </div>
            <div class="muted pr-pad pr-tablenote">点一行可展开产品描述、英文名称 / 描述 / 品牌、备注。</div>
          </section>

          <section v-else class="panel flush">
            <div class="pt pr-pad"><span>购买明细 <span class="muted">{{ lines.length }} 项</span></span></div>
            <div class="tbl">
              <table class="pr-table">
                <thead><tr><th>#</th><th>购买物品</th><th>规格型号</th><th>产品说明</th><th class="r">数量</th><th>单位</th><th class="r">预计单价</th><th class="r">小计</th><th>备注</th></tr></thead>
                <tbody>
                  <tr v-for="(line, index) in lines" :key="line.name || index">
                    <td class="muted">{{ index + 1 }}</td>
                    <td><b>{{ line.item_name || '—' }}</b></td>
                    <td>{{ line.specification || '—' }}</td>
                    <td class="pr-wrap">{{ line.product_desc || '—' }}</td>
                    <td class="r num">{{ quantityText(line.quantity) }}</td>
                    <td>{{ line.unit || '—' }}</td>
                    <td class="r num">{{ Number(line.unit_price || 0) > 0 ? money(line.unit_price) : '—' }}</td>
                    <td class="r num">{{ Number(line.unit_price || 0) > 0 ? money(Number(line.quantity || 0) * Number(line.unit_price || 0)) : '—' }}</td>
                    <td class="pr-wrap">{{ line.remarks || '—' }}</td>
                  </tr>
                  <tr v-if="!lines.length"><td colspan="9" class="empty">该申请没有明细</td></tr>
                </tbody>
                <tfoot v-if="Number(row.amount || 0) > 0"><tr><td colspan="7" class="r muted">预计总金额</td><td class="r num strong">¥ {{ money(row.amount) }}</td><td></td></tr></tfoot>
              </table>
            </div>
          </section>

          <MaterialExecutionProgress v-if="showExec" :key="row.name" :request="row.name" :expanded="true" />

          <section v-if="showExec && poRows.length" class="panel">
            <div class="pt"><span>PO 与付款计划 <span class="muted">来自价格审批单选定的供应商；只有采购 / PMC / 副总 / 财务看得到</span></span></div>
            <div v-for="po in poRows" :key="po.name" class="pr-po">
              <div class="pr-po-head">
                <div><span class="muted">{{ po.name }} · 供应商</span><b>{{ po.supplier || '—' }}</b></div>
                <div><span class="muted">PO 总额（本申请物料）</span><b>{{ poCash(po, poAmount(po)) }}</b></div>
                <div><span class="muted">付款方式</span>{{ po.payment_method || '—' }}</div>
                <div><span class="muted">币种 / 税率</span>{{ po.currency || 'CNY' }} / {{ po.tax_rate || 0 }}%</div>
                <router-link v-if="row.can_view_procurement_po" :to="{ name: 'procurement-price-approvals', query: { tab: 'po', po: po.name } }" class="btn sm">打开 PO →</router-link>
                <router-link v-if="row.can_view_procurement_po" :to="paymentPoLink(po)" class="btn sm">去采购付款登记 →</router-link>
              </div>
              <div class="tbl">
                <table class="pr-table">
                  <thead><tr><th>期次</th><th>阶段</th><th class="r">比例</th><th class="r">金额</th><th>触发条件</th><th>发票</th><th>状态</th></tr></thead>
                  <tbody>
                    <tr v-for="plan in po.payment_plan || []" :key="plan.name">
                      <td>{{ plan.installment_name }}</td><td>{{ plan.payment_stage }}</td>
                      <td class="r num">{{ plan.percentage }}%</td><td class="r num strong">{{ poCash(po, plan.amount) }}</td>
                      <td>{{ plan.trigger_condition || '—' }}</td><td>{{ plan.invoice_requirement || '—' }}</td>
                      <td>
                        <span class="pill p-gray">{{ plan.status || '待生成' }}</span>
                        <router-link v-if="plan.payment_request" :to="{ path: '/approval/procurement-payment', query: { request: plan.payment_request } }" class="link pr-pay-link">{{ plan.payment_request }}</router-link>
                      </td>
                    </tr>
                    <tr v-if="!(po.payment_plan || []).length"><td colspan="7" class="empty">这张 PO 还没有付款计划</td></tr>
                  </tbody>
                </table>
              </div>
            </div>
            <router-link :to="paymentPoLink(poRows.length === 1 ? poRows[0] : null)" class="pr-banner info pr-paylink">到货、验收、付款审批都在"采购付款"里按 PO 处理：到货和验收都由生产主管登记，采购负责提交付款审批 →</router-link>
          </section>
        </div>

        <aside>
          <section class="panel">
            <div class="pt">审批进度</div>
            <div v-for="(item, index) in timeline" :key="item.key" :class="['tl', item.state]">
              <div class="rail"><i></i><span v-if="index < timeline.length - 1"></span></div>
              <div class="body">
                <b>{{ item.label }}</b>
                <span v-if="item.sub" class="muted">{{ item.sub }}</span>
                <span v-for="person in item.people" :key="person.user" :class="['pr-person', { done: person.done }]">{{ person.name }}：{{ person.done ? '已同意' : '待审批' }}</span>
                <span v-if="item.note" class="note">{{ item.note }}</span>
              </div>
            </div>
            <div v-if="!timeline.length" class="muted">还没有提交审批</div>
            <div v-if="isProcurement" class="muted">会签：并列的人都同意才进入下一步。PMC 通过前，每项物料都要绑定物料目录里的编号。</div>
          </section>

          <section v-if="related.length" class="panel">
            <div class="pt">关联单据</div>
            <div v-for="item in related" :key="item.key" class="pr-rel">
              <span class="muted">{{ item.t }}</span>
              <span class="pr-rel-names">{{ item.names.join('、') }}</span>
              <router-link v-if="item.to" :to="item.to" class="link">{{ item.v }}</router-link>
              <span v-else class="muted">{{ item.v }}</span>
            </div>
            <div class="muted pr-docs-note">"价格审批 / PO"只有采购、PMC、副总、财务看得到；"物料看板"只有 PMC、采购经理、副总能打开。你可以在上面的执行明细里看到每项物料的数量和进度。</div>
          </section>

          <ProcDocuments ref="docs" :request="row.name" :row="row" />

          <section class="panel">
            <div class="pt">操作记录</div>
            <div v-for="(event, index) in log" :key="index" class="pr-log">
              <span class="muted">{{ formatDateTime(event.acted_on) }}</span>
              <span>{{ ctx.nameOf(event.actor) }} · {{ eventLabel(event.action) }}<template v-if="event.note"> · {{ event.note }}</template></span>
            </div>
            <div v-if="!log.length" class="muted">还没有操作记录</div>
            <div class="muted pr-docs-note">只记这张申请本身的操作；价格审批、PO、付款的记录在各自页面。</div>
          </section>
        </aside>
      </div>
    </template>
  </div>
</template>
