// 首页看板的纯逻辑：把 get_home 的响应整理成页面直接能用的样子（页签状态、指标卡、提醒、待办、四种块的行）。
// 字段约定见 rayher_hr_payroll/dashboard/core.py；这里对缺字段、乱值都按"不显示"处理，不抛错。
import { firstValue } from './navContext.js';

export const TONES = Object.freeze(['', 'ok', 'info', 'warn', 'bad', 'hot']);
export const BLOCK_TYPES = Object.freeze(['bars', 'cols', 'stack', 'list', 'calendar']);
export const BLOCK_FAILED_TEXT = '这一块暂时加载失败';
export const EMPTY_TODO_TEXT = '没有需要你处理的事';
export const EMPTY_ALERT_TEXT = '目前没有需要关注的事';
export const EMPTY_BLOCK_TEXT = '本期暂无数据';
export const EMPTY_PAGE_TEXT = '这里暂时没有可看的内容';

const ALERT_LABELS = Object.freeze({ bad: '需处理', warn: '注意', info: '提示' });
// 堆叠条后端没给颜色（或给了不认识的写法）时按顺序用这组，和系统里其他图表的低饱和配色一致。
export const STACK_PALETTE = Object.freeze(['#147B73', '#34489A', '#2F7A55', '#8A5A1C', '#65788B', '#B42318']);
const TONE_COLORS = Object.freeze({ ok: '#2F7A55', info: '#34489A', warn: '#8A5A1C', bad: '#B42318', hot: '#147B73' });

// ---------------------------------------------------------------- 问候 / 期间
export function greetingFor(hour) {
  const h = Number(hour);
  if (h < 6) return '夜深了';
  if (h < 12) return '上午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

export function currentMonth(now = new Date()) {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

export function isValidMonth(value) {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(String(value || ''));
}

export function monthLabel(value) {
  if (!isValidMonth(value)) return '';
  const [year, month] = String(value).split('-');
  return `${year} 年 ${Number(month)} 月`;
}

// ---------------------------------------------------------------- 页签
// 旧页签的地址：研发页签并进了“经营”（cost），旧书签 ?tab=rd 落到经营页签（审查 2026-10-13）。
export const TAB_ALIASES = Object.freeze({ rd: 'cost' });

// 地址里的 tab 是旧名字时给出新名字，否则给 ''（页面据此把地址换成新名字）。
export function tabAlias(requested) {
  const wanted = String(firstValue(requested) || '');
  return Object.prototype.hasOwnProperty.call(TAB_ALIASES, wanted) ? TAB_ALIASES[wanted] : '';
}

// 地址里的 tab 不在返回的页签里（岗位变了、链接过期）就回到第一个；旧名字先换成新名字。
export function resolveTabKey(tabs = [], requested) {
  const list = Array.isArray(tabs) ? tabs : [];
  const raw = String(firstValue(requested) || '');
  const wanted = list.some((item) => item.key === raw) ? raw : (tabAlias(raw) || raw);
  if (wanted && list.some((item) => item.key === wanted)) return wanted;
  return list[0]?.key || '';
}

// 切页签时保留地址里的其他参数，只换 tab。
export function tabQuery(query = {}, key) {
  const next = {};
  for (const [name, raw] of Object.entries(query || {})) {
    const value = firstValue(raw);
    if (value !== undefined && value !== null && value !== '') next[name] = String(value);
  }
  next.tab = String(key);
  return next;
}

// 键盘左右键切页签（首尾循环）。
export function neighbourTab(tabs = [], current, step) {
  const list = Array.isArray(tabs) ? tabs : [];
  if (!list.length) return '';
  const index = Math.max(0, list.findIndex((item) => item.key === current));
  return list[(index + step + list.length) % list.length].key;
}

// ---------------------------------------------------------------- 通用小件
export function toneClass(tone) {
  return TONES.includes(tone) && tone ? `t-${tone}` : '';
}

export function clampPct(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, number));
}

// 条形图的宽度：有数就至少露出一点，免得 0.3% 看不见。
export function barWidth(pct) {
  const value = clampPct(pct);
  return value > 0 ? Math.max(value, 1.5) : 0;
}

// 只放行十六进制 / rgb / hsl 写法或 tone 名，其他一律按序号取配色（颜色会写进 style，不能原样信任）。
export function safeColor(color, index = 0) {
  const text = String(color || '').trim();
  if (/^#[0-9a-fA-F]{3,8}$/.test(text)) return text;
  if (/^(rgb|hsl)a?\([\d\s.,%/-]+\)$/.test(text)) return text;
  if (TONE_COLORS[text]) return TONE_COLORS[text];
  return STACK_PALETTE[index % STACK_PALETTE.length];
}

export function errorText(error) {
  if (!error) return '';
  return error.messages?.[0] || error.message || String(error);
}

// ---------------------------------------------------------------- 指标卡 / 提醒 / 待办
export function kpiView(item = {}) {
  return {
    key: String(item.key || ''),
    label: String(item.label || ''),
    value: item.value === undefined || item.value === null || item.value === '' ? '—' : String(item.value),
    unit: String(item.unit || ''),
    sub: String(item.sub || ''),
    tone: TONES.includes(item.tone) ? item.tone : '',
    toneClass: toneClass(item.tone),
    hint: String(item.hint || ''),
    preview: Boolean(item.preview),
    target: item.target || null,
  };
}

export function alertView(item = {}) {
  const tone = ALERT_LABELS[item.tone] ? item.tone : 'info';
  return {
    key: String(item.key || ''), tone, toneClass: `t-${tone}`, toneLabel: ALERT_LABELS[tone],
    title: String(item.title || ''), sub: String(item.sub || ''), go: String(item.go || ''), target: item.target || null,
  };
}

export function todoView(item = {}) {
  const tone = TONES.includes(item.tone) && item.tone ? item.tone : 'info';
  return {
    kind: String(item.kind || ''), title: String(item.title || ''), sub: String(item.sub || ''),
    btn: String(item.btn || '去处理'), tone, toneClass: `t-${tone}`, target: item.target || null,
  };
}

// ---------------------------------------------------------------- 四种块的行
export function barRows(rows = []) {
  return (Array.isArray(rows) ? rows : []).map((row) => ({
    label: String(row.label ?? ''), value: String(row.value ?? ''), width: barWidth(row.pct), toneClass: toneClass(row.tone),
  }));
}

export function colRows(rows = []) {
  return (Array.isArray(rows) ? rows : []).map((row) => ({
    label: String(row.label ?? ''), value: String(row.value ?? ''), height: barWidth(row.pct), last: Boolean(row.last),
  }));
}

export function stackRows(rows = []) {
  return (Array.isArray(rows) ? rows : []).map((row, index) => ({
    label: String(row.label ?? ''), value: String(row.value ?? ''), width: clampPct(row.pct), color: safeColor(row.color, index),
  }));
}

export function listRows(rows = []) {
  return (Array.isArray(rows) ? rows : []).map((row) => ({
    label: String(row.label ?? ''), sub: String(row.sub ?? ''), value: String(row.value ?? ''),
    toneClass: TONES.includes(row.tone) && row.tone ? `t-${row.tone}` : '', target: row.target || null,
  }));
}

// ---------------------------------------------------------------- 日历块（团队日历：行 = 人，列 = 天）
// 颜色和考勤中心一致；虚线 = 还在审批；最下面一行是当天在岗人数，人少的日子标橙 / 红。
export const CALENDAR_KINDS = Object.freeze({ annual: '年假', personal: '事假', sick: '病假', comp: '调休', other: '其他假', trip: '出差', ot: '加班' });
export const LOW_STAFF_MIN = 3;
export const LOW_STAFF_SHARE = 0.2;
export const BAD_STAFF_SHARE = 0.4;

export function staffLevel(off, headcount) {
  const count = Number(off) || 0;
  const total = Number(headcount) || 0;
  if (!total || count < Math.max(LOW_STAFF_MIN, Math.ceil(total * LOW_STAFF_SHARE))) return '';
  return count / total >= BAD_STAFF_SHARE ? 'low' : 'mid';
}

export function calendarView(block = {}) {
  const days = (Array.isArray(block.days) ? block.days : []).map((day) => ({
    date: String(day.date || ''), label: String(day.label || ''), day: Number(day.day) || 0, weekday: String(day.weekday || ''), off: Boolean(day.off_day),
  }));
  const people = (Array.isArray(block.people) ? block.people : []).map((person) => ({
    name: String(person.name ?? ''),
    cells: days.map((day, index) => {
      const cell = person.cells?.[index];
      if (!cell || !CALENDAR_KINDS[cell.kind]) return null;
      const pending = Boolean(cell.pending);
      return { kind: cell.kind, pending, title: `${person.name ?? ''} ${day.label} ${CALENDAR_KINDS[cell.kind]}${pending ? '（审批中）' : ''}` };
    }),
  }));
  // 没有 totals（比如我自己的“下两周”只有一行）就不画最下面的在岗人数。
  const wantTotals = Array.isArray(block.totals) && block.totals.length > 0;
  const totals = !wantTotals ? [] : days.map((day, index) => {
    const total = block.totals?.[index] || {};
    const present = total.present === null || total.present === undefined ? null : Number(total.present);
    return { off: Number(total.off) || 0, present, level: present === null ? '' : staffLevel(total.off, people.length), title: present === null ? '休息日' : `${Number(total.off) || 0} 人不在岗` };
  });
  const legend = Object.entries(CALENDAR_KINDS).map(([kind, label]) => ({ kind, label }));
  return { days, people, totals, legend, headcount: people.length };
}

const ROW_MAKERS = Object.freeze({ bars: barRows, cols: colRows, stack: stackRows, list: listRows, calendar: () => [] });

export function blockView(block = {}) {
  const type = BLOCK_TYPES.includes(block.type) ? block.type : '';
  const failed = Boolean(block.error);
  const rows = type && !failed ? ROW_MAKERS[type](block.rows) : [];
  const calendar = type === 'calendar' && !failed ? calendarView(block) : null;
  return {
    key: String(block.key || ''), type, title: String(block.title || ''), sub: String(block.sub || ''),
    rows, calendar, wide: type === 'calendar' || block.wide === true, failed, failedText: failed ? BLOCK_FAILED_TEXT : '',
    empty: !failed && (calendar ? calendar.people.length === 0 : rows.length === 0),
    more: String(block.more || ''), target: block.target || null, hint: String(block.hint || ''),
  };
}

// 页签里的一段：小标题 + 自己的指标卡和图表块（人事页的“人员 / 考勤”）。
export function sectionView(section = {}) {
  const kpis = (section.kpis || []).map(kpiView);
  const blocks = (section.blocks || []).map(blockView).filter((block) => block.type);
  return { title: String(section.title || ''), sub: String(section.sub || ''), kpis, blocks };
}

// ---------------------------------------------------------------- 一个页签
// 「要我处理」和「需要关注」是否显示由后端的 has_todos / has_alerts 决定（岗位有没有这两块）；
// 显示了但里面是空的，就写"没有需要你处理的事"，而不是整块消失。
export function pageView(page) {
  const source = page && typeof page === 'object' ? page : {};
  const kpis = (source.kpis || []).map(kpiView);
  const alerts = (source.alerts || []).map(alertView);
  const todos = (source.todos || []).map(todoView);
  const blocks = (source.blocks || []).map(blockView).filter((block) => block.type);
  const sections = (source.sections || []).map(sectionView).filter((section) => section.kpis.length || section.blocks.length);
  const showTodos = Boolean(source.has_todos);
  const showAlerts = Boolean(source.has_alerts);
  const attention = showTodos && showAlerts ? 'both' : showTodos ? 'todos' : showAlerts ? 'alerts' : 'none';
  // 2026-10-13 排版：后端 kpis_first=false（干活岗位的总览）时先放「要我处理」；没给就按原来先放指标卡
  const kpisFirst = source.kpis_first !== false;
  return {
    kpis, alerts, todos, blocks, sections, showTodos, showAlerts, attention, kpisFirst,
    todoCount: todos.length, alertCount: alerts.length,
    isEmpty: !kpis.length && !blocks.length && !sections.length && !(showTodos || showAlerts),
  };
}
