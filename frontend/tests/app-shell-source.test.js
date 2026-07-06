import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");

test("app shell shows current account level and logout", () => {
  assert.match(source, /roleLabel\(\)/);
  assert.match(source, /currentUser/);
  assert.ok(source.includes("&#x9000;&#x51fa;&#x767b;&#x5f55;"));
  assert.ok(source.includes("/?cmd=web_logout"));
});

test("app shell exposes project management in the R&D ledger nav", () => {
  assert.ok(source.includes("\u9879\u76ee\u7ba1\u7406"));
  assert.ok(source.includes("/projects"));
});

test("app shell hides the redundant R and D personnel ledger", () => {
  assert.doesNotMatch(source, /研发人员台账/);
  assert.doesNotMatch(source, /to: "\/ledger"/);
  assert.ok(source.includes('label: "研发工时填报"'));
  assert.ok(source.includes('step: "04", label: "研发工时填报"'));
});
