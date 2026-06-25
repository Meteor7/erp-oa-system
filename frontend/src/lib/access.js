// Role-aware page access for the SPA nav + route gating.
// Mirrors the backend guards: expense/allocation are finance-only; the rest
// require an R&D management role. Employees (no management role) see nothing.
const FINANCE = ["System Manager", "Accounts User"];
const HR = ["System Manager", "HR User", "HR Manager"];
const MANAGE = ["System Manager", "Accounts User", "HR User", "HR Manager"];
// HR manages people/hours; finance does expense import + allocation. The HR pages
// read Employee (report/record perms) which finance lacks, so they are HR-scoped.
const PAGE_ROLES = {
  "/expense": FINANCE, "/allocation": FINANCE,
  "/personnel": HR, "/accommodation": HR, "/ledger": HR, "/entry": HR, "/timesheet": HR,
};

function myRoles() {
  return (typeof window !== "undefined" && Array.isArray(window.roles)) ? window.roles : [];
}
export function canSee(path) {
  const need = PAGE_ROLES[path] || MANAGE;
  return myRoles().some((r) => need.includes(r));
}
