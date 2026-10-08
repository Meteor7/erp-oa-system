// 页面之间的"上下文"（2026-10 导航整改）：每个按钮 / 链接都要带上类型、范围、筛选、来源，
// 目标页按它显示，返回时回到原来的位置。这里只放不依赖页面的纯函数，方便单元测试。
//
// 约定：
//   列表状态放在地址里：scope=todo|mine|all，bucket=<状态桶>，status=<业务状态>，stage=<阶段>，q=<搜索词>。
//   从列表点进详情 / 表单时带上 from=list 和同一份列表状态；详情页的"列表"、表单的"取消"据此回到同一个范围和筛选。
//   从别的页面（首页、看板）点进来时 from=<页面路径（可带查询）>，返回时回到那个页面。

export const LIST_KEYS = Object.freeze(['scope', 'status', 'bucket', 'stage', 'q', 'long']);

export function firstValue(value) {
  return Array.isArray(value) ? value[0] : value;
}

// 去掉空值，数字转成字符串；查询参数在地址里本来就是字符串。
export function cleanQuery(query = {}) {
  const out = {};
  for (const [key, raw] of Object.entries(query || {})) {
    const value = firstValue(raw);
    if (value === undefined || value === null || value === '' || value === false) continue;
    out[key] = String(value);
  }
  return out;
}

// 只取列表状态那几项（scope / bucket / status / stage / q）。
export function listState(query = {}) {
  const picked = {};
  for (const key of LIST_KEYS) picked[key] = (query || {})[key];
  return cleanQuery(picked);
}

// from 可以是 'list' 或站内路径（可带查询），别的值一律忽略。
export function isInternalPath(value) {
  const text = String(value || '');
  return text.startsWith('/') && !text.startsWith('//') && !text.includes('://') && !/[\r\n]/.test(text);
}

export function fromValue(query = {}) {
  const from = String(firstValue((query || {}).from) || '');
  if (from === 'list' || isInternalPath(from)) return from;
  return '';
}

// 列表页自己的来源页（首页 / 看板点进列表时 from=那个页面）。点进详情后 from 要用来记"来自列表"，
// 列表自己的来源就记在 origin 里，这样详情 → 列表 → 看板的返回链不会断。
export function originOf(query = {}) {
  const from = fromValue(query);
  return from && from !== 'list' ? from : '';
}

function originKeys(state = {}) {
  const origin = firstValue((state || {}).origin);
  return isInternalPath(origin) ? { origin: String(origin) } : {};
}

// 去掉某一项筛选后的列表地址（点筛选条上的 × 用）。
export function listWithout(state = {}, ...keys) {
  const next = { ...listState(state) };
  for (const key of keys) delete next[key];
  const origin = originOf(state);
  return { view: 'list', ...(origin ? { from: origin } : {}), ...next };
}

export function listLocation(state = {}) {
  const origin = originKeys(state).origin;
  return { view: 'list', ...(origin ? { from: origin } : {}), ...listState(state) };
}

// 从列表点进详情：带上列表状态，返回时原样恢复。
export function detailQuery(name, state = {}) {
  return { request: String(name), from: 'list', ...listState(state), ...originKeys(state) };
}

// 从列表点进表单（新建 / 编辑草稿）。
export function formQuery(extra = {}, state = {}) {
  return { ...cleanQuery(extra), from: 'list', ...listState(state), ...originKeys(state) };
}

// 表单里 router.replace（例如保存草稿后补上 draft=）时要保留的来源信息。
export function carryQuery(query = {}) {
  const carried = listState(query);
  const from = cleanQuery({ from: (query || {}).from });
  return { ...from, ...carried, ...originKeys(query) };
}

export function splitPath(value) {
  const text = String(value || '');
  const index = text.indexOf('?');
  const path = (index === -1 ? text : text.slice(0, index)).replace(/#.*$/, '');
  const query = {};
  if (index !== -1) {
    new URLSearchParams(text.slice(index + 1).replace(/#.*$/, '')).forEach((val, key) => {
      if (!(key in query)) query[key] = val;
    });
  }
  return { path: path || '/', query };
}

const ORIGIN_LABELS = Object.freeze({
  '/dashboard': '首页',
  '/approval/expense-request-board': '申请看板',
  '/approval/expense-payment-board': '付款看板',
  '/approval/request-dashboard': '申请看板',
  '/approval/payment-dashboard': '付款看板',
  '/approval/material-progress': '物料进度看板',
  '/approval/procurement': '采购申请',
  '/approval/direct-purchase': '购买申请',
  '/approval/travel': '出差申请',
  '/approval/claim': '报销',
  '/approval/payment': '付款',
  '/approval/procurement-payment': '采购付款',
  '/approval/procurement/price-approvals': '价格审批',
  '/approval/invoice-folder': '发票夹',
});

// 来源页的名字，用在"← 返回首页"这样的文字上；列表和不认识的页面没有名字。
export function originLabel(query = {}) {
  const from = fromValue(query);
  if (!from || from === 'list') return from === 'list' ? '列表' : '';
  return ORIGIN_LABELS[splitPath(from).path] || '';
}

// 返回到哪里：from=list 回到同一个范围 / 筛选的列表；from=站内路径回到那个页面；否则用 fallback。
// 结果是 router.push 能直接用的对象：{ query } 留在当前页面，{ path, query } 去别的页面。
export function returnTarget(query = {}, fallback = {}) {
  const from = fromValue(query);
  if (from === 'list') return { query: listLocation(query) };
  if (from) {
    const { path, query: target } = splitPath(from);
    return { path, query: target };
  }
  return { query: { ...fallback } };
}

// router.push 能直接用的完整地址：留在当前页面时 path 用 currentPath。
export function backLocation(currentPath, query = {}, fallback = {}) {
  const target = returnTarget(query, fallback);
  return { path: target.path || currentPath, query: target.query };
}

// 只关心留在当前页面的查询时（工作台里 go(query)）。from 指向别的页面时返回 null，由调用方 router.push。
export function returnQuery(query = {}, fallback = {}) {
  const target = returnTarget(query, fallback);
  return target.path ? null : target.query;
}

// 自己这一页作为"来源"写进下一页的 from（看板、首页用）。
export function hereAsFrom(path, query = {}) {
  const clean = cleanQuery(query);
  const text = new URLSearchParams(clean).toString();
  return text ? `${path}?${text}` : String(path);
}

// 给一个跳转目标补上来源（目标自己已经写了 from 就不覆盖）。
export function withFrom(target, from) {
  if (!target || !from) return target;
  const query = { ...(target.query || {}) };
  if (!query.from) query.from = from;
  return { ...target, query };
}

// ---------------------------------------------------------------- 查看范围
export const SCOPE_LABELS = Object.freeze({ todo: '待我处理', mine: '我的', all: '全部' });

// 范围参数的统一处理。allowed 之外的范围退回 fallback，并说明原因（页面上显示出来，不再悄悄换）。
//   subject：单据叫什么（"报销单"），fallbackLabel：退回后显示的名字（"你的报销单"）。
export function resolveScope(requested, { allowed = ['todo', 'mine'], fallback = 'mine', subject = '', fallbackLabel = '' } = {}) {
  const value = String(firstValue(requested) || '').trim();
  if (!value) return { scope: fallback, notice: '', requested: '' };
  if (allowed.includes(value)) return { scope: value, notice: '', requested: value };
  const shown = fallbackLabel || `你的${subject || '单据'}`;
  if (value === 'all') {
    return { scope: fallback, notice: `你没有查看全部${subject || '单据'}的权限，已显示${shown}。`, requested: value };
  }
  return { scope: fallback, notice: `不认识的查看范围「${value}」，已显示${shown}。`, requested: value };
}

// 看板指标卡里 scope=all 的链接：看的人打不开全部，就不让点（返回 null），而不是点了再被悄悄换成别的范围。
const ALL_NEEDS = Object.freeze({
  '/approval/claim': 'claimAll',
  '/approval/payment': 'claimAll',
  '/approval/travel': 'travelAll',
});

export function resolveKpiTarget(to, access = {}) {
  if (!to || !to.path) return to || null;
  if ((to.query || {}).scope !== 'all') return to;
  const need = ALL_NEEDS[splitPath(to.path).path];
  if (need && !access[need]) return null;
  return to;
}

// ---------------------------------------------------------------- 侧栏
// 当前路径属于侧栏哪一项：完全相同，或者是它下面的详情 / 新建 / 编辑页（最长的前缀优先）。
export function ownerOfPath(path, candidates = []) {
  const current = String(path || '');
  let best = '';
  for (const raw of candidates) {
    const base = splitPath(raw).path;
    if (!base) continue;
    if ((current === base || current.startsWith(`${base}/`)) && base.length > best.length) best = base;
  }
  return best;
}

// 带子项的分组里，哪一组含当前路径（用来自动展开）。items 形如 [{ label, children: [{ to }] }]。
export function groupOwning(path, items = []) {
  const all = items.flatMap((item) => (item.children || []).map((child) => child.to));
  const owner = ownerOfPath(path, all);
  if (!owner) return null;
  return items.find((item) => (item.children || []).some((child) => splitPath(child.to).path === owner)) || null;
}

// ---------------------------------------------------------------- 站内链接
// 通知里存的链接可能是 /planck-semicon/...、旧的 /rayher/...，也可能是整条网址；统一成路由里的路径（保留查询和锚点）。
// 整条网址只认和当前站点同一个主机（host 由调用方传入），别的站点一律不当作站内链接。
export function stripAppPrefix(link, host = '') {
  let target = String(link || '').trim();
  if (!target) return '';
  const absolute = target.match(/^https?:\/\/([^/?#]+)(.*)$/i);
  if (absolute) {
    if (!host || absolute[1].toLowerCase() !== String(host).toLowerCase()) return '';
    target = absolute[2] || '/';
    if (!target.startsWith('/')) target = `/${target}`;
  }
  if (!target.startsWith('/') || target.startsWith('//')) return '';
  for (const base of ['/planck-semicon', '/rayher']) {
    if (target === base) return '/dashboard';
    if (target.startsWith(`${base}/`) || target.startsWith(`${base}?`) || target.startsWith(`${base}#`)) {
      target = target.slice(base.length) || '/dashboard';
      if (!target.startsWith('/')) target = `/${target}`;
      break;
    }
  }
  return target;
}

// 没有权限的深链接被带回别的页面时，页面顶部说一声。labelOf(path) 给出页面名，没有名字就用路径。
export function deniedNoticeText(denied, fallback, labelOf = () => '') {
  const deniedLabel = labelOf(denied) || denied;
  const fallbackLabel = labelOf(fallback) || fallback;
  return `你没有权限打开「${deniedLabel}」，已回到「${fallbackLabel}」。`;
}

// ---------------------------------------------------------------- 首页待办 / 通知的跳转目标
export const ATTENDANCE_TYPE_BY_ROUTE = Object.freeze({
  '/approval/leave': '请假',
  '/approval/overtime': '加班',
  '/approval/comp-time': '调休',
});

// 采购付款页没有 view=list，待审批的付款单都在"付款审批单"页签里。
const TODO_LIST_QUERY = Object.freeze({ '/approval/procurement-payment': { tab: 'approvals' } });

// 审批待办里"加班 5"这样的按钮：只有一张就打开这一张，有多张就打开该类型"待我处理"的列表。
export function approvalTodoTarget(item = {}, from = '/dashboard') {
  const route = String(item.route || '');
  if (!route) return null;
  const requests = Array.isArray(item.requests) ? item.requests : [];
  const count = Math.max(Number(item.count || 0), requests.length);
  if (count > 1) return { path: route, query: { ...(TODO_LIST_QUERY[route] || { view: 'list', scope: 'todo' }), from } };
  if (requests.length === 1) return { path: route, query: { request: requests[0], from } };
  return { path: route, query: { from } };
}

const DRAFT_PATHS = Object.freeze({
  '/approval/procurement': '/approval/procurement/new',
  '/approval/direct-purchase': '/approval/direct-purchase/new',
});
const DRAFT_VIEW_PAGES = Object.freeze(['/approval/claim', '/approval/payment', '/approval/travel']);

// 草稿 / 被退回的申请"修改后重新提交"：各页面打开草稿的参数不一样。
export function draftTarget(item = {}, from = '/dashboard') {
  const route = String(item.route || '');
  const name = String(item.name || '');
  if (!route || !name) return null;
  if (ATTENDANCE_TYPE_BY_ROUTE[route]) {
    return { path: route, query: { view: 'new', type: ATTENDANCE_TYPE_BY_ROUTE[route], draft: name, from } };
  }
  if (DRAFT_PATHS[route]) return { path: DRAFT_PATHS[route], query: { draft: name, from } };
  if (DRAFT_VIEW_PAGES.includes(route)) return { path: route, query: { view: 'new', draft: name, from } };
  return { path: route, query: { request: name, from } };
}

// "我发起的申请"里的按钮：草稿状态（被退回后也是草稿）去编辑，其余看详情。
export function myRequestTarget(item = {}, from = '/dashboard') {
  const route = String(item.route || '');
  if (!route) return null;
  if (item.status === '草稿') return draftTarget(item, from);
  return { path: route, query: { request: String(item.name || ''), from } };
}

// "要我处理"里的按钮：后端给了 query 就用它（价格审批 approval=、PO po= 等），否则 request=。
export function queueTarget(item = {}, from = '/dashboard') {
  const route = String(item.route || '');
  if (!route) return null;
  const query = item.query && Object.keys(item.query).length ? item.query : { request: item.name };
  return { path: route, query: { ...cleanQuery(query), from } };
}

// 通知：后端已经算好 route + query。
export function noteTarget(item = {}, from = '/dashboard') {
  const route = String(item.route || '');
  if (!route) return null;
  return { path: route, query: { ...cleanQuery(item.query || {}), from } };
}

// ---------------------------------------------------------------- 确认文字
export function pushConfirmText(kind, source = '') {
  const label = kind === 'payment' ? '付款单' : '报销单';
  return `确定要为${source ? ` ${source} ` : '这张单'}创建${label}草稿吗？`;
}
