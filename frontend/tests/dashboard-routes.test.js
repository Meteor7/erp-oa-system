import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { ATTENDANCE_HOME_PATH } from "../src/lib/attendanceView.js";
import { canSee } from "../src/lib/access.js";
import { BOARD_REDIRECTS } from "../src/lib/approvalGroupPaths.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
// 点击目标表是后端那一份 JSON（前端直接读它，不手写）。
const targets = JSON.parse(read("../../rayher_hr_payroll/dashboard/targets.json")).targets;
const router = read("../src/router.js");

const ALL_FLAGS = {
  leave_approval: true, procurement_application: true, direct_purchase_application: true, travel_application: true,
  procurement_payment: true, expense_reimbursement: true, reimbursement_request: true, payment_request: true,
};

function as({ roles = ["Employee"], positions = {}, access = ALL_FLAGS } = {}) {
  globalThis.window = { roles, position_access: positions, oa_access: access };
}

const pathsOf = (keys) => keys.map((key) => targets[key].path);
const openable = (keys) => keys.filter((key) => canSee(targets[key].path));

test("every dashboard target lands on a registered route", () => {
  assert.ok(Object.keys(targets).length > 30);
  for (const [key, target] of Object.entries(targets)) {
    assert.ok(router.includes(`path: '${target.path}'`) || target.path in BOARD_REDIRECTS, `${key} -> ${target.path} has no route`);
  }
});

test("the attendance center home is a real route that reuses the attendance page", () => {
  assert.equal(ATTENDANCE_HOME_PATH, "/approval/attendance");
  assert.match(router, /path: '\/approval\/attendance', component: attendancePage/);
  assert.match(router, /const attendancePage = \(\) => import\('\.\/pages\/AttendanceCenter\.vue'\)/);
  // 看板的考勤目标全部落在它上面
  for (const key of ["attendance.home", "attendance.month", "attendance.away", "attendance.todo", "attendance.mine", "attendance.all", "attendance.today", "attendance.detail"]) {
    assert.equal(targets[key].path, ATTENDANCE_HOME_PATH, key);
  }
});

test("the attendance cards land directly on a block of the attendance home, which reads the same parameters from the address", () => {
  // 2026-10-14：本月请假 / 加班 → 「N 月」概览（选好类型和月份）；出差中 / 今天不在岗 → 「谁不在」（出差中选好出差）
  assert.deepEqual(targets["attendance.month"].query, { view: "home", section: "month" });
  assert.deepEqual(targets["attendance.month"].params, ["metric", "month"]);
  assert.deepEqual(targets["attendance.away"].query, { view: "home", section: "away" });
  assert.deepEqual(targets["attendance.away"].params, ["tile"]);
  const home = read("../src/lib/attendanceHome.js");
  for (const key of ["section", "metric", "month", "tile"]) assert.match(home, new RegExp(`'${key}'`), key);
  const page = read("../src/components/attendance/AttendanceHome.vue");
  assert.match(page, /id="ac-month"|getElementById\(section === 'month' \? 'ac-month' : 'ac-away'\)/);
  assert.match(read("../src/components/attendance/AttendanceMonthPanel.vue"), /id="ac-month"/);
  assert.match(read("../src/components/attendance/AttendanceAwayPanel.vue"), /id="ac-away"/);
});

test("the attendance home opens for exactly the people who can open leave, and follows the same switch", () => {
  for (const roles of [["Employee"], ["Employee", "Department Manager"], ["Accounts User"], ["HR User"], ["System Manager"], ["Guest"], []]) {
    as({ roles });
    assert.equal(canSee("/approval/attendance"), canSee("/approval/leave"), roles.join(","));
  }
  as({ roles: ["Employee"] });
  assert.equal(canSee("/approval/attendance"), true);
  as({ roles: ["Employee"], access: { ...ALL_FLAGS, leave_approval: false } });
  assert.equal(canSee("/approval/attendance"), false);
  assert.equal(canSee("/approval/leave"), false);
});

test("an ordinary employee can open the pages every role's dashboard links to for them", () => {
  as({ roles: ["Employee"] });
  const mine = ["claim.todo", "claim.mine", "claim.detail", "payment.todo", "payment.detail", "invoice.folder", "attendance.home", "attendance.todo",
    "attendance.mine", "attendance.today", "attendance.detail", "timesheet.board", "timesheet.mine", "procurement.list", "procurement.detail",
    "travel.list"];
  assert.deepEqual(openable(mine), mine);
  // 员工没有的页面不能在看板上点开（卡片置灰）
  for (const key of ["personnel.list", "payroll", "social", "housing", "dorm.board", "cost.summary", "allocation", "board.request", "board.payment", "material.progress", "material.overdue"]) {
    assert.equal(canSee(targets[key].path), false, key);
  }
});

test("finance opens the allocation pages, the boards and the payment pages, but not HR pages", () => {
  as({ roles: ["Employee", "Accounts User"] });
  const finance = ["cost.summary", "allocation", "board.request", "board.payment", "payment.unpaid", "payment.waiting", "claim.stuck",
    "procpay.work", "procpay.approvals", "invoice.folder", "timesheet.board"];
  assert.deepEqual(openable(finance), finance);
  for (const key of ["personnel.list", "payroll", "social", "housing", "dorm.board", "material.progress"]) {
    assert.equal(canSee(targets[key].path), false, key);
  }
});

test("HR opens the personnel, payroll, social insurance, housing fund and dormitory pages, but not the allocation pages", () => {
  for (const roles of [["Employee", "HR User"], ["Employee", "HR Manager"]]) {
    as({ roles });
    const hr = ["personnel.list", "personnel.expiring", "personnel.rd_gap", "personnel.file", "personnel.joined", "payroll", "social", "housing",
      "dorm.board", "dorm.lease", "dorm.leaver", "dorm.monthly", "attendance.all", "timesheet.board"];
    assert.deepEqual(openable(hr), hr, roles.join(","));
    for (const key of ["cost.summary", "allocation", "material.progress", "material.overdue"]) {
      assert.equal(canSee(targets[key].path), false, `${roles.join(",")} ${key}`);
    }
  }
});

test("the material progress board opens for PMC, procurement manager, vice and general manager, and system managers", () => {
  const board = pathsOf(["material.progress", "material.overdue"]);
  for (const position of ["pmc", "procurement_manager", "vice_manager", "general_manager"]) {
    as({ roles: ["Employee"], positions: { [position]: true } });
    assert.deepEqual(board.map((path) => canSee(path)), [true, true], position);
  }
  as({ roles: ["System Manager"] });
  assert.deepEqual(board.map((path) => canSee(path)), [true, true]);
  // 别的岗位（生产主管、财务经理、普通员工）看不到，卡片置灰
  for (const position of ["production_asset_owner", "finance_manager", "hr_manager"]) {
    as({ roles: ["Employee"], positions: { [position]: true } });
    assert.deepEqual(board.map((path) => canSee(path)), [false, false], position);
  }
  as({ roles: ["Employee"] });
  assert.deepEqual(board.map((path) => canSee(path)), [false, false]);
});

test("the vice and general manager can open the procurement and board pages their dashboard links to", () => {
  as({ roles: ["Employee"], positions: { vice_manager: true } });
  for (const key of ["board.request", "board.payment", "price.approvals", "procpay.work", "material.progress", "payment.unpaid", "claim.stuck"]) {
    assert.equal(canSee(targets[key].path), true, key);
  }
});

test("a system manager can open every dashboard target (nothing in the table is unreachable)", () => {
  as({ roles: ["System Manager"] });
  for (const [key, target] of Object.entries(targets)) {
    assert.equal(canSee(target.path), true, `${key} -> ${target.path}`);
  }
});

test("a feature switched off greys the target out, the same way the menu hides it", () => {
  as({ roles: ["System Manager"], access: { ...ALL_FLAGS, procurement_payment: false, reimbursement_request: false } });
  assert.equal(canSee(targets["procpay.work"].path), false);
  assert.equal(canSee(targets["claim.todo"].path), false);
  assert.equal(canSee(targets["payment.todo"].path), true);
});

test("the reimbursement and payment lists read view / scope / bucket / long from the address", () => {
  assert.deepEqual(targets["payment.waiting"].query, { view: "list", scope: "all", bucket: "topay", long: "1" });
  assert.deepEqual(targets["claim.stuck"].query, { view: "list", scope: "all", bucket: "review", long: "1" });
  const workbench = read("../src/components/claim/ClaimWorkbench.vue");
  assert.match(workbench, /resolveScope\(route\.query\.scope/);
  assert.match(workbench, /normalizeBucket\(route\.query\.bucket\)/);
  assert.match(workbench, /ref\(route\.query\.long === '1'\)/);
  // 报销和付款是同一个工作台，付款页面只是换了 kind
  assert.match(read("../src/pages/PaymentRequestCenter.vue"), /<ClaimWorkbench kind="payment"/);
  assert.match(read("../src/pages/ClaimCenter.vue"), /ClaimWorkbench/);
});

test("the request board and the payment board read their tab from the address", () => {
  for (const page of ["RequestBoard", "PaymentBoard"]) {
    assert.match(read(`../src/pages/${page}.vue`), /boardTab\(route\.query\)/, page);
  }
  assert.deepEqual(targets["board.request"].params, ["tab"]);
  assert.deepEqual(targets["board.payment"].params, ["tab", "focus"]);
  // 「出纳待付款」点进来带 focus=cashier：付款看板加载完滚到 id="bd-cashier" 那一块
  assert.match(read("../src/lib/expenseBoards.js"), /cashier: 'bd-cashier'/);
  assert.match(read("../src/pages/PaymentBoard.vue"), /id="bd-cashier"/);
  for (const page of ["PaymentBoard", "ApprovalGroupHome"]) assert.match(read(`../src/pages/${page}.vue`), /focusAnchor\(route\.query\)/, page);
  assert.match(read("../src/lib/expenseBoards.js"), /query\.tab === 'procurement' \? 'procurement' : 'main'/);
});
