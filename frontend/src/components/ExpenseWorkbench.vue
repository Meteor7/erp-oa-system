<script setup>
import { Button, FeatherIcon, createResource } from 'frappe-ui';
import { computed, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  fetchInvoiceSupplementalAttachmentPreview, getRequestInvoices, invoicesForLine,
  newLineKey, withdrawInvoicePush,
} from '../lib/invoiceOcr.js';
import {
  addSignRequest, fetchExpenseAttachmentPreview, isStaleStepError, listApprovalPeople,
  rejectRequest, saveFinanceExpenseItems,
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
const ASSET_ADMIN = '非电子类固定资产（人事/行政）';
const ASSET_IT = '电子类固定资产（IT）';
const ASSET_OTHER = '其他';
const FALLBACK_ASSET_CATEGORIES = [ASSET_ADMIN, ASSET_IT, ASSET_OTHER];
const NAV_ITEMS = [
  { key: 'invoices', label: '上传发票', icon: 'upload-cloud' },
  { key: 'board', label: '付款/报销流程', icon: 'trello' },
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

const route = useRoute();
const router = useRouter();
const activeView = ref('invoices');
const detailRequestName = ref('');
const showRequestForm = ref(false);
const editingDraft = ref('');
const draftEditor = createResource({ url: 'rayher_hr_payroll.api.oa_entry.update_manual_expense_draft' });
const saving = ref(false);
const actionNote = ref('');
const message = ref('');
const errorMessage = ref('');
const detailInvoices = ref([]);
const previewInvoiceRow = ref(null);
const previewAttachmentRow = ref(null);
const financeSources = ref([]);
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
const showInvoiceSupplement = ref(false);
const manualExpense = reactive({
  project_name: '', expense_account_level_1: '', expense_account_level_2: '',
  issue_date: '', total_amount: '', expense_description: '', description: '',
});

const blankLine = () => ({
  line_key: newLineKey(),
  invoice_category: '',
  project_name: '',
  expense_account_level_1: '',
  expense_account_level_2: '',
  expense_item: '',
  issue_date: '',
  invoice_number: '',
  amount_before_tax: '',
  tax_amount: '',
  total_amount: '',
  expense_description: '',
  description: '',
  invoice_difference_reason: '',
});
const expenseLines = ref([blankLine()]);
const requestForm = reactive({
  subject: '', company: '', department: '', supervisor: '', doc_type: '', urgency: '',
  asset_category: '', payment_type: '支付个人', payment_method: '', bank_name: '',
  payee_name: '', branch: '', account_no: '', reason: '', no_invoice_reason: '',
  invoice_handling_mode: '', expected_invoice_date: '',
  payment_source_kind: '', source_request: '',
});

const options = createResource({ url: 'rayher_hr_payroll.api.oa_entry.get_options', method: 'GET', auto: true });
const expensePaymentSourceLoader = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.list_expense_payment_sources', method: 'GET',
  makeParams: () => ({ limit: 500 }), auto: true,
});
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
const invoiceVerifier = createResource({ url: 'rayher_hr_payroll.api.oa_entry.verify_request_invoices' });

const rows = computed(() => requests.data || []);
const exactRequest = computed(() => requestDetail.data?.[0] || null);
const selectedRequest = computed(() => rows.value.find((row) => row.name === detailRequestName.value)
  || (exactRequest.value?.name === detailRequestName.value ? exactRequest.value : null));
const departments = computed(() => options.data?.departments || []);
const companies = computed(() => options.data?.companies || []);
const docTypes = computed(() => options.data?.expense_doc_types || ['非固定资产', '固定资产']);
const isFixedAsset = computed(() => requestForm.doc_type.startsWith('固定资产'));
const urgencies = computed(() => options.data?.urgencies || []);
const assetCategories = computed(() => (options.data?.asset_categories || FALLBACK_ASSET_CATEGORIES).filter((item) => item !== ASSET_OTHER));
const paymentTypes = computed(() => options.data?.payment_types || []);
const paymentMethods = computed(() => options.data?.payment_methods || []);
const invoiceHandlingModes = computed(() => options.data?.invoice_handling_modes || ['已有发票', '暂未取得发票', '无需发票']);
const expensePaymentSources = computed(() => expensePaymentSourceLoader.data || []);
const selectedPaymentSource = computed(() => expensePaymentSources.value.find((row) => row.name === requestForm.source_request) || null);
const expenseAccountTree = computed(() => options.data?.expense_account_tree || []);
const isDraftDetail = computed(() => selectedRequest.value?.kanban_status === 'draft');
const canEditExpenseItems = computed(() => Boolean(selectedRequest.value?.can_edit_expense_items));
const previewAttachmentLoader = computed(() => (
  previewAttachmentRow.value?.attachment_source === 'invoice'
    ? fetchInvoiceSupplementalAttachmentPreview
    : fetchExpenseAttachmentPreview
));
const canWithdrawInvoicePush = computed(() => Boolean(
  isDraftDetail.value
  && selectedRequest.value?.from_invoice_push
  && detailInvoices.value.length,
));
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
  return '手工新建';
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
    const level1Values = uniqueValues(group.source_lines.map((source) => source.expense_account_level_1));
    const level2Values = uniqueValues(group.source_lines.map((source) => source.expense_account_level_2));
    return {
      ...group,
      source_count: group.source_lines.length,
      expense_item: items.length === 1 ? items[0] : '',
      expense_account_level_1: level1Values.length === 1 ? level1Values[0] : '',
      expense_account_level_2: level2Values.length === 1 ? level2Values[0] : '',
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
function accountChildren(level1) {
  return expenseAccountTree.value.find((item) => item.level_1 === clean(level1))?.level_2 || [];
}
function updateGroupAccount(group, level, value) {
  updateGroupField(group, level, value);
  if (level === 'expense_account_level_1') {
    updateGroupField(group, 'expense_account_level_2', '');
  }
}
function updateSourceField(lineKey, field, value) {
  const target = isDraftDetail.value ? draftSources : financeSources;
  target.value = target.value.map((source) => (
    clean(source.line_key) === clean(lineKey)
      ? { ...source, [field]: value, description: field === 'expense_description' ? value : source.description }
      : source
  ));
}
function invoicesForGroup(group) {
  return (group?.source_line_keys || []).flatMap((lineKey) => invoicesForLine(detailInvoices.value, lineKey));
}
function invoiceForSource(source) {
  return detailInvoices.value.find((invoice) => invoice.name === source?.source_invoice)
    || invoicesForLine(detailInvoices.value, source?.line_key)?.[0]
    || null;
}
function resetManualExpense() {
  Object.assign(manualExpense, {
    project_name: '', expense_account_level_1: '', expense_account_level_2: '',
    issue_date: '', total_amount: '', expense_description: '', description: '',
  });
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
    if (!silent) message.value = '付款/报销草稿费用明细已保存。';
    await requests.reload();
    return true;
  } catch (error) {
    errorMessage.value = apiError(error, '付款/报销草稿保存失败');
    return false;
  } finally {
    saving.value = false;
  }
}
async function addManualExpense() {
  const row = {
    line_key: '', source_invoice: null, invoice_category: '',
    project_name: clean(manualExpense.project_name),
    expense_account_level_1: clean(manualExpense.expense_account_level_1),
    expense_account_level_2: clean(manualExpense.expense_account_level_2),
    issue_date: manualExpense.issue_date, invoice_number: '', amount_before_tax: null, tax_amount: null,
    total_amount: Number(manualExpense.total_amount || 0), expense_description: clean(manualExpense.expense_description), description: clean(manualExpense.expense_description),
  };
  const children = accountChildren(row.expense_account_level_1);
  if (!row.project_name || !row.expense_account_level_1 || (children.length && !row.expense_account_level_2)
    || !row.issue_date || row.total_amount <= 0 || !row.expense_description) {
    errorMessage.value = '请完整填写项目名称、费用科目、日期、税后金额和费用说明。';
    return;
  }
  draftSources.value.push(row);
  const saved = await saveDraftSources(true);
  if (saved) {
    showManualExpense.value = false;
    message.value = '手工费用已加入付款/报销草稿。';
  } else {
    draftSources.value = draftSources.value.filter((source) => source !== row);
  }
}
function applyDefaults() {
  const context = options.data?.context || {};
  requestForm.company ||= first(companies.value);
  requestForm.department = context.department || '';
  requestForm.supervisor = context.supervisor || '';
  requestForm.doc_type ||= first(docTypes.value);
  requestForm.urgency ||= first(urgencies.value);
  requestForm.payment_type ||= first(paymentTypes.value);
  requestForm.payment_method ||= first(paymentMethods.value);
  requestForm.payee_name ||= context.employee_name || '';
}
function resetForm() {
  Object.assign(requestForm, {
    subject: '', company: '', department: '', supervisor: '', doc_type: '', urgency: '',
    asset_category: '', payment_type: '', payment_method: '', bank_name: '',
    payee_name: '', branch: '', account_no: '', reason: '', no_invoice_reason: '',
    invoice_handling_mode: '', expected_invoice_date: '',
    payment_source_kind: '', source_request: '',
  });
  expenseLines.value = [blankLine()];
  applyDefaults();
}
function openManualRequest() {
  editingDraft.value = '';
  errorMessage.value = '';
  resetForm();
  showRequestForm.value = true;
}
function editManualDraft(row) {
  resetForm();
  editingDraft.value = row.name;
  for (const key of Object.keys(requestForm)) requestForm[key] = row[key] || '';
  requestForm.doc_type = String(row.doc_type || '').startsWith('固定资产') ? '固定资产' : '非固定资产';
  expenseLines.value = (row.expense_lines || []).map((line) => ({ ...blankLine(), ...line, total_amount: line.total_amount ?? line.amount ?? '' }));
  if (!expenseLines.value.length) expenseLines.value = [blankLine()];
  applyDefaults();
  detailRequestName.value = '';
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
  const valid = submit ? expenseLines.value.filter((line) => Number(line.total_amount || 0) > 0) : expenseLines.value.filter((line) => Object.entries(line).some(([key, value]) => key !== 'line_key' && value !== '' && value !== null));
  const hasIncompleteLine = expenseLines.value.some((line) => (
    !clean(line.project_name)
    || !clean(line.expense_account_level_1)
    || (accountChildren(line.expense_account_level_1).length && !clean(line.expense_account_level_2))
    || !line.issue_date
    || Number(line.total_amount || 0) <= 0
    || !clean(line.expense_description || line.description)
  ));
  if (submit && (!requestForm.department || (isFixedAsset.value && !requestForm.asset_category) || !requestForm.invoice_handling_mode || hasIncompleteLine || !valid.length)) {
    errorMessage.value = '请完整填写申请部门、固定资产类型、发票处理方式、项目名称、费用科目、日期、金额和费用说明。';
    return;
  }
  if (submit && ['暂未取得发票', '无需发票'].includes(requestForm.invoice_handling_mode) && !requestForm.source_request) {
    errorMessage.value = '公司事前付款必须关联一张已审批通过且仍有可付款余额的购买申请。';
    return;
  }
  if (requestForm.invoice_handling_mode === '已有发票') {
    errorMessage.value = '已有发票请从“上传发票”页面识别后生成申请。';
    return;
  }
  if (submit && (!clean(requestForm.no_invoice_reason) || (requestForm.invoice_handling_mode === '暂未取得发票' && !requestForm.expected_invoice_date))) {
    errorMessage.value = '请填写发票情况说明；暂未取得发票时还需填写预计取得日期。';
    return;
  }
  saving.value = true;
  try {
    const payload = {
      request_type: REQUEST_TYPE,
      subject: requestForm.subject.trim() || valid[0]?.project_name || valid[0]?.invoice_category || '费用付款/报销',
      department: requestForm.department,
      asset_category: isFixedAsset.value ? requestForm.asset_category : ASSET_OTHER,
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
      no_invoice_reason: requestForm.no_invoice_reason,
      invoice_handling_mode: requestForm.invoice_handling_mode,
      expected_invoice_date: requestForm.expected_invoice_date || '',
      payment_source_kind: requestForm.source_request ? '关联购买申请' : '无事前申请',
      source_request: requestForm.source_request || '',
    };
    let result;
    if (editingDraft.value) {
      result = await draftEditor.submit({ name: editingDraft.value, payload: JSON.stringify({ ...payload, expense_lines: JSON.parse(payload.expense_lines) }) });
      if (submit) await draftSubmitter.submit({ name: result.name, no_invoice_reason: requestForm.no_invoice_reason });
    } else {
      result = await creator.submit(payload);
    }
    showRequestForm.value = false;
    activeView.value = 'board';
    await reload();
    await openRequest(result.name);
  } catch (error) {
    errorMessage.value = apiError(error, '付款/报销单保存失败');
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
    errorMessage.value = apiError(error, '付款/报销单详情加载失败');
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
  // 防重入：处理中再点不会再提交一次（修复 2026-09-29，审查 #10）。
  if (saving.value) return;
  saving.value = true;
  try {
    await actor.submit({ name: row.name, action, note: actionNote.value.trim(), expected_step_key: row.current_step_key || '' });
    actionNote.value = '';
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '审批处理失败');
    if (isStaleStepError(error)) await reload();
  } finally {
    saving.value = false;
  }
}
async function markPaid(row) {
  if (saving.value) return;
  saving.value = true;
  try {
    await paidMarker.submit({ name: row.name, note: actionNote.value.trim() });
    actionNote.value = '';
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '付款标记失败');
  } finally {
    saving.value = false;
  }
}
async function withdrawRequest(row) {
  if (!window.confirm('确认撤回该付款/报销申请到草稿吗？审批操作会保留在日志中。')) return;
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

async function invoiceSupplemented(name) {
  showInvoiceSupplement.value = false;
  message.value = `发票已补录到 ${name}。`;
  await reload();
  await loadInvoices(name);
}

async function verifyInvoices(row) {
  saving.value = true;
  errorMessage.value = '';
  try {
    await invoiceVerifier.submit({ name: row.name, note: actionNote.value.trim() });
    actionNote.value = '';
    message.value = '发票已由财务确认核验。';
    await reload();
    await loadInvoices(row.name);
  } catch (error) {
    errorMessage.value = apiError(error, '发票核验失败');
  } finally {
    saving.value = false;
  }
}

async function withdrawPushedInvoices(row) {
  if (!canWithdrawInvoicePush.value) return;
  if (!window.confirm('撤回下推会解除这些发票与付款/报销草稿的关联，发票将重新回到上传发票页面，是否继续？')) return;
  saving.value = true;
  errorMessage.value = '';
  try {
    await withdrawInvoicePush(
      detailInvoices.value.map((invoice) => invoice.name),
      actionNote.value.trim() || '从付款/报销草稿撤回发票下推',
    );
    actionNote.value = '';
    message.value = '已撤回下推，发票已重新回到上传发票页面。';
    await reload();
    await loadInvoices(row.name);
  } catch (error) {
    errorMessage.value = apiError(error, '撤回下推失败');
  } finally {
    saving.value = false;
  }
}

function openExpenseAttachment(attachment) {
  previewAttachmentRow.value = attachment ? { ...attachment } : null;
}
async function saveFinanceClassification() {
  if (!selectedRequest.value?.can_edit_expense_items) return false;
  saving.value = true;
  errorMessage.value = '';
  try {
    await saveFinanceExpenseItems(selectedRequest.value.name, financeSources.value);
    message.value = '\u8d39\u7528\u79d1\u76ee\u5df2\u4fdd\u5b58\uff0c\u73b0\u5728\u53ef\u4ee5\u5ba1\u6279\u901a\u8fc7\u3002';
    await reload();
    return true;
  } catch (error) {
    errorMessage.value = apiError(error, '\u8d39\u7528\u79d1\u76ee\u4fdd\u5b58\u5931\u8d25');
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
    await rejectRequest(selectedRequest.value.name, rejectTarget.value, rejectReason.value, { expectedStepKey: selectedRequest.value.current_step_key });
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
    approvalPeople.value = await listApprovalPeople(peopleQuery.value, { name: selectedRequest.value?.name });
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
    await addSignRequest(selectedRequest.value.name, addSignForm.approver, addSignForm.position, addSignForm.opinion, { expectedStepKey: selectedRequest.value.current_step_key });
    showAddSignDialog.value = false;
    await reload();
  } catch (error) {
    errorMessage.value = apiError(error, '\u52a0\u7b7e\u5931\u8d25');
  } finally {
    saving.value = false;
  }
}
// 待办和通知里"费用付款申请"的链接是 /approval/reimbursement?request=单号：旧页面原来不读地址，打开后是空白首页。
// 现在直接打开这张单据（详情弹层）；关掉弹层时把地址里的 request 去掉，同一个链接可以再次打开。
watch(() => route.query.request, (name) => {
  const wanted = String(name || '').trim();
  if (!wanted || wanted === detailRequestName.value) return;
  activeView.value = 'board';
  openRequest(wanted);
}, { immediate: true });
watch(detailRequestName, (value) => {
  if (!value && route.query.request) router.replace({ path: route.path, query: {} });
});
watch(() => options.data, applyDefaults, { immediate: true });
watch(() => requestForm.doc_type, () => { if (!isFixedAsset.value) requestForm.asset_category = ''; }, { flush: 'sync' });
watch(selectedRequest, hydrateDraftSources, { immediate: true });
watch(() => requestForm.invoice_handling_mode, (mode) => {
  if (mode === '已有发票') {
    requestForm.payment_source_kind = '无事前申请';
    requestForm.source_request = '';
  } else if (['暂未取得发票', '无需发票'].includes(mode)) {
    requestForm.payment_source_kind = '关联购买申请';
  }
});
</script>

<template>
  <div class="flex min-h-[calc(100vh-120px)] gap-4">
    <aside class="w-44 shrink-0 rounded border bg-white p-3 shadow-sm">
      <div class="mb-4 flex items-center gap-2 border-b pb-3">
        <div class="rounded bg-amber-50 p-2 text-amber-700"><FeatherIcon name="briefcase" class="h-4 w-4" /></div>
        <div><div class="text-sm font-semibold">费用管理</div><div class="text-[11px] text-gray-500">付款、报销与发票</div></div>
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
          <div><h2 class="text-xl font-bold">付款/报销流程</h2><p class="mt-1 text-sm text-gray-500">统一审批流程，通过发票取得时间区分业务</p></div>
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
          <Button variant="solid" @click="openManualRequest"><FeatherIcon name="plus" class="h-4 w-4" />新建付款/报销单</Button>
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
          <div><h3 class="font-semibold">{{ editingDraft ? '编辑付款/报销草稿' : '新建付款/报销单' }}</h3><p class="mt-1 text-xs text-gray-500">审批流保持一致，发票方式按本次业务实际情况选择。</p></div>
          <button title="关闭" @click="showRequestForm = false"><FeatherIcon name="x" class="h-5 w-5" /></button>
        </header>
        <div class="flex-1 space-y-5 overflow-y-auto p-5">
          <section>
            <h4 class="mb-3 text-sm font-semibold">基本信息</h4>
            <div class="grid gap-3 md:grid-cols-3">
              <label class="text-xs text-gray-500">主题<input v-model="requestForm.subject" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500">公司<select v-model="requestForm.company" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in companies" :key="item">{{ item }}</option></select></label>
              <label class="text-xs text-gray-500">申请部门<input :value="requestForm.department" readonly class="mt-1 w-full rounded border border-gray-300 bg-gray-50 px-3 py-2 text-sm" placeholder="请在人事档案中维护部门" /></label>
              <div data-testid="resolved-supervisor" class="text-xs text-gray-500">部门主管<div class="mt-1 min-h-9 rounded border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700">{{ requestForm.supervisor || '由系统按组织架构判断' }}</div></div>
              <label class="text-xs text-gray-500">单据类型<select v-model="requestForm.doc_type" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in docTypes" :key="item">{{ item }}</option></select></label>
              <label class="text-xs text-gray-500">紧急程度<select v-model="requestForm.urgency" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in urgencies" :key="item">{{ item }}</option></select></label>
              <label v-if="isFixedAsset" class="text-xs text-gray-500">资产类型（必选）<select v-model="requestForm.asset_category" data-testid="asset-category-select" required class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">请选择资产类型</option><option v-for="item in assetCategories" :key="item" :value="item">{{ item }}</option></select></label>
              <div class="md:col-span-3">
                <p class="text-xs font-medium text-gray-600">业务性质与发票状态（必选）</p>
                <div class="mt-2 grid overflow-hidden rounded-md border border-gray-300 md:grid-cols-3">
                  <button type="button" class="min-h-16 border-b px-4 py-3 text-left last:border-0 md:border-b-0 md:border-r" :class="requestForm.invoice_handling_mode === '已有发票' ? 'bg-blue-50 text-blue-800' : 'bg-white text-gray-700'" @click="requestForm.invoice_handling_mode = '已有发票'"><span class="block text-sm font-semibold">员工垫付报销</span><span class="mt-1 block text-xs opacity-75">已有发票，从发票识别生成</span></button>
                  <button type="button" class="min-h-16 border-b px-4 py-3 text-left last:border-0 md:border-b-0 md:border-r" :class="requestForm.invoice_handling_mode === '暂未取得发票' ? 'bg-amber-50 text-amber-800' : 'bg-white text-gray-700'" @click="requestForm.invoice_handling_mode = '暂未取得发票'"><span class="block text-sm font-semibold">事前申请付款</span><span class="mt-1 block text-xs opacity-75">关联购买申请，付款后补票</span></button>
                  <button type="button" class="min-h-16 px-4 py-3 text-left" :class="requestForm.invoice_handling_mode === '无需发票' ? 'bg-emerald-50 text-emerald-800' : 'bg-white text-gray-700'" @click="requestForm.invoice_handling_mode = '无需发票'"><span class="block text-sm font-semibold">事前申请付款</span><span class="mt-1 block text-xs opacity-75">关联购买申请，依法无需发票</span></button>
                </div>
              </div>
              <label v-if="['暂未取得发票','无需发票'].includes(requestForm.invoice_handling_mode)" class="text-xs text-gray-500 md:col-span-2">来源购买申请（必选）<select v-model="requestForm.source_request" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option value="">请选择已审批通过的购买申请</option><option v-for="item in expensePaymentSources" :key="item.name" :value="item.name">{{ item.name }} · {{ item.subject }} · 可付 {{ money(item.available_amount) }}</option></select></label>
              <div v-if="selectedPaymentSource" class="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600"><span class="font-medium text-gray-900">{{ selectedPaymentSource.employee_name }}</span><span class="mx-2">{{ selectedPaymentSource.department }}</span><span>批准 {{ money(selectedPaymentSource.approved_amount) }}</span><span class="ml-2">已付 {{ money(selectedPaymentSource.paid_amount) }}</span></div>
              <label v-if="requestForm.invoice_handling_mode === '暂未取得发票'" class="text-xs text-gray-500">预计取得发票日期<input v-model="requestForm.expected_invoice_date" type="date" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label v-if="['暂未取得发票','无需发票'].includes(requestForm.invoice_handling_mode)" class="text-xs text-gray-500 md:col-span-3">发票情况说明<textarea v-model="requestForm.no_invoice_reason" rows="2" maxlength="1000" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"></textarea></label>
              <p v-if="requestForm.invoice_handling_mode === '已有发票'" class="text-xs text-blue-700 md:col-span-3">请关闭本窗口并进入“上传发票”，完成识别确认后生成申请。</p>
            </div>
          </section>
          <section>
            <div class="mb-3 flex items-center justify-between">
              <div><h4 class="text-sm font-semibold">费用明细（无票/手工）</h4><p class="mt-1 text-xs text-gray-500">每行填写项目、一级/二级费用科目、日期、税后金额和费用说明。</p></div>
              <button class="text-sm text-blue-700" @click="addLine">＋ 添加明细</button>
            </div>
            <div class="overflow-x-auto rounded border border-gray-200">
              <table class="w-full min-w-[1240px] text-sm">
                <thead class="border-b bg-gray-50 text-gray-500"><tr><th class="px-3 py-2 text-left">项目名称</th><th class="px-3 py-2 text-left">一级费用科目</th><th class="px-3 py-2 text-left">二级费用科目</th><th class="px-3 py-2 text-left">日期</th><th class="px-3 py-2 text-right">税后金额</th><th class="px-3 py-2 text-left">费用说明</th><th class="w-10"></th></tr></thead>
                <tbody><tr v-for="(line,index) in expenseLines" :key="line.line_key" class="border-b last:border-0">
                  <td class="p-2"><input v-model="line.project_name" class="w-full rounded border border-gray-300 px-2 py-1.5" placeholder="必填" /></td>
                  <td class="p-2"><select v-model="line.expense_account_level_1" class="w-full rounded border border-gray-300 px-2 py-1.5" @change="line.expense_account_level_2 = ''"><option value="">请选择</option><option v-for="item in expenseAccountTree" :key="item.level_1" :value="item.level_1">{{ item.level_1 }}</option></select></td>
                  <td class="p-2"><select v-model="line.expense_account_level_2" class="w-full rounded border border-gray-300 px-2 py-1.5" :disabled="!accountChildren(line.expense_account_level_1).length"><option value="">{{ accountChildren(line.expense_account_level_1).length ? '请选择' : '无二级科目' }}</option><option v-for="item in accountChildren(line.expense_account_level_1)" :key="item" :value="item">{{ item }}</option></select></td>
                  <td class="p-2"><input v-model="line.issue_date" type="date" class="w-full rounded border border-gray-300 px-2 py-1.5" /></td>
                  <td class="p-2"><input v-model="line.total_amount" type="number" min="0.01" step="0.01" class="w-full rounded border border-gray-300 px-2 py-1.5 text-right" /></td>
                  <td class="p-2"><input v-model="line.expense_description" class="w-full rounded border border-gray-300 px-2 py-1.5" placeholder="费用说明" /></td>
                  <td class="p-2"><button title="删除明细" :disabled="expenseLines.length === 1" class="text-red-600 disabled:text-gray-300" @click="removeLine(index)"><FeatherIcon name="trash-2" class="h-4 w-4" /></button></td>
                </tr></tbody>
                <tfoot class="border-t bg-gray-50"><tr><td colspan="4" class="px-3 py-3 text-right font-medium">总费用发生额</td><td class="px-3 py-3 text-right text-base font-semibold text-red-600">{{ money(total) }}</td><td colspan="2"></td></tr></tfoot>
              </table>
            </div>
          </section>
          <section>
            <h4 class="mb-3 text-sm font-semibold">付款信息</h4>
            <div class="grid gap-3 md:grid-cols-3">
              <label class="text-xs text-gray-500">付款类型<input v-model="requestForm.payment_type" list="request-payment-type-suggestions" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="可自由填写" /><datalist id="request-payment-type-suggestions"><option v-for="item in paymentTypes" :key="item" :value="item" /></datalist></label>
              <label class="text-xs text-gray-500">付款方式<select v-model="requestForm.payment_method" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in paymentMethods" :key="item">{{ item }}</option></select></label>
              <label class="text-xs text-gray-500">收款人<input v-model="requestForm.payee_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500">开户行<input v-model="requestForm.bank_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500">支行<input v-model="requestForm.branch" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500">收款账号<input v-model="requestForm.account_no" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs text-gray-500 md:col-span-3">情况说明/备注<textarea v-model="requestForm.reason" rows="2" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"></textarea></label>
            </div>
          </section>
        </div>
        <footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3"><Button variant="subtle" @click="showRequestForm = false">取消</Button><Button variant="subtle" :loading="saving" @click="saveRequest(false)">保存草稿</Button><Button variant="solid" :loading="saving" @click="saveRequest(true)">保存并提交</Button></footer>
      </div>
    </div>

    <div v-if="detailRequestName && !selectedRequest && requestDetail.loading" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4">
      <div class="rounded bg-white px-6 py-5 text-sm text-gray-600 shadow-xl">正在加载付款/报销单详情...</div>
    </div>

    <div v-if="selectedRequest" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/45 p-3 sm:p-4" @click.self="detailRequestName = ''">
      <div data-testid="expense-detail-workbench" role="dialog" aria-modal="true" class="flex max-h-[94vh] w-full max-w-[1500px] flex-col overflow-hidden rounded-xl bg-white shadow-2xl ring-1 ring-black/5">
        <header class="sticky top-0 z-20 flex shrink-0 items-start justify-between gap-4 border-b border-gray-200 bg-white px-5 py-4 sm:px-6">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="truncate text-lg font-semibold text-gray-900">{{ selectedRequest.name }} - 付款/报销详情</h3>
              <span class="rounded-full px-2.5 py-1 text-xs font-medium" :class="statusMeta(selectedRequest.kanban_status).badge">{{ statusMeta(selectedRequest.kanban_status).label }}</span>
              <span v-if="selectedRequest.action_scope === 'override'" class="rounded-full bg-violet-50 px-2.5 py-1 text-xs font-medium text-violet-700">&#x4E1A;&#x52A1;&#x7BA1;&#x7406;&#x4EE3;&#x529E;</span>
            </div>
            <p class="mt-1 truncate text-sm text-gray-500">{{ selectedRequest.subject }} &middot; {{ sourceLabel(selectedRequest) }}</p>
          </div>
          <button class="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-900" title="&#x5173;&#x95ED;" @click="detailRequestName = ''"><FeatherIcon name="x" class="h-5 w-5" /></button>
        </header>

        <div class="flex-1 overflow-y-auto bg-gray-50/70">
          <section data-testid="expense-summary" class="grid gap-px border-b border-gray-200 bg-gray-200 sm:grid-cols-2 xl:grid-cols-6">
            <div class="bg-white px-5 py-3"><div class="text-xs text-gray-500">&#x516C;&#x53F8;</div><div class="mt-1 truncate text-sm font-medium text-gray-900" :title="selectedRequest.company">{{ selectedRequest.company || '-' }}</div></div>
            <div class="bg-white px-5 py-3"><div class="text-xs text-gray-500">&#x7533;&#x8BF7;&#x4EBA;</div><div class="mt-1 text-sm font-medium text-gray-900">{{ selectedRequest.employee_name || '-' }}</div></div>
            <div class="bg-white px-5 py-3"><div class="text-xs text-gray-500">&#x7533;&#x8BF7;&#x90E8;&#x95E8;</div><div class="mt-1 text-sm font-medium text-gray-900">{{ selectedRequest.department || '-' }}</div></div>
            <div class="bg-white px-5 py-3"><div class="text-xs text-gray-500">&#x5F53;&#x524D;&#x8282;&#x70B9;</div><div class="mt-1 truncate text-sm font-medium text-gray-900" :title="selectedRequest.current_step_label">{{ selectedRequest.current_step_label || '-' }}</div></div>
            <div class="bg-white px-5 py-3"><div class="text-xs text-gray-500">发票状态</div><div class="mt-1 text-sm font-semibold text-gray-900">{{ selectedRequest.invoice_followup_status || selectedRequest.invoice_status || '-' }} · {{ selectedRequest.invoice_count || 0 }} 张</div></div>
            <div class="bg-white px-5 py-3"><div class="text-xs text-gray-500">付款/报销总额</div><div class="mt-1 text-base font-semibold text-red-600">{{ money(detailGroupTotal || selectedRequest.amount) }}</div></div>
          </section>

          <div class="grid gap-5 p-4 sm:p-5 xl:grid-cols-[minmax(0,1fr)_300px] xl:items-start">
            <main class="min-w-0 space-y-4">
              <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <h4 class="text-base font-semibold text-gray-900">&#x8D39;&#x7528;&#x660E;&#x7EC6;</h4>
                  <p class="mt-1 text-xs leading-5 text-gray-500">&#x6309;&#x9879;&#x76EE;&#x540D;&#x79F0;&#x6C47;&#x603B;&#xFF0C;&#x53D1;&#x7968;&#x3001;&#x8BF4;&#x660E;&#x548C;&#x9644;&#x4EF6;&#x4ECD;&#x4FDD;&#x7559;&#x5728;&#x5BF9;&#x5E94;&#x660E;&#x7EC6;&#x4E2D;&#x3002;</p>
                </div>
                <div v-if="isDraftDetail" class="flex shrink-0 flex-wrap gap-2">
                  <Button variant="subtle" @click="openManualExpense"><FeatherIcon name="plus" class="h-4 w-4" />&#x624B;&#x52A8;&#x589E;&#x52A0;</Button>
                  <Button variant="solid" :loading="saving" @click="saveDraftSources(false)">&#x4FDD;&#x5B58;&#x8D39;&#x7528;&#x660E;&#x7EC6;</Button>
                </div>
              </div>

              <div v-if="selectedRequest.can_edit_expense_items && !selectedRequest.classification_ready" class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                <div class="font-medium">&#x5F85;&#x8D22;&#x52A1;&#x5F52;&#x7C7B;</div>
                <div class="mt-1 text-xs leading-5">&#x8BF7;&#x4E3A;&#x6BCF;&#x4E2A;&#x9879;&#x76EE;&#x9009;&#x62E9;&#x8D39;&#x7528;&#x79D1;&#x76EE;&#x5E76;&#x4FDD;&#x5B58;&#xFF0C;&#x5168;&#x90E8;&#x5B8C;&#x6574;&#x540E;&#x624D;&#x80FD;&#x5BA1;&#x6279;&#x901A;&#x8FC7;&#x3002;</div>
              </div>

              <section v-for="(group, groupIndex) in detailGroups" :key="group.group_key" data-testid="expense-group" class="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
                <div class="flex flex-col gap-3 border-b border-gray-200 bg-gray-50/80 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div class="min-w-0">
                    <div class="text-xs font-medium text-gray-500">&#x8D39;&#x7528;&#x7EC4; {{ groupIndex + 1 }}</div>
                    <input v-if="isDraftDetail" :value="group.project_name" class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium" placeholder="&#x8BC6;&#x522B;&#x4E3A;&#x7A7A;&#x65F6;&#x8BF7;&#x586B;&#x5199;&#x9879;&#x76EE;&#x540D;&#x79F0;" @change="updateGroupField(group, 'project_name', $event.target.value)" />
                    <div v-else class="mt-1 truncate text-base font-semibold text-gray-900">{{ group.project_name || '&#x672A;&#x586B;&#x9879;&#x76EE;&#x540D;&#x79F0;' }}</div>
                  </div>
                  <div class="shrink-0 text-left sm:text-right"><div class="text-xs text-gray-500">&#x5C0F;&#x8BA1;</div><div class="mt-1 text-lg font-semibold text-red-600">{{ money(group.total_amount, true) }}</div></div>
                </div>

                <div data-testid="finance-classification" class="border-b px-4 py-4" :class="selectedRequest.can_edit_expense_items ? 'border-amber-200 bg-amber-50/70' : 'border-gray-100 bg-white'">
                  <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div><div class="text-sm font-semibold text-gray-900">&#x8D39;&#x7528;&#x79D1;&#x76EE;</div><div class="mt-1 text-xs text-gray-500">{{ selectedRequest.can_edit_expense_items ? '&#x7531;&#x8D22;&#x52A1;&#x5728;&#x5F53;&#x524D;&#x5BA1;&#x6279;&#x8282;&#x70B9;&#x9009;&#x62E9;' : '&#x5458;&#x5DE5;&#x53EF;&#x7559;&#x7A7A;&#xFF0C;&#x8D22;&#x52A1;&#x5BA1;&#x6279;&#x65F6;&#x5F52;&#x7C7B;' }}</div></div>
                    <div v-if="canEditExpenseItems" class="grid w-full gap-2 sm:max-w-xl sm:grid-cols-2">
                      <select :value="group.expense_account_level_1" class="w-full rounded-lg border bg-white px-3 py-2 text-sm" :class="!group.expense_account_level_1 ? 'border-amber-400 ring-2 ring-amber-100' : 'border-gray-300'" @change="updateGroupAccount(group, 'expense_account_level_1', $event.target.value)"><option value="">选择一级科目</option><option v-for="item in expenseAccountTree" :key="item.level_1" :value="item.level_1">{{ item.level_1 }}</option></select>
                      <select :value="group.expense_account_level_2" class="w-full rounded-lg border bg-white px-3 py-2 text-sm" :class="accountChildren(group.expense_account_level_1).length && !group.expense_account_level_2 ? 'border-amber-400 ring-2 ring-amber-100' : 'border-gray-300'" :disabled="!accountChildren(group.expense_account_level_1).length" @change="updateGroupAccount(group, 'expense_account_level_2', $event.target.value)"><option value="">{{ accountChildren(group.expense_account_level_1).length ? '选择二级科目' : '无二级科目' }}</option><option v-for="item in accountChildren(group.expense_account_level_1)" :key="item" :value="item">{{ item }}</option></select>
                    </div>
                    <span v-else class="rounded-lg bg-gray-100 px-3 py-2 text-sm font-medium text-gray-800">{{ group.expense_item || '&#x5F85;&#x8D22;&#x52A1;&#x5F52;&#x7C7B;' }}</span>
                  </div>
                </div>

                <div class="grid gap-x-5 gap-y-4 px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div><div class="text-xs text-gray-500">&#x53D1;&#x7968;&#x7C7B;&#x522B;</div><div class="mt-1 text-sm text-gray-900">{{ group.invoice_category || '-' }}</div></div>
                  <div><div class="text-xs text-gray-500">&#x5F00;&#x7968;&#x65E5;&#x671F;</div><div class="mt-1 text-sm text-gray-900">{{ group.issue_date || '-' }}</div></div>
                  <div class="sm:col-span-2"><div class="text-xs text-gray-500">&#x53D1;&#x7968;&#x53F7;&#x7801;</div><div class="mt-1 break-all text-sm text-gray-900">{{ group.invoice_number || '-' }}</div></div>
                  <div><div class="text-xs text-gray-500">&#x7A0E;&#x524D;&#x91D1;&#x989D;</div><div class="mt-1 text-sm font-medium text-gray-900">{{ money(group.amount_before_tax, true) }}</div></div>
                  <div><div class="text-xs text-gray-500">&#x7A0E;&#x989D;</div><div class="mt-1 text-sm font-medium text-gray-900">{{ money(group.tax_amount, true) }}</div></div>
                  <div><div class="text-xs text-gray-500">&#x5408;&#x8BA1;&#x91D1;&#x989D;</div><div class="mt-1 text-sm font-semibold text-red-600">{{ money(group.total_amount, true) }}</div></div>
                </div>

                <div class="space-y-3 border-t border-gray-100 bg-gray-50/50 px-4 py-4">
                  <div v-for="(source, sourceIndex) in group.source_lines" :key="source.line_key" data-testid="expense-source-row" class="rounded-lg border border-gray-200 bg-white p-3">
                    <div class="grid gap-3 lg:grid-cols-[minmax(230px,0.75fr)_minmax(260px,1fr)_minmax(0,1.2fr)] lg:items-start">
                      <div data-testid="source-invoice" class="min-w-0">
                        <div class="text-xs font-medium text-gray-700">&#x539F;&#x59CB;&#x660E;&#x7EC6; {{ sourceIndex + 1 }}</div>
                        <div class="mt-1 truncate text-xs text-gray-500">{{ source.invoice_number || source.invoice_category || source.project_name || '-' }}</div>
                        <button v-if="invoiceForSource(source)" class="mt-2 inline-flex items-center rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100" @click="previewInvoiceRow = invoiceForSource(source)"><FeatherIcon name="eye" class="mr-1 h-3.5 w-3.5" />&#x67E5;&#x770B;&#x53D1;&#x7968;</button>
                        <span v-else class="mt-2 inline-flex rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-500">&#x65E0;&#x7968;&#x660E;&#x7EC6;</span>
                      </div>
                      <div data-testid="source-attachments" class="min-w-0 text-xs text-gray-500 lg:border-l lg:border-gray-100 lg:pl-3">
                        <div>&#x8865;&#x5145;&#x9644;&#x4EF6; ({{ source.attachments?.length || 0 }})</div>
                        <div class="mt-2 flex min-h-8 flex-wrap gap-1">
                          <span v-if="!source.attachments?.length" class="py-1 text-gray-400">&#x6682;&#x65E0;&#x8865;&#x5145;&#x9644;&#x4EF6;</span>
                          <span v-for="attachment in source.attachments || []" :key="attachment.name" class="inline-flex max-w-full items-center gap-1 rounded-md bg-blue-50 px-2 py-1 text-blue-700"><button class="truncate" :title="attachment.original_filename" @click="openExpenseAttachment(attachment)">{{ attachment.original_filename }}</button></span>
                        </div>
                      </div>
                      <label data-testid="source-description" class="text-xs text-gray-500 lg:border-l lg:border-gray-100 lg:pl-3">&#x8D39;&#x7528;&#x8BF4;&#x660E;
                        <input v-if="isDraftDetail && !source.source_invoice" :value="source.expense_description || source.description" class="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900" placeholder="&#x5458;&#x5DE5;&#x5FC5;&#x586B;&#x8D39;&#x7528;&#x8BF4;&#x660E;" @input="updateSourceField(source.line_key, 'expense_description', $event.target.value)" />
                        <div v-else class="mt-1 min-h-9 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-800">{{ source.expense_description || source.description || '-' }}</div>
                      </label>
                    </div>
                  </div>
                </div>
              </section>

              <div v-if="!detailGroups.length" class="rounded-xl border border-dashed border-gray-300 bg-white px-5 py-12 text-center text-sm text-gray-400">&#x6682;&#x65E0;&#x8D39;&#x7528;&#x660E;&#x7EC6;</div>

              <section v-if="detailInvoices.length" class="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
                <header class="border-b bg-gray-50 px-4 py-3"><h4 class="text-sm font-semibold text-gray-900">关联发票</h4><p class="mt-1 text-xs text-gray-500">包含申请时上传和付款后补录的全部发票。</p></header>
                <div class="divide-y">
                  <div v-for="invoice in detailInvoices" :key="invoice.name" class="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                    <div class="min-w-0"><div class="truncate text-sm font-medium text-gray-900">{{ invoice.original_filename || invoice.name }}</div><div class="mt-1 text-xs text-gray-500">{{ invoice.invoice_category || '-' }} · {{ invoice.invoice_number || '无号码' }} · {{ invoice.recognition_status }}</div></div>
                    <Button variant="subtle" @click="previewInvoiceRow = invoice"><FeatherIcon name="eye" class="h-4 w-4" />查看发票</Button>
                  </div>
                </div>
              </section>
            </main>

            <aside class="min-w-0 space-y-4 xl:sticky xl:top-4">
              <section class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <h4 class="text-sm font-semibold text-gray-900">&#x4ED8;&#x6B3E;&#x4FE1;&#x606F;</h4>
                <dl class="mt-3 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-1">
                  <div><dt class="text-xs text-gray-500">&#x4ED8;&#x6B3E;&#x7C7B;&#x578B;</dt><dd class="mt-1 text-gray-900">{{ selectedRequest.payment_type || '-' }}</dd></div>
                  <div><dt class="text-xs text-gray-500">&#x4ED8;&#x6B3E;&#x65B9;&#x5F0F;</dt><dd class="mt-1 text-gray-900">{{ selectedRequest.payment_method || '-' }}</dd></div>
                  <div><dt class="text-xs text-gray-500">&#x6536;&#x6B3E;&#x4EBA;</dt><dd class="mt-1 text-gray-900">{{ selectedRequest.payee_name || '-' }}</dd></div>
                  <div><dt class="text-xs text-gray-500">&#x5F00;&#x6237;&#x884C; / &#x652F;&#x884C;</dt><dd class="mt-1 break-words text-gray-900">{{ [selectedRequest.bank_name,selectedRequest.branch].filter(Boolean).join(' / ') || '-' }}</dd></div>
                  <div><dt class="text-xs text-gray-500">&#x6536;&#x6B3E;&#x8D26;&#x53F7;</dt><dd class="mt-1 break-all text-gray-900">{{ selectedRequest.account_no || '-' }}</dd></div>
                  <div><dt class="text-xs text-gray-500">&#x4ED8;&#x6B3E;&#x65F6;&#x95F4;</dt><dd class="mt-1 text-gray-900">{{ dateText(selectedRequest.paid_on) }}</dd></div>
                </dl>
              </section>

              <section class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm"><h4 class="text-sm font-semibold text-gray-900">发票跟踪</h4><dl class="mt-3 space-y-2 text-sm"><div><dt class="text-xs text-gray-500">处理方式</dt><dd class="mt-1 text-gray-900">{{ selectedRequest.invoice_handling_mode || '-' }}</dd></div><div><dt class="text-xs text-gray-500">跟踪状态</dt><dd class="mt-1 text-gray-900">{{ selectedRequest.invoice_followup_status || '-' }}</dd></div><div v-if="selectedRequest.expected_invoice_date"><dt class="text-xs text-gray-500">预计取得日期</dt><dd class="mt-1 text-gray-900">{{ selectedRequest.expected_invoice_date }}</dd></div><div v-if="selectedRequest.no_invoice_reason"><dt class="text-xs text-gray-500">情况说明</dt><dd class="mt-1 whitespace-pre-wrap text-gray-900">{{ selectedRequest.no_invoice_reason }}</dd></div></dl></section>

              <section class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <h4 class="text-sm font-semibold text-gray-900">&#x5BA1;&#x6279;&#x8FDB;&#x5EA6;</h4>
                <ol class="mt-4 space-y-0">
                  <li v-for="(step,index) in selectedRequest.steps || []" :key="step.step_key || step.step_index" class="relative flex gap-3 pb-5 last:pb-0">
                    <div v-if="index < selectedRequest.steps.length - 1" class="absolute left-[15px] top-8 h-[calc(100%-1rem)] border-l border-dashed border-gray-300"></div>
                    <div class="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold" :class="['&#x5DF2;&#x901A;&#x8FC7;','&#x5DF2;&#x529E;&#x7406;'].includes(step.status) ? 'bg-emerald-600 text-white' : step.status === '&#x5DF2;&#x62D2;&#x7EDD;' ? 'bg-red-600 text-white' : step.step_index === selectedRequest.current_step_index ? 'bg-amber-500 text-white' : 'bg-gray-200 text-gray-600'">{{ step.step_index }}</div>
                    <div class="min-w-0 pt-0.5"><div class="text-sm font-medium text-gray-900">{{ step.label }}</div><div class="mt-1 break-all text-xs text-gray-500">{{ step.approvers.join(' / ') }}</div><div v-if="step.origin === 'add_sign'" class="mt-1 text-xs font-medium text-blue-700">&#x52A0;&#x7B7E;&#x8282;&#x70B9; &middot; {{ step.add_sign_position === 'before' ? '&#x5728;&#x524D;' : '&#x5728;&#x540E;' }}</div><div v-if="step.acted_on" class="mt-1 text-xs text-gray-400">{{ dateText(step.acted_on) }}</div><div v-if="step.note" class="mt-1 text-xs text-gray-600">{{ step.note }}</div><div v-if="step.add_sign_opinion" class="mt-2 rounded-md bg-blue-50 px-2 py-1.5 text-xs text-blue-700">&#x52A0;&#x7B7E;&#x610F;&#x89C1;&#xFF1A;{{ step.add_sign_opinion }}</div></div>
                  </li>
                </ol>
              </section>

              <section v-if="selectedRequest.operation_log?.length" class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <h4 class="text-sm font-semibold text-gray-900">&#x64CD;&#x4F5C;&#x8BB0;&#x5F55;</h4>
                <div class="mt-3 max-h-52 space-y-2 overflow-y-auto"><div v-for="(event,index) in selectedRequest.operation_log" :key="index" class="rounded-lg bg-gray-50 p-3 text-xs leading-5 text-gray-600"><div class="font-medium text-gray-800">{{ event.action }}</div><div>{{ event.actor }} &middot; {{ dateText(event.acted_on) }}</div><div>{{ event.from_status }} &rarr; {{ event.to_status }}<span v-if="event.note"> &middot; {{ event.note }}</span></div></div></div>
              </section>
            </aside>
          </div>
        </div>

        <footer data-testid="approval-actions" class="sticky bottom-0 z-20 flex shrink-0 flex-col gap-3 border-t border-gray-200 bg-white px-5 py-3 shadow-[0_-8px_20px_rgba(15,23,42,0.06)] sm:px-6 lg:flex-row lg:items-center">
          <input v-model="actionNote" class="min-w-0 flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm" placeholder="&#x5BA1;&#x6279;&#x3001;&#x4ED8;&#x6B3E;&#x6216;&#x64A4;&#x56DE;&#x5907;&#x6CE8;" />
          <div class="flex flex-wrap justify-end gap-2">
            <Button variant="subtle" @click="detailRequestName = ''">&#x5173;&#x95ED;</Button>
            <Button v-if="selectedRequest.can_withdraw" variant="subtle" @click="withdrawRequest(selectedRequest)">&#x64A4;&#x56DE;&#x7533;&#x8BF7;</Button>
            <Button v-if="selectedRequest.can_withdraw_payment" variant="subtle" @click="withdrawPayment(selectedRequest)">&#x64A4;&#x56DE;&#x4ED8;&#x6B3E;</Button>
            <Button v-if="canWithdrawInvoicePush" variant="subtle" :loading="saving" @click="withdrawPushedInvoices(selectedRequest)">撤回下推</Button>
            <Button v-if="selectedRequest.can_supplement_invoices" variant="subtle" @click="showInvoiceSupplement = true"><FeatherIcon name="upload-cloud" class="h-4 w-4" />补录发票</Button>
            <Button v-if="selectedRequest.can_verify_invoices" variant="subtle" :loading="saving" @click="verifyInvoices(selectedRequest)"><FeatherIcon name="check-circle" class="h-4 w-4" />确认已核验</Button>
            <Button v-if="isDraftDetail && !selectedRequest.from_invoice_push && !(selectedRequest.expense_lines || []).some(line => line.source_invoice)" variant="subtle" @click="editManualDraft(selectedRequest)">继续编辑草稿</Button>
            <Button v-if="selectedRequest.kanban_status === 'draft'" variant="solid" :loading="saving" @click="submitDraft(selectedRequest)">&#x63D0;&#x4EA4;&#x5BA1;&#x6279;</Button>
            <Button v-if="selectedRequest.can_edit_expense_items" variant="subtle" :loading="saving" @click="saveFinanceClassification">&#x4FDD;&#x5B58;&#x8D39;&#x7528;&#x79D1;&#x76EE;</Button>
            <Button v-if="selectedRequest.can_add_sign" variant="subtle" @click="openAddSign"><FeatherIcon name="user-plus" class="h-4 w-4" />&#x52A0;&#x7B7E;</Button>
            <Button v-if="selectedRequest.can_reject && selectedRequest.current_step_mode !== 'handle'" variant="subtle" @click="openReject(selectedRequest)"><FeatherIcon name="corner-up-left" class="h-4 w-4" />&#x5B9A;&#x5411;&#x9A73;&#x56DE;</Button>
            <Button v-if="selectedRequest.can_approve" variant="solid" :loading="saving" @click="act(selectedRequest,'approve')"><FeatherIcon name="check" class="h-4 w-4" /><span v-if="selectedRequest.current_step_mode === 'handle'">确认付款</span><span v-else>&#x5BA1;&#x6279;&#x901A;&#x8FC7;</span></Button>
            <Button v-else-if="selectedRequest.can_act && selectedRequest.current_step_mode !== 'handle'" variant="subtle" disabled title="Finance classification required">&#x8BF7;&#x5148;&#x8865;&#x5168;&#x8D39;&#x7528;&#x79D1;&#x76EE;</Button>
            <Button v-if="selectedRequest.can_mark_paid" variant="solid" :loading="saving" @click="markPaid(selectedRequest)">&#x6807;&#x8BB0;&#x5DF2;&#x4ED8;&#x6B3E;</Button>
          </div>
        </footer>
      </div>
    </div>
    <div v-if="showInvoiceSupplement && selectedRequest" class="fixed inset-0 z-[80] overflow-y-auto bg-white p-4"><div class="mx-auto max-w-[1600px]"><div class="mb-3 flex justify-end"><Button variant="subtle" @click="showInvoiceSupplement = false"><FeatherIcon name="x" class="h-4 w-4" />关闭补录</Button></div><InvoiceUploadWorkbench :options="options.data || {}" :target-request="selectedRequest" @supplemented="invoiceSupplemented" /></div></div>
    <div v-if="showManualExpense" class="fixed inset-0 z-[60] flex items-center justify-center bg-gray-900/50 p-4" @click.self="showManualExpense = false">
      <div role="dialog" aria-modal="true" class="w-full max-w-2xl overflow-hidden rounded-lg bg-white shadow-2xl">
        <header class="flex items-center justify-between border-b bg-gray-50 px-5 py-4">
          <div><h3 class="font-semibold">手动增加费用</h3><p class="mt-1 text-xs text-gray-500">用于出差津贴等没有发票的费用，费用科目按一级、二级选择。</p></div>
          <button title="关闭" @click="showManualExpense = false"><FeatherIcon name="x" class="h-5 w-5" /></button>
        </header>
        <div class="grid gap-4 p-5 md:grid-cols-2">
          <label class="text-xs text-gray-500">项目名称<input v-model="manualExpense.project_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="必填" /></label>
          <label class="text-xs text-gray-500">一级费用科目<select v-model="manualExpense.expense_account_level_1" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" @change="manualExpense.expense_account_level_2 = ''"><option value="">请选择</option><option v-for="item in expenseAccountTree" :key="item.level_1" :value="item.level_1">{{ item.level_1 }}</option></select></label>
          <label class="text-xs text-gray-500">二级费用科目<select v-model="manualExpense.expense_account_level_2" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" :disabled="!accountChildren(manualExpense.expense_account_level_1).length"><option value="">{{ accountChildren(manualExpense.expense_account_level_1).length ? '请选择' : '无二级科目' }}</option><option v-for="item in accountChildren(manualExpense.expense_account_level_1)" :key="item" :value="item">{{ item }}</option></select></label>
          <label class="text-xs text-gray-500">日期<input v-model="manualExpense.issue_date" type="date" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
          <label class="text-xs text-gray-500">税后金额<input v-model="manualExpense.total_amount" type="number" min="0.01" step="0.01" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm text-right" /></label>
          <label class="text-xs text-gray-500 md:col-span-2">费用说明<input v-model="manualExpense.expense_description" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="例如：深圳出差津贴" /></label>
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
      <fieldset><legend class="text-xs text-gray-500">&#x52A0;&#x7B7E;&#x4F4D;&#x7F6E;</legend><div class="mt-2 flex gap-6 text-sm"><label class="flex items-center gap-2"><input v-model="addSignForm.position" type="radio" value="before" />&#x5728;&#x6211;&#x4E4B;&#x524D;</label><label v-if="selectedRequest.can_add_sign_after" class="flex items-center gap-2"><input v-model="addSignForm.position" type="radio" value="after" />&#x5728;&#x6211;&#x4E4B;&#x540E;</label></div><p v-if="!selectedRequest.can_add_sign_after" class="mt-1 text-xs text-gray-500">付款节点只能在前面加签：被加签人审批后才能确认付款。</p></fieldset>
      <label class="block text-xs text-gray-500">&#x52A0;&#x7B7E;&#x610F;&#x89C1;&#xFF08;&#x5FC5;&#x586B;&#xFF09;<textarea v-model="addSignForm.opinion" rows="4" maxlength="1000" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="&#x586B;&#x5199;&#x52A0;&#x7B7E;&#x539F;&#x56E0;&#x6216;&#x8981;&#x6C42;"></textarea></label>
    </div>
    <footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3"><Button variant="subtle" @click="showAddSignDialog = false">&#x53D6;&#x6D88;</Button><Button variant="solid" :loading="saving" @click="submitAddSign">&#x786E;&#x8BA4;&#x52A0;&#x7B7E;</Button></footer>
  </div>
</div>

    <InvoicePreviewDrawer :open="Boolean(previewInvoiceRow)" :invoice="previewInvoiceRow" @close="previewInvoiceRow = null" />
    <InvoicePreviewDrawer :open="Boolean(previewAttachmentRow)" :invoice="previewAttachmentRow" :preview-loader="previewAttachmentLoader" title="补充附件预览" @close="previewAttachmentRow = null" />
  </div>
</template>
