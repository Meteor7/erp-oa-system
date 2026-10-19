import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  NO_RD_TYPE, PERSONNEL_QUERY_KEYS, decorateEmployees, departmentGroupMap, filterByUrlExtras, filterEmployees, kpiCounts,
  parsePersonnelQuery, personnelQueryOf,
} from "../src/lib/personnelView.js";

const TODAY = "2026-10-09";
const deptMeta = [
  { department_name: "研发一部 - RAY", group_name: "研发" },
  { department_name: "销售部 - RAY", group_name: "运营" },
];
const rows = [
  // 研发一部：试用期 5 天后到期，本月入职，全时研发
  { name: "E1", employee_name: "南通工厂9", company: "QIHENG Demo", department: "研发一部 - RAY", status: "Active", date_of_joining: "2026-10-02", probation_end_date: "2026-10-14", rd_personnel_type: "全时研发", archive_status: "待完善" },
  // 研发一部：研发类型没设（缺口），档案待确认
  { name: "E2", employee_name: "演示员工146", company: "QIHENG Demo", department: "研发一部 - RAY", status: "Active", date_of_joining: "2025-01-01", rd_personnel_type: "", archive_status: "待确认" },
  // 销售部：合同 30 天后到期
  { name: "E3", employee_name: "演示员工157", company: "QIHENG Demo", department: "销售部 - RAY", status: "Active", date_of_joining: "2024-05-01", first_contract_end_date: "2026-11-08", rd_personnel_type: "非研发", archive_status: "已归档" },
  // 研发一部：已离职（离职日早于今天），不该出现在到期提醒里
  { name: "E4", employee_name: "演示员工175", company: "QIHENG Demo", department: "研发一部 - RAY", status: "Active", date_of_joining: "2023-01-01", relieving_date: "2026-09-01", probation_end_date: "2026-10-12", rd_personnel_type: "全时研发", archive_status: "已归档" },
  // 部门不在分组表里：算「其他」
  { name: "E5", employee_name: "演示员工179", company: "QIHENG Demo", department: "后勤部 - RAY", status: "Active", date_of_joining: "2022-01-01", rd_personnel_type: "非研发", archive_status: "已归档" },
  // 没有部门
  { name: "E6", employee_name: "南通工厂4", company: "QIHENG Demo", department: "", status: "Active", date_of_joining: "2022-02-01", rd_personnel_type: "", archive_status: "待完善" },
];
const items = decorateEmployees(rows, { today: TODAY, groupOf: departmentGroupMap(deptMeta) });
const names = (list) => list.map((item) => item.row.employee_name);

test("parsePersonnelQuery reads every supported key and defaults the rest", () => {
  assert.deepEqual(parsePersonnelQuery({}), { status: "active", reminder: "", rd: "", group: "", archive: "", joined: "", left: "", dept: "" });
  assert.deepEqual(
    parsePersonnelQuery({ status: "left", reminder: "expiring", rd: "none", group: "研发", archive: "待完善", joined: "month", left: "month", dept: "研发一部 - RAY" }),
    { status: "left", reminder: "expiring", rd: NO_RD_TYPE, group: "研发", archive: "待完善", joined: "month", left: "month", dept: "研发一部" },
    "dept goes through displayDepartment so the dashboard may pass either spelling",
  );
  assert.equal(parsePersonnelQuery({ rd: "全时研发" }).rd, "全时研发");
  assert.equal(parsePersonnelQuery({ status: ["left", "active"] }).status, "left");
});

test("parsePersonnelQuery drops values the page does not know", () => {
  const state = parsePersonnelQuery({ status: "all", reminder: "alert", rd: "天文学家", archive: "乱写", joined: "year", left: "year" });
  assert.deepEqual(state, { status: "active", reminder: "", rd: "", group: "", archive: "", joined: "", left: "", dept: "" });
});

test("personnelQueryOf writes only non-default values, so clearing every filter gives no params", () => {
  assert.deepEqual(personnelQueryOf(parsePersonnelQuery({})), {});
  assert.deepEqual(personnelQueryOf({ status: "active" }), {});
  assert.deepEqual(personnelQueryOf({ status: "left" }), { status: "left" });
  assert.deepEqual(
    personnelQueryOf({ status: "active", reminder: "expiring", rd: NO_RD_TYPE, group: "研发", archive: "待确认", joined: "month", left: "month", dept: "销售部" }),
    { reminder: "expiring", rd: "none", group: "研发", archive: "待确认", joined: "month", left: "month", dept: "销售部" },
  );
  for (const key of Object.keys(personnelQueryOf({ status: "left", reminder: "expiring", rd: "x", group: "g", archive: "a", joined: "month", left: "month", dept: "d" }))) {
    assert.ok(PERSONNEL_QUERY_KEYS.includes(key), `${key} must be a key the page owns`);
  }
});

test("address -> state -> address is stable", () => {
  const query = { reminder: "expiring", rd: "none", group: "研发", archive: "待完善", joined: "month", left: "month", dept: "研发一部" };
  assert.deepEqual(personnelQueryOf(parsePersonnelQuery(query)), query);
});

test("reminder=expiring is the 60-day probation / contract reminder, not 'has any reminder'", () => {
  const expiring = filterByUrlExtras(items, { reminder: "expiring" }, TODAY);
  assert.deepEqual(names(expiring), ["南通工厂9", "演示员工157"]);
  // 与指标卡「60 天内合同或试用期到期」同口径：在职、probation 或 contract 提醒
  assert.equal(kpiCounts(items, TODAY).expiring, expiring.length);
  // 「只看有提醒」（alertOnly）更宽：缺资料、研发类型缺口也算
  const alerting = filterEmployees(items, { alertOnly: true });
  assert.ok(alerting.length > expiring.length);
});

test("group=研发 filters by department group; unknown departments are 其他; no department is in no group", () => {
  assert.deepEqual(names(filterByUrlExtras(items, { group: "研发" }, TODAY)), ["南通工厂9", "演示员工146", "演示员工175"]);
  assert.deepEqual(names(filterByUrlExtras(items, { group: "运营" }, TODAY)), ["演示员工157"]);
  assert.deepEqual(names(filterByUrlExtras(items, { group: "其他" }, TODAY)), ["演示员工179"]);
  assert.deepEqual(filterByUrlExtras(items, { group: "不存在的分组" }, TODAY), []);
});

test("joined=month keeps people who joined in the current month", () => {
  assert.deepEqual(names(filterByUrlExtras(items, { joined: "month" }, TODAY)), ["南通工厂9"]);
});

test("left=month with status=left keeps exactly the people who already left and whose leaving day is in this month", () => {
  const leavers = decorateEmployees([
    { name: "L1", employee_name: "甲", status: "Active", department: "", date_of_joining: "2020-01-01", relieving_date: "2026-10-03" },
    { name: "L2", employee_name: "乙", status: "Left", department: "", date_of_joining: "2020-01-01", relieving_date: "2026-09-20" },
    { name: "L3", employee_name: "丙", status: "Active", department: "", date_of_joining: "2020-01-01", relieving_date: "2026-10-20" },
    { name: "L4", employee_name: "丁", status: "Active", department: "", date_of_joining: "2020-01-01" },
  ], { today: TODAY, groupOf: departmentGroupMap(deptMeta) });
  const gone = filterEmployees(leavers, { status: "left" });
  assert.deepEqual(names(filterByUrlExtras(gone, { left: "month" }, TODAY)), ["甲"]);      // 乙上个月走的，丙 10-20 才走（还在职）
  assert.deepEqual(names(gone), ["甲", "乙"]);
  assert.equal(filterByUrlExtras(gone, {}, TODAY), gone);
});

test("personnel.rd_gap target (active + no R&D type + group 研发) finds exactly the R&D-department gap", () => {
  const state = parsePersonnelQuery({ status: "active", rd: "none", group: "研发" });
  const list = filterByUrlExtras(filterEmployees(items, { status: state.status, rdType: state.rd }), { group: state.group }, TODAY);
  assert.deepEqual(names(list), ["演示员工146"]);
  assert.equal(kpiCounts(items, TODAY).rdGap, list.length, "same number as the page's own 'R&D department without a type' counter");
});

test("filters combine; with none set everything passes through", () => {
  assert.equal(filterByUrlExtras(items, {}, TODAY), items);
  assert.deepEqual(names(filterByUrlExtras(items, { group: "研发", reminder: "expiring" }, TODAY)), ["南通工厂9"]);
  assert.deepEqual(names(filterByUrlExtras(items, { group: "研发", joined: "month", reminder: "expiring" }, TODAY)), ["南通工厂9"]);
  assert.deepEqual(filterByUrlExtras(items, { group: "运营", joined: "month" }, TODAY), []);
});

// ---------- 页面接线（读源码） ----------
const source = readFileSync(new URL("../src/pages/Personnel.vue", import.meta.url), "utf8");
const script = source.match(/<script setup>[\s\S]*?<\/script>/)?.[0] || "";
const template = source.match(/<template>[\s\S]*<\/template>\s*<style/)?.[0] || "";

test("Personnel reads its filters from the address and writes changes back with replace", () => {
  assert.match(script, /import \{ useRoute, useRouter \} from "vue-router"/);
  assert.match(script, /bindRouteFilters\(\{route,router,specs:\[\{/);
  assert.match(script, /keys:PERSONNEL_QUERY_KEYS/);
  assert.match(script, /read:parsePersonnelQuery/);
  assert.match(script, /toQuery:personnelQueryOf/);
  // 来源页是看板：写回只能是 replace（在 bindRouteFilters 里），页面自己不能 push
  assert.doesNotMatch(script, /router\.push/);
  // 每个会进地址的筛选都在 sources 里
  assert.match(script, /sources:\[statusFilter,expiringOnly,rdFilter,groupFilter,archiveFilter,joinedMonth,leftMonth,departmentFilter\]/);
  // 先理顺「部门不可用就清掉」，再写地址
  assert.ok(script.indexOf("departmentOptions.value.includes(departmentFilter.value)") < script.indexOf("bindRouteFilters("));
});

test("Personnel applies the extra filters to the list and the export, and shows removable tags", () => {
  assert.match(script, /filterByUrlExtras\(filterEmployees\(items\.value,/);
  assert.match(script, /group:groupFilter\.value,joined:joinedMonth\.value\?"month":"",left:leftMonth\.value\?"month":"",reminder:expiringOnly\.value\?"expiring":""/);
  assert.match(template, /data-chip-expiring :aria-pressed="expiringOnly"/);
  assert.match(template, /data-chip-joined :aria-pressed="joinedMonth"/);
  assert.match(template, /data-chip-left :aria-pressed="leftMonth"/);
  assert.match(template, /v-if="groupFilter"[^>]*data-chip-group/);
  assert.match(template, /@click="groupFilter=''"/);
  assert.match(template, /分组：\{\{groupFilter\}\}/);
  // 「只看有提醒」仍是原来宽泛的那个，没有被换成到期
  assert.match(template, /:aria-pressed="alertOnly" @click="alertOnly=!alertOnly"/);
});

// ---------- 与后端目标表对齐 ----------
const targets = JSON.parse(readFileSync(new URL("../../rayher_hr_payroll/dashboard/targets.json", import.meta.url), "utf8")).targets;

test("every /personnel dashboard target only uses params the page understands", () => {
  const personnel = Object.entries(targets).filter(([, target]) => target.path === "/personnel");
  assert.ok(personnel.length >= 5);
  for (const [key, target] of personnel) {
    for (const name of [...Object.keys(target.query || {}), ...(target.params || [])]) {
      assert.ok(PERSONNEL_QUERY_KEYS.includes(name), `${key}: ${name} is not read by Personnel.vue`);
    }
    // 固定参数的值必须被解析（不会被当成「不认识」丢掉）
    const state = parsePersonnelQuery(target.query);
    assert.deepEqual(personnelQueryOf(state), Object.fromEntries(Object.entries(target.query).filter(([name, value]) => !(name === "status" && value === "active"))), `${key} round-trips`);
  }
});

test("the dashboard's personnel targets select the expected people", () => {
  const apply = (key) => {
    const state = parsePersonnelQuery(targets[key].query);
    return filterByUrlExtras(
      filterEmployees(items, { status: state.status, rdType: state.rd, archive: state.archive }),
      { group: state.group, joined: state.joined, reminder: state.reminder },
      TODAY,
    );
  };
  assert.deepEqual(names(apply("personnel.expiring")), ["南通工厂9", "演示员工157"]);
  assert.deepEqual(names(apply("personnel.rd_gap")), ["演示员工146"]);
  assert.deepEqual(names(apply("personnel.file")), ["南通工厂9", "南通工厂4"]);
  assert.deepEqual(names(apply("personnel.joined")), ["南通工厂9"]);
});
