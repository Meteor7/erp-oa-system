import { EXPENSE_ACCOUNT_PATHS, unknownExpenseAccountPaths, validateExpenseAccount } from './expenseAccounts.js';

function clean(value) {
  return String(value ?? '').trim();
}

function aliasKey(value) {
  return clean(value)
    .replace(/[\s_\-:：|｜()（）]/g, '')
    .toLowerCase();
}

function splitLooseWhitespace(text) {
  return clean(text).split(/\s+/).map(clean).filter(Boolean);
}

function splitWideSpaces(cells) {
  return cells.flatMap((cell) => clean(cell).split(/\s{2,}/).map(clean).filter(Boolean));
}

function splitLine(line) {
  const text = String(line ?? '');
  let cells;
  if (text.includes('\t')) {
    cells = text.split('\t').map(clean);
  } else if (/[,，]/.test(text)) {
    cells = text.split(/[,，]/).map(clean);
  } else {
    cells = [clean(text)];
  }

  if (cells.length >= 6) return cells;

  const wideSpaceCells = splitWideSpaces(cells);
  if (wideSpaceCells.length >= 6) return wideSpaceCells;

  const looseCells = splitLooseWhitespace(text);
  return looseCells.length >= 6 ? looseCells : cells;
}

const HEADER_ALIASES = {
  voucher_no: ['凭证号', '凭证', 'voucher_no', 'voucher'],
  account_level_1: ['1级费用科目', '一级费用科目', '1级科目', '一级科目', 'account_level_1'],
  account_level_2: ['2级费用科目', '二级费用科目', '2级科目', '二级科目', 'account_level_2'],
  account_level_3: ['3级费用科目', '三级费用科目', '3级科目', '三级科目', '费用项', 'account_level_3'],
  account_level_4: ['4级费用科目', '四级费用科目', '4级科目', '四级科目', 'account_level_4'],
  amount: ['费用金额', '金额', 'amount'],
  project_text: ['项目', '所属项目', '归属项目', 'project'],
};

const REQUIRED_HEADERS = ['account_level_1', 'account_level_2', 'account_level_3', 'amount'];

function headerField(value) {
  const key = aliasKey(value);
  return Object.entries(HEADER_ALIASES).find(([, aliases]) => aliases.some((alias) => aliasKey(alias) === key))?.[0] || '';
}

function headerMap(cells) {
  const map = {};
  cells.forEach((cell, index) => {
    const field = headerField(cell);
    if (field && map[field] === undefined) map[field] = index;
  });
  return REQUIRED_HEADERS.every((field) => map[field] !== undefined) ? map : null;
}

function rowFromHeader(cells, map) {
  const pick = (field) => (map[field] === undefined ? '' : clean(cells[map[field]]));
  return {
    voucher_no: pick('voucher_no'),
    account_level_1: pick('account_level_1'),
    account_level_2: pick('account_level_2'),
    account_level_3: pick('account_level_3'),
    account_level_4: pick('account_level_4'),
    amount: pick('amount'),
    project_text: pick('project_text') || '公共费用',
  };
}

function rowFromPosition(cells) {
  const values = cells.map(clean);
  if (values.length >= 7) {
    return {
      voucher_no: values[0],
      account_level_1: values[1],
      account_level_2: values[2],
      account_level_3: values[3],
      account_level_4: values[4],
      amount: values[5],
      project_text: values[6] || '公共费用',
    };
  }
  if (values.length >= 6) {
    return {
      voucher_no: '',
      account_level_1: values[0],
      account_level_2: values[1],
      account_level_3: values[2],
      account_level_4: values[3],
      amount: values[4],
      project_text: values[5] || '公共费用',
    };
  }
  return {
    voucher_no: '',
    account_level_1: values[0] || '',
    account_level_2: values[1] || '',
    account_level_3: values[2] || '',
    account_level_4: '',
    amount: values[3] || '',
    project_text: values[4] || '公共费用',
  };
}

function normalizedProjectKey(value) {
  return aliasKey(value).replace(/[|｜]/g, '');
}

function projectValues(project) {
  const code = project?.rd_project_code || project?.project_code || project?.name || '';
  const name = project?.project_name || '';
  return [
    project?.name,
    project?.rd_project_code,
    project?.project_code,
    project?.project_name,
    code && name ? code + '|' + name : '',
    code && name ? code + ' | ' + name : '',
  ].filter(Boolean);
}

function findProject(value, projects = []) {
  const text = clean(value);
  if (!text) return '';
  const candidates = [text, text.split('|')[0], text.split('｜')[0]].map(normalizedProjectKey).filter(Boolean);
  for (const project of projects) {
    const values = projectValues(project).map(normalizedProjectKey);
    if (candidates.some((candidate) => values.includes(candidate))) return project.name || '';
  }
  return '';
}

function isCommonProject(value) {
  const key = aliasKey(value || '公共费用');
  return !key || ['公共费用', '公共', 'common', '公摊'].some((label) => aliasKey(label) === key);
}

export function resolveProjectValue(value, projects = []) {
  const text = clean(value) || '公共费用';
  if (isCommonProject(text)) {
    return { allocation_type: 'common', direct_project: '', project_text: text };
  }
  const directProject = findProject(text, projects);
  if (!directProject) {
    return { allocation_type: 'project', direct_project: '', project_text: text, error: '项目“' + text + '”未匹配到有效项目' };
  }
  return { allocation_type: 'project', direct_project: directProject, project_text: text };
}

export function deriveExpenseCategory(row = {}) {
  const text = [row.account_level_2, row.account_level_3, row.account_level_4].map(clean).join(' ');
  if (/人员人工|人工|工资|社保|社会保险|养老保险|医疗保险|生育保险|工伤保险|失业保险|住房公积金/.test(text)) return 'personnel';
  if (/直接投入/.test(text)) return 'direct_input';
  if (/折旧/.test(text)) return 'depreciation';
  if (/摊销|无形资产/.test(text)) return 'amortization';
  if (/设计/.test(text)) return 'design';
  return 'other';
}

function expenseRowIdentity(row = {}) {
  const amount = Number(row.amount);
  const amountKey = Number.isFinite(amount) ? amount.toFixed(2) : clean(row.amount);
  return [
    row.voucher_no,
    row.account_level_1,
    row.account_level_2,
    row.account_level_3,
    row.account_level_4,
    amountKey,
    row.direct_project,
  ].map(clean).join('|');
}

export function filterNewExpenseRows(existingRows = [], incomingRows = []) {
  const existingKeys = new Set(existingRows.map(expenseRowIdentity));
  const rows = incomingRows.filter((row) => !existingKeys.has(expenseRowIdentity(row)));
  return { rows, skipped: incomingRows.length - rows.length };
}
function parseAmount(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const cleaned = clean(value).replace(/[￥¥,，\s]/g, '');
  if (!cleaned || /^#+$/.test(cleaned)) return null;
  const amount = Number(cleaned);
  return Number.isFinite(amount) ? amount : null;
}

function normalizeRawRow(rawRow, projects, lineNo, accountPaths) {
  const amount = parseAmount(rawRow.amount);
  const row = {
    voucher_no: clean(rawRow.voucher_no),
    account_level_1: clean(rawRow.account_level_1),
    account_level_2: clean(rawRow.account_level_2),
    account_level_3: clean(rawRow.account_level_3),
    account_level_4: clean(rawRow.account_level_4),
    project_text: clean(rawRow.project_text) || '公共费用',
    amount,
  };
  row.category = deriveExpenseCategory(row);

  const rowErrors = [];
  rowErrors.push(...validateExpenseAccount(row, lineNo, accountPaths, true));
  if (amount === null) rowErrors.push('第 ' + lineNo + ' 行：费用金额必须是有效数字');

  const project = resolveProjectValue(row.project_text, projects);
  if (project.error) rowErrors.push('第 ' + lineNo + ' 行：' + project.error);

  return {
    row: {
      ...row,
      amount,
      allocation_type: project.allocation_type,
      direct_project: project.direct_project,
      project_text: project.project_text,
    },
    errors: rowErrors,
  };
}

// 表头识别：认得出（含必填的 1-3 级科目和费用金额）就返回列位置表，否则 null。模板的表头行也走这里。
export function detectExpenseHeader(cells = []) {
  return headerMap(Array.from(cells || []).map(clean));
}

// 返回 { rows, errors }：有任何错误时 rows 为空（整份不导入）。
// 另外给导入预览用：validRows = 没有问题的行；dataRows = 读到的数据行总数；badRows = 有问题的行数。
export function parseExpenseTableRows(tableRows, projects = [], accountPaths = EXPENSE_ACCOUNT_PATHS) {
  const rows = [];
  const errors = [];
  let dataRows = 0;
  let badRows = 0;
  let map = null;
  let seenContentRow = false;

  tableRows.forEach((inputRow, index) => {
    const cells = Array.from(inputRow || []).map(clean);
    if (!cells.some(Boolean)) return;

    const possibleHeader = headerMap(cells);
    if (!seenContentRow && possibleHeader) {
      map = possibleHeader;
      return;
    }

    seenContentRow = true;
    dataRows += 1;
    const lineNo = index + 1;
    const rawRow = map ? rowFromHeader(cells, map) : rowFromPosition(cells);
    const result = normalizeRawRow(rawRow, projects, lineNo, accountPaths);
    if (result.errors.length) {
      errors.push(...result.errors);
      badRows += 1;
      return;
    }
    rows.push(result.row);
  });

  return { rows: errors.length ? [] : rows, errors, validRows: rows, dataRows, badRows };
}

// ---- Excel 导入预览 ---------------------------------------------------------------------
// parsed: parseExpenseTableRows / importWorkbookFile 的结果；existingRows: 页面里现有的明细。
// replace=true 覆盖：现有明细会被清空；false 追加：和现有明细完全相同的行会被跳过。
// 有问题的行（badRows > 0）时整份演示员工177能导入，blocked = true。
export function summarizeExpenseImport(parsed = {}, { existingRows = [], replace = false, accountPaths = EXPENSE_ACCOUNT_PATHS } = {}) {
  const validRows = Array.isArray(parsed.validRows) ? parsed.validRows : (Array.isArray(parsed.rows) ? parsed.rows : []);
  const errors = Array.isArray(parsed.errors) ? parsed.errors : [];
  const badRows = Number.isFinite(parsed.badRows) ? parsed.badRows : (errors.length ? errors.length : 0);
  const dataRows = Number.isFinite(parsed.dataRows) ? parsed.dataRows : validRows.length + badRows;
  let addRows = validRows;
  let skipped = 0;
  if (!replace) {
    const filtered = filterNewExpenseRows(existingRows, validRows);
    addRows = filtered.rows;
    skipped = filtered.skipped;
  }
  const total = addRows.reduce((sum, row) => sum + (Number.isFinite(Number(row.amount)) ? Number(row.amount) : 0), 0);
  return {
    replace,
    dataRows,
    badRows,
    errors,
    addRows,
    addCount: addRows.length,
    skipped,
    total: Math.round(total * 100) / 100,
    newAccountCount: unknownExpenseAccountPaths(addRows, accountPaths).length,
    existingCount: replace ? existingRows.length : 0,
    blocked: badRows > 0 || errors.length > 0 || addRows.length === 0,
  };
}

// ---- Excel 模板 --------------------------------------------------------------------------
// 表头就是 HEADER_ALIASES 里每个字段的第一个写法，所以一定能被上面的 detectExpenseHeader 认出来。
export const EXPENSE_TEMPLATE_HEADERS = ['凭证号', '1级费用科目', '2级费用科目', '3级费用科目', '4级费用科目', '费用金额', '项目'];

// 示例行全是占位内容：凭证号带“示例”，第二行项目故意写成不存在的 RDxx。不改就上传的话，导入预览会把它挡住。
const EXPENSE_TEMPLATE_EXAMPLES = [
  ['示例001', '研发支出', '直接投入费用', '研发材料', '', 1000, '公共费用'],
  ['示例002', '研发支出', '其他相关费用', '职工福利费', '节日福利', 500, 'RDxx'],
];

// 返回两演示员工17作表（交给 exportSheetsWorkbook）：第一张是 importWorkbookFile 会读的“费用明细”，第二张是“填写说明”。
export function buildExpenseTemplateSheets(accountPaths = EXPENSE_ACCOUNT_PATHS) {
  const level2 = [...new Set(accountPaths.map((path) => clean(path.account_level_2)).filter(Boolean))];
  const guide = [
    ['列名', '是否必填', '怎么填'],
    ['凭证号', '选填', '财务凭证号，可以留空。页面里用它按凭证号分组、提醒重复录入。'],
    ['1级费用科目', '必填', '固定填“研发支出”。'],
    ['2级费用科目', '必填', '必须是固定分类之一：' + level2.join('、') + '。'],
    ['3级费用科目', '必填', '具体费用项，如“研发材料”“差旅费”。科目目录里还没有的，导入后会标为“新科目”，确认后保存时创建。'],
    ['4级费用科目', '选填', '只有部分三级科目有四级（如“职工福利费”下的“节日福利”）；没有就留空。'],
    ['费用金额', '必填', '数字，冲销可以填负数；不要带单位或文字。'],
    ['项目', '选填', '留空或填“公共费用”：公共费用，按工时比例分摊。填项目编号（如 RD16）或“编号|项目名称”：项目费用，直接归属该项目。项目必须是系统里已有、未取消的项目。'],
    [],
    ['导入方式', '', '“追加到现有费用”：把表里的行加到页面下面，和页面已有明细完全相同的行会跳过。“覆盖现有费用”：确认后先清空页面里现有的明细，再放入表里的内容。两种方式都会先给出预览，确认后才生效。'],
    ['注意', '', '1. 表头放在“费用明细”工作表的第一行，列的顺序可以调整，但表头名称不要改。 2. 示例行的凭证号、金额、项目都是占位内容，导入前请删除或改成真实数据。 3. 只要有一行有问题，整份文件演示员工177会导入，请先改好。 4. 导入后还需要在页面上点“保存本月费用”才会真正保存。'],
  ];
  return [
    { name: '费用明细', rows: [EXPENSE_TEMPLATE_HEADERS, ...EXPENSE_TEMPLATE_EXAMPLES], widths: [12, 14, 16, 36, 20, 14, 18] },
    { name: '填写说明', rows: guide, widths: [14, 10, 110] },
  ];
}

export function parseExpensePaste(text, projects = [], accountPaths = EXPENSE_ACCOUNT_PATHS) {
  const lines = String(text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const tableRows = lines.map(splitLine);
  return parseExpenseTableRows(tableRows, projects, accountPaths);
}

export async function importWorkbookFile(file, projects = [], accountPaths = EXPENSE_ACCOUNT_PATHS) {
  const XLSX = await import('xlsx');
  const data = await file.arrayBuffer();
  const workbook = XLSX.read(data, { type: 'array' });
  const firstSheetName = workbook.SheetNames[0];
  if (!firstSheetName) return { rows: [], errors: ['Excel 文件没有工作表'] };
  const worksheet = workbook.Sheets[firstSheetName];
  const tableRows = XLSX.utils.sheet_to_json(worksheet, { header: 1, defval: '' });
  return parseExpenseTableRows(tableRows, projects, accountPaths);
}
