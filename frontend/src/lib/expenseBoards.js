// 申请看板 / 付款看板的前端口径：指标卡、堆叠柱状图几何、横条图比例、跳转。
import { money } from './expenseClaims.js';

const yuan = (value) => `¥ ${money(value)}`;

export function requestKpis(data = {}) {
  const s = data.summary || {};
  return [
    { key: 'month', label: '本月通过的购买申请', value: yuan(s.month_approved_amount), sub: `${s.month_approved_count || 0} 张` },
    { key: 'unpaid', label: '已批准未付出的额度', value: yuan(s.unpaid_amount), sub: '已通过但还没付出去的钱', tone: '#E57A00' },
    { key: 'pending', label: '审批中', value: `${s.pending_count || 0} 张`, sub: `最久已等 ${s.longest_wait_days || 0} 天`, tone: (s.longest_wait_days || 0) > 3 ? '#DC2626' : '' },
    { key: 'trip', label: '出差中 / 本月出差', value: `${s.on_trip_count || 0} 人 / ${s.month_trip_count || 0} 次`, sub: '按出发、返回日期' },
  ];
}

export function paymentKpis(data = {}) {
  const s = data.summary || {};
  return [
    { key: 'bx', label: '本月已付 · 报销', value: yuan(s.reimbursement_paid), sub: '员工垫付，按付款日期' },
    { key: 'fk', label: '本月已付 · 付款', value: yuan(s.payment_paid), sub: '对外支付' },
    { key: 'pay', label: '出纳待付款', value: yuan(s.to_pay_amount), sub: `${s.to_pay_count || 0} 张，其中加急 ${s.to_pay_urgent || 0} 张`, tone: '#E57A00' },
    { key: 'inv', label: '待补票', value: yuan(s.invoice_pending_amount), sub: `${s.invoice_pending_count || 0} 张，逾期 ${s.invoice_overdue_count || 0} 张`, tone: (s.invoice_overdue_count || 0) ? '#DC2626' : '' },
  ];
}

export function procurementKpis(data = {}, part = 'request') {
  const s = data.summary || {};
  if (part === 'request') {
    return [
      { key: 'count', label: '采购申请', value: `${s.application_count || 0} 张`, sub: `审批中 ${s.application_pending || 0} 张` },
      { key: 'amount', label: '采购申请金额', value: yuan(s.application_amount), sub: '批准金额，未批准的按申请金额' },
    ];
  }
  return [
    { key: 'paid', label: '本月采购已付', value: yuan(s.month_paid_amount), sub: `采购付款共 ${s.payment_count || 0} 张` },
    { key: 'arrival', label: '待到货', value: `${s.pending_arrival || 0} 张`, sub: '已付款未到货', tone: (s.pending_arrival || 0) ? '#E57A00' : '' },
    { key: 'inspect', label: '待验收', value: `${s.pending_inspection || 0} 张`, sub: '已付款未验收' },
    { key: 'writeoff', label: '待预付款核销', value: `${s.pending_writeoff || 0} 张`, sub: '100% 预付款', tone: (s.pending_writeoff || 0) ? '#DC2626' : '' },
  ];
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
