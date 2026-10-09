import { createRouter, createWebHistory } from 'vue-router';
import { canSee, firstVisiblePath } from './lib/access';
import { stripAppPrefix } from './lib/navContext';
import { setDeniedNotice } from './lib/routeNotice';

const approvalPage = () => import('./pages/OAApprovals.vue');
const attendancePage = () => import('./pages/AttendanceCenter.vue');

const routes = [
  { path: '/', redirect: () => firstVisiblePath() },
  { path: '/dashboard', component: () => import('./pages/Dashboard.vue') },
  { path: '/personnel', component: () => import('./pages/Personnel.vue') },
  { path: '/social-insurance', component: () => import('./pages/SocialInsurance.vue') },
  { path: '/housing-fund', component: () => import('./pages/HousingFund.vue') },
  { path: '/accommodation', component: () => import('./pages/AccommodationBoard.vue') },
  { path: '/accommodation/master', component: () => import('./pages/AccommodationMaster.vue') },
  { path: '/accommodation/monthly', component: () => import('./pages/Accommodation.vue') },
  { path: '/payroll', component: () => import('./pages/Payroll.vue') },
  { path: '/projects', component: () => import('./pages/Projects.vue') },
  { path: '/ledger', redirect: '/entry' },
  { path: '/entry', component: () => import('./pages/TimesheetEntry.vue') },
  { path: '/oa', redirect: '/approval/leave' },
  // 考勤中心首页和「全部类型」的列表（看板的「今天不在岗」也落在这里）；类型各自的路径照旧。
  { path: '/approval/attendance', component: attendancePage },
  { path: '/approval/leave', component: attendancePage },
  { path: '/approval/overtime', component: attendancePage },
  { path: '/approval/overtime/:name', component: attendancePage },
  { path: '/approval/comp-time', component: attendancePage },
  { path: '/approval/comp-time/:name', component: attendancePage },
  { path: '/approval/leave/:name', name: 'leave-detail', component: attendancePage },
  { path: '/approval/procurement', component: () => import('./pages/PreRequestCenter.vue') },
  { path: '/approval/procurement/new', name: 'procurement-new', component: () => import('./pages/PreRequestCenter.vue') },
  { path: '/approval/procurement/price-approvals', name: 'procurement-price-approvals', component: () => import('./pages/PriceApprovalWorkbench.vue') },
  { path: '/approval/procurement/po', name: 'procurement-po', redirect: (to) => ({ name: 'procurement-price-approvals', query: { ...to.query, tab: 'po' } }) },
  { path: '/approval/procurement/:name/pmc-edit', name: 'procurement-pmc-edit', component: () => import('./pages/PreRequestCenter.vue') },
  { path: '/approval/procurement/:name/price-approval', name: 'procurement-price-approval', redirect: (to) => ({ name: 'procurement-price-approvals', query: { ...to.query, request: to.params.name } }) },
  { path: '/approval/procurement/:name/contract', name: 'procurement-contract', redirect: (to) => ({ name: 'procurement-price-approvals', query: { ...to.query, request: to.params.name, tab: 'po' } }) },
  { path: '/approval/direct-purchase', component: () => import('./pages/PreRequestCenter.vue') },
  { path: '/approval/direct-purchase/new', name: 'direct-purchase-new', component: () => import('./pages/PreRequestCenter.vue') },
  { path: '/approval/travel', component: () => import('./pages/TravelRequest.vue') },
  { path: '/approval/request-dashboard', component: () => import('./pages/ApprovalDashboard.vue') },
  { path: '/approval/procurement-payment', component: () => import('./pages/PaymentCenter.vue') },
  { path: '/approval/reimbursement', component: approvalPage },
  { path: '/approval/corporate-payment', redirect: '/approval/reimbursement' },
  { path: '/approval/invoice-folder', component: () => import('./pages/InvoiceFolder.vue') },
  { path: '/approval/claim', component: () => import('./pages/ClaimCenter.vue') },
  { path: '/approval/payment', component: () => import('./pages/PaymentRequestCenter.vue') },
  { path: '/approval/payment-dashboard', component: () => import('./pages/ApprovalDashboard.vue') },
  { path: '/approval/expense-request-board', component: () => import('./pages/RequestBoard.vue') },
  { path: '/approval/expense-payment-board', component: () => import('./pages/PaymentBoard.vue') },
  { path: '/approval/material-progress', component: () => import('./pages/MaterialProgress.vue') },
  { path: '/approval/purchase', component: approvalPage },
  { path: '/timesheet', component: () => import('./pages/Timesheet.vue') },
  { path: '/expense', component: () => import('./pages/ExpenseImport.vue') },
  { path: '/allocation', component: () => import('./pages/Allocation.vue') },
  { path: '/allocation-dashboard', component: () => import('./pages/AllocationDashboard.vue') },
  { path: '/foreign-rd', component: () => import('./pages/ForeignRD.vue') },
  { path: '/foreign-rd-timesheet', component: () => import('./pages/ForeignRDTimesheet.vue') },
  // 旧通知、旧收藏里的 /rayher/...、/planck-semicon/... 链接：去掉前缀后原样（含查询）打开。
  { path: '/rayher/:rest(.*)*', redirect: (to) => stripAppPrefix(to.fullPath) || '/dashboard' },
  { path: '/planck-semicon/:rest(.*)*', redirect: (to) => stripAppPrefix(to.fullPath) || '/dashboard' },
  // 地址不对：给一个说得清的页面，不再悄悄跳走。
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('./pages/NotFound.vue') },
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

// 没有权限的深链接：带回第一个能打开的页面，并留一条一次性的提示（App.vue 显示），不再悄悄换页。
router.beforeEach((to) => {
  if (to.name === 'not-found' || to.path === '/' || canSee(to.path)) return true;
  const fallback = firstVisiblePath();
  if (fallback === to.path) return true;
  setDeniedNotice(to.path, fallback);
  return { path: fallback, replace: true };
});

export default router;
