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

test('parses monthly foreign hours and derives the days', () => {
  const text = [
    '主体\t项目代码\t项目名称\t工时\t备注',
    'QIHENG DEMO OVERSEAS\tRD14\tACONCA 7961\t20\tmonthly work',
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

test('the old template with the days column is still accepted at 1 day = 8 hours', () => {
  const result = parseForeignRdPaste([
    '主体\t项目代码\t项目名称\t发生天数\t备注',
    'QIHENG DEMO OVERSEAS\tRD14\tACONCA 7961\t2.35\told template',
  ].join('\n'), options());

  assert.deepEqual(result.errors, []);
  assert.equal(result.rows[0].hours, 18.8);
  assert.equal(result.rows[0].occurrence_days, 2.35);
});

test('without a header the fourth column is hours', () => {
  const result = parseForeignRdPaste('QIHENG DEMO OVERSEAS\tRD16\tEFEM-8-2LP-EG-A\t12\tacceptance', options());

  assert.deepEqual(result.errors, []);
  assert.equal(result.rows[0].hours, 12);
  assert.equal(result.rows[0].occurrence_days, 1.5);
});

test('rejects more than two decimals and more than the calendar month times eight hours', () => {
  const result = parseForeignRdTableRows([
    ['主体', '项目代码', '项目名称', '工时', '备注'],
    ['QIHENG DEMO OVERSEAS', 'RD14', 'ACONCA 7961', '8.001', 'precision'],
    ['QIHENG DEMO OVERSEAS', 'RD16', 'EFEM-8-2LP-EG-A', '240.01', 'too many'],
  ], options({ period: '2026-06' }));

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /第 2 行：工时最多保留两位小数/);
  assert.match(result.errors.join('\n'), /第 3 行：工时不能超过当月自然日数 × 8 小时/);
  assert.equal(parseForeignRdTableRows([['主体', '项目代码', '项目名称', '工时'], ['QIHENG DEMO OVERSEAS', 'RD14', 'ACONCA 7961', '240']], options({ period: '2026-06' })).errors.length, 0);
});

test('rejects unknown subject, invalid project, invalid hours and duplicate subject-project rows', () => {
  const result = parseForeignRdTableRows([
    ['主体', '项目代码', '项目名称', '工时', '备注'],
    ['UNKNOWN', 'RD14', 'ACONCA 7961', '8', 'bad subject'],
    ['QIHENG DEMO OVERSEAS', 'RD404', 'none', '8', 'bad project'],
    ['QIHENG DEMO OVERSEAS', 'RD14', 'ACONCA 7961', '1.001', 'bad precision'],
    ['QIHENG DEMO OVERSEAS', 'RD14', 'ACONCA 7961', '8', 'duplicate'],
  ], options({ existingRows: [{ foreign_entity: 'QIHENG DEMO OVERSEAS', project: 'PROJ-1' }] }));

  assert.deepEqual(result.rows, []);
  assert.match(result.errors.join('\n'), /第 2 行：主体/);
  assert.match(result.errors.join('\n'), /第 3 行：项目代码和项目名称未匹配/);
  assert.match(result.errors.join('\n'), /第 4 行：工时最多保留两位小数/);
  assert.match(result.errors.join('\n'), /第 5 行：系统中已存在相同主体和项目/);
});