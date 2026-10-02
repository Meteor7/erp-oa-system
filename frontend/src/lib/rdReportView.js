// 研发工时报表（国内 / 境外）指标卡与个人占比用到的纯函数，页面里不再各写一份。
import { projectKey } from './timesheetPivot.js';

function clean(value) {
  return String(value ?? '').trim();
}

function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function round(value, digits) {
  const base = 10 ** digits;
  return Math.round(value * base) / base;
}

// 'YYYY-MM' 的上一个月；格式不对返回空串。
export function previousPeriod(value) {
  const match = /^(\d{4})-(\d{2})$/.exec(clean(value));
  if (!match) return '';
  let year = Number(match[1]);
  let month = Number(match[2]);
  if (month < 1 || month > 12) return '';
  month -= 1;
  if (month < 1) {
    month = 12;
    year -= 1;
  }
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}`;
}

export function sumHours(rows = []) {
  return round((rows || []).reduce((total, row) => total + num(row?.hours), 0), 2);
}

// 工时（小时）折算天数，1 天 = 8 小时。
export function hoursToDays(hours) {
  return round(num(hours) / 8, 2);
}

// 较上月：previous 为空（没取到）返回 null；上月为 0 无法算百分比，返回 direction 'none'。
export function hoursDelta(current, previous) {
  if (previous === null || previous === undefined || previous === '') return null;
  const prev = num(previous);
  const cur = num(current);
  if (prev <= 0) return { pct: null, direction: 'none' };
  const pct = round((cur - prev) / prev * 100, 1);
  const direction = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
  return { pct, direction };
}

export function formatDelta(delta) {
  if (!delta) return '';
  if (delta.direction === 'none') return '上月无工时记录';
  if (delta.direction === 'flat') return '与上月持平';
  const arrow = delta.direction === 'up' ? '↑' : '↓';
  return `${arrow} ${Math.abs(delta.pct).toFixed(1)}% 较上月`;
}

// part 占 total 的百分比；total 不为正返回 0。
export function sharePercent(part, total, digits = 2) {
  const whole = num(total);
  if (whole <= 0) return 0;
  return round(num(part) / whole * 100, digits);
}

// 一行（一个员工 / 主体）各项目工时占该行合计的百分比。
export function employeeShareRow(vals = [], total) {
  const whole = total === undefined ? (vals || []).reduce((sum, value) => sum + num(value), 0) : num(total);
  return (vals || []).map((value) => sharePercent(value, whole, 2));
}

// 项目 id -> 项目名称（用于列头提示）。id 形如「代码 | 名称」时可回退到名称部分。
export function projectNames(rows = []) {
  const names = {};
  for (const row of rows || []) {
    const id = projectKey(row);
    if (!id) continue;
    let name = clean(row.project_name);
    if (!name && id.includes('|')) name = clean(id.split('|').slice(1).join('|'));
    if (name && !names[id]) names[id] = name;
  }
  return names;
}

// 工时合计最高的项目。pivot 是 timesheetPivot 的结果（projects / projTotals / grand）。
export function topProject(pivot, names = {}) {
  const totals = pivot?.projTotals || [];
  const projects = pivot?.projects || [];
  let best = -1;
  totals.forEach((value, index) => {
    if (num(value) > 0 && (best < 0 || num(value) > num(totals[best]))) best = index;
  });
  if (best < 0) return null;
  const project = projects[best] || {};
  return {
    id: project.id,
    label: project.label || project.id,
    name: names[project.id] || '',
    hours: num(totals[best]),
    percent: sharePercent(totals[best], pivot.grand, 1),
  };
}
