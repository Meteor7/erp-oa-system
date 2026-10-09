export const APPROVAL_CENTER_ROUTES = Object.freeze({
  // 考勤中心首页（请假/加班/调休合在一起看）：和三个类型页同一个功能开关。
  '/approval/attendance': { flag: 'leave_approval', label: '考勤中心' },
  '/approval/leave': { flag: 'leave_approval', label: '请假审批' },
  '/approval/overtime': { flag: 'leave_approval', label: '加班审批' },
  '/approval/comp-time': { flag: 'leave_approval', label: '调休审批' },
  '/approval/procurement': { flag: 'procurement_application', label: '采购申请' },
  '/approval/direct-purchase': { flag: 'direct_purchase_application', label: '购买申请' },
  '/approval/travel': { flag: 'travel_application', label: '出差申请' },
  '/approval/request-dashboard': { flag: 'procurement_application', label: '申请看板' },
  '/approval/procurement-payment': { flag: 'procurement_payment', label: '采购付款' },
  '/approval/reimbursement': { flag: 'expense_reimbursement', label: '付款/报销' },
  '/approval/invoice-folder': { flag: 'reimbursement_request', label: '发票夹' },
  '/approval/claim': { flag: 'reimbursement_request', label: '报销' },
  '/approval/payment': { flag: 'payment_request', label: '付款' },
  '/approval/corporate-payment': { flag: 'expense_reimbursement', label: '付款/报销（兼容地址）' },
  '/approval/payment-dashboard': { flag: 'procurement_payment', label: '付款看板' },
  '/approval/expense-request-board': { flag: 'reimbursement_request', label: '申请看板' },
  '/approval/expense-payment-board': { flag: 'payment_request', label: '付款看板' },
});

// 新流程（报销单 + 付款单）两个都启用后，旧的付款/报销页面和旧看板才从菜单里退出；
// 只开一个时旧入口还要留着，否则另一类付款没有地方提交。把站点配置关掉就回到旧入口。
export function newExpenseFlowEnabled(access = {}) {
  return access.reimbursement_request === true && access.payment_request === true;
}

const LEGACY_EXPENSE_PAGES = new Set(['/approval/reimbursement', '/approval/corporate-payment', '/approval/purchase']);
const LEGACY_BOARDS = new Set(['/approval/request-dashboard', '/approval/payment-dashboard']);
const NEW_BOARDS = new Set(['/approval/expense-request-board', '/approval/expense-payment-board']);

// 页面能不能打开。旧的付款/报销页面一直能打开：在途的旧单据（待审批、待补票、被驳回的
// 草稿）要从待办和通知链接进去走完（修复 2026-09-23，原来新流程一开就整个进不去）。
export function isApprovalRouteEnabled(path, access = {}) {
  if (LEGACY_EXPENSE_PAGES.has(path)) return access.expense_reimbursement !== false;
  // 发票夹服务于报销和付款，任一开放即可进入。
  if (path === '/approval/invoice-folder') return access.reimbursement_request === true || access.payment_request === true;
  // 新看板包含购买、出差、报销、付款和采购，任一新单据类型开放即可进入。
  if (NEW_BOARDS.has(path)) {
    return access.reimbursement_request === true || access.payment_request === true || access.travel_application === true;
  }
  const config = APPROVAL_CENTER_ROUTES[path];
  if (!config) return true;
  if (config.flag === 'leave_approval' || config.flag === 'expense_reimbursement') {
    return access[config.flag] !== false;
  }
  return access[config.flag] === true;
}

// 菜单里显示哪些入口：能打开的前提下，新旧两套只显示一套，不会出现两个"申请看板"。
export function isApprovalMenuVisible(path, access = {}) {
  if (!isApprovalRouteEnabled(path, access)) return false;
  const migrated = newExpenseFlowEnabled(access);
  if (LEGACY_EXPENSE_PAGES.has(path) || LEGACY_BOARDS.has(path)) return !migrated;
  if (NEW_BOARDS.has(path)) return migrated;
  return true;
}
