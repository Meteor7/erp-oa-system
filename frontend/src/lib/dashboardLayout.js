// 首页看板的排版（2026-10-13）：拿到这个页签 / 分段实际返回的块以后怎么摆。纯函数，不碰页面。
// - 空块（没有行、也没出错）不占卡片，收进最后一行“暂无数据：标题（副标题）· …”；
// - 需要宽度的块（日历、超过 8 根柱子的竖柱、后端标了 wide 的）独占一行；
// - 其余半宽的块按顺序两两成一行，落单的最后一个占满一行；同一行的两张卡等高（CSS）。
// 指标卡按实际张数排列：1–4 演示员工128行放下，5–6 演示员工129列，7 张以上四列。
// 「要我处理」「需要关注」最多先列 5 条，“全部 N 条”就地展开。

export const WIDE_COLS_MIN = 9;
export const ATTN_LIMIT = 5;
export const OVERVIEW_KPI_LIMIT = 4;
export const MORE_KPIS_KEY = 'rayher.dashboard.moreKpis';

// 需要整行宽度的块：日历（团队日历、我的下两周）、柱子多的竖柱（全公司未来 14 天）、后端标了 wide 的。
export function isWideBlock(block = {}) {
  if (block.wide) return true;
  return block.type === 'cols' && Array.isArray(block.rows) && block.rows.length >= WIDE_COLS_MIN;
}

// 空块 = 没有行、也没出错（出错的块照样占卡片，告诉人这一块加载失败）。
export function isEmptyBlock(block = {}) {
  return Boolean(block.empty) && !block.failed;
}

// blocks：blockView 之后的块。返回 { cards: [{ block, span: 'full' | 'half' }], rows: [[block, block?]], empty: [block] }。
// cards 按行展开，直接放进两列的 grid 就是 rows 的样子（成对的两张相邻，整行的 span 两列）。
export function arrangeBlocks(blocks = []) {
  const list = Array.isArray(blocks) ? blocks : [];
  const rows = [];
  const empty = [];
  let open = null;   // 只放了一张半宽卡、还等着配对的那一行
  for (const block of list) {
    if (!block) continue;
    if (isEmptyBlock(block)) {
      empty.push(block);
    } else if (isWideBlock(block)) {
      rows.push([block]);
    } else if (open) {
      open.push(block);
      open = null;
    } else {
      open = [block];
      rows.push(open);
    }
  }
  const cards = [];
  for (const row of rows) {
    const full = row.length === 1;
    for (const block of row) cards.push({ block, span: full ? 'full' : 'half' });
  }
  return { cards, rows, empty };
}

// 空块收起来那一行：每个块的标题 + 副标题（有的话）。
export function emptyStripItems(blocks = []) {
  return (Array.isArray(blocks) ? blocks : []).map((block) => ({
    key: String(block.key || ''), title: String(block.title || ''), sub: String(block.sub || ''), target: block.target || null,
  }));
}

// 指标卡列数：按实际张数，不留半行空位。
export function kpiColumns(count) {
  const n = Math.max(0, Number(count) || 0);
  if (n <= 4) return Math.max(1, n);
  if (n <= 6) return 3;
  return 4;
}

export function kpiGridClass(count) {
  return `is-c${kpiColumns(count)}`;
}

// 总览页先放前 4 张，其余收在“更多指标 N”后面；open 时全部显示。
export function foldKpis(kpis = [], { fold = false, open = false, limit = OVERVIEW_KPI_LIMIT } = {}) {
  const list = Array.isArray(kpis) ? kpis : [];
  if (!fold || list.length <= limit) return { shown: list, hidden: 0, foldable: false };
  return { shown: open ? list : list.slice(0, limit), hidden: list.length - limit, foldable: true };
}

// 「要我处理」「需要关注」：先列前 limit 条，展开后全部。
export function limitRows(items = [], open = false, limit = ATTN_LIMIT) {
  const list = Array.isArray(items) ? items : [];
  const more = Math.max(0, list.length - limit);
  return { shown: open || !more ? list : list.slice(0, limit), total: list.length, more };
}

// 首屏顺序：看整体的岗位（后端 kpis_first）先指标卡，干活的岗位总览先「要我处理」。
export function attentionFirst(page = {}) {
  return Boolean(page && page.attention && page.attention !== 'none' && page.kpisFirst === false);
}

// “更多指标”展开与否，按浏览器记住（看不到 localStorage 就当收起）。
export function readMoreKpis(storage) {
  try {
    const store = storage === undefined ? globalThis.localStorage : storage;
    return store?.getItem(MORE_KPIS_KEY) === '1';
  } catch {
    return false;
  }
}

export function writeMoreKpis(open, storage) {
  try {
    const store = storage === undefined ? globalThis.localStorage : storage;
    store?.setItem(MORE_KPIS_KEY, open ? '1' : '0');
  } catch {
    // 隐私模式等写不进去，不影响页面
  }
}
