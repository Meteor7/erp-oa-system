import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { APPROVAL_CENTER_ROUTES, isApprovalRouteEnabled } from "../src/lib/approvalCenter.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("approval center defines the four business flows and two dashboards", () => {
  assert.deepEqual(Object.keys(APPROVAL_CENTER_ROUTES), [
    "/approval/leave",
    "/approval/procurement",
    "/approval/direct-purchase",
    "/approval/request-dashboard",
    "/approval/procurement-payment",
    "/approval/reimbursement",
    "/approval/corporate-payment",
    "/approval/payment-dashboard",
  ]);
});

test("closed procurement routes require explicit server boot flags", () => {
  assert.equal(isApprovalRouteEnabled("/approval/leave", { leave_approval: true }), true);
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
});

test("procurement pages save and submit through the real workflow engine", () => {
  const pre = read("../src/pages/PreRequestCenter.vue");
  assert.doesNotMatch(pre, /审批流程尚未配置/);
  assert.match(pre, /save_approval_center_draft/);
  assert.match(pre, /submit_approval_center_draft/);
  assert.match(pre, />提交审批</);
  assert.match(pre, /current_step_label/);
  assert.match(pre, /row in selectedRequest.steps/);
  assert.match(pre, /reject_target/);
  assert.match(pre, /驳回原因/);
});

test("dashboard renders all five money meanings and historical unclassified", () => {
  const source = read("../src/pages/ApprovalDashboard.vue");
  for (const label of ["申请金额", "批准金额", "占用金额", "已付金额", "可用余额", "历史未分类"]) {
    assert.ok(source.includes(label), label);
  }
  assert.match(source, /get_approval_center_dashboard/);
});

test("existing payment and reimbursement aliases remain on OA approvals", () => {
  const source = read("../src/pages/OAApprovals.vue");
  assert.ok(source.includes("/approval/reimbursement"));
  assert.ok(source.includes("/approval/corporate-payment"));
  assert.match(source, /reject_target/);
  assert.match(source, /rejection_targets/);
  assert.match(source, /驳回原因必填/);
});