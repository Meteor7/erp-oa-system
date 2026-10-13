// 请假 / 加班 / 调休的列表、详情和新建页用到的纯函数：筛选、行上的文字、新建页月历选日期。
// 规则（每天 8 小时、上午 3、下午 5、自定义每次 0.5）和服务端校验仍在 attendanceView.js 和后端，这里只管展示和筛选。
import {
  actedText, canQuickApprove, dayChip, filterRows, isTrip, isoDate, modeOfHours, nodeText, numText, parseDate, reviewedResult, rowDays, shortDate, sizeText,
  statusTag, totalOf, waitText, waitingSince, weekLabel, workedSpan,
} from './attendanceView.js';
import { calendarDaysSince, isWaitingTooLong } from './waiting.js';

export const TIME_FILTERS = Object.freeze([['all', '全部时间'], ['week', '未来 7 天'], ['month', '本月']]);

export function addDays(iso, count) {
  const date = parseDate(iso);
  if (!date) return '';
  date.setDate(date.getDate() + count);
  return isoDate(date);
}

// 一张申请占用的日期（有时长的天）；没有逐日明细时用起止日期。
export function rowDates(row) {
  const days = rowDays(row).map((day) => String(day.work_date).slice(0, 10));
  if (days.length) return days;
  const from = String(row?.from_date || '').slice(0, 10);
  return from ? [from] : [];
}

// 时间筛选：未来 7 天 = 有一天落在今天到 7 天后；本月 = 有一天在今天所在的月。
export function timeMatch(row, key, today) {
  if (key === 'all' || !key) return true;
  const dates = rowDates(row);
  if (!dates.length) return true;
  if (key === 'week') {
    const end = addDays(today, 7);
    return dates.some((date) => date >= today && date <= end);
  }
  return dates.some((date) => date.slice(0, 7) === String(today).slice(0, 7));
}

// 等太久：和数据看板、各审批页同一条规则（按日历日算，严格大于 3 天，见 waiting.js）。
export function isSlow(row, now = Date.now()) {
  const since = waitingSince(row);
  return since !== null && isWaitingTooLong(calendarDaysSince(since, now));
}

export function searchMatch(row, query) {
  const text = String(query || '').trim().toLowerCase();
  if (!text) return true;
  return [row?.employee_name, row?.name, row?.subject, row?.reason, row?.department, row?.travel_destination, row?.project].join(' ').toLowerCase().includes(text);
}

// 列表上的筛选：类型、时间、只看等了超过 3 天的、搜索。
export function applyFilters(rows, { type = 'all', time = 'all', slow = false, query = '' } = {}, { today = '', now = Date.now() } = {}) {
  return filterRows(rows, type).filter((row) => timeMatch(row, time, today) && (!slow || isSlow(row, now)) && searchMatch(row, query));
}

export function filtersActive({ type = 'all', time = 'all', slow = false, query = '' } = {}) {
  return type !== 'all' || time !== 'all' || Boolean(slow) || Boolean(String(query || '').trim());
}

// ---------------------------------------------------------------- 一行上的文字
const dayText = (date) => `${shortDate(date).replace('-', '/')} ${weekLabel(date)}`;

// "10/26 周一 – 10/27 周二"；只有一天时带上时段："10/30 周五 · 全天"（上午、下午同理）。加班和自定义小时不重复写小时数（旁边的时长里有）。
export function whenText(row) {
  const days = rowDays(row);
  const span = days.length ? workedSpan(days, row?.from_date, row?.to_date) : { from: row?.from_date, to: row?.to_date };
  const from = String(span.from || '').slice(0, 10);
  const to = String(span.to || span.from || '').slice(0, 10);
  if (!from) return '';
  if (from !== to) return `${dayText(from)} – ${dayText(to)}`;
  const chip = days.length === 1 ? dayChip(days[0], row?.request_type === '加班申请') : null;
  return chip && ['full', 'am', 'pm'].includes(chip.mode) && row?.request_type !== '加班申请' && !isTrip(row) ? `${dayText(from)} · ${chip.label}` : dayText(from);
}

// "2 天 · 16 小时" / "3 小时" / 出差 "3 天"
export function lengthText(row) {
  if (isTrip(row)) return sizeText(row);
  const hours = numText(totalOf(row));
  const count = rowDays(row).length;
  return count > 1 ? `${count} 天 · ${hours} 小时` : `${hours} 小时`;
}

// 行右边那一格：{tag: {text, tone} | null, sub}。待我审批说等了多久；我审批过的说我做了什么；其他是申请状态和当前节点。
export function statusInfo(row, scope, now = Date.now(), names = {}) {
  if (scope === 'done') {
    const result = reviewedResult(row);
    return { tag: { text: result.text, tone: result.tone }, sub: actedText(row) };
  }
  if (scope === 'todo') {
    const text = waitText(row, now);
    if (!text || text === '刚刚') return { tag: null, sub: '刚刚提交' };
    return { tag: { text: `等了 ${text}`, tone: isSlow(row, now) ? 'bad' : 'warn' }, sub: '' };
  }
  const tag = statusTag(row);
  return { tag, sub: tag.text === '审批中' ? nodeText(row, names) : '' };
}

// 选中的那行：还在列表里就是它，否则（批掉了、换了筛选）退回第一行；没有就是 null。
export function pickSelected(rows, name) {
  return (rows || []).find((row) => row.name === name) || (rows || [])[0] || null;
}

export function batchable(rows) {
  return (rows || []).filter(canQuickApprove);
}

// ---------------------------------------------------------------- 新建页的月历
export const monthOf = (iso) => String(iso || '').slice(0, 7);

export function shiftMonth(month, delta) {
  const [year, number] = String(month || '').split('-').map(Number);
  const date = new Date(year || 2000, (number || 1) - 1 + Number(delta || 0), 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

// 一个月的格子：周一开头，前面补空格。cells 里 null 是空格，其余 {date, day}。
export function monthGrid(month) {
  const [year, number] = String(month || '').split('-').map(Number);
  const first = new Date(year, number - 1, 1);
  const last = new Date(year, number, 0).getDate();
  const cells = Array.from({ length: (first.getDay() + 6) % 7 }, () => null);
  for (let day = 1; day <= last; day += 1) cells.push({ date: isoDate(new Date(year, number - 1, day)), day });
  return { title: `${year} 年 ${number} 月`, from: isoDate(first), to: isoDate(new Date(year, number - 1, last)), cells };
}

// 点一天以后的起止日期。先点开始日，再点结束日；只请一天点一次就够；结束日早于开始日时重新当作开始日。
// 加班默认只选一天（multi 为 false），勾了"跨多天"才能选范围。
export function pickRange(state, date, { multi = true } = {}) {
  if (!multi) return { from: date, to: date, awaiting: false };
  if (!state?.from || !state.awaiting) return { from: date, to: date, awaiting: true };
  if (date < state.from) return { from: date, to: date, awaiting: true };
  return { from: state.from, to: date, awaiting: false };
}

// 月历上一天的状态：work 能选；rest 休息日（请假和调休选不了，加班可以）；busy 这天已经被占满；part 这天已有部分申请（还能请一部分）。
// info：这个月服务端返回的可填日子 Map(日期 → {conflict, max_hours})；还没取到时都当 work。
export function dayStatus(date, info, overtime = false) {
  if (!info) return 'work';
  const day = info.get(date);
  if (!day) return overtime ? 'work' : 'rest';
  if (day.conflict) return 'busy';
  return Number(day.max_hours ?? 8) < 8 && !overtime ? 'part' : 'work';
}

export function infoMap(days) {
  return new Map((days || []).map((day) => [day.work_date, day]));
}

export const inRange = (date, from, to) => Boolean(from) && date >= from && date <= (to || from);

// ---------------------------------------------------------------- 申请详情上的日期条
// 申请的日期前后各留两天，每天一格：申请的那几天标出时段（全天 / 上午 / 下午 / N 小时），休息日浅色。最多 10 格。
export function stripCells(row, { before = 2, max = 10 } = {}) {
  const days = rowDays(row);
  if (!days.length) return [];
  const overtime = row?.request_type === '加班申请';
  const byDate = new Map(days.map((day) => [String(day.work_date).slice(0, 10), day]));
  const dates = [...byDate.keys()].sort();
  const start = addDays(dates[0], -before);
  const span = Math.min(max, Math.round((parseDate(dates[dates.length - 1]) - parseDate(dates[0])) / 864e5) + before * 2 + 1);
  return Array.from({ length: span }, (_, index) => {
    const date = addDays(start, index);
    const day = byDate.get(date);
    const mode = day ? modeOfHours(day.hours) : '';
    return {
      date, label: shortDate(date).replace('-', '/'), week: weekLabel(date).slice(1), hit: Boolean(day),
      off: [0, 6].includes(parseDate(date).getDay()),
      text: day ? (isTrip(row) ? '出差' : overtime || mode === 'custom' ? `${numText(day.hours)}h` : { full: '全天', am: '上午', pm: '下午' }[mode] || `${numText(day.hours)}h`) : '',
      title: `${dayText(date)}${day ? (isTrip(row) ? ' 出差' : ` ${numText(day.hours)} 小时`) : ''}`,
    };
  });
}
