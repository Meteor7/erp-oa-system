// 薪酬计算（决定 2026-10-14）：基本工资按工时折算、个税按累计预扣法现算，和后端 income_tax.py 同样的数。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { bonusTax, computeTax, cumulativeTax, withholding } from "../src/lib/payrollTax.js";
import { payrollNet, payrollProrated, payrollTax } from "../src/lib/payrollAmounts.js";
import { autoHours, dirtyRows, editSnapshot, figures, isProrated, readiness } from "../src/lib/payrollView.js";

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");

test("first month tax matches the hr sheet rows", () => {
  assert.equal(withholding({ income: 10000, special: 1720 }).tax, 98.4);
  assert.equal(withholding({ income: 10000, special: 894.54, special_additional: 3300 }).tax, 24.16);
});

test("later months subtract what was already withheld and never refund", () => {
  const second = withholding({ income: 10000, special: 1720 }, { months: 1, income: 10000, special: 1720, tax: 98.4 });
  assert.equal(second.months, 2);
  assert.equal(second.cum_taxable, 6560);
  assert.equal(second.tax, 98.4);
  assert.equal(withholding({ income: 3000 }, { months: 1, income: 20000, tax: 500 }).tax, 0);
  const crossing = withholding({ income: 9000 }, { months: 3, income: 51000, tax: 900 });
  assert.deepEqual([crossing.rate, crossing.quick, crossing.cum_tax, crossing.tax], [10, 2520, 1480, 580]);
});

test("brackets, the 60k rule and the separate annual bonus", () => {
  assert.deepEqual(cumulativeTax(36000), { rate: 3, quick: 0, tax: 1080 });
  assert.equal(cumulativeTax(36000.01).rate, 10);
  assert.equal(withholding({ income: 9000 }, {}, true).tax, 0);
  assert.deepEqual(bonusTax(36001), { rate: 10, quick: 210, tax: 3390.1 });
  const basis = { prior: {}, low_income: false, special_additional: 0, other: 0, tax_period: "2027-01" };
  const apart = computeTax(basis, { payable: 46000, social: 1000, fund: 0, bonus: 36000, bonusSeparate: true });
  assert.equal(apart.income, 10000);
  assert.equal(apart.total, 120 + 1080);
});

const row = (overrides = {}) => ({
  employee: "E1", total_hours: 176, actual_hours: 160, employed_hours: 176, personal_leave_hours: 16, hours_manual: false,
  base_salary: 11000, salary_adjustment: 0, company_subsidy: 0, bonus: 0, other_adjustment: 0, social_insurance: 1020,
  housing_fund: 700, accommodation: 150, advanced_paid: 0, income_tax: 999, tax_manual: false,
  tax_basis: { tax_period: "2026-11", prior: {}, low_income: false, special_additional: 0, other: 0, bonus_used: false, has_profile: true },
  social_record_exists: true, housing_record_exists: true, ...overrides,
});

test("an unsaved row prorates by hours and works out the tax on the spot", () => {
  const value = row();
  assert.equal(payrollProrated(value), 10000);         // 11000 × 160 / 176
  assert.equal(payrollTax(value), 98.4);               // 不用行上的 999（没勾手动）
  assert.equal(payrollNet(value), 10000 - 1020 - 700 - 98.4 - 150);
  assert.equal(isProrated(value), true);
  assert.equal(autoHours(row({ actual_hours: 100, hours_manual: true })), 160);
  assert.equal(figures(value).taxDetail.cum_taxable, 3280);
  // 手动改过就用填的数
  assert.equal(payrollTax(row({ tax_manual: true, income_tax: 50 })), 50);
  // 旧工资条只有天数：按天算同一个比例
  assert.equal(payrollProrated({ base_salary: 22000, payment_days: 11, total_working_days: 22 }), 11000);
});

test("hours, manual tax and the separate bonus count as unsaved edits", () => {
  const rows = [row()];
  const snapshot = editSnapshot(rows);
  rows[0].actual_hours = "120";
  rows[0].hours_manual = true;
  assert.deepEqual(dirtyRows(rows, snapshot).map((item) => item.employee), ["E1"]);
  const other = [row()];
  const before = editSnapshot(other);
  other[0].bonus_separate = true;
  assert.equal(dirtyRows(other, before).length, 1);
});

test("the readiness strip counts hours, archive-based contributions and tax warnings", () => {
  const info = readiness([row({ social_source: "按档案基数 10000（示例总部-2026）" }), row({ tax_warnings: ["x"], personal_leave_hours: 0 })]);
  assert.equal(info.workHours, 176);
  assert.equal(info.leavePeople, 1);
  assert.equal(info.autoContributions, 1);
  assert.equal(info.taxWarnings, 1);
});

test("the drawer and the page send hours and tax the way the backend expects", () => {
  const drawer = read("components/payroll/PayrollDrawer.vue");
  assert.match(drawer, /按考勤重算/);
  assert.match(drawer, /手动改个税/);
  assert.match(drawer, /奖金按全年一次性奖金单独计税/);
  assert.doesNotMatch(drawer, /目前手填/);
  const page = read("pages/Payroll.vue");
  assert.match(page, /hours_manual: row\.hours_manual \? 1 : 0, actual_hours: row\.hours_manual \? n\(row\.actual_hours\) : undefined/);
  assert.match(page, /tax_manual: row\.tax_manual \? 1 : 0/);
  assert.match(page, /PayrollTaxProfiles/);
  assert.match(read("components/payroll/PayrollTaxProfiles.vue"), /payroll_tax_entry\.'/);
});
