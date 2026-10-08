// 研发费用导入页的纯逻辑：合计与占比、重复凭证行、按归属/问题/搜索筛选。校验本身仍在页面里（rowValidationErrors）。
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

// 疑似重复的行：凭证号、一至四级科目、金额和所属项目都一样。凭证号为空的行不参与（没有可比对的凭证）。
// 只用来提醒，不拦保存：同一个项目买同一样东西好几次是正常的。
// 返回 { groups: [[行下标…]…], indexes: Map<行下标, 同组其他行的下标[]> }
export function duplicateVoucherRows(rows = []) {
  const buckets = new Map();
  (rows || []).forEach((row, index) => {
    const voucher = text(row?.voucher_no);
    if (!voucher) return;
    const project = isProjectRow(row) ? text(row?.direct_project) : '';
    const key = `${voucher}\u0002${accountPathKey(row)}\u0002${amountOf(row).toFixed(2)}\u0002${project}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(index);
  });
  const groups = [...buckets.values()].filter((list) => list.length > 1);
  const indexes = new Map();
  groups.forEach((list) => list.forEach((index) => indexes.set(index, list.filter((other) => other !== index))));
  return { groups, indexes };
}

// 校验信息形如“第 3 行：费用金额必须是有效数字”，第二行显示在该行下面时不再带行号
export function stripLinePrefix(message) {
  return String(message ?? '').replace(/^第\s*\d+\s*行[：:]\s*/, '');
}

export function rowSearchText(row) {
  return [row?.voucher_no, ...LEVELS.map((field) => row?.[field])].map(text).join(' ').toLowerCase();
}

// entries: [{ row, index, problems: string[] }]；kind: all | common | project | bad
export function filterExpenseRows(entries = [], { kind = 'all', query = '' } = {}) {
  const needle = text(query).toLowerCase();
  return entries.filter((entry) => {
    if (kind === 'common' && isProjectRow(entry.row)) return false;
    if (kind === 'project' && !isProjectRow(entry.row)) return false;
    if (kind === 'bad' && !(entry.problems || []).length) return false;
    return !needle || rowSearchText(entry.row).includes(needle);
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
