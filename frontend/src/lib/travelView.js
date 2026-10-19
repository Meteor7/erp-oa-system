// 出差申请的前端口径：出差申请在考勤中心里（AttendanceCenter，和请假、加班、调休同一个入口，地址仍是 /approval/travel），
// 这里只留考勤中心的出差表单和报销、付款里用到的几个纯函数。
// 页面（首页 / 列表 / 详情）的逻辑在 attendanceView.js / attendanceFlow.js。

// 出发、返回日期都含当天：10-08 到 10-10 是 3 天；日期不全或返回早于出发返回 0。
export function tripDays(start, end) {
  const from = Date.parse(start);
  const to = Date.parse(end);
  if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) return 0;
  return Math.round((to - from) / 86400000) + 1;
}

export function emptyTravelForm() {
  return { subject: '', travel_destination: '', travel_start_date: '', travel_end_date: '', reason: '', project: '' };
}

export function travelFormFrom(row = {}) {
  return {
    subject: row.subject || '', travel_destination: row.travel_destination || '',
    travel_start_date: row.travel_start_date || '', travel_end_date: row.travel_end_date || '',
    reason: row.reason || '', project: row.project || '',
  };
}

// 提交前还差什么（服务端仍是权威校验）。
export function travelBlockers(form = {}) {
  const messages = [];
  if (!String(form.subject || '').trim()) messages.push('主题');
  if (!String(form.travel_destination || '').trim()) messages.push('出差地点');
  if (!form.travel_start_date || !form.travel_end_date) messages.push('出发和返回日期');
  else if (!tripDays(form.travel_start_date, form.travel_end_date)) messages.push('返回日期不能早于出发日期');
  if (!String(form.reason || '').trim()) messages.push('出差事由');
  return messages;
}

// 开始填了任何一项，或者点过提交，才显示"还差"清单；一进来就满屏红字是不友好的。
export function showMissing(form = {}, attempted = false) {
  const started = ['subject', 'travel_destination', 'travel_start_date', 'travel_end_date', 'reason'].some((key) => String(form[key] || '').trim());
  return Boolean(attempted || started);
}

// 能看到所有人的出差申请（列表的"全部"栏目、申请看板上的"出差中"指标）：和考勤中心的"全部"同一批角色——
// 系统管理员、人事（HR Manager / HR User）和管理层（QIHENG Demo Business Executive）。其他人只看自己的和轮到自己审批的。
// 要和 attendance_entry.ALL_VIEW_ROLES 保持一致（服务端才是权威，这里只决定页面上给不给入口）。
const ALL_ROLES = ['System Manager', 'HR Manager', 'HR User', 'QIHENG Demo Business Executive'];

export function canSeeAllTravel(roles = globalThis.window?.roles || []) {
  return (roles || []).some((role) => ALL_ROLES.includes(role));
}

// 报销、付款里"关联出差申请"的入口：已通过的出差申请直接下推（先弹确认，确认后才生成草稿）。
export function pushTarget(kind) {
  return kind === 'claim' ? '/approval/claim' : '/approval/payment';
}
