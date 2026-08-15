import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildApprovalCenterPayload,
  canCloseProcurement,
  canRecordArrival,
  normalizeServerError,
} from "../src/lib/procurementWorkflow.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("server errors are converted to plain text without rendering raw HTML", () => {
  assert.equal(normalizeServerError({ messages: ["用户<strong>admin</strong>无权访问"] }), "用户admin无权访问");
  assert.equal(normalizeServerError({ message: "<script>alert(1)</script>保存失败" }), "alert(1)保存失败");
});

test("payload separates procurement, direct purchase, and payment-only fields", () => {
  const form = {
    subject: "申请", reason: "原因", urgency: "一般", asset_nature: "非固定资产",
    fixed_asset_category: "", procurement_scope: "项目采购", expected_delivery_date: "2026-09-01",
    project: "PRJ-1", non_project_allocation_type: "部门", non_project_department: "研发部",
    purchase_method: "京东购买", source_request: "PROC-1", supplier: "SUP-1", payment_stage: "预付款",
    prepayment_percentage: 100, has_balance_payment: false, expected_arrival_date: "2026-09-10",
    prepayment_risk_note: "风险已评估", business_lines: [],
  };
  const procurement = buildApprovalCenterPayload(form, "采购申请");
  const direct = buildApprovalCenterPayload(form, "购买申请");
  const payment = buildApprovalCenterPayload(form, "采购付款");
  assert.equal(procurement.project, "PRJ-1");
  assert.equal(procurement.purchase_method, undefined);
  assert.equal(direct.purchase_method, "京东购买");
  assert.equal(direct.payment_stage, undefined);
  assert.equal(payment.source_request, "PROC-1");
  assert.equal(payment.purchase_method, undefined);
});

test("evidence gates visible lifecycle actions before the server revalidates", () => {
  assert.equal(canRecordArrival({ workflow_status: "已付款", business_status: "待到货" }, ["送货单"]), true);
  assert.equal(canRecordArrival({ workflow_status: "已付款", business_status: "待到货" }, []), false);
  assert.equal(canCloseProcurement({ inspection_status: "验收通过", prepayment_writeoff_status: "已核销", has_balance_payment: 0 }, ["发票", "验收资料", "采购完成报告"]), true);
});

test("forms use real project options and conditional business fields", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  assert.match(source, /oa_entry\.list_approval_center_projects/);
  assert.match(source, /<select v-model='form\.project'/);
  assert.match(source, /form\.procurement_scope === "项目采购"/);
  assert.match(source, /non_project_allocation_type/);
  assert.match(source, /purchase_method/);
  assert.match(source, /payment_stage/);
  assert.match(source, /prepayment_risk_note/);
  assert.match(source, /record_arrival/);
  assert.match(source, /record_inspection/);
  assert.match(source, /writeoff_prepayment/);
  assert.match(source, /close_procurement/);
});
