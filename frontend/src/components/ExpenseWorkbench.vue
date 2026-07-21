<script setup>
import { Button, FeatherIcon, createResource } from 'frappe-ui';
import { computed, reactive, ref, watch } from 'vue';
import { exportTableWorkbook } from '../lib/tableExport';
import InvoiceRecognitionPanel from './invoice/InvoiceRecognitionPanel.vue';
import InvoicePreviewDrawer from './invoice/InvoicePreviewDrawer.vue';
import { createInvoiceRequestLoadContext, getRequestInvoices, inspectRequestInvoiceRows, invoiceBlockers, invoiceSaveGuard, invoicesForLine, linkInvoice, moneyToCents, newLineKey, persistInvoiceRequest } from '../lib/invoiceOcr.js';

const REQUEST_TYPE = '费用付款申请';
const ASSET_OTHER = '其它';
const NAV_GROUPS = [
  { label: '主看板', items: [{ key: 'board', label: '付款/报销单', icon: 'trello' }] },
  { label: '子模板', items: [{ key: 'consumption', label: '消费明细', icon: 'file-text' }] },
  { label: '流程', items: [{ key: 'flow', label: '审批流配置', icon: 'git-branch' }] },
  { label: '报表', items: [
    { key: 'stats', label: '费用统计', icon: 'bar-chart-2' },
    { key: 'records', label: '审批记录', icon: 'clipboard' },
  ] },
];
const STATUS_COLUMNS = [
  { key: 'draft', label: '待提交', icon: 'edit-3', header: 'border-gray-400 text-gray-700', accent: 'border-l-gray-400', badge: 'bg-gray-100 text-gray-700' },
  { key: 'pending', label: '审批中', icon: 'clock', header: 'border-amber-500 text-amber-700', accent: 'border-l-amber-500', badge: 'bg-amber-50 text-amber-700' },
  { key: 'approved', label: '已通过', icon: 'check-circle', header: 'border-emerald-500 text-emerald-700', accent: 'border-l-emerald-500', badge: 'bg-emerald-50 text-emerald-700' },
  { key: 'rejected', label: '已驳回', icon: 'x-circle', header: 'border-red-500 text-red-700', accent: 'border-l-red-500', badge: 'bg-red-50 text-red-700' },
  { key: 'paid', label: '已付款', icon: 'credit-card', header: 'border-blue-500 text-blue-700', accent: 'border-l-blue-500', badge: 'bg-blue-50 text-blue-700' },
];
const VIEW_TITLES = {
  board: '费用付款/报销单看板',
  consumption: '消费明细看板',
  flow: '费用付款/报销审批流',
  stats: '费用统计',
  records: '审批记录',
};
const CD_STATUS = {
  '待上传': { label: '待上传', class: 'bg-gray-100 text-gray-700', icon: 'paperclip' },
  '已上传发票': { label: '已上传', class: 'bg-blue-50 text-blue-700', icon: 'upload-cloud' },
  '待下推': { label: '待下推', class: 'bg-amber-50 text-amber-700', icon: 'clock' },
  '已下推': { label: '已下推', class: 'bg-emerald-50 text-emerald-700', icon: 'check-circle' },
  '已驳回': { label: '已驳回', class: 'bg-red-50 text-red-700', icon: 'x-circle' },
};

const activeView = ref('board');
const showRequestForm = ref(false);
const showConsumptionForm = ref(false);
const showPushForm = ref(false);
const detailRequestName = ref('');
const selectedConsumptionName = ref('');
const selectedInvoiceName = ref('');
const pushSelection = ref([]);
const flowMode = ref('config');
const saving = ref(false);
const uploading = ref(false);
const message = ref('');
const errorMessage = ref('');
const actionNote = ref('');
const filters = reactive({ keyword: '', department: '', category: '' });
const consumptionFilter = ref('');
const recordFilters = reactive({ keyword: '', status: '' });
const invoiceBatch = ref(null);
const formInvoices = ref([]);
const formRequestName = ref('');
const formInvoiceBusy = ref(false);
const detailInvoices = ref([]);
const detailInvoiceBusy = ref(false);
const detailSubmitting = ref(false);
const previewInvoiceRow = ref(null);
const detailInvoiceLoadState = ref({ request: "", status: "idle", rows: [], batch: "", error: "", multipleBatches: false });
const detailInvoiceLoader = createInvoiceRequestLoadContext((state) => {
  detailInvoiceLoadState.value = state;
  detailInvoices.value = state.rows;
});

const blankLine = () => ({ line_key: newLineKey(), start_date: '', end_date: '', category: '', amount: '', description: '', invoice_difference_reason: '' });
const requestForm = reactive({
  subject: '', company: '', department: '', supervisor: '', doc_type: '', urgency: '', asset_category: ASSET_OTHER,
  payment_type: '', payment_method: '', bank_name: '', payee_name: '', branch: '', account_no: '', reason: '', no_invoice_reason: '',
});
const expenseLines = ref([blankLine()]);
const consumptionForm = reactive({ title: '', category: '', amount: '', expense_date: '', department: '', description: '' });
const pushPayment = reactive({
  subject: '', company: '', department: '', supervisor: '', doc_type: '', urgency: '', asset_category: ASSET_OTHER,
  payment_type: '', payment_method: '', bank_name: '', payee_name: '', branch: '', account_no: '', reason: '',
});

const options = createResource({ url: 'rayher_hr_payroll.api.oa_entry.get_options', method: 'GET', auto: true });
const requests = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_requests', method: 'GET',
  makeParams: () => ({ view: 'all', request_type: REQUEST_TYPE, limit: 200 }), auto: true,
});
const consumptions = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_consumption_details', method: 'GET',
  makeParams: () => ({ view: 'all', limit: 300 }), auto: true,
});
const preview = createResource({ url: 'rayher_hr_payroll.api.oa_entry.preview_route', method: 'GET' });
const creator = createResource({ url: 'rayher_hr_payroll.api.oa_entry.create_request' });
const consumptionSaver = createResource({ url: 'rayher_hr_payroll.api.oa_entry.save_consumption_detail' });
const invoiceAdder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.add_invoice' });
const pusher = createResource({ url: 'rayher_hr_payroll.api.oa_entry.push_consumption_to_request' });
const actor = createResource({ url: 'rayher_hr_payroll.api.oa_entry.action_request' });
const draftSubmitter = createResource({ url: 'rayher_hr_payroll.api.oa_entry.submit_request' });
const draftInvoiceDetailsSaver = createResource({ url: 'rayher_hr_payroll.api.oa_entry.update_draft_invoice_details' });
const paidMarker = createResource({ url: 'rayher_hr_payroll.api.oa_entry.mark_paid' });

const requestRows = computed(() => requests.data || []);
const consumptionRows = computed(() => consumptions.data || []);
const departments = computed(() => options.data?.departments || []);
const expenseCategories = computed(() => options.data?.expense_categories || []);
const companies = computed(() => options.data?.companies || []);
const docTypes = computed(() => options.data?.doc_types || []);
const urgencies = computed(() => options.data?.urgencies || []);
const assetCategories = computed(() => options.data?.asset_categories || [ASSET_OTHER]);
const paymentTypes = computed(() => options.data?.payment_types || []);
const paymentMethods = computed(() => options.data?.payment_methods || []);
const routeSteps = computed(() => preview.data?.steps || []);
const selectedRequest = computed(() => requestRows.value.find((row) => row.name === detailRequestName.value));
const detailInvoiceBatch = computed(() => detailInvoiceLoadState.value.batch || '');
const selectedConsumption = computed(() => consumptionRows.value.find((row) => row.name === selectedConsumptionName.value) || consumptionRows.value[0]);
const selectedInvoice = computed(() => (selectedConsumption.value?.invoices || []).find((invoice) => invoice.invoice_name === selectedInvoiceName.value));
const requestTotal = computed(() => expenseLines.value.reduce((sum, row) => sum + Number(row.amount || 0), 0));

function clean(value) {
  return String(value || '').replace(/<[^>]*>/g, '').trim();
}

function apiError(error, fallback) {
  const messages = error?.messages || [];
  if (messages.length) return messages.map(clean).filter(Boolean).join('；');
  return clean(error?._error_message || error?.message) || fallback;
}

function first(list, fallback = '') {
  return Array.isArray(list) && list.length ? list[0] : fallback;
}

function fmtMoney(value) {
  return Number(value || 0).toLocaleString('zh-CN', { style: 'currency', currency: 'CNY', minimumFractionDigits: 2 });
}

function fmtMoneyShort(value) {
  const amount = Number(value || 0);
  if (Math.abs(amount) >= 10000) return `¥${(amount / 10000).toFixed(1)}万`;
  return `¥${amount.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
}

function fmtDate(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-';
}

function currentMonthKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function inCurrentMonth(value) {
  return String(value || '').slice(0, 7) === currentMonthKey();
}

function statusMeta(status) {
  return STATUS_COLUMNS.find((item) => item.key === status) || STATUS_COLUMNS[1];
}

function consumptionMeta(status) {
  return CD_STATUS[status] || { label: status || '-', class: 'bg-gray-100 text-gray-700', icon: 'circle' };
}

function modeLabel(mode) {
  if (mode === 'all') return '会签';
  if (mode === 'handle') return '办理';
  return '审批';
}

const filteredRequests = computed(() => requestRows.value.filter((row) => {
  const keyword = filters.keyword.trim().toLowerCase();
  const searchable = [
    row.name, row.subject, row.employee_name, row.department, row.reason, row.invoice_search_text,
    ...(row.expense_lines || []).flatMap((line) => [line.category, line.description]),
  ].join(' ').toLowerCase();
  if (keyword && !searchable.includes(keyword)) return false;
  if (filters.department && row.department !== filters.department) return false;
  if (filters.category && !(row.expense_lines || []).some((line) => line.category === filters.category)) return false;
  return true;
}));

function rowsForStatus(status) {
  return filteredRequests.value.filter((row) => row.kanban_status === status);
}

const requestStats = computed(() => {
  const rows = requestRows.value;
  const monthRows = rows.filter((row) => inCurrentMonth(row.creation || row.modified));
  const pending = rows.filter((row) => row.kanban_status === 'pending').length;
  const approved = rows.filter((row) => ['approved', 'paid'].includes(row.kanban_status)).length;
  const paidRows = rows.filter((row) => row.kanban_status === 'paid');
  return {
    total: rows.length,
    thisMonth: monthRows.length,
    pending,
    approved,
    passRate: rows.length ? Math.round((approved / rows.length) * 100) : 0,
    monthAmount: monthRows.reduce((sum, row) => sum + Number(row.amount || 0), 0),
    paidAmount: paidRows.reduce((sum, row) => sum + Number(row.amount || 0), 0),
    paidCount: paidRows.length,
  };
});

const filteredConsumptions = computed(() => consumptionRows.value.filter((row) => !consumptionFilter.value || row.status === consumptionFilter.value));
const consumptionStats = computed(() => {
  const rows = consumptionRows.value;
  const invoices = rows.flatMap((row) => row.invoices || []);
  return {
    total: rows.length,
    thisMonth: rows.filter((row) => inCurrentMonth(row.creation || row.modified)).length,
    pending: rows.filter((row) => ['已上传发票', '待下推'].includes(row.status)).length,
    pushed: rows.filter((row) => row.status === '已下推').length,
    invoiceCount: invoices.length,
    verified: invoices.filter((row) => row.invoice_status === '已验证').length,
    duplicate: invoices.filter((row) => row.invoice_status === '重复发票').length,
  };
});

function groupRequestAmounts(keyGetter) {
  const grouped = new Map();
  requestRows.value.forEach((request) => {
    const key = keyGetter(request) || '未分类';
    const current = grouped.get(key) || { label: key, count: 0, amount: 0 };
    current.count += 1;
    current.amount += Number(request.amount || 0);
    grouped.set(key, current);
  });
  return [...grouped.values()].sort((a, b) => b.amount - a.amount);
}

const departmentStats = computed(() => groupRequestAmounts((row) => row.department));
const categoryStats = computed(() => {
  const grouped = new Map();
  requestRows.value.forEach((request) => (request.expense_lines || []).forEach((line) => {
    const key = line.category || '未分类';
    const current = grouped.get(key) || { label: key, count: 0, amount: 0 };
    current.count += 1;
    current.amount += Number(line.amount || 0);
    grouped.set(key, current);
  }));
  return [...grouped.values()].sort((a, b) => b.amount - a.amount);
});
const maxDepartmentAmount = computed(() => Math.max(...departmentStats.value.map((row) => row.amount), 1));
const maxCategoryAmount = computed(() => Math.max(...categoryStats.value.map((row) => row.amount), 1));
const totalRequestAmount = computed(() => requestRows.value.reduce((sum, row) => sum + Number(row.amount || 0), 0));
const recordRows = computed(() => requestRows.value.filter((row) => {
  const keyword = recordFilters.keyword.trim().toLowerCase();
  const text = [row.name, row.subject, row.employee_name, row.department, row.current_step_label].join(' ').toLowerCase();
  if (keyword && !text.includes(keyword)) return false;
  return !recordFilters.status || row.kanban_status === recordFilters.status;
}));

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
  expenseLines.value.forEach((line) => { line.category ||= first(expenseCategories.value); });
  consumptionForm.department ||= context.department || first(departments.value);
  consumptionForm.category ||= first(expenseCategories.value);
  Object.assign(pushPayment, {
    company: pushPayment.company || first(companies.value),
    department: pushPayment.department || context.department || first(departments.value),
    supervisor: pushPayment.supervisor || context.supervisor || '',
    doc_type: pushPayment.doc_type || first(docTypes.value),
    urgency: pushPayment.urgency || first(urgencies.value),
    payment_type: pushPayment.payment_type || first(paymentTypes.value),
    payment_method: pushPayment.payment_method || first(paymentMethods.value),
    payee_name: pushPayment.payee_name || context.employee_name || '',
  });
}

async function refreshRoute() {
  try {
    await preview.submit({
      request_type: REQUEST_TYPE,
      department: requestForm.department || options.data?.context?.department || '',
      supervisor: requestForm.supervisor || options.data?.context?.supervisor || '直属上级',
      asset_category: requestForm.asset_category || ASSET_OTHER,
    });
  } catch (error) {
    errorMessage.value = apiError(error, '审批流加载失败');
  }
}

async function reloadAll() {
  errorMessage.value = '';
  await Promise.allSettled([requests.reload(), consumptions.reload(), refreshRoute()]);
}

function openNewRequest() {
  message.value = '';
  errorMessage.value = '';
  resetRequestForm();
  showRequestForm.value = true;
  applyDefaults();
}

function resetRequestForm() {
  Object.assign(requestForm, {
    subject: '', bank_name: '', branch: '', account_no: '', reason: '', no_invoice_reason: '',
  });
  expenseLines.value = [blankLine()];
  invoiceBatch.value = null;
  formInvoices.value = [];
  formRequestName.value = '';
  formInvoiceBusy.value = false;
  applyDefaults();
}

function addExpenseLine() {
  const line = blankLine();
  line.category = first(expenseCategories.value);
  expenseLines.value.push(line);
}

function removeExpenseLine(index) {
  const line = expenseLines.value[index];
  if (invoicesForLine(formInvoices.value, line?.line_key).length) {
    errorMessage.value = '该费用明细已关联发票，请先在发票 OCR 区域解绑或改绑。';
    return;
  }
  if (expenseLines.value.length > 1) expenseLines.value.splice(index, 1);
}

function onBatchCreated(batch) {
  invoiceBatch.value = batch;
}

function onInvoicesChange(rows) {
  formInvoices.value = (rows || []).map((row) => ({ ...row }));
}

function onLinkChange(change) {
  formInvoices.value = formInvoices.value.map((row) => row.name === change.invoice ? { ...row, expense_line_key: change.expense_line_key } : row);
}

function validateInvoiceSubmission(invoices, lines, noInvoiceReason) {
  const included = (invoices || []).filter((row) => row.recognition_status !== '已排除');
  const blockers = invoiceBlockers(included);
  if (blockers.length) return blockers.join('；');
  if (!included.length) return String(noInvoiceReason || '').trim() ? '' : '未上传有效发票时，请填写无票原因。';
  if (included.some((row) => !row.expense_line_key)) return '已确认发票必须关联到一行费用明细。';
  try {
    for (const line of lines) {
      const linked = invoicesForLine(included, line.line_key);
      const invoiceTotal = linked.reduce((sum, row) => sum + moneyToCents(row.total_amount), 0);
      const difference = Math.abs(moneyToCents(line.amount) - invoiceTotal);
      if ((!linked.length || difference > 2) && !String(line.invoice_difference_reason || '').trim()) {
        return !linked.length ? '存在未关联发票的费用明细，请填写差异说明。' : '费用明细金额与发票合计不一致，请填写差异说明。';
      }
    }
  } catch {
    return '发票或费用明细金额格式无效。';
  }
  return '';
}

async function saveRequest(submit) {
  errorMessage.value = "";
  const validLines = expenseLines.value.filter((line) => line.category && Number(line.amount || 0) > 0);
  if (!requestForm.department || validLines.length !== expenseLines.value.length) {
    errorMessage.value = "请填写申请部门、费用项目和金额。";
    return;
  }
  const invoiceSaveError = invoiceSaveGuard({ busy: formInvoiceBusy.value, batch: invoiceBatch.value, invoices: formInvoices.value });
  if (invoiceSaveError) {
    errorMessage.value = invoiceSaveError;
    return;
  }
  if (submit) {
    if (formInvoiceBusy.value || (invoiceBatch.value && !formInvoices.value.length)) {
      errorMessage.value = "发票上传或批次回填尚未完成，请等待后再提交。";
      return;
    }
    const blocker = validateInvoiceSubmission(formInvoices.value, validLines, requestForm.no_invoice_reason);
    if (blocker) {
      errorMessage.value = blocker;
      return;
    }
  }
  const payload = {
    request_type: REQUEST_TYPE,
    subject: requestForm.subject.trim() || validLines[0].description || validLines[0].category,
    department: requestForm.department,
    supervisor: requestForm.supervisor,
    asset_category: requestForm.asset_category,
    amount: requestTotal.value,
    reason: requestForm.reason,
    submit: 0,
    company: requestForm.company,
    doc_type: requestForm.doc_type,
    urgency: requestForm.urgency,
    payment_type: requestForm.payment_type,
    payment_method: requestForm.payment_method,
    bank_name: requestForm.bank_name,
    payee_name: requestForm.payee_name,
    branch: requestForm.branch,
    account_no: requestForm.account_no,
    invoice_batch: typeof invoiceBatch.value === "string" ? invoiceBatch.value : invoiceBatch.value?.name || "",
    no_invoice_reason: requestForm.no_invoice_reason.trim(),
    expense_lines: JSON.stringify(validLines.map((line) => ({ ...line, amount: Number(line.amount || 0) }))),
  };
  saving.value = true;
  try {
    const result = await persistInvoiceRequest({
      requestName: formRequestName.value,
      payload,
      invoices: formInvoices.value,
      shouldSubmit: submit,
      createDraft: (draftPayload) => creator.submit(draftPayload),
      onDraftCreated: (row) => { formRequestName.value = row.name; },
      link: (invoice, request, lineKey) => linkInvoice(invoice, request, lineKey),
      submitDraft: (name) => draftSubmitter.submit({ name, no_invoice_reason: requestForm.no_invoice_reason.trim() }),
    });
    const savedName = result.requestName;
    showRequestForm.value = false;
    resetRequestForm();
    await requests.reload();
    detailRequestName.value = savedName;
  } catch (error) {
    const saved = formRequestName.value ? ("草稿 " + formRequestName.value + " 已保存；") : "";
    errorMessage.value = saved + apiError(error, "单据保存失败");
  } finally {
    saving.value = false;
  }
}

async function saveConsumption() {
  errorMessage.value = '';
  if (!consumptionForm.title || !consumptionForm.category || !consumptionForm.expense_date || Number(consumptionForm.amount || 0) <= 0) {
    errorMessage.value = '请填写消费标题、费用项目、日期和金额。';
    return;
  }
  saving.value = true;
  try {
    const row = await consumptionSaver.submit({ ...consumptionForm });
    selectedConsumptionName.value = row.name;
    showConsumptionForm.value = false;
    Object.assign(consumptionForm, { title: '', amount: '', expense_date: '', description: '' });
    await consumptions.reload();
  } catch (error) {
    errorMessage.value = apiError(error, '消费明细保存失败');
  } finally {
    saving.value = false;
  }
}

async function uploadInvoice(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file || !selectedConsumption.value) return;
  if (file.size > 10 * 1024 * 1024) {
    errorMessage.value = '发票文件不能超过 10MB。';
    return;
  }
  uploading.value = true;
  errorMessage.value = '';
  try {
    const body = new FormData();
    body.append('file', file);
    body.append('is_private', '1');
    body.append('doctype', 'OA Consumption Detail');
    body.append('docname', selectedConsumption.value.name);
    const headers = {};
    if (window.csrf_token) headers['X-Frappe-CSRF-Token'] = window.csrf_token;
    const response = await fetch('/api/method/upload_file', { method: 'POST', headers, body });
    const payload = await response.json();
    if (!response.ok || !payload.message?.file_url) throw new Error(payload.message || '文件上传失败');
    await invoiceAdder.submit({
      consumption: selectedConsumption.value.name,
      invoice_name: file.name,
      invoice_file: payload.message.file_url,
      file_type: file.type || file.name.split('.').pop() || '',
      file_size: `${Math.max(1, Math.round(file.size / 1024))}KB`,
    });
    selectedInvoiceName.value = file.name;
    await consumptions.reload();
  } catch (error) {
    errorMessage.value = apiError(error, '发票上传失败');
  } finally {
    uploading.value = false;
  }
}

function canPush(row) {
  return ['已上传发票', '待下推'].includes(row.status) && (row.invoices || []).length > 0;
}

function togglePush(name) {
  pushSelection.value = pushSelection.value.includes(name)
    ? pushSelection.value.filter((item) => item !== name)
    : [...pushSelection.value, name];
}

function openPush(row = null) {
  if (row) pushSelection.value = [row.name];
  if (!pushSelection.value.length) {
    errorMessage.value = '请选择可下推的消费明细。';
    return;
  }
  showPushForm.value = true;
  applyDefaults();
}

async function pushSelected(submit) {
  saving.value = true;
  errorMessage.value = '';
  try {
    const row = await pusher.submit({
      consumption_names: JSON.stringify(pushSelection.value),
      payment_info: JSON.stringify(pushPayment),
      submit: submit ? 1 : 0,
    });
    pushSelection.value = [];
    showPushForm.value = false;
    activeView.value = 'board';
    detailRequestName.value = row.name;
    await reloadAll();
  } catch (error) {
    errorMessage.value = apiError(error, '下推失败');
  } finally {
    saving.value = false;
  }
}

async function loadDetailInvoices(name, showError = true) {
  const token = detailInvoiceLoader.begin(name);
  if (!name) return [];
  let rows;
  try {
    rows = await getRequestInvoices(name);
  } catch (error) {
    const failed = detailInvoiceLoader.reject(token, error);
    if (failed.applied && showError) {
      errorMessage.value = apiError(error, '\u53d1\u7968\u660e\u7ec6\u52a0\u8f7d\u5931\u8d25');
    }
    throw error;
  }
  const loaded = detailInvoiceLoader.resolve(token, rows);
  if (!loaded.applied) return [];
  if (loaded.state.status === 'error') {
    const error = new Error(loaded.state.error);
    if (showError) errorMessage.value = loaded.state.error;
    throw error;
  }
  return loaded.state.rows;
}

function retryDetailInvoices() {
  const name = detailRequestName.value;
  if (name) loadDetailInvoices(name).catch(() => {});
}

function onDetailBatchCreated(batch) {
  const name = typeof batch === 'string' ? batch : batch?.name || '';
  if (!name || detailInvoiceLoadState.value.status !== 'loaded') return;
  detailInvoiceLoadState.value = {
    ...detailInvoiceLoadState.value,
    batch: name,
  };
}

function onDetailInvoicesChange(rows) {
  const nextRows = (rows || []).map((row) => ({ ...row }));
  detailInvoices.value = nextRows;
  detailInvoiceLoadState.value = {
    ...detailInvoiceLoadState.value,
    rows: nextRows,
  };
}
function onDetailLinkChange(change) {
  onDetailInvoicesChange(
    detailInvoices.value.map((row) =>
      row.name === change.invoice
        ? { ...row, expense_line_key: change.expense_line_key }
        : row),
  );
}
function draftInvoiceDetailsPayload(row) {
  return {
    name: row.name,
    no_invoice_reason: String(row.no_invoice_reason || "").trim(),
    expense_line_reasons: JSON.stringify(Object.fromEntries((row.expense_lines || []).map((line) => [line.line_key, String(line.invoice_difference_reason || "").trim()]))),
  };
}

async function persistDraftInvoiceDetails(row) {
  return draftInvoiceDetailsSaver.submit(draftInvoiceDetailsPayload(row));
}

async function saveDraftInvoiceDetails(row) {
  errorMessage.value = "";
  try {
    await persistDraftInvoiceDetails(row);
    message.value = "发票说明已保存。";
    await requests.reload();
  } catch (error) {
    errorMessage.value = apiError(error, "发票说明保存失败");
  }
}

async function submitDraft(row) {
  if (detailInvoiceLoadState.value.status !== 'loaded' || detailInvoiceLoadState.value.error) {
    errorMessage.value = detailInvoiceLoadState.value.error || '\u53d1\u7968\u660e\u7ec6\u5c1a\u672a\u52a0\u8f7d\u5b8c\u6210\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002';
    return;
  }
  if (detailInvoiceBusy.value || detailSubmitting.value) {
    errorMessage.value = '\u53d1\u7968\u4e0a\u4f20\u6216\u6279\u6b21\u56de\u586b\u5c1a\u672a\u5b8c\u6210\uff0c\u8bf7\u7b49\u5f85\u540e\u518d\u63d0\u4ea4\u3002';
    return;
  }
  detailSubmitting.value = true;
  try {
    await persistDraftInvoiceDetails(row);
    const fetchedInvoices = await getRequestInvoices(row.name);
    const invoiceContext = inspectRequestInvoiceRows(fetchedInvoices);
    if (invoiceContext.error) throw new Error(invoiceContext.error);
    const blocker = validateInvoiceSubmission(
      invoiceContext.rows,
      row.expense_lines || [],
      row.no_invoice_reason,
    );
    if (blocker) {
      errorMessage.value = blocker;
      return;
    }
    await draftSubmitter.submit({
      name: row.name,
      no_invoice_reason: String(row.no_invoice_reason || '').trim(),
    });
    await requests.reload();
    if (detailRequestName.value === row.name) {
      await loadDetailInvoices(row.name, false);
    }
  } catch (error) {
    errorMessage.value = apiError(error, '\u8349\u7a3f\u63d0\u4ea4\u5931\u8d25');
  } finally {
    detailSubmitting.value = false;
  }
}
async function act(row, action) {
  try {
    await actor.submit({ name: row.name, action, note: actionNote.value.trim() });
    actionNote.value = '';
    await requests.reload();
  } catch (error) {
    errorMessage.value = apiError(error, '审批处理失败');
  }
}

async function markPaid(row) {
  try {
    await paidMarker.submit({ name: row.name, note: actionNote.value.trim() });
    actionNote.value = '';
    await requests.reload();
  } catch (error) {
    errorMessage.value = apiError(error, '付款标记失败');
  }
}

async function exportRequests() {
  await exportTableWorkbook({
    filename: '费用付款报销单',
    sheetName: '付款报销单',
    rows: filteredRequests.value,
    columns: [
      { label: '单据编号', key: 'name', width: 20 },
      { label: '主题', key: 'subject', width: 28 },
      { label: '申请人', key: 'employee_name', width: 14 },
      { label: '部门', key: 'department', width: 16 },
      { label: '状态', value: (row) => statusMeta(row.kanban_status).label, width: 12 },
      { label: '当前节点', key: 'current_step_label', width: 22 },
      { label: '金额', value: (row) => Number(row.amount || 0), width: 14 },
      { label: '发票类别', value: (row) => (row.invoice_categories || []).join('；'), width: 28 },
      { label: '项目名称', value: (row) => (row.invoice_project_names || []).join('；'), width: 28 },
      { label: '发票号码', value: (row) => (row.invoice_numbers || []).join('；'), width: 24 },
      { label: '付款时间', key: 'paid_on', width: 20 },
    ],
  });
}

async function exportFlow() {
  await exportTableWorkbook({
    filename: '费用付款报销审批流',
    sheetName: '审批流',
    rows: routeSteps.value,
    columns: [
      { label: '序号', key: 'step_index', width: 10 },
      { label: '审批节点', key: 'label', width: 28 },
      { label: '审批人', value: (row) => (row.approvers || []).join(' / '), width: 28 },
      { label: '节点类型', value: (row) => modeLabel(row.mode), width: 14 },
    ],
  });
}

watch(() => options.data, () => {
  applyDefaults();
  refreshRoute();
}, { immediate: true });
watch(detailRequestName, (name) => {
  previewInvoiceRow.value = null;
  detailInvoiceBusy.value = false;
  if (name) loadDetailInvoices(name).catch(() => {});
  else detailInvoiceLoader.invalidate();
});
watch(selectedConsumption, (row) => {
  if (!row) return;
  const invoices = row.invoices || [];
  if (!invoices.some((invoice) => invoice.invoice_name === selectedInvoiceName.value)) {
    selectedInvoiceName.value = invoices[0]?.invoice_name || '';
  }
}, { immediate: true });
</script>

<template>
  <div class="grid min-w-0 gap-4 xl:grid-cols-[170px_minmax(0,1fr)]">
    <aside class="self-start overflow-hidden rounded-md border border-gray-200 bg-white xl:sticky xl:top-4">
      <div class="flex items-center gap-2 border-b border-gray-200 px-3 py-3">
        <span class="flex h-8 w-8 items-center justify-center rounded-md bg-amber-50 text-amber-700"><FeatherIcon name="briefcase" class="h-4 w-4" /></span>
        <div class="min-w-0"><div class="text-sm font-semibold text-gray-900">费用管理</div><div class="text-[11px] text-gray-500">付款与报销</div></div>
      </div>
      <nav class="flex gap-1 overflow-x-auto p-2 xl:block">
        <div v-for="group in NAV_GROUPS" :key="group.label" class="xl:mb-3">
          <div class="hidden px-2 pb-1 pt-2 text-[10px] font-semibold text-gray-400 xl:block">{{ group.label }}</div>
          <button v-for="item in group.items" :key="item.key" type="button"
            class="flex shrink-0 items-center gap-2 rounded px-2.5 py-2 text-left text-sm transition xl:mb-1 xl:w-full"
            :class="activeView === item.key ? 'bg-blue-50 font-medium text-blue-700' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'"
            @click="activeView = item.key">
            <FeatherIcon :name="item.icon" class="h-4 w-4" />{{ item.label }}
          </button>
        </div>
      </nav>
    </aside>

    <main class="min-w-0">
      <header class="mb-4 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div><h2 class="text-lg font-semibold text-gray-900">{{ VIEW_TITLES[activeView] }}</h2><p class="mt-0.5 text-xs text-gray-500">费用付款/报销工作台</p></div>
        <button type="button" title="刷新" class="flex h-9 w-9 items-center justify-center rounded border border-gray-200 bg-white text-gray-600 hover:bg-gray-50" @click="reloadAll"><FeatherIcon name="refresh-cw" class="h-4 w-4" /></button>
      </header>

      <div v-if="errorMessage" class="mb-4 flex items-start justify-between rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"><span>{{ errorMessage }}</span><button title="关闭" @click="errorMessage = ''"><FeatherIcon name="x" class="h-4 w-4" /></button></div>
      <div v-if="message" class="mb-4 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{{ message }}</div>

      <template v-if="activeView === 'board'">
        <div class="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <div class="relative min-h-[112px] rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">总申请数</div><div class="mt-2 text-2xl font-semibold">{{ requestStats.total }}</div><div class="mt-2 text-xs text-emerald-600">本月新增 {{ requestStats.thisMonth }} 笔</div><FeatherIcon name="clipboard" class="absolute right-4 top-4 h-5 w-5 text-blue-500" /></div>
          <div class="relative min-h-[112px] rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">待审批</div><div class="mt-2 text-2xl font-semibold">{{ requestStats.pending }}</div><div class="mt-2 text-xs text-gray-500">需及时处理</div><FeatherIcon name="clock" class="absolute right-4 top-4 h-5 w-5 text-amber-500" /></div>
          <div class="relative min-h-[112px] rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">已通过</div><div class="mt-2 text-2xl font-semibold">{{ requestStats.approved }}</div><div class="mt-2 text-xs text-emerald-600">通过率 {{ requestStats.passRate }}%</div><FeatherIcon name="check-circle" class="absolute right-4 top-4 h-5 w-5 text-emerald-500" /></div>
          <div class="relative min-h-[112px] rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">本月申请总额</div><div class="mt-2 text-2xl font-semibold">{{ fmtMoneyShort(requestStats.monthAmount) }}</div><div class="mt-2 text-xs text-gray-500">含 {{ requestStats.thisMonth }} 笔</div><FeatherIcon name="dollar-sign" class="absolute right-4 top-4 h-5 w-5 text-rose-500" /></div>
          <div class="relative min-h-[112px] rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">已付款总额</div><div class="mt-2 text-2xl font-semibold">{{ fmtMoneyShort(requestStats.paidAmount) }}</div><div class="mt-2 text-xs text-emerald-600">{{ requestStats.paidCount }} 笔已结清</div><FeatherIcon name="credit-card" class="absolute right-4 top-4 h-5 w-5 text-cyan-600" /></div>
        </div>

        <section class="mb-4 flex flex-col gap-3 rounded-md border border-gray-200 bg-white p-3 lg:flex-row lg:items-end lg:justify-between">
          <div class="grid flex-1 gap-2 sm:grid-cols-3">
            <label class="text-xs text-gray-500">关键字搜索<input v-model="filters.keyword" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="单据编号/申请人/说明" /></label>
            <label class="text-xs text-gray-500">部门<select v-model="filters.department" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">全部</option><option v-for="item in departments" :key="item">{{ item }}</option></select></label>
            <label class="text-xs text-gray-500">费用类型<select v-model="filters.category" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">全部</option><option v-for="item in expenseCategories" :key="item">{{ item }}</option></select></label>
          </div>
          <div class="flex gap-2"><Button variant="subtle" @click="exportRequests"><FeatherIcon name="download" class="mr-1 h-4 w-4" />导出</Button><Button variant="solid" @click="openNewRequest"><FeatherIcon name="plus" class="mr-1 h-4 w-4" />新建费用付款/报销单</Button></div>
        </section>

        <div class="overflow-x-auto pb-2">
          <div class="grid min-w-[1180px] grid-cols-5 gap-3">
            <section v-for="column in STATUS_COLUMNS" :key="column.key" class="min-h-[500px] overflow-hidden rounded-md border border-gray-200 bg-gray-50">
              <header class="flex items-center justify-between border-b-2 bg-white px-3 py-3 text-sm font-semibold" :class="column.header"><span class="flex items-center gap-2"><FeatherIcon :name="column.icon" class="h-4 w-4" />{{ column.label }}</span><span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{{ rowsForStatus(column.key).length }}</span></header>
              <div class="max-h-[620px] space-y-2 overflow-y-auto p-2">
                <button v-for="row in rowsForStatus(column.key)" :key="row.name" type="button" class="block w-full rounded-md border border-l-[3px] border-gray-200 bg-white p-3 text-left shadow-sm transition hover:-translate-y-px hover:shadow" :class="column.accent" @click="detailRequestName = row.name">
                  <div class="flex items-start justify-between gap-2"><span class="text-[11px] font-medium text-gray-500">{{ row.name }}</span><span class="rounded px-1.5 py-0.5 text-[10px] font-semibold" :class="column.badge">{{ column.label }}</span></div>
                  <div class="mt-2 text-sm font-semibold text-gray-900">{{ [...new Set((row.expense_lines || []).map((line) => line.category))].join('、') || row.subject }}</div>
                  <div class="mt-1 truncate text-xs text-gray-500">{{ row.subject }}</div>
                  <div class="mt-3 flex items-end justify-between gap-2 border-t border-gray-100 pt-2"><span class="text-base font-semibold text-red-600">{{ fmtMoney(row.amount) }}</span><span class="flex flex-wrap justify-end gap-1 text-[10px] text-gray-500"><span class="rounded bg-gray-100 px-1.5 py-0.5">{{ row.department || '-' }}</span><span class="rounded bg-gray-100 px-1.5 py-0.5">{{ row.employee_name || '-' }}</span><span v-if="row.from_consumption" class="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">下推</span></span></div>
                </button>
                <div v-if="!rowsForStatus(column.key).length" class="py-16 text-center text-xs text-gray-400">暂无数据</div>
              </div>
            </section>
          </div>
        </div>
      </template>

      <template v-else-if="activeView === 'consumption'">
        <div class="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="relative rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">消费明细总数</div><div class="mt-2 text-2xl font-semibold">{{ consumptionStats.total }}</div><div class="mt-2 text-xs text-emerald-600">本月新增 {{ consumptionStats.thisMonth }} 条</div><FeatherIcon name="file-text" class="absolute right-4 top-4 h-5 w-5 text-blue-500" /></div>
          <div class="relative rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">待下推</div><div class="mt-2 text-2xl font-semibold">{{ consumptionStats.pending }}</div><div class="mt-2 text-xs text-gray-500">可下推生成付款单</div><FeatherIcon name="upload-cloud" class="absolute right-4 top-4 h-5 w-5 text-amber-500" /></div>
          <div class="relative rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">已下推</div><div class="mt-2 text-2xl font-semibold">{{ consumptionStats.pushed }}</div><div class="mt-2 text-xs text-emerald-600">已关联付款单</div><FeatherIcon name="check-circle" class="absolute right-4 top-4 h-5 w-5 text-emerald-500" /></div>
          <div class="relative rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">发票总数</div><div class="mt-2 text-2xl font-semibold">{{ consumptionStats.invoiceCount }}</div><div class="mt-2 text-xs text-gray-500">已验证 {{ consumptionStats.verified }} / 重复 {{ consumptionStats.duplicate }}</div><FeatherIcon name="paperclip" class="absolute right-4 top-4 h-5 w-5 text-rose-500" /></div>
        </div>
        <div class="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between"><h3 class="text-base font-semibold">消费明细看板（子模板）</h3><div class="flex gap-2"><Button variant="subtle" @click="openPush()"><FeatherIcon name="upload" class="mr-1 h-4 w-4" />批量下推</Button><Button variant="solid" @click="showConsumptionForm = true"><FeatherIcon name="plus" class="mr-1 h-4 w-4" />新建消费明细</Button></div></div>
        <div class="mb-4 flex items-center gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800"><FeatherIcon name="lock" class="h-4 w-4 shrink-0" /><span><strong>发票查看限制：</strong>发票仅支持在线预览，不提供下载；预览显示水印，发票验证状态自动跟踪。</span></div>
        <div class="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(380px,.85fr)]">
          <section class="overflow-hidden rounded-md border border-gray-200 bg-white"><header class="flex items-center justify-between border-b border-gray-200 px-4 py-3"><h3 class="text-sm font-semibold">消费明细列表</h3><select v-model="consumptionFilter" class="rounded border border-gray-300 px-2 py-1.5 text-xs"><option value="">全部状态</option><option v-for="(meta, status) in CD_STATUS" :key="status" :value="status">{{ meta.label }}</option></select></header>
            <div class="max-h-[650px] space-y-2 overflow-y-auto p-3">
              <div v-for="row in filteredConsumptions" :key="row.name" class="flex items-center gap-3 rounded-md border border-gray-200 p-3 transition hover:border-gray-400" :class="selectedConsumption?.name === row.name ? 'border-blue-400 bg-blue-50/30' : 'bg-white'">
                <input type="checkbox" :checked="pushSelection.includes(row.name)" :disabled="!canPush(row)" title="选择下推" @change="togglePush(row.name)" />
                <button type="button" class="min-w-0 flex-1 text-left" @click="selectedConsumptionName = row.name"><div class="flex items-start justify-between gap-3"><div class="min-w-0"><div class="truncate text-sm font-semibold text-gray-900">{{ row.title }}</div><div class="mt-1 truncate text-xs text-gray-500">{{ row.employee_name || '-' }} · {{ row.department || '-' }} · {{ row.expense_date }} · {{ row.category }}</div></div><span class="shrink-0 text-sm font-semibold text-red-600">{{ fmtMoney(row.amount) }}</span></div><div class="mt-2 flex items-center gap-2 text-[11px]"><span class="rounded px-1.5 py-0.5" :class="consumptionMeta(row.status).class">{{ consumptionMeta(row.status).label }}</span><span class="text-gray-500">发票×{{ row.invoice_count || 0 }}</span><span v-if="row.linked_request" class="text-blue-600">→ {{ row.linked_request }}</span></div></button>
                <button v-if="canPush(row)" type="button" title="下推" class="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-gray-200 text-blue-600 hover:bg-blue-50" @click="openPush(row)"><FeatherIcon name="upload" class="h-4 w-4" /></button>
              </div>
              <div v-if="!filteredConsumptions.length" class="py-16 text-center text-sm text-gray-400">暂无消费明细</div>
            </div>
          </section>
          <section class="min-h-[520px] overflow-hidden rounded-md border border-gray-200 bg-white">
            <template v-if="selectedConsumption"><header class="border-b border-gray-200 px-4 py-3"><div class="flex items-start justify-between gap-3"><div><h3 class="text-sm font-semibold">发票管理 - {{ selectedConsumption.title }}</h3><p class="mt-1 text-xs text-gray-500">{{ selectedConsumption.employee_name || '-' }} · {{ selectedConsumption.department || '-' }} · {{ fmtMoney(selectedConsumption.amount) }}</p></div><label v-if="selectedConsumption.status !== '已下推'" class="cursor-pointer rounded bg-gray-900 px-3 py-2 text-xs font-medium text-white hover:bg-gray-800"><input type="file" accept=".pdf,.jpg,.jpeg,.png" class="hidden" @change="uploadInvoice" />{{ uploading ? '上传中...' : '上传发票' }}</label></div></header>
              <div class="p-4"><div class="mb-3 flex gap-2 overflow-x-auto"><button v-for="invoice in selectedConsumption.invoices || []" :key="invoice.invoice_name" type="button" class="shrink-0 rounded border px-3 py-2 text-left text-xs" :class="selectedInvoiceName === invoice.invoice_name ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600'" @click="selectedInvoiceName = invoice.invoice_name"><div class="max-w-[180px] truncate font-medium">{{ invoice.invoice_name }}</div><div class="mt-1 text-[10px]">{{ invoice.invoice_status }} · {{ invoice.file_size || '-' }}</div></button></div>
                <div v-if="selectedInvoice?.invoice_file" class="relative aspect-[4/3] overflow-hidden rounded border border-gray-200 bg-gray-50"><iframe v-if="String(selectedInvoice.file_type).toLowerCase().includes('pdf') || selectedInvoice.invoice_name.toLowerCase().endsWith('.pdf')" :src="selectedInvoice.invoice_file" title="发票预览" class="h-full w-full bg-white"></iframe><img v-else :src="selectedInvoice.invoice_file" alt="发票预览" class="h-full w-full object-contain" /><div class="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden text-2xl font-semibold text-gray-500/15 -rotate-12">{{ options.data?.context?.employee_name || '内部预览' }} · {{ selectedConsumption.name }}</div></div>
                <div v-else class="flex aspect-[4/3] flex-col items-center justify-center rounded border border-dashed border-gray-300 bg-gray-50 text-center"><FeatherIcon name="file-text" class="h-10 w-10 text-gray-300" /><p class="mt-3 text-sm text-gray-500">{{ (selectedConsumption.invoices || []).length ? '该历史附件未保存可预览文件' : '暂无发票，请上传 PDF / JPG / PNG' }}</p><p class="mt-1 text-xs text-gray-400">单文件最大 10MB</p></div>
              </div>
            </template>
            <div v-else class="flex min-h-[520px] flex-col items-center justify-center text-center"><FeatherIcon name="clipboard" class="h-10 w-10 text-gray-300" /><p class="mt-3 text-sm text-gray-500">请从左侧选择消费明细</p></div>
          </section>
        </div>
      </template>

      <template v-else-if="activeView === 'flow'">
        <div class="mb-4 flex items-center justify-between"><div><h3 class="text-base font-semibold">审批流节点配置</h3><p class="mt-1 text-xs text-gray-500">仅展示系统当前生效规则，审批逻辑保持原有路由。</p></div><div class="flex gap-2"><Button variant="subtle" @click="exportFlow"><FeatherIcon name="download" class="mr-1 h-4 w-4" />导出配置</Button><Button variant="subtle" @click="refreshRoute"><FeatherIcon name="refresh-cw" class="mr-1 h-4 w-4" />刷新流程</Button></div></div>
        <div class="mb-4 inline-flex overflow-hidden rounded border border-gray-200 bg-white"><button class="px-4 py-2 text-sm" :class="flowMode === 'config' ? 'bg-gray-900 text-white' : 'text-gray-600'" @click="flowMode = 'config'">审批流节点配置</button><button class="px-4 py-2 text-sm" :class="flowMode === 'viz' ? 'bg-gray-900 text-white' : 'text-gray-600'" @click="flowMode = 'viz'">流程图可视化</button></div>
        <section v-if="flowMode === 'config'" class="overflow-hidden rounded-md border border-gray-200 bg-white"><div class="overflow-x-auto"><table class="w-full min-w-[780px] text-sm"><thead class="border-b bg-gray-50 text-gray-500"><tr><th class="px-3 py-3 text-left">序号</th><th class="px-3 py-3 text-left">审批节点</th><th class="px-3 py-3 text-left">审批人</th><th class="px-3 py-3 text-left">节点类型</th><th class="px-3 py-3 text-left">通过规则</th></tr></thead><tbody><tr v-for="step in routeSteps" :key="step.step_index" class="border-b last:border-0"><td class="px-3 py-3">{{ step.step_index }}</td><td class="px-3 py-3 font-medium">{{ step.label }}</td><td class="px-3 py-3">{{ step.approvers.join(' / ') }}</td><td class="px-3 py-3"><span class="rounded bg-blue-50 px-2 py-1 text-xs text-blue-700">{{ modeLabel(step.mode) }}</span></td><td class="px-3 py-3 text-xs text-gray-500">{{ step.mode === 'all' ? '所有审批人通过后进入下一节点' : step.mode === 'handle' ? '办理完成后流程结束' : '审批通过后进入下一节点' }}</td></tr><tr v-if="!routeSteps.length"><td colspan="5" class="py-12 text-center text-gray-400">暂无流程节点</td></tr></tbody></table></div></section>
        <section v-else class="overflow-x-auto rounded-md border border-gray-200 bg-white p-6"><div class="flex min-w-[850px] items-center"><template v-for="(step, index) in routeSteps" :key="step.step_index"><div class="w-44 shrink-0 rounded-md border border-blue-200 bg-blue-50 p-4 text-center"><div class="mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">{{ step.step_index }}</div><div class="mt-3 text-sm font-semibold text-gray-900">{{ step.label }}</div><div class="mt-1 text-xs text-gray-500">{{ step.approvers.join(' / ') }}</div><div class="mt-2 text-[11px] text-blue-700">{{ modeLabel(step.mode) }}</div></div><div v-if="index < routeSteps.length - 1" class="flex-1 border-t-2 border-dashed border-gray-300"></div></template></div></section>
      </template>

      <template v-else-if="activeView === 'stats'">
        <div class="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><div class="rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">申请总额</div><div class="mt-2 text-2xl font-semibold">{{ fmtMoneyShort(totalRequestAmount) }}</div></div><div class="rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">单据数</div><div class="mt-2 text-2xl font-semibold">{{ requestStats.total }}</div></div><div class="rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">通过率</div><div class="mt-2 text-2xl font-semibold">{{ requestStats.passRate }}%</div></div><div class="rounded-md border border-gray-200 bg-white p-4"><div class="text-xs text-gray-500">已付款</div><div class="mt-2 text-2xl font-semibold">{{ fmtMoneyShort(requestStats.paidAmount) }}</div></div></div>
        <div class="grid gap-4 xl:grid-cols-2"><section class="rounded-md border border-gray-200 bg-white"><header class="border-b px-4 py-3 text-sm font-semibold">部门费用汇总</header><div class="space-y-4 p-4"><div v-for="row in departmentStats" :key="row.label"><div class="mb-1 flex items-center justify-between text-sm"><span>{{ row.label }} <span class="text-xs text-gray-400">{{ row.count }} 笔</span></span><span class="font-medium">{{ fmtMoney(row.amount) }}</span></div><div class="h-2 overflow-hidden rounded bg-gray-100"><div class="h-full rounded bg-blue-500" :style="{ width: `${Math.max(2, row.amount / maxDepartmentAmount * 100)}%` }"></div></div></div><div v-if="!departmentStats.length" class="py-12 text-center text-gray-400">暂无数据</div></div></section><section class="rounded-md border border-gray-200 bg-white"><header class="border-b px-4 py-3 text-sm font-semibold">费用分类汇总</header><div class="space-y-4 p-4"><div v-for="row in categoryStats" :key="row.label"><div class="mb-1 flex items-center justify-between text-sm"><span>{{ row.label }} <span class="text-xs text-gray-400">{{ row.count }} 行</span></span><span class="font-medium">{{ fmtMoney(row.amount) }}</span></div><div class="h-2 overflow-hidden rounded bg-gray-100"><div class="h-full rounded bg-emerald-500" :style="{ width: `${Math.max(2, row.amount / maxCategoryAmount * 100)}%` }"></div></div></div><div v-if="!categoryStats.length" class="py-12 text-center text-gray-400">暂无数据</div></div></section></div>
      </template>

      <template v-else>
        <section class="overflow-hidden rounded-md border border-gray-200 bg-white"><header class="flex flex-col gap-3 border-b px-4 py-3 md:flex-row md:items-center md:justify-between"><h3 class="text-sm font-semibold">审批记录列表</h3><div class="flex gap-2"><input v-model="recordFilters.keyword" class="rounded border border-gray-300 px-3 py-2 text-sm" placeholder="单号/申请人/节点" /><select v-model="recordFilters.status" class="rounded border border-gray-300 px-3 py-2 text-sm"><option value="">全部状态</option><option v-for="column in STATUS_COLUMNS" :key="column.key" :value="column.key">{{ column.label }}</option></select></div></header><div class="overflow-x-auto"><table class="w-full min-w-[1120px] text-sm"><thead class="border-b bg-gray-50 text-gray-500"><tr><th class="px-3 py-3 text-left">单据编号</th><th class="px-3 py-3 text-left">主题</th><th class="px-3 py-3 text-left">申请人</th><th class="px-3 py-3 text-left">部门</th><th class="px-3 py-3 text-left">当前节点</th><th class="px-3 py-3 text-left">状态</th><th class="px-3 py-3 text-right">金额</th><th class="px-3 py-3 text-left">更新时间</th></tr></thead><tbody><tr v-for="row in recordRows" :key="row.name" class="cursor-pointer border-b last:border-0 hover:bg-gray-50" @click="detailRequestName = row.name"><td class="px-3 py-3 font-medium text-blue-700">{{ row.name }}</td><td class="max-w-[260px] truncate px-3 py-3">{{ row.subject }}</td><td class="px-3 py-3">{{ row.employee_name || '-' }}</td><td class="px-3 py-3">{{ row.department || '-' }}</td><td class="px-3 py-3">{{ row.current_step_label || '-' }}</td><td class="px-3 py-3"><span class="rounded px-2 py-1 text-xs" :class="statusMeta(row.kanban_status).badge">{{ statusMeta(row.kanban_status).label }}</span></td><td class="px-3 py-3 text-right font-medium">{{ fmtMoney(row.amount) }}</td><td class="px-3 py-3 text-xs text-gray-500">{{ fmtDate(row.modified) }}</td></tr><tr v-if="!recordRows.length"><td colspan="8" class="py-14 text-center text-gray-400">暂无审批记录</td></tr></tbody></table></div></section>
      </template>
    </main>
  </div>

  <div v-if="showRequestForm" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4" @click.self="showRequestForm = false"><div role="dialog" aria-modal="true" class="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-md bg-white shadow-xl"><header class="flex items-center justify-between border-b bg-gray-50 px-5 py-4"><h3 class="font-semibold">新建费用付款/报销单</h3><button title="关闭" @click="showRequestForm = false"><FeatherIcon name="x" class="h-5 w-5" /></button></header><div class="flex-1 space-y-5 overflow-y-auto p-5"><p v-if="formRequestName" class="rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">草稿 {{ formRequestName }} 已保存。基本信息和费用行已锁定，可继续处理发票后重试提交。</p><fieldset :disabled="Boolean(formRequestName)"><section><h4 class="mb-3 text-sm font-semibold">基本信息</h4><div class="grid gap-3 md:grid-cols-3"><label class="text-xs text-gray-500">主题<input v-model="requestForm.subject" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">公司<select v-model="requestForm.company" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in companies" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">申请部门<select v-model="requestForm.department" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in departments" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">部门主管<input v-model="requestForm.supervisor" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">单据类型<select v-model="requestForm.doc_type" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in docTypes" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">紧急程度<select v-model="requestForm.urgency" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in urgencies" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">资产类别<select v-model="requestForm.asset_category" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in assetCategories" :key="item">{{ item }}</option></select></label></div></section></fieldset><InvoiceRecognitionPanel :batch="invoiceBatch" :invoices="formInvoices" :request="formRequestName" :expense-lines="expenseLines" :disabled="saving" @batch-created="onBatchCreated" @invoices-change="onInvoicesChange" @link-change="onLinkChange" v-on:busy-change="formInvoiceBusy = $event" /><fieldset :disabled="Boolean(formRequestName)"><section><div class="mb-3 flex items-center justify-between"><h4 class="text-sm font-semibold">费用明细</h4><button type="button" class="flex items-center gap-1 text-sm text-blue-700" @click="addExpenseLine"><FeatherIcon name="plus" class="h-4 w-4" />添加明细</button></div><div class="overflow-x-auto"><table class="w-full min-w-[1120px] text-sm"><thead class="border-b bg-gray-50 text-gray-500"><tr><th class="px-2 py-2 text-left">起始日期</th><th class="px-2 py-2 text-left">结束日期</th><th class="px-2 py-2 text-left">费用项目</th><th class="px-2 py-2 text-left">费用说明</th><th class="px-2 py-2 text-left">发票差异说明</th><th class="px-2 py-2 text-right">金额</th><th class="w-10"></th></tr></thead><tbody><tr v-for="(line, index) in expenseLines" :key="line.line_key" class="border-b"><td class="p-2"><input v-model="line.start_date" type="date" class="w-full rounded border border-gray-300 px-2 py-1.5" /></td><td class="p-2"><input v-model="line.end_date" type="date" class="w-full rounded border border-gray-300 px-2 py-1.5" /></td><td class="p-2"><select v-model="line.category" class="w-full rounded border border-gray-300 px-2 py-1.5"><option v-for="item in expenseCategories" :key="item">{{ item }}</option></select></td><td class="p-2"><input v-model="line.description" class="w-full rounded border border-gray-300 px-2 py-1.5" /></td><td class="p-2"><input v-model="line.invoice_difference_reason" placeholder="无票或金额不一致时必填" class="w-full rounded border border-gray-300 px-2 py-1.5" /></td><td class="p-2"><input v-model="line.amount" type="number" min="0" step="0.01" class="w-full rounded border border-gray-300 px-2 py-1.5 text-right" /></td><td class="p-2"><button title="删除明细" :disabled="expenseLines.length === 1" class="text-red-600 disabled:text-gray-300" @click="removeExpenseLine(index)"><FeatherIcon name="trash-2" class="h-4 w-4" /></button></td></tr></tbody><tfoot><tr><td colspan="5" class="px-2 py-3 text-right font-medium">总费用发生额</td><td class="px-2 py-3 text-right text-base font-semibold text-red-600">{{ fmtMoney(requestTotal) }}</td><td></td></tr></tfoot></table></div></section></fieldset><fieldset :disabled="Boolean(formRequestName)"><section><h4 class="mb-3 text-sm font-semibold">付款信息</h4><div class="grid gap-3 md:grid-cols-3"><label class="text-xs text-gray-500">付款类型<select v-model="requestForm.payment_type" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in paymentTypes" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">付款方式<select v-model="requestForm.payment_method" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in paymentMethods" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">收款人<input v-model="requestForm.payee_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">开户行<input v-model="requestForm.bank_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">支行<input v-model="requestForm.branch" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">收款账号<input v-model="requestForm.account_no" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500 md:col-span-3">情况说明/备注<textarea v-model="requestForm.reason" rows="2" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"></textarea></label><label class="text-xs text-gray-500 md:col-span-3">无票原因（未上传有效发票时必填）<textarea v-model="requestForm.no_invoice_reason" rows="2" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"></textarea></label></div></section></fieldset></div><footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3"><Button variant="subtle" @click="showRequestForm = false">取消</Button><Button variant="subtle" :loading="saving" @click="saveRequest(false)">保存草稿</Button><Button variant="solid" :loading="saving" @click="saveRequest(true)">保存并提交</Button></footer></div></div>

  <div v-if="showConsumptionForm" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4" @click.self="showConsumptionForm = false"><div role="dialog" aria-modal="true" class="w-full max-w-2xl rounded-md bg-white shadow-xl"><header class="flex items-center justify-between border-b bg-gray-50 px-5 py-4"><h3 class="font-semibold">新建消费明细</h3><button title="关闭" @click="showConsumptionForm = false"><FeatherIcon name="x" class="h-5 w-5" /></button></header><div class="grid gap-3 p-5 md:grid-cols-2"><label class="text-xs text-gray-500 md:col-span-2">标题<input v-model="consumptionForm.title" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">费用项目<select v-model="consumptionForm.category" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in expenseCategories" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">金额<input v-model="consumptionForm.amount" type="number" min="0" step="0.01" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">日期<input v-model="consumptionForm.expense_date" type="date" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">部门<select v-model="consumptionForm.department" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in departments" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500 md:col-span-2">费用说明<textarea v-model="consumptionForm.description" rows="3" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"></textarea></label></div><footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3"><Button variant="subtle" @click="showConsumptionForm = false">取消</Button><Button variant="solid" :loading="saving" @click="saveConsumption">创建</Button></footer></div></div>

  <div v-if="showPushForm" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4" @click.self="showPushForm = false"><div role="dialog" aria-modal="true" class="w-full max-w-3xl rounded-md bg-white shadow-xl"><header class="flex items-center justify-between border-b bg-gray-50 px-5 py-4"><div><h3 class="font-semibold">下推生成付款单</h3><p class="mt-1 text-xs text-gray-500">已选 {{ pushSelection.length }} 条消费明细，发票附件将自动带入。</p></div><button title="关闭" @click="showPushForm = false"><FeatherIcon name="x" class="h-5 w-5" /></button></header><div class="grid gap-3 p-5 md:grid-cols-3"><label class="text-xs text-gray-500 md:col-span-2">主题<input v-model="pushPayment.subject" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">公司<select v-model="pushPayment.company" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in companies" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">部门<select v-model="pushPayment.department" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in departments" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">部门主管<input v-model="pushPayment.supervisor" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">收款人<input v-model="pushPayment.payee_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label><label class="text-xs text-gray-500">付款类型<select v-model="pushPayment.payment_type" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in paymentTypes" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">付款方式<select v-model="pushPayment.payment_method" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in paymentMethods" :key="item">{{ item }}</option></select></label><label class="text-xs text-gray-500">收款账号<input v-model="pushPayment.account_no" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label></div><footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3"><Button variant="subtle" @click="showPushForm = false">取消</Button><Button variant="subtle" :loading="saving" @click="pushSelected(false)">下推生成草稿</Button><Button variant="solid" :loading="saving" @click="pushSelected(true)">下推并提交</Button></footer></div></div>

  <div v-if="selectedRequest" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4" @click.self="detailRequestName = ''"><div role="dialog" aria-modal="true" class="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-md bg-white shadow-xl"><header class="flex items-center justify-between border-b bg-gray-50 px-5 py-4"><div><h3 class="font-semibold">{{ selectedRequest.name }} - 费用付款/报销单详情</h3><p class="mt-1 text-xs text-gray-500">{{ selectedRequest.subject }}</p></div><button title="关闭" @click="detailRequestName = ''"><FeatherIcon name="x" class="h-5 w-5" /></button></header><div class="flex-1 space-y-5 overflow-y-auto p-5"><section><div class="mb-3 flex items-center justify-between"><h4 class="text-sm font-semibold">基本信息</h4><span class="rounded px-2 py-1 text-xs font-medium" :class="statusMeta(selectedRequest.kanban_status).badge">{{ statusMeta(selectedRequest.kanban_status).label }}</span></div><dl class="grid gap-x-5 gap-y-3 text-sm md:grid-cols-3"><div><dt class="text-xs text-gray-500">公司</dt><dd class="mt-1">{{ selectedRequest.company || '-' }}</dd></div><div><dt class="text-xs text-gray-500">申请部门</dt><dd class="mt-1">{{ selectedRequest.department || '-' }}</dd></div><div><dt class="text-xs text-gray-500">申请人</dt><dd class="mt-1">{{ selectedRequest.employee_name || '-' }}</dd></div><div><dt class="text-xs text-gray-500">单据类型</dt><dd class="mt-1">{{ selectedRequest.doc_type || '-' }}</dd></div><div><dt class="text-xs text-gray-500">紧急程度</dt><dd class="mt-1">{{ selectedRequest.urgency || '-' }}</dd></div><div><dt class="text-xs text-gray-500">来源</dt><dd class="mt-1">{{ selectedRequest.from_consumption ? '消费明细下推' : '手工新建' }}</dd></div></dl></section><div v-if="detailInvoiceLoadState.status === 'loading'" class="rounded bg-blue-50 px-3 py-2 text-sm text-blue-700">&#x53D1;&#x7968;&#x4FE1;&#x606F;&#x52A0;&#x8F7D;&#x4E2D;...</div><div v-else-if="detailInvoiceLoadState.status === 'error'" role="alert" class="flex items-center justify-between gap-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700"><span>{{ detailInvoiceLoadState.error }}</span><button type="button" class="shrink-0 underline" @click="retryDetailInvoices">&#x91CD;&#x8BD5;</button></div><InvoiceRecognitionPanel v-else-if="selectedRequest.kanban_status === 'draft' && detailInvoiceLoadState.status === 'loaded'" :disabled="detailSubmitting" :batch="detailInvoiceBatch" :invoices="detailInvoices" :request="selectedRequest.name" :expense-lines="selectedRequest.expense_lines || []" v-on:batch-created="onDetailBatchCreated" v-on:invoices-change="onDetailInvoicesChange" v-on:link-change="onDetailLinkChange" v-on:busy-change="detailInvoiceBusy = $event" /><section><h4 class="mb-3 text-sm font-semibold">费用明细</h4><div class="overflow-x-auto"><table class="w-full min-w-[820px] text-sm"><thead class="border-b bg-gray-50 text-gray-500"><tr><th class="px-2 py-2 text-left">起始日期</th><th class="px-2 py-2 text-left">结束日期</th><th class="px-2 py-2 text-left">费用项目</th><th class="px-2 py-2 text-left">说明</th><th class="px-2 py-2 text-left">发票</th><th class="px-2 py-2 text-left">发票状态</th><th class="px-2 py-2 text-left">差异说明</th><th class="px-2 py-2 text-right">金额</th></tr></thead><tbody><tr v-for="line in selectedRequest.expense_lines || []" :key="line.line_key" class="border-b"><td class="px-2 py-2">{{ line.start_date || '-' }}</td><td class="px-2 py-2">{{ line.end_date || '-' }}</td><td class="px-2 py-2">{{ line.category }}</td><td class="px-2 py-2">{{ line.description || '-' }}</td><td class="px-2 py-2"><div class="flex flex-wrap gap-1"><button v-for="(invoice, invoiceIndex) in invoicesForLine(detailInvoices, line.line_key)" :key="invoice.name" type="button" class="rounded bg-blue-50 px-2 py-1 text-xs text-blue-700" v-on:click="previewInvoiceRow = invoice">查看发票 {{ invoiceIndex + 1 }}/{{ invoicesForLine(detailInvoices, line.line_key).length }}</button><span v-if="!invoicesForLine(detailInvoices, line.line_key).length" class="text-gray-400">无</span></div></td><td class="px-2 py-2">{{ line.invoice_status || '-' }}</td><td class="px-2 py-2"><input v-if="selectedRequest.kanban_status === 'draft'" v-model="line.invoice_difference_reason" class="w-48 rounded border border-gray-300 px-2 py-1 text-xs" placeholder="无票或金额不一致时必填" /><span v-else>{{ line.invoice_difference_reason || '-' }}</span></td><td class="px-2 py-2 text-right font-medium text-red-600">{{ fmtMoney(line.amount) }}</td></tr></tbody><tfoot><tr><td colspan="7" class="px-2 py-3 text-right font-medium">总额</td><td class="px-2 py-3 text-right text-base font-semibold text-red-600">{{ fmtMoney(selectedRequest.amount) }}</td></tr></tfoot></table></div></section><section><h4 class="mb-3 text-sm font-semibold">付款信息</h4><dl class="grid gap-x-5 gap-y-3 text-sm md:grid-cols-3"><div><dt class="text-xs text-gray-500">付款类型</dt><dd class="mt-1">{{ selectedRequest.payment_type || '-' }}</dd></div><div><dt class="text-xs text-gray-500">付款方式</dt><dd class="mt-1">{{ selectedRequest.payment_method || '-' }}</dd></div><div><dt class="text-xs text-gray-500">收款人</dt><dd class="mt-1">{{ selectedRequest.payee_name || '-' }}</dd></div><div><dt class="text-xs text-gray-500">开户行/支行</dt><dd class="mt-1">{{ [selectedRequest.bank_name, selectedRequest.branch].filter(Boolean).join(' / ') || '-' }}</dd></div><div><dt class="text-xs text-gray-500">收款账号</dt><dd class="mt-1">{{ selectedRequest.account_no || '-' }}</dd></div><div><dt class="text-xs text-gray-500">付款时间</dt><dd class="mt-1">{{ fmtDate(selectedRequest.paid_on) }}</dd></div></dl></section><section><h4 class="mb-2 text-sm font-semibold">无票原因</h4><textarea v-if="selectedRequest.kanban_status === 'draft'" v-model="selectedRequest.no_invoice_reason" rows="2" class="w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="未上传有效发票时必填"></textarea><p v-else class="rounded bg-gray-50 p-3 text-sm text-gray-600 whitespace-pre-wrap">{{ selectedRequest.no_invoice_reason || '无' }}</p></section><section><h4 class="mb-4 text-sm font-semibold">审批记录</h4><div class="overflow-x-auto"><div class="flex min-w-[760px] items-start"><template v-for="(step, index) in selectedRequest.steps || []" :key="step.step_index"><div class="w-40 shrink-0 text-center"><div class="mx-auto flex h-9 w-9 items-center justify-center rounded-full text-sm font-semibold" :class="step.status === '已通过' || step.status === '已办理' ? 'bg-emerald-600 text-white' : step.status === '已拒绝' ? 'bg-red-600 text-white' : step.step_index === selectedRequest.current_step_index ? 'bg-amber-500 text-white' : 'bg-gray-200 text-gray-600'">{{ step.step_index }}</div><div class="mt-2 text-xs font-medium">{{ step.label }}</div><div class="mt-1 text-[11px] text-gray-500">{{ step.approvers.join(' / ') }}</div><div v-if="step.acted_on" class="mt-1 text-[10px] text-gray-400">{{ fmtDate(step.acted_on) }}</div><div v-if="step.note" class="mt-1 text-[10px] text-gray-500">{{ step.note }}</div></div><div v-if="index < selectedRequest.steps.length - 1" class="mt-4 flex-1 border-t-2 border-dashed border-gray-300"></div></template></div></div></section><section v-if="selectedRequest.reason"><h4 class="mb-2 text-sm font-semibold">备注</h4><p class="rounded bg-gray-50 p-3 text-sm text-gray-600 whitespace-pre-wrap">{{ selectedRequest.reason }}</p></section></div><footer class="flex flex-col gap-2 border-t bg-gray-50 px-5 py-3 md:flex-row md:items-center md:justify-between"><input v-model="actionNote" class="min-w-0 flex-1 rounded border border-gray-300 px-3 py-2 text-sm" placeholder="审批/付款备注" /><div class="flex justify-end gap-2"><Button variant="subtle" @click="detailRequestName = ''">关闭</Button><Button v-if="selectedRequest.kanban_status === 'draft'" variant="subtle" @click="saveDraftInvoiceDetails(selectedRequest)">保存发票说明</Button><Button v-if="selectedRequest.kanban_status === 'draft'" variant="solid" :loading="detailSubmitting" :disabled="detailSubmitting || detailInvoiceLoadState.status !== 'loaded' || Boolean(detailInvoiceLoadState.error) || detailInvoiceBusy" @click="submitDraft(selectedRequest)">提交审批</Button><Button v-if="selectedRequest.can_act && selectedRequest.current_step_mode !== 'handle'" variant="subtle" @click="act(selectedRequest, 'reject')">驳回</Button><Button v-if="selectedRequest.can_act" variant="solid" @click="act(selectedRequest, 'approve')">{{ selectedRequest.current_step_mode === 'handle' ? '办理完成' : '审批通过' }}</Button><Button v-if="selectedRequest.can_mark_paid" variant="solid" @click="markPaid(selectedRequest)">标记已付款</Button></div></footer></div></div>
  <InvoicePreviewDrawer :open="Boolean(previewInvoiceRow)" :invoice="previewInvoiceRow" :current-user="options.data?.context?.employee_name || '内部用户'" v-on:close="previewInvoiceRow = null" />
</template>
