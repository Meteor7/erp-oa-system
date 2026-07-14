import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/Timesheet.vue", import.meta.url), "utf8");

test("timesheet page is named as the R&D timesheet report table", () => {
  assert.match(source, /title: "\\u7814\\u53d1\\u5de5\\u65f6\\u62a5\\u8868"/);
  assert.doesNotMatch(source, /title: "\\u7814\\u53d1\\u5de5\\u65f6\\u8868"/);
  assert.doesNotMatch(source, /title: "\\u7814\\u53d1\\u5de5\\u65f6\\u62a5\\u544a"/);
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

test("timesheet pivot uses a wider scrollable table layout", () => {
  assert.match(source, /overflow-x-auto/);
  assert.match(source, /max-h-\[70vh\]/);
  assert.match(source, /min-w-max/);
  assert.match(source, /sticky left-0/);
  assert.match(source, /min-w-\[96px\]/);
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
