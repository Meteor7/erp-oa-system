import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/Dashboard.vue", import.meta.url), "utf8");

test("personal approval todos render independently of company dashboard permission", () => {
  const personalTodos = source.indexOf("我的审批待办");
  const companyLoading = source.indexOf('v-if="d.loading"');
  const companyData = source.indexOf('v-else-if="d.data"');
  assert.ok(personalTodos > -1);
  assert.ok(personalTodos < companyLoading);
  assert.ok(personalTodos < companyData);
  assert.match(source, /oaTodos\.data\?\.total/);
  assert.match(source, /oaTodos\.error/);
});

test("dashboard presents personal queues as actionable categories", () => {
  assert.match(source, /todoCategories/);
  assert.match(source, /openApprovalTodo\(item\)/);
  assert.match(source, /item\.requests\?\./);
  assert.match(source, /个人审批工作台与本期经营数据/);
  assert.match(source, /月度核算流程/);
  assert.match(source, /数据完整度/);
});
