// 请假 / 加班 / 调休页面的前端逻辑：申请表的每日时长、本次申请的汇总和影响、记录分组、月历、审批进度。
// 服务端仍是权威校验（额度、日期冲突、每天上限），这里只做即时提示。
import { callApi } from './expenseClaims.js';

export const HOURS_PER_DAY = 8;
export const MAX_OVERTIME_HOURS = 24;

export const TYPES = Object.freeze({
  请假申请: Object.freeze({ key: 'leave', label: '请假', path: '/approval/leave', title: '新建请假申请', submit: '提交请假申请' }),
  加班申请: Object.freeze({ key: 'overtime', label: '加班', path: '/approval/overtime', title: '新建加班申请', submit: '提交加班申请' }),
  调休申请: Object.freeze({ key: 'comp', label: '调休', path: '/approval/comp-time', title: '新建调休申请', submit: '提交调休申请' }),
});
export const TYPE_ORDER = Object.freeze(['请假申请', '加班申请', '调休申请']);

export function typeForPath(path) {
  const text = String(path || '');
  if (text.startsWith('/approval/overtime')) return '加班申请';
  if (text.startsWith('/approval/comp-time')) return '调休申请';
  return '请假申请';
}

export const LEAVE_RULES = Object.freeze({
  事假: '审批通过后，从当月工时上限里扣：全天 8 小时，半天 4 小时；跨月的分别扣。',
  年假: '从年假余额里扣，审批中就先占用，被驳回或撤回后退回。',
  病假: '不扣年假，也不扣当月工时上限。',
});
export const LEAVE_RULE_DEFAULT = '不扣年假，也不扣当月工时上限。';

// 审批步骤的名字里常带着人名（"直属主管：陈立"）；页面上人名单独显示，这里只留岗位。
export function stepRole(label) {
  return String(label || '').split('：')[0];
}

// ERPNext 部门名带公司后缀（"客服部 - RAY"），页面上只显示前面的部门名。
export function departmentLabel(text) {
  return String(text || '').replace(/\s+-\s+[A-Za-z0-9]{1,8}$/, '');
}

// 一张申请真正有时长的第一天和最后一天（中间有被去掉的天时，起止日期以有时长的天为准）。
export function workedSpan(days, from = '', to = '') {
  const worked = (days || []).filter((day) => Number(day.hours) > 0).map((day) => day.work_date).sort();
  return worked.length ? { from: worked[0], to: worked[worked.length - 1] } : { from, to };
}

export function numText(value) {
  const number = Number(value || 0);
  return String(Number.isInteger(number) ? number : Math.round(number * 100) / 100);
}

// ---------------------------------------------------------------- 每天的时长

export function modeOfHours(hours) {
  const value = Number(hours || 0);
  if (value === HOURS_PER_DAY) return 'full';
  if (value === HOURS_PER_DAY / 2) return 'half';
  if (value === 0) return 'none';
  return 'custom';
}

export function hoursOfMode(mode, maxHours = HOURS_PER_DAY) {
  const wanted = { full: HOURS_PER_DAY, half: HOURS_PER_DAY / 2, none: 0 }[mode] ?? 0;
  return Math.min(wanted, Number(maxHours ?? HOURS_PER_DAY));
}

const WEEK = ['日', '一', '二', '三', '四', '五', '六'];

export function parseDate(text) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(text || ''));
  if (!match) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

export function isoDate(date) {
  const pad = (number) => String(number).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function dayLabel(text) {
  const date = parseDate(text);
  return date ? `${date.getMonth() + 1}月${date.getDate()}日` : String(text || '');
}

export function weekLabel(text) {
  const date = parseDate(text);
  return date ? `周${WEEK[date.getDay()]}` : '';
}

export function rangeText(from, to) {
  const start = parseDate(from);
  const end = parseDate(to);
  if (!start) return '';
  if (!end || isoDate(start) === isoDate(end)) return dayLabel(from);
  return start.getMonth() === end.getMonth()
    ? `${start.getMonth() + 1}月${start.getDate()}日–${end.getDate()}日`
    : `${dayLabel(from)}–${dayLabel(to)}`;
}

// 服务端返回的可填日子 [{work_date, hours, max_hours, conflict}] 合并用户已经填过的时长：
// 日期还在的保留用户填的（不超过当天上限），新出现的日子用服务端的默认值。
export function mergeDays(serverDays, previous = []) {
  const kept = new Map((previous || []).map((day) => [day.work_date, day]));
  return (serverDays || []).map((day) => {
    const max = Number(day.max_hours ?? HOURS_PER_DAY);
    const before = kept.get(day.work_date);
    const hours = before ? Math.min(Number(before.hours || 0), max) : Math.min(Number(day.hours ?? HOURS_PER_DAY), max);
    return { work_date: day.work_date, hours, max_hours: max, conflict: day.conflict || null };
  });
}

// 起止日期之间每一天的显示行：能填的日子（工作日，加班是每一天）、休息日。最多 366 天。
export function dayRows(from, to, days, overtime = false) {
  const start = parseDate(from);
  const end = parseDate(to);
  if (!start || !end || end < start) return [];
  const byDate = new Map((days || []).map((day) => [day.work_date, day]));
  const rows = [];
  const cursor = new Date(start);
  for (let count = 0; cursor <= end && count < 366; count += 1) {
    const date = isoDate(cursor);
    const day = byDate.get(date);
    rows.push({
      date, label: dayLabel(date), week: weekLabel(date),
      kind: day ? (day.conflict ? 'conflict' : (overtime ? 'ot' : 'work')) : 'rest',
      day: day || null,
    });
    cursor.setDate(cursor.getDate() + 1);
  }
  return rows;
}

export function totalHours(days) {
  return Math.round((days || []).reduce((sum, day) => sum + Number(day.hours || 0), 0) * 100) / 100;
}

export function stepHours(hours, delta, max = MAX_OVERTIME_HOURS) {
  return Math.min(Math.max(0, Math.round((Number(hours || 0) + delta) * 100) / 100), Number(max));
}

// ---------------------------------------------------------------- 本次申请的汇总

function hoursByMonth(days) {
  const months = new Map();
  (days || []).forEach((day) => {
    const date = parseDate(day.work_date);
    if (date) months.set(date.getMonth() + 1, (months.get(date.getMonth() + 1) || 0) + Number(day.hours || 0));
  });
  return [...months.entries()].sort((left, right) => left[0] - right[0]);
}

export function subjectFor(requestType, leaveType, hours, reason = '') {
  const label = requestType === '请假申请' ? (leaveType || '请假') : TYPES[requestType]?.label || '';
  const size = requestType === '加班申请' ? `${numText(hours)} 小时` : `${numText(hours / HOURS_PER_DAY)} 天`;
  const why = String(reason || '').trim().replace(/\s+/g, ' ').slice(0, 12);
  return why ? `${label} ${size} · ${why}` : `${label} ${size}`;
}

// 提交给服务端的字段。只带有时长的天：起止日期取这些天的第一天和最后一天，
// 时长为 0 的天（不请、已被占用的天）不进明细，否则服务端会认为它们超出了申请日期。
export function buildFields({ requestType, leaveType, from, to, days, subject, reason }) {
  const worked = (days || []).filter((day) => Number(day.hours) > 0).map((day) => ({ work_date: day.work_date, hours: Number(day.hours) }));
  const span = workedSpan(worked, from, to);
  return {
    subject: String(subject || '').trim() || subjectFor(requestType, leaveType, totalHours(worked), reason),
    from_date: span.from,
    to_date: span.to,
    attendance_days: JSON.stringify(worked),
    leave_type: requestType === '请假申请' ? leaveType : '',
    reason: String(reason || '').trim(),
  };
}

// 汇总：大数字、明细、对额度和月度上限的影响，以及不能提交的原因。
export function formSummary({ requestType, leaveType, days, rows = [], annual = null, comp = null }) {
  const hours = totalHours(days);
  const restDays = rows.filter((row) => row.kind === 'rest').length;
  const takenDays = rows.filter((row) => row.kind === 'conflict').length;
  const overtime = requestType === '加班申请';
  const result = {
    hours,
    big: overtime ? numText(hours) : numText(hours / HOURS_PER_DAY),
    unit: overtime ? '小时加班' : `天 · ${numText(hours)} 小时`,
    detail: '', impact: '', tone: 'ok', blocked: '',
  };
  const notes = [];
  if (restDays) notes.push(`已去掉 ${restDays} 个休息日`);
  if (takenDays) notes.push(`${takenDays} 天已有申请`);
  result.detail = [overtime ? '加班' : (requestType === '请假申请' ? leaveType : '调休'), ...notes].filter(Boolean).join(' · ');
  if (overtime) {
    const available = Number(comp?.available_hours || 0);
    result.impact = `提交后调休额度 ${numText(available)} → ${numText(available + hours)} 小时（1:1）`;
  } else if (requestType === '调休申请') {
    const left = Number(comp?.available_hours || 0) - hours;
    result.impact = left >= 0 ? `调休余额 ${numText(comp?.available_hours || 0)} → ${numText(left)} 小时` : `调休不够：还差 ${numText(-left)} 小时`;
    result.tone = left >= 0 ? 'ok' : 'warn';
    if (left < 0) result.blocked = '调休余额不足';
  } else if (leaveType === '年假') {
    const left = Number(annual?.available_hours || 0) - hours;
    result.impact = left >= 0 ? `年假余额 ${numText(annual?.available_hours || 0)} → ${numText(left)} 小时` : `年假不够：还差 ${numText(-left)} 小时`;
    result.tone = left >= 0 ? 'ok' : 'warn';
    if (annual && annual.eligible === false) {
      result.blocked = annual.eligibility_message || '暂不能申请年假';
      result.tone = 'warn';
    } else if (left < 0) {
      result.blocked = '年假余额不足';
    }
  } else if (leaveType === '事假') {
    result.impact = hoursByMonth(days).map(([month, value]) => `通过后，${month} 月工时上限少 ${numText(value)} 小时`).join('；') || '通过后扣当月工时上限';
    result.tone = 'info';
  } else {
    result.impact = LEAVE_RULE_DEFAULT.replace('。', '');
  }
  if (!result.blocked && hours <= 0) result.blocked = '请至少填一天的时长';
  return result;
}

// ---------------------------------------------------------------- 记录

export function rejectionOf(row) {
  const log = Array.isArray(row?.operation_log) ? row.operation_log : [];
  const event = [...log].reverse().find((item) => ['Targeted rejection', '定向驳回'].includes(item?.action));
  if (!event) return null;
  return { actor: event?.details?.actor || event?.actor || event?.user || '', note: event.note || '', time: event.timestamp || event.acted_on || '' };
}

export function typeBadge(row) {
  if (row?.request_type === '加班申请') return { text: '加班', tone: 'ot' };
  if (row?.request_type === '调休申请') return { text: '调休', tone: 'comp' };
  return { text: row?.leave_type || '请假', tone: 'leave' };
}

const PILLS = {
  草稿: ['草稿', 'p-gray'], 待审批: ['审批中', 'p-cobalt'], 待办理: ['审批中', 'p-cobalt'], 待流转: ['审批中', 'p-cobalt'],
  已完成: ['已通过', 'p-jade'], 已通过: ['已通过', 'p-jade'], 已拒绝: ['已驳回', 'p-red'], 已撤回: ['已撤回', 'p-gray'],
};

export function statusPill(row) {
  if (row?.workflow_status === '草稿' && rejectionOf(row)) return { text: '被退回', tone: 'p-brand' };
  const [text, tone] = PILLS[row?.workflow_status] || [row?.workflow_status || '', 'p-gray'];
  return { text, tone };
}

export function hoursText(row) {
  const hours = Number(row?.duration_hours || 0);
  return hours > 0 ? `${numText(hours)} 小时` : '';
}

export function waitedDays(row, now = Date.now()) {
  const since = Date.parse(String(row?.modified || '').replace(' ', 'T'));
  if (!Number.isFinite(since)) return 0;
  return Math.max(0, Math.floor((now - since) / 86400000));
}

// 我的申请按"要你处理 / 草稿 / 审批中 / 已完成 / 已驳回"分组，空组不显示。
export function groupMine(rows) {
  const groups = [
    { key: 'todo', title: '要你处理', items: [] },
    { key: 'draft', title: '草稿', items: [] },
    { key: 'pending', title: '审批中', items: [] },
    { key: 'done', title: '已完成', items: [] },
    { key: 'closed', title: '已驳回或撤回', items: [] },
  ];
  const by = Object.fromEntries(groups.map((group) => [group.key, group]));
  (rows || []).forEach((row) => {
    if (row.kanban_status === 'draft') (rejectionOf(row) ? by.todo : by.draft).items.push(row);
    else if (row.kanban_status === 'approved') by.done.items.push(row);
    else if (row.kanban_status === 'pending') by.pending.items.push(row);
    else by.closed.items.push(row);
  });
  return groups.filter((group) => group.items.length);
}

export function returnedDrafts(rows) {
  return (rows || []).filter((row) => row.kanban_status === 'draft' && rejectionOf(row));
}

// ---------------------------------------------------------------- 月历

export function periodOf(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

export function shiftPeriod(period, delta) {
  const [year, month] = String(period).split('-').map(Number);
  const moved = new Date(year, month - 1 + delta, 1);
  return periodOf(moved);
}

export function periodTitle(period) {
  const [year, month] = String(period).split('-').map(Number);
  return `${year} 年 ${month} 月`;
}

// 月历格子：前面补空格（周一开头），每天带上申请记录、是不是休息日、今天、本次选择的日子。
export function calendarCells({ period, firstWeekday, daysInMonth, workDates = [], entries = [], selected = [], today = isoDate(new Date()) }) {
  const work = new Set(workDates);
  const chosen = new Set(selected);
  const byDate = new Map();
  entries.forEach((entry) => byDate.set(entry.date, [...(byDate.get(entry.date) || []), entry]));
  const cells = [];
  for (let blank = 0; blank < Number(firstWeekday || 0); blank += 1) cells.push({ blank: true, key: `b${blank}` });
  for (let day = 1; day <= Number(daysInMonth || 0); day += 1) {
    const date = `${period}-${String(day).padStart(2, '0')}`;
    const items = byDate.get(date) || [];
    const first = items[0] || null;
    cells.push({
      blank: false, key: date, date, day, off: !work.has(date), today: date === today, chosen: chosen.has(date),
      kind: first ? first.kind : '', pending: items.length ? items.every((item) => item.pending) : false,
      tag: first ? (items.length > 1 ? `${items.length} 项` : first.label) : (date === today ? '今天' : ''),
    });
  }
  while (cells.length % 7) cells.push({ blank: true, key: `t${cells.length}` });
  return cells;
}

// ---------------------------------------------------------------- 审批进度

// [{label, who, state: done | current | wait | stop, note, time}]
export function stepStates(request, names = {}) {
  const steps = Array.isArray(request?.steps) ? request.steps : [];
  const active = ['待审批', '待办理'].includes(request?.workflow_status);
  return steps.map((step) => {
    const status = String(step.status || '');
    let state = 'wait';
    if (status.includes('通过') || (status.includes('办理') && !status.includes('待'))) state = 'done';
    else if (status.includes('拒绝') || status.includes('撤回')) state = 'stop';
    else if (active && Number(step.step_index) === Number(request.current_step_index)) state = 'current';
    const who = (step.approvers || []).map((user) => names[String(user).toLowerCase()] || String(user).split('@')[0]).join(' / ');
    return { label: step.label, who, state, note: step.note || '', time: step.acted_on || '' };
  });
}

// ---------------------------------------------------------------- 审批人

export function reviewCount(items) {
  return (items || []).length;
}

// 团队图：每天不在的人数（已通过 + 审批中），以及柱子里每一格的样式。
export function teamBars(team) {
  return (team?.days || []).map((day) => ({
    ...day,
    total: day.approved.length + day.pending.length,
    crowded: !day.off_day && day.approved.length + day.pending.length >= 2,
    label: day.off_day ? '休' : (day.approved.length + day.pending.length ? `${day.approved.length + day.pending.length} 人` : ''),
  }));
}

// ---------------------------------------------------------------- 异步请求只认最新一次

// 日期连续改动、定时刷新会同时发出多个请求；只有最近一次发出的请求结果可以用，旧的丢掉。
export function createLatest() {
  let version = 0;
  return {
    begin() {
      version += 1;
      return version;
    },
    isCurrent(token) {
      return token === version;
    },
  };
}

export const api = {
  home: (params) => callApi('attendance_entry.get_attendance_home', params, { method: 'GET' }),
  route: (requestType) => callApi('attendance_entry.get_attendance_route', { request_type: requestType }, { method: 'GET' }),
  mine: (requestType) => callApi('attendance_entry.list_attendance_mine', { request_type: requestType, limit: 50 }, { method: 'GET' }),
  review: () => callApi('attendance_entry.list_attendance_review', {}, { method: 'GET' }),
  reviewed: () => callApi('attendance_entry.list_attendance_reviewed', {}, { method: 'GET' }),
  detail: (name) => callApi('attendance_entry.get_attendance_request', { name }, { method: 'GET' }),
  options: (requestType, from, to) => callApi('oa_entry.get_attendance_options', { request_type: requestType, from_date: from || '', to_date: to || '' }, { method: 'GET' }),
  create: (params) => callApi('oa_entry.create_request', params),
  updateDraft: (params) => callApi('oa_entry.update_leave_draft', params),
  submitDraft: (name) => callApi('oa_entry.submit_request', { name }),
  act: (params) => callApi('oa_entry.action_request', params),
  withdraw: (name) => callApi('oa_entry.withdraw_request', { name }),
};
