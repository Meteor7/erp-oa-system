import assert from "node:assert/strict";
import test from "node:test";
import { documentChecklistForRequest } from "../src/lib/businessDocumentChecklist.js";

test("procurement checklist follows the active lifecycle node", () => {
  const rows = documentChecklistForRequest({ request_type: "采购申请", business_status: "待到货" }, [
    { document_type: "合同", version_no: 1, status: "有效" },
  ]);
  const arrival = rows.find((item) => item.key === "arrival");
  assert.ok(arrival);
  assert.equal(arrival.satisfied, false);
  assert.deepEqual(arrival.uploadTypes, ["送货单", "收料单", "入库单"]);
});

test("payment checklist only requires an invoice when the payment plan says so", () => {
  const withInvoiceGate = documentChecklistForRequest({
    request_type: "采购付款",
    invoice_requirement: "付款前提供",
  });
  assert.equal(withInvoiceGate.find((item) => item.key === "invoice").satisfied, false);
  const noInvoice = documentChecklistForRequest({
    request_type: "采购付款",
    invoice_requirement: "无需发票",
  });
  assert.equal(noInvoice.some((item) => item.key === "invoice"), false);
});

test("demand stage has no synthetic upload requirement", () => {
  const rows = documentChecklistForRequest({ request_type: "采购申请", business_status: "待审批" });
  assert.equal(rows.some((item) => item.label === "需求申请"), false);
  assert.equal(rows.length, 0);
});
