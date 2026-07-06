import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/TimesheetEntry.vue", import.meta.url), "utf8");

test("timesheet entry constrains work date to selected period", () => {
  assert.match(source, /const dateMin = computed/);
  assert.match(source, /const dateMax = computed/);
  assert.match(source, /:min="dateMin"/);
  assert.match(source, /:max="dateMax"/);
  assert.ok(source.includes("\u586b\u62a5\u65e5\u671f\u5fc5\u987b\u5728\u4f1a\u8ba1\u671f\u95f4\u5185"));
});

test("timesheet entry shows Frappe validation messages", () => {
  assert.match(source, /function serverMessage/);
  assert.match(source, /_server_messages/);
  assert.match(source, /serverMessage\(saver\.error/);
  assert.match(source, /serverMessage\(e,/);
});

test("project labels do not use a broken question mark separator", () => {
  assert.doesNotMatch(source, /\$\{code\} \? \$\{/);
});

test("project code and project name are both editable inputs", () => {
  assert.doesNotMatch(source, /\u9879\u76ee\u4ee3\u7801 \/ \u9879\u76ee\u540d\u79f0/);
  assert.ok(source.includes("\u9879\u76ee\u4ee3\u7801"));
  assert.ok(source.includes("\u9879\u76ee\u540d\u79f0"));
  assert.match(source, /project_code: ""/);
  assert.match(source, /project_name: ""/);
  assert.match(source, /function projectKey/);
  assert.match(source, /v-model="form\.project_code"/);
  assert.match(source, /v-model="form\.project_name"/);
  assert.doesNotMatch(source, /const selectedProjectCode = ref/);
  assert.doesNotMatch(source, /const selectedProjectName = ref/);
  assert.doesNotMatch(source, /v-model="selectedProjectCode"/);
  assert.doesNotMatch(source, /v-model="selectedProjectName"/);
  assert.match(source, /projectLabel\(project\)/);
  assert.doesNotMatch(source, /项目选择/);
  assert.doesNotMatch(source, /选择已有代码/);
  assert.ok(source.includes("选择项目代码"));
  assert.doesNotMatch(source, /选择已有名称/);
  assert.ok(source.includes("选择项目名称"));
  assert.match(source, /const activeProjectPicker = ref\(""\)/);
  assert.match(source, /const filteredCodeProjects = computed/);
  assert.match(source, /const filteredNameProjects = computed/);
  assert.match(source, /function chooseProject/);
  assert.match(source, /function toggleProjectPicker/);
  assert.match(source, /activeProjectPicker === 'code'/);
  assert.match(source, /activeProjectPicker === 'name'/);
  assert.match(source, /@mousedown\.prevent="chooseProject\(project\)"/);
  assert.match(source, /&#9662;/);
  assert.doesNotMatch(source, /list="rd-project-codes"/);
  assert.doesNotMatch(source, /list="rd-project-names"/);
  assert.doesNotMatch(source, /<datalist id="rd-project-codes">/);
  assert.doesNotMatch(source, /<datalist id="rd-project-names">/);
  assert.doesNotMatch(source, /<select[^>]+selectedProjectCode/);
  assert.doesNotMatch(source, /<select[^>]+selectedProjectName/);
  assert.match(source, /projectByCode/);
  assert.match(source, /projectByName/);
  assert.match(source, /watch\(\(\) => form\.project_code,/);
  assert.match(source, /watch\(\(\) => form\.project_name,/);
  assert.match(source, /project_code: form\.project_code\.trim\(\)/);
  assert.match(source, /project_name: form\.project_name\.trim\(\)/);
  assert.match(source, /project: matchedProject\.name/);
  assert.doesNotMatch(source, /\u9879\u76ee\u4ee3\u7801\u548c\u9879\u76ee\u540d\u79f0\u5fc5\u987b\u540c\u65f6\u5339\u914d\u540c\u4e00\u4e2a\u53ef\u586b\u62a5\u9879\u76ee/);
  assert.match(source, /row\.rd_project_code/);
  assert.match(source, /row\.project_name/);
  assert.match(source, /projectOrCode\.rd_project_key/);
});



test("timesheet edit controls remain role-gated", () => {
  assert.match(source, /canEditTimesheetEntry/);
  assert.match(source, /const canEdit = computed/);
  assert.match(source, /v-if="canEdit"/);
  assert.match(source, /canEdit && row\.rd_spa_managed/);
});

test("timesheet details hides backend project identity from the visible table", () => {
  assert.doesNotMatch(source, />\u9879\u76ee\u6807\u8bc6</);
  assert.doesNotMatch(source, /row\.rd_project_key \|\| projectKey/);
  assert.match(source, /projectOrCode\.rd_project_key/);
  assert.match(source, /colspan="8"/);
  assert.match(source, /colspan="5">\u5408\u8ba1/);
});

test("timesheet entry enforces an eight hour day in the UI", () => {
  assert.match(source, /hours > 8/);
  assert.doesNotMatch(source, /hours > 24/);
  assert.ok(source.includes("\u5355\u65e5\u4e0d\u8d85\u8fc7 8 \u5c0f\u65f6"));
  assert.match(source, /max="8"/);
  assert.doesNotMatch(source, /max="24"/);
});
test("timesheet entry shows PLM style hour summary cards and employee picker", () => {
  assert.match(source, /rayher_hr_payroll\.api\.timesheet_entry\.get_rd_hour_summary/);
  assert.match(source, /summaryEmployee/);
  assert.match(source, /selectedSummaryEmployee/);
  assert.match(source, /summaryCards/);
  assert.ok(source.includes("总填报工时"));
  assert.ok(source.includes("填报天数"));
  assert.ok(source.includes("日均工时"));
  assert.ok(source.includes("与标准差值"));
  assert.ok(source.includes("查看员工"));
  assert.match(source, /summary\.reload\(\)/);
});


test("timesheet entry requires project values from project management", () => {
  assert.doesNotMatch(source, /无匹配项目，可直接输入后保存/);
  assert.ok(source.includes("无匹配项目，请先在项目管理中新增"));
  assert.ok(source.includes("选择项目代码"));
  assert.ok(source.includes("选择项目名称"));
});


test("timesheet entry blocks save when project code and name do not match", () => {
  assert.match(source, /if \(!matchedProject\)/);
  assert.ok(source.includes("项目代码和项目名称必须匹配项目管理中的可填报项目"));
});
