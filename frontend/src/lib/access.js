import { displayUser } from './displayBrand.js';
// Role-aware page access for the SPA nav + route gating.
// Expense/allocation stay finance-only; HR pages stay HR-only.
// Employees and department supervisors can use the R&D timesheet entry and approval pages.
const FINANCE = ['System Manager', 'Accounts User'];
const FOREIGN_RD_ACCESS = [...FINANCE, 'All Project Access'];
const HR = ['System Manager', 'HR User', 'HR Manager'];
const MANAGE = ['System Manager', 'Accounts User', 'HR User', 'HR Manager'];
const PROJECT_ACCESS = [...MANAGE, 'Project Owner'];
const TIME_MANAGE = ['System Manager', 'HR User', 'HR Manager', 'Department Manager'];
const TIME_ENTRY = [...TIME_MANAGE, 'Employee'];
const TIME_VIEW = [...TIME_ENTRY, 'Accounts User', 'Employee'];
const APPROVAL = ['System Manager', 'Accounts User', 'HR User', 'HR Manager', 'Department Manager', 'Employee'];
const ROUTE_ORDER = ['/dashboard', '/personnel', '/social-insurance', '/housing-fund', '/accommodation/monthly', '/accommodation/master', '/payroll', '/projects', '/entry', '/approval/leave', '/approval/purchase', '/timesheet', '/expense', '/foreign-rd', '/foreign-rd-timesheet', '/allocation', '/allocation-dashboard'];

const PAGE_ROLES = {
  '/expense': FINANCE,
  '/allocation': FINANCE,
  '/allocation-dashboard': FINANCE,
  '/foreign-rd': FOREIGN_RD_ACCESS,
  '/foreign-rd-timesheet': FOREIGN_RD_ACCESS,
  '/personnel': HR,
  '/social-insurance': HR,
  '/housing-fund': HR,
  '/accommodation': HR,
  '/accommodation/master': HR,
  '/accommodation/monthly': HR,
  '/payroll': HR,
  '/projects': PROJECT_ACCESS,
  '/ledger': [],
  '/entry': TIME_VIEW,
  '/oa': APPROVAL,
  '/approval/leave': APPROVAL,
  '/approval/purchase': APPROVAL,
  '/timesheet': TIME_VIEW,
};

const OA_FLAG_BY_PATH = {
  '/approval/leave': 'leave_approval',
  '/approval/purchase': 'expense_reimbursement',
};

function hasEnabledFeature(path) {
  const flag = OA_FLAG_BY_PATH[path];
  if (!flag) return true;
  const access = (typeof window !== 'undefined' && window.oa_access) || {};
  return access[flag] !== false;
}

function myRoles() {
  return (typeof window !== 'undefined' && Array.isArray(window.roles)) ? window.roles : [];
}

export function canSee(path) {
  if (!hasEnabledFeature(path)) return false;
  const need = PAGE_ROLES[path] || MANAGE;
  return myRoles().some((role) => need.includes(role));
}

export function canAdministerProjects() {
  return myRoles().some((role) => MANAGE.includes(role));
}

export function canEditTimesheetEntry() {
  const roles = myRoles();
  if (roles.some((role) => TIME_MANAGE.includes(role))) return true;
  if (roles.includes('Accounts User')) return false;
  return roles.includes('Employee');
}

export function firstVisiblePath() {
  return ROUTE_ORDER.find((path) => canSee(path)) || '/dashboard';
}

export function roleLabel() {
  const roles = myRoles();
  if (roles.includes('System Manager')) return '\u603b\u63a7';
  if (roles.includes('HR Manager') || roles.includes('HR User')) return 'HR';
  if (roles.includes('Accounts User')) return '\u8d22\u52a1';
  if (roles.includes('Project Owner')) return '\u9879\u76ee\u8d1f\u8d23\u4eba';
  if (roles.includes('Department Manager')) return '\u90e8\u95e8\u4e3b\u7ba1';
  if (roles.includes('Employee')) return '\u5458\u5de5';
  return '\u666e\u901a\u8d26\u53f7';
}

export function currentUser() {
  if (typeof window === 'undefined') return '';
  return displayUser(window.full_name || window.user || '');
}
