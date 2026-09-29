import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  buildFields, calendarCells, createLatest, dayRows, departmentLabel, formSummary, groupMine, hoursOfMode, mergeDays, modeOfHours, numText,
  rangeText, rejectionOf, returnedDrafts, shiftPeriod, statusPill, stepHours, stepRole, stepStates, subjectFor, teamBars,
  totalHours, typeBadge, typeForPath, waitedDays, workedSpan,
} from "../src/lib/attendanceView.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("the page type follows the route", () => {
  assert.equal(typeForPath("/approval/leave"), "请假申请");
  assert.equal(typeForPath("/approval/leave/OA-1"), "请假申请");
  assert.equal(typeForPath("/approval/overtime/OA-1"), "加班申请");
  assert.equal(typeForPath("/approval/comp-time"), "调休申请");
});

test("day modes map to hours and respect the hours left on that day", () => {
  assert.equal(hoursOfMode("full"), 8);
  assert.equal(hoursOfMode("half"), 4);
  assert.equal(hoursOfMode("none"), 0);
  assert.equal(hoursOfMode("full", 4), 4);
  assert.equal(hoursOfMode("half", 0), 0);
  assert.deepEqual([8, 4, 0, 2.5].map(modeOfHours), ["full", "half", "none", "custom"]);
  assert.equal(stepHours(5.5, 0.5, 24), 6);
  assert.equal(stepHours(0, -0.5, 24), 0);
  assert.equal(stepHours(23.75, 0.5, 24), 24);
  assert.equal(stepHours(3, 0.5, 3), 3);
});

test("changing the dates keeps the hours the user already chose", () => {
  const server = [{ work_date: "2026-10-13", hours: 8, max_hours: 8, conflict: null }, { work_date: "2026-10-14", hours: 8, max_hours: 8, conflict: null }, { work_date: "2026-10-15", hours: 4, max_hours: 4, conflict: null }];
  const before = [{ work_date: "2026-10-13", hours: 4 }, { work_date: "2026-10-15", hours: 8 }];
  const merged = mergeDays(server, before);
  assert.deepEqual(merged.map((day) => [day.work_date, day.hours]), [["2026-10-13", 4], ["2026-10-14", 8], ["2026-10-15", 4]]);
  assert.equal(totalHours(merged), 16);
});

test("rows between the dates show work days, rest days and days already booked", () => {
  const days = [
    { work_date: "2026-10-15", hours: 8, max_hours: 8, conflict: null },
    { work_date: "2026-10-16", hours: 0, max_hours: 0, conflict: { request: "OA-1", text: "10月16日已有请假申请 OA-1（审批中）" } },
    { work_date: "2026-10-19", hours: 8, max_hours: 8, conflict: null },
  ];
  const rows = dayRows("2026-10-15", "2026-10-19", days);
  assert.deepEqual(rows.map((row) => [row.date, row.kind]), [["2026-10-15", "work"], ["2026-10-16", "conflict"], ["2026-10-17", "rest"], ["2026-10-18", "rest"], ["2026-10-19", "work"]]);
  assert.equal(rows[0].week, "周四");
  assert.deepEqual(dayRows("2026-10-19", "2026-10-15", days), []);
  assert.equal(dayRows("2026-10-17", "2026-10-17", [{ work_date: "2026-10-17", hours: 8, max_hours: 24, conflict: null }], true)[0].kind, "ot");
});

test("the summary shows the effect on the balance or the monthly cap and says why it cannot be submitted", () => {
  const days = [{ work_date: "2026-09-30", hours: 8 }, { work_date: "2026-10-01", hours: 4 }];
  const annual = { available_hours: 88, eligible: true };
  const year = formSummary({ requestType: "请假申请", leaveType: "年假", days, annual });
  assert.equal(year.big, "1.5");
  assert.equal(year.impact, "年假余额 88 → 76 小时");
  assert.equal(year.blocked, "");
  const short = formSummary({ requestType: "请假申请", leaveType: "年假", days, annual: { available_hours: 8, eligible: true } });
  assert.equal(short.impact, "年假不够：还差 4 小时");
  assert.equal(short.blocked, "年假余额不足");
  assert.equal(formSummary({ requestType: "请假申请", leaveType: "年假", days, annual: { available_hours: 88, eligible: false, eligibility_message: "入职不满 12 个月" } }).blocked, "入职不满 12 个月");
  const personal = formSummary({ requestType: "请假申请", leaveType: "事假", days });
  assert.equal(personal.impact, "通过后，9 月工时上限少 8 小时；通过后，10 月工时上限少 4 小时");
  assert.equal(formSummary({ requestType: "请假申请", leaveType: "病假", days }).impact, "不扣年假，也不扣当月工时上限");
  const comp = formSummary({ requestType: "调休申请", days, comp: { available_hours: 16 } });
  assert.equal(comp.impact, "调休余额 16 → 4 小时");
  assert.equal(formSummary({ requestType: "调休申请", days, comp: { available_hours: 4 } }).blocked, "调休余额不足");
  const overtime = formSummary({ requestType: "加班申请", days: [{ work_date: "2026-10-17", hours: 6 }], comp: { available_hours: 16 } });
  assert.equal(overtime.big, "6");
  assert.equal(overtime.impact, "提交后调休额度 16 → 22 小时（1:1）");
  assert.equal(formSummary({ requestType: "请假申请", leaveType: "事假", days: [] }).blocked, "请至少填一天的时长");
});

test("the subject is generated from the type, the length and the start of the reason", () => {
  assert.equal(subjectFor("请假申请", "事假", 16), "事假 2 天");
  assert.equal(subjectFor("请假申请", "年假", 12, "带家人出游"), "年假 1.5 天 · 带家人出游");
  assert.equal(subjectFor("加班申请", "", 6, "版本上线值守很久很久很久很久"), "加班 6 小时 · 版本上线值守很久很久很久");
  assert.equal(subjectFor("调休申请", "", 8), "调休 1 天");
});

const requestRow = (name, status, extra = {}) => ({ name, workflow_status: status, kanban_status: { 草稿: "draft", 待审批: "pending", 已完成: "approved", 已拒绝: "rejected" }[status], ...extra });
const rejected = { operation_log: [{ action: "定向驳回", note: "事由写得不清楚", details: { actor: "chen@tests-x.example.invalid" }, timestamp: "2026-09-18T15:11:06" }] };

test("records are grouped so what needs the employee comes first", () => {
  const rows = [
    requestRow("OA-1", "已完成"), requestRow("OA-2", "待审批"), requestRow("OA-3", "草稿", rejected),
    requestRow("OA-4", "草稿"), requestRow("OA-5", "已拒绝"),
  ];
  const groups = groupMine(rows);
  assert.deepEqual(groups.map((group) => [group.title, group.items.map((row) => row.name)]),
    [["要你处理", ["OA-3"]], ["草稿", ["OA-4"]], ["审批中", ["OA-2"]], ["已完成", ["OA-1"]], ["已驳回或撤回", ["OA-5"]]]);
  assert.deepEqual(groupMine([requestRow("OA-2", "待审批")]).map((group) => group.title), ["审批中"]);
  assert.deepEqual(returnedDrafts(rows).map((row) => row.name), ["OA-3"]);
  assert.deepEqual(rejectionOf(rows[2]), { actor: "chen@tests-x.example.invalid", note: "事由写得不清楚", time: "2026-09-18T15:11:06" });
  assert.equal(rejectionOf(rows[3]), null);
  assert.deepEqual(statusPill(rows[2]), { text: "被退回", tone: "p-brand" });
  assert.equal(statusPill(rows[0]).text, "已通过");
  assert.equal(statusPill(rows[1]).text, "审批中");
  assert.deepEqual(typeBadge({ request_type: "请假申请", leave_type: "年假" }), { text: "年假", tone: "leave" });
  assert.deepEqual(typeBadge({ request_type: "加班申请" }), { text: "加班", tone: "ot" });
});

test("how long a request has been waiting", () => {
  const now = Date.parse("2026-09-28T10:00:00");
  assert.equal(waitedDays({ modified: "2026-09-18 15:11:06.123" }, now), 9);
  assert.equal(waitedDays({}, now), 0);
});

test("the calendar starts on Monday, marks rest days, pending days, today and the days being filled in", () => {
  const cells = calendarCells({
    period: "2026-10", firstWeekday: 3, daysInMonth: 31, today: "2026-10-14",
    workDates: ["2026-10-13", "2026-10-14", "2026-10-15"],
    entries: [
      { date: "2026-10-13", kind: "leave", label: "事假", hours: 8, pending: true, request: "OA-1" },
      { date: "2026-10-15", kind: "overtime", label: "加班", hours: 6, pending: false, request: "OA-2" },
      { date: "2026-10-15", kind: "comp", label: "调休", hours: 2, pending: false, request: "OA-3" },
    ],
    selected: ["2026-10-14"],
  });
  assert.equal(cells.length % 7, 0);
  assert.equal(cells.filter((cell) => cell.blank).slice(0, 3).length, 3);
  const day = (n) => cells.find((cell) => cell.day === n);
  assert.deepEqual([day(13).kind, day(13).pending, day(13).tag], ["leave", true, "事假"]);
  assert.equal(day(14).today, true);
  assert.equal(day(14).chosen, true);
  assert.equal(day(14).tag, "今天");
  assert.equal(day(15).tag, "2 项");
  assert.equal(day(17).off, true);
  assert.equal(day(13).off, false);
});

test("periods move by month and are titled in Chinese", () => {
  assert.equal(shiftPeriod("2026-12", 1), "2027-01");
  assert.equal(shiftPeriod("2026-01", -1), "2025-12");
  assert.equal(rangeText("2026-10-13", "2026-10-14"), "10月13日–14日");
  assert.equal(rangeText("2026-09-30", "2026-10-02"), "9月30日–10月2日");
  assert.equal(rangeText("2026-10-13", "2026-10-13"), "10月13日");
  assert.equal(numText(1.5), "1.5");
  assert.equal(numText(2), "2");
});

test("approval progress shows who is done, who is up and who is waiting, with names", () => {
  const request = {
    workflow_status: "待审批", current_step_index: 2,
    steps: [
      { step_index: 1, label: "直属主管", status: "已通过", approvers: ["chen@tests-x.example.invalid"], acted_on: "2026-09-18T16:00:00" },
      { step_index: 2, label: "人事经理", status: "待审批", approvers: ["zhou@tests-x.example.invalid"] },
      { step_index: 3, label: "总经理", status: "待流转", approvers: ["he@tests-x.example.invalid"] },
    ],
  };
  const steps = stepStates(request, { "chen@tests-x.example.invalid": "陈立", "zhou@tests-x.example.invalid": "周敏" });
  assert.deepEqual(steps.map((step) => [step.who, step.state]), [["陈立", "done"], ["周敏", "current"], ["he", "wait"]]);
  assert.equal(stepStates({ ...request, workflow_status: "已完成" }, {})[1].state, "wait");
});

test("the team chart flags crowded workdays and rest days", () => {
  const bars = teamBars({ days: [
    { date: "2026-10-20", label: "10/20", weekday: "二", off_day: false, approved: ["演示员工14"], pending: [] },
    { date: "2026-10-21", label: "10/21", weekday: "三", off_day: false, approved: ["演示员工14"], pending: ["演示员工151"] },
    { date: "2026-10-24", label: "10/24", weekday: "六", off_day: true, approved: [], pending: [] },
  ] });
  assert.deepEqual(bars.map((bar) => [bar.total, bar.crowded, bar.label]), [[1, false, "1 人"], [2, true, "2 人"], [0, false, "休"]]);
});

test("only the newest of several overlapping requests may apply its result", () => {
  const latest = createLatest();
  const first = latest.begin();
  const second = latest.begin();
  assert.equal(latest.isCurrent(first), false);
  assert.equal(latest.isCurrent(second), true);
});

test("the redesigned page is wired in: routes, real API names, no email addresses in the route", () => {
  const router = read("../src/router.js");
  for (const path of ["/approval/leave", "/approval/overtime", "/approval/comp-time"]) {
    assert.match(router, new RegExp(`path: '${path}', component: attendancePage`));
    assert.match(router, new RegExp(`path: '${path}/:name'[^\\n]*component: attendancePage`));
  }
  assert.match(router, /path: '\/approval\/reimbursement', component: approvalPage/);
  const view = read("../src/lib/attendanceView.js");
  for (const name of ["get_attendance_home", "get_attendance_route", "list_attendance_mine", "list_attendance_review", "list_attendance_reviewed", "get_attendance_request"]) {
    assert.match(view, new RegExp(`attendance_entry\\.${name}`));
  }
  const form = read("../src/components/attendance/AttendanceForm.vue");
  assert.match(form, /person\.name/);
  assert.doesNotMatch(form, /approvers\.join/);
  const detail = read("../src/components/attendance/AttendanceDetail.vue");
  assert.match(detail, /暂不能撤回/);
});

test("names inside step labels and department suffixes are not shown twice", () => {
  assert.equal(stepRole("直属主管：陈立"), "直属主管");
  assert.equal(stepRole("人事经理"), "人事经理");
  assert.equal(departmentLabel("客服部 - RAY"), "客服部");
  assert.equal(departmentLabel("Round3 Review B - RAY"), "Round3 Review B");
  assert.equal(departmentLabel("研发部"), "研发部");
});

test("a request starts on its first day with hours and ends on its last", () => {
  const days = [{ work_date: "2026-10-14", hours: 0 }, { work_date: "2026-10-15", hours: 8 }, { work_date: "2026-10-16", hours: 4 }, { work_date: "2026-10-19", hours: 0 }];
  assert.deepEqual(workedSpan(days, "2026-10-14", "2026-10-19"), { from: "2026-10-15", to: "2026-10-16" });
  assert.deepEqual(workedSpan([], "2026-10-14", "2026-10-19"), { from: "2026-10-14", to: "2026-10-19" });
});

test("the submitted fields only carry days that have hours, so the dates always match the details", () => {
  // 验收时发现：选的第一天已被占用（0 小时）时，起止日期变成第二天，明细里却还留着第一天，服务端拒绝。
  const days = [
    { work_date: "2026-09-28", hours: 0, max_hours: 0, conflict: { request: "OA-1" } },
    { work_date: "2026-09-29", hours: 8 }, { work_date: "2026-09-30", hours: 0 }, { work_date: "2026-10-01", hours: 4 },
  ];
  const fields = buildFields({ requestType: "请假申请", leaveType: "年假", from: "2026-09-28", to: "2026-10-02", days, subject: "", reason: " 带家人出游 " });
  assert.equal(fields.from_date, "2026-09-29");
  assert.equal(fields.to_date, "2026-10-01");
  assert.deepEqual(JSON.parse(fields.attendance_days), [{ work_date: "2026-09-29", hours: 8 }, { work_date: "2026-10-01", hours: 4 }]);
  assert.equal(fields.subject, "年假 1.5 天 · 带家人出游");
  assert.equal(fields.leave_type, "年假");
  assert.equal(fields.reason, "带家人出游");
  assert.equal(buildFields({ requestType: "加班申请", leaveType: "事假", from: "2026-10-17", to: "2026-10-17", days: [{ work_date: "2026-10-17", hours: 6 }], subject: "值守", reason: "" }).leave_type, "");
});
