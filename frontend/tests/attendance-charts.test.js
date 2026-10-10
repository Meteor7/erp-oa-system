import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  CHARTS_KEY, attendanceRate, avatarKind, awayList, cellClass, cellTitle, donutArcs, hoursByKind, longDate, monthBars, offPerDay,
  quotaRows, rankDepartments, rateTone, ratePercent, readChartsOpen, rowKind, sparklinePoints, stackColumns, stripTitle, todayParts,
  totalHours, waitBuckets, writeChartsOpen,
} from "../src/lib/attendanceCharts.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

// ---------------------------------------------------------------- 纯函数

test("attendance rate is the share of leave and comp-time hours in the hours people should work", () => {
  // 4 人 × 8 小时 × 10 个工作日 = 320 小时应出勤，请假 27 小时
  assert.equal(attendanceRate(27, 4, 10), 1 - 27 / 320);
  assert.equal(attendanceRate(0, 4, 10), 1);
  assert.equal(attendanceRate(5, 0, 10), 1);                 // 没有人 / 没有工作日：不扣
  assert.equal(attendanceRate(5, 4, 0), 1);
  assert.equal(attendanceRate(999, 1, 1), 0);                // 不会出现负数
  assert.equal(ratePercent(0.9156), "91.6");
  assert.equal(ratePercent(1), "100.0");
  assert.equal(rateTone(0.92), "warn");
  assert.equal(rateTone(0.93), "ok");
});

test("leave hours by type keep the fixed order and drop the empty types", () => {
  const items = hoursByKind({ comp: 8, annual: 16, personal: 0, trip: 40, ot: 6, other: 3 });
  assert.deepEqual(items.map((item) => [item.kind, item.label, item.hours]), [["annual", "年假", 16], ["comp", "调休", 8], ["other", "其他假", 3]]);   // 出差和加班不算请假
  assert.equal(totalHours(items), 27);
  assert.deepEqual(hoursByKind(undefined), []);
});

test("people off per day, and the stacked columns scale to the busiest day", () => {
  const days = [
    { date: "2026-10-15", day: 15, label: "10/15", weekday: "四", off_day: false, off: 1, by_kind: { annual: 1, trip: 1 } },
    { date: "2026-10-16", day: 16, label: "10/16", weekday: "五", off_day: false, off: 2, by_kind: { personal: 2 } },
    { date: "2026-10-17", day: 17, label: "10/17", weekday: "六", off_day: true, off: 0, by_kind: {} },
  ];
  assert.deepEqual(offPerDay(days), [1, 2, 0]);
  const columns = stackColumns(days, 76);
  assert.deepEqual(columns[0].segments.map((item) => [item.kind, item.count, item.height]), [["annual", 1, 38], ["trip", 1, 38]]);   // 从下到上：请假在下，出差在上
  assert.deepEqual(columns[1].segments.map((item) => [item.kind, item.height]), [["personal", 76]]);
  assert.equal(columns[0].title, "10/15 周四：年假 1 人，出差 1 人");
  assert.equal(columns[2].title, "10/17 周六：全员在岗");
  assert.equal(columns[2].offDay, true);
  assert.deepEqual(columns[2].segments, []);
  assert.deepEqual(stackColumns([], 76), []);
});

test("pending requests are bucketed by how long they have waited", () => {
  const now = Date.parse("2026-10-15T12:00:00");
  const rows = [
    { submitted_on: "2026-10-15 08:00:00" },          // 4 小时
    { submitted_on: "2026-10-14 12:00:00" },          // 正好 1 天
    { submitted_on: "2026-10-13 12:00:00" },          // 2 天
    { submitted_on: "2026-10-12 11:00:00" },          // 3 天多
    {},
  ];
  const result = waitBuckets(rows, now);
  assert.deepEqual(result.buckets.map((item) => [item.key, item.count]), [["fresh", 1], ["mid", 2], ["late", 1]]);
  assert.equal(result.late, 1);
  assert.equal(result.average, 1.6);
  assert.deepEqual(waitBuckets([], now), { buckets: [{ key: "fresh", label: "不到 1 天", count: 0 }, { key: "mid", label: "1–3 天", count: 0 }, { key: "late", label: "超过 3 天", count: 0 }], average: 0, late: 0 });
});

test("departments rank by the month's leave hours, then headcount, then name", () => {
  const list = [{ label: "乙", month_hours: 8, headcount: 3 }, { label: "甲", month_hours: 16, headcount: 2 }, { label: "丙", month_hours: 8, headcount: 5 }];
  assert.deepEqual(rankDepartments(list).map((item) => item.label), ["甲", "丙", "乙"]);
  assert.deepEqual(rankDepartments(list, "headcount").map((item) => item.label), ["丙", "乙", "甲"]);
  assert.deepEqual(list.map((item) => item.label), ["乙", "甲", "丙"]);       // 不改原数组
});

test("donut arcs fill the circle in order, the sparkline and the month bars scale", () => {
  const arcs = donutArcs([{ kind: "annual", hours: 16 }, { kind: "comp", hours: 8 }, { kind: "sick", hours: 0 }]);
  assert.deepEqual(arcs.map((arc) => [arc.kind, arc.dash, arc.gap, arc.offset]), [["annual", "138.23", "69.12", "0.00"], ["comp", "69.12", "138.23", "-138.23"]]);
  assert.equal(sparklinePoints([0, 2, 1], 84, 24), "0.0,21.0 42.0,4.0 84.0,12.5");
  assert.equal(sparklinePoints([3], 84, 24), "");
  const bars = monthBars([{ period: "2026-05", label: "5月", hours: 8 }, { period: "2026-06", label: "6月", hours: 0 }, { period: "2026-10", label: "10月", hours: 40 }], 74);
  assert.deepEqual(bars.map((item) => item.height), [14.8, 2, 74]);
});

test("the quota rows: bars for annual leave and comp time, words for personal leave", () => {
  const rows = quotaRows({
    annual: { credit_hours: 56, used_hours: 8, reserved_hours: 8, available_hours: 40 },
    comp: { credit_hours: 40, used_hours: 0, reserved_hours: 100, available_hours: 16 },
    month: { leave_days_by_type: { 事假: 1 }, pending_cap_hours: 4 },
  });
  assert.deepEqual(rows.map((row) => [row.key, row.label, row.right]), [["annual", "年假（共 56 小时）", "剩 40 小时"], ["comp", "调休（累计加班 40 小时）", "剩 16 小时"], ["personal", "事假（本月）", "已请 8 小时"]]);
  assert.deepEqual(rows[0].bar.map((piece) => [Math.round(piece.pct), piece.faded]), [[14, false], [14, true]]);
  assert.deepEqual(rows[1].bar.map((piece) => [piece.pct, piece.faded]), [[0, false], [100, true]]);      // 占用不会画出总额
  assert.equal(rows[2].bar, null);
  assert.equal(rows[2].note, "其中审批中 4 小时；通过后扣当月研发工时上限");
  assert.deepEqual(quotaRows(null), []);
});

test("today's bar: in / off / trip as shares of the headcount", () => {
  assert.deepEqual(todayParts({ in: 2, off: 1, trip: 1 }, 4).map((part) => [part.key, part.count, part.pct]), [["in", 2, 50], ["off", 1, 25], ["trip", 1, 25]]);
  assert.deepEqual(todayParts({ in: 0, off: 0, trip: 0 }, 0).map((part) => part.pct), [0, 0, 0]);
  assert.equal(longDate("2026-10-05"), "10 月 5 日");
  assert.equal(longDate(""), "");
});

test("who is away in the next five days: approved leave, comp time and trips only, most days first", () => {
  const leave = (kind, pending = false) => ({ kind, pending, hours: 8 });
  const members = [
    { id: "A", name: "甲", cells: [leave("annual"), leave("annual"), null, null, null, leave("sick")] },
    { id: "B", name: "乙", cells: [null, leave("sick", true), leave("ot"), leave("trip"), null] },
    { id: "C", name: "丙", cells: [null, null, null, null, null, leave("comp")] },
  ];
  assert.deepEqual(awayList(members, 0, 5), [{ id: "A", name: "甲", kinds: ["annual"], days: 2 }, { id: "B", name: "乙", kinds: ["trip"], days: 1 }]);
  assert.deepEqual(awayList([], 0, 5), []);
});

test("calendar cells: weekend tint, type colour, dashed-looking pending, and readable titles", () => {
  assert.equal(cellClass(null, { off_day: true }), "we");
  assert.equal(cellClass(null, { off_day: false }), "");
  assert.equal(cellClass({ kind: "sick", pending: false }, {}), "sick");
  assert.equal(cellClass({ kind: "sick", pending: true }, {}), "sick pend");
  const day = { label: "10/15", weekday: "四" };
  assert.equal(cellTitle("甲", day, { kind: "annual", hours: 3, pending: false }), "甲 10/15 周四 年假 3 小时");
  assert.equal(cellTitle("甲", day, { kind: "annual", hours: 8, pending: true }), "甲 10/15 周四 年假（审批中）");
  assert.equal(cellTitle("甲", day, null), "甲 10/15 周四");
  assert.equal(stripTitle({ label: "10/15", weekday: "四", kind: "comp", hours: 8, pending: false }), "10/15 周四 调休");
  assert.equal(stripTitle({ label: "10/16", weekday: "五", kind: null }), "10/16 周五");
});

test("an avatar keeps its colour and a request gets its type colour", () => {
  assert.equal(avatarKind("张雨桐"), avatarKind("张雨桐"));
  assert.ok(["annual", "personal", "sick", "comp", "ot", "trip"].includes(avatarKind("刘子轩")));
  assert.equal(rowKind({ request_type: "请假申请", leave_type: "年假" }), "annual");
  assert.equal(rowKind({ request_type: "请假申请", leave_type: "婚假" }), "other");
  assert.equal(rowKind({ request_type: "调休申请" }), "comp");
  assert.equal(rowKind({ request_type: "加班申请" }), "ot");
});

test("the charts panel remembers whether it is open and survives a browser that refuses storage", () => {
  const store = new Map();
  const storage = { getItem: (key) => (store.has(key) ? store.get(key) : null), setItem: (key, value) => store.set(key, value) };
  assert.equal(readChartsOpen(storage), true);            // 没记过：展开
  writeChartsOpen(false, storage);
  assert.equal(store.get(CHARTS_KEY), "closed");
  assert.equal(readChartsOpen(storage), false);
  writeChartsOpen(true, storage);
  assert.equal(readChartsOpen(storage), true);
  const broken = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  assert.equal(readChartsOpen(broken), true);
  writeChartsOpen(false, broken);                         // 不抛错
  assert.equal(readChartsOpen(null), true);
});

// ---------------------------------------------------------------- 页面接线（读源码）

const section = (text, from, to) => {
  const start = text.indexOf(from);
  assert.ok(start >= 0, from);
  const end = to ? text.indexOf(to, start + from.length) : text.length;
  assert.ok(end > start, to);
  return text.slice(start, end);
};

test("the employee view has no team calendar and no department table; the company home renders no calendar", () => {
  const home = read("../src/components/attendance/AttendanceHome.vue");
  const employee = section(home, "<!-- 员工：", "<!-- 部门主管：");
  const manager = section(home, "<!-- 部门主管：", "<!-- 人事 / 领导：");
  const company = section(home, "<!-- 人事 / 领导：", "<!-- 点进某个部门：");
  const dept = section(home, "<!-- 点进某个部门：", "");
  for (const name of ["AttendanceCalendar", "AttendanceDeptTable", "AttendanceAway"]) assert.doesNotMatch(employee, new RegExp(name), `employee: ${name}`);
  assert.match(employee, /<AttendanceMyStrip/);
  assert.match(employee, /<AttendanceMineCard/);
  assert.match(manager, /<AttendanceCalendar/);
  assert.doesNotMatch(manager, /AttendanceDeptTable/);
  for (const name of ["AttendanceCalendar", "AttendanceAway", "AttendanceMyStrip"]) assert.doesNotMatch(company, new RegExp(name), `company: ${name}`);
  assert.match(company, /<AttendanceDeptTable/);
  assert.match(dept, /<AttendanceCalendar/);
  assert.match(dept, /<AttendanceAway/);
  // 员工用的是 personal，没有任何团队数据；部门概况只传汇总，日历只吃 detail 里的成员
  assert.match(home, /const personal = computed\(\(\) => props\.board\?\.personal/);
  assert.match(company, /:departments="summary\?\.departments/);
  assert.doesNotMatch(company, /members/);
  const table = read("../src/components/attendance/AttendanceDeptTable.vue");
  assert.doesNotMatch(table, /members|employee_name|\.cells/);
  assert.match(table, /@click="emit\('pick', item\.department\)"/);
});

test("the charts are plain SVG and CSS, remembered open/closed, and each identity gets its own three columns", () => {
  for (const name of ["AttendanceCharts", "AttendanceDonut", "AttendanceDayStack", "AttendanceCalendar", "AttendanceDeptTable", "AttendanceMyStrip", "AttendanceMetrics", "AttendanceQueue", "AttendanceAway"]) {
    const source = read(`../src/components/attendance/${name}.vue`);
    assert.doesNotMatch(source, /from ['"](echarts|chart\.js|d3|apexcharts)/i, name);
  }
  const charts = read("../src/components/attendance/AttendanceCharts.vue");
  for (const text of ["我的额度", "我今年的请假构成", "近 6 个月请假", "待我审批等了多久", "各部门本月请假", "本月请假类型", "14 天"]) assert.ok(charts.includes(text), text);
  assert.match(charts, /kind === 'employee'/);
  assert.match(charts, /kind === 'company'/);
  const home = read("../src/components/attendance/AttendanceHome.vue");
  assert.match(home, /readChartsOpen\(\)/);
  assert.match(home, /writeChartsOpen\(chartsOpen\.value\)/);
  for (const text of ["收起图表", "展开图表", "仅显示你自己的数据", "先看部门汇总；点进某个部门才显示具体的人", "图表只统计这个部门"]) assert.ok(home.includes(text), text);
  assert.match(home, /@dept="|emit\('dept'/);
});

test("the page loads the board and the drilled department with latest-wins tokens, and clears the drill on a refusal", () => {
  const page = read("../src/pages/AttendanceCenter.vue");
  assert.match(page, /api\.board\(\)/);
  assert.match(page, /api\.department\(department\)/);
  assert.match(page, /latest\.drill\.isCurrent\(token\)/);
  assert.match(page, /drillDept\.value = '';\s*drill\.value = null;/);
  assert.match(page, /:board="board" :drill-dept="drillDept" :drill="drill"/);
  assert.match(page, /@dept="pickDept"/);
  assert.match(page, /attendanceBoardUi\.css/);
  const view = read("../src/lib/attendanceView.js");
  for (const name of ["get_attendance_board", "get_department_attendance"]) assert.match(view, new RegExp(`attendance_board_entry\\.${name}`));
});

test("the style sheet covers the type colours and a dark theme, scoped under .acx", () => {
  const css = read("../src/styles/attendanceBoardUi.css");
  for (const kind of ["annual", "personal", "sick", "comp", "ot", "trip", "other"]) assert.match(css, new RegExp(`--ac-t-${kind}:`), kind);
  assert.match(css, /prefers-color-scheme: dark/);
  assert.match(css, /data-theme="dark"/);
  assert.match(css, /\.ac-cal th\.t \{ color: var\(--ac-accent\); font-weight: 700; \}/);       // 今天只把表头日期标成橙色加粗
  assert.doesNotMatch(css, /\.ac-cal [^{]*t0[^{]*\{[^}]*(outline|border)/);                     // 不描边
  assert.match(css, /\.ac-cal td\.we \{ background: var\(--ac-we\); \}/);                        // 周末格子很浅的底色
  const bare = css.split("\n").filter((line) => /^\s*\.[a-z]/.test(line) && !line.includes(".acx"));
  assert.deepEqual(bare, []);
});
