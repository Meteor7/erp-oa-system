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
  assert.match(source, /请假日期/);
  assert.match(source, /查看详情/);
  assert.match(source, /<Card v-if='!isLeaveInnerPage' :title='T\.pendingTitle' class='oa-panel oa-table-panel oa-pending-panel'>/);
});

test("leave approvals open each request in a dedicated inner page", () => {
  const source = read("../src/pages/OAApprovals.vue");
  assert.match(source, /isLeaveInnerPage/);
  assert.match(source, /name: 'leave-detail'/);
  assert.match(source, /返回请假审批/);
  assert.match(source, /新建请假/);
  assert.match(source, /router.push\(\{ name: 'leave-detail'/);
  assert.match(source, /请假申请/);
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
