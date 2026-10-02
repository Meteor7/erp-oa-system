// 研发工时填报页（/entry）用到的纯函数：状态判定、天数微调、平均分配、项目选择器筛选、
// 截止倒计时、填报进度汇总、服务器报错解析。不依赖 Vue，方便用 node:test 单独测。

export const HOURS_PER_DAY = 8;
export const DAY_STEP = 0.5;
const EPS = 1e-6;
const DAY_PATTERN = /^\d+(?:\.\d{1,2})?$/;

export const STATUS_META = {
  full: { label: '已填满', tone: 'ok' },
  part: { label: '未填满', tone: 'warn' },
  none: { label: '未填', tone: 'bad' },
  over: { label: '超上限', tone: 'bad' },
};

// 进度条颜色只表达状态：已填满 = 绿，未填满 = 琥珀，未填 = 红，超上限 = 红色斜纹。
const STATUS_FILL = {
  full: 'var(--rd-ok)',
  part: '#E0A030',
  none: 'var(--rd-bad)',
  over: 'repeating-linear-gradient(45deg, var(--rd-bad) 0 4px, #E8837A 4px 8px)',
};

export function statusMeta(status) {
  return STATUS_META[status] || { label: '', tone: '' };
}

export function statusFill(status) {
  return STATUS_FILL[status] || 'var(--rd-blue)';
}

export function round2(value) {
  return Math.round((Number(value) || 0) * 100) / 100;
}

export function validDays(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

// 1.50 -> "1.5"，2.00 -> "2"
export function trimDays(value) {
  return String(round2(value));
}

export function fmtDays(value, digits = 1) {
  return Number(value || 0).toFixed(digits);
}

export function rowHours(row) {
  return round2(validDays(row?.occurrence_days) * HOURS_PER_DAY);
}

export function sumDays(rows) {
  return round2((rows || []).reduce((sum, row) => sum + validDays(row?.occurrence_days), 0));
}

export function sumHours(rows) {
  return round2((rows || []).reduce((sum, row) => sum + rowHours(row), 0));
}

export function daysInMonth(period) {
  const match = String(period || '').match(/^(\d{4})-(\d{2})$/);
  if (!match) return 31;
  return new Date(Number(match[1]), Number(match[2]), 0).getDate();
}

export function previousPeriod(period) {
  const match = String(period || '').match(/^(\d{4})-(\d{2})$/);
  if (!match) return '';
  const date = new Date(Number(match[1]), Number(match[2]) - 2, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

// ---- 状态 ----
// 超上限 > 未填 > 已填满（差 0.01 天以内）> 未填满
export function deriveStatus(used, limit) {
  const u = Number(used) || 0;
  const l = Number(limit) || 0;
  if (u > l + EPS) return 'over';
  if (u <= EPS) return 'none';
  if (Math.abs(u - l) < 0.01) return 'full';
  return 'part';
}

export function needsRemind(status) {
  return status === 'none' || status === 'part';
}

export function progressPercent(used, limit) {
  const l = Number(limit) || 0;
  if (l <= 0) return Number(used) > 0 ? 100 : 0;
  return Math.max(0, Math.min(100, ((Number(used) || 0) / l) * 100));
}

// ---- 项目行 ----
export function projectCode(project) {
  return project?.rd_project_code || project?.project_code || project?.name || '';
}

export function projectName(project) {
  return project?.project_name || project?.name || '';
}

export function projectOwner(project) {
  return project?.project_owner_name || project?.project_owner || project?.owner_name || project?.project_manager || '';
}

export function findProject(projects, id) {
  return (projects || []).find((item) => item.name === id) || null;
}

let keySeed = 0;
export function newRowKey(prefix = 'new') {
  keySeed += 1;
  return `${prefix}-${Date.now()}-${keySeed}`;
}

export function rowFromProject(project, employee, days) {
  const value = validDays(days) || DAY_STEP;
  return {
    key: newRowKey(),
    monthly_entry_id: '',
    employee: employee || '',
    project: project?.name || '',
    project_code: projectCode(project),
    project_name: projectName(project),
    occurrence_days: trimDays(value),
    hours: round2(value * HOURS_PER_DAY),
    remark: '',
  };
}

// 新增项目时的默认天数：剩余不足 1 天就只给剩余的整 0.5 天，至少 0.5。
export function defaultNewDays(left) {
  const steps = Math.floor((Number(left) || 0) / DAY_STEP + 1e-9) * DAY_STEP;
  return Math.max(DAY_STEP, Math.min(1, steps));
}

export function canStepDown(value) {
  return validDays(value) > DAY_STEP + EPS;
}

export function stepDays(value, delta) {
  return trimDays(Math.max(DAY_STEP, round2(validDays(value) + delta)));
}

export function isValidDaysText(value) {
  const text = String(value ?? '').trim();
  return DAY_PATTERN.test(text) && Number(text) > 0;
}

// 把剩余天数平均分给现有项目：每行加 floor(剩余 / 行数 / 0.5) × 0.5，合计绝不超过上限。
export function averageFill(rows, limit) {
  const list = rows || [];
  const left = round2((Number(limit) || 0) - sumDays(list));
  if (!list.length || left < DAY_STEP - EPS) return { rows: list, added: 0 };
  const add = Math.floor(left / list.length / DAY_STEP + 1e-9) * DAY_STEP;
  if (add <= 0) return { rows: list, added: 0 };
  const next = list.map((row) => {
    const days = round2(validDays(row.occurrence_days) + add);
    return { ...row, occurrence_days: trimDays(days), hours: round2(days * HOURS_PER_DAY) };
  });
  return { rows: next, added: round2(add * list.length) };
}

// 复制上月：只取仍然可选的项目，去重，天数 > 0，备注不带过来。
export function rowsFromPrevious(entries, { employee = '', projects = [] } = {}) {
  const available = new Set((projects || []).map((item) => item.name));
  const seen = new Set();
  const rows = [];
  let skipped = 0;
  for (const entry of entries || []) {
    const project = String(entry?.project || '');
    const days = validDays(entry?.occurrence_days);
    if (!project || days <= 0 || seen.has(project)) continue;
    seen.add(project);
    if (available.size && !available.has(project)) {
      skipped += 1;
      continue;
    }
    rows.push({
      key: newRowKey('copy'),
      monthly_entry_id: '',
      employee,
      project,
      project_code: entry.project_code || '',
      project_name: entry.project_name || '',
      occurrence_days: trimDays(days),
      hours: round2(days * HOURS_PER_DAY),
      remark: '',
    });
  }
  return { rows, skipped };
}

// 保存前的逐行校验，文案与原页面一致。返回空串表示通过。
export function validateEntryRows(rows, { employee, hasLegacy = false, dayLimit } = {}) {
  if (!employee) return '请选择研发人员';
  if (hasLegacy) return '历史按日记录不能在月度视图中直接修改';
  const seen = new Set();
  let sum = 0;
  for (let index = 0; index < (rows || []).length; index += 1) {
    const row = rows[index];
    if (!row.project || !row.project_code || !row.project_name) return `第 ${index + 1} 行请选择项目`;
    if (seen.has(row.project)) return `第 ${index + 1} 行项目重复`;
    seen.add(row.project);
    const text = String(row.occurrence_days ?? '').trim();
    if (!DAY_PATTERN.test(text)) return `第 ${index + 1} 行发生天数最多保留两位小数`;
    const days = Number(text);
    if (!Number.isFinite(days) || days <= 0) return `第 ${index + 1} 行发生天数必须大于 0`;
    sum = round2(sum + days);
  }
  if (Number.isFinite(Number(dayLimit)) && sum > Number(dayLimit) + EPS) {
    return `当月累计发生天数不能超过 ${Number(dayLimit).toFixed(2)} 天`;
  }
  return '';
}

// 「4 月可填 20.0 天（160 小时）= 日历工时 176 小时 − 已批请假 16 小时」等说明文字。
export function capText({ month, dayLimit, hourLimit, baseHourLimit, leaveHours, joinedOn, relievedOn } = {}) {
  const parts = [`${month ? `${month} 月` : '本月'}可填 ${fmtDays(dayLimit, 1)} 天（${fmtDays(hourLimit, 0)} 小时）`];
  const base = baseHourLimit ?? hourLimit;
  parts.push(`= 日历工时 ${fmtDays(base, 0)} 小时 − 已批请假 ${fmtDays(leaveHours || 0, 0)} 小时`);
  let text = parts.join(' ');
  if (joinedOn) text += ` · ${joinedOn} 入职，之前的日子不计`;
  if (relievedOn) text += ` · ${relievedOn} 离职，之后的日子不计`;
  return text;
}

// ---- 名单（左侧列表） ----
export function rosterItemsFromProgress(employees) {
  return (employees || []).map((item) => {
    const used = Number(item.used_days) || 0;
    const limit = Number(item.limit_days) || 0;
    return {
      employee: item.employee,
      name: item.employee_name || item.employee,
      department: item.department || '',
      used,
      limit,
      status: item.status || deriveStatus(used, limit),
      lastReminded: item.last_reminded || '',
    };
  });
}

// 进度接口不可用时，名单只有姓名，没有进度条。
export function rosterItemsFromOptions(employees) {
  return (employees || []).map((item) => ({
    employee: item.name,
    name: item.employee_name || item.name,
    department: item.department || '',
    used: null,
    limit: null,
    status: '',
    lastReminded: '',
  }));
}

export function rosterCounts(items) {
  const list = items || [];
  return {
    all: list.length,
    full: list.filter((item) => item.status === 'full').length,
    todo: list.filter((item) => needsRemind(item.status)).length,
    over: list.filter((item) => item.status === 'over').length,
  };
}

export function filterRoster(items, { query = '', filter = 'all', department = 'all' } = {}) {
  const q = String(query || '').trim().toLowerCase();
  return (items || []).filter((item) => {
    if (q && !`${item.name} ${item.employee}`.toLowerCase().includes(q)) return false;
    if (filter === 'todo' && !needsRemind(item.status)) return false;
    if (filter === 'over' && item.status !== 'over') return false;
    if (department && department !== 'all' && item.department !== department) return false;
    return true;
  });
}

export function departmentsOf(items) {
  return [...new Set((items || []).map((item) => item.department).filter(Boolean))];
}

// ---- 添加项目选择器 ----
// 已用项目不再出现；按名称 / 编号 / 负责人搜索（多个词都要命中）；上月用过的排前面；最多 limit 个。
export function pickerOptions(projects, { usedIds = [], query = '', recentIds = [], limit = 8 } = {}) {
  const used = new Set(usedIds || []);
  const tokens = String(query || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
  const rank = new Map((recentIds || []).map((id, index) => [id, index]));
  const matched = (projects || [])
    .filter((project) => !used.has(project.name))
    .filter((project) => {
      const haystack = `${projectName(project)} ${projectCode(project)} ${projectOwner(project)} ${project.name}`.toLowerCase();
      return tokens.every((token) => haystack.includes(token));
    })
    .map((project, index) => ({ project, index }));
  matched.sort((a, b) => {
    const ra = rank.has(a.project.name) ? rank.get(a.project.name) : Infinity;
    const rb = rank.has(b.project.name) ? rank.get(b.project.name) : Infinity;
    if (ra !== rb) return ra - rb;
    return a.index - b.index;
  });
  return {
    total: matched.length,
    items: matched.slice(0, limit).map(({ project }) => ({ project, recent: rank.has(project.name) })),
  };
}

// ---- 截止倒计时 ----
function dayNumber(value) {
  if (value instanceof Date) return Math.floor(Date.UTC(value.getFullYear(), value.getMonth(), value.getDate()) / 86400000);
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  return Math.floor(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) / 86400000);
}

export function daysLeft(deadline, today = new Date()) {
  const end = dayNumber(deadline);
  const now = dayNumber(today);
  if (end === null || now === null) return null;
  return end - now;
}

export function deadlineLabel(days) {
  if (days === null || days === undefined) return '';
  if (days < 0) return `已逾期 ${-days} 天`;
  if (days === 0) return '今天截止';
  return `还剩 ${days} 天`;
}

export function deadlineTone(days, complete = false) {
  if (complete) return 'ok';
  if (days === null || days === undefined) return 'info';
  if (days < 0) return 'bad';
  if (days <= 3) return 'warn';
  return 'info';
}

// ---- 填报进度（看板） ----
export function boardKindLabel(kind) {
  if (kind === 'all') return '全公司';
  if (kind === 'team') return '本部门';
  return '本人';
}

function countOf(employees, status) {
  return (employees || []).filter((item) => item.status === status).length;
}

function pickNumber(value, fallback) {
  return value === undefined || value === null || value === '' || !Number.isFinite(Number(value)) ? fallback : Number(value);
}

// 汇总：服务器给了数字就用服务器的，没给就从名单算。
export function summarizeProgress(employees, summary) {
  const list = employees || [];
  const s = summary || {};
  const total = pickNumber(s.total, list.length);
  const full = pickNumber(s.full, countOf(list, 'full'));
  return {
    total,
    full,
    part: pickNumber(s.part, countOf(list, 'part')),
    none: pickNumber(s.none, countOf(list, 'none')),
    over: pickNumber(s.over, countOf(list, 'over')),
    rate: pickNumber(s.rate, total ? Math.round((full / total) * 100) : 0),
  };
}

export const UNASSIGNED_DEPARTMENT = '未分配部门';

export function groupByDepartment(employees) {
  const groups = new Map();
  for (const item of employees || []) {
    const key = item.department || UNASSIGNED_DEPARTMENT;
    if (!groups.has(key)) groups.set(key, { department: key, total: 0, full: 0, part: 0, none: 0, over: 0, rate: 0 });
    const group = groups.get(key);
    group.total += 1;
    if (group[item.status] !== undefined) group[item.status] += 1;
  }
  return [...groups.values()].map((group) => ({ ...group, rate: group.total ? Math.round((group.full / group.total) * 100) : 0 }));
}

// 需要跟进：未填、未填满。未填的在前，同类里进度低的在前。
export function followUpList(employees) {
  const rank = { none: 0, part: 1 };
  return (employees || [])
    .filter((item) => needsRemind(item.status))
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      if (rank[a.item.status] !== rank[b.item.status]) return rank[a.item.status] - rank[b.item.status];
      const pa = progressPercent(a.item.used_days, a.item.limit_days);
      const pb = progressPercent(b.item.used_days, b.item.limit_days);
      return pa - pb || a.index - b.index;
    })
    .map(({ item }) => item);
}

export function namesText(employees, max = 3) {
  const names = (employees || []).map((item) => item.employee_name || item.employee).filter(Boolean);
  if (!names.length) return '无';
  return names.slice(0, max).join('、') + (names.length > max ? '…' : '');
}

export function lastRemindedText(value, today = new Date()) {
  const match = String(value || '').match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
  if (!match) return '';
  return dayNumber(match[1]) === dayNumber(today) ? `今天 ${match[2]}` : `${match[1].slice(5)} ${match[2]}`;
}

export function remindResultText(result) {
  const sent = Number(result?.sent) || 0;
  const today = Number(result?.skipped_today) || 0;
  const done = Number(result?.skipped_done) || 0;
  const parts = [sent ? `已催办 ${sent} 人` : '没有发出催办'];
  if (today) parts.push(`${today} 人今天已催办过`);
  if (done) parts.push(`${done} 人已填满，无需催办`);
  return parts.join('，');
}

// ---- 服务器报错 ----
export function parseFrappeServerMessages(raw) {
  if (!raw) return [];
  try {
    const items = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (!Array.isArray(items)) return [];
    return items.map((message) => {
      try {
        const parsed = typeof message === 'string' ? JSON.parse(message) : message;
        return parsed.message || parsed.title || message;
      } catch {
        return message;
      }
    }).filter(Boolean);
  } catch {
    return [];
  }
}

export function serverMessage(error, fallback) {
  const messages = [...(error?.messages || []), ...parseFrappeServerMessages(error?._server_messages)]
    .map((value) => String(value || '').replace(/<[^>]*>/g, '').trim()).filter(Boolean);
  return messages.join('；') || String(error?._error_message || error?.message || fallback).replace(/<[^>]*>/g, '').trim();
}
