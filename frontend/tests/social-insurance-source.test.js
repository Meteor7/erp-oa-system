import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/pages/SocialInsurance.vue", import.meta.url), "utf8");

test("pending social rows expose both audited decisions", () => {
  assert.match(source, /ignore_social_row/);
  assert.match(source, /确认并纳入本批次/);
  assert.match(source, /忽略此行/);
  assert.match(source, /填写确认或忽略原因/);
});

test("pending batches expose confirm and cancel in each row", () => {
  assert.match(source, /cancel_social_batch/);
  assert.match(source, /取消批次/);
  assert.match(source, /批次操作/);
  assert.doesNotMatch(source, /v-if="currentPreview"[^>]*>确认导入/);
});

test("pending audit table shows record inputs and policy", () => {
  assert.match(source, /档案社保基数/);
  assert.match(source, /Excel缴费工资/);
  assert.match(source, /基数来源/);
  assert.match(source, /户口信息/);
  assert.match(source, /系统判断/);
  assert.match(source, /政策版本/);
});


test("pending reasons are visible before financial columns and explain exact mismatches", () => {
  assert.match(source, /pendingReasonSummary/);
  assert.match(source, /pendingReason\(row\)/);
  assert.match(source, /地方补充养老：Excel/);
  assert.ok(source.indexOf("待确认原因") < source.indexOf("关联员工"));
});

test("linked employee select displays the stored association by default", () => {
  assert.match(source, /:value="selectedEmployees\[row\.name\] \|\| row\.employee \|\| ''"/);
  assert.match(source, /selectedEmployees\[row\.name\] = \$event\.target\.value/);
});
