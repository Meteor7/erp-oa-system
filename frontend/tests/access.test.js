import assert from "node:assert/strict";
import test from "node:test";
import {
  canAdministerProjects,
  canEditTimesheetEntry,
  canSee,
  firstVisiblePath,
  roleLabel,
} from "../src/lib/access.js";

function asRoles(roles) {
  globalThis.window = { roles };
}

test("employees can edit their own timesheet without management-page access", () => {
  asRoles(["Employee"]);
  assert.equal(canSee("/entry"), true);
  assert.equal(firstVisiblePath(), "/entry");
  assert.equal(canSee("/approval/leave"), true);
  assert.equal(canSee("/approval/purchase"), true);
  assert.equal(canSee("/dashboard"), false);
  assert.equal(canSee("/accommodation"), false);
  assert.equal(canSee("/expense"), false);
  assert.equal(canEditTimesheetEntry(), true);
});

test("department supervisors can use timesheet entry and approval pages without HR access", () => {
  asRoles(["Employee", "Department Manager"]);
  assert.equal(canSee("/entry"), true);
  assert.equal(firstVisiblePath(), "/entry");
  assert.equal(canSee("/approval/leave"), true);
  assert.equal(canSee("/approval/purchase"), true);
  assert.equal(canSee("/personnel"), false);
  assert.equal(canSee("/accommodation"), false);
  assert.equal(canSee("/expense"), false);
  assert.equal(canEditTimesheetEntry(), true);
});

test("finance can manage projects and view R&D timesheets without editing them", () => {
  asRoles(["Accounts User"]);
  assert.equal(canSee("/expense"), true);
  assert.equal(canSee("/allocation"), true);
  assert.equal(canSee("/allocation-dashboard"), true);
  assert.equal(canSee("/entry"), true);
  assert.equal(canSee("/timesheet"), true);
  assert.equal(canSee("/projects"), true);
  assert.equal(canSee("/approval/leave"), true);
  assert.equal(canSee("/approval/purchase"), true);
  assert.equal(canEditTimesheetEntry(), false);
  assert.equal(canAdministerProjects(), true);
});

test("project owners can open project management without admin controls", () => {
  asRoles(["Employee", "Project Owner"]);
  assert.equal(canSee("/projects"), true);
  assert.equal(canAdministerProjects(), false);
  assert.equal(canSee("/personnel"), false);
  assert.equal(canSee("/expense"), false);
  assert.equal(canEditTimesheetEntry(), true);
});

test("all-project access widens project data without granting administration", () => {
  asRoles(["Employee", "Project Owner", "All Project Access"]);
  assert.equal(canSee("/projects"), true);
  assert.equal(canAdministerProjects(), false);
  assert.equal(canSee("/personnel"), false);
  assert.equal(canSee("/expense"), false);
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
  asRoles(["Employee", "Project Owner"]);
  assert.equal(roleLabel(), "\u9879\u76ee\u8d1f\u8d23\u4eba");
  asRoles(["System Manager", "HR Manager", "Accounts User"]);
  assert.equal(roleLabel(), "\u603b\u63a7");
});

test("the removed personnel ledger is not a visible business page", () => {
  asRoles(["HR User"]);
  assert.equal(canSee("/ledger"), false);
});


test("foreign commissioned R&D is finance plus the all-project account exception", () => {
  asRoles(["Accounts User"]);
  assert.equal(canSee("/foreign-rd"), true);
  asRoles(["System Manager"]);
  assert.equal(canSee("/foreign-rd"), true);
  asRoles(["Employee", "Project Owner", "All Project Access"]);
  assert.equal(canSee("/foreign-rd"), true);
  assert.equal(canSee("/expense"), false);
  asRoles(["Employee", "Project Owner"]);
  assert.equal(canSee("/foreign-rd"), false);
  asRoles(["HR User"]);
  assert.equal(canSee("/foreign-rd"), false);
});

test("allocation dashboard is finance-only", () => {
  asRoles(["Accounts User"]);
  assert.equal(canSee("/allocation-dashboard"), true);
  asRoles(["System Manager"]);
  assert.equal(canSee("/allocation-dashboard"), true);
  asRoles(["HR User"]);
  assert.equal(canSee("/allocation-dashboard"), false);
  asRoles(["Employee"]);
  assert.equal(canSee("/allocation-dashboard"), false);
});

test("temporary OA flags hide both approval pages from non-admin roles", () => {
  for (const roles of [["Employee"], ["Employee", "Department Manager"], ["Accounts User"], ["HR Manager"], ["System Manager"]]) {
    globalThis.window = { roles, oa_access: { leave_approval: false, expense_reimbursement: false } };
    assert.equal(canSee("/approval/leave"), false);
    assert.equal(canSee("/approval/purchase"), false);
  }
});

test("temporary OA flags restore modules independently", () => {
  globalThis.window = { roles: ["Employee"], oa_access: { leave_approval: true, expense_reimbursement: false } };
  assert.equal(canSee("/approval/leave"), true);
  assert.equal(canSee("/approval/purchase"), false);
  globalThis.window = { roles: ["Employee"], oa_access: { leave_approval: false, expense_reimbursement: true } };
  assert.equal(canSee("/approval/leave"), false);
  assert.equal(canSee("/approval/purchase"), true);
});

test("closed approval center drafts stay hidden until explicit server flags", () => {
  globalThis.window = { roles: ["System Manager"], oa_access: { procurement_application: false, direct_purchase_application: false, procurement_payment: false } };
  assert.equal(canSee("/approval/procurement"), false);
  assert.equal(canSee("/approval/direct-purchase"), false);
  assert.equal(canSee("/approval/procurement-payment"), false);
  globalThis.window.oa_access = { procurement_application: true, direct_purchase_application: true, procurement_payment: true };
  assert.equal(canSee("/approval/procurement"), true);
  assert.equal(canSee("/approval/direct-purchase"), true);
  assert.equal(canSee("/approval/procurement-payment"), true);
});
