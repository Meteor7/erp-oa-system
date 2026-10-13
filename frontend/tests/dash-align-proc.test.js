// 看板数字和点进去看到的对齐（采购 / PMC / 生产主管 / 项目负责人，2026-10-13 审查 F1–F17）：页面这一侧。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { STAGE_GROUPS, filterRows, normalizeStage, stageFilterLabel, stageMatches } from "../src/lib/procurementView.js";
import { PR_CLOSED_STATUSES, amountText, availableLineCount, money, pendingLineCount, poHeaderDiffers, poLineTotal } from "../src/lib/priceView.js";
import { amountText as payAmountText, buildPoGroups } from "../src/lib/paymentView.js";
import { buildTargetTable, mergeQuery } from "../src/lib/dashboardTargets.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const targets = buildTargetTable(JSON.parse(read("../../rayher_hr_payroll/dashboard/targets.json")));

// ---------------------------------------------------------------- 目标参数（targets.json 的增补见 SHARED_CHANGES.md）
test("the dashboard can pass the filters the destination pages now read", () => {
  assert.deepEqual(mergeQuery(targets["material.progress"], { uncoded: "1", status: "采购确认中", project: "RD03" }), { uncoded: "1", status: "采购确认中", project: "RD03" });
  assert.deepEqual(mergeQuery(targets["material.overdue"], { project: "RD03" }), { overdue: "1", project: "RD03" });
  assert.deepEqual(mergeQuery(targets["price.approvals"], { view: "approvals", status: "pending" }), { view: "approvals", status: "pending" });
  assert.deepEqual(mergeQuery(targets["procurement.list"], { scope: "owned", project: "RD02", stage: "live" }), { view: "list", scope: "owned", project: "RD02", stage: "live" });
});

// ---------------------------------------------------------------- F5 / F7 采购申请列表：项目筛选、有进度的阶段
test("F7 the live stage group is demand + execution + closed, never drafts or withdrawn ones", () => {
  assert.deepEqual([...STAGE_GROUPS.live], ["demand", "await_pr", "quote", "price", "po", "closed"]);
  assert.equal(normalizeStage("live"), "live");
  assert.match(stageFilterLabel("live"), /有进度/);
  const row = (workflow, extra = {}) => ({ request_type: "采购申请", workflow_status: workflow, business_status: "", ...extra });
  assert.equal(stageMatches(row("待审批"), "live"), true);
  assert.equal(stageMatches(row("已完成", { procurement_chain: { stage: "closed" } }), "live"), true);
  assert.equal(stageMatches(row("已完成", { business_status: "已关闭" }), "live"), true);
  assert.equal(stageMatches(row("已拒绝"), "live"), false);
  assert.equal(stageMatches(row("已撤回"), "live"), false);
  assert.equal(stageMatches(row("草稿"), "live"), false);
  assert.equal(stageMatches(row("已取消"), "live"), false);
});

test("F5 the list filters by the project the dashboard row points at", () => {
  const rows = [
    { name: "A", project: "RD02", workflow_status: "待审批" },
    { name: "B", project: "RD03", workflow_status: "待审批" },
    { name: "C", project: "RD02", workflow_status: "已拒绝" },
  ];
  assert.deepEqual(filterRows(rows, { project: "RD02", stage: "live" }).map((row) => row.name), ["A"]);
  const list = read("../src/components/procurement/ProcList.vue");
  assert.match(list, /project: String\(route\.query\.project \|\| ''\)/);
  assert.match(list, /cleanQuery\(\{ stage: filters\.stage, q: filters\.text, project: filters\.project \}\)/);
  assert.match(list, /清除项目筛选/);
});

// ---------------------------------------------------------------- F2 / F10 / F11 物料进度页读看板带来的筛选
test("F2/F10/F11 the material board passes overdue, uncoded and project to the server", () => {
  const page = read("../src/pages/MaterialProgress.vue");
  assert.match(page, /const status = ref\(String\(route\.query\.status \|\| ''\)\)/);
  assert.match(page, /const uncodedOnly = ref\(String\(route\.query\.uncoded \|\| ''\) === '1'\)/);
  assert.match(page, /const projectOnly = ref\(String\(route\.query\.project \|\| ''\)\)/);
  assert.match(page, /source_request: sourceRequest\.value, \.\.\.boardFilters\(\) \}\)/);
  // 逾期在服务端筛（按服务器的今天），条数取接口给的 total
  assert.match(page, /offset: sweepOffset\.value, source_request: sourceRequest\.value, overdue: 1, \.\.\.boardFilters\(\)/);
  assert.match(page, /overdueTotal\.value = Number\(sweeper\.data\?\.total \|\| 0\)/);
  assert.match(page, /data-testid="uncoded-filter"/);
  assert.match(page, /data-testid="project-filter"/);
  assert.match(page, /clearBoardFilter\('uncoded'\)/);
});

// ---------------------------------------------------------------- F9 价格审批列表读 ?status=
test("F9 the price approval list starts with the filter the dashboard asked for", () => {
  const list = read("../src/components/price/PriceApprovalList.vue");
  assert.match(list, /APPROVAL_FILTERS\.some\(\(item\) => item\.key === query\.status\)/);
  assert.match(list, /const filter = ref\(presetFilter\(route\.query\)\)/);
});

// ---------------------------------------------------------------- F3 PO 金额 = 物料行金额合计
test("F3 a PO amount is the sum of its lines and a differing header total is shown aside", () => {
  const po = { total_amount: 100, lines: [{ amount: 60 }, { amount: 40.5 }] };
  assert.equal(poLineTotal(po), 100.5);
  assert.equal(poHeaderDiffers(po), true);
  assert.equal(poHeaderDiffers({ total_amount: 100, lines: [{ amount: 100 }] }), false);
  assert.equal(poHeaderDiffers({ total_amount: 100, lines: [] }), false);
  const list = read("../src/components/price/PoList.vue");
  assert.match(list, /amountText\(poLineTotal\(po\), po\.amounts_hidden\)/);
  assert.match(list, /data-testid="po-header-total"/);
  assert.match(read("../src/components/price/PoDetail.vue"), /cash\(poLineTotal\(po\)\)/);
});

// ---------------------------------------------------------------- F12 PMC / 生产主管看不到金额
test("F12 hidden amounts read as a dash, not as zero", () => {
  assert.equal(amountText(1234.5), money(1234.5));
  assert.equal(amountText(null, true), "—");
  assert.equal(payAmountText(10, "CNY", true), "—");
  assert.equal(payAmountText(10, "CNY"), "¥ 10.00");
  const groups = buildPoGroups([{ po: "PO-1", amount: null, paid_amount: null, amounts_hidden: 1, lines: [{ amount: null, quantity: 1 }] }]);
  assert.equal(groups[0].amounts_hidden, true);
  assert.equal(buildPoGroups([{ po: "PO-2", amount: 5, lines: [] }])[0].amounts_hidden, false);
  const pages = ["../src/components/price/PoDetail.vue", "../src/components/price/PriceMatrix.vue"].map(read);
  for (const page of pages) {
    assert.doesNotMatch(page.split("</script>")[1], /\bmoney\(/);
    assert.match(page, /amountText\(value, props\.(po|approval)\.amounts_hidden\)/);
  }
  assert.match(read("../src/components/payment/PayInstallmentCard.vue"), /amountText\(view\.amount, currency, hidden\)/);
  assert.match(read("../src/components/payment/PayWorkTab.vue"), /:hidden="active\.amounts_hidden"/);
  assert.match(read("../src/components/payment/PayFulfilmentPanel.vue"), /v-if="!group\.amounts_hidden"/);
  assert.match(read("../src/components/price/PriceApprovalList.vue"), /amountText\(item\.total_amount, item\.amounts_hidden\)/);
});

// ---------------------------------------------------------------- F17 待比价：不能再生成价格审批单的 PR 不算
test("F17 closed, draft and cancelled PRs have nothing left to compare", () => {
  assert.deepEqual([...PR_CLOSED_STATUSES], ["草稿", "Draft", "已取消", "已关闭"]);
  const line = { remaining_quantity: 2 };
  assert.equal(availableLineCount({ status: "待采购", lines: [line] }), 1);
  for (const status of PR_CLOSED_STATUSES) assert.equal(availableLineCount({ status, lines: [line] }), 0, status);
  assert.equal(pendingLineCount([{ status: "已关闭", lines: [line] }, { status: "待采购", lines: [line, line] }]), 2);
});
