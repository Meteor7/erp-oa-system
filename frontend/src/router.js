import { createRouter, createWebHistory } from "vue-router";
const routes = [
  { path: "/", redirect: "/dashboard" },
  { path: "/dashboard", component: () => import("./pages/Dashboard.vue") },
  { path: "/personnel", component: () => import("./pages/Personnel.vue") },
  { path: "/accommodation", component: () => import("./pages/Accommodation.vue") },
  { path: "/ledger", component: () => import("./pages/Ledger.vue") },
  { path: "/entry", component: () => import("./pages/TimesheetEntry.vue") },
  { path: "/timesheet", component: () => import("./pages/Timesheet.vue") },
  { path: "/expense", component: () => import("./pages/ExpenseImport.vue") },
  { path: "/allocation", component: () => import("./pages/Allocation.vue") },
];
export default createRouter({ history: createWebHistory("/rayher"), routes });
