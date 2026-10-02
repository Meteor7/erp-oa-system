import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { pendingProjectItems, pendingSummary, projectCode, projectStage, projectStats, stageTone, statusTone } from '../src/lib/rdProjects.js';

const rows = [
  { name: 'P1', rd_project_code: 'RD19', project_name: 'A', status: 'Open', rd_stage: '资本化', project_initiation_report: '/f/a.pdf', capitalization_confirmation_file: '' },
  { name: 'P2', rd_project_code: 'RD18', project_name: 'B', status: 'Open', rd_stage: '费用化', project_initiation_report: '' },
  { name: 'P3', rd_project_code: 'RD17', project_name: 'C', status: 'Open', rd_stage: '未判定', project_initiation_report: '/f/c.pdf' },
  { name: 'P4', rd_project_code: 'RD16', project_name: 'D', status: 'Completed', rd_stage: '资本化', project_initiation_report: '/f/d.pdf', project_completion_report: '', capitalization_confirmation_file: '/f/d2.pdf' },
  { name: 'P5', rd_project_code: 'RD15', project_name: 'E', status: 'Cancelled', rd_stage: '未判定', project_initiation_report: '' },
];

test('projectStats counts totals and open capitalized / expensed projects', () => {
  assert.deepEqual(projectStats(rows), { total: 5, open: 3, capitalized: 1, expensed: 1 });
  assert.deepEqual(projectStats(), { total: 0, open: 0, capitalized: 0, expensed: 0 });
});

test('pendingProjectItems lists the four kinds in order and ignores cancelled projects', () => {
  const items = pendingProjectItems(rows);
  assert.deepEqual(items.map((item) => `${item.code}:${item.text}`), [
    'RD18:进行中但缺立项报告',
    'RD17:研发阶段未判定，费用暂不能资本化',
    'RD19:资本化项目缺确认书',
    'RD16:已结项但缺结项报告',
  ]);
  assert.equal(items[0].tone, 'bad');
  assert.equal(items[0].label, 'RD18 B');
});

test('pendingProjectItems is empty when nothing is missing', () => {
  assert.deepEqual(pendingProjectItems([{ name: 'X', status: 'Open', rd_stage: '费用化', project_initiation_report: '/f/x.pdf' }]), []);
  assert.deepEqual(pendingProjectItems(), []);
});

test('pendingSummary keeps at most three items and flags the rest', () => {
  const items = pendingProjectItems(rows);
  const summary = pendingSummary(items, 3);
  assert.equal(summary.count, 4);
  assert.equal(summary.more, true);
  assert.equal(summary.text.split('；').length, 3);
  assert.ok(summary.text.startsWith('RD18 B：进行中但缺立项报告'));
  assert.equal(pendingSummary(items.slice(0, 2), 3).more, false);
});

test('project display helpers', () => {
  assert.equal(projectCode({ name: 'N1' }), 'N1');
  assert.equal(projectCode({ name: 'N1', rd_project_code: 'RD01' }), 'RD01');
  assert.equal(projectStage({}), '未判定');
  assert.equal(projectStage({ rd_stage: '费用化' }), '费用化');
  assert.equal(stageTone('资本化'), 'ok');
  assert.equal(stageTone('费用化'), 'info');
  assert.equal(stageTone('未判定'), '');
  assert.equal(statusTone('Open'), 'ok');
  assert.equal(statusTone('Completed'), '');
  assert.equal(statusTone('Cancelled'), 'bad');
});

const page = readFileSync(new URL('../src/pages/Projects.vue', import.meta.url), 'utf8');

test('project page is wrapped in the shared R&D page shell with KPI cards and one pending note', () => {
  assert.match(page, /<RdPage title="项目管理"/);
  assert.match(page, /label="项目总数"/);
  assert.match(page, /label="进行中"/);
  assert.match(page, /label="待处理事项"/);
  assert.match(page, /class="note warn"/);
  assert.match(page, /pendingSummary\(pending\.value, 3\)/);
  assert.doesNotMatch(page, /本年工时/);
});

test('project editor is a teleported right-side drawer and cancelling asks for confirmation', () => {
  assert.match(page, /<Teleport to="body">/);
  assert.match(page, /<div v-if="editing" class="rd">/);
  assert.match(page, /class="rd-drawer"/);
  assert.ok(page.includes('确认取消'));
  assert.ok(page.includes('返回'));
  assert.match(page, /@click="askCancelName = row\.name"/);
  assert.match(page, /await canceler\.submit\(\{ name \}\)/);
  // the table row button no longer cancels directly
  assert.doesNotMatch(page, /@click="cancelProject\(row\.name\)"[^>]*>取消</);
});

test('three attachments are shown as status icons linking to the scoped download', () => {
  assert.match(page, /class="ico3"/);
  assert.match(page, /v-for="field in PROJECT_FILE_FIELDS"/);
  assert.match(page, /reportDownloadUrl\(row, field\.key\)/);
});

test('project page keeps search, status filter, export and upload controls', () => {
  assert.match(page, /v-model="filters\.search"/);
  assert.match(page, /v-model="filters\.status"/);
  assert.match(page, /exportCurrentProjects/);
  assert.match(page, /clear|清除/);
  assert.match(page, /form\[fileField\.key\] = ''/);
});
