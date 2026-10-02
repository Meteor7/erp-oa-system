import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/AllocationDashboard.vue", import.meta.url), "utf8");

test("allocation dashboard is titled as the R&D expense summary", () => {
  assert.ok(source.includes('title: "研发费用汇总"'));
});

test("allocation dashboard loads the Excel-style summary API", () => {
  assert.match(source, /rayher_hr_payroll\.api\.allocation_entry\.get_allocation_dashboard/);
  assert.match(source, /periodScope/);
  assert.match(source, /dashboardMode/);
  assert.match(source, /scope:\s*periodScope\.value/);
  assert.match(source, /mode:\s*dashboardMode\.value/);
});

test("allocation dashboard renders one second-level summary table with a grand total", () => {
  assert.ok(source.includes("费用汇总"));
  assert.match(source, /summaryRows/);
  assert.match(source, /isSubtotal/);
  assert.match(source, /isGrandTotal/);
  assert.match(source, /projectColumns/);
  assert.match(source, /v-for="project in projectColumns"/);
  assert.doesNotMatch(source, /detailRows/);
  assert.doesNotMatch(source, /detail_rows/);
  assert.doesNotMatch(source, /台账明细/);
  assert.doesNotMatch(source, /voucher_no/);
});

test("allocation dashboard exposes the three accounting views from the workbook", () => {
  assert.ok(source.includes("汇总"));
  assert.ok(source.includes("资本化"));
  assert.ok(source.includes("费用化"));
  assert.match(source, /modeOptions/);
});

test("allocation dashboard uses compact project codes and sticky grouped columns", () => {
  assert.match(source, /project\.project_code/);
  assert.doesNotMatch(source, /\{\{\s*project\.label\s*\}\}/);
  assert.match(source, /:title="project\.project_name"/);
  assert.match(source, /secondLevelText/);
  assert.match(source, /class="c1"/);
  assert.match(source, /class="c2"/);
  assert.match(source, /position: sticky/);
});

test("allocation dashboard uses the shared R&D page shell with three metric cards", () => {
  assert.match(source, /<RdPage /);
  assert.match(source, /<RdPeriod \/>/);
  assert.match(source, /<RdKpi /);
  assert.ok(source.includes('totalAmount: "分摊合计"'));
  assert.ok(source.includes('projectCount: "项目数"'));
  assert.ok(source.includes('accountCount: "科目数"'));
  assert.match(source, /second_level_count/);
  assert.match(source, /third_level_count/);
});

test("allocation dashboard drops the redundant refresh button and icon tiles", () => {
  assert.doesNotMatch(source, /refresh/i);
  assert.doesNotMatch(source, /@click="load"/);
  assert.doesNotMatch(source, /toUpperCase\(\)\.slice/);
  // 切换期间、范围、口径仍会自动重新加载
  assert.match(source, /watch\(period, \(\) => load\(\)\)/);
  assert.match(source, /watch\(periodScope, \(\) => load\(\)\)/);
  assert.match(source, /watch\(dashboardMode, \(\) => load\(\)\)/);
});

test("allocation dashboard ranks projects in a single-colour bar card above the table", () => {
  assert.match(source, /rankProjects/);
  assert.ok(source.includes("各项目承担"));
  assert.match(source, /class="rank wide"/);
  assert.ok(source.indexOf("{{ TEXT.rankTitle }}") < source.indexOf('<table class="matrix">'));
});

test("allocation dashboard total row is a slim bold row, not a dark filled block", () => {
  assert.doesNotMatch(source, /bg-gray-900/);
  assert.match(source, /return "t"/);
  assert.match(source, /return "g"/);
});

test("allocation dashboard keeps the Excel export and the error and empty states", () => {
  assert.match(source, /exportTableWorkbook/);
  assert.match(source, /exportCurrentAllocationDashboard/);
  assert.match(source, /看板加载失败/);
  assert.match(source, /noData/);
});
