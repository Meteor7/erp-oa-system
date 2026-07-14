import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const pageUrl = new URL("../src/pages/Projects.vue", import.meta.url);
const source = existsSync(pageUrl) ? readFileSync(pageUrl, "utf8") : "";

test("project management page uses the project API and table columns", () => {
  assert.match(source, /rayher_hr_payroll\.api\.project_entry\.list_projects/);
  assert.match(source, /rayher_hr_payroll\.api\.project_entry\.save_project/);
  assert.match(source, /rayher_hr_payroll\.api\.project_entry\.cancel_project/);
  assert.ok(source.includes("\u7f16\u53f7"));
  assert.ok(source.includes("\u9879\u76ee\u540d\u79f0"));
  assert.ok(!source.includes("\u82f1\u6587\u540d"));
  assert.doesNotMatch(source, /english_name/);
  assert.ok(source.includes("\u7acb\u9879\u65f6\u95f4"));
  assert.ok(source.includes("\u7ed3\u9879\u65f6\u95f4"));
  assert.ok(source.includes("\u7814\u53d1\u9636\u6bb5"));
  assert.ok(source.includes("\u8d44\u672c\u5316"));
  assert.ok(source.includes("\u8d39\u7528\u5316"));
  assert.ok(source.includes("\u72b6\u6001"));
  assert.ok(source.includes("\u65b0\u589e\u9879\u76ee"));
});

test("project management page keeps project codes tied to timesheet options", () => {
  assert.match(source, /rd_project_code/);
  assert.match(source, /allow_rd_timesheet/);
  assert.match(source, /rd_stage/);
  assert.doesNotMatch(source, /delete_project/);
});

test("project management captures owner and uploads the three project documents", () => {
  assert.match(source, /project_owner_name/);
  assert.match(source, /<input[^>]+v-model="form\.project_owner_name"/);
  assert.doesNotMatch(source, /v-model="form\.project_owner"/);
  assert.doesNotMatch(source, /list_project_owners/);
  assert.match(source, /project_initiation_report/);
  assert.match(source, /project_completion_report/);
  assert.match(source, /capitalization_confirmation_file/);
  assert.match(source, /uploadProjectFile/);
  assert.match(source, /\/api\/method\/upload_file/);
  assert.match(source, /table-fixed/);
  assert.match(source, /min-w-\[1480px\]/);
  assert.match(source, /sticky left-0/);
  assert.match(source, /sticky right-0/);
});
