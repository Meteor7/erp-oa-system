import assert from 'node:assert/strict';
import test from 'node:test';

import { parseForeignRdPaste, parseForeignRdTableRows } from '../src/lib/foreignRdImport.js';

const projects = [
  { name: 'PROJ-1', rd_project_code: 'RD14', project_name: 'ACONCA 7961' },
  { name: 'PROJ-2', rd_project_code: 'RD16', project_name: 'EFEM-8-2LP-EG-A' },
];

function options(extra = {}) {
  return { projects, foreignEntities: ['QIHENG DEMO OVERSEAS'], existingRows: [], ...extra };
}

test('parses monthly foreign occurrence days and calculates hours', () => {
  const text = [
    '主体\t项目代码\t项目名称\t发生天数\t备注',
    'QIHENG DEMO OVERSEAS\tRD14\tACONCA 7961\t2.5\tmonthly work',
  ].join('\n');

  const result = parseForeignRdPaste(text, options());

  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.rows, [{
    foreign_entity: 'QIHENG DEMO OVERSEAS',
    project: 'PROJ-1',
    project_code: 'RD14',
    project_name: 'ACONCA 7961',
    occurrence_days: 2.5,
    hours: 20,
    remark: 'monthly work',
  }]);
});

test('rejects unknown subject, invalid project, invalid days and duplicate subject-project rows', () => {
  const result = parseForeignRdTableRows([
    ['主体', '项目代码', '项目名称', '发生天数', '备注'],
    ['UNKNOWN', 'RD14', 'ACONCA 7961', '1', 'bad subject'],
    ['QIHENG DEMO OVERSEAS', 'RD404', 'none', '1', 'bad project'],
    ['QIHENG DEMO OVERSEAS', 'RD14', 'ACONCA 7961', '1.001', 'bad precision'],
    ['QIHENG DEMO OVERSEAS', 'RD14', 'ACONCA 7961', '1', 'duplicate'],
  ], options({ existingRows: [{ foreign_entity: 'QIHENG DEMO OVERSEAS', project: 'PROJ-1' }] }));

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /第 2 行：主体/);
  assert.match(result.errors.join('\n'), /第 3 行：项目代码和项目名称未匹配/);
  assert.match(result.errors.join('\n'), /第 4 行：发生天数最多保留两位小数/);
  assert.match(result.errors.join('\n'), /第 5 行：系统中已存在相同主体和项目/);
});