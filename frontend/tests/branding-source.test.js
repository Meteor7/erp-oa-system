import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { displayCompany, displayUser } from "../src/lib/displayBrand.js";

const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");

test("legacy visible route is replaced with the canonical Qiheng Demo path", () => {
  assert.ok(routerSource.includes("const LEGACY_BASE = '/rayher';"));
  assert.ok(routerSource.includes("const CANONICAL_BASE = '/planck-semicon';"));
  assert.match(routerSource, /history\.replaceState/);
  assert.match(routerSource, /createWebHistory\(CANONICAL_BASE\)/);
  assert.doesNotMatch(routerSource, /const spaBase .*\? '\/rayher'/);
});

test("visible company and administrator labels never expose the legacy name", () => {
  assert.equal(displayCompany("Rayher"), "示例总部");
  assert.equal(displayUser("Rayher Admin"), "QIHENG DEMO 管理员");
  assert.match(appSource, /currentUser\(\)/);
  assert.doesNotMatch(appSource, />\s*Rayher\s*</i);
});