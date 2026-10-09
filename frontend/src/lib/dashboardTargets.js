// 首页看板的点击跳转：后端只返回 {key, params}，这里按同一份 targets.json 对应到路由。
// 目标表不手写（单一来源在 rayher_hr_payroll/dashboard/targets.json），页面里 table = buildTargetTable(raw)。
// 纯函数，不依赖 window / router，方便单元测试。
import { cleanQuery, hereAsFrom, resolveKpiTarget, withFrom } from './navContext.js';

// 接受整份 JSON（{ targets: {...} }）或直接是 targets 这一层。
export function buildTargetTable(json) {
  const source = (json && typeof json === 'object' && json.targets && typeof json.targets === 'object') ? json.targets : (json || {});
  const table = {};
  for (const [key, spec] of Object.entries(source)) {
    if (!spec || typeof spec !== 'object' || typeof spec.path !== 'string' || !spec.path.startsWith('/')) continue;
    table[key] = {
      key,
      label: String(spec.label || ''),
      path: spec.path,
      query: cleanQuery(spec.query || {}),
      params: Array.isArray(spec.params) ? spec.params.map(String) : [],
    };
  }
  return table;
}

// 固定的 query + 调用方带来的动态参数：参数名不在表里声明的丢掉，空值丢掉。
export function mergeQuery(spec, params = {}) {
  const query = { ...spec.query };
  for (const name of spec.params) {
    const value = (params || {})[name];
    if (value === undefined || value === null || value === '') continue;
    query[name] = String(value);
  }
  return query;
}

// 从看板点出去后，目标页的"返回"回到当前页签：/dashboard?tab=xxx
export function dashboardFrom(tab) {
  return hereAsFrom('/dashboard', tab ? { tab } : {});
}

// 一个目标现在能不能点：
//   none    —— 这一项本来就没有跳转（后端没给 target），只是显示；
//   link    —— 可以点，to = { path, query }；
//   unknown —— 目标名不在表里（前后端漂移了），置灰但不报错；
//   denied  —— 当前账号打不开那个页面（canSee 为假，或"全部"范围没有权限），置灰。
// access = { canSee(path)，以及 expenseBoards.boardAccess() 的 claimAll / travelAll }
export function targetState(target, { table = {}, from = '', access = {} } = {}) {
  if (!target || !target.key) return { state: 'none', to: null };
  const spec = table[target.key];
  if (!spec) return { state: 'unknown', to: null };
  const to = { path: spec.path, query: mergeQuery(spec, target.params) };
  if (typeof access.canSee === 'function' && !access.canSee(spec.path)) return { state: 'denied', to: null };
  if (!resolveKpiTarget(to, access)) return { state: 'denied', to: null };
  return { state: 'link', to: withFrom(to, from) };
}

// 只要地址：打不开 / 没有 / 未知都是 null。
export function resolveTarget(target, options = {}) {
  return targetState(target, options).to;
}

// 置灰时鼠标悬停的说明。
export function targetHint(state) {
  if (state === 'denied') return '你的账号没有权限打开这个页面';
  if (state === 'unknown') return '这个入口暂时不可用';
  return '';
}
