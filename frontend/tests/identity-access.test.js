import assert from "node:assert/strict";
import test from "node:test";
import { canOpenMaterialBoard, canSee, isHrSensitiveHidden } from "../src/lib/access.js";

const ROLES = ["Employee", "Accounts User", "HR Manager", "Department Manager"];
const SENSITIVE = ["/social-insurance", "/housing-fund"];

test("nobody is masked now: the former test account sees the sensitive HR pages like everyone else", () => {
  for (const user of ["person046@staff.example.invalid", "person030@staff.example.invalid", "person052@staff.example.invalid"]) {
    globalThis.window = { user, roles: ROLES };
    assert.equal(isHrSensitiveHidden(), false, user);
    assert.deepEqual(SENSITIVE.map((path) => canSee(path)), [true, true], user);
  }
});

test("the general manager can open the material progress board, like PMC, the procurement manager and the vice manager", () => {
  const board = () => { globalThis.window.oa_access = undefined; return canOpenMaterialBoard() && canSee("/approval/material-progress"); };
  globalThis.window = { user: "person014@staff.example.invalid", roles: ["Employee"], position_access: { general_manager: true } };
  assert.equal(board(), true);
  for (const position of ["pmc", "procurement_manager", "vice_manager"]) {
    globalThis.window = { user: "person061@staff.example.invalid", roles: ["Employee"], position_access: { [position]: true } };
    assert.equal(board(), true, position);
  }
  globalThis.window = { user: "person061@staff.example.invalid", roles: ["Employee"], position_access: { finance_manager: true } };
  assert.equal(board(), false);
});
