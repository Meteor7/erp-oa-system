import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/Timesheet.vue", import.meta.url), "utf8");

test("timesheet pivot uses the role-scoped R&D hours API", () => {
  assert.match(source, /rayher_hr_payroll\.api\.timesheet_entry\.list_rd_hours/);
  assert.doesNotMatch(source, /frappe\.desk\.query_report\.run/);
  assert.match(source, /row\.employee_name/);
  assert.match(source, /row\.rd_project_key/);
});
