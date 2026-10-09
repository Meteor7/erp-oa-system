import test from "node:test";
import assert from "node:assert/strict";
import { nextTick, reactive, ref } from "vue";
import { bindRouteFilters, mergeQuery, queryText, sameQuery } from "../src/lib/urlFilterState.js";
import { parsePeriodParam, period, periodRouteSpec, periodScope, setPeriodScope, usePeriodFromRoute } from "../src/lib/period.js";

const settle = async () => { await nextTick(); await nextTick(); };

// 假路由：replace 同步改 route（真实 router 是异步的，这里足够验证绑定逻辑）
function fakeRouter(route) {
  const calls = [];
  return {
    calls,
    replace(to) {
      calls.push(to);
      route.path = to.path;
      route.query = to.query;
      return Promise.resolve();
    },
  };
}

function statusSpec() {
  const status = ref("active");
  const reminder = ref(false);
  return {
    status, reminder,
    spec: {
      keys: ["status", "reminder"],
      read: (query) => ({ status: queryText(query, "status") === "left" ? "left" : "active", reminder: queryText(query, "reminder") === "expiring" }),
      snapshot: () => ({ status: status.value, reminder: reminder.value }),
      apply: (state) => { status.value = state.status; reminder.value = state.reminder; },
      toQuery: (state) => ({ ...(state.status === "left" ? { status: "left" } : {}), ...(state.reminder ? { reminder: "expiring" } : {}) }),
      sources: [status, reminder],
    },
  };
}

test("queryText takes the first value, trims it, and treats missing as empty", () => {
  assert.equal(queryText({ a: " x " }, "a"), "x");
  assert.equal(queryText({ a: ["1", "2"] }, "a"), "1");
  assert.equal(queryText({}, "a"), "");
  assert.equal(queryText({ a: null }, "a"), "");
  assert.equal(queryText(undefined, "a"), "");
});

test("mergeQuery rewrites only the keys the page owns and keeps the rest (from=, room=)", () => {
  const current = { status: "left", reminder: "expiring", from: "/dashboard?tab=hr", room: "A101" };
  assert.deepEqual(mergeQuery(current, ["status", "reminder"], { status: "left" }), { status: "left", from: "/dashboard?tab=hr", room: "A101" });
  assert.deepEqual(mergeQuery(current, ["status", "reminder"], {}), { from: "/dashboard?tab=hr", room: "A101" });
  assert.deepEqual(mergeQuery({ status: "left" }, ["status"], {}), {}, "clearing every filter goes back to no params");
  assert.deepEqual(mergeQuery({}, ["rd"], { rd: "none", other: "x" }), { rd: "none" }, "keys the page does not own are never written");
  assert.deepEqual(mergeQuery({}, ["a", "b"], { a: "", b: undefined }), {});
});

test("sameQuery ignores key order, empty values and array-vs-string", () => {
  assert.equal(sameQuery({ a: "1", b: "2" }, { b: "2", a: "1" }), true);
  assert.equal(sameQuery({ a: ["1"] }, { a: "1" }), true);
  assert.equal(sameQuery({ a: "1", b: "" }, { a: "1" }), true);
  assert.equal(sameQuery({ a: "1" }, { a: "2" }), false);
  assert.equal(sameQuery({ a: "1" }, {}), false);
});

test("bindRouteFilters initialises from the address without rewriting it", async () => {
  const route = reactive({ path: "/personnel", query: { status: "left", reminder: "expiring", from: "/dashboard?tab=hr" } });
  const router = fakeRouter(route);
  const { status, reminder, spec } = statusSpec();
  bindRouteFilters({ route, router, specs: [spec] });
  assert.equal(status.value, "left");
  assert.equal(reminder.value, true);
  await settle();
  assert.equal(router.calls.length, 0, "opening the page must not add or replace a history entry");
});

test("changing a filter replaces the address, keeps foreign params, and clearing returns to no params", async () => {
  const route = reactive({ path: "/personnel", query: { reminder: "expiring", from: "/dashboard?tab=hr" } });
  const router = fakeRouter(route);
  const { status, reminder, spec } = statusSpec();
  bindRouteFilters({ route, router, specs: [spec] });

  status.value = "left";
  await settle();
  assert.deepEqual(router.calls.at(-1), { path: "/personnel", query: { status: "left", reminder: "expiring", from: "/dashboard?tab=hr" } });

  reminder.value = false;
  await settle();
  assert.deepEqual(router.calls.at(-1).query, { status: "left", from: "/dashboard?tab=hr" });
  assert.equal(router.calls.length, 2, "our own replace must not trigger another write");

  const bare = reactive({ path: "/personnel", query: { status: "left" } });
  const bareRouter = fakeRouter(bare);
  const other = statusSpec();
  bindRouteFilters({ route: bare, router: bareRouter, specs: [other.spec] });
  other.status.value = "active";
  await settle();
  assert.deepEqual(bareRouter.calls.at(-1), { path: "/personnel", query: {} });
});

test("a new address for the same page (side-bar link, dashboard link) resets the filters", async () => {
  const route = reactive({ path: "/personnel", query: { status: "left" } });
  const router = fakeRouter(route);
  const { status, reminder, spec } = statusSpec();
  bindRouteFilters({ route, router, specs: [spec] });
  assert.equal(status.value, "left");

  route.query = { reminder: "expiring" };
  await settle();
  assert.equal(status.value, "active");
  assert.equal(reminder.value, true);
  assert.equal(router.calls.length, 0, "applying the address must not write it back");

  route.query = {};
  await settle();
  assert.equal(reminder.value, false);
});

test("once the user leaves the page the filters are never written into the new page's address", async () => {
  const route = reactive({ path: "/personnel", query: {} });
  const router = fakeRouter(route);
  const { status, spec } = statusSpec();
  bindRouteFilters({ route, router, specs: [spec] });

  route.path = "/dashboard";
  route.query = { tab: "hr" };
  await settle();
  status.value = "left";
  await settle();
  assert.equal(router.calls.length, 0);
  assert.equal(status.value, "left", "the page keeps its own state; it is simply no longer bound");
});

test("parsePeriodParam only accepts YYYY-MM with a real month", () => {
  assert.equal(parsePeriodParam("2026-09"), "2026-09");
  assert.equal(parsePeriodParam(" 2026-12 "), "2026-12");
  assert.equal(parsePeriodParam(["2026-08", "x"]), "2026-08");
  for (const bad of ["2026-13", "2026-00", "2026-9", "26-09", "2026/09", "2026-09-01", "", undefined, null, "abc"]) {
    assert.equal(parsePeriodParam(bad), "", `${bad} must be ignored`);
  }
});

test("usePeriodFromRoute writes a valid ?period into the shared ref, ignores a bad one, and follows later changes", async () => {
  const now = new Date();
  const thisMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const other = thisMonth === "2026-03" ? "2026-04" : "2026-03";
  period.value = thisMonth;

  const bad = reactive({ path: "/payroll", query: { period: "2026-13" } });
  usePeriodFromRoute(bad, fakeRouter(bad));
  assert.equal(period.value, thisMonth, "an invalid period is ignored");

  setPeriodScope("year");
  const route = reactive({ path: "/payroll", query: { period: other, status: "draft" } });
  const router = fakeRouter(route);
  usePeriodFromRoute(route, router);
  assert.equal(period.value, other);
  assert.equal(periodScope.value, "month", "a link that names a month is viewed month by month");
  await settle();
  assert.equal(router.calls.length, 0);

  // 用户在页面里换月份：地址跟着变，别的参数不丢；回到本月就不再写 period
  period.value = "2026-05";
  await settle();
  assert.deepEqual(router.calls.at(-1).query, { period: "2026-05", status: "draft" });
  period.value = thisMonth;
  await settle();
  assert.deepEqual(router.calls.at(-1).query, { status: "draft" });

  period.value = thisMonth;
  setPeriodScope("month");
});

test("periodRouteSpec keeps the current period when the address has none", () => {
  const spec = periodRouteSpec();
  const before = period.value;
  assert.equal(spec.read({}).period, before);
  assert.equal(spec.read({}).fromUrl, false);
  assert.deepEqual(spec.read({ period: "2026-02" }), { period: "2026-02", fromUrl: true });
  assert.deepEqual(spec.toQuery({ period: before }), {}, "the current month is the default and is not written");
  assert.deepEqual(spec.toQuery({ period: "1999-01" }), { period: "1999-01" });
});
