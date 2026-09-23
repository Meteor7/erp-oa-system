import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { APPROVAL_CENTER_ROUTES, isApprovalRouteEnabled } from "../src/lib/approvalCenter.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("approval center defines every business flow and the two dashboards", () => {
  assert.deepEqual(Object.keys(APPROVAL_CENTER_ROUTES), [
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

test("the legacy 付款/报销 page and the old boards retire once the new flow is on", () => {
  const legacy = { expense_reimbursement: true, procurement_application: true, procurement_payment: true };
  assert.equal(isApprovalRouteEnabled("/approval/reimbursement", legacy), true);
  assert.equal(isApprovalRouteEnabled("/approval/purchase", legacy), true);
  assert.equal(isApprovalRouteEnabled("/approval/request-dashboard", legacy), true);
  assert.equal(isApprovalRouteEnabled("/approval/payment-dashboard", legacy), true);
  const migrated = { ...legacy, reimbursement_request: true };
  assert.equal(isApprovalRouteEnabled("/approval/reimbursement", migrated), false);
  assert.equal(isApprovalRouteEnabled("/approval/corporate-payment", migrated), false);
  assert.equal(isApprovalRouteEnabled("/approval/purchase", migrated), false);
  assert.equal(isApprovalRouteEnabled("/approval/request-dashboard", migrated), false);
  assert.equal(isApprovalRouteEnabled("/approval/payment-dashboard", migrated), false);
  assert.equal(isApprovalRouteEnabled("/approval/claim", migrated), true);
  assert.equal(isApprovalRouteEnabled("/approval/expense-request-board", migrated), true);
  // turning the new types off again brings the legacy pages back
  assert.equal(isApprovalRouteEnabled("/approval/reimbursement", legacy), true);
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
    assert.ok(source.includes(`path: '${path}'`), path);
  }
  assert.match(source, /OAApprovals\.vue/);
  assert.match(source, /PreRequestCenter\.vue/);
  assert.match(source, /PaymentCenter\.vue/);
  assert.match(source, /ApprovalDashboard\.vue/);
  assert.match(source, /TravelRequest\.vue/);
  assert.match(source, /InvoiceFolder\.vue/);
  assert.match(source, /ClaimCenter\.vue/);
  assert.match(source, /PaymentRequestCenter\.vue/);
  assert.match(source, /ExpenseBoards\.vue/);
});

test("procurement pages save and submit through the real workflow engine", () => {
  const pre = read("../src/pages/PreRequestCenter.vue");
  assert.doesNotMatch(pre, /审批流程尚未配置/);
  assert.match(pre, /save_approval_center_draft/);
  assert.match(pre, /submit_approval_center_draft/);
  assert.match(pre, />提交审批</);
  assert.match(pre, /current_step_label/);
  assert.match(pre, /row in selectedRequest.steps/);
  assert.match(pre, /currentStepMode/);
  assert.match(pre, /办理完成/);
  assert.match(pre, /审批通过/);
  assert.doesNotMatch(pre, /通过\/办理/);
  assert.match(pre, /reject_target/);
  assert.match(pre, /驳回原因/);
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


test("existing payment and reimbursement aliases remain on OA approvals", () => {
  const source = read("../src/pages/OAApprovals.vue");
  assert.ok(source.includes("/approval/reimbursement"));
  assert.ok(source.includes("/approval/corporate-payment"));
  assert.match(source, /reject_target/);
  assert.match(source, /rejection_targets/);
  assert.match(source, /驳回原因必填/);
});

test("leave approvals render one detailed pending table", () => {
  const source = read("../src/pages/OAApprovals.vue");
  assert.match(source, /申请日期/);
  assert.match(source, /查看详情/);
  assert.match(source, /<Card v-if='!isLeaveInnerPage' :title='T\.pendingTitle' class='oa-panel oa-table-panel oa-pending-panel'>/);
});

test("leave approvals open each request in a dedicated inner page", () => {
  const source = read("../src/pages/OAApprovals.vue");
  assert.match(source, /isLeaveInnerPage/);
  assert.match(source, /attendanceBase/);
  assert.match(source, /返回\{\{ pageConfig.title \}\}/);
  assert.match(source, /新建\{\{ currentRequestType \}\}/);
  assert.match(source, /encodeURIComponent\(row.name\)/);
  assert.match(source, /REQUEST_LEAVE/);
  assert.match(source, /v-if='isLeaveInnerPage && selectedLeave'/);
});

test("returned leave drafts can be edited and resubmitted", () => {
  const source = read("../src/pages/OAApprovals.vue");
  assert.match(source, /update_leave_draft/);
  assert.match(source, /hydrateLeaveDraft/);
  assert.match(source, /leaveDraftName/);
  assert.match(source, /mine\.data/);
  assert.match(source, /draftSubmitter\.submit/);
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
