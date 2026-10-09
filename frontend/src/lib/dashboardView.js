// 首页看板的纯逻辑：把 get_home 的响应整理成页面直接能用的样子（页签状态、指标卡、提醒、待办、四种块的行）。
// 字段约定见 rayher_hr_payroll/dashboard/core.py；这里对缺字段、乱值都按"不显示"处理，不抛错。
import { firstValue } from './navContext.js';

export const TONES = Object.freeze(['', 'ok', 'info', 'warn', 'bad', 'hot']);
export const BLOCK_TYPES = Object.freeze(['bars', 'cols', 'stack', 'list']);
export const BLOCK_FAILED_TEXT = '这一块暂时加载失败';
export const EMPTY_TODO_TEXT = '没有需要你处理的事';
export const EMPTY_ALERT_TEXT = '目前没有需要关注的事';
export const EMPTY_BLOCK_TEXT = '本期暂无数据';
export const EMPTY_PAGE_TEXT = '这里暂时没有可看的内容';

const ALERT_LABELS = Object.freeze({ bad: '需处理', warn: '注意', info: '提示' });
// 堆叠条后端没给颜色（或给了不认识的写法）时按顺序用这组，和系统里其他图表的低饱和配色一致。
export const STACK_PALETTE = Object.freeze(['#D9731F', '#34489A', '#2F7A55', '#8A5A1C', '#8A93A3', '#B42318']);
const TONE_COLORS = Object.freeze({ ok: '#2F7A55', info: '#34489A', warn: '#D9731F', bad: '#B42318', hot: '#D9731F' });

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
// 地址里的 tab 不在返回的页签里（岗位变了、链接过期）就回到第一个。
export function resolveTabKey(tabs = [], requested) {
  const list = Array.isArray(tabs) ? tabs : [];
  const wanted = String(firstValue(requested) || '');
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

const ROW_MAKERS = Object.freeze({ bars: barRows, cols: colRows, stack: stackRows, list: listRows });

export function blockView(block = {}) {
  const type = BLOCK_TYPES.includes(block.type) ? block.type : '';
  const failed = Boolean(block.error);
  const rows = type && !failed ? ROW_MAKERS[type](block.rows) : [];
  return {
    key: String(block.key || ''), type, title: String(block.title || ''), sub: String(block.sub || ''),
    rows, failed, failedText: failed ? BLOCK_FAILED_TEXT : '', empty: !failed && rows.length === 0,
    more: String(block.more || ''), target: block.target || null, hint: String(block.hint || ''),
  };
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
  const showTodos = Boolean(source.has_todos);
  const showAlerts = Boolean(source.has_alerts);
  const attention = showTodos && showAlerts ? 'both' : showTodos ? 'todos' : showAlerts ? 'alerts' : 'none';
  return {
    kpis, alerts, todos, blocks, showTodos, showAlerts, attention,
    todoCount: todos.length, alertCount: alerts.length,
    isEmpty: !kpis.length && !blocks.length && !(showTodos || showAlerts),
  };
}
