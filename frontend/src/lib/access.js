import { displayUser } from './displayBrand.js';
import { isApprovalRouteEnabled } from './approvalCenter.js';
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
const ROUTE_ORDER = ['/dashboard', '/personnel', '/social-insurance', '/housing-fund', '/accommodation/monthly', '/accommodation/master', '/payroll', '/projects', '/entry', '/approval/leave', '/approval/procurement', '/approval/direct-purchase', '/approval/request-dashboard', '/approval/procurement-payment', '/approval/reimbursement', '/approval/corporate-payment', '/approval/payment-dashboard', '/approval/material-progress', '/approval/purchase', '/timesheet', '/expense', '/foreign-rd', '/foreign-rd-timesheet', '/allocation', '/allocation-dashboard'];

// Temporary test-account restriction. Remove the account from this set to restore
// the sensitive HR pages and fields without changing role assignments.
const HR_SENSITIVE_HIDDEN_USERS = new Set(['person046@staff.example.invalid', 'person030@staff.example.invalid']);

const PAGE_ROLES = {
  '/dashboard': APPROVAL,
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
  '/approval/procurement': APPROVAL,
  '/approval/direct-purchase': APPROVAL,
  '/approval/request-dashboard': APPROVAL,
  '/approval/procurement-payment': APPROVAL,
  '/approval/reimbursement': APPROVAL,
  '/approval/corporate-payment': APPROVAL,
  '/approval/payment-dashboard': APPROVAL,
  '/approval/material-progress': [],
  '/approval/purchase': APPROVAL,
  '/timesheet': TIME_VIEW,
};

function hasEnabledFeature(path) {
  const access = (typeof window !== 'undefined' && window.oa_access) || {};
  return isApprovalRouteEnabled(path, access);
}

function myRoles() {
  return (typeof window !== 'undefined' && Array.isArray(window.roles)) ? window.roles : [];
}

const PROCUREMENT_PRICE_USERS = new Set([
  'person076@staff.example.invalid',
  'person033@staff.example.invalid',
  'person046@staff.example.invalid', 'person030@staff.example.invalid',
  'admin@staff.example.invalid',
  'administrator',
]);
const PRODUCTION_RECEIPT_USERS = new Set(['person074@staff.example.invalid']);
const PROCUREMENT_PO_ROLES = [...FINANCE, 'Purchase User', 'Purchase Manager', 'Rayher Business Executive'];

function currentLogin() {
  return String((typeof window !== 'undefined' && window.user) || '').toLowerCase();
}

export function isHrSensitiveHidden() {
  return HR_SENSITIVE_HIDDEN_USERS.has(currentLogin());
}

export function canSeeProcurementPrice() {
  return PROCUREMENT_PRICE_USERS.has(currentLogin())
    || myRoles().some((role) => ['System Manager', 'Purchase User', 'Purchase Manager', 'Rayher Business Executive'].includes(role));
}

export function canSeeProcurementPO() {
  return canSeeProcurementPrice() || PRODUCTION_RECEIPT_USERS.has(currentLogin())
    || myRoles().some((role) => PROCUREMENT_PO_ROLES.includes(role));
}

export function canEditProcurementPrice() {
  if (currentLogin() === 'person076@staff.example.invalid') return false;
  return ['person033@staff.example.invalid', 'admin@staff.example.invalid', 'administrator'].includes(currentLogin())
    || myRoles().some((role) => ['System Manager', 'Purchase User', 'Purchase Manager'].includes(role));
}

function accessPath(path) {
  if (path === '/approval/procurement/new' || /^\/approval\/procurement\/[^/]+\/pmc-edit$/.test(path)) return '/approval/procurement';
  if (path === '/approval/direct-purchase/new') return '/approval/direct-purchase';
  return path;
}

const MATERIAL_PROGRESS_USERS = new Set(['person076@staff.example.invalid', 'person033@staff.example.invalid', 'person046@staff.example.invalid', 'person030@staff.example.invalid']);

function canSeeMaterialProgress() {
  const user = String((typeof window !== 'undefined' && (window.user || window.full_name)) || '').toLowerCase();
  return myRoles().includes('System Manager') || MATERIAL_PROGRESS_USERS.has(user);
}

export function canSee(path) {
  if (isHrSensitiveHidden() && (path === '/social-insurance' || path === '/housing-fund')) return false;
  if (path === '/approval/procurement/price-approvals' || /^\/approval\/procurement\/[^/]+\/price-approval$/.test(path)) {
    return hasEnabledFeature('/approval/procurement') && (canSeeProcurementPrice() || canSeeProcurementPO());
  }
  if (path === '/approval/procurement/po' || /^\/approval\/procurement\/[^/]+\/contract$/.test(path)) {
    return hasEnabledFeature('/approval/procurement') && canSeeProcurementPO();
  }
  const normalizedPath = accessPath(path);
  if (!hasEnabledFeature(normalizedPath)) return false;
  if (normalizedPath === '/approval/material-progress') return canSeeMaterialProgress();
  const need = PAGE_ROLES[normalizedPath] || MANAGE;
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
