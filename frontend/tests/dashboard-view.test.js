import assert from "node:assert/strict";
import test from "node:test";
import {
  BLOCK_FAILED_TEXT, STACK_PALETTE, alertView, barRows, barWidth, blockView, clampPct, colRows, currentMonth, errorText, greetingFor,
  isValidMonth, kpiView, listRows, monthLabel, neighbourTab, pageView, resolveTabKey, safeColor, stackRows, tabQuery, todoView, toneClass,
} from "../src/lib/dashboardView.js";
import {
  ALERTS, BARS, BLOCK_EMPTY, BLOCK_ERROR, COLS, HOME_LEADER, HOME_NOTHING, HOME_SINGLE, HOME_TODOS_ONLY, KPIS, LIST, STACK, TODOS,
} from "./dashboard-fixture.js";

// ---------------------------------------------------------------- 问候 / 期间
test("greeting follows the hour of the day", () => {
  assert.equal(greetingFor(2), "夜深了");
  assert.equal(greetingFor(6), "上午好");
  assert.equal(greetingFor(11), "上午好");
  assert.equal(greetingFor(12), "下午好");
  assert.equal(greetingFor(17), "下午好");
  assert.equal(greetingFor(18), "晚上好");
  assert.equal(greetingFor(23), "晚上好");
});

test("months are validated and labelled", () => {
  assert.equal(currentMonth(new Date(2026, 9, 9)), "2026-10");
  assert.equal(currentMonth(new Date(2027, 0, 1)), "2027-01");
  for (const good of ["2026-10", "2026-01", "1999-12"]) assert.equal(isValidMonth(good), true, good);
  for (const bad of ["", "2026-13", "2026-00", "2026-1", "202610", null, undefined, "2026-10-01"]) assert.equal(isValidMonth(bad), false, String(bad));
  assert.equal(monthLabel("2026-10"), "2026 年 10 月");
  assert.equal(monthLabel("2026-01"), "2026 年 1 月");
  assert.equal(monthLabel("oops"), "");
});

// ---------------------------------------------------------------- 页签状态
test("the tab comes from the address when it exists, otherwise the first one", () => {
  const tabs = HOME_LEADER.tabs;
  assert.equal(resolveTabKey(tabs, "cost"), "cost");
  assert.equal(resolveTabKey(tabs, ["people", "cost"]), "people");
  assert.equal(resolveTabKey(tabs, undefined), "overview");
  assert.equal(resolveTabKey(tabs, "gone"), "overview", "a stale link falls back to the first tab");
  assert.equal(resolveTabKey([], "cost"), "");
  assert.equal(resolveTabKey(null, "cost"), "");
});

test("switching tab keeps the other parameters of the address", () => {
  assert.deepEqual(tabQuery({ period: "2026-09", tab: "cost" }, "people"), { period: "2026-09", tab: "people" });
  assert.deepEqual(tabQuery({}, "cost"), { tab: "cost" });
  assert.deepEqual(tabQuery({ a: ["x", "y"], empty: "", gone: null }, "cost"), { a: "x", tab: "cost" });
  assert.deepEqual(tabQuery(undefined, "overview"), { tab: "overview" });
});

test("arrow keys move between tabs and wrap around", () => {
  const tabs = HOME_LEADER.tabs;
  assert.equal(neighbourTab(tabs, "overview", 1), "cost");
  assert.equal(neighbourTab(tabs, "people", 1), "overview");
  assert.equal(neighbourTab(tabs, "overview", -1), "people");
  assert.equal(neighbourTab(tabs, "unknown", 1), "cost");
  assert.equal(neighbourTab([], "x", 1), "");
});

// ---------------------------------------------------------------- 小件
test("tones map to css classes and anything unknown is plain", () => {
  for (const tone of ["ok", "info", "warn", "bad", "hot"]) assert.equal(toneClass(tone), `t-${tone}`);
  for (const tone of ["", "purple", undefined, null]) assert.equal(toneClass(tone), "");
});

test("percentages are clamped and a tiny non-zero bar stays visible", () => {
  assert.equal(clampPct(150), 100);
  assert.equal(clampPct(-5), 0);
  assert.equal(clampPct("abc"), 0);
  assert.equal(clampPct(undefined), 0);
  assert.equal(clampPct("42.5"), 42.5);
  assert.equal(barWidth(0), 0);
  assert.equal(barWidth(0.3), 1.5);
  assert.equal(barWidth(50), 50);
  assert.equal(barWidth(NaN), 0);
});

test("colors that go into a style attribute are whitelisted", () => {
  assert.equal(safeColor("#8A5A1C"), "#8A5A1C");
  assert.equal(safeColor("#abc"), "#abc");
  assert.equal(safeColor("rgb(1, 2, 3)"), "rgb(1, 2, 3)");
  assert.equal(safeColor("hsl(30 80% 50% / 0.5)"), "hsl(30 80% 50% / 0.5)");
  assert.equal(safeColor("warn"), "#8A5A1C");
  assert.equal(safeColor("red; background:url(//evil)", 1), STACK_PALETTE[1]);
  assert.equal(safeColor("javascript:alert(1)", 2), STACK_PALETTE[2]);
  assert.equal(safeColor("", STACK_PALETTE.length), STACK_PALETTE[0]);
  assert.equal(safeColor(undefined, 0), STACK_PALETTE[0]);
});

test("error text prefers the server message", () => {
  assert.equal(errorText(null), "");
  assert.equal(errorText({ messages: ["没有权限"] }), "没有权限");
  assert.equal(errorText({ message: "boom" }), "boom");
  assert.equal(errorText("plain"), "plain");
});

// ---------------------------------------------------------------- 指标卡 / 提醒 / 待办
test("a kpi keeps its value, unit, sub, tone, hint, preview flag and target", () => {
  const view = kpiView(KPIS[0]);
  assert.equal(view.label, "本月费用合计");
  assert.equal(view.value, "128.6");
  assert.equal(view.unit, "万");
  assert.equal(view.sub, "较上月 +3.2%");
  assert.equal(view.preview, true);
  assert.match(view.hint, /研发分摊/);
  assert.deepEqual(view.target, { key: "cost.summary", params: { period: "2026-10" } });
  assert.equal(kpiView(KPIS[1]).toneClass, "t-hot");
  assert.equal(kpiView(KPIS[2]).toneClass, "t-bad");
  assert.equal(kpiView({ key: "k", tone: "purple" }).tone, "");
});

test("a kpi without a value shows a dash, and a missing target stays null", () => {
  assert.equal(kpiView({ key: "k", label: "x", value: "" }).value, "—");
  assert.equal(kpiView({ key: "k", label: "x", value: null }).value, "—");
  assert.equal(kpiView({ key: "k", label: "x", value: 0 }).value, "0");
  assert.equal(kpiView({}).target, null);
  assert.equal(kpiView({}).preview, false);
});

test("alerts show a plain-language level and default to info", () => {
  assert.equal(alertView(ALERTS[0]).toneLabel, "需处理");
  assert.equal(alertView(ALERTS[1]).toneLabel, "注意");
  assert.equal(alertView(ALERTS[2]).toneLabel, "提示");
  assert.equal(alertView({ tone: "weird" }).tone, "info");
  assert.equal(alertView(ALERTS[0]).toneClass, "t-bad");
  assert.equal(alertView(ALERTS[3]).target, null);
});

test("todo items default their button text and tone", () => {
  assert.equal(todoView(TODOS[0]).btn, "去审批");
  assert.equal(todoView({ kind: "x", title: "y" }).btn, "去处理");
  assert.equal(todoView({ kind: "x", title: "y" }).toneClass, "t-info");
  assert.equal(todoView(TODOS[2]).toneClass, "t-warn");
  assert.deepEqual(todoView(TODOS[1]).target, { key: "attendance.detail", params: { request: "OA-18300" } });
});

// ---------------------------------------------------------------- 四种块的行
test("bars rows carry label, value, width and tone", () => {
  const rows = barRows(BARS.rows);
  assert.equal(rows.length, 6);
  assert.deepEqual(rows[0], { label: "研发软件部", value: "24", width: 100, toneClass: "" });
  assert.equal(rows[1].toneClass, "t-info");
  assert.equal(rows[3].toneClass, "t-warn");
  assert.equal(rows[5].width, 1.5, "0.3% is still drawn");
  assert.deepEqual(barRows(undefined), []);
  assert.equal(barRows([{ label: null, value: undefined, pct: "x" }])[0].width, 0);
});

test("cols rows mark the last column and size by percentage", () => {
  const rows = colRows(COLS.rows);
  assert.equal(rows.length, 6);
  assert.equal(rows[5].last, true);
  assert.equal(rows.slice(0, 5).some((row) => row.last), false);
  assert.equal(rows[5].height, 100);
  assert.equal(rows[0].height, 70);
  assert.equal(rows[5].value, "128.6");
});

test("stack rows keep every legend entry but only coloured safe values", () => {
  const rows = stackRows(STACK.rows);
  assert.equal(rows.length, 4);
  assert.equal(rows[0].color, "#8A5A1C");
  assert.equal(rows[2].color, STACK_PALETTE[2], "an unsafe colour falls back to the palette");
  assert.equal(rows[3].width, 0);
  assert.equal(rows[0].value, "79.2 万");
  assert.ok(rows.every((row) => /^#|^rgb|^hsl/.test(row.color)));
});

test("list rows keep their own target and tone", () => {
  const rows = listRows(LIST.rows);
  assert.equal(rows.length, 4);
  assert.equal(rows[0].toneClass, "t-bad");
  assert.deepEqual(rows[0].target, { key: "personnel.expiring", params: {} });
  assert.equal(rows[1].target, null);
  assert.equal(rows[0].sub, "试用期");
  assert.equal(listRows([{ label: "a", tone: "weird" }])[0].toneClass, "");
});

test("every block type is turned into rows and keeps its header, more text and target", () => {
  for (const [block, type] of [[BARS, "bars"], [COLS, "cols"], [STACK, "stack"], [LIST, "list"]]) {
    const view = blockView(block);
    assert.equal(view.type, type);
    assert.equal(view.title, block.title);
    assert.equal(view.rows.length, block.rows.length);
    assert.equal(view.failed, false);
    assert.equal(view.empty, false);
  }
  assert.equal(blockView(BARS).more, "员工信息");
  assert.deepEqual(blockView(BARS).target, { key: "personnel.list", params: { status: "active" } });
  assert.match(blockView(BARS).hint, /在职/);
  assert.equal(blockView(STACK).target, null);
});

test("a failed block says so and shows no rows, even when the server left some in", () => {
  const view = blockView(BLOCK_ERROR);
  assert.equal(view.failed, true);
  assert.equal(view.failedText, BLOCK_FAILED_TEXT);
  assert.equal(BLOCK_FAILED_TEXT, "这一块暂时加载失败");
  assert.equal(view.empty, false);
  assert.deepEqual(view.rows, []);
  assert.deepEqual(blockView({ ...BARS, error: "x" }).rows, []);
});

test("a block without rows is empty, not failed", () => {
  const view = blockView(BLOCK_EMPTY);
  assert.equal(view.empty, true);
  assert.equal(view.failed, false);
  assert.equal(blockView({ ...BARS, rows: undefined }).empty, true);
});

test("an unknown block type has no type, so the page leaves it out", () => {
  assert.equal(blockView({ key: "x", type: "pie", rows: [{ label: "a" }] }).type, "");
  const page = pageView({ blocks: [BARS, { key: "x", type: "pie", rows: [] }, COLS] });
  assert.deepEqual(page.blocks.map((block) => block.type), ["bars", "cols"]);
});

// ---------------------------------------------------------------- 一个页签怎么摆
test("the overview of a leader puts todos and alerts side by side", () => {
  const page = pageView(HOME_LEADER.pages.overview);
  assert.equal(page.attention, "both");
  assert.equal(page.showTodos, true);
  assert.equal(page.showAlerts, true);
  assert.equal(page.todoCount, 3);
  assert.equal(page.alertCount, 4);
  assert.equal(page.kpis.length, KPIS.length);
  assert.equal(page.blocks.length, 2);
  assert.equal(page.isEmpty, false);
});

test("only the lists the role has are shown, and an empty list still shows its card", () => {
  const todosOnly = pageView(HOME_TODOS_ONLY.pages.overview);
  assert.equal(todosOnly.attention, "todos");
  assert.equal(todosOnly.showAlerts, false);
  const noTodos = pageView(HOME_SINGLE.pages.overview);
  assert.equal(noTodos.attention, "both", "has_todos / has_alerts decide, not whether anything came back");
  assert.equal(noTodos.todoCount, 0);
  assert.equal(noTodos.alertCount, 0);
  assert.equal(pageView(HOME_LEADER.pages.cost).attention, "none");
});

test("a tab with nothing in it is flagged empty; a missing page is safe", () => {
  assert.equal(pageView(HOME_NOTHING.pages.overview).isEmpty, true);
  assert.equal(pageView(undefined).isEmpty, true);
  assert.equal(pageView(null).kpis.length, 0);
  assert.equal(pageView({}).attention, "none");
});

test("the errors list of a tab is ignored by the view", () => {
  const page = pageView(HOME_LEADER.pages.overview);
  assert.equal("errors" in page, false);
  assert.ok(HOME_LEADER.pages.overview.errors.length > 0, "the fixture does carry errors");
});

test("the fixture follows the server's response shape", () => {
  for (const home of [HOME_LEADER, HOME_SINGLE, HOME_TODOS_ONLY, HOME_NOTHING]) {
    assert.deepEqual(Object.keys(home).sort(), ["generated_at", "pages", "period", "role", "tabs"]);
    for (const tab of home.tabs) {
      assert.deepEqual(Object.keys(tab).sort(), ["key", "label"]);
      assert.deepEqual(Object.keys(home.pages[tab.key]).sort(), ["alerts", "blocks", "errors", "has_alerts", "has_todos", "kpis", "todos"]);
    }
  }
  assert.deepEqual(Object.keys(KPIS[0]).sort(), ["hint", "key", "label", "preview", "sub", "target", "tone", "unit", "value"]);
  assert.deepEqual(Object.keys(ALERTS[0]).sort(), ["go", "key", "sub", "target", "title", "tone"]);
  assert.deepEqual(Object.keys(TODOS[0]).sort(), ["btn", "kind", "sub", "target", "title", "tone"]);
  for (const block of [BARS, COLS, STACK, LIST, BLOCK_ERROR]) {
    assert.deepEqual(Object.keys(block).sort(), ["error", "hint", "key", "more", "rows", "sub", "target", "title", "type"]);
  }
  assert.deepEqual(Object.keys(BARS.rows[0]).sort(), ["label", "pct", "tone", "value"]);
  assert.deepEqual(Object.keys(COLS.rows[0]).sort(), ["label", "last", "pct", "value"]);
  assert.deepEqual(Object.keys(STACK.rows[0]).sort(), ["color", "label", "pct", "value"]);
  assert.deepEqual(Object.keys(LIST.rows[0]).sort(), ["label", "sub", "target", "tone", "value"]);
});
