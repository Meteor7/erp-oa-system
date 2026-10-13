// 看板排版（2026-10-13）：块怎么配对、空块收起、指标卡列数、总览“更多指标”、要我处理 / 需要关注只先列 5 条。
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ATTN_LIMIT, MORE_KPIS_KEY, arrangeBlocks, attentionFirst, emptyStripItems, foldKpis, isEmptyBlock, isWideBlock, kpiColumns, kpiGridClass,
  limitRows, readMoreKpis, writeMoreKpis,
} from '../src/lib/dashboardLayout.js';
import { blockView, pageView } from '../src/lib/dashboardView.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const bars = (key, n = 2, extra = {}) => blockView({ key, type: 'bars', title: key, rows: Array.from({ length: n }, (_, i) => ({ label: `r${i}`, value: '1', pct: 10 })), ...extra });
const cols = (key, n) => blockView({ key, type: 'cols', title: key, rows: Array.from({ length: n }, (_, i) => ({ label: String(i), value: '1', pct: 10 })) });
const empty = (key, extra = {}) => blockView({ key, type: 'bars', title: `T-${key}`, rows: [], ...extra });
const calendar = (key) => blockView({ key, type: 'calendar', title: key, days: [{ date: '2026-10-13', label: '10-13', day: 13, weekday: '二' }], people: [{ name: 'A', cells: [null] }], totals: [] });
const keys = (rows) => rows.map((row) => row.map((block) => block.key));

test('half blocks pair in order and an odd leftover takes the whole row', () => {
  const out = arrangeBlocks([bars('a'), bars('b'), bars('c')]);
  assert.deepEqual(keys(out.rows), [['a', 'b'], ['c']]);
  assert.deepEqual(out.cards.map((card) => [card.block.key, card.span]), [['a', 'half'], ['b', 'half'], ['c', 'full']]);
  assert.deepEqual(arrangeBlocks([bars('a'), bars('b')]).cards.map((card) => card.span), ['half', 'half']);
  assert.deepEqual(arrangeBlocks([bars('a')]).cards.map((card) => card.span), ['full']);
});

test('wide blocks take a row of their own and halves still pair around them', () => {
  const out = arrangeBlocks([bars('a'), calendar('cal'), bars('b'), cols('days', 14), bars('c')]);
  assert.deepEqual(keys(out.rows), [['a', 'b'], ['cal'], ['days'], ['c']]);
  assert.deepEqual(out.cards.map((card) => card.span), ['half', 'half', 'full', 'full', 'full']);
});

test('what counts as wide: calendars, more than 8 columns, or marked wide by the server', () => {
  assert.equal(isWideBlock(calendar('x')), true);
  assert.equal(isWideBlock(cols('x', 9)), true);
  assert.equal(isWideBlock(cols('x', 8)), false);
  assert.equal(isWideBlock(cols('x', 6)), false);
  assert.equal(isWideBlock(bars('x', 20)), false);
  assert.equal(isWideBlock(blockView({ key: 'x', type: 'list', rows: [{ label: 'a' }], wide: true })), true);
  assert.equal(blockView({ key: 'x', type: 'list', rows: [], wide: 'yes' }).wide, false);
});

test('empty blocks are not cards: they go to one strip at the end, failed blocks stay cards', () => {
  const failed = blockView({ key: 'f', type: 'bars', title: 'F', rows: [], error: 'x' });
  const out = arrangeBlocks([empty('cost', { sub: '10 月还没有登记费用', target: { key: 'dorm.monthly', params: {} } }), empty('split'), bars('a'), failed, bars('b')]);
  assert.deepEqual(keys(out.rows), [['a', 'f'], ['b']]);
  assert.deepEqual(out.empty.map((block) => block.key), ['cost', 'split']);
  assert.equal(isEmptyBlock(failed), false);
  assert.deepEqual(emptyStripItems(out.empty), [
    { key: 'cost', title: 'T-cost', sub: '10 月还没有登记费用', target: { key: 'dorm.monthly', params: {} } },
    { key: 'split', title: 'T-split', sub: '', target: null },
  ]);
  const calendarEmpty = blockView({ key: 'c', type: 'calendar', title: 'C', days: [], people: [] });
  assert.deepEqual(arrangeBlocks([calendarEmpty]).empty.map((block) => block.key), ['c']);
  assert.deepEqual(arrangeBlocks(null), { cards: [], rows: [], empty: [] });
});

test('kpi columns follow the real count', () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12].map(kpiColumns), [1, 1, 2, 3, 4, 3, 3, 4, 4, 4, 4]);
  assert.equal(kpiGridClass(6), 'is-c3');
  assert.equal(kpiGridClass(3), 'is-c3');
  assert.equal(kpiGridClass(8), 'is-c4');
});

test('the overview shows four cards and keeps the rest behind "more"', () => {
  const kpis = Array.from({ length: 8 }, (_, i) => ({ key: `k${i}` }));
  const closed = foldKpis(kpis, { fold: true, open: false });
  assert.deepEqual([closed.shown.length, closed.hidden, closed.foldable], [4, 4, true]);
  assert.equal(foldKpis(kpis, { fold: true, open: true }).shown.length, 8);
  assert.equal(foldKpis(kpis, { fold: false }).foldable, false);
  assert.equal(foldKpis(kpis.slice(0, 4), { fold: true }).foldable, false);
  assert.deepEqual(foldKpis(undefined, { fold: true }), { shown: [], hidden: 0, foldable: false });
});

test('the "more" state is remembered per browser and survives a broken storage', () => {
  const store = new Map();
  const storage = { getItem: (key) => (store.has(key) ? store.get(key) : null), setItem: (key, value) => store.set(key, value) };
  assert.equal(readMoreKpis(storage), false);
  writeMoreKpis(true, storage);
  assert.equal(store.get(MORE_KPIS_KEY), '1');
  assert.equal(readMoreKpis(storage), true);
  writeMoreKpis(false, storage);
  assert.equal(readMoreKpis(storage), false);
  const broken = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
  assert.equal(readMoreKpis(broken), false);
  assert.doesNotThrow(() => writeMoreKpis(true, broken));
  assert.equal(readMoreKpis(null), false);
});

test('todos and alerts list five rows first and expand in place', () => {
  const items = Array.from({ length: 12 }, (_, i) => i);
  assert.equal(ATTN_LIMIT, 5);
  assert.deepEqual(limitRows(items, false), { shown: [0, 1, 2, 3, 4], total: 12, more: 7 });
  assert.equal(limitRows(items, true).shown.length, 12);
  assert.deepEqual(limitRows([1, 2, 3], false), { shown: [1, 2, 3], total: 3, more: 0 });
  assert.deepEqual(limitRows(null), { shown: [], total: 0, more: 0 });
});

test('working roles see their todos before the kpis; the server decides', () => {
  assert.equal(attentionFirst(pageView({ has_todos: true, has_alerts: true, kpis_first: false })), true);
  assert.equal(attentionFirst(pageView({ has_todos: true, kpis_first: true })), false);
  assert.equal(attentionFirst(pageView({ has_todos: true })), false, 'old payloads without the flag keep kpis first');
  assert.equal(attentionFirst(pageView({ kpis_first: false })), false, 'nothing to put first');
});

test('the page wires the arrangement, the fold and the empty strip', () => {
  const page = read('../src/pages/Dashboard.vue');
  assert.match(page, /from '\.\.\/lib\/dashboardLayout'/);
  assert.match(page, /arrangeBlocks\(page\.value\.blocks\)/);
  assert.match(page, /page\.value\.sections\.map\(\(section\) => arrangeBlocks\(section\.blocks\)\)/);
  assert.match(page, /:class="\{ 'is-full': card\.span === 'full' \}"/);
  assert.match(page, /<DashNoData :blocks="arranged\.empty"/);
  assert.match(page, /<DashNoData :blocks="sectionLayouts\[index\]\.empty"/);
  assert.match(page, /kpiGridClass\(kpiFold\.shown\.length\)/);
  assert.match(page, /kpiGridClass\(section\.kpis\.length\)/);
  assert.match(page, /fold: activeKey\.value === 'overview'/);
  assert.match(page, /更多指标 \$\{kpiFold\.hidden\}/);
  assert.match(page, /writeMoreKpis\(moreKpis\.value\)/);
  const strip = read('../src/components/dashboard/DashNoData.vue');
  assert.match(strip, /暂无数据：/);
  assert.match(strip, /item\.link\.state === 'link'/);
  assert.match(strip, /（\{\{ item\.sub \}\}）/);
  for (const name of ['DashTodos', 'DashAlerts']) {
    const source = read(`../src/components/dashboard/${name}.vue`);
    assert.match(source, /limitRows\(props\.\w+, open\.value\)/, name);
    assert.match(source, /v-for="[^"]+ in view\.shown"/, name);
    assert.match(source, /全部 \$\{view\.total\} 条/, name);
  }
});

test('cards in one row stretch to the same height and collapse to one column under 860px', () => {
  const css = read('../src/styles/dashboardUi.css');
  assert.match(css, /\.db-blocks \{[^}]*align-items: stretch/);
  assert.match(css, /\.db-attn \{[^}]*align-items: stretch/);
  assert.match(css, /\.db-blocks > \.db-block \{[^}]*flex-direction: column/);
  assert.match(css, /\.db-block\.is-full \{ grid-column: 1 \/ -1; \}/);
  assert.match(css, /\.db-foot \{[^}]*margin-top: auto/);
  for (const n of [1, 2, 3, 4]) assert.ok(css.includes(`.db-kpis.is-c${n}`), n);
  assert.match(css, /@media \(max-width: 860px\) \{\s*\.db-attn\.is-both, \.db-blocks \{ grid-template-columns: minmax\(0, 1fr\); \}/);
  assert.match(css, /\.db-nodata \{/);
});
