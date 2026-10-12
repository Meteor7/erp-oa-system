// 采购申请 / 购买申请页面逻辑（2026-09-30 改版）：首页 → 列表 → 详情；新建、PMC 补录单独一页。
// 同一个地址用查询参数区分页面，通知里的 ?request= 链接照常打开单据详情。
// 这里只放不依赖页面的纯函数，方便单元测试。
import { validateProcurementRequestForm } from './procurementWorkflow.js';

export const REQUEST_PROCUREMENT = '采购申请';
export const REQUEST_DIRECT = '购买申请';
export const PAGE_SIZE = 50;
export const LIST_LIMIT = 200;
// 与后端 approval_center.FIXED_ASSET_CATEGORIES 一致（只有购买申请需要选类别；采购申请只分固定 / 非固定）。
export const FIXED_ASSET_CATEGORIES = Object.freeze([
  '办公家具、工具及器具',
  '电子设备、研发专用设备、仪器仪表',
  '生产设备、生产工具及器具',
]);
export const ACTIVE_STATUSES = Object.freeze(['待审批', '待办理']);

// ---------------------------------------------------------------- 路由
export function requestTypeForPath(path = '') {
  return String(path).startsWith('/approval/direct-purchase') ? REQUEST_DIRECT : REQUEST_PROCUREMENT;
}

export function basePathFor(requestType) {
  return requestType === REQUEST_DIRECT ? '/approval/direct-purchase' : '/approval/procurement';
}

export function procurementView(route = {}) {
  const query = route.query || {};
  const path = String(route.path || '');
  if (route.name === 'procurement-pmc-edit' || /\/pmc-edit$/.test(path)) return 'pmc-edit';
  if (['procurement-new', 'direct-purchase-new'].includes(route.name) || /\/new$/.test(path)) return 'new';
  if (query.request) return 'detail';
  if (query.view === 'list') return 'list';
  return 'home';
}

export function listScope(query = {}, fallback = 'mine') {
  return ['todo', 'mine', 'all', 'owned'].includes(query.scope) ? query.scope : fallback;
}

// 我负责的项目里别人提的申请（项目负责人只读可见，不含草稿；自己提的算“我提交的”，不在这里重复）。
export function ownedRows(rows, user, employee = '') {
  const me = String(user || '').toLowerCase();
  if (!me) return [];
  return (rows || []).filter((row) => String(row?.project_owner || '').toLowerCase() === me
    && String(row?.owner || '').toLowerCase() !== me && !(employee && row?.employee === employee) && row?.workflow_status !== '草稿');
}

// ---------------------------------------------------------------- 阶段
export const CHAIN_STAGES = Object.freeze([
  { key: 'demand', label: '需求审批' },
  { key: 'await_pr', label: '等待提 PR' },
  { key: 'quote', label: '询价比价' },
  { key: 'price', label: '价格审批' },
  { key: 'po', label: 'PO 执行中' },
  { key: 'closed', label: '已关闭' },
]);

export const STAGES = Object.freeze({
  draft: { key: 'draft', label: '草稿', tone: 'p-gray', index: -1 },
  withdrawn: { key: 'withdrawn', label: '已撤回', tone: 'p-gray', index: -1 },
  rejected: { key: 'rejected', label: '已驳回', tone: 'p-red', index: -1 },
  cancelled: { key: 'cancelled', label: '已取消', tone: 'p-gray', index: -1 },
  demand: { key: 'demand', label: '需求审批', tone: 'p-cobalt', index: 0 },
  await_pr: { key: 'await_pr', label: '等待提 PR', tone: 'p-sun', index: 1 },
  quote: { key: 'quote', label: '询价比价', tone: 'p-sun', index: 2 },
  price: { key: 'price', label: '价格审批', tone: 'p-cobalt', index: 3 },
  po: { key: 'po', label: 'PO 执行中', tone: 'p-brand', index: 4 },
  closed: { key: 'closed', label: '已关闭', tone: 'p-jade', index: 5 },
});

// 筛选下拉里的阶段，顺序固定。
export const STAGE_FILTERS = Object.freeze([
  'demand', 'await_pr', 'quote', 'price', 'po', 'closed', 'withdrawn', 'rejected', 'draft',
].map((key) => ({ key, label: STAGES[key].label })));

// 首页指标卡"采购执行中""退回 / 已撤回"合并了好几个阶段；点进列表要按合并后的口径筛，不能再只是"全部"（2026-10 导航整改）。
export const STAGE_GROUPS = Object.freeze({
  back: Object.freeze(['draft', 'withdrawn', 'rejected']),
  exec: Object.freeze(['await_pr', 'quote', 'price', 'po']),
});
export const STAGE_GROUP_FILTERS = Object.freeze([
  { key: 'exec', label: '采购执行中（提 PR / 比价 / 价格审批 / PO）' },
  { key: 'back', label: '草稿 / 退回 / 已撤回' },
]);

// 旧版（合同 / 到货 / 验收都在申请单上走）遗留数据的业务状态：这些单据只读展示，归入 PO 执行中。
const LEGACY_EXEC = new Set([
  '价格已批准/待补充合同信息', '待采购复核', '待电子用印', '合同已生效', '付款计划已生成', '采购执行中',
  '待到货', '部分到货', '待验收', '验收通过', '验收不合格', '预付款逾期', '催办中', '换货中', '供应商退款中', '退货中',
  '待价格审批',
]);

export function isActive(row) {
  return ACTIVE_STATUSES.includes(String(row?.workflow_status || ''));
}

// 草稿有三种：新建的、被撤回的、被驳回回来的。
export function draftKind(row) {
  if (String(row?.workflow_status || '') !== '草稿') return '';
  if (row?.business_status === '已撤回' || row?.workflow_status_label === '已撤回') return 'withdrawn';
  const log = Array.isArray(row?.operation_log) ? row.operation_log : [];
  const last = log[log.length - 1];
  if (last && /驳回|退回/.test(String(last.action || ''))) return 'rejected';
  return 'draft';
}

export function stageKey(row) {
  const workflow = String(row?.workflow_status || '');
  const business = String(row?.business_status || '');
  if (workflow === '草稿') return draftKind(row);
  if (workflow === '已拒绝') return 'rejected';
  if (workflow === '已撤回' || business === '已撤回') return 'withdrawn';
  if (workflow === '已取消' || business === '已取消') return 'cancelled';
  if (isActive(row)) return 'demand';
  const chain = row?.procurement_chain || {};
  if (workflow === '已完成' || business.startsWith('需求已批准')) {
    if (business === '已关闭') return 'closed';
    const hasLinks = (chain.pr_numbers || []).length || (chain.price_approval_numbers || []).length || (chain.po_numbers || []).length;
    if (!hasLinks && LEGACY_EXEC.has(business)) return 'po';
    return STAGES[chain.stage] && chain.stage !== 'demand' ? chain.stage : 'await_pr';
  }
  return 'demand';
}

export function stageOf(row) {
  return STAGES[stageKey(row)] || STAGES.demand;
}

// 购买申请没有采购链，只有一条审批：草稿 / 审批中 / 已批准后的业务状态。
const PURCHASE_TONES = {
  草稿: 'p-gray', 已撤回: 'p-gray', 已取消: 'p-gray',
  审批中: 'p-cobalt', 待审批: 'p-cobalt', 待办理: 'p-cobalt',
  待付款: 'p-sun', 部分付款: 'p-sun',
  已付款: 'p-jade', 已完成: 'p-jade', 已通过: 'p-jade', 已完结: 'p-jade',
  已拒绝: 'p-red', 已驳回: 'p-red',
};

export function purchaseStatus(row) {
  const workflow = String(row?.workflow_status || '');
  let label;
  if (workflow === '草稿') label = { withdrawn: '已撤回', rejected: '已驳回' }[draftKind(row)] || '草稿';
  else if (isActive(row)) label = '审批中';
  else if (workflow === '已拒绝') label = '已拒绝';
  else label = String(row?.business_status || workflow || '');
  return { label, tone: PURCHASE_TONES[label] || 'p-gray' };
}

// 列表和详情统一用这个：采购申请看采购链阶段，购买申请看审批状态。
export function statusOf(row) {
  if (row?.request_type === REQUEST_DIRECT) return purchaseStatus(row);
  const stage = stageOf(row);
  return { label: stage.label, tone: stage.tone, key: stage.key };
}

export function stageIndex(row) {
  return stageOf(row).index;
}

// ---------------------------------------------------------------- 时间
export function waitedDays(row = {}, now = Date.now()) {
  const stamps = (row.steps || []).map((step) => step.acted_on).filter(Boolean).map(String).sort();
  const since = stamps[stamps.length - 1] || row.submitted_on || row.modified || row.creation;
  const time = Date.parse(String(since || '').replace(' ', 'T'));
  return Number.isFinite(time) ? Math.max(0, Math.floor((now - time) / 86400000)) : null;
}

// 只有还在审批中的单据才算"等待"。
export function approvalWait(row, now = Date.now()) {
  return isActive(row) ? waitedDays(row, now) : null;
}

export function waitText(days) {
  if (days === null || days === undefined) return '—';
  return days ? `等了 ${days} 天` : '今天';
}

export function longestWait(rows = [], now = Date.now()) {
  return Math.max(0, ...rows.map((row) => waitedDays(row, now) || 0));
}

export function formatDateTime(value) {
  if (!value) return '—';
  return String(value).replace('T', ' ').slice(0, 16);
}

export function shortDate(value) {
  const text = String(value || '').slice(0, 10);
  const match = text.match(/^\d{4}-(\d{2})-(\d{2})$/);
  return match ? `${Number(match[1])} 月 ${Number(match[2])} 日` : text;
}

export function money(value) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function quantityText(value) {
  return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 });
}

// ---------------------------------------------------------------- 队列
// 页面规则：有全局权限的角色看全部；其余人看"我提交的 + 轮到我审批的"，按单号去重。
export function mergeRows(requestType, ...lists) {
  const seen = new Map();
  for (const rows of lists) {
    for (const row of rows || []) {
      if (!row || (requestType && row.request_type !== requestType)) continue;
      if (!seen.has(row.name)) seen.set(row.name, row);
    }
  }
  return [...seen.values()].sort((a, b) => String(b.modified || '').localeCompare(String(a.modified || '')));
}

export function allocationLabel(row, projectName = (name) => name) {
  if (row?.project) return `项目 · ${projectName(row.project)}`;
  if (row?.non_project_cost_center) return `成本中心 · ${row.non_project_cost_center}`;
  if (row?.non_project_department) return `部门 · ${row.non_project_department}`;
  return row?.non_project_allocation_type || '非项目';
}

// 采购申请的费用类别：项目采购一律是研发费用；非项目采购按所选部门的性质（部门列表由后端给出，和后端同一份对应关系）。
export function expenseCategoryOf(form = {}, departments = []) {
  if (form.procurement_scope === '项目采购') return '研发费用';
  return departments.find((item) => item.name === form.non_project_department)?.category || '';
}

export function projectText(row, projectName = (name) => name) {
  if (row?.project) return projectName(row.project);
  if (row?.non_project_department) return `非项目 · ${row.non_project_department}`;
  if (row?.non_project_cost_center) return `非项目 · ${row.non_project_cost_center}`;
  return '非项目';
}

export function projectOptions(rows = [], projectName = (name) => name) {
  const names = [...new Set(rows.map((row) => row.project).filter(Boolean))];
  const options = names.map((name) => ({ key: name, label: projectName(name) }))
    .sort((a, b) => String(a.label).localeCompare(String(b.label), 'zh-CN'));
  if (rows.some((row) => !row.project)) options.push({ key: '__none__', label: '非项目' });
  return options;
}

export function lineNames(row) {
  return (row?.business_lines || []).map((line) => line.item_name).filter(Boolean);
}

export function searchText(row, projectName = (name) => name) {
  return [
    row.name, row.subject, row.employee_name, row.department, projectText(row, projectName),
    ...lineNames(row), ...(row.business_lines || []).map((line) => line.material_code),
    ...((row.procurement_chain || {}).po_numbers || []), ...((row.procurement_chain || {}).pr_numbers || []),
  ].join(' ').toLowerCase();
}

// 搜索、阶段、项目、加急都在已经取回的单据里筛（后端没有搜索接口）。
// 阶段筛选：单个阶段，或 STAGE_GROUPS 里的合并口径（exec / back）。
export function stageMatches(row, stage = '') {
  if (!stage) return true;
  const key = stageKey(row);
  return STAGE_GROUPS[stage] ? STAGE_GROUPS[stage].includes(key) : key === stage;
}

export function stageFilterLabel(stage = '') {
  const group = STAGE_GROUP_FILTERS.find((item) => item.key === stage);
  if (group) return group.label;
  return (STAGE_FILTERS.find((item) => item.key === stage) || {}).label || '';
}

// 地址里的 stage= 认不得就当没有筛选。
export function normalizeStage(value) {
  const key = String((Array.isArray(value) ? value[0] : value) || '');
  return stageFilterLabel(key) ? key : '';
}

export function filterRows(rows = [], filters = {}, projectName = (name) => name) {
  const text = String(filters.text || '').trim().toLowerCase();
  return rows.filter((row) => {
    if (filters.urgent && row.urgency !== '加急') return false;
    if (filters.stage && !stageMatches(row, filters.stage)) return false;
    if (filters.project) {
      if (filters.project === '__none__' ? row.project : row.project !== filters.project) return false;
    }
    return !text || searchText(row, projectName).includes(text);
  });
}

export function pageCount(total, size = PAGE_SIZE) {
  return Math.max(1, Math.ceil(total / size));
}

export function pageSlice(rows = [], page = 0, size = PAGE_SIZE) {
  return rows.slice(page * size, page * size + size);
}

// 当前在哪：审批中看节点，执行中看采购链摘要和 PO。
export function whereText(row) {
  const key = stageKey(row);
  const chain = row?.procurement_chain || {};
  if (row?.request_type === REQUEST_DIRECT) return isActive(row) ? (row.current_step_label || '—') : (row.business_status || '—');
  if (key === 'demand') return row.current_step_label || '—';
  if (key === 'await_pr') return '等 PMC 在物料看板提 PR';
  if (['quote', 'price', 'po'].includes(key)) {
    return [(chain.po_numbers || []).join('、'), chain.summary].filter(Boolean).join(' · ') || chain.label || '—';
  }
  if (key === 'closed') return '—';
  return draftHint(row);
}

export function draftHint(row) {
  const kind = draftKind(row);
  if (kind === 'withdrawn') return '申请人已撤回，可编辑后重新提交';
  if (kind === 'rejected') return '被驳回，修改后重新提交';
  if (kind === 'draft') return '草稿，还没有提交';
  return '—';
}

// 首页状态分组（只数传进来的这些单据）。
export function stageGroups(rows = []) {
  const count = (keys) => rows.filter((row) => keys.includes(stageKey(row))).length;
  return {
    back: count(['draft', 'withdrawn', 'rejected']),
    demand: count(['demand']),
    exec: count(['await_pr', 'quote', 'price', 'po']),
  };
}

// 购买申请首页的指标卡（我的草稿 / 退回、我的审批中、已批准待付款）点进列表时的状态筛选：?status=draft|review|topay。
export const PURCHASE_STATUS_FILTERS = Object.freeze([
  { key: 'draft', label: '我的草稿 / 退回', match: (row) => Boolean(draftKind(row)) },
  { key: 'review', label: '我的 · 审批中', match: (row) => isActive(row) },
  { key: 'topay', label: '已批准 · 待付款', match: (row) => row?.workflow_status === '已完成' && ['待付款', '部分付款'].includes(row?.business_status) },
]);

export function normalizePurchaseStatus(value) {
  const key = String((Array.isArray(value) ? value[0] : value) || '');
  return PURCHASE_STATUS_FILTERS.some((item) => item.key === key) ? key : '';
}

export function purchaseStatusLabel(key) {
  return (PURCHASE_STATUS_FILTERS.find((item) => item.key === key) || {}).label || '';
}

export function filterPurchaseStatus(rows = [], key = '') {
  const filter = PURCHASE_STATUS_FILTERS.find((item) => item.key === key);
  return filter ? rows.filter(filter.match) : rows;
}

const PO_ORDER = ['草稿', '待采购确认', '待合同复核', '待电子用印', '已生效', '供应商制作中', '到货验收中', '付款中'];

export function poSubStatus(status) {
  if (['供应商制作中', '到货验收中', '付款中'].includes(status)) return status;
  return '合同处理中';
}

// 整张申请取最靠前的 PO 状态（没有 PO 状态数据时返回空）。
export function earliestPoStatus(row, poStatus = {}) {
  const found = ((row?.procurement_chain || {}).po_numbers || [])
    .map((name) => poStatus[name]).filter((status) => status && status !== '已关闭' && status !== '已取消');
  if (!found.length) return '';
  return found.sort((a, b) => PO_ORDER.indexOf(a) - PO_ORDER.indexOf(b))[0];
}

// 首页"全部采购申请走到哪一步了"：每张取最靠前的阶段；仅全局角色显示。
export function stageDistribution(rows = [], poStatus = {}) {
  const counts = Object.fromEntries(CHAIN_STAGES.map((stage) => [stage.key, 0]));
  const demandParts = { 会签: 0, PMC: 0, 终审: 0 };
  const poParts = {};
  for (const row of rows) {
    const key = stageKey(row);
    if (!(key in counts)) continue;
    counts[key] += 1;
    if (key === 'demand') {
      const label = String(row.current_step_label || '');
      if (label.includes('会签')) demandParts.会签 += 1;
      else if (label.startsWith('PMC')) demandParts.PMC += 1;
      else if (label.includes('终审')) demandParts.终审 += 1;
    }
    if (key === 'po') {
      const sub = earliestPoStatus(row, poStatus);
      if (sub) poParts[poSubStatus(sub)] = (poParts[poSubStatus(sub)] || 0) + 1;
    }
  }
  const subs = {
    demand: Object.entries(demandParts).filter(([, n]) => n).map(([label, n]) => `${label} ${n}`).join(' · '),
    await_pr: counts.await_pr ? 'PMC 在物料看板提' : '',
    quote: counts.quote ? '采购在价格审批里比价' : '',
    price: counts.price ? '物料全部报价、等副总批' : '',
    po: Object.entries(poParts).map(([label, n]) => `${label} ${n}`).join(' · '),
    closed: '',
  };
  return CHAIN_STAGES.map((stage, index) => ({
    key: stage.key, no: String(index + 1).padStart(2, '0'), label: stage.label,
    count: counts[stage.key], sub: subs[stage.key],
  }));
}

export function poBreakdown(rows = [], poStatus = {}) {
  const parts = {};
  for (const row of rows) {
    if (stageKey(row) !== 'po') continue;
    const sub = earliestPoStatus(row, poStatus);
    if (sub) parts[poSubStatus(sub)] = (parts[poSubStatus(sub)] || 0) + 1;
  }
  return Object.entries(parts).map(([label, count]) => ({ label, count }));
}

// ---------------------------------------------------------------- 审批
export function currentStepOf(row) {
  return (row?.steps || []).find((step) => Number(step.step_index) === Number(row?.current_step_index)) || null;
}

export function currentStepKey(row) {
  const step = currentStepOf(row);
  return String(step?.step_key || row?.current_step_key || row?.current_step_label || '');
}

// 在同一个节点上操作过以后，列表刷新前先在本地把按钮藏起来，避免重复点。
export function canActOn(row, acted = {}, key = 'can_approve') {
  if (!row?.[key]) return false;
  const done = acted[row.name];
  return !done || done !== currentStepKey(row);
}

export function unboundLines(lines = []) {
  return (lines || []).filter((line) => !String(line?.material_code || '').trim());
}

export function isPmcStep(row) {
  return Boolean(row?.can_modify_procurement_request);
}

// PMC 节点：有物料没绑定目录里的编号时不能点通过（后端同样会拦）。
export function approveBlocker(row) {
  if (row?.request_type !== REQUEST_PROCUREMENT || !isPmcStep(row)) return '';
  const missing = unboundLines(row.business_lines).length;
  return missing ? `还有 ${missing} 项物料没有绑定物料编号，请先点"补充/修改物料"绑定` : '';
}

export function approvalButtonLabel(row, step = currentStepOf(row)) {
  if (step?.mode === 'handle') return String(step.label || '').includes('总经理付款') ? '确认付款' : '办理完成';
  if (row?.request_type === REQUEST_PROCUREMENT && (row.workflow_status === '待审批' || String(step?.label || '').includes('需求'))) return '需求审批通过';
  return '审批通过';
}

export function canWithdrawRow(row, currentEmployee = '') {
  if (!isActive(row)) return false;
  const own = Boolean(row?.request_type === REQUEST_PROCUREMENT && row?.employee && currentEmployee && row.employee === currentEmployee);
  return Boolean(row?.can_withdraw || own);
}

export function canMaintainLines(row) {
  return row?.request_type === REQUEST_PROCUREMENT && Boolean(row?.can_modify_procurement_request);
}

export function pmcButtonLabel(row) {
  return unboundLines(row?.business_lines).length ? '补充/修改物料' : '修改采购申请';
}

// 并列的会签节点：标签形如"直属主管：直属领导、项目主管：项目主管（会签）"。
export function labelParts(label = '') {
  return String(label).replace(/（会签）\s*$/, '').split('、').map((part) => part.trim()).filter(Boolean);
}

export function stepPeople(step, nameOf = (user) => user) {
  const approvers = Array.isArray(step?.approvers) ? step.approvers : [];
  if (approvers.length < 2) return [];
  const parts = labelParts(step.label);
  const approved = new Set(Array.isArray(step.approved_by) ? step.approved_by : []);
  const finished = ['已通过', '已办理'].includes(step.status);
  return approvers.map((user, index) => ({
    user,
    name: parts.length === approvers.length ? parts[index] : nameOf(user),
    done: finished || approved.has(user),
  }));
}

// 审批进度（详情页右侧竖线）：已处理 / 当前 / 未到 / 驳回；会签节点列出每个人。
export function stepTimeline(row = {}, nameOf = (user) => user) {
  const current = Number(row.current_step_index || 0);
  const active = isActive(row);
  return (row.steps || []).map((step) => {
    const index = Number(step.step_index || 0);
    const people = stepPeople(step, nameOf);
    let state = 'todo';
    if (['已通过', '已办理'].includes(step.status)) state = 'done';
    else if (step.status === '已拒绝') state = 'rejected';
    else if (active && index === current) state = 'now';
    const when = step.acted_on ? ` · ${String(step.acted_on).slice(0, 16)}` : '';
    const who = !people.length && step.action_by ? ` · ${nameOf(step.action_by)}` : '';
    let sub = '';
    if (state === 'done') sub = `${people.length ? '全部同意' : (step.mode === 'handle' ? '已办理' : '已同意')}${who}${when}`;
    else if (state === 'rejected') sub = `已驳回${who}${when}`;
    else if (state === 'now') sub = people.length ? `会签中 · 已同意 ${people.filter((p) => p.done).length}/${people.length}` : '等待处理';
    return {
      key: `${index}-${step.step_key || step.label}`, label: `${index}. ${step.label}`, state, sub,
      note: step.note || '', people, parallel: people.length > 1,
    };
  });
}

// ---------------------------------------------------------------- 采购链（跳转与阶段条）
export function chainRoute(row, target = 'price') {
  const chain = row?.procurement_chain || {};
  if (target === 'price' && chain.stage === 'await_pr') {
    return { path: '/approval/material-progress', query: { request: row?.name || '' } };
  }
  const query = { request: row?.name || '' };
  if (target === 'po') query.tab = 'po';
  if (target === 'price' && (chain.stage === 'quote' || String(row?.current_step_label || '').includes('询价'))) query.view = 'source';
  return { name: 'procurement-price-approvals', query };
}

function stripSub(row, key) {
  const chain = row?.procurement_chain || {};
  if (key === 'demand') return String(row.current_step_label || '').replace(/（会签）$/, '') || '';
  if (key === 'closed') return chain.summary || '';
  return chain.summary || chain.label || '';
}

export function chainStrip(row) {
  const key = stageKey(row);
  const index = STAGES[key]?.index;
  if (index === undefined || index < 0) return [];
  return CHAIN_STAGES.map((stage, i) => {
    const done = i < index || (i === index && key === 'closed');
    return {
      key: stage.key, label: stage.label, state: done ? 'done' : (i === index ? 'now' : 'todo'),
      mark: done ? '✓' : String(i + 1), sub: i === index ? stripSub(row, key) : '',
    };
  });
}

// 右侧"关联单据"：价格审批 / PO 只给有权限的人（后端行标志），物料看板只给能打开的人。
export function relatedDocuments(row, { canBoard = false } = {}) {
  const chain = row?.procurement_chain || {};
  const price = chain.price_approval_numbers || [];
  const pos = chain.po_numbers || [];
  const result = [];
  if ((chain.pr_numbers || []).length) {
    result.push({ key: 'pr', t: 'PR', names: chain.pr_numbers, to: null, v: '' });
  }
  if (price.length || row?.can_view_procurement_price) {
    result.push({
      key: 'price', t: '价格审批', names: price,
      to: row?.can_view_procurement_price ? (price.length === 1 ? { name: 'procurement-price-approvals', query: { approval: price[0] } } : chainRoute(row, 'price')) : null,
      v: row?.can_view_procurement_price ? '打开 →' : '无权限查看',
    });
  }
  if (pos.length) {
    result.push({
      key: 'po', t: 'PO', names: pos,
      to: row?.can_view_procurement_po ? (pos.length === 1 ? { name: 'procurement-price-approvals', query: { tab: 'po', po: pos[0] } } : chainRoute(row, 'po')) : null,
      v: row?.can_view_procurement_po ? '打开 →' : '无权限查看',
    });
  }
  if (canBoard) {
    result.push({ key: 'board', t: '物料看板', names: ['整张申请的物料进度'], to: { path: '/approval/material-progress', query: { request: row?.name || '' } }, v: '打开 →' });
  }
  return result;
}

// ---------------------------------------------------------------- 详情页文字
export function requestFacts(row, { projectName = (name) => name, nameOf = (user) => user, purchasers = [] } = {}) {
  const direct = row?.request_type === REQUEST_DIRECT;
  const purchaser = purchasers.find((item) => item.name === row?.purchaser_user)?.full_name
    || (row?.purchaser_user ? nameOf(row.purchaser_user) : '');
  const facts = [{ k: '申请用途', v: row?.reason || '—', wide: true }];
  if (direct) {
    facts.push({ k: '购买方式', v: row?.purchase_method || '—' });
    facts.push({ k: '采购归属', v: allocationLabel(row, projectName) });
    facts.push({ k: '资产属性', v: row?.asset_nature || '未标注', hot: row?.asset_nature === '固定资产' });
    if (row?.asset_nature === '固定资产') facts.push({ k: '固定资产类别', v: row.fixed_asset_category || '未分类' });
    facts.push({ k: '预计交期', v: row?.expected_delivery_date || '—' });
    facts.push({ k: '申请部门', v: row?.department || '—' });
  } else {
    facts.push({ k: '采购范围', v: row?.procurement_scope || (row?.project ? '项目采购' : '非项目采购') });
    facts.push({ k: '采购归属', v: allocationLabel(row, projectName) });
    facts.push({ k: '费用类别', v: row?.expense_account_category || '—' });
    facts.push({ k: '资产属性', v: row?.asset_nature || '未标注', hot: row?.asset_nature === '固定资产' });
    facts.push({ k: '预计交期', v: row?.expected_delivery_date || row?.expected_arrival_date || '—' });
    facts.push({ k: '采购经办人', v: purchaser || '—' });
    facts.push({ k: '申请部门', v: row?.department || '—' });
  }
  if (row?.source_purchase_order) facts.push({ k: '来源 PO', v: row.source_purchase_order });
  else if (row?.source_request) facts.push({ k: '来源采购单', v: row.source_request });
  return facts;
}

export function copiedToLabels(row) {
  return (Array.isArray(row?.copied_to) ? row.copied_to : [])
    .map((item) => (typeof item === 'string' ? item : (item?.label || item?.name || item?.user || '')))
    .filter(Boolean);
}

// 最近一次驳回的原因（草稿被驳回回来时给申请人看）。
export function lastRejection(row) {
  const rejected = [...(row?.steps || [])].reverse().find((step) => step.status === '已拒绝' && step.note);
  if (rejected) return rejected.note;
  const log = Array.isArray(row?.operation_log) ? row.operation_log : [];
  const event = [...log].reverse().find((item) => /驳回|退回/.test(String(item.action || '')));
  return event?.note || '';
}

// 详情页顶部那条提示，跟着角色和单据状态变。
export function detailBanner(row, { canAct = false, canWithdraw = false, insider = false } = {}) {
  const key = stageKey(row);
  const direct = row?.request_type === REQUEST_DIRECT;
  const step = currentStepOf(row);
  if (canAct) {
    if (approveBlocker(row)) {
      const missing = unboundLines(row.business_lines).length;
      return { tone: 'warn', text: `轮到你审批（PMC）。还有 ${missing} 项物料没有绑定物料编号，绑定后才能通过；绑定、改数量请用"补充/修改物料"。` };
    }
    return { tone: 'act', text: `轮到你审批（${row.current_step_label || '当前节点'}）。同意后进入下一步；驳回可以退回申请人或更早的节点，需要写原因。` };
  }
  if (key === 'draft') return { tone: 'info', text: '草稿，还没有提交审批。' };
  if (key === 'withdrawn') return { tone: 'info', text: '已撤回，可以编辑后重新提交审批。' };
  if (key === 'rejected') {
    const note = lastRejection(row);
    return { tone: 'warn', text: `被驳回${note ? `：${note}` : ''}。修改后可以重新提交。` };
  }
  if (isActive(row)) {
    const where = row.current_step_label || (step && step.label) || '当前节点';
    return { tone: 'info', text: `审批中：当前在 ${where}。${canWithdraw ? '审批开始后你仍可以撤回；批准完成后不能撤回。' : ''}` };
  }
  if (direct) return { tone: 'info', text: '已批准。可以用它发起报销或付款；批准后不能撤回。' };
  if (insider) return { tone: 'info', text: `需求已批准，采购在推进。${row?.procurement_chain?.summary || ''} 这张申请本身没有可做的操作；到货、验收、付款在采购付款里按 PO 办理。` };
  return { tone: 'info', text: '需求已批准，采购在推进。你可以看到数量和进度，价格、供应商只对采购和财务显示。' };
}

// ---------------------------------------------------------------- 首页的"待我处理"（非 OA 部分）
function groupBy(rows, keyOf) {
  const map = new Map();
  for (const row of rows) {
    const key = keyOf(row);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(row);
  }
  return map;
}

const num = (value) => quantityText(value);

// PMC：已批准、还没提完 PR 的物料（物料进度看板的 pr_eligible），按申请汇总。
export function prWorkItems(progressRows = []) {
  const rows = progressRows.filter((row) => Number(row.pr_eligible) === 1);
  return [...groupBy(rows, (row) => row.source_request).entries()].map(([request, lines]) => ({
    key: `pr:${request}`, tag: '提 PR', tone: 'p-sun',
    subject: lines[0].item_name ? `${lines.map((l) => l.item_name).slice(0, 2).join('、')}${lines.length > 2 ? ' 等' : ''}` : request,
    meta: `${lines[0].requester || ''} · ${request} · ${lines.length} 项物料还没提 PR（${lines.slice(0, 2).map((l) => `${num(l.pr_available_quantity)}${l.unit || ''}`).join(' + ')}${lines.length > 2 ? ' ...' : ''}）`,
    action: '去物料看板', to: { path: '/approval/material-progress', query: { request } }, count: lines.length,
    since: lines[0].request_modified || '',
  }));
}

// 采购：还有物料可以提价格审批的 PR，以及价格审批草稿。
export function priceWorkItems({ prs = [], drafts = [] } = {}) {
  const items = [];
  for (const pr of prs.filter((item) => Number(item.can_create_price_approval) === 1)) {
    items.push({
      key: `pr-price:${pr.name}`, tag: '待比价', tone: 'p-sun', subject: pr.name,
      meta: `${pr.source_projects || '非项目'} · ${pr.available_line_count} 项物料还没比价 · 共 ${num(pr.available_quantity)}`,
      action: '去价格审批', to: { name: 'procurement-price-approvals', query: { view: 'source' } }, count: Number(pr.available_line_count || 0),
      since: pr.modified || '',
    });
  }
  for (const approval of drafts) {
    items.push({
      key: `pa-draft:${approval.name}`, tag: '价格审批', tone: 'p-brand', subject: approval.name,
      meta: `草稿 · ${approval.demand_summary || approval.summary || '继续录入供应商报价'}`.slice(0, 120),
      action: '继续比价', to: { name: 'procurement-price-approvals', query: { approval: approval.name } }, count: 1,
      since: approval.modified || '',
    });
  }
  return items;
}

// 采购：PO 需要确认 / 生成合同草稿 / 复核；副总：电子用印。
export function poWorkItems(orders = [], { manage = false, seal = false } = {}) {
  const items = [];
  for (const po of orders) {
    const to = { name: 'procurement-price-approvals', query: { tab: 'po', po: po.name } };
    const base = { key: `po:${po.name}`, subject: po.name, to, since: po.modified || '', count: 1 };
    const meta = `${po.supplier || '未填供应商'} · ${po.status || ''}`;
    if (seal && Number(po.can_seal_contract) === 1) {
      items.push({ ...base, key: `${base.key}:seal`, tag: '电子用印', tone: 'p-brand', meta, action: '去用印' });
    } else if (manage && Number(po.can_manage_purchase) === 1) {
      if (['草稿', '待采购确认'].includes(po.status)) items.push({ ...base, tag: '确认 PO', tone: 'p-cobalt', meta, action: '去确认' });
      else if (po.status === '待合同复核' && po.contract_status === '待补充信息') items.push({ ...base, tag: '合同草稿', tone: 'p-cobalt', meta, action: '生成合同草稿' });
      else if (po.status === '待合同复核' && po.contract_status === '草稿待复核') items.push({ ...base, tag: '复核合同', tone: 'p-cobalt', meta, action: '去复核' });
    }
  }
  return items;
}

// 副总：价格审批等他选成交供应商。
export function approvalWorkItems(approvals = []) {
  return approvals.filter((item) => Number(item.can_select_quote) === 1 && item.status === '待审批').map((item) => ({
    key: `pa:${item.name}`, tag: '价格审批', tone: 'p-brand', subject: item.name,
    meta: `${item.source_projects || '非项目'} · ${item.demand_summary || ''}`.slice(0, 120),
    action: '去审批', to: { name: 'procurement-price-approvals', query: { approval: item.name } }, count: 1, since: item.modified || '',
  }));
}

// 采购：付款条件已满足、可以提交付款审批的 PO 期次。
export function paymentWorkItems(items = []) {
  return items.filter((item) => item.work_status === '可提交付款审批' && Number(item.can_push_payment) === 1).map((item) => ({
    key: `pay:${item.key}`, tag: '提交付款', tone: 'p-brand',
    subject: `${item.po} · ${item.installment_name || ''}${item.payment_stage || ''}`.trim(),
    meta: `${item.supplier || ''} · 合同已生效，付款条件满足`,
    action: '去采购付款', to: { path: '/approval/procurement-payment', query: { po: item.po } }, count: 1,
    since: item.planned_date || '',
  }));
}

// ---------------------------------------------------------------- 表单
let uidSeed = 0;

export function blankLine() {
  uidSeed += 1;
  return {
    _uid: uidSeed, material_code: '', material_serial: '', category_code: '', category_path: '', category_parts: [],
    item_name: '', specification: '', product_desc: '', brand: '', product_name: '', product_desc_en: '', brand_en: '',
    material_attr: '外购', quantity: 1, unit: '个', unit_price: 0, remarks: '',
  };
}

export function blankForm() {
  return {
    subject: '', reason: '', urgency: '一般', asset_nature: '非固定资产', fixed_asset_category: '',
    procurement_scope: '项目采购', expected_delivery_date: '', project: '', applicant_employee: '',
    non_project_allocation_type: '部门', non_project_cost_center: '', non_project_department: '',
    purchaser_user: '', purchase_method: '京东购买', business_lines: [blankLine()],
  };
}

export function categoryPartsFromCode(code) {
  const parts = String(code || '').split('.').filter(Boolean);
  return parts.map((_part, index) => parts.slice(0, index + 1).join('.'));
}

export function categoryDepth(code) {
  return String(code || '').split('.').filter(Boolean).length;
}

export function categoryParentCode(item) {
  return item?.parent_category || String(item?.category_code || '').split('.').slice(0, -1).join('.');
}

export function lineFromRow(line = {}) {
  return {
    ...blankLine(), ...line,
    _uid: blankLine()._uid,
    category_parts: line.category_parts?.length ? line.category_parts : categoryPartsFromCode(line.category_code),
    quantity: Number(line.quantity || 0), unit_price: Number(line.unit_price || 0),
  };
}

const FORM_FIELDS = [
  'subject', 'urgency', 'asset_nature', 'fixed_asset_category', 'expected_delivery_date', 'procurement_scope',
  'project', 'non_project_allocation_type', 'non_project_cost_center', 'non_project_department',
  'purchase_method', 'reason', 'purchaser_user',
];

// 草稿 / 被撤回 / 被驳回的单据重新打开，或 PMC 补录时，把单据放回表单。
export function formFromRow(row = {}) {
  const form = blankForm();
  for (const field of FORM_FIELDS) {
    if (row[field] !== null && row[field] !== undefined && row[field] !== '') form[field] = row[field];
  }
  // 非项目采购现在只按部门归属：旧草稿里的"成本中心 / 非项目采购"改回"部门"，部门要重新选。
  if (form.procurement_scope === '非项目采购' && row.non_project_allocation_type !== '部门') {
    form.non_project_allocation_type = '部门';
    form.non_project_department = '';
  }
  form.applicant_employee = row.request_type === REQUEST_DIRECT ? '' : (row.employee || '');
  form.business_lines = (row.business_lines || []).map(lineFromRow);
  if (!form.business_lines.length) form.business_lines = [blankLine()];
  return form;
}

// PMC 修改时发给后端的明细：保留物料流水号（系统生成，不能改）。
export function pmcLines(lines = []) {
  return lines.map((line) => ({
    material_code: line.material_code || '', material_serial: line.material_serial || '',
    category_code: line.category_code || '', category_path: line.category_path || '',
    item_name: line.item_name || '', specification: line.specification || '', product_desc: line.product_desc || '',
    brand: line.brand || '', product_name: line.product_name || '', product_desc_en: line.product_desc_en || '',
    brand_en: line.brand_en || '', material_attr: line.material_attr || '外购',
    quantity: line.quantity, unit: line.unit || '', unit_price: line.unit_price || 0, remarks: line.remarks || '',
  }));
}

export function summarizeLines(lines = [], requestType = REQUEST_PROCUREMENT) {
  const total = lines.length;
  const bound = lines.filter((line) => String(line.material_code || '').trim()).length;
  const amount = lines.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0);
  return { total, bound, pending: requestType === REQUEST_PROCUREMENT ? total - bound : 0, amount };
}

// 提交前还差什么：先看表头，再看明细（明细只提示第一处，与后端校验口径一致）。
export function formBlockers(form = {}, requestType = REQUEST_PROCUREMENT) {
  const list = [];
  if (!String(form.subject || '').trim()) list.push('主题未填');
  if (!String(form.expected_delivery_date || '').trim()) list.push('预计交期未填');
  if (requestType === REQUEST_PROCUREMENT) {
    if (form.procurement_scope === '项目采购') {
      if (!form.project) list.push('所属项目未选');
    } else if (!String(form.non_project_department || '').trim()) {
      list.push('所属部门未选');
    }
  } else {
    if (!['京东购买', '其他购买'].includes(form.purchase_method)) list.push('购买方式未选');
    if (form.asset_nature === '固定资产' && !FIXED_ASSET_CATEGORIES.includes(form.fixed_asset_category)) list.push('固定资产类别未选');
  }
  const lineProblem = validateProcurementRequestForm(form, requestType);
  if (lineProblem) list.push(lineProblem);
  return list;
}

export function validateRequestForm(form, requestType) {
  return formBlockers(form, requestType)[0] || '';
}

// 审批路线预览需要的参数（后端 oa_entry.preview_route）。
export function routePreviewParams(form = {}, requestType = REQUEST_PROCUREMENT, projects = []) {
  const project = projects.find((item) => item.name === form.project) || {};
  const params = { request_type: requestType, project_owner: project.project_owner || '', project_owner_name: project.project_owner_name || '' };
  if (requestType === REQUEST_DIRECT) params.purchase_method = form.purchase_method;
  if (requestType === REQUEST_PROCUREMENT && form.applicant_employee) params.applicant_employee = form.applicant_employee;
  if (!form.project || (requestType === REQUEST_PROCUREMENT && form.procurement_scope !== '项目采购')) {
    params.project_owner = '';
    params.project_owner_name = '';
  }
  return params;
}

// ---------------------------------------------------------------- 物料选择（分类逐级选）
export function categoryChildren(categories = [], parent = '') {
  return categories
    .filter((item) => (parent ? categoryParentCode(item) === parent : !categoryParentCode(item)))
    .sort((a, b) => String(a.category_code).localeCompare(String(b.category_code), undefined, { numeric: true }));
}

export function categoryHasChildren(categories = [], item) {
  const code = String(item?.category_code || '').trim();
  return Boolean(code && categories.some((candidate) => categoryParentCode(candidate) === code));
}

// 至少三级的分类才能提交（后面的流水号由 PMC 补）。
export function selectableCategories(categories = [], query = '') {
  const text = String(query || '').trim().toLowerCase();
  const pool = categories.filter((item) => Number(item.level || categoryDepth(item.category_code)) >= 3);
  if (!text) return pool.slice(0, 8);
  return pool.filter((item) => [item.category_code, item.category_name, item.full_path]
    .some((value) => String(value || '').toLowerCase().includes(text))).slice(0, 8);
}

// 分类接口可能把整棵子树都返回，这里只留这个分类自己名下的物料（编号 = 分类编号 + 一段流水号）。
export function directMaterials(rows = [], code = '') {
  return rows.filter((row) => {
    const materialCode = String(row?.material_code || '').trim();
    const rowCategory = String(row?.category_code || '').trim();
    const suffix = materialCode.startsWith(`${code}.`) ? materialCode.slice(code.length + 1) : '';
    return Boolean(suffix && !suffix.includes('.')) || (!materialCode && rowCategory === code);
  });
}

// 选了目录里的物料后，把名称、规格、品牌等带入这一行（并锁定）。
export function applyMaterial(line, item = {}) {
  const materialCode = String(item.material_code || '').trim();
  const inferred = materialCode.includes('.') ? materialCode.split('.').slice(0, -1).join('.') : '';
  const categoryCode = String(item.category_code || inferred).trim();
  Object.assign(line, {
    material_code: materialCode, category_code: categoryCode, category_path: item.category_path || '',
    category_parts: categoryPartsFromCode(categoryCode), item_name: item.material_name || '',
    specification: item.specification || '', product_desc: item.product_desc || '', brand: item.brand || '',
    product_name: item.product_name || '', product_desc_en: item.product_desc_en || '', brand_en: item.brand_en || '',
    material_attr: item.material_attr || '外购', unit: item.unit || '个',
  });
  return line;
}

export function applyCategory(line, item = {}) {
  line.category_code = item.category_code || '';
  line.category_path = item.full_path || item.category_name || '';
  line.category_parts = categoryPartsFromCode(line.category_code);
  return line;
}

export function clearMaterial(line) {
  line.material_code = '';
  return line;
}

export function lineCodeText(line) {
  return line?.material_code || (line?.category_code ? `${line.category_code} · 待 PMC 完善` : '');
}

// ---------------------------------------------------------------- 进度条（首页、列表、详情共用）
// 采购申请 6 格：需求审批 → 提 PR → 比价 → 价格审批 → PO 执行 → 完成；购买申请 3 格：审批 → 付款 → 完成。
export const PIPE_LABELS = Object.freeze(['需求审批', '提 PR', '比价', '价格审批', 'PO 执行', '完成']);
export const PURCHASE_PIPE_LABELS = Object.freeze(['审批', '付款', '完成']);
export const NUDGE_AFTER_DAYS = 3;

function pipeCells(labels, index) {
  const last = labels.length - 1;
  return labels.map((_, position) => (index >= last || position < index ? 'done' : position === index ? 'cur' : 'todo'));
}

// 草稿、被驳回 / 撤回的没有进度条（返回 null）。
export function pipeline(row) {
  if (!row) return null;
  if (row.request_type === REQUEST_DIRECT) {
    if (isActive(row)) return { labels: PURCHASE_PIPE_LABELS, index: 0, cells: pipeCells(PURCHASE_PIPE_LABELS, 0), current: '审批' };
    if (String(row.workflow_status || '') !== '已完成') return null;
    const business = String(row.business_status || '');
    const index = ['待付款', '部分付款'].includes(business) ? 1 : 2;
    return { labels: PURCHASE_PIPE_LABELS, index, cells: pipeCells(PURCHASE_PIPE_LABELS, index), current: index === 1 ? '付款' : '完成' };
  }
  const index = stageIndex(row);
  if (index < 0) return null;
  return { labels: PIPE_LABELS, index, cells: pipeCells(PIPE_LABELS, index), current: PIPE_LABELS[index] };
}

// 到货进度：已到 / 订购的物料数量（有 PO 并登记了到货才有）。
export function arrivalOf(row) {
  const total = Number(row?.ordered_quantity || 0);
  if (!(total > 0)) return null;
  const got = Math.min(total, Number(row?.received_quantity || 0));
  return { got, total, pct: Math.round((got / total) * 100) };
}

// 能不能“催一下”：和后端 request_nudge.nudge_problem 同一套规则（后端才是准的，这里只决定按钮显不显示）。
export function canNudge(row, { user = '', employee = '', now = Date.now() } = {}) {
  if (!row || !isActive(row) || ![REQUEST_PROCUREMENT, REQUEST_DIRECT].includes(row.request_type)) return false;
  const me = String(user || '').toLowerCase();
  const mine = (me && String(row.owner || '').toLowerCase() === me) || Boolean(employee && row.employee === employee);
  const projectOwner = Boolean(me && String(row.project_owner || '').toLowerCase() === me);
  if (!(mine || projectOwner)) return false;
  // 当前节点只剩我自己（比如项目负责人正好是等的那个人）就没有人可催。
  const step = (row.steps || []).find((item) => Number(item.step_index || 0) === Number(row.current_step_index || 0));
  if (step && Array.isArray(step.approvers)) {
    const approved = new Set(Array.isArray(step.approved_by) ? step.approved_by : []);
    const others = step.approvers.filter((approver) => !approved.has(approver) && String(approver).toLowerCase() !== me);
    if (!others.length) return false;
  }
  return (waitedDays(row, now) || 0) >= NUDGE_AFTER_DAYS;
}
