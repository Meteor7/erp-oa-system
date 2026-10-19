import test from "node:test";
import assert from "node:assert/strict";
import {
  NO_RD_TYPE,
  avatarText,
  archiveTone,
  completeness,
  daysBetween,
  decorateEmployee,
  decorateEmployees,
  defaultRdType,
  departmentGroupMap,
  departmentGroups,
  displayFieldValue,
  filterEmployees,
  isLeft,
  kpiCounts,
  lastModifiedText,
  maskValue,
  missingSummary,
  pageSlice,
  reminders,
  requiredFields,
  seniority,
  sortEmployees,
  supervisorLabel,
  todayIso,
  visibleTabs,
} from "../src/lib/personnelView.js";

const TODAY = "2026-10-08";

const full = (extra = {}) => ({
  name: "HR-EMP-1", company: "QIHENG Demo", employee_number: "A001", employee_name: "演示员工186", english_name: "Chunlin Huang",
  date_of_birth: "1990-02-03", cell_number: "13800000002", household_registration: "深圳",
  department: "研发软件部 - RAY", designation: "软件工程师", reports_to: "HR-EMP-9", employment_type: "全职",
  labour_contract_start_date: "2023-03-06", rd_personnel_type: "全时研发", education_level_cn: "本科", graduation_school: "示例大学",
  default_monthly_salary: 20000, default_social_insurance_base: 8000, default_housing_fund_base: 8000,
  social_insurance_number: "SI1", housing_fund_number: "HF1", id_card_number_cn: "110101199001010050",
  bank_name: "中国银行", bank_ac_no: "6222000011112222", date_of_joining: "2023-03-06", relieving_date: null,
  archive_status: "已归档", status: "Active",
  ...extra,
});

test("todayIso formats the local date", () => {
  assert.equal(todayIso(new Date(2026, 9, 8, 23, 59)), "2026-10-08");
  assert.equal(todayIso(new Date(2026, 0, 2)), "2026-01-02");
});

test("daysBetween handles invalid dates", () => {
  assert.equal(daysBetween("2026-10-08", "2026-10-10"), 2);
  assert.equal(daysBetween("2026-10-08", "2026-10-01"), -7);
  assert.equal(daysBetween("2026-10-08", ""), null);
  assert.equal(daysBetween("2026-02-30", "2026-03-01"), null);
});

test("isLeft follows the server rule: the relieving day itself is still active", () => {
  assert.equal(isLeft({ relieving_date: null }, TODAY), false);
  assert.equal(isLeft({ relieving_date: "2026-10-08" }, TODAY), false);
  assert.equal(isLeft({ relieving_date: "2026-10-09" }, TODAY), false);
  assert.equal(isLeft({ relieving_date: "2026-10-07" }, TODAY), true);
  assert.equal(isLeft({ status: "Left" }, TODAY), true);
  assert.equal(isLeft({ status: "Active", relieving_date: "2099-01-01" }, TODAY), false);
});

test("seniority is shown as years and months, until the relieving date for leavers", () => {
  assert.equal(seniority({ date_of_joining: "2023-03-06" }, TODAY), "3 年 7 个月");
  assert.equal(seniority({ date_of_joining: "2025-10-08" }, TODAY), "1 年");
  assert.equal(seniority({ date_of_joining: "2026-03-08" }, TODAY), "7 个月");
  assert.equal(seniority({ date_of_joining: "2026-09-30" }, TODAY), "8 天");
  assert.equal(seniority({ date_of_joining: TODAY }, TODAY), "今天入职");
  assert.equal(seniority({ date_of_joining: "2026-11-01" }, TODAY), "尚未入职");
  assert.equal(seniority({}, TODAY), "");
  assert.equal(seniority({ date_of_joining: "2023-08-14", relieving_date: "2025-08-13" }, TODAY), "1 年 11 个月");
});

test("a complete record has 100% and nothing missing", () => {
  const result = completeness(full());
  assert.equal(result.pct, 100);
  assert.deepEqual(result.missing, []);
  assert.equal(result.total, requiredFields().length);
});

test("missing items are listed with their tab; zero amounts count as missing", () => {
  const result = completeness(full({ cell_number: " ", bank_ac_no: null, default_monthly_salary: 0, graduation_school: "" }));
  assert.deepEqual(result.missing.map((item) => item.key), ["cell_number", "graduation_school", "default_monthly_salary", "bank_ac_no"]);
  assert.deepEqual(result.missing.map((item) => item.tab), ["basic", "edu", "pay", "id"]);
  assert.equal(result.filled, result.total - 4);
  assert.equal(result.pct, Math.round((result.filled / result.total) * 100));
});

test("sensitive-hidden accounts are not measured on fields of the locked tabs", () => {
  const row = full({ bank_name: "", social_insurance_number: "", default_monthly_salary: 0 });
  const hidden = completeness(row, { sensitiveHidden: true });
  assert.deepEqual(hidden.missing, []);
  assert.equal(hidden.pct, 100);
  assert.ok(hidden.total < completeness(row).total);
  assert.ok(requiredFields({ sensitiveHidden: true }).every((field) => !["pay", "id"].includes(field.tab)));
  assert.deepEqual(visibleTabs({ sensitiveHidden: true }).map((tab) => tab.key), ["basic", "job", "edu"]);
  assert.deepEqual(visibleTabs().map((tab) => tab.key), ["basic", "job", "edu", "pay", "id"]);
});

test("missingSummary names the first three items", () => {
  assert.equal(missingSummary([]), "资料齐全");
  const missing = completeness(full({ cell_number: "", household_registration: "", department: "", designation: "" })).missing;
  assert.equal(missingSummary(missing), "还缺 4 项：联系电话、户口信息、部门…");
});

test("reminders: probation and contract inside 60 days, soonest first, urgent when within a week", () => {
  const list = reminders(full({ probation_end_date: "2026-10-31", first_contract_end_date: "2026-12-06" }), TODAY);
  assert.deepEqual(list.map((item) => item.key), ["probation", "contract"]);
  assert.equal(list[0].text, "演示员工173期 10-31 到期");
  assert.equal(list[0].tone, "warn");
  assert.equal(list[1].text, "演示员工116 12-06 到期");
  const urgent = reminders(full({ probation_end_date: "2026-10-12" }), TODAY);
  assert.equal(urgent[0].tone, "bad");
});

test("reminders ignore dates past or beyond 60 days, and a renewed first contract", () => {
  assert.deepEqual(reminders(full({ probation_end_date: "2026-10-07" }), TODAY), []);
  assert.deepEqual(reminders(full({ first_contract_end_date: "2026-12-08" }), TODAY), []);
  assert.equal(reminders(full({ first_contract_end_date: "2026-12-07" }), TODAY)[0].key, "contract");
  const renewed = reminders(full({ first_contract_end_date: "2026-11-01", second_contract_end_date: "2029-11-01" }), TODAY);
  assert.deepEqual(renewed, []);
  const second = reminders(full({ first_contract_end_date: "2023-11-01", second_contract_end_date: "2026-11-15" }), TODAY);
  assert.equal(second[0].text, "演示员工116 11-15 到期");
});

test("reminders: leaving soon, left, and missing data", () => {
  assert.deepEqual(reminders(full({ relieving_date: "2026-10-31" }), TODAY).map((item) => item.text), ["10-31 演示员工166"]);
  const left = reminders(full({ relieving_date: "2026-06-17", probation_end_date: "2026-10-31", cell_number: "" }), TODAY);
  assert.deepEqual(left.map((item) => item.text), ["已演示员工166 06-17"]);
  const missing = reminders(full({ cell_number: "", employee_number: "" }), TODAY);
  assert.deepEqual(missing.map((item) => item.text), ["缺 2 项资料"]);
});

test("decorateEmployee derives the list row fields", () => {
  const item = decorateEmployee(full({ department: "研发软件部 - RAY", archive_status: null, probation_end_date: "2026-10-31" }), { today: TODAY });
  assert.equal(item.department, "研发软件部");
  assert.equal(item.archive, "待完善");
  assert.equal(item.left, false);
  assert.equal(item.seniority, "3 年 7 个月");
  assert.equal(item.reminders[0].key, "probation");
});

test("archive tones and avatar text", () => {
  assert.equal(archiveTone("已归档"), "ok");
  assert.equal(archiveTone("待确认"), "warn");
  assert.equal(archiveTone("待完善"), "");
  assert.equal(avatarText("演示员工186"), "春林");
  assert.equal(avatarText("演示员工108"), "演示员工108");
  assert.equal(avatarText("Chunlin Huang"), "CH");
  assert.equal(avatarText(""), "?");
});

const roster = () => decorateEmployees([
  full({ name: "E1", employee_name: "甲", employee_number: "A010", rd_personnel_type: "全时研发", date_of_joining: "2026-10-01", department: "研发软件部 - RAY", archive_status: "待完善", probation_end_date: "2026-12-30" }),
  full({ name: "E2", employee_name: "乙", employee_number: "A002", rd_personnel_type: "非研发", date_of_joining: "2020-01-01", department: "总经办 - RAY", probation_end_date: "2026-10-20" }),
  full({ name: "E3", employee_name: "丙", employee_number: "", rd_personnel_type: "研发辅助", date_of_joining: "2024-05-20", department: "研发软件部 - SHGL", company: "示例研发中心", archive_status: "待确认", first_contract_end_date: "2026-11-30" }),
  full({ name: "E4", employee_name: "丁", employee_number: "A001", rd_personnel_type: "", date_of_joining: "2023-08-14", relieving_date: "2026-10-02", department: "研发光学部 - RAY", english_name: "Ding Ding" }),
  full({ name: "E5", employee_name: "戊", employee_number: "A003", rd_personnel_type: "全时研发", date_of_joining: "2021-01-01", relieving_date: "2026-10-30" }),
], { today: TODAY });

test("kpiCounts covers active, joined, left, file pending and expiring", () => {
  const k = kpiCounts(roster(), TODAY);
  assert.equal(k.active, 4);
  assert.equal(k.rd, 3);
  assert.equal(k.other, 1);
  assert.equal(k.joinedThisMonth, 1);
  assert.equal(k.onProbation, 2);
  assert.equal(k.leftThisMonth, 2);
  assert.equal(k.leftEffective, 1);
  assert.equal(k.leftPending, 1);
  assert.equal(k.fileOpen, 2);
  assert.equal(k.filePending, 1);
  assert.equal(k.fileConfirm, 1);
  assert.equal(k.expiringProbation, 1);
  assert.equal(k.expiringContract, 1);
  assert.equal(k.expiring, 2);
});

test("filterEmployees combines company, status, department, rd type, archive, alerts and keyword", () => {
  const items = roster();
  const names = (filters) => filterEmployees(items, filters).map((item) => item.row.name);
  assert.deepEqual(names({ status: "active" }), ["E1", "E2", "E3", "E5"]);
  assert.deepEqual(names({ status: "left" }), ["E4"]);
  assert.deepEqual(names({ status: "all" }), ["E1", "E2", "E3", "E4", "E5"]);
  assert.deepEqual(names({ status: "active", company: "示例研发中心" }), ["E3"]);
  assert.deepEqual(names({ status: "active", department: "研发软件部" }), ["E1", "E3", "E5"]);
  assert.deepEqual(names({ status: "active", rdType: "全时研发" }), ["E1", "E5"]);
  assert.deepEqual(names({ status: "all", rdType: NO_RD_TYPE }), ["E4"]);
  assert.deepEqual(names({ status: "active", archive: "待确认" }), ["E3"]);
  assert.deepEqual(names({ status: "active", archive: "已归档" }), ["E2", "E5"]);
  assert.deepEqual(names({ status: "active", alertOnly: true }), ["E2", "E3", "E5"]);
  assert.deepEqual(names({ status: "left", alertOnly: true }), []);
  assert.deepEqual(names({ status: "all", keyword: " ding " }), ["E4"]);
  assert.deepEqual(names({ status: "all", keyword: "a010" }), ["E1"]);
  assert.deepEqual(names({ status: "all", keyword: "光学" }), ["E4"]);
  assert.deepEqual(names({ status: "all", keyword: "软件工程师" }), ["E1", "E2", "E3", "E4", "E5"]);
});

test("search never matches salary, id number or bank data", () => {
  const items = roster();
  assert.deepEqual(filterEmployees(items, { status: "all", keyword: "440101" }), []);
  assert.deepEqual(filterEmployees(items, { status: "all", keyword: "6222" }), []);
  assert.deepEqual(filterEmployees(items, { status: "all", keyword: "20000" }), []);
});

test("sortEmployees: default keeps order, others are stable", () => {
  const items = roster();
  const ids = (mode) => sortEmployees(items, mode).map((item) => item.row.name);
  assert.deepEqual(ids("default"), ["E1", "E2", "E3", "E4", "E5"]);
  assert.deepEqual(ids("joined_desc"), ["E1", "E3", "E4", "E5", "E2"]);
  assert.deepEqual(ids("joined_asc"), ["E2", "E5", "E4", "E3", "E1"]);
  assert.deepEqual(ids("number"), ["E4", "E2", "E5", "E1", "E3"]);
  // 提醒优先：即将演示员工166 < 演示员工173期 < 演示员工116 < 缺资料 < 无提醒（一周内到期的排在所有提醒之前）
  assert.deepEqual(ids("alert").slice(0, 4), ["E5", "E2", "E3", "E1"]);
  assert.equal(items.length, 5);
});

test("pageSlice clamps the page", () => {
  const list = Array.from({ length: 45 }, (_, index) => index);
  assert.equal(pageSlice(list, 1, 20).items.length, 20);
  assert.equal(pageSlice(list, 3, 20).items.length, 5);
  assert.equal(pageSlice(list, 9, 20).page, 3);
  assert.equal(pageSlice([], 4, 20).page, 1);
  assert.equal(pageSlice([], 1, 20).pageCount, 1);
});

test("departmentGroups counts from the roster, by status and company, with an 其他 group", () => {
  const meta = [
    { name: "研发软件部 - RAY", department_name: "研发软件部", company: "QIHENG Demo", group_name: "研发" },
    { name: "研发软件部 - SHGL", department_name: "研发软件部", company: "示例研发中心", group_name: "研发" },
    { name: "研发光学部 - RAY", department_name: "研发光学部", company: "QIHENG Demo", group_name: "研发" },
    { name: "财务部 - RAY", department_name: "财务部", company: "QIHENG Demo", group_name: "职能" },
  ];
  const items = roster();
  const active = departmentGroups(items, meta, { status: "active" });
  assert.deepEqual(active.map((group) => group.name), ["研发", "其他"]);
  assert.deepEqual(active[0].departments.map((d) => [d.name, d.employee_count]), [["研发软件部", 3]]);
  assert.deepEqual(active[1].departments.map((d) => [d.name, d.employee_count]), [["总经办", 1]]);
  assert.equal(active[0].total, 3);
  const left = departmentGroups(items, meta, { status: "left" });
  assert.deepEqual(left.map((group) => [group.name, group.total]), [["研发", 1]]);
  const shanghai = departmentGroups(items, meta, { status: "active", company: "示例研发中心" });
  assert.deepEqual(shanghai.map((group) => [group.name, group.total]), [["研发", 1]]);
});

const RD_META = [
  { name: "研发软件部 - RAY", department_name: "研发软件部", company: "QIHENG Demo", group_name: "研发" },
  { name: "研发AI部 - RAY", department_name: "研发AI部", company: "QIHENG Demo", group_name: "研发" },
  { name: "财务部 - RAY", department_name: "财务部", company: "QIHENG Demo", group_name: "职能" },
  { name: "总经办 - RAY", department_name: "总经办", company: "QIHENG Demo", group_name: "职能" },
];

test("defaultRdType: the R&D group is 全时研发, other known groups 非研发, unknown stays empty", () => {
  assert.equal(defaultRdType("研发"), "全时研发");
  assert.equal(defaultRdType("职能"), "非研发");
  assert.equal(defaultRdType("客户运营"), "非研发");
  assert.equal(defaultRdType("其他"), "");
  assert.equal(defaultRdType(""), "");
  assert.equal(defaultRdType(undefined), "");
});

test("an active person in an R&D department without an R&D type is flagged, others are not", () => {
  const groupOf = departmentGroupMap(RD_META);
  const ctx = { today: TODAY, groupOf };
  const flagged = decorateEmployee(full({ department: "研发AI部 - RAY", rd_personnel_type: "" }), ctx);
  assert.equal(flagged.rdGap, true);
  assert.equal(flagged.group, "研发");
  assert.ok(flagged.reminders.some((r) => r.key === "rdtype" && r.tone === "warn"));
  // 填了类型、非研发部门、已演示员工166、没有分组信息：演示员工177提醒
  assert.equal(decorateEmployee(full({ rd_personnel_type: "全时研发" }), ctx).rdGap, false);
  assert.equal(decorateEmployee(full({ department: "财务部 - RAY", rd_personnel_type: "" }), ctx).rdGap, false);
  assert.equal(decorateEmployee(full({ department: "研发AI部 - RAY", rd_personnel_type: "", relieving_date: "2026-09-01" }), ctx).rdGap, false);
  assert.equal(decorateEmployee(full({ department: "研发AI部 - RAY", rd_personnel_type: "" }), { today: TODAY }).rdGap, false);
  // 明确选了「非研发」是 HR 的决定，不当作缺口
  assert.equal(decorateEmployee(full({ department: "研发AI部 - RAY", rd_personnel_type: "非研发" }), ctx).rdGap, false);
});

test("the R&D type reminder sits between contract dates and missing data, and counts in the KPI", () => {
  const groupOf = departmentGroupMap(RD_META);
  const list = reminders(full(), TODAY, { rdGap: true, missingCount: 2 });
  assert.deepEqual(list.map((r) => r.key), ["rdtype", "missing"]);
  const items = decorateEmployees([
    full({ name: "a", department: "研发AI部 - RAY", rd_personnel_type: "" }),
    full({ name: "b", department: "研发AI部 - RAY", rd_personnel_type: "全时研发" }),
    full({ name: "c", department: "财务部 - RAY", rd_personnel_type: "" }),
  ], { today: TODAY, groupOf });
  const kpi = kpiCounts(items, TODAY);
  assert.equal(kpi.rdGap, 1);
  assert.equal(kpi.rd, 1);
  assert.equal(kpi.other, 2);
  assert.equal(filterEmployees(items, { alertOnly: true, status: "active" }).some((item) => item.key === "a"), true);
});

test("departmentGroups also reports how many people of each group fill in the R&D timesheet", () => {
  const items = decorateEmployees([
    full({ name: "1", department: "研发软件部 - RAY", rd_personnel_type: "全时研发" }),
    full({ name: "2", department: "研发软件部 - RAY", rd_personnel_type: "非研发" }),
    full({ name: "3", department: "研发AI部 - RAY", rd_personnel_type: "" }),
    full({ name: "4", department: "总经办 - RAY", rd_personnel_type: "研发辅助" }),
    full({ name: "5", department: "财务部 - RAY", rd_personnel_type: "非研发" }),
  ], { today: TODAY });
  const groups = departmentGroups(items, RD_META, { status: "active" });
  const byName = Object.fromEntries(groups.map((group) => [group.name, group]));
  assert.deepEqual([byName["研发"].total, byName["研发"].fill], [3, 1]);
  // 研发辅助的人在职能部门，也要填工时，所以算在职能这一组的 fill 里
  assert.deepEqual([byName["职能"].total, byName["职能"].fill], [2, 1]);
  assert.deepEqual(byName["研发"].departments.map((d) => [d.name, d.employee_count, d.fill_count]), [["研发软件部", 2, 1], ["研发AI部", 1, 0]]);
});

test("maskValue hides sensitive values and leaves blanks alone", () => {
  assert.equal(maskValue("id_card_number_cn", "110101199001010050"), "440*************34");
  assert.equal(maskValue("bank_ac_no", "6222000011112222"), "•••• •••• ••••");
  assert.equal(maskValue("social_insurance_number", "SI123"), "•••• ••••");
  assert.equal(maskValue("housing_fund_number", "HF123"), "•••• ••••");
  assert.equal(maskValue("default_monthly_salary", 20000), "••••••");
  assert.equal(maskValue("default_monthly_salary", ""), "");
  assert.equal(maskValue("bank_ac_no", null), "");
  assert.equal(maskValue("employee_name", "演示员工186"), "演示员工186");
  assert.ok(!maskValue("id_card_number_cn", "110101199001010050").includes("0101"));
});

test("displayFieldValue masks by default and shows plain values when revealed", () => {
  assert.equal(displayFieldValue("default_monthly_salary", 20000), "••••••");
  assert.equal(displayFieldValue("default_monthly_salary", 20000, { reveal: true }), "20,000.00");
  assert.equal(displayFieldValue("bank_ac_no", "6222", { reveal: true }), "6222");
  assert.equal(displayFieldValue("cell_number", "138"), "138");
  assert.equal(displayFieldValue("bank_ac_no", ""), "");
});

test("lastModifiedText and supervisorLabel", () => {
  assert.equal(lastModifiedText({ modified: "2026-10-06 16:20:45.123456", modified_by: "hr@example.com" }), "最近修改：hr@example.com · 10-06 16:20");
  assert.equal(lastModifiedText({ modified: "2026-10-06 16:20:45" }), "最近修改：10-06 16:20");
  assert.equal(lastModifiedText({}), "");
  const names = new Map([["HR-EMP-9", "王主管"]]);
  assert.equal(supervisorLabel({ reports_to: "HR-EMP-9" }, names), "王主管");
  assert.equal(supervisorLabel({ reports_to: "HR-EMP-0" }, names), "HR-EMP-0");
  assert.equal(supervisorLabel({}, names), "");
});
