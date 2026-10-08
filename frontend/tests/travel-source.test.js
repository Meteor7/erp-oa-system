import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const page = read("../src/pages/TravelRequest.vue");
const bench = read("../src/components/travel/TravelWorkbench.vue");
const table = read("../src/components/travel/TravelTable.vue");

test("the route page is a thin wrapper and keeps the old one's projects lookup out of the approval-center list", () => {
  assert.match(page, /import TravelWorkbench from '\.\.\/components\/travel\/TravelWorkbench\.vue'/);
  assert.match(page, /<TravelWorkbench \/>/);
  assert.doesNotMatch(page + bench, /list_approval_center_projects/);
});

test("every API call the old page made is still made", () => {
  assert.match(bench, /oa_entry\.list_requests/);
  assert.match(bench, /request_type: REQUEST_TYPE/);
  assert.match(bench, /const REQUEST_TYPE = '出差申请'/);
  assert.match(bench, /listFor\('mine'\)/);
  assert.match(bench, /expense_claim_entry\.list_claim_projects/);
  assert.match(bench, /travel_entry\.save_travel_draft/);
  assert.match(bench, /oa_entry\.submit_request/);
  assert.match(bench, /oa_entry\.withdraw_request/);
  assert.match(bench, /oa_entry\.action_request/);
  assert.match(bench, /approveArgs\(/);
  assert.match(bench, /isStaleError\(error\)/);
});

test("approvers get their own 待我审批 entry through list_requests view=pending", () => {
  assert.match(bench, /listFor\('pending'\)/);
  assert.match(bench, /待我审批/);
  assert.match(bench, /scope: 'todo'/);
  assert.match(bench, /看详情/);
});

test("home, list, detail and new are selected by query like the claim pages", () => {
  assert.match(bench, /travelView\(route\.query\)/);
  assert.match(bench, /v-if="view === 'home'"/);
  assert.match(bench, /view === 'list'/);
  assert.match(bench, /view === 'detail'/);
  assert.match(bench, /view: 'new'/);
  assert.match(bench, /draft: doc\.name/);
});

test("form: all fields, auto days, project select, and a 还差 list instead of live red blockers", () => {
  for (const field of ["subject", "travel_destination", "travel_start_date", "travel_end_date", "reason", "project"]) assert.match(bench, new RegExp(`form\\.${field}`));
  assert.match(bench, /tripDays\(form\.travel_start_date, form\.travel_end_date\)/);
  assert.match(bench, /还差/);
  assert.match(bench, /都填好了/);
  assert.match(bench, /missingVisible/);
  assert.match(bench, /保存草稿/);
  assert.match(bench, /提交审批/);
  assert.match(bench, /继续编辑/);
  assert.match(bench, /直属主管/);
  assert.match(bench, /副总经理/);
});

test("withdraw and reject collect the reason inline; push buttons go to claim and payment with ?source=", () => {
  assert.doesNotMatch(bench + table, /window\.prompt|window\.confirm/);
  assert.match(bench, /驳回原因/);
  assert.match(bench, /请填写驳回原因|rejectProblem/);
  assert.match(bench, /撤回原因（可选）/);
  assert.match(table, /撤回原因/);
  assert.match(table, /下推报销/);
  assert.match(table, /下推付款/);
  assert.match(bench, /pushTarget\(kind\)/);
  // from 让目标页取消时回到这里；目标页（ClaimWorkbench）会先弹出"确定要创建草稿吗"再生成
  assert.match(bench, /query: \{ source: row\.name, from: hereAsFrom\(route\.path, route\.query\) \}/);
});

test("detail shows the approval timeline instead of chips", () => {
  assert.match(bench, /travelTimeline\(/);
  assert.match(bench, /class="tl"|:class="\['tl'/);
  assert.doesNotMatch(bench, /stepChips/);
  assert.doesNotMatch(bench + table, /class="steps"/);
});

test("no hard-coded person names", () => {
  for (const name of ["刘伟", "演示员工21", "周航", "刘洋"]) assert.doesNotMatch(bench + table, new RegExp(name));
});
