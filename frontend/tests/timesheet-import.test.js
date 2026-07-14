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
const activityTypes = [{ name: '方案设计' }, { name: '编码开发' }];

function options(extra = {}) {
  return { employees, projects, activityTypes, period: '2026-07', existingRows: [], ...extra };
}

test('parses timesheet rows with employee and project matching', () => {
  const text = [
    '日期\t研发人员\t项目代码\t项目名称\t活动类型\t工时(h)\t工作内容',
    '2026/07/01\t演示员工134\tRD14\tACONCA 7961\t方案设计\t6\t完成方案设计',
    '2026-07-02\tEMP-2\tRD16\tEFEM-8-2LP-EG-A\t编码开发\t2.5\t接口联调',
  ].join('\n');

  const result = parseTimesheetPaste(text, options());

  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.rows, [
    {
      work_date: '2026-07-01',
      employee: 'EMP-1',
      employee_name: '演示员工134',
      project: 'PROJ-1',
      project_code: 'RD14',
      project_name: 'ACONCA 7961',
      activity_type: '方案设计',
      hours: 6,
      description: '完成方案设计',
    },
    {
      work_date: '2026-07-02',
      employee: 'EMP-2',
      employee_name: '演示员工107',
      project: 'PROJ-2',
      project_code: 'RD16',
      project_name: 'EFEM-8-2LP-EG-A',
      activity_type: '编码开发',
      hours: 2.5,
      description: '接口联调',
    },
  ]);
});

test('rejects rows outside period, invalid references, and daily totals over eight hours', () => {
  const result = parseTimesheetTableRows([
    ['日期', '研发人员', '项目代码', '项目名称', '活动类型', '工时', '工作内容'],
    ['2026-08-01', '演示员工134', 'RD14', 'ACONCA 7961', '方案设计', 1, 'wrong period'],
    ['2026-07-01', '不存在', 'RD14', 'ACONCA 7961', '方案设计', 1, 'bad employee'],
    ['2026-07-01', '演示员工134', 'RD404', '无项目', '方案设计', 1, 'bad project'],
    ['2026-07-01', '演示员工134', 'RD14', 'ACONCA 7961', '不存在活动', 1, 'bad activity'],
    ['2026-07-01', '演示员工134', 'RD14', 'ACONCA 7961', '方案设计', 5, 'too much'],
  ], options({ existingRows: [{ employee: 'EMP-1', work_date: '2026-07-01', hours: 4 }] }));

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /第 2 行：日期必须在当前会计期间 2026-07 内/);
  assert.match(result.errors.join('\n'), /第 3 行：研发人员“不存在”未匹配/);
  assert.match(result.errors.join('\n'), /第 4 行：项目代码和项目名称未匹配/);
  assert.match(result.errors.join('\n'), /第 5 行：活动类型“不存在活动”不存在/);
  assert.match(result.errors.join('\n'), /第 6 行：演示员工134 2026-07-01 工时合计超过 8 小时/);
});

test('rejects duplicate imported or existing employee date project activity rows', () => {
  const rows = [
    ['日期', '研发人员', '项目代码', '项目名称', '活动类型', '工时', '工作内容'],
    ['2026-07-03', '演示员工134', 'RD14', 'ACONCA 7961', '方案设计', 2, 'a'],
    ['2026-07-03', '演示员工134', 'RD14', 'ACONCA 7961', '方案设计', 1, 'b'],
    ['2026-07-04', '演示员工134', 'RD14', 'ACONCA 7961', '方案设计', 1, 'c'],
  ];
  const result = parseTimesheetTableRows(rows, options({
    existingRows: [{ employee: 'EMP-1', work_date: '2026-07-04', rd_project_code: 'RD14', project_name: 'ACONCA 7961', activity_type: '方案设计', hours: 2 }],
  }));

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /第 3 行：导入内容中存在重复的员工\/日期\/项目\/活动类型/);
  assert.match(result.errors.join('\n'), /第 4 行：系统中已存在相同员工\/日期\/项目\/活动类型工时/);
});