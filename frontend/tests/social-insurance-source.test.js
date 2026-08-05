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
