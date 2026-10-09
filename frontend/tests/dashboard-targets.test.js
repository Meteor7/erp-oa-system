import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  buildTargetTable, dashboardFrom, mergeQuery, resolveTarget, targetHint, targetState,
} from "../src/lib/dashboardTargets.js";
import { canSee } from "../src/lib/access.js";

// 前后端共用同一份目标表；测试直接读后端那份 JSON（页面里是 vite 打包进去的，见 lib/dashboardTargetsData.js）。
const json = JSON.parse(readFileSync(new URL("../../rayher_hr_payroll/dashboard/targets.json", import.meta.url), "utf8"));
const table = buildTargetTable(json);
const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

// 目标页还没有路由时才往这里写（现在 /approval/attendance 已经补上，清单是空的）。
const PENDING_ROUTES = [];

const open = { canSee: () => true, claimAll: true, travelAll: true };
const from = "/dashboard?tab=overview";

// ---------------------------------------------------------------- 目标表
test("every backend target is in the front-end table and points at a real route", () => {
  const keys = Object.keys(json.targets);
  assert.ok(keys.length > 30);
  assert.deepEqual(Object.keys(table).sort(), keys.sort());
  for (const [key, spec] of Object.entries(table)) {
    assert.ok(spec.path.startsWith("/"), `${key} path`);
    const routed = routerSource.includes(`path: '${spec.path}'`);
    assert.ok(routed || PENDING_ROUTES.includes(spec.path), `${key}: ${spec.path} has no route in router.js (and is not in the pending list)`);
  }
});

test("a pending route really is pending or already added, never silently stale", () => {
  for (const path of PENDING_ROUTES) {
    assert.ok(Object.values(table).some((spec) => spec.path === path), `${path} is no longer used by any target; drop it from PENDING_ROUTES`);
  }
});

test("a dynamic parameter never collides with the fixed query of the same target", () => {
  for (const [key, spec] of Object.entries(table)) {
    for (const name of spec.params) assert.ok(!(name in spec.query), `${key}: ${name} is both fixed and dynamic`);
    assert.equal(new Set(spec.params).size, spec.params.length, `${key}: duplicate params`);
    assert.ok(spec.label, `${key}: label`);
  }
});

test("buildTargetTable accepts the whole file or just the targets and skips malformed entries", () => {
  const spec = { label: "付款申请", path: "/approval/payment", query: { view: "list" }, params: ["request"] };
  assert.deepEqual(buildTargetTable({ _doc: "x", targets: { a: spec } }).a, { key: "a", label: "付款申请", path: "/approval/payment", query: { view: "list" }, params: ["request"] });
  assert.deepEqual(Object.keys(buildTargetTable({ a: spec, b: null, c: { path: "no-slash" }, d: { label: "x" } })), ["a"]);
  assert.deepEqual(buildTargetTable(null), {});
  assert.deepEqual(buildTargetTable({ a: { path: "/x" } }).a.params, []);
});

// ---------------------------------------------------------------- 解析
test("a fixed query and the dynamic params are merged, with from added", () => {
  assert.deepEqual(resolveTarget({ key: "payment.waiting", params: {} }, { table, from, access: open }),
    { path: "/approval/payment", query: { view: "list", scope: "all", bucket: "topay", long: "1", from } });
  assert.deepEqual(resolveTarget({ key: "payment.detail", params: { request: "OA-1" } }, { table, from, access: open }),
    { path: "/approval/payment", query: { request: "OA-1", from } });
  assert.deepEqual(resolveTarget({ key: "timesheet.board", params: { status: "open", dept: "研发软件部", period: "2026-10" } }, { table, from, access: open }).query,
    { tab: "board", status: "open", dept: "研发软件部", period: "2026-10", from });
});

test("params that the target does not declare are dropped, empty ones too, numbers become strings", () => {
  const spec = table["claim.todo"];
  assert.deepEqual(mergeQuery(spec, { request: "OA-1", scope: "all" }), { view: "list", scope: "todo" });
  assert.deepEqual(mergeQuery(table["cost.summary"], { period: "", project: null, other: "x" }), {});
  assert.deepEqual(mergeQuery(table["cost.summary"], { period: 202610, project: "RD14" }), { period: "202610", project: "RD14" });
  assert.deepEqual(mergeQuery(table["payroll"], undefined), {});
});

test("an unknown key is null and greyed out, not an error", () => {
  assert.equal(resolveTarget({ key: "no.such.target", params: {} }, { table, from, access: open }), null);
  assert.deepEqual(targetState({ key: "no.such.target" }, { table }), { state: "unknown", to: null });
  assert.doesNotThrow(() => targetState({ key: "x" }, { table: {} }));
  assert.match(targetHint("unknown"), /暂时不可用/);
});

test("no target at all means the card is only a number, not a greyed link", () => {
  for (const empty of [null, undefined, {}, { params: {} }]) assert.deepEqual(targetState(empty, { table }), { state: "none", to: null });
  assert.equal(targetHint("none"), "");
  assert.equal(targetHint("link"), "");
});

test("an existing from in the target wins and the target object is not mutated", () => {
  const custom = buildTargetTable({ a: { label: "x", path: "/p", query: { from: "/elsewhere" }, params: [] } });
  assert.equal(resolveTarget({ key: "a" }, { table: custom, from }).query.from, "/elsewhere");
  const target = { key: "payment.detail", params: { request: "OA-1" } };
  const before = JSON.stringify(target);
  resolveTarget(target, { table, from, access: open });
  assert.equal(JSON.stringify(target), before);
  assert.equal(resolveTarget({ key: "payroll" }, { table }).query.from, undefined);
});

test("from points back at the current tab of the dashboard", () => {
  assert.equal(dashboardFrom("cost"), "/dashboard?tab=cost");
  assert.equal(dashboardFrom(""), "/dashboard");
  assert.equal(dashboardFrom(undefined), "/dashboard");
});

// ---------------------------------------------------------------- 权限置灰
test("a page the account cannot open is greyed out, with the reason", () => {
  const nobody = { ...open, canSee: () => false };
  const state = targetState({ key: "allocation", params: { period: "2026-10" } }, { table, from, access: nobody });
  assert.deepEqual(state, { state: "denied", to: null });
  assert.match(targetHint(state.state), /没有权限/);
  assert.equal(resolveTarget({ key: "allocation" }, { table, from, access: nobody }), null);
  assert.equal(targetState({ key: "allocation" }, { table, from, access: open }).state, "link");
});

test("canSee is asked about the path of the target, not its key", () => {
  const asked = [];
  const access = { canSee: (path) => { asked.push(path); return true; } };
  targetState({ key: "dorm.lease" }, { table, from, access });
  targetState({ key: "payment.detail", params: { request: "OA-1" } }, { table, from, access });
  assert.deepEqual(asked, ["/accommodation/master", "/approval/payment"]);
});

test("a list of everyone's documents is greyed out for people who may only see their own", () => {
  const own = { canSee: () => true, claimAll: false, travelAll: false };
  assert.equal(targetState({ key: "payment.unpaid" }, { table, from, access: own }).state, "denied");
  assert.equal(targetState({ key: "payment.waiting" }, { table, from, access: own }).state, "denied");
  assert.equal(targetState({ key: "claim.stuck" }, { table, from, access: own }).state, "denied");
  assert.equal(targetState({ key: "travel.list", params: { scope: "all" } }, { table, from, access: own }).state, "denied");
  // 待我处理 / 我的 不需要"全部"权限
  assert.equal(targetState({ key: "claim.todo" }, { table, from, access: own }).state, "link");
  assert.equal(targetState({ key: "claim.mine" }, { table, from, access: own }).state, "link");
  assert.equal(targetState({ key: "travel.list", params: { scope: "mine" } }, { table, from, access: own }).state, "link");
  assert.equal(targetState({ key: "payment.unpaid" }, { table, from, access: { ...own, claimAll: true } }).state, "link");
});

test("with the real canSee, finance sees the allocation pages and a plain employee does not", () => {
  const saved = globalThis.window;
  try {
    globalThis.window = { roles: ["Employee"] };
    assert.equal(targetState({ key: "cost.summary" }, { table, from, access: { canSee } }).state, "denied");
    assert.equal(targetState({ key: "personnel.list" }, { table, from, access: { canSee } }).state, "denied");
    globalThis.window = { roles: ["Employee", "Accounts User"] };
    assert.equal(targetState({ key: "cost.summary" }, { table, from, access: { canSee } }).state, "link");
    assert.equal(targetState({ key: "personnel.list" }, { table, from, access: { canSee } }).state, "denied");
    globalThis.window = { roles: ["Employee", "HR User"] };
    assert.equal(targetState({ key: "personnel.expiring" }, { table, from, access: { canSee } }).state, "link");
    // 物料进度看板按岗位，不按角色
    globalThis.window = { roles: ["Employee"], position_access: { pmc: true } };
    assert.equal(targetState({ key: "material.overdue" }, { table, from, access: { canSee } }).state, "link");
    globalThis.window = { roles: ["Employee"] };
    assert.equal(targetState({ key: "material.overdue" }, { table, from, access: { canSee } }).state, "denied");
  } finally {
    globalThis.window = saved;
  }
});

test("dashboard sources never hard-code a page path outside the target table", () => {
  const files = ["../src/pages/Dashboard.vue", "../src/components/dashboard/DashKpi.vue", "../src/components/dashboard/DashTodos.vue",
    "../src/components/dashboard/DashAlerts.vue", "../src/components/dashboard/DashBlock.vue", "../src/lib/dashboardView.js"];
  for (const file of files) {
    const text = readFileSync(new URL(file, import.meta.url), "utf8");
    assert.doesNotMatch(text, /['"`]\/(approval|personnel|payroll|allocation|accommodation|entry|social-insurance|housing-fund)\b/, file);
  }
});
