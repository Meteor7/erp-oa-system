import assert from 'node:assert/strict';
import test from 'node:test';

import * as expensePaste from '../src/lib/expensePaste.js';

const { parseExpensePaste, parseExpenseTableRows } = expensePaste;

const projects = [
  { name: 'PROJ-0001', rd_project_code: 'RD16', project_name: 'EFEM-8-2LP-EG-A' },
  { name: 'PROJ-0002', rd_project_code: 'RD17', project_name: 'Test project' },
];

test('parses four-level expense rows with optional header', () => {
  const pasted = [
    '凭证号\t1级费用科目\t2级费用科目\t3级费用科目\t4级费用科目\t费用金额\t项目',
    '2\t研发支出\t直接投入费用\t仪器、设备的运行维护、调整、检验、维修等费用\t\t7477.88\t公共费用',
    '3\t研发支出\t其他相关费用\t职工福利费\t节日福利\t2389.93\tRD16',
  ].join('\n');

  const result = parseExpensePaste(pasted, projects);

  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.rows, [
    {
      voucher_no: '2',
      account_level_1: '研发支出',
      account_level_2: '直接投入费用',
      account_level_3: '仪器、设备的运行维护、调整、检验、维修等费用',
      account_level_4: '',
      category: 'direct_input',
      allocation_type: 'common',
      direct_project: '',
      project_text: '公共费用',
      amount: 7477.88,
    },
    {
      voucher_no: '3',
      account_level_1: '研发支出',
      account_level_2: '其他相关费用',
      account_level_3: '职工福利费',
      account_level_4: '节日福利',
      category: 'other',
      allocation_type: 'project',
      direct_project: 'PROJ-0001',
      project_text: 'RD16',
      amount: 2389.93,
    },
  ]);
});

test('parses Excel workbook matrix rows without a voucher column', () => {
  const result = parseExpenseTableRows([
    ['1级费用科目', '2级费用科目', '3级费用科目', '4级费用科目', '费用金额', '项目'],
    ['研发支出', '其他相关费用', '差旅费', '', 3508.4, '公共费用'],
  ], projects);

  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.rows, [
    {
      voucher_no: '',
      account_level_1: '研发支出',
      account_level_2: '其他相关费用',
      account_level_3: '差旅费',
      account_level_4: '',
      category: 'other',
      allocation_type: 'common',
      direct_project: '',
      project_text: '公共费用',
      amount: 3508.4,
    },
  ]);
});

test('accepts negative expense amounts from pasted or workbook rows', () => {
  const result = parseExpenseTableRows([
    ['1\u7ea7\u8d39\u7528\u79d1\u76ee', '2\u7ea7\u8d39\u7528\u79d1\u76ee', '3\u7ea7\u8d39\u7528\u79d1\u76ee', '4\u7ea7\u8d39\u7528\u79d1\u76ee', '\u8d39\u7528\u91d1\u989d', '\u9879\u76ee'],
    ['\u7814\u53d1\u652f\u51fa', '\u5176\u4ed6\u76f8\u5173\u8d39\u7528', '\u5dee\u65c5\u8d39', '', -125.50, '\u516c\u5171\u8d39\u7528'],
  ], projects);

  assert.deepEqual(result.errors, []);
  assert.equal(result.rows[0].amount, -125.50);
});

test('reports invalid four-level expense rows before import', () => {
  const pasted = [
    '研发支出\t其他相关费用\t差旅费\t\t########\t公共费用',
    '研发支出\t人员人工费用\t社会保险费用（单位）\t\t100\tRD404',
  ].join('\n');

  const result = parseExpensePaste(pasted, projects);

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /第 1 行：费用金额必须是有效数字/);
  assert.match(result.errors.join('\n'), /第 2 行：项目“RD404”未匹配到有效项目/);
});

test('reports expense account hierarchy mismatches before import', () => {
  const pasted = [
    '研发支出\t人员人工费用\t住房公积金（单位）\t养老保险\t100\t公共费用',
    '研发支出\t其他相关费用\t职工福利费\t\t100\t公共费用',
  ].join('\n');

  const result = parseExpensePaste(pasted, projects);

  assert.deepEqual(result.errors, []);
  assert.equal(result.rows.length, 2);
});

test('skips rows already present while preserving repeated rows inside one new import', () => {
  const saved = {
    voucher_no: '60', account_level_1: 'R&D', account_level_2: 'Commissioned',
    account_level_3: 'Overseas', account_level_4: 'Sabri', amount: 100, direct_project: 'RD10',
  };
  const newRow = { ...saved, voucher_no: '61' };

  assert.equal(typeof expensePaste.filterNewExpenseRows, 'function');
  const appended = expensePaste.filterNewExpenseRows([saved], [saved, newRow]);
  assert.deepEqual(appended.rows, [newRow]);
  assert.equal(appended.skipped, 1);

  const originalDuplicates = expensePaste.filterNewExpenseRows([], [saved, { ...saved }]);
  assert.equal(originalDuplicates.rows.length, 2);
  assert.equal(originalDuplicates.skipped, 0);
});


test('the Excel template header row is recognised by the same header detection the importer uses', () => {
  const [detail, guide] = expensePaste.buildExpenseTemplateSheets();
  assert.equal(detail.name, '费用明细');
  assert.equal(guide.name, '填写说明');

  const header = detail.rows[0];
  assert.deepEqual(header, expensePaste.EXPENSE_TEMPLATE_HEADERS);
  const map = expensePaste.detectExpenseHeader(header);
  assert.ok(map, 'template header must be detected');
  for (const field of ['voucher_no', 'account_level_1', 'account_level_2', 'account_level_3', 'account_level_4', 'amount', 'project_text']) {
    assert.ok(map[field] !== undefined, field + ' column is mapped');
  }
  // the header row alone parses to an empty, error-free result
  const headerOnly = parseExpenseTableRows([header], projects);
  assert.deepEqual(headerOnly.errors, []);
  assert.deepEqual(headerOnly.rows, []);
  assert.equal(headerOnly.dataRows, 0);
  // a random row is not a header
  assert.equal(expensePaste.detectExpenseHeader(['研发支出', '其他相关费用', '差旅费', '', 100, '公共费用']), null);
});

test('template example rows are placeholders: the first parses, the second needs a real project', () => {
  const [detail, guide] = expensePaste.buildExpenseTemplateSheets();
  const [, first, second] = detail.rows;
  assert.match(String(first[0]), /示例/);
  assert.match(String(second[0]), /示例/);

  const parsed = parseExpenseTableRows(detail.rows, projects);
  assert.equal(parsed.dataRows, 2);
  assert.equal(parsed.validRows.length, 1);
  assert.equal(parsed.validRows[0].allocation_type, 'common');
  assert.equal(parsed.badRows, 1);
  assert.match(parsed.errors.join('\n'), /项目“RDxx”未匹配到有效项目/);
  assert.deepEqual(parsed.rows, []);

  // the second sheet explains every column and the attribution rule
  const guideText = guide.rows.map((row) => row.join(' ')).join('\n');
  for (const label of expensePaste.EXPENSE_TEMPLATE_HEADERS) assert.ok(guideText.includes(label), label);
  assert.ok(guideText.includes('公共费用'));
  assert.ok(guideText.includes('项目费用'));
});

test('import preview counts rows, total, problems and new accounts without touching the table', () => {
  const rows = [
    ['1级费用科目', '2级费用科目', '3级费用科目', '4级费用科目', '费用金额', '项目'],
    ['研发支出', '其他相关费用', '差旅费', '', 100.5, '公共费用'],
    ['研发支出', '其他相关费用', '年终一次性礼品', '', 20, 'RD16'],
  ];
  const good = parseExpenseTableRows(rows, projects);
  const existing = [{ voucher_no: '', account_level_1: '研发支出', account_level_2: '其他相关费用', account_level_3: '差旅费', account_level_4: '', amount: 100.5, direct_project: '' }];

  const replace = expensePaste.summarizeExpenseImport(good, { existingRows: existing, replace: true });
  assert.equal(replace.dataRows, 2);
  assert.equal(replace.addCount, 2);
  assert.equal(replace.total, 120.5);
  assert.equal(replace.badRows, 0);
  assert.equal(replace.newAccountCount, 1);
  assert.equal(replace.existingCount, 1);
  assert.equal(replace.blocked, false);

  const append = expensePaste.summarizeExpenseImport(good, { existingRows: existing, replace: false });
  assert.equal(append.skipped, 1);
  assert.equal(append.addCount, 1);
  assert.equal(append.total, 20);
  assert.equal(append.existingCount, 0);

  const bad = parseExpenseTableRows([...rows, ['研发支出', '其他相关费用', '差旅费', '', 'abc', '公共费用']], projects);
  const blocked = expensePaste.summarizeExpenseImport(bad, { existingRows: existing, replace: true });
  assert.equal(blocked.dataRows, 3);
  assert.equal(blocked.badRows, 1);
  assert.equal(blocked.errors.length, 1);
  assert.equal(blocked.blocked, true);

  const allDuplicates = expensePaste.summarizeExpenseImport(parseExpenseTableRows(rows.slice(0, 2), projects), { existingRows: existing, replace: false });
  assert.equal(allDuplicates.addCount, 0);
  assert.equal(allDuplicates.blocked, true);
});

test('accepts an unknown third-level account for confirmation when fixed levels are valid', () => {
  const result = parseExpensePaste('研发支出\t人员人工费用\t年终一次性奖金\t\t100\t公共费用', projects, []);
  assert.deepEqual(result.errors, []);
  assert.equal(result.rows[0].account_level_3, '年终一次性奖金');
});
