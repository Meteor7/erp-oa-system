import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/Allocation.vue", import.meta.url), "utf8");

test("allocation page can cancel the current submitted allocation", () => {
  assert.match(source, /rayher_hr_payroll\.api\.allocation_entry\.cancel_allocation/);
  assert.match(source, /const canceling = ref\(false\)/);
  assert.ok(source.includes("cancelAllocation"));
  assert.ok(source.includes("confirmCancel"));
  assert.match(source, /cancelRes\.submit\(\{ period: period\.value \}\)/);
  assert.match(source, /await load\(\)/);
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
});

test("allocation ledger uses the shared summary capitalized and expensed views", () => {
  assert.ok(source.includes("title: \"\\u7814\\u53d1\\u8d39\\u7528\\u53f0\\u8d26\""));
  assert.match(source, /const modeOptions =/);
  assert.ok(source.includes('{ value: "all", label: "\\u6c47\\u603b" }'));
  assert.ok(source.includes('{ value: "capitalized", label: "\\u8d44\\u672c\\u5316" }'));
  assert.ok(source.includes('{ value: "expensed", label: "\\u8d39\\u7528\\u5316" }'));
  assert.match(source, /const allocationMode = ref\("all"\)/);
  assert.match(source, /stage: allocationMode\.value/);
  assert.match(source, /watch\(allocationMode, \(\) => loadMatrix\(\)\)/);
  assert.match(source, /v-for="option in modeOptions"/);
});

test("allocation page removes the middle project summary and keeps a bottom total row in the matrix", () => {
  assert.doesNotMatch(source, /projectSummaries/);
  assert.doesNotMatch(source, /project_summaries/);
  assert.match(source, /isTotalRow/);
  assert.match(source, /projectTotal/);
  assert.match(source, /result\.length/);
});

test("allocation page can export the current allocation workbook", () => {
  assert.match(source, /exportAllocationWorkbook/);
  assert.match(source, /const exporting = ref\(false\)/);
  assert.match(source, /const canExport = computed/);
  assert.match(source, /exportExcel/);
  assert.match(source, /:disabled="!canExport"/);
  assert.match(source, /summary: summary\.value/);
  assert.match(source, /allocationModeLabel\.value/);
});


test("allocation total row label is rendered in the level-3 expense column", () => {
  assert.match(source, /key === "account_level_3"/);
  assert.doesNotMatch(source, /key === "expense_item_name"/);
});
