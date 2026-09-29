<script setup>
import MaterialExecutionProgress from "../components/MaterialExecutionProgress.vue";
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { FeatherIcon, createResource } from 'frappe-ui';
import { useRoute, useRouter } from 'vue-router';
import {
  buildApprovalCenterPayload,
  canCloseProcurement,
  canCompleteSupplierRefund,
  canRecordArrival,
  canRecordInspection,
  canWriteoffPrepayment,
  normalizeServerError,
  organizationPreflightMessage,
  paymentPlanTotals,
  validateProcurementRequestForm,
  validatePriceApprovalForm,
} from '../lib/procurementWorkflow';
import { documentChecklistForRequest } from '../lib/businessDocumentChecklist';
import { canSeeProcurementPrice } from '../lib/access';

// Keep long material names and specifications visible, including values filled by the catalog.
function resizeMaterialField(el) {
  el.style.height = 'auto';
  el.style.height = Math.max(58, el.scrollHeight + 2) + 'px';
}
const materialFieldObservers = new WeakMap();
const vAutoGrow = {
  mounted(el) {
    resizeMaterialField(el);
    let width = el.getBoundingClientRect().width;
    const observer = new ResizeObserver(() => {
      const nextWidth = el.getBoundingClientRect().width;
      if (nextWidth !== width) { width = nextWidth; resizeMaterialField(el); }
    });
    observer.observe(el);
    materialFieldObservers.set(el, observer);
  },
  updated: resizeMaterialField,
  unmounted(el) { materialFieldObservers.get(el)?.disconnect(); materialFieldObservers.delete(el); },
};

const route = useRoute();
const router = useRouter();
const config = computed(() => ({
  '/approval/procurement': { requestType: '采购申请', title: '采购申请' },
  '/approval/direct-purchase': { requestType: '购买申请', title: '购买申请' },
  '/approval/direct-purchase/new': { requestType: '购买申请', title: '购买申请' },
  '/approval/procurement-payment': { requestType: '采购付款', title: '采购付款' },
}[route.path] || { requestType: '采购申请', title: '采购申请' }));
const isProcurement = computed(() => config.value.requestType === '采购申请');
const isDirectPurchase = computed(() => config.value.requestType === '购买申请');
const isPayment = computed(() => config.value.requestType === '采购付款');
const isProcurementOrPayment = computed(() => isProcurement.value || isPayment.value);
const isPriceInnerPage = computed(() => route.name === 'procurement-price-approval');
const isContractInnerPage = computed(() => route.name === 'procurement-contract');
const isNewRequestPage = computed(() => ['procurement-new', 'direct-purchase-new'].includes(route.name));
const isPmcEditPage = computed(() => route.name === 'procurement-pmc-edit');
const isInnerPage = computed(() => isNewRequestPage.value || isPmcEditPage.value || isPriceInnerPage.value || isContractInnerPage.value);
const innerPageTitle = computed(() => {
  if (isPmcEditPage.value) return 'PMC补录/修改';
  if (isPriceInnerPage.value) return '价格审批单';
  if (isContractInnerPage.value) return 'PO 采购订单';
  return config.value.title;
});
const blankLine = () => ({
  material_code: '', material_serial: '', category_code: '', category_path: '', category_parts: [], category_query: '', category_open: false, category_picker_parent: '', category_picker_path: [], material_query: '', material_open: false, item_name: '', specification: '',
  product_desc: '', brand: '', product_name: '', product_desc_en: '', brand_en: '', material_attr: '外购',
  quantity: 1, unit: '个', unit_price: 0, remarks: '',
});
const blankInstallment = (index = 1) => ({
  installment_name: `第${index}期`, payment_stage: index === 1 ? '预付款' : '尾款',
  percentage: index === 1 ? 30 : 70, amount: 0, planned_date: '',
  trigger_condition: index === 1 ? '合同生效' : '验收通过',
  invoice_requirement: index === 1 ? '付款后提供' : '付款前提供',
});
const blankForm = () => ({
  subject: '', reason: '', urgency: '一般', asset_nature: '非固定资产', fixed_asset_category: '',
  procurement_scope: '项目采购', expected_delivery_date: '', project: '', applicant_employee: '',
  non_project_allocation_type: '非项目采购', non_project_cost_center: '', non_project_department: '',
  purchaser_user: '', purchase_method: '京东购买', source_request: '', source_payment_plan_row: '', supplier: '',
  source_purchase_order: '', source_po_payment_plan_row: '',
  prepayment_percentage: 30, expected_arrival_date: '', prepayment_risk_note: '',
  business_lines: [blankLine()],
});
const form = reactive(blankForm());
const quoteForm = reactive({
  supplier: '', change_reason: '', business_lines: [], tax_included: 1, tax_rate: 13,
  delivery_terms: '', warranty_terms: '', invoice_condition: '',
  payment_plan: [blankInstallment(1), blankInstallment(2)],
});
// Keep unsaved detail edits stable while the approval queues refresh in the background.
const hydratedDetailRequestName = ref('');
const contractForm = reactive({
  supplier_legal_name: '', credit_code: '', supplier_address: '', contract_contact: '',
  contract_bank_name: '', contract_bank_account: '', contract_entity: '示例企业032有限公司',
  contract_template: '标准采购合同（测试版）', seal_user: '', contract_delivery_date: '',
});
const draftName = ref('');
const selectedRequestName = ref('');
const message = ref('');
const error = ref('');
const uploadInput = ref(null);
const documentType = ref('合同');
const documents = ref([]);
const showCreateForm = ref(false);
const creatingNew = ref(false);
const pmcEditMode = ref(false);
const actedRequestSteps = reactive({});
const saving = ref(false)
const refreshing = ref(false);
const uploading = ref(false);
let refreshTimer = null;
const rejectTarget = ref('applicant');
const rejectReason = ref('');
const actionNote = ref('');
const contractDate = ref('');
const contractReason = ref('');
const arrivalQuantity = ref(0);
const arrivalDate = ref('');
const inspectionOutcome = ref('通过');
const inspectionDirection = ref('退货');
const inspectionReason = ref('');
const followupStatus = ref('催办中');
const followupReason = ref('');

const optionLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.get_options', method: 'GET', auto: true });
const saver = createResource({ url: 'rayher_hr_payroll.api.oa_entry.save_approval_center_draft' });
const pmcModifier = createResource({ url: 'rayher_hr_payroll.api.oa_entry.modify_procurement_request' });
const submitter = createResource({ url: 'rayher_hr_payroll.api.oa_entry.submit_approval_center_draft' });
const actor = createResource({ url: 'rayher_hr_payroll.api.oa_entry.action_request' });
const requestWithdrawer = createResource({ url: 'rayher_hr_payroll.api.oa_entry.withdraw_request' });
const quoteSubmitter = createResource({ url: 'rayher_hr_payroll.api.oa_entry.submit_procurement_quote' });
const attacher = createResource({ url: 'rayher_hr_payroll.api.oa_entry.attach_approval_business_document' });
const documentLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_approval_business_documents', method: 'GET' });
const documentRemover = createResource({ url: 'rayher_hr_payroll.api.oa_entry.remove_approval_business_document' });
const contractSaver = createResource({ url: 'rayher_hr_payroll.api.oa_entry.save_procurement_contract_information' });
const contractReviewer = createResource({ url: 'rayher_hr_payroll.api.oa_entry.review_procurement_contract' });
const contractSealer = createResource({ url: 'rayher_hr_payroll.api.oa_entry.seal_procurement_contract' });
const projectLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_approval_center_projects', method: 'GET', auto: true });
const applicantLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_procurement_applicants', method: 'GET', auto: true });
const userLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_procurement_users', method: 'GET', auto: true });
const sourceLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_procurement_payment_sources', method: 'GET', makeParams: () => ({ limit: 500 }), auto: true });
const categoryLoader = createResource({ url: 'rayher_hr_payroll.api.procurement_materials.list_categories', method: 'GET', makeParams: () => ({ limit: 2000 }) });
const materialLoader = createResource({ url: 'rayher_hr_payroll.api.procurement_materials.list_materials', method: 'GET' });
const categorySaver = createResource({ url: 'rayher_hr_payroll.api.procurement_materials.save_category' });
const materialSaver = createResource({ url: 'rayher_hr_payroll.api.procurement_materials.save_material' });
const materialSuggestionLoader = createResource({ url: 'rayher_hr_payroll.api.procurement_materials.suggest_material', method: 'GET' });
const queuePage = ref(0);
const queuePageSize = 50;
const exactLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_requests', method: 'GET' });
const mineLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_requests', method: 'GET', makeParams: () => ({ view: 'mine', request_type: config.value.requestType, limit: queuePageSize, offset: queuePage.value * queuePageSize }) });
const pendingLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_requests', method: 'GET', makeParams: () => ({ view: 'pending', request_type: config.value.requestType, limit: queuePageSize, offset: queuePage.value * queuePageSize }) });
const allLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_requests', method: 'GET', makeParams: () => ({ view: 'all', request_type: config.value.requestType, limit: queuePageSize, offset: queuePage.value * queuePageSize }) });
const contractRegistrar = createResource({ url: 'rayher_hr_payroll.api.oa_entry.register_contract_delivery' });
const arrivalRecorder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.record_arrival' });
const inspectionRecorder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.record_inspection' });
const followupRecorder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.record_prepayment_followup' });
const writeoffRecorder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.writeoff_prepayment' });
const closeRecorder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.close_procurement' });
const refundCompleter = createResource({ url: 'rayher_hr_payroll.api.oa_entry.complete_supplier_refund' });

const organizationWarning = computed(() => organizationPreflightMessage(
  config.value.requestType,
  optionLoader.data?.context || {},
));
const projects = computed(() => (projectLoader.data || []).filter((row) => row.status !== 'Cancelled'));
function projectOptionLabel(project) {
  const code = project?.rd_project_code || project?.project_code || project?.name || '';
  const name = project?.project_name || project?.name || '';
  const owner = project?.project_owner_name || project?.project_owner || '未配置负责人';
  return `${code}${name && name !== code ? ` · ${name}` : ''} · 负责人：${owner}`;
}
const applicants = computed(() => applicantLoader.data || []);
const canSubmitForOthers = computed(() => Boolean(optionLoader.data?.can_submit_procurement_for_others));
const purchasers = computed(() => userLoader.data || []);
const materialCategories = computed(() => categoryLoader.data || []);
const canManageCatalog = computed(() => Boolean(optionLoader.data?.can_manage_procurement_catalog));
const catalogOpen = ref(false);
const catalogCategoryForm = reactive({ category_code: '', category_name: '', parent_category: '', full_path: '' });
const catalogMaterialForm = reactive({ material_code: '', category_code: '', material_name: '', specification: '', product_desc: '', brand: '', unit: '个', category_path: '', material_attr: '外购' });
const materialSuggestions = reactive({});
const materialSearchResults = reactive({});
const categoryMaterialResults = reactive({});
const categoryMaterialLoading = reactive({});
const paymentSources = computed(() => {
  const currentUser = optionLoader.data?.current_applicant?.user || '';
  const canManageExpense = Boolean(optionLoader.data?.can_manage_expense);
  return (sourceLoader.data || []).filter((row) => (
    row.request_type === '采购申请'
    && row.workflow_status === '已完成'
    && Number(row.available_amount) > 0
    && (canManageExpense || row.purchaser_user === currentUser)
  ));
});
const selectedPaymentSource = computed(() => paymentSources.value.find(
  (row) => row.payment_plan_row === form.source_payment_plan_row,
) || null);
const paymentStageHint = computed(() => selectedPaymentSource.value?.payment_stage || '请选择付款计划期次');
const quoteTotal = computed(() => (quoteForm.business_lines || []).reduce(
  (total, row) => total + Number(row.quantity || 0) * Number(row.unit_price || 0), 0,
));
const quotePlanTotals = computed(() => paymentPlanTotals(quoteForm.payment_plan));

const requestRows = computed(() => {
  const rows = [...(mineLoader.data || []), ...(pendingLoader.data || []), ...(allLoader.data || [])];
  return [...new Map(rows.filter((row) => row.request_type === config.value.requestType).map((row) => [row.name, row])).values()];
});
const pmcQueueFilter = ref('all');
function procurementLineNeedsPmc(line) {
  return Boolean(line?.category_code && !line?.material_code);
}
function needsPmcMaterial(row) {
  return Boolean((row?.business_lines || []).some((line) => procurementLineNeedsPmc(line)));
}
function isPmcPending(row) {
  return Boolean(row?.can_modify_procurement_request);
}
function queueBucket(row) {
  if (isPmcPending(row) && needsPmcMaterial(row)) return 'new-material';
  if (String(row?.workflow_status || '') === '待审批' || row?.can_approve) return 'pending';
  return 'other';
}
const queueFilterOptions = computed(() => {
  const rows = requestRows.value;
  return [
    { key: 'all', label: '全部', count: rows.length },
    { key: 'pending', label: '待审批', count: rows.filter((row) => queueBucket(row) === 'pending').length },
    { key: 'new-material', label: '待审批（新增物料）', count: rows.filter((row) => queueBucket(row) === 'new-material').length },
    { key: 'other', label: '其他进度', count: rows.filter((row) => queueBucket(row) === 'other').length },
  ];
});
const filteredRequestRows = computed(() => (
  pmcQueueFilter.value === 'all'
    ? requestRows.value
    : requestRows.value.filter((row) => queueBucket(row) === pmcQueueFilter.value)
));
const selectedRequest = computed(() => {
  if (creatingNew.value) return null;
  const routeRequestName = String(route.params.name || '');
  if (routeRequestName) {
    return requestRows.value.find((row) => row.name === routeRequestName) || (exactLoader.data?.[0]?.name === routeRequestName ? exactLoader.data[0] : null);
  }
  if (selectedRequestName.value) {
    return requestRows.value.find((row) => row.name === selectedRequestName.value) || (exactLoader.data?.[0]?.name === selectedRequestName.value ? exactLoader.data[0] : null);
  }
  return requestRows.value[0] || null;
});
const currentStep = computed(() => (selectedRequest.value?.steps || []).find(
  (row) => Number(row.step_index) === Number(selectedRequest.value?.current_step_index),
) || null);
const currentStepMode = computed(() => currentStep.value?.mode || 'approve');
const activeRequestName = computed(() => (creatingNew.value ? draftName.value : (selectedRequest.value?.name || draftName.value)));
const canPmcModify = computed(() => (
  isProcurement.value
  && Boolean(selectedRequest.value?.can_modify_procurement_request)
));
const canWithdrawSelected = computed(() => {
  const row = selectedRequest.value;
  const currentEmployee = optionLoader.data?.current_applicant?.employee;
  const ownApproval = Boolean(
    row?.request_type === '采购申请'
    && row?.employee
    && currentEmployee
    && row.employee === currentEmployee
    && ['待审批', '待办理'].includes(row.workflow_status)
  );
  return Boolean(!isInnerPage.value && (row?.can_withdraw || ownApproval));
});
const canResumeWithdrawn = computed(() => Boolean(
  !isInnerPage.value
  && isProcurement.value
  && selectedRequest.value?.workflow_status === '草稿'
  && selectedRequest.value?.business_status === '已撤回'
));
const pmcModifyButtonLabel = computed(() => (
  needsPmcMaterial(selectedRequest.value) ? '补充/修改物料' : '修改采购申请'
));
const requestRowsLoading = computed(() => Boolean(
  optionLoader.loading || mineLoader.loading || pendingLoader.loading || allLoader.loading,
));
const requestRowsError = computed(() => (
  mineLoader.error || pendingLoader.error || allLoader.error || null
));
const isMissingInnerRequest = computed(() => (
  isPmcEditPage.value
  && Boolean(route.params.name)
  && !requestRowsLoading.value
  && !selectedRequest.value
));
const isUnauthorizedPmcEdit = computed(() => (
  isPmcEditPage.value
  && Boolean(selectedRequest.value)
  && !requestRowsLoading.value
  && !selectedRequest.value.can_modify_procurement_request
));
const showQuoteForm = computed(() => isProcurement.value && Boolean(selectedRequest.value?.can_submit_procurement_quote));
const documentChecklist = computed(() => documentChecklistForRequest(selectedRequest.value, documents.value));
const missingDocumentCount = computed(() => documentChecklist.value.filter((item) => item.required && !item.satisfied).length);
const activeDocumentTypes = computed(() => {
  const latest = new Map();
  for (const row of documents.value) latest.set(row.document_type, row);
  return [...latest.keys()];
});
const showContractRegistration = computed(() => isProcurement.value && ['合同已生效', '付款计���已生成', '采购执行中'].includes(selectedRequest.value?.business_status));
const showContractForm = computed(() => isProcurement.value && Boolean(selectedRequest.value?.can_edit_procurement_contract));
const showContractReview = computed(() => isProcurement.value && Boolean(selectedRequest.value?.can_review_procurement_contract));
const showContractSeal = computed(() => isProcurement.value && Boolean(selectedRequest.value?.can_seal_procurement_contract));
const showArrival = computed(() => isProcurementOrPayment.value && canRecordArrival(selectedRequest.value, activeDocumentTypes.value));
const showInspection = computed(() => isProcurementOrPayment.value && canRecordInspection(selectedRequest.value, activeDocumentTypes.value));
const showWriteoff = computed(() => isPayment.value && canWriteoffPrepayment(selectedRequest.value, activeDocumentTypes.value));
// 确认供应商退款只给财务（2026-09-24）。
const showRefundCompletion = computed(() => isPayment.value && Boolean(optionLoader.data?.can_manage_expense) && canCompleteSupplierRefund(selectedRequest.value, activeDocumentTypes.value));
const showClose = computed(() => isPayment.value && canCloseProcurement(selectedRequest.value, activeDocumentTypes.value));
function demandApprovalCompleted(row) {
  if (!row) return false;
  const business = String(row.business_status || '');
  return String(row.workflow_status || '') === '已完成'
    || ['需求已批准/待询价', '需求已批准/待提PR', '待价格审批', '价格已批准/待补充合同信息', '待采购复核', '待电子用印', '合同已生效', '付款计划已生成', '采购执行中'].includes(business);
}
const contractPageAvailable = computed(() => Boolean(
  selectedRequest.value?.procurement_chain
    ? selectedRequest.value.procurement_chain.po_numbers?.length
    : selectedRequest.value?.price_revision
  || selectedRequest.value?.contract_status
  || selectedRequest.value?.can_edit_procurement_contract
  || selectedRequest.value?.can_review_procurement_contract
  || selectedRequest.value?.can_seal_procurement_contract
));
const showExecutionLinks = computed(() => {
  const row = selectedRequest.value;
  if (!isProcurement.value || !row) return false;
  return Boolean(row.can_view_procurement_price || row.can_view_procurement_po || row.procurement_chain?.stage === 'await_pr');
});
const priceStatusLabel = computed(() => {
  const row = selectedRequest.value;
  if (!row) return '-';
  if (row.procurement_chain?.label) return `${row.procurement_chain.label} · ${row.procurement_chain.summary}`;
  if (row.contract_status || ['价格已批准/待补充合同信息', '待采购复核', '待电子用印', '合同已生效', '付款计划已生成', '采购执行中'].includes(row.business_status)) return '已批准';
  if (String(row.current_step_label || '').includes('价格')) return row.current_step_label;
  if (row.can_submit_procurement_quote) return '待填写';
  if (row.price_revision) return '已提交 V' + row.price_revision;
  if (demandApprovalCompleted(row)) return '从 PR 选择物料生成 / 查看';
  return '等待需求审批';
});
const contractStatusLabel = computed(() => {
  const row = selectedRequest.value;
  if (!row) return '-';
  if (row.procurement_chain?.po_numbers?.length) return `${row.procurement_chain.po_numbers.length} 张 PO · ${row.procurement_chain.label}`;
  if (row.contract_status) return row.contract_status;
  if (row.price_revision) return '等待价格批准';
  if (demandApprovalCompleted(row)) return '价格审批通过后自动生成';
  return '尚未开始';
});

function approvalStageMeta(row) {
  const workflow = String(row?.workflow_status || '');
  if (row?.business_status === '已撤回' && workflow === '草稿') {
    return {
      key: 'withdrawn', label: '已撤回', description: '申请人已撤回，可编辑后重新提交审批。',
      action: '已撤回', tone: 'border-red-200 bg-red-50 text-red-700', panel: 'border-red-200 bg-red-50', icon: 'corner-up-left',
    };
  }
  const step = String(row?.current_step_label || '');
  const business = String(row?.business_status || '');
  if (!isProcurement.value) {
    return {
      key: 'workflow', label: workflow || '业务进度', description: step || business || '查看当前处理节点',
      action: step ? `当前处理：${step}` : '查看当前处理任务',
      tone: 'border-gray-200 bg-gray-50 text-gray-700', panel: 'border-gray-200 bg-gray-50', icon: 'inbox',
    };
  }
  if (row?.can_modify_procurement_request) {
    const needsMaterial = needsPmcMaterial(row);
    return {
      key: needsMaterial ? 'pmc-material' : 'demand',
      label: needsMaterial ? '待审批（新增物料）' : '待审批',
      action: needsMaterial ? 'PMC补充物料后继续审批' : '本次需要审批采购需求',
      tone: needsMaterial ? 'border-amber-300 bg-amber-50 text-amber-800' : 'border-amber-200 bg-amber-50 text-amber-800',
      panel: needsMaterial ? 'border-amber-300 bg-amber-50/80' : 'border-amber-200 bg-amber-50/70',
      icon: needsMaterial ? 'database' : 'clipboard',
    };
  }
  const chain = row?.procurement_chain || {};
  if (workflow === '已完成' && chain.stage === 'quote') {
    return {
      key: 'quote', label: '采购询价/录价', description: chain.summary || '采购从 PR 选择物料生成价格审批单并维护供应商报价。',
      action: '进入价格审批并录入报价',
      tone: 'border-blue-200 bg-blue-50 text-blue-700', panel: 'border-blue-200 bg-blue-50/70', icon: 'edit-3',
    };
  }
  if (workflow === '已完成' && chain.stage === 'await_pr') {
    return {
      key: 'await-pr', label: '等待 PMC 提 PR', description: chain.summary || '需求审批已完成，等待 PMC 从物料进度看板选择物料生成 PR。',
      action: '等待 PMC 提 PR',
      tone: 'border-amber-200 bg-amber-50 text-amber-800', panel: 'border-amber-200 bg-amber-50/70', icon: 'git-merge',
    };
  }
  if (workflow === '已完成' && chain.stage === 'price') {
    return {
      key: 'price', label: '价格审批中', description: chain.summary || '采购已提交供应商比价，等待演示员工37选择成交方案并审批。',
      action: '等待演示员工37选择成交方案',
      tone: 'border-blue-700 bg-blue-700 text-white', panel: 'border-blue-300 bg-blue-50', icon: 'dollar-sign',
    };
  }
  if (workflow === '已完成' && ['po', 'closed'].includes(chain.stage)) {
    return {
      key: chain.stage, label: chain.label, description: chain.summary || '价格审批已完成，物料已进入 PO 履约。',
      action: chain.label,
      tone: 'border-emerald-200 bg-emerald-50 text-emerald-700', panel: 'border-emerald-200 bg-emerald-50', icon: 'package',
    };
  }
  if (step.includes('价格审批') || business === '待价格审批') {
    return {
      key: 'price', label: '价格审批', description: '审核供应商、物品价格、付款方式和分期付款计划',
      action: '本次需要审批价格及付款计划',
      tone: 'border-blue-700 bg-blue-700 text-white', panel: 'border-blue-300 bg-blue-50', icon: 'dollar-sign',
    };
  }
  if (step.includes('询价') || business === '需求已批准/待询价' || business === '需求已批准/待提PR') {
    return {
      key: 'quote', label: '采购询价/录价', description: '补充供应商商业条件并填写结构化价格审批表',
      action: '进入价格审批并录入报价',
      tone: 'border-blue-200 bg-blue-50 text-blue-700', panel: 'border-blue-200 bg-blue-50/70', icon: 'edit-3',
    };
  }
  if (step.includes('合同') || ['价格已批准/待补充合同信息', '待采购复核', '待电子用印'].includes(business)) {
    return {
      key: 'contract', label: '合同处理', description: '补充合同信息、采购复核并完成电子用印',
      action: step ? `本次需要处理：${step}` : '本次需要处理采购合同',
      tone: 'border-emerald-200 bg-[#15803d] text-white', panel: 'border-emerald-200 bg-emerald-50', icon: 'file-text',
    };
  }
  if (workflow === '待审批' || step.includes('需求') || business === '待审批') {
    return {
      key: 'demand', label: '需求审批', description: '审核采购必要性、采购范围、物品数量和业务责任',
      action: '本次需要审批采购需求',
      tone: 'border-amber-200 bg-amber-50 text-amber-800', panel: 'border-amber-200 bg-amber-50/70', icon: 'clipboard',
    };
  }
  return {
    key: 'progress', label: business || workflow || '采购进度', description: step || '查看采购业务当前进度',
    action: step ? `当前处理：${step}` : '查看采购业务进度',
    tone: 'border-gray-200 bg-gray-50 text-gray-700', panel: 'border-gray-200 bg-gray-50', icon: 'activity',
  };
}
function isPriceApprovalStep(row) { return approvalStageMeta(row).key === 'price'; }
function isPriceChainAction(row) { return ['quote', 'price'].includes(approvalStageMeta(row).key); }
function procurementChainRoute(row, target = 'price') {
  if (target === 'price' && row?.procurement_chain?.stage === 'await_pr') {
    return { path: '/approval/material-progress', query: { request: row?.name || '' } };
  }
  const query = { request: row?.name || '' };
  if (target === 'po') query.tab = 'po';
  if (target === 'price' && (row?.procurement_chain?.stage === 'quote' || String(row?.current_step_label || '').includes('询价'))) query.view = 'source';
  return { name: 'procurement-price-approvals', query };
}
function approvalButtonLabel(row) {
  if (currentStepMode.value === 'handle') {
    return String(currentStep.value?.label || '').includes('总经理付款') ? '确认付款' : '办理完成';
  }
  return approvalStageMeta(row).key === 'demand' ? '需求审批通过' : '审批通过';
}
function currentStepKeyFor(row) {
  const current = (row?.steps || []).find((item) => Number(item.step_index) === Number(row?.current_step_index));
  return String(current?.step_key || row?.current_step_key || row?.current_step_label || '');
}
function canApproveRow(row) {
  if (!row?.can_approve) return false;
  const actedStep = actedRequestSteps[row.name];
  return !actedStep || actedStep !== currentStepKeyFor(row);
}
function canRejectRow(row) {
  if (!row?.can_reject) return false;
  const actedStep = actedRequestSteps[row.name];
  return !actedStep || actedStep !== currentStepKeyFor(row);
}
const selectedCanApprove = computed(() => canApproveRow(selectedRequest.value));
const selectedCanReject = computed(() => canRejectRow(selectedRequest.value));

function queueRowClass(row) {
  if (selectedRequest.value?.name !== row?.name) return 'border-l-transparent bg-gray-50/40 hover:bg-white';
  const key = approvalStageMeta(row).key;
  if (key === 'price') return 'border-l-blue-700 bg-white';
  if (key === 'demand') return 'border-l-amber-500 bg-white';
  if (key === 'contract') return 'border-l-[#15803d] bg-white';
  if (key === 'withdrawn') return 'border-l-red-500 bg-white';
  return 'border-l-gray-800 bg-white';
}
function paymentPlanSummary(row) {
  const plans = row?.payment_plan || [];
  return plans.length
    ? plans.map((item) => `${item.payment_stage} ${Number(item.percentage || 0)}%`).join(' / ')
    : '-';
}
function priceLineAmount(line) {
  return Number(line?.quantity || 0) * Number(line?.unit_price || 0);
}

const selectedTotalQuantity = computed(() => (selectedRequest.value?.business_lines || []).reduce(
  (total, line) => total + Number(line.quantity || 0),
  0,
));
function formatMoney(value) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function formatDateTime(value) {
  if (!value) return '-';
  return String(value).replace('T', ' ').slice(0, 19);
}
function allocationLabel(row) {
  if (row?.project) return `项目 · ${row.project}`;
  if (row?.non_project_cost_center) return `成本中心 · ${row.non_project_cost_center}`;
  if (row?.non_project_department) return `部门 · ${row.non_project_department}`;
  return row?.non_project_allocation_type || '非项目采购';
}
function statusTone(status) {
  if (['待审批', '待办理', '待流转'].includes(status)) return 'bg-amber-50 text-amber-700';
  if (['已完成', '已付款', '已处理'].includes(status)) return 'bg-emerald-50 text-emerald-700';
  if (['已驳回', '已撤回', '已取消'].includes(status)) return 'bg-red-50 text-red-700';
  if (status === '草稿') return 'bg-gray-100 text-gray-600';
  return 'bg-blue-50 text-blue-700';
}
function stepTone(status) {
  if (['已审批', '已办理', '已完成', '已处理'].includes(status)) return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  if (['待审批', '待办理'].includes(status)) return 'border-amber-300 bg-amber-50 text-amber-700';
  if (status === '已驳回') return 'border-red-200 bg-red-50 text-red-700';
  return 'border-gray-200 bg-white text-gray-400';
}
function stepIcon(status) {
  if (['已审批', '已办理', '已完成', '已处理'].includes(status)) return 'check';
  if (['待审批', '待办理'].includes(status)) return 'clock';
  if (status === '已驳回') return 'x';
  return 'circle';
}

function addLine() { if (form.business_lines.length < 100) form.business_lines.push(blankLine()); }
function removeLine(index) { if (form.business_lines.length > 1) form.business_lines.splice(index, 1); }
function materialMatchesFor(index) { return materialSearchResults[index] || []; }
async function searchMaterials(index, line) {
  const query = String(line.material_query || line.material_code || '').trim();
  line.material_open = Boolean(query);
  if (!query) { materialSearchResults[index] = []; return; }
  try {
    materialSearchResults[index] = await materialLoader.fetch({ query, limit: 10 });
  } catch (exception) {
    materialSearchResults[index] = [];
    fail(exception, '物料库查询失败');
  }
}
function clearMaterialSelection(line) {
  if (!line) return;
  Object.assign(line, {
    material_code: '', material_query: '', material_open: false,
    category_open: false, category_picker_parent: '', category_picker_path: [],
    category_query: line.category_code || '',
  });
}
function selectMaterial(index, line, item) {
  const materialCode = String(item.material_code || '').trim();
  // Catalog imports from older snapshots may omit category_code. The material
  // number always ends with a serial segment, so recover the five-level path.
  const inferredCategory = materialCode.includes('.')
    ? materialCode.split('.').slice(0, -1).join('.')
    : '';
  const categoryCode = String(item.category_code || inferredCategory).trim();
  Object.assign(line, {
    material_code: materialCode,
    category_code: categoryCode,
    category_path: item.category_path || '',
    category_parts: categoryPartsFromCode(categoryCode),
    category_query: categoryCode,
    item_name: item.material_name || '',
    specification: item.specification || '',
    product_desc: item.product_desc || '',
    brand: item.brand || '',
    product_name: item.product_name || '',
    product_desc_en: item.product_desc_en || '',
    brand_en: item.brand_en || '',
    material_attr: item.material_attr || '外购',
    unit: item.unit || '个',
    material_query: `${materialCode} ${item.material_name || ''}`.trim(),
    material_open: false,
  });
  materialSearchResults[index] = [];
  closeCategoryPicker(line)
}
function selectFirstMaterial(index, line) {
  const first = materialMatchesFor(index)[0];
  if (first) {
    selectMaterial(index, line, first);
    return;
  }
  const firstCategory = categoryMatches(line)[0];
  if (firstCategory) selectCategory(line, firstCategory);
}
function categoryMatches(line) {
  const query = String(line.material_query || line.category_query || line.category_code || '').trim().toLowerCase();
  const selectable = materialCategories.value.filter((item) => Number(item.level || String(item.category_code || '').split('.').filter(Boolean).length) >= 3);
  if (!query) return selectable.slice(0, 8);
  return selectable.filter((item) => [item.category_code, item.category_name, item.full_path]
    .some((value) => String(value || '').toLowerCase().includes(query))).slice(0, 8);
}
function openCategoryPicker(line) {
  line.category_open = true;
  line.material_open = false;
  if (!Array.isArray(line.category_picker_path)) line.category_picker_path = [];
  line.category_picker_parent = line.category_picker_path[line.category_picker_path.length - 1] || '';
  loadCategoryMaterials(line.category_picker_parent);
}
function closeCategoryPicker(line) {
  line.category_open = false;
  line.category_picker_parent = '';
  line.category_picker_path = [];
}
function categoryChildrenFor(line) {
  const parent = String(line.category_picker_parent || '').trim();
  return materialCategories.value
    .filter((item) => {
      const itemParent = categoryParentCode(item);
      return parent ? itemParent === parent : !itemParent;
    })
    .sort((a, b) => String(a.category_code).localeCompare(String(b.category_code), undefined, { numeric: true }));
}
function categoryHasChildren(item) {
  const code = String(item?.category_code || '').trim();
  return Boolean(code && materialCategories.value.some((candidate) => categoryParentCode(candidate) === code));
}
function categoryMaterialsFor(line) {
  return categoryMaterialResults[String(line?.category_picker_parent || '').trim()] || [];
}
async function loadCategoryMaterials(categoryCode) {
  const code = String(categoryCode || '').trim();
  if (!code || categoryMaterialResults[code] || categoryMaterialLoading[code]) return;
  categoryMaterialLoading[code] = true;
  try {
    const rowsFrom = (response) => (Array.isArray(response)
      ? response
      : (Array.isArray(response?.message)
        ? response.message
        : (Array.isArray(response?.data)
          ? response.data
          : (Array.isArray(materialLoader.data) ? materialLoader.data : []))));
    const response = await materialLoader.fetch({ category_code: code, limit: 500 });
    const responseRows = rowsFrom(response);
    const rows = responseRows.filter((row) => {
      const materialCode = String(row?.material_code || '').trim();
      const rowCategory = String(row?.category_code || '').trim();
      // The API may return the whole descendant subtree for a category query.
      // Only show materials directly owned by this category; descendants stay
      // behind their own category nodes so the picker remains truly sequential.
      const suffix = materialCode.startsWith(`${code}.`)
        ? materialCode.slice(code.length + 1)
        : '';
      const isDirectSerial = Boolean(suffix && !suffix.includes('.'));
      return isDirectSerial || (!materialCode && rowCategory === code);
    });
    // Older endpoints can ignore category_code. Query by the exact prefix so
    // the fifth category still exposes its .001/.002/.003 serials.
    if (!rows.length) {
      const fallbackResponse = await materialLoader.fetch({ query: `${code}.`, limit: 500 });
      const fallbackRows = rowsFrom(fallbackResponse);
      categoryMaterialResults[code] = fallbackRows.filter((row) => {
        const materialCode = String(row?.material_code || '').trim();
        const rowCategory = String(row?.category_code || '').trim();
        const suffix = materialCode.startsWith(`${code}.`)
          ? materialCode.slice(code.length + 1)
          : '';
        return Boolean(suffix && !suffix.includes('.')) || (!materialCode && rowCategory === code);
      });
    } else {
      categoryMaterialResults[code] = rows;
    }
  } catch (exception) {
    categoryMaterialResults[code] = [];
    fail(exception, '物料库查询失败');
  } finally {
    categoryMaterialLoading[code] = false;
  }
}
function categoryPickerPathLabels(line) {
  return (line.category_picker_path || [])
    .map((code) => materialCategories.value.find((item) => item.category_code === code)?.category_name || code);
}
function goBackCategory(line) {
  const path = Array.isArray(line.category_picker_path) ? line.category_picker_path.slice(0, -1) : [];
  line.category_picker_path = path;
  line.category_picker_parent = path[path.length - 1] || '';
}
function categoryPickerConfirmCode(line) {
  return String(line?.category_picker_parent || line?.category_picker_path?.slice(-1)[0] || '').trim();
}
function categoryPickerCanConfirm(line) {
  const code = categoryPickerConfirmCode(line);
  return !line?.material_code && code.split('.').filter(Boolean).length >= 3;
}
function confirmCategorySelection(line) {
  const code = categoryPickerConfirmCode(line);
  if (code.split('.').filter(Boolean).length < 3) return;
  const item = materialCategories.value.find((candidate) => candidate.category_code === code);
  if (item) selectCategory(line, item);
}
async function chooseCategoryNode(index, line, item) {
  const code = String(item?.category_code || '').trim();
  if (!code) return;
  // Persist the deepest category as soon as it reaches the minimum depth.
  // A category can still expose serials below it; keeping the code here makes
  // the form valid even when the user submits without choosing a serial.
  const depth = code.split('.').filter(Boolean).length;
  if (depth >= 3) {
    line.category_code = code;
    line.category_path = item.full_path || item.category_name || '';
    line.category_parts = categoryPartsFromCode(code);
    line.category_query = `${code} ${item.category_name || ''}`.trim();
  }
  if (categoryHasChildren(item)) {
    line.category_picker_path = [...(line.category_picker_path || []), code];
    line.category_picker_parent = code;
    line.material_query = code + (item.category_name ? " " + item.category_name : "");
    await loadCategoryMaterials(code);
    return;
  }
  line.category_picker_path = [...(line.category_picker_path || []), code];
  line.category_picker_parent = code;
  line.material_query = code + (item.category_name ? " " + item.category_name : "");
  await loadCategoryMaterials(code);
  if (!categoryMaterialsFor(line).length) selectCategory(line, item);
}
function chooseCategoryMaterial(index, line, item) {
  selectMaterial(index, line, item);
}
function selectCategory(line, item) {
  line.category_code = item.category_code || '';
  line.category_path = item.full_path || item.category_name || '';
  line.category_parts = String(line.category_code).split('.').filter(Boolean).reduce((parts, _part, index, all) => {
    parts.push(all.slice(0, index + 1).join('.'));
    return parts;
  }, []);
  line.category_query = `${line.category_code} ${item.category_name || ''}`.trim();
  line.material_query = line.category_code + (item.category_name ? " " + item.category_name : "");
  closeCategoryPicker(line);
}
function selectFirstCategory(line) {
  const first = categoryMatches(line)[0];
  if (first) selectCategory(line, first);
}
function categoryParentCode(item) {
  return item.parent_category || String(item.category_code || '').split('.').slice(0, -1).join('.');
}
function categoryPartsFromCode(code) {
  const parts = String(code || '').split('.').filter(Boolean);
  return parts.map((_part, index) => parts.slice(0, index + 1).join('.'));
}
function categoryLevelOptions(line, level) {
  const parent = level > 0 ? line.category_parts?.[level - 1] : '';
  return materialCategories.value
    .filter((item) => Number(item.level || String(item.category_code || '').split('.').filter(Boolean).length) === level + 1)
    .filter((item) => level === 0 ? !categoryParentCode(item) : categoryParentCode(item) === parent)
    .sort((a, b) => String(a.category_code).localeCompare(String(b.category_code), undefined, { numeric: true }));
}
function categoryLevelsFor(line) {
  const levels = [];
  for (let level = 0; level < 6; level += 1) {
    const options = categoryLevelOptions(line, level);
    if (!options.length) break;
    levels.push(options);
    if (!line.category_parts?.[level]) break;
  }
  return levels;
}
function selectCategoryLevel(line, level, code) {
  line.category_parts = (line.category_parts || []).slice(0, level);
  if (code) line.category_parts.push(code);
  const selected = materialCategories.value.find((item) => item.category_code === code);
  line.category_code = level >= 2 ? code : '';
  line.category_path = selected?.full_path || selected?.category_name || '';
  line.category_query = line.category_code;
}
async function saveCatalogCategory() {
  if (!catalogCategoryForm.category_code.trim() || !catalogCategoryForm.category_name.trim()) { error.value = '请填写分类编码和名称'; return; }
  saving.value = true; error.value = ''; message.value = '';
  try {
    await categorySaver.submit({ ...catalogCategoryForm });
    message.value = `分类 ${catalogCategoryForm.category_code} 已保存`;
    Object.assign(catalogCategoryForm, { category_code: '', category_name: '', parent_category: '', full_path: '' });
    await categoryLoader.reload();
  } catch (exception) { fail(exception, '分类保存失败'); }
  finally { saving.value = false; }
}
async function saveCatalogMaterial() {
  const required = ['material_code', 'category_code', 'material_name', 'specification', 'product_desc', 'brand', 'unit'];
  if (required.some((field) => !String(catalogMaterialForm[field] || '').trim())) { error.value = '请完整填写物料编号、物料编号层级及物料资料'; return; }
  if (catalogMaterialForm.category_code.split('.').filter(Boolean).length < 3) { error.value = '物料编号至少需要三级'; return; }
  saving.value = true; error.value = ''; message.value = '';
  try {
    await materialSaver.submit({ ...catalogMaterialForm });
    message.value = `物料 ${catalogMaterialForm.material_code} 已保存`;
    Object.assign(catalogMaterialForm, { material_code: '', category_code: '', material_name: '', specification: '', product_desc: '', brand: '', unit: '个', category_path: '', material_attr: '外购' });
  } catch (exception) { fail(exception, '物料保存失败'); }
  finally { saving.value = false; }
}
function addInstallment() { if (quoteForm.payment_plan.length < 20) quoteForm.payment_plan.push(blankInstallment(quoteForm.payment_plan.length + 1)); }
function removeInstallment(index) { if (quoteForm.payment_plan.length > 1) quoteForm.payment_plan.splice(index, 1); }
function cleanPayload() { return buildApprovalCenterPayload(form, config.value.requestType); }
function fail(exception, fallback) { error.value = normalizeServerError(exception, fallback); }
function resetRequestForm() {
  Object.assign(form, blankForm());
  if (isProcurement.value) {
    const currentEmployee = optionLoader.data?.current_applicant?.employee;
    form.applicant_employee = applicants.value.find((row) => row.name === currentEmployee)?.name
      || applicants.value[0]?.name || '';
    form.purchaser_user = purchasers.value[0]?.name || '';
  }
}
function startNewRequest() {
  resetRequestForm();
  creatingNew.value = true;
  draftName.value = '';
  showCreateForm.value = true;
  documents.value = [];
  message.value = '';
  error.value = '';
  pmcEditMode.value = false;
}
function closeRequestForm() {
  if (isPmcEditPage.value) {
    router.push({ path: '/approval/procurement', query: { request: route.params.name } });
    return;
  }
  showCreateForm.value = false;
}
function toggleCreateForm() {
  if (isProcurement.value) {
    if (showCreateForm.value && isNewRequestPage.value) router.push('/approval/procurement');
    else router.push('/approval/procurement/new');
    return;
  }
  if (isDirectPurchase.value) {
    if (showCreateForm.value && isNewRequestPage.value) router.push('/approval/direct-purchase');
    else router.push('/approval/direct-purchase/new');
    return;
  }
  if (showCreateForm.value) closeRequestForm();
  else startNewRequest();
}
function selectRequest(name) {
  creatingNew.value = false;
  selectedRequestName.value = String(name || '');
  const row = requestRows.value.find((item) => item.name === selectedRequestName.value);
  if (isPmcEditPage.value) {
    if (row && (!pmcEditMode.value || draftName.value !== row.name)) startPmcEdit();
    return;
  }
  if (row?.workflow_status !== '草稿') {
    draftName.value = '';
    showCreateForm.value = false;
    resetRequestForm();
  }
  pmcEditMode.value = false;
}
function startPmcEdit() {
  const row = selectedRequest.value;
  if (!row || !row.can_modify_procurement_request) {
    error.value = '仅当前 PMC 节点的采购申请可进入 PMC 修改。';
    return;
  }
  Object.assign(form, blankForm(), {
    subject: row.subject || '', reason: row.reason || '', expected_delivery_date: row.expected_delivery_date || '',
    procurement_scope: row.procurement_scope || '项目采购', project: row.project || '', applicant_employee: row.employee || '',
    business_lines: (row.business_lines || []).map((line) => ({
      ...blankLine(), ...line,
      category_parts: line.category_parts?.length ? line.category_parts : categoryPartsFromCode(line.category_code),
      material_query: line.material_query || [line.material_code, line.item_name].filter(Boolean).join(' '),
    })),
  });
  pmcEditMode.value = true;
  Object.keys(materialSuggestions).forEach((key) => delete materialSuggestions[key]);
  creatingNew.value = false;
  showCreateForm.value = true;
  draftName.value = row.name;
  if (!isPmcEditPage.value) router.push({ name: 'procurement-pmc-edit', params: { name: row.name } });
  form.business_lines.forEach((line, index) => suggestMaterialForLine(index, line));
}
async function suggestMaterialForLine(index, line) {
  if (!pmcEditMode.value || !line) return;
  if (line.material_code) return;
  try {
    materialSuggestions[index] = await materialSuggestionLoader.fetch({
      item_name: line.item_name,
      specification: line.specification,
      product_desc: line.product_desc,
      brand: line.brand,
      category_code: line.category_code,
      limit: 5,
    });
  } catch (exception) { fail(exception, '物料重复建议生成失败'); }
}
async function savePmcModification() {
  if (!selectedRequest.value) return;
  const validation = validateProcurementRequestForm(form, '采购申请');
  if (validation) { error.value = validation; return; }
  saving.value = true; error.value = ''; message.value = '';
  try {
    await pmcModifier.submit({ name: selectedRequest.value.name, business_lines: JSON.stringify(form.business_lines), expected_delivery_date: form.expected_delivery_date, reason: form.reason, subject: form.subject });
    message.value = `${selectedRequest.value.name} 已保存 PMC 修改并抄送相关人员`;
    pmcEditMode.value = false; showCreateForm.value = false;
    await reloadRequests();
  } catch (exception) { fail(exception, 'PMC 修改保存失败'); }
  finally { saving.value = false; }
}
function hasGlobalQueueAccess() {
  return Boolean(optionLoader.data?.procurement_global_access?.[config.value.requestType]);
}
async function reloadRequestQueues() {
  if (!optionLoader.data) return;
  if (hasGlobalQueueAccess()) await allLoader.reload();
  else await Promise.all([mineLoader.reload(), pendingLoader.reload()]);
}
async function changeQueuePage(delta) {
  queuePage.value += delta;
  selectedRequestName.value = '';
  await reloadRequestQueues();
}
const queueHasMore = computed(() => hasGlobalQueueAccess() ? (allLoader.data || []).length === queuePageSize : (mineLoader.data || []).length === queuePageSize || (pendingLoader.data || []).length === queuePageSize);
watch(() => String(route.params.name || route.query.request || selectedRequestName.value || ''), async (name) => {
  if (name) {
    try { await exactLoader.fetch({ view: 'all', request_type: config.value.requestType, name, limit: 1 }); }
    catch (err) { error.value = normalizeServerError(err) || '无法加载申请详情'; }
  }
}, { immediate: true });
async function reloadRequests() {
  const requests = [reloadRequestQueues()];
  const name = String(route.params.name || route.query.request || selectedRequestName.value || '');
  if (name) requests.push(exactLoader.fetch({ view: 'all', request_type: config.value.requestType, name, limit: 1 }));
  if (isPayment.value) requests.push(sourceLoader.reload());
  await Promise.all(requests);
}
async function refreshRequestsSilently() {
  if (refreshing.value) return;
  refreshing.value = true;
  try { await reloadRequests(); }
  catch (_) { /* Keep the current data; explicit actions still surface request errors. */ }
  finally { refreshing.value = false; }
}
function refreshWhenVisible() {
  if (document.visibilityState === 'visible') refreshRequestsSilently();
}

onMounted(() => {
  window.addEventListener('focus', refreshRequestsSilently);
  document.addEventListener('visibilitychange', refreshWhenVisible);
  refreshTimer = window.setInterval(refreshRequestsSilently, 30000);
});
onBeforeUnmount(() => {
  window.removeEventListener('focus', refreshRequestsSilently);
  document.removeEventListener('visibilitychange', refreshWhenVisible);
  if (refreshTimer) window.clearInterval(refreshTimer);
});

async function saveDraft() {
  saving.value = true; error.value = ''; message.value = '';
  try {
    const result = await saver.submit({ request_type: config.value.requestType, payload: JSON.stringify(cleanPayload()), name: draftName.value || undefined });
    draftName.value = result.name;
    message.value = `草稿 ${result.name} 已保存`;
    await reloadRequests();
    creatingNew.value = false;
    selectedRequestName.value = result.name;
    showCreateForm.value = true;
    await loadDocuments(result.name);
    return result;
  } catch (exception) { fail(exception, '保存失败'); return null; }
  finally { saving.value = false; }
}
async function submitApproval() {
  error.value = ''; message.value = '';
  if (organizationWarning.value) { error.value = organizationWarning.value; return; }
  const validation = validateProcurementRequestForm(form, config.value.requestType);
  if (validation) { error.value = validation; return; }
  saving.value = true;
  try {
    let name = draftName.value;
    const payload = JSON.stringify(cleanPayload());
    if (!name) {
      const result = await saver.submit({ request_type: config.value.requestType, payload });
      name = result.name;
      draftName.value = name;
    } else {
      await saver.submit({ request_type: config.value.requestType, payload, name });
    }
    await submitter.submit({ name });
    message.value = `${name} 已提交审批`;
    await reloadRequests();
    creatingNew.value = false;
    draftName.value = '';
    selectedRequestName.value = name;
    showCreateForm.value = false;
    await loadDocuments(name);
  } catch (exception) { fail(exception, '提交失败'); }
  finally { saving.value = false; }
}
async function loadDocuments(name = activeRequestName.value) {
  if (!name) { documents.value = []; return; }
  const requestedName = name;
  try {
    const rows = await documentLoader.fetch({ request: requestedName }) || [];
    if (requestedName === activeRequestName.value) documents.value = rows;
  } catch (exception) {
    if (requestedName === activeRequestName.value) fail(exception, '资料加载失败');
  }
}
function pickDocument(type) {
  documentType.value = type;
  uploadInput.value?.click();
}

async function uploadDocument(event) {
  const file = event.target.files?.[0]; event.target.value = '';
  if (!file || !activeRequestName.value) { error.value = '请先保存或选择申请单，再上传资料'; return; }
  uploading.value = true; error.value = '';
  try {
    const body = new FormData(); body.append('file', file); body.append('is_private', '1');
    const response = await fetch('/api/method/upload_file', { method: 'POST', body, credentials: 'same-origin', headers: { 'X-Frappe-CSRF-Token': window.csrf_token || '' } });
    const data = await response.json();
    if (!response.ok || data.exc) throw new Error(data.message || '上传失败');
    await attacher.submit({ request: activeRequestName.value, document_type: documentType.value, file_ref: data.message.name });
    message.value = '资料已归档并生成新版本'; await loadDocuments();
  } catch (exception) { fail(exception, '上传失败'); }
  finally { uploading.value = false; }
}
async function submitQuote() {
  if (!selectedRequest.value) return;
  error.value = ''; message.value = '';
  const validation = validatePriceApprovalForm(quoteForm);
  if (validation) { error.value = validation; return; }
  saving.value = true;
  try {
    await quoteSubmitter.submit({
      name: selectedRequest.value.name,
      supplier: quoteForm.supplier.trim(),
      business_lines: JSON.stringify(quoteForm.business_lines),
      payment_plan: JSON.stringify(quoteForm.payment_plan),
      tax_included: quoteForm.tax_included ? 1 : 0,
      tax_rate: quoteForm.tax_rate,
      delivery_terms: quoteForm.delivery_terms.trim(),
      warranty_terms: quoteForm.warranty_terms.trim(),
      invoice_condition: quoteForm.invoice_condition.trim(),
      change_reason: quoteForm.change_reason.trim(),
    });
    message.value = `${selectedRequest.value.name} 已提交价格审批表`;
    quoteForm.change_reason = '';
    await reloadRequests();
  } catch (exception) { fail(exception, '价格审批表提交失败'); }
  finally { saving.value = false; }
}

async function saveContractInformation() {
  if (!selectedRequest.value || saving.value) return;
  saving.value = true; error.value = ''; message.value = '';
  try {
    await contractSaver.submit({ name: selectedRequest.value.name, ...contractForm });
    message.value = `${selectedRequest.value.name} 已生成PO 采购订单草稿`;
    await reloadRequests();
  } catch (exception) { fail(exception, '合同信息保存失败'); }
  finally { saving.value = false; }
}
async function reviewContract() {
  try { await contractReviewer.submit({ name: selectedRequest.value.name, note: actionNote.value.trim() }); message.value = 'PO 采购订单已复核，等待用印'; await reloadRequests(); }
  catch (exception) { fail(exception, '合同复核失败'); }
}
async function sealContract() {
  try { await contractSealer.submit({ name: selectedRequest.value.name, note: actionNote.value.trim() }); message.value = 'PO 采购订单已生效，付款计划已生成'; await reloadRequests(); }
  catch (exception) { fail(exception, '电子用印失败'); }
}
async function removeDocument(row) {
  const reason = selectedRequest.value?.workflow_status === '草稿' || selectedRequest.value?.business_status === '需求已批准/待询价'
    ? '' : window.prompt('审批开始后的资料会保留审计记录，请填写作废原因') || '';
  try {
    await documentRemover.submit({ name: row.name, reason });
    message.value = reason ? '资料已作废并保留审计记录' : '错误资料已删除';
    await loadDocuments();
  } catch (exception) { fail(exception, '资料移除失败'); }
}

async function act(action) {
  if (!selectedRequest.value || saving.value) return;
  const requestName = selectedRequest.value.name;
  error.value = ''; message.value = ''; saving.value = true;
  try {
    const params = { name: requestName, action, note: action === 'reject' ? rejectReason.value.trim() : actionNote.value.trim(), expected_step_key: selectedRequest.value.current_step_key || '' };
    if (action === 'reject') params.reject_target = rejectTarget.value;
    await actor.submit(params);
    actedRequestSteps[requestName] = currentStepKeyFor(selectedRequest.value);
    rejectReason.value = ''; actionNote.value = '';
    message.value = action === 'reject' ? `${requestName} 已定向驳回` : `${requestName} 已审批通过`;
    await reloadRequests();
  } catch (exception) {
    fail(exception, '审批操作失败');
    await refreshRequestsSilently();
  } finally { saving.value = false; }
}
async function withdrawSelectedRequest() {
  if (!selectedRequest.value || saving.value) return;
  const note = window.prompt('请输入撤回原因（可选）') || '';
  saving.value = true; error.value = ''; message.value = '';
  try {
    await requestWithdrawer.submit({ name: selectedRequest.value.name, note });
    message.value = `${selectedRequest.value.name} 已撤回，可编辑后重新提交`;
    await reloadRequests();
  } catch (exception) {
    fail(exception, '撤回申请失败');
    await refreshRequestsSilently();
  } finally { saving.value = false; }
}
function resumeWithdrawnRequest() {
  const row = selectedRequest.value;
  if (!row || !canResumeWithdrawn.value) return;
  hydrateDraftForm(row);
  draftName.value = row.name;
  creatingNew.value = false;
  pmcEditMode.value = false;
  showCreateForm.value = true;
  message.value = '';
  error.value = '';
}
async function registerContract() {
  try { await contractRegistrar.submit({ name: selectedRequest.value.name, contract_delivery_date: contractDate.value, reason: contractReason.value }); await reloadRequests(); }
  catch (exception) { fail(exception, '合同交期登记失败'); }
}
async function recordArrival() {
  try { await arrivalRecorder.submit({ name: selectedRequest.value.name, quantity: arrivalQuantity.value, arrival_date: arrivalDate.value }); await reloadRequests(); }
  catch (exception) { fail(exception, '到货登记失败'); }
}
async function recordInspection() {
  try { await inspectionRecorder.submit({ name: selectedRequest.value.name, outcome: inspectionOutcome.value, reason: inspectionReason.value, direction: inspectionDirection.value }); await reloadRequests(); }
  catch (exception) { fail(exception, '验收登记失败'); }
}
async function recordFollowup() {
  try { await followupRecorder.submit({ name: selectedRequest.value.name, status: followupStatus.value, reason: followupReason.value }); await reloadRequests(); }
  catch (exception) { fail(exception, '异常跟进登记失败'); }
}
async function completeRefund() {
  try { await refundCompleter.submit({ name: selectedRequest.value.name, reason: followupReason.value }); await reloadRequests(); }
  catch (exception) { fail(exception, '供应商退款确认失败'); }
}
async function writeoff() {
  try { await writeoffRecorder.submit({ name: selectedRequest.value.name, reason: actionNote.value }); await reloadRequests(); }
  catch (exception) { fail(exception, '预付款核销失败'); }
}
async function closeOrder() {
  try { await closeRecorder.submit({ name: selectedRequest.value.name, reason: actionNote.value }); await reloadRequests(); }
  catch (exception) { fail(exception, '采购关闭失败'); }
}

function hydrateDraftForm(row) {
  if (!row || row.workflow_status !== '草稿') return;
  showCreateForm.value = true;
  const fields = [
    'subject', 'urgency', 'asset_nature', 'fixed_asset_category',
    'expected_delivery_date', 'applicant_employee', 'procurement_scope',
    'project', 'non_project_allocation_type', 'non_project_cost_center',
    'non_project_department', 'purchase_method', 'source_request', 'source_payment_plan_row',
    'source_purchase_order', 'source_po_payment_plan_row', 'supplier',
    'prepayment_percentage', 'expected_arrival_date', 'prepayment_risk_note',
    'reason', 'purchaser_user',
  ];
  for (const field of fields) {
    if (Object.prototype.hasOwnProperty.call(row, field) && row[field] !== null && row[field] !== undefined) {
      form[field] = row[field];
    }
  }
  form.business_lines = (row.business_lines || []).map((line) => ({
    ...blankLine(),
    ...line,
    category_parts: line.category_parts?.length ? line.category_parts : categoryPartsFromCode(line.category_code),
      material_query: line.material_query || [line.material_code, line.item_name].filter(Boolean).join(' '),
    category_query: line.category_query || [line.category_code, line.category_name].filter(Boolean).join(' '),
    material_query: line.material_query || [line.material_code, line.item_name].filter(Boolean).join(' '),
    quantity: Number(line.quantity || 0),
    unit_price: Number(line.unit_price || 0),
  }));
  if (!form.business_lines.length) form.business_lines = [blankLine()];
  draftName.value = row.name;
}

watch(form, () => {
  if (error.value && !saving.value) error.value = '';
}, { deep: true });
watch(() => optionLoader.data, async (options, previous) => {
  if (options && !previous) await reloadRequests();
}, { immediate: true });
watch(() => route.path, async () => {
  queuePage.value = 0;
  hydratedDetailRequestName.value = '';
  resetRequestForm(); creatingNew.value = false; draftName.value = ''; selectedRequestName.value = ''; showCreateForm.value = false;
  documents.value = []; message.value = ''; error.value = '';
  if (isNewRequestPage.value) startNewRequest();
  await reloadRequests();
  if (isPmcEditPage.value) {
    const row = requestRows.value.find((item) => item.name === String(route.params.name || ''));
    if (row) startPmcEdit();
  }
});
watch(() => config.value.requestType, async (requestType) => {
  if (requestType === '采购申请') await categoryLoader.reload();
}, { immediate: true });
watch(applicants, (rows) => {
  if (!isProcurement.value || form.applicant_employee || !rows.length) return;
  const currentEmployee = optionLoader.data?.current_applicant?.employee;
  form.applicant_employee = rows.find((row) => row.name === currentEmployee)?.name || rows[0].name;
}, { immediate: true });
watch(purchasers, (rows) => {
  if (isProcurement.value && !form.purchaser_user && rows.length) form.purchaser_user = rows[0].name;
}, { immediate: true });
watch(selectedRequest, (row) => {
  if (creatingNew.value) return;
  if (row?.name) {
    selectedRequestName.value = row.name;
    // Queue reloads replace row objects even when the user is still editing the
    // same request. Only hydrate from the server when the selected request
    // actually changes; otherwise local, unsaved price/contract edits survive.
    if (hydratedDetailRequestName.value === row.name) return;
    hydratedDetailRequestName.value = row.name;
    hydrateDraftForm(row);
    quoteForm.supplier = row.supplier || '';
    quoteForm.change_reason = '';
    quoteForm.tax_included = Number(row.price_tax_included ?? 1);
    quoteForm.tax_rate = Number(row.price_tax_rate || 13);
    quoteForm.delivery_terms = row.price_delivery_terms || '';
    quoteForm.warranty_terms = row.price_warranty_terms || '';
    quoteForm.invoice_condition = row.price_invoice_condition || '';
    quoteForm.payment_plan = (row.payment_plan || []).map((item) => ({
      installment_name: item.installment_name, payment_stage: item.payment_stage,
      percentage: Number(item.percentage || 0), amount: Number(item.amount || 0),
      planned_date: item.planned_date || '', trigger_condition: item.trigger_condition || '',
      invoice_requirement: item.invoice_requirement || '付款前提供',
    }));
    if (!quoteForm.payment_plan.length) quoteForm.payment_plan = [blankInstallment(1), blankInstallment(2)];
    quoteForm.business_lines = (row.business_lines || []).map((line) => ({
      item_name: line.item_name || '', specification: line.specification || '',
      quantity: Number(line.quantity || 0), unit: line.unit || '个',
      unit_price: Number(line.unit_price || 0), remarks: line.remarks || '',
    }));
    Object.assign(contractForm, {
      supplier_legal_name: row.contract_supplier_legal_name || row.supplier || '',
      credit_code: row.contract_credit_code || '',
      supplier_address: row.contract_supplier_address || '',
      contract_contact: row.contract_contact || '',
      contract_bank_name: row.contract_bank_name || '',
      contract_bank_account: row.contract_bank_account || '',
      contract_entity: !row.contract_entity || ['普朗克半导体', '示例企业022有限公司', 'Rayher', 'Rayher Technology Co., Ltd.'].includes(row.contract_entity) ? '示例企业032有限公司' : row.contract_entity,
      contract_template: row.contract_template || '标准采购合同（测试版）',
      seal_user: row.contract_seal_user || '',
      contract_delivery_date: row.contract_delivery_date || row.expected_delivery_date || '',
    });
    loadDocuments(row.name);
  }
}, { immediate: true });
watch(() => form.source_payment_plan_row, (rowName) => {
  if (!isPayment.value || !rowName) return;
  const source = paymentSources.value.find((item) => item.payment_plan_row === rowName);
  if (!source) return;
  const fromPo = Boolean(source.source_purchase_order);
  form.source_request = fromPo ? (source.source_request || '') : source.name;
  form.source_payment_plan_row = fromPo ? '' : source.payment_plan_row;
  form.source_purchase_order = source.source_purchase_order || '';
  form.source_po_payment_plan_row = fromPo ? source.source_po_payment_plan_row || source.payment_plan_row : '';
  form.supplier = source.supplier;
  form.prepayment_percentage = source.payment_stage === '预付款' ? Number(source.percentage || 0) : 0;
  form.expected_arrival_date = source.expected_arrival_date || source.planned_date || '';
  form.subject = form.subject || `${source.name} · ${source.installment_name}`;
  form.business_lines = (source.business_lines || []).map((line) => ({
    item_name: line.item_name || '', specification: line.specification || '',
    quantity: Number(line.quantity || 0), unit: line.unit || '个',
    unit_price: Number(line.unit_price || 0), remarks: line.remarks || '',
  }));
});

watch(requestRows, (rows) => {
  if (creatingNew.value) return;
  const requested = String(route.params.name || route.query.request || '');
  if (requested && rows.some((row) => row.name === requested)) selectRequest(requested);
}, { immediate: true });
watch(() => [route.query.request, route.params.name], ([queryName, paramName]) => {
  const name = paramName || queryName;
  if (name) selectRequest(String(name));
});
</script>

<template>
  <div class="space-y-5">
    <header v-if="isNewRequestPage" class="border-b border-gray-200 pb-5">
      <router-link :to="isDirectPurchase ? '/approval/direct-purchase' : '/approval/procurement'" class="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900"><FeatherIcon name="arrow-left" class="h-4 w-4" />返回{{ isDirectPurchase ? '购买申请' : '采购审批' }}</router-link>
      <div class="mt-4 flex flex-wrap items-end justify-between gap-4"><div><h1 class="text-xl font-semibold text-gray-900">{{ isDirectPurchase ? '新建购买申请' : '新建采购申请' }}</h1></div><span class="rounded-md bg-gray-100 px-2.5 py-1 text-xs text-gray-600">{{ isDirectPurchase ? '购买申请' : '采购申请' }}</span></div>
    </header>
    <header v-else-if="isInnerPage" class="border-b border-gray-200 pb-5">
      <router-link :to="{ path: '/approval/procurement', query: { request: route.params.name } }" class="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900"><FeatherIcon name="arrow-left" class="h-4 w-4" />返回采购主单</router-link>
      <div class="mt-4 flex flex-wrap items-end justify-between gap-4">
        <div><div class="flex flex-wrap items-center gap-2"><h1 class="text-xl font-semibold text-gray-900">{{ innerPageTitle }}</h1><span class="rounded-md bg-gray-100 px-2.5 py-1 font-mono text-xs text-gray-600">{{ route.params.name }}</span></div><p class="mt-2 text-sm text-gray-500">{{ selectedRequest?.subject || '采购业务单据' }}</p></div>
        <nav v-if="!isPmcEditPage && (selectedRequest?.can_view_procurement_price || selectedRequest?.can_view_procurement_po)" class="inline-flex rounded-md border border-gray-300 bg-white p-1 text-sm">
          <router-link :to="{ name: 'procurement-price-approvals', query: { request: route.params.name, tab: selectedRequest?.can_view_procurement_price ? undefined : 'po' } }" class="rounded px-3 py-1.5 text-gray-600" active-class="bg-gray-900 text-white">价格审批与PO</router-link>
        </nav>
      </div>
    </header>
    <header v-else class="flex flex-wrap items-center justify-between gap-4 border-b border-gray-200 pb-4">
      <div>
        <h1 class="text-xl font-semibold text-gray-900">{{ config.title }}</h1>
        <p class="mt-1 text-sm text-gray-500">{{ isPayment ? '由 PO 付款计划下推，完成付款审批与付款记录' : (isDirectPurchase ? '提交个人购买需求并进入审批' : '申请、审批、询价与履约') }}</p>
      </div>
      <div class="flex items-center gap-2">
        <router-link v-if="isProcurement && canSeeProcurementPrice()" :to="{ name: 'procurement-price-approvals' }" class="inline-flex h-9 items-center gap-2 rounded-md border border-gray-300 bg-white px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"><FeatherIcon name="file-text" class="h-4 w-4" />价格审批</router-link>
        <button v-if="!isPayment" type="button" class="inline-flex h-9 items-center gap-2 rounded-md bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-800" @click="toggleCreateForm">
          <FeatherIcon :name="showCreateForm ? 'x' : 'plus'" class="h-4 w-4" />
          {{ showCreateForm ? '收起申请表' : '新建申请' }}
        </button>
      </div>
    </header>

    <div v-if="showCreateForm && organizationWarning" class="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{{ organizationWarning }}</div>
    <div v-if="message" class="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{{ message }}</div>
    <div v-if="error" class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{{ error }}</div>
    <div v-if="isPayment" class="flex flex-wrap items-center justify-between gap-3 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
      <span>采购付款单由 PO 付款计划下推生成，不能单独新建。</span>
      <router-link to="/approval/procurement/price-approvals?tab=po" class="inline-flex items-center gap-1.5 font-semibold text-blue-700 hover:text-blue-900"><FeatherIcon name="external-link" class="h-4 w-4" />进入 PO 下推付款</router-link>
    </div>

    <section v-if="false" class="overflow-hidden rounded-lg border border-amber-200 bg-amber-50">
      <button type="button" class="flex w-full items-center justify-between px-5 py-4 text-left" @click="catalogOpen = !catalogOpen">
        <span class="flex items-center gap-2 text-sm font-semibold text-amber-900"><FeatherIcon name="database" class="h-4 w-4" />PMC物料目录维护</span>
        <FeatherIcon :name="catalogOpen ? 'chevron-up' : 'chevron-down'" class="h-4 w-4 text-amber-700" />
      </button>
      <div v-if="catalogOpen" class="grid gap-5 border-t border-amber-200 bg-white px-5 py-5 lg:grid-cols-2">
        <form class="space-y-3" @submit.prevent="saveCatalogCategory">
          <h3 class="text-sm font-semibold text-gray-900">新增或修改分类</h3>
          <div class="grid gap-3 sm:grid-cols-2"><label class="text-sm">分类编码<input v-model="catalogCategoryForm.category_code" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" placeholder="例如 1.ELC.3.3" /></label><label class="text-sm">分类名称<input v-model="catalogCategoryForm.category_name" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label></div>
          <div class="grid gap-3 sm:grid-cols-2"><label class="text-sm">父级编码<input v-model="catalogCategoryForm.parent_category" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label><label class="text-sm">完整路径<input v-model="catalogCategoryForm.full_path" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label></div>
          <button type="submit" class="inline-flex h-9 items-center gap-2 rounded-md bg-amber-700 px-4 text-sm font-medium text-white disabled:opacity-50" :disabled="saving"><FeatherIcon name="save" class="h-4 w-4" />保存分类</button>
        </form>
        <form class="space-y-3" @submit.prevent="saveCatalogMaterial">
          <h3 class="text-sm font-semibold text-gray-900">新增或修改正式物料</h3>
          <div class="grid gap-3 sm:grid-cols-2"><label class="text-sm">物料编号<input v-model="catalogMaterialForm.material_code" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" placeholder="例如 1.ELC.3.3.01.001" /></label><label class="text-sm">物料编号层级<input v-model="catalogMaterialForm.category_code" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" placeholder="例如 1.ELC.3" /></label></div>
          <div class="grid gap-3 sm:grid-cols-2"><label class="text-sm">物料名称<input v-model="catalogMaterialForm.material_name" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label><label class="text-sm">规格型号<input v-model="catalogMaterialForm.specification" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label></div>
          <div class="grid gap-3 sm:grid-cols-2"><label class="text-sm">商品品牌<input v-model="catalogMaterialForm.brand" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label><label class="text-sm">计量单位<input v-model="catalogMaterialForm.unit" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label></div>
          <label class="block text-sm">产品描述<textarea v-model="catalogMaterialForm.product_desc" rows="2" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
          <button type="submit" class="inline-flex h-9 items-center gap-2 rounded-md bg-gray-900 px-4 text-sm font-medium text-white disabled:opacity-50" :disabled="saving"><FeatherIcon name="save" class="h-4 w-4" />保存物料</button>
        </form>
      </div>
    </section>

    <section v-if="!isNewRequestPage && !isPmcEditPage" class="overflow-hidden rounded-lg border border-gray-200 bg-white">
      <div class="grid min-h-[0]" :class="isInnerPage ? 'grid-cols-1' : 'xl:grid-cols-[300px_minmax(0,1fr)]'">
        <aside v-if="!isInnerPage" class="order-2 border-b border-gray-200 bg-gray-50 xl:order-1 xl:border-b-0 xl:border-r">
          <div class="sticky top-0 z-10 flex items-center justify-between border-b border-gray-200 bg-gray-50 px-4 py-4">
            <div>
              <h2 class="text-sm font-semibold text-gray-900">审批队列</h2>
              <p class="mt-1 text-xs text-gray-500">{{ requestRowsLoading && !requestRows.length ? '正在加载业务单据...' : `${filteredRequestRows.length} / ${requestRows.length} 张业务单据` }}</p>
            </div>
            <span class="flex h-8 w-8 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-500"><FeatherIcon name="inbox" class="h-4 w-4" /></span>
          </div>
          <div v-if="isProcurement" class="border-b border-gray-200 bg-white px-3 py-3">
            <div class="mb-2 flex items-center justify-between gap-2">
              <span class="text-[11px] font-semibold uppercase tracking-wide text-gray-400">筛选本页审批状态</span>
              <button type="button" class="text-[11px] font-medium text-gray-500 hover:text-gray-900" @click="pmcQueueFilter = 'all'">重置</button>
            </div>
            <div class="grid grid-cols-2 gap-1">
              <button v-for="option in queueFilterOptions" :key="option.key" type="button" class="rounded-md px-2 py-2 text-left text-xs transition-colors" :class="pmcQueueFilter === option.key ? 'bg-gray-900 font-semibold text-white' : 'text-gray-600 hover:bg-gray-100'" @click="pmcQueueFilter = option.key">
                <span class="block truncate">{{ option.label }}</span><span class="mt-0.5 block text-[11px]" :class="pmcQueueFilter === option.key ? 'text-gray-300' : 'text-gray-400'">{{ option.count }}</span>
              </button>
            </div>
          </div>
          <div class="max-h-[640px] divide-y divide-gray-200 overflow-y-auto">
            <button
              v-for="row in filteredRequestRows"
              :key="row.name"
              type="button"
              class="group relative block w-full border-l-[3px] px-4 py-4 text-left transition-colors"
              :class="queueRowClass(row)"
              @click="selectRequest(row.name)"
            >
              <div class="flex items-center justify-between gap-3">
                <span class="rounded-md border px-2 py-1 text-[11px] font-semibold" :class="approvalStageMeta(row).tone">{{ approvalStageMeta(row).label }}</span>
                <span class="font-mono text-[11px] text-gray-400">{{ row.name }}</span>
              </div>
              <p class="mt-3 line-clamp-2 text-sm font-semibold leading-5 text-gray-900">{{ row.subject || '未填写主题' }}</p>
              <div class="mt-3 flex items-center justify-between gap-3 text-xs">
                <span class="min-w-0 truncate text-gray-600">{{ row.employee_name || '未关联员工' }}</span>
                <span v-if="Number(row.amount || 0) > 0" class="shrink-0 font-semibold tabular-nums text-gray-900">¥ {{ formatMoney(row.amount) }}</span>
              </div>
              <div class="mt-2 flex items-start gap-2 text-xs leading-5 text-gray-500">
                <FeatherIcon name="git-commit" class="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span class="min-w-0 flex-1">{{ row.current_step_label || approvalStageMeta(row).description || row.business_status || '-' }}</span>
              </div>
              <div v-if="canApproveRow(row) || canRejectRow(row)" class="mt-3 flex items-center justify-between border-t border-gray-200 pt-3">
                <span class="text-xs font-medium" :class="approvalStageMeta(row).key === 'price' ? 'text-blue-700' : 'text-amber-700'">{{ approvalStageMeta(row).action }}</span>
                <FeatherIcon name="arrow-right" class="h-3.5 w-3.5 shrink-0 text-gray-400 transition-transform group-hover:translate-x-0.5" />
              </div>
            </button>
            <div v-if="requestRowsLoading && !requestRows.length" class="px-5 py-16 text-center text-sm text-gray-500" aria-live="polite">
              <span class="mx-auto mb-3 block h-5 w-5 animate-spin rounded-full border-2 border-gray-300 border-t-gray-800"></span>
              正在读取申请和待办，请稍候
            </div>
            <div v-else-if="requestRowsError && !requestRows.length" class="px-5 py-16 text-center text-sm text-red-700">
              <FeatherIcon name="alert-circle" class="mx-auto mb-3 h-5 w-5" />
              <p>业务单据加载失败</p>
              <button type="button" class="mt-3 rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-semibold hover:bg-red-50" @click="reloadRequests">重新加载</button>
            </div>
            <div v-else-if="!filteredRequestRows.length" class="px-5 py-16 text-center text-sm text-gray-400">
              <FeatherIcon name="inbox" class="mx-auto mb-3 h-5 w-5" />
              {{ requestRows.length ? '当前筛选暂无单据' : '暂无申请或待办' }}
            </div>
          </div>
          <div class="flex flex-wrap items-center justify-between gap-2 border-t p-3 text-xs"><button type="button" :disabled="queuePage === 0 || requestRowsLoading" class="rounded border px-2 py-1 disabled:opacity-40" @click="changeQueuePage(-1)">上一页</button><span>第 {{ queuePage + 1 }} 页</span><button type="button" :disabled="!queueHasMore || requestRowsLoading" class="rounded border px-2 py-1 disabled:opacity-40" @click="changeQueuePage(1)">下一页</button></div>
        </aside>

        <article v-if="selectedRequest" class="order-1 min-w-0 bg-white xl:order-2">
          <header class="border-b border-gray-200 bg-white px-5 py-6 lg:px-7">
            <div class="flex flex-wrap items-start justify-between gap-5">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="rounded-md border px-2.5 py-1 text-xs font-semibold" :class="approvalStageMeta(selectedRequest).tone">{{ approvalStageMeta(selectedRequest).label }}</span>
                  <span class="text-xs font-medium text-gray-500">{{ selectedRequest.workflow_status_label || selectedRequest.workflow_status }}</span>
                  <span v-if="selectedRequest.urgency === '加急'" class="inline-flex items-center gap-1 text-xs font-semibold text-red-700"><span class="h-1.5 w-1.5 rounded-full bg-red-600"></span>加急</span>
                </div>
                <h2 class="mt-3 text-xl font-semibold leading-7 text-gray-900">{{ selectedRequest.subject || selectedRequest.name }}</h2>
                <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500"><span class="font-mono">{{ selectedRequest.name }}</span><span>{{ selectedRequest.employee_name || '-' }}</span><span>{{ selectedRequest.department || '-' }}</span></div>
              </div>
              <div class="w-full border-t-2 border-gray-900 pt-3 sm:w-auto sm:min-w-[340px] sm:border-l-2 sm:border-t-0 sm:pl-4 sm:pt-0">
                <p class="text-[11px] font-medium text-gray-500">当前审批节点</p>
                <p class="mt-1 text-sm font-semibold leading-5 text-gray-900">{{ selectedRequest.current_step_label || approvalStageMeta(selectedRequest).label || selectedRequest.business_status || '-' }}</p>
                <p class="mt-1 text-xs text-gray-500">{{ approvalStageMeta(selectedRequest).description || selectedRequest.business_status || '-' }}</p>
                <div class="mt-3 flex flex-wrap gap-2">
                <button v-if="canPmcModify && !isInnerPage" type="button" class="inline-flex h-9 min-w-[150px] flex-1 items-center justify-center gap-2 rounded-md bg-amber-700 px-3 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-800 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2" @click="startPmcEdit">
                  <FeatherIcon name="edit-3" class="h-4 w-4" />{{ pmcModifyButtonLabel }}
                </button>
                <button v-if="canWithdrawSelected" type="button" class="inline-flex h-9 min-w-[150px] flex-1 items-center justify-center gap-2 rounded-md border border-red-300 bg-white px-3 text-sm font-semibold text-red-700 shadow-sm transition hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2" :disabled="saving" @click="withdrawSelectedRequest">
                  <FeatherIcon name="corner-up-left" class="h-4 w-4" />撤回申请
                </button>
                <button v-if="canResumeWithdrawn" type="button" class="inline-flex h-9 min-w-[150px] flex-1 items-center justify-center gap-2 rounded-md bg-gray-900 px-3 text-sm font-semibold text-white shadow-sm transition hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2" @click="resumeWithdrawnRequest">
                  <FeatherIcon name="edit-3" class="h-4 w-4" />编辑并重新提交
                </button>
                </div>
              </div>
            </div>

            <div v-if="isProcurement && !(selectedCanApprove || selectedCanReject)" class="mt-5 flex flex-wrap items-center justify-between gap-4 border-l-4 px-4 py-3.5" :class="approvalStageMeta(selectedRequest).panel">
              <div class="flex min-w-0 items-start gap-3">
                <span class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white text-gray-800"><FeatherIcon :name="approvalStageMeta(selectedRequest).icon" class="h-4 w-4" /></span>
                <div class="min-w-0"><p class="text-sm font-semibold text-gray-900">{{ selectedCanApprove || selectedCanReject ? approvalStageMeta(selectedRequest).action : approvalStageMeta(selectedRequest).label }}</p><p class="mt-0.5 text-xs leading-5 text-gray-600">{{ approvalStageMeta(selectedRequest).description }}</p></div>
              </div>
              <router-link v-if="!isInnerPage && isPriceChainAction(selectedRequest)" :to="procurementChainRoute(selectedRequest)" class="inline-flex h-9 shrink-0 items-center gap-2 rounded-md bg-blue-700 px-4 text-sm font-semibold text-white hover:bg-blue-800"><FeatherIcon name="external-link" class="h-4 w-4" />{{ approvalStageMeta(selectedRequest).key === 'quote' ? '处理询价/录价' : '打开价格审批单' }}</router-link>
            </div>

          </header>

          <section v-if="!isInnerPage" class="border-b border-gray-200 bg-white px-5 py-6 lg:px-7">
            <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
              <div>
                <div class="flex items-center gap-2"><span class="flex h-8 w-8 items-center justify-center rounded-md bg-gray-900 text-white"><FeatherIcon name="list" class="h-4 w-4" /></span><h3 class="text-base font-semibold text-gray-900">{{ isProcurement ? '采购明细' : (isPayment ? '采购付款明细' : '购买明细') }}</h3></div>
                <p class="mt-1.5 text-xs text-gray-500"><template v-if="isPayment">关联 PO 物料范围 · 本期付款计划金额 ¥ {{ formatMoney(selectedRequest.amount) }} · {{ selectedRequest.business_lines?.length || 0 }} 项 · 合计数量 {{ selectedTotalQuantity }}</template><template v-else>逐项核对物料、规格、数量与金额 · {{ selectedRequest.business_lines?.length || 0 }} 项 · 合计数量 {{ selectedTotalQuantity }}</template></p>
              </div>
              <span v-if="isProcurement && selectedRequest.business_lines?.some((line) => !line.material_code)" class="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700">部分物料待 PMC 绑定编号</span>
            </div>
            <div v-if="isProcurement" class="request-materials material-details">
              <article v-for="(line, index) in selectedRequest.business_lines || []" :key="line.name || index" class="request-material">
                <header class="material-row-head"><strong>第 {{ index + 1 }} 项</strong></header>
                <div class="material-fields"><div class="material-field span-3"><span>物料编号 / 流水号</span><p class="font-mono">{{ line.material_code || line.category_code || '待 PMC 补充' }}</p><p class="text-xs text-teal-700">{{ line.material_serial || '提交后自动生成' }}</p><p v-if="line.category_path" class="text-xs text-gray-500">{{ line.category_path }}</p></div>
<div class="material-field span-2"><span>物料名称</span><p>{{ line.item_name || '-' }}</p></div>
<div class="material-field span-2"><span>Product name</span><p>{{ line.product_name || '-' }}</p></div>
<div class="material-field span-3"><span>规格型号</span><p>{{ line.specification || '-' }}</p></div>
<div class="material-field span-1"><span>数量</span><p>{{ line.quantity || 0 }}</p></div>
<div class="material-field span-1"><span>单位</span><p>{{ line.unit || '-' }}</p></div></div>
                <div class="material-fields material-fields-secondary"><div class="material-field span-3"><span>产品描述</span><p>{{ line.product_desc || '-' }}</p></div>
<div class="material-field span-3"><span>Product description</span><p>{{ line.product_desc_en || '-' }}</p></div>
<div class="material-field span-1"><span>商品品牌</span><p>{{ line.brand || '-' }}</p></div>
<div class="material-field span-1"><span>Brand</span><p>{{ line.brand_en || '-' }}</p></div>
<div class="material-field span-1"><span>单价</span><p>{{ Number(line.unit_price || 0) > 0 ? formatMoney(line.unit_price) : '待询价' }}</p></div>
<div class="material-field span-1"><span>金额</span><p>{{ Number(line.amount || 0) > 0 ? formatMoney(line.amount) : (Number(line.unit_price || 0) > 0 ? formatMoney(Number(line.quantity || 0) * Number(line.unit_price || 0)) : '-') }}</p></div>
<div class="material-field span-2"><span>备注</span><p>{{ line.remarks || '-' }}</p></div></div>
              </article>
              <p v-if="!selectedRequest.business_lines?.length" class="p-5 text-center text-gray-400">该申请没有明细</p>
              <div v-if="Number(selectedRequest.amount || 0) > 0" class="p-4 text-right text-sm font-semibold">当前总金额 ¥ {{ formatMoney(selectedRequest.amount) }}</div>
            </div>
            <div v-else class="overflow-x-auto border border-gray-200">
              <table :class="isProcurement ? 'min-w-[1180px]' : 'min-w-[860px]'" class="w-full text-sm">
                <thead class="border-b border-gray-200 bg-gray-50 text-left text-xs font-medium text-gray-500">
                  <tr><th v-if="isProcurement" class="px-4 py-3 lg:pl-5">物料编号</th><th v-if="isProcurement" class="px-4 py-3">物料流水号</th><th class="px-5 py-3 lg:pl-6">物品名称</th><th class="px-4 py-3">规格</th><th class="px-4 py-3">产品描述</th><th v-if="isProcurement" class="px-4 py-3">品牌</th><th class="px-4 py-3 text-right">数量</th><th class="px-4 py-3">单位</th><th class="px-4 py-3 text-right">单价</th><th class="px-4 py-3 text-right">金额</th><th class="px-5 py-3 lg:pr-6">备注</th></tr>
                </thead>
                <tbody class="divide-y divide-gray-100">
                  <tr v-for="(line, index) in selectedRequest.business_lines || []" :key="index" class="align-top hover:bg-gray-50/70">
                    <td v-if="isProcurement" class="max-w-[210px] px-4 py-4 text-xs text-gray-600 lg:pl-5"><span class="font-mono text-gray-500">{{ line.material_code || line.category_code || '待 PMC 补充' }}</span><span v-if="!line.material_code && line.category_code" class="mt-1 block text-[11px] text-amber-700">待 PMC 完善完整编号</span><span v-if="line.category_path" class="mt-1 block whitespace-normal text-[11px] leading-5 text-gray-400" :title="line.category_path">{{ line.category_path }}</span></td>
                    
                    <td v-if="isProcurement" class="px-4 py-4 font-mono text-xs font-semibold text-teal-700">{{ line.material_serial || '提交后自动生成' }}</td>
                    <td class="px-5 py-4 font-medium text-gray-900 lg:pl-6">{{ line.item_name || '-' }}</td>
                    <td class="px-4 py-4 text-gray-600">{{ line.specification || '-' }}</td>
                    <td class="max-w-[260px] px-4 py-4 text-gray-600"><span class="line-clamp-3 leading-5" :title="line.product_desc || ''">{{ line.product_desc || '-' }}</span></td>
                    <td v-if="isProcurement" class="px-4 py-4 text-gray-600">{{ line.brand || '-' }}</td>
                    <td class="px-4 py-4 text-right tabular-nums text-gray-900">{{ line.quantity || 0 }}</td>
                    <td class="px-4 py-4 text-gray-600">{{ line.unit || '-' }}</td>
                    <td class="px-4 py-4 text-right tabular-nums text-gray-900">{{ Number(line.unit_price || 0) > 0 ? formatMoney(line.unit_price) : (isProcurement ? '待询价' : '-') }}</td>
                    <td class="px-4 py-4 text-right tabular-nums text-gray-900">{{ Number(line.amount || 0) > 0 ? formatMoney(line.amount) : (Number(line.unit_price || 0) > 0 ? formatMoney(Number(line.quantity || 0) * Number(line.unit_price || 0)) : '-') }}</td>
                    <td class="px-5 py-4 text-gray-600 lg:pr-6">{{ line.remarks || '-' }}</td>
                  </tr>
                  <tr v-if="!selectedRequest.business_lines?.length"><td :colspan="isProcurement ? 11 : 8" class="px-5 py-10 text-center text-sm text-gray-400">该申请没有明细</td></tr>
                </tbody>
                <tfoot v-if="Number(selectedRequest.amount || 0) > 0" class="border-t border-gray-200 bg-gray-50"><tr><td :colspan="isProcurement ? 9 : 6" class="px-5 py-3 text-right text-xs font-medium text-gray-500">{{ isPayment ? '本期付款金额' : '当前总金额' }}</td><td class="px-4 py-3 text-right font-semibold tabular-nums text-gray-900">¥ {{ formatMoney(selectedRequest.amount) }}</td><td></td></tr></tfoot>
              </table>
            </div>
          </section>

          <section v-if="!isInnerPage && isPriceApprovalStep(selectedRequest)" class="border-b border-blue-200 bg-blue-50/40 px-5 py-5 lg:px-7">
            <div class="flex flex-wrap items-end justify-between gap-3">
              <div><div class="flex items-center gap-2"><span class="flex h-7 w-7 items-center justify-center rounded-md bg-blue-700 text-white"><FeatherIcon name="bar-chart-2" class="h-3.5 w-3.5" /></span><h3 class="text-sm font-semibold text-gray-900">价格决策摘要</h3><span class="text-xs text-blue-700">V{{ selectedRequest.price_revision }}</span></div><p class="mt-1.5 text-xs text-gray-600">{{ selectedRequest.supplier || '未填写供应商' }} · {{ paymentPlanSummary(selectedRequest) }}</p></div>
              <div class="text-right"><p class="text-[11px] text-gray-500">本次审批总额</p><p class="mt-1 text-2xl font-semibold tabular-nums text-gray-900">¥ {{ formatMoney(selectedRequest.amount) }}</p></div>
            </div>

            <div class="mt-4 grid overflow-hidden border border-blue-200 bg-white lg:grid-cols-2">
              <div class="border-b border-blue-100 lg:border-b-0 lg:border-r">
                <div class="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-4 py-2.5"><span class="text-xs font-semibold text-gray-700">报价明细</span><span class="text-[11px] text-gray-500">{{ selectedRequest.business_lines?.length || 0 }} 项</span></div>
                <div class="divide-y divide-gray-100">
                  <div v-for="(line, index) in (selectedRequest.business_lines || []).slice(0, 3)" :key="line.name || index" class="grid grid-cols-[minmax(0,1fr)_auto] gap-3 px-4 py-3 text-sm">
                    <div class="min-w-0"><p class="truncate font-semibold text-gray-900">{{ line.item_name || '-' }}<span v-if="line.specification" class="font-normal text-gray-500"> · {{ line.specification }}</span></p><p class="mt-1 text-xs text-gray-500">{{ line.quantity || 0 }} {{ line.unit || '' }} · 单价 ¥ {{ formatMoney(line.unit_price) }}</p></div>
                    <p class="font-semibold tabular-nums text-gray-900">¥ {{ formatMoney(priceLineAmount(line)) }}</p>
                  </div>
                </div>
              </div>
              <div>
                <div class="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-4 py-2.5"><span class="text-xs font-semibold text-gray-700">付款安排</span><span class="text-[11px] text-gray-500">{{ selectedRequest.payment_plan?.length || 0 }} 期</span></div>
                <div class="divide-y divide-gray-100">
                  <div v-for="row in selectedRequest.payment_plan || []" :key="row.name || row.installment_no" class="grid grid-cols-[minmax(0,1fr)_auto] gap-3 px-4 py-3 text-sm">
                    <div class="min-w-0"><p class="font-semibold text-gray-900">{{ row.installment_name }} · {{ row.payment_stage }} · {{ row.percentage }}%</p><p class="mt-1 truncate text-xs text-gray-500">{{ row.planned_date || '未定日期' }} · {{ row.trigger_condition || '未填写触发条件' }}</p></div>
                    <p class="font-semibold tabular-nums text-gray-900">¥ {{ formatMoney(row.amount) }}</p>
                  </div>
                </div>
              </div>
            </div>

            <dl class="grid border-x border-b border-blue-200 bg-white sm:grid-cols-2 xl:grid-cols-4">
              <div class="border-b border-r border-gray-200 px-4 py-3 sm:border-b-0"><dt class="text-[11px] text-gray-500">计价方式</dt><dd class="mt-1 text-xs font-medium text-gray-900">{{ selectedRequest.price_tax_included ? `含税价 · ${selectedRequest.price_tax_rate}%` : '未税价' }}</dd></div>
              <div class="border-b border-gray-200 px-4 py-3 sm:border-b-0 xl:border-r"><dt class="text-[11px] text-gray-500">交付条件</dt><dd class="mt-1 truncate text-xs font-medium text-gray-900">{{ selectedRequest.price_delivery_terms || '-' }}</dd></div>
              <div class="border-r border-gray-200 px-4 py-3"><dt class="text-[11px] text-gray-500">开票条件</dt><dd class="mt-1 truncate text-xs font-medium text-gray-900">{{ selectedRequest.price_invoice_condition || '-' }}</dd></div>
              <div class="px-4 py-3"><dt class="text-[11px] text-gray-500">质保条件</dt><dd class="mt-1 truncate text-xs font-medium text-gray-900">{{ selectedRequest.price_warranty_terms || '-' }}</dd></div>
            </dl>
          </section>

          <section v-if="!isInnerPage" class="border-b border-gray-200 bg-gray-50/40 px-5 py-3 lg:px-7">
            <div class="mb-2 flex items-center justify-between"><div class="flex items-center gap-2"><span class="flex h-6 w-6 items-center justify-center rounded-md bg-white text-gray-500"><FeatherIcon name="clipboard" class="h-3 w-3" /></span><h3 class="text-sm font-semibold text-gray-900">{{ isPayment ? '付款来源与关联' : '采购需求信息' }}</h3></div><span class="text-xs text-gray-400">{{ formatDateTime(selectedRequest.creation) }}</span></div>
            <dl class="grid gap-x-5 gap-y-2.5 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
              <div class="min-w-0 xl:col-span-2"><dt class="text-[11px] text-gray-500">申请用途</dt><dd class="mt-0.5 whitespace-pre-wrap text-sm leading-5 text-gray-900">{{ selectedRequest.reason || '-' }}</dd></div>
              <div><dt class="text-[11px] text-gray-500">采购范围</dt><dd class="mt-0.5 text-sm font-medium text-gray-900">{{ selectedRequest.procurement_scope || (selectedRequest.project ? '项目购买' : '非项目购买') }}</dd></div>
              <div><dt class="text-[11px] text-gray-500">资产属性</dt><dd class="mt-0.5 text-sm font-semibold" :class="selectedRequest.asset_nature === '固定资产' ? 'text-amber-700' : 'text-gray-900'">{{ selectedRequest.asset_nature || '未标注' }}</dd></div>
              <div><dt class="text-[11px] text-gray-500">预计交期</dt><dd class="mt-0.5 text-sm font-medium text-gray-900">{{ selectedRequest.expected_delivery_date || selectedRequest.expected_arrival_date || '-' }}</dd></div>
              <div><dt class="text-[11px] text-gray-500">采购归属</dt><dd class="mt-0.5 truncate text-sm font-medium text-gray-900">{{ allocationLabel(selectedRequest) }}</dd></div>
              <div><dt class="text-[11px] text-gray-500">{{ selectedRequest.supplier ? '供应商' : '申请部门' }}</dt><dd class="mt-0.5 truncate text-sm font-medium text-gray-900">{{ selectedRequest.supplier || selectedRequest.department || '-' }}</dd></div>
              <div v-if="isDirectPurchase && selectedRequest.asset_nature === '固定资产'"><dt class="text-[11px] text-gray-500">固定资产类别</dt><dd class="mt-0.5 text-sm font-medium text-gray-900">{{ selectedRequest.fixed_asset_category || '未分类' }}</dd></div>
              <div v-if="selectedRequest.source_purchase_order"><dt class="text-[11px] text-gray-500">来源 PO</dt><dd class="mt-0.5 text-sm font-medium text-gray-900">{{ selectedRequest.source_purchase_order }}</dd></div>
              <div v-else-if="selectedRequest.source_request"><dt class="text-[11px] text-gray-500">来源采购单</dt><dd class="mt-0.5 text-sm font-medium text-gray-900">{{ selectedRequest.source_request }}</dd></div>
              <div v-if="isPayment"><dt class="text-[11px] text-gray-500">付款阶段</dt><dd class="mt-0.5 text-sm font-medium text-gray-900">{{ selectedRequest.payment_stage || '-' }}</dd></div>
              <div v-if="isPayment"><dt class="text-[11px] text-gray-500">本期付款金额</dt><dd class="mt-0.5 text-sm font-semibold text-gray-900">¥ {{ formatMoney(selectedRequest.amount) }}</dd></div>
              <div v-if="isPayment"><dt class="text-[11px] text-gray-500">来源类型</dt><dd class="mt-0.5 text-sm font-medium text-gray-900">{{ selectedRequest.source_type || 'PO付款下推' }}</dd></div>
            </dl>
          </section>

          <MaterialExecutionProgress v-if="isProcurement && !isInnerPage && selectedRequest" :key="selectedRequest.name" :request="selectedRequest.name" />

          <section v-if="isProcurement && !isInnerPage && showExecutionLinks" class="grid border-b border-gray-200 md:grid-cols-2">
            <router-link v-if="selectedRequest.can_view_procurement_price" :to="procurementChainRoute(selectedRequest)" class="group flex items-center justify-between gap-4 border-b border-gray-200 px-5 py-5 hover:bg-gray-50 md:border-b-0 md:border-r lg:px-6">
              <div class="flex min-w-0 items-center gap-3"><span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-700"><FeatherIcon name="calculator" class="h-5 w-5" /></span><div class="min-w-0"><h3 class="text-sm font-semibold text-gray-900">{{ selectedRequest.procurement_chain?.stage === 'await_pr' ? '去物料进度看板提 PR' : (selectedRequest.procurement_chain?.stage === 'quote' ? '去 PR 表格提价格审批表' : '价格审批单') }}</h3><p class="mt-1 truncate text-xs text-gray-500">{{ priceStatusLabel }}</p></div></div><FeatherIcon name="chevron-right" class="h-4 w-4 shrink-0 text-gray-400 group-hover:text-gray-700" />
            </router-link>
            <router-link v-if="selectedRequest.can_view_procurement_po && contractPageAvailable" :to="procurementChainRoute(selectedRequest, 'po')" class="group flex items-center justify-between gap-4 px-5 py-5 hover:bg-gray-50 lg:px-6">
              <div class="flex min-w-0 items-center gap-3"><span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-emerald-50 text-emerald-700"><FeatherIcon name="file-text" class="h-5 w-5" /></span><div class="min-w-0"><h3 class="text-sm font-semibold text-gray-900">PO 采购订单</h3><p class="mt-1 truncate text-xs text-gray-500">{{ contractStatusLabel }}</p></div></div><FeatherIcon name="chevron-right" class="h-4 w-4 shrink-0 text-gray-400 group-hover:text-gray-700" />
            </router-link>
          </section>

          <section v-if="isProcurement && !isInnerPage && selectedRequest.price_revision && !isPriceApprovalStep(selectedRequest)" class="border-b border-gray-200 bg-gray-50 px-5 py-5 lg:px-6">
            <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div><h3 class="text-sm font-semibold text-gray-900">已提交商业条件</h3><p class="mt-1 text-xs text-gray-500">价格审批表 V{{ selectedRequest.price_revision }} · 由演示员工37审批后锁定</p></div>
              <div class="text-right"><p class="text-xs text-gray-500">审批总额</p><p class="mt-1 text-lg font-semibold tabular-nums text-gray-900">¥ {{ formatMoney(selectedRequest.amount) }}</p></div>
            </div>
            <dl class="grid gap-4 border-y border-gray-200 bg-white px-4 py-4 md:grid-cols-2 xl:grid-cols-4">
              <div><dt class="text-xs text-gray-500">含税方式</dt><dd class="mt-1 text-sm font-medium">{{ selectedRequest.price_tax_included ? `含税 · ${selectedRequest.price_tax_rate}%` : '未税价' }}</dd></div>
              <div><dt class="text-xs text-gray-500">交付条件</dt><dd class="mt-1 text-sm leading-5">{{ selectedRequest.price_delivery_terms || '-' }}</dd></div>
              <div><dt class="text-xs text-gray-500">质保条件</dt><dd class="mt-1 text-sm leading-5">{{ selectedRequest.price_warranty_terms || '-' }}</dd></div>
              <div><dt class="text-xs text-gray-500">开票条件</dt><dd class="mt-1 text-sm leading-5">{{ selectedRequest.price_invoice_condition || '-' }}</dd></div>
            </dl>
            <div class="mt-4 overflow-x-auto rounded-md border border-gray-200 bg-white">
              <table class="min-w-[820px] w-full text-sm">
                <thead class="bg-gray-100 text-left text-xs text-gray-500"><tr><th class="px-3 py-2.5">期次</th><th class="px-3 py-2.5">付款阶段</th><th class="px-3 py-2.5 text-right">比例</th><th class="px-3 py-2.5 text-right">金额</th><th class="px-3 py-2.5">计划日期</th><th class="px-3 py-2.5">触发条件</th><th class="px-3 py-2.5">发票条件</th><th class="px-3 py-2.5">状态</th></tr></thead>
                <tbody class="divide-y divide-gray-100"><tr v-for="row in selectedRequest.payment_plan || []" :key="row.name || row.installment_no"><td class="px-3 py-3 font-medium">{{ row.installment_name }}</td><td class="px-3 py-3">{{ row.payment_stage }}</td><td class="px-3 py-3 text-right tabular-nums">{{ row.percentage }}%</td><td class="px-3 py-3 text-right tabular-nums">¥ {{ formatMoney(row.amount) }}</td><td class="px-3 py-3">{{ row.planned_date || '-' }}</td><td class="px-3 py-3">{{ row.trigger_condition }}</td><td class="px-3 py-3">{{ row.invoice_requirement }}</td><td class="px-3 py-3"><span class="rounded-full bg-gray-100 px-2 py-1 text-xs">{{ row.status }}</span></td></tr></tbody>
              </table>
            </div>
          </section>

          <section v-if="!isPriceInnerPage && (selectedCanApprove || selectedCanReject) && !isPriceApprovalStep(selectedRequest)" class="z-20 border-t border-gray-300 bg-white px-5 py-4 shadow-[0_-8px_24px_rgba(15,23,42,0.08)] xl:sticky xl:top-3 lg:px-7">
            <div class="mb-4"><h3 class="text-sm font-semibold text-gray-900">{{ approvalStageMeta(selectedRequest).action }}</h3><p class="mt-1 text-xs text-gray-600">{{ approvalStageMeta(selectedRequest).description }} · 当前节点：{{ currentStep?.label }}</p></div>
            <div v-if="selectedCanApprove" class="border-b border-amber-200 pb-5">
              <label class="block text-xs font-medium text-gray-700">审批意见（可选）<textarea v-model="actionNote" rows="3" class="mt-2 w-full rounded-md border-gray-300 bg-white px-3 py-2 text-sm" placeholder="填写审批意见"></textarea></label>
              <button type="button" class="mt-3 inline-flex h-10 min-w-[160px] items-center justify-center gap-2 rounded-md bg-[#15803d] px-5 text-sm font-semibold text-white shadow-sm hover:bg-[#166534] disabled:cursor-not-allowed disabled:opacity-50" :disabled="saving" @click="act('approve')"><FeatherIcon name="check-circle" class="h-4 w-4" />{{ approvalButtonLabel(selectedRequest) }}</button>
            </div>
            <div v-if="selectedCanReject" class="pt-5">
              <p class="mb-3 text-xs font-medium text-red-800">定向驳回</p>
              <div class="grid gap-2 md:grid-cols-[180px_minmax(220px,1fr)_auto]">
                <select v-model="rejectTarget" class="h-10 rounded-md border-gray-300 bg-white py-1.5 text-sm"><option v-for="target in selectedRequest.rejection_targets || []" :key="target.target" :value="target.target">{{ target.label }}</option></select>
                <input v-model="rejectReason" class="h-10 rounded-md border-gray-300 bg-white px-3 text-sm" placeholder="驳回原因（必填）" />
                <button type="button" class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-red-300 bg-white px-4 text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50" :disabled="saving" @click="act('reject')"><FeatherIcon name="corner-up-left" class="h-4 w-4" />定向驳回</button>
              </div>
            </div>
          </section>
          <section v-if="!isInnerPage" class="grid border-b border-gray-200 lg:grid-cols-2">
            <div v-if="isPayment && selectedRequest.po_fulfillment_records?.length" class="border-b border-gray-200 px-5 py-5 lg:col-span-2 lg:px-6">
              <div class="mb-4 flex items-center gap-2"><FeatherIcon name="clipboard" class="h-4 w-4 text-gray-500" /><h3 class="text-sm font-semibold text-gray-900">来源 PO 到货与验收资料</h3></div>
              <div class="divide-y divide-gray-100 border-y border-gray-100">
                <a v-for="record in selectedRequest.po_fulfillment_records" :key="record.name" :href="record.evidence_file" target="_blank" rel="noopener" class="grid gap-2 py-3 text-sm hover:text-blue-700 md:grid-cols-[80px_120px_minmax(0,1fr)_220px]">
                  <span class="font-medium">{{ record.record_type }}</span><span>{{ record.record_date }}</span><span>{{ record.recorded_by }}</span><span class="truncate">{{ record.original_filename }}</span>
                </a>
              </div>
            </div>
            <div class="border-b border-gray-200 px-5 py-5 lg:border-b-0 lg:border-r lg:px-6">
              <div class="mb-4 flex items-center justify-between gap-3">
                <div class="flex items-center gap-2"><FeatherIcon name="paperclip" class="h-4 w-4 text-gray-500" /><h3 class="text-sm font-semibold text-gray-900">业务资料</h3></div>
                <span class="text-xs text-gray-500">{{ documents.length }} 份</span>
              </div>
              <div v-if="documents.length" class="divide-y divide-gray-100 border-y border-gray-100">
                <div v-for="doc in documents" :key="doc.name" class="flex items-center gap-3 py-3 text-sm" :class="doc.status === '已作废' ? 'opacity-50' : ''">
                  <span class="flex h-8 w-8 items-center justify-center rounded-md bg-gray-100 text-gray-500"><FeatherIcon name="file" class="h-4 w-4" /></span>
                  <a :href="doc.file" target="_blank" rel="noopener" class="min-w-0 flex-1 hover:text-blue-700">
                    <span class="block truncate font-medium" :class="doc.status === '已作废' ? 'line-through' : ''">{{ doc.original_filename }}</span>
                    <span class="text-xs text-gray-500">{{ doc.document_type }} · v{{ doc.version_no }}<template v-if="doc.status === '已作废'"> · 已作废</template></span>
                  </a>
                  <button v-if="doc.status !== '已作废'" type="button" class="rounded-md p-2 text-gray-500 hover:bg-red-50 hover:text-red-700" title="删除或作废资料" @click="removeDocument(doc)"><FeatherIcon name="trash-2" class="h-4 w-4" /></button>
                  <FeatherIcon name="external-link" class="h-4 w-4 text-gray-400" />
                </div>
              </div>
              <p v-else class="py-4 text-sm text-gray-400">暂无已归档资料</p>
              <div class="mb-4 border-y border-gray-100">
                <div v-for="item in documentChecklist" :key="item.key" class="border-b border-gray-100 py-3 last:border-b-0">
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0"><p class="text-sm font-medium text-gray-900">{{ item.label }}</p><p class="mt-1 text-xs leading-5 text-gray-500">{{ item.description }}</p></div>
                    <span class="shrink-0 rounded-full px-2 py-1 text-xs font-medium" :class="item.satisfied ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'">{{ item.satisfied ? '已满足' : '待补资料' }}</span>
                  </div>
                  <p v-if="item.matchedTypes?.length" class="mt-2 text-xs text-gray-500">已归档：{{ item.matchedTypes.join('、') }}</p>
                  <div v-if="!item.satisfied && item.uploadTypes?.length" class="mt-2 flex flex-wrap gap-2">
                    <button v-for="type in item.uploadTypes" :key="type" type="button" class="inline-flex h-8 items-center gap-1 rounded-md border border-gray-300 px-2.5 text-xs font-medium text-gray-700 hover:bg-gray-50" :disabled="uploading || !activeRequestName" @click="pickDocument(type)"><FeatherIcon name="upload-cloud" class="h-3.5 w-3.5" />上传{{ type }}</button>
                  </div>
                </div>
              </div>
              <div class="flex flex-wrap items-center justify-between gap-3">
                <p class="text-xs text-gray-500">当前节点缺少 {{ missingDocumentCount }} 项；资料可在审批后补交；到货、验收、付款、退款回单和关闭节点会再次校验。</p>
                <button type="button" class="inline-flex h-9 items-center gap-2 rounded-md border border-gray-300 px-3 text-sm font-medium text-gray-700 hover:bg-gray-50" :disabled="uploading || !activeRequestName" @click="pickDocument('其他补充资料')"><FeatherIcon name="plus" class="h-4 w-4" />上传补充资料</button>
              </div>
              <input ref="uploadInput" type="file" class="hidden" :disabled="uploading || !activeRequestName" @change="uploadDocument" />
            </div>

            <div class="px-5 py-5 lg:px-6">
              <div class="mb-4 flex items-center gap-2"><FeatherIcon name="git-commit" class="h-4 w-4 text-gray-500" /><h3 class="text-sm font-semibold text-gray-900">审批轨迹</h3></div>
              <ol class="space-y-0">
                <li v-for="row in selectedRequest.steps || []" :key="row.step_key" class="relative flex gap-3 pb-4 last:pb-0">
                  <span class="absolute bottom-0 left-[13px] top-7 w-px bg-gray-200 last:hidden"></span>
                  <span class="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border" :class="stepTone(row.status)"><FeatherIcon :name="stepIcon(row.status)" class="h-3.5 w-3.5" /></span>
                  <div class="min-w-0 flex-1 pt-0.5">
                    <div class="flex items-start justify-between gap-3"><p class="text-sm font-medium text-gray-900">{{ row.step_index }}. {{ row.label }}</p><span class="shrink-0 text-xs text-gray-500">{{ row.status }}</span></div>
                    <p v-if="row.action_by || row.acted_on" class="mt-1 text-xs text-gray-500">{{ row.action_by || '-' }} · {{ formatDateTime(row.acted_on) }}</p>
                    <p v-if="row.note" class="mt-1 text-xs leading-5 text-gray-600">意见：{{ row.note }}</p>
                  </div>
                </li>
              </ol>
            </div>
          </section>

          <section v-if="!isInnerPage && selectedRequest.operation_log?.length" class="border-b border-gray-200 px-5 py-5 lg:px-6">
            <div class="mb-3 flex items-center gap-2"><FeatherIcon name="activity" class="h-4 w-4 text-gray-500" /><h3 class="text-sm font-semibold text-gray-900">操作记录</h3></div>
            <div class="divide-y divide-gray-100 border-y border-gray-100">
              <div v-for="(event, index) in [...selectedRequest.operation_log].reverse()" :key="index" class="grid gap-1 py-3 text-sm md:grid-cols-[180px_1fr_auto]">
                <span class="font-medium text-gray-900">{{ event.action }}</span><span class="text-gray-600">{{ event.actor }}<span v-if="event.note"> · {{ event.note }}</span></span><span class="text-xs text-gray-400">{{ formatDateTime(event.acted_on) }}</span>
              </div>
            </div>
          </section>

          <section v-if="!isInnerPage && isProcurement && isPriceApprovalStep(selectedRequest) && (selectedCanApprove || selectedCanReject)" class="z-20 border-t border-blue-200 bg-blue-50 px-5 py-4 shadow-[0_-8px_24px_rgba(15,23,42,0.08)] xl:sticky xl:top-3 lg:px-7">
            <div class="flex flex-wrap items-center justify-between gap-4">
              <div><h3 class="text-sm font-semibold text-gray-900">价格审批待处理</h3><p class="mt-1 text-xs leading-5 text-gray-600">请先进入价格审批单，核对供应商、物品价格、付款方式和每期付款计划后再决定。</p></div>
              <router-link :to="procurementChainRoute(selectedRequest)" class="inline-flex h-10 items-center gap-2 rounded-md bg-blue-700 px-5 text-sm font-semibold text-white hover:bg-blue-800"><FeatherIcon name="arrow-right" class="h-4 w-4" />进入价格审批单</router-link>
            </div>
          </section>

          <section v-if="isPriceInnerPage && showQuoteForm" class="border-b border-gray-200 bg-white px-5 py-6 lg:px-7">
            <div class="mb-6 flex flex-wrap items-start justify-between gap-4">
              <div><p class="text-xs font-semibold text-blue-700">采购经办填写</p><h3 class="mt-1 text-lg font-semibold text-gray-900">{{ selectedRequest.workflow_status === '已完成' ? '变更价格审批表' : '填写价格审批表' }}</h3><p class="mt-1 text-sm text-gray-500">录入供应商商业条件和付款计划，提交副总经理审批。</p></div>
              <div class="border-l-2 border-gray-900 pl-4 text-right"><p class="text-xs text-gray-500">当前总价</p><p class="mt-1 text-2xl font-semibold tabular-nums text-gray-900">¥ {{ formatMoney(quoteTotal) }}</p></div>
            </div>
            <div class="grid gap-4 md:grid-cols-3">
              <label class="text-sm md:col-span-2">供应商<input v-model="quoteForm.supplier" class="mt-1 w-full rounded-md border-gray-300 bg-white px-3 py-2" maxlength="140" /></label>
              <div class="grid grid-cols-[1fr_120px] gap-2">
                <label class="text-sm">计价方式<select v-model.number="quoteForm.tax_included" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"><option :value="1">含税价</option><option :value="0">未税价</option></select></label>
                <label class="text-sm">税率<input v-model.number="quoteForm.tax_rate" type="number" min="0" max="100" step="0.01" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
              </div>
            </div>
            <div class="mt-5 overflow-x-auto border-y border-gray-200">
              <table class="min-w-[760px] w-full text-sm"><thead class="bg-gray-50 text-left text-xs text-gray-500"><tr><th class="p-3">物品</th><th class="p-3">规格</th><th class="p-3 text-right">数量</th><th class="p-3">单位</th><th class="p-3 text-right">单价</th><th class="p-3">备注</th></tr></thead><tbody class="divide-y divide-gray-100"><tr v-for="(line, index) in quoteForm.business_lines" :key="index"><td class="p-3"><input v-model="line.item_name" class="w-40 rounded-md border-gray-300 px-2 py-1.5" /></td><td class="p-3"><input v-model="line.specification" class="w-32 rounded-md border-gray-300 px-2 py-1.5" /></td><td class="p-3"><input v-model.number="line.quantity" type="number" min="0.0001" step="0.0001" class="w-24 rounded-md border-gray-300 px-2 py-1.5 text-right" /></td><td class="p-3"><input v-model="line.unit" class="w-20 rounded-md border-gray-300 px-2 py-1.5" /></td><td class="p-3"><input v-model.number="line.unit_price" type="number" min="0.01" step="0.01" class="w-28 rounded-md border-gray-300 px-2 py-1.5 text-right" /></td><td class="p-3"><input v-model="line.remarks" class="w-40 rounded-md border-gray-300 px-2 py-1.5" /></td></tr></tbody></table>
            </div>
            <div class="mt-5 grid gap-4 md:grid-cols-3">
              <label class="text-sm">交付条件<textarea v-model="quoteForm.delivery_terms" rows="3" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" placeholder="交付期限、地点、运输等"></textarea></label>
              <label class="text-sm">质保条件<textarea v-model="quoteForm.warranty_terms" rows="3" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" placeholder="质保期限和范围"></textarea></label>
              <label class="text-sm">开票条件<textarea v-model="quoteForm.invoice_condition" rows="3" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" placeholder="票种、税率、开票节点"></textarea></label>
            </div>
            <div class="mt-6">
              <div class="mb-3 flex items-center justify-between"><div><h4 class="text-sm font-semibold text-gray-900">付款计划</h4><p class="mt-1 text-xs text-gray-500">比例与金额必须分别等于 100% 和审批总额</p></div><button type="button" class="inline-flex h-8 items-center gap-2 rounded-md border border-gray-300 px-3 text-sm" @click="addInstallment"><FeatherIcon name="plus" class="h-4 w-4" />添加期次</button></div>
              <div class="overflow-x-auto border-y border-gray-200">
                <table class="min-w-[1080px] w-full text-sm"><thead class="bg-gray-50 text-left text-xs text-gray-500"><tr><th class="p-3">期次</th><th class="p-3">付款阶段</th><th class="p-3">比例%</th><th class="p-3">金额</th><th class="p-3">计划日期</th><th class="p-3">触发条件</th><th class="p-3">发票条件</th><th class="w-12"></th></tr></thead><tbody class="divide-y divide-gray-100"><tr v-for="(row, index) in quoteForm.payment_plan" :key="index"><td class="p-3"><input v-model="row.installment_name" class="w-24 rounded-md border-gray-300 px-2 py-1.5" /></td><td class="p-3"><select v-model="row.payment_stage" class="w-32 rounded-md border-gray-300 py-1.5"><option>预付款</option><option>到货款</option><option>尾款</option><option>到货后全额付款</option></select></td><td class="p-3"><input v-model.number="row.percentage" type="number" min="0.0001" max="100" step="0.01" class="w-24 rounded-md border-gray-300 px-2 py-1.5 text-right" /></td><td class="p-3"><input v-model.number="row.amount" type="number" min="0.01" step="0.01" class="w-28 rounded-md border-gray-300 px-2 py-1.5 text-right" /></td><td class="p-3"><input v-model="row.planned_date" type="date" class="w-36 rounded-md border-gray-300 px-2 py-1.5" /></td><td class="p-3"><input v-model="row.trigger_condition" class="w-48 rounded-md border-gray-300 px-2 py-1.5" /></td><td class="p-3"><select v-model="row.invoice_requirement" class="w-32 rounded-md border-gray-300 py-1.5"><option>付款前提供</option><option>付款后提供</option><option>无需发票</option></select></td><td><button type="button" class="rounded-md p-2 text-red-600 hover:bg-red-50" title="删除期次" @click="removeInstallment(index)"><FeatherIcon name="trash-2" class="h-4 w-4" /></button></td></tr></tbody><tfoot class="border-t border-gray-200 bg-gray-50"><tr><td colspan="2" class="p-3 text-right text-xs font-medium text-gray-500">合计</td><td class="p-3 text-right font-semibold">{{ quotePlanTotals.percentage.toFixed(2) }}%</td><td class="p-3 text-right font-semibold">¥ {{ formatMoney(quotePlanTotals.amount) }}</td><td colspan="4"></td></tr></tfoot></table>
              </div>
            </div>
            <label v-if="selectedRequest.workflow_status === '已完成'" class="mt-4 block text-sm">商业条件修改原因<textarea v-model="quoteForm.change_reason" rows="2" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"></textarea></label>
            <div class="mt-5 flex justify-end"><button type="button" class="inline-flex h-10 items-center gap-2 rounded-md bg-[#1d4ed8] px-5 text-sm font-semibold text-white hover:bg-[#1e40af] disabled:opacity-50" :disabled="saving" @click="submitQuote"><FeatherIcon name="send" class="h-4 w-4" />提交价格审批</button></div>
          </section>

          <section v-else-if="isPriceInnerPage && selectedRequest.price_revision" class="border-b border-gray-200 bg-white">
            <div class="grid border-b border-gray-200 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div class="px-5 py-6 lg:px-7">
                <div class="flex flex-wrap items-center gap-2"><span class="rounded-md bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700">价格审批表 V{{ selectedRequest.price_revision }}</span><span class="text-xs text-gray-500">商业条件审批</span></div>
                <h3 class="mt-4 text-xl font-semibold text-gray-900">{{ selectedRequest.supplier || '未填写供应商' }}</h3>
                <p class="mt-2 text-sm text-gray-500">采购内容、价格条件与付款计划以本版本为准</p>
              </div>
              <div class="flex flex-col justify-center bg-gray-900 px-5 py-6 text-white lg:px-6">
                <p class="text-xs text-gray-400">审批总额</p>
                <p class="mt-2 text-3xl font-semibold tabular-nums">¥ {{ formatMoney(selectedRequest.amount) }}</p>
                <p class="mt-2 text-xs text-gray-400">{{ selectedRequest.price_tax_included ? `含税价 · 税率 ${selectedRequest.price_tax_rate}%` : '未税价' }}</p>
              </div>
            </div>

            <div class="px-5 py-6 lg:px-7">
              <div class="mb-3 flex items-end justify-between gap-3"><div><h4 class="text-sm font-semibold text-gray-900">采购报价明细</h4><p class="mt-1 text-xs text-gray-500">{{ selectedRequest.business_lines?.length || 0 }} 项 · 合计数量 {{ selectedTotalQuantity }}</p></div><span class="text-xs text-gray-400">版本 V{{ selectedRequest.price_revision }}</span></div>
              <div class="overflow-x-auto border-y border-gray-200">
                <table class="min-w-[760px] w-full text-sm">
                  <thead class="bg-gray-50 text-left text-xs font-medium text-gray-500"><tr><th class="px-3 py-3">物品名称</th><th class="px-3 py-3">规格</th><th class="px-3 py-3 text-right">数量</th><th class="px-3 py-3">单位</th><th class="px-3 py-3 text-right">单价</th><th class="px-3 py-3 text-right">金额</th><th class="px-3 py-3">备注</th></tr></thead>
                  <tbody class="divide-y divide-gray-100"><tr v-for="(line, index) in selectedRequest.business_lines || []" :key="index"><td class="px-3 py-3.5 font-semibold text-gray-900">{{ line.item_name || '-' }}</td><td class="px-3 py-3.5 text-gray-600">{{ line.specification || '-' }}</td><td class="px-3 py-3.5 text-right tabular-nums">{{ line.quantity || 0 }}</td><td class="px-3 py-3.5 text-gray-600">{{ line.unit || '-' }}</td><td class="px-3 py-3.5 text-right tabular-nums">¥ {{ formatMoney(line.unit_price) }}</td><td class="px-3 py-3.5 text-right font-semibold tabular-nums">¥ {{ formatMoney(Number(line.quantity || 0) * Number(line.unit_price || 0)) }}</td><td class="px-3 py-3.5 text-gray-600">{{ line.remarks || '-' }}</td></tr></tbody>
                </table>
              </div>
            </div>

            <dl class="grid border-y border-gray-200 bg-gray-50 md:grid-cols-3">
              <div class="border-b border-gray-200 px-5 py-5 md:border-b-0 md:border-r lg:px-7"><dt class="text-xs font-medium text-gray-500">交付条件</dt><dd class="mt-2 text-sm leading-6 text-gray-900">{{ selectedRequest.price_delivery_terms || '-' }}</dd></div>
              <div class="border-b border-gray-200 px-5 py-5 md:border-b-0 md:border-r lg:px-7"><dt class="text-xs font-medium text-gray-500">质保条件</dt><dd class="mt-2 text-sm leading-6 text-gray-900">{{ selectedRequest.price_warranty_terms || '-' }}</dd></div>
              <div class="px-5 py-5 lg:px-7"><dt class="text-xs font-medium text-gray-500">开票条件</dt><dd class="mt-2 text-sm leading-6 text-gray-900">{{ selectedRequest.price_invoice_condition || '-' }}</dd></div>
            </dl>

            <div class="px-5 py-6 lg:px-7">
              <div class="mb-3"><h4 class="text-sm font-semibold text-gray-900">付款计划</h4><p class="mt-1 text-xs text-gray-500">付款阶段、比例、触发条件与发票要求</p></div>
              <div class="overflow-x-auto border-y border-gray-200">
                <table class="min-w-[1080px] w-full text-sm"><thead class="bg-gray-50 text-left text-xs font-medium text-gray-500"><tr><th class="px-3 py-3">期次</th><th class="px-3 py-3">付款阶段</th><th class="px-3 py-3 text-right">比例</th><th class="px-3 py-3 text-right">金额</th><th class="px-3 py-3">计划日期</th><th class="px-3 py-3">触发条件</th><th class="px-3 py-3">发票要求</th><th class="px-3 py-3">下推状态</th><th class="px-3 py-3">付款单</th></tr></thead><tbody class="divide-y divide-gray-100"><tr v-for="row in selectedRequest.payment_plan || []" :key="row.name || row.installment_no"><td class="px-3 py-3.5 font-semibold text-gray-900">{{ row.installment_name }}</td><td class="px-3 py-3.5"><span class="rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-700">{{ row.payment_stage }}</span></td><td class="px-3 py-3.5 text-right font-semibold tabular-nums">{{ row.percentage }}%</td><td class="px-3 py-3.5 text-right font-semibold tabular-nums">¥ {{ formatMoney(row.amount) }}</td><td class="px-3 py-3.5 text-gray-600">{{ row.planned_date || '-' }}</td><td class="px-3 py-3.5 text-gray-600">{{ row.trigger_condition }}</td><td class="px-3 py-3.5 text-gray-600">{{ row.invoice_requirement }}</td><td class="px-3 py-3.5"><span class="rounded-md px-2 py-1 text-xs font-medium" :class="row.status === '已下推' || row.status === '已付款' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'">{{ row.status || '待生成' }}</span></td><td class="px-3 py-3.5"><router-link v-if="row.payment_request" :to="{ path: '/approval/procurement-payment', query: { request: row.payment_request } }" class="font-medium text-blue-700 hover:text-blue-900">{{ row.payment_request }}</router-link><span v-else class="text-gray-400">等待触发条件</span></td></tr></tbody></table>
              </div>
            </div>
          </section>

          <section v-if="isPriceInnerPage && (selectedCanApprove || selectedCanReject) && String(currentStep?.label || '').includes('价格')" class="z-20 border-t border-gray-300 bg-white px-5 py-4 shadow-[0_-8px_24px_rgba(15,23,42,0.08)] xl:sticky xl:top-3 lg:px-7">
            <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
              <div><div class="flex items-center gap-2"><span class="flex h-7 w-7 items-center justify-center rounded-md bg-blue-50 text-blue-700"><FeatherIcon name="check-square" class="h-3.5 w-3.5" /></span><div><h3 class="text-sm font-semibold text-gray-900">价格审批决策</h3><p class="text-xs text-gray-500">{{ currentStep?.label }}</p></div></div><label v-if="selectedCanApprove" class="mt-3 block text-xs font-medium text-gray-600">审批意见（可选）<textarea v-model="actionNote" rows="2" class="mt-1.5 w-full rounded-md border-gray-300 bg-white px-3 py-2 text-sm" placeholder="填写审批意见"></textarea></label></div>
              <button v-if="selectedCanApprove" type="button" class="inline-flex h-11 min-w-[180px] items-center justify-center gap-2 rounded-md bg-[#15803d] px-5 text-sm font-semibold text-white hover:bg-[#166534] disabled:opacity-50" :disabled="saving" @click="act('approve')"><FeatherIcon name="check-circle" class="h-4 w-4" />价格审批通过</button>
            </div>
            <div v-if="selectedCanReject" class="mt-4 grid gap-2 border-t border-gray-200 pt-4 md:grid-cols-[180px_minmax(220px,1fr)_auto]"><select v-model="rejectTarget" class="h-10 rounded-md border-gray-300 bg-white py-1.5 text-sm"><option v-for="target in selectedRequest.rejection_targets || []" :key="target.target" :value="target.target">{{ target.label }}</option></select><input v-model="rejectReason" class="h-10 rounded-md border-gray-300 bg-white px-3 text-sm" placeholder="驳回原因（必填）" /><button type="button" class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-red-300 bg-white px-4 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50" :disabled="saving" @click="act('reject')"><FeatherIcon name="corner-up-left" class="h-4 w-4" />定向驳回</button></div>
          </section>

          <section v-if="isContractInnerPage" class="border-b border-gray-200 px-5 py-6 lg:px-6">
            <div class="mb-5 flex flex-wrap items-center justify-between gap-3"><div><p class="text-xs font-medium text-emerald-700">合同阶段</p><h3 class="mt-1 text-base font-semibold text-gray-900">PO 采购订单</h3></div><span class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">{{ selectedRequest.contract_status || '待补充信息' }}</span></div>
            <div v-if="showContractForm" class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <label class="text-sm">供应商法定名称<input v-model="contractForm.supplier_legal_name" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
              <label class="text-sm">统一社会信用代码<input v-model="contractForm.credit_code" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
              <label class="text-sm">合同联系人<input v-model="contractForm.contract_contact" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
              <label class="text-sm md:col-span-2">供应商地址<input v-model="contractForm.supplier_address" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
              <label class="text-sm">合同交付日期<input v-model="contractForm.contract_delivery_date" type="date" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
              <label class="text-sm">收款银行<input v-model="contractForm.contract_bank_name" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
              <label class="text-sm">收款账号<input v-model="contractForm.contract_bank_account" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
              <label class="text-sm">我方签约主体<input v-model="contractForm.contract_entity" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
              <label class="text-sm">合同模板<input v-model="contractForm.contract_template" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
              <label class="text-sm">用印账号<select v-model="contractForm.seal_user" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"><option value="">请选择</option><option v-for="employee in applicants.filter((item) => item.user)" :key="employee.user" :value="employee.user">{{ employee.employee_name }} · {{ employee.user }}</option></select></label>
              <div class="flex items-end"><button type="button" class="h-10 rounded-md bg-gray-900 px-5 text-sm font-semibold text-white disabled:opacity-50" :disabled="saving" @click="saveContractInformation">保存并生成合同草稿</button></div>
            </div>
            <div v-if="selectedRequest.contract_draft_content" class="mt-5 rounded-md border border-gray-200 bg-gray-50 p-4"><div class="mb-3 flex items-center justify-between"><h4 class="text-sm font-semibold">合同草稿 V{{ selectedRequest.contract_version }}</h4><span class="text-xs text-gray-500">商业条件已锁定</span></div><pre class="max-h-80 overflow-auto whitespace-pre-wrap font-sans text-sm leading-6 text-gray-700">{{ selectedRequest.contract_draft_content }}</pre></div>
            <div v-if="showContractReview || showContractSeal" class="mt-4 flex flex-wrap justify-end gap-3">
              <button v-if="showContractReview" type="button" class="inline-flex h-10 items-center gap-2 rounded-md bg-[#15803d] px-5 text-sm font-semibold text-white" @click="reviewContract"><FeatherIcon name="check-circle" class="h-4 w-4" />采购复核无误</button>
              <button v-if="showContractSeal" type="button" class="inline-flex h-10 items-center gap-2 rounded-md bg-gray-900 px-5 text-sm font-semibold text-white" @click="sealContract"><FeatherIcon name="award" class="h-4 w-4" />确认电子用印</button>
            </div>
          </section>

          <section v-if="(isContractInnerPage && showContractRegistration) || (!isInnerPage && isProcurementOrPayment && ((isPayment && selectedRequest.workflow_status === '已付款') || (isProcurement && selectedRequest.workflow_status === '已完成')))" class="space-y-4 px-5 py-5 lg:px-6">
            <div v-if="isContractInnerPage && showContractRegistration"><h3 class="mb-3 text-sm font-semibold text-gray-900">合同交期</h3><div class="grid gap-2 md:grid-cols-[180px_1fr_auto]"><input v-model="contractDate" type="date" class="rounded-md border-gray-300 px-3 py-2 text-sm" /><input v-model="contractReason" class="rounded-md border-gray-300 px-3 py-2 text-sm" placeholder="延期时必须填写原因" /><button class="rounded-md bg-gray-900 px-4 py-2 text-sm text-white" @click="registerContract">登记合同交期</button></div></div>
            <div v-if="!isInnerPage && isProcurementOrPayment && ((isPayment && selectedRequest.workflow_status === '已付款') || (isProcurement && selectedRequest.workflow_status === '已完成'))" class="space-y-3 border-t border-gray-200 pt-4">
              <div v-if="selectedRequest.request_type === '采购申请'" class="text-sm text-gray-700">到货、验收及付款请查看上方物料执行进度，各批次分别跟踪。</div>
              <div v-else class="text-sm text-gray-700">到货 {{ selectedRequest.received_quantity }}/{{ selectedRequest.ordered_quantity }} · {{ selectedRequest.arrival_status }} · {{ selectedRequest.inspection_status }}</div>
              <div v-if="showArrival" class="flex flex-wrap gap-2"><input v-model.number="arrivalQuantity" type="number" class="w-28 rounded-md border-gray-300 px-3 py-2 text-sm" placeholder="到货数量" /><input v-model="arrivalDate" type="date" class="rounded-md border-gray-300 px-3 py-2 text-sm" /><button class="rounded-md bg-gray-900 px-3 py-2 text-sm text-white" @click="recordArrival">登记到货</button></div>
              <div v-if="showInspection" class="grid gap-2 md:grid-cols-4"><select v-model="inspectionOutcome" class="rounded-md border-gray-300 px-3 py-2"><option>通过</option><option>不合格</option></select><select v-if="inspectionOutcome === '不合格'" v-model="inspectionDirection" class="rounded-md border-gray-300 px-3 py-2"><option>退货</option><option>换货</option></select><input v-model="inspectionReason" class="rounded-md border-gray-300 px-3 py-2" placeholder="验收说明/不合格原因" /><button class="rounded-md bg-gray-900 px-3 py-2 text-white" @click="recordInspection">登记验收</button></div>
              <div v-if="selectedRequest.payment_stage === '预付款'" class="grid gap-2 md:grid-cols-3"><select v-model="followupStatus" class="rounded-md border-gray-300 px-3 py-2"><option>催办中</option><option>供应商退款中</option><option>退货中</option><option>换货中</option></select><input v-model="followupReason" class="rounded-md border-gray-300 px-3 py-2" placeholder="异常跟进说明" /><button class="rounded-md border border-gray-300 px-3 py-2" @click="recordFollowup">记录跟进</button></div>
              <div class="flex flex-wrap gap-2"><button v-if="showRefundCompletion" class="rounded-md bg-blue-700 px-3 py-2 text-white" @click="completeRefund">确认供应商退款</button><button v-if="showWriteoff" class="rounded-md bg-blue-700 px-3 py-2 text-white" @click="writeoff">预付款核销</button><button v-if="showClose" class="rounded-md bg-gray-900 px-3 py-2 text-white" @click="closeOrder">关闭采购</button></div>
            </div>
          </section>
        </article>

        <div v-else class="order-1 flex min-h-[500px] items-center justify-center p-8 text-center text-sm text-gray-400">
          <div><FeatherIcon name="file-text" class="mx-auto mb-3 h-6 w-6" /><p>选择左侧单据查看完整申请内容</p></div>
        </div>
      </div>
    </section>

    <section v-if="isMissingInnerRequest" class="rounded-lg border border-red-200 bg-red-50 px-6 py-12 text-center">
      <FeatherIcon name="file-minus" class="mx-auto mb-3 h-8 w-8 text-red-400" />
      <h2 class="text-base font-semibold text-red-900">采购申请不存在或已被删除</h2>
      <p class="mt-1 text-sm text-red-700">请返回采购审批队列后重新选择有效单据。</p>
      <router-link to="/approval/procurement" class="mt-5 inline-flex h-9 items-center gap-2 rounded-md bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800"><FeatherIcon name="arrow-left" class="h-4 w-4" />返回采购审批</router-link>
    </section>
    <section v-else-if="isUnauthorizedPmcEdit" class="rounded-lg border border-amber-200 bg-amber-50 px-6 py-12 text-center">
      <FeatherIcon name="lock" class="mx-auto mb-3 h-8 w-8 text-amber-600" />
      <h2 class="text-base font-semibold text-amber-950">当前账号无 PMC 编辑权限</h2>
      <p class="mt-1 text-sm text-amber-800">只有动态指定的 PMC 账号，且申请处于 PMC 节点时，才能补充或修改物料。</p>
      <router-link :to="{ path: '/approval/procurement', query: { request: route.params.name } }" class="mt-5 inline-flex h-9 items-center gap-2 rounded-md bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800"><FeatherIcon name="arrow-left" class="h-4 w-4" />返回采购主单</router-link>
    </section>
    <template v-if="!isMissingInnerRequest && !isUnauthorizedPmcEdit">
    <section v-if="!isPayment && (showCreateForm || isNewRequestPage || isPmcEditPage) && !isPriceInnerPage && !isContractInnerPage" class="request-form overflow-hidden rounded-lg border border-gray-200 bg-white">
      <div class="border-b border-gray-200 bg-gray-50/70 px-5 py-3 lg:px-6" :class="pmcEditMode ? 'sticky top-0 z-30 shadow-sm' : ''"><div class="flex flex-wrap items-center justify-between gap-3"><div><div class="flex flex-wrap items-center gap-2"><h2 class="text-base font-semibold text-gray-900">{{ pmcEditMode ? 'PMC补充/修改采购申请' : (draftName ? '编辑申请' : (isDirectPurchase ? '新建购买申请' : '新建采购申请')) }}</h2><span v-if="pmcEditMode" class="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">仅 PMC 可编辑</span></div><p v-if="pmcEditMode" class="mt-1 text-xs text-amber-800">可补充物料编号及修改申请资料；物料流水号由系统生成且不可修改。</p></div><div class="flex items-center gap-2"><span v-if="draftName" class="rounded-md bg-white px-3 py-1 text-xs font-medium text-gray-600 shadow-sm">{{ draftName }}</span><template v-if="pmcEditMode"><button type="button" class="inline-flex h-9 items-center gap-2 rounded-md border border-gray-300 bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50" :disabled="saving" @click="pmcEditMode = false; closeRequestForm()"><FeatherIcon name="x" class="h-4 w-4" />取消</button><button type="button" class="inline-flex h-9 items-center gap-2 rounded-md bg-amber-700 px-3 text-sm font-semibold text-white shadow-sm hover:bg-amber-800 disabled:opacity-50" :disabled="saving" @click="savePmcModification"><FeatherIcon name="save" class="h-4 w-4" />保存修改</button></template></div></div></div>
      <div class="grid gap-x-4 gap-y-3 px-5 py-4 md:grid-cols-2 xl:grid-cols-4 lg:px-6">
        <label class="text-xs font-medium text-gray-700">主题<input v-model="form.subject" class="mt-1 w-full rounded-md border-gray-300 px-3 py-1.5 text-sm" maxlength="140" /></label>
        <label class="text-xs font-medium text-gray-700">紧急程度<select v-model="form.urgency" class="mt-1 w-full rounded-md border-gray-300 px-3 py-1.5 text-sm"><option>一般</option><option>加急</option></select></label>
        <label v-if="isProcurement || isDirectPurchase" class="text-xs font-medium text-gray-700">资产属性<select v-model="form.asset_nature" class="mt-1 w-full rounded-md border-gray-300 px-3 py-1.5 text-sm"><option>非固定资产</option><option>固定资产</option></select></label>
        <label v-if="isDirectPurchase && form.asset_nature === '固定资产'" class="text-xs font-medium text-gray-700">固定资产类别<select v-model="form.fixed_asset_category" class="mt-1 w-full rounded-md border-gray-300 px-3 py-1.5 text-sm"><option value="">请选择</option><option v-for="item in fixedCategories" :key="item">{{ item }}</option></select></label>
        <label v-if="!isPayment" class="text-xs font-medium text-gray-700">预计交期<input v-model="form.expected_delivery_date" type="date" class="mt-1 w-full rounded-md border-gray-300 px-3 py-1.5 text-sm" /></label>
        <label v-if="isProcurement && canSubmitForOthers" class="text-sm">申请人<select v-model="form.applicant_employee" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"><option v-for="employee in applicants" :key="employee.name" :value="employee.name">{{ employee.employee_name }} · {{ employee.department || '未分配部门' }}</option></select></label>
        <div v-else-if="isProcurement" class="text-sm">申请人<div class="mt-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 font-medium">{{ applicants.find((employee) => employee.name === form.applicant_employee)?.employee_name || optionLoader.data?.current_applicant?.employee_name || '未关联员工' }}</div></div>
        <div v-if="isProcurement" class="text-sm">采购经办人<div class="mt-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 font-medium">{{ purchasers.find((user) => user.name === form.purchaser_user)?.full_name || '未配置' }}</div></div>
        <label v-if="isProcurement" class="text-sm">采购范围<select v-model="form.procurement_scope" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"><option>项目采购</option><option>非项目采购</option></select></label>
        <label v-if="isProcurement && form.procurement_scope === '项目采购'" class="text-sm">所属项目<select v-model="form.project" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"><option value="">请选择项目</option><option v-for="project in projects" :key="project.name" :value="project.name">{{ project.project_name }} · {{ project.project_owner_name || project.project_owner }}</option></select></label>
        <template v-if="isProcurement && form.procurement_scope !== '项目采购'">
          <label class="text-sm">非项目归属<select v-model="form.non_project_allocation_type" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"><option>成本中心</option><option>部门</option><option>非项目采购</option></select></label>
          <label v-if="form.non_project_allocation_type === '成本中心'" class="text-sm">成本中心<input v-model="form.non_project_cost_center" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
          <label v-if="form.non_project_allocation_type === '部门'" class="text-sm">所属部门<input v-model="form.non_project_department" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
</template>

        <label v-if="isDirectPurchase" class="text-sm">购买方式<select v-model="form.purchase_method" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"><option>京东购买</option><option>其他购买</option></select></label>
        <label v-if="isDirectPurchase" class="text-sm">所属项目<select v-model="form.project" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"><option value="">非项目购买</option><option v-for="project in projects" :key="project.name" :value="project.name">{{ projectOptionLabel(project) }}</option></select></label>
        <label v-if="isPayment" class="text-sm md:col-span-2">付款计划期次<select v-model="form.source_payment_plan_row" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"><option value="">请选择已生效合同的付款期次</option><option v-for="source in paymentSources" :key="source.payment_plan_row" :value="source.payment_plan_row">{{ source.name }} · {{ source.installment_name }} · {{ source.payment_stage }} · ¥{{ formatMoney(source.amount) }} · {{ source.trigger_condition }}</option></select></label>
        <div v-if="isPayment" class="text-sm">供应商<div class="mt-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 font-medium">{{ form.supplier || '-' }}</div></div>
        <div v-if="isPayment" class="text-sm">付款阶段<div class="mt-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 font-medium">{{ paymentStageHint }}</div></div>
        <div v-if="isPayment && paymentStageHint === '预付款'" class="text-sm">预付款比例<div class="mt-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 font-medium">{{ form.prepayment_percentage }}%</div></div>
        <label v-if="isPayment && paymentStageHint === '预付款' && Number(form.prepayment_percentage) === 100" class="text-sm">预计到货日期<input v-model="form.expected_arrival_date" type="date" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2" /></label>
        <label v-if="isPayment && paymentStageHint === '预付款' && Number(form.prepayment_percentage) === 100" class="text-sm xl:col-span-2">100%预付款风险说明<textarea v-model="form.prepayment_risk_note" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2"></textarea></label>
        <label class="text-xs font-medium text-gray-700 md:col-span-2 xl:col-span-4">申请说明<textarea v-model="form.reason" rows="2" class="mt-1 w-full rounded-md border-gray-300 px-3 py-1.5 text-sm" maxlength="1000"></textarea></label>
      </div>

     <div v-if="pmcEditMode && Object.keys(materialSuggestions).length" class="border-t border-amber-200 bg-amber-50 px-5 py-4 lg:px-6"><h3 class="text-sm font-semibold text-amber-900">物料重复与智能分类建议</h3><p class="mt-1 text-xs text-amber-800">建议仅供 PMC 核对；人工选择的分类不会被自动覆盖。规格型号命中或名称、型号、品牌完全一致时，请优先绑定已有物料。</p><div class="mt-3 grid gap-2 md:grid-cols-2"><div v-for="(suggestion, index) in materialSuggestions" :key="index" class="rounded-md border border-amber-200 bg-white p-3 text-xs text-gray-700"><div class="font-medium">第{{ Number(index) + 1 }}项：{{ suggestion.risk_assessment?.level }}｜{{ suggestion.risk_assessment?.action }}</div><div v-if="suggestion.duplicates?.identity?.length" class="mt-1 text-red-700">名称、规格型号、品牌完全一致：{{ suggestion.duplicates.identity.map((item) => item.material_code).join('、') }}，建议绑定已有物料。</div><div v-else-if="suggestion.duplicates?.spec?.length" class="mt-1 text-red-700">规格型号命中：{{ suggestion.duplicates.spec.map((item) => item.material_code).join('、') }}，建议先核对后再新增。</div><div v-if="suggestion.duplicates?.spec_format?.length" class="mt-1 text-amber-700">规格型号仅分隔符/书写格式不同：{{ suggestion.duplicates.spec_format.map((item) => item.material_code).join('、') }}，需人工确认是否同一型号。</div><div v-if="suggestion.duplicates?.name?.length" class="mt-1 text-gray-600">仅名称相同：{{ suggestion.duplicates.name.map((item) => item.material_code).join('、') }}，请继续核对规格、品牌和用途。</div><div v-if="suggestion.suggested_category" class="mt-1">智能分类建议：{{ suggestion.suggested_category.category_code }}（{{ suggestion.suggested_category.category_path || '分类路径待补充' }}，置信度 {{ suggestion.suggested_category.confidence }}%）</div><div v-if="suggestion.matches?.length" class="mt-1 text-[11px] text-gray-500">参考物料：{{ suggestion.matches.slice(0, 3).map((item) => `${item.material_code} ${item.material_name || ''}`).join('、') }}</div></div></div></div>
      <div v-if="isProcurement" class="border-t border-gray-200">
        <div class="flex items-center justify-between border-b border-gray-100 bg-white px-5 py-3 lg:px-6"><div class="flex items-center gap-2"><h3 class="text-sm font-semibold text-gray-900" title="选择物料编号会自动带出完整物料资料">采购明细</h3><span class="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">{{ form.business_lines.length }} 项</span></div><button type="button" class="inline-flex h-8 items-center gap-2 rounded-md border border-gray-300 px-3 text-sm font-medium hover:border-gray-400 hover:bg-gray-50" @click="addLine"><FeatherIcon name="plus" class="h-4 w-4" />添加一行</button></div>
        <div class="request-materials">
          <article v-for="(line, index) in form.business_lines" :key="index" class="request-material">
            <header class="material-row-head"><strong>第 {{ index + 1 }} 项</strong><button type="button" class="rounded-md p-2 text-red-600 hover:bg-red-50" title="删除明细" @click="removeLine(index)"><FeatherIcon name="trash-2" class="h-4 w-4" /></button></header>
            <div class="material-fields"><div class="material-field span-3"><span title="逐级选择，至少三级">物料编号</span><div class="relative min-w-0">
  <div class="flex items-stretch">
    <input v-model="line.material_query" class="min-w-0 flex-1 rounded-l-md border-gray-300 px-2 py-1.5 text-xs" placeholder="搜索物料编号或名称" title="至少选择到三级；没有下一级时可停在当前级，由 PMC 后续补全" @focus="searchMaterials(index, line)" @input="searchMaterials(index, line)" @keydown.enter.prevent="selectFirstMaterial(index, line)" />
    <button type="button" class="flex w-9 shrink-0 items-center justify-center rounded-r-md border border-l-0 border-gray-300 bg-gray-50 text-gray-500 hover:bg-gray-100" title="逐级选择物料编号" :aria-expanded="line.category_open" @click="line.category_open ? closeCategoryPicker(line) : openCategoryPicker(line)">
      <FeatherIcon :name="line.category_open ? 'chevron-up' : 'chevron-down'" class="h-4 w-4" />
    </button>
  </div>
  <div v-if="line.material_open && materialMatchesFor(index).length && !line.category_open" class="material-picker-panel relative mt-2 max-h-72 w-[26rem] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-xl">
    <button v-for="item in materialMatchesFor(index)" :key="item.material_code" type="button" class="block w-full px-3 py-2 text-left text-xs hover:bg-gray-50" @mousedown.prevent="selectMaterial(index, line, item)">
      <span class="font-mono text-gray-500">{{ item.material_code }}</span><span class="ml-2 font-medium text-gray-900">{{ item.material_name }}</span><span class="mt-0.5 block whitespace-normal break-words text-[11px] text-gray-400">{{ item.specification || item.category_path }}</span>
    </button>
  </div>
  <div v-if="line.category_open" class="material-picker-panel relative mt-2 w-[26rem] max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-gray-200 bg-white shadow-xl">
    <div v-if="line.material_code" class="flex items-center justify-between border-b border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-900"><span>已选物料编号</span><button type="button" class="font-medium underline underline-offset-2" @mousedown.prevent="clearMaterialSelection(line)">不绑定物料编号，交由 PMC 补充</button></div>
    <div class="flex items-center gap-2 border-b border-gray-100 bg-gray-50 px-3 py-2 text-xs text-gray-500">
      <button v-if="line.category_picker_path?.length" type="button" class="rounded border border-gray-300 bg-white px-2 py-1 hover:bg-gray-100" @click="goBackCategory(line)">返回</button>
      <span class="whitespace-normal break-words">{{ line.category_picker_path?.length ? categoryPickerPathLabels(line).join(' / ') : '选择一级分类' }}</span>
    </div>
    <div class="max-h-64 overflow-y-auto p-1">
      <button v-for="item in categoryChildrenFor(line)" :key="item.category_code" type="button" class="flex w-full items-center justify-between gap-3 rounded-md px-3 py-2.5 text-left text-sm hover:bg-blue-50" @mousedown.prevent="chooseCategoryNode(index, line, item)">
        <span><span class="mr-2 font-mono text-gray-400">{{ item.category_code }}</span><span class="font-medium text-gray-800">{{ item.category_name }}</span></span>
        <FeatherIcon v-if="categoryHasChildren(item)" name="chevron-right" class="h-4 w-4 shrink-0 text-gray-400" />
      </button>
      <div v-if="categoryMaterialsFor(line).length" class="mt-1 border-t border-gray-100 pt-1">
        <p class="px-3 py-1.5 text-[11px] text-gray-500">选择物料编号</p>
        <button v-for="item in categoryMaterialsFor(line)" :key="item.material_code" type="button" class="block w-full rounded-md px-3 py-2.5 text-left text-sm hover:bg-blue-50" @mousedown.prevent="chooseCategoryMaterial(index, line, item)">
          <span class="font-mono text-gray-500">{{ item.material_code }}</span><span class="ml-2 font-medium text-gray-900">{{ item.material_name }}</span>
          <span class="mt-0.5 block whitespace-normal break-words text-[11px] text-gray-500">{{ item.specification || '-' }} · {{ item.brand || '-' }} · {{ item.unit || '-' }}</span>
        </button>
      </div>
      <p v-if="!categoryChildrenFor(line).length && !categoryMaterialsFor(line).length" class="px-3 py-4 text-center text-xs text-gray-400">暂无下级分类或物料</p>
    </div>
    <div v-if="categoryPickerCanConfirm(line)" class="border-t border-blue-100 bg-blue-50 px-3 py-2.5">
      <button type="button" class="flex w-full items-center justify-center rounded-md bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700" @mousedown.prevent="confirmCategorySelection(line)">确认当前物料编号，交由 PMC 后续完善</button>
    </div>
  </div>
  <div v-if="line.category_code" class="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]"><span class="text-gray-400">{{ line.material_code ? '已绑定物料编号' : '待 PMC 完善物料编号' }}</span><span class="break-all rounded bg-gray-50 px-1.5 py-0.5 font-mono text-gray-600">{{ line.material_code || line.category_code }}</span><button v-if="line.material_code" type="button" class="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 font-medium text-amber-800 hover:bg-amber-100" @click="clearMaterialSelection(line)">改为新增物料</button></div>
</div></div>
<label class="material-field span-2"><span>物料名称</span><textarea v-model="line.item_name" v-auto-grow rows="2" :readonly="!!line.material_code"></textarea></label>
<label class="material-field span-2"><span>Product name</span><textarea v-model="line.product_name" v-auto-grow rows="2" :readonly="!!line.material_code" :placeholder="line.material_code ? '物料库未填写' : 'Product name'"></textarea></label>
<label class="material-field span-3"><span>规格型号</span><textarea v-model="line.specification" v-auto-grow rows="2" :readonly="!!line.material_code"></textarea></label>
<label class="material-field span-1"><span>数量</span><input v-model.number="line.quantity" type="number" min="0.0001" step="0.0001" /></label>
<label class="material-field span-1"><span>单位</span><textarea v-model="line.unit" v-auto-grow rows="2"></textarea></label></div>
            <div class="material-fields material-fields-secondary"><label class="material-field span-3"><span>产品描述</span><textarea v-model="line.product_desc" v-auto-grow rows="2" :readonly="!!line.material_code"></textarea></label>
<label class="material-field span-3"><span>Product description</span><textarea v-model="line.product_desc_en" v-auto-grow rows="2" :readonly="!!line.material_code" :placeholder="line.material_code ? '物料库未填写' : 'Product description'"></textarea></label>
<label class="material-field span-1"><span>商品品牌</span><textarea v-model="line.brand" v-auto-grow rows="2" :readonly="!!line.material_code"></textarea></label>
<label class="material-field span-1"><span>Brand</span><textarea v-model="line.brand_en" v-auto-grow rows="2" :readonly="!!line.material_code" :placeholder="line.material_code ? '物料库未填写' : 'Brand'"></textarea></label>
<label class="material-field span-1"><span>需求阶段单价</span><input v-model.number="line.unit_price" type="number" min="0" step="0.01" disabled placeholder="询价后录入" /></label>
<label class="material-field span-3"><span>备注</span><textarea v-model="line.remarks" v-auto-grow rows="2"></textarea></label></div>
          </article>
        </div>
      </div>
      <div v-else class="border-t border-gray-200">
        <div class="flex items-center justify-between border-b border-gray-100 bg-white px-5 py-3 lg:px-6"><div class="flex items-center gap-2"><h3 class="text-sm font-semibold text-gray-900">购买明细</h3><span class="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">{{ form.business_lines.length }} 项</span></div><button type="button" class="inline-flex h-8 items-center gap-2 rounded-md border border-gray-300 px-3 text-sm font-medium hover:border-gray-400 hover:bg-gray-50" @click="addLine"><FeatherIcon name="plus" class="h-4 w-4" />添加一行</button></div>
        <div class="grid gap-3 bg-gray-50/70 p-4 lg:p-5" :class="form.business_lines.length > 1 ? 'lg:grid-cols-2' : 'lg:grid-cols-1'">
          <article v-for="(line, index) in form.business_lines" :key="index" class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <div class="mb-3 flex items-center justify-between"><span class="text-xs font-semibold uppercase tracking-wide text-gray-500">第 {{ index + 1 }} 项</span><button type="button" class="rounded-md p-2 text-red-600 hover:bg-red-50" title="删除明细" @click="removeLine(index)"><FeatherIcon name="trash-2" class="h-4 w-4" /></button></div>
            <div class="grid gap-3 sm:grid-cols-2">
              <label class="text-xs font-medium text-gray-700 sm:col-span-2">购买物品<input v-model="line.item_name" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2 text-sm" placeholder="填写购买物品" /></label>
              <label class="text-xs font-medium text-gray-700">规格型号<input v-model="line.specification" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2 text-sm" placeholder="可选" /></label>
              <label class="text-xs font-medium text-gray-700">产品说明<textarea v-model="line.product_desc" rows="2" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2 text-sm" placeholder="可选" /></label>
              <label class="text-xs font-medium text-gray-700">数量<input v-model.number="line.quantity" type="number" min="0.0001" step="0.0001" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs font-medium text-gray-700">单位<input v-model="line.unit" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2 text-sm" /></label>
              <label class="text-xs font-medium text-gray-700">预计单价<input v-model.number="line.unit_price" type="number" min="0" step="0.01" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2 text-sm" placeholder="可选" /></label>
              <label class="text-xs font-medium text-gray-700">备注<input v-model="line.remarks" class="mt-1 w-full rounded-md border-gray-300 px-3 py-2 text-sm" placeholder="可选" /></label>
            </div>
          </article>
        </div>
      </div>
      <div v-if="!pmcEditMode" class="flex flex-wrap items-center gap-3 border-t border-gray-200 bg-gray-50 px-5 py-4 lg:px-6"><button type="button" class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium disabled:opacity-50" :disabled="saving" @click="saveDraft">保存草稿</button><button type="button" class="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50" :disabled="saving || Boolean(organizationWarning)" @click="submitApproval">提交审批</button></div>
     </section>
    </template>
   </div>
 </template>

<style>
.request-form > .grid > label,
.request-form > .grid > div {
  line-height: 1.25;
}

.request-form input,
.request-form select,
.request-form textarea {
  font-size: 0.875rem;
  padding: 0.375rem 0.75rem;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}

.request-form input:focus,
.request-form select:focus,
.request-form textarea:focus {
  border-color: rgb(37 99 235);
  box-shadow: 0 0 0 1px rgb(37 99 235 / 0.16);
  outline: none;
}


.request-materials { padding: 16px; background: #f7f9fa; display: grid; gap: 14px; }
.request-material { min-width: 0; border: 1px solid #dce3e5; border-radius: 6px; background: white; }
.material-row-head { display: flex; align-items: center; justify-content: space-between; min-height: 38px; padding: 4px 14px; border-bottom: 1px solid #e6ebed; background: #f8fafb; color: #53666c; font-size: 12px; }
.material-fields { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 14px; padding: 14px; align-items: start; }
.material-fields-secondary { border-top: 1px solid #e8edef; }
.material-field { display: flex; flex-direction: column; min-width: 0; gap: 6px; color: #263b42; font-size: 13px; }
.material-field > span { color: #667980; font-size: 12px; line-height: 1.5; }
.material-field p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; }
.material-field input, .material-field textarea { width: 100%; min-width: 0; border: 1px solid #cbd5db; border-radius: 5px; padding: 7px 8px; font-size: 13px; line-height: 1.55; }
.material-field textarea { min-height: 58px; overflow-y: hidden; resize: vertical; overflow-wrap: anywhere; }
.material-field textarea[readonly] { background: #f6f8f9; color: #42565e; }
.material-field input:disabled { background: #f6f8f9; color: #809198; }
.material-field input:focus, .material-field textarea:focus { border-color: #176f73; outline: 1px solid #176f73; }
.span-1 { grid-column: span 1; }
.span-2 { grid-column: span 2; }
.span-3 { grid-column: span 3; }
.material-picker-panel { width: 100%; max-height: 24rem; overscroll-behavior: contain; color: #1f2937; }
.material-picker-panel button { min-height: 2.5rem; }
.material-picker-panel .font-mono { letter-spacing: 0; font-size: 0.72rem; }
@media (max-width: 1100px) {
  .material-fields { grid-template-columns: repeat(6, minmax(0, 1fr)); }
  .material-field.span-1 { grid-column: span 2; }
}
@media (max-width: 640px) {
  .request-materials { padding: 10px; }
  .material-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 12px; }
  .material-field.span-1 { grid-column: span 1; }
  .material-field.span-2, .material-field.span-3 { grid-column: span 2; }
}
</style>
