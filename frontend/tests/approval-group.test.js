import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, readFileSync } from "node:fs";
import { GROUP_HOME_CHILDREN, GROUP_HOME_PATHS, BOARD_REDIRECTS } from "../src/lib/approvalGroupPaths.js";
import { GROUPS, buildGroupHome, listLinkFor, mineRow, stepTracker, todoRow, typeTone, waitedText, workRow } from "../src/lib/approvalGroup.js";
import { canSee } from "../src/lib/access.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const NOW = Date.parse("2026-10-09T10:00:00");

const row = (overrides = {}) => ({
  name: "OA-1", request_type: "购买申请", subject: "测试工装", employee_name: "演示员工117", department: "研发软件部",
  workflow_status: "待审批", current_step_label: "直属部门主管：演示员工132", amount: 1720, current_step_index: 1,
  steps: [{ label: "直属部门主管：演示员工132", status: "待审批", step_index: 1 }, { label: "演示员工113经理：演示员工21", status: "待流转", step_index: 2 }],
  creation: "2026-10-07 09:00:00", modified: "2026-10-07 10:00:00", ...overrides,
});

test("the two groups have their own home path and every child page stays reachable", () => {
  assert.deepEqual(GROUP_HOME_PATHS, { request: "/approval/requests", payment: "/approval/payments" });
  assert.deepEqual(GROUP_HOME_CHILDREN["/approval/requests"], ["/approval/procurement", "/approval/procurement/price-approvals", "/approval/direct-purchase"]);
  assert.deepEqual(GROUP_HOME_CHILDREN["/approval/payments"], ["/approval/procurement-payment", "/approval/reimbursement", "/approval/invoice-folder", "/approval/claim", "/approval/payment"]);
  assert.deepEqual(BOARD_REDIRECTS, { "/approval/expense-request-board": "/approval/requests", "/approval/expense-payment-board": "/approval/payments" });
  // 出差申请在考勤中心里，不在这一组
  assert.deepEqual(GROUPS.request.types, ["采购申请", "购买申请"]);
  assert.deepEqual(GROUPS.payment.types, ["采购付款", "报销单", "付款单"]);
});

test("a group home opens for anyone who can open one of its pages", () => {
  globalThis.window = { roles: ["Employee"], oa_access: { procurement_application: true, expense_reimbursement: false } };
  assert.equal(canSee("/approval/requests"), true);
  assert.equal(canSee("/approval/payments"), false, "no payment page is open to this account");
  globalThis.window = { roles: ["Employee"], oa_access: { reimbursement_request: true, payment_request: true } };
  assert.equal(canSee("/approval/payments"), true);
  globalThis.window = { roles: ["Employee"], oa_access: {} };
  assert.equal(canSee("/approval/requests"), false, "none of the application pages is switched on");
  assert.equal(canSee("/approval/payments"), true, "the old payment / reimbursement page is on unless switched off");
});

test("to-do rows open the request itself, longest wait first, and carry where they came from", () => {
  const home = buildGroupHome("request", {
    pending: { 购买申请: [row()], 采购申请: [row({ name: "OA-2", request_type: "采购申请", subject: "杭州联调", modified: "2026-10-09 09:00:00", amount: 0 })] },
    here: "/approval/requests", now: NOW,
  });
  assert.deepEqual(home.todoAll.map((item) => item.key), ["oa:OA-1", "oa:OA-2"]);
  const first = home.todoAll[0];
  assert.equal(first.days, 2);
  assert.equal(first.waited, "等你 2 天");
  assert.equal(first.warn, false);
  assert.deepEqual(first.to, { path: "/approval/direct-purchase", query: { request: "OA-1", from: "/approval/requests" } });
  assert.equal(first.amount, "¥ 1,720.00");
  assert.equal(home.todoAll[1].waited, "今天刚到");
  assert.equal(home.todoAll[1].amount, "");
  assert.equal(first.node, "现在在：直属部门主管：演示员工132");
  assert.equal(waitedText(null), "");
});

test("filter chips count each type and the list can be cut to one type", () => {
  const pending = { 购买申请: [row(), row({ name: "OA-3" })], 采购申请: [row({ name: "OA-2", request_type: "采购申请" })] };
  const all = buildGroupHome("request", { pending, now: NOW });
  assert.deepEqual(all.chips.map((chip) => chip.label), ["全部 3", "采购申请 1", "购买申请 2"]);
  const cut = buildGroupHome("request", { pending, now: NOW, filter: "采购申请" });
  assert.equal(cut.todo.length, 1);
  assert.equal(cut.chips[1].on, true);
  assert.deepEqual(listLinkFor("采购申请"), { path: "/approval/procurement", query: { view: "list", scope: "todo" } });
  assert.equal(listLinkFor("出差申请"), null, "trips are approved in the attendance centre now");
  assert.equal(listLinkFor("价格审批"), null, "chain items have no list of their own");
});

test("only the first six to-dos are listed and the rest is said out loud", () => {
  const many = Array.from({ length: 8 }, (_, index) => row({ name: `OA-${index}` }));
  const home = buildGroupHome("request", { pending: { 购买申请: many }, now: NOW });
  assert.equal(home.todo.length, 6);
  assert.equal(home.todoMore, 2);
});

test("procurement chain work shows up in the request group and payment work in the payment group", () => {
  const work = {
    pr: [{ key: "pr:1", tag: "请购单", subject: "线缆", meta: "演示员工178", action: "建价格审批", to: { name: "procurement-price-approvals" }, wait: 4 }],
    price: [], approvals: [], po: [{ key: "po:1", tag: "PO", subject: "PO-1 待确认", meta: "等你确认", action: "确认", to: "/approval/procurement/price-approvals?tab=po", wait: 0 }],
    payment: [{ key: "pay:1", tag: "采购付款", subject: "第1期", meta: "可提交", action: "提交付款", to: "/approval/procurement-payment", wait: 0 }],
  };
  const req = buildGroupHome("request", { work, now: NOW });
  assert.deepEqual(req.todoAll.map((item) => item.type), ["请购单", "PO"]);
  assert.equal(req.todoAll[0].tone, "g-orange");
  assert.equal(req.todoAll[0].action, "建价格审批 →");
  const pay = buildGroupHome("payment", { work, now: NOW });
  assert.deepEqual(pay.todoAll.map((item) => item.type), ["采购付款"]);
  assert.deepEqual(workRow({ key: "x", tag: "PO", subject: "s", request: "OA-9", action: "审批", wait: 3 }, { here: "/approval/requests" }).to, { path: "/approval/procurement", query: { request: "OA-9", from: "/approval/requests" } });
});

test("my in-progress requests show where they are stuck; finished and draft ones do not", () => {
  const mine = {
    购买申请: [row({ name: "OA-A", workflow_status: "待审批", employee_name: "演示员工150" }), row({ name: "OA-B", workflow_status: "已完成" }), row({ name: "OA-C", workflow_status: "草稿" })],
  };
  const home = buildGroupHome("request", { mine, now: NOW });
  assert.deepEqual(home.mineActive.map((item) => item.row.name), ["OA-A"]);
  assert.equal(home.hasTodo, false, "someone with nothing to approve gets the mine card as the main column");
  const tracker = stepTracker(row());
  assert.deepEqual(tracker.map((step) => [step.cls, step.mark]), [["cur", "●"], ["todo", ""]]);
  assert.match(tracker[0].text, /（现在）/);
  assert.equal(stepTracker(row({ steps: [{ label: "演示员工132", status: "已通过", step_index: 1 }, { label: "演示员工21", status: "待审批", step_index: 2 }], current_step_index: 2 }))[0].cls, "done");
  assert.equal(mineRow(row(), { now: NOW }).meta.includes("已等 2 天"), true);
});

test("indicator cards follow the group", () => {
  const pending = { 购买申请: [row({ modified: "2026-10-01 10:00:00" })] };
  const request = buildGroupHome("request", { pending, mine: { 购买申请: [row({ name: "OA-M", creation: "2026-10-03 09:00:00" })] }, now: NOW });
  assert.deepEqual(request.kpis.map((kpi) => [kpi.key, kpi.value]), [["todo", 1], ["mine", 1], ["stale", 1], ["month", 1]]);
  const payment = buildGroupHome("payment", {
    mine: { 付款单: [row({ name: "PAY-1", request_type: "付款单", workflow_status: "已付款", business_status: "已付款·待补票" }), row({ name: "PAY-2", request_type: "付款单" })] }, now: NOW,
  });
  assert.deepEqual(payment.kpis.map((kpi) => kpi.key), ["todo", "mine", "invoice", "month"]);
  assert.equal(payment.kpis[2].value, 1);
});

test("type tags have colours and the new-request buttons point at the original pages", () => {
  assert.equal(typeTone("采购申请"), "g-blue");
  assert.equal(typeTone("出差申请"), "", "trips are not in this group any more");
  assert.equal(typeTone("没见过的类型"), "");
  assert.deepEqual(GROUPS.request.actions.map((item) => item.to.path), ["/approval/procurement/new", "/approval/direct-purchase/new"]);
  assert.deepEqual(GROUPS.payment.actions.map((item) => item.to.path), ["/approval/payment", "/approval/claim", "/approval/invoice-folder"]);
  assert.equal(todoRow(row({ request_type: "付款单" }), { now: NOW }).to.path, "/approval/payment");
});

test("the group home page, routes and sidebar are wired (2026-10-10)", () => {
  const page = read("../src/pages/ApprovalGroupHome.vue");
  assert.match(page, /oa_entry\.list_requests/);
  assert.match(page, /view, request_type: type, limit: 100/);
  assert.match(page, /loadProcurementWork\(work\)/);
  assert.match(page, /<RequestBoard v-if="group === 'request'" embedded \/>/);
  assert.match(page, /<PaymentBoard v-else embedded \/>/);
  assert.match(page, /inMenu\(config\.value\.board\.path\)/);          // 看板只放给能看看板的人
  assert.match(page, /canSee\(boardRoute\(type\)\)/);                  // 没权限的类型不取
  assert.match(page, /expense_claim_entry\.list_available_invoices/);
  assert.match(page, /\.catch\(\(\) => \[\]\)/);                       // 取不到就当没有，不影响其他部分
  for (const board of ["RequestBoard", "PaymentBoard"]) {
    const source = read(`../src/pages/${board}.vue`);
    assert.match(source, /defineProps\(\{ embedded: \{ type: Boolean, default: false \} \}\)/);
    assert.match(source, /<div v-if="!embedded">\s*<div class="crumb">/);
  }
  const router = read("../src/router.js");
  assert.match(router, /path: '\/approval\/requests', component: \(\) => import\('\.\/pages\/ApprovalGroupHome\.vue'\), props: \{ group: 'request' \}/);
  assert.match(router, /path: '\/approval\/payments', component: \(\) => import\('\.\/pages\/ApprovalGroupHome\.vue'\), props: \{ group: 'payment' \}/);
  assert.match(router, /Object\.entries\(BOARD_REDIRECTS\)/);
  assert.match(router, /query: route\.query, hash: route\.hash/);      // 旧看板地址带着页签和锚点跳过来
  const app = read("../src/App.vue");
  // 侧栏菜单不再有看板条目（App.vue 里另有一份「已知页面」路径表，会提到旧地址，所以只看菜单项的 to）
  assert.doesNotMatch(app, /to: '\/approval\/(expense-request-board|expense-payment-board|request-dashboard|payment-dashboard)'/);
  assert.match(app, /:class='isNavActive\(n\.to\)/);
  assert.equal(existsSync(new URL("../src/components/procurement/work.js", import.meta.url)), true);
});
