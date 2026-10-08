import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { accountPathKey, amountOf, duplicateVoucherRows, expenseFilterCounts, expenseTotals, filterExpenseRows, rowSearchText, stripLinePrefix } from '../src/lib/rdExpense.js';

const row = (voucher, l2, l3, l4, amount, type = 'common', project = '') => ({
  voucher_no: voucher, account_level_1: '研发支出', account_level_2: l2, account_level_3: l3, account_level_4: l4,
  amount, allocation_type: type, direct_project: project,
});

test('amountOf ignores blanks and non numbers', () => {
  assert.equal(amountOf({ amount: '12.5' }), 12.5);
  assert.equal(amountOf({ amount: -3 }), -3);
  assert.equal(amountOf({ amount: '' }), 0);
  assert.equal(amountOf({ amount: 'abc' }), 0);
  assert.equal(amountOf({}), 0);
});

test('expenseTotals splits common and project expenses with shares', () => {
  const t = expenseTotals([
    row('1', 'a', 'b', '', 600, 'common'),
    row('2', 'a', 'b', '', '300', 'project', 'RD1'),
    row('3', 'a', 'b', '', 100, 'project', 'RD2'),
    row('4', 'a', 'b', '', '', 'common'),
  ]);
  assert.deepEqual(t, { total: 1000, common: 600, project: 400, commonShare: 60, projectShare: 40 });
  assert.deepEqual(expenseTotals([]), { total: 0, common: 0, project: 0, commonShare: 0, projectShare: 0 });
});

test('duplicateVoucherRows only flags rows with the same voucher, account path, amount and project', () => {
  const rows = [
    row('V1', 'x', 'y', 'z', 100),
    row('V1', 'x', 'y', 'z', '100.00'),
    row('V1', 'x', 'y', 'z', 200),
    row('V1', 'x', 'y', 'z', 100, 'project', 'RD1'),
    row('V1', 'x', 'y', '', 100),
    row('V2', 'x', 'y', 'z', 100),
    row('', 'x', 'y', 'z', 5),
    row('', 'x', 'y', 'z', 5),
    row(' V3 ', 'a', 'b', 'c', 7, 'project', 'RD2'),
    row('V3', 'a', 'b', 'c', 7, 'project', 'RD2'),
    row('V3', 'a', 'b', 'c', 7, 'project', 'RD3'),
  ];
  const { groups, indexes } = duplicateVoucherRows(rows);
  assert.deepEqual(groups, [[0, 1], [8, 9]]);
  assert.deepEqual(indexes.get(0), [1]);
  assert.deepEqual(indexes.get(9), [8]);
  [2, 3, 4, 5, 6, 7, 10].forEach((index) => assert.equal(indexes.has(index), false));
  assert.notEqual(accountPathKey(rows[0]), accountPathKey(rows[4]));
});

test('stripLinePrefix removes the leading line number from validation messages', () => {
  assert.equal(stripLinePrefix('第 12 行：费用金额必须是有效数字'), '费用金额必须是有效数字');
  assert.equal(stripLinePrefix('第3行:所属项目无效'), '所属项目无效');
  assert.equal(stripLinePrefix('没有行号'), '没有行号');
});

test('filterExpenseRows filters by kind, problems and voucher / account text', () => {
  const entries = [
    { row: row('V001', '直接投入费用', '差旅费', '', 1, 'common'), index: 0, problems: [] },
    { row: row('V002', '人员人工', '工资薪金', '基本工资', 2, 'project', 'RD1'), index: 1, problems: ['费用金额必须是有效数字'] },
    { row: row('V003', '折旧', '设备折旧', '', 3, 'project', 'RD2'), index: 2, problems: [] },
  ];
  assert.deepEqual(expenseFilterCounts(entries), { all: 3, common: 1, project: 2, bad: 1 });
  assert.equal(filterExpenseRows(entries).length, 3);
  assert.deepEqual(filterExpenseRows(entries, { kind: 'common' }).map((e) => e.index), [0]);
  assert.deepEqual(filterExpenseRows(entries, { kind: 'project' }).map((e) => e.index), [1, 2]);
  assert.deepEqual(filterExpenseRows(entries, { kind: 'bad' }).map((e) => e.index), [1]);
  assert.deepEqual(filterExpenseRows(entries, { query: 'v003' }).map((e) => e.index), [2]);
  assert.deepEqual(filterExpenseRows(entries, { query: ' 工资 ' }).map((e) => e.index), [1]);
  assert.deepEqual(filterExpenseRows(entries, { kind: 'project', query: '折旧' }).map((e) => e.index), [2]);
  assert.ok(rowSearchText(entries[1].row).includes('基本工资'));
});

const page = readFileSync(new URL('../src/pages/ExpenseImport.vue', import.meta.url), 'utf8');

test('expense page uses the shared page shell with period control and KPI cards', () => {
  assert.match(page, /<RdPage title="研发费用导入"/);
  assert.match(page, /<RdPeriod/);
  assert.match(page, /<RdSeg/);
  assert.match(page, /本期费用合计/);
  assert.match(page, /label="公共费用"/);
  assert.match(page, /label="项目费用"/);
  assert.doesNotMatch(page, /较上月/);
});

test('expense page has a pre-save check card, filter chips and row problems under the row', () => {
  assert.ok(page.includes('保存前检查'));
  assert.match(page, /duplicateVoucherRows/);
  assert.match(page, /filterExpenseRows/);
  assert.match(page, /class="chip"/);
  assert.match(page, /class="field"/);
  assert.match(page, /\{ rowerr: problems\.length \}/);
  assert.match(page, /<tr v-if="problems\.length" class="rowerr">/);
  assert.match(page, /class="savebar"/);
  assert.match(page, /rowValidationErrors\(row, index\)/);
});

test('replacing the table asks for an inline confirmation first', () => {
  assert.ok(page.includes('确认覆盖'));
  assert.ok(page.includes('覆盖导入'));
  assert.match(page, /confirmWorkbookOverwrite/);
  assert.match(page, /confirmPasteOverwrite/);
  assert.match(page, /@click="confirmWorkbookReplace"/);
  // the Excel replace button only asks; it does not open the file picker directly
  assert.match(page, /@click="requestWorkbookReplace"/);
  assert.doesNotMatch(page, /@click="chooseWorkbook\(true\)"/);
});

test('paste import lives in a teleported drawer and Excel import is the primary button', () => {
  assert.match(page, /<Teleport to="body">/);
  assert.match(page, /<div v-if="pasteOpen" class="rd">/);
  assert.match(page, /class="btn pri" @click="chooseWorkbook\(false\)"/);
  assert.match(page, /@click="openPaste"/);
  assert.ok(page.includes('粘贴导入'));
});

test('saving keeps whole-month overwrite semantics and the new-account confirmation gate', () => {
  assert.match(page, /new_account_paths: JSON\.stringify\(pendingAccountPaths\.value\)/);
  assert.match(page, /pendingAccountPaths\.value\.length > 0 && !confirmNewAccounts\.value/);
  assert.match(page, /clearInvalidLowerLevels\(row, level, expenseAccountPaths\.value\)/);
});
