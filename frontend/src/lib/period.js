import { ref } from "vue";
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
