// 境外委托研发工时：和国内研发工时填报同一个规则——填的是小时（最多两位小数），天数 = 小时 ÷ 8 只用来显示、
// 保存时一起带上。每一行（主体 + 项目）一个月的工时不能超过当月自然日数 × 8 小时。
export const HOURS_PER_DAY = 8;
export const HOUR_STEP = 1;

const round2 = (value) => Math.round(Number(value) * 100) / 100;

// 小时 → 天，显示用（最多两位小数）。
export function daysOfHours(hours) {
  const value = Number(hours);
  return Number.isFinite(value) ? round2(value / HOURS_PER_DAY) : 0;
}

// 保存时带给后端的天数（五位小数，和库里的精度一致）。
export function savedDays(hours) {
  const value = Number(hours);
  return Number.isFinite(value) ? Math.round((value / HOURS_PER_DAY) * 100000) / 100000 : 0;
}

export function stepHours(current, delta) {
  const value = Number(current);
  const next = round2((Number.isFinite(value) ? value : 0) + delta);
  return Math.max(0, Number.isFinite(next) ? next : 0);
}

// 输入的小时文本：{ value, error }；error 为 '' | 'format' | 'precision' | 'zero'。
export function parseHoursText(text) {
  const raw = String(text ?? '').trim();
  if (!/^\d+(?:\.\d+)?$/.test(raw)) return { value: null, error: 'format' };
  if (!/^\d+(?:\.\d{1,2})?$/.test(raw)) return { value: null, error: 'precision' };
  const value = Number(raw);
  return value > 0 ? { value, error: '' } : { value: null, error: 'zero' };
}

// 会计期间 "2026-06" → 当月自然日数 × 8（没有期间就按 31 天）。
export function monthHourLimit(period) {
  const match = String(period ?? '').trim().match(/^(\d{4})-(\d{2})$/);
  const days = match ? new Date(Number(match[1]), Number(match[2]), 0).getDate() : 31;
  return days * HOURS_PER_DAY;
}

const fmt = (value) => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });

// 逐行校验，返回第一条错误（没有错误返回空字符串）；rows 是页面上已填的行。
export function validateForeignRows(rows, { period = '', entities = [], commonAmount = 0 } = {}) {
  if (!rows.length) return Number(commonAmount) > 0 ? '有境外公共费用时，必须录入至少一条工时' : '请至少填写一条境外工时';
  const limit = monthHourLimit(period);
  const keys = new Set();
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    const label = `${index + 1}.`;
    if (!entities.includes(row.foreign_entity)) return `${label} 请选择研发主体`;
    if (!row.project || !row.project_code || !row.project_name) return `${label} 请选择项目`;
    const parsed = parseHoursText(row.hours);
    if (parsed.error === 'precision') return `${label} 工时最多保留两位小数`;
    if (parsed.error) return `${label} 工时必须大于 0（单位：小时）`;
    if (parsed.value > limit) return `${label} 工时不能超过当月自然日数 × 8 = ${fmt(limit)} 小时`;
    const key = `${row.foreign_entity}|${row.project}`;
    if (keys.has(key)) return `${label} 同一主体和项目只能填写一行`;
    keys.add(key);
  }
  return '';
}

// 保存给后端的行：小时是源头，天数是小时 ÷ 8（后端据此认出这是月度行）。
export function payloadRow(row) {
  const hours = Number(row.hours);
  return {
    foreign_entity: row.foreign_entity,
    project: row.project,
    project_code: row.project_code,
    project_name: row.project_name,
    hours,
    occurrence_days: savedDays(hours),
    remark: String(row.remark || '').trim(),
  };
}
