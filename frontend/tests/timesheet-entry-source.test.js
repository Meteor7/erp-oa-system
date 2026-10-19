import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const page = read("../src/pages/TimesheetEntry.vue");
const sheet = read("../src/components/timesheet/EntrySheet.vue");
const board = read("../src/components/timesheet/EntryBoard.vue");
const roster = read("../src/components/timesheet/EntryRoster.vue");
const drawer = read("../src/components/timesheet/EntryImportDrawer.vue");
const view = read("../src/lib/timesheetEntryView.js");
// 页面拆成了 页面 + 组件 + 纯函数，原来针对单个文件的断言改为针对整体。
const source = [page, sheet, board, roster, drawer, view].join("\n");

test("timesheet entry uses grouped monthly APIs and never asks for a work date", () => {
  assert.match(page, /monthly_timesheet_entry\.list_monthly_entries/);
  assert.match(page, /monthly_timesheet_entry\.save_monthly_entries/);
  assert.doesNotMatch(source, /type="date"/);
  assert.doesNotMatch(source, /work_date/);
  assert.doesNotMatch(source, /from_time/);
});

test("row removal is staged locally and persisted by the single atomic save", () => {
  assert.match(page, /function removeRow\([^)]+\)[\s\S]+entries\.value\.splice/);
  assert.ok(page.includes("该行已移出表格，点击保存后生效"));
  assert.doesNotMatch(source, /remover\.submit/);
});

test("timesheet entry is a master-detail sheet with a searchable project picker", () => {
  assert.ok(page.includes("研发工时填报"));
  assert.ok(page.includes("个人填报"));
  assert.ok(page.includes("填报进度"));
  assert.ok(roster.includes("搜索姓名或工号"));
  assert.ok(roster.includes("未填满"));
  assert.ok(roster.includes("超上限"));
  assert.ok(sheet.includes("项目分配"));
  assert.ok(sheet.includes("已分配"));
  assert.ok(sheet.includes("剩余"));
  assert.ok(sheet.includes("备注"));
  assert.ok(sheet.includes("搜索项目"));
  assert.ok(sheet.includes("上月用过"));
  assert.ok(sheet.includes("复制上月"));
  assert.ok(sheet.includes("批量导入"));
  assert.ok(sheet.includes("把剩余小时平均分给现有项目"));
  assert.ok(sheet.includes("清空"));
  assert.match(page, /class="split ts-split"[^>]*solo/);
  // 项目可能有几十个：用搜索选择器，不再一排 chip
  assert.match(sheet, /pickerOptions/);
  assert.match(view, /limit = 8/);
});

test("the save button lives in the sheet header and the bottom savebar is gone", () => {
  assert.doesNotMatch(page, /savebar/);
  assert.match(page, /@save="saveRows"/);
  assert.match(page, /const saveDisabled = computed\(\(\) => saving\.value \|\| overLimit\.value \|\| !dirty\.value\)/);
  assert.match(page, /:save-disabled="saveDisabled"/);
  assert.match(sheet, /emit\('save'\)/);
  assert.match(sheet, /:disabled="saveDisabled"/);
  assert.ok(sheet.includes("有未保存的修改"));
  assert.ok(sheet.includes("已保存"));
  assert.ok(sheet.includes("保存中…"));
  // 超上限提示仍在
  assert.ok(sheet.includes("超出本月上限"));
});

test("the sheet shows a stacked per-project meter with remaining text", () => {
  assert.match(sheet, /stackedSegments/);
  assert.match(sheet, /remainingMeta/);
  assert.match(sheet, /projectColor\(index\)/);
  assert.match(sheet, /aria-label="删除|:aria-label="`删除/);
});

test("hours keep two decimals, step by one hour, and the days shown are hours divided by eight", () => {
  assert.match(view, /\\d\+\(\?:\\\.\\d\{1,2\}\)\?/);
  assert.match(view, /HOUR_STEP = 1/);
  assert.match(view, /HOURS_PER_DAY = 8/);
  assert.match(view, /\/ HOURS_PER_DAY/);
  assert.match(page, /toFixed\(2\)/);
  assert.match(page, /hours: Number\(row\.hours\)\.toFixed\(2\)/);          // 保存时只发小时，天数由服务端按 小时 ÷ 8 反推
  assert.doesNotMatch(page, /occurrence_days: Number/);
  assert.match(sheet, /rowHours\(row\)/);
  assert.match(sheet, /daysOfHours\(rowHours\(row\)\)/);
  assert.doesNotMatch(source, /v-model[^>]+hours/);
});

test("activity type is supplied by the backend and hidden from the monthly form", () => {
  assert.doesNotMatch(source, /activity_type/);
  assert.doesNotMatch(source, />活动类型</);
});

test("monthly rows keep resolved project identity and the picker explains an empty project list", () => {
  assert.match(view, /project_code/);
  assert.match(view, /project_name/);
  assert.match(view, /function rowFromProject/);
  assert.match(view, /function pickerOptions/);
  assert.ok(sheet.includes("无匹配项目，请先在项目管理中新增"));
});

test("entry mutations remain role-gated and show server validation messages", () => {
  assert.match(page, /canEditTimesheetEntry/);
  assert.match(page, /const canEdit = computed/);
  assert.match(page, /const canEditSelection = computed/);
  assert.match(page, /if \(!canEditSelection\.value\) return;/);
  assert.match(sheet, /v-if="editable"/);
  assert.match(view, /function serverMessage/);
  assert.match(view, /_server_messages/);
  assert.match(page, /serverMessage\(error/);
});

test("monthly import and export contain hours and the derived days but no technical dates", () => {
  assert.match(drawer, /parseTimesheetPaste/);
  assert.match(drawer, /importTimesheetWorkbookFile/);
  assert.match(page, /exportTableWorkbook/);
  assert.match(page, /async function exportCurrent/);
  assert.ok(page.includes("折合天数"));
  assert.ok(page.includes("工时(小时)"));
  assert.doesNotMatch(source, /label: "日期"/);
  // 抽屉挂到 body，外层带 rd 类才能吃到样式；导入只收当前所选人员
  assert.match(drawer, /<Teleport to="body">/);
  assert.match(drawer, /class="rd"/);
  assert.ok(drawer.includes("导入文件中的研发人员必须与当前选择一致"));
});

test("legacy daily data is read-only and everyone sees the employees they are allowed to", () => {
  assert.match(page, /const hasLegacySources = computed/);
  assert.match(page, /&& !hasLegacySources\.value/);
  assert.match(page, /employees\.value\.length > 1/);
  assert.match(page, /editable_employees/);
  assert.match(page, /get_monthly_options/);
  assert.ok(sheet.includes("历史按日记录不能在月度视图中直接修改"));
  assert.ok(page.includes("只读："));
  assert.doesNotMatch(source, /该员工本月已有按日工时/);
});

test("monthly work limit shows days hours and calendar fallback", () => {
  assert.match(page, /hour_limit/);
  assert.match(page, /calendar_source/);
  assert.match(view, /可填/);
  assert.match(view, /已批请假/);
  assert.ok(sheet.includes("未配置假日表，按周一至周五计算"));
  assert.ok(sheet.includes("超出本月上限"));
});

test("monthly saves submit the revision returned by the loaded snapshot", () => {
  assert.match(page, /const loadedRevision = ref/);
  assert.match(page, /loadedRevision\.value = String\(monthly\.data\?\.revision/);
  assert.match(page, /expected_revision: loadedRevision\.value/);
});

test("period is the shared global period and the page is month-only", () => {
  assert.match(page, /from "\.\.\/lib\/period"/);
  assert.match(page, /<RdPeriod/);
  assert.match(page, /setPeriodScope\("month"\)/);
});

test("fill-progress board reads the progress endpoint and reminders go through the reminder endpoint", () => {
  assert.match(page, /monthly_timesheet_entry\.get_fill_progress/);
  assert.match(page, /monthly_timesheet_entry\.remind_timesheet_fill/);
  assert.match(page, /employees: JSON\.stringify\(list\)/);
  assert.match(page, /refreshProgress\(\)/);
  assert.match(page, /defaultTab|tabChoice/);
  assert.ok(board.includes("需要跟进的人"));
  assert.ok(board.includes("催办所选"));
  assert.ok(board.includes("催办全部未填"));
  assert.ok(board.includes("批量催办"));
  assert.ok(board.includes("导出名单"));
  assert.match(board, /followUpRows/);
  assert.match(board, /remindOpen/);
  assert.match(board, /REMIND_CLOSED_TEXT/);
  assert.match(board, /showDepartment/);
  assert.match(board, /kind\.value === 'all'/);
  // 旧的红色截止横幅和四张指标卡已经换成一张汇总卡
  assert.doesNotMatch(board, /RdKpi|deadlineTone/);
  assert.doesNotMatch(board, /一键催办|填报完成率/);
});

test("reminders are locked once the month is past its deadline", () => {
  assert.match(page, /remindClosed\(progressData\.value\?\.deadline\)/);
  assert.match(page, /Boolean\(progressData\.value\?\.can_remind\) && !remindIsClosed\.value/);
  assert.match(board, /remindClosed\(props\.progress\?\.deadline\)/);
  assert.match(board, /disabled :title="REMIND_CLOSED_TEXT"/);
  assert.ok(view.includes("该月已截止/已分摊，无需催办"));
});

test("the page ships no demo-only controls", () => {
  assert.doesNotMatch(source, /演示角色/);
  assert.doesNotMatch(source, /保留与新增的功能/);
});

test("the follow-up list scrolls inside its card with a sticky header and a head-count footer", () => {
  assert.match(board, /<div class="tbl ts-scroll">/);
  assert.match(board, /共 \{\{ rows\.length \}\} 人/);
  const css = read("../src/styles/rdTimesheet.css");
  assert.match(css, /\.rd \.ts-scroll \{ max-height: 560px; overflow: auto; \}/);
  // the sticky header comes from the shared table style
  assert.match(read("../src/styles/rdUi.css"), /\.rd th \{[^}]*position: sticky; top: 0;/);
  // the department list is untouched (no scroll box)
  assert.doesNotMatch(board, /class="card ts-scroll/);
});

test("redesigned pages carry product copy, not design commentary", () => {
  const pages = [
    source,
    read("../src/pages/Projects.vue"),
    read("../src/pages/ExpenseImport.vue"),
    read("../src/pages/Allocation.vue"),
  ].join("\n");
  for (const phrase of ["点一个部门，右边只看它", "是默认状态", "不再每行都贴标签", "表头固定", "点单元格直接编辑", "为示意", "上月没有工时记录，所以没有"]) {
    assert.ok(!pages.includes(phrase), phrase);
  }
  assert.doesNotMatch(pages, /示意/);
});
