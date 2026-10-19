<script setup>
// 社保信息管理 / 公积金信息管理共用的工作台：导入申报表 → 核对差异 → 基数与金额 → 确认生效（薪酬直接读取）。
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { createResource } from 'frappe-ui';
import '../../styles/expenseUi.css';
import '../../styles/contributionUi.css';
import { period, usePeriodFromRoute } from '../../lib/period';
import { extractFrappeError } from '../../lib/frappeError';
import { displayCompany } from '../../lib/displayBrand.js';
import { canEditHr } from '../../lib/access.js';
import {
  SHARED_API, STEPS, STATUS_LABEL, activationBlockers, batchOf, issueFilter, kindOf, missingBaseCount, money, normalizeRow,
  pendingSummary, progress, readinessText, signed, sortIssues, stepStates,
} from '../../lib/contributionView.js';
import ContributionDrawer from './ContributionDrawer.vue';
import ContributionBaseTable from './ContributionBaseTable.vue';

const props = defineProps({ kind: { type: String, required: true } });
const cfg = kindOf(props.kind);
const other = kindOf(props.kind === 'si' ? 'fund' : 'si');
// 总经理、副总经理只读打开：不显示上传、取消批次、确认纳入 / 忽略、改基数、确认生效（服务端也会拒绝）。
const canEdit = canEditHr();

// 看板链接带 ?period=YYYY-MM：先读好期间，再建下面的数据请求。
usePeriodFromRoute(useRoute(), useRouter());
const company = ref('all');
const companyOptions = [{ value: 'all', label: '全部公司' }, { value: 'QIHENG Demo', label: '栖衡科技' }, { value: '示例研发中心', label: '栖衡研发' }];
const step = ref(1);
const filter = ref('pending');
const file = ref(null);
const dragging = ref(false);
const preview = ref(null);
const message = ref('');
const error = ref('');
const drawerError = ref('');
const openId = ref('');
const busy = ref(false);
const batchNotes = ref({});
let settled = false;

const workbench = createResource({ url: cfg.fn.workbench, method: 'GET', makeParams: () => ({ period: period.value, company: company.value }), auto: true });
const baseTable = createResource({ url: SHARED_API + 'get_base_table', method: 'GET', makeParams: () => ({ kind: props.kind, period: period.value, company: company.value }), auto: true });
const readiness = createResource({ url: SHARED_API + 'get_payroll_readiness', method: 'GET', makeParams: () => ({ period: period.value }), auto: true });
const employees = createResource({ url: 'rayher_hr_payroll.api.social_insurance_import_entry.get_employee_options', method: 'GET', makeParams: () => ({ company: 'all' }), auto: true });
const uploader = createResource({ url: cfg.fn.upload });
const activator = createResource({ url: cfg.fn.activate });
const confirmer = createResource({ url: cfg.fn.confirm });
const ignorer = createResource({ url: cfg.fn.ignore });
const canceler = createResource({ url: cfg.fn.cancel });
const reconciler = createResource({ url: cfg.fn.reconcile });
const baseSaver = createResource({ url: SHARED_API + 'save_employee_base' });
const householdSaver = createResource({ url: SHARED_API + 'save_employee_household' });

const data = computed(() => preview.value || workbench.data || { dashboard: {}, company_summaries: [], batches: [], pending: [], details: [], handled: [] });
const dashboard = computed(() => data.value.dashboard || {});
const batch = computed(() => batchOf(data.value));
const batchPending = computed(() => batch.value?.status === 'Pending Activation');
const rows = computed(() => baseTable.data?.rows || []);
const missingBase = computed(() => missingBaseCount(rows.value, props.kind));
const items = computed(() => sortIssues([...(data.value.pending || []), ...(data.value.handled || [])].map((row) => normalizeRow(props.kind, row))));
const shownItems = computed(() => issueFilter(items.value, filter.value));
const pendingItems = computed(() => items.value.filter((item) => !item.resolved));
const summary = computed(() => pendingSummary(items.value));
const prog = computed(() => progress(data.value));
const states = computed(() => stepStates({ data: data.value, missingBase: missingBase.value }));
const blockers = computed(() => activationBlockers({ data: data.value, missingBase: missingBase.value }));
const openItem = computed(() => items.value.find((item) => item.id === openId.value) || null);
const unmatchedHint = computed(() => (props.kind === 'si' ? '证件号码或姓名对不上的，请在差异里选择员工后再确认。' : '证件号码或姓名对不上的，请在差异里选择员工后再确认。'));

const RING = 2 * Math.PI * 30;
const ringOffset = computed(() => RING * (1 - prog.value.percent / 100));

// 社保的"险种构成"：按 Excel 申报金额汇总（个人 / 单位）。
const MIX = [['养老', ['employee_pension'], ['company_pension']], ['医疗', ['employee_medical'], ['company_medical']], ['失业', ['employee_unemployment'], ['company_unemployment']], ['工伤', [], ['company_injury']], ['生育', [], ['company_maternity']], ['地方补充养老', [], ['local_pension']]];
const mix = computed(() => {
  if (props.kind !== 'si') return [];
  const source = [...(data.value.pending || []), ...(data.value.details || []), ...(data.value.handled || [])].filter((row) => row.status !== 'Ignored' && row.row_type !== 'missing');
  const sum = (fields) => source.reduce((total, row) => total + fields.reduce((inner, field) => inner + Number(row[field] || 0), 0), 0);
  const list = MIX.map(([label, personal, companyFields]) => ({ label, personal: sum(personal), company: sum(companyFields) }));
  const top = Math.max(...list.map((item) => Math.max(item.personal, item.company)), 1);
  return list.map((item) => ({ ...item, pw: item.personal / top * 100, cw: item.company / top * 100 }));
});

watch([period, company], () => { preview.value = null; settled = false; message.value = ''; workbench.reload(); baseTable.reload(); readiness.reload(); });
watch(() => workbench.data, (value) => {
  if (settled || !value) return;
  settled = true;
  const current = batchOf(value);
  step.value = !current ? 1 : current.status === 'Current' ? 4 : 2;
}, { immediate: true });

function say(text) { message.value = text; error.value = ''; }
function fail(exception, fallback) { error.value = extractFrappeError(exception, fallback); message.value = ''; }
async function refreshAll() { await Promise.all([baseTable.reload(), readiness.reload()]); }

function choose(selected) { file.value = selected || null; error.value = ''; }
function onPick(event) { choose(event.target.files?.[0]); event.target.value = ''; }
function onDrop(event) { dragging.value = false; choose(event.dataTransfer?.files?.[0]); }
function readDataUrl(selected) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('读取Excel失败'));
    reader.readAsDataURL(selected);
  });
}
async function upload() {
  error.value = ''; message.value = '';
  if (!file.value) { error.value = '请选择Excel文件'; return; }
  busy.value = true;
  try {
    const params = { filename: file.value.name, content_base64: await readDataUrl(file.value) };
    if (props.kind === 'fund') params.period = period.value;
    const result = await uploader.submit(params);
    if (company.value !== 'all') company.value = 'all';
    period.value = result.period || period.value;
    preview.value = result; file.value = null; step.value = 2; filter.value = 'pending';
    say(`已导入${result.period}${cfg.fileTitle}：后台按员工档案${props.kind === 'si' ? '基数、户口和期间政策' : '基数和比例'}复算，差异在下面处理`);
    await refreshAll();
  } catch (exception) { fail(exception, '上传失败'); } finally { busy.value = false; }
}

async function run(resource, params, done, failure) {
  drawerError.value = ''; error.value = '';
  busy.value = true;
  try {
    preview.value = await resource.submit(params);
    done?.();
    await refreshAll();
  } catch (exception) {
    const text = extractFrappeError(exception, failure);
    if (openId.value) drawerError.value = text; else error.value = text;
  } finally { busy.value = false; }
}
const onConfirm = (payload) => run(confirmer, payload, () => { openId.value = ''; say('已确认纳入，生效后薪酬按 Excel 金额读取'); }, '确认失败');
const onIgnore = (payload) => run(ignorer, payload, () => { openId.value = ''; say('已忽略，不会进入正式明细'); }, '忽略失败');
function onFix() { openId.value = ''; step.value = 3; say(`请在这里补齐${cfg.name}基数${props.kind === 'si' ? '和户口' : ''}，改完系统会自动重新核对`); }
async function cancelBatch(target) {
  const remark = (batchNotes.value[target.name] || '').trim();
  if (!remark) { error.value = '取消批次前必须填写原因'; return; }
  await run(canceler, { batch: target.name, remark }, () => say('批次已取消，原文件和解析记录仍然保留'), '取消批次失败');
}
async function activate() {
  if (!batch.value || blockers.value.length) return;
  await run(activator, { batch: batch.value.name }, () => { preview.value = null; say(`${cfg.name}已生效，薪酬可以读取这个月的记录`); }, '确认生效失败');
  await workbench.reload();
}

async function afterBaseChange() {
  await baseTable.reload();
  if (batchPending.value) preview.value = await reconciler.submit({ batch: batch.value.name });
  await readiness.reload();
}
async function onBase(payload) {
  error.value = ''; busy.value = true;
  try { await baseSaver.submit({ kind: props.kind, employee: payload.employee, base: payload.base, period: period.value }); await afterBaseChange(); } catch (exception) { fail(exception, '保存基数失败'); await baseTable.reload(); } finally { busy.value = false; }
}
async function onHousehold(payload) {
  error.value = ''; busy.value = true;
  try { await householdSaver.submit(payload); await afterBaseChange(); } catch (exception) { fail(exception, '保存户口失败'); await baseTable.reload(); } finally { busy.value = false; }
}
async function onCarry() {
  error.value = ''; busy.value = true;
  try {
    for (const row of rows.value.filter((item) => item.base == null && item.prev_base != null)) {
      await baseSaver.submit({ kind: props.kind, employee: row.employee, base: row.prev_base, period: period.value });
    }
    await afterBaseChange();
    say('已按上月基数带入');
  } catch (exception) { fail(exception, '带入失败'); } finally { busy.value = false; }
}

const statusPill = (status) => ({ Current: 'p-jade', 'Pending Activation': 'p-sun', Historical: 'p-gray', Canceled: 'p-gray', Failed: 'p-red' }[status] || 'p-gray');
const company2 = (item) => item.company_display || displayCompany(item.company);
const missingNames = (kind) => (readiness.data?.kinds?.[kind]?.missing || []).slice(0, 12).map((item) => item.employee_name).join('、');
</script>

<template>
  <div class="xp cw">
    <div class="ph">
      <div>
        <div class="muted">人事中心</div>
        <h3>{{ cfg.title }}</h3>
        <div class="muted">导入{{ cfg.source }}的 Excel，系统按档案{{ kind === 'si' ? '基数、户口和政策' : '基数和比例' }}复算并对出差异，处理完确认生效，薪酬直接读取</div>
      </div>
      <div class="cw-ctl">
        <label>期间 <input v-model="period" type="month" aria-label="期间"></label>
        <label>所属公司 <select v-model="company" aria-label="所属公司"><option v-for="option in companyOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      </div>
    </div>

    <div v-if="error" class="banner err" role="alert">{{ error }}</div>
    <div v-if="message" class="banner ok" role="status">{{ message }}</div>

    <div class="cw-cards">
      <div class="cw-card c3">
        <span class="l">核对进度</span>
        <div class="cw-ring">
          <svg viewBox="0 0 76 76" role="img" :aria-label="`核对进度 ${prog.percent}%`"><circle cx="38" cy="38" r="30" fill="none" stroke="#EEF1F6" stroke-width="8" /><circle cx="38" cy="38" r="30" fill="none" stroke="#2F7A55" stroke-width="8" stroke-linecap="round" :stroke-dasharray="RING.toFixed(1)" :stroke-dashoffset="ringOffset.toFixed(1)" transform="rotate(-90 38 38)" /><text x="38" y="43" text-anchor="middle" font-size="15" font-weight="700" fill="#1A2130">{{ prog.percent }}%</text></svg>
          <div><div class="v">{{ prog.done }}<span class="muted"> / {{ prog.total }}</span></div><div class="s">行已核对完</div></div>
        </div>
      </div>
      <div :class="['cw-card', 'c3', { hot: pendingItems.length }]">
        <span class="l">待处理差异</span>
        <span class="v">{{ pendingItems.length }}</span>
        <div class="cw-chips"><span v-for="entry in summary.slice(0, 4)" :key="entry.key" :class="['pill', entry.tone === 'bad' ? 'p-red' : 'p-sun']">{{ entry.label }} {{ entry.count }}</span><span v-if="!summary.length" class="pill p-jade">{{ batch ? '全部处理完' : '还没有导入' }}</span></div>
      </div>
      <div class="cw-card c3"><span class="l">个人承担合计</span><span class="v">{{ money(dashboard.employee_total) }}</span><span class="s">按 Excel 申报</span></div>
      <div class="cw-card c3"><span class="l">单位承担合计</span><span class="v">{{ money(dashboard.company_total) }}</span><span class="s">按 Excel 申报</span></div>
      <div v-if="kind === 'si'" class="cw-card c7">
        <div class="pt"><span>险种构成 <span class="muted">按 Excel 申报</span></span><span class="cw-legend"><span><i style="background:#34489A"></i>个人</span><span><i style="background:#147B73"></i>单位</span></span></div>
        <div class="cw-mix">
          <div v-for="item in mix" :key="item.label" class="cw-mixrow">
            <span>{{ item.label }}</span>
            <div class="cw-bars"><div class="cw-track"><i :style="{ width: item.pw + '%', background: '#34489A' }"></i></div><div class="cw-track"><i :style="{ width: item.cw + '%', background: '#147B73' }"></i></div></div>
            <span class="num r">{{ item.personal ? money(item.personal) : '—' }}<br>{{ item.company ? money(item.company) : '—' }}</span>
          </div>
        </div>
      </div>
      <div :class="['cw-card', kind === 'si' ? 'c5' : 'c12']">
        <div class="pt"><span>各公司 <span class="muted">应{{ kind === 'si' ? '收' : '缴' }}合计 {{ money(dashboard.receivable_total) }}</span></span></div>
        <div class="tbl narrow"><table>
          <thead><tr><th>公司</th><th class="r">人数</th><th class="r">个人</th><th class="r">单位</th><th class="r">待处理</th></tr></thead>
          <tbody><tr v-for="item in data.company_summaries || []" :key="item.company"><td>{{ item.company_display }}</td><td class="r num">{{ item.total_rows }}</td><td class="r num">{{ money(item.employee_total) }}</td><td class="r num">{{ money(item.company_total) }}</td><td class="r num">{{ item.pending_rows }}</td></tr></tbody>
        </table></div>
      </div>
    </div>

    <div class="cw-steps" role="tablist" aria-label="处理步骤">
      <button v-for="(name, index) in STEPS" :key="name" type="button" role="tab" :aria-selected="step === index + 1" :class="['cw-step', { done: states[index].done }]" @click="step = index + 1">
        <span class="n">{{ states[index].done ? '✓' : index + 1 }}</span>
        <span style="min-width:0"><div class="t">{{ name }}</div><div class="d">{{ states[index].desc }}</div></span>
      </button>
    </div>

    <section v-if="step === 1" class="panel" aria-label="导入申报表">
      <div class="pt"><span>第一步：导入本月{{ cfg.fileTitle }} <span class="muted">Excel 只当作“申报结果”，金额以后台按档案复算为准</span></span></div>
      <div v-if="!canEdit" class="cw-hint" data-cw-readonly>只读查看：导入和处理由人事完成，这里只能看已导入的批次和核对结果。</div>
      <label v-if="canEdit" :class="['cw-drop', { over: dragging }]" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
        <input type="file" accept=".xlsx" @change="onPick">
        <b>{{ file ? file.name : `把${cfg.source}导出的 ${cfg.fileTitle}（.xlsx）拖到这里，或点击选择` }}</b>
        <span class="muted">{{ kind === 'si' ? '读取“申报明细”工作表里的在职人员' : '按表头名字识别：姓名、证件号码、缴存基数、个人缴存额、单位缴存额（缴存年月可有可无）' }}</span>
      </label>
      <div v-if="canEdit" class="cw-foot"><span class="muted">{{ unmatchedHint }}</span><button type="button" class="btn pri" data-cw-upload :disabled="busy || !file" @click="upload">{{ busy ? '处理中…' : '上传并核对' }}</button></div>
      <div class="cw-hint">
        <b>怎么认人：</b>先用证件号码，认不出再按姓名（姓名唯一才自动关联），都认不出的放进差异让人确认。<br>
        <b>怎么复算：</b>{{ kind === 'si' ? '深圳地区按 2026 政策：养老 个人 8% / 单位 16%；医疗 个人 2% / 单位 6%（基数不低于 6,727）；生育 单位 0.5%；工伤 单位 0.8%；失业 个人 0.2% / 单位 0.8%；地方补充养老 1% 仅深户。户口取员工档案。' : '公积金 = 档案公积金基数 × 比例（默认个人 7%、单位 7%）；本月已有月度记录的按记录里的基数和比例。社保和公积金基数各自维护，不要求一致。' }}<br>
        <b>怎么对差异：</b>基数不一致、金额对不上、档案缺基数{{ kind === 'si' ? '、户口未维护' : '' }}、人关联不上，以及档案里有基数却不在申报表里的人，都会列出来。
      </div>
      <div v-if="data.batches && data.batches.length" class="tbl">
        <table>
          <thead><tr><th>文件</th><th>上传时间</th><th class="r">人数</th><th class="r">待处理</th><th>状态</th><th>操作</th></tr></thead>
          <tbody><tr v-for="item in data.batches" :key="item.name">
            <td>{{ item.source_filename }}<div class="muted">{{ company2(item) }}</div></td><td>{{ item.uploaded_at }}</td><td class="r num">{{ item.parsed_rows }}</td><td class="r num">{{ item.pending_rows }}</td>
            <td><span :class="['pill', statusPill(item.status)]">{{ STATUS_LABEL[item.status] || item.status }}</span></td>
            <td><span v-if="canEdit && item.status === 'Pending Activation'" class="cw-chips"><input v-model="batchNotes[item.name]" class="cell" style="width:200px" placeholder="取消批次时填写原因" :aria-label="`取消 ${item.source_filename} 的原因`"><button type="button" class="btn sm danger" :disabled="busy" @click="cancelBatch(item)">取消批次</button></span><span v-else class="muted">{{ item.cancel_remark || '-' }}</span></td>
          </tr></tbody>
        </table>
      </div>
    </section>

    <section v-else-if="step === 2" class="panel" aria-label="核对差异">
      <div class="pt">
        <span>第二步：核对差异</span>
        <span class="cw-seg" role="group" aria-label="筛选">
          <button type="button" :aria-pressed="filter === 'pending'" @click="filter = 'pending'">待处理 {{ pendingItems.length }}</button>
          <button type="button" :aria-pressed="filter === 'done'" @click="filter = 'done'">已处理 {{ items.length - pendingItems.length }}</button>
          <button type="button" :aria-pressed="filter === 'all'" @click="filter = 'all'">全部</button>
        </span>
      </div>
      <div v-if="!batch" class="cw-block">还没有导入{{ cfg.fileTitle }}，没有可核对的内容。<button v-if="canEdit" type="button" class="btn sm" @click="step = 1">去导入</button></div>
      <div class="tbl">
        <table>
          <thead><tr><th>员工</th><th>差异原因</th><th class="r">申报合计</th><th class="r">复算合计</th><th class="r">差额</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="item in shownItems" :key="item.id" :class="['row-sel', { done: item.resolved }]" tabindex="0" @click="openId = item.id" @keydown.enter="openId = item.id">
              <td><span class="cw-avatar">{{ String(item.name || '').slice(-2) }}</span><b>{{ item.name }}</b><div class="cw-sub">{{ displayCompany(item.company) }}<template v-if="item.rowType === 'missing'"> · 申报表里没有</template></div></td>
              <td><span v-for="type in item.types.slice(0, 2)" :key="type.label" :class="['pill', type.tone === 'bad' ? 'p-red' : 'p-sun']" :title="type.text" style="margin-right:4px">{{ type.label }}</span><span v-if="item.types.length > 2" class="pill p-gray">+{{ item.types.length - 2 }}</span></td>
              <td class="r num">{{ item.excelTotal == null ? '—' : money(item.excelTotal) }}</td>
              <td class="r num">{{ item.calcTotal == null ? '—' : money(item.calcTotal) }}</td>
              <td :class="['r', 'num', item.diff > 0 ? 'd-up' : item.diff < 0 ? 'd-dn' : '']">{{ item.diff == null ? '—' : signed(item.diff) }}</td>
              <td><span :class="['pill', item.resolved ? 'p-jade' : 'p-sun']">{{ item.resolved ? (STATUS_LABEL[item.status] || item.status) : '待处理' }}</span></td>
            </tr>
            <tr v-if="!shownItems.length"><td colspan="6" class="empty">{{ filter === 'pending' ? (batch ? '没有待处理的差异，可以去补齐基数了' : '还没有导入') : '没有记录' }}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="cw-foot"><span class="muted">点一行看明细并选择处理方式；每一条处理都会记下是谁、什么时候、为什么。</span><button type="button" class="btn pri" @click="step = 3">下一步：基数与金额 →</button></div>
    </section>

    <ContributionBaseTable v-else-if="step === 3" :kind="kind" :rows="rows" :readonly="!canEdit" :household-options="baseTable.data?.household_options || []" :loading="baseTable.loading" :busy="busy" @base="onBase" @household="onHousehold" @carry="onCarry" />

    <section v-else class="panel" aria-label="确认生效">
      <div class="pt"><span>第四步：确认{{ cfg.name }}生效 <span class="muted">生效后这个月的{{ cfg.name }}记录写入系统，薪酬计算直接读取</span></span></div>
      <div v-if="batch && batch.status === 'Current'" class="cw-ok">已生效：{{ batch.source_filename }}。薪酬计算会读取这个月的{{ cfg.name }}记录；重新上传文件可以替换这一批。</div>
      <div v-else-if="blockers.length" class="cw-block"><b>还不能确认生效：</b><div v-for="entry in blockers" :key="entry.text">· {{ entry.text }} <button type="button" class="btn sm" @click="step = entry.step">去处理</button></div></div>
      <div v-else class="cw-ok">全部核对完毕，可以确认生效。</div>
      <div class="cw-hint">
        <b>薪酬就绪情况</b>（薪酬计算要求每个在职员工本月都有社保和公积金记录）<br>
        <span>· {{ readinessText(readiness.data, kind) }}<template v-if="missingNames(kind)">：{{ missingNames(kind) }}</template></span><br>
        <span>· {{ readinessText(readiness.data, other.key) }}<template v-if="missingNames(other.key)">：{{ missingNames(other.key) }}</template></span>
      </div>
      <div class="cw-foot">
        <span class="muted">生效后需要改动：重新上传文件生成新批次，或在“基数与金额”里改基数。</span>
        <span class="cw-chips"><router-link to="/payroll" class="btn">去薪酬计算</router-link><button v-if="canEdit" type="button" class="btn pri" data-cw-activate :disabled="busy || !batch || batch.status === 'Current' || blockers.length > 0" @click="activate">确认{{ cfg.name }}生效</button></span>
      </div>
    </section>

    <ContributionDrawer v-if="openItem" :kind="kind" :item="openItem" :readonly="!canEdit" :employees="employees.data || []" :busy="busy" :error="drawerError" @close="openId = ''; drawerError = ''" @confirm="onConfirm" @ignore="onIgnore" @fix="onFix" />
  </div>
</template>
