import { createRouter, createWebHistory } from 'vue-router';
import { canSee, firstVisiblePath } from './lib/access';

const approvalPage = () => import('./pages/OAApprovals.vue');

const routes = [
  { path: '/', redirect: () => firstVisiblePath() },
  { path: '/dashboard', component: () => import('./pages/Dashboard.vue') },
  { path: '/personnel', component: () => import('./pages/Personnel.vue') },
  { path: '/social-insurance', component: () => import('./pages/SocialInsurance.vue') },
  { path: '/housing-fund', component: () => import('./pages/HousingFund.vue') },
  { path: '/accommodation', redirect: '/accommodation/monthly' },
  { path: '/accommodation/master', component: () => import('./pages/AccommodationMaster.vue') },
  { path: '/accommodation/monthly', component: () => import('./pages/Accommodation.vue') },
  { path: '/payroll', component: () => import('./pages/Payroll.vue') },
  { path: '/projects', component: () => import('./pages/Projects.vue') },
  { path: '/ledger', redirect: '/entry' },
  { path: '/entry', component: () => import('./pages/TimesheetEntry.vue') },
  { path: '/oa', redirect: '/approval/leave' },
  { path: '/approval/leave', component: approvalPage },
  { path: '/approval/overtime', component: approvalPage },
  { path: '/approval/overtime/:name', component: approvalPage },
  { path: '/approval/comp-time', component: approvalPage },
  { path: '/approval/comp-time/:name', component: approvalPage },
  { path: '/approval/leave/:name', name: 'leave-detail', component: approvalPage },
  { path: '/approval/procurement', component: () => import('./pages/PreRequestCenter.vue') },
  { path: '/approval/procurement/new', name: 'procurement-new', component: () => import('./pages/PreRequestCenter.vue') },
  { path: '/approval/procurement/price-approvals', name: 'procurement-price-approvals', component: () => import('./pages/PriceApprovalWorkbench.vue') },
  { path: '/approval/procurement/po', name: 'procurement-po', redirect: (to) => ({ name: 'procurement-price-approvals', query: { ...to.query, tab: 'po' } }) },
  { path: '/approval/procurement/:name/pmc-edit', name: 'procurement-pmc-edit', component: () => import('./pages/PreRequestCenter.vue') },
  { path: '/approval/procurement/:name/price-approval', name: 'procurement-price-approval', redirect: (to) => ({ name: 'procurement-price-approvals', query: { ...to.query, request: to.params.name } }) },
  { path: '/approval/procurement/:name/contract', name: 'procurement-contract', redirect: (to) => ({ name: 'procurement-price-approvals', query: { ...to.query, request: to.params.name, tab: 'po' } }) },
  { path: '/approval/direct-purchase', component: () => import('./pages/PreRequestCenter.vue') },
  { path: '/approval/direct-purchase/new', name: 'direct-purchase-new', component: () => import('./pages/PreRequestCenter.vue') },
  { path: '/approval/request-dashboard', component: () => import('./pages/ApprovalDashboard.vue') },
  { path: '/approval/procurement-payment', component: () => import('./pages/PaymentCenter.vue') },
  { path: '/approval/reimbursement', component: approvalPage },
  { path: '/approval/corporate-payment', redirect: '/approval/reimbursement' },
  { path: '/approval/payment-dashboard', component: () => import('./pages/ApprovalDashboard.vue') },
  { path: '/approval/material-progress', component: () => import('./pages/MaterialProgress.vue') },
  { path: '/approval/purchase', component: approvalPage },
  { path: '/timesheet', component: () => import('./pages/Timesheet.vue') },
  { path: '/expense', component: () => import('./pages/ExpenseImport.vue') },
  { path: '/allocation', component: () => import('./pages/Allocation.vue') },
  { path: '/allocation-dashboard', component: () => import('./pages/AllocationDashboard.vue') },
  { path: '/foreign-rd', component: () => import('./pages/ForeignRD.vue') },
  { path: '/foreign-rd-timesheet', component: () => import('./pages/ForeignRDTimesheet.vue') },
];

const LEGACY_BASE = '/rayher';
const CANONICAL_BASE = '/planck-semicon';
if (typeof window !== 'undefined') {
  const path = window.location.pathname;
  if (path === LEGACY_BASE || path.startsWith(`${LEGACY_BASE}/`)) {
    const canonicalPath = `${CANONICAL_BASE}${path.slice(LEGACY_BASE.length)}`;
    window.history.replaceState(
      window.history.state,
      '',
      `${canonicalPath}${window.location.search}${window.location.hash}`,
    );
  }
}
const router = createRouter({ history: createWebHistory(CANONICAL_BASE), routes });

router.beforeEach((to) => {
  if (to.path === '/' || canSee(to.path)) return true;
  const fallback = firstVisiblePath();
  return fallback !== to.path ? fallback : true;
});

export default router;
