import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { awayToday, listLocation, parseLocation } from "../src/lib/attendanceView.js";
import {
  contractDates, currentPeriodText, entryQuery, entryRowsFor, isContractOverdue, normalizeFolderTab, overdueRows,
  parseEntryQuery, todayText, validPeriod,
} from "../src/lib/dashboardLanding.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const NOW = new Date(2026, 9, 9); // 2026-10-09

test("local date helpers", () => {
  assert.equal(currentPeriodText(NOW), "2026-10");
  assert.equal(todayText(NOW), "2026-10-09");
  assert.equal(todayText(new Date(2026, 0, 5)), "2026-01-05");
  assert.equal(validPeriod("2026-09"), "2026-09");
  for (const bad of ["2026-13", "2026-9", "2026", "", undefined, "abc", "2026-00"]) assert.equal(validPeriod(bad), "", String(bad));
});

// ---------------------------------------------------------------- 工时填报
test("timesheet entry reads tab / status / dept / period from the address and ignores junk", () => {
  assert.deepEqual(parseEntryQuery({ tab: "board", status: "open", dept: "研发部", period: "2026-09" }), { tab: "board", status: "open", dept: "研发部", period: "2026-09" });
  assert.deepEqual(parseEntryQuery({ tab: "sheet" }), { tab: "sheet", status: "all", dept: "all", period: "" });
  assert.deepEqual(parseEntryQuery({ tab: "x", status: "weird", period: "2026-99" }), { tab: "", status: "all", dept: "all", period: "" });
  assert.deepEqual(parseEntryQuery({}), { tab: "", status: "all", dept: "all", period: "" });
  assert.deepEqual(parseEntryQuery(), { tab: "", status: "all", dept: "all", period: "" });
  for (const status of ["none", "part", "full", "over", "open"]) assert.equal(parseEntryQuery({ status }).status, status);
  // vue-router 重复参数给数组：取第一个
  assert.equal(parseEntryQuery({ status: ["none", "part"] }).status, "none");
});

test("timesheet entry writes only what is not the default back to the address and keeps unrelated keys", () => {
  assert.deepEqual(entryQuery({ tab: "", status: "all", dept: "all", period: "2026-10" }, {}, NOW), {});
  assert.deepEqual(entryQuery({ tab: "board", status: "open", dept: "研发部", period: "2026-09" }, {}, NOW), { tab: "board", status: "open", dept: "研发部", period: "2026-09" });
  // 当前月不写；from（看板的返回地址）原样保留；旧的筛选键被清掉
  const base = { from: "/dashboard?tab=rd", status: "none", dept: "客服部", period: "2026-09", other: "1" };
  assert.deepEqual(entryQuery({ tab: "sheet", status: "all", dept: "all", period: "2026-10" }, base, NOW), { from: "/dashboard?tab=rd", other: "1", tab: "sheet" });
  // 地址 → 状态 → 地址 不变（来回不抖动）
  const query = { tab: "board", status: "open", dept: "研发部", period: "2026-09" };
  assert.deepEqual(entryQuery(parseEntryQuery(query), {}, NOW), query);
});

const people = [
  { employee: "E1", employee_name: "甲", department: "研发部", status: "none", used_days: 0, limit_days: 20 },
  { employee: "E2", employee_name: "乙", department: "研发部", status: "part", used_days: 10, limit_days: 20 },
  { employee: "E3", employee_name: "丙", department: "客服部", status: "full", used_days: 20, limit_days: 20 },
  { employee: "E4", employee_name: "丁", department: "客服部", status: "over", used_days: 22, limit_days: 20 },
  { employee: "E5", employee_name: "戊", department: "客服部", status: "part", used_days: 5, limit_days: 20 },
];

test("the follow-up list: open = none + part, full lists the people who are done, other statuses as before", () => {
  const names = (rows) => rows.map((item) => item.employee_name);
  assert.deepEqual(names(entryRowsFor(people, { status: "open" })).sort(), ["乙", "甲", "戊"].sort());
  assert.deepEqual(names(entryRowsFor(people, { status: "open", department: "客服部" })), ["戊"]);
  assert.deepEqual(names(entryRowsFor(people, { status: "full" })), ["丙"]);
  assert.deepEqual(names(entryRowsFor(people, { status: "full", department: "研发部" })), []);
  assert.deepEqual(names(entryRowsFor(people, { status: "none" })), ["甲"]);
  assert.deepEqual(names(entryRowsFor(people, { status: "over" })), ["丁"]);
  // 不选状态：需要跟进的（未填、未填满、超上限）都在，已填满的不在
  assert.deepEqual(names(entryRowsFor(people, {})).sort(), ["丁", "乙", "戊", "甲"].sort());
});

test("the timesheet page and its board take their filters from the address and write them back", () => {
  const page = read("../src/pages/TimesheetEntry.vue");
  const board = read("../src/components/timesheet/EntryBoard.vue");
  assert.match(page, /from "\.\.\/lib\/dashboardLanding"/);
  assert.match(page, /parseEntryQuery\(route\.query\)/);
  assert.match(page, /if \(landing\.period\) period\.value = landing\.period/);
  assert.match(page, /const tabChoice = ref\(landing\.tab\)/);
  assert.match(page, /router\.replace\(\{ path: route\.path, query: next \}\)/);
  // 离开本页时不能再动别的页面的地址
  assert.match(page, /if \(route\.path !== ownPath\) return;/);
  assert.match(page, /v-model:dept="boardDept"/);
  assert.match(page, /v-model:status="boardStatus"/);
  assert.match(board, /'update:dept'/);
  assert.match(board, /'update:status'/);
  assert.ok(board.includes("未完成"));
  assert.ok(board.includes("已填满"));
  assert.match(board, /entryRowsFor\(/);
  // 没有部门栏（只看自己团队）时，地址里的部门不生效
  assert.match(board, /showDepartment\.value && dept\.value !== 'all'/);
});

// ---------------------------------------------------------------- 发票夹
test("invoice folder tabs from the address: finance and staff have different tab sets", () => {
  for (const tab of ["dup", "allinv", "mine"]) assert.equal(normalizeFolderTab(tab, true), tab);
  for (const tab of ["list", "todo", "ok", "used", "dup"]) assert.equal(normalizeFolderTab(tab, false), tab);
  // 没写页签：各用各的默认页签
  assert.equal(normalizeFolderTab("", true), "dup");
  assert.equal(normalizeFolderTab(undefined, false), "list");
  // 不属于自己这一套的页签退到最接近的：财务看全部发票，员工看全部
  for (const tab of ["todo", "ok", "used", "list", "bogus"]) assert.equal(normalizeFolderTab(tab, true), "allinv", tab);
  for (const tab of ["allinv", "mine", "bogus"]) assert.equal(normalizeFolderTab(tab, false), "list", tab);
  const page = read("../src/pages/InvoiceFolder.vue");
  assert.match(page, /ref\(normalizeFolderTab\(route\.query\.tab, finance\)\)/);
  assert.match(page, /view = computed\(\(\) => \(route\.query\.view === 'list' \? 'list' : 'home'\)\)/);
});

// ---------------------------------------------------------------- 物料进度
test("contract delivery dates come as one string joined by 、", () => {
  assert.deepEqual(contractDates({ contract_delivery_date: "2026-10-12、2026-10-01" }), ["2026-10-01", "2026-10-12"]);
  assert.deepEqual(contractDates({ contract_delivery_date: "" }), []);
  assert.deepEqual(contractDates({}), []);
  assert.deepEqual(contractDates({ contract_delivery_date: "待定" }), []);
});

test("a material line is overdue when its contract date has passed and the PO quantity is not fully received", () => {
  const today = "2026-10-09";
  const row = (extra) => ({ contract_delivery_date: "2026-10-01", po_quantity: 10, received_quantity: 4, record_status: "正常", ...extra });
  assert.equal(isContractOverdue(row(), today), true);
  // 收齐了（含超收）不算
  assert.equal(isContractOverdue(row({ received_quantity: 10 }), today), false);
  assert.equal(isContractOverdue(row({ received_quantity: 12 }), today), false);
  // 合同交期是今天或以后不算（必须早于今天）
  assert.equal(isContractOverdue(row({ contract_delivery_date: "2026-10-09" }), today), false);
  assert.equal(isContractOverdue(row({ contract_delivery_date: "2026-10-20" }), today), false);
  // 缺合同交期、还没下 PO 的不算；已取消的物料不算
  assert.equal(isContractOverdue(row({ contract_delivery_date: "" }), today), false);
  assert.equal(isContractOverdue(row({ po_quantity: 0, received_quantity: 0 }), today), false);
  assert.equal(isContractOverdue(row({ record_status: "已取消" }), today), false);
  assert.equal(isContractOverdue(null, today), false);
  // 分批交期取最早的一个
  assert.equal(isContractOverdue(row({ contract_delivery_date: "2026-10-01、2026-11-01" }), today), true);
  // 接口以后直接给逐 PO 行算好的结果时，以它为准
  assert.equal(isContractOverdue(row({ contract_overdue: false }), today), false);
  assert.equal(isContractOverdue(row({ contract_delivery_date: "", contract_overdue: true }), today), true);
  assert.deepEqual(overdueRows([row(), row({ received_quantity: 10 }), row({ record_status: "已取消" })], today).length, 1);
});

test("the material board reads overdue=1, fetches every page for that mode and can be cleared", () => {
  const page = read("../src/pages/MaterialProgress.vue");
  assert.match(page, /String\(route\.query\.overdue \|\| ''\) === '1'/);
  assert.match(page, /overdueRows\(items, todayText\(\)\)/);
  assert.match(page, /const SWEEP_SIZE = 200/);
  assert.match(page, /if \(overdueOnly\.value\) sweepOverdue\(\)/);
  assert.match(page, /router\.replace\(\{ path: route\.path, query: next \}\)/);
  assert.match(page, /查看全部物料/);
  assert.match(page, /const pageSize = 50/);
  assert.match(page, /if \(route\.path !== ownPath\) return;/);
});

// ---------------------------------------------------------------- 考勤中心
test("attendance center: today=1 only counts in the 'all' scope, and stays on type switches only", () => {
  assert.equal(parseLocation({ path: "/approval/attendance", query: { view: "list", scope: "all", today: "1" } }).today, true);
  assert.equal(parseLocation({ path: "/approval/attendance", query: { view: "list", scope: "mine", today: "1" } }).today, false);
  assert.equal(parseLocation({ path: "/approval/attendance", query: { view: "list", scope: "all" } }).today, false);
  assert.equal(parseLocation({ path: "/approval/attendance", query: { view: "list", scope: "all", today: "0" } }).today, false);
  const home = "/approval/attendance";
  assert.deepEqual(listLocation({ scope: "all", filter: "all", today: true }, home), { path: home, query: { view: "list", scope: "all", type: "all", today: "1" } });
  // 换到别的范围就去掉；不带 today 的老调用不变
  assert.deepEqual(listLocation({ scope: "mine", filter: "all", today: true }, home), { path: home, query: { view: "list", scope: "mine", type: "all" } });
  assert.deepEqual(listLocation({ scope: "all", filter: "all" }, home), { path: home, query: { view: "list", scope: "all", type: "all" } });
});

test("who is away today: approved leave / comp-time whose dates include today; overtime and unapproved do not count", () => {
  const today = "2026-10-09";
  const row = (extra) => ({ request_type: "请假申请", workflow_status: "已完成", from_date: "2026-10-08", to_date: "2026-10-10", ...extra });
  assert.equal(awayToday([row()], today).length, 1);
  assert.equal(awayToday([row({ request_type: "调休申请", workflow_status: "已通过" })], today).length, 1);
  assert.equal(awayToday([row({ from_date: "2026-10-09", to_date: "2026-10-09" })], today).length, 1);
  assert.equal(awayToday([row({ from_date: "2026-10-10", to_date: "2026-10-12" })], today).length, 0);
  assert.equal(awayToday([row({ from_date: "2026-10-01", to_date: "2026-10-08" })], today).length, 0);
  assert.equal(awayToday([row({ request_type: "加班申请" })], today).length, 0);
  for (const workflow_status of ["待审批", "待办理", "草稿", "已驳回", "已撤回"]) assert.equal(awayToday([row({ workflow_status })], today).length, 0, workflow_status);
  assert.equal(awayToday([row({ from_date: "", to_date: "" })], today).length, 0);
  assert.deepEqual(awayToday(null, today), []);
});

test("the attendance pages wire today=1 through and fall back to 'mine' with a notice when 'all' is not allowed", () => {
  const center = read("../src/pages/AttendanceCenter.vue");
  const list = read("../src/components/attendance/AttendanceList.vue");
  assert.match(center, /@today-off="clearToday"/);
  assert.match(center, /你没有查看全部申请的权限，已显示「我的」/);
  assert.match(center, /validScope\(page\.value\.scope, \{ canViewAll: canViewAll\.value \}\)/);
  assert.match(center, /<div v-if="notice" class="banner info"/);
  assert.match(list, /awayToday\(list, todayText\(new Date\(props\.now\)\)\)/);
  assert.match(list, /今天不在岗/);
  assert.match(list, /今天没有人在休假或调休/);
});
