import assert from "node:assert/strict";
import test from "node:test";
import { canSee, canSeeProcurementPrice } from "../src/lib/access.js";

const ROLES = ["Employee", "Accounts User", "HR Manager", "Department Manager"];
const SENSITIVE = ["/social-insurance", "/housing-fund"];
const OTHER = ["/approval/material-progress", "/projects", "/accommodation"];

test("the temporarily masked executive loses only the sensitive HR pages", () => {
  globalThis.window = { user: "person046@staff.example.invalid", roles: ROLES };
  assert.deepEqual(SENSITIVE.map((path) => canSee(path)), [false, false]);

  globalThis.window = { user: "person052@staff.example.invalid", roles: ROLES };
  assert.deepEqual(SENSITIVE.map((path) => canSee(path)), [true, true]);
});

test("the mask does not change any other access of that account", () => {
  const results = [];
  for (const user of ["person046@staff.example.invalid", "person052@staff.example.invalid"]) {
    globalThis.window = { user, roles: ROLES };
    results.push([...OTHER.map((path) => canSee(path)), canSeeProcurementPrice()]);
  }
  assert.deepEqual(results[0], results[1]);
});

test("the old lidemo_executive@ spelling is not a masked account any more", () => {
  globalThis.window = { user: "person030@staff.example.invalid", roles: ROLES };
  assert.deepEqual(SENSITIVE.map((path) => canSee(path)), [true, true]);
});
