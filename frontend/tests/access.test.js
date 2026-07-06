import assert from "node:assert/strict";
import test from "node:test";
import { canEditTimesheetEntry, canSee, firstVisiblePath, roleLabel } from "../src/lib/access.js";

function asRoles(roles) {
  globalThis.window = { roles };
}

test("employees land on timesheet entry and cannot see HR pages", () => {
  asRoles(["Employee"]);
  assert.equal(canSee("/entry"), true);
  assert.equal(firstVisiblePath(), "/entry");
  assert.equal(canSee("/dashboard"), false);
  assert.equal(canSee("/accommodation"), false);
  assert.equal(canSee("/expense"), false);
  assert.equal(canEditTimesheetEntry(), true);
});

test("department managers can use timesheet entry without HR access", () => {
  asRoles(["Employee", "Department Manager"]);
  assert.equal(canSee("/entry"), true);
  assert.equal(firstVisiblePath(), "/entry");
  assert.equal(canSee("/personnel"), false);
  assert.equal(canSee("/accommodation"), false);
  assert.equal(canSee("/expense"), false);
  assert.equal(canEditTimesheetEntry(), true);
});

test("finance can manage projects and fill R&D timesheets", () => {
  asRoles(["Accounts User"]);
  assert.equal(canSee("/expense"), true);
  assert.equal(canSee("/allocation"), true);
  assert.equal(canSee("/entry"), true);
  assert.equal(canSee("/timesheet"), true);
  assert.equal(canSee("/projects"), true);
  assert.equal(canEditTimesheetEntry(), true);
});


test("role labels use the highest business level", () => {
  asRoles(["Employee"]);
  assert.equal(roleLabel(), "\u5458\u5de5");
  asRoles(["Employee", "Department Manager"]);
  assert.equal(roleLabel(), "\u90e8\u95e8\u4e3b\u7ba1");
  asRoles(["HR User"]);
  assert.equal(roleLabel(), "HR");
  asRoles(["Accounts User"]);
  assert.equal(roleLabel(), "\u8d22\u52a1");
  asRoles(["System Manager", "HR Manager", "Accounts User"]);
  assert.equal(roleLabel(), "\u603b\u63a7");
});

test("the removed personnel ledger is not a visible business page", () => {
  asRoles(["HR User"]);
  assert.equal(canSee("/ledger"), false);
});
