<script setup>
import { Button, Card, createResource } from 'frappe-ui';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import ExpenseWorkbench from '../components/ExpenseWorkbench.vue';

const REQUEST_LEAVE = '\u8bf7\u5047\u7533\u8bf7';
const REQUEST_OVERTIME = '加班申请';
const REQUEST_COMP_TIME = '调休申请';
const ATTENDANCE_TYPES = [REQUEST_LEAVE, REQUEST_OVERTIME, REQUEST_COMP_TIME];
const REQUEST_EXPENSE_PAYMENT = '\u8d39\u7528\u4ed8\u6b3e\u7533\u8bf7';
const ASSET_ADMIN = '非电子类固定资产（人事/行政）';
const ASSET_IT = '电子类固定资产（IT）';
const ASSET_OTHER = '其他';

const PAGE_CONFIG = {
  '/approval/overtime': { requestType: REQUEST_OVERTIME, title: '加班审批', formTitle: '新建加班申请' },
  '/approval/comp-time': { requestType: REQUEST_COMP_TIME, title: '调休审批', formTitle: '新建调休申请' },
  '/approval/leave': {
    requestType: REQUEST_LEAVE,
    title: '\u8bf7\u5047\u5ba1\u6279',
    formTitle: '\u65b0\u5efa\u8bf7\u5047\u7533\u8bf7',
  },
  '/approval/purchase': {
    requestType: REQUEST_EXPENSE_PAYMENT,
    title: '\u8d39\u7528\u4ed8\u6b3e/\u62a5\u9500',
    formTitle: '\u8d39\u7528\u4ed8\u6b3e/\u62a5\u9500\u5de5\u4f5c\u53f0',
  },
  '/approval/reimbursement': {
    requestType: REQUEST_EXPENSE_PAYMENT,
    title: '付款/报销',
    formTitle: '付款/报销工作台',
  },
  '/approval/corporate-payment': {
    requestType: REQUEST_EXPENSE_PAYMENT,
    title: '付款/报销',
    formTitle: '付款/报销工作台',
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
const router = useRouter();
const attendanceBase = computed(() => route.path.startsWith('/approval/overtime') ? '/approval/overtime' : route.path.startsWith('/approval/comp-time') ? '/approval/comp-time' : '/approval/leave');
const pageConfig = computed(() => PAGE_CONFIG[route.path] || PAGE_CONFIG[attendanceBase.value]);
const currentRequestType = computed(() => pageConfig.value.requestType);
const isLeave = computed(() => ATTENDANCE_TYPES.includes(currentRequestType.value));
const isLeaveInnerPage = computed(() => isLeave.value && Boolean(route.params.name || route.query.request));
const isPurchase = computed(() => currentRequestType.value === REQUEST_EXPENSE_PAYMENT);

const leaveForm = reactive({
  leave_type: '事假',
  attendance_days: [],
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
const rejectTargetByRequest = reactive({});
const purchaseTab = ref('board');
const showManualForm = ref(false);
const selectedRequestName = ref('');
const selectedLeaveName = ref('');
const leaveDraftName = ref('');
const lastAutoHydratedDraft = ref('');
let leaveRefreshTimer = null;
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
const leaveDetailLoader = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_requests',
  method: 'GET',
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
const leaveDraftUpdater = createResource({ url: 'rayher_hr_payroll.api.oa_entry.update_leave_draft' });
const actor = createResource({ url: 'rayher_hr_payroll.api.oa_entry.action_request' });
const draftSubmitter = createResource({ url: 'rayher_hr_payroll.api.oa_entry.submit_request' });
const withdrawer = createResource({ url: 'rayher_hr_payroll.api.oa_entry.withdraw_request' });
const attendanceOptions = createResource({ url: 'rayher_hr_payroll.api.oa_entry.get_attendance_options', method: 'GET' });
const attendanceBalance = ref(null);
const annualBalance = ref(null);
const annualLeaveBlocked = computed(() => currentRequestType.value === REQUEST_LEAVE && leaveForm.leave_type === "年假" && (!annualBalance.value?.eligible || attendanceHours.value > Number(annualBalance.value?.available_hours || 0)));
const leaveTypes = ref([]);
let attendanceVersion = 0;
let hydratingAttendance = false;
const attendanceHours = computed(() => Math.round(leaveForm.attendance_days.reduce((total, day) => total + Number(day.hours || 0), 0) * 100) / 100);
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
const copiedTo = computed(() => preview.data?.copied_to || []);
const requestRows = computed(() => purchaseRequests.data || []);
const selectedRequest = computed(() => requestRows.value.find((row) => row.name === selectedRequestName.value) || requestRows.value[0]);
const consumptionList = computed(() => consumptionRows.data || []);
const selectedConsumption = computed(() => consumptionList.value.find((row) => row.name === selectedConsumptionName.value) || consumptionList.value[0]);
const pushableConsumption = computed(() => consumptionList.value.filter((row) => row.status === '\u5f85\u4e0b\u63a8' || row.status === '\u5df2\u4e0a\u4f20\u53d1\u7968'));
const leaveRows = computed(() => {
  const rows = [...(pending.data || []), ...(mine.data || [])];
  return [...new Map(rows.map((row) => [row.name, row])).values()];
});
const leavePendingCount = computed(() => (pending.data || []).length);
const leaveMineCount = computed(() => (mine.data || []).length);
const selectedLeave = computed(() => {
  const requested = String(route.params.name || route.query.request || selectedLeaveName.value || '');
  return leaveRows.value.find((row) => row.name === requested)
    || (leaveDetailLoader.data?.name === requested ? leaveDetailLoader.data : null);
});

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
      request_type: currentRequestType.value,
      subject: leaveForm.subject.trim(),
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
  await Promise.allSettled([mine.reload(), pending.reload(), previewRoute(), refreshAttendance(false)]);
}

async function refreshAttendance(replaceDays = true) {
  if (!isLeave.value) return;
  const version = ++attendanceVersion;
  try {
    const data = await attendanceOptions.fetch({ request_type: currentRequestType.value, from_date: leaveForm.from_date || "", to_date: leaveForm.to_date || "" });
    if (version !== attendanceVersion) return;
    attendanceBalance.value = data.balance;
    annualBalance.value = data.annual_balance;
    leaveTypes.value = data.leave_types || [];
    if (replaceDays) leaveForm.attendance_days = data.days || [];
  } catch (error) {
    if (version !== attendanceVersion) return;
    if (replaceDays) leaveForm.attendance_days = [];
    annualBalance.value = null;
    errMsg.value = serverMessage(error, T.loadFailed);
  }
}

async function withdrawAttendance(row) {
  saving.value = true;
  errMsg.value = '';
  try {
    await withdrawer.submit({ name: row.name });
    await reloadLists();
    await loadLeaveDetail(row.name);
    message.value = '已撤回，工时上限和调休余额已重新计算';
  } catch (error) { errMsg.value = serverMessage(error, T.actionFailed); }
  finally { saving.value = false; }
}

function validateLeave() {
  return Boolean(!attendanceOptions.loading && !annualLeaveBlocked.value && attendanceHours.value > 0 && leaveForm.subject.trim() && leaveForm.department.trim() && leaveForm.supervisor.trim() && leaveForm.from_date && leaveForm.to_date);
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

function leaveDays(row) {
  if (row?.duration_hours != null && Number(row.duration_hours) > 0) return `${Number(row.duration_hours)} 小时 / ${Number((Number(row.duration_hours) / 8).toFixed(2))} 天`;
  if (!row?.from_date || !row?.to_date) return '-';
  const start = new Date(`${row.from_date}T00:00:00`);
  const end = new Date(`${row.to_date}T00:00:00`);
  const days = Math.floor((end - start) / 86400000) + 1;
  return days > 0 ? `${days} 天` : '-';
}

function formatEventTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '-';
}

function rejectionEvent(row) {
  return [...(row?.operation_log || [])].reverse().find((event) => (
    ['Targeted rejection', '定向驳回'].includes(event?.action)
  )) || null;
}

function eventActor(event) {
  return event?.details?.actor || event?.actor || event?.user || '-';
}

function selectLeave(row) {
  if (!row?.name) return;
  selectedLeaveName.value = row.name;
  router.push(`${attendanceBase.value}/${encodeURIComponent(row.name)}`);
}

async function loadLeaveDetail(name) {
  const requested = String(name || '').trim();
  if (!requested || !isLeave.value) return;
  try {
    const rows = await leaveDetailLoader.fetch({
      view: 'all',
      request_type: currentRequestType.value,
      name: requested,
      limit: 1,
    }) || [];
    const row = Array.isArray(rows) ? rows[0] : rows;
    if (row?.name === requested) leaveDetailLoader.data = row;
  } catch (error) {
    if (!selectedLeave.value) errMsg.value = serverMessage(error, T.loadFailed);
  }
}

function hydrateLeaveDraft(row) {
  if (!row || row.kanban_status !== 'draft') return;
  if (isLeaveInnerPage.value) router.push(attendanceBase.value);
  hydratingAttendance = Boolean(row.attendance_days?.length && (leaveForm.from_date !== row.from_date || leaveForm.to_date !== row.to_date));
  leaveDraftName.value = row.name;
  Object.assign(leaveForm, {
    leave_type: row.leave_type || '事假',
    attendance_days: (row.attendance_days || []).map((day) => ({ ...day })),
    subject: row.subject || '',
    department: row.department || leaveForm.department,
    supervisor: row.supervisor || leaveForm.supervisor,
    from_date: row.from_date || '',
    to_date: row.to_date || '',
    reason: row.reason || '',
  });
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
    const fields = {
      subject: leaveForm.subject.trim(),
      from_date: leaveForm.from_date,
      to_date: leaveForm.to_date,
      attendance_days: JSON.stringify(leaveForm.attendance_days),
      leave_type: currentRequestType.value === REQUEST_LEAVE ? leaveForm.leave_type : '',
      reason: leaveForm.reason.trim(),
    };
    if (leaveDraftName.value) {
      const name = leaveDraftName.value;
      await leaveDraftUpdater.submit({ name, ...fields });
      await draftSubmitter.submit({ name });
    } else {
      await creator.submit({ request_type: currentRequestType.value, ...fields });
    }
    message.value = T.saved;
    Object.assign(leaveForm, { subject: '', from_date: '', to_date: '', reason: '', attendance_days: [] });
    leaveDraftName.value = '';
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
    const params = { name: row.name, action, note: actionNote.value.trim() };
    if (action === 'reject') {
      if (!params.note) throw new Error('驳回原因必填');
      params.reject_target = rejectTargetByRequest[row.name] || row.rejection_targets?.[0]?.target || 'applicant';
    }
    await actor.submit(params);
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
watch([() => leaveForm.from_date, () => leaveForm.to_date], () => {
  if (hydratingAttendance) { hydratingAttendance = false; refreshAttendance(false); return; }
  refreshAttendance(true);
});
watch(currentRequestType, () => {
  leaveDraftName.value = '';
  lastAutoHydratedDraft.value = '';
  leaveDetailLoader.data = null;
  Object.assign(leaveForm, { subject: '', from_date: '', to_date: '', reason: '', attendance_days: [] });
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
watch(leaveRows, (rows) => {
  const requested = String(route.query.request || '');
  if (requested && rows.some((row) => row.name === requested)) {
    selectedLeaveName.value = requested;
  } else if (!rows.some((row) => row.name === selectedLeaveName.value)) {
    selectedLeaveName.value = rows[0]?.name || '';
  }
  const returnedDraft = (mine.data || []).find((row) => row.kanban_status === 'draft' && rejectionEvent(row));
  if (returnedDraft && returnedDraft.name !== lastAutoHydratedDraft.value) {
    lastAutoHydratedDraft.value = returnedDraft.name;
    selectedLeaveName.value = returnedDraft.name;
    hydrateLeaveDraft(returnedDraft);
  }
}, { immediate: true });
watch(() => route.query.request, (name) => {
  if (name) {
    selectedLeaveName.value = String(name);
    loadLeaveDetail(name);
  }
});
watch(() => route.params.name, (name) => {
  if (name) {
    selectedLeaveName.value = String(name);
    loadLeaveDetail(name);
  }
}, { immediate: true });
watch(leaveRows, (rows) => {
  const requested = String(route.params.name || route.query.request || '');
  if (requested && !rows.some((row) => row.name === requested)) loadLeaveDetail(requested);
});
onMounted(() => {
  refreshAttendance(false);
  leaveRefreshTimer = window.setInterval(() => {
    if (isLeave.value && !saving.value && document.visibilityState === 'visible') reloadLists();
  }, 10000);
});
onBeforeUnmount(() => {
  if (leaveRefreshTimer) window.clearInterval(leaveRefreshTimer);
});
</script>

<template>
  <div class='oa-page space-y-4'>
    <div v-if='isLeave' class='oa-header flex flex-col gap-3 border-b border-gray-200 pb-4 md:flex-row md:items-end md:justify-between'>
      <div>
        <router-link v-if='isLeaveInnerPage' :to='attendanceBase' class='mb-2 inline-flex items-center gap-1 text-sm font-medium text-gray-500 hover:text-gray-900'>← 返回{{ pageConfig.title }}</router-link>
        <div v-if='isLeaveInnerPage && selectedLeave' class='oa-kicker'>{{ selectedLeave.name }} · {{ selectedLeave.workflow_status }}</div>
        <h2 class='text-xl font-semibold text-gray-950'>{{ isLeaveInnerPage ? currentRequestType : pageConfig.title }}</h2>
        <p class='mt-1 text-sm text-gray-500'>{{ isLeaveInnerPage ? (selectedLeave ? `审批详情 · 当前节点：${selectedLeave.current_step_label || '已结束'}` : '正在加载请假单详情…') : '提交申请、查看本人记录与待审批事项' }}</p>
      </div>
      <div class='flex items-center gap-2'>
        <router-link v-if='isLeaveInnerPage' :to='attendanceBase' class='oa-primary inline-flex h-9 items-center gap-2 rounded-md px-4 text-sm font-semibold text-white'>＋ 新建{{ currentRequestType }}</router-link>
        <Button variant='subtle' @click='reloadLists'>{{ T.refresh }}</Button>
      </div>
    </div>

    <template v-if='isLeave'>
      <nav class='flex gap-4 text-sm'><router-link to='/approval/leave'>请假</router-link><router-link to='/approval/overtime'>加班</router-link><router-link to='/approval/comp-time'>调休</router-link></nav>
      <p v-if='errMsg' class='text-sm text-red-700'>{{ errMsg }}</p>
      <p v-if='attendanceBalance' class='rounded border bg-white p-3 text-sm'>调休可用：<strong>{{ attendanceBalance.available_hours }} 小时</strong> · 加班累计：{{ attendanceBalance.credit_hours }} · 申请中占用：{{ attendanceBalance.reserved_hours }} · 已用：{{ attendanceBalance.used_hours }}<span v-if='attendanceBalance.available_hours < 0' class='ml-2 text-red-700'>余额不足，请联系人事处理</span></p>
      <div v-if='currentRequestType === REQUEST_LEAVE && annualBalance' class='rounded border bg-white p-3 text-sm space-y-1' role='region' aria-label='我的年假余额'>
        <p>我的年假可用：<strong>{{ annualBalance.available_hours }} 小时 / {{ Number((annualBalance.available_hours / 8).toFixed(2)) }} 天</strong></p>
        <p>累计发放：{{ annualBalance.credit_hours }} 小时 · 申请中占用：{{ annualBalance.reserved_hours }} 小时 · 已用：{{ annualBalance.used_hours }} 小时</p>
        <p class='text-gray-600'>入职满12个月发放5天，此后每个入职周年增加5天；未用余额累计保留，不清零。<span v-if='annualBalance.next_grant_date'>下次发放：{{ annualBalance.next_grant_date }}</span></p>
        <p v-if='annualBalance.eligibility_message' class='text-amber-700'>{{ annualBalance.eligibility_message }}</p>
        <p v-else-if='annualBalance.available_hours <= 0' class='text-amber-700'>当前没有可用年假余额。</p>
      </div>
      <section v-if='!isLeaveInnerPage' class='oa-overview-strip' :aria-label='pageConfig.title + "概览"'>
        <div class='oa-overview-primary'>
          <div class='oa-overview-label'>我的待办</div>
          <div class='oa-overview-value'>{{ leavePendingCount }}<span>项</span></div>
          <div class='oa-overview-caption'>只显示当前账号需要处理的审批</div>
        </div>
        <div class='oa-overview-stat'><span>我的申请</span><strong>{{ leaveMineCount }}</strong><small>全部状态</small></div>
        <div class='oa-overview-stat'><span>当前节点</span><strong>{{ leavePendingCount ? '待处理' : '已清空' }}</strong><small>{{ leavePendingCount ? '请先查看待办详情' : '暂无新的审批任务' }}</small></div>
      </section>
      <div v-if='!isLeaveInnerPage' class='oa-list-top grid grid-cols-1 xl:grid-cols-3 gap-4 items-start'>
        <Card :title='pageConfig.formTitle' class='oa-panel oa-form-panel xl:col-span-2'>
          <div class='grid grid-cols-1 md:grid-cols-2 gap-3'>
            <label class='flex flex-col gap-1 text-sm'>
              <span class='text-xs text-gray-500'>{{ T.subject }}</span>
              <input v-model='leaveForm.subject' class='border border-gray-300 rounded px-3 py-2' />
            </label>
            <label class='flex flex-col gap-1 text-sm'>
              <span class='text-xs text-gray-500'>{{ T.department }}</span>
              <input v-model='leaveForm.department' readonly class='border border-gray-200 bg-gray-50 rounded px-3 py-2 text-gray-600' />
            </label>
            <label class='flex flex-col gap-1 text-sm'>
              <span class='text-xs text-gray-500'>{{ T.supervisor }}</span>
              <input v-model='leaveForm.supervisor' readonly class='border border-gray-200 bg-gray-50 rounded px-3 py-2 text-gray-600' />
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
          <div class='mt-4 space-y-3'>
            <label v-if='currentRequestType === REQUEST_LEAVE' class='flex items-center gap-3 text-sm'>请假类型<select v-model='leaveForm.leave_type' class='rounded border px-3 py-2'><option v-for='item in leaveTypes' :key='item'>{{ item }}</option></select></label>
            <p class='text-sm text-gray-600'>{{ currentRequestType === REQUEST_LEAVE ? (leaveForm.leave_type === '事假' ? '事假审批完成后扣减工时上限：半天＝4小时，工作日上限减0.5天；跨月分别计算。' : '此类请假不扣减月度工作日和工时上限。年假另外占用、扣减年假余额。') : currentRequestType === REQUEST_OVERTIME ? '提交申请即按1:1增加调休额度，不增加月度工时上限。' : '提交占用额度，审批通过后正式扣减；不减少月度工时上限。' }}</p>
            <p v-if='currentRequestType === REQUEST_LEAVE && leaveForm.leave_type === "年假" && annualLeaveBlocked' class='text-sm text-amber-700'>{{ annualBalance?.eligibility_message || '年假可用余额不足，不能提交本次申请。' }}</p>
            <div class='max-h-64 overflow-auto rounded border'><div v-for='day in leaveForm.attendance_days' :key='day.work_date' class='flex items-center justify-between border-b px-3 py-2 text-sm'><label :for='`hours-${day.work_date}`'>{{ day.work_date }}</label><div><input :id='`hours-${day.work_date}`' v-model='day.hours' type='number' min='0' :max='currentRequestType === REQUEST_OVERTIME ? 24 : 8' step='0.01' class='w-24 rounded border px-2 py-1 text-right' /> 小时</div></div></div>
            <p class='text-sm'>合计 {{ attendanceHours }} 小时 / {{ Number((attendanceHours / 8).toFixed(2)) }} 天（1天＝8小时）</p>
          </div>
          <div v-if='leaveDraftName' class='mt-3 rounded border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800'>正在编辑：{{ leaveDraftName }}</div>
          <div class='mt-3 flex items-center gap-3'>
            <Button variant='solid' :loading='saving' :disabled='attendanceOptions.loading || !attendanceHours || annualLeaveBlocked' @click='submitLeaveRequest'>{{ T.submit }}</Button>
            <span v-if='message' class='text-sm text-green-600'>{{ message }}</span>
            <span v-if='errMsg' class='text-sm text-red-600'>{{ errMsg }}</span>
          </div>
        </Card>

        <Card :title='T.routeTitle' class='oa-panel oa-flow-panel'>
          <div v-if='preview.loading' class='text-sm text-gray-500 py-4'>...</div>
          <div v-else-if='!routeSteps.length' class='oa-empty-flow text-sm text-gray-400 py-4'>填写部门和直属主管后，这里会显示实际审批路径</div>
          <ol v-else class='space-y-2'>
            <li v-for='step in routeSteps' :key='step.step_index' class='oa-route-step rounded border border-gray-200 px-3 py-2'>
              <div class='flex items-center justify-between gap-2'>
                <span class='font-medium text-gray-900'>{{ step.step_index }}. {{ step.label }}</span>
                <span class='text-xs rounded bg-gray-100 px-2 py-1 text-gray-600'>{{ modeLabel(step.mode) }}</span>
              </div>
              <div class='text-xs text-gray-500 mt-1'>{{ step.approvers.join(' / ') }}</div>
            </li>
          </ol>
          <div v-if='copiedTo.length' class='mt-3 rounded border border-blue-100 bg-blue-50 px-3 py-2 text-sm text-blue-800'>
            抄送：{{ copiedTo.map((row) => row.label).join('、') }}
          </div>
        </Card>
      </div>

      <Card v-if='!isLeaveInnerPage' :title='T.mineTitle' class='oa-panel oa-table-panel oa-mine-panel'>
        <div class='overflow-x-auto'>
          <table class='oa-table w-full table-fixed text-sm'>
            <thead class='border-b text-gray-500'>
              <tr><th class='px-3 py-2 text-left'>{{ T.subject }}</th><th class='px-3 py-2 text-left'>申请日期</th><th class='px-3 py-2 text-left'>{{ T.status }}</th><th class='px-3 py-2 text-left'>最近驳回</th><th class='px-3 py-2 text-right'>{{ T.action }}</th></tr>
            </thead>
            <tbody>
              <tr v-for='row in mine.data || []' :key='row.name' class='border-b last:border-0' :class='row.kanban_status === "draft" && rejectionEvent(row) ? "bg-amber-50" : ""'>
                <td class='px-3 py-2'><div class='font-medium'>{{ row.subject }}</div><div class='text-xs text-gray-500'>{{ row.name }}</div></td>
                <td class='px-3 py-2'>{{ row.from_date || '-' }} 至 {{ row.to_date || '-' }}<div class='text-xs text-gray-500'>{{ leaveDays(row) }}</div></td>
                <td class='px-3 py-2'><span class='oa-status-pill' :class='row.kanban_status'>{{ row.workflow_status }}</span></td>
                <td class='px-3 py-2 text-xs'><template v-if='rejectionEvent(row)'>{{ eventActor(rejectionEvent(row)) }} · {{ rejectionEvent(row).note }}<div class='text-gray-500'>{{ formatEventTime(rejectionEvent(row).timestamp || rejectionEvent(row).acted_on) }}</div></template><span v-else>-</span></td>
                <td class='px-3 py-2 text-right'><button class='mr-3 text-gray-700 hover:underline' @click='selectLeave(row)'>查看</button><button v-if='row.kanban_status === "draft"' class='text-blue-700 hover:underline' @click='hydrateLeaveDraft(row)'>编辑</button></td>
              </tr>
              <tr v-if='!(mine.data || []).length'><td colspan='5' class='py-6 text-center text-gray-400'>{{ T.empty }}</td></tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card v-if='!isLeaveInnerPage' :title='T.pendingTitle' class='oa-panel oa-table-panel oa-pending-panel'>
        <div class='overflow-x-auto'>
          <table class='oa-table w-full table-fixed text-sm'>
            <thead class='border-b text-gray-500'><tr><th class='px-3 py-2 text-left'>申请</th><th class='px-3 py-2 text-left'>申请人/部门</th><th class='px-3 py-2 text-left'>申请日期</th><th class='px-3 py-2 text-left'>事由</th><th class='px-3 py-2 text-left'>当前节点</th><th class='px-3 py-2 text-right'>操作</th></tr></thead>
            <tbody>
              <tr v-for='row in pending.data || []' :key='row.name' class='border-b last:border-0'>
                <td class='px-3 py-2'><div class='font-medium'>{{ row.subject }}</div><div class='text-xs text-gray-500'>{{ row.name }}</div></td>
                <td class='px-3 py-2'>{{ row.employee_name }}<div class='text-xs text-gray-500'>{{ row.department }}</div></td>
                <td class='px-3 py-2'>{{ row.from_date || '-' }} 至 {{ row.to_date || '-' }}<div class='text-xs text-gray-500'>{{ leaveDays(row) }}</div></td>
                <td class='oa-reason-cell px-3 py-2 text-gray-700' :title='row.reason || ""'>{{ row.reason || '-' }}</td>
                <td class='px-3 py-2'><span class='oa-node-pill'>{{ row.current_step_label || '待处理' }}</span></td>
                <td class='px-3 py-2 text-right'><button class='text-blue-700 hover:underline' @click='selectLeave(row)'>查看详情</button></td>
              </tr>
              <tr v-if='!(pending.data || []).length'><td colspan='6' class='py-6 text-center text-gray-400'>{{ T.empty }}</td></tr>
            </tbody>
          </table>
        </div>
      </Card>

      <section v-if='isLeaveInnerPage && selectedLeave' class='oa-detail-panel'>
        <div class='oa-detail-heading flex flex-wrap items-start justify-between gap-3'><div><div class='oa-kicker'>{{ currentRequestType }}详情</div><h3 class='mt-1 text-xl font-semibold text-gray-950'>{{ selectedLeave.subject || '未填写主题' }}</h3><p class='mt-1 text-sm text-gray-500'>{{ selectedLeave.employee_name }} · {{ selectedLeave.department }}</p></div><div class='oa-status'>{{ selectedLeave.workflow_status }}</div></div>
        <div v-if='rejectionEvent(selectedLeave)' class='oa-rejection mt-3 border-l-4 border-amber-500 bg-amber-50 px-4 py-3 text-sm text-amber-900'>最近驳回：{{ eventActor(rejectionEvent(selectedLeave)) }} · {{ formatEventTime(rejectionEvent(selectedLeave).timestamp || rejectionEvent(selectedLeave).acted_on) }} · {{ rejectionEvent(selectedLeave).note }}</div>
        <dl class='oa-meta-grid mt-5 grid gap-3 text-sm md:grid-cols-3'>
          <div><dt class='text-gray-500'>申请人</dt><dd>{{ selectedLeave.employee_name }}</dd></div><div><dt class='text-gray-500'>部门</dt><dd>{{ selectedLeave.department }}</dd></div><div><dt class='text-gray-500'>直属主管</dt><dd>{{ selectedLeave.supervisor }}</dd></div>
          <div><dt class='text-gray-500'>开始日期</dt><dd>{{ selectedLeave.from_date }}</dd></div><div><dt class='text-gray-500'>结束日期</dt><dd>{{ selectedLeave.to_date }}</dd></div><div><dt class='text-gray-500'>申请时长</dt><dd>{{ leaveDays(selectedLeave) }}</dd></div>
          <div class='md:col-span-3'><dt class='text-gray-500'>申请事由</dt><dd class='whitespace-pre-wrap'>{{ selectedLeave.reason || '-' }}</dd></div>
        </dl>
        <div class='oa-detail-section oa-attachments mt-4'><h4 class='text-sm font-medium'>附件</h4><div v-if='selectedLeave.attachments?.length' class='mt-2 flex flex-wrap gap-2'><a v-for='file in selectedLeave.attachments' :key='file.name' :href='file.file_url' target='_blank' rel='noopener' class='text-sm text-blue-700 hover:underline'>{{ file.file_name }}</a></div><p v-else class='mt-1 text-sm text-gray-400'>无附件</p></div>
        <div class='oa-detail-section oa-timeline mt-4'><h4 class='text-sm font-medium'>审批轨迹与意见</h4><ol class='mt-2 space-y-2'><li v-for='step in selectedLeave.steps || []' :key='step.step_key' class='grid gap-2 border-b border-gray-100 pb-2 text-sm md:grid-cols-[1fr_140px_1fr]'><span>{{ step.step_index }}. {{ step.label }}<span class='ml-2 text-xs text-gray-500'>{{ step.approvers.join(' / ') }}</span></span><span>{{ step.status }}</span><span class='text-gray-600'>{{ step.note || '-' }}<span v-if='step.action_by' class='ml-2 text-xs'>{{ step.action_by }} · {{ formatEventTime(step.acted_on) }}</span></span></li></ol></div>
        <div v-if='selectedLeave.operation_log?.length' class='oa-detail-section oa-history mt-4'><h4 class='text-sm font-medium'>历史操作</h4><ol class='mt-2 space-y-1 text-sm text-gray-600'><li v-for='(event, index) in [...selectedLeave.operation_log].reverse()' :key='index'>{{ formatEventTime(event.timestamp || event.acted_on) }} · {{ event.action }} · {{ eventActor(event) }}<span v-if='event.note'> · {{ event.note }}</span></li></ol></div>
        <div v-if='selectedLeave.can_withdraw' class='mt-4'><Button :loading='saving' @click='withdrawAttendance(selectedLeave)'>撤回申请</Button></div>
        <div v-if='selectedLeave.attendance_days?.length' class='mt-4 text-sm'><div v-for='day in selectedLeave.attendance_days' :key='day.work_date'>{{ day.work_date }}：{{ day.hours }} 小时</div></div>
        <div v-if='selectedLeave.can_act' class='oa-action-bar mt-5 border-t border-gray-200 bg-slate-50 px-4 py-4'><textarea v-model='actionNote' rows='2' class='w-full rounded border px-3 py-2 text-sm' placeholder='审批意见（可选）'></textarea><div class='mt-2 flex flex-wrap gap-2'><Button variant='solid' @click='act(selectedLeave, "approve")'>通过</Button><select v-model='rejectTargetByRequest[selectedLeave.name]' class='rounded border px-3 py-2 text-sm'><option v-for='target in selectedLeave.rejection_targets || []' :key='target.target' :value='target.target'>驳回至：{{ target.label }}</option></select><Button variant='subtle' @click='act(selectedLeave, "reject")'>驳回</Button></div></div>
      </section>
      <section v-else-if='isLeaveInnerPage' class='border-t border-gray-200 bg-white py-10 text-center text-sm text-gray-500'>
        正在加载请假单详情…
      </section>
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
                    <select v-if='row.current_step_mode !== "handle"' v-model='rejectTargetByRequest[row.name]' class='mr-2 rounded border border-gray-300 px-1 py-0.5 text-xs'><option v-for='target in row.rejection_targets || []' :key='target.target' :value='target.target'>{{ target.label }}</option></select>
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

  </div>
</template>

<style scoped>
.oa-page {
  --ink: #172033;
  --muted: #667085;
  --line: #e5e9f0;
  --blue: #2563eb;
  color: var(--ink);
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 1360px;
  min-height: calc(100vh - 3.5rem);
  margin: 0 auto;
  padding: 1.75rem 2.25rem 3.5rem;
  background: #f6f8fb;
}
.oa-overview-strip { order: 1; display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 1rem; }
.oa-overview-primary { min-height: 116px; border: 1px solid #c7d8f8; border-radius: 14px; background: linear-gradient(135deg,#edf4ff 0%,#f7faff 100%); color: #174ea6; padding: 1.1rem 1.25rem; box-shadow: 0 8px 22px rgba(37,99,235,.10); }
.oa-overview-label { color: #315b97; font-size: .78rem; font-weight: 700; letter-spacing: .02em; }
.oa-overview-value { margin-top: .3rem; font-size: 2.15rem; font-weight: 750; line-height: 1; }
.oa-overview-value span { margin-left: .25rem; color: #5c78a7; font-size: .8rem; font-weight: 600; }
.oa-overview-caption { margin-top: .6rem; color: #5d7399; font-size: .72rem; }
.oa-overview-stat { display: flex; min-height: 116px; flex-direction: column; justify-content: center; border: 1px solid var(--line); border-radius: 14px; background: #fff; padding: 1.1rem 1.25rem; box-shadow: 0 8px 22px rgba(16,32,56,.055); }
.oa-overview-stat span { color: #667085; font-size: .76rem; font-weight: 650; }
.oa-overview-stat strong { margin-top: .35rem; color: #172033; font-size: 1.45rem; }
.oa-overview-stat small { margin-top: .22rem; color: #98a2b3; font-size: .7rem; }
.oa-pending-panel { order: 2; }
.oa-list-top { order: 3; align-items: start; }
.oa-mine-panel { order: 4; }
.oa-detail-panel { order: 1; }
.oa-header { border-color: var(--line); padding: .25rem 0 1.1rem; }
.oa-header h2 { font-size: 1.65rem; letter-spacing: -.02em; }
.oa-kicker { color: #64748b; font-size: .7rem; font-weight: 750; letter-spacing: .06em; text-transform: uppercase; }
.oa-back { color: #64748b; }
.oa-primary { background: #1f4f99 !important; border: 1px solid #1f4f99 !important; box-shadow: 0 2px 5px rgba(31,79,153,.18); }
.oa-primary:hover { background: #173d78 !important; }
.oa-panel, .oa-detail-panel { border: 1px solid var(--line); border-radius: 14px; background: #fff; box-shadow: 0 8px 24px rgba(20,33,61,.065); overflow: hidden; }
.oa-panel > :first-child { color: #172033; }
.oa-panel h2 { letter-spacing: -.01em; font-size: 1rem; }
.oa-list-top .oa-panel { align-self: start !important; }
.oa-form-panel :deep(.p-5), .oa-flow-panel :deep(.p-5) { padding: 1.25rem 1.35rem; }
.oa-input { min-height: 40px; border-color: #d9dee8 !important; background: #fff; transition: border-color .15s, box-shadow .15s; }
.oa-input:focus { border-color: #7aa2ef !important; box-shadow: 0 0 0 3px rgba(37,99,235,.12); outline: none; }
.oa-flow-panel { min-height: 0 !important; height: fit-content; }
.oa-route-step { border-color: #e3e8f0 !important; background: #fbfcfe; transition: border-color .15s, background .15s, transform .15s; }
.oa-route-step:hover { border-color: #b7cdf5 !important; background: #f6f9ff; transform: translateY(-1px); }
.oa-route-step:first-child { border-left: 3px solid #2563eb !important; }
.oa-flow-panel :deep(.text-gray-400) { color: #98a2b3; }
.oa-table-panel { margin-top: .25rem; }
.oa-pending-panel { border-top: 3px solid #2f6fed; }
.oa-pending-panel :deep(.p-5) { padding: 1rem 1.2rem; }
.oa-table-panel :deep(.p-5) { padding: 1rem 1.2rem; }
.oa-table thead { background: #f8fafc; }
.oa-table th { color: #667085; font-size: .72rem; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; }
.oa-table tbody tr:hover { background: #f8fbff; }
.oa-table-panel table { border-collapse: separate; border-spacing: 0; table-layout: fixed; }
.oa-table-panel th, .oa-table-panel td { overflow-wrap: anywhere; }
.oa-table-panel th:nth-child(1) { width: 22%; }
.oa-table-panel th:nth-child(2) { width: 18%; }
.oa-table-panel th:nth-child(3) { width: 19%; }
.oa-table-panel th:nth-child(4) { width: 20%; }
.oa-table-panel th:nth-child(5) { width: 13%; }
.oa-table-panel th:nth-child(6) { width: 8%; }
.oa-reason-cell { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; }
.oa-table-panel th { background: #f8fafc; }
.oa-status-pill, .oa-node-pill { display: inline-flex; align-items: center; border-radius: 999px; padding: .25rem .6rem; font-size: .72rem; font-weight: 600; white-space: nowrap; }
.oa-status-pill.pending { background: #eaf2ff; color: #1d4ed8; }
.oa-status-pill.draft { background: #fff7e6; color: #b54708; }
.oa-status-pill.approved, .oa-status-pill.paid { background: #eaf8f0; color: #087443; }
.oa-status-pill.rejected { background: #fff0f0; color: #b42318; }
.oa-node-pill { border: 1px solid #dbe5f5; background: #f5f8fd; color: #315b97; }
.oa-detail-panel { border-top: 4px solid #2f6fed; padding: 1.5rem 1.75rem 1.75rem; }
.oa-detail-heading { border-bottom: 1px solid var(--line); padding: .25rem 0 1.25rem; }
.oa-detail-heading h3 { font-size: 1.35rem; line-height: 1.25; }
.oa-status { border-radius: 999px; background: #eaf2ff; color: #1d4ed8; padding: .35rem .7rem; font-size: .75rem; font-weight: 700; }
.oa-meta-grid > div { border: 1px solid #e4e9f1; border-radius: 10px; background: #f8fafc; padding: .85rem .95rem; }
.oa-meta-grid dt { color: #7a8699; font-size: .72rem; margin-bottom: .2rem; }
.oa-meta-grid dd { color: #182b49; font-weight: 600; }
.oa-detail-panel > div.mt-4 { border-top: 1px solid var(--line); padding-top: 1rem; }
.oa-detail-panel h4 { color: #344054; font-weight: 700; }
.oa-detail-panel ol li { border-color: #edf0f4 !important; }
.oa-detail-section { border: 1px solid #e7ebf2; border-radius: 12px; background: #fcfdff; padding: 1rem 1.1rem; }
.oa-rejection { border-radius: 8px; }
.oa-timeline { background: #fff; }
.oa-timeline ol { border-left: 2px solid #dbe5f5; padding-left: 1rem; }
.oa-timeline ol li { position: relative; }
.oa-timeline ol li::before { position: absolute; left: -1.42rem; top: .25rem; width: .5rem; height: .5rem; border-radius: 50%; background: #4f7fca; content: ''; }
.oa-history { background: #f8fafc; }
.oa-action-bar { border: 1px solid #cbdcf8; border-radius: 12px; background: #f4f8ff !important; padding: 1rem 1.1rem; }
@media (max-width: 768px) {
  .oa-page { padding: 1rem .75rem 2rem; }
  .oa-header h2 { font-size: 1.35rem; }
  .oa-overview-strip { grid-template-columns: 1fr; }
  .oa-overview-primary { min-height: 96px; }
  .oa-overview-stat { min-height: 86px; }
  .oa-detail-panel { padding: 1rem; }
  .oa-table-panel th, .oa-table-panel td { padding-left: .55rem !important; padding-right: .55rem !important; }
  .oa-form-panel :deep(.p-5), .oa-flow-panel :deep(.p-5), .oa-table-panel :deep(.p-5) { padding: .9rem; }
}
</style>
