<script setup>
// 报销单（付给员工）与付款单（付给外部单位）共用的工作台：同一套列表、表单和审批操作，
// 差别只在明细来源（发票 / 手工）和补票。页面按 kind 区分，路由和菜单是分开的两项。
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  CLAIM_KINDS, accountBlockers, applicationLabel, callApi, claimDraftPayload, claimTabs,
  money, statusTone, submitBlockers, sumAmount,
} from '../../lib/expenseClaims.js';

const props = defineProps({ kind: { type: String, required: true } });
const config = computed(() => CLAIM_KINDS[props.kind]);
const route = useRoute();
const router = useRouter();

const tab = ref('mine');
const rows = ref([]);
const selected = ref(null);
const applications = ref([]);
const availableInvoices = ref([]);
const accountOptions = ref([]);
const loading = ref(false);
const busy = ref(false);
const errorMessage = ref('');
const message = ref('');
const editorOpen = ref(false);
const editingName = ref('');
const pickedInvoices = ref([]);
const lineProjects = reactive({});
const manualLines = ref([]);
const projects = ref([]);
const accountDraft = reactive({});
const supplementPicked = ref([]);
const supplementNote = ref('');

const form = reactive({
  source_request: '', subject: '', reason: '', urgency: '一般', doc_type: '非固定资产',
  asset_category: '其他', payment_method: '银行转账', payee_name: '', bank_name: '', branch: '',
  account_no: '', expected_invoice_date: '', no_invoice_reason: '', invoice_difference_note: '',
});

const application = computed(() => applications.value.find((item) => item.name === form.source_request) || null);
const draftTotal = computed(() => (props.kind === 'claim' ? sumAmount(pickedInvoices.value) : sumAmount(manualLines.value)));
const blockers = computed(() => submitBlockers(props.kind, form, {
  invoices: pickedInvoices.value, lines: manualLines.value, application: application.value,
}));
const detailLines = computed(() => selected.value?.expense_lines || []);
const cashierLines = computed(() => (selected.value?.can_edit_expense_items ? detailLines.value : []));

function fail(error) {
  errorMessage.value = String(error?.message || error || '操作失败');
}

async function run(action, { reload = true, keepSelection = true } = {}) {
  busy.value = true;
  errorMessage.value = '';
  message.value = '';
  try {
    const result = await action();
    if (reload) await loadRows(keepSelection ? (selected.value?.name || '') : '');
    return result;
  } catch (error) {
    fail(error);
    return null;
  } finally {
    busy.value = false;
  }
}

async function loadRows(selectName = '') {
  loading.value = true;
  try {
    rows.value = await callApi('oa_entry.list_requests', { view: tab.value, request_type: config.value.requestType, limit: 100 }, { method: 'GET' }) || [];
    const wanted = selectName || selected.value?.name || String(route.query.request || '');
    selected.value = wanted ? await loadOne(wanted) : null;
  } catch (error) {
    fail(error);
  } finally {
    loading.value = false;
  }
}

async function loadOne(name) {
  const found = await callApi('oa_entry.list_requests', { view: 'all', name, limit: 1 }, { method: 'GET' });
  return (found || [])[0] || null;
}

async function loadLookups() {
  try {
    const [apps, invoices, options, projectRows] = await Promise.all([
      callApi('expense_claim_entry.list_linkable_applications', { request_type: config.value.requestType }, { method: 'GET' }),
      callApi('expense_claim_entry.list_available_invoices', { request_type: config.value.requestType }, { method: 'GET' }),
      callApi('oa_entry.get_options', {}, { method: 'GET' }),
      callApi('oa_entry.list_approval_center_projects', {}, { method: 'GET' }),
    ]);
    applications.value = apps || [];
    availableInvoices.value = invoices || [];
    accountOptions.value = options?.expense_account_tree || [];
    projects.value = (projectRows || []).map((row) => row.name || row);
  } catch (error) {
    fail(error);
  }
}

function resetForm() {
  Object.assign(form, {
    source_request: '', subject: '', reason: '', urgency: '一般', doc_type: '非固定资产',
    asset_category: '其他', payment_method: '银行转账', payee_name: '', bank_name: '', branch: '',
    account_no: '', expected_invoice_date: '', no_invoice_reason: '', invoice_difference_note: '',
  });
  pickedInvoices.value = [];
  manualLines.value = [];
  Object.keys(lineProjects).forEach((key) => delete lineProjects[key]);
  editingName.value = '';
}

async function openNew(sourceRequest = '') {
  resetForm();
  await loadLookups();
  form.source_request = sourceRequest || '';
  editorOpen.value = true;
}

async function openDraft(row) {
  await loadLookups();
  const doc = await loadOne(row.name);
  if (!doc) return;
  resetForm();
  editingName.value = doc.name;
  Object.assign(form, {
    source_request: doc.source_request || '', subject: doc.subject || '', reason: doc.reason || '',
    urgency: doc.urgency || '一般', doc_type: doc.doc_type || '非固定资产', asset_category: doc.asset_category || '其他',
    payment_method: doc.payment_method || '银行转账', payee_name: doc.payee_name || '', bank_name: doc.bank_name || '',
    branch: doc.branch || '', account_no: doc.account_no || '', expected_invoice_date: doc.expected_invoice_date || '',
    no_invoice_reason: doc.no_invoice_reason || '', invoice_difference_note: doc.invoice_difference_note || '',
  });
  const linked = (doc.expense_lines || []).filter((line) => line.source_invoice);
  if (props.kind === 'claim') {
    pickedInvoices.value = linked.map((line) => ({
      name: line.source_invoice, project_name: line.project_name, issue_date: line.issue_date,
      invoice_number: line.invoice_number, total_amount: line.total_amount, expense_description: line.expense_description,
    }));
    Object.entries(doc.claim_line_projects || {}).forEach(([lineKey, project]) => {
      const line = (doc.expense_lines || []).find((item) => item.line_key === lineKey);
      if (line?.source_invoice) lineProjects[line.source_invoice] = project;
    });
  } else {
    manualLines.value = (doc.expense_lines || []).filter((line) => !line.source_invoice).map((line) => ({
      line_key: line.line_key, project_name: line.project_name, claim_project: (doc.claim_line_projects || {})[line.line_key] || '',
      issue_date: line.issue_date, total_amount: line.total_amount, expense_description: line.expense_description,
    }));
    pickedInvoices.value = linked.map((line) => ({ name: line.source_invoice, total_amount: line.total_amount }));
  }
  editorOpen.value = true;
}

function togglePicked(invoice) {
  const index = pickedInvoices.value.findIndex((item) => item.name === invoice.name);
  if (index >= 0) pickedInvoices.value.splice(index, 1);
  else pickedInvoices.value.push(invoice);
}

function addLine() {
  manualLines.value.push({ line_key: '', project_name: '', claim_project: '', issue_date: '', total_amount: '', expense_description: '' });
}

async function saveDraft({ thenSubmit = false } = {}) {
  const payload = claimDraftPayload(props.kind, form, { invoices: pickedInvoices.value, projects: lineProjects, lines: manualLines.value });
  const saved = await run(async () => {
    const doc = await callApi('expense_claim_entry.save_claim_draft', {
      request_type: config.value.requestType, payload: JSON.stringify(payload), name: editingName.value || undefined,
    });
    editingName.value = doc.name;
    if (thenSubmit) await callApi('oa_entry.submit_request', { name: doc.name });
    return doc;
  }, { keepSelection: false });
  if (saved) {
    message.value = thenSubmit ? `${config.value.label}单 ${saved.name} 已提交` : `草稿 ${saved.name} 已保存`;
    if (thenSubmit) {
      editorOpen.value = false;
      resetForm();
    }
    await loadRows(saved.name);
    await loadLookups();
  }
}

async function select(row) {
  selected.value = await loadOne(row.name);
  Object.keys(accountDraft).forEach((key) => delete accountDraft[key]);
  (selected.value?.expense_lines || []).forEach((line) => {
    accountDraft[line.line_key] = {
      expense_account_level_1: line.expense_account_level_1 || '',
      expense_account_level_2: line.expense_account_level_2 || '',
    };
  });
  supplementPicked.value = [];
  supplementNote.value = '';
  router.replace({ path: route.path, query: { ...route.query, request: row.name } });
}

async function act(action) {
  const note = action === 'reject' ? (window.prompt('请填写驳回原因') || '').trim() : '';
  if (action === 'reject' && !note) return;
  await run(() => callApi('oa_entry.action_request', { name: selected.value.name, action, note, reject_target: action === 'reject' ? 'applicant' : undefined }));
  message.value = action === 'reject' ? '已驳回给申请人' : '已处理';
}

async function withdraw() {
  const note = (window.prompt('请填写撤回原因（可选）') || '').trim();
  await run(() => callApi('oa_entry.withdraw_request', { name: selected.value.name, note }));
  message.value = '已撤回，单据回到草稿';
}

async function saveAccounts() {
  const lines = Object.entries(accountDraft).map(([line_key, value]) => ({ line_key, ...value }));
  const problems = accountBlockers(lines);
  if (problems.length) {
    errorMessage.value = problems[0];
    return;
  }
  await run(() => callApi('expense_claim_entry.save_claim_accounts', { name: selected.value.name, lines: JSON.stringify(lines) }));
  message.value = '费用科目已保存';
}

async function supplement() {
  if (!supplementPicked.value.length) {
    errorMessage.value = '请选择要补录的发票';
    return;
  }
  await run(() => callApi('expense_claim_entry.supplement_payment_invoices', {
    name: selected.value.name, invoice_names: JSON.stringify(supplementPicked.value), difference_note: supplementNote.value,
  }));
  message.value = '发票已补录，等待财务核验';
  await loadLookups();
}

async function verifyInvoices() {
  await run(() => callApi('expense_claim_entry.verify_claim_invoices', { name: selected.value.name }));
  message.value = '发票已核验，单据完结';
}

async function returnInvoices() {
  const note = (window.prompt('请填写退回原因') || '').trim();
  if (!note) return;
  await run(() => callApi('expense_claim_entry.return_claim_invoices', { name: selected.value.name, note }));
  message.value = '已退回给申请人重新补票';
  await loadLookups();
}

async function withdrawPayment() {
  const note = (window.prompt('请填写撤回付款原因') || '').trim();
  await run(() => callApi('expense_claim_entry.withdraw_claim_payment', { name: selected.value.name, note }));
  message.value = '付款已撤回，单据回到出纳确认付款';
}

const levelTwoOptions = (levelOne) => (accountOptions.value.find((item) => item.level_1 === levelOne)?.level_2) || [];

watch(tab, () => loadRows(''));
onMounted(async () => {
  await loadRows();
  await loadLookups();
  if (route.query.source) openNew(String(route.query.source));
});
</script>

<template>
  <div class="space-y-4">
    <section class="rounded-lg border bg-white p-5 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold">{{ config.label }}</h1>
          <p class="mt-1 text-sm text-gray-500">{{ config.hint }}每张单据必须挂在本人一张已通过的申请下。</p>
        </div>
        <button type="button" class="rounded bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50" :disabled="busy" @click="openNew()">
          新建{{ config.label }}单
        </button>
      </div>
      <div class="mt-4 flex gap-2">
        <button
          v-for="item in claimTabs(props.kind)" :key="item.key" type="button"
          class="rounded px-3 py-1.5 text-sm" :class="tab === item.key ? 'bg-gray-900 text-white' : 'border'"
          @click="tab = item.key"
        >{{ item.label }}</button>
      </div>
      <p v-if="errorMessage" class="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{{ errorMessage }}</p>
      <p v-if="message" class="mt-3 rounded bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{{ message }}</p>
    </section>

    <section v-if="editorOpen" class="rounded-lg border bg-white p-5 shadow-sm">
      <div class="flex items-center justify-between">
        <h2 class="font-semibold">{{ editingName ? `编辑草稿 ${editingName}` : `新建${config.label}单` }}</h2>
        <button type="button" class="text-sm text-gray-500 underline" @click="editorOpen = false">关闭</button>
      </div>
      <div class="mt-4 grid gap-3 md:grid-cols-2">
        <label class="text-sm">关联申请
          <select v-model="form.source_request" class="mt-1 w-full rounded border px-2 py-1.5">
            <option value="">请选择本人已通过的申请</option>
            <option v-for="item in applications" :key="item.name" :value="item.name">{{ applicationLabel(item) }}</option>
          </select>
        </label>
        <label class="text-sm">主题<input v-model="form.subject" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
        <label class="text-sm">紧急程度
          <select v-model="form.urgency" class="mt-1 w-full rounded border px-2 py-1.5"><option>一般</option><option>加急</option></select>
        </label>
        <label class="text-sm">付款方式
          <select v-model="form.payment_method" class="mt-1 w-full rounded border px-2 py-1.5"><option>银行转账</option><option>现金支付</option></select>
        </label>
        <label class="text-sm md:col-span-2">申请说明<textarea v-model="form.reason" rows="2" class="mt-1 w-full rounded border px-2 py-1.5"></textarea></label>
        <template v-if="props.kind === 'payment'">
          <label class="text-sm">收款单位<input v-model="form.payee_name" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
          <label class="text-sm">开户行<input v-model="form.bank_name" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
          <label class="text-sm">开户支行<input v-model="form.branch" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
          <label class="text-sm">银行账号<input v-model="form.account_no" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
        </template>
      </div>

      <template v-if="props.kind === 'claim'">
        <h3 class="mt-5 font-medium">选择发票（发票夹里"可用"的发票）</h3>
        <p v-if="!availableInvoices.length" class="mt-2 text-sm text-gray-500">发票夹里没有可用发票，请先到发票夹上传并确认。</p>
        <table v-else class="mt-2 min-w-full text-sm">
          <thead><tr class="border-b text-left text-gray-500"><th class="p-2">选择</th><th class="p-2">项目名称</th><th class="p-2">开票日期</th><th class="p-2">发票号码</th><th class="p-2 text-right">合计</th><th class="p-2">费用说明</th><th class="p-2">所属项目</th></tr></thead>
          <tbody>
            <tr v-for="invoice in availableInvoices" :key="invoice.name" class="border-b">
              <td class="p-2"><input type="checkbox" :checked="pickedInvoices.some((item) => item.name === invoice.name)" @change="togglePicked(invoice)" /></td>
              <td class="p-2">{{ invoice.project_name }}</td>
              <td class="p-2">{{ invoice.issue_date }}</td>
              <td class="p-2">{{ invoice.invoice_number }}</td>
              <td class="p-2 text-right">{{ money(invoice.total_amount) }}</td>
              <td class="p-2">{{ invoice.expense_description }}</td>
              <td class="p-2">
                <select v-model="lineProjects[invoice.name]" class="w-40 rounded border px-2 py-1">
                  <option value="">非项目</option>
                  <option v-for="project in projects" :key="project" :value="project">{{ project }}</option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
      </template>

      <template v-else>
        <div class="mt-5 flex items-center justify-between">
          <h3 class="font-medium">付款明细</h3>
          <button type="button" class="rounded border px-2 py-1 text-sm" @click="addLine">添加一行</button>
        </div>
        <table class="mt-2 min-w-full text-sm">
          <thead><tr class="border-b text-left text-gray-500"><th class="p-2">付款内容</th><th class="p-2">日期</th><th class="p-2 text-right">金额</th><th class="p-2">费用说明</th><th class="p-2">所属项目</th><th class="p-2"></th></tr></thead>
          <tbody>
            <tr v-for="(line, index) in manualLines" :key="index" class="border-b">
              <td class="p-2"><input v-model="line.project_name" class="w-full rounded border px-2 py-1" /></td>
              <td class="p-2"><input v-model="line.issue_date" type="date" class="rounded border px-2 py-1" /></td>
              <td class="p-2"><input v-model="line.total_amount" type="number" step="0.01" class="w-28 rounded border px-2 py-1 text-right" /></td>
              <td class="p-2"><input v-model="line.expense_description" class="w-full rounded border px-2 py-1" /></td>
              <td class="p-2">
                <select v-model="line.claim_project" class="w-36 rounded border px-2 py-1">
                  <option value="">非项目</option>
                  <option v-for="project in projects" :key="project" :value="project">{{ project }}</option>
                </select>
              </td>
              <td class="p-2"><button type="button" class="text-sm text-red-600" @click="manualLines.splice(index, 1)">删除</button></td>
            </tr>
          </tbody>
        </table>
        <h3 class="mt-5 font-medium">发票（可先付款后补票）</h3>
        <div class="mt-2 space-y-1 text-sm">
          <label v-for="invoice in availableInvoices" :key="invoice.name" class="flex items-center gap-2">
            <input type="checkbox" :checked="pickedInvoices.some((item) => item.name === invoice.name)" @change="togglePicked(invoice)" />
            <span>{{ invoice.invoice_number }} · {{ invoice.project_name }} · {{ money(invoice.total_amount) }}</span>
          </label>
        </div>
        <div class="mt-3 grid gap-3 md:grid-cols-3">
          <label class="text-sm">预计取票日期<input v-model="form.expected_invoice_date" type="date" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
          <label class="text-sm">无票原因<input v-model="form.no_invoice_reason" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
          <label class="text-sm">发票差异说明<input v-model="form.invoice_difference_note" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
        </div>
      </template>

      <div class="mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-3">
        <div class="text-sm">
          合计 <span class="text-lg font-semibold">{{ money(draftTotal) }}</span> 元
          <span v-if="application && application.request_type === '购买申请'" class="ml-2 text-gray-500">关联申请剩余 {{ money(application.available_amount) }} 元</span>
        </div>
        <div class="flex gap-2">
          <button type="button" class="rounded border px-3 py-1.5 text-sm disabled:opacity-50" :disabled="busy" @click="saveDraft()">保存草稿</button>
          <button type="button" class="rounded bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50" :disabled="busy || blockers.length" @click="saveDraft({ thenSubmit: true })">提交</button>
        </div>
      </div>
      <ul v-if="blockers.length" class="mt-2 list-disc pl-5 text-sm text-amber-700"><li v-for="item in blockers" :key="item">{{ item }}</li></ul>
    </section>

    <section class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <div class="rounded-lg border bg-white p-4 shadow-sm">
        <p v-if="loading" class="py-8 text-center text-sm text-gray-500">正在加载…</p>
        <table v-else class="min-w-full text-sm">
          <thead><tr class="border-b text-left text-gray-500"><th class="p-2">单号</th><th class="p-2">主题</th><th class="p-2 text-right">金额</th><th class="p-2">状态</th></tr></thead>
          <tbody>
            <tr v-for="row in rows" :key="row.name" class="cursor-pointer border-b hover:bg-gray-50" :class="{ 'bg-gray-50': selected?.name === row.name }" @click="select(row)">
              <td class="p-2 font-medium text-blue-700">{{ row.name }}</td>
              <td class="p-2">{{ row.subject }}</td>
              <td class="p-2 text-right">{{ money(row.amount) }}</td>
              <td class="p-2">
                <span class="rounded px-2 py-0.5 text-xs" :class="statusTone(row.business_status || row.workflow_status)">{{ row.business_status || row.workflow_status }}</span>
                <span v-if="row.invoice_due_state" class="ml-1 rounded bg-orange-50 px-2 py-0.5 text-xs text-orange-700">{{ row.invoice_due_state }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="!loading && !rows.length" class="py-10 text-center text-gray-400">暂无单据。</p>
      </div>

      <div v-if="selected" class="rounded-lg border bg-white p-5 shadow-sm">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 class="font-semibold">{{ selected.name }} · {{ selected.subject }}</h2>
            <p class="mt-1 text-sm text-gray-500">
              关联申请 {{ selected.source_request || '-' }}
              <span v-if="selected.source_locked" class="ml-1 rounded bg-gray-100 px-2 py-0.5 text-xs">下推锁定</span>
              · 金额 {{ money(selected.amount) }} 元 · 当前节点 {{ selected.current_step_label || '-' }}
            </p>
          </div>
          <span class="rounded px-2 py-0.5 text-xs" :class="statusTone(selected.business_status || selected.workflow_status)">{{ selected.business_status || selected.workflow_status }}</span>
        </div>

        <table class="mt-4 min-w-full text-sm">
          <thead><tr class="border-b text-left text-gray-500"><th class="p-2">内容</th><th class="p-2">日期</th><th class="p-2 text-right">金额</th><th class="p-2">费用科目</th><th class="p-2">说明</th></tr></thead>
          <tbody>
            <tr v-for="line in detailLines" :key="line.line_key" class="border-b">
              <td class="p-2">{{ line.project_name || line.invoice_category }}</td>
              <td class="p-2">{{ line.issue_date }}</td>
              <td class="p-2 text-right">{{ money(line.total_amount) }}</td>
              <td class="p-2">
                <template v-if="cashierLines.length && accountDraft[line.line_key]">
                  <select v-model="accountDraft[line.line_key].expense_account_level_1" class="rounded border px-1 py-0.5 text-xs">
                    <option value="">一级科目</option>
                    <option v-for="option in accountOptions" :key="option.level_1" :value="option.level_1">{{ option.level_1 }}</option>
                  </select>
                  <select v-model="accountDraft[line.line_key].expense_account_level_2" class="ml-1 rounded border px-1 py-0.5 text-xs">
                    <option value="">二级科目</option>
                    <option v-for="option in levelTwoOptions(accountDraft[line.line_key].expense_account_level_1)" :key="option" :value="option">{{ option }}</option>
                  </select>
                </template>
                <span v-else>{{ line.expense_item || '-' }}</span>
              </td>
              <td class="p-2">{{ line.expense_description }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="cashierLines.length" class="mt-2">
          <button type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="saveAccounts">保存费用科目</button>
        </div>

        <div v-if="selected.can_supplement_claim_invoices" class="mt-5 rounded border border-orange-200 bg-orange-50 p-3">
          <h3 class="text-sm font-medium text-orange-800">补录发票 {{ selected.invoice_due_state ? `（${selected.invoice_due_state}）` : '' }}</h3>
          <label v-for="invoice in availableInvoices" :key="invoice.name" class="mt-1 flex items-center gap-2 text-sm">
            <input type="checkbox" :value="invoice.name" v-model="supplementPicked" />
            <span>{{ invoice.invoice_number }} · {{ money(invoice.total_amount) }} · {{ invoice.expense_description }}</span>
          </label>
          <input v-model="supplementNote" placeholder="与付款金额相差超过 0.02 元时填写差异说明" class="mt-2 w-full rounded border px-2 py-1 text-sm" />
          <button type="button" class="mt-2 rounded bg-orange-600 px-3 py-1.5 text-sm text-white" :disabled="busy" @click="supplement">提交补录</button>
        </div>

        <ol class="mt-5 space-y-1 text-sm">
          <li v-for="step in selected.steps || []" :key="step.step_index" class="flex justify-between border-b py-1">
            <span>{{ step.step_index }}. {{ step.label }}</span>
            <span class="text-gray-500">{{ step.status }}<span v-if="step.action_by"> · {{ step.action_by }}</span></span>
          </li>
        </ol>

        <div class="mt-4 flex flex-wrap gap-2 border-t pt-3">
          <button v-if="selected.workflow_status === '草稿'" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="openDraft(selected)">编辑草稿</button>
          <button v-if="selected.can_approve" type="button" class="rounded bg-gray-900 px-3 py-1.5 text-sm text-white" :disabled="busy" @click="act('approve')">
            {{ selected.current_step_mode === 'handle' ? '确认付款' : '同意' }}
          </button>
          <button v-if="selected.can_reject" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="act('reject')">驳回</button>
          <button v-if="selected.can_withdraw" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="withdraw">撤回</button>
          <button v-if="selected.can_verify_claim_invoices" type="button" class="rounded bg-blue-600 px-3 py-1.5 text-sm text-white" :disabled="busy" @click="verifyInvoices">核验发票</button>
          <button v-if="selected.can_verify_claim_invoices" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="returnInvoices">退回补票</button>
          <button v-if="selected.can_withdraw_claim_payment" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="withdrawPayment">撤回付款</button>
        </div>
        <p v-if="selected.invoice_difference_note" class="mt-2 text-xs text-gray-500">发票差异说明：{{ selected.invoice_difference_note }}</p>
      </div>
      <div v-else class="rounded-lg border bg-white p-10 text-center text-sm text-gray-400 shadow-sm">在左侧选择一张单据查看明细。</div>
    </section>
  </div>
</template>
