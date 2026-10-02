import assert from 'node:assert/strict';
import test from 'node:test';
import { buildEmployeeProjectPivot } from '../src/lib/timesheetPivot.js';
import {
  employeeShareRow,
  formatDelta,
  hoursDelta,
  hoursToDays,
  previousPeriod,
  projectNames,
  sharePercent,
  sumHours,
  topProject,
} from '../src/lib/rdReportView.js';

test('previousPeriod steps back one month and across the year boundary', () => {
  assert.equal(previousPeriod('2026-10'), '2026-09');
  assert.equal(previousPeriod('2026-01'), '2025-12');
  assert.equal(previousPeriod('2026-13'), '');
  assert.equal(previousPeriod(''), '');
  assert.equal(previousPeriod('bad'), '');
});

test('sumHours and hoursToDays ignore blanks and use 8 hours per day', () => {
  assert.equal(sumHours([{ hours: 8 }, { hours: '4.5' }, { hours: null }, {}]), 12.5);
  assert.equal(sumHours(undefined), 0);
  assert.equal(hoursToDays(12), 1.5);
});

test('hoursDelta compares with last month and handles missing or zero baselines', () => {
  assert.deepEqual(hoursDelta(110, 100), { pct: 10, direction: 'up' });
  assert.deepEqual(hoursDelta(90, 100), { pct: -10, direction: 'down' });
  assert.deepEqual(hoursDelta(100, 100), { pct: 0, direction: 'flat' });
  assert.equal(hoursDelta(100, null), null);
  assert.equal(hoursDelta(100, undefined), null);
  assert.deepEqual(hoursDelta(100, 0), { pct: null, direction: 'none' });
});

test('formatDelta renders plain text for every direction', () => {
  assert.equal(formatDelta(hoursDelta(103.2, 100)), '↑ 3.2% 较上月');
  assert.equal(formatDelta(hoursDelta(80, 100)), '↓ 20.0% 较上月');
  assert.equal(formatDelta(hoursDelta(100, 100)), '与上月持平');
  assert.equal(formatDelta(hoursDelta(100, 0)), '上月无工时记录');
  assert.equal(formatDelta(null), '');
});

test('sharePercent and employeeShareRow give each employee share of their own total', () => {
  assert.equal(sharePercent(1, 4), 25);
  assert.equal(sharePercent(1, 0), 0);
  assert.deepEqual(employeeShareRow([2, 6, 0], 8), [25, 75, 0]);
  assert.deepEqual(employeeShareRow([2, 6, 0]), [25, 75, 0]);
  assert.deepEqual(employeeShareRow([0, 0], 0), [0, 0]);
  assert.deepEqual(employeeShareRow([1, 1, 1]), [33.33, 33.33, 33.33]);
});

const ROWS = [
  { employee: 'E1', employee_name: 'A', rd_project_code: 'RD1', project_name: 'Alpha', hours: 8 },
  { employee: 'E1', employee_name: 'A', rd_project_code: 'RD2', project_name: 'Beta', hours: 24 },
  { employee: 'E2', employee_name: 'B', rd_project_code: 'RD2', project_name: 'Beta', hours: 8 },
];

test('projectNames maps a project id to its name, falling back to the key suffix', () => {
  const names = projectNames([
    ...ROWS,
    { rd_project_key: 'RD9 | Gamma', rd_project_code: 'RD9', hours: 1 },
    { rd_project_code: 'RD8', hours: 1 },
  ]);
  assert.equal(names['RD1 | Alpha'], 'Alpha');
  assert.equal(names['RD2 | Beta'], 'Beta');
  assert.equal(names['RD9 | Gamma'], 'Gamma');
  assert.equal(names.RD8, undefined);
});

test('topProject returns the project with the most hours and its share', () => {
  const pivot = buildEmployeeProjectPivot(ROWS);
  const top = topProject(pivot, projectNames(ROWS));
  assert.equal(top.label, 'RD2');
  assert.equal(top.name, 'Beta');
  assert.equal(top.hours, 32);
  assert.equal(top.percent, 80);
  assert.equal(topProject({ projects: [], projTotals: [], grand: 0 }), null);
  assert.equal(topProject(undefined), null);
});
