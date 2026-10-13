import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { BOARD_REDIRECTS } from "../src/lib/approvalGroupPaths.js";
import { APPROVAL_CENTER_ROUTES, isApprovalMenuVisible, isApprovalRouteEnabled } from "../src/lib/approvalCenter.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("approval center defines every business flow and the two dashboards", () => {
  assert.deepEqual(Object.keys(APPROVAL_CENTER_ROUTES), [
    "/approval/attendance",
    "/approval/leave",
    "/approval/overtime",
    "/approval/comp-time",
    "/approval/procurement",
    "/approval/direct-purchase",
    "/approval/travel",
    "/approval/request-dashboard",
    "/approval/procurement-payment",
    "/approval/reimbursement",
    "/approval/invoice-folder",
    "/approval/claim",
    "/approval/payment",
    "/approval/corporate-payment",
    "/approval/payment-dashboard",
    "/approval/expense-request-board",
    "/approval/expense-payment-board",
  ]);
});

test("the legacy 付款/报销 page and the old boards leave the menu only once both new types are on", () => {
  const legacy = { expense_reimbursement: true, procurement_application: true, procurement_payment: true };
  const menu = (path, access) => isApprovalMenuVisible(path, access);
  assert.equal(menu("/approval/reimbursement", legacy), true);
  assert.equal(menu("/approval/purchase", legacy), true);
  assert.equal(menu("/approval/request-dashboard", legacy), true);
  assert.equal(menu("/approval/payment-dashboard", legacy), true);
  assert.equal(menu("/approval/expense-request-board", legacy), false);
  // only 报销单 on: the legacy page stays so payments to suppliers still have a place
  const half = { ...legacy, reimbursement_request: true };
  assert.equal(menu("/approval/reimbursement", half), true);
  assert.equal(menu("/approval/claim", half), true);
  assert.equal(menu("/approval/payment", half), false);
  // only 出差申请 on: one 申请看板 in the menu, not two
  const travel = { ...legacy, travel_application: true };
  assert.equal(menu("/approval/request-dashboard", travel), true);
  assert.equal(menu("/approval/expense-request-board", travel), false);
  const migrated = { ...legacy, reimbursement_request: true, payment_request: true };
  for (const path of ["/approval/reimbursement", "/approval/corporate-payment", "/approval/purchase", "/approval/request-dashboard", "/approval/payment-dashboard"]) {
    assert.equal(menu(path, migrated), false, path);
  }
  assert.equal(menu("/approval/claim", migrated), true);
  assert.equal(menu("/approval/expense-request-board", migrated), true);
  // the legacy pages still open from a to-do or notification link: in-flight legacy documents must finish
  assert.equal(isApprovalRouteEnabled("/approval/reimbursement", migrated), true);
  assert.equal(isApprovalRouteEnabled("/approval/request-dashboard", migrated), true);
  // turning the new types off again brings the legacy pages back into the menu
  assert.equal(menu("/approval/reimbursement", legacy), true);
});

test("closed procurement routes require explicit server boot flags", () => {
  assert.equal(isApprovalRouteEnabled("/approval/leave", { leave_approval: true }), true);
  assert.equal(isApprovalRouteEnabled("/approval/reimbursement", {}), true);
  assert.equal(isApprovalRouteEnabled("/approval/procurement", {}), false);
  assert.equal(isApprovalRouteEnabled("/approval/procurement", { procurement_application: true }), true);
  assert.equal(isApprovalRouteEnabled("/approval/payment-dashboard", { procurement_payment: false }), false);
});

test("router registers each page without replacing the existing leave implementation", () => {
  const source = read("../src/router.js");
  for (const path of Object.keys(APPROVAL_CENTER_ROUTES)) {
    // 两个旧看板地址现在由分组首页的重定向接住，router.js 里不再逐条写 path。
    assert.ok(source.includes(`path: '${path}'`) || path in BOARD_REDIRECTS, path);
  }
  assert.match(source, /OAApprovals\.vue/);
  assert.match(source, /PreRequestCenter\.vue/);
  assert.match(source, /PaymentCenter\.vue/);
  // (the page is now a thin wrapper around components/payment/PaymentWorkbench.vue)
  assert.match(source, /ApprovalDashboard\.vue/);
  // 出差申请并进了考勤中心：地址 /approval/travel 还在，指向考勤中心页面
  assert.match(source, /path: '\/approval\/travel', component: attendancePage/);
  assert.match(source, /InvoiceFolder\.vue/);
  assert.match(source, /ClaimCenter\.vue/);
  assert.match(source, /PaymentRequestCenter\.vue/);
  // 申请看板 / 付款看板现在嵌在分组首页里，router 只认识分组首页
  assert.match(source, /ApprovalGroupHome\.vue/);
});

test("procurement pages save and submit through the real workflow engine", () => {
  // 采购申请 / 购买申请页面在 components/procurement 下（2026-09-30 改版）；旧页面只是一层壳。
  const form = read("../src/components/procurement/ProcForm.vue");
  const detail = read("../src/components/procurement/ProcDetail.vue");
  const view = read("../src/lib/procurementView.js");
  const pre = [form, detail, view, read("../src/components/procurement/ProcurementWorkbench.vue")].join("\n");
  assert.doesNotMatch(pre, /审批流程尚未配置/);
  assert.match(form, /save_approval_center_draft/);
  assert.match(form, /submit_approval_center_draft/);
  assert.match(form, />\{\{ saving \? '处理中…' : '提交审批' \}\}</);
  assert.match(pre, /current_step_label/);
  assert.match(view, /stepTimeline/);
  assert.match(detail, /stepTimeline\(row\.value/);
  assert.match(view, /办理完成/);
  assert.match(view, /审批通过/);
  assert.doesNotMatch(pre, /通过\/办理/);
  assert.match(detail, /reject_target/);
  assert.match(detail, /驳回原因/);
});

test("dashboard renders money, fixed-asset and prepayment risk drilldowns", () => {
  const source = read("../src/pages/ApprovalDashboard.vue");
  for (const label of [
    "申请金额", "批准金额", "占用金额", "已付金额", "可用余额", "历史未分类",
    "固定资产", "非固定资产", "100%预付款逾期", "待到货", "待验收",
    "验收不合格", "待预付款核销", "显示全部",
  ]) {
    assert.ok(source.includes(label), label);
  }
  assert.match(source, /get_approval_center_dashboard/);
  assert.match(source, /asset_summary/);
  assert.match(source, /prepayment_risk_summary/);
  assert.match(source, /selectedNames/);
  assert.match(source, /filteredRows/);
});

test("dashboard shows an explicit loading state instead of false zero totals", () => {
  const source = read("../src/pages/ApprovalDashboard.vue");
  assert.match(source, /resource\.loading/);
  assert.match(source, /正在加载看板数据/);
  assert.match(source, /v-else/);
});


test("the reimbursement pages render the expense workbench; leave has its own page", () => {
  const source = read("../src/pages/OAApprovals.vue");
  assert.match(source, /<ExpenseWorkbench\s*\/>/);
  assert.doesNotMatch(source, /leaveForm|preview_route|create_request|update_leave_draft/);
  const router = read("../src/router.js");
  for (const path of ["/approval/reimbursement", "/approval/purchase"]) {
    assert.match(router, new RegExp(`path: '${path}', component: approvalPage`));
  }
  for (const path of ["/approval/leave", "/approval/overtime", "/approval/comp-time"]) {
    assert.match(router, new RegExp(`path: '${path}', component: attendancePage`));
  }
});

test("overtime and compensatory leave follow the leave access flag", () => {
  for (const route of ["/approval/overtime", "/approval/comp-time"]) {
    assert.equal(isApprovalRouteEnabled(route, { leave_approval: false }), false);
    assert.equal(isApprovalRouteEnabled(route, { leave_approval: true }), true);
  }
});

test("the removed consumption push leaves no references behind in OA approvals", () => {
  // 请假 / 加班 / 调休也用这个页面：残留的变量会让监听器报错、路线预览不刷新。
  const source = read("../src/pages/OAApprovals.vue");
  for (const name of ["pushPayment", "pushSelection", "consumptionRows", "consumptionForm", "selectedConsumption",
    "push_consumption_to_request", "list_consumption_details", "save_consumption_detail"]) {
    assert.ok(!source.includes(name), name);
  }
});

test("procurement pages follow the server's rights (review fixes 2026-09-24)", () => {
  const payment = read("../src/components/payment/PaymentWorkbench.vue");
  assert.match(payment, /const canWork = canSeeProcurementPO\(\)/);
  assert.match(payment, /v-if="canWork"/);
  const board = read("../src/pages/MaterialProgress.vue");
  assert.match(board, /v-if="canCreatePr"/);
  const price = read("../src/components/price/SupplierDrawer.vue");
  assert.doesNotMatch(price, /<option>USD<\/option>/);
});
