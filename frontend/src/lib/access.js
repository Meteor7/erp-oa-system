import { displayUser } from './displayBrand.js';
import { isApprovalMenuVisible, isApprovalRouteEnabled } from './approvalCenter.js';
import { GROUP_HOME_CHILDREN } from './approvalGroupPaths.js';
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
// 看板：财务和管理层看全公司，部门主管看本部门，普通员工不开放（服务端同样限制）。
const BOARD = ['System Manager', 'Accounts User', 'Rayher Business Executive', 'Department Manager'];
// 岗位也能看全公司看板（与服务端 expense_boards.SCOPE_ALL_POSITIONS 一致），比如没有看板角色的副总。
const BOARD_POSITIONS = ['finance_manager', 'finance_auditor', 'vice_manager', 'general_manager'];
const BOARD_PATHS = new Set(['/approval/expense-request-board', '/approval/expense-payment-board']);
const ROUTE_ORDER = ['/dashboard', '/personnel', '/social-insurance', '/housing-fund', '/accommodation', '/accommodation/monthly', '/accommodation/master', '/payroll', '/projects', '/entry', '/approval/leave', '/approval/procurement', '/approval/direct-purchase', '/approval/travel', '/approval/request-dashboard', '/approval/procurement-payment', '/approval/reimbursement', '/approval/invoice-folder', '/approval/claim', '/approval/payment', '/approval/expense-request-board', '/approval/expense-payment-board', '/approval/corporate-payment', '/approval/payment-dashboard', '/approval/material-progress', '/approval/purchase', '/timesheet', '/expense', '/foreign-rd', '/foreign-rd-timesheet', '/allocation', '/allocation-dashboard'];

// Temporary test-account restriction: add an account's login here to hide the sensitive HR pages
// and fields from it without changing role assignments. Nobody is hidden now (2026-10-09).
const HR_SENSITIVE_HIDDEN_USERS = new Set([]);

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
  '/approval/attendance': APPROVAL,
  '/approval/leave': APPROVAL,
  '/approval/overtime': APPROVAL,
  '/approval/comp-time': APPROVAL,
  '/approval/procurement': APPROVAL,
  '/approval/direct-purchase': APPROVAL,
  '/approval/travel': APPROVAL,
  '/approval/request-dashboard': APPROVAL,
  '/approval/procurement-payment': APPROVAL,
  '/approval/reimbursement': APPROVAL,
  '/approval/invoice-folder': APPROVAL,
  '/approval/claim': APPROVAL,
  '/approval/payment': APPROVAL,
  '/approval/corporate-payment': APPROVAL,
  '/approval/payment-dashboard': APPROVAL,
  '/approval/expense-request-board': BOARD,
  '/approval/expense-payment-board': BOARD,
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

// 与服务端 procurement_chain._require_po_view 一致（修复 2026-09-24，补上 Finance User）。
const PROCUREMENT_PO_ROLES = [...FINANCE, 'Finance User', 'Purchase User', 'Purchase Manager', 'Rayher Business Executive'];

function holdsPosition(...keys) {
  const positions = (typeof window !== 'undefined' && window.position_access) || {};
  return keys.some(key => positions[key] === true);
}

function currentLogin() {
  return String((typeof window !== 'undefined' && window.user) || '').toLowerCase();
}

export function isHrSensitiveHidden() {
  return HR_SENSITIVE_HIDDEN_USERS.has(currentLogin());
}

export function canSeeProcurementPrice() {
  return holdsPosition('pmc', 'procurement_manager', 'vice_manager')
    || myRoles().some((role) => ['System Manager', 'Purchase User', 'Purchase Manager', 'Rayher Business Executive'].includes(role));
}

export function canSeeProcurementPO() {
  return canSeeProcurementPrice() || holdsPosition('production_asset_owner')
    || myRoles().some((role) => PROCUREMENT_PO_ROLES.includes(role));
}

// 生成 PR 只有 PMC 可以（服务端 procurement_chain._require_pmc），按钮也只给 PMC 看（修复 2026-09-24）。
export function canCreateProcurementPr() {
  return holdsPosition('pmc') || myRoles().includes('System Manager');
}

export function canEditProcurementPrice() {
  if (holdsPosition('pmc')) return false;
  return holdsPosition('procurement_manager')
    || myRoles().some((role) => ['System Manager', 'Purchase User', 'Purchase Manager'].includes(role));
}

// 到货、验收、换货到货、退货发出都由生产主管登记（决定 2026-10-01；服务端 _require_production_receipt）。
// 采购不再登记验收，采购只负责合同、PO 和提交付款审批。
export function canRecordPoFulfilment() {
  return holdsPosition('production_asset_owner') || myRoles().includes('System Manager');
}

// 物料目录（分类、正式物料）由 PMC 和采购维护（服务端 procurement_materials.can_maintain_catalog）。
export function canMaintainProcurementCatalog() {
  return holdsPosition('pmc', 'procurement_manager')
    || myRoles().some((role) => ['System Manager', 'Purchase User', 'Purchase Manager'].includes(role));
}

function accessPath(path) {
  for (const base of ['/approval/leave', '/approval/overtime', '/approval/comp-time']) {
    if (path.startsWith(base + '/')) return base;
  }
  if (path === '/approval/procurement/new' || /^\/approval\/procurement\/[^/]+\/pmc-edit$/.test(path)) return '/approval/procurement';
  if (path === '/approval/direct-purchase/new') return '/approval/direct-purchase';
  return path;
}


function canSeeMaterialProgress() {
  const user = String((typeof window !== 'undefined' && (window.user || window.full_name)) || '').toLowerCase();
  return myRoles().includes('System Manager') || holdsPosition('pmc', 'procurement_manager', 'vice_manager', 'general_manager');
}

// 物料进度看板只对 PMC、采购经理、副总经理和系统管理员开放（服务端 material_progress._board_user）。
export function canOpenMaterialBoard() {
  return canSeeMaterialProgress();
}

export function canSee(path) {
  if (isHrSensitiveHidden() && (path === '/social-insurance' || path === '/housing-fund')) return false;
  // 审批中心的分组首页：下面任何一个子页面能进，首页就能进。
  if (GROUP_HOME_CHILDREN[path]) return GROUP_HOME_CHILDREN[path].some((child) => canSee(child));
  if (path === '/approval/procurement/price-approvals' || /^\/approval\/procurement\/[^/]+\/price-approval$/.test(path)) {
    return hasEnabledFeature('/approval/procurement') && (canSeeProcurementPrice() || canSeeProcurementPO());
  }
  if (path === '/approval/procurement/po' || /^\/approval\/procurement\/[^/]+\/contract$/.test(path)) {
    return hasEnabledFeature('/approval/procurement') && canSeeProcurementPO();
  }
  const normalizedPath = accessPath(path);
  if (!hasEnabledFeature(normalizedPath)) return false;
  if (normalizedPath === '/approval/material-progress') return canSeeMaterialProgress();
  if (BOARD_PATHS.has(normalizedPath) && holdsPosition(...BOARD_POSITIONS)) return true;
  const need = PAGE_ROLES[normalizedPath] || MANAGE;
  return myRoles().some((role) => need.includes(role));
}

// 菜单入口：能打开，且新旧两套里当前该显示的那一套。
export function inMenu(path) {
  if (!canSee(path)) return false;
  const access = (typeof window !== 'undefined' && window.oa_access) || {};
  return isApprovalMenuVisible(accessPath(path), access);
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
  return ROUTE_ORDER.find((path) => inMenu(path)) || '/dashboard';
}

export function roleLabel() {
  const roles = myRoles();
  if (roles.includes('System Manager')) return '总控';
  if (roles.includes('HR Manager') || roles.includes('HR User')) return 'HR';
  if (roles.includes('Accounts User')) return '财务';
  if (roles.includes('Project Owner')) return '项目负责人';
  if (roles.includes('Department Manager')) return '部门主管';
  if (roles.includes('Employee')) return '员工';
  return '普通账号';
}

export function currentUser() {
  if (typeof window === 'undefined') return '';
  return displayUser(window.full_name || window.user || '');
}
