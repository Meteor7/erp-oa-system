import assert from "node:assert/strict";
import test from "node:test";
import {
  allocationEmptyState,
  buildAllocationMatrixFilters,
  hasAllocationData,
} from "../src/lib/allocationView.js";

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

test("empty state distinguishes no business data from no matrix detail", () => {
  assert.equal(allocationEmptyState({ hasData: false, mode: "all" }), "no-data");
  assert.equal(allocationEmptyState({ hasData: true, mode: "all" }), "no-detail");
  assert.equal(allocationEmptyState({ hasData: true, mode: "capitalized" }), "no-detail-for-mode");
  assert.equal(allocationEmptyState({ hasData: true, mode: "expensed" }), "no-detail-for-mode");
});
