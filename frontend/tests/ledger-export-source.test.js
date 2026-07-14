import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const pages = [
  "Projects.vue",
  "TimesheetEntry.vue",
  "Timesheet.vue",
  "ExpenseImport.vue",
  "ForeignRD.vue",
  "AllocationDashboard.vue",
];

for (const page of pages) {
  test(`${page} exports the current ledger view`, () => {
    const source = readFileSync(new URL(`../src/pages/${page}`, import.meta.url), "utf8");
    assert.match(source, /exportTableWorkbook/);
    assert.match(source, /exportCurrent/);
  });
}

test("allocation table keeps its dedicated workbook export", () => {
  const source = readFileSync(new URL("../src/pages/Allocation.vue", import.meta.url), "utf8");
  assert.match(source, /exportAllocationWorkbook/);
  assert.match(source, /exportCurrentAllocation/);
});
