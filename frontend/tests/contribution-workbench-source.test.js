import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (name) => readFileSync(new URL(`../src/components/contribution/${name}`, import.meta.url), "utf8");
const workbench = read("ContributionWorkbench.vue");
const drawer = read("ContributionDrawer.vue");
const table = read("ContributionBaseTable.vue");

test("a pending row can only be settled with an audited decision and a reason", () => {
  assert.match(drawer, /emit\('confirm'/);
  assert.match(drawer, /emit\('ignore'/);
  assert.match(drawer, /备注（必填/);
  assert.match(drawer, /Boolean\(note\.value\.trim\(\)\)/);
  assert.match(workbench, /createResource\(\{ url: cfg\.fn\.confirm \}\)/);
  assert.match(workbench, /createResource\(\{ url: cfg\.fn\.ignore \}\)/);
});

test("a pending batch can be cancelled only with a reason, and goes live only when nothing blocks it", () => {
  assert.match(workbench, /取消批次前必须填写原因/);
  assert.match(workbench, /cfg\.fn\.cancel/);
  assert.match(workbench, /blockers\.value\.length/);
  assert.match(workbench, /确认\{\{ cfg\.name \}\}生效/);
  assert.match(workbench, /activationBlockers\(/);
});

test("changing a base or household re-runs the check on the pending batch", () => {
  assert.match(workbench, /async function afterBaseChange\(\)/);
  assert.match(workbench, /reconciler\.submit\(\{ batch: batch\.value\.name \}\)/);
  assert.match(workbench, /baseSaver\.submit\(\{ kind: props\.kind/);
  assert.match(workbench, /householdSaver\.submit\(payload\)/);
});

test("the period is read from the address before the first request", () => {
  assert.ok(workbench.indexOf("usePeriodFromRoute(useRoute(), useRouter())") >= 0);
  assert.ok(workbench.indexOf("usePeriodFromRoute(") < workbench.indexOf("const workbench = createResource"));
});

test("the four steps and the payroll readiness are on the page", () => {
  assert.match(workbench, /STEPS/);
  assert.match(workbench, /第一步：导入本月/);
  assert.match(workbench, /第二步：核对差异/);
  assert.match(workbench, /第四步：确认/);
  assert.match(workbench, /薪酬就绪情况/);
  assert.match(workbench, /get_payroll_readiness/);
  assert.match(table, /第三步：/);
});

test("the base table edits the archive base, and only the social page shows the household", () => {
  assert.match(table, /emit\('base'/);
  assert.match(table, /emit\('household'/);
  assert.match(table, /v-if="kind === 'si'"/);
  assert.match(table, /缺基数的按上月带入/);
});

test("both audited states are listed under 已处理, including ignored rows", () => {
  assert.match(workbench, /data\.value\.handled/);
});
