import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { BLOCK_TYPES, blockView, calendarView, pageView, sectionView, staffLevel } from '../src/lib/dashboardView.js';
import { listScope, ownedRows } from '../src/lib/procurementView.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

const days = Array.from({ length: 14 }, (_, index) => ({
  date: `2026-10-${12 + index}`, label: `10/${12 + index}`, day: 12 + index, weekday: '一', off_day: [5, 6, 12, 13].includes(index),
}));
const calendarBlock = (extra = {}) => ({
  key: 'block.team_calendar', type: 'calendar', title: '团队日历', sub: '', rows: [], more: '考勤中心', hint: '', error: null, days,
  people: [
    { name: '杨员工', cells: [{ kind: 'annual', pending: false }, { kind: 'comp', pending: true }, null, { kind: 'bogus' }, ...Array(10).fill(null)] },
    { name: '演示员工120', cells: Array(14).fill(null) },
  ],
  totals: days.map((day, index) => (day.off_day ? { off: 0, present: null } : { off: index === 0 ? 1 : 0, present: index === 0 ? 1 : 2 })),
  ...extra,
});

test('calendar is a block type and has no plain rows', () => {
  assert.ok(BLOCK_TYPES.includes('calendar'));
  const view = blockView(calendarBlock());
  assert.equal(view.type, 'calendar');
  assert.equal(view.wide, true);
  assert.deepEqual(view.rows, []);
  assert.equal(view.empty, false);
});

test('calendar cells keep the kind, mark pending ones and drop unknown kinds', () => {
  const { people, days: shown } = calendarView(calendarBlock());
  assert.equal(shown.length, 14);
  assert.deepEqual(shown[5], { date: '2026-10-17', label: '10/17', day: 17, weekday: '一', off: true });
  assert.deepEqual(people[0].cells[0], { kind: 'annual', pending: false, title: '杨员工 10/12 年假' });
  assert.equal(people[0].cells[1].pending, true);
  assert.match(people[0].cells[1].title, /调休（审批中）/);
  assert.equal(people[0].cells[2], null);
  assert.equal(people[0].cells[3], null, 'unknown kinds are not drawn');
  assert.equal(people[1].cells.every((cell) => cell === null), true);
});

test('present counts: weekends have none and low-staff days are marked orange or red', () => {
  const view = calendarView(calendarBlock());
  assert.equal(view.totals[5].present, null);
  assert.equal(view.totals[5].title, '休息日');
  assert.equal(view.totals[0].present, 1);
  assert.equal(view.headcount, 2);
  // 15 人：缺 3 人橙（至少 3 人且占 20%），缺 6 人红（占 40%）
  assert.equal(staffLevel(2, 15), '');
  assert.equal(staffLevel(3, 15), 'mid');
  assert.equal(staffLevel(5, 15), 'mid');
  assert.equal(staffLevel(6, 15), 'low');
  assert.equal(staffLevel(3, 5), 'low', '3 of 5 is 60%');
  assert.equal(staffLevel(2, 4), '', 'fewer than three people never alert');
  assert.equal(staffLevel(0, 0), '');
});

test('an empty calendar or a failed one is shown as such', () => {
  assert.equal(blockView(calendarBlock({ people: [] })).empty, true);
  const failed = blockView(calendarBlock({ error: 'x' }));
  assert.equal(failed.failed, true);
  assert.equal(failed.calendar, null);
  assert.deepEqual(calendarView({}), { days: [], people: [], totals: [], legend: calendarView({}).legend, headcount: 0 });
});

test('sections carry their own cards and blocks, and empty sections vanish', () => {
  const section = sectionView({ title: '考勤', sub: '只有汇总', kpis: [{ key: 'att.trip', label: '出差中', value: 2 }], blocks: [{ key: 'b', type: 'bars', rows: [{ label: 'x', value: '1', pct: 10 }] }, { key: 'weird', type: 'pie' }] });
  assert.equal(section.title, '考勤');
  assert.equal(section.kpis[0].value, '2');
  assert.deepEqual(section.blocks.map((block) => block.key), ['b']);
  const page = pageView({ kpis: [], blocks: [], sections: [{ title: '人员', kpis: [{ key: 'k', label: 'k', value: 1 }] }, { title: '空', kpis: [], blocks: [] }] });
  assert.deepEqual(page.sections.map((item) => item.title), ['人员']);
  assert.equal(page.isEmpty, false);
  assert.equal(pageView({ kpis: [], blocks: [], sections: [] }).isEmpty, true);
});

test('the dashboard page renders sections and the calendar block with the shared styles', () => {
  const page = read('../src/pages/Dashboard.vue');
  assert.match(page, /v-for="\(section, index\) in page\.sections"/);
  assert.match(page, /class="db-sec-h"/);
  const block = read('../src/components/dashboard/DashBlock.vue');
  assert.match(block, /block\.type === 'calendar'/);
  assert.match(block, /class="db-cal"/);
  assert.match(block, /在岗人数/);
  assert.match(block, /:class="\{ 'is-failed': block\.failed, 'is-wide': block\.wide \}"/);
  const css = read('../src/styles/dashboardUi.css');
  for (const rule of ['.db-cal-c.k-annual', '.db-cal-c.k-trip', '.db-cal-s.is-low', '.db-cal-c.pend', '.db-block.is-wide', '.db-sec-h']) assert.ok(css.includes(rule), rule);
});

test('the procurement list knows the project-owner scope and never lists the owner\'s own requests there', () => {
  assert.equal(listScope({ scope: 'owned' }, 'mine'), 'owned');
  assert.equal(listScope({ scope: 'nope' }, 'mine'), 'mine');
  const rows = [
    { name: 'A', project_owner: 'Owner@tests-x.example.invalid', owner: 'bob@tests-x.example.invalid', employee: 'E2', workflow_status: '待审批' },
    { name: 'B', project_owner: 'person041@tests-x.example.invalid', owner: 'person041@tests-x.example.invalid', employee: 'E1', workflow_status: '已完成' },
    { name: 'C', project_owner: 'person041@tests-x.example.invalid', owner: 'carol@tests-x.example.invalid', employee: 'E1', workflow_status: '已完成' },
    { name: 'D', project_owner: 'person041@tests-x.example.invalid', owner: 'dan@tests-x.example.invalid', employee: 'E4', workflow_status: '草稿' },
    { name: 'E', project_owner: 'person040@tests-x.example.invalid', owner: 'eve@tests-x.example.invalid', employee: 'E5', workflow_status: '已完成' },
  ];
  assert.deepEqual(ownedRows(rows, 'person041@tests-x.example.invalid', 'E1').map((row) => row.name), ['A']);
  assert.deepEqual(ownedRows(rows, 'person041@tests-x.example.invalid').map((row) => row.name), ['A', 'C']);
  assert.deepEqual(ownedRows(rows, ''), []);
  assert.deepEqual(ownedRows(null, 'person041@tests-x.example.invalid'), []);
  const list = read('../src/components/procurement/ProcList.vue');
  assert.match(list, /key: 'owned', label: '我负责的项目'/);
  assert.match(list, /listFor\('all'\)/);
  const home = read('../src/components/procurement/ProcHome.vue');
  assert.match(home, /scope: 'owned'/);
  assert.match(read('../src/components/procurement/ProcurementWorkbench.vue'), /currentUser: computed/);
});
