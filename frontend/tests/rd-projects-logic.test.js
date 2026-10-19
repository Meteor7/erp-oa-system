import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { attachmentPills, hasMissingAttachment, pendingProjectItems, pendingSummary, projectCode, projectStage, projectStats, requiredAttachments, stageTone, statusTone } from '../src/lib/rdProjects.js';

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

const states = (row) => attachmentPills(row).map((pill) => pill.state).join(',');

test('attachmentPills always returns the three pills in the fixed order', () => {
  const pills = attachmentPills({ status: 'Open', rd_stage: '费用化' });
  assert.deepEqual(pills.map((pill) => pill.label), ['立项报告', '结项报告', '资本化确认书']);
  assert.deepEqual(pills.map((pill) => pill.key), ['project_initiation_report', 'project_completion_report', 'capitalization_confirmation_file']);
  assert.equal(attachmentPills().length, 3);
});

test('attachmentPills applies the required / not-required rules by status and stage', () => {
  // 进行中 + 费用化：只要立项报告
  assert.equal(states({ status: 'Open', rd_stage: '费用化' }), 'miss,na,na');
  // 进行中 + 资本化：立项报告 + 确认书
  assert.equal(states({ status: 'Open', rd_stage: '资本化' }), 'miss,na,miss');
  // 已结束 + 资本化：三个都要
  assert.equal(states({ status: 'Completed', rd_stage: '资本化' }), 'miss,miss,miss');
  // 已结束 + 费用化：不要确认书
  assert.equal(states({ status: 'Completed', rd_stage: '费用化' }), 'miss,miss,na');
  // 阶段未判定：不要确认书
  assert.equal(states({ status: 'Open', rd_stage: '未判定' }), 'miss,na,na');
  // 已取消：演示员工177要
  assert.equal(states({ status: 'Cancelled', rd_stage: '资本化' }), 'na,na,na');
  // 没有状态按进行中算
  assert.equal(states({ rd_stage: '费用化' }), 'miss,na,na');
  assert.deepEqual(requiredAttachments({ status: 'Completed', rd_stage: '资本化' }), {
    project_initiation_report: true,
    project_completion_report: true,
    capitalization_confirmation_file: true,
  });
});

test('attachmentPills: uploaded files are green even when not required, missing ones read 缺…', () => {
  const pills = attachmentPills({ status: 'Open', rd_stage: '费用化', project_initiation_report: '/f/a.pdf', project_completion_report: '/f/b.pdf' });
  assert.deepEqual(pills.map((pill) => pill.state), ['up', 'up', 'na']);
  assert.equal(pills[1].required, false);
  assert.equal(pills[1].file, '/f/b.pdf');
  const cancelled = attachmentPills({ status: 'Cancelled', project_initiation_report: '/f/a.pdf' });
  assert.equal(cancelled[0].state, 'up');
  const missing = attachmentPills({ status: 'Completed', rd_stage: '资本化', project_initiation_report: '/f/a.pdf' });
  assert.deepEqual(missing.map((pill) => pill.text), ['立项报告', '缺结项报告', '缺资本化确认书']);
  assert.deepEqual(missing.map((pill) => pill.missing), [false, true, true]);
});

test('hasMissingAttachment is true only when a required file is missing', () => {
  assert.equal(hasMissingAttachment({ status: 'Open', rd_stage: '费用化', project_initiation_report: '/f/a.pdf' }), false);
  assert.equal(hasMissingAttachment({ status: 'Open', rd_stage: '资本化', project_initiation_report: '/f/a.pdf' }), true);
  assert.equal(hasMissingAttachment({ status: 'Cancelled' }), false);
});

test('pending attachment items agree one-to-one with the missing pills (KPI count equals amber pills)', () => {
  const mixed = [
    ...rows,
    { name: 'P6', rd_project_code: 'RD14', project_name: 'F', status: 'Completed', rd_stage: '费用化', project_initiation_report: '', project_completion_report: '' },
    { name: 'P7', rd_project_code: 'RD13', project_name: 'G', status: 'Open', rd_stage: '资本化', project_initiation_report: '/f/g.pdf', capitalization_confirmation_file: '/f/g2.pdf' },
  ];
  const missingPills = mixed.reduce((sum, row) => sum + attachmentPills(row).filter((pill) => pill.missing).length, 0);
  const attachmentItems = pendingProjectItems(mixed).filter((item) => !item.text.includes('阶段未判定'));
  assert.equal(attachmentItems.length, missingPills);
  // 已结束但没传立项报告也会被算进来
  assert.ok(attachmentItems.some((item) => item.code === 'RD14' && item.text === '已结项但缺立项报告'));
  assert.ok(attachmentItems.some((item) => item.code === 'RD14' && item.text === '已结项但缺结项报告'));
  // 已取消的项目不产生待处理
  assert.ok(!pendingProjectItems(mixed).some((item) => item.code === 'RD15'));
  // 仍保留「阶段未判定」（只针对进行中）
  assert.ok(pendingProjectItems(mixed).some((item) => item.code === 'RD17' && item.text.startsWith('研发阶段未判定')));
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
  assert.ok(page.includes('附件齐全、阶段都已判定'));
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

test('three attachments are shown as labelled pills; uploaded ones link to the scoped download', () => {
  assert.doesNotMatch(page, /三类附件/);
  assert.doesNotMatch(page, /class="ico3"/);
  assert.match(page, /attachmentPills\(row\)/);
  assert.match(page, /v-for="pill in pills"/);
  assert.match(page, /class="pill up"[^>]*:href="reportDownloadUrl\(row, pill\.key\)"/);
  assert.match(page, /class="pill miss"/);
  assert.match(page, /class="pill na"/);
  assert.match(page, /pillTitle\(pill\)/);
});

test('a missing-attachment pill is a button that opens the edit drawer on the matching field; there is no separate upload path', () => {
  assert.match(page, /<button v-else-if="pill\.state === 'miss'" type="button" class="pill miss"/);
  assert.match(page, /@click="editAttachment\(row, pill\.key\)"/);
  // the drawer's own full save stays the only way to persist a file (save_project clears omitted fields)
  assert.match(page, /async function editAttachment\(row, fieldKey\) \{\s*edit\(row\);\s*await nextTick\(\);/);
  assert.match(page, /querySelector\(`\[data-file-field="\$\{fieldKey\}"\]`\)/);
  assert.match(page, /:data-file-field="fileField\.key"/);
  assert.match(page, /hl: highlightField === fileField\.key/);
  assert.equal((page.match(/\/api\/method\/upload_file/g) || []).length, 1);
  assert.equal((page.match(/saver\.submit/g) || []).length, 1);
  // uploaded pills keep downloading
  assert.match(page, /<a v-if="pill\.state === 'up'" class="pill up" :href="reportDownloadUrl\(row, pill\.key\)"/);
  // keyboard access to the upload button inside the drawer
  assert.match(page, /data-file-pick @keydown\.enter\.prevent="pickFile" @keydown\.space\.prevent="pickFile"/);
});

test('project page has an attachment filter and a legend under the table', () => {
  assert.match(page, /v-model="filters\.attachment"/);
  assert.match(page, /aria-label="附件筛选"/);
  assert.ok(page.includes('附件：有缺失'));
  assert.match(page, /hasMissingAttachment/);
  assert.match(page, /class="att-legend"/);
  assert.ok(page.includes('已上传'));
  assert.ok(page.includes('缺附件'));
  assert.ok(page.includes('不需要'));
});

test('project page keeps search, status filter, export and upload controls', () => {
  assert.match(page, /v-model="filters\.search"/);
  assert.match(page, /v-model="filters\.status"/);
  assert.match(page, /exportCurrentProjects/);
  assert.match(page, /clear|清除/);
  assert.match(page, /form\[fileField\.key\] = ''/);
});
