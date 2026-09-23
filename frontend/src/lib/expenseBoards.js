// 看板前端逻辑：三个页签、卡片口径、趋势条的比例与逾期着色。
export const BOARD_TABS = Object.freeze([
  { key: 'request', label: '申请看板', path: '/approval/expense-request-board', method: 'expense_board_entry.request_board', hint: '购买申请与出差申请；采购申请在采购看板。' },
  { key: 'payment', label: '付款看板', path: '/approval/expense-payment-board', method: 'expense_board_entry.payment_board', hint: '报销单与付款单，金额按实际付款日期计入月份。' },
  { key: 'procurement', label: '采购看板', path: '/approval/expense-payment-board', method: 'expense_board_entry.procurement_board', hint: '采购申请与采购付款单独统计：到货、验收、预付款核销。' },
]);

export function tabFor(path, query = {}) {
  const wanted = String(query.tab || '').trim();
  if (BOARD_TABS.some((tab) => tab.key === wanted)) return wanted;
  return path === '/approval/expense-request-board' ? 'request' : 'payment';
}

export function requestCards(data = {}) {
  const summary = data.summary || {};
  return [
    { key: 'approved_amount', label: '已批准金额', value: summary.approved_amount || 0, money: true },
    { key: 'unpaid_amount', label: '已批准未付出', value: summary.unpaid_amount || 0, money: true, tone: 'amber' },
    { key: 'reserved_amount', label: '已占用（在途单据）', value: summary.reserved_amount || 0, money: true },
    { key: 'paid_amount', label: '已付款', value: summary.paid_amount || 0, money: true, tone: 'emerald' },
    { key: 'stale', label: `超过 ${data.stale_days || 30} 天未执行`, value: (data.stale_applications || []).length },
    { key: 'stuck', label: `审批卡点（等待 ${data.stuck_days || 3} 天以上）`, value: (data.stuck_approvals || []).filter((row) => row.overdue).length, tone: 'red' },
  ];
}

export function paymentCards(data = {}) {
  const summary = data.summary || {};
  return [
    { key: 'reimbursement_paid', label: `本月已付·报销（${summary.month || ''}）`, value: summary.reimbursement_paid || 0, money: true },
    { key: 'payment_paid', label: '本月已付·付款', value: summary.payment_paid || 0, money: true },
    { key: 'paid_total', label: '本月已付合计', value: summary.paid_total || 0, money: true, tone: 'emerald' },
    { key: 'cashier_pending', label: '出纳待办', value: summary.cashier_pending || 0, tone: 'amber' },
    { key: 'invoice_pending', label: '待补票', value: summary.invoice_pending || 0 },
    { key: 'invoice_overdue', label: '补票逾期', value: summary.invoice_overdue || 0, tone: 'red' },
  ];
}

export function procurementCards(data = {}) {
  const summary = data.summary || {};
  return [
    { key: 'application_count', label: '采购申请', value: summary.application_count || 0 },
    { key: 'application_amount', label: '采购申请金额', value: summary.application_amount || 0, money: true },
    { key: 'payment_count', label: '采购付款', value: summary.payment_count || 0 },
    { key: 'paid_amount', label: '采购已付款', value: summary.paid_amount || 0, money: true, tone: 'emerald' },
    { key: 'pending_arrival', label: '待到货', value: summary.pending_arrival || 0, tone: 'amber' },
    { key: 'pending_inspection', label: '待验收', value: summary.pending_inspection || 0, tone: 'amber' },
    { key: 'pending_writeoff', label: '待预付款核销', value: summary.pending_writeoff || 0, tone: 'red' },
  ];
}

export function cardTone(tone) {
  return {
    amber: 'border-amber-200 bg-amber-50',
    red: 'border-red-200 bg-red-50',
    emerald: 'border-emerald-200 bg-emerald-50',
  }[tone] || 'bg-gray-50';
}

// 趋势条按同组最大值缩放，最小给 2% 让非零月份看得见。
export function trendBars(trend = []) {
  const max = trend.reduce((peak, row) => Math.max(peak, Number(row.reimbursement || 0) + Number(row.payment || 0)), 0);
  return trend.map((row) => {
    const reimbursement = Number(row.reimbursement || 0);
    const payment = Number(row.payment || 0);
    const scale = (value) => (max <= 0 || value <= 0 ? 0 : Math.max(2, Math.round((value / max) * 100)));
    return { ...row, total: reimbursement + payment, reimbursementHeight: scale(reimbursement), paymentHeight: scale(payment) };
  });
}

export function overdueTone(days) {
  const value = Number(days || 0);
  if (value > 7) return 'text-red-700 font-medium';
  if (value > 0) return 'text-orange-700';
  return 'text-gray-600';
}

export function dueText(row = {}) {
  if (Number(row.overdue_days || 0) > 0) return `已逾期 ${row.overdue_days} 天`;
  if (Number(row.days_left || 0) === 0) return '今天到期';
  return `${row.days_left} 天后到期`;
}

export function boardRoute(requestType) {
  return {
    购买申请: '/approval/direct-purchase',
    出差申请: '/approval/travel',
    报销单: '/approval/claim',
    付款单: '/approval/payment',
    采购申请: '/approval/procurement',
    采购付款: '/approval/procurement-payment',
  }[String(requestType || '').trim()] || '/approval/request-dashboard';
}
