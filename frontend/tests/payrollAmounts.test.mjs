import test from "node:test";
import assert from "node:assert/strict";
import { payrollNet, payrollPayable } from "../src/lib/payrollAmounts.js";

test("submitted salary uses saved amounts even when inputs differ", () => {
  const row = { docstatus: 1, net_pay: 9000, payable_salary: 10000, base_salary: 50000, social_insurance: 2000 };
  assert.equal(payrollNet(row), 9000);
  assert.equal(payrollPayable(row), 10000);
});
test("editable draft still previews input changes", () => {
  const row = { docstatus: 0, base_salary: 10000, payment_days: 30, total_working_days: 30, social_insurance: 1000 };
  assert.equal(payrollNet(row), 9000);
  assert.equal(payrollNet({ ...row, social_insurance: 2000 }), 8000);
});
