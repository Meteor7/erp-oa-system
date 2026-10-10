import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  addDays, applyFilters, dayStatus, filtersActive, infoMap, inRange, isSlow, lengthText, monthGrid, monthOf, pickRange, pickSelected, rowDates,
  searchMatch, shiftMonth, statusInfo, stripCells, timeMatch, whenText,
} from "../src/lib/attendanceFlow.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const NOW = Date.parse("2026-10-15T12:00:00");
const TODAY = "2026-10-15";

const leave = (days, extra = {}) => ({
  name: "OA-1", request_type: "请假申请", leave_type: "事假", employee_name: "演示员工117", department: "研发软件部 - RAY", reason: "家里有事", workflow_status: "待审批",
  attendance_days: days.map(([work_date, hours]) => ({ work_date, hours })), from_date: days[0][0], to_date: days[days.length - 1][0], ...extra,
});

// ---------------------------------------------------------------- 筛选

test("the time filter looks at the days a request really uses", () => {
  assert.deepEqual(rowDates(leave([["2026-10-26", 8], ["2026-10-27", 8]])), ["2026-10-26", "2026-10-27"]);
  assert.deepEqual(rowDates({ from_date: "2026-10-20" }), ["2026-10-20"]);
  assert.equal(addDays("2026-10-30", 3), "2026-11-02");
  const at = (date) => leave([[date, 8]]);
  assert.equal(timeMatch(at("2026-10-16"), "week", TODAY), true);
  assert.equal(timeMatch(at("2026-10-22"), "week", TODAY), true);     // 今天 + 7 天
  assert.equal(timeMatch(at("2026-10-23"), "week", TODAY), false);
  assert.equal(timeMatch(at("2026-10-14"), "week", TODAY), false);    // 已经过去的不算未来 7 天
  assert.equal(timeMatch(at("2026-10-30"), "month", TODAY), true);
  assert.equal(timeMatch(at("2026-11-02"), "month", TODAY), false);
  assert.equal(timeMatch(at("2026-11-02"), "all", TODAY), true);
  assert.equal(timeMatch({}, "week", TODAY), true);                   // 没有日期的不被筛掉
  assert.equal(timeMatch(leave([["2026-10-14", 8], ["2026-10-16", 8]]), "week", TODAY), true);   // 有一天落在范围里就算
});

test("slow means waiting more than three days; search looks at the person, the number and the reason", () => {
  assert.equal(isSlow({ submitted_on: "2026-10-11 12:00:00" }, NOW), true);      // 4 天
  assert.equal(isSlow({ submitted_on: "2026-10-12 12:00:00" }, NOW), false);     // 正好 3 天
  assert.equal(isSlow({}, NOW), false);
  const row = leave([["2026-10-26", 8]], { name: "OA-2026-18311", reason: "回老家处理" });
  assert.equal(searchMatch(row, "吴大"), true);
  assert.equal(searchMatch(row, "18311"), true);
  assert.equal(searchMatch(row, "老家"), true);
  assert.equal(searchMatch(row, "oa-2026"), true);
  assert.equal(searchMatch(row, "演示员工129"), false);
  assert.equal(searchMatch(row, "  "), true);
});

test("filters combine, and 'active' says whether any is on", () => {
  const rows = [
    leave([["2026-10-16", 8]], { name: "A", submitted_on: "2026-10-10 09:00:00" }),
    leave([["2026-10-30", 8]], { name: "B", request_type: "调休申请", leave_type: "", submitted_on: "2026-10-15 09:00:00" }),
    leave([["2026-10-17", 6]], { name: "C", request_type: "加班申请", leave_type: "", employee_name: "演示员工112", submitted_on: "2026-10-14 09:00:00" }),
  ];
  const names = (state) => applyFilters(rows, state, { today: TODAY, now: NOW }).map((row) => row.name);
  assert.deepEqual(names({}), ["A", "B", "C"]);
  assert.deepEqual(names({ type: "调休" }), ["B"]);
  assert.deepEqual(names({ time: "week" }), ["A", "C"]);
  assert.deepEqual(names({ slow: true }), ["A"]);
  assert.deepEqual(names({ query: "静静" }), ["C"]);
  assert.deepEqual(names({ type: "请假", time: "week", slow: true }), ["A"]);
  assert.deepEqual(names({ type: "加班", slow: true }), []);
  assert.equal(filtersActive({}), false);
  assert.equal(filtersActive({ type: "all", time: "all", slow: false, query: " " }), false);
  assert.equal(filtersActive({ time: "week" }), true);
  assert.equal(filtersActive({ slow: true }), true);
  assert.equal(filtersActive({ query: "a" }), true);
  assert.equal(filtersActive({ type: "加班" }), true);
});

// ---------------------------------------------------------------- 一行上的文字

test("when and how long: one day shows its slot, several days show the range", () => {
  assert.equal(whenText(leave([["2026-10-30", 8]])), "10/30 周五 · 全天");
  assert.equal(whenText(leave([["2026-10-22", 3]])), "10/22 周四 · 上午");
  assert.equal(whenText(leave([["2026-10-22", 5]])), "10/22 周四 · 下午");
  assert.equal(whenText(leave([["2026-10-26", 8], ["2026-10-27", 8]])), "10/26 周一 – 10/27 周二");
  assert.equal(whenText(leave([["2026-10-17", 6]], { request_type: "加班申请", leave_type: "" })), "10/17 周六 · 6 小时");
  assert.equal(whenText({ from_date: "2026-10-20", to_date: "2026-10-20" }), "10/20 周二 · 全天");   // 只有起止日期的旧申请：按周一到周五 8 小时
  assert.equal(whenText({}), "");
  assert.equal(lengthText(leave([["2026-10-26", 8], ["2026-10-27", 8]])), "2 天 · 16 小时");
  assert.equal(lengthText(leave([["2026-10-22", 3]])), "3 小时");
});

test("the right-hand cell says how long it has waited, what happened, or where it is", () => {
  const waiting = (submitted) => leave([["2026-10-26", 8]], { submitted_on: submitted });
  assert.deepEqual(statusInfo(waiting("2026-10-15 12:00:00"), "todo", NOW), { tag: null, sub: "刚刚提交" });
  assert.deepEqual(statusInfo(waiting("2026-10-13 12:00:00"), "todo", NOW), { tag: { text: "等了 2 天", tone: "warn" }, sub: "" });
  assert.deepEqual(statusInfo(waiting("2026-10-09 12:00:00"), "todo", NOW), { tag: { text: "等了 6 天", tone: "bad" }, sub: "" });
  const mine = leave([["2026-10-26", 8]], { steps: [{ step_index: 1, approvers: ["a@tests-x.example.invalid"], status: "" }], current_step_index: 1, current_step_label: "直属主管：演示员工132" });
  assert.deepEqual(statusInfo(mine, "mine", NOW, { "a@tests-x.example.invalid": "演示员工132" }), { tag: { text: "审批中", tone: "info" }, sub: "等待 演示员工132（直属主管）" });
  assert.deepEqual(statusInfo({ ...mine, workflow_status: "已完成" }, "mine", NOW), { tag: { text: "已通过", tone: "ok" }, sub: "" });
  assert.deepEqual(statusInfo({ my_status: "已通过", acted_on: "2026-10-09 14:30:12" }, "done", NOW), { tag: { text: "已同意", tone: "ok" }, sub: "10-09 14:30" });
  assert.deepEqual(statusInfo({ my_status: "已拒绝", acted_on: "2026-10-09 14:30:12" }, "done", NOW).tag, { text: "已驳回", tone: "bad" });
});

test("the selected row stays while it exists and falls back to the first", () => {
  const rows = [{ name: "A" }, { name: "B" }];
  assert.equal(pickSelected(rows, "B").name, "B");
  assert.equal(pickSelected(rows, "gone").name, "A");
  assert.equal(pickSelected(rows, "").name, "A");
  assert.equal(pickSelected([], "A"), null);
});

// ---------------------------------------------------------------- 新建页的月历

test("month helpers", () => {
  assert.equal(monthOf("2026-10-15"), "2026-10");
  assert.equal(shiftMonth("2026-10", 1), "2026-11");
  assert.equal(shiftMonth("2026-01", -1), "2025-12");
  assert.equal(shiftMonth("2026-12", 1), "2027-01");
  const grid = monthGrid("2026-10");
  assert.equal(grid.title, "2026 年 10 月");
  assert.deepEqual([grid.from, grid.to], ["2026-10-01", "2026-10-31"]);
  assert.deepEqual(grid.cells.slice(0, 4).map((cell) => cell && cell.day), [null, null, null, 1]);   // 10 月 1 日是周四，周一开头前面补 3 格
  assert.equal(grid.cells.length, 34);
  assert.equal(monthGrid("2026-06").cells.filter((cell) => cell === null).length, 0);                  // 6 月 1 日是周一
});

test("picking days: start, then end; one click is one day; an earlier click restarts; overtime is one day unless 'several days'", () => {
  let state = { from: "", to: "", awaiting: false };
  state = pickRange(state, "2026-10-19");
  assert.deepEqual(state, { from: "2026-10-19", to: "2026-10-19", awaiting: true });         // 点一次就是这一天
  state = pickRange(state, "2026-10-21");
  assert.deepEqual(state, { from: "2026-10-19", to: "2026-10-21", awaiting: false });
  state = pickRange(state, "2026-10-26");
  assert.deepEqual(state, { from: "2026-10-26", to: "2026-10-26", awaiting: true });         // 选完以后再点是重新开始
  state = pickRange(state, "2026-10-20");
  assert.deepEqual(state, { from: "2026-10-20", to: "2026-10-20", awaiting: true });         // 比开始日早：改成新的开始日
  state = pickRange(state, "2026-10-20");
  assert.deepEqual(state, { from: "2026-10-20", to: "2026-10-20", awaiting: false });        // 同一天：就是这一天
  assert.deepEqual(pickRange({ from: "2026-10-19", to: "2026-10-21", awaiting: false }, "2026-10-24", { multi: false }), { from: "2026-10-24", to: "2026-10-24", awaiting: false });
  assert.equal(inRange("2026-10-20", "2026-10-19", "2026-10-21"), true);
  assert.equal(inRange("2026-10-22", "2026-10-19", "2026-10-21"), false);
  assert.equal(inRange("2026-10-19", "2026-10-19", ""), true);
  assert.equal(inRange("2026-10-19", "", ""), false);
});

test("a day on the calendar is workable, a rest day, full, or partly taken", () => {
  const info = infoMap([
    { work_date: "2026-10-19", max_hours: 8, conflict: null }, { work_date: "2026-10-20", max_hours: 0, conflict: { request: "OA-9", text: "已有请假" } },
    { work_date: "2026-10-21", max_hours: 3, conflict: null },
  ]);
  assert.equal(dayStatus("2026-10-19", info), "work");
  assert.equal(dayStatus("2026-10-20", info), "busy");
  assert.equal(dayStatus("2026-10-21", info), "part");
  assert.equal(dayStatus("2026-10-24", info), "rest");                 // 服务端没给：休息日或假期
  assert.equal(dayStatus("2026-10-24", info, true), "work");           // 加班可以选休息日
  assert.equal(dayStatus("2026-10-21", info, true), "work");           // 加班按 24 小时算，不显示"部分占用"
  assert.equal(dayStatus("2026-10-24", null), "work");                 // 这个月还没取到：都能点，提交时服务端校验
});

test("the date strip keeps two days either side and labels the requested days", () => {
  const cells = stripCells(leave([["2026-10-19", 8], ["2026-10-20", 3]]));
  assert.deepEqual(cells.map((cell) => cell.date), ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"]);
  assert.deepEqual(cells.map((cell) => [cell.hit, cell.text]), [[false, ""], [false, ""], [true, "全天"], [true, "上午"], [false, ""], [false, ""]]);
  assert.deepEqual(cells.map((cell) => cell.off), [true, true, false, false, false, false]);
  assert.equal(cells[2].label, "10/19");
  assert.equal(cells[2].week, "一");
  assert.equal(stripCells(leave([["2026-10-17", 6]], { request_type: "加班申请" }))[2].text, "6h");
  assert.equal(stripCells(leave([["2026-10-19", 4]]))[2].text, "4h");
  assert.equal(stripCells(leave(Array.from({ length: 12 }, (_, index) => [addDays("2026-10-19", index), 8]))).length, 10);   // 最多 10 格
  assert.deepEqual(stripCells({}), []);
});

// ---------------------------------------------------------------- 页面接线（读源码）

test("the list is one card with tabs and a filter bar, and the detail opens beside it", () => {
  const list = read("../src/components/attendance/AttendanceList.vue");
  for (const text of ["时间", "等了超过 3 天", "搜申请人、单号、事由", "清除筛选", "批量同意", "全选"]) assert.ok(list.includes(text), text);
  assert.match(list, /<AttendanceDetail v-if="current"[^>]*variant="panel"/);
  assert.match(list, /@open="emit\('open', current\)"/);                       // 完整页面才进详情页
  assert.match(list, /@changed="emit\('changed'\)"/);
  assert.match(list, /@keydown\.down\.prevent="move\(1\)"/);
  assert.match(list, /applyFilters\(/);
  assert.match(list, /TIME_FILTERS/);
  assert.doesNotMatch(list, /emit\('open', row\)/);                            // 点一行是在右边看，不再整页跳转
  const page = read("../src/pages/AttendanceCenter.vue");
  assert.match(page, /@changed="refreshLists" @navigate="go"/);
  assert.match(page, /attendanceFlowUi\.css/);
});

test("the detail has a narrow panel and a full page that share one set of actions", () => {
  const detail = read("../src/components/attendance/AttendanceDetail.vue");
  assert.match(detail, /v-if="panel"/);
  for (const text of ["完整页面", "批之前先看影响", "同期谁不在", "驳回原因", "确认驳回", "同意", "审批意见（驳回时必填）"]) assert.ok(detail.includes(text), text);
  assert.match(detail, /api\.overlap\(props\.name\)/);
  assert.match(detail, /!row\?\.can_act \|\| row\.request_type === '加班申请'/);        // 只有轮到我审批的请假、调休才查同期
  assert.equal(detail.match(/api\.act\(/g).length, 1);                              // 同意和驳回走同一个函数
  assert.match(detail, /<AttendanceDayStrip/);
  assert.match(detail, /<AttendanceSteps/);
  const view = read("../src/lib/attendanceView.js");
  assert.match(view, /attendance_board_entry\.get_request_overlap/);
});

test("the new page picks dates on a calendar, shows the month's blocked days, and keeps the old rules", () => {
  const form = read("../src/components/attendance/AttendanceForm.vue");
  const picker = read("../src/components/attendance/AttendancePicker.vue");
  assert.match(form, /<AttendancePicker/);
  assert.doesNotMatch(form, /type="date"/);
  assert.match(form, /pickRange\(/);
  assert.match(form, /api\.options\(type, grid\.from, grid\.to\)/);                  // 月历按当前类型取这个月能选的日子
  assert.match(form, /monthLatest\.isCurrent\(token\)/);
  for (const text of ["申请什么", "哪几天", "事由", "本次申请", "通过后的影响", "审批路线"]) assert.ok(form.includes(text), text);
  assert.match(form, /v-if="cannotSubmit && whyNot && !busy"/);                       // 提交不了时直接说差什么
  assert.match(form, /:disabled="cannotSubmit"/);
  assert.match(picker, /disabled: status === 'busy' \|\| \(status === 'rest' && !props\.overtime\)/);
});

test("the flow style sheet is scoped and avoids the shared .r and .bar class names", () => {
  const css = read("../src/styles/attendanceFlowUi.css");
  for (const name of ["af-split", "af-row", "af-fbar", "af-strip", "af-tl", "af-cal", "af-day", "af-sum", "af-bar"]) assert.ok(css.includes(`.${name}`), name);
  const bare = css.split("\n").filter((line) => /^\s*\.[a-z]/.test(line) && !line.includes(".acx"));
  assert.deepEqual(bare, []);
  for (const name of ["AttendanceList", "AttendanceDetail", "AttendanceForm", "AttendancePicker", "AttendanceDayStrip", "AttendanceSteps"]) {
    assert.doesNotMatch(read(`../src/components/attendance/${name}.vue`), /class="(bar|r)"/, name);
  }
});
