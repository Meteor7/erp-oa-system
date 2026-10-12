import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { DETAIL_PATH, cellClass, detailBack, detailItem, detailParams, detailPeriod, rowClickable } from '../src/lib/dashboardDetail.js';
import { buildTargetTable, targetState } from '../src/lib/dashboardTargets.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const raw = JSON.parse(read('../../rayher_hr_payroll/dashboard/targets.json'));
const table = buildTargetTable(raw);

test('the detail list is named by letters, digits, dots and underscores only; the period only by YYYY-MM', () => {
  assert.equal(detailItem({ item: 'approval.stuck' }), 'approval.stuck');
  assert.equal(detailItem({ item: ['proc.po_overdue', 'x'] }), 'proc.po_overdue');
  for (const bad of ['', undefined, '../etc/passwd', 'a b', 'a;b', 'x'.repeat(81), '<script>']) assert.equal(detailItem({ item: bad }), '', String(bad));
  assert.equal(detailPeriod({ period: '2026-10' }), '2026-10');
  for (const bad of ['', '2026-13', '2026-1', '26-10', 'abc']) assert.equal(detailPeriod({ period: bad }), '', bad);
  assert.deepEqual(detailParams({ item: 'cost.total', period: '2026-10' }), { item: 'cost.total', period: '2026-10' });
  assert.deepEqual(detailParams({ item: 'cost.total', period: 'oops' }), { item: 'cost.total' });
});

test('back goes to the page the card was on, never off site, and falls back to the dashboard', () => {
  assert.equal(detailBack({ from: '/dashboard?tab=cost' }), '/dashboard?tab=cost');
  assert.equal(detailBack({}), '/dashboard');
  assert.equal(detailBack({ from: 'list' }), '/dashboard');
  assert.equal(detailBack({ from: '//evil.example.com' }), '/dashboard');
  assert.equal(detailBack({ from: 'https://evil.example.com/x' }), '/dashboard');
});

test('only rows whose target can be opened are clickable', () => {
  assert.equal(rowClickable({ state: 'link', to: { path: '/x' } }), true);
  for (const state of ['none', 'denied', 'unknown']) assert.equal(rowClickable({ state, to: null }), false, state);
  assert.equal(rowClickable(undefined), false);
  assert.equal(cellClass({ align: 'r' }), 'is-r');
  assert.equal(cellClass({ align: '' }), '');
  assert.equal(cellClass(undefined), '');
});

test('the drill target in targets.json opens the detail page with the item and the period', () => {
  const spec = raw.targets.drill;
  assert.equal(spec.path, DETAIL_PATH);
  assert.deepEqual(spec.params, ['item', 'period']);
  const open = targetState({ key: 'drill', params: { item: 'approval.stuck', period: '2026-10', ignored: 'x' } }, { table, from: '/dashboard?tab=overview', access: { canSee: () => true } });
  assert.equal(open.state, 'link');
  assert.equal(open.to.path, '/dashboard/detail');
  assert.equal(open.to.query.item, 'approval.stuck');
  assert.equal(open.to.query.period, '2026-10');
  assert.equal(open.to.query.ignored, undefined);
  assert.equal(open.to.query.from, '/dashboard?tab=overview');
  const denied = targetState({ key: 'drill', params: { item: 'approval.stuck' } }, { table, access: { canSee: () => false } });
  assert.equal(denied.state, 'denied');
});

test('the page, the route and the access rule are wired up', () => {
  const page = read('../src/pages/DashboardDetail.vue');
  assert.match(page, /rayher_hr_payroll\.api\.dashboard_home\.get_detail/);
  assert.match(page, /method: 'GET'/);
  assert.match(page, /makeParams: \(\) => detailParams\(route\.query\)/);
  assert.match(page, /targetState\(target, \{ table, from: here\.value, access \}\)/);     // 点一行进真实单据，返回时回到这张清单
  assert.match(page, /router\.push\(detailBack\(route\.query\)\)/);
  assert.match(page, /data\.rows\.length/);
  assert.match(page, /这个清单暂时看不到/);
  assert.match(page, /class="dd-table"/);
  assert.match(read('../src/router.js'), /\{ path: '\/dashboard\/detail', component: \(\) => import\('\.\/pages\/DashboardDetail\.vue'\) \}/);
  assert.match(read('../src/lib/access.js'), /if \(path === '\/dashboard\/detail'\) return '\/dashboard';/);
  assert.match(read('../src/lib/navContext.js'), /'\/dashboard\/detail': '看板明细'/);
  const css = read('../src/styles/dashboardUi.css');
  for (const rule of ['.db .dd-table', '.db .dd-table tr.is-link:hover td', '.db .dd-card']) assert.ok(css.includes(rule), rule);
});

test('every param the detail page reads is declared for it in targets.json', () => {
  const page = read('../src/pages/DashboardDetail.vue') + read('../src/lib/dashboardDetail.js');
  for (const name of raw.targets.drill.params) assert.match(page, new RegExp(`query\\.${name}\\b`), name);
});
