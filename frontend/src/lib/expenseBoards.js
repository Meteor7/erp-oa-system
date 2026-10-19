// 申请看板 / 付款看板的前端口径：指标卡、堆叠柱状图几何、横条图比例、跳转。
import { money } from './expenseClaims.js';
import { canSeeAllTravel } from './travelView.js';
import { resolveKpiTarget } from './navContext.js';
import { STUCK_AFTER_DAYS, isWaitingTooLong } from './waiting.js';

const yuan = (value) => `¥ ${money(value)}`;

// 指标卡可以点：to = { path, query } 跳到对应的列表或页面，to = { anchor } 滚动到本页的某一块。
const page = (path, query) => ({ path, ...(query ? { query } : {}) });

// 看的人能打开哪些"全部"：出差申请的全部只给系统演示员工170 / QIHENG Demo Business Executive；
// 报销单、付款单的全部给财务（系统演示员工170、会计演示员工110）和 QIHENG Demo Business Executive（与 ClaimWorkbench、服务端一致）。
const CLAIM_ALL_ROLES = ['System Manager', 'Accounts User', 'QIHENG Demo Business Executive'];

export function boardAccess(roles = globalThis.window?.roles || []) {
  const list = roles || [];
  return { travelAll: canSeeAllTravel(list), claimAll: list.some((role) => CLAIM_ALL_ROLES.includes(role)) };
}

// 卡片上的链接按看的人的权限处理：打不开"全部"的人，这张卡不再可点（to 为 null，note 说明原因），
// 而不是点进去被悄悄换成"我的"。
function withAccess(cards, access = boardAccess()) {
  return cards.map((card) => {
    const to = resolveKpiTarget(card.to, access);
    return to ? { ...card, to } : { ...card, to: null, note: '你没有查看全部的权限，这张卡只用来看数字' };
  });
}

export function requestKpis(data = {}, access = boardAccess()) {
  const s = data.summary || {};
  return withAccess([
    { key: 'month', label: '本月通过的购买申请', value: yuan(s.month_approved_amount), sub: `${s.month_approved_count || 0} 张`, to: page('/approval/direct-purchase', { view: 'list', scope: 'all' }) },
    { key: 'unpaid', label: '已批准未付出的额度', value: yuan(s.unpaid_amount), sub: '已通过但还没付出去的钱', tone: '#0E615B', to: { anchor: 'bd-budget' } },
    { key: 'pending', label: '审批中', value: `${s.pending_count || 0} 张`, sub: `最久已等 ${s.longest_wait_days || 0} 天`, tone: (s.longest_wait_days || 0) > 3 ? '#B42318' : '', to: { anchor: 'bd-stuck' } },
    { key: 'trip', label: '出差中 / 本月出差', value: `${s.on_trip_count || 0} 人 / ${s.month_trip_count || 0} 次`, sub: '按出发、返回日期', to: page('/approval/travel', { view: 'list', scope: 'all' }) },
  ], access);
}

export function paymentKpis(data = {}, access = boardAccess()) {
  const s = data.summary || {};
  return withAccess([
    { key: 'bx', label: '本月已付 · 报销', value: yuan(s.reimbursement_paid), sub: '员工垫付，按付款日期', to: page('/approval/claim', { view: 'list', scope: 'all', bucket: 'paid' }) },
    { key: 'fk', label: '本月已付 · 付款', value: yuan(s.payment_paid), sub: '对外支付', to: page('/approval/payment', { view: 'list', scope: 'all', bucket: 'paid' }) },
    { key: 'pay', label: '演示员工110待付款', value: yuan(s.to_pay_amount), sub: `${s.to_pay_count || 0} 张，其中加急 ${s.to_pay_urgent || 0} 张`, tone: '#0E615B', to: { anchor: 'bd-cashier' } },
    { key: 'inv', label: '待补票', value: yuan(s.invoice_pending_amount), sub: `${s.invoice_pending_count || 0} 张，逾期 ${s.invoice_overdue_count || 0} 张`, tone: (s.invoice_overdue_count || 0) ? '#B42318' : '', to: { anchor: 'bd-invoices' } },
  ], access);
}

// 采购页签的指标卡。采购付款优先用按 PO 付款期次汇总的 po_work；服务端还没有这一块时退回旧口径
// （不再显示"待预付款核销"：PO 付款不走核销，永远是 0）。
export function procurementKpis(data = {}, part = 'request') {
  const s = data.summary || {};
  if (part === 'request') {
    return [
      { key: 'count', label: '采购申请', value: `${s.application_count || 0} 张`, sub: `审批中 ${s.application_pending || 0} 张`, to: page('/approval/procurement', { view: 'list', scope: 'all' }) },
      { key: 'amount', label: '采购申请金额', value: yuan(s.application_amount), sub: '批准金额，未批准的按申请金额', to: page('/approval/procurement', { view: 'list', scope: 'all' }) },
    ];
  }
  if (hasPoWork(data)) return poWorkKpis(data.po_work);
  // 旧口径没有按期次的数据：按页面认得的状态筛选（PayWorkTab 读 ?status=）。
  return [
    { key: 'paid', label: '本月采购已付', value: yuan(s.month_paid_amount), sub: `采购付款共 ${s.payment_count || 0} 张`, to: page('/approval/procurement-payment', { status: '已付款' }) },
    { key: 'arrival', label: '待到货', value: `${s.pending_arrival || 0} 张`, sub: '已付款未到货', tone: (s.pending_arrival || 0) ? '#0E615B' : '', to: page('/approval/procurement-payment', { status: '待到货资料' }) },
    { key: 'inspect', label: '待验收', value: `${s.pending_inspection || 0} 张`, sub: '已付款未验收', to: page('/approval/procurement-payment', { status: '待验收' }) },
  ];
}

// ---------------------------------------------------------------- 采购付款：按 PO 付款期次的真实状态

export const PO_STATUS_ORDER = Object.freeze(['待演示员工116生效', '待到货资料', '待验收', '可提交付款审批', '付款审批中', '待实际付款', '已付款']);

export function hasPoWork(data = {}) {
  const work = data?.po_work;
  return Boolean(work && typeof work === 'object' && (work.summary || Array.isArray(work.by_status) || Array.isArray(work.pos)));
}

// 四张卡原来都指向同一个页面。现在各去各的：
//   已付 -> 付款工作项里"已付款"；等总经理确认 / 付款审批中 -> 付款审批单页签（PaymentWorkbench 读 ?tab=approvals）；
//   待提交 -> 付款工作项里"可提交付款审批"（PayWorkTab 读 ?status=）。
export function poWorkKpis(work = {}) {
  const s = work.summary || {};
  const path = '/approval/procurement-payment';
  return [
    { key: 'paid', label: '本月采购已付', value: yuan(s.month_paid_amount), sub: `${s.paid_count || 0} 期`, to: page(path, { status: '已付款' }) },
    { key: 'final', label: '等总经理确认付款', value: yuan(s.waiting_final_amount), sub: `${s.waiting_final_count || 0} 张 · 在总经理付款这一步`, tone: '#0E615B', to: page(path, { tab: 'approvals' }) },
    { key: 'approval', label: '付款审批中', value: yuan(s.in_approval_amount), sub: `${s.in_approval_count || 0} 张`, to: page(path, { tab: 'approvals' }) },
    { key: 'ready', label: '待提交付款审批', value: yuan(s.ready_amount), sub: `${s.ready_count || 0} 期 · 采购还没提交`, to: page(path, { status: '可提交付款审批' }) },
  ];
}

// 横条图用：[[ "待到货资料 · 3 期", 金额 ], ...]，按付款期次的处理顺序排。
export function poStatusRows(work = {}) {
  const rank = (status) => (PO_STATUS_ORDER.includes(status) ? PO_STATUS_ORDER.indexOf(status) : PO_STATUS_ORDER.length);
  return [...(work.by_status || [])]
    .map((row) => (Array.isArray(row) ? { status: row[0], count: Number(row[1] || 0), amount: Number(row[2] || 0) } : { status: row.status, count: Number(row.count || 0), amount: Number(row.amount || 0) }))
    .sort((a, b) => rank(a.status) - rank(b.status))
    .map((row) => [`${row.status} · ${row.count} 期`, row.amount]);
}

export function poStatusCount(work = {}) {
  return (work.by_status || []).reduce((sum, row) => sum + Number(Array.isArray(row) ? row[1] : row.count || 0), 0);
}

export function poStatusTone(status) {
  const value = String(status || '').trim();
  if (['到货验收中', '待到货', '待验收', '部分到货'].includes(value)) return 'p-sun';
  if (value === '供应商制作中') return 'p-brand';
  if (['付款中', '待审批'].includes(value)) return 'p-cobalt';
  if (['已关闭', '已付款', '已完成'].includes(value)) return 'p-jade';
  if (['退货中', '换货中'].includes(value)) return 'p-red';
  return 'p-gray';
}

// 各 PO 进度表的一行：到货 / 验收通过按"几项 / 共几项"，已付按金额条。
export function poProgressRows(work = {}) {
  return (work.pos || []).map((po) => {
    const total = Number(po.total_amount || 0);
    const paid = Number(po.paid_amount || 0);
    const lines = Number(po.lines || 0);
    return {
      po: po.po, supplier: po.supplier || '—', status: po.status || '', tone: poStatusTone(po.status),
      received: `${Number(po.received_lines || 0)} / ${lines} 项`, passed: `${Number(po.passed_lines || 0)} / ${lines} 项`,
      receivedDone: lines > 0 && Number(po.received_lines || 0) >= lines, passedDone: lines > 0 && Number(po.passed_lines || 0) >= lines,
      paidText: `${yuan(paid)} / ${yuan(total)}`,
      paidWidth: total > 0 ? `${Math.min(100, (paid / total) * 100).toFixed(1)}%` : '0%',
    };
  });
}

// 到货 / 验收显示成状态标签，不是一串文字。
export function fulfilTone(text) {
  const value = String(text || '').trim();
  if (!value) return 'p-gray';
  if (/不合格|退货|换货/.test(value)) return 'p-red';
  if (/^(已到货|验收通过|已通过|已验收|已完成)/.test(value)) return 'p-jade';
  if (/部分|待|中/.test(value)) return 'p-sun';
  return 'p-gray';
}

// 采购付款单那一行的到货 / 验收标签：能对上 PO 就用 PO 的进度（几项 / 共几项），对不上用单据上的状态。
export function paymentFulfilment(row = {}, work = {}) {
  const po = (work.pos || []).find((item) => item.po && item.po === row.source_purchase_order);
  if (po) {
    const lines = Number(po.lines || 0);
    const received = Number(po.received_lines || 0);
    const passed = Number(po.passed_lines || 0);
    return {
      arrival: { text: `到货 ${received}/${lines}`, tone: lines > 0 && received >= lines ? 'p-jade' : received > 0 ? 'p-sun' : 'p-gray' },
      inspection: { text: `验收 ${passed}/${lines}`, tone: lines > 0 && passed >= lines ? 'p-jade' : passed > 0 ? 'p-sun' : 'p-gray' },
    };
  }
  return {
    arrival: { text: row.arrival_status || '—', tone: row.arrival_status ? fulfilTone(row.arrival_status) : 'p-gray' },
    inspection: { text: row.inspection_status || '—', tone: row.inspection_status ? fulfilTone(row.inspection_status) : 'p-gray' },
  };
}

// 横条图：按同组最大值给宽度百分比。
export function hbarRows(rows = []) {
  const max = Math.max(1, ...rows.map((row) => Number(row[1] || 0)));
  return rows.map(([label, value]) => ({ label, value: Number(value || 0), width: (Number(value || 0) / max) * 100 }));
}

// 近 6 个月堆叠柱状图（报销在下、付款在上），刻度以万元为单位向上取整。
export function stackedChart(trend = [], { width = 560, height = 190, pad = 34, bar = 46 } = {}) {
  const totals = trend.map((row) => Number(row.reimbursement || 0) + Number(row.payment || 0));
  const peak = Math.max(0, ...totals);
  const step = peak > 50000 ? 20000 : peak > 20000 ? 10000 : peak > 5000 ? 2000 : peak > 1000 ? 500 : 100;
  const max = Math.max(step, Math.ceil(peak / step) * step);
  const count = Math.max(1, trend.length);
  const gap = count > 1 ? (width - pad * 2 - bar * count) / (count - 1) : 0;
  const y = (value) => height - 24 - (value / max) * (height - 44);
  const ticks = [];
  for (let value = 0; value <= max; value += step) ticks.push({ value, y: y(value), label: value >= 10000 ? `${value / 10000}万` : String(value) });
  const bars = trend.map((row, index) => {
    const reimbursement = Number(row.reimbursement || 0);
    const payment = Number(row.payment || 0);
    const x = pad + index * (bar + gap);
    return {
      month: row.month, x, width: bar, reimbursement, payment, total: reimbursement + payment,
      reimbursementY: y(reimbursement), reimbursementHeight: y(0) - y(reimbursement),
      paymentY: y(reimbursement + payment), paymentHeight: y(reimbursement) - y(reimbursement + payment),
      labelY: y(reimbursement + payment) - 5, label: `${Number(row.month.slice(5))}月`,
    };
  });
  return { width, height, pad, ticks, bars, baseline: y(0) };
}

export function shortMoney(value) {
  const number = Number(value || 0);
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return money(number);
}

export function dueText(row = {}) {
  if (Number(row.overdue_days || 0) > 0) return { text: `逾期 ${row.overdue_days} 天`, tone: 'p-red' };
  if (Number(row.days_left || 0) === 0) return { text: '今天到期', tone: 'p-sun' };
  return { text: `${row.days_left} 天后到期`, tone: 'p-sun' };
}

export function boardRoute(requestType) {
  return {
    购买申请: '/approval/direct-purchase',
    出差申请: '/approval/travel',
    报销单: '/approval/claim',
    付款单: '/approval/payment',
    采购申请: '/approval/procurement',
    采购付款: '/approval/procurement-payment',
  }[String(requestType || '').trim()] || '/dashboard';
}

export function scopeText(data = {}) {
  if (data.scope === 'department') return `范围：本部门（${data.department || ''}）`;
  if (data.scope === 'all') return '范围：全公司';
  return '';
}

// 看板页签放在地址里（?tab=main|procurement），刷新、分享链接、从别处跳回来都停在同一页签。
export function boardTab(query = {}) {
  return query.tab === 'procurement' ? 'procurement' : 'main';
}

// ?focus=cashier|invoices：从数据看板的卡片点进来，直接滚到付款看板的那一块（id="bd-cashier" / "bd-invoices"）。
const FOCUS_IDS = Object.freeze({ cashier: 'bd-cashier', invoices: 'bd-invoices' });
export function focusAnchor(query = {}) {
  return FOCUS_IDS[String(query.focus || '')] || '';
}

// 底部一排卡片：部门范围没有"今年付给谁最多"，只剩两列，不留空列。
export function bottomColumns(data = {}) {
  return data.scope === 'department' ? 2 : 3;
}

// ---------------------------------------------------------------- 图表（2026-09-30 看板改版）

// 看板统一用的低饱和配色：蓝、沙、绿灰、石板灰、浅灰。
export const CHART_COLORS = Object.freeze(['#5470C6', '#78B8AD', '#7FA38E', '#8C96A8', '#C3CAD6', '#B7A6CF']);

function pairs(rows = []) {
  return (rows || []).map((row) => (Array.isArray(row) ? { label: row[0], value: Number(row[1] || 0) } : { label: row.label, value: Number(row.value || 0) }))
    .filter((row) => row.value > 0);
}

function percentText(part, total) {
  return total > 0 ? `${Math.round((part / total) * 100)}%` : '0%';
}

// 环形图：从大到小，超过 max 类时把后面的合并成"其他"。
export function donutSegments(rows = [], max = 5) {
  const sorted = pairs(rows).sort((a, b) => b.value - a.value);
  const kept = sorted.length > max ? sorted.slice(0, max - 1) : sorted;
  if (sorted.length > max) kept.push({ label: '其他', value: sorted.slice(max - 1).reduce((sum, row) => sum + row.value, 0) });
  const total = kept.reduce((sum, row) => sum + row.value, 0);
  let start = 0;
  const segments = kept.map((row, index) => {
    const end = total > 0 ? start + (row.value / total) * 360 : start;
    const segment = { ...row, color: CHART_COLORS[index % CHART_COLORS.length], share: percentText(row.value, total), from: start, to: end };
    start = end;
    return segment;
  });
  const gradient = segments.length
    ? `conic-gradient(${segments.map((row) => `${row.color} ${row.from.toFixed(1)}deg ${row.to.toFixed(1)}deg`).join(', ')})`
    : 'conic-gradient(#E6E9EF 0deg 360deg)';
  return { total: Math.round(total * 100) / 100, segments, gradient };
}

// 演示员工110待付按等待天数分段。和数据看板「待付款按等待时长」同一套三段（2026-10-13 统一）：
// 今天（0 天）/ 1–3 天 / 超过 3 天（严格大于 3，正好 3 天算在 1–3 天里，见 waiting.js）。
export function agingColumns(queue = []) {
  const buckets = [
    { label: '今天', test: (days) => days <= 0, color: '#C3CAD6' },
    { label: `1–${STUCK_AFTER_DAYS} 天`, test: (days) => days > 0 && !isWaitingTooLong(days), color: '#78B8AD' },
    { label: `超过 ${STUCK_AFTER_DAYS} 天`, test: (days) => isWaitingTooLong(days), color: '#4B9E91' },
  ];
  return buckets.map((bucket) => {
    const rows = (queue || []).filter((row) => bucket.test(Number(row.waited_days || 0)));
    const amount = rows.reduce((sum, row) => sum + Number(row.amount || 0), 0);
    return { label: bucket.label, value: rows.length, color: bucket.color, sub: rows.length ? `¥ ${money(amount)}` : '' };
  });
}

// 演示员工110待付款面板里"待付款"和"待核验"分开：标题上的张数、金额只算待付款（和数据看板「演示员工110待付款」一致），
// 已付款等核验发票的付款单单独列在后面。
export function cashierSplit(queue = []) {
  const rows = queue || [];
  return { toPay: rows.filter((row) => row.status !== '待核验'), verifying: rows.filter((row) => row.status === '待核验') };
}

// 演示员工110待付款面板顶部的三个小方块：各等待区间几张、多少钱，条按张数最多的那一段算宽度。
export function agingTiles(queue = []) {
  const columns = agingColumns(queue);
  const peak = Math.max(1, ...columns.map((column) => column.value));
  return columns.map((column) => ({
    label: column.label, count: column.value, amount: column.sub || '¥ 0.00', color: column.color,
    width: `${((column.value / peak) * 100).toFixed(1)}%`,
  }));
}

// "申请走到哪一步了"：各步按本月提交的张数算宽度。
export function flowBars(flow = []) {
  const colors = { submitted: '#C3CAD6', approved: '#8C96A8', executed: '#5470C6', pending: '#78B8AD' };
  const base = Math.max(1, Number(flow[0]?.count || 0));
  return (flow || []).map((step) => ({ ...step, color: colors[step.key] || '#8C96A8', width: `${Math.min(100, (Number(step.count || 0) / base) * 100).toFixed(1)}%` }));
}

// 额度执行：已付（深蓝）+ 在途（浅蓝），按批准金额算宽度。
export function budgetBars(applications = []) {
  return (applications || []).map((row) => {
    const approved = Number(row.approved_amount || 0);
    const width = (value) => (approved > 0 ? `${Math.min(100, (Number(value || 0) / approved) * 100).toFixed(1)}%` : '0%');
    return { ...row, paidWidth: width(row.paid_amount), reservedWidth: width(row.reserved_amount) };
  });
}

// 卡住的申请：条长按等得最久的一张算。
export function waitBars(pending = [], stuckDays = 3) {
  const longest = Math.max(1, ...(pending || []).map((row) => Number(row.waited_days || 0)));
  return (pending || []).map((row) => ({
    ...row,
    overdue: Boolean(row.overdue) || Number(row.waited_days || 0) > Number(stuckDays || 3),
    width: `${Math.max(4, (Number(row.waited_days || 0) / longest) * 100).toFixed(1)}%`,
  }));
}
