// 研发费用导入页的纯逻辑：合计与占比、重复凭证行、筛选 / 排序 / 按凭证分组、提醒确认键、检查状态条。
// 校验本身仍在页面里（rowValidationErrors）；这里只负责把校验结果、提醒、新科目整理成页面要显示的东西。
const LEVELS = ['account_level_1', 'account_level_2', 'account_level_3', 'account_level_4'];

function text(value) {
  return String(value ?? '').trim();
}

export function amountOf(row) {
  const raw = text(row?.amount);
  if (!raw) return 0;
  const value = Number(raw);
  return Number.isFinite(value) ? value : 0;
}

export function isProjectRow(row) {
  return row?.allocation_type === 'project';
}

// 境外 = 二级科目“委托研发”下的三级科目“境外”
export const FOREIGN_LEVEL_2 = '委托研发';
export const FOREIGN_LEVEL_3 = '境外';

export function isForeignRow(row) {
  return text(row?.account_level_2) === FOREIGN_LEVEL_2 && text(row?.account_level_3) === FOREIGN_LEVEL_3;
}

// 合计、公共、项目，以及占比（百分数，保留 1 位小数的数字；合计为 0 时占比为 0）
export function expenseTotals(rows = []) {
  let total = 0;
  let project = 0;
  (rows || []).forEach((row) => {
    const amount = amountOf(row);
    total += amount;
    if (isProjectRow(row)) project += amount;
  });
  const common = total - project;
  const share = (part) => (total ? Math.round((part / total) * 1000) / 10 : 0);
  return { total, common, project, commonShare: share(common), projectShare: share(project) };
}

// 一级到四级科目拼成一个键
export function accountPathKey(row) {
  return LEVELS.map((field) => text(row?.[field])).join('\u001f');
}

// “完全相同”的内容键：凭证号、一至四级科目、金额、所属项目。凭证号为空的行没有键（不参与重复检查）。
// 同时也是“确认无误”的键：按内容而不是按行号，增删行后不会指到别的行上。
export function expenseRowKey(row) {
  const voucher = text(row?.voucher_no);
  if (!voucher) return '';
  const project = isProjectRow(row) ? text(row?.direct_project) : '';
  return `${voucher}\u0002${accountPathKey(row)}\u0002${amountOf(row).toFixed(2)}\u0002${project}`;
}

// 疑似重复的行：凭证号、一至四级科目、金额和所属项目都一样。凭证号为空的行不参与（没有可比对的凭证）。
// 只用来提醒，不拦保存：同一个项目买同一样东西好几次是演示员工152的。
// 返回 { groups: [[行下标…]…], keys: [组的内容键…]（与 groups 一一对应）, indexes: Map<行下标, 同组其他行的下标[]> }
export function duplicateVoucherRows(rows = []) {
  const buckets = new Map();
  (rows || []).forEach((row, index) => {
    const key = expenseRowKey(row);
    if (!key) return;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(index);
  });
  const groups = [];
  const keys = [];
  buckets.forEach((list, key) => {
    if (list.length > 1) {
      groups.push(list);
      keys.push(key);
    }
  });
  const indexes = new Map();
  groups.forEach((list) => list.forEach((index) => indexes.set(index, list.filter((other) => other !== index))));
  return { groups, keys, indexes };
}

// 已确认无误的提醒键集合：只留下仍然存在的组；没有变化时原样返回（避免触发多余的更新）
export function pruneAcks(acked, liveKeys = []) {
  const live = new Set(liveKeys);
  let changed = false;
  const next = new Set();
  acked.forEach((key) => {
    if (live.has(key)) next.add(key);
    else changed = true;
  });
  return changed ? next : acked;
}

// 校验信息形如“第 3 行：费用金额必须是有效数字”，第二行显示在该行下面时不再带行号
export function stripLinePrefix(message) {
  return String(message ?? '').replace(/^第\s*\d+\s*行[：:]\s*/, '');
}

// 从（已去掉行号的）校验信息里看出哪几个格子有问题，用来给对应的输入框标红
export function errorFields(messages = []) {
  const list = (messages || []).map((message) => String(message ?? ''));
  const levels = [];
  list.forEach((message) => {
    const hit = /([1-4])级费用科目/.exec(message);
    if (hit && !levels.includes(Number(hit[1]))) levels.push(Number(hit[1]));
  });
  return {
    amount: list.some((message) => message.includes('费用金额')),
    project: list.some((message) => message.includes('所属项目')),
    levels,
  };
}

function withThousands(fixed) {
  const [integer, decimal] = fixed.split('.');
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (decimal ? `.${decimal}` : '');
}

// 搜索用的文本：凭证号、各级科目、项目（编号 + 名称，由页面传入）、金额（原文、两位小数、带千分位）
export function rowSearchText(row, projectText = '') {
  const raw = text(row?.amount);
  const amountTexts = [];
  if (raw) {
    const fixed = amountOf(row).toFixed(2);
    amountTexts.push(raw, fixed, withThousands(fixed));
  }
  return [row?.voucher_no, ...LEVELS.map((field) => row?.[field]), projectText, ...amountTexts].map(text).join(' ').toLowerCase();
}

// entries: [{ row, index, problems: string[] }]；kind: all | common | project | bad
export function filterExpenseRows(entries = [], { kind = 'all', query = '' } = {}) {
  const needle = text(query).toLowerCase();
  return entries.filter((entry) => {
    if (kind === 'common' && isProjectRow(entry.row)) return false;
    if (kind === 'project' && !isProjectRow(entry.row)) return false;
    if (kind === 'bad' && !(entry.problems || []).length) return false;
    return !needle || rowSearchText(entry.row, entry.projectText).includes(needle);
  });
}

export function expenseFilterCounts(entries = []) {
  return {
    all: entries.length,
    common: entries.filter((entry) => !isProjectRow(entry.row)).length,
    project: entries.filter((entry) => isProjectRow(entry.row)).length,
    bad: entries.filter((entry) => (entry.problems || []).length).length,
  };
}

// ---- 工具栏：筛选 / 排序 / 分组 ----------------------------------------------------------
// entries: [{ row, index, errors: string[], notice: {…}|null, isNew: boolean, projectText: string }]
export const STATUS_FILTERS = [
  { value: 'bad', label: '有问题' },
  { value: 'notice', label: '有提醒' },
  { value: 'new', label: '新科目' },
  { value: 'foreign', label: '境外' },
];

export const SORT_OPTIONS = [
  { value: 'line', label: '行号' },
  { value: 'amount_desc', label: '金额 高→低' },
  { value: 'amount_asc', label: '金额 低→高' },
  { value: 'voucher', label: '凭证号' },
];

export function emptyFilters() {
  return { query: '', scope: 'all', account2: '', project: '', status: '' };
}

function statusMatches(entry, status) {
  if (status === 'bad') return (entry.errors || []).length > 0;
  if (status === 'notice') return Boolean(entry.notice);
  if (status === 'new') return Boolean(entry.isNew);
  if (status === 'foreign') return isForeignRow(entry.row);
  return true;
}

export function filterExpenseEntries(entries = [], filters = {}) {
  const { query = '', scope = 'all', account2 = '', project = '', status = '' } = filters || {};
  const needle = text(query).toLowerCase();
  return entries.filter((entry) => {
    const row = entry.row;
    if (scope === 'common' && isProjectRow(row)) return false;
    if (scope === 'project' && !isProjectRow(row)) return false;
    if (account2 && text(row?.account_level_2) !== account2) return false;
    if (project && !(isProjectRow(row) && text(row?.direct_project) === project)) return false;
    if (status && !statusMatches(entry, status)) return false;
    return !needle || rowSearchText(row, entry.projectText).includes(needle);
  });
}

// 归属分段上的数字、状态下拉里的数字（都按全部行算，不受当前筛选影响）
export function scopeCounts(entries = []) {
  return {
    all: entries.length,
    common: entries.filter((entry) => !isProjectRow(entry.row)).length,
    project: entries.filter((entry) => isProjectRow(entry.row)).length,
  };
}

export function statusCounts(entries = []) {
  return {
    bad: entries.filter((entry) => statusMatches(entry, 'bad')).length,
    notice: entries.filter((entry) => statusMatches(entry, 'notice')).length,
    new: entries.filter((entry) => statusMatches(entry, 'new')).length,
    foreign: entries.filter((entry) => statusMatches(entry, 'foreign')).length,
  };
}

// 下拉里的选项：当前表里出现过的二级科目、项目（按首次出现的顺序）
export function account2Options(entries = []) {
  const seen = new Set();
  const result = [];
  entries.forEach((entry) => {
    const value = text(entry.row?.account_level_2);
    if (value && !seen.has(value)) {
      seen.add(value);
      result.push(value);
    }
  });
  return result;
}

export function projectFilterOptions(entries = [], labelOf = (value) => value) {
  const seen = new Set();
  const result = [];
  entries.forEach((entry) => {
    if (!isProjectRow(entry.row)) return;
    const value = text(entry.row?.direct_project);
    if (value && !seen.has(value)) {
      seen.add(value);
      result.push({ value, label: labelOf(value) });
    }
  });
  return result;
}

function compareVoucher(a, b) {
  const va = text(a.row?.voucher_no);
  const vb = text(b.row?.voucher_no);
  if (!va && !vb) return a.index - b.index;
  if (!va) return 1;
  if (!vb) return -1;
  return va.localeCompare(vb, 'zh-CN', { numeric: true }) || a.index - b.index;
}

// 排序不改原数组；相同时按原行号
export function sortExpenseEntries(entries = [], sort = 'line') {
  const list = [...entries];
  if (sort === 'amount_desc') return list.sort((a, b) => amountOf(b.row) - amountOf(a.row) || a.index - b.index);
  if (sort === 'amount_asc') return list.sort((a, b) => amountOf(a.row) - amountOf(b.row) || a.index - b.index);
  if (sort === 'voucher') return list.sort(compareVoucher);
  return list.sort((a, b) => a.index - b.index);
}

// 点列标题排序：金额 高→低 → 低→高 → 行号；凭证号 升序 → 行号
export function nextSort(current, column) {
  if (column === 'amount') {
    if (current === 'amount_desc') return 'amount_asc';
    if (current === 'amount_asc') return 'line';
    return 'amount_desc';
  }
  if (column === 'voucher') return current === 'voucher' ? 'line' : 'voucher';
  return 'line';
}

export function sortIndicator(sort, column) {
  if (column === 'amount') return sort === 'amount_desc' ? '↓' : sort === 'amount_asc' ? '↑' : '';
  if (column === 'voucher') return sort === 'voucher' ? '↑' : '';
  return '';
}

export function ariaSort(sort, column) {
  if (column === 'amount') return sort === 'amount_desc' ? 'descending' : sort === 'amount_asc' ? 'ascending' : 'none';
  if (column === 'voucher') return sort === 'voucher' ? 'ascending' : 'none';
  return 'none';
}

export const NO_VOUCHER_LABEL = '（无凭证号）';

// 按凭证号分组：组按第一次出现的顺序，组内保持传入的顺序；没有凭证号的行进“（无凭证号）”组。
// keyOf 可以换成固定下来的分组依据（编辑凭证号时行不会在组之间跳来跳去）。
export function groupByVoucher(entries = [], keyOf = (entry) => text(entry.row?.voucher_no)) {
  const groups = new Map();
  entries.forEach((entry) => {
    const key = text(keyOf(entry));
    if (!groups.has(key)) groups.set(key, { key, label: key || NO_VOUCHER_LABEL, count: 0, subtotal: 0, entries: [] });
    const group = groups.get(key);
    group.count += 1;
    group.subtotal += amountOf(entry.row);
    group.entries.push(entry);
  });
  return [...groups.values()];
}

export function groupTitle(group) {
  return group.key ? `凭证 ${group.key}` : NO_VOUCHER_LABEL;
}

// 页面渲染用的一维列表：分组时先放一个组标题，再放组内的行
export function buildDisplayRows(entries = [], { group = false, keyOf } = {}) {
  const rowItem = (entry) => ({ type: 'row', key: `r${entry.index}`, row: entry.row, index: entry.index, entry });
  if (!group) return entries.map(rowItem);
  return groupByVoucher(entries, keyOf).flatMap((g) => [
    { type: 'group', key: `g:${g.key}`, group: g },
    ...g.entries.map(rowItem),
  ]);
}

export function sumAmounts(entries = []) {
  return entries.reduce((sum, entry) => sum + amountOf(entry.row), 0);
}

// 已启用的筛选条件，做成可以逐个清除的小标签
export function activeFilterChips(filters = {}, { projectLabel = (value) => value } = {}) {
  const chips = [];
  const query = text(filters.query);
  if (query) chips.push({ key: 'query', label: `搜索：${query}` });
  if (filters.scope && filters.scope !== 'all') chips.push({ key: 'scope', label: `归属：${filters.scope === 'project' ? '项目' : '公共'}` });
  if (filters.account2) chips.push({ key: 'account2', label: `二级科目：${filters.account2}` });
  if (filters.project) chips.push({ key: 'project', label: `项目：${projectLabel(filters.project)}` });
  if (filters.status) {
    const status = STATUS_FILTERS.find((item) => item.value === filters.status);
    chips.push({ key: 'status', label: `状态：${status ? status.label : filters.status}` });
  }
  return chips;
}

// ---- 检查状态条与保存按钮 ------------------------------------------------------------------
// errorRows: 有校验错误的行数；newCount: 目录里没有的新科目个数；newConfirmed: 已勾选“我已核对”；
// noticePending / noticeAcked: 还没确认 / 已确认无误的“完全相同的行”组数。
// 红：有错误（不能保存）；黄：只剩新科目待确认（不能保存）或只剩提醒（可以保存）；绿：全部通过。
export function computeStripState({ errorRows = 0, newCount = 0, newConfirmed = false, noticePending = 0, noticeAcked = 0 } = {}) {
  const newPending = newCount > 0 && !newConfirmed;
  const parts = [];
  if (errorRows) parts.push(`${errorRows} 个问题`);
  if (newPending) parts.push(`${newCount} 个新科目待确认`);
  else if (newCount) parts.push(`${newCount} 个新科目已确认`);
  if (noticePending) parts.push(`${noticePending} 条提醒`);

  if (errorRows) return { tone: 'bad', title: '有问题，暂时不能保存', summary: parts.join(' · '), hasList: true };
  if (newPending) return { tone: 'warn', title: '确认新科目后才能保存', summary: parts.join(' · '), hasList: true };
  if (noticePending) return { tone: 'warn', title: '有提醒，不影响保存', summary: parts.join(' · '), hasList: true };
  const summary = [
    '金额、归属、项目都已填写',
    newCount ? '新科目已确认' : '科目都在目录里',
    noticeAcked ? '提醒已确认' : '没有完全相同的行',
  ].join(' · ');
  return { tone: 'ok', title: '检查通过', summary, hasList: false };
}

// 保存按钮被禁用的原因（空字符串 = 可以保存），同时当作按钮的提示文字
export function saveBlockReason({ isYear = false, loading = false, catalogReady = true, saving = false, errorRows = 0, newPending = false } = {}) {
  if (isYear) return '年度视图只读，请切回月度再保存';
  if (loading) return '数据加载中，请稍候';
  if (!catalogReady) return '费用科目目录还没加载好';
  if (saving) return '正在保存…';
  if (errorRows > 0) return `还有 ${errorRows} 行有问题，处理后才能保存`;
  if (newPending) return '请先确认新科目（在“处理清单”里勾选“我已核对”）';
  return '';
}
