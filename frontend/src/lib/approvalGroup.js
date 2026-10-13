// 审批中心的分组首页（采购/购买申请、付款申请）：我要处理的、我提交的、快捷新建；下面是原来的看板统计。
// 数据都来自各类型已有的接口（oa_entry.list_requests）和采购链路的待办汇总，这里只做汇总和整理。
import { GROUP_HOME_PATHS } from './approvalGroupPaths.js';
import { boardRoute } from './expenseBoards.js';
import { approvalWait, approveBlocker, money, shortDate, waitedDays } from './procurementView.js';
import { STUCK_AFTER_DAYS, isWaitingTooLong } from './waiting.js';

export const TODO_LIMIT = 6;
export const MINE_LIMIT = 3;
const ACTIVE = new Set(['待审批', '待办理', '待流转']);
const PAID_WAIT_INVOICE = '已付款·待补票';

export const GROUPS = Object.freeze({
  request: {
    key: 'request',
    path: GROUP_HOME_PATHS.request,
    title: '采购 / 购买申请',
    sub: '采购、购买、出差申请都在这里：我要处理的和我提交的先看，下面是申请的整体情况。',
    types: ['采购申请', '购买申请', '出差申请'],
    board: { path: '/approval/expense-request-board', legacy: '/approval/request-dashboard', title: '申请情况', note: '原来的「申请看板」，数字按你能看到的范围统计' },
    actions: [
      { label: '＋ 新建采购申请', to: { path: '/approval/procurement/new' }, primary: true },
      { label: '＋ 新建购买申请', to: { path: '/approval/direct-purchase/new' } },
      { label: '＋ 新建出差申请', to: { path: '/approval/travel', query: { view: 'new' } } },
    ],
  },
  payment: {
    key: 'payment',
    path: GROUP_HOME_PATHS.payment,
    title: '付款申请',
    sub: '采购付款、付款单、报销都在这里：我要处理的和我提交的先看，下面是付款的整体情况。',
    types: ['采购付款', '报销单', '付款单'],
    board: { path: '/approval/expense-payment-board', legacy: '/approval/payment-dashboard', title: '付款情况', note: '原来的「付款看板」，数字按你能看到的范围统计' },
    actions: [
      { label: '＋ 新建付款', to: { path: '/approval/payment', query: { view: 'new' } }, primary: true },
      { label: '＋ 新建报销', to: { path: '/approval/claim', query: { view: 'new' } } },
      { label: '发票夹', to: { path: '/approval/invoice-folder' } },
    ],
  },
});

const TONES = { 采购申请: 'g-blue', 购买申请: 'g-green', 出差申请: 'g-purple', 请购单: 'g-orange', 价格审批: 'g-orange', PO: 'g-orange', 电子用印: 'g-orange', 采购付款: 'g-teal', 报销单: 'g-teal', 付款单: 'g-teal' };
export const typeTone = (type) => TONES[String(type || '').trim()] || '';

export const isActive = (row) => ACTIVE.has(String(row?.workflow_status || ''));

// 等待天数文字：不到一天说"今天刚到"。
export function waitedText(days) {
  if (days === null || days === undefined) return '';
  return days ? `等你 ${days} 天` : '今天刚到';
}

function amountText(row) {
  const amount = Number(row?.amount || 0);
  return amount > 0 ? `¥ ${money(amount)}` : '';
}

// 一条 OA 审批待办：打开就是这张单自己的页面（和在各子页面里点开的一样）。
export function todoRow(row, { here = '', now = Date.now() } = {}) {
  const days = approvalWait(row, now) ?? 0;
  return {
    key: `oa:${row.name}`, type: row.request_type, tone: typeTone(row.request_type),
    subject: row.subject || '（无主题）', who: row.employee_name || '', dept: row.department || '',
    amount: amountText(row), node: row.current_step_label ? `现在在：${row.current_step_label}` : '',
    days, waited: waitedText(days), warn: isWaitingTooLong(days),
    to: { path: boardRoute(row.request_type), query: { request: row.name, ...(here ? { from: here } : {}) } },
    action: row.request_type === '采购申请' && approveBlocker(row) ? '补录并审批' : '去处理 →',
  };
}

// 采购链路里不是 OA 审批节点的待办（提 PR、比价、价格审批、用印、提交付款）：ProcHome 的汇总项，换成同一个行格式。
export function workRow(item, { here = '' } = {}) {
  const days = Number(item.wait || 0);
  const to = item.request
    ? { path: '/approval/procurement', query: { request: item.request, ...(here ? { from: here } : {}) } }
    : item.to;
  return {
    key: item.key, type: item.tag, tone: typeTone(item.tag) || 'g-orange', subject: item.subject, who: '', dept: '', amount: '',
    node: item.meta || '', days, waited: item.request ? waitedText(days) : '', warn: isWaitingTooLong(days), to, action: `${item.action || '处理'} →`,
  };
}

// 每一步一个小标记：已通过 ✓、现在 ●、还没到空心。
export function stepTracker(row) {
  const steps = Array.isArray(row?.steps) ? row.steps : [];
  const current = Number(row?.current_step_index);
  return steps.map((step) => {
    const status = String(step?.status || '');
    const done = status.includes('通过') || status.includes('同意') || (status.includes('办理') && !status.includes('待'));
    const now = !done && Number(step?.step_index) === current && isActive(row);
    return { text: `${step?.label || ''}${now ? '（现在）' : ''}`, cls: done ? 'done' : now ? 'cur' : 'todo', mark: done ? '✓' : now ? '●' : '' };
  });
}

export function mineRow(row, { here = '', now = Date.now() } = {}) {
  const days = waitedDays(row, now) ?? 0;
  return {
    key: `mine:${row.name}`, type: row.request_type, tone: typeTone(row.request_type), subject: row.subject || '（无主题）',
    status: row.business_status && !isActive(row) ? row.business_status : row.workflow_status, active: isActive(row),
    steps: stepTracker(row), meta: [amountText(row), row.creation ? `${shortDate(row.creation)} 提交` : '', days >= 1 && isActive(row) ? `已等 ${days} 天` : ''].filter(Boolean).join(' · '),
    to: { path: boardRoute(row.request_type), query: { request: row.name, ...(here ? { from: here } : {}) } },
    row,
  };
}

const monthOf = (value) => String(value || '').slice(0, 7);

// 整个页面要显示的东西：指标卡、待办（含筛选芯片）、我提交的在途。
// pending / mine：{ 类型: 行[] }；work：采购链路汇总（ProcHome 的 work）；
export function buildGroupHome(groupKey, { pending = {}, mine = {}, work = {}, here = '', now = Date.now(), filter = 'all', invoices = 0 } = {}) {
  const group = GROUPS[groupKey];
  const oa = group.types.flatMap((type) => (pending[type] || []).map((row) => todoRow({ ...row, request_type: row.request_type || type }, { here, now })));
  const chain = groupKey === 'request'
    ? [...(work.pr || []), ...(work.price || []), ...(work.approvals || []), ...(work.po || [])]
    : [...(work.payment || [])];
  const todo = [...oa, ...chain.map((item) => workRow(item, { here }))].sort((a, b) => b.days - a.days);
  const types = [...new Set(todo.map((row) => row.type))];
  const chips = [{ key: 'all', label: `全部 ${todo.length}`, on: filter === 'all' }].concat(
    types.map((type) => ({ key: type, label: `${type} ${todo.filter((row) => row.type === type).length}`, on: filter === type })),
  );
  const shown = filter === 'all' ? todo : todo.filter((row) => row.type === filter);

  const mineAll = group.types.flatMap((type) => (mine[type] || []).map((row) => mineRow({ ...row, request_type: row.request_type || type }, { here, now })));
  const mineActive = mineAll.filter((row) => row.active);
  const month = monthOf(new Date(now).toISOString());
  const monthCount = mineAll.filter((row) => row.row.workflow_status !== '草稿' && monthOf(row.row.creation) === month).length;
  const waitingOver = [...todo, ...mineActive.map((row) => ({ days: waitedDays(row.row, now) ?? 0 }))].filter((row) => isWaitingTooLong(row.days)).length;
  const waitInvoice = mineAll.filter((row) => row.row.business_status === PAID_WAIT_INVOICE || row.row.invoice_followup_status === '待收票').length;

  const kpis = [
    { key: 'todo', label: '待我处理', value: todo.length, unit: '张', sub: todo.length ? `最久等了 ${Math.max(0, ...todo.map((row) => row.days))} 天` : '没有需要你处理的', tone: 'hot', anchor: 'gh-todo' },
    { key: 'mine', label: '我提交的在途', value: mineActive.length, unit: '张', sub: mineActive.length ? '卡在谁手里一眼能看到' : '没有进行中的', tone: '', anchor: 'gh-mine' },
    groupKey === 'payment'
      ? { key: 'invoice', label: '待补票', value: waitInvoice, unit: '张', sub: waitInvoice ? '先付款、后补票的' : '没有要补票的', tone: '', anchor: 'gh-mine' }
      : { key: 'stale', label: `我这里卡住超过 ${STUCK_AFTER_DAYS} 天`, value: waitingOver, unit: '张', sub: waitingOver ? '待办和我提交的合计' : '没有卡住的', tone: waitingOver ? 'warn' : '', anchor: 'gh-todo' },
    { key: 'month', label: '本月我提交的', value: monthCount, unit: '张', sub: '不含草稿', tone: '', anchor: 'gh-mine' },
  ];
  return {
    kpis, chips, todoAll: todo, todo: shown.slice(0, TODO_LIMIT), todoMore: Math.max(0, shown.length - TODO_LIMIT),
    mineActive, mine: mineActive.slice(0, MINE_LIMIT), hasTodo: todo.length > 0, invoices,
  };
}

// 筛到某一类时，"全部 →"去那一类自己的待办列表；链路事项（请购单、价格审批、PO）没有单独的列表，不给。
export function listLinkFor(type) {
  const path = { 采购申请: '/approval/procurement', 购买申请: '/approval/direct-purchase', 出差申请: '/approval/travel', 报销单: '/approval/claim', 付款单: '/approval/payment' }[type];
  return path ? { path, query: { view: 'list', scope: 'todo' } } : null;
}
