// 研发工时填报页（/entry）用到的纯函数：状态判定、小时微调、平均分配、项目选择器筛选、
// 截止倒计时、填报进度汇总、服务器报错解析。不依赖 Vue，方便用 node:test 单独测。
// 2026-10-12 起月度工时按小时填：小时是真实的数，天数 = 小时 ÷ 8，只用来显示；一天最多 8 小时这条不变
// （月度上限 = 工作日 × 8 − 已批事假小时，保存时系统自动把小时摊到各个工作日）。

export const HOURS_PER_DAY = 8;
export const HOUR_STEP = 1;
export const MIN_HOURS = 0.5;
const EPS = 1e-6;
const HOURS_PATTERN = /^\d+(?:\.\d{1,2})?$/;

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

export function validHours(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

// 1.50 -> "1.5"，2.00 -> "2"
export function trimHours(value) {
  return String(round2(value));
}

// 小时反推的天数（显示用，两位小数）：173 小时 = 21.63 天（21.625）
export function daysOfHours(hours) {
  return round2((Number(hours) || 0) / HOURS_PER_DAY);
}

export function fmtDays(value, digits = 1) {
  return Number(value || 0).toFixed(digits);
}

// 一行填的小时数
export function rowHours(row) {
  return round2(validHours(row?.hours));
}

export function rowDays(row) {
  return daysOfHours(rowHours(row));
}

export function sumHours(rows) {
  return round2((rows || []).reduce((sum, row) => sum + rowHours(row), 0));
}

export function sumDays(rows) {
  return daysOfHours(sumHours(rows));
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

// ---- 上限、剩余、状态（都按小时算，精确比较，没有零头容差） ----
// 离上限还差多少小时
export function remainingHours(used, limit) {
  return Math.max(0, round2((Number(limit) || 0) - (Number(used) || 0)));
}

// 超上限 > 未填 > 已填满（填的小时等于可填小时）> 未填满；可填 0 小时的人没有什么要填，算已填满
export function deriveStatus(usedHours, limitHours) {
  const used = round2(usedHours);
  const limit = round2(limitHours);
  if (used > limit + EPS) return 'over';
  if (used <= EPS) return limit > EPS ? 'none' : 'full';
  return Math.abs(limit - used) < 0.005 ? 'full' : 'part';
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

// 把一行的小时设成 hours（字符串，同时更新反推的天数）
export function withHours(row, hours) {
  return { ...row, hours: trimHours(hours), occurrence_days: daysOfHours(hours) };
}

export function rowFromProject(project, employee, hours) {
  const value = validHours(hours) || HOUR_STEP;
  return {
    key: newRowKey(),
    monthly_entry_id: '',
    employee: employee || '',
    project: project?.name || '',
    project_code: projectCode(project),
    project_name: projectName(project),
    hours: trimHours(value),
    occurrence_days: daysOfHours(value),
    remark: '',
  };
}

// 新增项目时的默认小时：剩余够一天就给整数小时（最多 8），不够 1 小时就按 0.5 小时往下取，至少 0.5。
export function defaultNewHours(left) {
  const room = Number(left) || 0;
  if (room >= 1) return Math.min(HOURS_PER_DAY, Math.floor(room + 1e-9));
  return Math.max(MIN_HOURS, Math.floor(room * 2 + 1e-9) / 2);
}

export function canStepDown(value) {
  return validHours(value) > MIN_HOURS + EPS;
}

export function stepHours(value, delta) {
  return trimHours(Math.max(MIN_HOURS, round2(validHours(value) + delta)));
}

export function isValidHoursText(value) {
  const text = String(value ?? '').trim();
  return HOURS_PATTERN.test(text) && Number(text) > 0;
}

// 把某一行补到上限：该行的小时 = 现有 + 剩余，合计正好到「已填满」。
// index 是想补的那一行（最后编辑的那行），没有或越界就补最后一行。
export function topUpRow(rows, limit, index) {
  const list = rows || [];
  const target = Number.isInteger(index) && index >= 0 && index < list.length ? index : list.length - 1;
  const add = remainingHours(sumHours(list), limit);
  if (target < 0 || add <= 0) return { rows: list, added: 0, index: target };
  const next = list.map((row, i) => (i === target ? withHours(row, rowHours(row) + add) : row));
  return { rows: next, added: add, index: target };
}

// 把剩余小时平均分给现有项目：先每行加 floor(剩余 / 行数 / 1) 个整小时，分不尽的零头全部加在最后一行，合计正好到上限，绝不超过。
export function averageFill(rows, limit) {
  const list = rows || [];
  const left = remainingHours(sumHours(list), limit);
  if (!list.length || left <= 0) return { rows: list, added: 0 };
  const add = Math.floor(left / list.length / HOUR_STEP + 1e-9) * HOUR_STEP;
  const rest = round2(left - add * list.length);
  const next = list.map((row, index) => {
    const extra = add + (index === list.length - 1 ? rest : 0);
    return extra <= 0 ? row : withHours(row, rowHours(row) + extra);
  });
  return { rows: next, added: left };
}

// 复制上月：只取仍然可选的项目，去重，小时 > 0，备注不带过来。
export function rowsFromPrevious(entries, { employee = '', projects = [] } = {}) {
  const available = new Set((projects || []).map((item) => item.name));
  const seen = new Set();
  const rows = [];
  let skipped = 0;
  for (const entry of entries || []) {
    const project = String(entry?.project || '');
    // 老记录只有天数时按 天 × 8 换算
    const hours = validHours(entry?.hours) || validHours(entry?.occurrence_days) * HOURS_PER_DAY;
    if (!project || hours <= 0 || seen.has(project)) continue;
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
      hours: trimHours(hours),
      occurrence_days: daysOfHours(hours),
      remark: '',
    });
  }
  return { rows, skipped };
}

// 小时显示：去掉多余的 0（173 -> "173"，172.5 -> "172.5"）
export function fmtHours(value) {
  return String(round2(value));
}

// 天数显示：至少一位小数，最多两位（20 -> "20.0"，21.63 -> "21.63"）
export function fmtDaysExact(value) {
  const text = String(round2(value));
  return text.includes('.') ? text : `${text}.0`;
}

// 保存前的逐行校验。返回空串表示通过。
export function validateEntryRows(rows, { employee, hasLegacy = false, hourLimit } = {}) {
  if (!employee) return '请选择研发人员';
  if (hasLegacy) return '历史按日记录不能在月度视图中直接修改';
  const seen = new Set();
  let sum = 0;
  for (let index = 0; index < (rows || []).length; index += 1) {
    const row = rows[index];
    if (!row.project || !row.project_code || !row.project_name) return `第 ${index + 1} 行请选择项目`;
    if (seen.has(row.project)) return `第 ${index + 1} 行项目重复`;
    seen.add(row.project);
    const text = String(row.hours ?? '').trim();
    if (!text) return `第 ${index + 1} 行请填写工时`;
    if (!HOURS_PATTERN.test(text)) return `第 ${index + 1} 行工时必须是不超过两位小数的数字`;
    const hours = Number(text);
    if (!Number.isFinite(hours) || hours <= 0) return `第 ${index + 1} 行工时必须大于 0`;
    sum = round2(sum + hours);
  }
  if (Number.isFinite(Number(hourLimit)) && deriveStatus(sum, hourLimit) === 'over') {
    return `当月累计工时不能超过 ${fmtHours(hourLimit)} 小时：当前 ${fmtHours(sum)} 小时，本月最多 ${fmtHours(hourLimit)} 小时`;
  }
  return '';
}

// 「4 月可填 160 小时（约 20.0 天）= 日历工时 176 小时 − 已批请假 16 小时」等说明文字。
export function capText({ month, hourLimit, baseHourLimit, leaveHours, joinedOn, relievedOn } = {}) {
  const parts = [`${month ? `${month} 月` : '本月'}可填 ${fmtHours(hourLimit)} 小时（约 ${fmtDaysExact(daysOfHours(hourLimit))} 天）`];
  const base = baseHourLimit ?? hourLimit;
  parts.push(`= 日历工时 ${fmtHours(base)} 小时 − 已批请假 ${fmtHours(leaveHours || 0)} 小时`);
  let text = parts.join(' ');
  if (joinedOn) text += ` · ${joinedOn} 入职，之前的日子不计`;
  if (relievedOn) text += ` · ${relievedOn} 演示员工166，之后的日子不计`;
  return text;
}

// ---- 名单（左侧列表） ----
export function rosterItemsFromProgress(employees) {
  return (employees || []).map((item) => {
    const used = Number(item.used_hours ?? (Number(item.used_days) || 0) * HOURS_PER_DAY) || 0;
    const limit = Number(item.limit_hours ?? (Number(item.limit_days) || 0) * HOURS_PER_DAY) || 0;
    return {
      employee: item.employee,
      name: item.employee_name || item.employee,
      department: item.department || '',
      used,
      limit,
      usedDays: daysOfHours(used),
      limitDays: daysOfHours(limit),
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

// ---- 填报进度看板（部门筛选 / 还差排序 / 催办是否还有意义） ----
const FOLLOW_STATUSES = new Set(['none', 'part', 'over']);

// 进度条只表达「填了多少」：统一绿色，超上限用红色；状态由「还差」和标签表达。
export function barColor(status) {
  return status === 'over' ? 'var(--rd-bad)' : 'var(--rd-ok)';
}

export function avatarText(name) {
  return String(name || '').trim().slice(-2);
}

// 还差多少天（超上限和已填满都是 0）
export function gapDays(item) {
  return Math.max(0, round2((Number(item?.limit_days) || 0) - (Number(item?.used_days) || 0)));
}

export function gapText(item) {
  if (item?.status === 'over') return `超 ${fmtDays((Number(item.used_days) || 0) - (Number(item.limit_days) || 0), 1)}`;
  return `−${fmtDays(gapDays(item), 1)}`;
}

// 超上限、或差 10 天以上标红
export function gapTone(item) {
  return item?.status === 'over' || gapDays(item) >= 10 ? 'bad' : '';
}

export function matchesDepartment(item, department = 'all') {
  if (!department || department === 'all') return true;
  return (item?.department || UNASSIGNED_DEPARTMENT) === department;
}

// 左侧部门列表：已填满 / 总人数，条形 = 已填满占比（保持名单里出现的先后顺序）。
export function departmentBars(employees) {
  return groupByDepartment(employees).map((group) => ({
    department: group.department,
    total: group.total,
    full: group.full,
    percent: group.total ? Math.round((group.full / group.total) * 1000) / 10 : 0,
  }));
}

// 「需要跟进的人」：未填 / 未填满 / 超上限；可按部门和状态筛选；按「还差」从多到少排（同样多保持原顺序）。
export function followUpRows(employees, { department = 'all', status = 'all' } = {}) {
  return (employees || [])
    .filter((item) => FOLLOW_STATUSES.has(item.status))
    .filter((item) => matchesDepartment(item, department))
    .filter((item) => !status || status === 'all' || item.status === status)
    .map((item, index) => ({ item, index }))
    .sort((a, b) => gapDays(b.item) - gapDays(a.item) || a.index - b.index)
    .map(({ item }) => item);
}

// 筛选按钮上的数字：在所选部门范围内统计。
export function followUpCounts(employees, department = 'all') {
  const list = followUpRows(employees, { department });
  return {
    all: list.length,
    none: list.filter((item) => item.status === 'none').length,
    part: list.filter((item) => item.status === 'part').length,
    over: list.filter((item) => item.status === 'over').length,
  };
}

// 催办规则：该月已过截止日（截止日 = 当月最后一天，进度接口给出）就不再催办，
// 此时月度工时已被锁定 / 进入分摊，催了也没人能补。进度接口没有给出「已分摊」字段，所以只按截止日判断。
export const REMIND_CLOSED_TEXT = '该月已截止/已分摊，无需催办';

export function remindClosed(deadline, today = new Date()) {
  const days = daysLeft(deadline, today);
  return days !== null && days < 0;
}

// ---- 个人填报：项目配色、分段进度条、剩余文案 ----
// 5 色低饱和调色板，项目行的色点和分段条用同一个下标取色。
export const PROJECT_COLORS = ['#4C6A92', '#5E9C8F', '#C98B3C', '#8A6BA8', '#B5586B'];

export function projectColor(index) {
  const size = PROJECT_COLORS.length;
  const n = Number(index) || 0;
  return PROJECT_COLORS[((n % size) + size) % size];
}

// 占本月上限的百分比（四舍五入到整数，上限 0 时为 0）
export function sharePercent(hours, limit) {
  const l = Number(limit) || 0;
  if (l <= 0) return 0;
  return Math.round((validHours(hours) / l) * 100);
}

// 分段条：每个小时 > 0 的项目一段，宽度 = 小时 / max(上限, 合计)，颜色按它在表格里的行号取。
export function stackedSegments(rows, limit) {
  const list = rows || [];
  const denom = Math.max(Number(limit) || 0, sumHours(list)) || 1;
  const segments = [];
  list.forEach((row, index) => {
    const hours = validHours(row?.hours);
    if (hours <= 0) return;
    segments.push({
      key: row.key || row.monthly_entry_id || row.project || String(index),
      index,
      code: row.project_code || row.project || '',
      name: row.project_name || '',
      hours,
      days: daysOfHours(hours),
      color: projectColor(index),
      width: Math.round((hours / denom) * 10000) / 100,
      pct: sharePercent(hours, limit),
    });
  });
  return segments;
}

// 「还差 5 小时（约 0.63 天）」（琥珀）/「已分配满 ✓」（绿）/「超出上限 X 小时…」（红）
export function remainingMeta(used, limit) {
  const status = deriveStatus(used, limit);
  const hours = remainingHours(used, limit);
  if (status === 'over') {
    return { tone: 'bad', days: 0, hours: 0, text: `超出上限 ${fmtHours(round2(used) - round2(limit))} 小时，最多 ${fmtHours(limit)} 小时，请调整后再保存` };
  }
  if (status === 'full') return { tone: 'ok', days: 0, hours: 0, text: '已分配满 ✓' };
  const days = daysOfHours(hours);
  return { tone: 'warn', days, hours, text: `还差 ${fmtHours(hours)} 小时（约 ${fmtDaysExact(days)} 天）` };
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
