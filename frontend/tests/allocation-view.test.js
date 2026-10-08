import assert from "node:assert/strict";
import test from "node:test";
import * as allocationView from "../src/lib/allocationView.js";

const {
  allocationActionState,
  allocationEmptyState,
  allocationStatusTag,
  allocationViewState,
  buildAllocationMatrixFilters,
  buildFinalizeCheckLines,
  finalizeCheckIssueCount,
  hasAllocationData,
  previewWarningTexts,
} = allocationView;

test("foreign-only payload remains visible without a domestic allocation name", () => {
  assert.equal(hasAllocationData({
    name: null,
    has_data: true,
    has_domestic_data: false,
    has_foreign_data: true,
  }), true);
});

test("empty payload remains hidden", () => {
  assert.equal(hasAllocationData({
    name: null,
    has_data: false,
    has_domestic_data: false,
    has_foreign_data: false,
  }), false);
});

test("foreign-only month matrix uses exact year and month", () => {
  assert.deepEqual(buildAllocationMatrixFilters({
    scope: "month",
    period: "2026-06",
    allocation: null,
    stage: "all",
  }), { year: 2026, month: 6, stage: "all" });
});

test("domestic month matrix uses only allocation name", () => {
  assert.deepEqual(buildAllocationMatrixFilters({
    scope: "month",
    period: "2026-06",
    allocation: "ALLOC-1",
    stage: "capitalized",
  }), { allocation: "ALLOC-1", stage: "capitalized" });
});

test("year matrix does not include a month or allocation", () => {
  assert.deepEqual(buildAllocationMatrixFilters({
    scope: "year",
    period: "2026-06",
    allocation: "ALLOC-1",
    stage: "all",
  }), { year: 2026, stage: "all" });
});

test("preview month matrix adds preview: 1 and never an allocation name", () => {
  assert.deepEqual(buildAllocationMatrixFilters({
    scope: "month",
    period: "2026-06",
    allocation: null,
    stage: "expensed",
    preview: true,
  }), { year: 2026, month: 6, stage: "expensed", preview: 1 });
  assert.deepEqual(buildAllocationMatrixFilters({
    scope: "month",
    period: "2026-06",
    allocation: "ALLOC-1",
    stage: "all",
    preview: true,
  }), { year: 2026, month: 6, stage: "all", preview: 1 });
  // 年度和已定版都不带 preview
  assert.deepEqual(buildAllocationMatrixFilters({ scope: "year", period: "2026-06", stage: "all", preview: true }), { year: 2026, stage: "all" });
  assert.equal("preview" in buildAllocationMatrixFilters({ scope: "month", period: "2026-06", allocation: "A", stage: "all", preview: false }), false);
});

test("empty state distinguishes no business data from no matrix detail", () => {
  assert.equal(allocationEmptyState({ hasData: false, mode: "all" }), "no-data");
  assert.equal(allocationEmptyState({ hasData: true, mode: "all" }), "no-detail");
  assert.equal(allocationEmptyState({ hasData: true, mode: "capitalized" }), "no-detail-for-mode");
  assert.equal(allocationEmptyState({ hasData: true, mode: "expensed" }), "no-detail-for-mode");
});

test("export loader requests independent all capitalized and expensed matrices", async () => {
  assert.equal(typeof allocationView.loadAllocationStageMatrices, "function");
  const calls = [];
  const stageMatrices = await allocationView.loadAllocationStageMatrices({
    scope: "year",
    period: "2026-06",
    allocation: null,
    load: async (filters) => {
      calls.push(filters);
      return {
        columns: [{ fieldname: `project_${filters.stage}` }],
        result: [{ stage: filters.stage }],
      };
    },
  });

  assert.deepEqual(calls, [
    { year: 2026, stage: "all" },
    { year: 2026, stage: "capitalized" },
    { year: 2026, stage: "expensed" },
  ]);
  assert.deepEqual(stageMatrices.expensed, {
    columns: [{ fieldname: "project_expensed" }],
    result: [{ stage: "expensed" }],
  });
});

test("export loader passes preview through to every stage request", async () => {
  const calls = [];
  await allocationView.loadAllocationStageMatrices({
    scope: "month",
    period: "2026-06",
    allocation: null,
    preview: true,
    load: async (filters) => { calls.push(filters); return { columns: [], result: [] }; },
  });
  assert.deepEqual(calls, [
    { year: 2026, month: 6, stage: "all", preview: 1 },
    { year: 2026, month: 6, stage: "capitalized", preview: 1 },
    { year: 2026, month: 6, stage: "expensed", preview: 1 },
  ]);
});

test("view state: year, finalized, preview, preview error and empty", () => {
  assert.equal(allocationViewState({ payload: { has_data: true, finalized: true }, scope: "year" }), "year");
  assert.equal(allocationViewState({ payload: null, scope: "year" }), "year");
  assert.equal(allocationViewState({ payload: null, scope: "month" }), "empty");
  assert.equal(allocationViewState({ payload: { name: "ALLOC-1", finalized: true, preview: false, has_data: true }, scope: "month" }), "finalized");
  // 只有境外的月份：没有分摊单名，但 finalized 为真
  assert.equal(allocationViewState({ payload: { name: null, finalized: true, has_data: true }, scope: "month" }), "finalized");
  assert.equal(allocationViewState({ payload: { name: null, preview: true, finalized: false, has_data: true }, scope: "month" }), "preview");
  assert.equal(allocationViewState({ payload: { preview: true, preview_error: "缺少费用科目", has_data: false }, scope: "month" }), "preview-error");
  assert.equal(allocationViewState({ payload: { preview: true, preview_error: "缺少费用科目", has_data: true }, scope: "month" }), "preview-error");
  assert.equal(allocationViewState({ payload: { preview: true, preview_error: "", has_data: true }, scope: "month" }), "preview");
  // 既不是预览也没定版、也没有数据：显示空状态
  assert.equal(allocationViewState({ payload: { preview: false, finalized: false, has_data: false }, scope: "month" }), "empty");
  assert.equal(allocationViewState({ payload: { preview: true, finalized: false, has_data: false }, scope: "month" }), "empty");
});

test("status tag per state", () => {
  assert.deepEqual(allocationStatusTag("finalized"), { text: "已定版", cls: "ok" });
  assert.deepEqual(allocationStatusTag("preview"), { text: "预览 · 未定版", cls: "warn" });
  assert.deepEqual(allocationStatusTag("preview-error"), { text: "预览 · 未定版", cls: "warn" });
  assert.deepEqual(allocationStatusTag("year"), { text: "年度 · 只读", cls: "" });
  assert.equal(allocationStatusTag("empty"), null);
});

test("action buttons: only the finance manager (can_finalize) can finalize or cancel the finalize", () => {
  const ok = allocationActionState({ state: "preview", payload: { can_finalize: true } });
  assert.equal(ok.showFinalize, true);
  assert.equal(ok.finalizeDisabled, false);
  assert.equal(ok.finalizeTitle, undefined);
  assert.equal(ok.showCancel, false);

  const denied = allocationActionState({ state: "preview", payload: { can_finalize: false } });
  assert.equal(denied.showFinalize, true);
  assert.equal(denied.finalizeDisabled, true);
  assert.equal(denied.finalizeTitle, "只有财务主管可以定版");

  const errored = allocationActionState({ state: "preview-error", payload: { can_finalize: true, preview_error: "x" } });
  assert.equal(errored.showFinalize, true);
  assert.equal(errored.finalizeDisabled, true);
  assert.equal(errored.finalizeTitle, "预览算不出来，暂时不能定版");

  const cancelOk = allocationActionState({ state: "finalized", payload: { can_finalize: true } });
  assert.equal(cancelOk.showFinalize, false);
  assert.equal(cancelOk.showCancel, true);
  assert.equal(cancelOk.cancelDisabled, false);
  const cancelDenied = allocationActionState({ state: "finalized", payload: { can_finalize: false } });
  assert.equal(cancelDenied.showCancel, true);
  assert.equal(cancelDenied.cancelDisabled, true);
  assert.equal(cancelDenied.cancelTitle, "只有财务主管可以撤销定版");

  for (const state of ["year", "empty"]) {
    const s = allocationActionState({ state, payload: { can_finalize: true } });
    assert.equal(s.showFinalize, false);
    assert.equal(s.showCancel, false);
  }
  assert.equal(allocationActionState({ state: "preview", payload: null }).finalizeDisabled, true);
});

test("finalize check lines: amber when above zero, ok when zero", () => {
  const lines = buildFinalizeCheckLines({
    period: "2026-06",
    can_finalize: true,
    underfilled_people: 3,
    unfilled_people: 2,
    over_limit_people: 0,
    unknown_amount: 1234.5,
    unallocated_foreign_common_amount: 0,
    reconcile_diff: 0,
    warnings: ["有 1 个项目没有阶段"],
  });
  const byKey = Object.fromEntries(lines.map((l) => [l.key, l]));
  assert.equal(byKey.underfilled.text, "还有 3 人工时未填满");
  assert.equal(byKey.underfilled.tone, "warn");
  assert.equal(byKey.unfilled.text, "2 人未填工时");
  assert.equal(byKey.unfilled.tone, "warn");
  assert.equal(byKey["over-limit"].tone, "ok");
  assert.equal(byKey["over-limit"].text, "没有人工时超上限");
  assert.equal(byKey.unknown.text, "未判定金额 1,234.50 元");
  assert.equal(byKey.unknown.tone, "warn");
  assert.equal(byKey["foreign-common"].text, "没有境外工时可分的境外公共费用 0.00 元");
  assert.equal(byKey["foreign-common"].tone, "ok");
  assert.equal(byKey.diff.text, "差额 0.00 元");
  assert.equal(byKey.diff.tone, "ok");
  assert.equal(byKey["warning-0"].text, "有 1 个项目没有阶段");
  assert.equal(byKey["warning-0"].tone, "warn");
  assert.equal(finalizeCheckIssueCount(lines), 4);
});

test("finalize check lines accept people lists and warning objects, and tolerate missing fields", () => {
  const lines = buildFinalizeCheckLines({
    unfilled_people: [{ employee_name: "演示员工129" }, "演示员工146"],
    underfilled_people: [],
    warnings: [{ message: "提醒 A" }, "", null],
  });
  const byKey = Object.fromEntries(lines.map((l) => [l.key, l]));
  assert.equal(byKey.unfilled.text, "2 人未填工时");
  assert.equal(byKey.unfilled.detail, "演示员工129、演示员工146");
  assert.equal(byKey.underfilled.tone, "ok");
  assert.equal(byKey["warning-0"].text, "提醒 A");
  assert.equal(lines.length, 3);
  assert.deepEqual(buildFinalizeCheckLines(null), []);
  assert.deepEqual(buildFinalizeCheckLines({}), []);
  assert.equal(buildFinalizeCheckLines({ reconcile_diff: -0.004 })[0].tone, "ok");
  assert.equal(buildFinalizeCheckLines({ reconcile_diff: -12.3 })[0].tone, "warn");
});

test("preview warnings are plain texts without empties", () => {
  assert.deepEqual(previewWarningTexts({ preview_warnings: ["a", { message: "b" }, "", null] }), ["a", "b"]);
  assert.deepEqual(previewWarningTexts({}), []);
  assert.deepEqual(previewWarningTexts(null), []);
});
