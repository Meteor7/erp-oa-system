import assert from "node:assert/strict";
import test from "node:test";
import {
  canSeeAllTravel, emptyTravelForm, pushTarget, showMissing, travelBlockers, travelFormFrom, tripDays,
} from "../src/lib/travelView.js";

test("trip days count both ends and reject a return before the departure", () => {
  assert.equal(tripDays("2026-10-08", "2026-10-10"), 3);
  assert.equal(tripDays("2026-10-08", "2026-10-08"), 1);
  assert.equal(tripDays("2026-10-10", "2026-10-08"), 0);
  assert.equal(tripDays("", "2026-10-08"), 0);
});

test("the 还差 list names what is missing and only shows once the user started typing or tried to submit", () => {
  const form = emptyTravelForm();
  assert.equal(showMissing(form, false), false);
  assert.equal(showMissing(form, true), true);
  assert.equal(showMissing({ ...form, subject: "上海客户拜访" }, false), true);
  assert.deepEqual(travelBlockers(form), ["主题", "出差地点", "出发和返回日期", "出差事由"]);
  assert.deepEqual(travelBlockers({ ...form, subject: "a", travel_destination: "b", reason: "c", travel_start_date: "2026-10-10", travel_end_date: "2026-10-08" }), ["返回日期不能早于出发日期"]);
  assert.deepEqual(travelBlockers({ subject: "a", travel_destination: "b", reason: "c", travel_start_date: "2026-10-08", travel_end_date: "2026-10-10" }), []);
  assert.equal(showMissing({ ...form, project: "P1" }, false), false, "choosing only a project is not 'started typing'");
});

test("a draft fills the form back in", () => {
  assert.deepEqual(travelFormFrom({ subject: "北京参展", travel_destination: "北京", travel_start_date: "2026-10-20", travel_end_date: "2026-10-23", reason: "展会", project: "P1", extra: "x" }), {
    subject: "北京参展", travel_destination: "北京", travel_start_date: "2026-10-20", travel_end_date: "2026-10-23", reason: "展会", project: "P1",
  });
  assert.deepEqual(travelFormFrom(), emptyTravelForm());
});

test("everyone the server lets read all trips gets the 全部 entry: admins, HR and executives (same roles as the attendance centre)", () => {
  assert.equal(canSeeAllTravel(["Employee"]), false);
  assert.equal(canSeeAllTravel(["Employee", "Department Manager"]), false);
  assert.equal(canSeeAllTravel(["Accounts User", "Employee"]), false);
  assert.equal(canSeeAllTravel(["Employee", "QIHENG Demo Business Executive"]), true);
  assert.equal(canSeeAllTravel(["System Manager"]), true);
  assert.equal(canSeeAllTravel(["Employee", "HR Manager"]), true);
  assert.equal(canSeeAllTravel(["Employee", "HR User"]), true);
});

test("a completed trip is pushed to a reimbursement or a payment request", () => {
  assert.equal(pushTarget("claim"), "/approval/claim");
  assert.equal(pushTarget("payment"), "/approval/payment");
});
