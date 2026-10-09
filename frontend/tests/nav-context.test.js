import assert from "node:assert/strict";
import test from "node:test";
import {
  ATTENDANCE_TYPE_BY_ROUTE, approvalTodoTarget, backLocation, carryQuery, cleanQuery, deniedNoticeText, detailQuery, draftTarget,
  formQuery, fromValue, groupOwning, hereAsFrom, isInternalPath, listState, listWithout, myRequestTarget, noteTarget, originLabel,
  originOf, ownerOfPath, pushConfirmText, queueTarget, resolveKpiTarget, resolveScope, returnQuery, returnTarget, splitPath, stripAppPrefix, withFrom,
} from "../src/lib/navContext.js";
import { allowLeave, isFormDirty } from "../src/lib/leaveConfirm.js";
import { BUCKET_KEYS, bucketLabel, filterByBucket, normalizeBucket } from "../src/lib/claimView.js";
import {
  filterTravelByBucket, normalizeTravelBucket, travelBucketLabel, travelScopeInfo, travelStats,
} from "../src/lib/travelView.js";
import {
  PURCHASE_STATUS_FILTERS, filterPurchaseStatus, filterRows, normalizePurchaseStatus, normalizeStage, purchaseStatusLabel,
  stageFilterLabel, stageGroups, stageMatches,
} from "../src/lib/procurementView.js";
import { pageTitle, paymentPoLink, resolveTab } from "../src/lib/priceView.js";

// ---------------------------------------------------------------- list state in the URL

test("list state keeps only scope, status, bucket, stage, q and long, as clean strings", () => {
  assert.deepEqual(listState({ scope: "todo", bucket: "draft", q: "", stage: undefined, request: "OA-1", from: "list", long: "1" }),
    { scope: "todo", bucket: "draft", long: "1" });
  assert.deepEqual(listState({ scope: ["mine", "all"] }), { scope: "mine" });
  assert.deepEqual(cleanQuery({ a: 1, b: "", c: null, d: false, e: undefined, f: "x" }), { a: "1", f: "x" });
  assert.deepEqual(listState(undefined), {});
});

test("a detail link carries the list state and returning restores the same scope and filters (P2-4)", () => {
  const state = { scope: "todo", bucket: "review", q: "办公" };
  const detail = detailQuery("BX-1", state);
  assert.deepEqual(detail, { request: "BX-1", from: "list", scope: "todo", bucket: "review", q: "办公" });
  // back from the detail page: same page, the list with the same filters
  assert.deepEqual(backLocation("/approval/claim", detail), {
    path: "/approval/claim", query: { view: "list", scope: "todo", bucket: "review", q: "办公" },
  });
  assert.deepEqual(returnQuery(detail, { x: 1 }), { view: "list", scope: "todo", bucket: "review", q: "办公" });
});

test("a form opened from a list returns to the list (cancel / breadcrumb), otherwise to the fallback (P2-5)", () => {
  const form = formQuery({ view: "new", draft: "BX-9" }, { scope: "mine", bucket: "draft", junk: "x" });
  assert.deepEqual(form, { view: "new", draft: "BX-9", from: "list", scope: "mine", bucket: "draft" });
  assert.deepEqual(backLocation("/approval/claim", form), { path: "/approval/claim", query: { view: "list", scope: "mine", bucket: "draft" } });
  // no origin: the fallback (home)
  assert.deepEqual(backLocation("/approval/claim", { view: "new" }), { path: "/approval/claim", query: {} });
  assert.deepEqual(backLocation("/approval/procurement/new", { draft: "OA-1" }, { view: "list" }), { path: "/approval/procurement/new", query: { view: "list" } });
  // saving a draft replaces the query: the origin must survive
  assert.deepEqual(carryQuery({ view: "new", draft: "BX-9", from: "list", scope: "mine", bucket: "draft", request: "x" }),
    { from: "list", scope: "mine", bucket: "draft" });
  assert.deepEqual(carryQuery({ view: "new" }), {});
});

test("from can also point at another page (dashboard, board) and returning goes there", () => {
  const board = hereAsFrom("/approval/expense-payment-board", { tab: "procurement" });
  assert.equal(board, "/approval/expense-payment-board?tab=procurement");
  assert.deepEqual(returnTarget({ request: "PAY-1", from: board }), { path: "/approval/expense-payment-board", query: { tab: "procurement" } });
  assert.deepEqual(backLocation("/approval/payment", { request: "PAY-1", from: "/dashboard" }), { path: "/dashboard", query: {} });
  assert.equal(returnQuery({ from: "/dashboard" }), null, "workbench-internal callers must branch to router.push");
  assert.equal(originLabel({ from: "/dashboard" }), "首页");
  assert.equal(originLabel({ from: board }), "付款看板");
  assert.equal(originLabel({ from: "list" }), "列表");
  assert.equal(originLabel({}), "");
  assert.equal(hereAsFrom("/approval/travel", {}), "/approval/travel");
  assert.deepEqual(splitPath("/a/b?x=1&y=%E4%B8%AD#h"), { path: "/a/b", query: { x: "1", y: "中" } });
});

test("board -> list -> detail -> back -> back: the chain of origins is not lost", () => {
  const board = hereAsFrom("/approval/expense-payment-board", { tab: "main" });
  // 1. a KPI on the board opens the list with from=<board>
  const listQueryFromBoard = withFrom({ path: "/approval/claim", query: { view: "list", scope: "all", bucket: "paid" } }, board).query;
  assert.equal(originOf(listQueryFromBoard), board);
  // 2. a row on that list opens the detail: from=list + the list state + origin=<board>
  const state = { scope: "all", bucket: "paid", origin: originOf(listQueryFromBoard) };
  const detail = detailQuery("BX-5", state);
  assert.deepEqual(detail, { request: "BX-5", from: "list", scope: "all", bucket: "paid", origin: board });
  // 3. back from the detail: the same list, still pointing back at the board
  assert.deepEqual(backLocation("/approval/claim", detail).query, { view: "list", from: board, scope: "all", bucket: "paid" });
  // 4. back from that list: the board (with its tab)
  assert.deepEqual(backLocation("/approval/claim", backLocation("/approval/claim", detail).query), { path: "/approval/expense-payment-board", query: { tab: "main" } });
  // forms keep the origin across "save draft" (router.replace)
  assert.equal(carryQuery(formQuery({ view: "new" }, state)).origin, board);
  // removing a chip on a list opened from a board keeps the way back
  assert.equal(listWithout(listQueryFromBoard, "bucket").from, board);
  // a hostile origin is dropped
  assert.deepEqual(detailQuery("X", { scope: "mine", origin: "https://evil.example" }), { request: "X", from: "list", scope: "mine" });
});

test("from is ignored unless it is 'list' or an in-app path", () => {
  assert.equal(fromValue({ from: "list" }), "list");
  assert.equal(fromValue({ from: "/dashboard" }), "/dashboard");
  assert.equal(fromValue({ from: "https://evil.example/x" }), "");
  assert.equal(fromValue({ from: "//evil.example" }), "");
  assert.equal(fromValue({ from: "javascript:alert(1)" }), "");
  assert.equal(isInternalPath("/approval/claim?view=list"), true);
  assert.equal(isInternalPath("/x\r\ny"), false);
  assert.deepEqual(returnTarget({ from: "//evil.example" }, { view: "list" }), { query: { view: "list" } });
});

test("removing a filter chip keeps every other part of the list state", () => {
  assert.deepEqual(listWithout({ view: "list", scope: "mine", bucket: "draft", q: "x", from: "list" }, "bucket"), { view: "list", scope: "mine", q: "x" });
  assert.deepEqual(withFrom({ path: "/approval/claim", query: { view: "list" } }, "/approval/expense-payment-board"),
    { path: "/approval/claim", query: { view: "list", from: "/approval/expense-payment-board" } });
  assert.deepEqual(withFrom({ path: "/a", query: { from: "list" } }, "/b").query, { from: "list" }, "an existing origin is kept");
  assert.deepEqual(withFrom({ anchor: "x" }, "/b"), { anchor: "x", query: { from: "/b" } });
});

// ---------------------------------------------------------------- scope

test("an unauthorized scope falls back to the default WITH a visible notice (P2-7)", () => {
  const options = { allowed: ["todo", "mine"], fallback: "mine", subject: "报销单", fallbackLabel: "你的报销单" };
  assert.deepEqual(resolveScope("all", options), { scope: "mine", notice: "你没有查看全部报销单的权限，已显示你的报销单。", requested: "all" });
  assert.deepEqual(resolveScope("todo", options), { scope: "todo", notice: "", requested: "todo" });
  assert.deepEqual(resolveScope(undefined, options), { scope: "mine", notice: "", requested: "" });
  assert.match(resolveScope("nonsense", options).notice, /不认识的查看范围「nonsense」/);
  assert.equal(resolveScope("all", { ...options, allowed: ["todo", "mine", "all"] }).scope, "all");
  assert.equal(resolveScope("all", { ...options, allowed: ["todo", "mine", "all"] }).notice, "");
  assert.equal(resolveScope(["all", "mine"], { allowed: ["mine"], fallback: "mine" }).notice.startsWith("你没有查看全部"), true);
});

test("travel scope info explains why scope=all became 我的", () => {
  assert.equal(travelScopeInfo("all", false).scope, "mine");
  assert.equal(travelScopeInfo("all", false).notice, "你没有查看全部出差申请的权限，已显示你的出差申请。");
  assert.deepEqual(travelScopeInfo("all", true), { scope: "all", notice: "", requested: "all" });
  assert.equal(travelScopeInfo(undefined, false).notice, "");
});

test("KPI targets with scope=all are withheld from people who cannot open them", () => {
  const travel = { path: "/approval/travel", query: { view: "list", scope: "all" } };
  const claim = { path: "/approval/claim", query: { view: "list", scope: "all", bucket: "paid" } };
  assert.equal(resolveKpiTarget(travel, { travelAll: false, claimAll: true }), null);
  assert.equal(resolveKpiTarget(travel, { travelAll: true }), travel);
  assert.equal(resolveKpiTarget(claim, { claimAll: false }), null);
  assert.equal(resolveKpiTarget(claim, { claimAll: true }), claim);
  const mine = { path: "/approval/claim", query: { view: "list", scope: "mine" } };
  assert.equal(resolveKpiTarget(mine, {}), mine);
  assert.deepEqual(resolveKpiTarget({ anchor: "bd-budget" }, {}), { anchor: "bd-budget" });
  assert.equal(resolveKpiTarget(null, {}), null);
});

// ---------------------------------------------------------------- status filters on the lists (P2-6)

test("claim list buckets: a card that links to ?bucket= filters the list to the same documents the card counted", () => {
  const docs = [
    { name: "A", workflow_status: "草稿" },
    { name: "B", workflow_status: "待审批" },
    { name: "C", workflow_status: "已完成", business_status: "待付款" },
    { name: "D", workflow_status: "已完成", business_status: "已付款" },
  ];
  assert.deepEqual(BUCKET_KEYS, ["draft", "review", "topay", "paid", "back"]);
  assert.deepEqual(filterByBucket(docs, "draft").map((d) => d.name), ["A"]);
  assert.deepEqual(filterByBucket(docs, "review").map((d) => d.name), ["B"]);
  assert.deepEqual(filterByBucket(docs, "topay").map((d) => d.name), ["C"]);
  assert.deepEqual(filterByBucket(docs, "paid").map((d) => d.name), ["D"]);
  assert.equal(filterByBucket(docs, "").length, 4);
  assert.equal(normalizeBucket("review"), "review");
  assert.equal(normalizeBucket("bogus"), "", "a mistyped bucket must not empty the list");
  assert.equal(normalizeBucket(["draft", "x"]), "draft");
  assert.equal(bucketLabel("topay"), "待付款");
  assert.equal(bucketLabel("nope"), "");
});

test("travel list buckets and the home cards that link to them", () => {
  const docs = [
    { name: "T1", workflow_status: "草稿" },
    { name: "T2", workflow_status: "待审批" },
    { name: "T3", workflow_status: "已完成" },
  ];
  assert.deepEqual(filterTravelByBucket(docs, "approved").map((d) => d.name), ["T3"]);
  assert.deepEqual(filterTravelByBucket(docs, "draft").map((d) => d.name), ["T1"]);
  assert.equal(normalizeTravelBucket("zzz"), "");
  assert.equal(travelBucketLabel("approved"), "已通过");
  const cards = travelStats([], docs);
  assert.deepEqual(cards.map((c) => c.query.bucket), [undefined, "draft", "review", "approved"]);
  assert.ok(cards.slice(1).every((c) => c.query.scope === "mine" && c.query.view === "list"));
});

test("procurement stage groups: the exec / back cards count merged stages and the list filters the same way", () => {
  const rows = [
    { name: "1", workflow_status: "草稿" },
    { name: "2", workflow_status: "已撤回" },
    { name: "3", workflow_status: "已完成", business_status: "需求已批准", procurement_chain: { stage: "quote" } },
    { name: "4", workflow_status: "已完成", business_status: "需求已批准", procurement_chain: { stage: "po", po_numbers: ["PO-1"] } },
    { name: "5", workflow_status: "待审批" },
  ];
  const groups = stageGroups(rows);
  assert.equal(filterRows(rows, { stage: "exec" }).length, groups.exec);
  assert.equal(filterRows(rows, { stage: "back" }).length, groups.back);
  assert.deepEqual(filterRows(rows, { stage: "exec" }).map((r) => r.name), ["3", "4"]);
  assert.deepEqual(filterRows(rows, { stage: "demand" }).map((r) => r.name), ["5"]);
  assert.equal(stageMatches(rows[0], ""), true);
  assert.equal(stageMatches(rows[2], "quote"), true);
  assert.equal(stageMatches(rows[2], "po"), false);
  assert.equal(normalizeStage("exec"), "exec");
  assert.equal(normalizeStage("demand"), "demand");
  assert.equal(normalizeStage("bogus"), "");
  assert.match(stageFilterLabel("exec"), /采购执行中/);
  assert.equal(stageFilterLabel("po"), "PO 执行中");
});

test("purchase home cards link to a status, and the list applies it (购买申请 P2-6)", () => {
  const rows = [
    { name: "D1", workflow_status: "草稿" },
    { name: "R1", workflow_status: "待审批" },
    { name: "P1", workflow_status: "已完成", business_status: "待付款" },
    { name: "P2", workflow_status: "已完成", business_status: "部分付款" },
    { name: "X", workflow_status: "已完成", business_status: "已付款" },
  ];
  assert.deepEqual(PURCHASE_STATUS_FILTERS.map((f) => f.key), ["draft", "review", "topay"]);
  assert.deepEqual(filterPurchaseStatus(rows, "draft").map((r) => r.name), ["D1"]);
  assert.deepEqual(filterPurchaseStatus(rows, "review").map((r) => r.name), ["R1"]);
  assert.deepEqual(filterPurchaseStatus(rows, "topay").map((r) => r.name), ["P1", "P2"]);
  assert.equal(filterPurchaseStatus(rows, "").length, 5);
  assert.equal(normalizePurchaseStatus("topay"), "topay");
  assert.equal(normalizePurchaseStatus("junk"), "");
  assert.equal(purchaseStatusLabel("draft"), "我的草稿 / 退回");
});

// ---------------------------------------------------------------- leave confirmation

test("leaving a dirty form asks first; a clean form leaves silently (P2-5)", () => {
  let asked = 0;
  assert.equal(allowLeave(false, () => { asked += 1; return false; }), true);
  assert.equal(asked, 0);
  assert.equal(allowLeave(true, () => { asked += 1; return true; }), true);
  assert.equal(allowLeave(true, () => false), false);
  assert.equal(asked, 1);
  assert.equal(isFormDirty('{"a":1}', '{"a":1}'), false);
  assert.equal(isFormDirty('{"a":2}', '{"a":1}'), true);
});

// ---------------------------------------------------------------- sidebar

test("sidebar: detail / new / edit routes belong to the item with the longest matching prefix (P3-13)", () => {
  const targets = [
    "/approval/leave", "/approval/overtime", "/approval/comp-time",
    "/approval/procurement", "/approval/procurement/price-approvals", "/approval/direct-purchase",
    "/accommodation", "/accommodation/master", "/accommodation/monthly",
  ];
  assert.equal(ownerOfPath("/approval/procurement/new", targets), "/approval/procurement");
  assert.equal(ownerOfPath("/approval/procurement/OA-1/pmc-edit", targets), "/approval/procurement");
  assert.equal(ownerOfPath("/approval/procurement/price-approvals", targets), "/approval/procurement/price-approvals");
  assert.equal(ownerOfPath("/approval/leave/OA-9", targets), "/approval/leave");
  assert.equal(ownerOfPath("/approval/overtime/OA-9", targets), "/approval/overtime");
  assert.equal(ownerOfPath("/approval/direct-purchase/new", targets), "/approval/direct-purchase");
  assert.equal(ownerOfPath("/accommodation/master", targets), "/accommodation/master");
  assert.equal(ownerOfPath("/accommodation", targets), "/accommodation");
  assert.equal(ownerOfPath("/approval/leaves", targets), "", "a longer word is not a child path");
  assert.equal(ownerOfPath("/payroll", targets), "");
  assert.equal(ownerOfPath("/approval/leave", ["/approval/leave?view=home"]), "/approval/leave", "query strings on nav targets are ignored");
});

test("sidebar: the group owning the current path is the one that auto-expands", () => {
  const items = [
    { label: "请假/加班/调休", to: "/approval/attendance?view=home", children: [{ to: "/approval/leave" }, { to: "/approval/overtime" }, { to: "/approval/comp-time" }] },
    { label: "采购/购买申请", children: [{ to: "/approval/procurement" }, { to: "/approval/procurement/price-approvals" }, { to: "/approval/direct-purchase" }, { to: "/approval/travel" }] },
    { label: "宿舍信息管理", children: [{ to: "/accommodation" }, { to: "/accommodation/master" }, { to: "/accommodation/monthly" }] },
  ];
  assert.equal(groupOwning("/approval/procurement/OA-1/pmc-edit", items).label, "采购/购买申请");
  assert.equal(groupOwning("/approval/comp-time/OA-2", items).label, "请假/加班/调休");
  assert.equal(groupOwning("/approval/attendance", items).label, "请假/加班/调休", "the attendance home belongs to the group header");
  assert.equal(groupOwning("/accommodation/monthly", items).label, "宿舍信息管理");
  assert.equal(groupOwning("/approval/travel", items).label, "采购/购买申请");
  assert.equal(groupOwning("/dashboard", items), null);
});

// ---------------------------------------------------------------- links in notifications

test("notification links lose /planck-semicon and the old /rayher prefix and keep query and hash (P2-11)", () => {
  assert.equal(stripAppPrefix("/planck-semicon/approval/leave?request=OA-1"), "/approval/leave?request=OA-1");
  assert.equal(stripAppPrefix("/rayher/approval/claim?view=list&scope=todo"), "/approval/claim?view=list&scope=todo");
  assert.equal(stripAppPrefix("/rayher/approval/leave/OA-1#top"), "/approval/leave/OA-1#top");
  assert.equal(stripAppPrefix("/approval/travel?request=OA-3"), "/approval/travel?request=OA-3");
  assert.equal(stripAppPrefix("/planck-semicon"), "/dashboard");
  assert.equal(stripAppPrefix("/rayher"), "/dashboard");
  assert.equal(stripAppPrefix("/planck-semicon?x=1"), "/?x=1");
  assert.equal(stripAppPrefix("/rayherfoo/x"), "/rayherfoo/x", "only a whole path segment is a prefix");
  assert.equal(stripAppPrefix(""), "");
  assert.equal(stripAppPrefix("approval/leave"), "");
  assert.equal(stripAppPrefix("//evil.example/x"), "");
  assert.equal(stripAppPrefix("https://evil.example/planck-semicon/a", "erp.example"), "");
  assert.equal(stripAppPrefix("https://erp.example/planck-semicon/approval/leave?request=1", "erp.example"), "/approval/leave?request=1");
  assert.equal(stripAppPrefix("https://erp.example/planck-semicon/approval/leave"), "", "no host given: absolute URLs are not trusted");
});

test("the denied-link notice names both pages", () => {
  const label = (path) => ({ "/approval/payment": "付款", "/dashboard": "数据看板" }[path] || "");
  assert.equal(deniedNoticeText("/approval/payment", "/dashboard", label), "你没有权限打开「付款」，已回到「数据看板」。");
  assert.equal(deniedNoticeText("/secret", "/dashboard", label), "你没有权限打开「/secret」，已回到「数据看板」。");
});

// ---------------------------------------------------------------- dashboard targets

test("dashboard 审批待办 button: one request opens it, several open the list (P3-12)", () => {
  assert.deepEqual(approvalTodoTarget({ route: "/approval/overtime", count: 5, requests: ["a", "b", "c", "d", "e"] }),
    { path: "/approval/overtime", query: { view: "list", scope: "todo", from: "/dashboard" } });
  assert.deepEqual(approvalTodoTarget({ route: "/approval/overtime", count: 1, requests: ["OA-7"] }),
    { path: "/approval/overtime", query: { request: "OA-7", from: "/dashboard" } });
  assert.deepEqual(approvalTodoTarget({ route: "/approval/travel", count: 0, requests: [] }), { path: "/approval/travel", query: { from: "/dashboard" } });
  assert.equal(approvalTodoTarget({ count: 3 }), null);
  // 采购付款 has no list view: its pending payment approvals live in the approvals tab
  assert.deepEqual(approvalTodoTarget({ route: "/approval/procurement-payment", count: 2, requests: ["P-1", "P-2"] }),
    { path: "/approval/procurement-payment", query: { tab: "approvals", from: "/dashboard" } });
  assert.deepEqual(approvalTodoTarget({ route: "/approval/procurement-payment", count: 1, requests: ["P-1"] }).query, { request: "P-1", from: "/dashboard" });
  // the count says 3 but only two names were returned: still the list
  assert.equal(approvalTodoTarget({ route: "/approval/leave", count: 3, requests: ["a", "b"] }).query.view, "list");
});

test("dashboard '修改后重新提交' opens the draft in each workbench's own way (P3-12)", () => {
  assert.deepEqual(draftTarget({ route: "/approval/leave", name: "OA-1" }),
    { path: "/approval/leave", query: { view: "new", type: "请假", draft: "OA-1", from: "/dashboard" } });
  assert.equal(draftTarget({ route: "/approval/overtime", name: "OA-2" }).query.type, "加班");
  assert.equal(draftTarget({ route: "/approval/comp-time", name: "OA-3" }).query.type, "调休");
  assert.deepEqual(draftTarget({ route: "/approval/procurement", name: "OA-4" }), { path: "/approval/procurement/new", query: { draft: "OA-4", from: "/dashboard" } });
  assert.deepEqual(draftTarget({ route: "/approval/direct-purchase", name: "OA-5" }), { path: "/approval/direct-purchase/new", query: { draft: "OA-5", from: "/dashboard" } });
  for (const route of ["/approval/claim", "/approval/payment", "/approval/travel"]) {
    assert.deepEqual(draftTarget({ route, name: "X-1" }), { path: route, query: { view: "new", draft: "X-1", from: "/dashboard" } });
  }
  assert.deepEqual(draftTarget({ route: "/approval/reimbursement", name: "OA-6" }), { path: "/approval/reimbursement", query: { request: "OA-6", from: "/dashboard" } });
  assert.deepEqual(Object.keys(ATTENDANCE_TYPE_BY_ROUTE), ["/approval/leave", "/approval/overtime", "/approval/comp-time"]);
  assert.equal(draftTarget({ route: "/approval/leave" }), null);
});

test("my requests: drafts (including returned ones) go to the form, running ones to the detail", () => {
  assert.equal(myRequestTarget({ route: "/approval/claim", name: "BX-1", status: "草稿" }).query.view, "new");
  assert.deepEqual(myRequestTarget({ route: "/approval/claim", name: "BX-1", status: "待审批" }), { path: "/approval/claim", query: { request: "BX-1", from: "/dashboard" } });
  // a targeted rejection leaves the request in an approval step (not a draft): open the detail
  assert.equal(myRequestTarget({ route: "/approval/procurement", name: "OA-1", status: "待审批", returned: true }).query.request, "OA-1");
});

test("queue and note targets keep the backend's query (approval=, po=, pr=) and add the origin", () => {
  assert.deepEqual(queueTarget({ route: "/approval/procurement/price-approvals", name: "PA-1", query: { approval: "PA-1" } }),
    { path: "/approval/procurement/price-approvals", query: { approval: "PA-1", from: "/dashboard" } });
  assert.deepEqual(queueTarget({ route: "/approval/leave", name: "OA-1", query: {} }), { path: "/approval/leave", query: { request: "OA-1", from: "/dashboard" } });
  assert.deepEqual(queueTarget({ route: "/approval/leave", name: "OA-1" }).query.request, "OA-1");
  assert.deepEqual(noteTarget({ route: "/approval/material-progress", query: { request: "OA-9", source_line: "row-3" } }),
    { path: "/approval/material-progress", query: { request: "OA-9", source_line: "row-3", from: "/dashboard" } });
  assert.equal(noteTarget({ route: "", query: {} }), null);
});

// ---------------------------------------------------------------- misc

test("push-to-draft confirmation names the document type and the source", () => {
  assert.equal(pushConfirmText("claim", "OA-1"), "确定要为 OA-1 创建报销单草稿吗？");
  assert.equal(pushConfirmText("payment", "OA-1"), "确定要为 OA-1 创建付款单草稿吗？");
  assert.equal(pushConfirmText("claim"), "确定要为这张单创建报销单草稿吗？");
});

test("the queries the server puts in todo and notification links are the ones the price workbench understands (P1-1, P1-2)", () => {
  // keep in sync with overview_entry.DOC_ROUTES / _price_approval_tasks and procurement_chain._notification_link
  const everything = { canPrice: true, canPo: true };
  assert.equal(resolveTab({ approval: "PA-1" }, everything), "approvals");
  assert.equal(resolveTab({ view: "approvals", approval: "PA-7" }, everything), "approvals");
  assert.equal(resolveTab({ view: "source", pr: "PR-3" }, everything), "source");
  assert.equal(resolveTab({ tab: "po", po: "PO-5" }, everything), "po");
  // the old todo link used request=<PA name>: that is an OA procurement request filter, not a price approval
  assert.equal(resolveTab({ request: "PA-1" }, everything), "", "no tab chosen, and the page filters the whole chain by a request that does not exist");
});

test("PO payment link carries the PO; the workbench title says what the PO tab is (P2-9, P3-16)", () => {
  assert.deepEqual(paymentPoLink({ name: "PO-7" }), { path: "/approval/procurement-payment", query: { po: "PO-7" } });
  assert.deepEqual(paymentPoLink("PO-8"), { path: "/approval/procurement-payment", query: { po: "PO-8" } });
  assert.deepEqual(paymentPoLink(null), { path: "/approval/procurement-payment" });
  assert.deepEqual(paymentPoLink({}), { path: "/approval/procurement-payment" });
  assert.equal(pageTitle("po"), "价格审批 · 采购订单与合同");
  assert.equal(pageTitle("approvals"), "价格审批");
  assert.equal(pageTitle("source"), "价格审批 · PR 待比价物料");
  assert.equal(pageTitle(), "价格审批");
});
