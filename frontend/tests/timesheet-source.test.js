import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/Timesheet.vue", import.meta.url), "utf8");
const foreignSource = readFileSync(new URL("../src/pages/ForeignRDTimesheet.vue", import.meta.url), "utf8");

test("timesheet page is named as the R&D timesheet report table", () => {
  assert.match(source, /title: "研发工时报表"/);
  assert.doesNotMatch(source, /title: "研发工时表"/);
  assert.doesNotMatch(source, /title: "研发工时报告"/);
});

test("timesheet pivot uses the role-scoped R&D hours API", () => {
  assert.match(source, /rayher_hr_payroll\.api\.timesheet_entry\.list_rd_hours/);
  assert.doesNotMatch(source, /frappe\.desk\.query_report\.run/);
  assert.match(source, /buildEmployeeProjectPivot/);
  assert.match(source, /buildMonthlyProjectRatePivot/);
});

test("timesheet pivot keeps project identity internally but shows project codes", () => {
  assert.match(source, /buildEmployeeProjectPivot/);
  assert.match(source, /buildMonthlyProjectRatePivot/);
  assert.match(source, /\{\{ project\.label \}\}/);
  assert.doesNotMatch(source, /\{\{ p \}\}/);
  assert.doesNotMatch(source, /const p = row\.rd_project_key \|\| row\.project_name \|\| row\.rd_project_code \|\| row\.project/);
});

test("timesheet pivot keeps a scrollable table with sticky header and first column", () => {
  assert.match(source, /class="tbl pv"/);
  assert.match(source, /max-height:70vh/);
  assert.match(source, /<th class="l">/);
  assert.match(source, /<td class="l nw">/);
});

test("timesheet pivot formats displayed hours and rates consistently", () => {
  assert.match(source, /function fmtCell/);
  assert.match(source, /function fmtRate/);
  assert.match(source, /\{\{ fmtCell\(v\) \}\}/);
  assert.match(source, /\{\{ fmt\(row\.total\) \}\}/);
  assert.match(source, /\{\{ fmtRate\(rate\) \}\}%/);
  assert.doesNotMatch(source, /\{\{ v \|\| "" \}\}/);
  assert.doesNotMatch(source, /\{\{ row\.total \}\}/);
  assert.doesNotMatch(source, /\{\{ rate \}\}%/);
});

test("timesheet pivot supports month and year scopes", () => {
  assert.match(source, /periodScope/);
  assert.match(source, /scope: periodScope\.value/);
  assert.match(source, /PERIOD_SCOPES/);
  assert.match(source, /setPeriodScope/);
  assert.match(source, /watch\(periodScope/);
  assert.match(source, /buildMonthlyProjectRatePivot/);
  assert.match(source, /isYearScope/);
  assert.match(source, /yearlyPivot/);
  assert.match(source, /v-if="isYearScope"/);
});

test("timesheet page uses the shared R&D page shell with KPI cards", () => {
  assert.match(source, /<RdPage /);
  assert.match(source, /<RdPeriod \/>/);
  assert.match(source, /<RdSeg /);
  assert.equal((source.match(/<RdKpi /g) || []).length, 3);
  assert.doesNotMatch(source, /<Card /);
});

test("timesheet page compares with last month through one extra call to the same endpoint", () => {
  assert.match(source, /previousPeriod\(period\.value\)/);
  assert.match(source, /previous\.submit\(\{ period: target, scope: "month" \}\)/);
  assert.match(source, /formatDelta\(hoursDelta\(/);
  assert.match(source, /periodScope\.value !== "month"/);
});

test("timesheet page can show each employee's share and emphasise one project column", () => {
  assert.match(source, /value: "share", label: "个人占比"/);
  assert.match(source, /employeeShareRow/);
  assert.match(source, /toggleFocus\(project\.id\)/);
  assert.match(source, /dim: dimmed\(/);
  assert.match(source, /:title="nameOf\(project\.id\)/);
});

test("timesheet page keeps export and avoids charts, colours and demo-only controls", () => {
  assert.match(source, /exportTableWorkbook/);
  assert.match(source, /exportCurrentTimesheetPivot/);
  assert.doesNotMatch(source, /<svg|chart|演示角色|保留与新增/);
  assert.doesNotMatch(source, /rgba\(/);
});

test("foreign R&D timesheet report uses the shared shell, KPI cards and last-month delta", () => {
  assert.match(foreignSource, /rayher_hr_payroll\.api\.foreign_rd_entry\.get_foreign_rd/);
  assert.match(foreignSource, /buildForeignEntityProjectPivot/);
  assert.match(foreignSource, /buildMonthlyProjectRatePivot/);
  assert.match(foreignSource, /<RdPage /);
  assert.equal((foreignSource.match(/<RdKpi /g) || []).length, 3);
  assert.match(foreignSource, /previous\.submit\(\{ period: target, scope: 'month' \}\)/);
  assert.match(foreignSource, /exportTableWorkbook/);
  assert.match(foreignSource, /watch\(periodScope/);
  assert.doesNotMatch(foreignSource, /<Card /);
});
