import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/Allocation.vue", import.meta.url), "utf8");

test("allocation page can cancel the current submitted allocation with an inline confirmation", () => {
  assert.match(source, /rayher_hr_payroll\.api\.allocation_entry\.cancel_allocation/);
  assert.match(source, /const canceling = ref\(false\)/);
  assert.ok(source.includes("cancelAllocation"));
  assert.ok(source.includes("confirmCancel"));
  assert.match(source, /cancelRes\.submit\(\{ period: period\.value \}\)/);
  assert.match(source, /await load\(\)/);
  // 不再用 window.confirm，改成「确认撤销 / 返回」的行内确认
  assert.doesNotMatch(source, /window\.confirm/);
  assert.match(source, /const confirmingCancel = ref\(false\)/);
  assert.ok(source.includes("确认撤销"));
  assert.ok(source.includes("返回"));
  // 只有月度、且已有分摊单时才出现撤销按钮
  assert.match(source, /v-if="allocName && !isYearScope"/);
});

test("allocation page recalculates only in month scope", () => {
  assert.match(source, /rayher_hr_payroll\.api\.allocation_entry\.recalc_allocation/);
  assert.match(source, /if \(isYearScope\.value\) return/);
  assert.match(source, /:disabled="isYearScope \|\| recalcing/);
});

test("allocation page supports month and year views with four top totals", () => {
  assert.match(source, /periodScope/);
  assert.match(source, /scope: periodScope\.value/);
  assert.match(source, /PERIOD_SCOPES/);
  assert.match(source, /capitalExpense/);
  assert.match(source, /capitalized/);
  assert.match(source, /expensed/);
  assert.match(source, /unknown/);
  assert.match(source, /hasAllocationData\(a\)/);
  assert.match(source, /buildAllocationMatrixFilters/);
  assert.match(source, /allocationEmptyState/);
  assert.match(source, /if \(!summary\.value\) return/);
  assert.match(source, /allocName \|\| displayPeriod/);
  assert.match(source, /loadAllocationStageMatrices/);
  assert.match(source, /const exportMatrixRes = createResource/);
  assert.match(source, /stageMatrices = await loadAllocationStageMatrices/);
  assert.match(source, /stageMatrices,/);
  // 未判定大于 0 时卡片用「需处理」色调
  assert.match(source, /tone: unknown > 0 \? "warn" : ""/);
});

test("allocation ledger uses the shared summary capitalized and expensed views", () => {
  assert.ok(source.includes('title: "研发费用台账"'));
  assert.match(source, /const modeOptions =/);
  assert.ok(source.includes('{ value: "all", label: "汇总" }'));
  assert.ok(source.includes('{ value: "capitalized", label: "资本化" }'));
  assert.ok(source.includes('{ value: "expensed", label: "费用化" }'));
  assert.match(source, /const allocationMode = ref\("all"\)/);
  assert.match(source, /stage: allocationMode\.value/);
  assert.match(source, /watch\(allocationMode, \(\) => loadMatrix\(\)\)/);
  assert.match(source, /v-model="allocationMode"/);
  assert.match(source, /:options="modeOptions"/);
});

test("allocation page uses the shared R&D page shell and groups the toolbar into view and actions", () => {
  assert.match(source, /<RdPage /);
  assert.match(source, /<RdPeriod \/>/);
  assert.match(source, /<RdSeg /);
  assert.match(source, /<RdKpi /);
  assert.ok(source.includes('view: "查看"'));
  assert.ok(source.includes('actions: "操作"'));
  assert.match(source, /allocationReconcileDifference/);
  assert.ok(source.includes("分摊合计与费用池差额"));
});

test("allocation page has no status-and-reconcile card; status is a tag by the title and reconcile sits in the matrix header", () => {
  assert.ok(!source.includes("分摊状态与对账"));
  assert.doesNotMatch(source, /statusTitle/);
  assert.doesNotMatch(source, /const checks = computed/);
  assert.doesNotMatch(source, /class="chk"/);
  // 状态标签放在页头右侧
  assert.match(source, /<template #ctl>[\s\S]*statusTag\.text[\s\S]*<RdPeriod \/>/);
  assert.ok(source.includes('"年度 · 只读"'));
  assert.ok(source.includes('"已提交"'));
  assert.ok(source.includes('"未分摊"'));
  assert.ok(source.includes("年度汇总各月已提交的分摊，只读"));
  // 矩阵卡片头里的对账标签
  assert.ok(source.includes("已对账 · 差额 0.00"));
  assert.match(source, /差额 \{\{ fmt\(reconcileDiff\) \}\} 元/);
  // 差额异常条和未分摊条都带「重算分摊」按钮
  assert.match(source, /v-if="showDiffStrip" class="note warn strip" role="alert"/);
  assert.ok(source.includes("请核对后重算"));
  assert.ok(source.includes("本期尚未分摊，调整完工时后点「重算分摊」"));
  assert.match(source, /const showDiffStrip = computed\(\(\) => !loading\.value && !isYearScope\.value && reconcileOff\.value\)/);
  assert.match(source, /const showNotAllocated = computed\(\(\) => !loading\.value && !isYearScope\.value && !allocName\.value\)/);
  assert.equal((source.match(/@click="recalc"/g) || []).length, 3);
  // 未判定的重复检查行已去掉
  assert.ok(!source.includes("来自阶段未判定的项目"));
});

test("allocation page removes the middle project summary and keeps a bottom total row in the matrix", () => {
  assert.doesNotMatch(source, /projectSummaries/);
  assert.doesNotMatch(source, /project_summaries/);
  assert.match(source, /isTotalRow/);
  assert.match(source, /projectTotal/);
  assert.match(source, /result\.length/);
  assert.match(source, /matrixView\.totalRow/);
});

test("allocation matrix groups rows under collapsible level-3 account headers", () => {
  assert.match(source, /groupAllocationRows/);
  assert.match(source, /toggleGroup/);
  assert.match(source, /aria-expanded/);
  assert.match(source, /class="g"/);
  assert.match(source, /group\.totals\[colKey\(c\)\]/);
  assert.match(source, /stageLabel\(c\.project_stage\)/);
  assert.match(source, /:title="projectTitle\(c\)"/);
});

test("allocation page can export the current allocation workbook", () => {
  assert.match(source, /exportAllocationWorkbook/);
  assert.match(source, /const exporting = ref\(false\)/);
  assert.match(source, /const canExport = computed/);
  assert.match(source, /exportExcel/);
  assert.match(source, /!canExport/);
  assert.match(source, /summary: summary\.value/);
  assert.match(source, /allocationModeLabel\.value/);
});

test("allocation footer line uses Chinese separators and a Chinese row count", () => {
  assert.ok(source.includes("{{ totalRows }} 行明细"));
  assert.doesNotMatch(source, /\?\s*\{\{/);
  assert.doesNotMatch(source, /\}\}\s*\?/);
  assert.doesNotMatch(source, /totalRows \}\} rows/);
});

test("allocation total row label is rendered in the level-3 expense column", () => {
  assert.match(source, /key === "account_level_3"/);
  assert.doesNotMatch(source, /key === "expense_item_name"/);
});
