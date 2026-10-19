// 数据看板点进来时，地址里带的筛选 → 目标页的状态（纯函数；页面只负责读地址、写回地址）。
// 约定：地址是初始状态的来源，用户改了筛选地址跟着变（router.replace，不产生历史记录），刷新后筛选还在。
import { followUpRows, matchesDepartment, needsRemind } from './timesheetEntryView.js';

const one = (value) => String(Array.isArray(value) ? (value[0] ?? '') : (value ?? '')).trim();

export function currentPeriodText(now = new Date()) {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

// 本地日期 YYYY-MM-DD（合同交期、请假起止都是日期字符串，按字典序就能比较）。
export function todayText(now = new Date()) {
  return `${currentPeriodText(now)}-${String(now.getDate()).padStart(2, '0')}`;
}

// 只认 YYYY-MM；乱写的月份不采用。
export function validPeriod(value) {
  const text = one(value);
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(text) ? text : '';
}

// ---------------------------------------------------------------- 研发工时填报 /entry
export const ENTRY_TABS = Object.freeze(['board', 'sheet']);
// open = 未填 + 未填满（看板上的「还有人没填满」）；其余和填报进度里的状态一一对应。
export const ENTRY_STATUSES = Object.freeze(['none', 'part', 'full', 'over', 'open']);

export function parseEntryQuery(query = {}) {
  const tab = one(query.tab);
  const status = one(query.status);
  return {
    tab: ENTRY_TABS.includes(tab) ? tab : '',
    status: ENTRY_STATUSES.includes(status) ? status : 'all',
    dept: one(query.dept) || 'all',
    period: validPeriod(query.period),
  };
}

// 状态写回地址：没选的（默认值）不写，保持地址干净；别的参数（比如 from）原样保留。
// 期间等于当前月也不写：看板默认就是本月，写了反而让「刷新后换月」的链接过期。
export function entryQuery(state = {}, base = {}, now = new Date()) {
  const next = { ...base };
  ['tab', 'status', 'dept', 'period'].forEach((key) => { delete next[key]; });
  if (ENTRY_TABS.includes(state.tab)) next.tab = state.tab;
  if (ENTRY_STATUSES.includes(state.status)) next.status = state.status;
  if (state.dept && state.dept !== 'all') next.dept = state.dept;
  const period = validPeriod(state.period);
  if (period && period !== currentPeriodText(now)) next.period = period;
  return next;
}

// 填报进度里的名单：状态 open 是未填 + 未填满；full 是已填满的人（原名单只列需要跟进的，这里单独放出来）。
// 其余状态交给原来的 followUpRows。
export function entryRowsFor(employees = [], { department = 'all', status = 'all' } = {}) {
  if (status === 'open') return followUpRows(employees, { department }).filter((item) => needsRemind(item.status));
  if (status === 'full') return (employees || []).filter((item) => item.status === 'full' && matchesDepartment(item, department));
  return followUpRows(employees, { department, status });
}

// ---------------------------------------------------------------- 发票夹 /approval/invoice-folder
// 财务和普通员工看到的页签不一样：地址里的页签不属于自己这一套时，退到最接近的一个（没有就用默认）。
const FINANCE_TABS = ['dup', 'allinv', 'mine'];
const STAFF_TABS = ['list', 'todo', 'ok', 'used', 'dup'];

export function normalizeFolderTab(tab, finance) {
  const wanted = one(tab);
  const own = finance ? FINANCE_TABS : STAFF_TABS;
  if (own.includes(wanted)) return wanted;
  if (!wanted) return finance ? 'dup' : 'list';
  return finance ? 'allinv' : 'list';
}

// ---------------------------------------------------------------- 物料进度看板 /approval/material-progress
// 合同交期在接口里是同一条物料下各 PO 行的日期用「、」连起来的一个字符串。
export function contractDates(row) {
  return String(row?.contract_delivery_date || '').split(/[、,，;；\s]+/).filter((item) => /^\d{4}-\d{2}-\d{2}$/.test(item)).sort();
}

// 合同交期已过且未收齐（口径同看板的「物料逾期未到」：合同交期早于今天，累计到货少于 PO 数量）。
// 接口若直接给了 contract_overdue（逐 PO 行算好的），以它为准；否则用最早的合同交期和汇总数量近似。
// 已取消的物料不算。
export function isContractOverdue(row, today = todayText()) {
  if (!row || row.record_status === '已取消') return false;
  if (typeof row.contract_overdue === 'boolean') return row.contract_overdue;
  const first = contractDates(row)[0];
  const ordered = Number(row.po_quantity || 0);
  if (!first || !(ordered > 0)) return false;
  return first < today && Number(row.received_quantity || 0) < ordered;
}

export function overdueRows(rows = [], today = todayText()) {
  return (rows || []).filter((row) => isContractOverdue(row, today));
}
