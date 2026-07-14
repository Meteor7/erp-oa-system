import assert from "node:assert/strict";
import test from "node:test";

test("yearly timesheet groups by month and exposes project-code allocation rates", async () => {
  const pivotModule = await import("../src/lib/timesheetPivot.js").catch(() => ({}));
  assert.equal(typeof pivotModule.buildMonthlyProjectRatePivot, "function");
  assert.equal(typeof pivotModule.buildEmployeeProjectPivot, "function");

  const rows = [
    { employee: "EMP-1", employee_name: "Alice", work_date: "2026-01-03", rd_project_key: "RD01 | Alpha", rd_project_code: "RD01", project_name: "Alpha", hours: 6 },
    { employee: "EMP-2", employee_name: "Bob", work_date: "2026-01-04", rd_project_key: "RD02 | Beta", rd_project_code: "RD02", project_name: "Beta", hours: 2 },
    { employee: "EMP-1", employee_name: "Alice", work_date: "2026-02-03", rd_project_key: "RD01 | Alpha", rd_project_code: "RD01", project_name: "Alpha", hours: 3 },
    { employee: "EMP-2", employee_name: "Bob", work_date: "2026-02-04", rd_project_key: "RD02 | Beta", rd_project_code: "RD02", project_name: "Beta", hours: 3 },
  ];

  const yearly = pivotModule.buildMonthlyProjectRatePivot(rows, 2026);
  assert.deepEqual(yearly.projects.map((project) => project.label), ["RD01", "RD02"]);
  assert.equal(yearly.data.length, 12);
  assert.deepEqual(yearly.data[0], { id: "2026-01", month: "2026\u5e7401\u6708", vals: [75, 25], total: 100 });
  assert.deepEqual(yearly.data[1], { id: "2026-02", month: "2026\u5e7402\u6708", vals: [50, 50], total: 100 });
  assert.deepEqual(yearly.data[2], { id: "2026-03", month: "2026\u5e7403\u6708", vals: [0, 0], total: 0 });
  assert.equal(Object.hasOwn(yearly.data[0], "emp"), false);

  const monthly = pivotModule.buildEmployeeProjectPivot(rows.slice(0, 2));
  assert.deepEqual(monthly.projects.map((project) => project.label), ["RD01", "RD02"]);
  assert.deepEqual(monthly.data.map((row) => row.emp), ["Alice", "Bob"]);
});
