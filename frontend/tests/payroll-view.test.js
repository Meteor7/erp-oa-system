import assert from "node:assert/strict";
import test from "node:test";
import {
  accountShare, canSave, chartParts, chipCounts, chipOf, currentBatchTotal, deptBars, figures, filterRows, isProrated, netBuckets,
  readiness, reconRows, rowLocked, rowState, totalsOf,
} from "../src/lib/payrollView.js";

const row = (overrides = {}) => ({
  employee: "E1", employee_name: "员工甲", company: "QIHENG Demo", department: "研发软件部 - RAY", expense_account_category: "研发费用",
  total_working_days: 22, payment_days: 22, base_salary: 10000, salary_adjustment: 0, company_subsidy: 500, bonus: 0, other_adjustment: 0,
  social_insurance: 1000, housing_fund: 700, income_tax: 200, accommodation: 100, advanced_paid: 0,
  social_record_exists: true, housing_record_exists: true, salary_slip: null, docstatus: null, managed: false, ...overrides,
});

test("a row is in exactly one state, in the order a slip is produced", () => {
  assert.deepEqual(rowState(row()), { key: "new", label: "未生成", tone: "p-gray" });
  assert.equal(rowState(row({ salary_slip: "SS-1", docstatus: 0, managed: true })).label, "草稿");
  assert.equal(rowState(row({ salary_slip: "SS-2", docstatus: 0, managed: false })).label, "外部草稿");
  assert.equal(rowState(row({ salary_slip: "SS-3", docstatus: 1, managed: true })).label, "已确认");
  assert.equal(rowState(row({ social_record_exists: false })).label, "缺社保");
  assert.equal(rowState(row({ housing_record_exists: false })).label, "缺公积金");
  assert.equal(rowState(row({ social_record_exists: false, housing_record_exists: false })).label, "缺社保公积金");
});

test("submitted and external slips are locked; a draft can be saved only when both records exist", () => {
  assert.equal(rowLocked(row()), false);
  assert.equal(rowLocked(row({ salary_slip: "SS", docstatus: 1, managed: true })), true);
  assert.equal(rowLocked(row({ salary_slip: "SS", docstatus: 0, managed: false })), true);
  assert.equal(canSave(row()), true);
  assert.equal(canSave(row({ social_record_exists: false })), false);
  assert.equal(canSave(row({ salary_slip: "SS", docstatus: 1 })), false);
});

test("an unsaved row is calculated from the numbers on the page, in the order of the pay slip", () => {
  const f = figures(row({ base_salary: 22000, salary_adjustment: 2200, payment_days: 11 }));
  assert.equal(f.adjusted, 24200);
  assert.equal(f.prorated, 12100);
  assert.equal(f.payable, 12600);                 // 12,100 + 500 补贴
  assert.equal(f.deductions, 1000 + 700 + 200 + 100);
  assert.equal(f.net, 12600 - 2000);
  assert.equal(isProrated(row({ payment_days: 11 })), true);
  assert.equal(isProrated(row()), false);
});

test("a saved row keeps the slip's own figures", () => {
  const f = figures(row({ amount_source: "salary_slip", adjusted_base: 10000, prorated_base: 10000, payable_salary: 10500, net_pay: 8500 }));
  assert.equal(f.saved, true);
  assert.equal(f.payable, 10500);
  assert.equal(f.net, 8500);
});

const sample = () => [
  row({ employee: "A", employee_name: "甲", department: "研发软件部 - RAY", base_salary: 20000, social_insurance: 2000, housing_fund: 1400, income_tax: 1500, accommodation: 0 }),
  row({ employee: "B", employee_name: "乙", department: "研发电气部 - RAY", base_salary: 9000, company_subsidy: 0, social_insurance: 800, housing_fund: 630, income_tax: 0, accommodation: 300, expense_account_category: "管理费用" }),
  row({ employee: "C", employee_name: "丙", company: "示例研发中心", department: "研发软件部 - RAY", base_salary: 15000, salary_slip: "SS", docstatus: 1, managed: true, amount_source: "salary_slip", payable_salary: 15500, net_pay: 12000, social_insurance: 1500, housing_fund: 1050, income_tax: 800, accommodation: 0, advanced_paid: 150 }),
  row({ employee: "D", employee_name: "丁", social_record_exists: false }),
];

test("the chain totals add up: payable minus the deductions is the net pay", () => {
  const total = totalsOf(sample());
  assert.equal(total.people, 4);
  assert.equal(total.contrib, total.social + total.fund);
  assert.equal(total.other, total.dorm + total.advanced);
  assert.equal(total.dormPeople, 2);          // 只有 B（300）和 D（100）有宿舍扣款
  assert.equal(total.advancedPeople, 1);      // 只有 C 有已发放
  assert.equal(Math.round((total.payable - total.contrib - total.tax - total.other - total.net) * 100) / 100, 0);
});

test("the donut shares add up to one and follow the four parts of the chain", () => {
  const parts = chartParts(totalsOf(sample()));
  assert.deepEqual(parts.map((part) => part.key), ["net", "contrib", "tax", "other"]);
  assert.ok(Math.abs(parts.reduce((t, part) => t + part.share, 0) - 1) < 1e-9);
  assert.equal(chartParts({ net: 0, contrib: 0, tax: 0, other: 0 })[0].share, 0);
});

test("department bars are sorted by payable and the net never exceeds it", () => {
  const bars = deptBars(sample());
  assert.equal(bars[0].name, "研发软件部");
  assert.equal(bars[0].people, 3);
  assert.equal(bars[0].payableWidth, 100);
  assert.ok(bars.every((bar) => bar.netWidth <= bar.payableWidth));
  assert.equal(deptBars(sample(), 1).length, 1);
});

test("net pay buckets count every person once", () => {
  const buckets = netBuckets(sample());
  assert.equal(buckets.reduce((t, bucket) => t + bucket.count, 0), 4);
  assert.deepEqual(buckets.map((bucket) => bucket.label), ["8千以下", "8–12千", "12–16千", "16–20千", "2万以上"]);
});

test("the expense account split is the basis for cost sharing", () => {
  const shares = accountShare(sample());
  assert.equal(shares[0].name, "研发费用");
  assert.ok(Math.abs(shares.reduce((t, item) => t + item.share, 0) - 1) < 1e-9);
  assert.equal(accountShare([row({ expense_account_category: "" })])[0].name, "未设置");
});

test("filters combine: chip, company and a name search", () => {
  const rows = sample();
  assert.deepEqual(chipCounts(rows), { all: 4, new: 2, draft: 0, submitted: 1, issue: 1 });
  assert.equal(chipOf(rows[3]), "issue");
  // 别处生成的草稿也算草稿（和看板口径一致），能不能保存的问题才算"需处理"
  assert.equal(chipOf(row({ salary_slip: "SS", docstatus: 0, managed: false })), "draft");
  assert.equal(chipOf(row({ salary_slip: "SS", docstatus: 0, managed: true })), "draft");
  assert.equal(chipCounts([...rows, row({ employee: "X", salary_slip: "SS", docstatus: 0 })]).draft, 1);
  assert.deepEqual(filterRows(rows, { chip: "new" }).map((r) => r.employee), ["A", "B"]);
  assert.deepEqual(filterRows(rows, { company: "示例研发中心" }).map((r) => r.employee), ["C"]);
  assert.deepEqual(filterRows(rows, { query: " 乙 " }).map((r) => r.employee), ["B"]);
  assert.equal(filterRows(undefined, {}).length, 0);
});

test("readiness before calculating: who lacks records, who is prorated", () => {
  const info = readiness([...sample(), row({ employee: "E", payment_days: 14, housing_record_exists: false })]);
  assert.equal(info.total, 5);
  assert.equal(info.missingSocial, 1);
  assert.equal(info.missingFund, 1);
  assert.equal(info.prorated, 1);
  assert.equal(info.workingDays, 22);
  assert.equal(readiness([]).workingDays, 0);
});

test("reconciliation only compares with a batch that is live", () => {
  const total = { social: 1000, fund: 700 };
  const [social, fund] = reconRows({ total, social: { status: "Current", total: 1000 }, fund: { status: "Current", total: 650 } });
  assert.equal(social.status, "ok");
  assert.equal(fund.status, "diff");
  assert.equal(fund.diff, 50);
  const none = reconRows({ total, social: null, fund: { status: "Pending Activation", total: 1 } });
  assert.deepEqual(none.map((item) => item.status), ["na", "na"]);
  assert.equal(none[0].diff, null);
});

test("the live batch total is read from the workbench response", () => {
  assert.deepEqual(currentBatchTotal({ batches: [{ status: "Historical" }, { status: "Current" }], dashboard: { employee_total: 66318.78 } }), { status: "Current", total: 66318.78 });
  assert.equal(currentBatchTotal({ batches: [] }), null);
  assert.equal(currentBatchTotal(undefined), null);
});
