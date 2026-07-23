<script setup>
import { Button, FeatherIcon, createResource } from 'frappe-ui';
import { computed, reactive, ref, watch } from 'vue';
import { getRequestInvoices, invoicesForLine, newLineKey } from '../lib/invoiceOcr.js';
import {
  addSignRequest, deleteExpenseAttachment, fetchExpenseAttachmentPreview, listApprovalPeople,
  rejectRequest, saveFinanceExpenseItems, uploadExpenseAttachment, validateExpenseAttachments,
} from '../lib/expenseWorkflow.js';
// Backend response compatibility: project_groups are regrouped from expense_lines so per-line descriptions and attachments remain intact.
// const fields = [
//   ['invoice_category', '发票类别', 'text'],
//   ['project_name', '项目名称', 'text'],
//   ['issue_date', '开票日期', 'date'],
//   ['invoice_number', '发票号码', 'text'],
//   ['amount_before_tax', '税前金额', 'number'],
//   ['tax_amount', '税额', 'number'],
//   ['total_amount', '合计金额', 'number'],
// ];
//               <Button variant="subtle" @click="previewRow = selectedRow"><FeatherIcon name="eye" class="h-4 w-4" />查看发票</Button>
import ExpenseApprovalRecords from './expense/ExpenseApprovalRecords.vue';
import ExpenseStatistics from './expense/ExpenseStatistics.vue';
import InvoicePreviewDrawer from './invoice/InvoicePreviewDrawer.vue';
import InvoiceUploadWorkbench from './invoice/InvoiceUploadWorkbench.vue';

const REQUEST_TYPE = '费用付款申请';
const ASSET_OTHER = '其它';
const NAV_ITEMS = [
  { key: 'invoices', label: '上传发票', icon: 'upload-cloud' },
  { key: 'board', label: '费用报销流', icon: 'trello' },
  { key: 'statistics', label: '费用统计', icon: 'bar-chart-2' },
  { key: 'audit', label: '审批记录', icon: 'clipboard' },
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
const previewAttachmentRow = ref(null);
const financeSources = ref([]);
const attachmentBusy = ref({});
const showRejectDialog = ref(false);
const rejectTarget = ref('');
const rejectReason = ref('');
const showAddSignDialog = ref(false);
const approvalPeople = ref([]);
const peopleQuery = ref('');
const addSignForm = reactive({ approver: '', position: 'before', opinion: '' });
const keyword = ref('');
const statisticsView = ref(null);
const approvalView = ref(null);
const draftSources = ref([]);
const showManualExpense = ref(false);
const manualExpense = reactive({
  project_name: '', expense_item: '', issue_date: '', total_amount: '',
  expense_description: '', description: '', no_invoice_reason: '',
});

const blankLine = () => ({
  line_key: newLineKey(),
  invoice_category: '',
  project_name: '',
  expense_item: '',
  issue_date: '',
  invoice_number: '',
  amount_before_tax: '',
  tax_amount: '',
  total_amount: '',
  expense_description: '',
  description: '',
  no_invoice_reason: '',
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
const requestDetail = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_requests',
  method: 'GET',
  makeParams: () => ({
    view: 'all',
    limit: 1,
    request_type: REQUEST_TYPE,
    name: detailRequestName.value,
  }),
  auto: false,
});
const creator = createResource({ url: 'rayher_hr_payroll.api.oa_entry.create_request' });
const actor = createResource({ url: 'rayher_hr_payroll.api.oa_entry.action_request' });
const draftSubmitter = createResource({ url: 'rayher_hr_payroll.api.oa_entry.submit_request' });
const paidMarker = createResource({ url: 'rayher_hr_payroll.api.oa_entry.mark_paid' });
const requestWithdrawer = createResource({ url: 'rayher_hr_payroll.api.oa_entry.withdraw_request' });
const paymentWithdrawer = createResource({ url: 'rayher_hr_payroll.api.oa_entry.withdraw_payment' });
const draftSourceSaver = createResource({ url: 'rayher_hr_payroll.api.oa_entry.save_draft_expense_sources' });

const rows = computed(() => requests.data || []);
const exactRequest = computed(() => requestDetail.data?.[0] || null);
const selectedRequest = computed(() => rows.value.find((row) => row.name === detailRequestName.value)
  || (exactRequest.value?.name === detailRequestName.value ? exactRequest.value : null));
const departments = computed(() => options.data?.departments || []);
const companies = computed(() => options.data?.companies || []);
const docTypes = computed(() => options.data?.doc_types || []);
const urgencies = computed(() => options.data?.urgencies || []);
const assetCategories = computed(() => options.data?.asset_categories || [ASSET_OTHER]);
const paymentTypes = computed(() => options.data?.payment_types || []);
const paymentMethods = computed(() => options.data?.payment_methods || []);
const expenseCategories = computed(() => options.data?.expense_categories || []);
const isDraftDetail = computed(() => selectedRequest.value?.kanban_status === 'draft');
const canEditExpenseItems = computed(() => Boolean(isDraftDetail.value || selectedRequest.value?.can_edit_expense_items));
const detailSources = computed(() => (isDraftDetail.value ? draftSources.value : financeSources.value));
const detailGroups = computed(() => groupSources(detailSources.value));
const detailGroupTotal = computed(() => detailGroups.value.reduce((sum, group) => sum + Number(group.total_amount || 0), 0));
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
function uniqueValues(values) {
  return [...new Set(values.map((value) => clean(value)).filter(Boolean))];
}
function optionalSum(sources, field) {
  const values = sources
    .map((source) => source[field])
    .filter((value) => value !== null && value !== undefined && value !== '');
  return values.length ? Math.round(values.reduce((sum, value) => sum + Number(value || 0), 0) * 100) / 100 : null;
}
function groupSources(sources) {
  const groups = new Map();
  (sources || []).forEach((source, index) => {
    const projectName = clean(source.project_name);
    const lineKey = clean(source.line_key) || `draft-${index + 1}`;
    const groupKey = projectName ? `project:${projectName}` : `line:${lineKey}`;
    if (!groups.has(groupKey)) groups.set(groupKey, { group_key: groupKey, project_name: projectName, source_line_keys: [], source_lines: [] });
    const group = groups.get(groupKey);
    group.source_line_keys.push(lineKey);
    group.source_lines.push(source);
  });
  return [...groups.values()].map((group) => {
    const items = uniqueValues(group.source_lines.map((source) => source.expense_item));
    return {
      ...group,
      source_count: group.source_lines.length,
      expense_item: items.length === 1 ? items[0] : '',
      needs_expense_item: items.length !== 1,
      invoice_category: uniqueValues(group.source_lines.map((source) => source.invoice_category)).join('、'),
      issue_date: uniqueValues(group.source_lines.map((source) => source.issue_date)).join('、'),
      invoice_number: uniqueValues(group.source_lines.map((source) => source.invoice_number)).join('、'),
      amount_before_tax: optionalSum(group.source_lines, 'amount_before_tax'),
      tax_amount: optionalSum(group.source_lines, 'tax_amount'),
      total_amount: optionalSum(group.source_lines, 'total_amount'),
    };
  });
}
function hydrateDraftSources(row) {
  const values = (row?.expense_lines || []).map((source) => ({ ...source, attachments: [...(source.attachments || [])] }));
  if (row?.kanban_status === 'draft') draftSources.value = values;
  financeSources.value = values;
}
function updateGroupField(group, field, value) {
  const keys = new Set(group.source_line_keys || []);
  const target = isDraftDetail.value ? draftSources : financeSources;
  target.value = target.value.map((source) => (
    keys.has(clean(source.line_key)) ? { ...source, [field]: value } : source
  ));
}
function updateSourceField(lineKey, field, value) {
  const target = isDraftDetail.value ? draftSources : financeSources;
  target.value = target.value.map((source) => (
    clean(source.line_key) === clean(lineKey)
      ? { ...source, [field]: value, description: field === 'expense_description' ? value : source.description }
      : source
  ));
}
function attachmentKey(lineKey) { return clean(lineKey); }
function setAttachmentBusy(lineKey, value) {
  attachmentBusy.value = { ...attachmentBusy.value, [attachmentKey(lineKey)]: value };
}
function invoicesForGroup(group) {
  return (group?.source_line_keys || []).flatMap((lineKey) => invoicesForLine(detailInvoices.value, lineKey));
}
function resetManualExpense() {
  Object.assign(manualExpense, { project_name: '', expense_item: '', issue_date: '', total_amount: '', expense_description: '', description: '', no_invoice_reason: '' });
}
function openManualExpense() {
  resetManualExpense();
  showManualExpense.value = true;
}
async function saveDraftSources(silent = false) {
  if (!selectedRequest.value || selectedRequest.value.kanban_status !== 'draft') return false;
  saving.value = true;
  errorMessage.value = '';
  try {
    const result = await draftSourceSaver.submit({
      name: selectedRequest.value.name,
      source_lines: JSON.stringify(draftSources.value),
    });
    hydrateDraftSources(result);
    if (!silent) message.value = '报销草稿费用明细已保存。';
    await requests.reload();
    return true;
  } catch (error) {
    errorMessage.value = apiError(error, '报销草稿保存失败');
    return false;
  } finally {
    saving.value = false;
  }
}
async function addManualExpense() {
  const row = {
    line_key: '', source_invoice: null, invoice_category: '',
    project_name: clean(manualExpense.project_name), expense_item: clean(manualExpense.expense_item),
    issue_date: manualExpense.issue_date, invoice_number: '', amount_before_tax: null, tax_amount: null,
    total_amount: Number(manualExpense.total_amount || 0), expense_description: clean(manualExpense.expense_description), description: clean(manualExpense.expense_description),
    no_invoice_reason: clean(manualExpense.no_invoice_reason),
  };
  if (!row.project_name || !row.issue_date || row.total_amount <= 0 || !row.expense_description || !row.no_invoice_reason) {
    errorMessage.value = 'Please complete all required expense fields; Finance may add the expense category later.';
    return;
  }
  draftSources.value.push(row);
  const saved = await saveDraftSources(true);
  if (saved) {
    showManualExpense.value = false;
    message.value = '手工费用已加入报销草稿。';
  } else {
    draftSources.value = draftSources.value.filter((source) => source !== row);
  }
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
  if (detailRequestName.value && !rows.value.some((row) => row.name === detailRequestName.value)) {
    await requestDetail.reload();
  }
  if (activeView.value === 'statistics') await statisticsView.value?.reload?.();
  if (activeView.value === 'audit') await approvalView.value?.reload?.();
}
async function saveRequest(submit) {
  errorMessage.value = '';
  const valid = expenseLines.value.filter((line) => Number(line.total_amount || 0) > 0);
  const hasIncompleteLine = expenseLines.value.some((line) => (
    !clean(line.project_name)
    || !line.issue_date
    || Number(line.total_amount || 0) <= 0
    || !clean(line.expense_description || line.description)
    || !clean(line.no_invoice_reason)
  ));
  if (!requestForm.department || hasIncompleteLine) {
    errorMessage.value = 'Please complete all required expense fields; Finance may add the expense category later.';
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
      no_invoice_reason: requestForm.no_invoice_reason.trim()
        || uniqueValues(valid.map((line) => line.no_invoice_reason)).join('；'),
    });
    showRequestForm.value = false;
    activeView.value = 'board';
    await reload();
    await openRequest(result.name);
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
async function openRequest(name) {
  const requestedName = String(name || '').trim();
  if (!requestedName) return;
  errorMessage.value = '';
  detailRequestName.value = requestedName;
  detailInvoices.value = [];
  if (rows.value.some((row) => row.name === requestedName)) {
    await loadInvoices(requestedName);
    return;
  }
  try {
    await requestDetail.reload();
    if (!requestDetail.data?.some((row) => row.name === requestedName)) {
      errorMessage.value = '无权限或单据不存在。';
      detailRequestName.value = '';
      detailInvoices.value = [];
      return;
    }
    await loadInvoices(requestedName);
  } catch (error) {
    errorMessage.value = apiError(error, '报销单详情加载失败');
    detailRequestName.value = '';
    detailInvoices.value = [];
  }
}
async function requestCreated(name) {
  activeView.value = 'board';
  await reload();
  await openRequest(name);
}
async function submitDraft(row) {
  if (row.kanban_status === 'draft' && !(await saveDraftSources(true))) return;
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

async function handleExpenseAttachments(source, event) {
  const input = event?.target;
  const files = Array.from(input?.files || []);
  if (!files.length || !selectedRequest.value) return;
  const lineKey = clean(source?.line_key);
  try {
    validateExpenseAttachments(files, source?.attachments?.length || 0);
  } catch (error) {
    errorMessage.value = apiError(error, '\u9644\u4ef6\u6821\u9a8c\u5931\u8d25');
    if (input) input.value = '';
    return;
  }
  setAttachmentBusy(lineKey, true);
  errorMessage.value = '';
  try {
    if (isDraftDetail.value && !(await saveDraftSources(true))) return;
    for (const file of files) await uploadExpenseAttachment(selectedRequest.value.name, lineKey, file);
    message.value = '\u8865\u5145\u9644\u4ef6\u5df2\u5b89\u5168\u4e0a\u4f20\u3002';
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '\u8865\u5145\u9644\u4ef6\u4e0a\u4f20\u5931\u8d25');
  } finally {
    setAttachmentBusy(lineKey, false);
    if (input) input.value = '';
  }
}
function openExpenseAttachment(attachment) {
  previewAttachmentRow.value = attachment ? { ...attachment } : null;
}
async function removeExpenseAttachment(attachment) {
  if (!selectedRequest.value || !attachment) return;
  if (!window.confirm('\u786e\u8ba4\u5220\u9664\u8be5\u8865\u5145\u9644\u4ef6\u5417\uff1f')) return;
  const lineKey = clean(attachment.expense_line_key);
  setAttachmentBusy(lineKey, true);
  try {
    await deleteExpenseAttachment(selectedRequest.value.name, attachment.name);
    message.value = '\u8865\u5145\u9644\u4ef6\u5df2\u5220\u9664\u3002';
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '\u8865\u5145\u9644\u4ef6\u5220\u9664\u5931\u8d25');
  } finally {
    setAttachmentBusy(lineKey, false);
  }
}
async function saveFinanceClassification() {
  if (!selectedRequest.value?.can_edit_expense_items) return false;
  saving.value = true;
  errorMessage.value = '';
  try {
    await saveFinanceExpenseItems(selectedRequest.value.name, financeSources.value);
    message.value = '\u8d39\u7528\u9879\u76ee\u5df2\u4fdd\u5b58\uff0c\u73b0\u5728\u53ef\u4ee5\u5ba1\u6279\u901a\u8fc7\u3002';
    await reload();
    return true;
  } catch (error) {
    errorMessage.value = apiError(error, '\u8d39\u7528\u9879\u76ee\u4fdd\u5b58\u5931\u8d25');
    return false;
  } finally {
    saving.value = false;
  }
}
function openReject(row) {
  rejectTarget.value = row?.rejection_targets?.[0]?.target || 'applicant';
  rejectReason.value = '';
  showRejectDialog.value = true;
}
async function submitReject() {
  if (!selectedRequest.value || !rejectTarget.value || !clean(rejectReason.value)) {
    errorMessage.value = '\u8bf7\u9009\u62e9\u9a73\u56de\u8282\u70b9\u5e76\u586b\u5199\u9a73\u56de\u539f\u56e0\u3002';
    return;
  }
  saving.value = true;
  try {
    await rejectRequest(selectedRequest.value.name, rejectTarget.value, rejectReason.value);
    showRejectDialog.value = false;
    actionNote.value = '';
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '\u9a73\u56de\u5931\u8d25');
  } finally {
    saving.value = false;
  }
}
async function loadPeople() {
  try {
    approvalPeople.value = await listApprovalPeople(peopleQuery.value);
  } catch (error) {
    errorMessage.value = apiError(error, '\u5ba1\u6279\u4eba\u52a0\u8f7d\u5931\u8d25');
  }
}
async function openAddSign() {
  Object.assign(addSignForm, { approver: '', position: 'before', opinion: '' });
  peopleQuery.value = '';
  showAddSignDialog.value = true;
  await loadPeople();
}
async function submitAddSign() {
  if (!selectedRequest.value || !addSignForm.approver || !clean(addSignForm.opinion)) {
    errorMessage.value = '\u8bf7\u9009\u62e9\u52a0\u7b7e\u5ba1\u6279\u4eba\u5e76\u586b\u5199\u52a0\u7b7e\u610f\u89c1\u3002';
    return;
  }
  saving.value = true;
  try {
    await addSignRequest(selectedRequest.value.name, addSignForm.approver, addSignForm.position, addSignForm.opinion);
    showAddSignDialog.value = false;
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '\u52a0\u7b7e\u5931\u8d25');
  } finally {
    saving.value = false;
  }
}
watch(() => options.data, applyDefaults, { immediate: true });
watch(selectedRequest, hydrateDraftSources, { immediate: true });
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
      <ExpenseStatistics v-else-if="activeView === 'statistics'" ref="statisticsView" :options="options.data || {}" @open-request="openRequest" />
      <ExpenseApprovalRecords v-else-if="activeView === 'audit'" ref="approvalView" :options="options.data || {}" @open-request="openRequest" />

      <section v-else-if="activeView === 'board'" class="space-y-4">
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
              <button v-for="row in rowsForStatus(column.key)" :key="row.name" class="w-full rounded border border-l-4 bg-white p-3 text-left shadow-sm hover:bg-gray-50" :class="column.accent" @click="openRequest(row.name)">
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
            <div class="mb-3 flex items-center justify-between">
              <div><h4 class="text-sm font-semibold">费用明细（无票/手工）</h4><p class="mt-1 text-xs text-gray-500">每行填写项目、费用项目、日期、税后金额、费用说明和无票原因。</p></div>
              <button class="text-sm text-blue-700" @click="addLine">＋ 添加明细</button>
            </div>
            <div class="overflow-x-auto rounded border border-gray-200">
              <table class="w-full min-w-[1320px] text-sm">
                <thead class="border-b bg-gray-50 text-gray-500"><tr><th class="px-3 py-2 text-left">项目名称</th><th class="px-3 py-2 text-left">费用项目</th><th class="px-3 py-2 text-left">日期</th><th class="px-3 py-2 text-right">税后金额</th><th class="px-3 py-2 text-left">费用说明</th><th class="px-3 py-2 text-left">无票原因</th><th class="w-10"></th></tr></thead>
                <tbody><tr v-for="(line,index) in expenseLines" :key="line.line_key" class="border-b last:border-0">
                  <td class="p-2"><input v-model="line.project_name" class="w-full rounded border border-gray-300 px-2 py-1.5" placeholder="必填" /></td>
                  <td class="p-2"><input v-model="line.expense_item" list="expense-item-options" class="w-full rounded border border-gray-300 px-2 py-1.5" placeholder="可下拉或填写" /></td>
                  <td class="p-2"><input v-model="line.issue_date" type="date" class="w-full rounded border border-gray-300 px-2 py-1.5" /></td>
                  <td class="p-2"><input v-model="line.total_amount" type="number" min="0.01" step="0.01" class="w-full rounded border border-gray-300 px-2 py-1.5 text-right" /></td>
                  <td class="p-2"><input v-model="line.expense_description" class="w-full rounded border border-gray-300 px-2 py-1.5" placeholder="费用说明" /></td>
                  <td class="p-2"><input v-model="line.no_invoice_reason" class="w-full rounded border border-gray-300 px-2 py-1.5" placeholder="例如：出差津贴" /></td>
                  <td class="p-2"><button title="删除明细" :disabled="expenseLines.length === 1" class="text-red-600 disabled:text-gray-300" @click="removeLine(index)"><FeatherIcon name="trash-2" class="h-4 w-4" /></button></td>
                </tr></tbody>
                <tfoot class="border-t bg-gray-50"><tr><td colspan="3" class="px-3 py-3 text-right font-medium">总费用发生额</td><td class="px-3 py-3 text-right text-base font-semibold text-red-600">{{ money(total) }}</td><td colspan="3"></td></tr></tfoot>
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
              <label class="text-xs text-gray-500 md:col-span-3">整单无票补充说明（可选）<textarea v-model="requestForm.no_invoice_reason" rows="2" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"></textarea></label>
            </div>
          </section>
        </div>
        <footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3"><Button variant="subtle" @click="showRequestForm = false">取消</Button><Button variant="subtle" :loading="saving" @click="saveRequest(false)">保存草稿</Button><Button variant="solid" :loading="saving" @click="saveRequest(true)">保存并提交</Button></footer>
      </div>
    </div>

    <div v-if="detailRequestName && !selectedRequest && requestDetail.loading" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4">
      <div class="rounded bg-white px-6 py-5 text-sm text-gray-600 shadow-xl">正在加载报销单详情...</div>
    </div>

    <div v-if="selectedRequest" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4" @click.self="detailRequestName = ''">
      <div role="dialog" aria-modal="true" class="flex max-h-[94vh] w-full max-w-7xl flex-col overflow-hidden rounded bg-white shadow-xl">
        <header class="flex items-center justify-between border-b bg-gray-50 px-5 py-4"><div><h3 class="font-semibold">{{ selectedRequest.name }} - 费用报销详情</h3><p class="mt-1 text-xs text-gray-500">{{ selectedRequest.subject }} · {{ sourceLabel(selectedRequest) }}</p></div><button title="关闭" @click="detailRequestName = ''"><FeatherIcon name="x" class="h-5 w-5" /></button></header>
        <div class="flex-1 space-y-5 overflow-y-auto p-5">
          <section><div class="mb-3 flex items-center justify-between"><h4 class="text-sm font-semibold">基本信息</h4><span class="rounded px-2 py-1 text-xs" :class="statusMeta(selectedRequest.kanban_status).badge">{{ statusMeta(selectedRequest.kanban_status).label }}</span></div><dl class="grid gap-3 text-sm md:grid-cols-4"><div><dt class="text-xs text-gray-500">公司</dt><dd class="mt-1">{{ selectedRequest.company || '-' }}</dd></div><div><dt class="text-xs text-gray-500">申请部门</dt><dd class="mt-1">{{ selectedRequest.department || '-' }}</dd></div><div><dt class="text-xs text-gray-500">申请人</dt><dd class="mt-1">{{ selectedRequest.employee_name || '-' }}</dd></div><div><dt class="text-xs text-gray-500">来源</dt><dd class="mt-1">{{ sourceLabel(selectedRequest) }}</dd></div></dl></section>
          <section>
<div class="mb-3 flex flex-wrap items-center justify-between gap-2">
  <div>
    <h4 class="text-sm font-semibold">&#x8D39;&#x7528;&#x660E;&#x7EC6;&#xFF08;&#x6309;&#x9879;&#x76EE;&#x540D;&#x79F0;&#x6C47;&#x603B;&#xFF09;</h4>
    <p class="mt-1 text-xs text-gray-500">&#x540C;&#x4E00;&#x9879;&#x76EE;&#x540D;&#x79F0;&#x6C47;&#x603B;&#x4E3A;&#x4E00;&#x7EC4;&#xFF1B;&#x8D39;&#x7528;&#x8BF4;&#x660E;&#x548C;&#x8865;&#x5145;&#x9644;&#x4EF6;&#x4ECD;&#x4FDD;&#x7559;&#x5728;&#x6BCF;&#x6761;&#x539F;&#x59CB;&#x660E;&#x7EC6;&#x4E0A;&#x3002;</p>
  </div>
  <div class="flex flex-wrap gap-2">
    <Button v-if="isDraftDetail" variant="subtle" @click="openManualExpense"><FeatherIcon name="plus" class="h-4 w-4" />&#x624B;&#x52A8;&#x589E;&#x52A0;</Button>
    <Button v-if="isDraftDetail" variant="solid" :loading="saving" @click="saveDraftSources(false)">&#x4FDD;&#x5B58;&#x8D39;&#x7528;&#x660E;&#x7EC6;</Button>
    <Button v-if="selectedRequest.can_edit_expense_items" variant="solid" :loading="saving" @click="saveFinanceClassification">&#x4FDD;&#x5B58;&#x8D39;&#x7528;&#x79D1;&#x76EE;</Button>
  </div>
</div>
<div v-if="selectedRequest.can_edit_expense_items && !selectedRequest.classification_ready" class="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
  &#x8D22;&#x52A1;&#x5BA1;&#x6279;&#x524D;&#x9700;&#x8981;&#x4E3A;&#x6240;&#x6709;&#x9879;&#x76EE;&#x9009;&#x62E9;&#x8D39;&#x7528;&#x79D1;&#x76EE;&#xFF0C;&#x4FDD;&#x5B58;&#x540E;&#x5373;&#x53EF;&#x5BA1;&#x6279;&#x901A;&#x8FC7;&#x3002;
</div>
<div class="overflow-x-auto rounded-lg border border-gray-200">
  <table class="w-full min-w-[1500px] text-sm">
    <thead class="border-b bg-gray-50 text-gray-500"><tr><th class="px-3 py-2 text-left">&#x53D1;&#x7968;&#x7C7B;&#x522B;</th><th class="px-3 py-2 text-left">&#x9879;&#x76EE;&#x540D;&#x79F0;</th><th class="px-3 py-2 text-left">&#x8D39;&#x7528;&#x79D1;&#x76EE;</th><th class="px-3 py-2 text-left">&#x5F00;&#x7968;&#x65E5;&#x671F;</th><th class="px-3 py-2 text-left">&#x53D1;&#x7968;&#x53F7;&#x7801;</th><th class="px-3 py-2 text-right">&#x7A0E;&#x524D;&#x91D1;&#x989D;</th><th class="px-3 py-2 text-right">&#x7A0E;&#x989D;</th><th class="px-3 py-2 text-right">&#x5408;&#x8BA1;&#x91D1;&#x989D;</th><th class="px-3 py-2 text-left">&#x53D1;&#x7968;&#x6587;&#x4EF6;</th></tr></thead>
    <tbody>
      <template v-for="group in detailGroups" :key="group.group_key">
        <tr class="border-b bg-white align-top">
          <td class="px-3 py-3">{{ group.invoice_category || '-' }}</td>
          <td class="px-3 py-2">
            <input v-if="isDraftDetail" :value="group.project_name" class="w-full min-w-[160px] rounded border border-gray-300 px-2 py-1.5" placeholder="&#x8BC6;&#x522B;&#x4E3A;&#x7A7A;&#x65F6;&#x8BF7;&#x586B;&#x5199;" @change="updateGroupField(group, 'project_name', $event.target.value)" />
            <span v-else>{{ group.project_name || '-' }}</span>
          </td>
          <td class="px-3 py-2">
            <input v-if="canEditExpenseItems" :value="group.expense_item" list="expense-item-options" class="w-full min-w-[170px] rounded border px-2 py-1.5" :class="selectedRequest.can_edit_expense_items && !group.expense_item ? 'border-amber-400 bg-amber-50' : 'border-gray-300'" placeholder="&#x9009;&#x62E9;&#x6216;&#x586B;&#x5199;&#xFF0C;&#x8D22;&#x52A1;&#x5BA1;&#x6279;&#x524D;&#x5FC5;&#x586B;" @input="updateGroupField(group, 'expense_item', $event.target.value)" />
            <span v-else>{{ group.expense_item || '-' }}</span>
          </td>
          <td class="px-3 py-3">{{ group.issue_date || '-' }}</td>
          <td class="px-3 py-3">{{ group.invoice_number || '-' }}</td>
          <td class="px-3 py-3 text-right">{{ money(group.amount_before_tax, true) }}</td>
          <td class="px-3 py-3 text-right">{{ money(group.tax_amount, true) }}</td>
          <td class="px-3 py-3 text-right font-semibold text-red-600">{{ money(group.total_amount, true) }}</td>
          <td class="px-3 py-3"><div class="flex min-w-[120px] flex-wrap gap-1"><button v-for="(invoice,index) in invoicesForGroup(group)" :key="invoice.name" class="rounded bg-blue-50 px-2 py-1 text-xs text-blue-700 hover:bg-blue-100" @click="previewInvoiceRow = invoice">&#x67E5;&#x770B;&#x53D1;&#x7968; {{ index + 1 }}</button><span v-if="!invoicesForGroup(group).length" class="text-gray-400">&#x65E0;&#x7968;</span></div></td>
        </tr>
        <tr class="border-b bg-gray-50/60">
          <td colspan="9" class="px-3 py-3">
            <div class="space-y-2">
              <div v-for="(source, sourceIndex) in group.source_lines" :key="source.line_key" class="grid gap-3 rounded-lg border border-gray-200 bg-white p-3 lg:grid-cols-[minmax(160px,0.8fr)_minmax(260px,1.3fr)_minmax(320px,1.5fr)]">
                <div class="min-w-0">
                  <div class="text-xs font-medium text-gray-700">&#x539F;&#x59CB;&#x660E;&#x7EC6; {{ sourceIndex + 1 }}</div>
                  <div class="mt-1 truncate text-[11px] text-gray-500">{{ source.invoice_number || source.invoice_category || source.project_name || '-' }}</div>
                </div>
                <label class="text-xs text-gray-500">&#x8D39;&#x7528;&#x8BF4;&#x660E;
                  <input v-if="isDraftDetail" :value="source.expense_description || source.description" class="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm" placeholder="&#x5458;&#x5DE5;&#x5FC5;&#x586B;&#x8D39;&#x7528;&#x8BF4;&#x660E;" @input="updateSourceField(source.line_key, 'expense_description', $event.target.value)" />
                  <div v-else class="mt-1 min-h-8 rounded bg-gray-50 px-2 py-1.5 text-sm text-gray-700">{{ source.expense_description || source.description || '-' }}</div>
                </label>
                <div class="text-xs text-gray-500">
                  <div class="flex items-center justify-between gap-2"><span>&#x8865;&#x5145;&#x9644;&#x4EF6; ({{ source.attachments?.length || 0 }}/10)</span><label v-if="isDraftDetail" class="cursor-pointer rounded bg-gray-100 px-2 py-1 text-gray-700 hover:bg-gray-200"><span v-if="attachmentBusy[attachmentKey(source.line_key)]">&#x4E0A;&#x4F20;&#x4E2D;...</span><span v-else>&#x6DFB;&#x52A0;&#x9644;&#x4EF6;</span><input type="file" accept=".pdf,.jpg,.jpeg,.png" multiple class="hidden" :disabled="attachmentBusy[attachmentKey(source.line_key)]" @change="handleExpenseAttachments(source, $event)" /></label></div>
                  <div class="mt-2 flex min-h-8 flex-wrap gap-1">
                    <span v-if="!source.attachments?.length" class="py-1 text-gray-400">&#x6682;&#x65E0;&#x8865;&#x5145;&#x9644;&#x4EF6;</span>
                    <span v-for="attachment in source.attachments || []" :key="attachment.name" class="inline-flex max-w-[240px] items-center gap-1 rounded bg-blue-50 px-2 py-1 text-blue-700"><button class="truncate" :title="attachment.original_filename" @click="openExpenseAttachment(attachment)">{{ attachment.original_filename }}</button><button v-if="isDraftDetail" class="text-red-600" title="Delete" @click="removeExpenseAttachment(attachment)">&times;</button></span>
                  </div>
                </div>
              </div>
            </div>
          </td>
        </tr>
      </template>
      <tr v-if="!detailGroups.length"><td colspan="9" class="px-3 py-10 text-center text-gray-400">&#x6682;&#x65E0;&#x8D39;&#x7528;&#x660E;&#x7EC6;</td></tr>
    </tbody>
    <tfoot class="border-t bg-gray-50"><tr><td colspan="7" class="px-3 py-3 text-right font-medium">&#x603B;&#x989D;</td><td class="px-3 py-3 text-right text-base font-semibold text-red-600">{{ money(detailGroupTotal) }}</td><td></td></tr></tfoot>
  </table>
</div>
          </section>
          <section><h4 class="mb-3 text-sm font-semibold">付款信息</h4><dl class="grid gap-3 text-sm md:grid-cols-3"><div><dt class="text-xs text-gray-500">付款类型</dt><dd class="mt-1">{{ selectedRequest.payment_type || '-' }}</dd></div><div><dt class="text-xs text-gray-500">付款方式</dt><dd class="mt-1">{{ selectedRequest.payment_method || '-' }}</dd></div><div><dt class="text-xs text-gray-500">收款人</dt><dd class="mt-1">{{ selectedRequest.payee_name || '-' }}</dd></div><div><dt class="text-xs text-gray-500">开户行/支行</dt><dd class="mt-1">{{ [selectedRequest.bank_name,selectedRequest.branch].filter(Boolean).join(' / ') || '-' }}</dd></div><div><dt class="text-xs text-gray-500">收款账号</dt><dd class="mt-1">{{ selectedRequest.account_no || '-' }}</dd></div><div><dt class="text-xs text-gray-500">付款时间</dt><dd class="mt-1">{{ dateText(selectedRequest.paid_on) }}</dd></div></dl></section>
          <section v-if="selectedRequest.no_invoice_reason"><h4 class="mb-2 text-sm font-semibold">无票原因</h4><p class="rounded bg-gray-50 p-3 text-sm text-gray-600 whitespace-pre-wrap">{{ selectedRequest.no_invoice_reason }}</p></section>
          <section><h4 class="mb-4 text-sm font-semibold">&#x5BA1;&#x6279;&#x8BB0;&#x5F55;</h4><div class="flex min-w-[760px] items-start overflow-x-auto"><template v-for="(step,index) in selectedRequest.steps || []" :key="step.step_key || step.step_index"><div class="w-40 shrink-0 text-center"><div class="mx-auto flex h-9 w-9 items-center justify-center rounded-full text-sm font-semibold" :class="['&#x5DF2;&#x901A;&#x8FC7;','&#x5DF2;&#x529E;&#x7406;'].includes(step.status) ? 'bg-emerald-600 text-white' : step.status === '&#x5DF2;&#x62D2;&#x7EDD;' ? 'bg-red-600 text-white' : step.step_index === selectedRequest.current_step_index ? 'bg-amber-500 text-white' : 'bg-gray-200 text-gray-600'">{{ step.step_index }}</div><div class="mt-2 text-xs font-medium">{{ step.label }}</div><div class="mt-1 text-[11px] text-gray-500">{{ step.approvers.join(' / ') }}</div><div v-if="step.origin === 'add_sign'" class="mt-1 text-[10px] font-medium text-blue-700">&#x52A0;&#x7B7E;&#x8282;&#x70B9;</div><div v-if="step.acted_on" class="mt-1 text-[10px] text-gray-400">{{ dateText(step.acted_on) }}</div><div v-if="step.note" class="mt-1 text-[10px] text-gray-500">{{ step.note }}</div><div v-if="step.add_sign_opinion" class="mt-1 rounded bg-blue-50 px-2 py-1 text-[10px] text-blue-700">&#x52A0;&#x7B7E;&#x610F;&#x89C1;&#xFF1A;{{ step.add_sign_opinion }}</div></div><div v-if="index < selectedRequest.steps.length - 1" class="mt-4 flex-1 border-t-2 border-dashed border-gray-300"></div></template></div></section>
          <section v-if="selectedRequest.operation_log?.length"><h4 class="mb-2 text-sm font-semibold">撤回/下推操作记录</h4><div class="space-y-2"><div v-for="(event,index) in selectedRequest.operation_log" :key="index" class="rounded bg-gray-50 p-3 text-xs text-gray-600"><span class="font-medium">{{ event.action }}</span> · {{ event.actor }} · {{ dateText(event.acted_on) }} · {{ event.from_status }} → {{ event.to_status }}<span v-if="event.note"> · {{ event.note }}</span></div></div></section>
        </div>
<footer class="flex flex-col gap-2 border-t bg-gray-50 px-5 py-3 md:flex-row md:items-center">
  <input v-model="actionNote" class="min-w-0 flex-1 rounded border border-gray-300 px-3 py-2 text-sm" placeholder="&#x5BA1;&#x6279;&#x3001;&#x4ED8;&#x6B3E;&#x6216;&#x64A4;&#x56DE;&#x5907;&#x6CE8;" />
  <div class="flex flex-wrap justify-end gap-2">
    <Button variant="subtle" @click="detailRequestName = ''">&#x5173;&#x95ED;</Button>
    <Button v-if="selectedRequest.can_withdraw" variant="subtle" @click="withdrawRequest(selectedRequest)">&#x64A4;&#x56DE;&#x7533;&#x8BF7;</Button>
    <Button v-if="selectedRequest.can_withdraw_payment" variant="subtle" @click="withdrawPayment(selectedRequest)">&#x64A4;&#x56DE;&#x4ED8;&#x6B3E;</Button>
    <Button v-if="selectedRequest.kanban_status === 'draft'" variant="solid" :loading="saving" @click="submitDraft(selectedRequest)">&#x63D0;&#x4EA4;&#x5BA1;&#x6279;</Button>
    <Button v-if="selectedRequest.can_add_sign" variant="subtle" @click="openAddSign">&#x52A0;&#x7B7E;</Button>
    <Button v-if="selectedRequest.can_reject && selectedRequest.current_step_mode !== 'handle'" variant="subtle" @click="openReject(selectedRequest)">&#x9A73;&#x56DE;</Button>
    <Button v-if="selectedRequest.can_approve" variant="solid" :loading="saving" @click="act(selectedRequest,'approve')"><span v-if="selectedRequest.current_step_mode === 'handle'">&#x529E;&#x7406;&#x5B8C;&#x6210;</span><span v-else>&#x5BA1;&#x6279;&#x901A;&#x8FC7;</span></Button>
    <Button v-else-if="selectedRequest.can_act && selectedRequest.current_step_mode !== 'handle'" variant="subtle" disabled title="Finance classification required">&#x8BF7;&#x5148;&#x8865;&#x5168;&#x8D39;&#x7528;&#x79D1;&#x76EE;</Button>
    <Button v-if="selectedRequest.can_mark_paid" variant="solid" @click="markPaid(selectedRequest)">&#x6807;&#x8BB0;&#x5DF2;&#x4ED8;&#x6B3E;</Button>
  </div>
</footer>
      </div>
    </div>

    <div v-if="showManualExpense" class="fixed inset-0 z-[60] flex items-center justify-center bg-gray-900/50 p-4" @click.self="showManualExpense = false">
      <div role="dialog" aria-modal="true" class="w-full max-w-2xl overflow-hidden rounded-lg bg-white shadow-2xl">
        <header class="flex items-center justify-between border-b bg-gray-50 px-5 py-4">
          <div><h3 class="font-semibold">手动增加费用</h3><p class="mt-1 text-xs text-gray-500">用于出差津贴等没有发票的费用，六项内容均需填写。</p></div>
          <button title="关闭" @click="showManualExpense = false"><FeatherIcon name="x" class="h-5 w-5" /></button>
        </header>
        <div class="grid gap-4 p-5 md:grid-cols-2">
          <label class="text-xs text-gray-500">项目名称<input v-model="manualExpense.project_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="必填" /></label>
          <label class="text-xs text-gray-500">费用项目<input v-model="manualExpense.expense_item" list="expense-item-options" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="可下拉或填写" /></label>
          <label class="text-xs text-gray-500">日期<input v-model="manualExpense.issue_date" type="date" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
          <label class="text-xs text-gray-500">税后金额<input v-model="manualExpense.total_amount" type="number" min="0.01" step="0.01" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm text-right" /></label>
          <label class="text-xs text-gray-500 md:col-span-2">费用说明<input v-model="manualExpense.expense_description" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="例如：深圳出差津贴" /></label>
          <label class="text-xs text-gray-500 md:col-span-2">无票原因<textarea v-model="manualExpense.no_invoice_reason" rows="3" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="说明为什么没有发票"></textarea></label>
        </div>
        <footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3"><Button variant="subtle" @click="showManualExpense = false">取消</Button><Button variant="solid" :loading="saving" @click="addManualExpense">确认添加</Button></footer>
      </div>
    </div>

<div v-if="showRejectDialog && selectedRequest" class="fixed inset-0 z-[70] flex items-center justify-center bg-gray-900/50 p-4" @click.self="showRejectDialog = false">
  <div role="dialog" aria-modal="true" class="w-full max-w-lg overflow-hidden rounded-xl bg-white shadow-2xl">
    <header class="flex items-center justify-between border-b px-5 py-4"><div><h3 class="font-semibold">&#x9A73;&#x56DE;&#x62A5;&#x9500;&#x7533;&#x8BF7;</h3><p class="mt-1 text-xs text-gray-500">&#x9009;&#x62E9;&#x8FD4;&#x56DE;&#x8282;&#x70B9;&#xFF0C;&#x8BE5;&#x8282;&#x70B9;&#x53CA;&#x5176;&#x540E;&#x6D41;&#x7A0B;&#x5C06;&#x91CD;&#x65B0;&#x6267;&#x884C;&#x3002;</p></div><button @click="showRejectDialog = false"><FeatherIcon name="x" class="h-5 w-5" /></button></header>
    <div class="space-y-4 p-5">
      <label class="block text-xs text-gray-500">&#x9A73;&#x56DE;&#x5230;<select v-model="rejectTarget" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="target in selectedRequest.rejection_targets || []" :key="target.target" :value="target.target">{{ target.step_index ? `${target.step_index}. ${target.label}` : target.label }}</option></select></label>
      <label class="block text-xs text-gray-500">&#x9A73;&#x56DE;&#x539F;&#x56E0;&#xFF08;&#x5FC5;&#x586B;&#xFF09;<textarea v-model="rejectReason" rows="4" maxlength="1000" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="&#x8BF4;&#x660E;&#x9A73;&#x56DE;&#x539F;&#x56E0;"></textarea></label>
    </div>
    <footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3"><Button variant="subtle" @click="showRejectDialog = false">&#x53D6;&#x6D88;</Button><Button variant="solid" :loading="saving" @click="submitReject">&#x786E;&#x8BA4;&#x9A73;&#x56DE;</Button></footer>
  </div>
</div>

<div v-if="showAddSignDialog && selectedRequest" class="fixed inset-0 z-[70] flex items-center justify-center bg-gray-900/50 p-4" @click.self="showAddSignDialog = false">
  <div role="dialog" aria-modal="true" class="w-full max-w-lg overflow-hidden rounded-xl bg-white shadow-2xl">
    <header class="flex items-center justify-between border-b px-5 py-4"><div><h3 class="font-semibold">&#x52A0;&#x7B7E;&#x5BA1;&#x6279;&#x4EBA;</h3><p class="mt-1 text-xs text-gray-500">&#x53EF;&#x591A;&#x6B21;&#x52A0;&#x7B7E;&#xFF0C;&#x672C;&#x5355;&#x5269;&#x4F59; {{ selectedRequest.add_sign_remaining ?? 0 }} &#x6B21;&#x3002;</p></div><button @click="showAddSignDialog = false"><FeatherIcon name="x" class="h-5 w-5" /></button></header>
    <div class="space-y-4 p-5">
      <label class="block text-xs text-gray-500">&#x641C;&#x7D22;&#x5BA1;&#x6279;&#x4EBA;<div class="mt-1 flex gap-2"><input v-model="peopleQuery" class="min-w-0 flex-1 rounded border border-gray-300 px-3 py-2 text-sm" placeholder="&#x59D3;&#x540D;&#x6216;&#x90AE;&#x7BB1;" @keyup.enter="loadPeople" /><Button variant="subtle" @click="loadPeople">&#x641C;&#x7D22;</Button></div></label>
      <label class="block text-xs text-gray-500">&#x52A0;&#x7B7E;&#x5BA1;&#x6279;&#x4EBA;<select v-model="addSignForm.approver" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">&#x8BF7;&#x9009;&#x62E9;</option><option v-for="person in approvalPeople" :key="person.user" :value="person.user">{{ person.label }} ({{ person.user }})</option></select></label>
      <fieldset><legend class="text-xs text-gray-500">&#x52A0;&#x7B7E;&#x4F4D;&#x7F6E;</legend><div class="mt-2 flex gap-6 text-sm"><label class="flex items-center gap-2"><input v-model="addSignForm.position" type="radio" value="before" />&#x5728;&#x6211;&#x4E4B;&#x524D;</label><label class="flex items-center gap-2"><input v-model="addSignForm.position" type="radio" value="after" />&#x5728;&#x6211;&#x4E4B;&#x540E;</label></div></fieldset>
      <label class="block text-xs text-gray-500">&#x52A0;&#x7B7E;&#x610F;&#x89C1;&#xFF08;&#x5FC5;&#x586B;&#xFF09;<textarea v-model="addSignForm.opinion" rows="4" maxlength="1000" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="&#x586B;&#x5199;&#x52A0;&#x7B7E;&#x539F;&#x56E0;&#x6216;&#x8981;&#x6C42;"></textarea></label>
    </div>
    <footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3"><Button variant="subtle" @click="showAddSignDialog = false">&#x53D6;&#x6D88;</Button><Button variant="solid" :loading="saving" @click="submitAddSign">&#x786E;&#x8BA4;&#x52A0;&#x7B7E;</Button></footer>
  </div>
</div>

    <datalist id="expense-item-options"><option v-for="item in expenseCategories" :key="item" :value="item"></option></datalist>
    <InvoicePreviewDrawer :open="Boolean(previewInvoiceRow)" :invoice="previewInvoiceRow" @close="previewInvoiceRow = null" />
    <InvoicePreviewDrawer :open="Boolean(previewAttachmentRow)" :invoice="previewAttachmentRow" :preview-loader="fetchExpenseAttachmentPreview" title="Expense attachment preview" @close="previewAttachmentRow = null" />
  </div>
</template>
