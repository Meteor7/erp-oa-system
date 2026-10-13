import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { eventLabel, isRejectionEvent } from "../src/lib/operationLog.js";
import { draftKind, lastRejection } from "../src/lib/procurementView.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("operation log entries read in Chinese, old English names included", () => {
  assert.equal(eventLabel("Targeted rejection"), "驳回");
  assert.equal(eventLabel("Add-sign"), "加签");
  assert.equal(eventLabel("Finance expense classification"), "财务分类");
  assert.equal(eventLabel("同意"), "同意");
  assert.equal(eventLabel("已办理"), "已办理");
  assert.equal(eventLabel(undefined), "");
  assert.ok(isRejectionEvent("Targeted rejection"));
  assert.ok(isRejectionEvent("退回补录发票"));
  assert.ok(!isRejectionEvent("同意"));
});

test("a purchase request sent back to the applicant counts as rejected even when the log says Targeted rejection", () => {
  const row = { workflow_status: "草稿", operation_log: [{ action: "提交申请" }, { action: "Targeted rejection", note: "预算不够" }] };
  assert.equal(draftKind(row), "rejected");
  assert.equal(lastRejection(row), "预算不够");
});

test("every page that lists the operation log shows the Chinese name", () => {
  for (const path of [
    "../src/components/attendance/AttendanceDetail.vue",
    "../src/components/ExpenseWorkbench.vue",
    "../src/components/payment/PayApprovalPage.vue",
    "../src/components/procurement/ProcDetail.vue",
  ]) {
    const source = read(path);
    assert.match(source, /eventLabel\(event\.action\)/, path);
    assert.doesNotMatch(source, /\{\{ event\.action \}\}/, path);
  }
});
