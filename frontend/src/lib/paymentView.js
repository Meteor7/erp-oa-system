// 采购付款页面的纯函数：付款条件判断（和服务端同一套规则）、状态、物料行结果、登记表单校验、审批单辅助。
// 规则（2026-09-30 确认）：
//   * 一切按整张 PO 判断，和付款期次的比例无关；暂不支持分批到货。
//   * 触发条件含“到货” -> 全部物料到齐；含“验收” -> 全部到齐且每项验收结果为“已通过”。
//   * 到货和验收都由生产主管登记；验收不是审批节点，只是付款的前置条件。
import {
  canCloseProcurement, canCompleteSupplierRefund, canRecordArrival, canRecordInspection, canWriteoffPrepayment,
} from './procurementWorkflow.js';
import { documentChecklistForRequest } from './businessDocumentChecklist.js';

const EPS = 1e-6;

export const REFUND_NOTICE = '退款需线下与供应商、财务处理，系统暂不记录';
export const WORK_STATUSES = ['待合同生效', '待到货资料', '待验收', '可提交付款审批', '付款审批中', '待实际付款', '已付款'];
export const STATUS_FILTERS = ['未完成', '全部', ...WORK_STATUSES];
export const STATUS_PRIORITY = {
  可提交付款审批: 0, 待到货资料: 1, 待验收: 2, 付款审批中: 3, 待实际付款: 4, 待合同生效: 5, 已付款: 6,
};
export const STATUS_TONE = {
  已付款: 'jade', 付款审批中: 'cobalt', 待实际付款: 'cobalt', 待到货资料: 'sun', 待验收: 'sun', 可提交付款审批: 'brand', 待合同生效: 'gray',
};
// 服务端允许登记到货 / 验收 / 换货到货 / 退货发出的 PO 状态。
export const FULFILMENT_PO_STATUSES = ['供应商制作中', '到货验收中', '付款中'];
export const PO_STATUS_TONE = { 供应商制作中: 'brand', 到货验收中: 'sun', 付款中: 'cobalt', 已关闭: 'jade', 已取消: 'gray' };
export const RECORD_TONE = { 到货: 'jade', 验收: 'cobalt', 换货到货: 'brand', 退货: 'red' };
export const INSPECT_CHOICES = [
  { value: '已通过', label: '通过' },
  { value: '换货中', label: '换货' },
  { value: '退货中', label: '退货' },
];
export const INVOICE_BEFORE = '付款前提供';
export const INVOICE_AFTER = '付款后提供';

export function text(value) { return String(value ?? '').trim(); }
export function num(value) { const n = Number(value); return Number.isFinite(n) ? n : 0; }
function round4(value) { return Math.round(num(value) * 10000) / 10000; }

export function money(value, currency = 'CNY') {
  const body = num(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return !currency || currency === 'CNY' ? `¥ ${body}` : `${currency} ${body}`;
}
export function quantity(value) { return num(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 }); }

export function todayString(now = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
export function formatTime(value) {
  const s = text(value);
  return s ? s.replace('T', ' ').slice(0, 16) : '-';
}
function parseJson(value, fallback) {
  if (Array.isArray(value) || (value && typeof value === 'object')) return value;
  try { return value ? JSON.parse(value) : fallback; } catch { return fallback; }
}

// ------------------------------------------------------------------ 触发条件
export function requiresReceipt(trigger) { return text(trigger).includes('到货'); }
export function requiresInspection(trigger) { return text(trigger).includes('验收'); }
// 判断顺序以文字为准（服务端同一规则）；服务端另给了 requires_* 标记时优先用标记。
export function triggerFlags(item = {}) {
  const trigger = text(item.trigger_condition);
  const flag = (value, fallback) => (value === undefined || value === null || value === '' ? fallback : Boolean(Number(value)));
  const receipt = flag(item.requires_receipt, requiresReceipt(trigger));
  const inspection = flag(item.requires_inspection, requiresInspection(trigger));
  return { receipt, inspection, allReceived: receipt || inspection };
}

// ------------------------------------------------------------------ PO 物料行
const LINE_LABEL = { none: '未到', pending: '待验收', passed: '已通过', exchanging: '换货中', returning: '退货中', failed: '不合格' };
const LINE_TONE = { none: 'gray', pending: 'sun', passed: 'jade', exchanging: 'red', returning: 'red', failed: 'red' };

export function lineState(line = {}) {
  const qty = num(line.quantity);
  const recv = num(line.received_quantity);
  const status = text(line.inspection_status);
  const left = Math.max(0, round4(qty - recv));
  let key;
  if (status === '退货中') key = 'returning';
  else if (status === '换货中') key = 'exchanging';
  else if (status === '不合格') key = 'failed';
  else if (recv <= 0) key = 'none';
  else if (status === '已通过') key = 'passed';
  else key = 'pending';
  return {
    key, label: LINE_LABEL[key], tone: LINE_TONE[key], qty, recv, left,
    // 退货中的货要退回去，不算"已到齐"（服务端同一规则）。
    received: recv + EPS >= qty && status !== '退货中',
    partial: recv > 0 && left > 0,
    passed: status === '已通过',
    status,
  };
}

export function summarizeLines(lines = []) {
  const states = (lines || []).map(lineState);
  const total = states.length;
  const recvN = states.filter((s) => s.received).length;
  const inspN = states.filter((s) => s.passed).length;
  return {
    total, recvN, inspN,
    allReceived: total > 0 && recvN === total,
    allInspected: total > 0 && inspN === total,
    hasExchange: states.some((s) => s.key === 'exchanging'),
    hasReturn: states.some((s) => s.key === 'returning'),
    hasFailed: states.some((s) => s.key === 'failed'),
    unreceivedN: total - recvN,
    notPassedN: total - inspN,
    anyPartial: states.some((s) => s.partial),
  };
}

// ------------------------------------------------------------------ 付款条件 / 状态
export function contractReady(item = {}) {
  if (item.contract_ready !== undefined && item.contract_ready !== null && item.contract_ready !== '') return Boolean(Number(item.contract_ready));
  const notReady = ['草稿', '待采购确认', '待合同复核', '待电子用印', '已取消'];
  return text(item.contract_status) === '已生效' && !notReady.includes(text(item.po_status));
}

export function paymentBlockers({ contractOk, trigger, summary }) {
  const blockers = [];
  if (!contractOk) blockers.push('PO 合同尚未生效');
  if (requiresReceipt(trigger) && !summary.allReceived) blockers.push('本期要求全部到货');
  if (requiresInspection(trigger)) {
    if (!summary.allReceived) blockers.push('验收前需全部到货');
    if (!summary.allInspected) blockers.push('本期要求验收通过');
  }
  return blockers;
}

export function isInFlight(status) { return ['付款审批中', '待实际付款'].includes(status); }

export function computeWorkStatus({ paid = false, paymentRequest = '', requestSummary = {}, blockers = [], contractOk = true }) {
  if (paid) return '已付款';
  if (text(paymentRequest)) {
    const label = text(requestSummary?.current_step_label);
    const wf = text(requestSummary?.workflow_status);
    return label.includes('付款') || ['已通过', '已完成'].includes(wf) ? '待实际付款' : '付款审批中';
  }
  if (blockers.length) {
    if (!contractOk) return '待合同生效';
    return blockers.some((b) => b.includes('到货')) ? '待到货资料' : '待验收';
  }
  return '可提交付款审批';
}

export function itemPaid(item = {}) {
  const amount = num(item.amount);
  return item.work_status === '已付款' || text(item.status) === '已付款' || (amount > 0 && num(item.paid_amount) >= amount);
}

// 一个付款期次在整张 PO 上的完整判断：服务端给了就用服务端的（保持和工作台、提交校验同源），缺的用同一规则补算。
export function evaluateItem(item = {}, group = null) {
  const lines = (group?.lines) || item.lines || [];
  const summary = summarizeLines(lines);
  const contractOk = contractReady(item);
  const trigger = text(item.trigger_condition);
  const computedBlockers = paymentBlockers({ contractOk, trigger, summary });
  const blockers = Array.isArray(item.blockers) ? item.blockers.map(text).filter(Boolean) : computedBlockers;
  const status = text(item.work_status) || computeWorkStatus({
    paid: itemPaid(item), paymentRequest: item.payment_request, requestSummary: item.payment_request_summary, blockers, contractOk,
  });
  const flags = triggerFlags(item);
  return { lines, summary, contractOk, trigger, flags, blockers, status };
}

// 审批已经发出，但整张 PO 的到货 / 验收又变了：服务端给 conditions_regressed；没给就按同一规则补算。
export function conditionsRegressed(item = {}, evaluated = null) {
  if (item.conditions_regressed !== undefined && item.conditions_regressed !== null && item.conditions_regressed !== '') return Boolean(Number(item.conditions_regressed));
  const ev = evaluated || evaluateItem(item);
  return isInFlight(ev.status) && ev.blockers.length > 0;
}

export function regressionNote(blockers = []) {
  const why = blockers.length ? `（${blockers.join('；')}）` : '';
  return `审批过程中条件已回退${why}。系统会在最后一步“总经理确认付款”时再检查并拦下，请先处理到货 / 验收。`;
}

export function draftNote(name) { return `上次被退回的付款单 ${name}，重新提交会沿用这张单据`; }

// 谁在等谁。
export function waitingFor({ status, summary, canPush = false, draft = '', requestSummary = {}, paymentRequest = '' }) {
  if (status === '已付款') return '';
  if (status === '待合同生效') return '等 PO 合同电子用印生效';
  if (status === '待到货资料' || status === '待验收') {
    if (summary.hasReturn) return '等退货发出 / 供应商补发';
    if (summary.hasExchange) return '等供应商换货到货';
    if (summary.unreceivedN > 0) return '等生产主管登记到货';
    return '等生产主管登记验收';
  }
  if (status === '可提交付款审批') {
    return canPush ? '' : '等采购提交付款审批';
  }
  if (status === '付款审批中') return `审批中：${text(requestSummary?.current_step_label) || text(paymentRequest) || '-'}`;
  if (status === '待实际付款') return `等 ${text(requestSummary?.current_step_label) || '总经理付款'}`;
  return '';
}

// 条件格：state 1 满足 / 0 未满足 / -1 本期不要求（或仅提示）。
export function gateTiles({ contractOk, trigger, summary, invoiceRequirement = '', invoiceDocs = null }) {
  const needReceipt = requiresReceipt(trigger) || requiresInspection(trigger);
  const needInspect = requiresInspection(trigger);
  const tiles = [{ key: 'contract', k: '合同已生效', v: contractOk ? '已满足' : '合同尚未生效', state: contractOk ? 1 : 0 }];
  if (needReceipt) {
    tiles.push({
      key: 'receipt', k: '全部到货',
      v: summary.allReceived ? `已满足（${summary.recvN}/${summary.total} 项）` : `还差 ${summary.unreceivedN} 项未到齐`,
      state: summary.allReceived ? 1 : 0,
    });
  } else tiles.push({ key: 'receipt', k: '全部到货', v: '本期不要求', state: -1 });
  if (needInspect) {
    tiles.push({
      key: 'inspection', k: '验收通过',
      v: summary.allInspected ? '已满足' : (summary.allReceived ? `还有 ${summary.notPassedN} 项未通过` : '须先全部到货'),
      state: summary.allInspected ? 1 : 0,
    });
  } else tiles.push({ key: 'inspection', k: '验收通过', v: summary.inspN > 0 ? `本期不要求（已通过 ${summary.inspN}/${summary.total}）` : '本期不要求', state: -1 });
  const requirement = text(invoiceRequirement);
  if (invoiceDocs === null) {
    tiles.push({ key: 'invoice', k: '发票要求', v: requirement || '未约定', state: -1 });
  } else if (requirement === INVOICE_BEFORE) {
    tiles.push({ key: 'invoice', k: '发票', v: invoiceDocs > 0 ? `已上传 ${invoiceDocs} 份` : '付款前须上传发票', state: invoiceDocs > 0 ? 1 : 0 });
  } else if (requirement === INVOICE_AFTER) {
    tiles.push({ key: 'invoice', k: '发票', v: '付款后提供，现在不用', state: -1 });
  } else tiles.push({ key: 'invoice', k: '发票', v: requirement || '未约定', state: -1 });
  return tiles;
}

// ------------------------------------------------------------------ 按 PO 分组
function firstFlag(items, key) {
  const defined = items.filter((item) => item[key] !== undefined && item[key] !== null && item[key] !== '');
  if (!defined.length) return null;
  return defined.some((item) => Boolean(Number(item[key])));
}

export function buildPoGroups(items = []) {
  const map = new Map();
  for (const item of items || []) {
    const po = text(item.po);
    if (!po) continue;
    if (!map.has(po)) map.set(po, []);
    map.get(po).push(item);
  }
  const groups = [...map.entries()].map(([po, rows]) => {
    const first = rows[0];
    const lines = first.lines || [];
    const summary = summarizeLines(lines);
    const installments = [...rows].sort((a, b) => num(a.installment_no) - num(b.installment_no));
    const evaluated = installments.map((row) => ({ item: row, ev: evaluateItem(row, { lines }) }));
    const total = lines.reduce((sum, line) => sum + (line.amount !== undefined && line.amount !== null && line.amount !== '' ? num(line.amount) : num(line.quantity) * num(line.unit_price)), 0);
    const paid = installments.reduce((sum, row) => sum + (itemPaid(row) ? Math.max(num(row.paid_amount), num(row.amount)) : num(row.paid_amount)), 0);
    const sources = [...new Set(lines.map((line) => text(line.source_request)).filter(Boolean))];
    const records = normalizeRecords(first.fulfillment_records || []);
    const statuses = evaluated.map((x) => x.ev.status);
    const minPriority = Math.min(...statuses.map((s) => (STATUS_PRIORITY[s] ?? 9)));
    return {
      po, key: po,
      supplier: text(first.supplier), po_status: text(first.po_status), contract_status: text(first.contract_status),
      currency: text(first.currency) || 'CNY', source_price_approvals: text(first.source_price_approvals), sources,
      lines, summary, items: installments, evaluated, records, total, paid,
      flags: {
        receipt: firstFlag(installments, 'can_record_receipt'),
        inspect: firstFlag(installments, 'can_record_inspection'),
        exchange: firstFlag(installments, 'can_record_exchange'),
        return: firstFlag(installments, 'can_record_return'),
      },
      canPushAny: installments.some((row) => Boolean(Number(row.can_push_payment))),
      statuses, minPriority,
      openCount: statuses.filter((s) => s !== '已付款').length,
    };
  });
  return groups;
}

// 有待办的排前面：我能登记 / 能提交的 PO 先，其次按最紧的期次状态。
export function sortGroups(groups = [], { canFulfil = false } = {}) {
  const todo = new Map(groups.map((group) => [group, group.canPushAny || (canFulfil && fulfilmentModes(group, { canFulfil }).length > 0) ? 0 : 1]));
  return [...groups].sort((a, b) => (todo.get(a) - todo.get(b)) || (a.minPriority - b.minPriority) || a.po.localeCompare(b.po));
}

export function statusCounts(items = []) {
  const counts = {};
  let unfinished = 0;
  for (const item of items || []) {
    const status = evaluateItem(item).status;
    counts[status] = (counts[status] || 0) + 1;
    if (status !== '已付款') unfinished += 1;
  }
  return { counts, unfinished, all: (items || []).length };
}

export function filterGroups(groups = [], status = '未完成', query = '') {
  const q = text(query).toLowerCase();
  return groups.filter((group) => {
    if (status === '未完成' && group.openCount === 0) return false;
    if (!['未完成', '全部'].includes(status) && !group.statuses.includes(status)) return false;
    if (!q) return true;
    const hay = [group.po, group.supplier, ...group.items.map((i) => [i.installment_name, i.payment_stage, i.payment_request].join(' '))].join(' ').toLowerCase();
    return hay.includes(q);
  });
}

// ------------------------------------------------------------------ 到货 / 验收记录
export function normalizeRecords(records = []) {
  return (records || []).map((record) => ({ ...record, details: Array.isArray(record.details) ? record.details : parseJson(record.details_json, []) }));
}
export function sortRecordsDesc(records = []) {
  return records.map((r, i) => [r, i]).sort((a, b) => {
    const ka = text(a[0].creation) || text(a[0].record_date);
    const kb = text(b[0].creation) || text(b[0].record_date);
    return kb === ka ? a[1] - b[1] : (kb > ka ? 1 : -1);
  }).map((x) => x[0]);
}
const RESULT_LABEL = { 已通过: '已通过', 换货中: '换货', 退货中: '退货' };
export function recordDetailText(record = {}) {
  const details = Array.isArray(record.details) ? record.details : parseJson(record.details_json, []);
  const name = (d) => text(d.item_name) || text(d.material_serial) || text(d.line);
  if (record.record_type === '验收') {
    return details.map((d) => `${name(d)}：${RESULT_LABEL[d.status] || text(d.status) || '-'}${text(d.reason) ? `（${text(d.reason)}）` : ''}`).join('；');
  }
  return details.map((d) => `${name(d)} ${quantity(d.quantity)}${text(d.unit) ? ` ${text(d.unit)}` : ''}`).join('；');
}
// 最近一次验收记录里这一行的原因（换货中 / 退货中才有）。
export function latestInspectionReason(records = [], lineName = '') {
  for (const record of sortRecordsDesc(normalizeRecords(records))) {
    if (record.record_type !== '验收') continue;
    const hit = (record.details || []).find((d) => text(d.line) === text(lineName));
    if (hit) return text(hit.reason);
  }
  return '';
}
export function lineHint(line, records, canFulfil) {
  const state = lineState(line);
  if (state.key !== 'exchanging' && state.key !== 'returning') return '';
  const reason = latestInspectionReason(records, line.name);
  if (reason) return reason;
  if (canFulfil) return '';
  return state.key === 'exchanging' ? '等生产主管登记换货到货' : '等生产主管登记退货发出';
}

// ------------------------------------------------------------------ 到货 / 验收 / 换货到货 / 退货发出 登记
export const MODE_ORDER = ['arrive', 'inspect', 'exchange', 'return'];
export const MODE_CONFIG = {
  arrive: {
    label: '登记到货', column: '本次到货', dateLabel: '到货日期', fileLabel: '送货单 / 收料单 / 入库单', submit: '登记到货',
    api: 'record_po_receipt', dateParam: 'arrival_date', flag: 'receipt',
    warn: '登记后：本次到货的物料验收结果重置为“待验收”，各期付款条件重新判断。到货记录不能撤销，请核对数量。暂不支持分批到货：一项物料一次到齐。',
    done: '到货已登记，付款条件已重新判断',
  },
  inspect: {
    label: '登记验收', column: '本次验收', dateLabel: '验收日期', fileLabel: '验收记录 / 照片 / 报告', submit: '登记验收',
    api: 'record_po_inspection', dateParam: 'inspection_date', flag: 'inspect',
    warn: '每项选“通过”或“换货 / 退货”；换货、退货必须写原因。提交后已通过的物料不再出现在这里，请核对后再提交。',
    done: '验收结果已登记，付款条件已重新判断',
  },
  exchange: {
    label: '登记换货到货', column: '换货到货', dateLabel: '换货到货日期', fileLabel: '换货送货单', submit: '登记换货到货',
    api: 'record_po_exchange_receipt', dateParam: 'arrival_date', flag: 'exchange',
    warn: '供应商补发的换货物料到了：登记后这项回到“待验收”，已到数量不变。',
    done: '换货到货已登记，这些物料回到待验收',
  },
  return: {
    label: '登记退货发出', column: '退货数量', dateLabel: '退货日期', fileLabel: '退货单 / 物流单', submit: '登记退货发出',
    api: 'record_po_return', dateParam: 'return_date', flag: 'return',
    warn: `货已退回供应商：登记后这项已到数量清零；供应商补发后再登记到货。${REFUND_NOTICE}。`,
    done: '退货发出已登记，已到数量清零，等供应商补发',
  },
};

// 每种登记各自可以操作哪些物料行。
export function eligibleLines(mode, lines = []) {
  return (lines || []).filter((line) => {
    const s = lineState(line);
    if (mode === 'arrive') return s.left > 0 && s.key !== 'returning';
    if (mode === 'inspect') return s.recv > 0 && !['passed', 'exchanging', 'returning'].includes(s.key);
    if (mode === 'exchange') return s.key === 'exchanging';
    if (mode === 'return') return s.key === 'returning';
    return false;
  });
}

export function fulfilmentModes(group, { canFulfil = false } = {}) {
  if (!group || !canFulfil) return [];
  if (group.po_status && !FULFILMENT_PO_STATUSES.includes(group.po_status)) return [];
  return MODE_ORDER.filter((mode) => {
    const flag = group.flags?.[MODE_CONFIG[mode].flag];
    if (flag === false) return false;
    return eligibleLines(mode, group.lines).length > 0;
  }).map((key) => ({ key, label: MODE_CONFIG[key].label }));
}

export function pickMode(modes, preferred) {
  if (!modes.length) return '';
  return modes.some((m) => m.key === preferred) ? preferred : modes[0].key;
}

// 输入框的默认值：到货 = 这行还没到的数量；换货到货 / 退货 = 这行已到数量。
export function defaultQuantity(mode, line) {
  const s = lineState(line);
  if (mode === 'arrive') return s.left;
  if (mode === 'exchange' || mode === 'return') return s.recv;
  return 0;
}
export function enteredQuantity(mode, line, drafts = {}) {
  const raw = drafts?.[line.name];
  if (raw === undefined || raw === null) return defaultQuantity(mode, line);
  if (text(raw) === '') return 0;
  return num(raw);
}

// drafts: 到货 / 换货到货 / 退货 -> { 行名: 数量 }；验收 -> { 行名: { result, reason } }。返回 { error, lines }。
export function validateFulfilment(mode, group, drafts = {}, meta = {}) {
  const lines = eligibleLines(mode, group?.lines || []);
  const picked = [];
  if (mode === 'inspect') {
    for (const line of lines) {
      const d = drafts?.[line.name] || {};
      const result = text(d.result);
      if (!result) continue;
      if (!INSPECT_CHOICES.some((c) => c.value === result)) return { error: '验收结果无效', lines: [] };
      if (result !== '已通过' && !text(d.reason)) return { error: `${text(line.item_name) || text(line.material_serial)}：换货 / 退货必须填写原因`, lines: [] };
      picked.push({ line: line.name, status: result, reason: result === '已通过' ? '' : text(d.reason) });
    }
    if (!picked.length) return { error: '请至少选择一项验收结果', lines: [] };
  } else {
    for (const line of lines) {
      const raw = drafts?.[line.name];
      const name = text(line.item_name) || text(line.material_serial);
      if (raw !== undefined && raw !== null && text(raw) !== '' && (!Number.isFinite(Number(raw)) || Number(raw) < 0)) {
        return { error: `${name}：数量必须是大于 0 的数字`, lines: [] };
      }
      const qty = enteredQuantity(mode, line, drafts);
      if (qty <= 0) continue; // 留空或 0 = 这一行本次不登记
      const s = lineState(line);
      if (mode === 'arrive') {
        if (qty > s.left + EPS) return { error: `${name}：到货数量不能超过未到数量 ${quantity(s.left)}`, lines: [] };
        if (qty + EPS < s.left) return { error: `${name}：暂不支持分批到货，请一次登记到齐（${quantity(s.left)}）`, lines: [] };
      } else if (qty > s.recv + EPS) {
        return { error: `${name}：数量不能超过已到数量 ${quantity(s.recv)}`, lines: [] };
      }
      picked.push({ line: line.name, quantity: round4(qty) });
    }
    if (!picked.length) return { error: mode === 'arrive' ? '请填写至少一项本次到货数量' : '请填写至少一项物料的数量', lines: [] };
  }
  if (!text(meta.date)) return { error: `请填写${MODE_CONFIG[mode].dateLabel}`, lines: [] };
  if (!text(meta.fileRef)) return { error: `请上传${MODE_CONFIG[mode].fileLabel}`, lines: [] };
  return { error: '', lines: picked };
}

export function buildFulfilmentRequest(mode, po, lines, meta = {}) {
  const config = MODE_CONFIG[mode];
  const params = { name: po, lines: JSON.stringify(lines), [config.dateParam]: meta.date, file_ref: meta.fileRef };
  if (text(meta.note)) params.note = text(meta.note);
  return { method: config.api, params };
}

export function fulfilmentRoleNote({ canFulfil = false, canPurchase = false, modeCount = 0, poStatus = '' }) {
  if (canFulfil && modeCount > 0) return '';
  if (canFulfil) return poStatus === '已关闭' ? '这张 PO 已关闭。' : '这张 PO 当前没有需要登记的到货或验收。';
  if (canPurchase) return '到货和验收由生产主管登记，你在这里看进度；有“换货 / 退货”时跟进供应商。条件满足后，在下面对应期次点“提交付款审批”。';
  return '到货和验收由生产主管登记，这里只能查看；你的审批工作在“付款审批单”页签。';
}
export function roleHint({ canFulfil = false, canPurchase = false }) {
  if (canFulfil) return '生产主管：登记到货、验收、换货到货、退货发出';
  if (canPurchase) return '采购：只读，负责提交付款审批';
  return '只读';
}

// ------------------------------------------------------------------ 付款期次卡片
export function installmentView(item = {}, group = null, { canPurchase = false } = {}) {
  const ev = evaluateItem(item, group);
  const draft = text(item.draft_request);
  const flag = item.can_push_payment;
  const canPush = (flag === undefined || flag === null
    ? Boolean(canPurchase) && ev.status === '可提交付款审批'
    : Boolean(Number(flag)) && ev.status === '可提交付款审批');
  const regressed = conditionsRegressed(item, ev);
  const requestSummary = item.payment_request_summary || {};
  const gates = gateTiles({
    contractOk: ev.contractOk, trigger: ev.trigger, summary: ev.summary, invoiceRequirement: item.invoice_requirement,
  });
  return {
    key: item.key || `${item.po}:${item.payment_plan_row}`,
    po: text(item.po), planRow: text(item.payment_plan_row),
    title: `${text(item.installment_name)} · ${text(item.payment_stage)} ${num(item.percentage)}%`,
    status: ev.status, tone: STATUS_TONE[ev.status] || 'gray',
    trigger: ev.trigger, invoice: text(item.invoice_requirement) || '未约定', planned: text(item.planned_date),
    amount: num(item.amount), blockers: ev.blockers, gates, canPush, regressed,
    draft, draftText: draft ? draftNote(draft) : '',
    regressionText: regressed ? regressionNote(ev.blockers) : '',
    paymentRequest: text(item.payment_request),
    waitFor: waitingFor({ status: ev.status, summary: ev.summary, canPush, draft, requestSummary, paymentRequest: item.payment_request }),
  };
}

export function groupHeader(group) {
  return {
    po: group.po, supplier: group.supplier, status: group.po_status,
    tone: PO_STATUS_TONE[group.po_status] || 'gray',
    source: group.sources.join('、'), total: group.total, paid: group.paid, currency: group.currency,
    recvText: `${group.summary.recvN}/${group.summary.total} 项`, inspText: `${group.summary.inspN}/${group.summary.total} 项`,
  };
}

// ------------------------------------------------------------------ 付款审批单
export function mergeRequestRows(...lists) {
  const rows = lists.flat().filter((row) => row && row.request_type === '采购付款');
  return [...new Map(rows.map((row) => [row.name, row])).values()];
}
export function isActionable(request) { return Boolean(request?.can_approve || request?.can_reject); }
export function sortQueue(rows = []) {
  return rows.map((r, i) => [r, i]).sort((a, b) => (Number(isActionable(b[0])) - Number(isActionable(a[0]))) || a[1] - b[1]).map((x) => x[0]);
}
export function queueFilter(rows = [], filter = 'all', { employee = '' } = {}) {
  if (filter === 'todo') return rows.filter(isActionable);
  if (filter === 'mine') return rows.filter((r) => (employee ? text(r.employee) === text(employee) : Boolean(r.can_withdraw)));
  return rows;
}
export function waitedDays(request = {}, now = Date.now()) {
  const stamps = (request.steps || []).map((s) => s.acted_on).filter(Boolean).map(String).sort();
  const since = stamps[stamps.length - 1] || request.submitted_on || request.creation || request.modified;
  const time = Date.parse(text(since).replace(' ', 'T'));
  return Number.isFinite(time) ? Math.max(0, Math.floor((now - time) / 86400000)) : null;
}
export function waitText(days) {
  if (days === null || days === undefined) return '—';
  return days ? `等了 ${days} 天` : '今天';
}
export function requestTone(status) {
  if (['待审批', '待办理', '待流转'].includes(status)) return 'sun';
  if (['已完成', '已付款', '已处理'].includes(status)) return 'jade';
  if (['已驳回', '已撤回', '已取消', '已拒绝'].includes(status)) return 'red';
  if (status === '草稿') return 'gray';
  return 'cobalt';
}
export function currentStepOf(request = {}) {
  return (request.steps || []).find((s) => Number(s.step_index) === Number(request.current_step_index)) || null;
}
export function currentStepKey(request = {}) {
  const step = currentStepOf(request);
  return text(step?.step_key || request.current_step_key || request.current_step_label);
}
// 最后一步“总经理付款”是办理节点，按钮写“确认付款”。
export function approveLabel(request = {}) {
  const step = currentStepOf(request);
  const mode = text(step?.mode) || text(request.current_step_mode) || 'approve';
  if (mode === 'handle') return text(step?.label || request.current_step_label).includes('总经理付款') ? '确认付款' : '办理完成';
  return '审批通过';
}
export function isFinalPayStep(request = {}) { return approveLabel(request) === '确认付款'; }
export function rejectionTargets(request = {}) {
  const list = Array.isArray(request.rejection_targets) ? request.rejection_targets : [];
  return list.filter((t) => t && t.target !== undefined).map((t) => ({ target: t.target, label: text(t.label) || String(t.target) }));
}
export function defaultRejectTarget(request = {}) {
  const targets = rejectionTargets(request);
  return (targets.find((t) => t.target === 'applicant') || targets[0] || { target: 'applicant' }).target;
}
export function validateReject({ reason, target }) {
  if (!text(reason)) return '驳回时必须填写原因';
  if (text(target) === '') return '请选择驳回到哪里';
  return '';
}
export function stepRows(request = {}) {
  const current = Number(request.current_step_index || 0);
  const active = ['待审批', '待办理'].includes(request.workflow_status);
  return (request.steps || []).map((step, i) => {
    const index = Number(step.step_index ?? i + 1);
    let state = 'todo';
    if (['已通过', '已办理', '已审批', '已完成', '已处理'].includes(step.status)) state = 'done';
    else if (['已拒绝', '已驳回'].includes(step.status)) state = 'rejected';
    else if (active && index === current) state = 'now';
    const when = step.acted_on ? text(step.acted_on).replace('T', ' ').slice(0, 16) : '';
    const who = text(step.action_by);
    const sub = state === 'done' ? `${step.mode === 'handle' ? '已办理' : '已通过'}${who ? ` · ${who}` : ''}${when ? ` · ${when}` : ''}`
      : state === 'rejected' ? `已驳回${who ? ` · ${who}` : ''}${when ? ` · ${when}` : ''}`
        : state === 'now' ? (step.mode === 'handle' ? '待办理' : '待审批') : '未开始';
    return { key: text(step.step_key) || `${index}-${step.label}`, index, label: text(step.label), state, sub, note: text(step.note), mode: step.mode };
  });
}

// ---- 业务资料（发票）
export function activeDocuments(documents = []) {
  const latest = new Map();
  for (const row of documents || []) {
    if (!row) continue;
    if (text(row.status) === '已作废') continue;
    const prev = latest.get(row.document_type);
    if (!prev || num(row.version_no) > num(prev.version_no)) latest.set(row.document_type, row);
  }
  return latest;
}
export function activeDocumentTypes(documents = []) { return [...activeDocuments(documents).keys()]; }
export function invoiceDocCount(documents = []) {
  return (documents || []).filter((d) => d && text(d.document_type) === '发票' && text(d.status) !== '已作废').length;
}
// PO 下推的付款：报价和合同属于 PO，不再要求；只有“付款前提供”的发票是必须的，补充资料随便传。
export function poPaymentChecklist(documents = [], invoiceRequirement = '') {
  const requirement = text(invoiceRequirement);
  const count = invoiceDocCount(documents);
  if (requirement === INVOICE_BEFORE) {
    return [{ key: 'invoice', label: '发票', required: true, satisfied: count > 0, state: count > 0 ? '已满足' : '待补资料', tone: count > 0 ? 'jade' : 'sun', hint: '本期要求付款前提供；确认付款时系统会检查', uploadTypes: ['发票'], count }];
  }
  if (requirement === INVOICE_AFTER) {
    return [{ key: 'invoice', label: '发票', required: false, satisfied: true, state: '付款后提供', tone: 'gray', hint: '本期要求付款后补发票，不影响确认付款', uploadTypes: ['发票'], count }];
  }
  return [];
}
// 没有来源 PO 的旧采购付款：沿用旧的资料清单（报价 / 合同 / 发票 …）。
export function legacyChecklist(request = {}, documents = []) {
  return documentChecklistForRequest(request, documents).map((entry) => ({
    key: entry.key, label: entry.label, required: entry.required, satisfied: entry.satisfied,
    state: entry.satisfied ? '已满足' : '待补资料', tone: entry.satisfied ? 'jade' : 'sun',
    hint: entry.description, uploadTypes: entry.uploadTypes || [], matched: entry.matchedTypes || [],
  }));
}
export function missingRequired(checklist = []) { return checklist.filter((c) => c.required && !c.satisfied); }
export function removeNeedsReason(request = {}) { return text(request.workflow_status) !== '草稿'; }
export function validateRemoveReason(request, reason) {
  return removeNeedsReason(request) && !text(reason) ? '审批开始后的资料会保留审计记录，请填写作废原因' : '';
}

// ---- 来源 PO 的履约记录 / 物料进度
export function requestRecords(request = {}, group = null) {
  const own = request.po_fulfilment_records || request.po_fulfillment_records;
  const rows = Array.isArray(own) && own.length ? own : (group?.records || []);
  return sortRecordsDesc(normalizeRecords(rows));
}
export function findWorkItem(items = [], request = {}) {
  const po = text(request.source_purchase_order);
  const row = text(request.source_po_payment_plan_row);
  return (items || []).find((item) => text(item.po) === po && row && text(item.payment_plan_row) === row)
    || (items || []).find((item) => text(item.payment_request) === text(request.name))
    || null;
}
export function isPoSourced(request = {}) { return Boolean(text(request?.source_purchase_order)); }
// 审批单上的“本期付款条件复核”：用工作项（整张 PO 的物料）实时重算；没有 PO 查看权限就只能给出记录。
export function liveReview(request = {}, items = [], groups = [], documents = []) {
  const item = findWorkItem(items, request);
  if (!item) return { available: false, item: null, group: null, tiles: [], ev: null };
  const group = (groups || []).find((g) => g.po === text(item.po)) || null;
  const ev = evaluateItem(item, group);
  const tiles = gateTiles({
    contractOk: ev.contractOk, trigger: ev.trigger, summary: ev.summary,
    // 审批人常常没有权限读资料清单：以服务端数好的发票份数为准（两边取大）。
    invoiceRequirement: item.invoice_requirement, invoiceDocs: Math.max(invoiceDocCount(documents), num(item.invoice_documents)),
  });
  return { available: true, item, group, tiles, ev, blockers: ev.blockers, regressed: conditionsRegressed(item, ev) };
}
export function poLinesView(request = {}, group = null) {
  if (group) {
    return group.lines.map((line) => {
      const s = lineState(line);
      return { key: line.name, name: text(line.item_name), spec: text(line.specification), qty: `${quantity(line.quantity)} ${text(line.unit)}`.trim(), recv: `${quantity(line.received_quantity)} ${text(line.unit)}`.trim(), state: s, amount: line.amount !== undefined && line.amount !== null && line.amount !== '' ? num(line.amount) : num(line.quantity) * num(line.unit_price), hint: lineHint(line, group.records, false) };
    });
  }
  const lines = Array.isArray(request.po_lines) && request.po_lines.length ? request.po_lines : (request.business_lines || []);
  return lines.map((line, i) => {
    const s = lineState(line);
    const known = line.received_quantity !== undefined;
    return { key: line.name || i, name: text(line.item_name), spec: text(line.specification), qty: `${quantity(line.quantity)} ${text(line.unit)}`.trim(), recv: known ? `${quantity(line.received_quantity)} ${text(line.unit)}`.trim() : '—', state: known ? s : null, amount: line.amount !== undefined && line.amount !== null && line.amount !== '' ? num(line.amount) : num(line.quantity) * num(line.unit_price), hint: '' };
  });
}
export function paymentFacts(request = {}, item = null, group = null) {
  const plan = group ? group.items.map((i) => `${text(i.payment_stage)} ${num(i.percentage)}%`).join(' / ') : '';
  return [
    ['付款阶段', text(request.payment_stage || item?.payment_stage) || '—'],
    ['本期比例', item ? `${num(item.percentage)}%` : '—'],
    ['来源类型', text(request.source_type) || 'PO付款下推'],
    ['来源 PO', text(request.source_purchase_order) || '—'],
    ['付款计划', plan || '—'],
    ['供应商', text(request.supplier || item?.supplier || group?.supplier) || '—'],
    ['计划付款日', text(item?.planned_date || request.expected_arrival_date) || '—'],
    ['申请时间', formatTime(request.creation)],
  ].map(([k, v]) => ({ k, v }));
}
export function approvalBanner(request = {}, { canAct = false, finalPay = false, review = null } = {}) {
  if (text(request.workflow_status) === '草稿') {
    return { tone: 'warn', text: '这张付款单已被退回，现在是草稿。付款工作项里这一期不会再开放提交，避免重复付款；请先处理这张草稿。' };
  }
  if (canAct && finalPay) {
    const blocked = review?.available && review.blockers?.length;
    return { tone: blocked ? 'warn' : 'act', text: blocked ? `轮到你“确认付款”（最后一步）。但本期条件现在不满足：${review.blockers.join('；')}。确认时系统会拦下，请先让生产主管登记到货 / 验收，或驳回。` : '轮到你“确认付款”（最后一步）。系统会再检查：合同已生效、本期到货 / 验收条件、发票（本期要求付款前提供）。条件都满足，可以确认。' };
  }
  if (canAct) return { tone: review?.available && review.blockers?.length ? 'warn' : 'act', text: `轮到你审批（${text(request.current_step_label) || '当前步骤'}）。${review?.available && review.blockers?.length ? `注意：本期条件现在不满足（${review.blockers.join('；')}）。` : '前面几级审批要自己看下面的条件复核，别等到最后一步被拦下。'}` };
  if (request.can_withdraw) return { tone: 'plain', text: '你是申请人：审批没结束前可以撤回，撤回后期次回到“可提交付款审批”。付款后不能撤回。' };
  return { tone: 'plain', text: '只读。你可以看到条件复核、到货验收进度和审批进度。' };
}

// ---- 旧数据（没有来源 PO 的采购付款）：到货 / 验收 / 预付款跟进 / 退款 / 核销 / 关闭
export function legacyActions(request = {}, documents = [], { canManageExpense = false } = {}) {
  if (isPoSourced(request)) return { show: false };
  const types = activeDocumentTypes(documents);
  return {
    show: text(request.workflow_status) === '已付款',
    arrival: canRecordArrival(request, types),
    inspection: canRecordInspection(request, types),
    followup: text(request.payment_stage) === '预付款',
    refund: Boolean(canManageExpense) && canCompleteSupplierRefund(request, types),
    writeoff: canWriteoffPrepayment(request, types),
    close: canCloseProcurement(request, types),
  };
}
