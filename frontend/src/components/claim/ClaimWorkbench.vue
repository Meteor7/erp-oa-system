<script setup>
// 报销单（付给员工）与付款单（付给外部单位）共用的工作台，版式按已确认的设计稿第 5 版：
// 员工看"我的 / 新建"，财务看"待我处理 / 全部"；审批人从待办或通知带 ?request= 打开单据。
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../../styles/expenseUi.css';
import {
  CLAIM_KINDS, accountBlockers, accountDraftFor, applicationLabel, callApi, claimDraftPayload, claimTabs,
  displayStatus, isFinanceUser, maskAccount, money, pillClass, quotaOf, sourceTypeLabel, stepChips,
  submitBlockers, sumAmount, withDefaultProjects,
} from '../../lib/expenseClaims.js';

const props = defineProps({ kind: { type: String, required: true } });
const config = computed(() => CLAIM_KINDS[props.kind]);
const isClaim = computed(() => props.kind === 'claim');
const route = useRoute();
const router = useRouter();
const finance = isFinanceUser();

const tab = ref(finance ? 'todo' : 'list');
const docs = ref([]);
const counts = reactive({ todo: undefined, all: undefined, list: undefined });
const focusDoc = ref(null);
const loading = ref(false);
const busy = ref(false);
const banner = reactive({ ok: '', err: '' });
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
}
resetForm();

const application = computed(() => applications.value.find((item) => item.name === form.source_request) || null);
const quota = computed(() => quotaOf(application.value));
const formInvoices = computed(() => (isClaim.value || invoiceMode.value === 'has' ? pickedInvoices.value : []));
const draftTotal = computed(() => (isClaim.value ? sumAmount(pickedInvoices.value) : sumAmount(manualLines.value)));
const blockers = computed(() => submitBlockers(props.kind, form, {
  invoices: formInvoices.value, lines: manualLines.value, application: application.value,
}));
const tabs = computed(() => claimTabs(props.kind, finance, counts));
const visibleDocs = computed(() => {
  const list = [...docs.value];
  if (focusDoc.value && !list.some((doc) => doc.name === focusDoc.value.name)) list.unshift(focusDoc.value);
  return list;
});

// ---------------------------------------------------------------- loading
function flash(ok = '', err = '') {
  banner.ok = ok;
  banner.err = err;
}

async function run(action, okText) {
  busy.value = true;
  flash();
  try {
    const result = await action();
    if (okText) flash(typeof okText === 'function' ? okText(result) : okText);
    await loadDocs();
    return result;
  } catch (error) {
    flash('', String(error?.message || error || '操作失败'));
    return null;
  } finally {
    busy.value = false;
  }
}

const listFor = (view, extra = {}) => callApi('oa_entry.list_requests', { view, request_type: config.value.requestType, limit: 50, ...extra }, { method: 'GET' });

async function loadDocs() {
  loading.value = true;
  try {
    if (finance) {
      // 待核验的付款单单独取，不受"全部"只取最近 50 张的限制；财务自己也报销、付款，所以也取"我的"。
      const [pending, all, verify, mine] = await Promise.all([
        listFor('pending'),
        listFor('all'),
        isClaim.value ? [] : callApi('expense_claim_entry.list_verify_queue', {}, { method: 'GET' }),
        listFor('mine'),
      ]);
      const todo = [...(pending || []), ...(verify || []).filter((doc) => !(pending || []).some((row) => row.name === doc.name))];
      counts.todo = todo.length;
      counts.all = (all || []).length;
      counts.list = (mine || []).length;
      docs.value = tab.value === 'todo' ? todo : tab.value === 'list' ? (mine || []) : (all || []);
    } else {
      const mine = await listFor('mine');
      counts.list = (mine || []).length;
      docs.value = mine || [];
    }
    const focus = String(route.query.request || '');
    focusDoc.value = focus ? ((await listFor('all', { name: focus, limit: 1 })) || [])[0] || null : null;
    for (const doc of [...docs.value, ...(focusDoc.value ? [focusDoc.value] : [])]) {
      if (doc.can_edit_expense_items) accountDrafts[doc.name] = accountDraftFor(doc.expense_lines);
    }
    // 修复（2026-09-23）：出纳在列表里直接选科目，科目表原来只在打开表单时才加载，
    // 下拉框只有"请选择"，单据卡在出纳审核。有待填科目的单据时就取科目表。
    const shown = [...docs.value, ...(focusDoc.value ? [focusDoc.value] : [])];
    if (!accountTree.value.length && shown.some((doc) => doc.can_edit_expense_items)) {
      const options = await callApi('oa_entry.get_options', {}, { method: 'GET' });
      accountTree.value = options?.expense_account_tree || [];
    }
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

// ---------------------------------------------------------------- form actions
async function openNew() {
  resetForm();
  tab.value = 'new';
  try {
    await loadLookups();
    if (!form.source_request && applications.value.length) form.source_request = applications.value[0].name;
  } catch (error) {
    flash('', String(error?.message || error));
  }
}

async function openDraft(doc) {
  resetForm();
  tab.value = 'new';
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
      tab.value = 'list';
      flash('', `草稿的发票加载失败，请稍后再试：${String(error?.message || error)}`);
      return;
    }
    pickedInvoices.value = attached.filter((row) => row.recognition_status === '已确认');
    availableInvoices.value = [...pickedInvoices.value, ...availableInvoices.value.filter((row) => !pickedInvoices.value.some((item) => item.name === row.name))];
    invoiceMode.value = pickedInvoices.value.length ? 'has' : 'pending';
  }
}

async function pushFrom(source) {
  const draft = await run(() => callApi('expense_claim_entry.push_from_application', {
    source_request: source, request_type: config.value.requestType,
  }), `已从申请 ${source} 生成${config.value.label}单草稿，关联申请已锁定`);
  router.replace({ path: route.path, query: {} });
  if (draft) await openDraft(draft);
  else await loadDocs();
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
  const saved = await run(async () => {
    const doc = await callApi('expense_claim_entry.save_claim_draft', {
      request_type: config.value.requestType, payload: JSON.stringify(payload), name: editingName.value || undefined,
    });
    editingName.value = doc.name;
    if (submit) await callApi('oa_entry.submit_request', { name: doc.name });
    return doc;
  }, (doc) => (submit ? `${config.value.label}单 ${doc.name} 已提交审批` : `草稿 ${doc.name} 已保存`));
  if (saved && submit) {
    resetForm();
    tab.value = 'list';
    await loadDocs();
  }
}

function cancelForm() {
  resetForm();
  tab.value = finance ? 'todo' : 'list';
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
    return callApi('oa_entry.action_request', { name: doc.name, action: 'approve' });
  }, doc.current_step_mode === 'handle' ? `${doc.name} 已确认付款` : `${doc.name} 已同意`);
}

async function reject(doc) {
  const note = (window.prompt('请填写驳回原因') || '').trim();
  if (!note) return;
  await run(() => callApi('oa_entry.action_request', { name: doc.name, action: 'reject', note, reject_target: 'applicant' }), `${doc.name} 已驳回给申请人`);
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

watch(tab, (value) => {
  if (value !== 'new') loadDocs();
});
watch(() => route.query.request, () => loadDocs());

onMounted(async () => {
  if (route.query.source) {
    await pushFrom(String(route.query.source));
    return;
  }
  if (route.query.tab === 'new') {
    await openNew();
    return;
  }
  await loadDocs();
});
</script>

<template>
  <div class="xp">
    <div class="ph">
      <div>
        <h3>{{ config.label }}</h3>
        <div class="muted">{{ isClaim ? '付给员工本人；必须从发票夹选发票，明细由发票生成。' : '付给外部单位；可以先付款，付款后必须补发票。' }}</div>
      </div>
    </div>
    <div class="tabs" role="tablist">
      <button v-for="item in tabs" :key="item.key" role="tab" :aria-selected="tab === item.key"
        @click="item.key === 'new' ? openNew() : (tab = item.key)">
        {{ item.label }}<span v-if="item.count != null" class="c">{{ item.count }}</span>
      </button>
    </div>
    <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
    <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>

    <!-- ============================== 新建 / 编辑草稿 ============================== -->
    <template v-if="tab === 'new'">
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
            <div class="h">只列出你自己已通过的申请</div>
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

      <div v-if="isClaim" class="panel">
        <div class="pt"><span>选择发票（必选）</span><button type="button" class="btn sm" @click="router.push('/approval/invoice-folder')">＋ 上传新发票</button></div>
        <div class="muted" style="margin-bottom:8px">只列出发票夹里"可用"的发票。</div>
        <div class="tbl">
          <table>
            <thead><tr><th style="width:36px"></th><th>发票号码</th><th>项目名称</th><th>开票日期</th><th class="r">合计</th><th>所属项目</th><th>费用说明</th></tr></thead>
            <tbody>
              <tr v-for="invoice in availableInvoices" :key="invoice.name">
                <td><input type="checkbox" :checked="pickedInvoices.some((item) => item.name === invoice.name)" :aria-label="'选择发票 ' + invoice.invoice_number" @change="togglePicked(invoice)" /></td>
                <td class="num">{{ invoice.invoice_number }}</td>
                <td>{{ invoice.project_name }}</td>
                <td class="num">{{ invoice.issue_date }}</td>
                <td class="r num">{{ money(invoice.total_amount) }}</td>
                <td>
                  <select v-model="lineProjects[invoice.name]" class="cell" aria-label="所属项目">
                    <option value="">非项目</option>
                    <option v-for="project in projects" :key="project" :value="project">{{ project }}</option>
                  </select>
                </td>
                <td>{{ invoice.expense_description }}</td>
              </tr>
              <tr v-if="!availableInvoices.length"><td colspan="7" class="empty">发票夹里没有可用的发票，点右上角上传</td></tr>
            </tbody>
          </table>
        </div>
        <div style="text-align:right;margin-top:8px">报销金额 = 所选发票合计 <b class="num" style="font-size:16px">{{ money(draftTotal) }}</b></div>
      </div>

      <template v-else>
        <div class="panel">
          <div class="pt"><span>费用明细</span><button type="button" class="btn sm" @click="addLine">＋ 添加一行</button></div>
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
          <div style="text-align:right;margin-top:8px">付款金额 <b class="num" style="font-size:16px">{{ money(draftTotal) }}</b></div>
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

      <div v-if="blockers.length" class="err" role="alert">{{ blockers.join('；') }}</div>
      <div class="actions">
        <button type="button" class="btn pri" :disabled="busy || blockers.length > 0" @click="save({ submit: true })">提交审批</button>
        <button type="button" class="btn" :disabled="busy" @click="save()">保存草稿</button>
        <button type="button" class="btn" :disabled="busy" @click="cancelForm">取消</button>
      </div>
    </template>

    <!-- ============================== 单据卡片 ============================== -->
    <template v-else>
      <div v-if="loading" class="panel empty">正在加载…</div>
      <template v-else>
        <div v-for="doc in visibleDocs" :key="doc.name" class="panel" :class="{ focus: doc.name === focusDoc?.name }">
          <div class="pt">
            <span>
              <span class="num">{{ doc.name }}</span>
              <span :class="pillClass(displayStatus(doc))" style="margin:0 6px">{{ displayStatus(doc) }}</span>
              <span v-if="doc.invoice_due_state" class="pill p-red" style="margin-right:6px">{{ doc.invoice_due_state }}</span>
              <span class="muted">{{ doc.subject }}</span>
            </span>
            <span class="num" style="font-size:17px">¥ {{ money(doc.amount) }}</span>
          </div>
          <div class="kv">
            <div><span>申请人</span>{{ doc.employee_name }}</div>
            <div><span>关联申请</span>{{ doc.source_request || '—' }} {{ sourceTypeLabel(doc) }}</div>
            <div><span>付款单位</span>{{ doc.company }}</div>
            <div><span>单据类型</span>{{ doc.doc_type }}</div>
            <div><span>资产类别</span>{{ doc.asset_category }}</div>
            <div><span>{{ isClaim ? '收款人' : '收款单位' }}</span>{{ doc.payee_name || '—' }}</div>
            <div><span>收款账户</span>{{ [doc.bank_name, doc.branch, maskAccount(doc.account_no)].filter(Boolean).join(' ') || '—' }}</div>
            <div v-if="!isClaim && doc.expected_invoice_date && doc.invoice_followup_status === '待收票'"><span>预计取票</span>{{ doc.expected_invoice_date }}</div>
          </div>

          <h4>费用明细<template v-if="doc.can_edit_expense_items"> · 请填写科目</template></h4>
          <div class="tbl">
            <table>
              <thead>
                <tr>
                  <th>{{ isClaim ? '发票号码' : '付款内容' }}</th><th>{{ isClaim ? '项目名称' : '日期' }}</th><th>所属项目</th><th>费用说明</th>
                  <th class="r">金额</th><th>一级科目</th><th>二级科目</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="line in doc.expense_lines || []" :key="line.line_key">
                  <td :class="{ num: isClaim }">{{ isClaim ? line.invoice_number : line.project_name }}</td>
                  <td :class="{ num: !isClaim }">{{ isClaim ? line.project_name : line.issue_date }}</td>
                  <td>{{ (doc.claim_line_projects || {})[line.line_key] || '非项目' }}</td>
                  <td>{{ line.expense_description }}</td>
                  <td class="r num">{{ money(line.total_amount) }}</td>
                  <template v-if="doc.can_edit_expense_items && accountDrafts[doc.name]?.[line.line_key]">
                    <td>
                      <select v-model="accountDrafts[doc.name][line.line_key].expense_account_level_1" class="cell" aria-label="一级科目"
                        @change="accountDrafts[doc.name][line.line_key].expense_account_level_2 = ''">
                        <option value="">请选择</option>
                        <option v-for="item in accountTree" :key="item.level_1" :value="item.level_1">{{ item.level_1 }}</option>
                      </select>
                    </td>
                    <td>
                      <select v-model="accountDrafts[doc.name][line.line_key].expense_account_level_2" class="cell" aria-label="二级科目"
                        :disabled="Boolean(accountDrafts[doc.name][line.line_key].expense_account_level_1) && !levelTwo(accountDrafts[doc.name][line.line_key].expense_account_level_1).length">
                        <option value="">{{ accountDrafts[doc.name][line.line_key].expense_account_level_1 && !levelTwo(accountDrafts[doc.name][line.line_key].expense_account_level_1).length ? '无二级科目' : '请选择' }}</option>
                        <option v-for="item in levelTwo(accountDrafts[doc.name][line.line_key].expense_account_level_1)" :key="item" :value="item">{{ item }}</option>
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
            <template v-if="(doc.invoice_numbers || []).length">{{ doc.invoice_numbers.join('、') }}</template>
            <span v-else-if="doc.invoice_followup_status === '待收票'" class="pill p-sun">待补票</span>
            <template v-else>—</template>
            <template v-if="doc.invoice_difference_note"> · 差异说明：{{ doc.invoice_difference_note }}</template>
          </div>

          <h4>审批进度</h4>
          <div class="steps"><span v-for="step in stepChips(doc)" :key="step.key" :class="step.state">{{ step.label }}</span></div>

          <div v-if="supplement.doc === doc.name" class="panel" style="margin:12px 0 0;background:var(--xp-brand-bg);border-color:#FDD9A8">
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
              <button type="button" class="btn pri" :disabled="busy" @click="submitSupplement(doc)">提交补录</button>
              <button type="button" class="btn" @click="supplement.doc = ''">取消</button>
            </div>
          </div>

          <div class="actions">
            <!-- 出纳审核：科目没填完时后端 can_approve 为 false，但出纳正是要在这里填科目再同意（先保存科目再同意）。 -->
            <button v-if="doc.can_approve || doc.can_edit_expense_items" type="button" class="btn pri" :disabled="busy" @click="approve(doc)">{{ doc.current_step_mode === 'handle' ? '确认付款' : '同意' }}</button>
            <button v-if="doc.can_reject" type="button" class="btn" :disabled="busy" @click="reject(doc)">驳回</button>
            <button v-if="doc.can_verify_claim_invoices" type="button" class="btn pri" :disabled="busy" @click="verify(doc)">核验通过</button>
            <button v-if="doc.can_verify_claim_invoices" type="button" class="btn" :disabled="busy" @click="returnInvoices(doc)">退回补票</button>
            <button v-if="doc.can_supplement_claim_invoices && supplement.doc !== doc.name" type="button" class="btn pri" :disabled="busy" @click="openSupplement(doc)">补录发票</button>
            <button v-if="doc.workflow_status === '草稿' && (!finance || tab === 'list')" type="button" class="btn" :disabled="busy" @click="openDraft(doc)">继续编辑</button>
            <button v-if="doc.can_withdraw" type="button" class="btn" :disabled="busy" @click="withdraw(doc)">撤回</button>
            <button v-if="doc.can_withdraw_claim_payment" type="button" class="btn danger" :disabled="busy" @click="withdrawPayment(doc)">撤回付款</button>
          </div>
        </div>
        <div v-if="!visibleDocs.length" class="panel empty">{{ tab === 'todo' ? '没有需要处理的单据' : `还没有${config.label}单` }}</div>
      </template>
    </template>
  </div>
</template>
