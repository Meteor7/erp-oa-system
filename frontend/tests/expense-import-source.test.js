import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/ExpenseImport.vue", import.meta.url), "utf8");

test("expense import supports common and project-specific expenses", () => {
  assert.match(source, /rayher_hr_payroll\.api\.project_entry\.list_projects/);
  assert.match(source, /allocation_type/);
  assert.match(source, /direct_project/);
  assert.ok(source.includes("\u5f52\u5c5e\u65b9\u5f0f"));
  assert.ok(source.includes("\u516c\u5171\u8d39\u7528"));
  assert.ok(source.includes("\u9879\u76ee\u8d39\u7528"));
  assert.ok(source.includes("\u6240\u5c5e\u9879\u76ee"));
});

test("allocated expense imports stay editable from the SPA", () => {
  assert.doesNotMatch(source, /status\.value === "Allocated" \|\| status\.value === "Imported"/);
  assert.doesNotMatch(source, /\u5df2\u63d0\u4ea4\/\u5df2\u5206\u644a/);
});
