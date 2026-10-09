// 页面筛选 <-> 地址 ?query 的双向绑定。
// 看板、提醒点进来的链接把筛选放在地址里（/personnel?status=active&reminder=expiring），
// 页面进入时从地址初始化筛选；用户再改筛选，地址用 router.replace 跟着变（不产生历史记录，
// 浏览器「返回」仍然回到来源页），刷新后筛选还在。
import { watch } from "vue";

// 地址里某个参数的字符串值（重复参数取第一个，没有返回 ""）
export function queryText(query, key) {
  const value = query?.[key];
  const first = Array.isArray(value) ? value[0] : value;
  return first === undefined || first === null ? "" : String(first).trim();
}

// 把本页管的参数（ownKeys）按 own 重写，其他参数原样保留：
// from=（返回看板用）、room=（打开某个房间）这类不归筛选管的参数不能丢。空值不写，所以清除筛选后地址回到无参数。
export function mergeQuery(current, ownKeys, own) {
  const next = {};
  for (const [key, value] of Object.entries(current || {})) {
    if (!ownKeys.includes(key)) next[key] = value;
  }
  for (const key of ownKeys) {
    const value = own?.[key];
    if (value !== undefined && value !== null && value !== "") next[key] = String(value);
  }
  return next;
}

function normalized(query) {
  const result = {};
  for (const key of Object.keys(query || {}).sort()) {
    const text = queryText(query, key);
    if (text !== "") result[key] = text;
  }
  return JSON.stringify(result);
}

export function sameQuery(a, b) {
  return normalized(a) === normalized(b);
}

// specs：每项 { keys, read(query)->state, apply(state), snapshot()->state, toQuery(state)->{key:value}, sources:[ref] }
//   read      把地址解析成规范化的筛选状态（非法值丢掉、缺省值补齐）
//   toQuery   只输出非缺省值，缺省值不进地址
// 必须在 setup 里调用，并放在页面自己的筛选 watch 之后（保证页面先把互相关联的筛选理顺，再写地址）。
export function bindRouteFilters({ route, router, specs }) {
  // 离开本页的那一刻 route 已经是新页面的地址，此时不能再把筛选写回去（否则会把用户拽回来）。
  const path = route.path;
  const keys = specs.flatMap((spec) => spec.keys);
  for (const spec of specs) spec.apply(spec.read(route.query));

  watch(specs.flatMap((spec) => spec.sources), () => {
    if (route.path !== path) return;
    const own = Object.assign({}, ...specs.map((spec) => spec.toQuery(spec.snapshot())));
    const query = mergeQuery(route.query, keys, own);
    if (sameQuery(query, route.query)) return;
    Promise.resolve(router.replace({ path, query })).catch(() => {});
  });

  // 同一个页面又被带着新参数点进来（侧栏链接、看板链接），组件不会重建，要按新地址重置筛选。
  watch(() => route.query, (query) => {
    if (route.path !== path) return;
    for (const spec of specs) {
      const next = spec.read(query);
      if (JSON.stringify(spec.toQuery(next)) !== JSON.stringify(spec.toQuery(spec.snapshot()))) spec.apply(next);
    }
  });
}
