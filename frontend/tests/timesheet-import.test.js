import assert from 'node:assert/strict';
import test from 'node:test';

import { parseTimesheetPaste, parseTimesheetTableRows } from '../src/lib/timesheetImport.js';

const employees = [
  { name: 'EMP-1', employee_name: '演示员工134' },
  { name: 'EMP-2', employee_name: '演示员工107' },
];
const projects = [
  { name: 'PROJ-1', rd_project_code: 'RD14', project_name: 'ACONCA 7961' },
  { name: 'PROJ-2', rd_project_code: 'RD16', project_name: 'EFEM-8-2LP-EG-A' },
];

function options(extra = {}) {
  return { employees, projects, period: '2026-07', existingRows: [], ...extra };
}

test('an old template with 发生天数 still imports: days times eight become the hours', () => {
  const text = [
    '研发人员\t项目代码\t项目名称\t发生天数\t备注',
    '演示员工134\tRD14\tACONCA 7961\t2.35\t方案设计',
    'EMP-2\tRD16\tEFEM-8-2LP-EG-A\t1.25\t接口联调',
  ].join('\n');

  const result = parseTimesheetPaste(text, options());

  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.rows, [
    {
      employee: 'EMP-1', employee_name: '演示员工134', project: 'PROJ-1',
      project_code: 'RD14', project_name: 'ACONCA 7961',
      occurrence_days: 2.35, hours: 18.8, remark: '方案设计',
    },
    {
      employee: 'EMP-2', employee_name: '演示员工107', project: 'PROJ-2',
      project_code: 'RD16', project_name: 'EFEM-8-2LP-EG-A',
      occurrence_days: 1.25, hours: 10, remark: '接口联调',
    },
  ]);
});

test('rejects invalid references and occurrence-day precision', () => {
  const result = parseTimesheetTableRows([
    ['研发人员', '项目代码', '项目名称', '发生天数', '备注'],
    ['不存在', 'RD14', 'ACONCA 7961', '1', 'bad employee'],
    ['演示员工134', 'RD404', '无项目', '1', 'bad project'],
    ['演示员工134', 'RD14', 'ACONCA 7961', '1.001', 'too precise'],
    ['演示员工107', 'RD16', 'EFEM-8-2LP-EG-A', '0', 'zero'],
  ], options());

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /第 2 行：研发人员“不存在”未匹配/);
  assert.match(result.errors.join('\n'), /第 3 行：项目代码和项目名称未匹配/);
  assert.match(result.errors.join('\n'), /第 4 行：发生天数最多保留两位小数/);
  assert.match(result.errors.join('\n'), /第 5 行：发生天数必须大于 0/);
});

test('rejects duplicate employee-project rows from import or saved entries', () => {
  const result = parseTimesheetTableRows([
    ['研发人员', '项目代码', '项目名称', '发生天数', '备注'],
    ['演示员工134', 'RD14', 'ACONCA 7961', '2', 'a'],
    ['演示员工134', 'RD14', 'ACONCA 7961', '1', 'b'],
    ['演示员工107', 'RD16', 'EFEM-8-2LP-EG-A', '1', 'c'],
  ], options({
    existingRows: [{ employee: 'EMP-2', project: 'PROJ-2', project_code: 'RD16', project_name: 'EFEM-8-2LP-EG-A', occurrence_days: 2 }],
  }));

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /第 3 行：导入内容中存在重复的员工和项目/);
  assert.match(result.errors.join('\n'), /第 4 行：系统中已存在相同员工和项目的月度工时/);
});

test('rejects employee monthly total above the selected calendar-month limit', () => {
  const result = parseTimesheetTableRows([
    ['研发人员', '项目代码', '项目名称', '发生天数', '备注'],
    ['演示员工134', 'RD14', 'ACONCA 7961', '20', 'a'],
    ['演示员工134', 'RD16', 'EFEM-8-2LP-EG-A', '11.01', 'b'],
  ], options());

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /演示员工134当月累计工时不能超过 248 小时/);          // 31 天 × 8
});

test('uses the accounting period to enforce February day capacity', () => {
  const result = parseTimesheetTableRows([
    ['研发人员', '项目代码', '项目名称', '发生天数', '备注'],
    ['演示员工134', 'RD14', 'ACONCA 7961', '29', 'too many'],
  ], options({ period: '2026-02' }));

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /不能超过 224 小时/);                         // 28 天 × 8
});

test('parses the hours column: hours are the source, the days are derived from them', () => {
  const text = [
    '研发人员\t项目代码\t项目名称\t工时（小时）\t备注',
    '演示员工134\tRD14\tACONCA 7961\t100\t方案设计',
    'EMP-2\tRD16\tEFEM-8-2LP-EG-A\t73.5小时\t接口联调',
  ].join('\n');
  const result = parseTimesheetPaste(text, options({ period: '2026-10' }));
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.rows.map((row) => [row.employee, row.hours, row.occurrence_days]), [['EMP-1', 100, 12.5], ['EMP-2', 73.5, 9.19]]);   // 73.5 / 8 = 9.1875
});

test('rows without a header read the fourth column as hours', () => {
  const result = parseTimesheetTableRows([['演示员工134', 'RD14', 'ACONCA 7961', '16', '联调']], options());
  assert.deepEqual(result.errors, []);
  assert.deepEqual([result.rows[0].hours, result.rows[0].occurrence_days, result.rows[0].remark], [16, 2, '联调']);
});

test('when both columns are present the hours win', () => {
  const result = parseTimesheetTableRows([
    ['研发人员', '项目代码', '项目名称', '发生天数', '工时', '备注'],
    ['演示员工134', 'RD14', 'ACONCA 7961', '3', '10', ''],
  ], options());
  assert.deepEqual(result.errors, []);
  assert.deepEqual([result.rows[0].hours, result.rows[0].occurrence_days], [10, 1.25]);
});

test('hour errors: precision, zero, text, and the monthly total in hours', () => {
  const result = parseTimesheetTableRows([
    ['研发人员', '项目代码', '项目名称', '工时', '备注'],
    ['演示员工134', 'RD14', 'ACONCA 7961', '1.005', ''],
    ['演示员工107', 'RD16', 'EFEM-8-2LP-EG-A', '0', ''],
    ['演示员工107', 'RD14', 'ACONCA 7961', 'abc', ''],
  ], options());
  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /第 2 行：工时最多保留两位小数/);
  assert.match(result.errors.join('\n'), /第 3 行：工时必须大于 0/);
  assert.match(result.errors.join('\n'), /第 4 行：工时必须是有效数字/);
  const over = parseTimesheetTableRows([
    ['研发人员', '项目代码', '项目名称', '工时', '备注'],
    ['演示员工134', 'RD14', 'ACONCA 7961', '200', ''],
    ['演示员工134', 'RD16', 'EFEM-8-2LP-EG-A', '48.01', ''],
  ], options({ period: '2026-10' }));
  assert.match(over.errors.join('\n'), /演示员工134当月累计工时不能超过 248 小时/);
  const exact = parseTimesheetTableRows([
    ['研发人员', '项目代码', '项目名称', '工时', '备注'],
    ['演示员工134', 'RD14', 'ACONCA 7961', '200', ''],
    ['演示员工134', 'RD16', 'EFEM-8-2LP-EG-A', '48', ''],
  ], options({ period: '2026-10' }));
  assert.deepEqual(exact.errors, []);
});

test('hours already in the sheet count towards the monthly total', () => {
  const result = parseTimesheetTableRows([
    ['研发人员', '项目代码', '项目名称', '工时', '备注'],
    ['演示员工134', 'RD14', 'ACONCA 7961', '100', ''],
  ], options({ period: '2026-10', existingRows: [{ employee: 'EMP-1', project: 'PROJ-9', hours: 150 }] }));
  assert.match(result.errors.join('\n'), /演示员工134当月累计工时不能超过 248 小时/);
});
