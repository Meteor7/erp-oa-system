import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  boardRoute,
  dueText,
  hbarRows,
  paymentKpis,
  procurementKpis,
  requestKpis,
  scopeText,
  shortMoney,
  stackedChart,
} from "../src/lib/expenseBoards.js";
import { canSee } from "../src/lib/access.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
import { agingColumns, budgetBars, donutSegments, flowBars, waitBars } from "../src/lib/expenseBoards.js";

test("申请看板 KPIs follow the design and drop the stand-alone 占用 number", () => {
  const cards = requestKpis({ summary: {
    month_approved_amount: 1000, month_approved_count: 1, unpaid_amount: 600,
    pending_count: 2, longest_wait_days: 5, on_trip_count: 1, month_trip_count: 3,
  } });
  assert.deepEqual(cards.map((card) => card.label), ["本月通过的购买申请", "已批准未付出的额度", "审批中", "出差中 / 本月出差"]);
  assert.deepEqual(cards.map((card) => card.value), ["¥ 1,000.00", "¥ 600.00", "2 张", "1 人 / 3 次"]);
  assert.equal(cards[2].tone, "#B42318", "waiting more than 3 days turns red");
  assert.ok(!cards.some((card) => card.label.includes("占用")));
});

test("付款看板 KPIs split the month and show what the cashier still owes", () => {
  const cards = paymentKpis({ summary: {
    reimbursement_paid: 200, payment_paid: 350, to_pay_amount: 45, to_pay_count: 1, to_pay_urgent: 1,
    invoice_pending_amount: 700, invoice_pending_count: 2, invoice_overdue_count: 1,
  } });
  assert.deepEqual(cards.map((card) => card.value), ["¥ 200.00", "¥ 350.00", "¥ 45.00", "¥ 700.00"]);
  assert.equal(cards[2].sub, "1 张，其中加急 1 张");
  assert.equal(cards[3].sub, "2 张，逾期 1 张");
  assert.equal(cards[3].tone, "#B42318");
  assert.deepEqual(procurementKpis({ summary: { application_count: 3, application_pending: 1 } }).map((card) => card.value)[0], "3 张");
  assert.equal(procurementKpis({ summary: {} }, "payment").length, 4);
});

test("horizontal bars scale to the largest value", () => {
  assert.deepEqual(hbarRows([["研发部", 200], ["财务部", 50]]).map((row) => row.width), [100, 25]);
  assert.deepEqual(hbarRows([]), []);
});

test("stacked chart puts 报销 under 付款 and rounds the axis", () => {
  const chart = stackedChart([
    { month: "2026-08", reimbursement: 0, payment: 0 },
    { month: "2026-09", reimbursement: 200, payment: 350 },
  ]);
  const [empty, september] = chart.bars;
  assert.equal(empty.reimbursementHeight, 0);
  assert.equal(empty.paymentHeight, 0);
  assert.ok(september.reimbursementHeight > 0 && september.paymentHeight > september.reimbursementHeight);
  assert.ok(Math.abs(september.paymentY + september.paymentHeight - september.reimbursementY) < 1e-9, "付款叠在报销上面");
  assert.equal(september.label, "9月");
  assert.equal(chart.ticks[0].value, 0);
  assert.ok(chart.ticks.at(-1).value >= 550);
  assert.equal(shortMoney(25000), "2.5万");
  assert.equal(shortMoney(550), "550.00");
});

test("due text, routes and scope", () => {
  assert.deepEqual(dueText({ overdue_days: 3, days_left: 0 }), { text: "逾期 3 天", tone: "p-red" });
  assert.deepEqual(dueText({ overdue_days: 0, days_left: 0 }), { text: "今天到期", tone: "p-sun" });
  assert.deepEqual(dueText({ overdue_days: 0, days_left: 7 }), { text: "7 天后到期", tone: "p-sun" });
  assert.equal(boardRoute("出差申请"), "/approval/travel");
  assert.equal(boardRoute("付款单"), "/approval/payment");
  assert.equal(scopeText({ scope: "department", department: "研发部" }), "范围：本部门（研发部）");
});

test("the two boards are separate pages, each with its own 采购 tab", () => {
  const request = read("../src/pages/RequestBoard.vue");
  const payment = read("../src/pages/PaymentBoard.vue");
  assert.match(request, /expense_board_entry\.request_board/);
  assert.match(request, /part="request"/);
  assert.match(payment, /expense_board_entry\.payment_board/);
  assert.match(payment, /part="payment"/);
  assert.doesNotMatch(request, /payment_board/);
  assert.doesNotMatch(payment, /request_board/);
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


test("board charts: donut merges the tail into 其他 and aging buckets count the cashier queue (2026-09-30)", () => {
  const donut = donutSegments([["差旅费", 600], ["办公费", 300], ["招待费", 50], ["维修费", 30], ["快递费", 15], ["其他费用", 5]], 5);
  assert.deepEqual(donut.segments.map((row) => [row.label, row.value]), [["差旅费", 600], ["办公费", 300], ["招待费", 50], ["维修费", 30], ["其他", 20]]);
  assert.equal(donut.total, 1000);
  assert.equal(donut.segments[0].share, "60%");
  assert.match(donut.gradient, /^conic-gradient\(#5470C6 0\.0deg 216\.0deg/);
  assert.equal(donutSegments([]).total, 0);
  const aging = agingColumns([{ waited_days: 0, amount: 10 }, { waited_days: 2, amount: 20 }, { waited_days: 4, amount: 30 }, { waited_days: 9, amount: 40 }, { waited_days: 9, amount: 1 }]);
  assert.deepEqual(aging.map((column) => column.value), [1, 1, 1, 2]);
  assert.equal(aging[3].sub, "¥ 41.00");
  assert.deepEqual(flowBars([{ key: "submitted", count: 4 }, { key: "approved", count: 3 }]).map((row) => row.width), ["100.0%", "75.0%"]);
  assert.deepEqual(budgetBars([{ approved_amount: 1000, paid_amount: 250, reserved_amount: 100 }]).map((row) => [row.paidWidth, row.reservedWidth]), [["25.0%", "10.0%"]]);
  assert.deepEqual(waitBars([{ waited_days: 8 }, { waited_days: 2 }], 3).map((row) => [row.overdue, row.width]), [[true, "100.0%"], [false, "25.0%"]]);
});

test("the boards draw charts instead of only tables (2026-09-30)", () => {
  const request = read("../src/pages/RequestBoard.vue");
  const payment = read("../src/pages/PaymentBoard.vue");
  assert.match(payment, /<DonutChart :rows="data\.by_account/);
  assert.match(payment, /<ColumnChart/);
  assert.match(request, /month_mix/);
  assert.match(request, /flowBars/);
});
