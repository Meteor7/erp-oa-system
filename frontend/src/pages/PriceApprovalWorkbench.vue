<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { createResource, FeatherIcon } from 'frappe-ui';
import { useRoute } from 'vue-router';
import { canEditProcurementPrice, canSeeProcurementPO, canSeeProcurementPrice } from '../lib/access';

const route = useRoute();
const canViewPrice = canSeeProcurementPrice();
const canViewPo = canSeeProcurementPO();
const canEditPrice = canEditProcurementPrice();
const tabs = [
  ...(canViewPrice ? [{ key: 'price', label: '价格审批', icon: 'file-text' }] : []),
  ...(canViewPo ? [{ key: 'po', label: 'PO 采购订单', icon: 'package' }] : []),
];
const tab = ref((route.path === '/approval/procurement/po' || route.query.tab === 'po') && canViewPo ? 'po' : (canViewPrice ? 'price' : 'po'));
const priceView = ref(route.query.view === 'source' ? 'source' : 'approvals');
const prSearch = ref('');
const prAvailability = ref('available');
const notice = ref('');
const error = ref('');
const selectedPrLines = ref(new Set());
const priceQuantities = ref({});
const activeApproval = ref(null);
const activePo = ref(null);
const supplierSlots = ref([]);
const approvalView = ref('compare');
const deliveryDraft = ref({});
const receiptDraft = ref({});
const inspectionDraft = ref({});
const paymentDraft = ref({ amount: '', reference: '' });
const paymentPlanDraft = ref('');
const contractDraft = ref({ seal_user: 'admin@staff.example.invalid', supplier_legal_name: '', contract_delivery_date: '' });
const summaryDraft = ref('');


const api = 'rayher_hr_payroll.api.procurement_chain.';
const prLoader = createResource({ url: api + 'list_prs', method: 'GET' });
const approvalLoader = createResource({ url: api + 'list_price_approvals', method: 'GET' });
const poLoader = createResource({ url: api + 'list_purchase_orders', method: 'GET' });
const actions = {
  createApproval: createResource({ url: api + 'create_price_approval', method: 'POST' }),
  saveSupplier: createResource({ url: api + 'save_supplier_comparison', method: 'POST' }),
  deleteSupplier: createResource({ url: api + 'delete_supplier_comparison', method: 'POST' }),
  updateSummary: createResource({ url: api + 'update_price_approval_summary', method: 'POST' }),
  chooseSupplier: createResource({ url: api + 'select_supplier_comparison', method: 'POST' }),
  submitApproval: createResource({ url: api + 'submit_price_approval', method: 'POST' }),
  approveApproval: createResource({ url: api + 'approve_price_approval', method: 'POST' }),
  withdrawApproval: createResource({ url: api + 'withdraw_price_approval', method: 'POST' }),
  cancelApproval: createResource({ url: api + 'cancel_price_approval', method: 'POST' }),
  updateDelivery: createResource({ url: api + 'update_po_delivery', method: 'POST' }),
  confirmPo: createResource({ url: api + 'confirm_po', method: 'POST' }),
  savePoContract: createResource({ url: api + 'save_po_contract_information', method: 'POST' }),
  reviewPoContract: createResource({ url: api + 'review_po_contract', method: 'POST' }),
  sealPoContract: createResource({ url: api + 'seal_po_contract', method: 'POST' }),
  pushPaymentRequest: createResource({ url: api + 'push_po_payment_request', method: 'POST' }),
  approvePaymentStep: createResource({ url: api + 'approve_po_payment_step', method: 'POST' }),
  receivePo: createResource({ url: api + 'record_po_receipt', method: 'POST' }),
  inspectPo: createResource({ url: api + 'record_po_inspection', method: 'POST' }),
  payPo: createResource({ url: api + 'record_po_payment', method: 'POST' }),
  closePo: createResource({ url: api + 'close_po', method: 'POST' }),
};
const contextRequest = computed(() => String(route.query.request || '').trim());
const allPrs = computed(() => prLoader.data || []);
const allApprovals = computed(() => approvalLoader.data || []);
const allPos = computed(() => poLoader.data || []);
const prs = computed(() => {
  if (!contextRequest.value) return allPrs.value;
  return allPrs.value.map((pr) => ({
    ...pr, lines: (pr.lines || []).filter((line) => line.source_request === contextRequest.value),
  })).filter((pr) => pr.lines.length);
});
const approvals = computed(() => {
  if (!contextRequest.value) return allApprovals.value;
  return allApprovals.value.filter((item) => String(item.source_requests || '').split(',').includes(contextRequest.value));
});
const pos = computed(() => {
  if (!contextRequest.value) return allPos.value;
  return allPos.value.filter((po) => (po.lines || []).some((line) => line.source_request === contextRequest.value));
});
const contextSummary = computed(() => {
  if (!contextRequest.value) return '';
  const pending = prs.value.reduce((sum, pr) => sum + (pr.lines || []).filter((line) => Number(line.remaining_quantity) > 0).length, 0);
  return `${contextRequest.value} · ${prs.value.length} 张 PR · 待比价 ${pending} 项 · ${approvals.value.length} 张价格审批单 · ${pos.value.length} 张 PO`;
});
const selectedPrCount = computed(() => selectedPrLines.value.size);
function availableLineCount(pr) {
  return (pr.lines || []).filter((line) => Number(line.remaining_quantity) > 0).length;
}
const filteredPrs = computed(() => {
  const query = prSearch.value.trim().toLowerCase();
  let result = prs.value.map((pr) => ({
    ...pr,
    lines: query ? (pr.lines || []).filter((line) => [pr.name, line.source_request, line.material_serial, line.item_name, line.project]
      .join(' ').toLowerCase().includes(query)) : (pr.lines || []),
  })).filter((pr) => pr.lines.length);
  if (prAvailability.value === 'available') result = result.filter((pr) => availableLineCount(pr) > 0);
  if (prAvailability.value === 'exhausted') result = result.filter((pr) => availableLineCount(pr) === 0);
  return result.sort((a, b) => availableLineCount(b) - availableLineCount(a));
});

function money(value, currency = 'CNY') {
  const amount = Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (currency || 'CNY') + ' ' + amount;
}
function quantity(value) { return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 }); }
function clearMessage() { notice.value = ''; error.value = ''; }
function fail(err, fallback) { error.value = err?.messages?.[0] || err?.message || fallback; }
function keyOfPr(pr, line) { return pr.name + ':' + line.name; }
function supplierComparisons() { return activeApproval.value?.supplier_comparisons || []; }
function supplierCount() { return supplierSlots.value.filter((slot) => String(slot.supplier || '').trim()).length; }
function comparisonPrice(slot, line) { return slot?.prices?.[line.name] || {}; }
function supplierSlotFromGroup(group, index) {
  const slot = emptySupplierDraft(activeApproval.value);
  const prices = {};
  (activeApproval.value?.lines || []).forEach((line) => {
    const price = (group.prices || []).find((item) => item.price_line === line.name) || {};
    prices[line.name] = { unit_price: price.unit_price ?? '', delivery_date: price.delivery_date || '' };
  });
  return {
    ...slot,
    slotKey: `saved-${group.supplier}-${index}`,
    original_supplier: group.supplier,
    supplier: group.supplier,
    payment_method: group.payment_method || '',
    currency: group.currency || 'CNY',
    tax_rate: group.tax_rate ?? 13,
    contract_entity: group.contract_entity || '示例企业032有限公司',
    is_recommended: Boolean(group.is_recommended),
    is_selected: Boolean(group.is_selected),
    package_total: group.package_total,
    note: group.note || '',
    payment_plan: (group.payment_plan || []).map((row) => ({ ...row })),
    prices,
  };
}
function addBlankSupplierSlot() {
  const slot = emptySupplierDraft(activeApproval.value);
  slot.slotKey = `new-${Date.now()}-${supplierSlots.value.length}`;
  supplierSlots.value.push(slot);
}
function syncSupplierSlots(approval = activeApproval.value) {
  const groups = approval?.supplier_comparisons || [];
  supplierSlots.value = groups.map((group, index) => supplierSlotFromGroup(group, index));
  while (supplierSlots.value.length < 3) addBlankSupplierSlot();
}

function materialCategory(line) {
  const parts = String(line?.material_code || '').split('.');
  return parts.length > 1 ? parts.slice(0, -1).join('.') : '-';
}
function statusClass(value) {
  if (['已关闭', '已通过', '已转PO', '已付款'].includes(value)) return 'status-done';
  if (['已拒绝', '不合格', '已取消'].includes(value)) return 'status-danger';
  if (['草稿', '待采购', '待审批', '待验收', '待合同复核', '待电子用印', '审批中', '审批通过', '部分付款'].includes(value)) return 'status-wait';
  return 'status-active';
}
function setToggle(setRef, key, checked) {
  const next = new Set(setRef.value);
  checked ? next.add(key) : next.delete(key);
  setRef.value = next;
}
function togglePr(pr, line, checked) {
  const key = keyOfPr(pr, line);
  setToggle(selectedPrLines, key, checked);
  if (checked && !priceQuantities.value[key]) priceQuantities.value[key] = line.remaining_quantity;
}
function selectAllPrLines() {
  const available = filteredPrs.value.flatMap((pr) => (pr.lines || []).filter((line) => Number(line.remaining_quantity) > 0).map((line) => ({ pr, line })));
  const all = selectedPrLines.value.size !== available.length;
  selectedPrLines.value = new Set(all ? available.map(({ pr, line }) => keyOfPr(pr, line)) : []);
  if (all) available.forEach(({ pr, line }) => { priceQuantities.value[keyOfPr(pr, line)] ||= line.remaining_quantity; });
}
async function reloadAll() {
  clearMessage();
  const requests = [];
  if (canViewPrice) requests.push(prLoader.reload(), approvalLoader.reload());
  if (canViewPo) requests.push(poLoader.reload());
  await Promise.all(requests);
  if (activeApproval.value) {
    activeApproval.value = approvals.value.find((item) => item.name === activeApproval.value.name) || null;
    syncSupplierSlots(activeApproval.value);
  }
  if (activePo.value) activePo.value = pos.value.find((item) => item.name === activePo.value.name) || null;
}
async function refreshApproval(name) {
  await Promise.all([approvalLoader.reload(), prLoader.reload(), poLoader.reload()]);
  activeApproval.value = approvals.value.find((item) => item.name === name) || null;
  syncSupplierSlots(activeApproval.value);
}
async function refreshPo(name) {
  await poLoader.reload();
  activePo.value = pos.value.find((item) => item.name === name) || null;
  initPoDrafts(activePo.value);
}
async function makeApproval() {
  clearMessage();
  const lines = [];
  prs.value.forEach((pr) => (pr.lines || []).forEach((line) => {
    const key = keyOfPr(pr, line);
    if (selectedPrLines.value.has(key)) lines.push({ source_pr: pr.name, source_pr_line: line.name, quantity: Number(priceQuantities.value[key]) });
  }));
  if (!lines.length) return fail(null, '请先选择需要比价的 PR 物料');
  try {
    const result = await actions.createApproval.submit({ lines: JSON.stringify(lines) });
    notice.value = result.name + ' 已生成，请维护候选供应商报价（可按实际询价结果部分填写）';
    selectedPrLines.value = new Set();
    priceQuantities.value = {};
    await refreshApproval(result.name);
    priceView.value = 'approvals';
  } catch (err) { fail(err, '生成价格审批单失败'); }
}
function emptySupplierDraft(approval = null) {
  const prices = {};
  (approval?.lines || []).forEach((line) => {
    prices[line.name] = { unit_price: '', delivery_date: '' };
  });
  return {
    original_supplier: '', supplier: '', payment_method: '', currency: 'CNY', tax_rate: 13,
    contract_entity: '示例企业032有限公司', is_recommended: false, note: '', prices,
    payment_plan: [{ installment_name: '验收合格后全额付款', payment_stage: '到货后全额付款', percentage: 100, amount: '', planned_date: '', trigger_condition: '全部到货并验收通过', invoice_requirement: '付款前提供' }],
  };
}
function supplierPackageTotal(slot) {
  return (activeApproval.value?.lines || []).reduce((sum, line) => sum + Number(slot.prices[line.name]?.unit_price || 0) * Number(line.quantity || 0), 0);
}
function syncSupplierPlanAmount(slot) {
  if (slot.payment_plan.length === 1) slot.payment_plan[0].amount = supplierPackageTotal(slot);
}
function addSupplierPlanRow(slot) {
  slot.payment_plan.push({ installment_name: `第${slot.payment_plan.length + 1}期`, payment_stage: '尾款', percentage: 0, amount: 0, planned_date: '', trigger_condition: '验收通过', invoice_requirement: '付款前提供' });
}
function removeSupplierPlanRow(slot, index) { if (slot.payment_plan.length > 1) slot.payment_plan.splice(index, 1); }
async function saveSupplierSlot(slot) {
  clearMessage();
  const supplier = String(slot.supplier || '').trim();
  if (!supplier) { error.value = '请先填写供应商名称'; return; }
  const prices = (activeApproval.value?.lines || []).map((line) => ({
    price_line: line.name,
    unit_price: slot.prices[line.name]?.unit_price === '' || slot.prices[line.name]?.unit_price == null ? '' : Number(slot.prices[line.name].unit_price),
    delivery_date: slot.prices[line.name]?.delivery_date || '',
  }));
  try {
    await actions.saveSupplier.submit({
      price_approval: activeApproval.value.name,
      original_supplier: slot.original_supplier || '',
      supplier,
      payment_method: slot.payment_method || '',
      currency: slot.currency || 'CNY',
      tax_rate: Number(slot.tax_rate || 0),
      contract_entity: slot.contract_entity || '',
      is_recommended: slot.is_recommended ? 1 : 0,
      note: slot.note || '',
      payment_plan: JSON.stringify(slot.payment_plan || []),
      prices: JSON.stringify(prices),
    });
    notice.value = supplier + ' 的报价方案已保存（未报价物料保持空白）';
    await refreshApproval(activeApproval.value.name);
  } catch (err) { fail(err, '保存供应商报价失败'); }
}
async function removeSupplierComparison(group) {
  if (!group?.original_supplier) return;
  if (!window.confirm('确认删除 ' + group.supplier + ' 对整张价格审批单的报价？')) return;
  clearMessage();
  try {
    await actions.deleteSupplier.submit({ price_approval: activeApproval.value.name, supplier: group.original_supplier });
    notice.value = group.supplier + ' 的报价已删除';
    await refreshApproval(activeApproval.value.name);
  } catch (err) { fail(err, '删除供应商报价失败'); }
}
async function chooseSupplierComparison(group) {
  clearMessage();
  if (!group?.original_supplier) return;
  try {
    await actions.chooseSupplier.submit({ price_approval: activeApproval.value.name, supplier: group.original_supplier });
    notice.value = '已选择 ' + group.supplier + '，有报价物料将进入 PO';
    await refreshApproval(activeApproval.value.name);
  } catch (err) { fail(err, '选择成交供应商失败'); }
}
async function saveSummary(showNotice = true) {
  if (!activeApproval.value || activeApproval.value.status !== '草稿') return true;
  const value = String(summaryDraft.value || '').trim();
  if (!value) {
    if (showNotice) { error.value = '请填写采购比价总结'; return false; }
    throw new Error('请填写采购比价总结');
  }
  try {
    const result = await actions.updateSummary.submit({ name: activeApproval.value.name, summary: value });
    activeApproval.value = result;
    if (showNotice) { notice.value = '采购比价总结已保存'; error.value = ''; }
    return true;
  } catch (err) {
    if (showNotice) { fail(err, '保存采购比价总结失败'); return false; }
    throw err;
  }
}
async function submitCurrent() {
  clearMessage();
  try {
    await saveSummary(false);
    await actions.submitApproval.submit({ name: activeApproval.value.name });
    notice.value = activeApproval.value.name + ' 已提交演示员工21审批';
    await refreshApproval(activeApproval.value.name);
  } catch (err) { fail(err, '提交价格审批失败'); }
}
async function approveCurrent() {
  clearMessage();
  try {
    const result = await actions.approveApproval.submit({ name: activeApproval.value.name });
    notice.value = '审批通过，已按商业条件生成 ' + result.po_names.length + ' 张 PO 草稿';
    await refreshApproval(activeApproval.value.name);
  } catch (err) { fail(err, '价格审批失败'); }
}
async function withdrawCurrent() {
  if (!window.confirm('撤回后价格审批单回到草稿，已占用的 PR 数量会释放，是否继续？')) return;
  clearMessage();
  try {
    await actions.withdrawApproval.submit({ name: activeApproval.value.name });
    notice.value = '已撤回，可修改后重新提交';
    await refreshApproval(activeApproval.value.name);
  } catch (err) { fail(err, '撤回价格审批失败'); }
}
async function cancelCurrent() {
  if (!window.confirm('取消后将终止价格审批单并释放 PR 数量，是否继续？')) return;
  clearMessage();
  try {
    await actions.cancelApproval.submit({ name: activeApproval.value.name });
    notice.value = '价格审批单已取消，物料已退回 PR';
    await refreshApproval(activeApproval.value.name);
  } catch (err) { fail(err, '取消价格审批失败'); }
}
function openApproval(item) {
  activeApproval.value = item;
  summaryDraft.value = item?.summary || '';
  approvalView.value = 'compare';
  syncSupplierSlots(item);
  priceView.value = 'approvals';
}
function syncRouteContext() {
  tab.value = (route.path === '/approval/procurement/po' || route.query.tab === 'po') && canViewPo ? 'po' : (canViewPrice ? 'price' : 'po');
  if (tab.value === 'po') {
    const requestedPo = String(route.query.po || '').trim();
    const linkedPo = requestedPo && pos.value.find((item) => item.name === requestedPo);
    const currentPo = activePo.value && pos.value.find((item) => item.name === activePo.value.name);
    if (linkedPo || currentPo || pos.value[0]) openPo(linkedPo || currentPo || pos.value[0]);
    else activePo.value = null;
    return;
  }
  const requested = String(route.query.approval || '').trim();
  const linked = requested && approvals.value.find((item) => item.name === requested);
  const actionable = approvals.value.find((item) => ['草稿', '待审批'].includes(item.status));
  const hasPendingPr = prs.value.some((pr) => (pr.lines || []).some((line) => Number(line.remaining_quantity) > 0));
  if (route.query.view === 'source' || (hasPendingPr && !actionable && !linked)) priceView.value = 'source';
  else priceView.value = 'approvals';
  const current = activeApproval.value && approvals.value.find((item) => item.name === activeApproval.value.name);
  const target = linked || actionable || current || approvals.value[0];
  if (target && activeApproval.value?.name !== target.name) openApproval(target);
  else if (!target) activeApproval.value = null;
}
watch([approvals, prs, pos, () => route.query.request, () => route.query.approval, () => route.query.po, () => route.query.tab, () => route.query.view], syncRouteContext, { immediate: true });
function initPoDrafts(po) {
  deliveryDraft.value = {};
  receiptDraft.value = {};
  inspectionDraft.value = {};
  (po?.lines || []).forEach((line) => {
    deliveryDraft.value[line.name] = line.contract_delivery_date || '';
    receiptDraft.value[line.name] = '';
    inspectionDraft.value[line.name] = '';
  });
  paymentDraft.value = { amount: '', reference: '' };
  paymentPlanDraft.value = '';
  contractDraft.value = {
    seal_user: po?.contract_seal_user || 'admin@staff.example.invalid',
    supplier_legal_name: po?.contract_supplier_legal_name || po?.supplier || '',
    contract_delivery_date: po?.contract_delivery_date || '',
  };
}
function openPo(po) { activePo.value = po; initPoDrafts(po); }
async function saveDelivery() {
  clearMessage();
  try {
    const lines = activePo.value.lines.map((line) => ({ line: line.name, contract_delivery_date: deliveryDraft.value[line.name] }));
    await actions.updateDelivery.submit({ name: activePo.value.name, lines: JSON.stringify(lines) });
    notice.value = '合同交期已保存';
    await refreshPo(activePo.value.name);
  } catch (err) { fail(err, '保存合同交期失败'); }
}
async function confirmPo() {
  clearMessage();
  try {
    await actions.confirmPo.submit({ name: activePo.value.name });
    notice.value = activePo.value.name + ' 已确认，进入合同复核';
    await refreshPo(activePo.value.name);
  } catch (err) { fail(err, '确认 PO 失败'); }
}
onMounted(reloadAll);
async function savePoContract() {
  clearMessage();
  try {
    await actions.savePoContract.submit({ name: activePo.value.name, seal_user: contractDraft.value.seal_user, supplier_legal_name: contractDraft.value.supplier_legal_name, contract_delivery_date: contractDraft.value.contract_delivery_date });
    notice.value = 'PO 合同草稿已生成';
    await refreshPo(activePo.value.name);
  } catch (err) { fail(err, '生成 PO 合同草稿失败'); }
}
async function reviewPoContract() {
  clearMessage();
  try { await actions.reviewPoContract.submit({ name: activePo.value.name }); notice.value = 'PO 合同已复核，等待电子用印'; await refreshPo(activePo.value.name); }
  catch (err) { fail(err, '复核 PO 合同失败'); }
}
async function sealPoContract() {
  clearMessage();
  try { await actions.sealPoContract.submit({ name: activePo.value.name }); notice.value = 'PO 已完成电子用印并生效'; await refreshPo(activePo.value.name); }
  catch (err) { fail(err, 'PO 电子用印失败'); }
}
async function pushPaymentRequest() {
  clearMessage();
  if (!paymentPlanDraft.value) return fail(null, '请先选择付款计划期次');
  try { const result = await actions.pushPaymentRequest.submit({ name: activePo.value.name, payment_plan_row: paymentPlanDraft.value }); notice.value = `已生成采购付款 ${result.payment_request} 并进入审批`; await refreshPo(activePo.value.name); }
  catch (err) { fail(err, '下推采购付款失败'); }
}
async function approvePaymentStep() {
  clearMessage();
  if (!paymentPlanDraft.value) return fail(null, '请先选择付款计划期次');
  try { await actions.approvePaymentStep.submit({ name: activePo.value.name, payment_plan_row: paymentPlanDraft.value }); notice.value = '当前付款审批节点已处理'; await refreshPo(activePo.value.name); }
  catch (err) { fail(err, '处理付款审批失败'); }
}
async function recordReceipt() {
  clearMessage();
  const lines = activePo.value.lines.filter((line) => Number(receiptDraft.value[line.name]) > 0)
    .map((line) => ({ line: line.name, quantity: Number(receiptDraft.value[line.name]) }));
  if (!lines.length) return fail(null, '请填写至少一项本次到货数量');
  try {
    await actions.receivePo.submit({ name: activePo.value.name, lines: JSON.stringify(lines) });
    notice.value = '到货数量已登记并通知相关人员';
    await refreshPo(activePo.value.name);
  } catch (err) { fail(err, '登记到货失败'); }
}
async function recordInspection() {
  clearMessage();
  const lines = activePo.value.lines.filter((line) => inspectionDraft.value[line.name])
    .map((line) => ({ line: line.name, status: inspectionDraft.value[line.name] }));
  if (!lines.length) return fail(null, '请至少选择一项验收结果');
  try {
    await actions.inspectPo.submit({ name: activePo.value.name, lines: JSON.stringify(lines) });
    notice.value = '验收结果已保存并通知相关人员';
    await refreshPo(activePo.value.name);
  } catch (err) { fail(err, '登记验收失败'); }
}
async function recordPayment() {
  clearMessage();
  try {
    await actions.payPo.submit({ name: activePo.value.name, payment_plan_row: paymentPlanDraft.value, amount: Number(paymentDraft.value.amount), payment_reference: paymentDraft.value.reference });
    notice.value = '付款记录已更新并通知相关人员';
    await refreshPo(activePo.value.name);
  } catch (err) { fail(err, '登记付款失败'); }
}
async function closeCurrentPo() {
  clearMessage();
  try {
    await actions.closePo.submit({ name: activePo.value.name });
    notice.value = activePo.value.name + ' 已完成到货、验收和付款并关闭';
    await refreshPo(activePo.value.name);
  } catch (err) { fail(err, '关闭 PO 失败'); }
}
</script>
<template>
  <div class="chain-shell">
    <header class="page-head">
      <div>
        <div class="eyebrow">采购申请 · 价格审批</div>
        <h1>价格评审表</h1>
        <p>采购可录入多个供应商，并按实际询价结果填写部分物料；演示员工37统一选择一个成交供应商；有报价的物料进入 PO，未报价的物料退回 PR。</p>
      </div>
      <button type="button" class="icon-button" title="刷新全部数据" :disabled="prLoader.loading || approvalLoader.loading || poLoader.loading" @click="reloadAll">
        <FeatherIcon name="refresh-cw" class="h-4 w-4" />
      </button>
    </header>

    <div v-if="notice" class="alert success">{{ notice }}</div>
    <div v-if="error" class="alert danger">{{ error }}</div>
    <div v-if="contextRequest" class="context-bar">
      <div><strong>当前仅查看这张采购申请的完整链路</strong><span>{{ contextSummary }}</span></div>
      <router-link :to="{ name: 'procurement-price-approvals' }">查看全部采购链路</router-link>
    </div>

    <nav class="main-tabs" aria-label="采购链路（价格审批与 PO）">
      <button v-for="item in tabs" :key="item.key" type="button" :class="{ active: tab === item.key }" @click="tab = item.key">
        <FeatherIcon :name="item.icon" class="h-4 w-4" />
        <span>{{ item.label }}</span>
        <span v-if="item.key === 'price'" class="count">{{ approvals.length }}</span>
        <span v-else class="count">{{ pos.length }}</span>
      </button>
    </nav>

    <section v-if="tab === 'price'" class="workspace">
      <div class="sub-tabs">
        <button type="button" :class="{ active: priceView === 'source' }" @click="priceView = 'source'">
          PR 待比价物料 <span>{{ prs.reduce((sum, item) => sum + (item.lines || []).filter((line) => Number(line.remaining_quantity) > 0).length, 0) }}</span>
        </button>
        <button type="button" :class="{ active: priceView === 'approvals' }" @click="priceView = 'approvals'">
          价格审批单 <span>{{ approvals.length }}</span>
        </button>
      </div>

      <div v-if="priceView === 'source'">
        <div class="section-bar">
          <div><h2>从 PR 选择物料</h2><span>可跨 PR、OA 和项目合并</span></div>
          <div class="bar-actions">
            <select v-model="prAvailability" class="source-filter" aria-label="PR 可用状态筛选">
              <option value="available">可提价格审批</option>
              <option value="all">全部 PR</option>
              <option value="exhausted">已无可选物料</option>
            </select>
            <label class="search-box"><FeatherIcon name="search" class="h-4 w-4" /><input v-model="prSearch" placeholder="搜索 PR、OA、项目或物料" /></label>
            <button type="button" class="primary-button" :disabled="!selectedPrCount" v-if="canEditPrice" @click="makeApproval">
              <FeatherIcon name="file-plus" class="h-4 w-4" />生成价格审批单 <span v-if="selectedPrCount">{{ selectedPrCount }}</span>
            </button>
          </div>
        </div>
        <div class="table-frame">
          <table class="data-grid min-pr-grid">
            <thead><tr>
              <th class="check-cell"><input type="checkbox" @change="selectAllPrLines" /></th>
              <th>PR / 物料层级</th><th>物料流水号</th><th>物料编号</th><th>来源 OA / 项目</th><th>物料名称</th><th>规格型号</th>
              <th class="number">PR 数量</th><th class="number">已占用</th><th class="number">可选数量</th><th class="number quantity-column">本次比价数量</th>
            </tr></thead>
            <tbody>
              <template v-for="pr in filteredPrs" :key="pr.name">
                <tr class="source-pr-group-row">
                  <th colspan="11"><div class="source-pr-group">
                    <strong>{{ pr.name }}</strong>
                    <span :class="availableLineCount(pr) ? 'available-source' : 'exhausted-source'">{{ availableLineCount(pr) ? `可提价格审批 ${availableLineCount(pr)} 项` : '已无可选物料' }}</span>
                    <span>单据状态 {{ pr.status || '待采购' }}</span><span>{{ pr.lines.length }} 项物料</span>
                  </div></th>
                </tr>
                <tr v-for="(line, lineIndex) in pr.lines" :key="line.name" :class="{ muted: Number(line.remaining_quantity) <= 0, selected: selectedPrLines.has(keyOfPr(pr, line)) }">
                  <td class="check-cell"><input type="checkbox" :disabled="Number(line.remaining_quantity) <= 0" :checked="selectedPrLines.has(keyOfPr(pr, line))" @change="togglePr(pr, line, $event.target.checked)" /></td>
                  <td class="source-pr-child"><span>物料 {{ lineIndex + 1 }}</span></td>
                  <td><strong class="serial">{{ line.material_serial }}</strong></td>
                  <td><strong class="code-cell">{{ line.material_code || '-' }}</strong></td>
                  <td><strong>{{ line.source_request }}</strong><small>{{ line.project || '-' }}</small></td>
                  <td><strong>{{ line.item_name }}</strong></td><td>{{ line.specification || '-' }}</td>
                  <td class="number">{{ quantity(line.quantity) }} {{ line.unit }}</td>
                  <td class="number">{{ quantity(Number(line.quantity) - Number(line.remaining_quantity)) }} {{ line.unit }}</td>
                  <td class="number remaining">{{ quantity(line.remaining_quantity) }} {{ line.unit }}</td>
                  <td class="number"><input v-model.number="priceQuantities[keyOfPr(pr, line)]" class="quantity-input" type="number" min="0.0001" :max="line.remaining_quantity" step="0.0001" :disabled="!selectedPrLines.has(keyOfPr(pr, line))" /></td>
                </tr>
              </template>
              <tr v-if="!filteredPrs.length"><td colspan="11" class="empty-state">{{ contextRequest ? `${contextRequest} 当前没有可询价的 PR 物料；请先确认 PMC 已生成 PR，或查看该 OA 的价格审批单。` : '当前没有符合条件的 PR 物料' }}</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-else class="master-detail">
        <aside class="record-list">
          <div class="list-head"><strong>价格审批单</strong><span>{{ approvals.length }}</span></div>
          <button v-for="item in approvals" :key="item.name" type="button" :class="{ active: activeApproval?.name === item.name }" @click="openApproval(item)">
            <div><strong>{{ item.name }}</strong><span :class="['status-pill', statusClass(item.status)]">{{ item.status }}</span></div>
            <small>{{ item.source_prs || '无来源 PR' }}</small>
            <footer><span>{{ item.lines.length }} 项</span><b>{{ money(item.total_amount) }}</b></footer>
          </button>
          <div v-if="!approvals.length" class="empty-state">暂无价格审批单</div>
        </aside>

        <article v-if="activeApproval" class="detail-pane">
          <header class="document-head">
            <div>
              <div class="document-number">{{ activeApproval.name }}</div>
              <div class="document-meta">
                <span :class="['status-pill', statusClass(activeApproval.status)]">{{ activeApproval.status }}</span>
                <span>来源 {{ activeApproval.source_prs }}</span>
                <span>{{ activeApproval.lines.length }} 项物料</span>
              </div>
            </div>
            <div class="document-total"><small>{{ (activeApproval.lines || []).some((line) => line.selected_supplier) ? '成交总额' : '已选报价总额' }}</small><strong>{{ money(activeApproval.total_amount) }}</strong></div>
            <div class="document-actions">
              <button v-if="canEditPrice && activeApproval.status === '草稿'" type="button" class="primary-button" @click="submitCurrent"><FeatherIcon name="send" class="h-4 w-4" />提交价格审批</button>
              <button v-if="canEditPrice && activeApproval.status === '草稿'" type="button" class="secondary-button" @click="cancelCurrent"><FeatherIcon name="x-circle" class="h-4 w-4" />取消价格审批</button>
              <button v-if="canEditPrice && activeApproval.status === '待审批'" type="button" class="secondary-button" @click="withdrawCurrent"><FeatherIcon name="corner-up-left" class="h-4 w-4" />撤回修改</button>
              <button v-if="activeApproval.can_select_quote && activeApproval.status === '待审批' && supplierComparisons().some((group) => group.is_selected)" type="button" class="approve-button" @click="approveCurrent"><FeatherIcon name="check-circle" class="h-4 w-4" />演示员工37审批通过</button>
            </div>
          </header>

          <div class="approval-view-tabs" role="tablist" aria-label="价格审批单内容">
            <button type="button" :class="{ active: approvalView === 'compare' }" @click="approvalView = 'compare'">供应商比价</button>
            <button type="button" :class="{ active: approvalView === 'requirement' }" @click="approvalView = 'requirement'">需求内容</button>
          </div>

          <section v-if="approvalView === 'compare'" class="supplier-comparison-section">
            <div class="comparison-title">
              <div><strong>供应商比价</strong><span>采购可在每个供应商栏位内填写报价；未报价物料保持空白；演示员工37审批时选择一个成交供应商</span></div>
              <span class="supplier-count">{{ supplierCount() }} 家已填写供应商</span>
            </div>

            <div class="quote-matrix-frame">
              <div class="quote-matrix-scroll">
                <table class="quote-matrix" :style="{ width: `${397 + supplierSlots.length * 360}px` }">
                  <colgroup>
                    <col class="col-index" />
                    <col class="col-serial" />
                    <col class="col-code" />
                    <col class="col-name" />
                    <col class="col-quantity" />
                    <template v-for="slot in supplierSlots" :key="slot.slotKey + ':cols'">
                      <col class="col-unit-price" />
                      <col class="col-total-price" />
                      <col class="col-delivery" />
                    </template>
                  </colgroup>
                  <thead>
                    <tr class="supplier-heading-row">
                      <th rowspan="2" class="sticky-col sticky-index number">序号</th>
                      <th rowspan="2" class="sticky-col sticky-serial">物料流水号</th>
                      <th rowspan="2" class="sticky-col sticky-code">物料编号</th>
                      <th rowspan="2" class="sticky-col sticky-name">物料名称</th>
                      <th rowspan="2" class="sticky-col sticky-quantity number">数量</th>
                      <th v-for="(slot, index) in supplierSlots" :key="slot.slotKey" colspan="3" :class="['supplier-group-heading', { recommended: slot.is_recommended, chosen: slot.is_selected }]">
                        <div class="supplier-heading-content">
                          <input v-if="canEditPrice && activeApproval.status === '草稿'" v-model="slot.supplier" class="supplier-inline supplier-name-input" :placeholder="`供应商 ${index + 1}`" />
                          <strong v-else>{{ slot.supplier || `供应商 ${index + 1}` }}</strong>
                          <span v-if="slot.is_recommended" class="recommend-label">采购推荐</span>
                          <span v-if="slot.is_selected" class="chosen-label">演示员工37已选</span>
                        </div>
                      </th>
                    </tr>
                    <tr class="quote-heading-row">
                      <template v-for="slot in supplierSlots" :key="slot.slotKey + ':heading'">
                        <th :class="{ 'matrix-recommended': slot.is_recommended, 'matrix-chosen': slot.is_selected }">供应商报价</th>
                        <th :class="{ 'matrix-recommended': slot.is_recommended, 'matrix-chosen': slot.is_selected }">总价</th>
                        <th :class="{ 'matrix-recommended': slot.is_recommended, 'matrix-chosen': slot.is_selected }">货期</th>
                      </template>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(line, index) in activeApproval.lines" :key="line.name">
                        <td class="sticky-col sticky-index number muted-cell">{{ index + 1 }}</td>
                        <td class="sticky-col sticky-serial"><strong class="serial">{{ line.material_serial }}</strong></td>
                        <td class="sticky-col sticky-code code-cell">{{ line.material_code || '-' }}</td>
                        <td class="sticky-col sticky-name item-cell"><strong>{{ line.item_name }}</strong></td>
                        <td class="sticky-col sticky-quantity number quantity-cell">{{ quantity(line.quantity) }} {{ line.unit }}</td>
                        <template v-for="slot in supplierSlots" :key="slot.slotKey + ':' + line.name">
                          <td :class="['number supplier-first', { 'matrix-chosen': slot.is_selected, 'matrix-recommended': slot.is_recommended }]">
                            <input v-if="canEditPrice && activeApproval.status === '草稿'" v-model.number="slot.prices[line.name].unit_price" class="supplier-inline number-input" type="number" min="0.01" step="0.01" placeholder="单价" />
                            <span v-else>{{ comparisonPrice(slot, line).unit_price == null || comparisonPrice(slot, line).unit_price === '' ? '-' : money(comparisonPrice(slot, line).unit_price, slot.currency) }}</span>
                          </td>
                          <td :class="['number strong-number', { 'matrix-chosen': slot.is_selected, 'matrix-recommended': slot.is_recommended }]">{{ comparisonPrice(slot, line).unit_price === '' || comparisonPrice(slot, line).unit_price == null ? '-' : money(Number(comparisonPrice(slot, line).unit_price || 0) * Number(line.quantity || 0), slot.currency) }}</td>
                          <td :class="[{ 'matrix-chosen': slot.is_selected, 'matrix-recommended': slot.is_recommended }]">
                            <input v-if="canEditPrice && activeApproval.status === '草稿'" v-model="slot.prices[line.name].delivery_date" class="supplier-inline date-input" type="date" />
                            <span v-else>{{ comparisonPrice(slot, line).delivery_date || '-' }}</span>
                          </td>
                        </template>
                    </tr>
                  </tbody>
                  <tfoot>
                    <tr class="quote-total-row">
                      <th colspan="5">报价合计</th>
                      <template v-for="slot in supplierSlots" :key="slot.slotKey + ':total'">
                        <td class="supplier-first muted-cell">-</td>
                        <td class="number strong-number">{{ money((activeApproval.lines || []).reduce((sum, line) => sum + (Number(comparisonPrice(slot, line).unit_price || 0) * Number(line.quantity || 0)), 0), slot.currency) }}</td>
                        <td class="muted-cell">-</td>
                      </template>
                    </tr>
                    <tr>
                      <th colspan="5">付款方式</th>
                      <td v-for="(slot, index) in supplierSlots" :key="slot.slotKey + ':payment'" colspan="3">
                        <div class="supplier-footer-content">
                          <input v-if="canEditPrice && activeApproval.status === '草稿'" v-model="slot.payment_method" class="supplier-inline full-input" placeholder="填写付款方式" />
                          <span v-else>{{ slot.payment_method || '-' }}</span>
                        </div>
                      </td>
                    </tr>
                    <tr class="supplier-plan-row">
                      <th colspan="5">付款计划</th>
                      <td v-for="(slot, index) in supplierSlots" :key="slot.slotKey + ':plan'" colspan="3">
                        <div class="supplier-footer-content supplier-plan">
                          <template v-if="canEditPrice && activeApproval.status === '草稿'">
                            <div v-for="(plan, planIndex) in slot.payment_plan" :key="planIndex" class="plan-line">
                              <label class="plan-field"><span>期次</span><input v-model="plan.installment_name" class="supplier-inline" placeholder="期次" /></label>
                              <label class="plan-field"><span>付款阶段</span><select v-model="plan.payment_stage" class="supplier-inline"><option>预付款</option><option>到货款</option><option>尾款</option><option>到货后全额付款</option></select></label>
                              <label class="plan-field"><span>比例（%）</span><input v-model.number="plan.percentage" class="supplier-inline number-input" type="number" min="0.01" max="100" step="0.01" placeholder="比例%" /></label>
                              <label class="plan-field"><span>金额</span><input v-model.number="plan.amount" class="supplier-inline number-input" type="number" min="0.01" step="0.01" placeholder="金额" /></label>
                              <label class="plan-field"><span>计划付款日期</span><input v-model="plan.planned_date" class="supplier-inline" type="date" /></label>
                              <label class="plan-field"><span>触发条件</span><input v-model="plan.trigger_condition" class="supplier-inline" placeholder="触发条件" /></label>
                              <label class="plan-field"><span>发票要求</span><select v-model="plan.invoice_requirement" class="supplier-inline"><option>付款前提供</option><option>付款后提供</option><option>无需发票</option></select></label>
                              <button type="button" class="plan-remove" title="删除期次" :disabled="slot.payment_plan.length === 1" @click="removeSupplierPlanRow(slot, planIndex)"><FeatherIcon name="trash-2" class="h-3 w-3" /></button>
                            </div>
                            <div class="plan-actions"><button type="button" @click="addSupplierPlanRow(slot)"><FeatherIcon name="plus" class="h-3 w-3" />增加期次</button><button type="button" @click="syncSupplierPlanAmount(slot)">按报价总额</button></div>
                          </template>
                          <div v-else class="readonly-plan"><span v-for="plan in slot.payment_plan" :key="plan.installment_no">{{ plan.installment_name }} · {{ plan.payment_stage }} · {{ plan.percentage }}% · {{ money(plan.amount, slot.currency) }} · {{ plan.trigger_condition }} · {{ plan.invoice_requirement }}</span></div>
                        </div>
                      </td>
                    </tr>
                    <tr>
                      <th colspan="5">币种 / 税率 / 合同主体</th>
                      <td v-for="(slot, index) in supplierSlots" :key="slot.slotKey + ':terms'" colspan="3">
                        <div class="supplier-footer-content">
                          <div v-if="canEditPrice && activeApproval.status === '草稿'" class="supplier-terms-inline">
                            <select v-model="slot.currency" class="supplier-inline"><option>CNY</option><option>USD</option><option>EUR</option><option>JPY</option></select>
                            <input v-model.number="slot.tax_rate" class="supplier-inline tax-input" type="number" min="0" max="100" step="0.01" placeholder="税率" />
                            <input v-model="slot.contract_entity" class="supplier-inline contract-input" placeholder="合同主体" />
                          </div>
                          <span v-else>{{ slot.currency || 'CNY' }} / {{ slot.tax_rate || 0 }}% · {{ slot.contract_entity || '-' }}</span>
                        </div>
                      </td>
                    </tr>
                    <tr>
                      <th colspan="5">报价说明</th>
                      <td v-for="(slot, index) in supplierSlots" :key="slot.slotKey + ':note'" colspan="3">
                        <div class="supplier-footer-content">
                          <input v-if="canEditPrice && activeApproval.status === '草稿'" v-model="slot.note" class="supplier-inline full-input" placeholder="交付能力、质量、商务说明" />
                          <span v-else>{{ slot.note || '-' }}</span>
                        </div>
                      </td>
                    </tr>
                    <tr class="supplier-actions-row">
                      <th colspan="5">供应商方案</th>
                      <td v-for="(slot, index) in supplierSlots" :key="slot.slotKey + ':actions'" colspan="3">
                        <div class="supplier-footer-content">
                          <div class="supplier-summary-actions">
                            <label v-if="canEditPrice && activeApproval.status === '草稿' && slot.supplier" class="recommend-toggle-inline"><input v-model="slot.is_recommended" type="checkbox" />采购推荐</label>
                            <span v-if="slot.is_selected" class="chosen-label">演示员工37已选</span>
                            <div class="row-actions package-actions">
                              <button v-if="activeApproval.can_select_quote && slot.original_supplier && !slot.is_selected" type="button" title="演示员工37选择该供应商作为成交供应商" @click="chooseSupplierComparison(slot)"><FeatherIcon name="check-circle" class="h-4 w-4" /></button>
                              <button v-if="canEditPrice && activeApproval.status === '草稿' && slot.supplier" type="button" class="save-slot-button" title="保存该供应商报价" @click="saveSupplierSlot(slot)"><FeatherIcon name="save" class="h-4 w-4" />保存</button>
                              <button v-if="canEditPrice && activeApproval.status === '草稿' && slot.original_supplier" type="button" class="danger-icon" title="删除供应商报价" @click="removeSupplierComparison(slot)"><FeatherIcon name="trash-2" class="h-4 w-4" /></button>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  </tfoot>
                </table>
                <button v-if="canEditPrice && activeApproval.status === '草稿'" type="button" class="add-supplier-column" title="新增供应商栏位" @click="addBlankSupplierSlot"><FeatherIcon name="plus" class="h-4 w-4" /></button>
              </div>
            </div>
          </section>

          <section v-else class="requirement-content bottom-section">
            <div class="summary-title"><strong>需求内容</strong><span>完整保留 OA、PR 来源及每项物料的规格参数，此处只读</span></div>
            <div class="requirement-facts">
              <dl><dt>需求单号</dt><dd>{{ activeApproval.source_requests || '-' }}</dd></dl>
              <dl><dt>来源 PR</dt><dd>{{ activeApproval.source_prs || '-' }}</dd></dl>
              <dl><dt>使用部门</dt><dd>{{ activeApproval.source_departments || '-' }}</dd></dl>
              <dl><dt>需求人</dt><dd>{{ activeApproval.source_requesters || '-' }}</dd></dl>
              <dl><dt>项目</dt><dd>{{ activeApproval.source_projects || '-' }}</dd></dl>
            </div>
            <div class="requirement-table-frame">
              <table class="requirement-table">
                <thead><tr><th>序号</th><th>物料流水号</th><th>物料编号</th><th>物料名称</th><th>规格参数</th><th>产品描述</th><th>品牌</th><th class="number">数量</th><th>单位</th><th>OA预计交期</th><th>项目</th></tr></thead>
                <tbody>
                  <tr v-for="(line, index) in activeApproval.lines" :key="line.name">
                      <td>{{ index + 1 }}</td>
                      <td class="serial">{{ line.material_serial }}</td>
                      <td class="code-cell">{{ line.material_code || '-' }}</td>
                      <td><strong>{{ line.item_name || '-' }}</strong></td>
                      <td class="wrap-cell">{{ line.specification || '-' }}</td>
                      <td class="wrap-cell">{{ line.product_desc || '-' }}</td>
                      <td>{{ line.brand || '-' }}</td>
                      <td class="number">{{ quantity(line.quantity) }}</td>
                      <td>{{ line.unit || '-' }}</td>
                      <td>{{ line.expected_delivery_date || '-' }}</td>
                      <td>{{ line.project || activeApproval.source_projects || '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="review-summary bottom-section">
            <div class="summary-title"><strong>采购比价总结</strong><span>推荐供应商、价格、交期、付款方式及选择依据</span></div>
            <div v-if="canEditPrice && activeApproval.status === '草稿'" class="summary-editor">
              <textarea v-model="summaryDraft" rows="3" maxlength="2000" placeholder="填写综合比较结论和推荐理由"></textarea>
              <button type="button" class="secondary-button" @click="saveSummary()"><FeatherIcon name="save" class="h-4 w-4" />保存总结</button>
            </div>
            <p v-else>{{ activeApproval.summary || '未填写' }}</p>
          </section>

          <section class="approval-trail bottom-section">
            <div class="trail-title"><FeatherIcon name="activity" class="h-4 w-4" /><strong>会签 / 审批轨迹</strong></div>
            <div v-if="activeApproval.steps?.length" class="trail-steps">
              <div v-for="step in activeApproval.steps" :key="step.name" class="trail-step">
                <span :class="['trail-dot', step.status === '已通过' ? 'done' : '']"><FeatherIcon :name="step.status === '已通过' ? 'check' : 'clock'" class="h-3 w-3" /></span>
                <div><strong>{{ step.label }}</strong><small>{{ step.action_by || '待演示员工21处理' }}<template v-if="step.acted_on"> · {{ step.acted_on }}</template></small><p v-if="step.note">{{ step.note }}</p></div>
                <span :class="['status-pill', statusClass(step.status)]">{{ step.status }}</span>
              </div>
            </div>
            <div v-else class="trail-empty">草稿尚未提交审批</div>
          </section>
        </article>
        <div v-else class="detail-empty"><FeatherIcon name="file-text" class="h-8 w-8" /><strong>选择价格审批单查看比价明细</strong></div>
      </div>
    </section>
    <section v-else class="workspace master-detail po-workspace">
      <aside class="record-list">
        <div class="list-head"><strong>PO 合同</strong><span>{{ pos.length }}</span></div>
        <button v-for="po in pos" :key="po.name" type="button" :class="{ active: activePo?.name === po.name }" @click="openPo(po)">
          <div><strong>{{ po.name }}</strong><span :class="['status-pill', statusClass(po.status)]">{{ po.status }}</span></div>
          <small>{{ po.supplier }}</small>
          <footer><span>{{ po.lines?.length || 0 }} 项</span><b>{{ money(po.total_amount, po.currency) }}</b></footer>
        </button>
        <div v-if="!pos.length" class="empty-state">暂无 PO</div>
      </aside>

      <article v-if="activePo" class="detail-pane">
        <header class="document-head">
          <div>
            <div class="document-number">{{ activePo.name }}</div>
            <div class="document-meta">
              <span :class="['status-pill', statusClass(activePo.status)]">{{ activePo.status }}</span>
              <span>{{ activePo.supplier }}</span>
              <span>{{ activePo.payment_method }}</span>
            </div>
          </div>
          <div class="document-total"><small>PO 总额</small><strong>{{ money(activePo.total_amount, activePo.currency) }}</strong></div>
          <div class="document-actions">
            <button v-if="activePo.can_manage_purchase && activePo.status === '草稿'" type="button" class="secondary-button" @click="saveDelivery"><FeatherIcon name="calendar" class="h-4 w-4" />保存合同交期</button>
            <button v-if="activePo.can_manage_purchase && activePo.status === '草稿'" type="button" class="approve-button" @click="confirmPo"><FeatherIcon name="check-circle" class="h-4 w-4" />确认 PO</button>
            <button v-if="activePo.can_manage_purchase && activePo.status === '待合同复核' && activePo.contract_status !== '草稿待复核'" type="button" class="secondary-button" @click="savePoContract"><FeatherIcon name="file-plus" class="h-4 w-4" />生成合同草稿</button>
            <button v-if="activePo.can_manage_purchase && activePo.contract_status === '草稿待复核'" type="button" class="secondary-button" @click="reviewPoContract"><FeatherIcon name="check-square" class="h-4 w-4" />复核合同</button>
            <button v-if="activePo.can_manage_purchase && activePo.contract_status === '待电子用印'" type="button" class="approve-button" @click="sealPoContract"><FeatherIcon name="pen-tool" class="h-4 w-4" />电子用印</button>
            <button v-if="activePo.can_manage_purchase && activePo.status !== '草稿' && activePo.status !== '已关闭'" type="button" class="primary-button" @click="closeCurrentPo"><FeatherIcon name="lock" class="h-4 w-4" />校验并关闭</button>
          </div>
        </header>

        <div class="po-facts">
          <dl><dt>供应商</dt><dd>{{ activePo.supplier }}</dd></dl>
          <dl><dt>付款方式</dt><dd>{{ activePo.payment_method || '-' }}</dd></dl>
          <dl><dt>币种 / 税率</dt><dd>{{ activePo.currency || 'CNY' }} / {{ activePo.tax_rate || 0 }}%</dd></dl>
          <dl><dt>合同主体</dt><dd>{{ activePo.contract_entity || '-' }}</dd></dl>
          <dl><dt>合同状态</dt><dd>{{ activePo.contract_status || '待补充信息' }}</dd></dl>
          <dl><dt>价格审批来源</dt><dd>{{ activePo.source_price_approvals }}</dd></dl>
          <dl class="payment-fact"><dt>付款进度</dt><dd>{{ activePo.payment_status || '待付款' }} · {{ money(activePo.paid_amount, activePo.currency) }} / {{ money(activePo.total_amount, activePo.currency) }}</dd></dl>
        </div>

        <div class="table-frame po-lines">
          <table class="data-grid">
            <thead><tr><th>物料流水号</th><th>物料编号</th><th>来源 OA / PR</th><th>项目</th><th>物料 / 型号</th><th class="number">数量</th><th class="number">单价</th><th class="number">金额</th><th>OA 预计交期</th><th>合同交期</th><th class="number">累计到货</th><th>验收</th></tr></thead>
            <tbody>
              <tr v-for="line in activePo.lines" :key="line.name">
                <td><strong class="serial">{{ line.material_serial }}</strong></td>
                <td class="code-cell">{{ line.material_code || '-' }}</td>
                <td><strong>{{ line.source_request }}</strong><small>{{ line.source_pr }}</small></td>
                <td>{{ line.project || '-' }}</td>
                <td><strong>{{ line.item_name }}</strong><small>{{ line.specification || '-' }}</small></td>
                <td class="number">{{ quantity(line.quantity) }} {{ line.unit }}</td>
                <td class="number">{{ money(line.unit_price, activePo.currency) }}</td>
                <td class="number strong-number">{{ money(line.amount, activePo.currency) }}</td>
                <td>{{ line.expected_delivery_date || '-' }}</td>
                <td><input v-if="activePo.status === '草稿'" v-model="deliveryDraft[line.name]" class="date-input" type="date" /><span v-else>{{ line.contract_delivery_date || '-' }}</span></td>
                <td class="number">{{ quantity(line.received_quantity) }} / {{ quantity(line.quantity) }}</td>
                <td><span :class="['status-pill', statusClass(line.inspection_status)]">{{ line.inspection_status || '未验收' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>

        <section v-if="activePo.payment_plan?.length" class="payment-handoff">
          <div>
            <strong>付款条件与执行已移至采购付款工作台</strong>
            <span>到货资料、验收资料、付款期次条件、付款审批和实际付款在同一入口处理。</span>
          </div>
          <router-link to="/approval/procurement-payment" class="primary-button"><FeatherIcon name="external-link" class="h-4 w-4" />进入采购付款</router-link>
        </section>

        <div v-if="false && !['草稿', '已关闭', '已取消'].includes(activePo.status)" class="execution-grid">
          <section v-if="activePo.can_record_receipt" class="operation-panel">
            <header><FeatherIcon name="truck" class="h-4 w-4" /><strong>到货登记</strong></header>
            <div v-for="line in activePo.lines" :key="line.name" class="operation-row">
              <span><b>{{ line.material_serial }}</b>{{ line.item_name }}</span>
              <span class="balance">未到 {{ quantity(Number(line.quantity) - Number(line.received_quantity)) }} {{ line.unit }}</span>
              <input v-model.number="receiptDraft[line.name]" type="number" min="0" :max="Number(line.quantity) - Number(line.received_quantity)" step="0.0001" placeholder="本次到货" />
            </div>
            <button type="button" class="secondary-button full" @click="recordReceipt"><FeatherIcon name="save" class="h-4 w-4" />保存到货记录</button>
          </section>

          <section v-if="activePo.can_record_inspection" class="operation-panel">
            <header><FeatherIcon name="clipboard" class="h-4 w-4" /><strong>验收登记</strong></header>
            <div v-for="line in activePo.lines" :key="line.name" class="operation-row">
              <span><b>{{ line.material_serial }}</b>{{ line.item_name }}</span>
              <span class="balance">已到 {{ quantity(line.received_quantity) }} {{ line.unit }}</span>
              <select v-model="inspectionDraft[line.name]" :disabled="Number(line.received_quantity) <= 0">
                <option value="">不变</option><option>已通过</option><option>不合格</option><option>退货中</option><option>换货中</option>
              </select>
            </div>
            <button type="button" class="secondary-button full" @click="recordInspection"><FeatherIcon name="check-square" class="h-4 w-4" />保存验收结果</button>
          </section>

          <section class="operation-panel payment-panel">
            <header><FeatherIcon name="credit-card" class="h-4 w-4" /><strong>PO 付款计划</strong><span :class="['status-pill', statusClass(activePo.payment_status)]">{{ activePo.payment_status || '待付款' }}</span></header>
            <div v-if="activePo.payment_plan?.length" class="payment-plan-list">
              <label><span>付款期次</span><select v-model="paymentPlanDraft"><option value="">请选择期次</option><option v-for="row in activePo.payment_plan" :key="row.name" :value="row.name">{{ row.installment_name }} · {{ row.payment_stage }} · {{ money(row.amount, activePo.currency) }} · {{ row.status }}</option></select></label>
              <button v-if="activePo.can_manage_purchase && activePo.contract_status === '已生效' && activePo.payment_plan?.some((row) => row.name === paymentPlanDraft && ['待审批','审批中'].includes(row.status) && !row.payment_request)" type="button" class="primary-button full" @click="pushPaymentRequest"><FeatherIcon name="send" class="h-4 w-4" />下推采购付款</button>
              <router-link v-if="activePo.payment_plan?.some((row) => row.name === paymentPlanDraft && row.payment_request)" :to="{ path: '/approval/procurement-payment', query: { request: activePo.payment_plan.find((row) => row.name === paymentPlanDraft)?.payment_request } }" class="secondary-button full"><FeatherIcon name="external-link" class="h-4 w-4" />查看采购付款审批</router-link>
            </div>
            <div class="payment-summary">
              <div><small>累计付款</small><strong>{{ money(activePo.paid_amount, activePo.currency) }}</strong></div>
              <div><small>未付金额</small><strong>{{ money(activePo.outstanding_amount, activePo.currency) }}</strong></div>
            </div>
            <div class="payment-inputs" v-if="false">
              <label><span>本次付款金额</span><input v-model.number="paymentDraft.amount" type="number" min="0.01" :max="activePo.outstanding_amount" step="0.01" /></label>
              <label><span>付款申请 / 凭证号</span><input v-model="paymentDraft.reference" /></label>
            </div>
            <small class="payment-hint">付款审批请在“采购付款”中处理，审批通过后由财务登记实际付款。</small>
          </section>
        </div>
      </article>
      <div v-else class="detail-empty"><FeatherIcon name="package" class="h-8 w-8" /><strong>选择 PO 查看合同和执行明细</strong></div>
    </section>
  </div>
</template>
<style scoped>
.chain-shell { color: #263238; background: #f5f7f7; min-height: calc(100vh - 80px); padding: 4px 0 24px; }
.page-head { display: flex; align-items: end; justify-content: space-between; gap: 20px; padding: 10px 4px 18px; border-bottom: 1px solid #ccd5d6; }
.eyebrow { color: #5c6d70; font-size: 11px; font-weight: 700; letter-spacing: 0; text-transform: uppercase; }
.page-head h1 { margin: 3px 0 0; font-size: 23px; line-height: 1.25; font-weight: 700; color: #182528; }
.page-head p { margin: 4px 0 0; color: #647376; font-size: 13px; }
.icon-button { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border: 1px solid #bdc8ca; border-radius: 4px; background: white; color: #42575b; }
.alert { margin: 12px 0 0; padding: 9px 12px; border: 1px solid; border-radius: 4px; font-size: 13px; }
.alert.success { border-color: #a8d5c0; background: #edf8f2; color: #176448; }
.alert.danger { border-color: #e7b6b3; background: #fff2f1; color: #a2342d; }
.context-bar { margin-top: 12px; display: flex; align-items: center; justify-content: space-between; gap: 16px; border: 1px solid #b9ced3; background: #edf5f6; padding: 10px 12px; color: #29474e; }
.context-bar div { min-width: 0; display: flex; align-items: baseline; gap: 10px; }
.context-bar strong { white-space: nowrap; font-size: 13px; }
.context-bar span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: #5b7176; }
.context-bar a { flex: none; color: #176977; font-size: 12px; font-weight: 700; }
.main-tabs { display: flex; gap: 2px; margin-top: 14px; border-bottom: 1px solid #cbd4d5; }
.main-tabs button { display: inline-flex; align-items: center; gap: 7px; min-height: 42px; padding: 0 16px; border: 0; border-bottom: 3px solid transparent; background: transparent; color: #647174; font-size: 13px; font-weight: 600; }
.main-tabs button.active { border-color: #176f73; color: #164f53; background: #eef5f5; }
.count { min-width: 20px; padding: 1px 6px; border-radius: 10px; background: #e0e6e7; color: #536164; font-size: 11px; text-align: center; }
.main-tabs button.active .count { background: #cfe4e2; color: #12585b; }
.workspace { margin-top: 12px; background: white; border: 1px solid #cfd8d9; border-radius: 5px; overflow: hidden; }
.section-bar { min-height: 62px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 14px; border-bottom: 1px solid #d9e0e1; background: #f8faf9; }
.section-bar h2 { margin: 0; font-size: 14px; font-weight: 700; color: #233538; }
.section-bar > div > span { display: block; margin-top: 2px; color: #748184; font-size: 11px; }
.bar-actions { display: flex; align-items: center; gap: 8px; }
.source-filter { height: 36px; min-width: 142px; border: 1px solid #c9d2d3; border-radius: 4px; background: white; padding: 0 30px 0 10px; color: #344548; font-size: 12px; }
.search-box { width: 310px; display: flex; align-items: center; gap: 7px; padding: 0 9px; border: 1px solid #c9d2d3; border-radius: 4px; background: white; color: #728083; }
.search-box input { width: 100%; height: 34px; padding: 0; border: 0; box-shadow: none; font-size: 12px; }
.primary-button, .secondary-button, .approve-button { min-height: 34px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 0 12px; border: 1px solid transparent; border-radius: 4px; font-size: 12px; font-weight: 700; }
.primary-button { background: #176f73; border-color: #176f73; color: white; }
.primary-button:hover { background: #115c60; }
.primary-button:disabled { background: #9ba8aa; border-color: #9ba8aa; cursor: not-allowed; }
.secondary-button { background: white; border-color: #aebbbc; color: #344b4f; }
.approve-button { background: #21774f; border-color: #21774f; color: white; }
.table-frame { width: 100%; overflow: auto; }
.data-grid { width: 100%; min-width: 1280px; border-collapse: separate; border-spacing: 0; table-layout: fixed; font-size: 12px; }
.min-pr-grid { min-width: 1360px; }
.min-pr-grid .source-pr-group-row th { position: static; z-index: auto; height: 36px; padding: 7px 14px; border-top: 2px solid #9fb9b8; border-bottom-color: #c7d7d6; background: #e5efee; }
.source-pr-group { display: flex; align-items: center; gap: 14px; min-width: 0; }
.source-pr-group strong { color: #1e4f52; font-size: 13px; }
.source-pr-group span { padding-left: 14px; border-left: 1px solid #b8ccca; color: #607477; font-size: 11px; font-weight: 600; }
.source-pr-group .available-source { color: #0f766e; }
.source-pr-group .exhausted-source { color: #879397; }
.source-pr-child { padding-left: 14px !important; color: #718184 !important; font-size: 11px; }
.data-grid th { position: sticky; top: 0; z-index: 2; height: 38px; padding: 7px 10px; border-bottom: 1px solid #cbd5d6; border-right: 1px solid #dde3e4; background: #e9eff0; color: #43575a; text-align: left; font-weight: 700; white-space: nowrap; }
.data-grid td { height: 48px; padding: 7px 10px; border-bottom: 1px solid #e1e6e7; border-right: 1px solid #edf0f0; color: #334548; vertical-align: middle; }
.data-grid tbody tr:nth-child(even) td { background: #fafcfc; }
.data-grid tbody tr:hover td { background: #eef7f6; }
.data-grid tbody tr.selected td { background: #e5f2f0; }
.data-grid tbody tr.muted td { color: #9aa5a7; background: #f7f8f8; }
.data-grid strong { display: block; font-weight: 650; color: #253639; }
.data-grid small { display: block; margin-top: 2px; color: #788588; font-size: 10px; }
.data-grid .serial { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: #12657a; white-space: nowrap; }
.check-cell { width: 42px; text-align: center !important; }
.number { text-align: right !important; font-variant-numeric: tabular-nums; }
.remaining { color: #176f52 !important; font-weight: 700; }
.quantity-column { width: 130px; }
.quantity-input, .date-input { width: 100%; min-width: 90px; height: 30px; padding: 3px 7px; border: 1px solid #b8c5c7; border-radius: 3px; background: white; text-align: right; font-size: 12px; }
.quantity-input:disabled { background: #eff2f2; color: #9aa3a4; }
.empty-state { padding: 36px 16px !important; color: #829093 !important; text-align: center !important; font-size: 12px; }
.empty-state.compact { padding: 18px !important; }
.sub-tabs { display: flex; border-bottom: 1px solid #d4dcdd; background: #f7f9f9; }
.sub-tabs button { min-height: 42px; padding: 0 16px; border: 0; border-right: 1px solid #dce2e3; background: transparent; color: #5b696c; font-size: 12px; font-weight: 650; }
.sub-tabs button.active { background: white; color: #145e62; box-shadow: inset 0 -3px #1b7478; }
.sub-tabs span { margin-left: 5px; color: #899496; }
.master-detail { display: grid; grid-template-columns: 245px minmax(0, 1fr); min-height: 660px; margin-top: 0; border: 0; border-radius: 0; }
.record-list { align-self: start; width: 100%; max-height: 520px; border-right: 1px solid #d6dedf; background: #eef3f3; overflow-y: auto; }
.list-head { display: flex; align-items: center; justify-content: space-between; height: 45px; padding: 0 12px; border-bottom: 1px solid #d3dcdd; color: #31474a; font-size: 12px; }
.record-list > button { width: 100%; padding: 9px 10px; border: 0; border-bottom: 1px solid #d7dfe0; background: transparent; text-align: left; }
.record-list > button:hover { background: #f8fbfb; }
.record-list > button.active { background: white; box-shadow: inset 3px 0 #176f73; }
.record-list > button > div, .record-list footer { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.record-list > button > div strong { font-size: 12px; color: #263b3e; }
.record-list > button small { display: block; margin-top: 4px; color: #6f7e81; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.record-list footer { margin-top: 5px; color: #798689; font-size: 10px; }
.record-list footer b { color: #33494c; font-size: 11px; }
.status-pill { display: inline-flex; align-items: center; padding: 2px 7px; border-radius: 10px; font-size: 10px; font-weight: 700; white-space: nowrap; }
.status-done { background: #dff2e8; color: #176346; }
.status-danger { background: #fae5e3; color: #a13c34; }
.status-wait { background: #f6edd5; color: #7b5b12; }
.status-active { background: #dcecf1; color: #225f71; }
.detail-pane { min-width: 0; padding-bottom: 24px; background: #f7f9f9; overflow: hidden; }
.detail-empty { min-height: 500px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: #879396; background: #f8faf9; }
.document-head { display: flex; align-items: center; gap: 20px; min-height: 76px; padding: 12px 16px; border-bottom: 1px solid #d2dcdd; background: white; }
.document-head > div:first-child { min-width: 250px; }
.document-number { color: #1f3437; font-size: 18px; font-weight: 750; }
.document-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; margin-top: 6px; color: #748184; font-size: 10px; }
.document-total { margin-left: auto; text-align: right; }
.document-total small { display: block; color: #788588; font-size: 10px; }
.document-total strong { display: block; margin-top: 2px; color: #164e50; font-size: 17px; font-variant-numeric: tabular-nums; }
.document-actions { display: flex; gap: 7px; }
.payment-handoff { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 12px 14px 0; padding: 12px; border: 1px solid #b9ced3; background: #edf5f6; }
.payment-handoff strong, .payment-handoff span { display: block; }
.payment-handoff strong { color: #29474e; font-size: 12px; }
.payment-handoff span { margin-top: 3px; color: #65787c; font-size: 10px; }
.approval-trail { margin: 12px 14px; border: 1px solid #d6dedf; border-radius: 4px; background: white; }
.trail-title { display: flex; align-items: center; gap: 7px; padding: 9px 12px; border-bottom: 1px solid #e1e6e7; color: #405558; font-size: 11px; }
.trail-step { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; align-items: start; gap: 8px; padding: 10px 12px; }
.trail-dot { width: 20px; height: 20px; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; background: #f3e8c8; color: #7f6116; }
.trail-dot.done { background: #d9efe4; color: #186346; }
.trail-step strong { display: block; color: #304548; font-size: 11px; }
.trail-step small { display: block; margin-top: 2px; color: #7c898b; font-size: 10px; }
.trail-step p { margin: 4px 0 0; color: #526467; font-size: 10px; }
.trail-empty { padding: 12px; color: #879396; font-size: 11px; }
.quote-sheet { margin: 12px 14px 0; border: 1px solid #cfd9da; border-radius: 5px; background: white; overflow: hidden; }
.material-head { display: grid; grid-template-columns: 34px minmax(230px, .8fr) minmax(440px, 1.4fr); gap: 10px; align-items: center; padding: 10px 12px; border-bottom: 1px solid #d5dfe0; background: #edf3f3; }
.line-index { color: #7c898b; font: 700 12px ui-monospace, monospace; }
.material-title strong { display: inline; color: #263a3d; font-size: 13px; }
.material-title .serial { margin-left: 8px; color: #12657a; font: 600 10px ui-monospace, monospace; }
.material-title small { display: block; margin-top: 3px; color: #6d7b7e; font-size: 10px; }
.material-head dl { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 0; }
.material-head dl div { min-width: 0; }
.material-head dt { color: #7c898b; font-size: 9px; }
.material-head dd { margin: 2px 0 0; color: #34494c; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.comparison-frame { overflow-x: auto; }
.comparison-table { width: 100%; min-width: 1120px; border-collapse: collapse; table-layout: fixed; font-size: 10px; }
.comparison-table th { padding: 7px 8px; border-right: 1px solid #e1e6e7; border-bottom: 1px solid #d7dfe0; background: #f7f9f9; color: #617174; text-align: left; }
.comparison-table td { height: 43px; padding: 7px 8px; border-right: 1px solid #e7ebec; border-bottom: 1px solid #e2e7e8; color: #3e5255; }
.comparison-table tr.recommended td { background: #edf7f1; }
.comparison-table tr.chosen td { box-shadow: inset 0 1px #4c9980, inset 0 -1px #4c9980; }
.comparison-table th:first-child { width: 180px; }
.comparison-table th:nth-child(4), .comparison-table th:nth-child(5) { width: 112px; }
.comparison-table th:nth-child(6) { width: 90px; }
.comparison-table th:nth-child(7) { width: 190px; }
.actions-column { width: 98px; }
.recommend-label, .chosen-label { display: inline-block; margin-left: 5px; padding: 1px 5px; border-radius: 2px; font-size: 9px; font-weight: 700; }
.recommend-label { background: #d7eee2; color: #176348; }
.chosen-label { background: #dcecf3; color: #185d73; }
.strong-number { color: #254f51 !important; font-weight: 750; }
.row-actions { white-space: nowrap; }
.row-actions button { width: 25px; height: 25px; display: inline-flex; align-items: center; justify-content: center; margin-left: 2px; border: 0; border-radius: 3px; background: #eaf0f1; color: #35666b; }
.row-actions .danger-icon { color: #a44038; }
.quote-editor { padding: 10px 12px 12px; background: #f7f9f9; }
.editor-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; color: #45595c; font-size: 10px; }
.editor-title button { border: 0; background: transparent; color: #176f73; font-size: 10px; }
.editor-grid { display: grid; grid-template-columns: repeat(6, minmax(110px, 1fr)); gap: 7px; align-items: end; }
.editor-grid label { min-width: 0; }
.editor-grid label > span, .payment-inputs label > span { display: block; margin-bottom: 3px; color: #6e7c7f; font-size: 9px; }
.editor-grid input, .editor-grid select, .operation-row input, .operation-row select, .payment-inputs input { width: 100%; height: 30px; padding: 3px 7px; border: 1px solid #bdc9ca; border-radius: 3px; background: white; font-size: 10px; }
.editor-grid .span-2 { grid-column: span 2; }
.recommend-toggle { height: 30px; display: flex; align-items: center; gap: 6px; }
.recommend-toggle input { width: 14px; height: 14px; }
.recommend-toggle span { margin: 0 !important; color: #176348 !important; font-weight: 700; }
.po-workspace { margin-top: 12px; border: 1px solid #cfd8d9; border-radius: 5px; }
.po-facts { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); border-bottom: 1px solid #d9e0e1; background: #eef3f3; }
.po-facts dl { min-width: 0; margin: 0; padding: 10px 12px; border-right: 1px solid #d7dfe0; }
.po-facts dt { color: #788588; font-size: 9px; }
.po-facts dd { margin: 3px 0 0; color: #31474a; font-size: 10px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.po-facts .payment-fact dd { white-space: normal; line-height: 1.35; }
.po-lines { max-height: 360px; border-bottom: 1px solid #d5ddde; background: white; }
.po-lines .data-grid { min-width: 1500px; }
.execution-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 12px; }
.operation-panel { border: 1px solid #d1dadb; border-radius: 4px; background: white; overflow: hidden; }
.operation-panel > header { height: 38px; display: flex; align-items: center; gap: 7px; padding: 0 10px; border-bottom: 1px solid #dbe2e3; background: #eef3f3; color: #3f5558; font-size: 11px; }
.operation-panel > header .status-pill { margin-left: auto; }
.operation-row { display: grid; grid-template-columns: minmax(140px, 1fr) 100px 110px; align-items: center; gap: 8px; min-height: 44px; padding: 6px 10px; border-bottom: 1px solid #e6eaeb; font-size: 10px; }
.operation-row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.operation-row b { display: block; color: #166579; font: 600 9px ui-monospace, monospace; }
.operation-row .balance { color: #6f7e81; text-align: right; }
.full { width: calc(100% - 20px); margin: 10px; }
.payment-panel { grid-column: 1 / -1; }
.payment-summary { display: grid; grid-template-columns: 1fr 1fr; }
.payment-summary div { padding: 12px; border-right: 1px solid #e0e5e6; }
.payment-summary small { display: block; color: #788588; font-size: 9px; }
.payment-summary strong { display: block; margin-top: 3px; color: #234d50; font-size: 15px; }
.payment-inputs { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 0 10px 4px; }
@media (max-width: 1100px) {
  .master-detail { grid-template-columns: 210px minmax(0, 1fr); }
  .material-head { grid-template-columns: 30px minmax(220px, 1fr); }
  .material-head dl { grid-column: 2; }
  .editor-grid { grid-template-columns: repeat(3, minmax(110px, 1fr)); }
  .po-facts { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .page-head, .section-bar { align-items: stretch; flex-direction: column; }
  .bar-actions { align-items: stretch; flex-direction: column; }
  .source-filter { width: 100%; }
  .search-box { width: 100%; }
  .main-tabs { overflow-x: auto; }
  .main-tabs button { white-space: nowrap; }
  .master-detail { display: block; }
  .record-list { max-height: 220px; border-right: 0; border-bottom: 1px solid #d6dedf; }
  .document-head { align-items: flex-start; flex-wrap: wrap; }
  .document-total { margin-left: 0; }
  .document-actions { width: 100%; }
  .material-head dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .editor-grid, .execution-grid, .payment-inputs { grid-template-columns: 1fr; }
  .editor-grid .span-2, .payment-panel { grid-column: auto; }
  .po-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.review-summary { margin: 12px 14px; border: 1px solid #d6dedf; border-radius: 4px; background: white; }
.summary-title { display: flex; align-items: baseline; gap: 8px; padding: 9px 12px; border-bottom: 1px solid #e1e6e7; }
.summary-title strong { color: #344a4d; font-size: 11px; }
.summary-title span { color: #839093; font-size: 9px; }
.summary-editor { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 8px; padding: 10px 12px; align-items: end; }
.summary-editor textarea { width: 100%; padding: 7px 9px; border: 1px solid #bdc9ca; border-radius: 3px; font-size: 11px; resize: vertical; }
.review-summary > p { margin: 0; padding: 12px; color: #405558; font-size: 11px; line-height: 1.7; white-space: pre-wrap; }
@media (max-width: 900px) {
  .summary-editor { grid-template-columns: 1fr; }
}
.approval-view-tabs { display: flex; gap: 0; margin: 14px 14px 0; border-bottom: 1px solid #cbd5d6; }
.approval-view-tabs button { border: 0; border-bottom: 2px solid transparent; background: transparent; padding: 8px 14px; color: #708083; font-size: 12px; cursor: pointer; }
.approval-view-tabs button.active { border-bottom-color: #176d69; color: #176d69; font-weight: 700; }
.supplier-comparison-section { margin-top: 0; border: 1px solid #cbd5d6; border-top: 0; background: #fff; }
.comparison-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 16px; border-bottom: 1px solid #d7dfe0; }
.comparison-title div { display: flex; flex-direction: column; gap: 3px; }
.comparison-title strong { font-size: 14px; color: #263238; }
.comparison-title span { font-size: 12px; color: #728083; }
.supplier-count { flex: none; border: 1px solid #b8c9c9; background: #eef6f5; color: #176d69 !important; padding: 4px 8px; font-weight: 700; }
.package-actions { min-width: 104px; }
.package-empty { padding: 28px; border-bottom: 1px solid #d7dfe0; }
.quote-matrix-frame { max-height: min(68vh, 720px); overflow: auto; border-bottom: 1px solid #d7dfe0; background: #fff; }
.quote-matrix-scroll { display: flex; width: max-content; min-width: 100%; align-items: stretch; }
.quote-matrix { flex: none; border-collapse: separate; border-spacing: 0; table-layout: fixed; color: #304347; font-size: 10px; }
.quote-matrix .col-index { width: 29px; }
.quote-matrix .col-serial { width: 100px; }
.quote-matrix .col-code { width: 108px; }
.quote-matrix .col-name { width: 106px; }
.quote-matrix .col-quantity { width: 54px; }
.quote-matrix .col-unit-price { width: 92px; }
.quote-matrix .col-total-price { width: 104px; }
.quote-matrix .col-delivery { width: 164px; }
.quote-matrix th, .quote-matrix td { height: 38px; padding: 5px 5px; border-right: 1px solid #dce3e4; border-bottom: 1px solid #dce3e4; text-align: left; vertical-align: middle; line-height: 1.35; }
.quote-matrix thead th { position: sticky; z-index: 6; background: #edf2f2; color: #45585b; font-weight: 700; }
.quote-matrix .supplier-heading-row th { top: 0; height: 42px; }
.quote-matrix .quote-heading-row th { top: 42px; height: 34px; background: #f5f7f7; text-align: right; }
.quote-matrix .supplier-group-heading { border-left: 2px solid #c4d0d1; }
.quote-matrix .supplier-group-heading.recommended { background: #edf7f2; }
.quote-matrix .supplier-group-heading.chosen { background: #dff3ec; box-shadow: inset 0 3px #17806f; }
.supplier-heading-content { display: flex; align-items: center; gap: 6px; min-width: 0; }
.supplier-heading-content strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.supplier-inline { box-sizing: border-box; min-width: 0; width: 100%; border: 1px solid #b9c7c9; background: #fff; padding: 4px 5px; color: #263238; font-size: 10px; }
.supplier-name-input { flex: 1; min-width: 90px; font-weight: 700; }
.number-input { text-align: right; }
.date-input { min-width: 0; width: 100%; }
.full-input { width: 100%; }
.supplier-terms-inline { display: grid; grid-template-columns: 58px 58px minmax(120px, 1fr); gap: 5px; }
.tax-input { text-align: right; }
.recommend-toggle-inline { display: inline-flex; align-items: center; gap: 4px; color: #176d69; font-size: 10px; font-weight: 700; white-space: nowrap; }
.save-slot-button { display: inline-flex; align-items: center; gap: 3px; width: auto !important; padding: 0 7px; color: #176d69; font-size: 10px; }
.add-supplier-column { display: flex; flex: 0 0 42px; min-height: 100%; align-items: center; justify-content: center; border: 0; border-left: 1px solid #cbd5d6; background: #f5f8f8; color: #176d69; cursor: pointer; }
.add-supplier-column:hover { background: #e8f2f1; }
.quote-matrix tbody td { background: #fff; }
.quote-matrix tbody tr:hover td { background: #f7f9f9; }
.quote-matrix .sticky-col { position: sticky; z-index: 4; background: #fff; }
.quote-matrix thead .sticky-col { z-index: 9; background: #e9efef; }
.quote-matrix tbody tr:hover .sticky-col { background: #f7f9f9; }
.quote-matrix .sticky-index { left: 0; }
.quote-matrix .sticky-serial { left: 29px; }
.quote-matrix .sticky-code { left: 129px; }
.quote-matrix .sticky-name { left: 237px; }
.quote-matrix .sticky-quantity { left: 343px; box-shadow: 3px 0 0 #cbd5d6; }
.quote-matrix .code-cell, .quote-matrix .serial { overflow: hidden; color: #32656a; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; text-overflow: ellipsis; white-space: nowrap; }
.quote-matrix .item-cell strong { display: block; overflow: hidden; color: #26383b; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.quote-matrix .item-cell small { display: block; overflow: hidden; margin-top: 2px; color: #7c898b; text-overflow: ellipsis; white-space: nowrap; }
.quote-matrix .quantity-cell { white-space: nowrap; }
.quote-matrix .supplier-first { border-left: 2px solid #c4d0d1; }
.quote-matrix .matrix-recommended { background: #f2f8f5 !important; }
.quote-matrix .matrix-chosen { background: #e4f5ef !important; }
.quote-matrix .muted-cell { color: #8b9698; }
.quote-matrix tfoot th, .quote-matrix tfoot td { background: #f7f9f9; }
.quote-matrix tfoot th { position: sticky; left: 0; z-index: 5; color: #4c5f62; }
.quote-matrix .quote-total-row th, .quote-matrix .quote-total-row td { background: #edf2f2; font-weight: 700; }
.supplier-footer-content { position: relative; min-width: 0; overflow: hidden; }
.supplier-footer-content > .supplier-inline { box-sizing: border-box; }
.supplier-plan-row td { vertical-align: top; }
.supplier-plan { padding: 2px 0; }
.plan-line { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; padding: 8px; margin-bottom: 8px; border: 1px solid #dce3e4; border-radius: 4px; }
.plan-field { display: grid; gap: 4px; min-width: 0; color: #53686b; font-size: 10px; }
.plan-line .supplier-inline { min-width: 0; height: 28px; padding: 2px 5px; border: 1px solid #bdc9ca; border-radius: 3px; background: white; font-size: 9px; }
.plan-remove { align-self: end; justify-self: end; width: 28px; height: 28px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid #dab9b6; border-radius: 3px; background: white; color: #9f3d36; }
.plan-remove:disabled { opacity: .35; }
.plan-actions { display: flex; gap: 6px; }
.plan-actions button { height: 26px; display: inline-flex; align-items: center; gap: 4px; padding: 0 7px; border: 1px solid #adbbbd; border-radius: 3px; background: white; color: #3e5659; font-size: 9px; }
.readonly-plan { display: grid; gap: 4px; color: #465b5e; font-size: 9px; line-height: 1.5; }
.supplier-summary-actions { display: flex; min-height: 28px; align-items: center; justify-content: space-between; gap: 6px; }
.supplier-summary-actions .row-actions { margin-left: auto; }
.supplier-summary-actions .row-actions button { width: 28px; height: 28px; }
.bottom-section { margin-top: 14px; }
.requirement-content { margin: 14px 14px 0; border: 1px solid #d6dedf; background: #fff; }
.requirement-facts { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border-bottom: 1px solid #e1e6e7; background: #f7f9f9; }
.requirement-facts dl { min-width: 0; margin: 0; padding: 9px 12px; border-right: 1px solid #e1e6e7; }
.requirement-facts dt { color: #7b898b; font-size: 10px; }
.requirement-facts dd { margin: 3px 0 0; color: #304548; font-size: 11px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.requirement-table-frame { overflow-x: auto; }
.requirement-table { width: 100%; min-width: 1080px; border-collapse: collapse; table-layout: fixed; font-size: 11px; }
.requirement-table th, .requirement-table td { padding: 8px 9px; border-right: 1px solid #e2e7e8; border-bottom: 1px solid #e2e7e8; text-align: left; vertical-align: top; }
.requirement-table th { background: #edf3f3; color: #596c6f; font-size: 10px; font-weight: 700; white-space: nowrap; }
.requirement-table td { color: #405558; line-height: 1.45; }
.requirement-table td strong { color: #26383b; font-weight: 700; }
.requirement-table .serial { color: #12657a; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; white-space: nowrap; }
.requirement-table .wrap-cell { white-space: normal; overflow-wrap: anywhere; }
@media (max-width: 900px) { .requirement-facts { grid-template-columns: repeat(2, minmax(0,1fr)); } } 
@media (max-width: 1100px) { .supplier-condition-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .supplier-condition-grid .span-2 { grid-column: span 2; } }
</style>
