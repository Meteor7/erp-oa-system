import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  CHARTS_KEY, attendanceRate, avatarKind, cellClass, cellTitle, donutArcs, hoursByKind, monthBars, offPerDay,
  quotaRows, rateTone, ratePercent, readChartsOpen, rowKind, sparklinePoints, stripTitle, todayParts,
  totalHours, writeChartsOpen,
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

test("people off per day", () => {
  const days = [{ off: 1 }, { off: 2 }, { off: 0 }];
  assert.deepEqual(offPerDay(days), [1, 2, 0]);
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

test("the employee view is unchanged and has no team data; the team and company views get the new panels, the calendar stays where it was", () => {
  const home = read("../src/components/attendance/AttendanceHome.vue");
  const employee = section(home, "<!-- 员工：", "<template v-else>");
  const shared = section(home, "<!-- 顶上的筛选：", "<!-- 部门主管：");
  const manager = section(home, "<!-- 部门主管：", "<!-- 人事 / 领导：");
  const company = section(home, "<!-- 人事 / 领导：", "<!-- 点进某个部门：");
  const dept = section(home, "<!-- 点进某个部门：", "");
  // 员工：和原来一样（指标栏、可收起的图表、我的申请、我未来 14 天），没有任何团队的东西
  for (const name of ["AttendanceCalendar", "AttendanceDeptTable", "AttendanceAwayPanel", "AttendanceAwayChart", "AttendanceMonthPanel", "AttendanceNearList", "requests"]) {
    assert.doesNotMatch(employee, new RegExp(name), `employee: ${name}`);
  }
  for (const name of ["<AttendanceMetrics", "<AttendanceCharts", "<AttendanceMyStrip", "<AttendanceMineCard"]) assert.match(employee, new RegExp(name), name);
  // 团队 / 全公司 / 部门：谁不在 + 未来 14 天 + N 月，都吃按部门 / 姓名筛过的明细
  for (const name of ["AttendanceAwayPanel", "AttendanceAwayChart", "AttendanceMonthPanel"]) assert.match(shared, new RegExp(`<${name}\\s+:rows="scoped"`), name);
  assert.match(home, /const scoped = computed\(\(\) => scopeRows\(props\.requests\?\.rows, \{ dept: view\.value === 'dept' \? props\.drillDept : '', q: state\.value\.q \}\)\);/);
  // 部门主管：待我审批、近 5 个工作日、团队日历（日历还在右边，和原来一样）；还留着他自己的年假可用和待我审批
  assert.match(manager, /<AttendanceQueue[\s\S]*<AttendanceNearList[\s\S]*<AttendanceCalendar title="我的团队 · 未来 14 天"/);
  assert.match(home, /if \(view\.value === 'manager'\) return \[\.\.\.\(props\.hasEmployee \? \[annualItem\.value\] : \[\]\), todoItem\.value\];/);
  // 全公司：部门概况（和原来一样）+ 待我审批；没有日历
  assert.match(company, /<AttendanceDeptTable :departments="summary\?\.departments \|\| \[\]"/);
  assert.match(company, /<AttendanceQueue/);
  assert.doesNotMatch(company, /AttendanceCalendar|members/);
  // 部门：谁在哪天不在（日历在左边，和原来一样）+ 这个部门的待审批 + 近 5 个工作日（换掉原来的近 5 天不在岗）
  assert.match(dept, /<AttendanceCalendar title="谁在哪天不在" :note="`\$\{detail\?\.headcount \|\| 0\} 人`" :days="stats\?\.days \|\| \[\]" :members="detail\?\.members \|\| \[\]" \/>/);
  assert.match(dept, /title="这个部门的待审批"/);
  assert.match(dept, /<AttendanceNearList/);
  assert.doesNotMatch(home, /AttendanceAway\b|AttendanceAway\.vue|awayList/);
  // 员工用的是 personal，没有任何团队数据；部门概况只传汇总
  assert.match(home, /const personal = computed\(\(\) => props\.board\?\.personal/);
  const table = read("../src/components/attendance/AttendanceDeptTable.vue");
  assert.doesNotMatch(table, /members|employee_name|\.cells/);
  assert.match(table, /@click="emit\('pick', item\.department\)"/);
  // 日历组件没有改：所有成员、同样的列和图例
  const calendar = read("../src/components/attendance/AttendanceCalendar.vue");
  assert.match(calendar, /<span>淡色 = 审批中（不计入统计）<\/span><span class="t0">橙色日期是今天<\/span>/);
  assert.match(calendar, /<tr v-for="member in members" :key="member\.id">/);
});

test("the charts are plain SVG and CSS; the employee panel is remembered open/closed", () => {
  for (const name of ["AttendanceCharts", "AttendanceDonut", "AttendanceCalendar", "AttendanceDeptTable", "AttendanceMyStrip", "AttendanceMetrics", "AttendanceQueue",
    "AttendanceAwayPanel", "AttendanceAwayChart", "AttendanceMonthPanel", "AttendanceNearList"]) {
    const source = read(`../src/components/attendance/${name}.vue`);
    assert.doesNotMatch(source, /from ['"](echarts|chart\.js|d3|apexcharts)/i, name);
  }
  const charts = read("../src/components/attendance/AttendanceCharts.vue");
  for (const text of ["我的额度", "我今年的请假构成", "近 6 个月请假"]) assert.ok(charts.includes(text), text);
  // 原来给部门主管 / 人事的三栏（待我审批等了多久、各部门本月请假、请假类型、14 天堆叠）换成了新的几块
  for (const text of ["待我审批等了多久", "各部门本月请假", "AttendanceDayStack", "topDepartments"]) assert.ok(!charts.includes(text), text);
  const home = read("../src/components/attendance/AttendanceHome.vue");
  assert.match(home, /readChartsOpen\(\)/);
  assert.match(home, /writeChartsOpen\(chartsOpen\.value\)/);
  for (const text of ["收起图表", "展开图表", "仅显示你自己的数据", "只显示你的团队：汇报关系向下的在职员工", "搜姓名"]) assert.ok(home.includes(text), text);
  assert.match(home, /<select v-if="view !== 'manager'" v-model="deptChoice"/);   // 部门选择 = 点进部门（部门主管没有）
  assert.match(home, /set: \(department\) => emit\('dept', department\)/);
  const chart = read("../src/components/attendance/AttendanceAwayChart.vue");
  assert.match(chart, /col\.offDay \? '休' : col\.weekday/);
  assert.match(chart, /\['dl', \{ t0: col\.today \}\]/);
  assert.match(chart, /v-if="col\.total"/);                                   // 一根柱子上面只写一个数，0 不写
  assert.doesNotMatch(chart, /\+\{\{|pending/);                               // 审批中的不画，也没有 +N
});

test("the page loads the board, the request rows and the chosen department with latest-wins tokens", () => {
  const page = read("../src/pages/AttendanceCenter.vue");
  assert.match(page, /api\.board\(\)/);
  assert.match(page, /api\.department\(department\)/);
  assert.match(page, /api\.requests\(\{ month: homeState\.value\.month \}\)/);
  assert.match(page, /latest\.drill\.isCurrent\(token\)/);
  // 选的部门在地址里（dept）：取不到就回到全公司
  assert.match(page, /const drillDept = computed\(\(\) => \(board\.value\?\.level === 'company' \? homeState\.value\.dept : ''\)\);/);
  assert.match(page, /drill\.value = null;\s*setHome\(\{ dept: '' \}\);/);
  assert.match(page, /:board="board" :drill-dept="drillDept" :drill="drill" :requests="requests" :home-state="homeState"/);
  assert.match(page, /@dept="pickDept" @home="onHome"/);
  assert.match(page, /if \(view\.value === 'home'\) return \{ kind: 'home', scope: '', filter: 'all', home: page\.value\.home \};/);
  assert.match(page, /attendanceBoardUi\.css/);
  const view = read("../src/lib/attendanceView.js");
  for (const name of ["get_attendance_board", "get_department_attendance", "get_attendance_requests"]) assert.match(view, new RegExp(`attendance_board_entry\\.${name}`));
});

test("the style sheet covers the type colours and a dark theme, scoped under .acx", () => {
  const css = read("../src/styles/attendanceBoardUi.css");
  for (const kind of ["annual", "personal", "sick", "comp", "ot", "trip", "other"]) assert.match(css, new RegExp(`--ac-t-${kind}:`), kind);
  assert.match(css, /prefers-color-scheme: dark/);
  assert.match(css, /data-theme="dark"/);
  assert.match(css, /\.ac-cal th\.t \{ color: var\(--ac-accent\); font-weight: 700; \}/);       // 今天只把表头日期标成橙色加粗
  assert.doesNotMatch(css, /\.ac-cal [^{]*t0[^{]*\{[^}]*(outline|border)/);                     // 不描边
  assert.match(css, /\.ac-cal td\.we \{ background: var\(--ac-we\); \}/);                        // 周末格子很浅的底色
  // expenseUi.css 里 .xp .r 是右对齐、.xp .bar 是 6px 高的进度条：这一页的布局类名不能撞上（部门表的数字列要右对齐，故意用 .r）
  for (const name of ["AttendanceCharts", "AttendanceQueue", "AttendanceCalendar", "AttendanceHome", "AttendanceAwayPanel", "AttendanceAwayChart", "AttendanceMonthPanel", "AttendanceNearList"]) {
    assert.doesNotMatch(read(`../src/components/attendance/${name}.vue`), /class="(bar|r)"/, name);
  }
  const bare = css.split("\n").filter((line) => /^\s*\.[a-z]/.test(line) && !line.includes(".acx"));
  assert.deepEqual(bare, []);
});
