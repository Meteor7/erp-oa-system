<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { useRoute } from 'vue-router';
import {
  buildApprovalCenterPayload,
  canCloseProcurement,
  canRecordArrival,
  canRecordInspection,
  canWriteoffPrepayment,
  normalizeServerError,
} from '../lib/procurementWorkflow';

const route = useRoute();
const config = computed(() => ({
  '/approval/procurement': { requestType: '采购申请', title: '采购申请' },
  '/approval/direct-purchase': { requestType: '购买申请', title: '购买申请' },
  '/approval/procurement-payment': { requestType: '采购付款', title: '采购付款' },
}[route.path] || { requestType: '采购申请', title: '采购申请' }));
const isProcurement = computed(() => config.value.requestType === '采购申请');
const isDirectPurchase = computed(() => config.value.requestType === '购买申请');
const isPayment = computed(() => config.value.requestType === '采购付款');
const blankLine = () => ({ item_name: '', specification: '', quantity: 1, unit: '个', unit_price: 0, remarks: '' });
const blankForm = () => ({
  subject: '', reason: '', urgency: '一般', asset_nature: '非固定资产', fixed_asset_category: '',
  procurement_scope: '项目采购', expected_delivery_date: '', project: '',
  non_project_allocation_type: '非项目采购', non_project_cost_center: '', non_project_department: '',
  purchaser_user: '', purchase_method: '京东购买', source_request: '', supplier: '', payment_stage: '预付款',
  prepayment_percentage: 30, has_balance_payment: true, expected_arrival_date: '', prepayment_risk_note: '',
  business_lines: [blankLine()],
});
const form = reactive(blankForm());
const draftName = ref('');
const selectedRequestName = ref('');
const message = ref('');
const error = ref('');
const documentType = ref('合同');
const documents = ref([]);
const saving = ref(false);
const uploading = ref(false);
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
const documentTypes = ['需求申请', '报价单', '价格审批表', 'PR', 'PO', '合同', '付款计划', '发票', '验收资料', '送货单', '收料单', '入库单', '付款回单', '采购完成报告'];
const fixedCategories = ['办公家具、工具及器具', '电子设备、研发专用设备、仪器仪表', '生产设备、生产工具及器具'];

const saver = createResource({ url: 'rayher_hr_payroll.api.oa_entry.save_approval_center_draft' });
const submitter = createResource({ url: 'rayher_hr_payroll.api.oa_entry.submit_approval_center_draft' });
const actor = createResource({ url: 'rayher_hr_payroll.api.oa_entry.action_request' });
const attacher = createResource({ url: 'rayher_hr_payroll.api.oa_entry.attach_approval_business_document' });
const documentLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_approval_business_documents', method: 'GET' });
const projectLoader = createResource({ url: 'rayher_hr_payroll.api.project_entry.list_projects', method: 'GET', auto: true });
const userLoader = createResource({ url: 'rayher_hr_payroll.api.project_entry.list_project_owners', method: 'GET', auto: true });
const sourceLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.get_approval_center_dashboard', method: 'GET', makeParams: () => ({ kind: 'request', limit: 500 }), auto: true });
const mineLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_requests', method: 'GET', makeParams: () => ({ view: 'mine', request_type: config.value.requestType, limit: 100 }), auto: true });
const pendingLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_requests', method: 'GET', makeParams: () => ({ view: 'pending', request_type: config.value.requestType, limit: 100 }), auto: true });
const contractRegistrar = createResource({ url: 'rayher_hr_payroll.api.oa_entry.register_contract_delivery' });
const arrivalRecorder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.record_arrival' });
const inspectionRecorder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.record_inspection' });
const followupRecorder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.record_prepayment_followup' });
const writeoffRecorder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.writeoff_prepayment' });
const closeRecorder = createResource({ url: 'rayher_hr_payroll.api.oa_entry.close_procurement' });

const projects = computed(() => (projectLoader.data || []).filter((row) => row.status !== 'Cancelled'));
const purchasers = computed(() => userLoader.data || []);
const paymentSources = computed(() => (sourceLoader.data?.rows || []).filter((row) => row.request_type === '采购申请' && row.workflow_status === '已完成' && Number(row.available_amount) > 0));
const requestRows = computed(() => {
  const rows = [...(mineLoader.data || []), ...(pendingLoader.data || [])];
  return [...new Map(rows.map((row) => [row.name, row])).values()];
});
const selectedRequest = computed(() => requestRows.value.find((row) => row.name === selectedRequestName.value) || requestRows.value[0] || null);
const activeRequestName = computed(() => selectedRequest.value?.name || draftName.value);
const activeDocumentTypes = computed(() => {
  const latest = new Map();
  for (const row of documents.value) latest.set(row.document_type, row);
  return [...latest.keys()];
});
const showContractRegistration = computed(() => isProcurement.value && selectedRequest.value?.workflow_status === '已完成' && selectedRequest.value?.business_status !== '合同交期待确认');
const showArrival = computed(() => isPayment.value && canRecordArrival(selectedRequest.value, activeDocumentTypes.value));
const showInspection = computed(() => isPayment.value && canRecordInspection(selectedRequest.value, activeDocumentTypes.value));
const showWriteoff = computed(() => isPayment.value && canWriteoffPrepayment(selectedRequest.value, activeDocumentTypes.value));
const showClose = computed(() => isPayment.value && canCloseProcurement(selectedRequest.value, activeDocumentTypes.value));

function addLine() { if (form.business_lines.length < 100) form.business_lines.push(blankLine()); }
function removeLine(index) { if (form.business_lines.length > 1) form.business_lines.splice(index, 1); }
function cleanPayload() { return buildApprovalCenterPayload(form, config.value.requestType); }
function fail(exception, fallback) { error.value = normalizeServerError(exception, fallback); }
async function reloadRequests() { await Promise.all([mineLoader.reload(), pendingLoader.reload(), sourceLoader.reload()]); }

async function saveDraft() {
  saving.value = true; error.value = ''; message.value = '';
  try {
    const result = await saver.submit({ request_type: config.value.requestType, payload: JSON.stringify(cleanPayload()), name: draftName.value || undefined });
    draftName.value = result.name;
    selectedRequestName.value = result.name;
    message.value = `草稿 ${result.name} 已保存`;
    await Promise.all([loadDocuments(result.name), reloadRequests()]);
    return result;
  } catch (exception) { fail(exception, '保存失败'); return null; }
  finally { saving.value = false; }
}
async function submitApproval() {
  saving.value = true; error.value = ''; message.value = '';
  try {
    let name = draftName.value;
    if (!name) {
      const result = await saver.submit({ request_type: config.value.requestType, payload: JSON.stringify(cleanPayload()) });
      name = result.name;
      draftName.value = name;
    }
    await submitter.submit({ name });
    selectedRequestName.value = name;
    message.value = `${name} 已提交审批`;
    await reloadRequests();
  } catch (exception) { fail(exception, '提交失败'); }
  finally { saving.value = false; }
}
async function loadDocuments(name = activeRequestName.value) {
  if (!name) { documents.value = []; return; }
  try { documents.value = await documentLoader.fetch({ request: name }) || []; }
  catch (exception) { fail(exception, '资料加载失败'); }
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
async function act(action) {
  if (!selectedRequest.value) return;
  error.value = '';
  try {
    const params = { name: selectedRequest.value.name, action, note: action === 'reject' ? rejectReason.value.trim() : actionNote.value.trim() };
    if (action === 'reject') params.reject_target = rejectTarget.value;
    await actor.submit(params);
    rejectReason.value = ''; actionNote.value = '';
    await reloadRequests();
  } catch (exception) { fail(exception, '审批操作失败'); }
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
async function writeoff() {
  try { await writeoffRecorder.submit({ name: selectedRequest.value.name, reason: actionNote.value }); await reloadRequests(); }
  catch (exception) { fail(exception, '预付款核销失败'); }
}
async function closeOrder() {
  try { await closeRecorder.submit({ name: selectedRequest.value.name, reason: actionNote.value }); await reloadRequests(); }
  catch (exception) { fail(exception, '采购关闭失败'); }
}

watch(() => route.path, async () => {
  Object.assign(form, blankForm()); draftName.value = ''; selectedRequestName.value = '';
  documents.value = []; message.value = ''; error.value = '';
  await reloadRequests();
});
watch(selectedRequest, (row) => { if (row?.name) { selectedRequestName.value = row.name; loadDocuments(row.name); } }, { immediate: true });
</script>

<template>
  <div class='space-y-5'>
    <section class='rounded-lg border bg-white p-6 shadow-sm'>
      <div class='flex items-start justify-between gap-4'><div><h1 class='text-xl font-semibold'>{{ config.title }}</h1><p class='mt-1 text-sm text-gray-500'>审批中心 · 表单、资料、审批与履约状态一体化</p></div><span v-if='draftName' class='rounded bg-gray-100 px-3 py-1 text-sm'>{{ draftName }}</span></div>
      <div class='mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3'>
        <label class='text-sm'>主题<input v-model='form.subject' class='mt-1 w-full rounded border px-3 py-2' maxlength='140' /></label>
        <label class='text-sm'>紧急程度<select v-model='form.urgency' class='mt-1 w-full rounded border px-3 py-2'><option>一般</option><option>加急</option></select></label>
        <label class='text-sm'>资产属性<select v-model='form.asset_nature' class='mt-1 w-full rounded border px-3 py-2'><option>非固定资产</option><option>固定资产</option></select></label>
        <label v-if='form.asset_nature === "固定资产"' class='text-sm'>固定资产类别<select v-model='form.fixed_asset_category' class='mt-1 w-full rounded border px-3 py-2'><option value=''>请选择</option><option v-for='item in fixedCategories' :key='item'>{{ item }}</option></select></label>
        <label v-if='!isPayment' class='text-sm'>意向交期<input v-model='form.expected_delivery_date' type='date' class='mt-1 w-full rounded border px-3 py-2' /></label>
        <label v-if='!isPayment' class='text-sm'>采购经办人<select v-model='form.purchaser_user' class='mt-1 w-full rounded border px-3 py-2'><option value=''>请选择</option><option v-for='user in purchasers' :key='user.name' :value='user.name'>{{ user.full_name || user.name }}</option></select></label>
        <label v-if='isProcurement' class='text-sm'>采购范围<select v-model='form.procurement_scope' class='mt-1 w-full rounded border px-3 py-2'><option>项目采购</option><option>非项目采购</option></select></label>
        <label v-if='isProcurement && form.procurement_scope === "项目采购"' class='text-sm'>所属项目<select v-model='form.project' class='mt-1 w-full rounded border px-3 py-2'><option value=''>请选择项目</option><option v-for='project in projects' :key='project.name' :value='project.name'>{{ project.project_name }} · {{ project.project_owner_name || project.project_owner }}</option></select></label>
        <template v-if='isProcurement && form.procurement_scope !== "项目采购"'>
          <label class='text-sm'>非项目归属<select v-model='form.non_project_allocation_type' class='mt-1 w-full rounded border px-3 py-2'><option>成本中心</option><option>部门</option><option>非项目采购</option></select></label>
          <label v-if='form.non_project_allocation_type === "成本中心"' class='text-sm'>成本中心<input v-model='form.non_project_cost_center' class='mt-1 w-full rounded border px-3 py-2' /></label>
          <label v-if='form.non_project_allocation_type === "部门"' class='text-sm'>所属部门<input v-model='form.non_project_department' class='mt-1 w-full rounded border px-3 py-2' /></label>
        </template>
        <label v-if='isDirectPurchase' class='text-sm'>购买方式<select v-model='form.purchase_method' class='mt-1 w-full rounded border px-3 py-2'><option>京东购买</option><option>其他购买</option></select></label>
        <label v-if='isDirectPurchase' class='text-sm'>所属项目<select v-model='form.project' class='mt-1 w-full rounded border px-3 py-2'><option value=''>非项目购买</option><option v-for='project in projects' :key='project.name' :value='project.name'>{{ project.project_name }}</option></select></label>
        <template v-if='isDirectPurchase && !form.project'>
          <label class='text-sm'>非项目成本归属<select v-model='form.non_project_allocation_type' class='mt-1 w-full rounded border px-3 py-2'><option>成本中心</option><option>部门</option><option>非项目采购</option></select></label>
          <label v-if='form.non_project_allocation_type === "成本中心"' class='text-sm'>成本中心<input v-model='form.non_project_cost_center' class='mt-1 w-full rounded border px-3 py-2' /></label>
          <label v-if='form.non_project_allocation_type === "部门"' class='text-sm'>所属部门<input v-model='form.non_project_department' class='mt-1 w-full rounded border px-3 py-2' /></label>
        </template>
        <label v-if='isPayment' class='text-sm'>关联采购申请<select v-model='form.source_request' class='mt-1 w-full rounded border px-3 py-2'><option value=''>请选择</option><option v-for='source in paymentSources' :key='source.name' :value='source.name'>{{ source.name }} · {{ source.subject }} · 可用 {{ source.available_amount }}</option></select></label>
        <label v-if='isPayment' class='text-sm'>供应商<input v-model='form.supplier' class='mt-1 w-full rounded border px-3 py-2' /></label>
        <label v-if='isPayment' class='text-sm'>付款阶段<select v-model='form.payment_stage' class='mt-1 w-full rounded border px-3 py-2'><option>预付款</option><option>到货款</option><option>尾款</option><option>全额付款</option></select></label>
        <label v-if='isPayment && form.payment_stage === "预付款"' class='text-sm'>预付款比例<input v-model.number='form.prepayment_percentage' type='number' min='0' max='100' class='mt-1 w-full rounded border px-3 py-2' /></label>
        <label v-if='isPayment && form.payment_stage === "预付款"' class='flex items-center gap-2 pt-6 text-sm'><input v-model='form.has_balance_payment' type='checkbox' />存在后续尾款</label>
        <label v-if='isPayment && Number(form.prepayment_percentage) === 100' class='text-sm'>预计到货日期<input v-model='form.expected_arrival_date' type='date' class='mt-1 w-full rounded border px-3 py-2' /></label>
        <label v-if='isPayment && Number(form.prepayment_percentage) === 100' class='text-sm xl:col-span-2'>100%预付款风险说明<textarea v-model='form.prepayment_risk_note' class='mt-1 w-full rounded border px-3 py-2'></textarea></label>
        <label class='text-sm md:col-span-2 xl:col-span-3'>申请说明<textarea v-model='form.reason' class='mt-1 w-full rounded border px-3 py-2' maxlength='1000'></textarea></label>
      </div>
    </section>

    <section class='rounded-lg border bg-white p-6 shadow-sm'>
      <div class='mb-3 flex items-center justify-between'><h2 class='font-semibold'>采购/购买明细</h2><button type='button' class='rounded border px-3 py-1.5 text-sm' @click='addLine'>添加一行</button></div>
      <div class='overflow-x-auto'><table class='min-w-full text-sm'><thead><tr class='border-b text-left text-gray-500'><th class='p-2'>物品名称</th><th class='p-2'>规格</th><th class='p-2'>数量</th><th class='p-2'>单位</th><th class='p-2'>单价</th><th class='p-2'>备注</th><th></th></tr></thead><tbody>
        <tr v-for='(line, index) in form.business_lines' :key='index' class='border-b'><td class='p-2'><input v-model='line.item_name' class='w-40 rounded border px-2 py-1.5' /></td><td class='p-2'><input v-model='line.specification' class='w-32 rounded border px-2 py-1.5' /></td><td class='p-2'><input v-model.number='line.quantity' type='number' min='0.0001' step='0.0001' class='w-24 rounded border px-2 py-1.5' /></td><td class='p-2'><input v-model='line.unit' class='w-20 rounded border px-2 py-1.5' /></td><td class='p-2'><input v-model.number='line.unit_price' type='number' min='0' step='0.01' class='w-28 rounded border px-2 py-1.5' /></td><td class='p-2'><input v-model='line.remarks' class='w-40 rounded border px-2 py-1.5' /></td><td><button type='button' class='text-red-600' @click='removeLine(index)'>删除</button></td></tr>
      </tbody></table></div>
      <div class='mt-4 flex flex-wrap items-center gap-3'><button type='button' class='rounded border px-4 py-2 disabled:opacity-50' :disabled='saving' @click='saveDraft'>保存草稿</button><button type='button' class='rounded bg-gray-900 px-4 py-2 text-white disabled:opacity-50' :disabled='saving' @click='submitApproval'>提交审批</button><span class='text-sm text-green-700'>{{ message }}</span><span class='text-sm text-red-600'>{{ error }}</span></div>
    </section>

    <section class='grid gap-5 xl:grid-cols-[360px_1fr]'>
      <div class='rounded-lg border bg-white p-4 shadow-sm'><h2 class='font-semibold'>我的申请与待办</h2><div class='mt-3 space-y-2'><button v-for='row in requestRows' :key='row.name' class='block w-full rounded border p-3 text-left' :class='selectedRequest?.name === row.name ? "border-gray-900" : "border-gray-200"' @click='selectedRequestName = row.name'><div class='flex justify-between'><span class='font-medium'>{{ row.name }}</span><span class='text-xs'>{{ row.workflow_status }}</span></div><div class='mt-1 text-xs text-gray-500'>{{ row.subject }}</div><div class='mt-1 text-xs'>当前：{{ row.current_step_label || '-' }}</div></button><p v-if='!requestRows.length' class='text-sm text-gray-400'>暂无申请</p></div></div>
      <div v-if='selectedRequest' class='space-y-4 rounded-lg border bg-white p-5 shadow-sm'>
        <div class='grid gap-3 text-sm md:grid-cols-4'><div><span class='text-gray-500'>申请单</span><div>{{ selectedRequest.name }}</div></div><div><span class='text-gray-500'>审批状态</span><div>{{ selectedRequest.workflow_status }}</div></div><div><span class='text-gray-500'>业务状态</span><div>{{ selectedRequest.business_status || '-' }}</div></div><div><span class='text-gray-500'>当前审批人/节点</span><div>{{ selectedRequest.current_step_label || '-' }}</div></div></div>
        <div><h3 class='text-sm font-medium'>审批轨迹</h3><ol class='mt-2 space-y-2'><li v-for='row in selectedRequest.steps || []' :key='row.step_key' class='flex justify-between rounded bg-gray-50 px-3 py-2 text-sm'><span>{{ row.step_index }}. {{ row.label }}</span><span>{{ row.status }}</span></li></ol></div>
        <div v-if='selectedRequest.can_act' class='rounded border p-3'><textarea v-model='actionNote' class='w-full rounded border px-3 py-2 text-sm' placeholder='审批意见（可选）'></textarea><div class='mt-2 flex gap-2'><button class='rounded bg-green-700 px-3 py-2 text-sm text-white' @click='act("approve")'>通过/办理</button></div><div class='mt-3 grid gap-2 md:grid-cols-3'><select v-model='rejectTarget' class='rounded border px-3 py-2 text-sm'><option v-for='target in selectedRequest.rejection_targets || []' :key='target.target' :value='target.target'>{{ target.label }}</option></select><input v-model='rejectReason' class='rounded border px-3 py-2 text-sm' placeholder='驳回原因（必填）' /><button class='rounded bg-red-600 px-3 py-2 text-sm text-white' @click='act("reject")'>定向驳回</button></div></div>
        <div v-if='showContractRegistration' class='grid gap-2 rounded border p-3 md:grid-cols-3'><input v-model='contractDate' type='date' class='rounded border px-3 py-2 text-sm' /><input v-model='contractReason' class='rounded border px-3 py-2 text-sm' placeholder='延期时必须填写原因' /><button class='rounded bg-gray-900 px-3 py-2 text-sm text-white' @click='registerContract'>登记合同交期</button></div>
        <div v-if='isPayment && selectedRequest.workflow_status === "已付款"' class='space-y-3 rounded border p-3'><div class='text-sm'>到货 {{ selectedRequest.received_quantity }}/{{ selectedRequest.ordered_quantity }} · {{ selectedRequest.arrival_status }} · {{ selectedRequest.inspection_status }}</div><div v-if='showArrival' class='flex gap-2'><input v-model.number='arrivalQuantity' type='number' class='w-28 rounded border px-3 py-2 text-sm' placeholder='到货数量' /><input v-model='arrivalDate' type='date' class='rounded border px-3 py-2 text-sm' /><button class='rounded bg-gray-900 px-3 py-2 text-sm text-white' @click='recordArrival'>登记到货</button></div><div v-if='showInspection' class='grid gap-2 md:grid-cols-4'><select v-model='inspectionOutcome' class='rounded border px-3 py-2'><option>通过</option><option>不合格</option></select><select v-if='inspectionOutcome === "不合格"' v-model='inspectionDirection' class='rounded border px-3 py-2'><option>退货</option><option>换货</option></select><input v-model='inspectionReason' class='rounded border px-3 py-2' placeholder='验收说明/不合格原因' /><button class='rounded bg-gray-900 px-3 py-2 text-white' @click='recordInspection'>登记验收</button></div><div v-if='selectedRequest.payment_stage === "预付款"' class='grid gap-2 md:grid-cols-3'><select v-model='followupStatus' class='rounded border px-3 py-2'><option>催办中</option><option>供应商退款中</option><option>退货中</option><option>换货中</option></select><input v-model='followupReason' class='rounded border px-3 py-2' placeholder='异常跟进说明' /><button class='rounded border px-3 py-2' @click='recordFollowup'>记录跟进</button></div><div class='flex gap-2'><button v-if='showWriteoff' class='rounded bg-blue-700 px-3 py-2 text-white' @click='writeoff'>预付款核销</button><button v-if='showClose' class='rounded bg-gray-900 px-3 py-2 text-white' @click='closeOrder'>关闭采购</button></div></div>
      </div>
    </section>

    <section class='rounded-lg border bg-white p-6 shadow-sm'><h2 class='font-semibold'>业务资料归档</h2><p class='mt-1 text-sm text-gray-500'>资料保存为私有版本；履约操作只认当前有效版本。</p><div class='mt-3 flex items-center gap-3'><select v-model='documentType' class='rounded border px-3 py-2 text-sm'><option v-for='item in documentTypes' :key='item'>{{ item }}</option></select><label class='cursor-pointer rounded border px-3 py-2 text-sm'>{{ uploading ? '上传中…' : '选择文件并归档' }}<input type='file' class='hidden' :disabled='uploading || !activeRequestName' @change='uploadDocument' /></label></div><div v-if='documents.length' class='mt-4 divide-y rounded border'><div v-for='doc in documents' :key='doc.name' class='flex justify-between p-3 text-sm'><span>{{ doc.document_type }} · {{ doc.original_filename }}</span><span>v{{ doc.version_no }}</span></div></div><p v-else class='mt-4 text-sm text-gray-400'>暂无已归档资料</p></section>
  </div>
</template>
