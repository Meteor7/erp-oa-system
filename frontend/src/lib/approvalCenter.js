export const APPROVAL_CENTER_ROUTES = Object.freeze({
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
});

export function isApprovalRouteEnabled(path, access = {}) {
  if (path === '/approval/purchase') return access.expense_reimbursement !== false;
  // 发票夹服务于报销和付款，任一开放即可进入。
  if (path === '/approval/invoice-folder') return access.reimbursement_request === true || access.payment_request === true;
  const config = APPROVAL_CENTER_ROUTES[path];
  if (!config) return true;
  if (config.flag === 'leave_approval' || config.flag === 'expense_reimbursement') {
    return access[config.flag] !== false;
  }
  return access[config.flag] === true;
}
