<script setup>
import { Button, Card, createResource } from 'frappe-ui';
import { computed, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import ExpenseWorkbench from '../components/ExpenseWorkbench.vue';

const REQUEST_LEAVE = '\u8bf7\u5047\u7533\u8bf7';
const REQUEST_EXPENSE_PAYMENT = '\u8d39\u7528\u4ed8\u6b3e\u7533\u8bf7';
const ASSET_ADMIN = '非电子类固定资产（人事/行政）';
const ASSET_IT = '电子类固定资产（IT）';
const ASSET_OTHER = '其他';

const PAGE_CONFIG = {
  '/approval/leave': {
    requestType: REQUEST_LEAVE,
    title: '\u8bf7\u5047\u5ba1\u6279',
    formTitle: '\u53d1\u8d77\u8bf7\u5047\u7533\u8bf7',
  },
  '/approval/purchase': {
    requestType: REQUEST_EXPENSE_PAYMENT,
    title: '\u8d39\u7528\u4ed8\u6b3e/\u62a5\u9500',
    formTitle: '\u8d39\u7528\u4ed8\u6b3e/\u62a5\u9500\u5de5\u4f5c\u53f0',
  },
};

const T = {
  refresh: '\u5237\u65b0',
  pendingTitle: '\u5f85\u6211\u5904\u7406',
  mineTitle: '\u6211\u7684\u7533\u8bf7',
  routeTitle: '\u5ba1\u6279\u6d41\u7a0b',
  subject: '\u4e3b\u9898',
  department: '\u90e8\u95e8',
  supervisor: '\u90e8\u95e8\u4e3b\u7ba1',
  dateFrom: '\u5f00\u59cb\u65e5\u671f',
  dateTo: '\u7ed3\u675f\u65e5\u671f',
  amount: '\u91d1\u989d',
  asset: '\u8d44\u4ea7\u7c7b\u522b',
  reason: '\u4e8b\u7531',
  submit: '\u63d0\u4ea4',
  saveDraft: '\u4fdd\u5b58\u8349\u7a3f',
  submitApproval: '\u63d0\u4ea4\u5ba1\u6279',
  approve: '\u901a\u8fc7',
  reject: '\u62d2\u7edd',
  handle: '确认付款',
  markPaid: '\u6807\u8bb0\u5df2\u4ed8\u6b3e',
  note: '\u5907\u6ce8',
  status: '\u72b6\u6001',
  action: '\u64cd\u4f5c',
  applicant: '\u7533\u8bf7\u4eba',
  current: '\u5f53\u524d\u8282\u70b9',
  empty: '\u6682\u65e0\u6570\u636e',
  saved: '\u7533\u8bf7\u5df2\u63d0\u4ea4',
  loadFailed: '\u52a0\u8f7d\u5931\u8d25',
  saveFailed: '\u63d0\u4ea4\u5931\u8d25',
  actionFailed: '\u5904\u7406\u5931\u8d25',
  required: '\u8bf7\u586b\u5199\u5fc5\u586b\u9879',
  board: '\u4ed8\u6b3e/\u62a5\u9500\u5355\u770b\u677f',
  consumption: '\u6d88\u8d39\u660e\u7ec6',
  pending: '\u5f85\u6211\u5904\u7406',
  flow: '\u5ba1\u6279\u6d41',
  newConsumption: '\u65b0\u5efa\u6d88\u8d39\u660e\u7ec6',
  newManual: '\u624b\u5de5\u65b0\u5efa\u4ed8\u6b3e/\u62a5\u9500\u5355',
  invoiceName: '\u53d1\u7968/\u9644\u4ef6\u540d',
  addInvoice: '\u4e0a\u4f20\u53d1\u7968',
  pushDown: '\u4e0b\u63a8\u751f\u6210\u4ed8\u6b3e\u5355',
  pushAndSubmit: '\u4e0b\u63a8\u5e76\u63d0\u4ea4',
  selectPush: '\u9009\u62e9\u4e0b\u63a8',
  detail: '\u5355\u636e\u8be6\u60c5',
  expenseDate: '\u8d39\u7528\u65e5\u671f',
  category: '\u8d39\u7528\u9879\u76ee',
  description: '\u8d39\u7528\u8bf4\u660e',
  paymentInfo: '\u4ed8\u6b3e\u4fe1\u606f',
  invoiceRestriction: '\u53d1\u7968\u4ec5\u5728\u7cfb\u7edf\u5185\u9884\u89c8\uff0c\u663e\u793a\u6c34\u5370\u5e76\u8bb0\u5f55\u67e5\u770b\uff1b\u6d4f\u89c8\u5668\u65e0\u6cd5\u771f\u6b63\u963b\u6b62\u622a\u56fe\u3002',
};

const STATUS_COLUMNS = [
  { key: 'draft', label: '\u5f85\u63d0\u4ea4' },
  { key: 'pending', label: '\u5ba1\u6279\u4e2d' },
  { key: 'approved', label: '\u5df2\u901a\u8fc7' },
  { key: 'rejected', label: '\u5df2\u9a73\u56de' },
  { key: 'paid', label: '\u5df2\u4ed8\u6b3e' },
];

const route = useRoute();
const pageConfig = computed(() => PAGE_CONFIG[route.path] || PAGE_CONFIG['/approval/leave']);
const currentRequestType = computed(() => pageConfig.value.requestType);
const isLeave = computed(() => currentRequestType.value === REQUEST_LEAVE);
const isPurchase = computed(() => currentRequestType.value === REQUEST_EXPENSE_PAYMENT);

const leaveForm = reactive({
  subject: '',
  department: '',
  supervisor: '',
  from_date: '',
  to_date: '',
  reason: '',
});

const manualForm = reactive({
  subject: '',
  company: '',
  department: '',
  supervisor: '',
  doc_type: '',
  urgency: '',
  asset_category: ASSET_OTHER,
  expense_date: '',
  category: '',
  amount: '',
  description: '',
  payment_type: '',
  payment_method: '',
  bank_name: '',
  payee_name: '',
  branch: '',
  account_no: '',
  reason: '',
});

const consumptionForm = reactive({
  title: '',
  category: '',
  amount: '',
  expense_date: '',
  department: '',
  description: '',
});
const invoiceForm = reactive({ invoice_name: '', file_type: '', file_size: '' });
const pushPayment = reactive({
  subject: '',
  company: '',
  department: '',
  supervisor: '',
  doc_type: '',
  urgency: '',
  asset_category: ASSET_OTHER,
  payment_type: '',
  payment_method: '',
  bank_name: '',
  payee_name: '',
  branch: '',
  account_no: '',
  reason: '',
});

const message = ref('');
const errMsg = ref('');
const saving = ref(false);
const actionNote = ref('');
const purchaseTab = ref('board');
const showManualForm = ref(false);
const selectedRequestName = ref('');
const selectedConsumptionName = ref('');
const pushSelection = ref([]);
const filters = reactive({ keyword: '', department: '', category: '' });

const options = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.get_options',
  method: 'GET',
  auto: true,
});
const preview = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.preview_route',
  method: 'GET',
});
const mine = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_requests',
  method: 'GET',
  makeParams: () => ({ view: 'mine', request_type: currentRequestType.value }),
  auto: true,
});
const pending = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_requests',
  method: 'GET',
  makeParams: () => ({ view: 'pending', request_type: currentRequestType.value }),
  auto: true,
});
const purchaseRequests = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_requests',
  method: 'GET',
  makeParams: () => ({ view: 'all', request_type: REQUEST_EXPENSE_PAYMENT, limit: 100 }),
  auto: true,
});
const consumptionRows = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_consumption_details',
  method: 'GET',
  makeParams: () => ({ view: 'all', limit: 200 }),
  auto: true,
});
const creator = createResource({ url: 'rayher_hr_payroll.api.oa_entry.create_request' });
const actor = createResource({ url: 'rayher_hr_payroll.api.oa_entry.action_request' });
const draftSubmitter = createResource({ url: 'rayher_hr_payroll.api.oa_entry.submit_request' });
const paidMarker = createResource({ url: 'rayher_hr_payroll.api.oa_entry.mark_paid' });
const consumptionSaver = createResource({ url: 'rayher_hr_payroll.api.oa_entry.save_consumption_detail' });
const invoiceAdder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.add_invoice' });
const pusher = createResource({ url: 'rayher_hr_payroll.api.oa_entry.push_consumption_to_request' });

const assetCategories = computed(() => options.data?.asset_categories || [ASSET_ADMIN, ASSET_IT, ASSET_OTHER]);
const expenseCategories = computed(() => options.data?.expense_categories || []);
const departments = computed(() => options.data?.departments || []);
const docTypes = computed(() => options.data?.doc_types || []);
const urgencies = computed(() => options.data?.urgencies || []);
const paymentTypes = computed(() => options.data?.payment_types || []);
const paymentMethods = computed(() => options.data?.payment_methods || []);
const companies = computed(() => options.data?.companies || []);
const routeSteps = computed(() => preview.data?.steps || []);
const requestRows = computed(() => purchaseRequests.data || []);
const selectedRequest = computed(() => requestRows.value.find((row) => row.name === selectedRequestName.value) || requestRows.value[0]);
const consumptionList = computed(() => consumptionRows.data || []);
const selectedConsumption = computed(() => consumptionList.value.find((row) => row.name === selectedConsumptionName.value) || consumptionList.value[0]);
const pushableConsumption = computed(() => consumptionList.value.filter((row) => row.status === '\u5f85\u4e0b\u63a8' || row.status === '\u5df2\u4e0a\u4f20\u53d1\u7968'));

const filteredRequests = computed(() => requestRows.value.filter((row) => {
  const keyword = filters.keyword.trim().toLowerCase();
  if (keyword) {
    const text = [
      row.name,
      row.subject,
      row.employee_name,
      row.department,
      row.reason,
      ...(row.expense_lines || []).map((line) => line.category + line.description),
    ].join(' ').toLowerCase();
    if (!text.includes(keyword)) return false;
  }
  if (filters.department && row.department !== filters.department) return false;
  if (filters.category && !(row.expense_lines || []).some((line) => line.category === filters.category)) return false;
  return true;
}));

const stats = computed(() => {
  const rows = requestRows.value;
  const total = rows.length;
  const pendingCount = rows.filter((row) => row.kanban_status === 'pending').length;
  const approved = rows.filter((row) => row.kanban_status === 'approved').length;
  const rejected = rows.filter((row) => row.kanban_status === 'rejected').length;
  const paid = rows.filter((row) => row.kanban_status === 'paid').length;
  const totalAmount = rows.reduce((sum, row) => sum + Number(row.amount || 0), 0);
  const paidAmount = rows.filter((row) => row.kanban_status === 'paid').reduce((sum, row) => sum + Number(row.amount || 0), 0);
  const passRate = total ? Math.round(((approved + paid) / total) * 100) : 0;
  return { total, pendingCount, approved, rejected, paid, totalAmount, paidAmount, passRate };
});

function cleanMessage(value) {
  return String(value || '').replace(/<[^>]*>/g, '').trim();
}

function parseServerMessages(raw) {
  if (!raw) return [];
  try {
    const items = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (!Array.isArray(items)) return [];
    return items.map((item) => {
      try {
        const parsed = typeof item === 'string' ? JSON.parse(item) : item;
        return parsed.message || parsed.title || item;
      } catch {
        return item;
      }
    }).filter(Boolean);
  } catch {
    return [];
  }
}

function serverMessage(error, fallback) {
  const messages = [
    ...(error?.messages || []),
    ...parseServerMessages(error?._server_messages),
  ].map(cleanMessage).filter(Boolean);
  return messages.length ? messages.join('\uFF1B') : cleanMessage(error?._error_message || error?.message) || fallback;
}

function first(list, fallback = '') {
  return Array.isArray(list) && list.length ? list[0] : fallback;
}

function applyContext(context) {
  if (!context) return;
  if (!leaveForm.department && context.department) leaveForm.department = context.department;
  if (!leaveForm.supervisor && context.supervisor) leaveForm.supervisor = context.supervisor;
  if (!manualForm.department && context.department) manualForm.department = context.department;
  if (!manualForm.supervisor && context.supervisor) manualForm.supervisor = context.supervisor;
  if (!manualForm.payee_name && context.employee_name) manualForm.payee_name = context.employee_name;
  if (!consumptionForm.department && context.department) consumptionForm.department = context.department;
  if (!pushPayment.department && context.department) pushPayment.department = context.department;
  if (!pushPayment.supervisor && context.supervisor) pushPayment.supervisor = context.supervisor;
  if (!pushPayment.payee_name && context.employee_name) pushPayment.payee_name = context.employee_name;
}

function applyDefaults() {
  manualForm.company ||= first(companies.value);
  manualForm.doc_type ||= first(docTypes.value);
  manualForm.urgency ||= first(urgencies.value);
  manualForm.category ||= first(expenseCategories.value);
  manualForm.payment_type ||= first(paymentTypes.value);
  manualForm.payment_method ||= first(paymentMethods.value);
  pushPayment.company ||= first(companies.value);
  pushPayment.doc_type ||= first(docTypes.value);
  pushPayment.urgency ||= first(urgencies.value);
  pushPayment.payment_type ||= first(paymentTypes.value);
  pushPayment.payment_method ||= first(paymentMethods.value);
  consumptionForm.category ||= first(expenseCategories.value);
}

function previewPayload() {
  if (isLeave.value) {
    return {
      request_type: REQUEST_LEAVE,
      subject: leaveForm.subject.trim(),
      department: leaveForm.department.trim(),
      supervisor: leaveForm.supervisor.trim() || T.supervisor,
      asset_category: ASSET_OTHER,
    };
  }
  return {
    request_type: REQUEST_EXPENSE_PAYMENT,
    department: manualForm.department || pushPayment.department,
    supervisor: manualForm.supervisor || pushPayment.supervisor,
    asset_category: manualForm.asset_category || pushPayment.asset_category || ASSET_OTHER,
  };
}

async function previewRoute() {
  errMsg.value = '';
  preview.data = null;
  try {
    await preview.submit(previewPayload());
  } catch (error) {
    preview.data = null;
    errMsg.value = serverMessage(error, T.loadFailed);
  }
}

async function reloadPurchase() {
  await Promise.allSettled([purchaseRequests.reload(), pending.reload(), consumptionRows.reload(), previewRoute()]);
}

async function reloadLists() {
  if (isPurchase.value) {
    await reloadPurchase();
    return;
  }
  await Promise.allSettled([mine.reload(), pending.reload(), previewRoute()]);
}

function validateLeave() {
  return Boolean(leaveForm.subject.trim() && leaveForm.department.trim() && leaveForm.supervisor.trim() && leaveForm.from_date && leaveForm.to_date);
}

function fmtAmount(value) {
  const n = Number(value || 0);
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function modeLabel(mode) {
  if (mode === 'all') return '\u4f1a\u7b7e';
  if (mode === 'handle') return '付款确认';
  return '\u5ba1\u6279';
}

function rowsForStatus(status) {
  return filteredRequests.value.filter((row) => row.kanban_status === status);
}

function resetManualForm() {
  Object.assign(manualForm, {
    subject: '',
    expense_date: '',
    amount: '',
    description: '',
    bank_name: '',
    branch: '',
    account_no: '',
    reason: '',
  });
  applyDefaults();
  applyContext(options.data?.context);
}

function manualPayload(submit) {
  return {
    request_type: REQUEST_EXPENSE_PAYMENT,
    subject: manualForm.subject.trim() || manualForm.description.trim() || manualForm.category,
    department: manualForm.department,
    supervisor: manualForm.supervisor,
    asset_category: manualForm.asset_category,
    amount: manualForm.amount,
    reason: manualForm.reason || manualForm.description,
    submit: submit ? 1 : 0,
    company: manualForm.company,
    doc_type: manualForm.doc_type,
    urgency: manualForm.urgency,
    payment_type: manualForm.payment_type,
    payment_method: manualForm.payment_method,
    bank_name: manualForm.bank_name,
    payee_name: manualForm.payee_name,
    branch: manualForm.branch,
    account_no: manualForm.account_no,
    expense_lines: JSON.stringify([{
      expense_date: manualForm.expense_date,
      category: manualForm.category,
      amount: Number(manualForm.amount || 0),
      description: manualForm.description,
      attachment_count: 0,
      invoice_status: '',
    }]),
  };
}

async function submitLeaveRequest() {
  message.value = '';
  errMsg.value = '';
  if (!validateLeave()) {
    errMsg.value = T.required;
    return;
  }
  saving.value = true;
  try {
    await creator.submit({
      request_type: REQUEST_LEAVE,
      subject: leaveForm.subject.trim(),
      department: leaveForm.department.trim(),
      supervisor: leaveForm.supervisor.trim(),
      from_date: leaveForm.from_date,
      to_date: leaveForm.to_date,
      reason: leaveForm.reason.trim(),
    });
    message.value = T.saved;
    Object.assign(leaveForm, { subject: '', from_date: '', to_date: '', reason: '' });
    await reloadLists();
  } catch (error) {
    errMsg.value = serverMessage(error, T.saveFailed);
  } finally {
    saving.value = false;
  }
}

async function saveManual(submit = false) {
  errMsg.value = '';
  if (!manualForm.department || !manualForm.category || Number(manualForm.amount || 0) <= 0) {
    errMsg.value = T.required;
    return;
  }
  saving.value = true;
  try {
    const row = await creator.submit(manualPayload(submit));
    selectedRequestName.value = row.name;
    showManualForm.value = false;
    resetManualForm();
    await reloadPurchase();
  } catch (error) {
    errMsg.value = serverMessage(error, T.saveFailed);
  } finally {
    saving.value = false;
  }
}

async function saveConsumption() {
  errMsg.value = '';
  if (!consumptionForm.title || !consumptionForm.category || !consumptionForm.expense_date || Number(consumptionForm.amount || 0) <= 0) {
    errMsg.value = T.required;
    return;
  }
  try {
    const row = await consumptionSaver.submit({ ...consumptionForm });
    selectedConsumptionName.value = row.name;
    Object.assign(consumptionForm, { title: '', amount: '', expense_date: '', description: '' });
    applyDefaults();
    applyContext(options.data?.context);
    await consumptionRows.reload();
  } catch (error) {
    errMsg.value = serverMessage(error, T.saveFailed);
  }
}

async function addInvoiceFromInput(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file || !selectedConsumption.value) return;
  invoiceForm.invoice_name = file.name;
  invoiceForm.file_type = file.type || file.name.split('.').pop() || '';
  invoiceForm.file_size = `${Math.round(file.size / 1024)}KB`;
  await addInvoice();
}

async function addInvoice() {
  if (!selectedConsumption.value || !invoiceForm.invoice_name.trim()) return;
  try {
    const row = await invoiceAdder.submit({
      consumption: selectedConsumption.value.name,
      invoice_name: invoiceForm.invoice_name.trim(),
      file_type: invoiceForm.file_type,
      file_size: invoiceForm.file_size,
    });
    selectedConsumptionName.value = row.name;
    Object.assign(invoiceForm, { invoice_name: '', file_type: '', file_size: '' });
    await consumptionRows.reload();
  } catch (error) {
    errMsg.value = serverMessage(error, T.saveFailed);
  }
}

function togglePush(name) {
  if (pushSelection.value.includes(name)) {
    pushSelection.value = pushSelection.value.filter((item) => item !== name);
  } else {
    pushSelection.value = [...pushSelection.value, name];
  }
}

function pushInfoPayload() {
  return {
    subject: pushPayment.subject,
    company: pushPayment.company,
    department: pushPayment.department,
    supervisor: pushPayment.supervisor,
    doc_type: pushPayment.doc_type,
    urgency: pushPayment.urgency,
    asset_category: pushPayment.asset_category,
    payment_type: pushPayment.payment_type,
    payment_method: pushPayment.payment_method,
    bank_name: pushPayment.bank_name,
    payee_name: pushPayment.payee_name,
    branch: pushPayment.branch,
    account_no: pushPayment.account_no,
    reason: pushPayment.reason,
  };
}

async function pushSelected(submit = false) {
  errMsg.value = '';
  if (!pushSelection.value.length) {
    errMsg.value = T.selectPush;
    return;
  }
  try {
    const row = await pusher.submit({
      consumption_names: JSON.stringify(pushSelection.value),
      payment_info: JSON.stringify(pushInfoPayload()),
      submit: submit ? 1 : 0,
    });
    selectedRequestName.value = row.name;
    pushSelection.value = [];
    purchaseTab.value = 'board';
    await reloadPurchase();
  } catch (error) {
    errMsg.value = serverMessage(error, T.saveFailed);
  }
}

async function submitDraft(row) {
  try {
    await draftSubmitter.submit({ name: row.name });
    await reloadPurchase();
  } catch (error) {
    errMsg.value = serverMessage(error, T.actionFailed);
  }
}

async function markPaid(row) {
  try {
    await paidMarker.submit({ name: row.name, note: actionNote.value.trim() });
    actionNote.value = '';
    await reloadPurchase();
  } catch (error) {
    errMsg.value = serverMessage(error, T.actionFailed);
  }
}

async function act(row, action) {
  errMsg.value = '';
  try {
    await actor.submit({ name: row.name, action, note: actionNote.value.trim() });
    actionNote.value = '';
    await reloadLists();
  } catch (error) {
    errMsg.value = serverMessage(error, T.actionFailed);
  }
}

watch(() => options.data, () => {
  applyDefaults();
  applyContext(options.data?.context);
  previewRoute();
}, { immediate: true });
watch(
  [() => leaveForm.department, () => leaveForm.supervisor, () => manualForm.department, () => manualForm.supervisor, () => manualForm.asset_category, () => pushPayment.department, () => pushPayment.asset_category],
  () => previewRoute(),
  { immediate: false }
);
watch(currentRequestType, () => {
  message.value = '';
  errMsg.value = '';
  reloadLists();
});
watch(consumptionList, (rows) => {
  if (!selectedConsumptionName.value && rows.length) selectedConsumptionName.value = rows[0].name;
});
watch(requestRows, (rows) => {
  if (!selectedRequestName.value && rows.length) selectedRequestName.value = rows[0].name;
});
</script>

<template>
  <div class='space-y-4'>
    <div v-if='isLeave' class='flex flex-col gap-2 md:flex-row md:items-center md:justify-between'>
      <div>
        <h2 class='text-xl font-semibold text-gray-900'>{{ pageConfig.title }}</h2>
        <p v-if='isPurchase' class='text-sm text-gray-500 mt-1'>{{ pageConfig.formTitle }}</p>
      </div>
      <Button variant='subtle' @click='reloadLists'>{{ T.refresh }}</Button>
    </div>

    <template v-if='isLeave'>
      <div class='grid grid-cols-1 xl:grid-cols-3 gap-4'>
        <Card :title='pageConfig.formTitle' class='xl:col-span-2'>
          <div class='grid grid-cols-1 md:grid-cols-2 gap-3'>
            <label class='flex flex-col gap-1 text-sm'>
              <span class='text-xs text-gray-500'>{{ T.subject }}</span>
              <input v-model='leaveForm.subject' class='border border-gray-300 rounded px-3 py-2' />
            </label>
            <label class='flex flex-col gap-1 text-sm'>
              <span class='text-xs text-gray-500'>{{ T.department }}</span>
              <input v-model='leaveForm.department' class='border border-gray-300 rounded px-3 py-2' />
            </label>
            <label class='flex flex-col gap-1 text-sm'>
              <span class='text-xs text-gray-500'>{{ T.supervisor }}</span>
              <input v-model='leaveForm.supervisor' class='border border-gray-300 rounded px-3 py-2' />
            </label>
            <label class='flex flex-col gap-1 text-sm'>
              <span class='text-xs text-gray-500'>{{ T.dateFrom }}</span>
              <input v-model='leaveForm.from_date' type='date' class='border border-gray-300 rounded px-3 py-2' />
            </label>
            <label class='flex flex-col gap-1 text-sm'>
              <span class='text-xs text-gray-500'>{{ T.dateTo }}</span>
              <input v-model='leaveForm.to_date' type='date' class='border border-gray-300 rounded px-3 py-2' />
            </label>
            <label class='md:col-span-2 flex flex-col gap-1 text-sm'>
              <span class='text-xs text-gray-500'>{{ T.reason }}</span>
              <textarea v-model='leaveForm.reason' rows='3' class='border border-gray-300 rounded px-3 py-2 resize-y'></textarea>
            </label>
          </div>
          <div class='mt-3 flex items-center gap-3'>
            <Button variant='solid' :loading='saving' @click='submitLeaveRequest'>{{ T.submit }}</Button>
            <span v-if='message' class='text-sm text-green-600'>{{ message }}</span>
            <span v-if='errMsg' class='text-sm text-red-600'>{{ errMsg }}</span>
          </div>
        </Card>

        <Card :title='T.routeTitle'>
          <div v-if='preview.loading' class='text-sm text-gray-500 py-4'>...</div>
          <div v-else-if='!routeSteps.length' class='text-sm text-gray-400 py-4'>{{ T.empty }}</div>
          <ol v-else class='space-y-2'>
            <li v-for='step in routeSteps' :key='step.step_index' class='rounded border border-gray-200 px-3 py-2'>
              <div class='flex items-center justify-between gap-2'>
                <span class='font-medium text-gray-900'>{{ step.step_index }}. {{ step.label }}</span>
                <span class='text-xs rounded bg-gray-100 px-2 py-1 text-gray-600'>{{ modeLabel(step.mode) }}</span>
              </div>
              <div class='text-xs text-gray-500 mt-1'>{{ step.approvers.join(' / ') }}</div>
            </li>
          </ol>
        </Card>
      </div>
    </template>

    <ExpenseWorkbench v-else />

    <template v-if='false'>
      <div class='flex flex-wrap items-center gap-2'>
        <button v-for='tab in [{k:"board",l:T.board},{k:"consumption",l:T.consumption},{k:"pending",l:T.pending},{k:"flow",l:T.flow}]' :key='tab.k'
          type='button'
          class='rounded border px-3 py-1.5 text-sm'
          :class="purchaseTab === tab.k ? 'border-gray-900 bg-gray-900 text-white' : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'"
          @click='purchaseTab = tab.k'>
          {{ tab.l }}
        </button>
      </div>

      <div v-if='errMsg' class='rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700'>{{ errMsg }}</div>

      <template v-if='purchaseTab === "board"'>
        <div class='grid grid-cols-1 gap-3 md:grid-cols-4'>
          <div class='rounded bg-white p-3 border border-gray-200'>
            <div class='text-xs text-gray-500'>{{ T.board }}</div>
            <div class='text-xl font-semibold'>{{ stats.total }}</div>
          </div>
          <div class='rounded bg-white p-3 border border-gray-200'>
            <div class='text-xs text-gray-500'>{{ T.pending }}</div>
            <div class='text-xl font-semibold'>{{ stats.pendingCount }}</div>
          </div>
          <div class='rounded bg-white p-3 border border-gray-200'>
            <div class='text-xs text-gray-500'>{{ T.amount }}</div>
            <div class='text-xl font-semibold'>{{ fmtAmount(stats.totalAmount) }}</div>
          </div>
          <div class='rounded bg-white p-3 border border-gray-200'>
            <div class='text-xs text-gray-500'>{{ T.markPaid }}</div>
            <div class='text-xl font-semibold'>{{ fmtAmount(stats.paidAmount) }}</div>
          </div>
        </div>

        <Card :title='T.board'>
          <div class='mb-4 flex flex-wrap gap-2'>
            <input v-model='filters.keyword' class='border border-gray-300 rounded px-3 py-1.5 text-sm' :placeholder='T.subject' />
            <select v-model='filters.department' class='border border-gray-300 rounded px-3 py-1.5 text-sm'>
              <option value=''>{{ T.department }}</option>
              <option v-for='item in departments' :key='item' :value='item'>{{ item }}</option>
            </select>
            <select v-model='filters.category' class='border border-gray-300 rounded px-3 py-1.5 text-sm'>
              <option value=''>{{ T.category }}</option>
              <option v-for='item in expenseCategories' :key='item' :value='item'>{{ item }}</option>
            </select>
            <Button variant='subtle' @click='showManualForm = !showManualForm'>{{ T.newManual }}</Button>
          </div>

          <div v-if='showManualForm' class='mb-4 rounded border border-gray-200 bg-gray-50 p-3'>
            <div class='grid grid-cols-1 gap-3 md:grid-cols-4'>
              <input v-model='manualForm.subject' class='border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.subject' />
              <select v-model='manualForm.company' class='border border-gray-300 rounded px-3 py-2 text-sm'><option v-for='item in companies' :key='item'>{{ item }}</option></select>
              <select v-model='manualForm.department' class='border border-gray-300 rounded px-3 py-2 text-sm'><option v-for='item in departments' :key='item'>{{ item }}</option></select>
              <select v-model='manualForm.doc_type' class='border border-gray-300 rounded px-3 py-2 text-sm'><option v-for='item in docTypes' :key='item'>{{ item }}</option></select>
              <input v-model='manualForm.expense_date' type='date' class='border border-gray-300 rounded px-3 py-2 text-sm' />
              <select v-model='manualForm.category' class='border border-gray-300 rounded px-3 py-2 text-sm'><option v-for='item in expenseCategories' :key='item'>{{ item }}</option></select>
              <input v-model='manualForm.amount' type='number' min='0' step='0.01' class='border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.amount' />
              <input v-model='manualForm.description' class='border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.description' />
              <select v-model='manualForm.payment_type' class='border border-gray-300 rounded px-3 py-2 text-sm'><option v-for='item in paymentTypes' :key='item'>{{ item }}</option></select>
              <select v-model='manualForm.payment_method' class='border border-gray-300 rounded px-3 py-2 text-sm'><option v-for='item in paymentMethods' :key='item'>{{ item }}</option></select>
              <input v-model='manualForm.payee_name' class='border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.applicant' />
              <input v-model='manualForm.account_no' class='border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.paymentInfo' />
            </div>
            <div class='mt-3 flex gap-2'>
              <Button variant='subtle' :loading='saving' @click='saveManual(false)'>{{ T.saveDraft }}</Button>
              <Button variant='solid' :loading='saving' @click='saveManual(true)'>{{ T.submitApproval }}</Button>
            </div>
          </div>

          <div class='grid grid-cols-1 gap-3 xl:grid-cols-5'>
            <div v-for='column in STATUS_COLUMNS' :key='column.key' class='rounded border border-gray-200 bg-gray-50'>
              <div class='flex items-center justify-between border-b border-gray-200 px-3 py-2 text-sm font-medium'>
                <span>{{ column.label }}</span>
                <span class='rounded bg-white px-2 py-0.5 text-xs text-gray-500'>{{ rowsForStatus(column.key).length }}</span>
              </div>
              <div class='space-y-2 p-2 min-h-[160px]'>
                <button v-for='row in rowsForStatus(column.key)' :key='row.name' type='button'
                  class='block w-full rounded border border-gray-200 bg-white p-3 text-left hover:border-gray-400'
                  :class="selectedRequest?.name === row.name ? 'ring-1 ring-gray-900' : ''"
                  @click='selectedRequestName = row.name'>
                  <div class='flex items-start justify-between gap-2'>
                    <div class='font-medium text-gray-900'>{{ row.name }}</div>
                    <div class='text-right text-sm font-semibold tabular-nums'>{{ fmtAmount(row.amount) }}</div>
                  </div>
                  <div class='mt-1 text-xs text-gray-500'>{{ row.subject }}</div>
                  <div class='mt-2 flex flex-wrap gap-1 text-[11px] text-gray-500'>
                    <span class='rounded bg-gray-100 px-1.5 py-0.5'>{{ row.department || '-' }}</span>
                    <span class='rounded bg-gray-100 px-1.5 py-0.5'>{{ row.employee_name || '-' }}</span>
                    <span v-if='row.from_consumption' class='rounded bg-blue-50 px-1.5 py-0.5 text-blue-700'>{{ T.pushDown }}</span>
                  </div>
                </button>
                <div v-if='!rowsForStatus(column.key).length' class='py-8 text-center text-xs text-gray-400'>{{ T.empty }}</div>
              </div>
            </div>
          </div>
        </Card>

        <Card v-if='selectedRequest' :title='T.detail'>
          <div class='grid grid-cols-1 gap-3 text-sm md:grid-cols-4'>
            <div><span class='text-gray-500'>{{ T.subject }}</span><div class='font-medium'>{{ selectedRequest.subject }}</div></div>
            <div><span class='text-gray-500'>{{ T.status }}</span><div class='font-medium'>{{ selectedRequest.workflow_status }}</div></div>
            <div><span class='text-gray-500'>{{ T.current }}</span><div class='font-medium'>{{ selectedRequest.current_step_label || '-' }}</div></div>
            <div><span class='text-gray-500'>{{ T.amount }}</span><div class='font-medium'>{{ fmtAmount(selectedRequest.amount) }}</div></div>
          </div>
          <div class='mt-4 overflow-x-auto'>
            <table class='w-full min-w-[760px] text-sm'>
              <thead class='border-b text-gray-500'><tr><th class='px-2 py-2 text-left'>{{ T.expenseDate }}</th><th class='px-2 py-2 text-left'>{{ T.category }}</th><th class='px-2 py-2 text-left'>{{ T.description }}</th><th class='px-2 py-2 text-right'>{{ T.amount }}</th><th class='px-2 py-2 text-left'>{{ T.status }}</th></tr></thead>
              <tbody>
                <tr v-for='line in selectedRequest.expense_lines || []' :key='line.category + line.amount' class='border-b last:border-0'>
                  <td class='px-2 py-2'>{{ line.start_date || '-' }}</td>
                  <td class='px-2 py-2'>{{ line.category }}</td>
                  <td class='px-2 py-2'>{{ line.description }}</td>
                  <td class='px-2 py-2 text-right tabular-nums'>{{ fmtAmount(line.amount) }}</td>
                  <td class='px-2 py-2'>{{ line.invoice_status || '-' }} / {{ line.attachment_count || 0 }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class='mt-4 flex flex-wrap gap-2'>
            <Button v-if='selectedRequest.kanban_status === "draft"' variant='solid' @click='submitDraft(selectedRequest)'>{{ T.submitApproval }}</Button>
            <Button v-if='selectedRequest.can_mark_paid' variant='solid' @click='markPaid(selectedRequest)'>{{ T.markPaid }}</Button>
          </div>
        </Card>
      </template>

      <template v-if='purchaseTab === "consumption"'>
        <div class='grid grid-cols-1 gap-4 xl:grid-cols-[1fr_420px]'>
          <Card :title='T.consumption'>
            <div class='mb-4 rounded border border-gray-200 bg-gray-50 p-3'>
              <div class='grid grid-cols-1 gap-3 md:grid-cols-5'>
                <input v-model='consumptionForm.title' class='border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.subject' />
                <select v-model='consumptionForm.category' class='border border-gray-300 rounded px-3 py-2 text-sm'><option v-for='item in expenseCategories' :key='item'>{{ item }}</option></select>
                <input v-model='consumptionForm.amount' type='number' min='0' step='0.01' class='border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.amount' />
                <input v-model='consumptionForm.expense_date' type='date' class='border border-gray-300 rounded px-3 py-2 text-sm' />
                <select v-model='consumptionForm.department' class='border border-gray-300 rounded px-3 py-2 text-sm'><option v-for='item in departments' :key='item'>{{ item }}</option></select>
              </div>
              <div class='mt-3 flex gap-2'>
                <input v-model='consumptionForm.description' class='flex-1 border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.description' />
                <Button variant='solid' @click='saveConsumption'>{{ T.newConsumption }}</Button>
              </div>
            </div>

            <div class='space-y-2'>
              <div v-for='row in consumptionList' :key='row.name' class='flex items-center gap-3 rounded border border-gray-200 bg-white p-3'>
                <input type='checkbox' :checked='pushSelection.includes(row.name)' :disabled='!pushableConsumption.some((item) => item.name === row.name)' @change='togglePush(row.name)' />
                <button type='button' class='flex-1 text-left' @click='selectedConsumptionName = row.name'>
                  <div class='font-medium text-gray-900'>{{ row.title }}</div>
                  <div class='text-xs text-gray-500'>{{ row.expense_date }} / {{ row.department }} / {{ row.category }} / {{ row.invoice_count }} {{ T.addInvoice }}</div>
                </button>
                <div class='text-right'>
                  <div class='font-semibold tabular-nums'>{{ fmtAmount(row.amount) }}</div>
                  <div class='text-xs text-gray-500'>{{ row.status }}</div>
                </div>
              </div>
              <div v-if='!consumptionList.length' class='py-10 text-center text-sm text-gray-400'>{{ T.empty }}</div>
            </div>
          </Card>

          <div class='space-y-4'>
            <Card :title='T.addInvoice'>
              <template v-if='selectedConsumption'>
                <div class='mb-3 text-sm'>
                  <div class='font-medium'>{{ selectedConsumption.title }}</div>
                  <div class='text-xs text-gray-500'>{{ selectedConsumption.status }} / {{ fmtAmount(selectedConsumption.amount) }}</div>
                </div>
                <div class='mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800'>{{ T.invoiceRestriction }}</div>
                <div class='flex gap-2'>
                  <input v-model='invoiceForm.invoice_name' class='min-w-0 flex-1 border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.invoiceName' />
                  <input type='file' class='hidden' id='oa-invoice-file' accept='.pdf,.jpg,.jpeg,.png' @change='addInvoiceFromInput' />
                  <label for='oa-invoice-file' class='rounded border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50'>{{ T.addInvoice }}</label>
                </div>
                <div class='mt-2'>
                  <Button variant='subtle' :disabled='!invoiceForm.invoice_name.trim()' @click='addInvoice'>{{ T.addInvoice }}</Button>
                </div>
                <div class='mt-4 space-y-2'>
                  <div v-for='invoice in selectedConsumption.invoices || []' :key='invoice.invoice_name' class='rounded border border-gray-200 p-2 text-sm'>
                    <div class='font-medium'>{{ invoice.invoice_name }}</div>
                    <div class='text-xs text-gray-500'>{{ invoice.file_size || '-' }} / {{ invoice.invoice_status }}</div>
                  </div>
                  <div v-if='!(selectedConsumption.invoices || []).length' class='text-sm text-gray-400'>{{ T.empty }}</div>
                </div>
              </template>
              <div v-else class='text-sm text-gray-400'>{{ T.empty }}</div>
            </Card>

            <Card :title='T.pushDown'>
              <div class='space-y-2'>
                <select v-model='pushPayment.company' class='w-full border border-gray-300 rounded px-3 py-2 text-sm'><option v-for='item in companies' :key='item'>{{ item }}</option></select>
                <select v-model='pushPayment.department' class='w-full border border-gray-300 rounded px-3 py-2 text-sm'><option v-for='item in departments' :key='item'>{{ item }}</option></select>
                <input v-model='pushPayment.subject' class='w-full border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.subject' />
                <input v-model='pushPayment.payee_name' class='w-full border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.applicant' />
                <input v-model='pushPayment.account_no' class='w-full border border-gray-300 rounded px-3 py-2 text-sm' :placeholder='T.paymentInfo' />
              </div>
              <div class='mt-3 flex gap-2'>
                <Button variant='subtle' :disabled='!pushSelection.length' @click='pushSelected(false)'>{{ T.pushDown }}</Button>
                <Button variant='solid' :disabled='!pushSelection.length' @click='pushSelected(true)'>{{ T.pushAndSubmit }}</Button>
              </div>
            </Card>
          </div>
        </div>
      </template>

      <template v-if='purchaseTab === "pending"'>
        <Card :title='T.pendingTitle'>
          <div class='mb-3 flex flex-col md:flex-row gap-2'>
            <input v-model='actionNote' class='border border-gray-300 rounded px-3 py-2 text-sm flex-1' :placeholder='T.note' />
          </div>
          <div class='overflow-x-auto'>
            <table class='w-full text-sm min-w-[760px]'>
              <thead class='text-gray-500 border-b'>
                <tr><th class='text-left px-3 py-2'>{{ T.subject }}</th><th class='text-left px-3 py-2'>{{ T.applicant }}</th><th class='text-left px-3 py-2'>{{ T.current }}</th><th class='text-right px-3 py-2'>{{ T.action }}</th></tr>
              </thead>
              <tbody>
                <tr v-for='row in pending.data || []' :key='row.name' class='border-b last:border-0 hover:bg-gray-50'>
                  <td class='px-3 py-2'>{{ row.subject }}</td>
                  <td class='px-3 py-2'>{{ row.employee_name }}</td>
                  <td class='px-3 py-2'>{{ row.current_step_label }}</td>
                  <td class='px-3 py-2 text-right whitespace-nowrap'>
                    <button class='text-green-700 hover:underline mr-3' @click='act(row, "approve")'>{{ row.current_step_mode === 'handle' ? T.handle : T.approve }}</button>
                    <button v-if='row.current_step_mode !== "handle"' class='text-red-600 hover:underline' @click='act(row, "reject")'>{{ T.reject }}</button>
                  </td>
                </tr>
                <tr v-if='!(pending.data || []).length'><td colspan='4' class='text-center text-gray-400 py-6'>{{ T.empty }}</td></tr>
              </tbody>
            </table>
          </div>
        </Card>
      </template>

      <template v-if='purchaseTab === "flow"'>
        <Card :title='T.routeTitle'>
          <div v-if='preview.loading' class='text-sm text-gray-500 py-4'>...</div>
          <ol v-else class='grid grid-cols-1 gap-2 md:grid-cols-2'>
            <li v-for='step in routeSteps' :key='step.step_index' class='rounded border border-gray-200 px-3 py-2'>
              <div class='flex items-center justify-between gap-2'>
                <span class='font-medium text-gray-900'>{{ step.step_index }}. {{ step.label }}</span>
                <span class='text-xs rounded bg-gray-100 px-2 py-1 text-gray-600'>{{ modeLabel(step.mode) }}</span>
              </div>
              <div class='text-xs text-gray-500 mt-1'>{{ step.approvers.join(' / ') }}</div>
            </li>
          </ol>
        </Card>
      </template>
    </template>

    <template v-if='isLeave'>
      <Card :title='T.pendingTitle'>
        <div class='mb-3 flex flex-col md:flex-row gap-2'>
          <input v-model='actionNote' class='border border-gray-300 rounded px-3 py-2 text-sm flex-1' :placeholder='T.note' />
        </div>
        <div class='overflow-x-auto'>
          <table class='w-full text-sm min-w-[760px]'>
            <thead class='text-gray-500 border-b'>
              <tr><th class='text-left px-3 py-2'>{{ T.subject }}</th><th class='text-left px-3 py-2'>{{ T.applicant }}</th><th class='text-left px-3 py-2'>{{ T.current }}</th><th class='text-right px-3 py-2'>{{ T.action }}</th></tr>
            </thead>
            <tbody>
              <tr v-for='row in pending.data || []' :key='row.name' class='border-b last:border-0 hover:bg-gray-50'>
                <td class='px-3 py-2'>{{ row.subject }}</td>
                <td class='px-3 py-2'>{{ row.employee_name }}</td>
                <td class='px-3 py-2'>{{ row.current_step_label }}</td>
                <td class='px-3 py-2 text-right whitespace-nowrap'>
                  <button class='text-green-700 hover:underline mr-3' @click='act(row, "approve")'>{{ row.current_step_mode === 'handle' ? T.handle : T.approve }}</button>
                  <button v-if='row.current_step_mode !== "handle"' class='text-red-600 hover:underline' @click='act(row, "reject")'>{{ T.reject }}</button>
                </td>
              </tr>
              <tr v-if='!(pending.data || []).length'><td colspan='4' class='text-center text-gray-400 py-6'>{{ T.empty }}</td></tr>
            </tbody>
          </table>
        </div>
      </Card>
    </template>
  </div>
</template>
