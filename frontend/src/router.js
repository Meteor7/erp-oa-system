import { createRouter, createWebHistory } from 'vue-router';
import { canSee, firstVisiblePath } from './lib/access';

const approvalPage = () => import('./pages/OAApprovals.vue');

const routes = [
  { path: '/', redirect: () => firstVisiblePath() },
  { path: '/dashboard', component: () => import('./pages/Dashboard.vue') },
  { path: '/personnel', component: () => import('./pages/Personnel.vue') },
  { path: '/accommodation', component: () => import('./pages/Accommodation.vue') },
  { path: '/projects', component: () => import('./pages/Projects.vue') },
  { path: '/ledger', redirect: '/entry' },
  { path: '/entry', component: () => import('./pages/TimesheetEntry.vue') },
  { path: '/oa', redirect: '/approval/leave' },
  { path: '/approval/leave', component: approvalPage },
  { path: '/approval/purchase', component: approvalPage },
  { path: '/timesheet', component: () => import('./pages/Timesheet.vue') },
  { path: '/expense', component: () => import('./pages/ExpenseImport.vue') },
  { path: '/allocation', component: () => import('./pages/Allocation.vue') },
  { path: '/allocation-dashboard', component: () => import('./pages/AllocationDashboard.vue') },
  { path: '/foreign-rd', component: () => import('./pages/ForeignRD.vue') },
  { path: '/foreign-rd-timesheet', component: () => import('./pages/ForeignRDTimesheet.vue') },
];

const router = createRouter({ history: createWebHistory('/rayher'), routes });

router.beforeEach((to) => {
  if (to.path === '/' || canSee(to.path)) return true;
  const fallback = firstVisiblePath();
  return fallback !== to.path ? fallback : true;
});

export default router;
