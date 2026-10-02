import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src/pages/ExpenseImport.vue', import.meta.url), 'utf8');

test('expense amount entry accepts finite negative values', () => {
  assert.doesNotMatch(source, /min=['"]0['"]/);
  assert.doesNotMatch(source, /amount\s*<=\s*0/);
  assert.match(source, /Number\.isFinite\(amount\)/);
});

test('expense import uses the R&D expense import name throughout the page', () => {
  assert.ok(source.includes('研发费用导入'));
  assert.doesNotMatch(source, /财务费用导入/);
});

test('expense import supports common and project-specific expenses', () => {
  assert.match(source, /rayher_hr_payroll\.api\.project_entry\.list_projects/);
  assert.match(source, /allocation_type/);
  assert.match(source, /direct_project/);
  assert.ok(source.includes('归属方式'));
  assert.ok(source.includes('公共费用'));
  assert.ok(source.includes('项目费用'));
  assert.ok(source.includes('所属项目'));
  assert.match(source, /ALLOCATION_TYPES/);
  assert.match(source, /v-model=["']it\.allocation_type["']/);
  assert.match(source, /v-model=["']it\.direct_project["']/);
  assert.doesNotMatch(source, /项目填“公共费用”/);
});

test('allocated expense imports stay editable from the SPA', () => {
  assert.doesNotMatch(source, /status\.value === 'Allocated' \|\| status\.value === 'Imported'/);
  assert.doesNotMatch(source, /已提交|已分摊/);
});

test('expense import page supports four-level manual entry and batch paste import', () => {
  assert.match(source, /parseExpensePaste/);
  assert.match(source, /pasteText/);
  assert.match(source, /pastePlaceholder/);
  assert.ok(source.includes('批量粘贴'));
  assert.ok(source.includes('追加导入'));
  assert.ok(source.includes('覆盖当前表格'));
  assert.ok(source.includes('1级费用科目'));
  assert.ok(source.includes('2级费用科目'));
  assert.ok(source.includes('3级费用科目'));
  assert.ok(source.includes('4级费用科目'));
  // the detail table keeps one column per account level
  assert.ok(source.includes('一级科目'));
  assert.ok(source.includes('二级科目'));
  assert.ok(source.includes('三级科目'));
  assert.ok(source.includes('四级科目'));
  assert.ok(source.includes('费用金额'));
  assert.match(source, /accountOptions/);
  assert.match(source, /validateExpenseAccount/);
  assert.match(source, /<datalist/);
  assert.match(source, /:list="accountDatalistId\(i, 1\)"/);
});

test('expense import page supports xlsx workbook import preview', () => {
  assert.match(source, /importWorkbookFile/);
  assert.match(source, /type=["']file["']/);
  assert.match(source, /accept=["']\.xlsx,\.xls["']/);
  assert.match(source, /导入\s?Excel/);
});

test('expense import page uses a wide scrollable spreadsheet layout', () => {
  assert.match(source, /overflow-x-auto/);
  assert.match(source, /min-w-\[1500px\]/);
  assert.match(source, /min-w-\[220px\]/);
  assert.match(source, /whitespace-nowrap/);
});


test('expense import can switch to a read-only year view', () => {
  assert.match(source, /periodScope/);
  assert.match(source, /scope: periodScope\.value/);
  assert.match(source, /isYearScope/);
  assert.ok(source.includes('??'));
  assert.match(source, /v-if=["']isYearScope["']/);
  // year rows are plain text (no inputs) with a date column
  assert.match(source, /<th[^>]*>日期<\/th>/);
  assert.match(source, /<td[^>]*>\{\{\s*it\.period\s*\}\}<\/td>/);
  assert.match(source, /label:\s*'日期',\s*key:\s*'period'/);
  assert.match(source, /年度视图只读/);
});

test('expense import surfaces detailed Frappe validation messages', () => {
  assert.match(source, /_server_messages/);
  assert.match(source, /serverMessage\(saver\.error \|\| e, '保存失败'\)/);
});
