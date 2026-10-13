// 薪酬计算页的纯函数：每行的状态和金额、合计、图表数据、计算前检查、对账。
// 金额沿用 payrollAmounts.js（未保存的行按页面上正在改的数字现算，已保存的行以工资单为准）。
import { isSavedPayroll, payrollAdjusted, payrollNet, payrollPayable, payrollProrated } from './payrollAmounts.js';
import { displayDepartment } from './displayBrand.js';

const n = (value) => Number(value || 0);
export const round2 = (value) => Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
export const money = (value) => (value == null ? '—' : n(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const near = (a, b) => Math.abs(n(a) - n(b)) < 0.005;

// ---------------------------------------------------------------- 每一行
// 已确认的工资条和别处生成的草稿不能在这里改（已确认的要改，先撤回确认）。
export function rowLocked(row) {
  return Number(row?.docstatus) === 1 || Boolean(row?.salary_slip && !row.managed);
}

export function rowState(row) {
  if (Number(row?.docstatus) === 1) return { key: 'submitted', label: '已确认', tone: 'p-jade' };
  if (row?.salary_slip) return row.managed ? { key: 'draft', label: '草稿', tone: 'p-cobalt' } : { key: 'external', label: '外部草稿', tone: 'p-sun' };
  const noSocial = !row?.social_record_exists, noFund = !row?.housing_record_exists;
  if (noSocial || noFund) return { key: 'blocked', label: noSocial && noFund ? '缺社保公积金记录' : noSocial ? '缺社保记录' : '缺公积金记录', tone: 'p-red' };
  return { key: 'new', label: '未生成', tone: 'p-gray' };
}

export const canSave = (row) => !rowLocked(row) && Boolean(row?.social_record_exists) && Boolean(row?.housing_record_exists);

export function figures(row) {
  const social = n(row?.social_insurance), fund = n(row?.housing_fund), tax = n(row?.income_tax), dorm = n(row?.accommodation), advanced = n(row?.advanced_paid);
  return {
    saved: isSavedPayroll(row || {}), adjusted: n(payrollAdjusted(row)), prorated: n(payrollProrated(row)), payable: n(payrollPayable(row)),
    social, fund, tax, dorm, advanced, other: dorm + advanced, deductions: social + fund + tax + dorm + advanced, net: n(payrollNet(row)),
  };
}

// 本月按天折算（入职、离职当月）：计薪天数少于应计薪天数。
export const isProrated = (row) => n(row?.total_working_days) > 0 && n(row?.payment_days) < n(row?.total_working_days);

// ---------------------------------------------------------------- 筛选
export const CHIPS = Object.freeze([
  { key: 'all', label: '全部' }, { key: 'new', label: '未生成' }, { key: 'draft', label: '草稿' }, { key: 'submitted', label: '已确认' }, { key: 'issue', label: '需处理' },
]);

// 确认本月工资：本页生成的草稿（别处生成的草稿不在这里确认）。
export const confirmTargets = (rows) => (rows || []).filter((row) => rowState(row).key === 'draft');

// ---------------------------------------------------------------- 改了还没保存（审查 2026-10-13）
// 抽屉里的输入框直接改这一行的数字；确认本月工资锁定的是已保存的草稿，所以有人改了没保存时不让确认。
export const EDITABLE_FIELDS = Object.freeze(['payment_days', 'base_salary', 'salary_adjustment', 'company_subsidy', 'bonus', 'other_adjustment', 'income_tax', 'advanced_paid']);

// 行加载时记下每个人可改的输入：{员工: {字段: 数字}}。
export function editSnapshot(rows) {
  const snapshot = {};
  (rows || []).forEach((row) => {
    if (row?.employee) snapshot[row.employee] = Object.fromEntries(EDITABLE_FIELDS.map((key) => [key, n(row[key])]));
  });
  return snapshot;
}

// 和加载时比，有输入改过的行（输入框给的是字符串，按数字比；空当 0）。
export function dirtyRows(rows, snapshot) {
  return (rows || []).filter((row) => {
    const before = snapshot?.[row?.employee];
    return Boolean(before) && EDITABLE_FIELDS.some((key) => !near(row[key], before[key]));
  });
}

// 撤回确认：本页生成、已经确认的工资条。
export const canWithdraw = (row) => Number(row?.docstatus) === 1 && Boolean(row?.managed);

// 筛选页签：草稿 = 已生成、还没提交的工资条（包括别处生成的外部草稿，和看板的「草稿工资条」同口径）；
// 需处理 = 缺社保或公积金记录、不能保存的人。
export function chipOf(row) {
  const key = rowState(row).key;
  if (key === 'blocked') return 'issue';
  return key === 'external' ? 'draft' : key;
}

export function chipCounts(rows) {
  const counts = { all: (rows || []).length, new: 0, draft: 0, submitted: 0, issue: 0 };
  (rows || []).forEach((row) => { counts[chipOf(row)] += 1; });
  return counts;
}

export function filterRows(rows, { chip = 'all', query = '', company = 'all' } = {}) {
  const text = String(query || '').trim();
  return (rows || []).filter((row) => (company === 'all' || row.company === company)
    && (chip === 'all' || chipOf(row) === chip)
    && (!text || String(row.employee_name || '').includes(text)));
}

// ---------------------------------------------------------------- 合计和图表
export function totalsOf(rows) {
  const total = { people: 0, payable: 0, contrib: 0, social: 0, fund: 0, tax: 0, other: 0, dorm: 0, advanced: 0, net: 0, dormPeople: 0, advancedPeople: 0 };
  (rows || []).forEach((row) => {
    const f = figures(row);
    total.people += 1; total.payable += f.payable; total.social += f.social; total.fund += f.fund; total.tax += f.tax;
    total.dorm += f.dorm; total.advanced += f.advanced; total.net += f.net;
    if (f.dorm) total.dormPeople += 1;
    if (f.advanced) total.advancedPeople += 1;
  });
  total.contrib = total.social + total.fund;
  total.other = total.dorm + total.advanced;
  Object.keys(total).forEach((key) => { total[key] = round2(total[key]); });
  return total;
}

export const DONUT_COLORS = Object.freeze({ net: '#2F7A55', contrib: '#7A56B8', tax: '#B42318', other: '#D9731F' });

export function chartParts(total) {
  const parts = [
    { key: 'net', label: '实发工资', value: total.net }, { key: 'contrib', label: '社保公积金', value: total.contrib },
    { key: 'tax', label: '个税', value: total.tax }, { key: 'other', label: '宿舍及已发放', value: total.other },
  ].map((part) => ({ ...part, color: DONUT_COLORS[part.key] }));
  const sum = parts.reduce((t, part) => t + Math.max(part.value, 0), 0);
  return parts.map((part) => ({ ...part, share: sum ? Math.max(part.value, 0) / sum : 0 }));
}

// 各部门应付和实发（应付最高的几个部门）。
export function deptBars(rows, limit = 6) {
  const map = new Map();
  (rows || []).forEach((row) => {
    const name = displayDepartment(row.department) || '未设置部门';
    const f = figures(row);
    const item = map.get(name) || { name, people: 0, payable: 0, net: 0 };
    item.people += 1; item.payable += f.payable; item.net += f.net;
    map.set(name, item);
  });
  const list = [...map.values()].sort((a, b) => b.payable - a.payable).slice(0, limit);
  const top = Math.max(...list.map((item) => item.payable), 1);
  return list.map((item) => ({ ...item, payable: round2(item.payable), net: round2(item.net), payableWidth: item.payable / top * 100, netWidth: Math.min(item.net, item.payable) / top * 100 }));
}

export const BUCKETS = Object.freeze([['8千以下', 0, 8000], ['8–12千', 8000, 12000], ['12–16千', 12000, 16000], ['16–20千', 16000, 20000], ['2万以上', 20000, Infinity]]);

export function netBuckets(rows) {
  const counts = BUCKETS.map(([label, low, high]) => ({ label, count: (rows || []).filter((row) => { const net = figures(row).net; return net >= low && net < high; }).length }));
  const top = Math.max(...counts.map((item) => item.count), 1);
  return counts.map((item) => ({ ...item, height: item.count / top }));
}

// 费用科目（研发费用 / 管理费用）占应付工资的比例，成本分摊的依据。
export function accountShare(rows) {
  const map = new Map();
  (rows || []).forEach((row) => { const key = row.expense_account_category || '未设置'; map.set(key, (map.get(key) || 0) + figures(row).payable); });
  const sum = [...map.values()].reduce((t, value) => t + value, 0);
  return [...map.entries()].map(([name, value]) => ({ name, value: round2(value), share: sum ? value / sum : 0 })).sort((a, b) => b.value - a.value);
}

// ---------------------------------------------------------------- 计算前检查
export function readiness(rows) {
  const list = rows || [];
  return {
    total: list.length,
    missingSocial: list.filter((row) => !row.social_record_exists).length,
    missingFund: list.filter((row) => !row.housing_record_exists).length,
    dormPeople: list.filter((row) => n(row.accommodation) > 0).length,
    prorated: list.filter(isProrated).length,
    workingDays: list.length ? Math.max(...list.map((row) => n(row.total_working_days))) : 0,
    calendarFallback: list.filter((row) => row.working_days_source === 'calendar_fallback').length,
  };
}

// ---------------------------------------------------------------- 对账
// 工资表里的社保 / 公积金个人合计，和已生效批次的个人合计逐项核对。批次没有生效（或还没接口数据）时只说明情况，不拿 0 当结果。
export function reconRows({ total, social, fund }) {
  const item = (key, label, system, batch, otherLabel, hint) => {
    if (!batch || batch.status !== 'Current') return { key, label, system, other: null, otherLabel, diff: null, status: 'na', hint: batch ? '批次还没有确认生效' : '本期还没有导入' };
    const diff = round2(system - n(batch.total));
    return { key, label, system, other: n(batch.total), otherLabel, diff, status: near(diff, 0) ? 'ok' : 'diff', hint };
  };
  return [
    item('social', '社保（个人）合计', total.social, social, '社保批次合计', '工资表读取的社保记录与生效批次对不上'),
    item('fund', '公积金（个人）合计', total.fund, fund, '公积金批次合计', '工资表读取的公积金记录与生效批次对不上（例如申报表里没有、按需补缴记账的人）'),
  ];
}

// 工作台返回的批次信息整理成对账要用的样子：只认当前生效批次。
export function currentBatchTotal(workbench) {
  const batch = (workbench?.batches || []).find((item) => item.status === 'Current') || (workbench?.batches || [])[0] || null;
  return batch ? { status: batch.status, total: n(workbench?.dashboard?.employee_total) } : null;
}
