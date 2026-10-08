<script setup>
// 报销单（付给员工）与付款单（付给外部单位）共用。2026-09-30 按确认的 demo 改版：
// 首页分栏目（待我处理 / 我的 / 发票夹里能用的发票 / 全部），点栏目进列表页，点单据进详情页；
// 新建单独一页，分三步。页面用查询参数区分，通知和待办里的 ?request= 链接照常打开单据。
import { computed, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../../styles/expenseUi.css';
import {
  CLAIM_KINDS, accountBlockers, accountDraftFor, applicationLabel, callApi, claimDraftPayload,
  displayStatus, isFinanceUser, maskAccount, money, pillClass, quotaOf, sourceTypeLabel,
  submitBlockers, sumAmount, withDefaultProjects,
} from '../../lib/expenseClaims.js';
import {
  bucketOf, byWait, canQuickApprove, claimView, statusBuckets, stepTimeline, sumDocs, waitText, waitedDays,
} from '../../lib/claimView.js';

const props = defineProps({ kind: { type: String, required: true } });
const config = computed(() => CLAIM_KINDS[props.kind]);
const isClaim = computed(() => props.kind === 'claim');
const route = useRoute();
const router = useRouter();
const finance = isFinanceUser();
// 服务端只对财务、系统管理员和 Rayher Business Executive 返回全部报销 / 付款单。
const seeAll = finance || (globalThis.window?.roles || []).includes('Rayher Business Executive');

const view = computed(() => claimView(route.query));
const scope = computed(() => String(route.query.scope || (finance ? 'todo' : 'mine')));
const home = reactive({ todo: [], mine: [], all: [], loaded: false });
const docs = ref([]);
const focusDoc = ref(null);
const loading = ref(false);
const busy = ref(false);
const banner = reactive({ ok: '', err: '' });
const search = ref('');
const longOnly = ref(false);
const picked = ref([]);
const defaults = ref({ payee: {}, companies: [], urgencies: ['一般', '加急'], payment_methods: ['银行转账', '现金支付'], asset_categories: [] });
const applications = ref([]);
const availableInvoices = ref([]);
const accountTree = ref([]);
const projects = ref([]);
const accountDrafts = reactive({});
const supplement = reactive({ doc: '', picked: [], note: '' });

// ---------------------------------------------------------------- form state
const editingName = ref('');
const lockedSource = ref(false);
const form = reactive({});
const pickedInvoices = ref([]);
const lineProjects = reactive({});
const manualLines = ref([]);
const invoiceMode = ref('pending');
const step = ref(1);

function resetForm() {
  Object.assign(form, {
    source_request: '', subject: '', reason: '', urgency: '一般', doc_type: '非固定资产', asset_category: '其他',
    payment_method: '银行转账', payee_name: '', bank_name: '', branch: '', account_no: '',
    expected_invoice_date: '', no_invoice_reason: '', invoice_difference_note: '',
  });
  pickedInvoices.value = [];
  manualLines.value = [];
  Object.keys(lineProjects).forEach((key) => delete lineProjects[key]);
  editingName.value = '';
  lockedSource.value = false;
  invoiceMode.value = 'pending';
  step.value = 1;
}
resetForm();

const application = computed(() => applications.value.find((item) => item.name === form.source_request) || null);
const quota = computed(() => quotaOf(application.value));
const formInvoices = computed(() => (isClaim.value || invoiceMode.value === 'has' ? pickedInvoices.value : []));
const draftTotal = computed(() => (isClaim.value ? sumAmount(pickedInvoices.value) : sumAmount(manualLines.value)));
const blockers = computed(() => submitBlockers(props.kind, form, {
  invoices: formInvoices.value, lines: manualLines.value, application: application.value,
}));
const stepOneBlockers = computed(() => {
  if (isClaim.value) return pickedInvoices.value.length ? [] : ['先选至少一张发票'];
  return manualLines.value.length ? [] : ['先添加至少一行付款明细'];
});
const steps = computed(() => [
  { n: 1, label: isClaim.value ? '选发票' : '付款明细与发票' },
  { n: 2, label: '填写信息' },
  { n: 3, label: '确认提交' },
]);

// ---------------------------------------------------------------- page data
const now = Date.now();
const todoTop = computed(() => byWait(home.todo, now).slice(0, 3));
const mineTop = computed(() => home.mine.slice(0, 4));
const mineBuckets = computed(() => statusBuckets(home.mine));
const allBuckets = computed(() => statusBuckets(home.all));
const readyInvoices = computed(() => availableInvoices.value.slice(0, 3));
const stats = computed(() => {
  const mine = (key) => home.mine.filter((doc) => bucketOf(doc) === key);
  const todoLongest = Math.max(0, ...home.todo.map((doc) => waitedDays(doc, now) || 0));
  return [
    { key: 'todo', label: '待我处理', count: home.todo.length, amount: sumDocs(home.todo), hint: home.todo.length ? `最久的等了 ${todoLongest} 天` : '没有要处理的', tone: '#D98C4A', query: { view: 'list', scope: 'todo' } },
    { key: 'draft', label: '我的草稿', count: mine('draft').length, amount: sumDocs(mine('draft')), hint: '继续编辑后提交', tone: '#C3CAD6', query: { view: 'list', scope: 'mine' } },
    { key: 'review', label: '我的 · 审批中', count: mine('review').length, amount: sumDocs(mine('review')), hint: '点进去看卡在谁那里', tone: '#5470C6', query: { view: 'list', scope: 'mine' } },
    { key: 'topay', label: '我的 · 待付款', count: mine('topay').length, amount: sumDocs(mine('topay')), hint: '出纳付款后会通知你', tone: '#E3B26B', query: { view: 'list', scope: 'mine' } },
  ];
});
const scopes = computed(() => [
  ...(finance || home.todo.length ? [{ key: 'todo', label: '待我处理' }] : []),
  { key: 'mine', label: `我的${config.value.label}` },
  ...(seeAll ? [{ key: 'all', label: `全部${config.value.label}` }] : []),
]);
const listRows = computed(() => {
  const query = search.value.trim().toLowerCase();
  return docs.value.filter((doc) => {
    if (longOnly.value && (waitedDays(doc, now) || 0) < 3) return false;
    return !query || [doc.name, doc.subject, doc.employee_name, doc.payee_name].join(' ').toLowerCase().includes(query);
  });
});
const pickedDocs = computed(() => listRows.value.filter((doc) => picked.value.includes(doc.name)));
const timeline = computed(() => stepTimeline(focusDoc.value || {}));

// ---------------------------------------------------------------- loading
function flash(ok = '', err = '') {
  banner.ok = ok;
  banner.err = err;
}

function go(query = {}) {
  flash();
  router.push({ path: route.path, query });
}

async function run(action, okText) {
  busy.value = true;
  flash();
  try {
    const result = await action();
    if (okText) flash(typeof okText === 'function' ? okText(result) : okText);
    await loadPage();
    return result;
  } catch (error) {
    flash('', String(error?.message || error || '操作失败'));
    // 单据已经变化（别人先处理了、被驳回过）：重新加载，页面显示最新的一步。
    if (/单据已经变化|页面版本过旧/.test(String(error?.message || error || ''))) await loadPage();
    return null;
  } finally {
    busy.value = false;
  }
}

const listFor = (listView, extra = {}) => callApi('oa_entry.list_requests', { view: listView, request_type: config.value.requestType, limit: 50, ...extra }, { method: 'GET' });

// 待我处理 = 当前轮到我的审批 + 待核验的付款单（财务）。
async function loadTodo() {
  const [pending, verify] = await Promise.all([
    listFor('pending'),
    finance && !isClaim.value ? callApi('expense_claim_entry.list_verify_queue', {}, { method: 'GET' }) : [],
  ]);
  return [...(pending || []), ...(verify || []).filter((doc) => !(pending || []).some((row) => row.name === doc.name))];
}

async function prepareAccounts(rows) {
  for (const doc of rows) {
    if (doc.can_edit_expense_items) accountDrafts[doc.name] = accountDraftFor(doc.expense_lines);
  }
  // 修复（2026-09-23）：出纳在单据里直接选科目，有待填科目的单据时就取科目表。
  if (!accountTree.value.length && rows.some((doc) => doc.can_edit_expense_items)) {
    const options = await callApi('oa_entry.get_options', {}, { method: 'GET' });
    accountTree.value = options?.expense_account_tree || [];
  }
}

async function loadHome() {
  const [todo, mine, all, invoices] = await Promise.all([
    loadTodo(),
    listFor('mine'),
    finance ? listFor('all', { limit: 200 }) : [],
    callApi('expense_claim_entry.list_available_invoices', { request_type: config.value.requestType }, { method: 'GET' }).catch(() => []),
  ]);
  Object.assign(home, { todo: todo || [], mine: mine || [], all: all || [], loaded: true });
  availableInvoices.value = invoices || [];
}

async function loadList() {
  picked.value = [];
  if (scope.value === 'todo') docs.value = await loadTodo();
  else if (scope.value === 'all' && seeAll) docs.value = (await listFor('all', { limit: 200 })) || [];
  else docs.value = (await listFor('mine')) || [];
  if (!home.loaded) home.todo = scope.value === 'todo' ? docs.value : await loadTodo();
}

async function loadDetail() {
  const name = String(route.query.request || '');
  focusDoc.value = ((await listFor('all', { name, limit: 1 })) || [])[0] || null;
  if (focusDoc.value) await prepareAccounts([focusDoc.value]);
}

async function loadPage() {
  if (view.value === 'new') return;
  loading.value = true;
  try {
    if (view.value === 'detail') await loadDetail();
    else if (view.value === 'list') await loadList();
    else await loadHome();
  } catch (error) {
    flash('', String(error?.message || error));
  } finally {
    loading.value = false;
  }
}

// 修复（2026-09-23）：原来五项数据一起取，任何一项失败其余全部作废（表单空白），
// 现在各取各的：失败的那项用空值，并提示出错原因。
async function loadLookups() {
  const type = { request_type: config.value.requestType };
  const results = await Promise.allSettled([
    callApi('expense_claim_entry.claim_defaults', type, { method: 'GET' }),
    callApi('expense_claim_entry.list_linkable_applications', type, { method: 'GET' }),
    callApi('expense_claim_entry.list_available_invoices', type, { method: 'GET' }),
    callApi('oa_entry.get_options', {}, { method: 'GET' }),
    callApi('expense_claim_entry.list_claim_projects', type, { method: 'GET' }),
  ]);
  const value = (index) => (results[index].status === 'fulfilled' ? results[index].value : null);
  defaults.value = value(0) || defaults.value;
  applications.value = value(1) || [];
  availableInvoices.value = value(2) || [];
  Object.assign(lineProjects, withDefaultProjects(availableInvoices.value, lineProjects));
  accountTree.value = value(3)?.expense_account_tree || accountTree.value;
  projects.value = (value(4) || []).map((row) => row.name || row);
  const failed = results.find((result) => result.status === 'rejected');
  if (failed) flash('', `部分数据加载失败：${String(failed.reason?.message || failed.reason)}`);
}

// ---------------------------------------------------------------- new / draft
async function openNew() {
  resetForm();
  try {
    await loadLookups();
    if (!form.source_request && applications.value.length) form.source_request = applications.value[0].name;
    // 从首页"用这些发票新建"进来：发票夹里能用的发票默认全选。
    if (route.query.pick === 'all' && isClaim.value) pickedInvoices.value = [...availableInvoices.value];
  } catch (error) {
    flash('', String(error?.message || error));
  }
}

async function openDraft(doc) {
  resetForm();
  // 先记住草稿编号：即使某项数据加载失败，保存时也是更新这张草稿，不会另存一份。
  editingName.value = doc.name;
  lockedSource.value = Boolean(doc.source_locked);
  await loadLookups();
  Object.assign(form, {
    source_request: doc.source_request || '', subject: doc.subject || '', reason: doc.reason || '',
    urgency: doc.urgency || '一般', doc_type: doc.doc_type === '固定资产' ? '固定资产' : '非固定资产',
    asset_category: doc.asset_category || '其他', payment_method: doc.payment_method || '银行转账',
    payee_name: doc.payee_name || '', bank_name: doc.bank_name || '', branch: doc.branch || '', account_no: doc.account_no || '',
    expected_invoice_date: doc.expected_invoice_date || '', no_invoice_reason: doc.no_invoice_reason || '',
    invoice_difference_note: doc.invoice_difference_note || '',
  });
  if (doc.source_request && !applications.value.some((item) => item.name === doc.source_request)) {
    applications.value.unshift({ name: doc.source_request, subject: '', request_type: sourceTypeLabel(doc) });
  }
  const lines = doc.expense_lines || [];
  const linked = lines.filter((line) => line.source_invoice).map((line) => ({
    name: line.source_invoice, project_name: line.project_name, issue_date: line.issue_date,
    invoice_number: line.invoice_number, total_amount: line.total_amount, expense_description: line.expense_description,
  }));
  if (isClaim.value) {
    pickedInvoices.value = linked;
    availableInvoices.value = [...linked, ...availableInvoices.value.filter((row) => !linked.some((item) => item.name === row.name))];
    lines.forEach((line) => { if (line.source_invoice) lineProjects[line.source_invoice] = (doc.claim_line_projects || {})[line.line_key] || ''; });
  } else {
    manualLines.value = lines.filter((line) => !line.source_invoice).map((line) => ({
      line_key: line.line_key, project_name: line.project_name, claim_project: (doc.claim_line_projects || {})[line.line_key] || '',
      issue_date: line.issue_date, total_amount: line.total_amount, expense_description: line.expense_description,
    }));
    // 付款单的发票挂在单据上（不对应明细行），重新打开草稿时要把已选的发票带回来，否则保存会把它们解除。
    let attached;
    try {
      attached = (await callApi('invoice_entry.get_request_invoices', { request: doc.name }, { method: 'GET' })) || [];
    } catch (error) {
      // 取不到已选的发票就不能打开编辑：保存会把这些发票从草稿上解除。
      resetForm();
      go({ view: 'list', scope: 'mine' });
      flash('', `草稿的发票加载失败，请稍后再试：${String(error?.message || error)}`);
      return;
    }
    pickedInvoices.value = attached.filter((row) => row.recognition_status === '已确认');
    availableInvoices.value = [...pickedInvoices.value, ...availableInvoices.value.filter((row) => !pickedInvoices.value.some((item) => item.name === row.name))];
    invoiceMode.value = pickedInvoices.value.length ? 'has' : 'pending';
  }
}

async function enterNewPage() {
  if (route.query.source) {
    const source = String(route.query.source);
    busy.value = true;
    try {
      const draft = await callApi('expense_claim_entry.push_from_application', { source_request: source, request_type: config.value.requestType });
      flash(`已从申请 ${source} 生成${config.value.label}单草稿，关联申请已锁定`);
      router.replace({ path: route.path, query: { view: 'new', draft: draft.name } });
    } catch (error) {
      flash('', String(error?.message || error));
      router.replace({ path: route.path, query: {} });
    } finally {
      busy.value = false;
    }
    return;
  }
  if (route.query.draft) {
    const draftName = String(route.query.draft);
    if (editingName.value === draftName) return;
    const doc = ((await listFor('mine', { name: draftName, limit: 1 })) || [])[0];
    if (!doc) {
      flash('', `找不到草稿 ${draftName}`);
      return;
    }
    await openDraft(doc);
    return;
  }
  await openNew();
}

function togglePicked(invoice) {
  const index = pickedInvoices.value.findIndex((item) => item.name === invoice.name);
  if (index >= 0) pickedInvoices.value.splice(index, 1);
  else pickedInvoices.value.push(invoice);
}

function addLine() {
  manualLines.value.push({ line_key: '', project_name: '', claim_project: '', issue_date: '', total_amount: '', expense_description: '' });
}

async function save({ submit = false } = {}) {
  if (!isClaim.value && invoiceMode.value === 'has') {
    form.no_invoice_reason = '';
    form.expected_invoice_date = '';
  }
  const payload = claimDraftPayload(props.kind, form, { invoices: formInvoices.value, projects: lineProjects, lines: manualLines.value });
  busy.value = true;
  flash();
  try {
    const doc = await callApi('expense_claim_entry.save_claim_draft', {
      request_type: config.value.requestType, payload: JSON.stringify(payload), name: editingName.value || undefined,
    });
    editingName.value = doc.name;
    if (submit) {
      await callApi('oa_entry.submit_request', { name: doc.name });
      resetForm();
      router.push({ path: route.path, query: { request: doc.name } });
      flash(`${config.value.label}单 ${doc.name} 已提交审批`);
    } else {
      router.replace({ path: route.path, query: { view: 'new', draft: doc.name } });
      flash(`草稿 ${doc.name} 已保存`);
    }
  } catch (error) {
    flash('', String(error?.message || error || '保存失败'));
  } finally {
    busy.value = false;
  }
}

function nextStep() {
  if (step.value === 1 && stepOneBlockers.value.length) {
    flash('', stepOneBlockers.value[0]);
    return;
  }
  flash();
  step.value = Math.min(3, step.value + 1);
}

// ---------------------------------------------------------------- document actions
const levelTwo = (levelOne) => (accountTree.value.find((item) => item.level_1 === levelOne)?.level_2) || [];

async function approve(doc) {
  await run(async () => {
    if (doc.can_edit_expense_items) {
      const lines = Object.entries(accountDrafts[doc.name] || {}).map(([line_key, value]) => ({ line_key, ...value }));
      const problems = accountBlockers(lines, accountTree.value);
      if (problems.length) throw new Error(problems[0]);
      await callApi('expense_claim_entry.save_claim_accounts', { name: doc.name, lines: JSON.stringify(lines) });
    }
    return callApi('oa_entry.action_request', { name: doc.name, action: 'approve', expected_step_key: doc.current_step_key || '' });
  }, doc.current_step_mode === 'handle' ? `${doc.name} 已确认付款` : `${doc.name} 已同意`);
}

async function approvePicked() {
  const rows = pickedDocs.value.filter(canQuickApprove);
  if (!rows.length) return;
  await run(async () => {
    for (const doc of rows) {
      await callApi('oa_entry.action_request', { name: doc.name, action: 'approve', expected_step_key: doc.current_step_key || '' });
    }
    return rows.length;
  }, (count) => `已同意 ${count} 张`);
}

async function reject(doc) {
  const note = (window.prompt('请填写驳回原因') || '').trim();
  if (!note) return;
  await run(() => callApi('oa_entry.action_request', { name: doc.name, action: 'reject', note, reject_target: 'applicant', expected_step_key: doc.current_step_key || '' }), `${doc.name} 已驳回给申请人`);
}

async function withdraw(doc) {
  const note = (window.prompt('请填写撤回原因（可选）') || '').trim();
  await run(() => callApi('oa_entry.withdraw_request', { name: doc.name, note }), `${doc.name} 已撤回为草稿`);
}

function openSupplement(doc) {
  Object.assign(supplement, { doc: doc.name, picked: [], note: '' });
  loadLookups().catch((error) => flash('', String(error?.message || error)));
}

async function submitSupplement(doc) {
  if (!supplement.picked.length) {
    flash('', '请选择要补录的发票');
    return;
  }
  const done = await run(() => callApi('expense_claim_entry.supplement_payment_invoices', {
    name: doc.name, invoice_names: JSON.stringify(supplement.picked), difference_note: supplement.note,
  }), '发票已补录，等待财务核验');
  if (done) supplement.doc = '';
}

async function verify(doc) {
  await run(() => callApi('expense_claim_entry.verify_claim_invoices', { name: doc.name }), `${doc.name} 发票核验通过，单据完结`);
}

async function returnInvoices(doc) {
  const note = (window.prompt('请填写退回原因') || '').trim();
  if (!note) return;
  await run(() => callApi('expense_claim_entry.return_claim_invoices', { name: doc.name, note }), `${doc.name} 已退回申请人重新补票`);
}

async function withdrawPayment(doc) {
  const note = (window.prompt('请填写撤回付款的原因') || '').trim();
  if (!note) return;
  await run(() => callApi('expense_claim_entry.withdraw_claim_payment', { name: doc.name, note }), `${doc.name} 付款已撤回，回到出纳确认付款`);
}

function togglePick(doc) {
  picked.value = picked.value.includes(doc.name) ? picked.value.filter((name) => name !== doc.name) : [...picked.value, doc.name];
}

watch(() => [view.value, scope.value, route.query.request, route.query.draft, route.query.source], () => {
  if (view.value === 'new') enterNewPage();
  else loadPage();
}, { immediate: true });
</script>

<template>
  <div class="xp claim">
    <!-- ============================== 首页 ============================== -->
    <template v-if="view === 'home'">
      <div class="ph">
        <div>
          <div class="crumb">审批中心 · 付款申请</div>
          <h3>{{ config.label }}</h3>
          <div class="muted">{{ isClaim ? '员工垫付的费用，凭发票报销，钱打到本人账户。' : '付给外部单位；可以先付款，付款后必须补发票。' }}</div>
        </div>
        <div class="head-actions">
          <button type="button" class="btn" @click="router.push('/approval/invoice-folder')">去发票夹上传发票</button>
          <button type="button" class="btn pri lg" @click="go({ view: 'new' })">＋ 新建{{ config.label }}</button>
        </div>
      </div>
      <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
      <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>
      <div v-if="loading && !home.loaded" class="panel empty">正在加载…</div>
      <template v-else>
        <div class="stat-cards">
          <button v-for="card in stats" :key="card.key" type="button" class="stat-card" @click="go(card.query)">
            <span class="l"><i :style="{ background: card.tone }"></i>{{ card.label }}</span>
            <span class="v"><b>{{ card.count }}</b> 张<em>¥ {{ money(card.amount) }}</em></span>
            <span class="l">{{ card.hint }}</span>
          </button>
        </div>

        <div class="home-grid">
          <section v-if="finance || home.todo.length" class="panel">
            <div class="pt"><span>待我处理 <span class="count-pill">{{ home.todo.length }}</span></span><button type="button" class="link" @click="go({ view: 'list', scope: 'todo' })">全部 {{ home.todo.length }} 张 →</button></div>
            <div v-for="doc in todoTop" :key="doc.name" class="todo-row">
              <span class="avatar">{{ (doc.employee_name || '?').slice(0, 1) }}</span>
              <div class="grow-col"><b class="ellipsis">{{ doc.subject || '（无主题）' }}</b><span class="muted">{{ doc.employee_name }} · {{ doc.name }}<template v-if="doc.current_step_label"> · {{ doc.current_step_label }}</template></span></div>
              <span class="amount">¥ {{ money(doc.amount) }}</span>
              <span :class="['wait', { warn: (waitedDays(doc, now) || 0) >= 3 }]">{{ waitText(waitedDays(doc, now)) }}</span>
              <span class="row-actions">
                <button type="button" class="btn sm" @click="go({ request: doc.name })">看详情</button>
                <button v-if="canQuickApprove(doc)" type="button" class="btn sm dark" :disabled="busy" @click="approve(doc)">同意</button>
              </span>
            </div>
            <div v-if="!home.todo.length" class="empty">没有需要你处理的单据</div>
            <div v-else class="muted foot">只列等得最久的 3 张；出纳填科目、确认付款请进详情页。</div>
          </section>

          <section class="panel">
            <div class="pt"><span>我的{{ config.label }}</span><button type="button" class="link" @click="go({ view: 'list', scope: 'mine' })">全部 {{ home.mine.length }} 张 →</button></div>
            <div class="stack-bar"><i v-for="bucket in mineBuckets" :key="bucket.key" :style="{ width: bucket.width, background: bucket.color }"></i></div>
            <div class="bucket-legend"><span v-for="bucket in mineBuckets" :key="bucket.key"><i :style="{ background: bucket.color }"></i>{{ bucket.label }} {{ bucket.count }}</span></div>
            <button v-for="doc in mineTop" :key="doc.name" type="button" class="mine-row" @click="doc.workflow_status === '草稿' ? go({ view: 'new', draft: doc.name }) : go({ request: doc.name })">
              <span class="grow-col"><span class="ellipsis">{{ doc.subject || '（无主题）' }}</span><span class="muted">{{ doc.name }}</span></span>
              <span class="amount">¥ {{ money(doc.amount) }}</span>
              <span :class="pillClass(displayStatus(doc))">{{ displayStatus(doc) }}</span>
            </button>
            <div v-if="!home.mine.length" class="empty">还没有{{ config.label }}单，点右上角新建</div>
          </section>
        </div>

        <section class="panel">
          <div class="pt"><span>发票夹里{{ isClaim ? '还能报销' : '可以用' }}的发票 <span class="muted">已识别、已确认、还没用过</span></span><button type="button" class="link" @click="router.push('/approval/invoice-folder')">去发票夹 →</button></div>
          <div class="invoice-strip">
            <div v-for="invoice in readyInvoices" :key="invoice.name" class="invoice-card">
              <span class="muted">{{ invoice.issue_date || '—' }}</span>
              <b class="ellipsis">{{ invoice.project_name || invoice.expense_description || '未填写项目名称' }}</b>
              <span class="split"><span class="muted num">{{ invoice.invoice_number }}</span><b>¥ {{ money(invoice.total_amount) }}</b></span>
            </div>
            <button v-if="availableInvoices.length && isClaim" type="button" class="invoice-cta" @click="go({ view: 'new', pick: 'all' })">
              <span>{{ availableInvoices.length }} 张 · 合计 ¥ {{ money(sumAmount(availableInvoices)) }}</span>
              <b>用这些发票新建报销 →</b>
            </button>
            <div v-if="!availableInvoices.length" class="empty grow-col">发票夹里没有能用的发票，先去上传、确认</div>
          </div>
        </section>

        <section v-if="finance" class="panel">
          <div class="pt"><span>全部{{ config.label }} <span class="tag">财务可见</span></span><span class="links"><button type="button" class="link" @click="go({ view: 'list', scope: 'all' })">全部列表 →</button><button type="button" class="link" @click="router.push('/approval/expense-payment-board')">付款看板 →</button></span></div>
          <div class="bucket-cards">
            <button v-for="bucket in allBuckets" :key="bucket.key" type="button" class="bucket-card" @click="go({ view: 'list', scope: 'all' })">
              <span class="muted"><i :style="{ background: bucket.color }"></i>{{ bucket.label }}</span>
              <b>{{ bucket.count }} 张</b>
              <span class="muted">¥ {{ money(bucket.amount) }}</span>
            </button>
          </div>
          <div class="muted foot">按最近 200 张统计。</div>
        </section>
      </template>
    </template>

    <!-- ============================== 列表页 ============================== -->
    <template v-else-if="view === 'list'">
      <div class="ph">
        <div>
          <div class="crumb"><button type="button" class="link" @click="go({})">{{ config.label }}</button> › {{ scopes.find((item) => item.key === scope)?.label }}</div>
          <h3>{{ scopes.find((item) => item.key === scope)?.label }} · {{ docs.length }} 张</h3>
        </div>
        <div class="seg">
          <button v-for="item in scopes" :key="item.key" type="button" :aria-pressed="scope === item.key" @click="go({ view: 'list', scope: item.key })">{{ item.label }}</button>
        </div>
      </div>
      <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
      <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>
      <div class="filter-bar">
        <input v-model="search" type="search" placeholder="搜单号、申请人、主题、收款单位" aria-label="搜索" />
        <button v-if="scope === 'todo'" type="button" :class="['chip', { on: longOnly }]" @click="longOnly = !longOnly">等超过 3 天</button>
        <button type="button" class="btn pri" @click="go({ view: 'new' })">＋ 新建{{ config.label }}</button>
      </div>
      <div class="panel flush">
        <div class="tbl">
          <table>
            <thead><tr><th v-if="scope === 'todo'" style="width:36px"></th><th>单号</th><th>申请人</th><th>主题</th><th class="r">金额</th><th>状态</th><th>当前节点</th><th>等待</th><th class="r">操作</th></tr></thead>
            <tbody>
              <tr v-for="doc in listRows" :key="doc.name" :class="{ on: picked.includes(doc.name) }">
                <td v-if="scope === 'todo'"><input type="checkbox" :disabled="!canQuickApprove(doc)" :checked="picked.includes(doc.name)" :aria-label="'选择 ' + doc.name" :title="canQuickApprove(doc) ? '' : '这一步要进详情页处理'" @change="togglePick(doc)" /></td>
                <td class="num"><button type="button" class="link strong" @click="go({ request: doc.name })">{{ doc.name }}</button><span v-if="doc.urgency === '加急'" class="pill p-red" style="margin-left:4px">加急</span></td>
                <td>{{ doc.employee_name }}</td>
                <td class="ellipsis-cell">{{ doc.subject }}</td>
                <td class="r num">¥ {{ money(doc.amount) }}</td>
                <td><span :class="pillClass(displayStatus(doc))">{{ displayStatus(doc) }}</span></td>
                <td>{{ ['待审批', '待办理'].includes(doc.workflow_status) ? (doc.current_step_label || '—') : '—' }}</td>
                <td :class="{ warn: (waitedDays(doc, now) || 0) >= 3 && ['待审批', '待办理'].includes(doc.workflow_status) }">{{ ['待审批', '待办理'].includes(doc.workflow_status) ? waitText(waitedDays(doc, now)) : '—' }}</td>
                <td class="r">
                  <button v-if="doc.workflow_status === '草稿' && scope === 'mine'" type="button" class="btn sm" @click="go({ view: 'new', draft: doc.name })">继续编辑</button>
                  <button v-else type="button" class="btn sm" @click="go({ request: doc.name })">详情</button>
                </td>
              </tr>
              <tr v-if="!listRows.length"><td colspan="9" class="empty">{{ loading ? '正在加载…' : '这里没有单据' }}</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-if="pickedDocs.length" class="batch-bar">
        <span>已选 {{ pickedDocs.length }} 张 · 合计 ¥ {{ money(sumDocs(pickedDocs)) }}</span>
        <span class="grow-col"></span>
        <button type="button" class="btn" @click="picked = []">取消选择</button>
        <button type="button" class="btn pri" :disabled="busy" @click="approvePicked">批量同意</button>
      </div>
    </template>

    <!-- ============================== 详情页 ============================== -->
    <template v-else-if="view === 'detail'">
      <div class="crumb"><button type="button" class="link" @click="go({})">{{ config.label }}</button> › <button type="button" class="link" @click="go({ view: 'list', scope })">列表</button> › {{ route.query.request }}</div>
      <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
      <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>
      <div v-if="loading && !focusDoc" class="panel empty">正在加载…</div>
      <div v-else-if="!focusDoc" class="panel empty">找不到单据 {{ route.query.request }}，可能没有查看权限</div>
      <template v-else>
        <section class="panel detail-head">
          <div class="grow-col">
            <div class="title-line"><h3>{{ focusDoc.subject || '（无主题）' }}</h3><span :class="pillClass(displayStatus(focusDoc))">{{ displayStatus(focusDoc) }}</span><span v-if="focusDoc.invoice_due_state" class="pill p-red">{{ focusDoc.invoice_due_state }}</span></div>
            <div class="muted">{{ focusDoc.name }} · {{ focusDoc.employee_name }}<template v-if="['待审批', '待办理'].includes(focusDoc.workflow_status) && focusDoc.current_step_label"> · 在 {{ focusDoc.current_step_label }} · {{ waitText(waitedDays(focusDoc, now)) }}</template></div>
          </div>
          <div class="amount-block"><span class="muted">{{ isClaim ? '报销金额' : '付款金额' }}</span><b>¥ {{ money(focusDoc.amount) }}</b></div>
          <div class="head-buttons">
            <button v-if="focusDoc.can_reject" type="button" class="btn danger" :disabled="busy" @click="reject(focusDoc)">驳回</button>
            <button v-if="focusDoc.can_withdraw" type="button" class="btn" :disabled="busy" @click="withdraw(focusDoc)">撤回</button>
            <button v-if="focusDoc.can_withdraw_claim_payment" type="button" class="btn danger" :disabled="busy" @click="withdrawPayment(focusDoc)">撤回付款</button>
            <button v-if="focusDoc.can_verify_claim_invoices" type="button" class="btn" :disabled="busy" @click="returnInvoices(focusDoc)">退回补票</button>
            <button v-if="focusDoc.can_verify_claim_invoices" type="button" class="btn pri" :disabled="busy" @click="verify(focusDoc)">核验通过</button>
            <button v-if="focusDoc.can_supplement_claim_invoices && supplement.doc !== focusDoc.name" type="button" class="btn pri" :disabled="busy" @click="openSupplement(focusDoc)">补录发票</button>
            <button v-if="focusDoc.workflow_status === '草稿'" type="button" class="btn" :disabled="busy" @click="go({ view: 'new', draft: focusDoc.name })">继续编辑</button>
            <!-- 出纳审核：科目没填完时后端 can_approve 为 false，但出纳正是要在这里填科目再同意（先保存科目再同意）。 -->
            <button v-if="focusDoc.can_approve || focusDoc.can_edit_expense_items" type="button" class="btn pri lg" :disabled="busy" @click="approve(focusDoc)">{{ focusDoc.current_step_mode === 'handle' ? '确认付款' : '同意' }}</button>
          </div>
        </section>

        <div class="detail-grid">
          <div>
            <section class="panel">
              <div class="pt">基本信息</div>
              <div class="kv">
                <div><span>申请人</span>{{ focusDoc.employee_name }}</div>
                <div><span>关联申请</span>{{ focusDoc.source_request || '—' }} {{ sourceTypeLabel(focusDoc) }}</div>
                <div><span>付款单位</span>{{ focusDoc.company }}</div>
                <div><span>单据类型</span>{{ focusDoc.doc_type }}</div>
                <div><span>资产类别</span>{{ focusDoc.asset_category }}</div>
                <div><span>紧急程度</span>{{ focusDoc.urgency || '一般' }}</div>
                <div><span>{{ isClaim ? '收款人' : '收款单位' }}</span>{{ focusDoc.payee_name || '—' }}</div>
                <div><span>收款账户</span>{{ [focusDoc.bank_name, focusDoc.branch, maskAccount(focusDoc.account_no)].filter(Boolean).join(' ') || '—' }}</div>
                <div v-if="!isClaim && focusDoc.expected_invoice_date && focusDoc.invoice_followup_status === '待收票'"><span>预计取票</span>{{ focusDoc.expected_invoice_date }}</div>
                <div v-if="focusDoc.reason" class="s2"><span>说明</span>{{ focusDoc.reason }}</div>
              </div>
            </section>

            <section class="panel">
              <div class="pt"><span>费用明细<template v-if="focusDoc.can_edit_expense_items"> · 请填写科目后再同意</template></span></div>
              <div class="tbl">
                <table>
                  <thead>
                    <tr>
                      <th>{{ isClaim ? '发票号码' : '付款内容' }}</th><th>{{ isClaim ? '项目名称' : '日期' }}</th><th>所属项目</th><th>费用说明</th>
                      <th class="r">金额</th><th>一级科目</th><th>二级科目</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="line in focusDoc.expense_lines || []" :key="line.line_key">
                      <td :class="{ num: isClaim }">{{ isClaim ? line.invoice_number : line.project_name }}</td>
                      <td :class="{ num: !isClaim }">{{ isClaim ? line.project_name : line.issue_date }}</td>
                      <td>{{ (focusDoc.claim_line_projects || {})[line.line_key] || '非项目' }}</td>
                      <td>{{ line.expense_description }}</td>
                      <td class="r num">{{ money(line.total_amount) }}</td>
                      <template v-if="focusDoc.can_edit_expense_items && accountDrafts[focusDoc.name]?.[line.line_key]">
                        <td>
                          <select v-model="accountDrafts[focusDoc.name][line.line_key].expense_account_level_1" class="cell" aria-label="一级科目"
                            @change="accountDrafts[focusDoc.name][line.line_key].expense_account_level_2 = ''">
                            <option value="">请选择</option>
                            <option v-for="item in accountTree" :key="item.level_1" :value="item.level_1">{{ item.level_1 }}</option>
                          </select>
                        </td>
                        <td>
                          <select v-model="accountDrafts[focusDoc.name][line.line_key].expense_account_level_2" class="cell" aria-label="二级科目"
                            :disabled="Boolean(accountDrafts[focusDoc.name][line.line_key].expense_account_level_1) && !levelTwo(accountDrafts[focusDoc.name][line.line_key].expense_account_level_1).length">
                            <option value="">{{ accountDrafts[focusDoc.name][line.line_key].expense_account_level_1 && !levelTwo(accountDrafts[focusDoc.name][line.line_key].expense_account_level_1).length ? '无二级科目' : '请选择' }}</option>
                            <option v-for="item in levelTwo(accountDrafts[focusDoc.name][line.line_key].expense_account_level_1)" :key="item" :value="item">{{ item }}</option>
                          </select>
                        </td>
                      </template>
                      <template v-else>
                        <td>{{ line.expense_account_level_1 || '—' }}</td>
                        <td>{{ line.expense_account_level_2 || '—' }}</td>
                      </template>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-if="!isClaim" class="muted" style="margin-top:6px">
                发票：
                <template v-if="(focusDoc.invoice_numbers || []).length">{{ focusDoc.invoice_numbers.join('、') }}</template>
                <span v-else-if="focusDoc.invoice_followup_status === '待收票'" class="pill p-sun">待补票</span>
                <template v-else>—</template>
                <template v-if="focusDoc.invoice_difference_note"> · 差异说明：{{ focusDoc.invoice_difference_note }}</template>
              </div>
            </section>

            <section v-if="supplement.doc === focusDoc.name" class="panel accent">
              <div class="pt"><span>补录发票</span><button type="button" class="btn sm" @click="router.push('/approval/invoice-folder')">＋ 上传新发票</button></div>
              <div class="tbl">
                <table>
                  <thead><tr><th style="width:36px"></th><th>发票号码</th><th>项目名称</th><th class="r">合计</th><th>费用说明</th></tr></thead>
                  <tbody>
                    <tr v-for="invoice in availableInvoices" :key="invoice.name">
                      <td><input v-model="supplement.picked" type="checkbox" :value="invoice.name" /></td>
                      <td class="num">{{ invoice.invoice_number }}</td><td>{{ invoice.project_name }}</td><td class="r num">{{ money(invoice.total_amount) }}</td><td>{{ invoice.expense_description }}</td>
                    </tr>
                    <tr v-if="!availableInvoices.length"><td colspan="5" class="empty">发票夹里没有可用的发票，先去上传并确认</td></tr>
                  </tbody>
                </table>
              </div>
              <div class="form" style="margin-top:10px">
                <div class="f s2"><label>差异说明</label><input v-model="supplement.note" placeholder="发票合计与付款金额相差超过 0.02 元时必填" /></div>
              </div>
              <div class="actions">
                <button type="button" class="btn pri" :disabled="busy" @click="submitSupplement(focusDoc)">提交补录</button>
                <button type="button" class="btn" @click="supplement.doc = ''">取消</button>
              </div>
            </section>
          </div>

          <aside>
            <section class="panel">
              <div class="pt">审批进度</div>
              <div v-for="(item, index) in timeline" :key="item.key" :class="['tl', item.state]">
                <div class="rail"><i></i><span v-if="index < timeline.length - 1"></span></div>
                <div class="body"><b>{{ item.label }}</b><span v-if="item.sub" class="muted">{{ item.sub }}</span><span v-if="item.note" class="note">{{ item.note }}</span></div>
              </div>
              <div v-if="!timeline.length" class="muted">还没有提交审批</div>
            </section>
          </aside>
        </div>
      </template>
    </template>

    <!-- ============================== 新建 / 编辑草稿 ============================== -->
    <template v-else>
      <div class="ph">
        <div>
          <div class="crumb"><button type="button" class="link" @click="go({})">{{ config.label }}</button> › {{ editingName ? `编辑草稿 ${editingName}` : `新建${config.label}` }}</div>
          <h3>{{ editingName ? '编辑草稿' : `新建${config.label}` }}</h3>
        </div>
        <div class="stepper">
          <button v-for="item in steps" :key="item.n" type="button" :aria-current="step === item.n ? 'step' : undefined" :class="{ on: step === item.n, done: step > item.n }" @click="item.n === 1 || !stepOneBlockers.length ? (step = item.n) : flash('', stepOneBlockers[0])">
            <i>{{ step > item.n ? '✓' : item.n }}</i>{{ item.label }}
          </button>
        </div>
      </div>
      <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
      <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>

      <div class="new-grid">
        <div>
          <!-- 第 1 步 -->
          <template v-if="step === 1">
            <div v-if="isClaim" class="panel">
              <div class="pt"><span>选这次要报销的发票</span><button type="button" class="btn sm" @click="router.push('/approval/invoice-folder')">＋ 上传新发票</button></div>
              <div class="muted" style="margin-bottom:10px">只列出发票夹里已确认、还没用过的发票；报销金额 = 所选发票合计，不用再手填。</div>
              <div class="pick-grid">
                <label v-for="invoice in availableInvoices" :key="invoice.name" :class="['pick', { on: pickedInvoices.some((item) => item.name === invoice.name) }]">
                  <input type="checkbox" :checked="pickedInvoices.some((item) => item.name === invoice.name)" :aria-label="'选择发票 ' + invoice.invoice_number" @change="togglePicked(invoice)" />
                  <span class="grow-col">
                    <span class="split"><span class="muted">{{ invoice.issue_date || '—' }}</span><span class="muted num">{{ invoice.invoice_number }}</span></span>
                    <b class="ellipsis">{{ invoice.project_name || '未填写项目名称' }}</b>
                    <span class="split"><span class="muted ellipsis">{{ invoice.expense_description }}</span><b>¥ {{ money(invoice.total_amount) }}</b></span>
                    <select v-model="lineProjects[invoice.name]" class="cell" aria-label="所属项目" @click.stop>
                      <option value="">非项目</option>
                      <option v-for="project in projects" :key="project" :value="project">{{ project }}</option>
                    </select>
                  </span>
                </label>
              </div>
              <div v-if="!availableInvoices.length" class="empty">发票夹里没有可用的发票，先去上传并确认</div>
            </div>
            <template v-else>
              <div class="panel">
                <div class="pt"><span>付款明细</span><button type="button" class="btn sm" @click="addLine">＋ 添加一行</button></div>
                <div class="tbl">
                  <table>
                    <thead><tr><th>付款内容</th><th>所属项目</th><th style="width:150px">日期</th><th>费用说明</th><th style="width:130px">金额</th><th style="width:48px"></th></tr></thead>
                    <tbody>
                      <tr v-for="(line, index) in manualLines" :key="index">
                        <td><input v-model="line.project_name" class="cell" aria-label="付款内容" /></td>
                        <td>
                          <select v-model="line.claim_project" class="cell" aria-label="所属项目">
                            <option value="">非项目</option>
                            <option v-for="project in projects" :key="project" :value="project">{{ project }}</option>
                          </select>
                        </td>
                        <td><input v-model="line.issue_date" type="date" class="cell" aria-label="日期" /></td>
                        <td><input v-model="line.expense_description" class="cell" aria-label="费用说明" /></td>
                        <td><input v-model="line.total_amount" type="number" min="0" step="0.01" class="cell num" aria-label="金额" /></td>
                        <td><button type="button" class="btn sm danger" @click="manualLines.splice(index, 1)">删</button></td>
                      </tr>
                      <tr v-if="!manualLines.length"><td colspan="6" class="empty">点右上角"添加一行"填写付款明细</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div class="panel">
                <div class="pt">发票</div>
                <div class="form">
                  <div class="f"><label>发票情况</label><select v-model="invoiceMode"><option value="pending">暂未取得发票，付款后补</option><option value="has">已有发票</option></select></div>
                  <template v-if="invoiceMode === 'pending'">
                    <div class="f"><label>预计取票日期<b>*</b></label><input v-model="form.expected_invoice_date" type="date" /><div class="h">到期前 3 天提醒，逾期每天提醒</div></div>
                    <div class="f s2"><label>暂无发票原因<b>*</b></label><input v-model="form.no_invoice_reason" /></div>
                  </template>
                  <div v-else class="f s2"><label>发票差异说明</label><input v-model="form.invoice_difference_note" placeholder="发票合计与付款金额相差超过 0.02 元时必填" /></div>
                </div>
                <div v-if="invoiceMode === 'has'" class="tbl" style="margin-top:10px">
                  <table>
                    <thead><tr><th style="width:36px"></th><th>发票号码</th><th>项目名称</th><th>开票日期</th><th class="r">合计</th></tr></thead>
                    <tbody>
                      <tr v-for="invoice in availableInvoices" :key="invoice.name">
                        <td><input type="checkbox" :checked="pickedInvoices.some((item) => item.name === invoice.name)" @change="togglePicked(invoice)" /></td>
                        <td class="num">{{ invoice.invoice_number }}</td><td>{{ invoice.project_name }}</td><td class="num">{{ invoice.issue_date }}</td><td class="r num">{{ money(invoice.total_amount) }}</td>
                      </tr>
                      <tr v-if="!availableInvoices.length"><td colspan="5" class="empty">发票夹里没有可用的发票</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </template>
          </template>

          <!-- 第 2 步 -->
          <template v-if="step === 2">
            <div v-if="lockedSource && application" class="lock">
              <span class="k">关联申请 · 已锁定</span>
              <span class="num" style="font-weight:600">{{ application.name }}</span>
              <span>{{ application.request_type }}<template v-if="application.subject"> · {{ application.subject }}</template></span>
              <template v-if="quota?.capped"><span class="bar"><i :style="{ width: quota.pct + '%' }"></i></span><span>剩余 <b class="num">{{ money(application.available_amount) }}</b></span></template>
              <span v-else-if="quota" class="muted">{{ quota.text }}</span>
              <span class="muted" style="margin-left:auto">从申请下推，不能更换</span>
            </div>
            <div v-else class="panel">
              <div class="pt">关联申请</div>
              <div class="form">
                <div class="f">
                  <label>选择申请<b>*</b></label>
                  <select v-model="form.source_request">
                    <option value="">请选择</option>
                    <option v-for="item in applications" :key="item.name" :value="item.name">{{ applicationLabel(item) }}</option>
                  </select>
                  <div class="h">只列出你自己已通过的购买申请或出差申请</div>
                </div>
                <div class="f">
                  <label>额度</label>
                  <div v-if="quota?.capped" style="display:flex;gap:8px;align-items:center;padding-top:6px">
                    <span class="bar"><i :style="{ width: quota.pct + '%' }"></i></span><span class="muted">{{ quota.text }}</span>
                  </div>
                  <div v-else-if="quota" class="muted" style="padding-top:8px">{{ quota.text }}</div>
                  <div v-else class="muted" style="padding-top:8px">{{ applications.length ? '先选择一张申请' : '你还没有已通过的购买申请或出差申请' }}</div>
                </div>
              </div>
            </div>

            <div class="panel">
              <div class="pt">单据信息</div>
              <div class="form">
                <div class="f"><label>付款单位<b>*</b></label><select disabled><option>{{ defaults.companies?.[0] || '示例企业032有限公司' }}</option></select></div>
                <div class="f"><label>主题<b>*</b></label><input v-model="form.subject" :placeholder="isClaim ? '如：北京出差住宿费' : '如：设备尾款'" /></div>
                <div class="f"><label>紧急程度</label><select v-model="form.urgency"><option v-for="item in defaults.urgencies" :key="item">{{ item }}</option></select></div>
                <div class="f"><label>单据类型<b>*</b></label><select v-model="form.doc_type"><option>非固定资产</option><option>固定资产</option></select></div>
                <div v-if="form.doc_type === '固定资产'" class="f">
                  <label>资产类别<b>*</b></label>
                  <select v-model="form.asset_category"><option v-for="item in defaults.asset_categories" :key="item">{{ item }}</option></select>
                  <div class="h">决定是否有"资产审批"这一步</div>
                </div>
                <div class="f"><label>付款方式</label><select v-model="form.payment_method"><option v-for="item in defaults.payment_methods" :key="item">{{ item }}</option></select></div>
                <div class="f s2"><label>申请说明</label><textarea v-model="form.reason"></textarea></div>
              </div>
            </div>

            <div class="panel">
              <div class="pt">收款信息</div>
              <div v-if="isClaim" class="form">
                <div class="f"><label>收款人</label><input :value="defaults.payee?.payee_name" readonly /><div class="h">报销固定付给本人</div></div>
                <div class="f"><label>开户银行</label><input :value="defaults.payee?.bank_name || '（员工档案未填写）'" readonly /></div>
                <div class="f"><label>账号</label><input :value="maskAccount(defaults.payee?.account_no) || '（员工档案未填写）'" readonly /><div class="h">取自员工信息，修改请联系人事</div></div>
              </div>
              <div v-else class="form">
                <div class="f"><label>收款单位<b>*</b></label><input v-model="form.payee_name" /></div>
                <div class="f"><label>开户银行<b>*</b></label><input v-model="form.bank_name" /></div>
                <div class="f"><label>支行</label><input v-model="form.branch" /></div>
                <div class="f"><label>账号<b>*</b></label><input v-model="form.account_no" /></div>
              </div>
            </div>
          </template>

          <!-- 第 3 步 -->
          <div v-if="step === 3" class="panel">
            <div class="pt">确认后提交</div>
            <div class="review">
              <span>主题</span><b>{{ form.subject || '（未填写）' }}</b>
              <span>关联申请</span><b>{{ application ? applicationLabel(application) : '（未选择）' }}</b>
              <span>{{ isClaim ? '发票' : '付款明细' }}</span><b>{{ isClaim ? `${pickedInvoices.length} 张` : `${manualLines.length} 行` }} · 合计 ¥ {{ money(draftTotal) }}</b>
              <template v-if="!isClaim"><span>发票</span><b>{{ invoiceMode === 'has' ? `已有 ${pickedInvoices.length} 张` : `付款后补，预计 ${form.expected_invoice_date || '（未填）'}` }}</b></template>
              <span>单据类型</span><b>{{ form.doc_type }}<template v-if="form.doc_type === '固定资产'"> · {{ form.asset_category }}</template></b>
              <span>收款</span><b>{{ isClaim ? `${defaults.payee?.payee_name || '本人'} · ${maskAccount(defaults.payee?.account_no) || '账户未填写'}` : `${form.payee_name || '（未填写）'} · ${maskAccount(form.account_no) || '账号未填写'}` }}</b>
              <span>紧急程度</span><b>{{ form.urgency }}</b>
            </div>
            <div v-if="blockers.length" class="err" role="alert">还不能提交：{{ blockers.join('；') }}</div>
            <div v-else class="ok-box">检查通过，提交后按审批规则自动流转。</div>
          </div>

          <div class="actions">
            <button v-if="step > 1" type="button" class="btn" @click="step -= 1">上一步</button>
            <button type="button" class="btn" :disabled="busy" @click="save()">保存草稿</button>
            <button type="button" class="btn" :disabled="busy" @click="go({})">取消</button>
            <span class="grow-col"></span>
            <button v-if="step < 3" type="button" class="btn pri lg" @click="nextStep">下一步</button>
            <button v-else type="button" class="btn pri lg" :disabled="busy || blockers.length > 0" @click="save({ submit: true })">提交审批</button>
          </div>
        </div>

        <aside class="panel summary">
          <span class="muted">本次{{ config.label }}金额</span>
          <b class="big">¥ {{ money(draftTotal) }}</b>
          <span class="muted">{{ isClaim ? `${pickedInvoices.length} 张发票` : `${manualLines.length} 行明细` }}</span>
          <div v-if="isClaim && pickedInvoices.length" class="summary-lines">
            <div v-for="invoice in pickedInvoices" :key="invoice.name"><span class="ellipsis">{{ invoice.project_name || invoice.invoice_number }}</span><span>¥ {{ money(invoice.total_amount) }}</span></div>
          </div>
          <div class="summary-block">
            <span class="muted">关联申请</span>
            <span>{{ application ? application.name : '未选择' }}</span>
            <span v-if="quota" class="muted">{{ quota.text }}</span>
          </div>
          <div v-if="blockers.length" class="summary-block">
            <span class="muted">还差</span>
            <span v-for="item in blockers" :key="item" class="todo-item">{{ item }}</span>
          </div>
        </aside>
      </div>
    </template>
  </div>
</template>
