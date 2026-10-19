const ACTIVE_STATUS = new Set(['有效', '']);
function text(value) { return String(value || '').trim(); }
function activeDocuments(documents) {
  const latest = new Map();
  for (const row of documents || []) {
    if (!row || !ACTIVE_STATUS.has(text(row.status))) continue;
    const previous = latest.get(row.document_type);
    if (!previous || Number(row.version_no || 0) > Number(previous.version_no || 0)) latest.set(row.document_type, row);
  }
  return latest;
}
function hasType(latest, types) { return (types || []).some((type) => latest.has(type)); }
function item(key, label, types, description, options = {}) {
  return { key, label, types, uploadTypes: options.uploadTypes || types, required: options.required !== false, auto: Boolean(options.auto), mode: options.mode || 'all', description };
}
function stageForRequest(request) {
  const step = text(request?.current_step_label);
  const business = text(request?.business_status);
  if (request?.request_type === '采购付款') return 'payment';
  if (step.includes('询价') || step.includes('价格审批') || business === '需求已批准/待询价' || business === '待价格审批') return 'quote';
  if (step.includes('演示员工116') || ['价格已批准/待补充演示员工116信息', '待采购复核', '待电子用印', '演示员工116已生效', '付款计划已生成'].includes(business)) return 'contract';
  if (business === '待到货') return 'arrival';
  if (business === '待验收') return 'inspection';
  if (['验收通过', '采购执行中', '已关闭'].includes(business)) return 'payment';
  return 'demand';
}
export function documentChecklistForRequest(request, documents = []) {
  if (!request) return [];
  const latest = activeDocuments(documents);
  const stage = stageForRequest(request);
  const result = [];
  if (stage === 'demand') return result;
  if (['quote', 'contract', 'arrival', 'inspection', 'payment'].includes(stage)) result.push(item('quote', '报价与价格审批', ['报价单', '价格审批表'], '价格审批节点需要报价依据和价格审批结果。', { uploadTypes: ['报价单', '价格审批表'] }));
  if (['contract', 'arrival', 'inspection', 'payment'].includes(stage)) result.push(item('contract', '演示员工116与付款计划', ['演示员工116', '付款计划'], '演示员工116生效和付款计划是后续履约与付款依据。', { uploadTypes: ['演示员工116', '付款计划'] }));
  if (stage === 'arrival') result.push(item('arrival', '到货资料（三选一）', ['送货单', '收料单', '入库单'], '登记到货前提供送货单、收料单或入库单任一份。', { uploadTypes: ['送货单', '收料单', '入库单'], mode: 'any' }));
  if (stage === 'inspection') result.push(item('inspection', '验收资料', ['验收资料'], '验收通过前需要上传验收记录、照片或验收报告。'));
  if (stage === 'payment') {
    const plan = (request.payment_plan || []).find((row) => row.payment_request === request.name) || (request.payment_plan || []).find((row) => row.status === '已下推') || request;
    if (text(plan?.invoice_requirement || request.invoice_requirement) === '付款前提供') result.push(item('invoice', '发票', ['发票'], '当前付款计划要求付款前提供发票。'));
  }
  if (stage === 'payment' && ['供应商退款中', '退货中', '换货中'].includes(text(request.business_status))) result.push(item('refund', '退款回单', ['退款回单'], '供应商退款或退货完成前需要上传退款回单。'));
  if (stage === 'payment' && text(request.business_status) === '已关闭') result.push(item('close', '采购完成报告', ['采购完成报告'], '关闭采购前需要留存采购完成报告。'));
  return result.map((entry) => ({ ...entry, satisfied: entry.auto || (entry.mode === 'any' ? hasType(latest, entry.types) : entry.types.every((type) => latest.has(type))), matchedTypes: entry.types.filter((type) => latest.has(type)) }));
}
export function documentChecklistSummary(request, documents = []) {
  const checklist = documentChecklistForRequest(request, documents);
  return { checklist, required: checklist.filter((item) => item.required), missing: checklist.filter((item) => item.required && !item.satisfied) };
}
