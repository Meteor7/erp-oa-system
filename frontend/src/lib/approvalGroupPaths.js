// 审批中心两个分组首页的路径和它们下面的子页面。这个文件不引用别的模块，access.js 和页面都能用，不会循环引用。
export const GROUP_HOME_PATHS = Object.freeze({ request: '/approval/requests', payment: '/approval/payments' });

export const GROUP_HOME_CHILDREN = Object.freeze({
  '/approval/requests': ['/approval/procurement', '/approval/procurement/price-approvals', '/approval/direct-purchase', '/approval/travel'],
  '/approval/payments': ['/approval/procurement-payment', '/approval/reimbursement', '/approval/invoice-folder', '/approval/claim', '/approval/payment'],
});

// 原来独立的看板地址：现在并进分组首页，旧地址（通知、收藏、数据看板的链接）带着查询跳到首页。
export const BOARD_REDIRECTS = Object.freeze({
  '/approval/expense-request-board': '/approval/requests',
  '/approval/expense-payment-board': '/approval/payments',
});
