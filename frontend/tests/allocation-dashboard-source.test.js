import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/AllocationDashboard.vue", import.meta.url), "utf8");

test("allocation dashboard is titled as the R&D expense summary", () => {
  assert.ok(source.includes("title: \"\\u7814\\u53d1\\u8d39\\u7528\\u6c47\\u603b\""));
});

test("allocation dashboard loads the Excel-style summary API", () => {
  assert.match(source, /rayher_hr_payroll\.api\.allocation_entry\.get_allocation_dashboard/);
  assert.match(source, /periodScope/);
  assert.match(source, /dashboardMode/);
  assert.match(source, /scope:\s*periodScope\.value/);
  assert.match(source, /mode:\s*dashboardMode\.value/);
});

test("allocation dashboard renders one second-level summary table with a grand total", () => {
  assert.ok(source.includes("\\u8d39\\u7528\\u6c47\\u603b"));
  assert.match(source, /summaryRows/);
  assert.match(source, /isSubtotal/);
  assert.match(source, /isGrandTotal/);
  assert.match(source, /projectColumns/);
  assert.match(source, /v-for="project in projectColumns"/);
  assert.doesNotMatch(source, /detailRows/);
  assert.doesNotMatch(source, /detail_rows/);
  assert.doesNotMatch(source, /\\u53f0\\u8d26\\u660e\\u7ec6/);
  assert.doesNotMatch(source, /voucher_no/);
});

test("allocation dashboard exposes the three accounting views from the workbook", () => {
  assert.ok(source.includes("\\u6c47\\u603b"));
  assert.ok(source.includes("\\u8d44\\u672c\\u5316"));
  assert.ok(source.includes("\\u8d39\\u7528\\u5316"));
  assert.match(source, /modeOptions/);
});

test("allocation dashboard uses compact project codes and sticky grouped columns", () => {
  assert.match(source, /project\.project_code/);
  assert.doesNotMatch(source, /\{\{\s*project\.label\s*\}\}/);
  assert.match(source, /secondLevelText/);
  assert.match(source, /sticky left-0/);
  assert.match(source, /sticky left-\[180px\]/);
});
