import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { PAYROLL_QUERY_KEYS, filterPayrollRows, isDraftSlip, parsePayrollQuery, payrollQueryOf } from "../src/lib/payrollFilters.js";

const read = (name) => readFileSync(new URL(`../src/pages/${name}`, import.meta.url), "utf8");
const targets = JSON.parse(readFileSync(new URL("../../rayher_hr_payroll/dashboard/targets.json", import.meta.url), "utf8")).targets;
const indexOf = (text, needle) => {
  const at = text.indexOf(needle);
  assert.ok(at >= 0, `${needle} not found`);
  return at;
};

// ---------- 薪酬：只看草稿 ----------
test("payroll: draft = a slip that exists and is not submitted", () => {
  assert.equal(isDraftSlip({ salary_slip: "SS-1", docstatus: 0 }), true);
  assert.equal(isDraftSlip({ salary_slip: "SS-2", docstatus: 1 }), false, "submitted");
  assert.equal(isDraftSlip({ salary_slip: null, docstatus: null }), false, "not generated");
  assert.equal(isDraftSlip({ docstatus: 0 }), false);
  assert.equal(isDraftSlip(undefined), false);
});

test("payroll: ?status=draft filters the rows and clearing it goes back to no params", () => {
  const rows = [
    { employee: "A", salary_slip: "SS-1", docstatus: 0 },
    { employee: "B", salary_slip: "SS-2", docstatus: 1 },
    { employee: "C", salary_slip: null, docstatus: null },
  ];
  assert.deepEqual(parsePayrollQuery({ status: "draft" }), { status: "draft" });
  assert.deepEqual(parsePayrollQuery({ status: "submitted" }), { status: "" });
  assert.deepEqual(parsePayrollQuery({}), { status: "" });
  assert.deepEqual(payrollQueryOf({ status: "draft" }), { status: "draft" });
  assert.deepEqual(payrollQueryOf({ status: "" }), {});
  assert.deepEqual(filterPayrollRows(rows, "draft").map((row) => row.employee), ["A"]);
  assert.equal(filterPayrollRows(rows, ""), rows);
  assert.deepEqual(filterPayrollRows(undefined, "draft"), []);
});

test("payroll page: period and the draft filter are bound to the address before the first request", () => {
  const source = read("Payroll.vue");
  assert.match(source, /bindRouteFilters\(\{ route: useRoute\(\), router: useRouter\(\), specs: \[periodRouteSpec\(\), \{/);
  assert.match(source, /keys: PAYROLL_QUERY_KEYS/);
  assert.match(source, /sources: \[statusFilter\]/);
  assert.ok(indexOf(source, "bindRouteFilters(") < indexOf(source, 'createResource({ url: api + "get_payroll_rows"'), "period must be read before the first fetch");
  // 页签「草稿」就是地址里的 ?status=draft：点它写进地址，别的页签清掉
  assert.match(source, /statusFilter\.value = key === "draft" \? "draft" : ""/);
  assert.match(source, /data-payroll-draft-only/);
  assert.match(source, /只看草稿工资条/);
  assert.match(source, /本期没有草稿工资条/);
  assert.match(source, /v-for="item in CHIPS"/);
});

// ---------- 只带期间的页面 ----------
test("social insurance, housing fund and allocation read ?period before their first request", () => {
  // 社保页和公积金页都是 ContributionWorkbench 的壳，期间在共用的工作台里读
  const workbench = readFileSync(new URL("../src/components/contribution/ContributionWorkbench.vue", import.meta.url), "utf8");
  assert.match(workbench, /usePeriodFromRoute\(useRoute\(\), useRouter\(\)\)/);
  assert.ok(indexOf(workbench, "usePeriodFromRoute(") < indexOf(workbench, "const workbench = createResource"));
  assert.match(read("SocialInsurance.vue"), /<ContributionWorkbench kind="si" \/>/);
  assert.match(read("HousingFund.vue"), /<ContributionWorkbench kind="fund" \/>/);

  const allocation = read("Allocation.vue");
  assert.match(allocation, /usePeriodFromRoute\(useRoute\(\), useRouter\(\)\)/);
  assert.ok(indexOf(allocation, "usePeriodFromRoute(") < allocation.lastIndexOf("\nload();"));
});

// ---------- 分摊汇总：project 定位 ----------
test("allocation dashboard: ?period and ?project are bound, the project is highlighted rather than filtered", () => {
  const source = read("AllocationDashboard.vue");
  assert.match(source, /specs: \[periodRouteSpec\(\), \{\s*keys: \["project"\]/);
  assert.match(source, /sources: \[projectFocus\]/);
  assert.ok(indexOf(source, "bindRouteFilters(") < source.lastIndexOf("\nload();"), "period must be read before the first load()");
  // 项目编号（project_code）或记录名都认
  assert.match(source, /project\?\.project_code === wanted \|\| project\?\.project === wanted/);
  // 高亮：汇总表的列头 / 单元格、各项目承担的行
  assert.match(source, /:class="\{ focus: isFocusedProject\(project\) \}"/);
  assert.match(source, /zero: !projectValue\(row, project\), focus: isFocusedProject\(project\)/);
  assert.match(source, /:class="\{ focus: isFocusedRank\(item\) \}"/);
  assert.match(source, /\.rd \.matrix th\.focus, \.rd \.matrix td\.focus/);
  // 可见的提示和清除；找不到项目时也要说明
  assert.match(source, /data-project-focus/);
  assert.match(source, /data-project-clear @click="projectFocus = ''"/);
  assert.match(source, /当前范围里没有项目/);
  // 没有过滤数据：合计仍然是全部项目，所以汇总表仍然遍历所有项目列
  assert.match(source, /v-for="project in projectColumns"/);
});

// ---------- 宿舍 ----------
test("accommodation monthly: ?period and ?status=open are bound; the board API supplies occupied-but-unregistered rooms", () => {
  const source = read("Accommodation.vue");
  assert.match(source, /specs: \[periodRouteSpec\(\), \{\s*keys: \["status"\]/);
  assert.match(source, /queryText\(query, "status"\) === "open"/);
  assert.ok(indexOf(source, "bindRouteFilters(") < indexOf(source, "const options = createResource"), "period must be read before the data requests");
  // 房间是否在住 / 是否已登记，用宿舍看板同一个接口（与看板「未登记」提醒同口径）
  assert.match(source, /rayher_hr_payroll\.api\.dormitory_board\.get_dormitory_board/);
  // 口径只有一份，在 lib 里（与后端 alert.dorm_register 同口径）；页面和"保存并登记下一间"都用它
  assert.match(source, /unregisteredRooms\(board\.data\?\.rooms\)/);
  assert.match(read("../lib/accommodationFees.js"), /room\?\.status === '入住' && !room\?\.registered/);
  assert.match(source, /watch\(statusFilter, \(value\) => \{ if \(value === "open"\) board\.reload\(\); \}\)/);
  assert.match(source, /data-open-rooms/);
  assert.match(source, /data-open-clear @click="statusFilter = ''"/);
  // 原来的 room= 仍然有效：现在由地址解析（旧链接 ?room=A-302 当作 view=edit）进入该房间的内页
  assert.match(source, /parseFeeLocation\(route\.query\)/);
  assert.match(source, /route\.query\.room/);
});

test("accommodation master: ?lease=expiring and ?leaver=1 are bound; the leaver filter uses employee_left", () => {
  const source = read("AccommodationMaster.vue");
  assert.match(source, /keys: \['lease', 'leaver'\]/);
  assert.match(source, /queryText\(query, 'lease'\) === 'expiring'/);
  assert.match(source, /queryText\(query, 'leaver'\) === '1'/);
  assert.match(source, /\(!filters\.lease \|\| leaseSoon\(row\)\) && \(!filters\.leaver \|\| row\.employee_left\)/);
  assert.match(source, /data-leaver-filter/);
  assert.match(source, /@click="filters\.leaver = false">显示全部房间/);
  assert.match(source, /@click="filters\.lease = false">显示全部房间/);
});

// ---------- 与后端目标表对齐 ----------
// 每个路径上，目标表里出现过的参数名（固定参数 + 可选参数）页面都必须会读。
const READ_BY_PAGE = {
  "/personnel": ["status", "reminder", "rd", "group", "archive", "joined", "dept"],
  "/payroll": ["period", ...PAYROLL_QUERY_KEYS],
  "/social-insurance": ["period"],
  "/housing-fund": ["period"],
  "/allocation": ["period"],
  "/allocation-dashboard": ["period", "project"],
  "/accommodation/master": ["lease", "leaver", "room"],
  "/accommodation/monthly": ["period", "status", "room"],
};

test("every dashboard target on an A-group page only uses params that page reads", () => {
  const seen = new Set();
  for (const [key, target] of Object.entries(targets)) {
    const known = READ_BY_PAGE[target.path];
    if (!known) continue;
    seen.add(target.path);
    for (const name of [...Object.keys(target.query || {}), ...(target.params || [])]) {
      assert.ok(known.includes(name), `${key} (${target.path}): ${name} is not read by the page`);
    }
  }
  for (const path of ["/personnel", "/payroll", "/social-insurance", "/housing-fund", "/allocation", "/allocation-dashboard", "/accommodation/master", "/accommodation/monthly"]) {
    assert.ok(seen.has(path), `targets.json has no target for ${path}`);
  }
});

test("payroll / dorm fixed values are the ones the pages understand", () => {
  assert.equal(targets["payroll"].params.includes("status"), true);
  assert.equal(parsePayrollQuery({ status: "draft" }).status, "draft");
  assert.deepEqual(targets["dorm.lease"].query, { lease: "expiring" });
  assert.deepEqual(targets["dorm.leaver"].query, { leaver: "1" });
  assert.equal(targets["dorm.monthly"].params.includes("status"), true);
  assert.equal(targets["cost.summary"].params.includes("project"), true);
});
