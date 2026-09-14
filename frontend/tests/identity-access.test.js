import assert from "node:assert/strict";
import test from "node:test";
import { canSee, canSeeProcurementPrice } from "../src/lib/access.js";

test("renamed executive keeps the same access and sensitive HR restrictions", () => {
  const paths = ["/social-insurance", "/housing-fund", "/approval/material-progress", "/projects", "/accommodation"];
  const results = [];
  for (const user of ["person046@staff.example.invalid", "person030@staff.example.invalid"]) {
    globalThis.window = { user, roles: ["Employee", "Accounts User", "HR Manager", "Department Manager"] };
    results.push([...paths.map(path => canSee(path)), canSeeProcurementPrice()]);
  }
  assert.deepEqual(results[0], results[1]);
});
