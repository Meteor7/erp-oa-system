import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

test("router registers project management page", () => {
  assert.match(source, /path: "\/projects"/);
  assert.match(source, /\.\/pages\/Projects\.vue/);
});

test("router stops loading the removed personnel ledger page", () => {
  assert.doesNotMatch(source, /\.\/pages\/Ledger\.vue/);
  assert.match(source, /path: "\/ledger", redirect: "\/entry"/);
});
