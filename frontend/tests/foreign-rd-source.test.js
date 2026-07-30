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