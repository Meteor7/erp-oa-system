// 考勤中心首页（人事 / 领导、部门主管）的计算（2026-10-14 按确认的 demo 改版）：谁不在、未来 14 天、N 月概览、近 5 个工作日。
// 数据来自 attendance_board_entry.get_attendance_requests：一张申请一行，服务端已经按身份限好了范围
// （人事经理 / 演示员工113 / 总经理是全公司，部门主管是自己的团队），这里只做展示用的计算，不决定谁能看到谁。
// 口径：人数和合计只算已批准的（出差到前台办理中也算已批准），审批中的列出来、标“审批中”，不算数；
// 不在岗 = 请假 + 调休，出差不算不在岗（同一天有请假又有出差的人算在请假里，和服务端 today_away 一样）。
// 每块一个主数字；名单超过 8 行折叠；页面上要记住的状态（部门、今天 / 本周 / 哪一天、选中的类型、N 月的选择）都放在地址里。

export const HOURS_PER_DAY = 8;
export const LIMIT = 8;          // 名单超过这么多行折叠
export const BAR_LIMIT = 6;      // 条形图最多几条，其余的“其余 N 个”
export const WINDOW_DAYS = 14;
export const KIND_LABELS = Object.freeze({
  annual: '年假', personal: '事假', sick: '病假', comp: '调休', other: '其他假', trip: '出差', ot: '加班',
});
export const ABSENCE_KINDS = Object.freeze(['annual', 'personal', 'sick', 'comp', 'other']);
// 「谁不在」的四格和「N 月」的四个页签（顺序不同：谁不在先看人在不在，N 月先看请假和调休）。
export const TILES = Object.freeze([
  { key: 'leave', label: '请假' }, { key: 'comp', label: '调休' }, { key: 'trip', label: '出差' }, { key: 'ot', label: '加班' },
]);
export const METRICS = Object.freeze([
  { key: 'leave', label: '请假' }, { key: 'comp', label: '调休' }, { key: 'ot', label: '加班' }, { key: 'trip', label: '出差' },
]);
// 「N 月」第二张图（构成）：请假看假别，出差看去哪里，加班 / 调休看哪一周。
export const PART_TITLES = Object.freeze({ leave: '按假别', trip: '去哪里', ot: '按周', comp: '按周' });
// 条形图的颜色（用 .k-* 类）：请假的假别各用各的颜色，其余按类型。
const METRIC_COLORS = Object.freeze({ leave: 'personal', comp: 'comp', ot: 'ot', trip: 'trip' });
const WEEK = '日一二三四五六';
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const ISO_MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

// ---------------------------------------------------------------- 日期（YYYY-MM-DD 字符串，按本地日历算，不受时区影响）
function toDate(iso) {
  const [year, month, day] = String(iso || '').slice(0, 10).split('-').map(Number);
  return new Date(year, (month || 1) - 1, day || 1);
}

function isoOf(date) {
  const pad = (number) => String(number).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(iso, count) {
  const date = toDate(iso);
  date.setDate(date.getDate() + Number(count || 0));
  return isoOf(date);
}

export function weekdayOf(iso) {
  return WEEK[toDate(iso).getDay()];
}

// 这一天所在那周的周一。
export function mondayOf(iso) {
  return addDays(iso, -((toDate(iso).getDay() + 6) % 7));
}

// 本周：周一到周日。
export function weekRange(today) {
  const monday = mondayOf(today);
  return [monday, addDays(monday, 6)];
}

// "2026-10-14" → "10/14"
export function md(iso) {
  const text = String(iso || '');
  return ISO_DAY.test(text.slice(0, 10)) ? `${Number(text.slice(5, 7))}/${Number(text.slice(8, 10))}` : '';
}

// 日期范围：10/14 · 10/14–16 · 10/30–11/2
export function spanText(from, to) {
  if (!to || from === to) return md(from);
  return String(from).slice(0, 7) === String(to).slice(0, 7) ? `${md(from)}–${Number(String(to).slice(8, 10))}` : `${md(from)}–${md(to)}`;
}

export function monthBounds(month) {
  const first = `${month}-01`;
  const next = toDate(first);
  next.setMonth(next.getMonth() + 1);
  next.setDate(0);
  return [first, isoOf(next)];
}

// "2026-10" → "10 月"；不是今年的带上年份。
export function monthTitle(month, today = '') {
  if (!ISO_MONTH.test(String(month || ''))) return '';
  const label = `${Number(month.slice(5))} 月`;
  return today && today.slice(0, 4) !== month.slice(0, 4) ? `${month.slice(0, 4)} 年 ${label}` : label;
}

// ---------------------------------------------------------------- 数字
export function num(value) {
  const number = Number(value || 0);
  return String(Number.isInteger(number) ? number : Math.round(number * 100) / 100);
}

// 小时 → 天，一位小数（四舍五入）。看板卡片上的“本月请假 / 加班”也是这样写的（dashboard/attendance._d1），两边的数一样。
// 有小时但不到 0.05 天时写“<0.1”，不写 0。
export function daysText(hours) {
  const value = Math.round(Number(hours || 0) / HOURS_PER_DAY * 10) / 10;
  if (!value && Number(hours) > 0) return '<0.1';
  return String(value);
}

// ---------------------------------------------------------------- 一张申请
// 四大类：请假（年假 / 事假 / 病假 / 其他假）、调休、出差、加班。
export function groupOf(row) {
  return ['comp', 'trip', 'ot'].includes(row?.kind) ? row.kind : 'leave';
}

// 标签上的字：请假写假别，其余写类型。
export function kindText(row) {
  return groupOf(row) === 'leave' ? row?.leave_type || KIND_LABELS[row?.kind] || '请假' : KIND_LABELS[row?.kind] || '';
}

export function hoursOn(row, day) {
  return (row?.days || []).reduce((sum, [date, hours]) => sum + (date === day ? Number(hours || 0) : 0), 0);
}

export function hoursIn(row, from, to) {
  return (row?.days || []).reduce((sum, [date, hours]) => sum + (date >= from && date <= to ? Number(hours || 0) : 0), 0);
}

export function totalHours(row) {
  return (row?.days || []).reduce((sum, [, hours]) => sum + Number(hours || 0), 0);
}

// 时长：整天写天，不是整天写小时；加班一律写小时；出差写天（全在休息日的出差写“休息日”）。
export function lengthText(row, hours = totalHours(row)) {
  const value = Number(hours || 0);
  if (row?.kind === 'ot') return `${num(value)} 小时`;
  if (row?.kind === 'trip') return value ? `${num(value / HOURS_PER_DAY)} 天` : '休息日';
  return value > 0 && value % HOURS_PER_DAY === 0 ? `${num(value / HOURS_PER_DAY)} 天` : `${num(value)} 小时`;
}

// 状态：审批中（还没批，不算人数）/ 前台办理中（出差已经批准，前台还没办完）/ 已批准的不写。
export function statusOf(row) {
  if (!row?.approved) return { text: '审批中', tone: 'pend' };
  if (row.kind === 'trip' && row.workflow_status === '待办理') return { text: '前台办理中', tone: 'quiet' };
  return null;
}

// 页面顶上的筛选：部门（服务端的部门名）+ 搜姓名。日历和部门概况不受它影响。
export function scopeRows(rows, { dept = '', q = '' } = {}) {
  const query = String(q || '').trim();
  return (rows || []).filter((row) => (!dept || row.department === dept) && (!query || String(row.employee_name || '').includes(query)));
}

const compareRows = (left, right) => String(left.from_date).localeCompare(String(right.from_date))
  || String(left.department_label || '').localeCompare(String(right.department_label || ''), 'zh')
  || String(left.employee_name || '').localeCompare(String(right.employee_name || ''), 'zh')
  || String(left.name).localeCompare(String(right.name));

export function sortRows(rows) {
  return [...(rows || [])].sort(compareRows);
}

// 超过 limit 行折叠：{shown, rest}（rest = 收起来的行数）。
export function fold(list, open = false, limit = LIMIT) {
  const items = list || [];
  return { shown: open ? items : items.slice(0, limit), rest: Math.max(0, items.length - limit) };
}

// ---------------------------------------------------------------- 谁不在
// 每天谁已批准地请假或调休（出差的人当天有请假就不算出差）。
function absentByDay(approved, from, to) {
  const byDay = new Map();
  approved.filter((row) => ['leave', 'comp'].includes(groupOf(row))).forEach((row) => {
    (row.days || []).forEach(([date, hours]) => {
      if (date < from || date > to || !(Number(hours) > 0)) return;
      if (!byDay.has(date)) byDay.set(date, new Set());
      byDay.get(date).add(row.employee);
    });
  });
  return byDay;
}

// period：'day'（day 空 = 今天，或者在图上点的某一天）/ 'week'（本周一到周日）。tile：只看哪一类（空 = 全部）。
// 返回 {from, to, title, picked, restDay, tiles [{key, label, count, on}], rows（已批准的在前，审批中的在后）, pendingFrom, emptyText}。
export function awayView(rows, { today, period = 'day', day = '', tile = '', workDates = [] } = {}) {
  const week = period === 'week';
  const pickedDay = !week && ISO_DAY.test(String(day || '')) ? day : today;
  const [from, to] = week ? weekRange(today) : [pickedDay, pickedDay];
  const hit = (rows || []).filter((row) => hoursIn(row, from, to) > 0);
  const approved = hit.filter((row) => row.approved);
  const people = { leave: new Set(), comp: new Set(), trip: new Set(), ot: new Set() };
  const absent = absentByDay(approved, from, to);
  approved.forEach((row) => {
    const group = groupOf(row);
    if (group !== 'trip') {
      people[group].add(row.employee);
      return;
    }
    if ((row.days || []).some(([date, hours]) => date >= from && date <= to && Number(hours) > 0 && !absent.get(date)?.has(row.employee))) {
      people.trip.add(row.employee);
    }
  });
  const listed = hit.filter((row) => !tile || groupOf(row) === tile);
  const ok = sortRows(listed.filter((row) => row.approved));
  const pending = sortRows(listed.filter((row) => !row.approved));
  const tileLabel = TILES.find((item) => item.key === tile)?.label || '';
  return {
    from, to,
    title: week ? `本周 ${spanText(from, to)}` : `${md(pickedDay)} 周${weekdayOf(pickedDay)}`,
    picked: !week && pickedDay !== today,
    restDay: !week && (workDates || []).length > 0 && !(workDates || []).includes(pickedDay),
    tiles: TILES.map((item) => ({ ...item, count: people[item.key].size, on: tile === item.key })),
    rows: [...ok, ...pending],
    pendingFrom: pending.length ? ok.length : -1,
    emptyText: tile ? `没有${tileLabel}的人` : '没有人请假、调休、出差或加班',
  };
}

// ---------------------------------------------------------------- 未来 14 天
const CHART = Object.freeze({ width: 560, height: 210, left: 26, right: 6, top: 20, bottom: 40 });

// 纵轴的刻度：最高至少到 2；4 以内每格 1，10 以内每格 2，再多每格 5。
export function axisTicks(biggest) {
  let top = Math.max(2, Number(biggest) || 0);
  const step = top <= 4 ? 1 : top <= 10 ? 2 : 5;
  top = Math.ceil(top / step) * step;
  const ticks = [];
  for (let value = 0; value <= top; value += step) ticks.push(value);
  return { top, step, ticks };
}

function isOffDay(iso, workSet) {
  if (workSet.size) return !workSet.has(iso);
  const day = toDate(iso).getDay();
  return day === 0 || day === 6;
}

const round1 = (value) => Math.round(value * 10) / 10;

// mode：'off' 不在岗（按年假 / 事假 / 病假 / 调休 / 其他假堆叠；一个人一天只算一次，算在他最早的那张单的类型里）；
//       'trip' 出差（当天有请假的人不算，和「谁不在」的出差一格同一个口径）。只画已批准的。
// 返回 SVG 要的坐标：{width, height, left, right, top, dayY, weekY, ticks [{value, y}], columns [...], legend [类型]}。
export function chartModel(rows, { today, workDates = [], mode = 'off', selected = '', count = WINDOW_DAYS } = {}) {
  const { width, height, left, right, top, bottom } = CHART;
  const days = Array.from({ length: count }, (_, index) => addDays(today, index));
  const workSet = new Set(workDates || []);
  const approved = sortRows((rows || []).filter((row) => row.approved));
  const perDay = days.map((date) => {
    const kinds = new Map();
    const absent = new Set();
    approved.forEach((row) => {
      if (!(hoursOn(row, date) > 0)) return;
      if (ABSENCE_KINDS.includes(row.kind)) {
        absent.add(row.employee);
        if (mode !== 'trip' && !kinds.has(row.employee)) kinds.set(row.employee, row.kind);
      }
    });
    if (mode === 'trip') {
      approved.forEach((row) => {
        if (row.kind === 'trip' && hoursOn(row, date) > 0 && !absent.has(row.employee)) kinds.set(row.employee, 'trip');
      });
    }
    const byKind = {};
    kinds.forEach((kind) => { byKind[kind] = (byKind[kind] || 0) + 1; });
    return { date, byKind, total: kinds.size };
  });
  const axis = axisTicks(Math.max(0, ...perDay.map((item) => item.total)));
  const plot = height - top - bottom;
  const y = (value) => round1(top + plot - value / axis.top * plot);
  const step = (width - left - right) / count;
  const order = mode === 'trip' ? ['trip'] : ABSENCE_KINDS;
  const used = new Set();
  const columns = perDay.map((item, index) => {
    const x = left + index * step;
    const barWidth = Math.min(22, step - 10);
    let stacked = 0;
    const segments = [];
    order.forEach((kind) => {
      const value = item.byKind[kind] || 0;
      if (!value) return;
      used.add(kind);
      const upper = y(stacked + value);
      const lower = y(stacked);
      segments.push({ kind, count: value, y: round1(upper + 1), height: round1(Math.max(2, lower - upper - 2)) });
      stacked += value;
    });
    const offDay = isOffDay(item.date, workSet);
    return {
      date: item.date, day: Number(item.date.slice(8, 10)), weekday: weekdayOf(item.date), offDay, today: index === 0,
      selected: item.date === selected, total: item.total, segments,
      x: round1(x), width: round1(step), center: round1(x + step / 2), barX: round1(x + (step - barWidth) / 2), barWidth: round1(barWidth),
      valueY: round1(y(item.total) - 6),
      label: `${md(item.date)} 周${weekdayOf(item.date)}${offDay ? '（休息日）' : ''} ${mode === 'trip' ? '出差' : '不在岗'} ${item.total} 人`,
    };
  });
  return {
    width, height, left, right, top, dayY: height - bottom + 17, weekY: height - bottom + 31,
    ticks: axis.ticks.map((value) => ({ value, y: y(value) })), columns, legend: order.filter((kind) => used.has(kind)),
  };
}

// ---------------------------------------------------------------- 近 5 个工作日
// 从今天起的 count 个工作日（服务端给的公司日历）；没有日历时按周一到周五算。
export function nextWorkDays(workDates, today, count = 5) {
  const list = [...(workDates || [])].filter((date) => date >= today).sort();
  if (list.length) return list.slice(0, count);
  const days = [];
  for (let offset = 0; days.length < count && offset < 31; offset += 1) {
    const date = addDays(today, offset);
    if (!isOffDay(date, new Set())) days.push(date);
  }
  return days;
}

// 每人一行，写清楚每张单是哪几天：不在岗（请假、调休）和出差分开两组；加班不列。审批中的也列（标“审批中”）。
export function nearView(rows, days) {
  const wanted = new Set(days || []);
  const people = new Map();
  sortRows(rows).forEach((row) => {
    if (row.kind === 'ot' || !(row.days || []).some(([date, hours]) => wanted.has(date) && Number(hours) > 0)) return;
    if (!people.has(row.employee)) people.set(row.employee, { employee: row.employee, name: row.employee_name, off: [], trip: [] });
    people.get(row.employee)[row.kind === 'trip' ? 'trip' : 'off'].push(row);
  });
  const list = [...people.values()];
  return {
    from: (days || [])[0] || '', to: (days || [])[(days || []).length - 1] || '',
    off: list.filter((person) => person.off.length), trip: list.filter((person) => person.trip.length),
  };
}

// ---------------------------------------------------------------- N 月概览
// 这个月要算的申请：已批准、这一类、有小时落在这个月里（全在休息日的出差按出发日期算在出发的那个月）。
export function monthRows(rows, metric, month) {
  return (rows || []).filter((row) => row.approved && groupOf(row) === metric
    && (Number(row.month_hours) > 0 || (row.kind === 'trip' && String(row.from_date).slice(0, 7) === month)));
}

// 四个页签上的合计（小时）：就是服务端 month_hours 加起来，和看板的“本月请假 / 加班 / 另有调休”同一个数。
export function monthTotals(rows, month) {
  return Object.fromEntries(METRICS.map((item) => [item.key, monthRows(rows, item.key, month).reduce((sum, row) => sum + Number(row.month_hours || 0), 0)]));
}

// 这一周（周一）在这个月里的那几天：10/1–5、10/27–31。
export function weekLabelOf(week, month) {
  const [first, last] = monthBounds(month);
  const from = week < first ? first : week;
  const end = addDays(week, 6);
  return spanText(from, end > last ? last : end);
}

function weeksOf(row, month) {
  const byWeek = new Map();
  (row.days || []).forEach(([date, hours]) => {
    if (String(date).slice(0, 7) !== month || !(Number(hours) > 0)) return;
    const week = mondayOf(date);
    byWeek.set(week, (byWeek.get(week) || 0) + Number(hours));
  });
  return [...byWeek.entries()];
}

// 构成：请假按假别（颜色类别），出差按去哪里，加班 / 调休按哪一周。[[键, 小时]]。
export function partsOf(row, metric, month) {
  if (metric === 'leave') return [[row.kind, Number(row.month_hours || 0)]];
  if (metric === 'trip') return [[row.travel_destination || '未填', Number(row.month_hours || 0)]];
  return weeksOf(row, month);
}

export function partLabel(key, metric, month) {
  if (metric === 'leave') return KIND_LABELS[key] || key;
  if (metric === 'ot' || metric === 'comp') return weekLabelOf(key, month);
  return key;
}

function barItems(groups, color) {
  const items = [...groups.values()];
  const biggest = Math.max(0, ...items.map((item) => item.hours));
  return items.map((item) => ({ ...item, days: daysText(item.hours), pct: biggest > 0 ? Math.round(item.hours / biggest * 1000) / 10 : 0, color: item.color || color }));
}

// metric：leave / comp / ot / trip；company：全公司（有“按部门”）还是部门 / 团队（有“按周”）；
// sel：{dept, part, week} 在图上点选的（互相筛：选了部门，构成图只算这个部门；选了假别，部门图只算这个假别），明细跟着所有选择。
// 返回 {tabs, charts [{key, field, title, items, selected}], list, listHours, listDays, chips [{field, label}]}。
export function overviewView(rows, { metric = 'leave', month, company = true, sel = {} } = {}) {
  const weekly = metric === 'ot' || metric === 'comp';
  const pick = {
    dept: company ? String(sel.dept || '') : '',
    part: String(sel.part || ''),
    week: !company && !weekly ? String(sel.week || '') : '',
  };
  const base = monthRows(rows, metric, month);
  const inWeek = (row) => weeksOf(row, month).some(([week]) => week === pick.week);
  const pass = (row, skip = '') => (skip === 'dept' || !pick.dept || row.department === pick.dept)
    && (skip === 'part' || !pick.part || partsOf(row, metric, month).some(([key]) => key === pick.part))
    && (skip === 'week' || !pick.week || inWeek(row));
  const color = METRIC_COLORS[metric];
  const charts = [];
  if (company) {
    const groups = new Map();
    base.filter((row) => pass(row, 'dept')).forEach((row) => {
      const entry = groups.get(row.department) || { key: row.department, label: row.department_label || '未分配部门', hours: 0 };
      entry.hours += Number(row.month_hours || 0);
      groups.set(row.department, entry);
    });
    const items = barItems(groups, color).sort((left, right) => right.hours - left.hours || left.label.localeCompare(right.label, 'zh'));
    charts.push({ key: 'dept', field: 'dept', title: '按部门', items, selected: pick.dept });
  }
  const parts = new Map();
  base.filter((row) => pass(row, 'part')).forEach((row) => {
    partsOf(row, metric, month).forEach(([key, hours]) => {
      const entry = parts.get(key) || { key, label: partLabel(key, metric, month), hours: 0, color: metric === 'leave' ? key : '' };
      entry.hours += hours;
      parts.set(key, entry);
    });
  });
  const partItems = barItems(parts, color).sort(weekly ? (left, right) => left.key.localeCompare(right.key) : (left, right) => right.hours - left.hours || left.label.localeCompare(right.label, 'zh'));
  charts.push({ key: 'part', field: 'part', title: PART_TITLES[metric], items: partItems, selected: pick.part });
  if (!company && !weekly) {
    const weeks = new Map();
    base.filter((row) => pass(row, 'week')).forEach((row) => {
      weeksOf(row, month).forEach(([week, hours]) => {
        const entry = weeks.get(week) || { key: week, label: weekLabelOf(week, month), hours: 0 };
        entry.hours += hours;
        weeks.set(week, entry);
      });
    });
    charts.push({ key: 'week', field: 'week', title: '按周', items: barItems(weeks, color).sort((left, right) => left.key.localeCompare(right.key)), selected: pick.week });
  }
  const list = sortRows(base.filter((row) => pass(row)));
  const listHours = list.reduce((sum, row) => sum + Number(row.month_hours || 0), 0);
  const chips = [];
  if (pick.dept) chips.push({ field: 'dept', label: base.find((row) => row.department === pick.dept)?.department_label || pick.dept });
  if (pick.part) chips.push({ field: 'part', label: partLabel(pick.part, metric, month) });
  if (pick.week) chips.push({ field: 'week', label: weekLabelOf(pick.week, month) });
  const totals = monthTotals(rows, month);
  return {
    tabs: METRICS.map((item) => ({ ...item, hours: totals[item.key], days: daysText(totals[item.key]), on: item.key === metric })),
    charts, list, listHours, listDays: daysText(listHours), chips,
  };
}

// ---------------------------------------------------------------- 地址里的首页状态
// dept 部门（只有人事 / 领导，等于点进部门）；q 搜姓名；period=week 本周（不写 = 今天）；day 在图上点的那天；tile 谁不在选中的类型；
// chart=trip 未来 14 天看出差；metric N 月的页签（不写 = 请假）；month N 月是哪个月（不写 = 本月）；odept / opart / oweek N 月图上点选的；
// section=away | month 打开时滚到哪一块（看板点进来用）。
export const HOME_KEYS = Object.freeze(['dept', 'q', 'period', 'day', 'tile', 'chart', 'metric', 'month', 'odept', 'opart', 'oweek', 'section']);
const TILE_KEYS = TILES.map((item) => item.key);
const METRIC_KEYS = METRICS.map((item) => item.key);

function one(value) {
  return Array.isArray(value) ? String(value[0] ?? '') : String(value ?? '');
}

export function homeStateOf(query = {}) {
  const get = (key) => one((query || {})[key]).trim();
  const period = get('period') === 'week' ? 'week' : 'day';
  return {
    dept: get('dept'),
    q: get('q').slice(0, 40),
    period,
    day: period === 'day' && ISO_DAY.test(get('day')) ? get('day') : '',
    tile: TILE_KEYS.includes(get('tile')) ? get('tile') : '',
    chart: get('chart') === 'trip' ? 'trip' : 'off',
    metric: METRIC_KEYS.includes(get('metric')) ? get('metric') : 'leave',
    month: ISO_MONTH.test(get('month')) ? get('month') : '',
    odept: get('odept'),
    opart: get('opart'),
    oweek: ISO_DAY.test(get('oweek')) ? get('oweek') : '',
    section: ['away', 'month'].includes(get('section')) ? get('section') : '',
  };
}

// 状态 → 查询参数：默认值不写，地址短一点。
export function homeQuery(state = {}) {
  const clean = homeStateOf(state || {});
  const query = {};
  for (const key of HOME_KEYS) {
    const value = clean[key];
    if (!value || (key === 'period' && value === 'day') || (key === 'chart' && value === 'off') || (key === 'metric' && value === 'leave')) continue;
    query[key] = value;
  }
  return query;
}

// 从首页点进详情 / 新建时，首页的状态带在 f 开头的参数里（fdept、fperiod……），返回时原样恢复。
export function homeOriginQuery(state = {}) {
  return Object.fromEntries(Object.entries(homeQuery(state)).map(([key, value]) => [`f${key}`, value]));
}

export function hasHomeOrigin(query = {}) {
  return HOME_KEYS.some((key) => one((query || {})[`f${key}`]) !== '');
}

export function homeOriginState(query = {}) {
  return homeStateOf(Object.fromEntries(HOME_KEYS.map((key) => [key, (query || {})[`f${key}`]])));
}
