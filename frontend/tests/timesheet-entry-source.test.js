import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/TimesheetEntry.vue", import.meta.url), "utf8");

test("timesheet entry uses grouped monthly APIs and never asks for a work date", () => {
  assert.match(source, /monthly_timesheet_entry\.list_monthly_entries/);
  assert.match(source, /monthly_timesheet_entry\.save_monthly_entries/);
  assert.doesNotMatch(source, /type="date"/);
  assert.doesNotMatch(source, /work_date/);
  assert.doesNotMatch(source, /from_time/);
});

test("row removal is staged locally and persisted by the single atomic save", () => {
  assert.match(source, /function removeRow\([^)]+\)[\s\S]+entries\.value\.splice/);
  assert.doesNotMatch(source, /remover\.submit/);
});

test("timesheet entry follows the team-leader monthly table layout", () => {
  assert.ok(source.includes("工时录入（按月）"));
  assert.ok(source.includes("研发人员"));
  assert.ok(source.includes("年份"));
  assert.ok(source.includes("月份"));
  assert.ok(source.includes("项目"));
  assert.ok(source.includes("发生天数"));
  assert.ok(source.includes("工时"));
  assert.ok(source.includes("备注"));
  assert.ok(source.includes("新增一行"));
  assert.ok(source.includes("当月合计"));
  assert.ok(source.includes("上限"));
});

test("occurrence days keep two decimals and hours are read-only days times eight", () => {
  assert.match(source, /step="0\.01"/);
  assert.match(source, /occurrence_days/);
  assert.match(source, /occurrenceDays \* 8/);
  assert.match(source, /toFixed\(2\)/);
  assert.match(source, /readonly/);
  assert.doesNotMatch(source, /v-model[^>]+hours/);
});

test("activity type is supplied by the backend and hidden from the monthly form", () => {
  assert.doesNotMatch(source, /activity_type/);
  assert.doesNotMatch(source, />活动类型</);
});

test("monthly rows keep resolved project identity and editable project search", () => {
  assert.match(source, /project_code/);
  assert.match(source, /project_name/);
  assert.match(source, /function chooseProject/);
  assert.match(source, /filteredProjects/);
  assert.ok(source.includes("无匹配项目，请先在项目管理中新增"));
});

test("entry mutations remain role-gated and show server validation messages", () => {
  assert.match(source, /canEditTimesheetEntry/);
  assert.match(source, /const canEdit = computed/);
  assert.match(source, /v-if="canEditSelection"/);
  assert.match(source, /function serverMessage/);
  assert.match(source, /_server_messages/);
});

test("monthly import and export contain days and hours but no technical dates", () => {
  assert.match(source, /parseTimesheetPaste/);
  assert.match(source, /importTimesheetWorkbookFile/);
  assert.match(source, /exportTableWorkbook/);
  assert.ok(source.includes("发生天数"));
  assert.doesNotMatch(source, /label: "日期"/);
});

test("legacy daily data and all employees render through the unified monthly view", () => {
  assert.match(source, /const isAllEmployees = computed/);
  assert.match(source, /const canEditSelection = computed/);
  assert.ok(source.includes('<option value="">全部员工</option>'));
  assert.match(source, /employee_count/);
  assert.match(source, /v-if="isAllEmployees"/);
  assert.doesNotMatch(source, /该员工本月已有按日工时/);
  assert.doesNotMatch(source, /entries\.value = \[\];\s*return;/);
});
