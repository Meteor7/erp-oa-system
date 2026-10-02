import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync(new URL('../src/pages/ForeignRD.vue', import.meta.url), 'utf8');
const router = readFileSync(new URL('../src/router.js', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');

test('router and nav expose the overseas commissioned R&D page', () => {
  assert.match(router, /path:\s*['"]\/foreign-rd['"]/);
  assert.match(router, /\.\/pages\/ForeignRD\.vue/);
  assert.ok(app.includes("to: '/foreign-rd'"));
});

test('overseas page preserves the dashboard and save-recalculation endpoints', () => {
  assert.ok(page.includes('rayher_hr_payroll.api.foreign_rd_entry.get_foreign_rd'));
  assert.ok(page.includes('rayher_hr_payroll.api.foreign_rd_entry.save_foreign_rd'));
  assert.match(page, /foreignExpenseCards/);
  assert.match(page, /importedTotalAmount/);
  assert.match(page, /commonAmount/);
  assert.match(page, /directAmount/);
  assert.match(page, /totalHours/);
});

test('overseas editor uses monthly subject-project occurrence-day rows', () => {
  assert.match(page, /QIHENG DEMO OVERSEAS/);
  assert.match(page, /foreign_entity/);
  assert.match(page, /occurrence_days/);
  assert.match(page, /occurrence_days[^\n]*\*\s*8|\*\s*8[^\n]*occurrence_days/);
  assert.match(page, /remark/);
  assert.doesNotMatch(page, /type=["']date["']/);
  assert.doesNotMatch(page, /v-model=["'][^"']*activity_type/);
});

test('overseas page uses the shared R&D shell with four KPI cards and one status card', () => {
  assert.match(page, /<RdPage /);
  assert.match(page, /<RdPeriod \/>/);
  assert.match(page, /<RdKpi v-for="card in foreignExpenseCards"/);
  for (const label of ['importedTotal', 'commonExpense', 'projectExpense', 'totalHours']) {
    assert.match(page, new RegExp(`label: TEXT\\.${label}`));
  }
  assert.doesNotMatch(page, /<Card /);
  assert.match(page, /分摊状态/);
  assert.match(page, /allocationSubmitted \? '已提交' : '未提交'/);
});

test('overseas status card keeps the three notices, status and source expense table', () => {
  assert.match(page, /unallocatedCommonAmount\.value > 0/);
  assert.match(page, /importChanged\.value && !isYearScope\.value/);
  assert.match(page, /allocationSubmitted\.value && !isYearScope\.value/);
  assert.match(page, /saved_total_amount/);
  assert.match(page, /data\.status/);
  assert.match(page, /data\.expense_import/);
});

test('overseas rows use half-day steppers, are read-only when frozen or yearly, and keep validations', () => {
  assert.match(page, /stepDays\(row, -0\.5\)/);
  assert.match(page, /stepDays\(row, 0\.5\)/);
  assert.match(page, /const readonly = computed\(\(\) => isYearScope\.value \|\| allocationSubmitted\.value\)/);
  assert.match(page, /\\d\+\(\?:\\\.\\d\{1,2\}\)\?/);
  assert.match(page, /发生天数必须大于 0，且最多保留两位小数/);
  assert.match(page, /同一主体和项目只能填写一行/);
  assert.match(page, /有境外公共费用时，必须录入至少一条工时/);
  assert.match(page, /请至少填写一条境外工时/);
});

test('overseas page adds projects through a searchable picker and saves from a sticky bar', () => {
  assert.match(page, /pickerQuery/);
  assert.match(page, /class="pitem"/);
  assert.match(page, /class="savebar"/);
  assert.match(page, /保存并重新计算费用/);
  assert.match(page, /:disabled="allocationSubmitted \|\| saving"/);
  assert.match(page, /v-if="!isYearScope" class="savebar"/);
});
