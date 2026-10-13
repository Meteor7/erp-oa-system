import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import {
  TYPES, TYPE_LABELS, TYPE_ORDER, detailLocation, effectLine, effectRows, isTrip, kindOf, listLocation, newLocation, pathForFilter, parseLocation,
  backLabel, backLocation, originOf, originQuery, requestTitle, rowDays, sizeText, tripDayCount, typeCounts, typeForPath,
} from "../src/lib/attendanceView.js";
import { applyFilters, lengthText, statusInfo, stripCells, whenText } from "../src/lib/attendanceFlow.js";
import { rowKind } from "../src/lib/attendanceCharts.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const exists = (path) => existsSync(new URL(path, import.meta.url));

// 2026-10-12（周一）到 10-14（周三）出差上海，已通过；周末也是出差日，不看工作日。
const trip = (extra = {}) => ({
  name: "OA-T1", request_type: "出差申请", employee_name: "演示员工117", department: "研发软件部", workflow_status: "已完成", subject: "上海客户拜访",
  travel_destination: "上海", travel_start_date: "2026-10-12", travel_end_date: "2026-10-14", travel_days: 3, project: "P1", reason: "拜访客户", ...extra,
});

test("出差申请 is the fourth type of the attendance centre and keeps its old address", () => {
  assert.deepEqual(TYPE_ORDER, ["请假申请", "加班申请", "调休申请", "出差申请"]);
  assert.deepEqual(TYPE_LABELS, ["请假", "加班", "调休", "出差"]);
  assert.equal(TYPES["出差申请"].path, "/approval/travel");
  assert.equal(typeForPath("/approval/travel"), "出差申请");
  assert.equal(typeForPath("/approval/travel/OA-1"), "出差申请");
  assert.equal(pathForFilter("出差"), "/approval/travel");
  assert.deepEqual(typeCounts([trip(), trip({ name: "OA-T2" }), { request_type: "请假申请" }]), { all: 3, 请假: 1, 加班: 0, 调休: 0, 出差: 2 });
  assert.equal(isTrip(trip()), true);
  assert.equal(isTrip({ request_type: "请假申请" }), false);
});

test("the old travel links keep working inside the attendance centre", () => {
  // 通知、看板、报销里的 /approval/travel?request=… 打开出差申请详情
  const detail = parseLocation({ path: "/approval/travel", query: { request: "OA-T1" } });
  assert.equal(detail.view, "detail");
  assert.equal(detail.request, "OA-T1");
  // /approval/travel/OA-T1
  assert.equal(parseLocation({ path: "/approval/travel/OA-T1", params: { name: "OA-T1" } }).view, "detail");
  // 侧栏点进来：出差列表，还没选范围
  const list = parseLocation({ path: "/approval/travel", query: {} });
  assert.deepEqual([list.view, list.filter, list.scope], ["list", "出差", ""]);
  // 旧的列表链接 ?view=list&scope=all（报销看板上的“出差中 / 本月出差”）
  const all = parseLocation({ path: "/approval/travel", query: { view: "list", scope: "all" } });
  assert.deepEqual([all.view, all.scope, all.filter], ["list", "all", "出差"]);
  // 旧的新建链接 ?view=new 直接进出差表单，不让用户先选类型；继续草稿也一样
  assert.equal(parseLocation({ path: "/approval/travel", query: { view: "new" } }).newType, "出差");
  assert.equal(parseLocation({ path: "/approval/travel", query: { draft: "OA-T1" } }).newType, "出差");
  assert.equal(parseLocation({ path: "/approval/leave", query: { view: "new" } }).newType, "", "other types still ask first");
  // 从考勤中心跳出去的链接
  assert.deepEqual(listLocation({ scope: "todo", filter: "出差" }), { path: "/approval/travel", query: { view: "list", scope: "todo", type: "出差" } });
  assert.deepEqual(detailLocation({ name: "OA-T1", type: "出差" }).path, "/approval/travel");
  assert.equal(newLocation({ type: "出差" }).query.type, "出差");
});

test("a trip covers every calendar day from departure to return and says days, not hours", () => {
  const days = rowDays(trip({ travel_start_date: "2026-10-09", travel_end_date: "2026-10-12" }));
  assert.deepEqual(days.map((day) => day.work_date), ["2026-10-09", "2026-10-10", "2026-10-11", "2026-10-12"]);
  assert.deepEqual(rowDays(trip({ travel_start_date: "", travel_end_date: "" })), []);
  assert.deepEqual(rowDays(trip({ travel_start_date: "2026-10-14", travel_end_date: "2026-10-12" })), []);
  assert.equal(tripDayCount(trip()), 3);
  assert.equal(tripDayCount(trip({ travel_days: 0 })), 3, "falls back to the dates");
  assert.equal(sizeText(trip()), "3 天");
  assert.equal(sizeText({ request_type: "请假申请", duration_hours: 16 }), "16 小时");
  assert.equal(lengthText(trip()), "3 天");
  assert.equal(whenText(trip()), "10/12 周一 – 10/14 周三");
  assert.equal(whenText(trip({ travel_end_date: "2026-10-12", travel_days: 1 })), "10/12 周一", "a one-day trip has no 全天 chip");
});

test("a trip row shows its destination, colour and a day strip marked 出差", () => {
  assert.equal(kindOf(trip()).text, "出差 · 上海");
  assert.equal(kindOf(trip()).label, "出差");
  assert.equal(kindOf(trip()).tone, "trip");
  assert.equal(kindOf(trip({ travel_destination: "" })).text, "出差");
  assert.equal(rowKind(trip()), "trip");
  assert.equal(requestTitle(trip()), "出差 · 上海 · 10月12日–14日");
  const cells = stripCells(trip());
  assert.ok(cells.length >= 3 && cells.filter((cell) => cell.hit).every((cell) => cell.text === "出差"));
  assert.equal(cells.filter((cell) => cell.hit).length, 3);
  assert.equal(statusInfo(trip({ workflow_status: "待审批", can_act: false, steps: [] }), "mine", Date.now()).tag.text, "审批中");
});

test("a trip says what it does to nothing: no balance, only that reimbursements can link to it", () => {
  assert.match(effectLine(trip()), /不扣年假和工时上限/);
  const rows = effectRows(trip());
  assert.equal(rows.length, 1);
  assert.equal(rows[0].value, "不扣额度");
  assert.match(rows[0].note, /报销/);
});

test("the list can search a trip by destination or project", () => {
  const rows = [trip(), trip({ name: "OA-T2", travel_destination: "北京", project: "P2", subject: "展会" })];
  assert.deepEqual(applyFilters(rows, { query: "上海" }).map((row) => row.name), ["OA-T1"]);
  assert.deepEqual(applyFilters(rows, { query: "p2" }).map((row) => row.name), ["OA-T2"]);
  assert.deepEqual(applyFilters(rows, { type: "出差" }).map((row) => row.name), ["OA-T1", "OA-T2"]);
  assert.deepEqual(applyFilters([...rows, { request_type: "请假申请", name: "OA-L" }], { type: "出差" }).map((row) => row.name), ["OA-T1", "OA-T2"]);
});

// ---------------------------------------------------------------- 页面接线

test("the old travel page is gone and /approval/travel opens the attendance centre", () => {
  for (const gone of ["../src/pages/TravelRequest.vue", "../src/components/travel/TravelWorkbench.vue", "../src/components/travel/TravelTable.vue"]) {
    assert.equal(exists(gone), false, gone);
  }
  const router = read("../src/router.js");
  assert.match(router, /\{ path: '\/approval\/travel', component: attendancePage \}/);
  assert.match(router, /\{ path: '\/approval\/travel\/:name', component: attendancePage \}/);
  assert.doesNotMatch(router, /TravelRequest/);
  const center = read("../src/pages/AttendanceCenter.vue");
  assert.match(center, /import AttendanceTripForm from '\.\.\/components\/attendance\/AttendanceTripForm\.vue'/);
  assert.match(center, /<AttendanceTripForm\s+v-else-if="newTypeRequest === '出差申请'"/);
});

test("the trip form saves and submits through the same travel endpoints as before and keeps the old rules", () => {
  const form = read("../src/components/attendance/AttendanceTripForm.vue");
  assert.match(form, /api\.saveTravel\(\{ payload: JSON\.stringify\(payload\(\)\), name: savedName\.value \|\| undefined \}\)/);
  assert.match(form, /api\.submitDraft\(doc\.name\)/);
  assert.match(form, /travelBlockers\(payload\(\)\)/);
  assert.match(form, /defineExpose\(\{ dirty \}\)/, "leaving a half-filled form still asks");
  assert.match(form, /:overtime="true"/, "weekends can be picked for a trip");
  const view = read("../src/lib/attendanceView.js");
  assert.match(view, /saveTravel: \(params\) => callApi\('travel_entry\.save_travel_draft', params\)/);
  assert.match(view, /expense_claim_entry\.list_claim_projects/);
});

test("a finished trip can start a reimbursement or a payment straight from its detail", () => {
  const detail = read("../src/components/attendance/AttendanceDetail.vue");
  assert.match(detail, /const canPush = computed\(\(\) => trip\.value && Boolean\(data\.value\?\.mine\)/);
  assert.match(detail, /@click="push\('claim'\)">发起报销</);
  assert.match(detail, /@click="push\('payment'\)">发起付款</);
  assert.match(detail, /query: \{ source: props\.name, from: hereAsFrom\(route\.path, route\.query\) \}/);
  assert.match(detail, /v-if="!trip" class="af-ps"/, "a trip has no per-day hours table");
});

test("the approval centre and the sidebar no longer list trips next to purchase requests", () => {
  const group = read("../src/lib/approvalGroup.js");
  assert.doesNotMatch(group, /\/approval\/travel/);
  const paths = read("../src/lib/approvalGroupPaths.js");
  assert.doesNotMatch(paths, /\/approval\/travel/);
});

test("a trip opened from the dashboard (or another page) goes back to that page, not to a list", () => {
  const query = { request: "OA-T1", from: "/dashboard/detail?item=att.trip&period=2026-10" };
  const origin = originOf(query);
  assert.equal(origin.kind, "page");
  assert.deepEqual(backLocation(origin), { path: "/dashboard/detail", query: { item: "att.trip", period: "2026-10" } });
  assert.equal(backLabel(origin), "返回看板明细");
  assert.deepEqual(originQuery(origin), { from: "/dashboard/detail?item=att.trip&period=2026-10" });
  assert.equal(backLabel(originOf({ from: "/somewhere/else" })), "返回上一页");
  // 外部地址和脚本地址不当作来源
  assert.equal(originOf({ from: "//evil.example/x" }).kind, "");
  assert.equal(originOf({ from: "https://evil.example/x" }).kind, "");
  // 原来的两种来源不变
  assert.equal(originOf({ from: "home" }).kind, "home");
  assert.deepEqual(originOf({ from: "list", fscope: "todo", ftype: "出差" }), { kind: "list", scope: "todo", filter: "出差" });
  assert.equal(backLabel(originOf({})), "返回列表");
});
