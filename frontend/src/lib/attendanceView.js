// 请假 / 加班 / 调休页面（考勤中心）的前端逻辑：一个页面四个视图（首页 / 列表 / 详情 / 新建），
// 页面类型来自路径（/approval/leave | overtime | comp-time），其余全部来自查询参数。
// 这里只放不依赖界面的计算：查询参数解析、跳转目标、筛选和计数、每天的时段与小时、汇总和影响、审批进度。
// 服务端仍是权威校验（额度、日期冲突、每天上限），这里只做即时提示。
import { callApi } from './expenseClaims.js';

export const HOURS_PER_DAY = 8;
// 公司规定：请假和调休每天 8 小时，上午 3 小时，下午 5 小时，也可以自定义小时（每次 0.5，0.5–8）；加班按小时。
export const MORNING_HOURS = 3;
export const AFTERNOON_HOURS = 5;
export const HOURS_STEP = 0.5;
export const MAX_CUSTOM_HOURS = 8;
export const MAX_OVERTIME_HOURS = 24;
export const DAY_RULE_TEXT = '全天 8 小时，上午 3 小时，下午 5 小时，也可以自定义小时（每次 0.5）';
export const DAY_RULE_MESSAGE = '请假和调休按天填：全天 8 小时、上午 3 小时、下午 5 小时，也可以自定义小时（每次 0.5）。';

export const TYPES = Object.freeze({
  请假申请: Object.freeze({ key: 'leave', label: '请假', path: '/approval/leave', title: '新建请假申请', submit: '提交请假申请', rule: '事假 / 病假 / 年假等；事假通过后从当月研发工时上限里扣' }),
  加班申请: Object.freeze({ key: 'overtime', label: '加班', path: '/approval/overtime', title: '新建加班申请', submit: '提交加班申请', rule: '按小时填；提交后按 1:1 增加调休额度，驳回或撤回后冲回' }),
  调休申请: Object.freeze({ key: 'comp', label: '调休', path: '/approval/comp-time', title: '新建调休申请', submit: '提交调休申请', rule: '用加班攒下的额度抵扣；提交时先占用，通过后正式扣减' }),
});
export const TYPE_ORDER = Object.freeze(['请假申请', '加班申请', '调休申请']);
export const TYPE_LABELS = Object.freeze(['请假', '加班', '调休']);
export const FILTER_ALL = 'all';
// 「考勤中心」首页和「全部类型」的列表放在这个路径上；路由里没有它时（router.js 还没加）退回请假的路径，靠 ?view=home 区分。
export const ATTENDANCE_HOME_PATH = '/approval/attendance';
export const FALLBACK_HOME_PATH = '/approval/leave';

export function requestTypeOf(label) {
  return TYPE_ORDER.find((type) => TYPES[type].label === label) || '';
}

export function labelOfType(requestType) {
  return TYPES[requestType]?.label || '';
}

export function typeForPath(path) {
  const text = String(path || '');
  if (text.startsWith('/approval/overtime')) return '加班申请';
  if (text.startsWith('/approval/comp-time')) return '调休申请';
  if (text.startsWith(ATTENDANCE_HOME_PATH)) return '';
  return '请假申请';
}

export const LEAVE_RULES = Object.freeze({
  事假: `审批通过后，从当月工时上限里扣：${DAY_RULE_TEXT}；跨月的分别扣。`,
  年假: '从年假余额里扣，审批中就先占用，被驳回或撤回后退回。',
  病假: '不扣年假，也不扣当月工时上限。',
});
export const LEAVE_RULE_DEFAULT = '不扣年假，也不扣当月工时上限。';
export const COMP_RULE = '提交时先占用额度，审批通过后正式扣减；不减少月度工时上限。';
export const OVERTIME_RULE = '提交申请就按 1:1 增加调休额度，不增加月度工时上限；每天最多 24 小时。';

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

export function stamp(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '';
}

// ---------------------------------------------------------------- 查询参数 → 视图

export const SCOPES = Object.freeze([
  { key: 'todo', label: '待我审批' },
  { key: 'mine', label: '我的' },
  { key: 'done', label: '我审批过的' },
  { key: 'all', label: '全部' },
]);
const SCOPE_KEYS = SCOPES.map((item) => item.key);

function filterOf(value, fallback = FILTER_ALL) {
  const text = String(value || '');
  return TYPE_LABELS.includes(text) || text === FILTER_ALL ? text : fallback;
}

function one(value) {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '');
}

// 页面是从哪来的：列表（带范围和类型筛选）或首页；详情和新建页的"返回"、面包屑靠它回到原处。
export function originOf(query = {}) {
  const from = one(query.from);
  if (from === 'list') {
    const scope = one(query.fscope);
    return { kind: 'list', scope: SCOPE_KEYS.includes(scope) ? scope : 'mine', filter: filterOf(one(query.ftype)) };
  }
  if (from === 'home') return { kind: 'home', scope: '', filter: FILTER_ALL };
  return { kind: '', scope: '', filter: FILTER_ALL };
}

export function originQuery(origin) {
  if (origin?.kind === 'list') return { from: 'list', fscope: origin.scope || 'mine', ftype: origin.filter || FILTER_ALL };
  if (origin?.kind === 'home') return { from: 'home' };
  return {};
}

// 路由 {path, params, query} → 页面状态。旧链接照常有效：/approval/<类型>/<单号>、?request=<单号>、?draft=<单号>。
export function parseLocation({ path = '', params = {}, query = {} } = {}) {
  const pathType = typeForPath(path);
  const pathLabel = labelOfType(pathType);
  const request = one(params.name) || one(query.request);
  const draft = one(query.draft);
  const queryView = one(query.view);
  let view = 'list';
  if (request) view = 'detail';
  else if (queryView === 'new' || draft) view = 'new';
  else if (queryView === 'list') view = 'list';
  else if (queryView === 'home' || !pathType) view = 'home';
  const scope = one(query.scope);
  const typeQuery = one(query.type);
  return {
    view,
    request,
    draft,
    scope: SCOPE_KEYS.includes(scope) ? scope : '',
    // 看板的「今天不在岗」：?today=1，只在「全部」范围里生效（别的范围没有这个筛选）。
    today: one(query.today) === '1' && scope === 'all',
    // 列表和首页的类型筛选：?type= 优先，没有就跟路径（侧栏进来的 /approval/overtime 就是加班）。
    filter: filterOf(typeQuery, pathLabel || FILTER_ALL),
    // 新建页要新建的类型；没有（也不是在继续某张草稿）就让用户先选。
    newType: TYPE_LABELS.includes(typeQuery) ? typeQuery : (draft ? pathLabel : ''),
    reject: one(query.reject) === '1',
    origin: originOf(query),
    pathType,
  };
}

export function pathForFilter(filter, homePath = FALLBACK_HOME_PATH) {
  const type = requestTypeOf(filter);
  return type ? TYPES[type].path : homePath;
}

function clean(query) {
  return Object.fromEntries(Object.entries(query).filter(([, value]) => value !== undefined && value !== null && value !== ''));
}

export function homeLocation(homePath = FALLBACK_HOME_PATH) {
  return { path: homePath, query: { view: 'home' } };
}

// today：只看今天在休假 / 调休的人（看板的「今天不在岗」），只有「全部」范围有这个筛选，别的范围不带。
export function listLocation({ scope = 'mine', filter = FILTER_ALL, today = false } = {}, homePath = FALLBACK_HOME_PATH) {
  return { path: pathForFilter(filter, homePath), query: clean({ view: 'list', scope, type: filter, today: today && scope === 'all' ? '1' : '' }) };
}

// 详情：path 是这张申请所属类型的路径（侧栏跟着走）；不知道类型时不给，由页面用当前路径。
export function detailLocation({ name, type = '' }, origin = null, { reject = false } = {}) {
  return {
    path: TYPE_LABELS.includes(type) ? TYPES[requestTypeOf(type)].path : undefined,
    query: clean({ request: name, reject: reject ? '1' : '', ...originQuery(origin) }),
  };
}

// 新建：type 为空时先显示"你要新建哪一种"；带 draft 时是继续填写那张草稿（类型用草稿自己的）。
export function newLocation({ type = '', draft = '' } = {}, origin = null) {
  return {
    path: TYPE_LABELS.includes(type) ? TYPES[requestTypeOf(type)].path : undefined,
    query: clean({ view: 'new', type: TYPE_LABELS.includes(type) ? type : '', draft, ...originQuery(origin) }),
  };
}

// 取消 / 返回：回到从哪来的；没有来源时回到该类型"我的"列表。
export function backLocation(origin, { filter = FILTER_ALL, homePath = FALLBACK_HOME_PATH } = {}) {
  if (origin?.kind === 'home') return homeLocation(homePath);
  if (origin?.kind === 'list') return listLocation({ scope: origin.scope || 'mine', filter: origin.filter || FILTER_ALL }, homePath);
  return listLocation({ scope: 'mine', filter }, homePath);
}

export function backLabel(origin) {
  return origin?.kind === 'home' ? '返回首页' : '返回列表';
}

export function listTitle(filter) {
  return TYPE_LABELS.includes(filter) ? `${filter}申请` : '申请列表';
}

export function newButtonLabel(filter) {
  return TYPE_LABELS.includes(filter) ? `＋ 新建${filter}` : '＋ 新建申请';
}

export function newTitle(type) {
  return TYPE_LABELS.includes(type) ? `新建${type}申请` : '新建申请';
}

// 侧栏跟着"正在处理的类型"走：列表看类型筛选，新建看正在新建的类型，详情看这张申请的类型，首页不属于任何类型。
export function contextFilter(page) {
  if (page.view === 'home') return FILTER_ALL;
  if (page.view === 'list') return page.filter;
  if (page.view === 'new') return page.newType || FILTER_ALL;
  return '';
}

// ---------------------------------------------------------------- 列表数据：类型、筛选、计数

export function rowLabel(row) {
  return labelOfType(row?.request_type);
}

export function filterRows(rows, filter) {
  return TYPE_LABELS.includes(filter) ? (rows || []).filter((row) => rowLabel(row) === filter) : [...(rows || [])];
}

// 今天在休假 / 调休的人：已批准的请假、调休单，起止日期包含今天（口径同总览的「今天不在岗」）。
// 加班不算不在岗。日期是 YYYY-MM-DD 字符串，直接按字典序比较。
const AWAY_TYPES = ['请假申请', '调休申请'];
const AWAY_DONE = ['已完成', '已通过'];

export function awayToday(rows, today) {
  return (rows || []).filter((row) => AWAY_TYPES.includes(row?.request_type) && AWAY_DONE.includes(row?.workflow_status)
    && String(row.from_date || '').slice(0, 10) <= today && today <= String(row.to_date || row.from_date || '').slice(0, 10));
}

export function typeCounts(rows) {
  const counts = { all: (rows || []).length };
  TYPE_LABELS.forEach((label) => { counts[label] = (rows || []).filter((row) => rowLabel(row) === label).length; });
  return counts;
}

// 类型筛选 chips；首页的 chip 带数量（"请假 2"），列表页不带。
export function typeChips(counts, active, withCounts = false) {
  return [[FILTER_ALL, '全部'], ...TYPE_LABELS.map((label) => [label, label])].map(([key, label]) => ({
    key, on: active === key, label: withCounts ? `${label} ${counts?.[key] ?? 0}` : label,
  }));
}

export function defaultScope(todoCount) {
  return Number(todoCount) > 0 ? 'todo' : 'mine';
}

export function validScope(scope, { canViewAll = false } = {}) {
  if (!SCOPE_KEYS.includes(scope)) return '';
  return scope === 'all' && !canViewAll ? 'mine' : scope;
}

// 范围标签页：待我审批和我审批过的只有审批人才有，全部只有人事 / 老板才有；数量按当前的类型筛选算。
export function scopeTabs({ sets, filter, isApprover, canViewAll, allLoaded }) {
  const count = (key) => filterRows(sets[key], filter).length;
  return SCOPES.filter((item) => (item.key === 'todo' || item.key === 'done' ? isApprover : item.key === 'all' ? canViewAll : true))
    .map((item) => ({ ...item, count: item.key === 'all' && !allLoaded ? null : count(item.key) }));
}

// 一张申请能不能在列表和首页上直接"同意"：只给普通审批步骤。
export function canQuickApprove(row) {
  return Boolean(row) && row.can_approve !== false && row.current_step_mode !== 'handle' && ['待审批', '待办理'].includes(row.workflow_status);
}

// ---------------------------------------------------------------- 等待时间和提交时间

function toTime(value) {
  const time = Date.parse(String(value || '').replace(' ', 'T'));
  return Number.isFinite(time) ? time : null;
}

// 轮到当前节点的时间：上一个人处理的时间，没有就是提交时间。
export function waitingSince(row) {
  const stamps = (row?.steps || []).map((step) => step.acted_on).filter(Boolean).map((item) => String(item).replace(' ', 'T')).sort();
  return toTime(stamps[stamps.length - 1]) ?? toTime(row?.submitted_on) ?? toTime(row?.creation) ?? toTime(row?.modified);
}

export function waitMinutes(row, now = Date.now()) {
  const since = waitingSince(row);
  return since === null ? null : Math.max(0, Math.floor((now - since) / 60000));
}

export function waitText(row, now = Date.now()) {
  const minutes = waitMinutes(row, now);
  if (minutes === null) return '';
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时`;
  return `${Math.floor(minutes / 1440)} 天`;
}

// 等得最久的排前面。
export function byWait(rows, now = Date.now()) {
  return [...(rows || [])].sort((left, right) => (waitMinutes(right, now) ?? -1) - (waitMinutes(left, now) ?? -1));
}

export function submittedText(row) {
  if (row?.workflow_status === '草稿') return '未提交';
  const text = stamp(row?.submitted_on || row?.creation);
  return text ? text.slice(5) : '';
}

// ---------------------------------------------------------------- 每天的时段与小时

// 一天的填法：全天 8 / 上午 3 / 下午 5 / 不请 0；其他都是自定义小时（旧的 4 小时半天现在也是自定义小时）。
export function modeOfHours(hours) {
  const value = Number(hours || 0);
  if (value === HOURS_PER_DAY) return 'full';
  if (value === MORNING_HOURS) return 'am';
  if (value === AFTERNOON_HOURS) return 'pm';
  if (value === 0) return 'none';
  return 'custom';
}

const MODE_HOURS = { full: HOURS_PER_DAY, am: MORNING_HOURS, pm: AFTERNOON_HOURS, none: 0 };

// 这一档放不进这天剩下的小时数时是 0（不请），不再退而求其次变成别的时长。
export function hoursOfMode(mode, maxHours = HOURS_PER_DAY) {
  const wanted = MODE_HOURS[mode] ?? 0;
  return wanted <= Number(maxHours ?? HOURS_PER_DAY) ? wanted : 0;
}

// 这天自定义小时能填的上限：不超过 8，也不超过这天还剩的小时。
export function customCap(day) {
  return Math.min(MAX_CUSTOM_HOURS, Number(day?.max_hours ?? HOURS_PER_DAY));
}

// 表单上这一档的按钮能不能点：全天要整天都空；上午、下午要那一半没被占且剩下的小时放得下；自定义至少还剩 0.5 小时。
export function modeAvailable(day, mode) {
  const max = Number(day?.max_hours ?? HOURS_PER_DAY);
  if (mode === 'none') return true;
  if (mode === 'full') return max >= HOURS_PER_DAY;
  if (mode === 'am') return !day?.am_taken && max >= MORNING_HOURS;
  if (mode === 'pm') return !day?.pm_taken && max >= AFTERNOON_HOURS;
  if (mode === 'custom') return max >= HOURS_STEP;
  return false;
}

export function stepHours(hours, delta, max = MAX_OVERTIME_HOURS, min = 0) {
  return Math.min(Math.max(Number(min), Math.round((Number(hours || 0) + delta) * 100) / 100), Number(max));
}

// 切到"自定义小时"时的起始小时数：上次填过的自定义小时（不超过上限），没有就 1 小时。
export function customStart(day) {
  const cap = customCap(day);
  return Math.min(cap, Math.max(HOURS_STEP, Number(day?.custom) || 1));
}

// 选一档以后这天的 {mode, hours}；这一档现在选不了时原样返回。
export function pickMode(day, mode) {
  if (!modeAvailable(day, mode)) return { mode: day.mode, hours: Number(day.hours || 0) };
  if (mode === 'custom') return { mode, hours: customStart(day) };
  return { mode, hours: hoursOfMode(mode, day.max_hours) };
}

// 自定义小时恰好是 3 / 5 时，服务端按上午 / 下午算（会占用那一半）；表单要说清楚，并在那一半已被占时不让提交。
export function slotNote(day) {
  if (day?.mode !== 'custom') return '';
  const hours = Number(day.hours || 0);
  if (hours === MORNING_HOURS) return '正好 3 小时按「上午」算，会占用这天的上午';
  if (hours === AFTERNOON_HOURS) return '正好 5 小时按「下午」算，会占用这天的下午';
  if (hours === HOURS_PER_DAY) return '8 小时就是全天';
  return '';
}

export function slotClash(day) {
  const hours = Number(day?.hours || 0);
  if (hours === MORNING_HOURS && day.am_taken) return '上午';
  if (hours === AFTERNOON_HOURS && day.pm_taken) return '下午';
  return '';
}

// 这天选项旁边的提示：哪一半被占了、还能自定义多少小时。
export function dayNote(day) {
  const cap = customCap(day);
  if (Number(day?.max_hours ?? HOURS_PER_DAY) >= HOURS_PER_DAY) return '';
  if (cap < HOURS_STEP) return '这天已经请满了';
  if (day.am_taken && day.pm_taken) return `这天上午和下午都已被占用，只能自定义不超过 ${numText(cap)} 小时`;
  if (day.am_taken) return `这天上午已被占用，只能请下午，或自定义不超过 ${numText(cap)} 小时`;
  if (day.pm_taken) return `这天下午已被占用，只能请上午，或自定义不超过 ${numText(cap)} 小时`;
  return `这天已有申请，还能请 ${numText(cap)} 小时`;
}

// 请假和调休每天只能是 0.5 的倍数、0.5–8 小时。
export function validLeaveHours(hours) {
  const value = Number(hours);
  return Number.isFinite(value) && value >= HOURS_STEP && value <= HOURS_PER_DAY && Math.round(value * 100) % 50 === 0;
}

export function invalidLeaveDays(days) {
  return (days || []).filter((day) => Number(day.hours) > 0 && !validLeaveHours(day.hours));
}

// 每天明细里一天的文字：上午 · 3 小时 / 下午 · 5 小时 / 全天 · 8 小时 / 自定义 · 2.5 小时。
export function dayModeText(hours) {
  const mode = modeOfHours(hours);
  const text = { full: '全天', am: '上午', pm: '下午', custom: '自定义' }[mode];
  return text ? `${text} · ${numText(hours)} 小时` : `${numText(hours)} 小时`;
}

// 请假和调休一张申请的总时长：整天数时"2 天 · 16 小时"，否则直接说小时（3 小时 / 11 小时），不拆成小数天。
export function durationText(hours) {
  const total = Number(hours || 0);
  return total % HOURS_PER_DAY === 0 && total > 0 ? `${numText(total / HOURS_PER_DAY)} 天 · ${numText(total)} 小时` : `${numText(total)} 小时`;
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

export function shortDate(text) {
  return String(text || '').slice(5, 10);
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

// 一张申请的逐日明细（只留有时长的天，按日期排）；只有起止日期的旧申请按期间内的周一到周五 8 小时算。
export function rowDays(row) {
  const days = Array.isArray(row?.attendance_days) ? row.attendance_days : [];
  const worked = days.filter((day) => Number(day.hours) > 0).sort((left, right) => String(left.work_date).localeCompare(String(right.work_date)));
  if (worked.length || days.length) return worked;
  const start = parseDate(row?.from_date);
  const end = parseDate(row?.to_date);
  if (!start || !end || end < start) return [];
  const legacy = [];
  const cursor = new Date(start);
  for (let count = 0; cursor <= end && count < 366; count += 1) {
    if (cursor.getDay() > 0 && cursor.getDay() < 6) legacy.push({ work_date: isoDate(cursor), hours: HOURS_PER_DAY });
    cursor.setDate(cursor.getDate() + 1);
  }
  return legacy;
}

export function totalOf(row) {
  const hours = Number(row?.duration_hours || 0);
  return hours > 0 ? hours : rowDays(row).reduce((sum, day) => sum + Number(day.hours || 0), 0);
}

// 列表和卡片上的日期时段小标签：全天 / 上午 / 下午 / 自定义 N 小时（加班只说小时）。
export function dayChip(day, overtime = false) {
  const hours = Number(day?.hours || 0);
  const mode = overtime ? 'custom' : modeOfHours(hours);
  const label = overtime ? `${numText(hours)} 小时` : { full: '全天', am: '上午', pm: '下午' }[mode] || `自定义 ${numText(hours)} 小时`;
  return { date: day?.work_date, mode, hours, label, text: `${shortDate(day?.work_date)} ${weekLabel(day?.work_date)} · ${label}` };
}

// 一张申请的日期时段标签；limit > 0 时最多给这么多个，其余算在 more 里。
export function rowChips(row, limit = 0) {
  const overtime = row?.request_type === '加班申请';
  const chips = rowDays(row).map((day) => dayChip(day, overtime));
  if (!chips.length) {
    const text = rangeText(row?.from_date, row?.to_date);
    return { chips: text ? [{ date: row?.from_date, mode: 'custom', hours: totalOf(row), label: text, text }] : [], more: 0 };
  }
  return limit > 0 && chips.length > limit ? { chips: chips.slice(0, limit), more: chips.length - limit } : { chips, more: 0 };
}

// ---------------------------------------------------------------- 一行申请的显示

export function personShort(name) {
  const text = String(name || '').trim();
  return text.length > 2 ? text.slice(-2) : text;
}

export function kindOf(row) {
  const label = rowLabel(row) || '请假';
  const leaveType = label === '请假' ? row?.leave_type || '' : '';
  return { label, tone: { 请假: 'leave', 加班: 'ot', 调休: 'comp' }[label], text: leaveType ? `${label} · ${leaveType}` : label, leaveType };
}

// "请假 · 事假 · 10月30日" / "加班 · 10月18日"：我的申请卡片上的标题。
export function requestTitle(row) {
  const kind = kindOf(row);
  const days = rowDays(row);
  const span = days.length ? workedSpan(days, row?.from_date, row?.to_date) : { from: row?.from_date, to: row?.to_date };
  return [kind.text, rangeText(span.from, span.to)].filter(Boolean).join(' · ');
}

const STATUS_TONES = { 草稿: ['草稿', ''], 待审批: ['审批中', 'info'], 待办理: ['审批中', 'info'], 待流转: ['审批中', 'info'], 已完成: ['已通过', 'ok'], 已通过: ['已通过', 'ok'], 已拒绝: ['已驳回', 'bad'], 已撤回: ['已撤回', ''] };

// 状态标签：{text, tone}，tone 是 ok / info / warn / bad / ''（灰）；轮到我审批的显示"待审批"。
export function statusTag(row) {
  if (row?.workflow_status === '草稿' && rejectionOf(row)) return { text: '被退回', tone: 'warn' };
  if (['待审批', '待办理'].includes(row?.workflow_status) && row?.can_act) return { text: '待审批', tone: 'warn' };
  const [text, tone] = STATUS_TONES[row?.workflow_status] || [row?.workflow_status || '', ''];
  return { text, tone };
}

function people(users, names = {}) {
  return (users || []).map((user) => names[String(user).toLowerCase()] || String(user).split('@')[0]).join(' / ');
}

// 状态下面那行：轮到你 · 人事经理 / 等待 陈立（直属主管）/ 我已同意。
export function nodeText(row, names = {}) {
  // 我审批过的：说我做了什么；这张申请还在往下走的话补一句。
  if (row?.my_status) {
    return `我已${/拒绝|驳回/.test(row.my_status) ? '驳回' : '同意'}${['待审批', '待办理'].includes(row.workflow_status) ? ' · 流转中' : ''}`;
  }
  if (['待审批', '待办理'].includes(row?.workflow_status)) {
    const step = (row.steps || []).find((item) => Number(item.step_index) === Number(row.current_step_index));
    const role = stepRole(row.current_step_label || step?.label);
    if (row.can_act) return `轮到你 · ${role || '审批'}`;
    const who = people(step?.approvers, names);
    return who ? `等待 ${who}（${role || '审批'}）` : `等待 ${role || '审批人'}`;
  }
  return '';
}

// ---------------------------------------------------------------- 通过后的影响

// 后端给的影响文字里的"16h → 8h"取出来："16 → 8 小时"。
export function shiftText(impact) {
  const match = /(-?[\d.]+)h\s*→\s*(-?[\d.]+)h/.exec(String(impact || ''));
  return match ? `${match[1]} → ${match[2]} 小时` : String(impact || '');
}

// "24h" → "24 小时"（后端的影响文字用 h，页面上写小时）。
export function hoursInText(text) {
  return String(text || '').replace(/(\d)h/g, '$1 小时');
}

// 首页和列表上一行字："通过后：…"。impact 是后端 list_attendance_review 给的那句话。
export function effectLine(row) {
  const hours = numText(totalOf(row));
  const impact = hoursInText(row?.impact);
  const label = rowLabel(row);
  if (label === '加班') return `通过后：调休额度 +${hours} 小时`;
  if (label === '调休') return impact ? `通过后：${impact}` : `通过后：扣调休额度 ${hours} 小时`;
  if (row?.leave_type === '年假') return impact ? `通过后：${impact}` : `通过后：扣年假 ${hours} 小时`;
  if (row?.leave_type === '事假') return `通过后：事假 ${hours} 小时${impact ? `，${impact}` : ''}`;
  return `通过后：${row?.leave_type || '请假'} ${hours} 小时，不扣年假和工时上限`;
}

// 按月拆开的小时：[[月, 小时]]。
export function hoursByMonth(days) {
  const months = new Map();
  (days || []).forEach((day) => {
    const date = parseDate(day.work_date);
    if (date) months.set(date.getMonth() + 1, (months.get(date.getMonth() + 1) || 0) + Number(day.hours || 0));
  });
  return [...months.entries()].sort((left, right) => left[0] - right[0]);
}

// 详情页"通过后的影响"：[{kind: balance | cap, label, value, note}]。事假另有每月工时上限一行；
// 该员工当月已填工时、新上限是多少后端没有给，页面不猜，只说"超过新上限时需要他先调整"。
export function effectRows(request, impact = '') {
  const hours = totalOf(request);
  const label = rowLabel(request);
  if (label === '加班') {
    return [{ kind: 'balance', label: '调休额度', value: `+${numText(hours)} 小时`, note: '加班提交后按 1:1 增加调休额度；驳回或撤回后冲回' }];
  }
  if (label === '调休') {
    return [{ kind: 'balance', label: '调休额度', value: shiftText(impact) || `−${numText(hours)} 小时`, note: '调休提交时先占用额度，审批通过后正式扣减' }];
  }
  if (request?.leave_type === '年假') {
    return [{ kind: 'balance', label: '年假额度', value: shiftText(impact) || `−${numText(hours)} 小时`, note: '审批中就先占用，被驳回或撤回后退回' }];
  }
  if (request?.leave_type === '事假') {
    return [
      { kind: 'balance', label: '事假（不扣年假额度）', value: `${numText(hours)} 小时`, note: '事假通过后才扣当月工时上限' },
      ...hoursByMonth(rowDays(request)).map(([month, value]) => ({
        kind: 'cap', label: `${month} 月研发工时上限`, value: `−${numText(value)} 小时`,
        note: '通过后从该员工当月研发工时上限里扣；已填工时超过新上限时，需要他先调整',
      })),
    ];
  }
  return [{ kind: 'balance', label: `${request?.leave_type || '请假'}（不扣年假额度）`, value: `${numText(hours)} 小时`, note: '不扣年假，也不扣当月工时上限' }];
}

// ---------------------------------------------------------------- 申请表：每天的数据

// 服务端返回的可填日子 [{work_date, hours, max_hours, am_taken, pm_taken, conflict}] 合并用户已经填过的：
// 日期还在、选的那一档（全天 / 上午 / 下午 / 自定义 / 不请）现在还能选的，保留用户填的；
// 选的那一档被占了（比如改日期后这天上午已有申请）就换成服务端给的默认值；自定义小时保留，但不超过这天的上限。
// zeroNew：继续填草稿时，草稿里没有的日子是用户当时选了"不请"，不要再套默认值。
export function mergeDays(serverDays, previous = [], overtime = false, { zeroNew = false } = {}) {
  const kept = new Map((previous || []).map((day) => [day.work_date, day]));
  return (serverDays || []).map((day) => {
    const max = Number(day.max_hours ?? HOURS_PER_DAY);
    const merged = {
      work_date: day.work_date, hours: 0, mode: 'none', custom: 0, max_hours: max,
      am_taken: Boolean(day.am_taken), pm_taken: Boolean(day.pm_taken), conflict: day.conflict || null,
    };
    const before = kept.get(day.work_date);
    const fallback = Math.min(Number(day.hours ?? HOURS_PER_DAY), max);
    const beforeMode = before ? (before.mode || modeOfHours(before.hours)) : '';
    if (!before) {
      merged.hours = zeroNew && kept.size ? 0 : fallback;
    } else if (overtime) {
      merged.hours = Math.min(Number(before.hours || 0), max);
    } else if (beforeMode === 'custom') {
      merged.hours = max >= HOURS_STEP ? Math.min(Number(before.hours || 0), customCap(merged)) : 0;
    } else {
      merged.hours = modeAvailable(merged, beforeMode) ? Number(before.hours || 0) : fallback;
    }
    // 自定义小时即使正好是 3 / 5 / 8 也保持"自定义"这一档（用户选的就是自定义）；其余按小时数判断。
    if (overtime) merged.mode = merged.hours > 0 ? 'custom' : 'none';
    else if (beforeMode === 'custom' && merged.hours > 0) merged.mode = 'custom';
    else merged.mode = modeOfHours(merged.hours);
    merged.custom = Number(before?.custom || 0) || (merged.mode === 'custom' ? merged.hours : 0);
    return merged;
  });
}

// 起止日期之间每一天的显示行：能填的日子（工作日，加班是每一天）、休息日、已被占满的日子。最多 366 天。
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

// "全天 2 · 上午 1 · 自定义 1"：本次申请按时段拆开。
export function breakdownText(days, overtime = false) {
  if (overtime) return (days || []).some((day) => Number(day.hours) > 0) ? '加班' : '';
  const count = (mode) => (days || []).filter((day) => Number(day.hours) > 0 && modeOfHours(day.hours) === mode).length;
  return [['full', '全天'], ['am', '上午'], ['pm', '下午'], ['custom', '自定义']]
    .map(([mode, label]) => (count(mode) ? `${label} ${count(mode)}` : '')).filter(Boolean).join(' · ');
}

export function subjectFor(requestType, leaveType, hours, reason = '') {
  const label = requestType === '请假申请' ? (leaveType || '请假') : TYPES[requestType]?.label || '';
  // 加班按小时；请假和调休满整天时说"N 天"，否则直接说小时（"请假 3 小时"），不出现 0.38 天。
  const size = requestType !== '加班申请' && Number(hours) % HOURS_PER_DAY === 0
    ? `${numText(hours / HOURS_PER_DAY)} 天` : `${numText(hours)} 小时`;
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

// 汇总：大数字（小时）、按时段拆开、对额度和月度上限的影响（lines），以及不能提交的原因。
export function formSummary({ requestType, leaveType, days, rows = [], annual = null, comp = null }) {
  const hours = totalHours(days);
  const restDays = rows.filter((row) => row.kind === 'rest').length;
  const takenDays = rows.filter((row) => row.kind === 'conflict').length;
  const overtime = requestType === '加班申请';
  const result = {
    hours, big: numText(hours), unit: '小时', breakdown: breakdownText(days, overtime),
    detail: '', impact: '', lines: [], note: '', tone: 'ok', blocked: '',
  };
  const notes = [];
  if (restDays) notes.push(`已去掉 ${restDays} 个休息日`);
  if (takenDays) notes.push(`${takenDays} 天已有申请`);
  result.detail = [overtime ? '加班' : (requestType === '请假申请' ? leaveType : '调休'), ...notes].filter(Boolean).join(' · ');
  if (overtime) {
    const available = Number(comp?.available_hours || 0);
    result.impact = `提交后调休额度 ${numText(available)} → ${numText(available + hours)} 小时（1:1）`;
    result.lines = [{ label: '调休额度', value: `${numText(available)} → ${numText(available + hours)} 小时` }];
    result.note = '加班提交后按 1:1 增加调休额度，驳回或撤回后冲回';
  } else if (requestType === '调休申请') {
    const left = Number(comp?.available_hours || 0) - hours;
    result.impact = left >= 0 ? `调休余额 ${numText(comp?.available_hours || 0)} → ${numText(left)} 小时` : `调休不够：还差 ${numText(-left)} 小时`;
    result.lines = [{ label: '调休额度', value: `${numText(comp?.available_hours || 0)} → ${numText(left)} 小时` }];
    result.note = left >= 0 ? '调休提交时先占用额度，审批通过后正式扣减' : `调休额度不足（只剩 ${numText(comp?.available_hours || 0)} 小时）`;
    result.tone = left >= 0 ? 'ok' : 'warn';
    if (left < 0) result.blocked = '调休余额不足';
  } else if (leaveType === '年假') {
    const left = Number(annual?.available_hours || 0) - hours;
    result.impact = left >= 0 ? `年假余额 ${numText(annual?.available_hours || 0)} → ${numText(left)} 小时` : `年假不够：还差 ${numText(-left)} 小时`;
    result.lines = [{ label: '年假额度', value: `${numText(annual?.available_hours || 0)} → ${numText(left)} 小时` }];
    result.note = left >= 0 ? '审批中就先占用，被驳回或撤回后退回' : `年假额度不足（只剩 ${numText(annual?.available_hours || 0)} 小时）`;
    result.tone = left >= 0 ? 'ok' : 'warn';
    if (annual && annual.eligible === false) {
      result.blocked = annual.eligibility_message || '暂不能申请年假';
      result.tone = 'warn';
    } else if (left < 0) {
      result.blocked = '年假余额不足';
    }
  } else if (leaveType === '事假') {
    const months = hoursByMonth(days);
    result.impact = months.map(([month, value]) => `通过后，${month} 月工时上限少 ${numText(value)} 小时`).join('；') || '通过后扣当月工时上限';
    result.lines = months.map(([month, value]) => ({ label: `${month} 月研发工时上限`, value: `−${numText(value)} 小时` }));
    result.note = '事假通过后，从当月研发工时上限里扣（跨月的分别扣）';
    result.tone = 'info';
  } else {
    result.impact = LEAVE_RULE_DEFAULT.replace('。', '');
    result.lines = [{ label: `${leaveType || '请假'}（不扣年假额度）`, value: `${numText(hours)} 小时` }];
    result.note = LEAVE_RULE_DEFAULT;
  }
  if (!result.blocked && !overtime && invalidLeaveDays(days).length) result.blocked = DAY_RULE_MESSAGE;
  if (!result.blocked && !overtime) {
    const clash = (days || []).find((day) => slotClash(day));
    if (clash) result.blocked = `${dayLabel(clash.work_date)}${slotClash(clash)}已被占用，请换一个时段或改小时数`;
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

export function returnedDrafts(rows) {
  return (rows || []).filter((row) => row.kanban_status === 'draft' && rejectionOf(row));
}

// 我的申请：进行中 = 审批中 + 草稿。
export function mineSummary(rows) {
  const active = (rows || []).filter((row) => ['draft', 'pending'].includes(row.kanban_status));
  return { total: (rows || []).length, active: active.length, activeRows: active };
}

// 我的申请卡片上的步骤条：[{cls: done | cur | '', mark, text}]。
export function stepTracker(row, names = {}) {
  return stepStates(row, names).map((step) => ({
    cls: step.state === 'done' ? 'done' : step.state === 'current' ? 'cur' : step.state === 'stop' ? 'stop' : '',
    mark: step.state === 'done' ? '✓' : step.state === 'stop' ? '✕' : '·',
    text: `${step.who ? `${step.who}（${stepRole(step.label)}）` : stepRole(step.label)}${step.state === 'current' ? ' · 当前' : ''}`,
  }));
}

// ---------------------------------------------------------------- 取数的月份

export function periodOf(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
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
    const who = people(step.approvers, names);
    return { label: step.label, who, state, note: step.note || '', time: step.acted_on || '' };
  });
}

// ---------------------------------------------------------------- 部门这两周谁不在

// 后端 team 数据（每天已通过 / 审批中的人名）→ 两周网格：只列出这两周有人不在的人，每人每天一格；
// 最后一行是每天不在的人数，工作日里 2 人以上不在标 crowded。只给名字和日期，不给类型和事由。
// 返回 {days: [{date, label, title, off}], rows: [{name, pending, cells: [{state: '' | approved | pending, title}]}], totals: [{n, crowded}], note, range}。
export function teamGrid(team) {
  const source = Array.isArray(team?.days) ? team.days : [];
  const days = source.map((day) => {
    const text = day.label || shortDate(day.date).replace('-', '/');
    return {
      date: day.date, label: String(Number(String(day.date || '').slice(8, 10)) || text), title: [text, day.weekday].filter(Boolean).join(' '), off: Boolean(day.off_day),
    };
  });
  const found = new Map();
  source.forEach((day, index) => {
    const approved = new Set(day.approved || []);
    [['approved', [...approved]], ['pending', (day.pending || []).filter((name) => !approved.has(name))]].forEach(([state, names]) => names.forEach((name) => {
      const entry = found.get(name) || { name, states: new Array(days.length).fill('') };
      entry.states[index] = state;
      found.set(name, entry);
    }));
  });
  const rows = [...found.values()].map(({ name, states }) => ({
    name,
    first: states.findIndex(Boolean),
    pending: states.filter(Boolean).every((state) => state === 'pending'),
    cells: states.map((state, index) => ({ state, title: state ? `${name} · ${days[index].title}${state === 'pending' ? '（审批中）' : ''}` : '' })),
  })).sort((left, right) => left.first - right.first || left.name.localeCompare(right.name, 'zh'))
    .map(({ first, ...row }) => row);
  const totals = days.map((day, index) => {
    const n = rows.filter((row) => row.cells[index].state).length;
    return { n, crowded: !day.off && n >= 2 };
  });
  const range = days.length ? `${source[0].label || shortDate(source[0].date)} 至 ${source[source.length - 1].label || shortDate(source[source.length - 1].date)}` : '';
  return { days, rows, totals, note: team?.note || '', range };
}

// 我审批过的：后端给的是我那一步的状态（已通过 / 已拒绝 …）。
export function reviewedResult(row) {
  return /拒绝|驳回/.test(String(row?.my_status || '')) ? { text: '已驳回', tone: 'bad' } : { text: '已同意', tone: 'ok' };
}

// 我处理的时间：10-09 14:30。
export function actedText(row) {
  return String(row?.acted_on || '').replace('T', ' ').slice(5, 16);
}

// ---------------------------------------------------------------- 额度卡片

export function balanceKpis(home) {
  const annual = home?.annual || null;
  const comp = home?.comp || null;
  return {
    annual: annual ? { days: numText((annual.available_hours || 0) / HOURS_PER_DAY), hours: numText(annual.available_hours), used: numText(annual.used_hours) } : null,
    comp: comp ? { hours: numText(comp.available_hours), credit: numText(comp.credit_hours) } : null,
  };
}

// ---------------------------------------------------------------- 异步请求只认最新一次

// 日期连续改动、定时刷新、快速切换类型会同时发出多个请求；只有最近一次发出的请求结果可以用，旧的丢掉。
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

export const STALE_STEP = /单据已经变化|页面版本过旧/;

export const api = {
  home: (params) => callApi('attendance_entry.get_attendance_home', params, { method: 'GET' }),
  route: (requestType) => callApi('attendance_entry.get_attendance_route', { request_type: requestType }, { method: 'GET' }),
  mine: (requestType = '') => callApi('attendance_entry.list_attendance_mine', { request_type: requestType, limit: 100 }, { method: 'GET' }),
  review: () => callApi('attendance_entry.list_attendance_review', {}, { method: 'GET' }),
  reviewed: () => callApi('attendance_entry.list_attendance_reviewed', { limit: 100 }, { method: 'GET' }),
  all: (requestType = '') => callApi('attendance_entry.list_attendance_all', { request_type: requestType, limit: 100 }, { method: 'GET' }),
  detail: (name) => callApi('attendance_entry.get_attendance_request', { name }, { method: 'GET' }),
  options: (requestType, from, to) => callApi('oa_entry.get_attendance_options', { request_type: requestType, from_date: from || '', to_date: to || '' }, { method: 'GET' }),
  create: (params) => callApi('oa_entry.create_request', params),
  updateDraft: (params) => callApi('oa_entry.update_leave_draft', params),
  submitDraft: (name) => callApi('oa_entry.submit_request', { name }),
  act: (params) => callApi('oa_entry.action_request', params),
  withdraw: (name) => callApi('oa_entry.withdraw_request', { name }),
};
