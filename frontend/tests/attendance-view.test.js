import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, readFileSync } from "node:fs";
import {
  ATTENDANCE_HOME_PATH, DAY_RULE_MESSAGE, LEAVE_RULES, backLabel, backLocation, balanceKpis, breakdownText, buildFields, byWait,
  canQuickApprove, contextFilter, createLatest, customCap, dayChip, dayLabel, dayModeText, dayNote, dayRows, defaultScope,
  departmentLabel, detailLocation, durationText, effectLine, effectRows, filterRows, formSummary, homeLocation, hoursOfMode, hoursInText,
  invalidLeaveDays, kindOf, listLocation, listTitle, mergeDays, mineSummary, modeAvailable, modeOfHours, newButtonLabel, newLocation,
  newTitle, nodeText, numText, originOf, originQuery, parseLocation, pathForFilter, personShort, pickMode, rangeText,
  actedText, rejectionOf, requestTitle, returnedDrafts, reviewedResult, rowChips, rowDays, scopeTabs, shiftText, slotClash, slotNote, statusTag,
  stepHours, stepRole, stepStates, stepTracker, subjectFor, submittedText, totalHours, totalOf, typeChips, typeCounts,
  typeForPath, validLeaveHours, validScope, waitText, workedSpan,
} from "../src/lib/attendanceView.js";

const exists = (path) => existsSync(new URL(path, import.meta.url));
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

// ---------------------------------------------------------------- 查询参数、跳转目标

test("the page type follows the path; the home path belongs to no type", () => {
  assert.equal(typeForPath("/approval/leave"), "请假申请");
  assert.equal(typeForPath("/approval/leave/OA-1"), "请假申请");
  assert.equal(typeForPath("/approval/overtime/OA-1"), "加班申请");
  assert.equal(typeForPath("/approval/comp-time"), "调休申请");
  assert.equal(typeForPath(ATTENDANCE_HOME_PATH), "");
});

test("the view and the filters come from the path and the query; old links still open the right page", () => {
  // 侧栏进来的 /approval/overtime 就是加班列表
  assert.deepEqual(
    (({ view, filter, scope }) => ({ view, filter, scope }))(parseLocation({ path: "/approval/overtime" })),
    { view: "list", filter: "加班", scope: "" },
  );
  const list = parseLocation({ path: "/approval/overtime", query: { view: "list", scope: "todo" } });
  assert.deepEqual([list.view, list.scope, list.filter], ["list", "todo", "加班"]);
  // ?type= 优先于路径；all 是全部类型
  assert.equal(parseLocation({ path: "/approval/leave", query: { view: "list", type: "all", scope: "mine" } }).filter, "all");
  assert.equal(parseLocation({ path: "/approval/leave", query: { view: "list", type: "调休" } }).filter, "调休");
  assert.equal(parseLocation({ path: "/approval/leave", query: { view: "list", scope: "bogus", type: "bogus" } }).scope, "");
  assert.equal(parseLocation({ path: "/approval/leave", query: { view: "home" } }).view, "home");
  const home = parseLocation({ path: ATTENDANCE_HOME_PATH });
  assert.deepEqual([home.view, home.filter], ["home", "all"]);
  // 详情：/approval/<类型>/<单号> 和 ?request=<单号>（通知、待办里的旧链接）
  const named = parseLocation({ path: "/approval/comp-time/OA-1", params: { name: "OA-1" } });
  assert.deepEqual([named.view, named.request], ["detail", "OA-1"]);
  assert.deepEqual([parseLocation({ path: "/approval/leave", query: { request: "OA-2" } }).view, parseLocation({ path: "/approval/leave", query: { request: "OA-2", reject: "1" } }).reject], ["detail", true]);
  // 新建：缺类型就是 ''（页面先让用户选）；旧的 ?draft= 链接按路径的类型继续填写
  const picker = parseLocation({ path: "/approval/leave", query: { view: "new" } });
  assert.deepEqual([picker.view, picker.newType], ["new", ""]);
  assert.equal(parseLocation({ path: "/approval/leave", query: { view: "new", type: "加班" } }).newType, "加班");
  const draft = parseLocation({ path: "/approval/overtime", query: { draft: "OA-3" } });
  assert.deepEqual([draft.view, draft.newType, draft.draft], ["new", "加班", "OA-3"]);
});

test("where a page came from travels in the query and comes back out unchanged", () => {
  const origin = { kind: "list", scope: "todo", filter: "加班" };
  assert.deepEqual(originQuery(origin), { from: "list", fscope: "todo", ftype: "加班" });
  assert.deepEqual(originOf(originQuery(origin)), origin);
  assert.deepEqual(originOf(originQuery({ kind: "home" })), { kind: "home", scope: "", filter: "all" });
  assert.deepEqual(originQuery(null), {});
  assert.deepEqual(originOf({ from: "list", fscope: "bogus", ftype: "bogus" }), { kind: "list", scope: "mine", filter: "all" });
  assert.deepEqual(originOf({}), { kind: "", scope: "", filter: "all" });
  const newer = newLocation({ type: "加班" }, origin);
  assert.deepEqual(parseLocation({ path: newer.path, query: newer.query }).origin, origin);
});

test("every button carries its context: new opens the type of the list, the picker only when the type is all", () => {
  const home = "/approval/attendance";
  assert.deepEqual(listLocation({ scope: "todo", filter: "加班" }, home), { path: "/approval/overtime", query: { view: "list", scope: "todo", type: "加班" } });
  assert.deepEqual(listLocation({ scope: "mine", filter: "all" }, home), { path: home, query: { view: "list", scope: "mine", type: "all" } });
  assert.deepEqual(homeLocation(home), { path: home, query: { view: "home" } });
  const fromList = { kind: "list", scope: "todo", filter: "加班" };
  assert.deepEqual(newLocation({ type: "加班" }, fromList), { path: "/approval/overtime", query: { view: "new", type: "加班", from: "list", fscope: "todo", ftype: "加班" } });
  // 类型是 all：不带类型，让用户先选；路径留给页面用当前路径
  const picker = newLocation({}, { kind: "list", scope: "mine", filter: "all" });
  assert.equal(picker.path, undefined);
  assert.deepEqual(picker.query, { view: "new", from: "list", fscope: "mine", ftype: "all" });
  assert.deepEqual(newLocation({ type: "调休", draft: "OA-9" }, { kind: "home" }), { path: "/approval/comp-time", query: { view: "new", type: "调休", draft: "OA-9", from: "home" } });
  assert.deepEqual(detailLocation({ name: "OA-1", type: "请假" }, fromList, { reject: true }), {
    path: "/approval/leave", query: { request: "OA-1", reject: "1", from: "list", fscope: "todo", ftype: "加班" },
  });
  assert.equal(detailLocation({ name: "OA-1" }, null).path, undefined);
  assert.deepEqual(detailLocation({ name: "OA-1" }, null).query, { request: "OA-1" });
});

test("cancel and back return to where the user came from", () => {
  const home = "/approval/attendance";
  assert.deepEqual(backLocation({ kind: "home" }, { homePath: home }), { path: home, query: { view: "home" } });
  assert.deepEqual(backLocation({ kind: "list", scope: "todo", filter: "加班" }, { homePath: home }), listLocation({ scope: "todo", filter: "加班" }, home));
  // 没有来源（直接打开的链接）：回到这个类型"我的"列表
  assert.deepEqual(backLocation({ kind: "" }, { filter: "调休", homePath: home }), listLocation({ scope: "mine", filter: "调休" }, home));
  assert.equal(backLabel({ kind: "home" }), "返回首页");
  assert.equal(backLabel({ kind: "list" }), "返回列表");
  assert.equal(backLabel({ kind: "" }), "返回列表");
});

test("titles and button labels follow the type filter", () => {
  assert.equal(listTitle("all"), "申请列表");
  assert.equal(listTitle("加班"), "加班申请");
  assert.equal(newButtonLabel("all"), "＋ 新建申请");
  assert.equal(newButtonLabel("加班"), "＋ 新建加班");
  assert.equal(newTitle(""), "新建申请");
  assert.equal(newTitle("请假"), "新建请假申请");
});

test("the sidebar context follows the type being worked on", () => {
  assert.equal(contextFilter({ view: "list", filter: "加班" }), "加班");
  assert.equal(contextFilter({ view: "home", filter: "加班" }), "all");
  assert.equal(contextFilter({ view: "new", newType: "调休" }), "调休");
  assert.equal(contextFilter({ view: "new", newType: "" }), "all");
  assert.equal(contextFilter({ view: "detail" }), "");
  const home = "/approval/attendance";
  assert.equal(pathForFilter("加班", home), "/approval/overtime");
  assert.equal(pathForFilter("调休", home), "/approval/comp-time");
  assert.equal(pathForFilter("请假", home), "/approval/leave");
  assert.equal(pathForFilter("all", home), home);
});

// ---------------------------------------------------------------- 列表：筛选、计数、范围

const rowOf = (request_type, extra = {}) => ({ name: `OA-${Math.random()}`, request_type, ...extra });

test("type chips, counts and scope tabs", () => {
  const rows = [rowOf("请假申请"), rowOf("加班申请"), rowOf("加班申请"), rowOf("调休申请")];
  const counts = typeCounts(rows);
  assert.deepEqual(counts, { all: 4, 请假: 1, 加班: 2, 调休: 1 });
  assert.deepEqual(typeChips(counts, "加班", true).map((chip) => [chip.label, chip.on]), [["全部 4", false], ["请假 1", false], ["加班 2", true], ["调休 1", false]]);
  assert.deepEqual(typeChips({}, "all").map((chip) => chip.label), ["全部", "请假", "加班", "调休"]);
  assert.equal(filterRows(rows, "加班").length, 2);
  assert.equal(filterRows(rows, "all").length, 4);
  const sets = { todo: rows, mine: [rows[0]], done: [], all: rows };
  // 数量按当前类型筛选算；待我审批 / 我审批过的只有审批人才有，全部只有人事 / 老板才有
  assert.deepEqual(scopeTabs({ sets, filter: "加班", isApprover: true, canViewAll: false, allLoaded: false }).map((tab) => [tab.key, tab.count]), [["todo", 2], ["mine", 0], ["done", 0]]);
  assert.deepEqual(scopeTabs({ sets, filter: "all", isApprover: false, canViewAll: false, allLoaded: false }).map((tab) => tab.key), ["mine"]);
  const hr = scopeTabs({ sets, filter: "all", isApprover: true, canViewAll: true, allLoaded: false });
  assert.deepEqual(hr.map((tab) => [tab.key, tab.count]), [["todo", 4], ["mine", 1], ["done", 0], ["all", null]]);
  assert.equal(scopeTabs({ sets, filter: "all", isApprover: true, canViewAll: true, allLoaded: true }).at(-1).count, 4);
  assert.equal(defaultScope(2), "todo");
  assert.equal(defaultScope(0), "mine");
  assert.equal(validScope("all", { canViewAll: false }), "mine");
  assert.equal(validScope("all", { canViewAll: true }), "all");
  assert.equal(validScope("bogus"), "");
  assert.equal(canQuickApprove({ workflow_status: "待审批", can_approve: true }), true);
  assert.equal(canQuickApprove({ workflow_status: "待审批", can_approve: true, current_step_mode: "handle" }), false);
  assert.equal(canQuickApprove({ workflow_status: "已完成", can_approve: true }), false);
  assert.equal(canQuickApprove({ workflow_status: "待审批", can_approve: false }), false);
});

// ---------------------------------------------------------------- 每天：全天 8 / 上午 3 / 下午 5 / 自定义 / 不请

test("a day is 全天 8 / 上午 3 / 下午 5 / 自定义 / 不请: modes map to hours and respect what is left on that day", () => {
  assert.equal(hoursOfMode("full"), 8);
  assert.equal(hoursOfMode("am"), 3);
  assert.equal(hoursOfMode("pm"), 5);
  assert.equal(hoursOfMode("none"), 0);
  // 放不进这天剩下的小时数就是 0，不会退成别的时长
  assert.equal(hoursOfMode("full", 5), 0);
  assert.equal(hoursOfMode("pm", 3), 0);
  assert.equal(hoursOfMode("am", 3), 3);
  assert.equal(hoursOfMode("am", 0), 0);
  assert.equal(hoursOfMode("half"), 0);
  // 4 小时不再是"半天"，只是一个自定义小时
  assert.deepEqual([8, 3, 5, 0, 4, 2.5].map(modeOfHours), ["full", "am", "pm", "none", "custom", "custom"]);
  assert.equal(stepHours(5.5, 0.5, 24), 6);
  assert.equal(stepHours(0, -0.5, 24), 0);
  assert.equal(stepHours(23.75, 0.5, 24), 24);
  // 自定义小时：每次 0.5，最少 0.5，最多这天的上限
  assert.equal(stepHours(1, -0.5, 8, 0.5), 0.5);
  assert.equal(stepHours(0.5, -0.5, 8, 0.5), 0.5);
  assert.equal(stepHours(8, 0.5, 8, 0.5), 8);
  assert.equal(stepHours(5, 0.5, 5.5, 0.5), 5.5);
  assert.equal(stepHours(5.5, 0.5, 5.5, 0.5), 5.5);
});

test("the buttons are disabled from the day limits; 自定义 is open while at least half an hour is left", () => {
  const free = { max_hours: 8, am_taken: false, pm_taken: false };
  const amTaken = { max_hours: 5, am_taken: true, pm_taken: false };
  const pmTaken = { max_hours: 3, am_taken: false, pm_taken: true };
  const four = { max_hours: 4, am_taken: false, pm_taken: false };
  const customTaken = { max_hours: 5.5, am_taken: false, pm_taken: false };
  const full = { max_hours: 0, am_taken: true, pm_taken: true };
  const available = (day) => ["full", "am", "pm", "custom", "none"].filter((mode) => modeAvailable(day, mode));
  assert.deepEqual(available(free), ["full", "am", "pm", "custom", "none"]);
  assert.deepEqual(available(amTaken), ["pm", "custom", "none"]);
  assert.deepEqual(available(pmTaken), ["am", "custom", "none"]);
  // 剩 4 小时：能再加上午 3 小时，也能自定义不超过 4 小时；下午 5 小时放不下
  assert.deepEqual(available(four), ["am", "custom", "none"]);
  assert.deepEqual(available(customTaken), ["am", "pm", "custom", "none"]);
  assert.deepEqual(available(full), ["none"]);
  assert.equal(modeAvailable({ max_hours: 0.25 }, "custom"), false);
  assert.equal(modeAvailable(free, "half"), false);
  assert.equal(customCap({ max_hours: 5.5 }), 5.5);
  assert.equal(customCap({ max_hours: 12 }), 8);
  assert.equal(customCap({}), 8);
});

test("picking a mode sets mode and hours; 自定义 starts at 1 hour (or the last custom value) within the day's limit", () => {
  const day = { mode: "full", hours: 8, max_hours: 5, am_taken: true, pm_taken: false };
  assert.deepEqual(pickMode(day, "full"), { mode: "full", hours: 8 });                 // 放不下，原样不动
  assert.deepEqual(pickMode(day, "pm"), { mode: "pm", hours: 5 });
  assert.deepEqual(pickMode(day, "am"), { mode: "full", hours: 8 });                   // 上午被占了
  assert.deepEqual(pickMode(day, "none"), { mode: "none", hours: 0 });
  assert.deepEqual(pickMode(day, "custom"), { mode: "custom", hours: 1 });
  assert.deepEqual(pickMode({ ...day, custom: 6 }, "custom"), { mode: "custom", hours: 5 });   // 上次填的 6 小时，这天最多 5
  assert.deepEqual(pickMode({ ...day, custom: 2.5 }, "custom"), { mode: "custom", hours: 2.5 });
  assert.deepEqual(pickMode({ mode: "none", hours: 0, max_hours: 0.5 }, "custom"), { mode: "custom", hours: 0.5 });
});

test("a custom 3 or 5 hours is treated as 上午 / 下午 by the server, and the form says so", () => {
  assert.match(slotNote({ mode: "custom", hours: 3 }), /上午/);
  assert.match(slotNote({ mode: "custom", hours: 5 }), /下午/);
  assert.equal(slotNote({ mode: "custom", hours: 2 }), "");
  assert.equal(slotNote({ mode: "am", hours: 3 }), "");
  assert.equal(slotClash({ hours: 3, am_taken: true }), "上午");
  assert.equal(slotClash({ hours: 5, pm_taken: true }), "下午");
  assert.equal(slotClash({ hours: 3, am_taken: false }), "");
  assert.equal(slotClash({ hours: 4, am_taken: true, pm_taken: true }), "");
  assert.equal(dayNote({ max_hours: 8 }), "");
  assert.match(dayNote({ max_hours: 5, am_taken: true }), /上午已被占用，只能请下午，或自定义不超过 5 小时/);
  assert.match(dayNote({ max_hours: 3, pm_taken: true }), /下午已被占用，只能请上午，或自定义不超过 3 小时/);
  assert.match(dayNote({ max_hours: 5.5 }), /还能请 5\.5 小时/);
  assert.match(dayNote({ max_hours: 0.25 }), /请满了/);
});

test("any multiple of half an hour up to a full day is valid for leave and comp-time", () => {
  assert.deepEqual([0.5, 1, 2.5, 4, 7.5, 8].map(validLeaveHours), [true, true, true, true, true, true]);
  assert.deepEqual([0, 0.25, 0.75, 8.5, 9, -1, "x"].map(validLeaveHours), [false, false, false, false, false, false, false]);
  assert.deepEqual(invalidLeaveDays([{ hours: 8 }, { hours: 3 }, { hours: 2.5 }, { hours: 4 }, { hours: 0 }]), []);
  assert.deepEqual(invalidLeaveDays([{ work_date: "a", hours: 8.5 }, { work_date: "b", hours: 0.25 }, { work_date: "c", hours: 1 }]).map((day) => day.work_date), ["a", "b"]);
});

test("changing the dates keeps what the user already chose", () => {
  const server = [{ work_date: "2026-10-13", hours: 8, max_hours: 8, conflict: null }, { work_date: "2026-10-14", hours: 8, max_hours: 8, conflict: null },
    { work_date: "2026-10-15", hours: 3, max_hours: 3, am_taken: false, pm_taken: true, conflict: null }];
  const merged = mergeDays(server, [{ work_date: "2026-10-13", hours: 5 }, { work_date: "2026-10-15", hours: 8 }]);
  // 13 日保留用户选的下午；15 日选的全天现在放不下，换成服务端的默认值（上午 3 小时）
  assert.deepEqual(merged.map((day) => [day.work_date, day.hours, day.mode]), [["2026-10-13", 5, "pm"], ["2026-10-14", 8, "full"], ["2026-10-15", 3, "am"]]);
  assert.equal(totalHours(merged), 16);
  assert.deepEqual([merged[2].am_taken, merged[2].pm_taken], [false, true]);
});

test("custom hours are kept (capped by the day's limit), even when they equal a preset; taken presets fall back to the server default", () => {
  const free = (date, max = 8) => ({ work_date: date, hours: Math.min(8, max), max_hours: max, conflict: null });
  const custom = (hours) => [{ work_date: "2026-10-13", hours, mode: "custom" }];
  assert.deepEqual(mergeDays([free("2026-10-13")], custom(2.5)).map((day) => [day.hours, day.mode, day.custom]), [[2.5, "custom", 2.5]]);
  // 用户选的是自定义 3 小时，仍然是"自定义"那一档（不会因为正好 3 小时变回"上午"）
  assert.deepEqual(mergeDays([free("2026-10-13")], custom(3)).map((day) => [day.hours, day.mode]), [[3, "custom"]]);
  // 这天现在只剩 5 小时了：自定义 7 小时缩到 5
  assert.equal(mergeDays([free("2026-10-13", 5)], custom(7))[0].hours, 5);
  // 上午被占了：原来选的上午换成服务端的默认值（下午 5 小时）
  const taken = [{ work_date: "2026-10-13", hours: 5, max_hours: 5, am_taken: true, pm_taken: false, conflict: null }];
  assert.deepEqual(mergeDays(taken, [{ work_date: "2026-10-13", hours: 3 }]).map((day) => [day.hours, day.mode]), [[5, "pm"]]);
  // 旧草稿里的 4 小时半天现在就是自定义 4 小时，保留，也不再需要重新选
  const legacy = mergeDays([free("2026-10-14")], [{ work_date: "2026-10-14", hours: 4 }]);
  assert.deepEqual([legacy[0].hours, legacy[0].mode], [4, "custom"]);
  assert.deepEqual(invalidLeaveDays(legacy), []);
  // 没选过的日子用服务端的默认值；继续填草稿时，草稿里没有的日子是"不请"
  const two = [free("2026-10-13"), free("2026-10-14")];
  assert.deepEqual(mergeDays(two, [{ work_date: "2026-10-13", hours: 3 }]).map((day) => day.hours), [3, 8]);
  assert.deepEqual(mergeDays(two, [{ work_date: "2026-10-13", hours: 3 }], false, { zeroNew: true }).map((day) => [day.hours, day.mode]), [[3, "am"], [0, "none"]]);
  assert.equal(mergeDays(two, [], false, { zeroNew: true })[0].hours, 8);
  // 加班按小时，原样保留（不超过上限）
  const overtime = mergeDays([{ work_date: "2026-10-17", hours: 8, max_hours: 24, conflict: null }], [{ work_date: "2026-10-17", hours: 4.5 }], true);
  assert.deepEqual([overtime[0].hours, overtime[0].mode], [4.5, "custom"]);
});

test("the day texts: 全天 / 上午 / 下午 / 自定义, and the rule text mentions custom hours", () => {
  assert.equal(dayModeText(8), "全天 · 8 小时");
  assert.equal(dayModeText(3), "上午 · 3 小时");
  assert.equal(dayModeText(5), "下午 · 5 小时");
  assert.equal(dayModeText(4), "自定义 · 4 小时");
  assert.equal(dayModeText(2.5), "自定义 · 2.5 小时");
  assert.equal(durationText(16), "2 天 · 16 小时");
  assert.equal(durationText(3), "3 小时");
  assert.equal(durationText(11), "11 小时");
  assert.match(LEAVE_RULES["事假"], /全天 8 小时，上午 3 小时，下午 5 小时，也可以自定义小时（每次 0\.5）/);
  assert.doesNotMatch(LEAVE_RULES["事假"], /半天/);
  assert.equal(DAY_RULE_MESSAGE, "请假和调休按天填：全天 8 小时、上午 3 小时、下午 5 小时，也可以自定义小时（每次 0.5）。");
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

test("the summary is in hours, split by slot, with the effect on the balance or the monthly cap and why it cannot be submitted", () => {
  const days = [{ work_date: "2026-09-30", hours: 8 }, { work_date: "2026-10-01", hours: 3 }];
  const annual = { available_hours: 88, eligible: true };
  const year = formSummary({ requestType: "请假申请", leaveType: "年假", days, annual });
  assert.deepEqual([year.big, year.unit, year.breakdown], ["11", "小时", "全天 1 · 上午 1"]);
  assert.equal(year.impact, "年假余额 88 → 77 小时");
  assert.deepEqual(year.lines, [{ label: "年假额度", value: "88 → 77 小时" }]);
  assert.equal(year.blocked, "");
  const short = formSummary({ requestType: "请假申请", leaveType: "年假", days, annual: { available_hours: 8, eligible: true } });
  assert.equal(short.impact, "年假不够：还差 3 小时");
  assert.equal(short.blocked, "年假余额不足");
  assert.equal(formSummary({ requestType: "请假申请", leaveType: "年假", days, annual: { available_hours: 88, eligible: false, eligibility_message: "入职不满 12 个月" } }).blocked, "入职不满 12 个月");
  const personal = formSummary({ requestType: "请假申请", leaveType: "事假", days });
  assert.equal(personal.impact, "通过后，9 月工时上限少 8 小时；通过后，10 月工时上限少 3 小时");
  assert.deepEqual(personal.lines, [{ label: "9 月研发工时上限", value: "−8 小时" }, { label: "10 月研发工时上限", value: "−3 小时" }]);
  assert.equal(formSummary({ requestType: "请假申请", leaveType: "病假", days }).impact, "不扣年假，也不扣当月工时上限");
  const comp = formSummary({ requestType: "调休申请", days, comp: { available_hours: 16 } });
  assert.equal(comp.impact, "调休余额 16 → 5 小时");
  assert.equal(formSummary({ requestType: "调休申请", days, comp: { available_hours: 4 } }).blocked, "调休余额不足");
  // 上午 3 + 下午 5：8 小时，不拆成小数天
  const split = formSummary({ requestType: "请假申请", leaveType: "事假", days: [{ work_date: "2026-10-13", hours: 3 }, { work_date: "2026-10-14", hours: 5 }] });
  assert.deepEqual([split.big, split.unit, split.breakdown], ["8", "小时", "上午 1 · 下午 1"]);
  assert.equal(split.impact, "通过后，10 月工时上限少 8 小时");
  // 自定义小时：0.5 的倍数都能提交；4 小时（旧的半天）也可以
  const custom = formSummary({ requestType: "调休申请", days: [{ work_date: "2026-10-13", hours: 2.5 }, { work_date: "2026-10-14", hours: 4 }], comp: { available_hours: 8 } });
  assert.deepEqual([custom.big, custom.breakdown, custom.impact, custom.blocked], ["6.5", "自定义 2", "调休余额 8 → 1.5 小时", ""]);
  // 不是 0.5 的倍数（或超过 8 小时）不能提交
  assert.equal(formSummary({ requestType: "调休申请", days: [{ work_date: "2026-10-13", hours: 2.3 }], comp: { available_hours: 8 } }).blocked, DAY_RULE_MESSAGE);
  assert.equal(formSummary({ requestType: "请假申请", leaveType: "事假", days: [{ work_date: "2026-10-13", hours: 8.5 }] }).blocked, DAY_RULE_MESSAGE);
  // 自定义小时正好是 3，而这天上午已被占：服务端会按上午冲突拒绝，页面先说清楚
  const clash = formSummary({ requestType: "请假申请", leaveType: "事假", days: [{ work_date: "2026-10-13", hours: 3, mode: "custom", am_taken: true }] });
  assert.equal(clash.blocked, "10月13日上午已被占用，请换一个时段或改小时数");
  // 加班不受每天规则限制
  assert.equal(formSummary({ requestType: "加班申请", days: [{ work_date: "2026-10-17", hours: 2.3 }], comp: { available_hours: 0 } }).blocked, "");
  const overtime = formSummary({ requestType: "加班申请", days: [{ work_date: "2026-10-17", hours: 6 }], comp: { available_hours: 16 } });
  assert.deepEqual([overtime.big, overtime.breakdown], ["6", "加班"]);
  assert.equal(overtime.impact, "提交后调休额度 16 → 22 小时（1:1）");
  assert.deepEqual(overtime.lines, [{ label: "调休额度", value: "16 → 22 小时" }]);
  assert.equal(formSummary({ requestType: "请假申请", leaveType: "事假", days: [] }).blocked, "请至少填一天的时长");
  assert.equal(breakdownText([{ hours: 8 }, { hours: 8 }, { hours: 3 }, { hours: 5 }, { hours: 2 }, { hours: 0 }]), "全天 2 · 上午 1 · 下午 1 · 自定义 1");
  assert.equal(breakdownText([], false), "");
});

test("the subject is generated from the type, the length and the start of the reason", () => {
  assert.equal(subjectFor("请假申请", "事假", 16), "事假 2 天");
  assert.equal(subjectFor("请假申请", "年假", 11, "带家人出游"), "年假 11 小时 · 带家人出游");
  assert.equal(subjectFor("请假申请", "事假", 3), "事假 3 小时");
  assert.equal(subjectFor("加班申请", "", 6, "版本上线值守很久很久很久很久"), "加班 6 小时 · 版本上线值守很久很久很久");
  assert.equal(subjectFor("调休申请", "", 8), "调休 1 天");
});

test("the submitted fields only carry days that have hours, so the dates always match the details", () => {
  // 验收时发现：选的第一天已被占用（0 小时）时，起止日期变成第二天，明细里却还留着第一天，服务端拒绝。
  const days = [
    { work_date: "2026-09-28", hours: 0, max_hours: 0, conflict: { request: "OA-1" } },
    { work_date: "2026-09-29", hours: 8, mode: "full" }, { work_date: "2026-09-30", hours: 0 }, { work_date: "2026-10-01", hours: 2.5, mode: "custom" },
  ];
  const fields = buildFields({ requestType: "请假申请", leaveType: "年假", from: "2026-09-28", to: "2026-10-02", days, subject: "", reason: " 带家人出游 " });
  assert.equal(fields.from_date, "2026-09-29");
  assert.equal(fields.to_date, "2026-10-01");
  assert.deepEqual(JSON.parse(fields.attendance_days), [{ work_date: "2026-09-29", hours: 8 }, { work_date: "2026-10-01", hours: 2.5 }]);
  assert.equal(fields.subject, "年假 10.5 小时 · 带家人出游");
  assert.equal(fields.leave_type, "年假");
  assert.equal(fields.reason, "带家人出游");
  assert.equal(buildFields({ requestType: "加班申请", leaveType: "事假", from: "2026-10-17", to: "2026-10-17", days: [{ work_date: "2026-10-17", hours: 6 }], subject: "值守", reason: "" }).leave_type, "");
});

// ---------------------------------------------------------------- 一行申请的显示

const leaveRow = {
  name: "OA-1", request_type: "请假申请", leave_type: "事假", employee_name: "演示员工186", workflow_status: "待审批", can_act: true, duration_hours: 13.5,
  attendance_days: [{ work_date: "2026-10-26", hours: 8 }, { work_date: "2026-10-27", hours: 3 }, { work_date: "2026-10-28", hours: 2.5 }],
};

test("day chips say 全天 / 上午 / 下午 / 自定义 N 小时, overtime just hours", () => {
  const { chips, more } = rowChips(leaveRow);
  assert.deepEqual(chips.map((chip) => [chip.text, chip.mode]), [
    ["10-26 周一 · 全天", "full"], ["10-27 周二 · 上午", "am"], ["10-28 周三 · 自定义 2.5 小时", "custom"],
  ]);
  assert.equal(more, 0);
  assert.deepEqual([rowChips(leaveRow, 2).chips.length, rowChips(leaveRow, 2).more], [2, 1]);
  assert.equal(dayChip({ work_date: "2026-10-24", hours: 5 }).label, "下午");
  const overtime = rowChips({ request_type: "加班申请", attendance_days: [{ work_date: "2026-10-24", hours: 6 }] }).chips[0];
  assert.deepEqual([overtime.text, overtime.mode], ["10-24 周六 · 6 小时", "custom"]);
  // 加班正好 8 小时也只说小时，不说"全天"
  assert.equal(dayChip({ work_date: "2026-10-24", hours: 8 }, true).label, "8 小时");
  // 只有起止日期的旧申请按期间内的周一到周五 8 小时算
  const legacy = { request_type: "请假申请", from_date: "2026-10-09", to_date: "2026-10-12", attendance_days: [] };
  assert.deepEqual(rowDays(legacy).map((day) => [day.work_date, day.hours]), [["2026-10-09", 8], ["2026-10-12", 8]]);
  assert.equal(totalOf(legacy), 16);
  assert.equal(totalOf(leaveRow), 13.5);
  assert.equal(totalOf({ attendance_days: leaveRow.attendance_days }), 13.5);
});

test("kind, title, status, node and wait text of a row", () => {
  assert.deepEqual([kindOf(leaveRow).text, kindOf(leaveRow).tone], ["请假 · 事假", "leave"]);
  assert.deepEqual([kindOf({ request_type: "加班申请" }).text, kindOf({ request_type: "调休申请" }).tone], ["加班", "comp"]);
  assert.equal(requestTitle(leaveRow), "请假 · 事假 · 10月26日–28日");
  assert.equal(requestTitle({ request_type: "加班申请", attendance_days: [{ work_date: "2026-10-24", hours: 6 }] }), "加班 · 10月24日");
  assert.equal(personShort("演示员工21"), "格乐");
  assert.equal(personShort("演示员工108"), "演示员工108");
  assert.deepEqual(statusTag(leaveRow), { text: "待审批", tone: "warn" });
  assert.deepEqual(statusTag({ workflow_status: "待审批" }), { text: "审批中", tone: "info" });
  assert.deepEqual(statusTag({ workflow_status: "已完成" }), { text: "已通过", tone: "ok" });
  assert.deepEqual(statusTag({ workflow_status: "已拒绝" }), { text: "已驳回", tone: "bad" });
  assert.deepEqual(statusTag({ workflow_status: "草稿" }), { text: "草稿", tone: "" });
  assert.deepEqual(statusTag({ workflow_status: "草稿", operation_log: [{ action: "定向驳回", note: "写清楚", details: { actor: "a@tests-x.example.invalid" } }] }), { text: "被退回", tone: "warn" });
  const pending = { workflow_status: "待审批", current_step_index: 2, current_step_label: "人事经理：周敏", steps: [{ step_index: 2, label: "人事经理：周敏", approvers: ["zhou@tests-x.example.invalid"] }] };
  assert.equal(nodeText({ ...pending, can_act: true }), "轮到你 · 人事经理");
  assert.equal(nodeText(pending, { "zhou@tests-x.example.invalid": "周敏" }), "等待 周敏（人事经理）");
  assert.equal(nodeText({ ...pending, steps: [] }), "等待 人事经理");
  assert.equal(nodeText({ workflow_status: "已完成", my_status: "已通过" }), "我已同意");
  assert.equal(nodeText({ workflow_status: "已拒绝", my_status: "已拒绝" }), "我已驳回");
  assert.equal(nodeText({ workflow_status: "待审批", my_status: "已通过" }), "我已同意 · 流转中");
  assert.equal(nodeText({ workflow_status: "已完成" }), "");
  assert.equal(submittedText({ workflow_status: "待审批", submitted_on: "2026-10-06 09:12:33.123456" }), "10-06 09:12");
  assert.equal(submittedText({ workflow_status: "待审批", creation: "2026-10-06T09:12:33" }), "10-06 09:12");
  assert.equal(submittedText({ workflow_status: "草稿" }), "未提交");
});

test("how long a request has been waiting for the current node", () => {
  const now = Date.parse("2026-10-08T12:00:00");
  assert.equal(waitText({ steps: [{ acted_on: "2026-10-06T11:20:00" }], submitted_on: "2026-10-01 09:00:00" }, now), "2 天");
  assert.equal(waitText({ submitted_on: "2026-10-08 09:00:00" }, now), "3 小时");
  assert.equal(waitText({ submitted_on: "2026-10-08 11:30:00" }, now), "30 分钟");
  assert.equal(waitText({ submitted_on: "2026-10-08 11:59:40" }, now), "刚刚");
  assert.equal(waitText({}, now), "");
  // 最近一次有人处理的时间优先于提交时间
  assert.equal(waitText({ steps: [{ acted_on: "2026-10-08 10:00:00" }, { acted_on: null }], submitted_on: "2026-10-01 09:00:00" }, now), "2 小时");
  const rows = [{ name: "new", submitted_on: "2026-10-08 11:00:00" }, { name: "old", submitted_on: "2026-10-05 11:00:00" }, { name: "none" }];
  assert.deepEqual(byWait(rows, now).map((row) => row.name), ["old", "new", "none"]);
});

test("the effect line and the effect card of a request", () => {
  const overtime = { request_type: "加班申请", attendance_days: [{ work_date: "2026-10-24", hours: 6 }] };
  assert.equal(effectLine(overtime), "通过后：调休额度 +6 小时");
  assert.equal(effectLine({ request_type: "调休申请", attendance_days: [{ work_date: "2026-10-29", hours: 5 }], impact: "调休余额 16h → 8h" }), "通过后：调休余额 16 小时 → 8 小时");
  assert.equal(effectLine({ ...leaveRow, impact: "10 月工时上限 −13.5h" }), "通过后：事假 13.5 小时，10 月工时上限 −13.5 小时");
  assert.equal(effectLine({ ...leaveRow, leave_type: "年假", impact: "年假余额 88h → 80h" }), "通过后：年假余额 88 小时 → 80 小时");
  assert.equal(effectLine({ ...leaveRow, leave_type: "病假" }), "通过后：病假 13.5 小时，不扣年假和工时上限");
  assert.equal(hoursInText("2.5h → 16h"), "2.5 小时 → 16 小时");
  assert.equal(shiftText("调休余额 16h → 8h"), "16 → 8 小时");
  assert.deepEqual(effectRows(overtime).map((row) => [row.label, row.value]), [["调休额度", "+6 小时"]]);
  assert.equal(effectRows({ request_type: "调休申请", attendance_days: [{ work_date: "2026-10-29", hours: 5 }] }, "调休余额 16h → 11h")[0].value, "16 → 11 小时");
  assert.equal(effectRows({ request_type: "请假申请", leave_type: "年假", attendance_days: [{ work_date: "2026-10-29", hours: 8 }] }, "年假余额 88h → 80h")[0].value, "88 → 80 小时");
  // 事假跨月：每个月一行工时上限；已填工时和新上限的对比后端没有给，页面不显示
  const cross = effectRows({ request_type: "请假申请", leave_type: "事假", attendance_days: [{ work_date: "2026-09-30", hours: 8 }, { work_date: "2026-10-01", hours: 3 }] });
  assert.deepEqual(cross.map((row) => [row.kind, row.label, row.value]), [
    ["balance", "事假（不扣年假额度）", "11 小时"], ["cap", "9 月研发工时上限", "−8 小时"], ["cap", "10 月研发工时上限", "−3 小时"],
  ]);
  assert.ok(!cross.some((row) => /已填/.test(row.value)));
  assert.equal(effectRows({ request_type: "请假申请", leave_type: "病假", attendance_days: [{ work_date: "2026-10-29", hours: 8 }] })[0].note, "不扣年假，也不扣当月工时上限");
});

test("my applications: in-progress count and the step tracker", () => {
  const rows = [{ kanban_status: "draft" }, { kanban_status: "pending" }, { kanban_status: "approved" }];
  const info = mineSummary(rows);
  assert.deepEqual([info.total, info.active, info.activeRows.length], [3, 2, 2]);
  const request = {
    workflow_status: "待审批", current_step_index: 2,
    steps: [
      { step_index: 1, label: "直属主管", status: "已通过", approvers: ["chen@tests-x.example.invalid"], acted_on: "2026-09-18T16:00:00" },
      { step_index: 2, label: "人事经理", status: "待审批", approvers: ["zhou@tests-x.example.invalid"] },
      { step_index: 3, label: "总经理", status: "待流转", approvers: ["he@tests-x.example.invalid"] },
    ],
  };
  const names = { "chen@tests-x.example.invalid": "陈立", "zhou@tests-x.example.invalid": "周敏" };
  assert.deepEqual(stepStates(request, names).map((step) => [step.who, step.state]), [["陈立", "done"], ["周敏", "current"], ["he", "wait"]]);
  assert.equal(stepStates({ ...request, workflow_status: "已完成" }, {})[1].state, "wait");
  assert.deepEqual(stepTracker(request, names), [
    { cls: "done", mark: "✓", text: "陈立（直属主管）" }, { cls: "cur", mark: "·", text: "周敏（人事经理） · 当前" }, { cls: "", mark: "·", text: "he（总经理）" },
  ]);
  const returned = { kanban_status: "draft", operation_log: [{ action: "定向驳回", note: "事由写得不清楚", details: { actor: "chen@tests-x.example.invalid" }, timestamp: "2026-09-18T15:11:06" }] };
  assert.deepEqual(returnedDrafts([returned, { kanban_status: "draft" }, { kanban_status: "pending", operation_log: returned.operation_log }]), [returned]);
  assert.deepEqual(rejectionOf(returned), { actor: "chen@tests-x.example.invalid", note: "事由写得不清楚", time: "2026-09-18T15:11:06" });
  assert.equal(rejectionOf({}), null);
});

test("the reviewed list says what I did and when", () => {
  assert.deepEqual(reviewedResult({ my_status: "已通过" }), { text: "已同意", tone: "ok" });
  assert.deepEqual(reviewedResult({ my_status: "已拒绝" }), { text: "已驳回", tone: "bad" });
  assert.equal(actedText({ acted_on: "2026-10-09 14:30:12" }), "10-09 14:30");
  assert.equal(actedText({}), "");
});

test("the balance cards", () => {
  assert.deepEqual(balanceKpis({ annual: { available_hours: 240, used_hours: 0 }, comp: { available_hours: 12, credit_hours: 16 } }), {
    annual: { days: "30", hours: "240", used: "0" }, comp: { hours: "12", credit: "16" },
  });
  assert.deepEqual(balanceKpis(null), { annual: null, comp: null });
});

// ---------------------------------------------------------------- 月历、日期、请求

test("dates read naturally", () => {
  assert.equal(rangeText("2026-10-13", "2026-10-14"), "10月13日–14日");
  assert.equal(rangeText("2026-09-30", "2026-10-02"), "9月30日–10月2日");
  assert.equal(rangeText("2026-10-13", "2026-10-13"), "10月13日");
  assert.equal(dayLabel("2026-10-05"), "10月5日");
  assert.equal(numText(1.5), "1.5");
  assert.equal(numText(2), "2");
});

test("only the newest of several overlapping requests may apply its result", () => {
  const latest = createLatest();
  const first = latest.begin();
  const second = latest.begin();
  assert.equal(latest.isCurrent(first), false);
  assert.equal(latest.isCurrent(second), true);
});

test("names inside step labels and department suffixes are not shown twice", () => {
  assert.equal(stepRole("直属主管：陈立"), "直属主管");
  assert.equal(stepRole("人事经理"), "人事经理");
  assert.equal(departmentLabel("客服部 - RAY"), "客服部");
  assert.equal(departmentLabel("Round3 Review B - RAY"), "Round3 Review B");
  assert.equal(departmentLabel("研发部"), "研发部");
});

test("a request starts on its first day with hours and ends on its last", () => {
  const days = [{ work_date: "2026-10-14", hours: 0 }, { work_date: "2026-10-15", hours: 8 }, { work_date: "2026-10-16", hours: 5 }, { work_date: "2026-10-19", hours: 0 }];
  assert.deepEqual(workedSpan(days, "2026-10-14", "2026-10-19"), { from: "2026-10-15", to: "2026-10-16" });
  assert.deepEqual(workedSpan([], "2026-10-14", "2026-10-19"), { from: "2026-10-14", to: "2026-10-19" });
});

// ---------------------------------------------------------------- 页面接线（读源码）

test("the four views are wired: home buttons, list header, detail actions and the new page", () => {
  const home = read("../src/components/attendance/AttendanceHome.vue");
  // 首页三个明确的新建按钮，各带自己的类型
  assert.match(home, /v-for="\(type, index\) in availableTypes"/);
  assert.match(home, /emit\('new', TYPES\[type\]\.label\)/);
  assert.match(home, /＋ 新建\{\{ TYPES\[type\]\.label \}\}/);
  for (const text of ["年假可用", "调休可用", "我的申请", "待我审批", "本月已请假", "团队今日请假", "团队本月请假", "今日在岗", "出勤率", "今日请假"]) assert.ok(home.includes(text), text);
  assert.match(home, /emit\('list', 'done', 'all'\)/);
  // 待我审批是一人一行的紧凑列表：驳回在行内完成（原因必填、可以选退回给谁），点一行才展开影响，按钮不会同时触发进详情
  const queue = read("../src/components/attendance/AttendanceQueue.vue");
  for (const text of ["批之前先看影响", "确认驳回", "驳回原因（必填），申请人会看到", "驳回必须写原因", "去详情处理"]) assert.ok(queue.includes(text), text);
  assert.match(queue, /emit\('list', 'todo', 'all'\)/);
  assert.match(queue, /props\.rejectRow \? await props\.rejectRow\(row, note\.value\.trim\(\), target\.value\)/);
  assert.match(queue, /row\.rejection_targets/);
  assert.match(queue, /row\.hints/);
  assert.match(queue, /class="who" role="button"/);
  assert.doesNotMatch(queue, /emit\('reject'/);
  assert.match(home, /<AttendanceMineCard/);
  assert.doesNotMatch(home, /AttendanceTeamGrid/);
  const mineCard = read("../src/components/attendance/AttendanceMineCard.vue");
  for (const text of ["我的申请 · 进行中", "继续填写", "撤回", "查看", "没有进行中的申请"]) assert.ok(mineCard.includes(text), text);
  const list = read("../src/components/attendance/AttendanceList.vue");
  assert.match(list, /newButtonLabel\(filter\)/);
  // 列表的新建按钮把当前类型筛选带出去：加班列表新建加班，全部列表才让用户先选
  assert.match(list, /emit\('new', filter\)/);
  assert.doesNotMatch(list, /emit\('new'\)/);
  assert.match(list, /listTitle\(filter\.value\)/);
  assert.match(list, /批量同意/);
  assert.match(list, /v-if="scope === 'todo'" class="at-check"/);
  const detail = read("../src/components/attendance/AttendanceDetail.vue");
  for (const text of ["审批意见（驳回时必填）", "驳回必须写意见", "撤回申请", "继续填写", "修改后重新提交", "逐日明细", "通过后的影响", "审批进度", "抄送", "操作记录", "暂不能撤回"]) assert.ok(detail.includes(text), text);
  assert.match(detail, /expected_step_key: request\.value\?\.current_step_key/);
  assert.match(detail, /request\.rejection_targets/);
  assert.match(detail, /reject_target/);
  assert.match(detail, /request\.attachments/);
  assert.match(detail, /v-if="hasOrigin"/);                    // 面包屑里的"返回列表"只在从列表来的时候出现
  assert.match(detail, /latest\.isCurrent\(token\)/);
});

test("the new page: every day offers 全天 / 上午 / 下午 / 自定义小时 / 不请, custom is a 0.5 stepper capped by the day, switching type resets", () => {
  const form = read("../src/components/attendance/AttendanceForm.vue");
  for (const mode of ["full", "am", "pm", "custom", "none"]) assert.match(form, new RegExp(`key: '${mode}'`));
  for (const text of ["全天", "上午", "下午", "自定义小时", "不请", "减 0.5 小时", "加 0.5 小时", "保存草稿", "提交申请", "取消", "审批路线"]) assert.ok(form.includes(text), text);
  assert.match(form, /:disabled="!modeAvailable\(row\.day, mode\.key\)"/);
  assert.match(form, /customCap\(row\.day\)/);
  assert.match(form, /mergeDays\(data\?\.days, form\.days, overtime\.value, \{ zeroNew \}\)/);
  assert.match(form, /latest\.isCurrent\(token\) \|\| type !== props\.requestType/);   // 换类型后旧类型的结果丢掉
  assert.match(form, /watch\(\(\) => props\.requestType/);
  assert.match(form, /Object\.assign\(form, \{ leaveType: '事假', days: \[\], subject: '' \}\)/);
  assert.match(form, /emit\('switch-type'/);
  assert.match(form, /person\.name/);
  assert.doesNotMatch(form, /approvers\.join/);
  assert.doesNotMatch(form, />半天<\/button>/);
});

test("the page keeps the context: picker only without a type, guard for unsaved forms, tokens for every load", () => {
  const page = read("../src/pages/AttendanceCenter.vue");
  assert.match(page, /v-else-if="!page\.newType"/);              // 没有类型只显示选择卡片
  assert.match(page, /你要新建哪一种？/);
  assert.match(page, /router\.beforeEach/);
  assert.match(page, /beforeunload/);
  assert.match(page, /createLatest\(\)/);
  assert.match(page, /latest\[key\]\.isCurrent\(token\)/);
  assert.match(page, /backLocation\(/);
  assert.match(page, /newLocation\(/);
  assert.match(page, /detailLocation\(/);
  assert.match(page, /expected_step_key: row\.current_step_key/);
  assert.match(page, /action: 'reject', note, expected_step_key: row\.current_step_key \|\| '', reject_target: target \|\| 'applicant'/);   // 首页卡片上直接驳回
  assert.match(page, /:reject-row="rejectNow"/);
  assert.match(page, /router\.getRoutes\(\)/);
  assert.match(page, /\{ replace: true \}/);
  const view = read("../src/lib/attendanceView.js");
  for (const name of ["get_attendance_home", "get_attendance_route", "list_attendance_mine", "list_attendance_review", "list_attendance_reviewed", "list_attendance_all", "get_attendance_request"]) {
    assert.match(view, new RegExp(`attendance_entry\\.${name}`));
  }
  assert.doesNotMatch(view, /半天 4 小时/);
});

test("the routes stay as they were, and the replaced components are gone", () => {
  const router = read("../src/router.js");
  for (const path of ["/approval/leave", "/approval/overtime", "/approval/comp-time"]) {
    assert.match(router, new RegExp(`path: '${path}', component: attendancePage`));
    assert.match(router, new RegExp(`path: '${path}/:name'[^\\n]*component: attendancePage`));
  }
  assert.match(router, /path: '\/approval\/reimbursement', component: approvalPage/);
  assert.equal(exists("../src/components/attendance/AttendanceCards.vue"), false);
  assert.equal(exists("../src/components/attendance/AttendanceReview.vue"), false);
  for (const name of ["AttendanceHome", "AttendanceList", "AttendanceDetail", "AttendanceForm", "AttendanceMineCard", "AttendanceQueue", "AttendanceCalendar", "AttendanceDeptTable", "AttendanceMyStrip", "AttendanceCharts", "AttendanceMetrics"]) assert.equal(exists(`../src/components/attendance/${name}.vue`), true, name);
  assert.equal(exists("../src/components/attendance/AttendanceTeamGrid.vue"), false);   // 两周网格换成了团队日历
});
