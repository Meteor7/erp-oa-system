// PR #79 审查修正（2026-10-13）：领导只读页面不显示写按钮、工资没保存不让确认、看板工资链接只看已确认、看板小修。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { dirtyRows, editSnapshot } from "../src/lib/payrollView.js";
import { filterPayrollRows, parsePayrollQuery, payrollQueryOf } from "../src/lib/payrollFilters.js";
import { resolveTabKey, tabAlias } from "../src/lib/dashboardView.js";

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");

// ---------------------------------------------------------------- 4. 改了还没保存
test("payroll dirty detection compares the editable inputs with the loaded snapshot", () => {
  const rows = [
    { employee: "E1", payment_days: 22, base_salary: 8000, salary_adjustment: 0, company_subsidy: 0, bonus: 0, other_adjustment: 0, income_tax: 0, advanced_paid: 0 },
    { employee: "E2", payment_days: 22, base_salary: 9000, income_tax: 120 },
  ];
  const snapshot = editSnapshot(rows);
  assert.deepEqual(dirtyRows(rows, snapshot), []);
  rows[0].base_salary = "8000";          // 输入框给的是字符串，数一样不算改
  rows[1].bonus = "";                    // 空当 0
  assert.deepEqual(dirtyRows(rows, snapshot), []);
  rows[1].income_tax = "150";
  assert.deepEqual(dirtyRows(rows, snapshot).map((row) => row.employee), ["E2"]);
  assert.deepEqual(dirtyRows([{ employee: "E9", income_tax: 5 }], snapshot), [], "加载时没有的人不算");
});

test("the payroll page blocks confirm while someone has unsaved edits", () => {
  const page = read("pages/Payroll.vue");
  assert.match(page, /watch\(\(\) => rows\.data, \(data\) => \{ baseline\.value = editSnapshot\(data\); \}/);
  assert.match(page, /data-payroll-confirm :disabled="!lockTargets\.length \|\| lock\.running \|\| dirty\.length > 0"/);
  assert.match(page, /有 \{\{ dirty\.length \}\} 人改了还没保存/);
  assert.match(page, /if \(dirty\.value\.length\) \{ lock\.asking = false; return; \}/);
  assert.match(read("components/payroll/PayrollDrawer.vue"), /data-payroll-row-dirty/);
});

// ---------------------------------------------------------------- 5. 只看已确认
test("the payroll page accepts status=submitted from the url", () => {
  assert.deepEqual(parsePayrollQuery({ status: "submitted" }), { status: "submitted" });
  assert.deepEqual(parsePayrollQuery({ status: "draft" }), { status: "draft" });
  assert.deepEqual(parsePayrollQuery({ status: "other" }), { status: "" });
  assert.deepEqual(payrollQueryOf({ status: "submitted" }), { status: "submitted" });
  assert.deepEqual(payrollQueryOf({ status: "" }), {});
  const rows = [{ salary_slip: "S1", docstatus: 1 }, { salary_slip: "S2", docstatus: 0 }, { salary_slip: null }];
  assert.deepEqual(filterPayrollRows(rows, "submitted"), [rows[0]]);
  const page = read("pages/Payroll.vue");
  assert.match(page, /const URL_CHIPS = \["draft", "submitted"\];/);
  assert.match(page, /<PayrollSummary :rows="summaryRows"/);
});

// ---------------------------------------------------------------- 3. 总经理、副总经理只读
test("accommodation rooms page does not load the HR-only employee list or show write buttons for leaders", () => {
  const page = read("pages/AccommodationMaster.vue");
  assert.match(page, /const canEdit = canEditHr\(\);/);
  assert.match(page, /get_emp_options',\n  method: 'GET',\n  auto: canEdit,/);
  assert.match(page, /<template v-if="canEdit" #actions><Button variant="solid" data-room-new/);
  assert.match(page, /<template v-if="canEdit"><router-link :to="editLocation\(row\)"/);
  assert.match(page, /const isList = computed\(\(\) => !canEdit \|\| state\.value === 'list'\);/);
});

test("dorm board hides edit-room and register-fee for leaders; tabs hide pages they cannot open", () => {
  const page = read("pages/AccommodationBoard.vue");
  assert.match(page, /<div v-if="canEdit" class="flex gap-2" data-board-actions>/);
  assert.match(page, /<button v-if="canEdit" type="button"[^>]*data-board-register/);
  assert.match(read("components/AccommodationTabs.vue"), /\.filter\(\(tab\) => canSee\(tab\.to\)\)/);
});

test("social insurance / housing fund workbench is read-only for leaders", () => {
  const page = read("components/contribution/ContributionWorkbench.vue");
  assert.match(page, /const canEdit = canEditHr\(\);/);
  assert.match(page, /<label v-if="canEdit" :class="\['cw-drop'/);
  assert.match(page, /<div v-if="canEdit" class="cw-foot"><span class="muted">\{\{ unmatchedHint \}\}/);
  assert.match(page, /v-if="canEdit && item\.status === 'Pending Activation'"/);
  assert.match(page, /<button v-if="canEdit" type="button" class="btn pri" data-cw-activate/);
  assert.match(page, /:readonly="!canEdit"/);
  const drawer = read("components/contribution/ContributionDrawer.vue");
  assert.match(drawer, /<button v-if="!readonly && !item\.resolved"/);
  const table = read("components/contribution/ContributionBaseTable.vue");
  assert.match(table, /<span v-if="!readonly" class="cw-chips">/);
  assert.equal((table.match(/:disabled="busy \|\| readonly"/g) || []).length, 2);
});

test("personnel write controls were already HR-only (import / new / edit / delete)", () => {
  const page = read("pages/Personnel.vue");
  assert.match(page, /<div v-if="canImport" ref="importWrap"/);
  assert.match(page, /<button v-if="canEdit" type="button" class="btn pri" data-new-emp/);
  assert.match(page, /<button v-if="canEdit&&!editing&&current"/);
  assert.match(page, /v-else-if="canDelete&&form\.name"/);
});

// ---------------------------------------------------------------- 6. 看板小修
test("old ?tab=rd lands on the business (cost) tab", () => {
  const tabs = [{ key: "overview" }, { key: "cost" }];
  assert.equal(resolveTabKey(tabs, "rd"), "cost");
  assert.equal(tabAlias("rd"), "cost");
  assert.equal(tabAlias("cost"), "");
  assert.equal(resolveTabKey([{ key: "rd" }, { key: "cost" }], "rd"), "rd", "真有 rd 页签时不换");
  assert.equal(resolveTabKey([{ key: "overview" }], "rd"), "overview");
  assert.match(read("pages/Dashboard.vue"), /if \(alias && key === alias\) router\.replace\(/);
});

test("todo / alert lists reset their expanded state per tab", () => {
  const page = read("pages/Dashboard.vue");
  assert.equal((page.match(/:key="`todos-\$\{activeKey\}`"/g) || []).length, 2);
  assert.equal((page.match(/:key="`alerts-\$\{activeKey\}`"/g) || []).length, 2);
  assert.match(read("components/dashboard/DashAlerts.vue"), /watch\(\(\) => props\.alerts, \(\) => \{ open\.value = false; \}\);/);
  assert.match(read("components/dashboard/DashTodos.vue"), /watch\(\(\) => props\.todos, \(\) => \{ open\.value = false; \}\);/);
});

test("no-data titles that cannot be opened get the greyed off style", () => {
  assert.match(read("components/dashboard/DashNoData.vue"), /:class="\{ 'is-off': \['denied', 'unknown'\]\.includes\(item\.link\.state\) \}"/);
  assert.match(read("styles/dashboardUi.css"), /\.db-nodata \.is-off \{/);
});
