// 考勤中心首页（部门主管、人事和管理层，2026-10-14 按确认的 demo 改版）的计算：谁不在、未来 14 天、N 月概览、近 5 个工作日、地址里的状态。
import assert from "node:assert/strict";
import test from "node:test";

import {
  addDays, awayView, axisTicks, chartModel, daysText, fold, homeOriginQuery, homeOriginState, homeQuery, homeStateOf, kindText, lengthText,
  md, mondayOf, monthBounds, monthTitle, monthTotals, nearView, nextWorkDays, overviewView, scopeRows, spanText, statusOf, weekLabelOf, weekRange,
} from "../src/lib/attendanceHome.js";
import { backLocation, detailLocation, homeLocation, originOf, originQuery, parseLocation } from "../src/lib/attendanceView.js";

const TODAY = "2026-10-14";   // 周三
const WORK = Array.from({ length: 31 }, (_, index) => addDays("2026-10-01", index))
  .filter((day) => day.startsWith("2026-10") && ![0, 6].includes(new Date(`${day}T00:00:00`).getDay()));

function row(name, employee, kind, days, extra = {}) {
  const names = { A: "甲", B: "乙", C: "丙", D: "丁", E: "戊", F: "己" };
  const depts = { A: "研发软件部 - RAY", B: "客服部 - RAY", C: "研发软件部 - RAY", D: "客服部 - RAY", E: "研发软件部 - RAY", F: "研发软件部 - RAY" };
  const types = { comp: "调休申请", ot: "加班申请", trip: "出差申请" };
  const leaveTypes = { annual: "年假", personal: "事假", sick: "病假" };
  const department = depts[employee];
  return {
    name, employee, employee_name: names[employee], department, department_label: department.replace(" - RAY", ""),
    request_type: types[kind] || "请假申请", kind, leave_type: leaveTypes[kind] || "", workflow_status: "已完成", approved: true,
    current_step_label: "", from_date: days[0]?.[0] || "", to_date: days[days.length - 1]?.[0] || "", travel_destination: "",
    days, month_hours: days.filter(([day]) => day.startsWith("2026-10")).reduce((sum, [, hours]) => sum + hours, 0), ...extra,
  };
}

const ROWS = [
  row("R1", "A", "annual", [["2026-10-14", 8], ["2026-10-15", 8]]),
  row("R2", "B", "personal", [["2026-10-14", 3]]),
  row("R3", "C", "comp", [["2026-10-14", 8]]),
  row("R4", "D", "trip", [["2026-10-14", 8], ["2026-10-15", 8]], { workflow_status: "待办理", travel_destination: "上海" }),
  row("R5", "A", "trip", [["2026-10-14", 8]], { travel_destination: "北京" }),          // 同一天甲在请假：出差那一格不算他
  row("R6", "E", "sick", [["2026-10-14", 8]], { workflow_status: "待审批", approved: false, current_step_label: "人事经理" }),
  row("R7", "B", "ot", [["2026-10-17", 6]]),                                              // 周六加班
  row("R8", "F", "annual", [["2026-10-20", 8]]),
];

// ---------------------------------------------------------------- 小工具
test("dates, lengths, tags and states read the way the demo shows them", () => {
  assert.deepEqual(weekRange(TODAY), ["2026-10-12", "2026-10-18"]);
  assert.equal(mondayOf("2026-10-18"), "2026-10-12");
  assert.equal(mondayOf("2026-10-19"), "2026-10-19");
  assert.equal(md("2026-10-04"), "10/4");
  assert.equal(spanText("2026-10-14", "2026-10-16"), "10/14–16");
  assert.equal(spanText("2026-10-30", "2026-11-02"), "10/30–11/2");
  assert.equal(spanText("2026-10-14", "2026-10-14"), "10/14");
  assert.deepEqual(monthBounds("2026-02"), ["2026-02-01", "2026-02-28"]);
  assert.equal(monthTitle("2026-10", TODAY), "10 月");
  assert.equal(monthTitle("2025-12", TODAY), "2025 年 12 月");
  assert.equal(weekLabelOf("2026-09-28", "2026-10"), "10/1–4");               // 跨月的周只算这个月里的几天
  assert.equal(weekLabelOf("2026-10-26", "2026-10"), "10/26–31");
  // 时长：整天写天，不是整天写小时；加班写小时；出差写天，全在休息日的出差写“休息日”
  assert.equal(lengthText(ROWS[0]), "2 天");
  assert.equal(lengthText(ROWS[1]), "3 小时");
  assert.equal(lengthText(ROWS[6]), "6 小时");
  assert.equal(lengthText(ROWS[3]), "2 天");
  assert.equal(lengthText({ kind: "trip", days: [] }), "休息日");
  assert.equal(lengthText({ kind: "personal" }, 12), "12 小时");
  assert.equal(kindText(ROWS[0]), "年假");
  assert.equal(kindText({ kind: "other", leave_type: "婚假" }), "婚假");
  assert.equal(kindText(ROWS[2]), "调休");
  assert.deepEqual(statusOf(ROWS[5]), { text: "审批中", tone: "pend" });
  assert.deepEqual(statusOf(ROWS[3]), { text: "前台办理中", tone: "quiet" });
  assert.equal(statusOf(ROWS[0]), null);
});

test("days have one decimal, rounded half up like the dashboard card; tiny amounts are '<0.1'", () => {
  assert.equal(daysText(27), "3.4");        // 3.375 天
  assert.equal(daysText(2), "0.3");         // 0.25 天：和看板 _d1(0.25) 一样是 0.3
  assert.equal(daysText(6), "0.8");
  assert.equal(daysText(0), "0");
  assert.equal(daysText(0.3), "<0.1");
  assert.equal(daysText(80), "10");
});

test("the filters at the top: department and name", () => {
  assert.deepEqual(scopeRows(ROWS, { dept: "客服部 - RAY" }).map((item) => item.name), ["R2", "R4", "R7"]);
  assert.deepEqual(scopeRows(ROWS, { q: " 甲 " }).map((item) => item.name), ["R1", "R5"]);
  assert.equal(scopeRows(ROWS, {}).length, ROWS.length);
  assert.deepEqual(scopeRows(null, {}), []);
});

test("more than eight rows fold away behind a button", () => {
  const list = Array.from({ length: 10 }, (_, index) => index);
  assert.deepEqual(fold(list, false), { shown: [0, 1, 2, 3, 4, 5, 6, 7], rest: 2 });
  assert.deepEqual(fold(list, true).shown.length, 10);
  assert.deepEqual(fold(list.slice(0, 8), false), { shown: list.slice(0, 8), rest: 0 });
  assert.deepEqual(fold(list, false, 6).rest, 4);
});

// ---------------------------------------------------------------- 谁不在
test("who is away today: one number per type = people with an approved request; a trip on a leave day counts as leave", () => {
  const view = awayView(ROWS, { today: TODAY, workDates: WORK });
  assert.deepEqual(view.tiles.map((item) => [item.key, item.count]), [["leave", 2], ["comp", 1], ["trip", 1], ["ot", 0]]);   // 甲乙请假（戊审批中不算）；甲那天的出差不算
  assert.equal(view.title, "10/14 周三");
  assert.equal(view.picked, false);
  assert.equal(view.restDay, false);
  // 一张申请一行，审批中的排在最后（“还在审批，不算人数”从这一行起）
  assert.deepEqual(view.rows.slice(0, 5).map((item) => item.name).sort(), ["R1", "R2", "R3", "R4", "R5"]);
  assert.deepEqual([view.rows[5].name, view.pendingFrom], ["R6", 5]);
  // 点一格只看这一类：名单跟着筛，数字不变
  const trips = awayView(ROWS, { today: TODAY, tile: "trip", workDates: WORK });
  assert.deepEqual(trips.rows.map((item) => item.name).sort(), ["R4", "R5"]);
  assert.equal(trips.pendingFrom, -1);
  assert.equal(trips.tiles.find((item) => item.key === "trip").on, true);
  assert.equal(awayView(ROWS, { today: TODAY, tile: "ot" }).emptyText, "没有加班的人");
});

test("this week, a day picked on the chart, and a rest day", () => {
  const week = awayView(ROWS, { today: TODAY, period: "week", workDates: WORK });
  assert.equal(week.title, "本周 10/12–18");
  assert.deepEqual(week.tiles.map((item) => item.count), [2, 1, 1, 1]);          // 本周有周六的加班
  const picked = awayView(ROWS, { today: TODAY, day: "2026-10-20", workDates: WORK });
  assert.deepEqual([picked.title, picked.picked, picked.tiles[0].count], ["10/20 周二", true, 1]);
  const saturday = awayView(ROWS, { today: TODAY, day: "2026-10-17", workDates: WORK });
  assert.deepEqual([saturday.restDay, saturday.tiles[3].count], [true, 1]);
  assert.equal(awayView([], { today: TODAY }).emptyText, "没有人请假、调休、出差或加班");
});

// ---------------------------------------------------------------- 未来 14 天
test("the y axis has integer ticks", () => {
  assert.deepEqual(axisTicks(0).ticks, [0, 1, 2]);
  assert.deepEqual(axisTicks(3).ticks, [0, 1, 2, 3]);
  assert.deepEqual(axisTicks(7), { top: 8, step: 2, ticks: [0, 2, 4, 6, 8] });
  assert.deepEqual(axisTicks(11).ticks, [0, 5, 10, 15]);
});

test("the 14-day chart: one number per bar, stacked by leave type, pending not drawn, weekends marked, today first", () => {
  const model = chartModel(ROWS, { today: TODAY, workDates: WORK, selected: TODAY });
  assert.equal(model.columns.length, 14);
  const [first, second] = model.columns;
  assert.deepEqual([first.total, first.segments.map((item) => [item.kind, item.count])], [3, [["annual", 1], ["personal", 1], ["comp", 1]]]);   // 戊审批中，不画
  assert.equal(second.total, 1);
  assert.deepEqual([first.today, first.selected, second.today], [true, true, false]);
  assert.deepEqual(model.columns.filter((col) => col.offDay).map((col) => col.date), ["2026-10-17", "2026-10-18", "2026-10-24", "2026-10-25"]);
  assert.deepEqual(model.ticks.map((tick) => tick.value), [0, 1, 2, 3]);
  assert.equal(model.ticks[0].y, 170);                                             // 刻度 0 在图的底边，最高的刻度在顶上
  assert.equal(model.ticks[3].y, 20);
  assert.ok(first.valueY < first.segments[2].y);                                     // 数字写在柱子上面
  assert.deepEqual(model.legend, ["annual", "personal", "comp"]);
  assert.equal(first.label, "10/14 周三 不在岗 3 人");
  // 出差：当天请假的人不算（甲），前台办理中的算（丁）
  const trips = chartModel(ROWS, { today: TODAY, workDates: WORK, mode: "trip" });
  assert.deepEqual(trips.columns.slice(0, 3).map((col) => col.total), [1, 1, 0]);
  assert.deepEqual(trips.legend, ["trip"]);
});

// ---------------------------------------------------------------- 近 5 个工作日
test("the next five working days: each person with each request, away and trips apart, overtime left out", () => {
  const days = nextWorkDays(WORK, TODAY, 5);
  assert.deepEqual(days, ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20"]);
  assert.deepEqual(nextWorkDays([], "2026-10-16", 3), ["2026-10-16", "2026-10-19", "2026-10-20"]);   // 没有日历时按周一到周五
  const view = nearView(ROWS, days);
  assert.deepEqual([view.from, view.to], ["2026-10-14", "2026-10-20"]);
  assert.deepEqual(view.off.map((person) => [person.name, person.off.map((item) => item.name)]).sort(), [["丙", ["R3"]], ["乙", ["R2"]], ["己", ["R8"]], ["戊", ["R6"]], ["甲", ["R1"]]].sort());
  assert.deepEqual(view.trip.map((person) => [person.name, person.trip.map((item) => item.name)]).sort(), [["丁", ["R4"]], ["甲", ["R5"]]].sort());
  assert.ok(!view.off.some((person) => person.off.some((item) => item.kind === "ot")));
});

// ---------------------------------------------------------------- N 月
test("the month tabs add up the server's month hours of approved requests, the same number as the dashboard", () => {
  const totals = monthTotals(ROWS, "2026-10");
  assert.deepEqual(totals, { leave: 27, comp: 8, ot: 6, trip: 24 });                 // 戊的病假审批中，不算
  const view = overviewView(ROWS, { metric: "leave", month: "2026-10" });
  assert.deepEqual(view.tabs.map((tab) => [tab.key, tab.days, tab.on]), [["leave", "3.4", true], ["comp", "1", false], ["ot", "0.8", false], ["trip", "3", false]]);
});

test("company level: by department + by leave type, max 6 bars, and the two charts filter each other and the list", () => {
  const view = overviewView(ROWS, { metric: "leave", month: "2026-10", company: true });
  assert.deepEqual(view.charts.map((chart) => [chart.key, chart.title]), [["dept", "按部门"], ["part", "按假别"]]);
  assert.deepEqual(view.charts[0].items.map((item) => [item.label, item.days, item.pct]), [["研发软件部", "3", 100], ["客服部", "0.4", 12.5]]);
  assert.deepEqual(view.charts[1].items.map((item) => [item.label, item.days, item.color]), [["年假", "3", "annual"], ["事假", "0.4", "personal"]]);
  assert.deepEqual([view.list.map((item) => item.name).sort(), view.listDays, view.chips], [["R1", "R2", "R8"], "3.4", []]);
  assert.equal(view.list[view.list.length - 1].name, "R8");                         // 按开始日期排
  // 选了部门：构成图只算这个部门，部门图不变（高亮选中的），明细只剩这个部门
  const dept = overviewView(ROWS, { metric: "leave", month: "2026-10", sel: { dept: "客服部 - RAY" } });
  assert.equal(dept.charts[0].items.length, 2);
  assert.equal(dept.charts[0].selected, "客服部 - RAY");
  assert.deepEqual(dept.charts[1].items.map((item) => item.label), ["事假"]);
  assert.deepEqual(dept.list.map((item) => item.name), ["R2"]);
  assert.deepEqual(dept.chips, [{ field: "dept", label: "客服部" }]);
  // 选了假别：部门图只算这个假别
  const annual = overviewView(ROWS, { metric: "leave", month: "2026-10", sel: { part: "annual" } });
  assert.deepEqual(annual.charts[0].items.map((item) => [item.label, item.days]), [["研发软件部", "3"]]);
  assert.deepEqual(annual.list.map((item) => item.name), ["R1", "R8"]);
  // 出差：构成是去哪里；按周的选择在全公司那一档不生效
  const trip = overviewView(ROWS, { metric: "trip", month: "2026-10", sel: { week: "2026-10-12" } });
  assert.deepEqual(trip.charts[1].items.map((item) => [item.label, item.days]).sort(), [["上海", "2"], ["北京", "1"]].sort());
  assert.deepEqual(trip.chips, []);
});

test("department or team level: composition + by week; overtime and comp time only by week", () => {
  const team = overviewView(ROWS, { metric: "leave", month: "2026-10", company: false, sel: { dept: "客服部 - RAY" } });
  assert.deepEqual(team.charts.map((chart) => [chart.key, chart.title]), [["part", "按假别"], ["week", "按周"]]);
  assert.deepEqual(team.charts[1].items.map((item) => [item.label, item.hours]), [["10/12–18", 19], ["10/19–25", 8]]);
  assert.equal(team.list.length, 3);                                                 // 部门的选择在这一档没有（只有全公司能选部门）
  const week = overviewView(ROWS, { metric: "leave", month: "2026-10", company: false, sel: { week: "2026-10-19" } });
  assert.deepEqual(week.list.map((item) => item.name), ["R8"]);
  assert.deepEqual(week.charts[0].items.map((item) => item.label), ["年假"]);
  assert.deepEqual(week.chips, [{ field: "week", label: "10/19–25" }]);
  const overtime = overviewView(ROWS, { metric: "ot", month: "2026-10", company: false });
  assert.deepEqual(overtime.charts.map((chart) => chart.title), ["按周"]);
  assert.deepEqual(overtime.charts[0].items.map((item) => [item.key, item.label, item.days]), [["2026-10-12", "10/12–18", "0.8"]]);
  const picked = overviewView(ROWS, { metric: "ot", month: "2026-10", company: false, sel: { part: "2026-10-12" } });
  assert.deepEqual([picked.list.map((item) => item.name), picked.chips], [["R7"], [{ field: "part", label: "10/12–18" }]]);
});

// ---------------------------------------------------------------- 地址
test("the home state lives in the address: defaults are left out, bad values are dropped", () => {
  const state = homeStateOf({ dept: "客服部 - RAY", period: "week", day: "2026-10-20", tile: "trip", chart: "trip", metric: "ot", month: "2026-09", opart: "2026-09-07", section: "month" });
  assert.deepEqual(state, { dept: "客服部 - RAY", q: "", period: "week", day: "", tile: "trip", chart: "trip", metric: "ot", month: "2026-09", odept: "", opart: "2026-09-07", oweek: "", section: "month" });
  assert.deepEqual(homeQuery(state), { dept: "客服部 - RAY", period: "week", tile: "trip", chart: "trip", metric: "ot", month: "2026-09", opart: "2026-09-07", section: "month" });
  assert.deepEqual(homeQuery(homeStateOf({ period: "day", chart: "off", metric: "leave", tile: "bogus", month: "2026-13", day: "x", section: "top" })), {});
  assert.deepEqual(homeStateOf(homeQuery(state)), state);
  // 看板的链接：?view=home&section=month&metric=leave&month=2026-10
  const fromDashboard = parseLocation({ path: "/approval/attendance", query: { view: "home", section: "month", metric: "leave", month: "2026-10", from: "/dashboard?tab=people" } });
  assert.deepEqual([fromDashboard.view, fromDashboard.home.section, fromDashboard.home.metric, fromDashboard.home.month], ["home", "month", "leave", "2026-10"]);
  assert.deepEqual(homeLocation("/approval/attendance", { ...state, section: "" }).query, { view: "home", dept: "客服部 - RAY", period: "week", tile: "trip", chart: "trip", metric: "ot", month: "2026-09", opart: "2026-09-07" });
});

test("opening a request from the home page and pressing back restores the home state", () => {
  const state = homeStateOf({ dept: "客服部 - RAY", day: "2026-10-20", tile: "leave", metric: "comp", odept: "研发软件部 - RAY", section: "away" });
  const origin = { kind: "home", scope: "", filter: "all", home: state };
  assert.deepEqual(homeOriginQuery(state), { fdept: "客服部 - RAY", fday: "2026-10-20", ftile: "leave", fmetric: "comp", fodept: "研发软件部 - RAY", fsection: "away" });
  const detail = detailLocation({ name: "OA-1", type: "请假" }, origin);
  assert.deepEqual(detail.query, { request: "OA-1", from: "home", fdept: "客服部 - RAY", fday: "2026-10-20", ftile: "leave", fmetric: "comp", fodept: "研发软件部 - RAY", fsection: "away" });
  const parsed = parseLocation({ path: detail.path, query: detail.query });
  assert.deepEqual(parsed.origin, origin);
  assert.deepEqual(homeOriginState(detail.query), state);
  assert.deepEqual(backLocation(parsed.origin, { homePath: "/approval/attendance" }), {
    path: "/approval/attendance", query: { view: "home", dept: "客服部 - RAY", day: "2026-10-20", tile: "leave", metric: "comp", odept: "研发软件部 - RAY", section: "away" },
  });
  // 没有首页状态时和原来一样
  assert.deepEqual(originQuery({ kind: "home" }), { from: "home" });
  assert.deepEqual(originOf({ from: "home" }), { kind: "home", scope: "", filter: "all" });
  assert.deepEqual(backLocation({ kind: "home" }, { homePath: "/approval/attendance" }), { path: "/approval/attendance", query: { view: "home" } });
});
