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

test("draft pages expose save only and explain that workflows are closed", () => {
  const pre = read("../src/pages/PreRequestCenter.vue");
  assert.match(pre, /审批流程尚未配置，当前仅可保存本地草稿。/);
  assert.match(pre, /save_approval_center_draft/);
  assert.match(pre, /attach_approval_business_document/);
  assert.doesNotMatch(pre, />提交审批</);
  assert.doesNotMatch(pre, /approved_amount\s*:/);
  assert.doesNotMatch(pre, /workflow_status\s*:/);
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
});