import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const pageUrl = new URL("../src/pages/Projects.vue", import.meta.url);
const source = existsSync(pageUrl) ? readFileSync(pageUrl, "utf8") : "";

test("project management page uses the project API and table columns", () => {
  assert.match(source, /rayher_hr_payroll\.api\.project_entry\.list_projects/);
  assert.match(source, /rayher_hr_payroll\.api\.project_entry\.save_project/);
  assert.match(source, /rayher_hr_payroll\.api\.project_entry\.cancel_project/);
  assert.ok(source.includes("编号"));
  assert.ok(source.includes("项目名称"));
  assert.ok(!source.includes("英文名"));
  assert.doesNotMatch(source, /english_name/);
  assert.ok(source.includes("立项时间"));
  assert.ok(source.includes("结项时间"));
  assert.ok(source.includes("研发阶段"));
  assert.ok(source.includes("资本化"));
  assert.ok(source.includes("费用化"));
  assert.ok(source.includes("状态"));
  assert.ok(source.includes("新增项目"));
});

test("project management page keeps project codes tied to timesheet options", () => {
  assert.match(source, /rd_project_code/);
  assert.match(source, /allow_rd_timesheet/);
  assert.match(source, /rd_stage/);
  assert.doesNotMatch(source, /delete_project/);
});

test("project management captures owner and uploads the three project documents", () => {
  assert.match(source, /list_project_owners/);
  assert.match(source, /project_owner/);
  assert.match(source, /project_initiation_report/);
  assert.match(source, /project_completion_report/);
  assert.match(source, /capitalization_confirmation_file/);
  assert.match(source, /uploadProjectFile/);
  assert.match(source, /\/api\/method\/upload_file/);
  // wide table that scrolls sideways
  assert.match(source, /min-w-\[1180px\]/);
});

test("project creation, owner assignment and cancellation are admin-only controls", () => {
  assert.match(source, /canAdministerProjects/);
  assert.match(source, /v-if="canAdministerProjects\(\)"[^>]*@click="newProject"/);
  assert.match(source, /v-if="canAdministerProjects\(\)"[^>]*v-model="form\.project_owner"/);
  assert.match(source, /v-if="canAdministerProjects\(\) && row\.status !== 'Cancelled'"/);
});


test("project reports use the scoped download endpoint instead of raw private URLs", () => {
  assert.match(source, /download_project_report/);
  assert.match(source, /encodeURIComponent\(row\.name\)/);
  assert.match(source, /encodeURIComponent\(fieldname\)/);
  assert.doesNotMatch(source, /:href="row\[field\]"/);
});
