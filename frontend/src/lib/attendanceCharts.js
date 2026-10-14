// 考勤中心首页图表和日历的计算（不依赖界面，便于单元测试）。
// 数据来自 attendance_board_entry：员工拿到自己的 personal，部门主管拿到自己团队的 detail（日历），人事和管理层拿到各部门汇总 summary
// （部门概况表），选了某个部门再拿到那个部门的 detail。这里只做展示用的计算，谁能看到什么由服务端决定。
// 2026-10-14：部门主管、人事和管理层首页的「谁不在」「未来 14 天」「N 月」「近 5 个工作日」在 attendanceHome.js 里算。

export const HOURS_PER_DAY = 8;
export const KINDS = Object.freeze({
  annual: '年假', personal: '事假', sick: '病假', comp: '调休', other: '其他假', trip: '出差', ot: '加班',
});
// 请假和调休（算不在岗）；出差、加班不算。
export const ABSENCE_KINDS = Object.freeze(['annual', 'personal', 'sick', 'comp', 'other']);
// 头像的底色在这六种柔色里挑（和请假类型同一套），同一个名字永远是同一种。
const AVATAR_KINDS = ['annual', 'personal', 'sick', 'comp', 'ot', 'trip'];

export const kindLabel = (kind) => KINDS[kind] || '';

// 一张申请的颜色类别（待办列表里的头像和标签）：年假 / 事假 / 病假，调休，加班，出差，其余的假归在其他假。
export function rowKind(row) {
  if (row?.request_type === '调休申请') return 'comp';
  if (row?.request_type === '加班申请') return 'ot';
  if (row?.request_type === '出差申请') return 'trip';
  return { 年假: 'annual', 事假: 'personal', 病假: 'sick' }[row?.leave_type] || 'other';
}

export function avatarKind(name) {
  const text = String(name || '');
  if (!text) return AVATAR_KINDS[0];
  return AVATAR_KINDS[(text.charCodeAt(0) + text.charCodeAt(text.length - 1)) % AVATAR_KINDS.length];
}

// 出勤率：请假和调休的小时占应出勤小时（人数 × 8 × 工作日数）的比例；没有应出勤小时算 1。
export function attendanceRate(absentHours, headcount, workDays) {
  const capacity = HOURS_PER_DAY * Number(headcount || 0) * Number(workDays || 0);
  if (!(capacity > 0)) return 1;
  return Math.min(1, Math.max(0, 1 - Number(absentHours || 0) / capacity));
}

// 0.9156 → "91.6"
export function ratePercent(rate) {
  return (Math.round(Number(rate || 0) * 1000) / 10).toFixed(1);
}

export const rateTone = (rate) => (Number(rate) < 0.93 ? 'warn' : 'ok');

// 本月请假小时按类型：{annual: 16, ...} → [{kind, label, hours}]，只留有小时的，顺序固定。
export function hoursByKind(byKind) {
  return ABSENCE_KINDS.map((kind) => ({ kind, label: KINDS[kind], hours: Number(byKind?.[kind] || 0) })).filter((item) => item.hours > 0);
}

export function totalHours(items) {
  return (items || []).reduce((sum, item) => sum + Number(item.hours || 0), 0);
}

// 14 天每天不在岗（请假 + 调休）的人数。
export function offPerDay(days) {
  return (days || []).map((day) => Number(day.off || 0));
}

// 环形图：每段的 stroke-dasharray / dashoffset（半径 radius，从 12 点方向顺时针）。
export function donutArcs(items, radius = 33) {
  const circumference = 2 * Math.PI * radius;
  const total = totalHours(items) || 1;
  let offset = 0;
  return (items || []).filter((item) => Number(item.hours) > 0).map((item) => {
    const length = Number(item.hours) / total * circumference;
    const arc = { kind: item.kind, hours: Number(item.hours), dash: length.toFixed(2), gap: (circumference - length).toFixed(2), offset: (-offset).toFixed(2) };
    offset += length;
    return arc;
  });
}

// 趋势小线：点坐标 "x,y x,y …"。
export function sparklinePoints(values, width = 84, height = 24) {
  const list = values || [];
  if (list.length < 2) return '';
  const biggest = Math.max(1, ...list);
  return list.map((value, index) => `${(index / (list.length - 1) * width).toFixed(1)},${(height - 3 - Number(value) / biggest * (height - 7)).toFixed(1)}`).join(' ');
}

// 近 6 个月请假柱状图。
export function monthBars(months, maxPx = 74) {
  const biggest = Math.max(8, ...(months || []).map((item) => Number(item.hours || 0)));
  return (months || []).map((item) => {
    const hours = Number(item.hours || 0);
    return { ...item, hours, height: Math.round(Math.max(hours / biggest * maxPx, hours ? 4 : 2) * 10) / 10 };
  });
}

// 员工的额度条：年假、调休是进度条（已用 + 审批中占用 / 总额），事假只有文字（它不是额度，通过后扣当月研发工时上限）。
export function quotaRows(home) {
  const rows = [];
  const bar = (balance) => {
    const credit = Number(balance.credit_hours || 0);
    const used = Number(balance.used_hours || 0);
    const reserved = Number(balance.reserved_hours || 0);
    const pct = (hours) => (credit > 0 ? Math.min(100, Math.max(0, hours / credit * 100)) : 0);
    return [{ pct: pct(used), faded: false }, { pct: pct(Math.min(reserved, Math.max(0, credit - used))), faded: true }];
  };
  const annual = home?.annual;
  if (annual) rows.push({ key: 'annual', kind: 'annual', label: `年假（共 ${num(annual.credit_hours)} 小时）`, right: `剩 ${num(annual.available_hours)} 小时`, bar: bar(annual) });
  const comp = home?.comp;
  if (comp) rows.push({ key: 'comp', kind: 'comp', label: `调休（累计加班 ${num(comp.credit_hours)} 小时）`, right: `剩 ${num(comp.available_hours)} 小时`, bar: bar(comp) });
  const month = home?.month;
  if (month) {
    const personal = Number(month.leave_days_by_type?.事假 || 0) * HOURS_PER_DAY;
    rows.push({
      key: 'personal', kind: 'personal', label: '事假（本月）', right: `已请 ${num(personal)} 小时`, bar: null,
      note: Number(month.pending_cap_hours) ? `其中审批中 ${num(month.pending_cap_hours)} 小时；通过后扣当月研发工时上限` : '通过后扣当月研发工时上限',
    });
  }
  return rows;
}

function num(value) {
  const number = Number(value || 0);
  return String(Number.isInteger(number) ? number : Math.round(number * 100) / 100);
}

// 今日出勤条：在岗 / 请假 / 出差，按人数的比例（总人数为 0 时都是 0）。
export function todayParts(today, headcount) {
  const total = Number(headcount) || 0;
  const share = (count) => (total > 0 ? Math.round(Number(count || 0) / total * 1000) / 10 : 0);
  return [
    { key: 'in', label: '在岗', count: Number(today?.in || 0), pct: share(today?.in), color: 'in' },
    { key: 'off', label: '请假', count: Number(today?.off || 0), pct: share(today?.off), color: 'personal' },
    { key: 'trip', label: '出差', count: Number(today?.trip || 0), pct: share(today?.trip), color: 'trip' },
  ];
}

// 日历格子的类名：休息日浅底色；有记录按类型上色，审批中的画成虚线。
export function cellClass(cell, day) {
  if (!cell) return day?.off_day ? 'we' : '';
  return `${cell.kind}${cell.pending ? ' pend' : ''}`;
}

export function cellTitle(name, day, cell) {
  const when = `${day?.label || ''}${day?.weekday ? ` 周${day.weekday}` : ''}`;
  if (!cell) return `${name} ${when}`;
  const hours = cell.kind === 'ot' ? ` ${num(cell.hours)} 小时` : cell.hours && cell.hours < HOURS_PER_DAY ? ` ${num(cell.hours)} 小时` : '';
  return `${name} ${when} ${KINDS[cell.kind]}${hours}${cell.pending ? '（审批中）' : ''}`;
}

// 员工"我未来 14 天"条：每天一格，有安排的按类型上色。
export function stripTitle(day) {
  if (!day.kind) return `${day.label} 周${day.weekday}`;
  return `${day.label} 周${day.weekday} ${KINDS[day.kind]}${day.hours && day.hours < HOURS_PER_DAY ? ` ${num(day.hours)} 小时` : ''}${day.pending ? '（审批中）' : ''}`;
}

// 图表面板是否展开：记在浏览器里（读写失败就用默认值：展开）。
export const CHARTS_KEY = 'rayher.attendance.charts';

export function readChartsOpen(storage = globalThis.localStorage) {
  try {
    return storage?.getItem(CHARTS_KEY) !== 'closed';
  } catch {
    return true;
  }
}

export function writeChartsOpen(open, storage = globalThis.localStorage) {
  try {
    storage?.setItem(CHARTS_KEY, open ? 'open' : 'closed');
  } catch {
    // 浏览器不让写（隐私模式等）：这次不记，不影响使用。
  }
}
