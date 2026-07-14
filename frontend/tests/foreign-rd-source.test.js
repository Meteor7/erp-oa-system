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
  assert.ok(app.includes('\\u5883\\u5916\\u59d4\\u6258\\u7814\\u53d1\\u5de5\\u65f6'));
  assert.match(app, /WIDE_PAGE_PATHS[\s\S]*['"]\/foreign-rd['"]/);
});

test('overseas page keeps hour entry and detail table but removes expense-source blocks', () => {
  assert.ok(page.includes('rayher_hr_payroll.api.foreign_rd_entry.get_foreign_rd'));
  assert.ok(page.includes('rayher_hr_payroll.api.foreign_rd_entry.save_foreign_rd'));
  assert.ok(page.includes('rayher_hr_payroll.api.timesheet_entry.get_rd_options'));
  assert.ok(page.includes('\\u5883\\u5916\\u5de5\\u65f6\\u586b\\u62a5'));
  assert.ok(page.includes('\\u672c\\u671f\\u5883\\u5916\\u5de5\\u65f6\\u8868'));
  assert.doesNotMatch(page, /\\u5883\\u5916\\u8d39\\u7528\\u5206\\u644a/);
  assert.doesNotMatch(page, /foreign-expense-sources/);
  assert.doesNotMatch(page, /\\u5883\\u5916\\u9879\\u76ee\\u5206\\u644a/);
  assert.doesNotMatch(page, /\\u5408\\u5e76\\u540e\\u9879\\u76ee\\u6c47\\u603b/);
  assert.doesNotMatch(page, /\\u8d44\\u672c\\u5316\/\\u8d39\\u7528\\u5316\\u6c47\\u603b/);
  assert.doesNotMatch(page, /foreignProjectSummaries/);
  assert.doesNotMatch(page, /combinedProjectSummaries/);
  assert.doesNotMatch(page, /combinedStageSummaries/);
  assert.doesNotMatch(page, /v-model=['"]totalAmount['"]/);
});


test('overseas page follows the standard timesheet entry fields and has no broken question marks', () => {
  assert.doesNotMatch(page, /\?\?\?\?/);
  assert.ok(page.includes('rayher_hr_payroll.api.timesheet_entry.get_rd_options'));
  assert.match(page, /work_date/);
  assert.match(page, /project_code/);
  assert.match(page, /project_name/);
  assert.match(page, /activity_type/);
  assert.match(page, /description/);
  assert.match(page, /syncProjectCode/);
  assert.match(page, /syncProjectName/);
  assert.ok(page.includes('\\u65e5\\u671f'));
  assert.ok(page.includes('\\u9879\\u76ee\\u4ee3\\u7801'));
  assert.ok(page.includes('\\u9879\\u76ee\\u540d\\u79f0'));
  assert.ok(page.includes('\\u6d3b\\u52a8\\u7c7b\\u578b'));
  assert.ok(page.includes('\\u5de5\\u65f6'));
  assert.ok(page.includes('\\u5de5\\u4f5c\\u5185\\u5bb9'));
});


test('overseas entry editor uses a wide table layout for project pickers', () => {
  const entryStart = page.indexOf('foreign-rd-entry-table');
  const batchStart = page.indexOf('foreign-rd-batch-import', entryStart);
  const entrySection = page.slice(entryStart, batchStart);
  assert.ok(entryStart > 0);
  assert.ok(batchStart > entryStart);
  assert.ok(page.includes('foreign-rd-entry-row'));
  assert.ok(page.includes('foreign-rd-project-menu'));
  assert.match(entrySection, /min-w-\[1280px\]/);
  assert.match(entrySection, /overflow-y-visible/);
  assert.match(entrySection, /z-50/);
  assert.doesNotMatch(entrySection, /foreign-rd-entry-row rounded-lg/);
});


test('overseas page keeps line allocation fields without rendering the expense-source table', () => {
  assert.ok(page.includes('common_allocated_amount'));
  assert.ok(page.includes('direct_allocated_amount'));
  assert.doesNotMatch(page, /foreign-expense-sources/);
  assert.doesNotMatch(page, /source:\s*'\\u5883\\u5916\\u8d39\\u7528\\u6765\\u6e90'/);
});


test('overseas page can switch between monthly entry and yearly read-only view', () => {
  assert.match(page, /periodScope/);
  assert.match(page, /scope: periodScope\.value/);
  assert.match(page, /isYearScope/);
  assert.ok(page.includes('??'));
  assert.ok(page.includes('??'));
});


test('overseas entry uses draft rows and keeps saved lines only in the detail table', () => {
  assert.match(page, /const draftTotalHours = computed/);
  assert.match(page, /const savedTotalHours = computed/);
  assert.match(page, /rows\.value = \[blankRow\(\)\]/);
  assert.doesNotMatch(page, /rows\.value = normalizeRows\(payload\.lines \|\| \[\]\)/);
  assert.match(page, /savedRowsForPayload\(\)/);
  assert.match(page, /deleteSavedLine/);
});
