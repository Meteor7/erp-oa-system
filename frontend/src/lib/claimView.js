// 报销 / 付款页面结构（2026-09-30 改版）：首页分栏目 → 列表页 → 详情页；新建单独一页，分三步。
// 同一个地址，用查询参数区分页面，通知和待办里的 ?request= 链接照常打开单据详情。
import { displayStatus } from './expenseClaims.js';
import { calendarDaysSince } from './waiting.js';

export function claimView(query = {}) {
  if (query.request) return 'detail';
  if (query.view === 'new' || query.tab === 'new' || query.source || query.draft) return 'new';
  if (query.view === 'list') return 'list';
  return 'home';
}

// 距离上一次有人处理（或提交）过了几个日历日（口径见 waiting.js）；算不出来返回 null。
export function waitedDays(doc = {}, now = Date.now()) {
  const stamps = (doc.steps || []).map((step) => step.acted_on).filter(Boolean).map(String).sort();
  const since = stamps[stamps.length - 1] || doc.submitted_on || doc.creation || doc.modified;
  return calendarDaysSince(since, now);
}

export function waitText(days) {
  if (days === null || days === undefined) return '—';
  return days ? `等了 ${days} 天` : '今天';
}

// 列表页和首页上的"同意"：只给普通审批步骤。出纳要先填科目、确认付款要看清金额账户，这两种进详情页做。
export function canQuickApprove(doc = {}) {
  return Boolean(doc.can_approve) && !doc.can_edit_expense_items && doc.current_step_mode !== 'handle';
}

const BUCKETS = [
  { key: 'draft', label: '草稿', color: '#C3CAD6', match: (status) => status === '草稿' },
  { key: 'review', label: '审批中', color: '#5470C6', match: (status) => status === '审批中' },
  { key: 'topay', label: '待付款', color: '#E3B26B', match: (status) => ['待付款', '部分付款', '待办理'].includes(status) },
  { key: 'paid', label: '已付款', color: '#7FA38E', match: (status) => ['已付款', '已完结', '已完成', '已付款·待补票', '待核验', '已通过'].includes(status) },
  { key: 'back', label: '驳回 / 撤回', color: '#D98C4A', match: (status) => ['已拒绝', '已撤回'].includes(status) },
];

// "我的"栏目的状态条：按单据张数。
export function statusBuckets(docs = []) {
  const total = Math.max(1, docs.length);
  return BUCKETS.map((bucket) => {
    const rows = docs.filter((doc) => bucket.match(displayStatus(doc)));
    return {
      key: bucket.key, label: bucket.label, color: bucket.color, count: rows.length,
      amount: rows.reduce((sum, doc) => sum + Number(doc.amount || 0), 0),
      width: `${((rows.length / total) * 100).toFixed(1)}%`,
    };
  });
}

export function bucketOf(doc) {
  const status = displayStatus(doc);
  return (BUCKETS.find((bucket) => bucket.match(status)) || {}).key || '';
}

// 列表页的 ?bucket=draft|review|topay|paid|back：首页指标卡点进来时只看这一类（2026-10 导航整改）。
export const BUCKET_KEYS = Object.freeze(BUCKETS.map((bucket) => bucket.key));

export function bucketLabel(key) {
  return (BUCKETS.find((bucket) => bucket.key === key) || {}).label || '';
}

// 认不得的值当作没有筛选，不让一个拼错的参数把列表筛空。
export function normalizeBucket(value) {
  const key = Array.isArray(value) ? value[0] : value;
  return BUCKET_KEYS.includes(String(key || '')) ? String(key) : '';
}

export function filterByBucket(docs = [], key = '') {
  return key ? docs.filter((doc) => bucketOf(doc) === key) : docs;
}

export function sumDocs(docs = []) {
  return docs.reduce((sum, doc) => sum + Number(doc.amount || 0), 0);
}

// 等得最久的排前面。
export function byWait(docs = [], now = Date.now()) {
  return [...docs].sort((a, b) => (waitedDays(b, now) ?? -1) - (waitedDays(a, now) ?? -1));
}

// 审批进度（详情页右侧竖线）：已处理 / 当前 / 未到 / 驳回。
export function stepTimeline(doc = {}) {
  const current = Number(doc.current_step_index || 0);
  const active = ['待审批', '待办理'].includes(doc.workflow_status);
  return (doc.steps || []).map((step) => {
    const index = Number(step.step_index || 0);
    let state = 'todo';
    if (['已通过', '已办理'].includes(step.status)) state = 'done';
    else if (step.status === '已拒绝') state = 'rejected';
    else if (active && index === current) state = 'now';
    const when = step.acted_on ? String(step.acted_on).slice(0, 16) : '';
    return {
      key: `${index}-${step.label}`, label: String(step.label || ''), state,
      note: step.note || '',
      sub: state === 'done' ? `已${step.mode === 'handle' ? '办理' : '同意'}${when ? ' · ' + when : ''}`
        : state === 'rejected' ? `已驳回${when ? ' · ' + when : ''}`
          : state === 'now' ? '等待处理' : '',
    };
  });
}
