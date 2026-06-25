import { ref } from "vue";
// shared accounting period (YYYY-MM) across all pages; defaults to the current
// month so the SPA targets the live period instead of a hard-coded one.
function currentPeriod() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
export const period = ref(currentPeriod());
