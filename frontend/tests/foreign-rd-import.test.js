
import assert from 'node:assert/strict';
import test from 'node:test';

import { parseForeignRdPaste, parseForeignRdTableRows } from '../src/lib/foreignRdImport.js';

const projects = [
  { name: 'PROJ-1', rd_project_code: 'RD14', project_name: 'ACONCA 7961' },
  { name: 'PROJ-2', rd_project_code: 'RD16', project_name: 'EFEM-8-2LP-EG-A' },
];
const activityTypes = [{ name: '需求分析' }, { name: '方案设计' }];

function options(extra = {}) {
  return { projects, activityTypes, period: '2026-07', existingRows: [], ...extra };
}

test('parses overseas R&D rows without an employee column', () => {
  const text = [
    '日期\t项目代码\t项目名称\t活动类型\t工时(h)\t工作内容',
    '2026/07/01\tRD14\tACONCA 7961\t需求分析\t6\t境外方案讨论',
    '2026-07-02\tRD16\tEFEM-8-2LP-EG-A\t方案设计\t2.5\t境外接口设计',
  ].join('\n');

  const result = parseForeignRdPaste(text, options());

  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.rows, [
    {
      work_date: '2026-07-01',
      project: 'PROJ-1',
      project_code: 'RD14',
      project_name: 'ACONCA 7961',
      activity_type: '需求分析',
      hours: 6,
      description: '境外方案讨论',
    },
    {
      work_date: '2026-07-02',
      project: 'PROJ-2',
      project_code: 'RD16',
      project_name: 'EFEM-8-2LP-EG-A',
      activity_type: '方案设计',
      hours: 2.5,
      description: '境外接口设计',
    },
  ]);
});

test('rejects invalid overseas rows and daily totals over eight hours', () => {
  const result = parseForeignRdTableRows([
    ['日期', '项目代码', '项目名称', '活动类型', '工时', '工作内容'],
    ['2026-08-01', 'RD14', 'ACONCA 7961', '需求分析', 1, 'wrong period'],
    ['2026-07-01', 'RD404', '无项目', '需求分析', 1, 'bad project'],
    ['2026-07-01', 'RD14', 'ACONCA 7961', '不存在活动', 1, 'bad activity'],
    ['2026-07-01', 'RD14', 'ACONCA 7961', '需求分析', 5, 'too much'],
  ], options({ existingRows: [{ work_date: '2026-07-01', hours: 4 }] }));

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /第 2 行：日期必须在当前会计期间 2026-07 内/);
  assert.match(result.errors.join('\n'), /第 3 行：项目代码和项目名称未匹配/);
  assert.match(result.errors.join('\n'), /第 4 行：活动类型“不存在活动”不存在/);
  assert.match(result.errors.join('\n'), /第 5 行：2026-07-01 工时合计超过 8 小时/);
});
