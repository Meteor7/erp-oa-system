import assert from "node:assert/strict";
import test from "node:test";
import {
  BOARD_TABS,
  boardRoute,
  cardTone,
  dueText,
  overdueTone,
  paymentCards,
  procurementCards,
  requestCards,
  tabFor,
  trendBars,
} from "../src/lib/expenseBoards.js";
import { canSee } from "../src/lib/access.js";

test("each board tab knows its own backend method", () => {
  assert.deepEqual(BOARD_TABS.map((tab) => tab.key), ["request", "payment", "procurement"]);
  assert.deepEqual(BOARD_TABS.map((tab) => tab.method), [
    "expense_board_entry.request_board",
    "expense_board_entry.payment_board",
    "expense_board_entry.procurement_board",
  ]);
});

test("the tab follows the route and the query", () => {
  assert.equal(tabFor("/approval/expense-request-board", {}), "request");
  assert.equal(tabFor("/approval/expense-payment-board", {}), "payment");
  assert.equal(tabFor("/approval/expense-payment-board", { tab: "procurement" }), "procurement");
  assert.equal(tabFor("/approval/expense-request-board", { tab: "nonsense" }), "request");
});

test("request cards show approved, unpaid, reserved and the two watch lists", () => {
  const cards = requestCards({
    summary: { approved_amount: 1000, unpaid_amount: 600, reserved_amount: 100, paid_amount: 400 },
    stale_applications: [{ name: "P1" }],
    stuck_approvals: [{ name: "P2", overdue: true }, { name: "P3", overdue: false }],
    stale_days: 30, stuck_days: 3,
  });
  assert.deepEqual(cards.map((card) => [card.key, card.value]), [
    ["approved_amount", 1000], ["unpaid_amount", 600], ["reserved_amount", 100],
    ["paid_amount", 400], ["stale", 1], ["stuck", 1],
  ]);
  assert.ok(cards[4].label.includes("30"));
  assert.ok(cards[5].label.includes("3"));
});

test("payment cards split 报销 and 付款 for the month", () => {
  const cards = paymentCards({ summary: { month: "2026-09", reimbursement_paid: 100, payment_paid: 250, paid_total: 350, cashier_pending: 2, invoice_pending: 3, invoice_overdue: 1 } });
  assert.deepEqual(cards.map((card) => card.value), [100, 250, 350, 2, 3, 1]);
  assert.ok(cards[0].label.includes("2026-09"));
  assert.equal(cards.find((card) => card.key === "invoice_overdue").tone, "red");
  const procurement = procurementCards({ summary: { application_count: 1, payment_count: 2, pending_arrival: 1 } });
  assert.deepEqual(procurement.map((card) => card.key), [
    "application_count", "application_amount", "payment_count", "paid_amount",
    "pending_arrival", "pending_inspection", "pending_writeoff",
  ]);
  assert.notEqual(cardTone("red"), cardTone("emerald"));
});

test("trend bars scale against the highest month and stay visible when small", () => {
  const bars = trendBars([
    { month: "2026-08", reimbursement: 0, payment: 0 },
    { month: "2026-09", reimbursement: 900, payment: 100 },
    { month: "2026-07", reimbursement: 1, payment: 0 },
  ]);
  assert.deepEqual(bars.map((row) => row.total), [0, 1000, 1]);
  assert.equal(bars[0].reimbursementHeight, 0);
  assert.equal(bars[1].reimbursementHeight, 90);
  assert.equal(bars[1].paymentHeight, 10);
  assert.equal(bars[2].reimbursementHeight, 2, "a tiny month still gets a visible bar");
  assert.deepEqual(trendBars([]), []);
});

test("overdue text and tone", () => {
  assert.equal(dueText({ overdue_days: 5, days_left: 0 }), "已逾期 5 天");
  assert.equal(dueText({ overdue_days: 0, days_left: 0 }), "今天到期");
  assert.equal(dueText({ overdue_days: 0, days_left: 3 }), "3 天后到期");
  assert.notEqual(overdueTone(8), overdueTone(1));
  assert.equal(overdueTone(0), "text-gray-600");
});

test("each row links back to its own document page", () => {
  assert.equal(boardRoute("购买申请"), "/approval/direct-purchase");
  assert.equal(boardRoute("出差申请"), "/approval/travel");
  assert.equal(boardRoute("报销单"), "/approval/claim");
  assert.equal(boardRoute("付款单"), "/approval/payment");
  assert.equal(boardRoute("采购付款"), "/approval/procurement-payment");
});

test("the boards are closed to plain employees and open to finance, managers and department heads", () => {
  const access = { reimbursement_request: true, payment_request: true };
  globalThis.window = { roles: ["Employee"], oa_access: access };
  assert.equal(canSee("/approval/expense-request-board"), false);
  assert.equal(canSee("/approval/expense-payment-board"), false);
  globalThis.window = { roles: ["Employee", "Department Manager"], oa_access: access };
  assert.equal(canSee("/approval/expense-request-board"), true);
  globalThis.window = { roles: ["Accounts User"], oa_access: access };
  assert.equal(canSee("/approval/expense-payment-board"), true);
  globalThis.window = { roles: ["Accounts User"], oa_access: {} };
  assert.equal(canSee("/approval/expense-payment-board"), false, "closed until a claim type is switched on");
});
