import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  agingColumns, agingTiles, boardRoute, boardTab, bottomColumns, budgetBars, donutSegments, dueText, flowBars, fulfilTone, hasPoWork,
  hbarRows, paymentFulfilment, paymentKpis, poProgressRows, poStatusCount, poStatusRows, poStatusTone, poWorkKpis, procurementKpis,
  requestKpis, scopeText, shortMoney, stackedChart, waitBars,
} from "../src/lib/expenseBoards.js";
import { canSee } from "../src/lib/access.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

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
});

test("every KPI card is clickable: a list page or an anchor on the same board (2026-10)", () => {
  const pay = paymentKpis({});
  assert.deepEqual(pay[0].to, { path: "/approval/claim", query: { view: "list", scope: "all" } });
  assert.deepEqual(pay[1].to, { path: "/approval/payment", query: { view: "list", scope: "all" } });
  assert.deepEqual(pay[2].to, { anchor: "bd-cashier" });
  assert.deepEqual(pay[3].to, { anchor: "bd-invoices" });
  const request = requestKpis({});
  assert.ok(request.every((card) => card.to && (card.to.path || card.to.anchor)));
  assert.deepEqual(request[3].to, { path: "/approval/travel", query: { view: "list", scope: "all" } });
  assert.ok(procurementKpis({}, "request").every((card) => card.to?.path === "/approval/procurement"));
  assert.ok(procurementKpis({}, "payment").every((card) => card.to?.path === "/approval/procurement-payment"));
});

test("采购付款 KPIs come from po_work when the server sends it, and 预付款核销 is gone either way", () => {
  const data = { po_work: { summary: {
    month_paid_amount: 3433.1, paid_count: 2, waiting_final_amount: 2860, waiting_final_count: 1,
    in_approval_amount: 1221, in_approval_count: 1, ready_amount: 515.4, ready_count: 1,
  } } };
  assert.equal(hasPoWork(data), true);
  const cards = procurementKpis(data, "payment");
  assert.deepEqual(cards.map((card) => card.label), ["本月采购已付", "等总经理确认付款", "付款审批中", "待提交付款审批"]);
  assert.deepEqual(cards.map((card) => card.value), ["¥ 3,433.10", "¥ 2,860.00", "¥ 1,221.00", "¥ 515.40"]);
  assert.equal(cards[0].sub, "2 期");
  assert.equal(cards[1].sub, "1 张 · 在总经理付款这一步");
  assert.equal(cards[3].sub, "1 期 · 采购还没提交");
  assert.deepEqual(poWorkKpis({}).map((card) => card.value), ["¥ 0.00", "¥ 0.00", "¥ 0.00", "¥ 0.00"]);

  // old payload: no po_work -> three old KPIs, none about 预付款核销
  assert.equal(hasPoWork({ summary: {} }), false);
  const legacy = procurementKpis({ summary: { month_paid_amount: 10, payment_count: 4, pending_arrival: 2, pending_inspection: 1, pending_writeoff: 9 } }, "payment");
  assert.deepEqual(legacy.map((card) => card.key), ["paid", "arrival", "inspect"]);
  assert.ok(!legacy.some((card) => card.label.includes("核销")));
});

test("po_work status rows follow the payment-instalment order and carry the count", () => {
  const work = { by_status: [["已付款", 2, 3433.1], ["待到货资料", 3, 7535.5], ["待实际付款", 1, 2860], ["未知状态", 1, 5]] };
  assert.deepEqual(poStatusRows(work), [
    ["待到货资料 · 3 期", 7535.5], ["待实际付款 · 1 期", 2860], ["已付款 · 2 期", 3433.1], ["未知状态 · 1 期", 5],
  ]);
  assert.equal(poStatusCount(work), 7);
  assert.deepEqual(poStatusRows({}), []);
});

test("per-PO progress shows received / passed lines and the paid share", () => {
  const rows = poProgressRows({ pos: [
    { po: "PO-1", supplier: "苏州精测", status: "到货验收中", lines: 3, received_lines: 2, passed_lines: 1, paid_amount: 1493.1, total_amount: 4977 },
    { po: "PO-2", supplier: "", status: "已关闭", lines: 1, received_lines: 1, passed_lines: 1, paid_amount: 1940, total_amount: 1940 },
    { po: "PO-3", status: "供应商制作中", lines: 0, received_lines: 0, passed_lines: 0, paid_amount: 0, total_amount: 0 },
  ] });
  assert.equal(rows[0].received, "2 / 3 项");
  assert.equal(rows[0].passed, "1 / 3 项");
  assert.equal(rows[0].receivedDone, false);
  assert.equal(rows[0].paidText, "¥ 1,493.10 / ¥ 4,977.00");
  assert.equal(rows[0].paidWidth, "30.0%");
  assert.equal(rows[0].tone, "p-sun");
  assert.equal(rows[1].paidWidth, "100.0%");
  assert.equal(rows[1].receivedDone, true);
  assert.equal(rows[1].tone, "p-jade");
  assert.equal(rows[1].supplier, "—");
  assert.equal(rows[2].paidWidth, "0%");
  assert.equal(rows[2].tone, "p-brand");
  assert.equal(poStatusTone("付款中"), "p-cobalt");
  assert.equal(poStatusTone("换货中"), "p-red");
});

test("arrival / inspection on the payment table are status pills, taken from the PO when it can be matched", () => {
  const work = { pos: [{ po: "PO-1", lines: 3, received_lines: 2, passed_lines: 0 }, { po: "PO-2", lines: 1, received_lines: 1, passed_lines: 1 }] };
  assert.deepEqual(paymentFulfilment({ source_purchase_order: "PO-1" }, work), {
    arrival: { text: "到货 2/3", tone: "p-sun" }, inspection: { text: "验收 0/3", tone: "p-gray" },
  });
  assert.deepEqual(paymentFulfilment({ source_purchase_order: "PO-2" }, work), {
    arrival: { text: "到货 1/1", tone: "p-jade" }, inspection: { text: "验收 1/1", tone: "p-jade" },
  });
  assert.deepEqual(paymentFulfilment({ arrival_status: "部分到货", inspection_status: "验收不合格" }, {}), {
    arrival: { text: "部分到货", tone: "p-sun" }, inspection: { text: "验收不合格", tone: "p-red" },
  });
  assert.deepEqual(paymentFulfilment({}, {}), { arrival: { text: "—", tone: "p-gray" }, inspection: { text: "—", tone: "p-gray" } });
  assert.equal(fulfilTone("已到货"), "p-jade");
  assert.equal(fulfilTone("未到货"), "p-gray");
  assert.equal(fulfilTone("待验收"), "p-sun");
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

test("due text, routes, scope and the URL tab", () => {
  assert.deepEqual(dueText({ overdue_days: 3, days_left: 0 }), { text: "逾期 3 天", tone: "p-red" });
  assert.deepEqual(dueText({ overdue_days: 0, days_left: 0 }), { text: "今天到期", tone: "p-sun" });
  assert.deepEqual(dueText({ overdue_days: 0, days_left: 7 }), { text: "7 天后到期", tone: "p-sun" });
  assert.equal(boardRoute("出差申请"), "/approval/travel");
  assert.equal(boardRoute("付款单"), "/approval/payment");
  assert.equal(scopeText({ scope: "department", department: "研发部" }), "范围：本部门（研发部）");
  assert.equal(boardTab({}), "main");
  assert.equal(boardTab({ tab: "main" }), "main");
  assert.equal(boardTab({ tab: "procurement" }), "procurement");
  assert.equal(boardTab({ tab: "nonsense" }), "main");
});

test("the bottom row reflows to two columns for a department head (no empty third column)", () => {
  assert.equal(bottomColumns({ scope: "all" }), 3);
  assert.equal(bottomColumns({}), 3);
  assert.equal(bottomColumns({ scope: "department" }), 2);
});

test("the two boards are separate pages, each with its own 采购 tab kept in the URL", () => {
  const request = read("../src/pages/RequestBoard.vue");
  const payment = read("../src/pages/PaymentBoard.vue");
  assert.match(request, /expense_board_entry\.request_board/);
  assert.match(request, /part="request"/);
  assert.match(payment, /expense_board_entry\.payment_board/);
  assert.match(payment, /part="payment"/);
  assert.doesNotMatch(request, /payment_board/);
  assert.doesNotMatch(payment, /request_board/);
  for (const source of [request, payment]) {
    assert.match(source, /boardTab\(route\.query\)/);
    assert.match(source, /router\.replace\(\{ path: route\.path, query: \{ \.\.\.route\.query, tab: value \} \}\)/);
    assert.match(source, /class="bd-kpi"/);
    assert.match(source, /openKpi\(kpi\)/);
  }
});

test("付款看板 merges the aging chart into the cashier panel, reflows the bottom row and has no month select without API support", () => {
  const payment = read("../src/pages/PaymentBoard.vue");
  assert.match(payment, /id="bd-cashier"/);
  assert.match(payment, /出纳待付款/);
  assert.match(payment, /agingTiles\(queue\.value\)/);
  assert.match(payment, /class="bd-tile"/);
  assert.doesNotMatch(payment, /ColumnChart/);
  assert.doesNotMatch(payment, /出纳待付：等了多久/);
  assert.match(payment, /bottomColumns\(data\.value\)/);
  assert.match(payment, /'bd-cols-' \+ columnCount/);
  assert.match(payment, /v-if="data\.scope !== 'department'"/);
  assert.match(payment, /@click="refresh"/);
  assert.doesNotMatch(payment, /<select/, "payment_board has no month parameter");
  assert.match(payment, /<DonutChart :rows="data\.by_account/);
  assert.match(payment, /<StackedBars/);
});

test("采购付款 tab renders po_work panels only when the server sends them", () => {
  const tab = read("../src/components/expense-ui/ProcurementTab.vue");
  assert.match(tab, /expense_board_entry\.procurement_board/);
  assert.match(tab, /hasPoWork\(data\.value\)/);
  assert.match(tab, /v-if="!isRequest && poWork"/);
  assert.match(tab, /付款期次按状态/);
  assert.match(tab, /各 PO 进度/);
  assert.match(tab, /<HBars :rows="statusRows" color="#5470C6"/);
  assert.match(tab, /paymentFulfilment\(row, poWork\.value \|\| \{\}\)/);
  assert.match(tab, /row\.fulfil\.arrival\.text/);
  assert.doesNotMatch(tab, /预付款核销/);
  assert.doesNotMatch(tab, /prepayment_writeoff_status/);
  assert.match(tab, /defineExpose\(\{ reload: load \}\)/);
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
  const queue = [{ waited_days: 0, amount: 10 }, { waited_days: 2, amount: 20 }, { waited_days: 4, amount: 30 }, { waited_days: 9, amount: 40 }, { waited_days: 9, amount: 1 }];
  const aging = agingColumns(queue);
  assert.deepEqual(aging.map((column) => column.value), [1, 1, 1, 2]);
  assert.equal(aging[3].sub, "¥ 41.00");
  assert.deepEqual(agingTiles(queue).map((tile) => [tile.label, tile.count, tile.width]), [["不到 1 天", 1, "50.0%"], ["1–3 天", 1, "50.0%"], ["3–7 天", 1, "50.0%"], ["超过 7 天", 2, "100.0%"]]);
  assert.equal(agingTiles([])[0].amount, "¥ 0.00");
  assert.deepEqual(flowBars([{ key: "submitted", count: 4 }, { key: "approved", count: 3 }]).map((row) => row.width), ["100.0%", "75.0%"]);
  assert.deepEqual(budgetBars([{ approved_amount: 1000, paid_amount: 250, reserved_amount: 100 }]).map((row) => [row.paidWidth, row.reservedWidth]), [["25.0%", "10.0%"]]);
  assert.deepEqual(waitBars([{ waited_days: 8 }, { waited_days: 2 }], 3).map((row) => [row.overdue, row.width]), [[true, "100.0%"], [false, "25.0%"]]);
});

test("the boards draw charts instead of only tables (2026-09-30)", () => {
  const request = read("../src/pages/RequestBoard.vue");
  assert.match(request, /month_mix/);
  assert.match(request, /flowBars/);
  assert.match(request, /<DonutChart/);
});
