import { validateExpenseAccount } from './expenseAccounts.js';

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

function parseAmount(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const cleaned = clean(value).replace(/[￥¥,，\s]/g, '');
  if (!cleaned || /^#+$/.test(cleaned)) return null;
  const amount = Number(cleaned);
  return Number.isFinite(amount) ? amount : null;
}

function normalizeRawRow(rawRow, projects, lineNo) {
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
  rowErrors.push(...validateExpenseAccount(row, lineNo));
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

export function parseExpenseTableRows(tableRows, projects = []) {
  const rows = [];
  const errors = [];
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
    const lineNo = index + 1;
    const rawRow = map ? rowFromHeader(cells, map) : rowFromPosition(cells);
    const result = normalizeRawRow(rawRow, projects, lineNo);
    if (result.errors.length) {
      errors.push(...result.errors);
      return;
    }
    rows.push(result.row);
  });

  return { rows: errors.length ? [] : rows, errors };
}

export function parseExpensePaste(text, projects = []) {
  const lines = String(text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const tableRows = lines.map(splitLine);
  return parseExpenseTableRows(tableRows, projects);
}

export async function importWorkbookFile(file, projects = []) {
  const XLSX = await import('xlsx');
  const data = await file.arrayBuffer();
  const workbook = XLSX.read(data, { type: 'array' });
  const firstSheetName = workbook.SheetNames[0];
  if (!firstSheetName) return { rows: [], errors: ['Excel 文件没有工作表'] };
  const worksheet = workbook.Sheets[firstSheetName];
  const tableRows = XLSX.utils.sheet_to_json(worksheet, { header: 1, defval: '' });
  return parseExpenseTableRows(tableRows, projects);
}
