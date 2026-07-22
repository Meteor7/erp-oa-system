<script setup>
import { Button, FeatherIcon, createResource } from 'frappe-ui';
import { computed, reactive, ref, watch } from 'vue';
import { getRequestInvoices, invoicesForLine, newLineKey } from '../lib/invoiceOcr.js';
import InvoicePreviewDrawer from './invoice/InvoicePreviewDrawer.vue';
import InvoiceUploadWorkbench from './invoice/InvoiceUploadWorkbench.vue';

const REQUEST_TYPE = '费用付款申请';
const ASSET_OTHER = '其它';
const NAV_ITEMS = [
  { key: 'invoices', label: '上传发票', icon: 'upload-cloud' },
  { key: 'board', label: '费用报销流', icon: 'trello' },
];
const STATUS_COLUMNS = [
  { key: 'draft', label: '待提交', icon: 'edit-3', header: 'border-gray-400 text-gray-700', accent: 'border-l-gray-400', badge: 'bg-gray-100 text-gray-700' },
  { key: 'pending', label: '审批中', icon: 'clock', header: 'border-amber-500 text-amber-700', accent: 'border-l-amber-500', badge: 'bg-amber-50 text-amber-700' },
  { key: 'approved', label: '已通过', icon: 'check-circle', header: 'border-emerald-500 text-emerald-700', accent: 'border-l-emerald-500', badge: 'bg-emerald-50 text-emerald-700' },
  { key: 'rejected', label: '已驳回', icon: 'x-circle', header: 'border-red-500 text-red-700', accent: 'border-l-red-500', badge: 'bg-red-50 text-red-700' },
  { key: 'paid', label: '已付款', icon: 'credit-card', header: 'border-blue-500 text-blue-700', accent: 'border-l-blue-500', badge: 'bg-blue-50 text-blue-700' },
];

const activeView = ref('invoices');
const detailRequestName = ref('');
const showRequestForm = ref(false);
const saving = ref(false);
const actionNote = ref('');
const message = ref('');
const errorMessage = ref('');
const detailInvoices = ref([]);
const previewInvoiceRow = ref(null);
const keyword = ref('');

const blankLine = () => ({
  line_key: newLineKey(),
  invoice_category: '',
  project_name: '',
  issue_date: '',
  invoice_number: '',
  amount_before_tax: '',
  tax_amount: '',
  total_amount: '',
  invoice_difference_reason: '',
});
const expenseLines = ref([blankLine()]);
const requestForm = reactive({
  subject: '', company: '', department: '', supervisor: '', doc_type: '', urgency: '',
  asset_category: ASSET_OTHER, payment_type: '', payment_method: '', bank_name: '',
  payee_name: '', branch: '', account_no: '', reason: '', no_invoice_reason: '',
});

const options = createResource({ url: 'rayher_hr_payroll.api.oa_entry.get_options', method: 'GET', auto: true });
const requests = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_requests', method: 'GET',
  makeParams: () => ({ view: 'all', request_type: REQUEST_TYPE, limit: 200 }), auto: true,
});
const creator = createResource({ url: 'rayher_hr_payroll.api.oa_entry.create_request' });
const actor = createResource({ url: 'rayher_hr_payroll.api.oa_entry.action_request' });
const draftSubmitter = createResource({ url: 'rayher_hr_payroll.api.oa_entry.submit_request' });
const paidMarker = createResource({ url: 'rayher_hr_payroll.api.oa_entry.mark_paid' });
const requestWithdrawer = createResource({ url: 'rayher_hr_payroll.api.oa_entry.withdraw_request' });
const paymentWithdrawer = createResource({ url: 'rayher_hr_payroll.api.oa_entry.withdraw_payment' });

const rows = computed(() => requests.data || []);
const selectedRequest = computed(() => rows.value.find((row) => row.name === detailRequestName.value) || null);
const departments = computed(() => options.data?.departments || []);
const companies = computed(() => options.data?.companies || []);
const docTypes = computed(() => options.data?.doc_types || []);
const urgencies = computed(() => options.data?.urgencies || []);
const assetCategories = computed(() => options.data?.asset_categories || [ASSET_OTHER]);
const paymentTypes = computed(() => options.data?.payment_types || []);
const paymentMethods = computed(() => options.data?.payment_methods || []);
const total = computed(() => expenseLines.value.reduce((sum, row) => sum + Number(row.total_amount || 0), 0));
const filteredRows = computed(() => {
  const value = keyword.value.trim().toLowerCase();
  if (!value) return rows.value;
  return rows.value.filter((row) => [
    row.name, row.subject, row.employee_name, row.department, row.invoice_search_text,
    ...(row.expense_lines || []).flatMap((line) => [line.invoice_category, line.project_name, line.invoice_number]),
  ].join(' ').toLowerCase().includes(value));
});
const stats = computed(() => ({
  total: rows.value.length,
  pending: rows.value.filter((row) => row.kanban_status === 'pending').length,
  approved: rows.value.filter((row) => ['approved', 'paid'].includes(row.kanban_status)).length,
  amount: rows.value.reduce((sum, row) => sum + Number(row.amount || 0), 0),
  paid: rows.value.filter((row) => row.kanban_status === 'paid').reduce((sum, row) => sum + Number(row.amount || 0), 0),
}));

function clean(value) {
  return String(value || '').replace(/<[^>]*>/g, '').trim();
}
function apiError(error, fallback) {
  const messages = error?.messages || [];
  if (messages.length) return messages.map(clean).filter(Boolean).join('；');
  return clean(error?._error_message || error?.message) || fallback;
}
function first(values, fallback = '') {
  return Array.isArray(values) && values.length ? values[0] : fallback;
}
function money(value, blank = false) {
  if (blank && (value === null || value === undefined || value === '')) return '-';
  return Number(value || 0).toLocaleString('zh-CN', { style: 'currency', currency: 'CNY', minimumFractionDigits: 2 });
}
function dateText(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-';
}
function statusMeta(status) {
  return STATUS_COLUMNS.find((column) => column.key === status) || STATUS_COLUMNS[1];
}
function rowsForStatus(status) {
  return filteredRows.value.filter((row) => row.kanban_status === status);
}
function sourceLabel(row) {
  if (row.from_invoice_push) return '发票下推';
  if (row.from_consumption) return '历史数据下推';
  return '无票/手工新建';
}
function applyDefaults() {
  const context = options.data?.context || {};
  requestForm.company ||= first(companies.value);
  requestForm.department ||= context.department || first(departments.value);
  requestForm.supervisor ||= context.supervisor || '';
  requestForm.doc_type ||= first(docTypes.value);
  requestForm.urgency ||= first(urgencies.value);
  requestForm.payment_type ||= first(paymentTypes.value);
  requestForm.payment_method ||= first(paymentMethods.value);
  requestForm.payee_name ||= context.employee_name || '';
}
function resetForm() {
  Object.assign(requestForm, {
    subject: '', company: '', department: '', supervisor: '', doc_type: '', urgency: '',
    asset_category: ASSET_OTHER, payment_type: '', payment_method: '', bank_name: '',
    payee_name: '', branch: '', account_no: '', reason: '', no_invoice_reason: '',
  });
  expenseLines.value = [blankLine()];
  applyDefaults();
}
function openManualRequest() {
  errorMessage.value = '';
  resetForm();
  showRequestForm.value = true;
}
function addLine() {
  expenseLines.value.push(blankLine());
}
function removeLine(index) {
  if (expenseLines.value.length > 1) expenseLines.value.splice(index, 1);
}
async function reload() {
  await requests.reload();
}
async function saveRequest(submit) {
  errorMessage.value = '';
  const valid = expenseLines.value.filter((line) => Number(line.total_amount || 0) > 0);
  if (!requestForm.department || valid.length !== expenseLines.value.length) {
    errorMessage.value = '请填写申请部门，并保证每行合计金额大于 0。';
    return;
  }
  if (submit && !requestForm.no_invoice_reason.trim()) {
    errorMessage.value = '无票报销提交前必须填写无票原因。';
    return;
  }
  saving.value = true;
  try {
    const result = await creator.submit({
      request_type: REQUEST_TYPE,
      subject: requestForm.subject.trim() || valid[0].project_name || valid[0].invoice_category || '无票费用报销',
      department: requestForm.department,
      supervisor: requestForm.supervisor,
      asset_category: requestForm.asset_category,
      amount: total.value,
      reason: requestForm.reason,
      submit: submit ? 1 : 0,
      expense_lines: JSON.stringify(valid.map((line) => ({
        ...line,
        amount_before_tax: line.amount_before_tax === '' ? null : Number(line.amount_before_tax),
        tax_amount: line.tax_amount === '' ? null : Number(line.tax_amount),
        total_amount: Number(line.total_amount),
      }))),
      company: requestForm.company,
      doc_type: requestForm.doc_type,
      urgency: requestForm.urgency,
      payment_type: requestForm.payment_type,
      payment_method: requestForm.payment_method,
      bank_name: requestForm.bank_name,
      payee_name: requestForm.payee_name,
      branch: requestForm.branch,
      account_no: requestForm.account_no,
      no_invoice_reason: requestForm.no_invoice_reason.trim(),
    });
    showRequestForm.value = false;
    activeView.value = 'board';
    detailRequestName.value = result.name;
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '报销单保存失败');
  } finally {
    saving.value = false;
  }
}
async function loadInvoices(name) {
  try {
    detailInvoices.value = name ? await getRequestInvoices(name) : [];
  } catch (error) {
    detailInvoices.value = [];
    errorMessage.value = apiError(error, '发票明细加载失败');
  }
}
function requestCreated(name) {
  activeView.value = 'board';
  detailRequestName.value = name;
  reload();
}
async function submitDraft(row) {
  saving.value = true;
  try {
    await draftSubmitter.submit({ name: row.name, no_invoice_reason: String(row.no_invoice_reason || '').trim() });
    await reload();
    await loadInvoices(row.name);
  } catch (error) {
    errorMessage.value = apiError(error, '草稿提交失败');
  } finally {
    saving.value = false;
  }
}
async function act(row, action) {
  try {
    await actor.submit({ name: row.name, action, note: actionNote.value.trim() });
    actionNote.value = '';
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '审批处理失败');
  }
}
async function markPaid(row) {
  try {
    await paidMarker.submit({ name: row.name, note: actionNote.value.trim() });
    actionNote.value = '';
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '付款标记失败');
  }
}
async function withdrawRequest(row) {
  if (!window.confirm('确认撤回该报销申请到草稿吗？审批操作会保留在日志中。')) return;
  try {
    await requestWithdrawer.submit({ name: row.name, note: actionNote.value.trim() || '申请人撤回' });
    actionNote.value = '';
    await reload();
    await loadInvoices(row.name);
  } catch (error) {
    errorMessage.value = apiError(error, '撤回申请失败');
  }
}
async function withdrawPayment(row) {
  if (!window.confirm('确认撤回已付款标记吗？仅财务可执行。')) return;
  try {
    await paymentWithdrawer.submit({ name: row.name, note: actionNote.value.trim() || '财务撤回付款' });
    actionNote.value = '';
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '撤回付款失败');
  }
}

watch(() => options.data, applyDefaults, { immediate: true });
watch(detailRequestName, loadInvoices);
</script>

<template>
  <div class="flex min-h-[calc(100vh-120px)] gap-4">
    <aside class="w-44 shrink-0 rounded border bg-white p-3 shadow-sm">
      <div class="mb-4 flex items-center gap-2 border-b pb-3">
        <div class="rounded bg-amber-50 p-2 text-amber-700"><FeatherIcon name="briefcase" class="h-4 w-4" /></div>
        <div><div class="text-sm font-semibold">费用管理</div><div class="text-[11px] text-gray-500">发票与报销</div></div>
      </div>
      <button v-for="item in NAV_ITEMS" :key="item.key" class="mb-1 flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm" :class="activeView === item.key ? 'bg-blue-50 font-medium text-blue-700' : 'text-gray-600 hover:bg-gray-50'" @click="activeView = item.key">
        <FeatherIcon :name="item.icon" class="h-4 w-4" />{{ item.label }}
      </button>
    </aside>

    <main class="min-w-0 flex-1">
      <div v-if="message" class="mb-3 rounded border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ message }}</div>
      <div v-if="errorMessage" role="alert" class="mb-3 rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{{ errorMessage }}</div>

      <InvoiceUploadWorkbench v-if="activeView === 'invoices'" :options="options.data || {}" @request-created="requestCreated" />

      <section v-else class="space-y-4">
        <header class="flex items-center justify-between">
          <div><h2 class="text-xl font-bold">费用报销流</h2><p class="mt-1 text-sm text-gray-500">报销审批看板与七字段费用明细</p></div>
          <Button variant="subtle" @click="reload"><FeatherIcon name="refresh-cw" class="h-4 w-4" />刷新</Button>
        </header>
        <div class="grid gap-3 md:grid-cols-5">
          <div v-for="item in [
            ['总申请数', stats.total],
            ['待审批', stats.pending],
            ['已通过', stats.approved],
            ['申请总额', money(stats.amount)],
            ['已付款总额', money(stats.paid)],
          ]" :key="item[0]" class="rounded border bg-white p-4 shadow-sm">
            <div class="text-xs text-gray-500">{{ item[0] }}</div><div class="mt-1 text-xl font-semibold">{{ item[1] }}</div>
          </div>
        </div>
        <div class="flex flex-wrap items-end gap-3 rounded border bg-white p-4 shadow-sm">
          <label class="min-w-[300px] flex-1 text-xs text-gray-500">关键字<input v-model="keyword" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="单据号/申请人/发票号码/项目名称" /></label>
          <Button variant="solid" @click="openManualRequest"><FeatherIcon name="plus" class="h-4 w-4" />无票新建报销单</Button>
        </div>
        <div class="grid min-h-[550px] grid-cols-5 gap-3 overflow-x-auto">
          <div v-for="column in STATUS_COLUMNS" :key="column.key" class="min-w-[220px] rounded border bg-white shadow-sm">
            <div class="flex items-center justify-between border-b-2 px-3 py-3" :class="column.header">
              <div class="flex items-center gap-2 font-semibold"><FeatherIcon :name="column.icon" class="h-4 w-4" />{{ column.label }}</div>
              <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{{ rowsForStatus(column.key).length }}</span>
            </div>
            <div class="space-y-2 p-2">
              <button v-for="row in rowsForStatus(column.key)" :key="row.name" class="w-full rounded border border-l-4 bg-white p-3 text-left shadow-sm hover:bg-gray-50" :class="column.accent" @click="detailRequestName = row.name">
                <div class="flex justify-between gap-2"><span class="text-xs text-gray-500">{{ row.name }}</span><span class="rounded px-1.5 py-0.5 text-[10px]" :class="column.badge">{{ column.label }}</span></div>
                <div class="mt-2 truncate text-sm font-semibold">{{ row.subject }}</div>
                <div class="mt-1 truncate text-xs text-gray-500">{{ sourceLabel(row) }}</div>
                <div class="mt-3 flex items-end justify-between border-t pt-2"><span class="font-semibold text-red-600">{{ money(row.amount) }}</span><span class="rounded bg-gray-100 px-2 py-0.5 text-[10px] text-gray-500">{{ row.department || '-' }}</span></div>
              </button>
              <div v-if="!rowsForStatus(column.key).length" class="py-20 text-center text-sm text-gray-300">暂无数据</div>
            </div>
          </div>
        </div>
      </section>
    </main>

    <div v-if="showRequestForm" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4" @click.self="showRequestForm = false">
      <div role="dialog" aria-modal="true" class="flex max-h-[94vh] w-full max-w-7xl flex-col overflow-hidden rounded bg-white shadow-xl">
        <header class="flex items-center justify-between border-b bg-gray-50 px-5 py-4">
          <div><h3 class="font-semibold">无票新建费用报销单</h3><p class="mt-1 text-xs text-gray-500">无票报销保留；提交前必须填写无票原因。</p></div>
          <button title="关闭" @click="showRequestForm = false"><FeatherIcon name="x" class="h-5 w-5" /></button>
        </header>
        <div class="flex-1 space-y-5 overflow-y-auto p-5">
          <section>
            <h4 class="mb-3 text-sm font-semibold">基本信息</h4>
            <div class="grid gap-3 md:grid-cols-3">
              <label class="text-xs text-gray-500">主题<input v-model="requestForm.subject" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500">公司<select v-model="requestForm.company" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in companies" :key="item">{{ item }}</option></select></label>
              <label class="text-xs text-gray-500">申请部门<select v-model="requestForm.department" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in departments" :key="item">{{ item }}</option></select></label>
              <label class="text-xs text-gray-500">部门主管<input v-model="requestForm.supervisor" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500">单据类型<select v-model="requestForm.doc_type" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in docTypes" :key="item">{{ item }}</option></select></label>
              <label class="text-xs text-gray-500">紧急程度<select v-model="requestForm.urgency" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in urgencies" :key="item">{{ item }}</option></select></label>
              <label class="text-xs text-gray-500">资产类别<select v-model="requestForm.asset_category" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in assetCategories" :key="item">{{ item }}</option></select></label>
            </div>
          </section>
          <section>
            <div class="mb-3 flex items-center justify-between"><h4 class="text-sm font-semibold">费用明细（七字段）</h4><button class="text-sm text-blue-700" @click="addLine">＋ 添加明细</button></div>
            <div class="overflow-x-auto">
              <table class="w-full min-w-[1320px] text-sm">
                <thead class="border-b bg-gray-50 text-gray-500"><tr><th class="px-2 py-2 text-left">发票类别</th><th class="px-2 py-2 text-left">项目名称</th><th class="px-2 py-2 text-left">开票日期</th><th class="px-2 py-2 text-left">发票号码</th><th class="px-2 py-2 text-right">税前金额</th><th class="px-2 py-2 text-right">税额</th><th class="px-2 py-2 text-right">合计金额</th><th class="w-10"></th></tr></thead>
                <tbody><tr v-for="(line,index) in expenseLines" :key="line.line_key" class="border-b">
                  <td class="p-2"><input v-model="line.invoice_category" class="w-full rounded border border-gray-300 px-2 py-1.5" /></td>
                  <td class="p-2"><input v-model="line.project_name" class="w-full rounded border border-gray-300 px-2 py-1.5" /></td>
                  <td class="p-2"><input v-model="line.issue_date" type="date" class="w-full rounded border border-gray-300 px-2 py-1.5" /></td>
                  <td class="p-2"><input v-model="line.invoice_number" class="w-full rounded border border-gray-300 px-2 py-1.5" /></td>
                  <td class="p-2"><input v-model="line.amount_before_tax" type="number" min="0" step="0.01" class="w-full rounded border border-gray-300 px-2 py-1.5 text-right" /></td>
                  <td class="p-2"><input v-model="line.tax_amount" type="number" min="0" step="0.01" class="w-full rounded border border-gray-300 px-2 py-1.5 text-right" /></td>
                  <td class="p-2"><input v-model="line.total_amount" type="number" min="0" step="0.01" class="w-full rounded border border-gray-300 px-2 py-1.5 text-right" /></td>
                  <td class="p-2"><button title="删除明细" :disabled="expenseLines.length === 1" class="text-red-600 disabled:text-gray-300" @click="removeLine(index)"><FeatherIcon name="trash-2" class="h-4 w-4" /></button></td>
                </tr></tbody>
                <tfoot><tr><td colspan="6" class="px-2 py-3 text-right font-medium">总费用发生额</td><td class="px-2 py-3 text-right text-base font-semibold text-red-600">{{ money(total) }}</td><td></td></tr></tfoot>
              </table>
            </div>
          </section>
          <section>
            <h4 class="mb-3 text-sm font-semibold">付款信息</h4>
            <div class="grid gap-3 md:grid-cols-3">
              <label class="text-xs text-gray-500">付款类型<select v-model="requestForm.payment_type" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in paymentTypes" :key="item">{{ item }}</option></select></label>
              <label class="text-xs text-gray-500">付款方式<select v-model="requestForm.payment_method" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in paymentMethods" :key="item">{{ item }}</option></select></label>
              <label class="text-xs text-gray-500">收款人<input v-model="requestForm.payee_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500">开户行<input v-model="requestForm.bank_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500">支行<input v-model="requestForm.branch" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500">收款账号<input v-model="requestForm.account_no" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500 md:col-span-3">情况说明/备注<textarea v-model="requestForm.reason" rows="2" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"></textarea></label>
              <label class="text-xs text-gray-500 md:col-span-3">无票原因（提交时必填）<textarea v-model="requestForm.no_invoice_reason" rows="2" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"></textarea></label>
            </div>
          </section>
        </div>
        <footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3"><Button variant="subtle" @click="showRequestForm = false">取消</Button><Button variant="subtle" :loading="saving" @click="saveRequest(false)">保存草稿</Button><Button variant="solid" :loading="saving" @click="saveRequest(true)">保存并提交</Button></footer>
      </div>
    </div>

    <div v-if="selectedRequest" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4" @click.self="detailRequestName = ''">
      <div role="dialog" aria-modal="true" class="flex max-h-[94vh] w-full max-w-7xl flex-col overflow-hidden rounded bg-white shadow-xl">
        <header class="flex items-center justify-between border-b bg-gray-50 px-5 py-4"><div><h3 class="font-semibold">{{ selectedRequest.name }} - 费用报销详情</h3><p class="mt-1 text-xs text-gray-500">{{ selectedRequest.subject }} · {{ sourceLabel(selectedRequest) }}</p></div><button title="关闭" @click="detailRequestName = ''"><FeatherIcon name="x" class="h-5 w-5" /></button></header>
        <div class="flex-1 space-y-5 overflow-y-auto p-5">
          <section><div class="mb-3 flex items-center justify-between"><h4 class="text-sm font-semibold">基本信息</h4><span class="rounded px-2 py-1 text-xs" :class="statusMeta(selectedRequest.kanban_status).badge">{{ statusMeta(selectedRequest.kanban_status).label }}</span></div><dl class="grid gap-3 text-sm md:grid-cols-4"><div><dt class="text-xs text-gray-500">公司</dt><dd class="mt-1">{{ selectedRequest.company || '-' }}</dd></div><div><dt class="text-xs text-gray-500">申请部门</dt><dd class="mt-1">{{ selectedRequest.department || '-' }}</dd></div><div><dt class="text-xs text-gray-500">申请人</dt><dd class="mt-1">{{ selectedRequest.employee_name || '-' }}</dd></div><div><dt class="text-xs text-gray-500">来源</dt><dd class="mt-1">{{ sourceLabel(selectedRequest) }}</dd></div></dl></section>
          <section>
            <h4 class="mb-3 text-sm font-semibold">费用明细（七字段）</h4>
            <div class="overflow-x-auto"><table class="w-full min-w-[1300px] text-sm">
              <thead class="border-b bg-gray-50 text-gray-500"><tr><th class="px-2 py-2 text-left">发票类别</th><th class="px-2 py-2 text-left">项目名称</th><th class="px-2 py-2 text-left">开票日期</th><th class="px-2 py-2 text-left">发票号码</th><th class="px-2 py-2 text-right">税前金额</th><th class="px-2 py-2 text-right">税额</th><th class="px-2 py-2 text-right">合计金额</th><th class="px-2 py-2 text-left">发票文件</th></tr></thead>
              <tbody><tr v-for="line in selectedRequest.expense_lines || []" :key="line.line_key" class="border-b"><td class="px-2 py-3">{{ line.invoice_category || '-' }}</td><td class="px-2 py-3">{{ line.project_name || '-' }}</td><td class="px-2 py-3">{{ line.issue_date || '-' }}</td><td class="px-2 py-3">{{ line.invoice_number || '-' }}</td><td class="px-2 py-3 text-right">{{ money(line.amount_before_tax, true) }}</td><td class="px-2 py-3 text-right">{{ money(line.tax_amount, true) }}</td><td class="px-2 py-3 text-right font-semibold text-red-600">{{ money(line.total_amount) }}</td><td class="px-2 py-3"><div class="flex flex-wrap gap-1"><button v-for="(invoice,index) in invoicesForLine(detailInvoices,line.line_key)" :key="invoice.name" class="rounded bg-blue-50 px-2 py-1 text-xs text-blue-700" @click="previewInvoiceRow = invoice">查看发票 {{ index + 1 }}</button><span v-if="!invoicesForLine(detailInvoices,line.line_key).length" class="text-gray-400">无票</span></div></td></tr></tbody>
              <tfoot><tr><td colspan="6" class="px-2 py-3 text-right font-medium">总额</td><td class="px-2 py-3 text-right text-base font-semibold text-red-600">{{ money(selectedRequest.amount) }}</td><td></td></tr></tfoot>
            </table></div>
          </section>
          <section><h4 class="mb-3 text-sm font-semibold">付款信息</h4><dl class="grid gap-3 text-sm md:grid-cols-3"><div><dt class="text-xs text-gray-500">付款类型</dt><dd class="mt-1">{{ selectedRequest.payment_type || '-' }}</dd></div><div><dt class="text-xs text-gray-500">付款方式</dt><dd class="mt-1">{{ selectedRequest.payment_method || '-' }}</dd></div><div><dt class="text-xs text-gray-500">收款人</dt><dd class="mt-1">{{ selectedRequest.payee_name || '-' }}</dd></div><div><dt class="text-xs text-gray-500">开户行/支行</dt><dd class="mt-1">{{ [selectedRequest.bank_name,selectedRequest.branch].filter(Boolean).join(' / ') || '-' }}</dd></div><div><dt class="text-xs text-gray-500">收款账号</dt><dd class="mt-1">{{ selectedRequest.account_no || '-' }}</dd></div><div><dt class="text-xs text-gray-500">付款时间</dt><dd class="mt-1">{{ dateText(selectedRequest.paid_on) }}</dd></div></dl></section>
          <section v-if="selectedRequest.no_invoice_reason"><h4 class="mb-2 text-sm font-semibold">无票原因</h4><p class="rounded bg-gray-50 p-3 text-sm text-gray-600 whitespace-pre-wrap">{{ selectedRequest.no_invoice_reason }}</p></section>
          <section><h4 class="mb-4 text-sm font-semibold">审批记录</h4><div class="flex min-w-[760px] items-start overflow-x-auto"><template v-for="(step,index) in selectedRequest.steps || []" :key="step.step_index"><div class="w-40 shrink-0 text-center"><div class="mx-auto flex h-9 w-9 items-center justify-center rounded-full text-sm font-semibold" :class="['已通过','已办理'].includes(step.status) ? 'bg-emerald-600 text-white' : step.status === '已拒绝' ? 'bg-red-600 text-white' : step.step_index === selectedRequest.current_step_index ? 'bg-amber-500 text-white' : 'bg-gray-200 text-gray-600'">{{ step.step_index }}</div><div class="mt-2 text-xs font-medium">{{ step.label }}</div><div class="mt-1 text-[11px] text-gray-500">{{ step.approvers.join(' / ') }}</div><div v-if="step.acted_on" class="mt-1 text-[10px] text-gray-400">{{ dateText(step.acted_on) }}</div><div v-if="step.note" class="mt-1 text-[10px] text-gray-500">{{ step.note }}</div></div><div v-if="index < selectedRequest.steps.length - 1" class="mt-4 flex-1 border-t-2 border-dashed border-gray-300"></div></template></div></section>
          <section v-if="selectedRequest.operation_log?.length"><h4 class="mb-2 text-sm font-semibold">撤回/下推操作记录</h4><div class="space-y-2"><div v-for="(event,index) in selectedRequest.operation_log" :key="index" class="rounded bg-gray-50 p-3 text-xs text-gray-600"><span class="font-medium">{{ event.action }}</span> · {{ event.actor }} · {{ dateText(event.acted_on) }} · {{ event.from_status }} → {{ event.to_status }}<span v-if="event.note"> · {{ event.note }}</span></div></div></section>
        </div>
        <footer class="flex flex-col gap-2 border-t bg-gray-50 px-5 py-3 md:flex-row md:items-center"><input v-model="actionNote" class="min-w-0 flex-1 rounded border border-gray-300 px-3 py-2 text-sm" placeholder="审批、付款或撤回备注" /><div class="flex flex-wrap justify-end gap-2"><Button variant="subtle" @click="detailRequestName = ''">关闭</Button><Button v-if="selectedRequest.can_withdraw" variant="subtle" @click="withdrawRequest(selectedRequest)">撤回申请</Button><Button v-if="selectedRequest.can_withdraw_payment" variant="subtle" @click="withdrawPayment(selectedRequest)">撤回付款</Button><Button v-if="selectedRequest.kanban_status === 'draft'" variant="solid" :loading="saving" @click="submitDraft(selectedRequest)">提交审批</Button><Button v-if="selectedRequest.can_act && selectedRequest.current_step_mode !== 'handle'" variant="subtle" @click="act(selectedRequest,'reject')">驳回</Button><Button v-if="selectedRequest.can_act" variant="solid" @click="act(selectedRequest,'approve')">{{ selectedRequest.current_step_mode === 'handle' ? '办理完成' : '审批通过' }}</Button><Button v-if="selectedRequest.can_mark_paid" variant="solid" @click="markPaid(selectedRequest)">标记已付款</Button></div></footer>
      </div>
    </div>

    <InvoicePreviewDrawer :invoice="previewInvoiceRow" @close="previewInvoiceRow = null" />
  </div>
</template>
