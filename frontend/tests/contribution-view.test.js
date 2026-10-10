import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  KINDS, activationBlockers, baseStatus, batchOf, comparisonLines, drawerOptions, issueFilter, mainReason, missingBaseCount, normalizeRow,
  pendingSummary, progress, readinessText, reasonText, reasonTypes, sortIssues, stepStates,
} from "../src/lib/contributionView.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

const socialRow = (overrides = {}) => ({
  name: "R1", excel_name: "员工甲", employee_name: "员工甲", company: "Rayher", employee: "E1", status: "Pending", row_type: undefined,
  difference_reasons: "local_pension与后台计算不一致", contribution_base: 17500, reference_base: 17500,
  employee_pension: 1400, calculated_employee_pension: 1400, local_pension: 0, calculated_local_pension: 175,
  employee_total: 2000, calculated_employee_total: 2000, company_total: 4500, calculated_company_total: 4675,
  receivable_total: 6500, calculated_receivable_total: 6675, ...overrides,
});
const fundRow = (overrides = {}) => ({
  name: "F1", excel_name: "员工乙", employee_name: "员工乙", company: "Rayher", employee: "E2", status: "Pending", row_type: "excel",
  difference_reasons: "个人缴存额与后台计算不一致", contribution_base: 12400, reference_base: 12400,
  employee_amount: 620, company_amount: 868, receivable_total: 1488,
  calculated_employee_amount: 868, calculated_company_amount: 868, calculated_receivable_total: 1736, ...overrides,
});

test("the two pages share one flow and call their own endpoints", () => {
  assert.equal(KINDS.si.fn.upload, "rayher_hr_payroll.api.social_insurance_import_entry.upload_social_workbook");
  assert.equal(KINDS.fund.fn.upload, "rayher_hr_payroll.api.housing_fund_import_entry.upload_fund_workbook");
  for (const key of ["workbench", "upload", "activate", "confirm", "ignore", "cancel", "reconcile"]) {
    assert.ok(KINDS.si.fn[key] && KINDS.fund.fn[key], key);
  }
});

test("reasons are sorted into the groups HR works through, blocking ones first", () => {
  const types = reasonTypes("员工档案社保基数未维护；员工户口信息未维护或无法判断深户/非深户；Excel缴费工资与员工档案社保基数不一致；证件号码一致但姓名不同");
  assert.deepEqual(types.map((item) => item.key), ["noBase", "hukou", "baseDiff", "nameDiff"]);
  assert.equal(mainReason(types).key, "noBase");
  assert.equal(reasonTypes("证件号码和姓名均无法关联员工")[0].key, "unlinked");
  assert.equal(reasonTypes("本月申报表里没有这个人")[0].key, "missing");
  assert.equal(reasonTypes("Excel缴存基数与员工档案公积金基数不一致")[0].key, "baseDiff");
  assert.equal(reasonTypes("个人缴存额与后台计算不一致")[0].key, "compDiff");
  assert.equal(reasonTypes("同一Excel内员工重复")[0].key, "duplicate");
  assert.equal(reasonTypes("某个没见过的原因")[0].key, "other");
  assert.deepEqual(reasonTypes(""), []);
});

test("component field names in a reason are shown in Chinese", () => {
  assert.equal(reasonText("local_pension与后台计算不一致"), "地方补充养老与后台计算不一致");
  assert.equal(reasonText("employee_medical与后台计算不一致"), "个人医疗与后台计算不一致");
});

test("a social row becomes an issue with the receivable difference", () => {
  const item = normalizeRow("si", socialRow());
  assert.equal(item.main.key, "compDiff");
  assert.equal(item.excelTotal, 6500);
  assert.equal(item.calcTotal, 6675);
  assert.equal(item.diff, -175);
  assert.equal(item.resolved, false);
  assert.deepEqual(item.reasons, ["地方补充养老与后台计算不一致"]);
});

test("a housing fund row compares the two employee and company amounts together", () => {
  const item = normalizeRow("fund", fundRow());
  assert.equal(item.excelTotal, 1488);
  assert.equal(item.calcTotal, 1736);
  assert.equal(item.diff, -248);
});

test("a row that could not be recalculated has no calculated side, not a zero", () => {
  const item = normalizeRow("fund", fundRow({ difference_reasons: "员工档案公积金基数未维护", reference_base: 0, calculated_employee_amount: 0, calculated_company_amount: 0, calculated_receivable_total: 0 }));
  assert.equal(item.calcTotal, null);
  assert.equal(item.diff, null);
  const lines = comparisonLines("fund", fundRow({ reference_base: 0, calculated_receivable_total: 0 }));
  assert.ok(lines.every((line) => line.calc === null));
});

test("the drawer table marks only the lines that differ", () => {
  const lines = comparisonLines("si", socialRow({ employee_pension: 1400, calculated_employee_pension: 1400 }));
  assert.equal(lines.find((line) => line.field === "local_pension").differs, true);
  assert.equal(lines.find((line) => line.field === "employee_pension").differs, false);
  assert.equal(lines.find((line) => line.field === "contribution_base").calc, 17500);
});

test("people missing from the file only offer the two audited answers", () => {
  const item = normalizeRow("fund", fundRow({ row_type: "missing", difference_reasons: "本月申报表里没有这个人", employee_amount: 0, company_amount: 0 }));
  assert.equal(item.rowType, "missing");
  assert.equal(item.excelTotal, null);
  const options = drawerOptions("fund", item);
  assert.deepEqual(options.map((option) => option.note), ["需补缴：", "无需缴纳："]);
  assert.ok(options.every((option) => option.key === "ignore"));
});

test("a missing base is fixed in the base table; confirming and ignoring always need a reason", () => {
  const noBase = normalizeRow("si", socialRow({ difference_reasons: "员工档案社保基数未维护；员工户口信息未维护或无法判断深户/非深户" }));
  const options = drawerOptions("si", noBase);
  assert.equal(options[0].key, "fix");
  assert.ok(options[0].recommended);
  assert.equal(options.find((option) => option.key === "confirm").needsNote, true);
  assert.equal(options.find((option) => option.key === "ignore").needsNote, true);
  const unlinked = normalizeRow("si", socialRow({ employee: "", difference_reasons: "证件号码和姓名均无法关联员工" }));
  assert.ok(drawerOptions("si", unlinked).some((option) => option.key === "link"));
});

test("issues are listed blocking first and filtered by their state", () => {
  const items = [
    normalizeRow("si", socialRow({ name: "A", employee_name: "甲", difference_reasons: "local_pension与后台计算不一致" })),
    normalizeRow("si", socialRow({ name: "B", employee_name: "乙", difference_reasons: "员工档案社保基数未维护" })),
    normalizeRow("si", socialRow({ name: "C", employee_name: "丙", status: "Ignored", difference_reasons: "证件号码一致但姓名不同" })),
  ];
  assert.deepEqual(sortIssues(items).map((item) => item.id), ["B", "A", "C"]);
  assert.deepEqual(issueFilter(items, "pending").map((item) => item.id), ["A", "B"]);
  assert.deepEqual(issueFilter(items, "done").map((item) => item.id), ["C"]);
  assert.equal(issueFilter(items, "all").length, 3);
  assert.deepEqual(pendingSummary(items).map((item) => [item.key, item.count]), [["noBase", 1], ["compDiff", 1]]);
});

const pending = (extra = {}) => ({
  batches: [{ name: "B1", status: "Pending Activation", source_filename: "10月.xlsx", parsed_rows: 60 }],
  dashboard: { total_rows: 60, pending_rows: 4 }, pending: [{ row_type: "excel" }, { row_type: "excel" }, { row_type: "missing" }, { row_type: "excel" }], ...extra,
});

test("progress counts Excel rows that no longer need a decision", () => {
  assert.deepEqual(progress(pending()), { total: 60, done: 57, percent: 95 });
  assert.deepEqual(progress({}), { total: 0, done: 0, percent: 0 });
});

test("the four steps report where the month stands", () => {
  const states = stepStates({ data: pending(), missingBase: 2 });
  assert.deepEqual(states.map((state) => state.done), [true, false, false, false]);
  assert.equal(states[1].desc, "4 条待处理");
  assert.equal(states[2].desc, "2 人缺基数");
  assert.equal(stepStates({ data: {}, missingBase: 0 })[0].desc, "还没导入");
  const done = stepStates({ data: { batches: [{ status: "Current", source_filename: "x", parsed_rows: 3 }], dashboard: { pending_rows: 0 } }, missingBase: 0 });
  assert.deepEqual(done.map((state) => state.done), [true, true, true, true]);
});

test("a batch can only go live once everything is decided and every base is filled", () => {
  assert.deepEqual(activationBlockers({ data: {}, missingBase: 0 }), [{ text: "还没有导入申报表", step: 1 }]);
  assert.deepEqual(activationBlockers({ data: pending(), missingBase: 2 }).map((item) => item.step), [2, 3]);
  assert.deepEqual(activationBlockers({ data: pending({ dashboard: { pending_rows: 0 } }), missingBase: 0 }), []);
  assert.deepEqual(activationBlockers({ data: { batches: [{ status: "Current" }] }, missingBase: 5 }), []);
  assert.equal(batchOf({ batches: [{ status: "Historical" }, { status: "Current", is_current: 1 }] }).status, "Current");
});

test("the base table flags missing bases and households, and changes against last month", () => {
  assert.equal(baseStatus({ base: null }, "fund").text, "缺基数");
  assert.equal(baseStatus({ base: 9000, household_classification: "待完善" }, "si").text, "缺户口");
  assert.equal(baseStatus({ base: 9000, household_classification: "待完善" }, "fund").text, "正常");
  assert.equal(baseStatus({ base: 9000, prev_base: 8000 }, "fund").text, "较上月有变化");
  assert.equal(baseStatus({ base: 9000, prev_base: 9000, note: "户口未维护，无法复算" }, "si").text, "户口未维护，无法复算");
  assert.equal(missingBaseCount([{ base: null }, { base: 1, household_classification: "待完善" }, { base: 1 }], "si"), 2);
  assert.equal(missingBaseCount([{ base: null }, { base: 1, household_classification: "待完善" }, { base: 1 }], "fund"), 1);
});

test("payroll readiness says who is still short", () => {
  const readiness = { kinds: { si: { label: "社保", ready: 70, missing_count: 3 }, fund: { label: "公积金", ready: 73, missing_count: 0 } } };
  assert.equal(readinessText(readiness, "si"), "社保还差 3 人没有本月记录");
  assert.equal(readinessText(readiness, "fund"), "公积金本月记录已齐（73 人）");
  assert.equal(readinessText(null, "fund"), "");
});

test("both pages are thin shells over the shared workbench", () => {
  assert.match(read("../src/pages/SocialInsurance.vue"), /<ContributionWorkbench kind="si" \/>/);
  assert.match(read("../src/pages/HousingFund.vue"), /<ContributionWorkbench kind="fund" \/>/);
});
