import { ref } from "vue";
import { bindRouteFilters } from "./urlFilterState.js";
// shared accounting period (YYYY-MM) across all pages; defaults to the current
// month so the SPA targets the live period instead of a hard-coded one.
function currentPeriod() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
export const period = ref(currentPeriod());
export const periodScope = ref("month");
export const PERIOD_SCOPES = [
  { value: "month", label: "\u6708\u5ea6" },
  { value: "year", label: "\u5e74\u5ea6" },
];
export function setPeriodScope(scope) {
  periodScope.value = scope === "year" ? "year" : "month";
}
export function periodYear(value = period.value) {
  return String(value || currentPeriod()).slice(0, 4);
}
export function periodScopeLabel(value = period.value, scope = periodScope.value) {
  return scope === "year" ? `${periodYear(value)}\u5e74` : value;
}

// ---------- \u4ece\u5730\u5740\u8bfb\u671f\u95f4 ----------
// \u770b\u677f\u70b9\u8fdb\u6765\u7684\u94fe\u63a5\u5e26 ?period=YYYY-MM\u3002\u53ea\u6709\u683c\u5f0f\u5408\u6cd5\uff08\u6708\u4efd 01-12\uff09\u7684\u624d\u91c7\u7528\uff0c\u5176\u4f59\u5f53\u6ca1\u5199\u3002
export function parsePeriodParam(value) {
  const first = Array.isArray(value) ? value[0] : value;
  const text = String(first ?? "").trim();
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(text) ? text : "";
}

// \u671f\u95f4\u5728\u300c\u5730\u5740 <-> \u5171\u4eab ref\u300d\u4e4b\u95f4\u7684\u89c4\u5219\uff0c\u53ef\u4ee5\u548c\u9875\u9762\u81ea\u5df1\u7684\u7b5b\u9009\u4e00\u8d77\u4ea4\u7ed9 bindRouteFilters\uff1a
// \u5730\u5740\u6ca1\u5199\u671f\u95f4\u5c31\u4fdd\u6301\u5f53\u524d\u503c\uff1b\u5f53\u524d\u671f\u95f4\u4e0d\u662f\u672c\u6708\u65f6\u624d\u5199\u8fdb\u5730\u5740\uff08\u7528\u6237\u5728\u9875\u9762\u91cc\u6362\u4e86\u6708\u4efd\uff0c\u5237\u65b0\u540e\u8fd8\u505c\u5728\u8fd9\u4e2a\u6708\uff09\u3002
export function periodRouteSpec() {
  return {
    keys: ["period"],
    read: (query) => {
      const fromUrl = parsePeriodParam(query?.period);
      return { period: fromUrl || period.value, fromUrl: Boolean(fromUrl) };
    },
    apply: (state) => {
      period.value = state.period;
      // \u94fe\u63a5\u91cc\u5199\u660e\u4e86\u67d0\u4e2a\u6708\uff0c\u5c31\u6309\u6708\u5ea6\u53e3\u5f84\u770b\uff0c\u4e0d\u6cbf\u7528\u4e4b\u524d\u9009\u7684\u300c\u5e74\u5ea6\u300d
      if (state.fromUrl) setPeriodScope("month");
    },
    snapshot: () => ({ period: period.value }),
    toQuery: (state) => (state.period && state.period !== currentPeriod() ? { period: state.period } : {}),
    sources: [period],
  };
}

// \u53ea\u6309\u671f\u95f4\u8fc7\u6ee4\u7684\u9875\u9762\uff08\u85aa\u916c\u3001\u793e\u4fdd\u3001\u516c\u79ef\u91d1\u3001\u5206\u644a\uff09\u5728 setup \u91cc\u8c03\u7528\u4e00\u6b21\u3002
export function usePeriodFromRoute(route, router) {
  bindRouteFilters({ route, router, specs: [periodRouteSpec()] });
}
