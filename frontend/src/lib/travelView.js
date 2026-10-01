// 出差申请页面的前端口径（2026-10 改版）：首页 / 列表 / 详情 / 新建用查询参数区分，和报销、付款页一致。
//   无参数 = 首页；?view=new（可带 &draft=单号）= 新建/编辑草稿；?request=单号 = 详情；?view=list&scope=todo|mine|all = 列表。
import { displayStatus } from './expenseClaims.js';

export function travelView(query = {}) {
  if (query.request) return 'detail';
  if (query.view === 'new' || query.tab === 'new' || query.draft) return 'new';
  if (query.view === 'list') return 'list';
  return 'home';
}

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

export function monthDay(value) {
  const text = String(value || '');
  return text.length >= 10 ? text.slice(5, 10) : text;
}

export function dateRange(row = {}) {
  if (!row.travel_start_date && !row.travel_end_date) return '—';
  return `${monthDay(row.travel_start_date)} ~ ${monthDay(row.travel_end_date)}`;
}

export function waitedDays(doc = {}, now = Date.now()) {
  const stamps = (doc.steps || []).map((step) => step.acted_on).filter(Boolean).map(String).sort();
  const since = stamps[stamps.length - 1] || doc.submitted_on || doc.creation || doc.modified;
  const time = Date.parse(String(since || '').replace(' ', 'T'));
  return Number.isFinite(time) ? Math.max(0, Math.floor((now - time) / 86400000)) : null;
}

export function waitText(days) {
  if (days === null || days === undefined) return '—';
  return days ? `等了 ${days} 天` : '今天';
}

const BUCKETS = [
  { key: 'draft', label: '草稿', color: '#C3CAD6', match: (status) => status === '草稿' },
  { key: 'review', label: '审批中', color: '#5470C6', match: (status) => status === '审批中' },
  { key: 'approved', label: '已通过', color: '#7FA38E', match: (status) => ['已完成', '已通过', '已付款', '已完结'].includes(status) },
  { key: 'back', label: '驳回 / 撤回', color: '#D98C4A', match: (status) => ['已拒绝', '已撤回'].includes(status) },
];

export function travelBucketOf(doc) {
  const status = displayStatus(doc);
  return (BUCKETS.find((bucket) => bucket.match(status)) || {}).key || '';
}

// "我的出差"的状态条：按张数。
export function travelBuckets(docs = []) {
  const total = Math.max(1, docs.length);
  return BUCKETS.map((bucket) => {
    const count = docs.filter((doc) => travelBucketOf(doc) === bucket.key).length;
    return { key: bucket.key, label: bucket.label, color: bucket.color, count, width: `${((count / total) * 100).toFixed(1)}%` };
  });
}

// 首页四张卡：待我审批 / 我的草稿 / 我的审批中 / 我的已通过（还没报销或付款的单独提示）。
export function travelStats(todo = [], mine = [], now = Date.now()) {
  const of = (key) => mine.filter((doc) => travelBucketOf(doc) === key);
  const longest = Math.max(0, ...todo.map((doc) => waitedDays(doc, now) || 0));
  const review = of('review');
  const approved = of('approved');
  return [
    { key: 'todo', label: '待我审批', count: todo.length, hint: todo.length ? `最久等了 ${longest} 天` : '没有要审批的', tone: '#D98C4A', query: { view: 'list', scope: 'todo' } },
    { key: 'draft', label: '我的 · 草稿', count: of('draft').length, hint: '继续编辑后提交', tone: '#C3CAD6', query: { view: 'list', scope: 'mine' } },
    { key: 'review', label: '我的 · 审批中', count: review.length, hint: review[0]?.current_step_label ? `在 ${review[0].current_step_label}` : '点进去看卡在谁那里', tone: '#5470C6', query: { view: 'list', scope: 'mine' } },
    { key: 'approved', label: '我的 · 已通过', count: approved.length, hint: '可下推报销或付款', tone: '#7FA38E', query: { view: 'list', scope: 'mine' } },
  ];
}

// 列表页的栏目：待我审批对每个人都开放（审批人原来只能从待办链接进来）；全部只给能看到别人单据的角色。
const ALL_ROLES = ['System Manager', 'Accounts User', 'Rayher Business Executive', 'Department Manager', 'HR Manager'];
const ALL_POSITIONS = ['vice_manager', 'general_manager', 'finance_manager'];

export function canSeeAllTravel(roles = globalThis.window?.roles || [], positions = globalThis.window?.position_access || {}) {
  return (roles || []).some((role) => ALL_ROLES.includes(role)) || ALL_POSITIONS.some((key) => positions?.[key] === true);
}

export function travelScopes({ canAll = false, todoCount = 0 } = {}) {
  return [
    { key: 'mine', label: '我的' },
    { key: 'todo', label: '待我审批', count: todoCount },
    ...(canAll ? [{ key: 'all', label: '全部（管理层）' }] : []),
  ];
}

export function normalizeScope(scope, canAll = false) {
  const value = String(scope || '');
  if (value === 'todo' || value === 'mine') return value;
  if (value === 'all' && canAll) return 'all';
  return 'mine';
}

// 列表每行最右边的操作：草稿继续编辑；审批中且能撤回就撤回；已完成下推；其余看详情。
export function rowAction(row = {}, own = true) {
  if (row.workflow_status === '草稿' && own) return 'edit';
  if (row.workflow_status === '已完成' && own) return 'push';
  if (row.can_withdraw) return 'withdraw';
  return 'detail';
}

export function canPushTravel(doc = {}, own = false) {
  return own && doc.workflow_status === '已完成';
}

export function pushTarget(kind) {
  return kind === 'claim' ? '/approval/claim' : '/approval/payment';
}

// 详情页右边的审批进度：谁在什么时候做了什么、写了什么意见。
export function travelTimeline(doc = {}) {
  const current = Number(doc.current_step_index || 0);
  const active = ['待审批', '待办理'].includes(doc.workflow_status);
  return (doc.steps || []).map((step) => {
    const index = Number(step.step_index || 0);
    let state = 'todo';
    if (['已通过', '已办理'].includes(step.status)) state = 'done';
    else if (step.status === '已拒绝') state = 'rejected';
    else if (active && index === current) state = 'now';
    const when = step.acted_on ? String(step.acted_on).slice(0, 16) : '';
    // 后端给了姓名就显示姓名，没有（旧数据）才退回账号。
    const accounts = Array.isArray(step.approved_by) ? step.approved_by.filter(Boolean).join('、') : '';
    const names = Array.isArray(step.approved_by_names) ? step.approved_by_names.filter(Boolean).join('、') : '';
    const who = String(step.action_by_name || '').trim() || String(step.action_by || '').trim() || names || accounts;
    const verb = state === 'done' ? `已${step.mode === 'handle' ? '办理' : '同意'}` : state === 'rejected' ? '已驳回' : state === 'now' ? '等待处理' : '';
    return {
      key: `${index}-${step.label}`, label: String(step.label || ''), state, note: String(step.note || ''),
      who, when, sub: [verb, who, when].filter(Boolean).join(' · '),
    };
  });
}

// 单据已经变化（别人先处理了、被撤回过）：页面要重新加载。
export function isStaleError(error) {
  return /单据已经变化|页面版本过旧/.test(String(error?.message || error || ''));
}

// 同意 / 驳回 / 撤回的接口参数。
export function approveArgs(doc, action, note = '') {
  return {
    name: doc.name, action, note: action === 'reject' ? String(note || '').trim() : '',
    reject_target: action === 'reject' ? 'applicant' : undefined,
    expected_step_key: doc.current_step_key || '',
  };
}

export function rejectProblem(note) {
  return String(note || '').trim() ? '' : '请填写驳回原因';
}
