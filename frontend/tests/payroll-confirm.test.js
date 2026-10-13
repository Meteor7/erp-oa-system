// 确认本月工资（决定 2026-10-13）：草稿核对完一次确认、确认后锁定，要改先撤回确认；总经理、副总经理只读。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { canWithdraw, confirmTargets, rowLocked } from "../src/lib/payrollView.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const row = (overrides = {}) => ({ employee: "E1", social_record_exists: true, housing_record_exists: true, salary_slip: null, docstatus: null, managed: false, ...overrides });

test("only this page's drafts are confirmed, and only confirmed ones can be withdrawn", () => {
  const rows = [
    row({ employee: "NEW" }),
    row({ employee: "DRAFT", salary_slip: "S1", docstatus: 0, managed: true }),
    row({ employee: "EXTERNAL", salary_slip: "S2", docstatus: 0, managed: false }),
    row({ employee: "DONE", salary_slip: "S3", docstatus: 1, managed: true }),
  ];
  assert.deepEqual(confirmTargets(rows).map((item) => item.employee), ["DRAFT"]);
  assert.deepEqual(rows.filter(canWithdraw).map((item) => item.employee), ["DONE"]);
  assert.equal(rowLocked(rows[3]), true);
});

test("the payroll page confirms in one go, warns before locking and lets leaders only read", () => {
  const page = read("../src/pages/Payroll.vue");
  assert.match(page, /url: api \+ "confirm_payroll"/);
  assert.match(page, /url: api \+ "withdraw_payroll_confirmation"/);
  assert.match(page, />确认本月工资（\{\{ lockTargets\.length \}\}）</);
  assert.match(page, /确认后锁定，不能再改，要改先撤回确认；看板和研发人工成本只算已确认的。/);
  assert.match(page, /<template v-if="canEdit">/);
  assert.match(page, /:read-only="!canEdit"/);
  const drawer = read("../src/components/payroll/PayrollDrawer.vue");
  assert.match(drawer, /const locked = computed\(\(\) => props\.readOnly \|\| rowLocked\(props\.row\)\);/);
  assert.match(drawer, /emit\('withdraw', row, reason\.trim\(\)\)/);
  assert.match(drawer, /撤回原因（必填）/);
});
