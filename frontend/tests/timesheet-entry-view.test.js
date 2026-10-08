import assert from 'node:assert/strict';
import test from 'node:test';

import {
  PROJECT_COLORS, REMIND_CLOSED_TEXT, barColor, departmentBars, followUpCounts, followUpRows, gapDays, gapText, gapTone, matchesDepartment,
  projectColor, remainingMeta, remindClosed, sharePercent, stackedSegments,
  projectOwner,
  averageFill, capText, daysLeft, deadlineLabel, deadlineTone, defaultNewDays, deriveStatus, filterRoster, followUpList,
  groupByDepartment, lastRemindedText, namesText, pickerOptions, previousPeriod, remindResultText, rosterCounts,
  rosterItemsFromProgress, rowsFromPrevious, serverMessage, stepDays, summarizeProgress, validateEntryRows,
} from '../src/lib/timesheetEntryView.js';

const row = (project, days, extra = {}) => ({ project, project_code: `C-${project}`, project_name: `N-${project}`, occurrence_days: String(days), ...extra });

test('status: over beats everything, none for zero, full within 0.01 day, otherwise part', () => {
  assert.equal(deriveStatus(0, 20), 'none');
  assert.equal(deriveStatus(10, 20), 'part');
  assert.equal(deriveStatus(20, 20), 'full');
  assert.equal(deriveStatus(19.995, 20), 'full');
  assert.equal(deriveStatus(19.98, 20), 'part');
  assert.equal(deriveStatus(20.5, 20), 'over');
  assert.equal(deriveStatus('21', '20'), 'over');
  assert.equal(deriveStatus(undefined, 20), 'none');
});

test('stepper moves by half a day and never goes below half a day', () => {
  assert.equal(stepDays('1', 0.5), '1.5');
  assert.equal(stepDays('1.5', -0.5), '1');
  assert.equal(stepDays('0.5', -0.5), '0.5');
  assert.equal(stepDays('', 0.5), '0.5');
  assert.equal(stepDays('abc', 0.5), '0.5');
  assert.equal(stepDays('2.25', 0.5), '2.75');
});

test('new rows default to one day, less when little room is left, never below half a day', () => {
  assert.equal(defaultNewDays(10), 1);
  assert.equal(defaultNewDays(1), 1);
  assert.equal(defaultNewDays(0.75), 0.5);
  assert.equal(defaultNewDays(0), 0.5);
  assert.equal(defaultNewDays(-3), 0.5);
});

test('average fill: floors to half days and never exceeds the limit', () => {
  const rows = [row('A', 1), row('B', 1), row('C', 1)];
  // 剩余 17，每行 floor(17/3/0.5)*0.5 = 5.5，合计 3 + 16.5 = 19.5 ≤ 20
  const result = averageFill(rows, 20);
  assert.deepEqual(result.rows.map((r) => r.occurrence_days), ['6.5', '6.5', '6.5']);
  assert.equal(result.added, 16.5);
  assert.ok(result.rows.reduce((s, r) => s + Number(r.occurrence_days), 0) <= 20);
  assert.deepEqual(result.rows.map((r) => r.hours), [52, 52, 52]);
});

test('average fill: nothing to do when full, over, empty or less than half a day per person', () => {
  const rows = [row('A', 10), row('B', 10)];
  assert.equal(averageFill(rows, 20).added, 0);
  assert.equal(averageFill(rows, 18).added, 0);
  assert.equal(averageFill([], 20).added, 0);
  // 剩 0.75 天分给 2 行：每行 floor(0.375/0.5)=0
  const thin = averageFill([row('A', 9.5), row('B', 9.75)], 20);
  assert.equal(thin.added, 0);
  assert.strictEqual(thin.rows[0].occurrence_days, '9.5');
  // 不修改入参
  const input = [row('A', 1)];
  averageFill(input, 5);
  assert.equal(input[0].occurrence_days, '1');
});

test('average fill treats invalid day text as zero', () => {
  const result = averageFill([row('A', 'x'), row('B', 2)], 6);
  assert.deepEqual(result.rows.map((r) => r.occurrence_days), ['2', '4']);
});

const projects = [
  { name: 'P1', project_name: 'ACONCA 7961', rd_project_code: 'RD14', project_owner: '演示员工132' },
  { name: 'P2', project_name: 'EFEM 机械手', rd_project_code: 'RD16', project_owner: '演示员工107' },
  { name: 'P3', project_name: '真空腔体', rd_project_code: 'RD17', project_owner: '演示员工132' },
  { name: 'P4', project_name: '晶圆传输', rd_project_code: 'RD18' },
];

test('picker: excludes used projects and searches name, code and owner', () => {
  const all = pickerOptions(projects, { usedIds: ['P2'] });
  assert.deepEqual(all.items.map((i) => i.project.name), ['P1', 'P3', 'P4']);
  assert.equal(all.total, 3);
  assert.deepEqual(pickerOptions(projects, { query: 'rd16' }).items.map((i) => i.project.name), ['P2']);
  assert.deepEqual(pickerOptions(projects, { query: '演示员工132' }).items.map((i) => i.project.name), ['P1', 'P3']);
  assert.deepEqual(pickerOptions(projects, { query: 'aconca 张' }).items.map((i) => i.project.name), ['P1']);
  assert.deepEqual(pickerOptions(projects, { query: '不存在' }).items, []);
  assert.deepEqual(pickerOptions(projects, { query: 'rd16', usedIds: ['P2'] }).items, []);
});

test('picker: recently used first (in recency order), then original order, at most 8 shown', () => {
  const result = pickerOptions(projects, { recentIds: ['P4', 'P2'] });
  assert.deepEqual(result.items.map((i) => i.project.name), ['P4', 'P2', 'P1', 'P3']);
  assert.deepEqual(result.items.map((i) => i.recent), [true, true, false, false]);
  const many = Array.from({ length: 30 }, (_, i) => ({ name: `X${i}`, project_name: `项目${i}`, rd_project_code: `C${i}` }));
  const capped = pickerOptions(many, { recentIds: ['X25'] });
  assert.equal(capped.items.length, 8);
  assert.equal(capped.total, 30);
  assert.equal(capped.items[0].project.name, 'X25');
  assert.equal(pickerOptions(many, { limit: 3 }).items.length, 3);
});

test('days left: whole calendar days between today and the deadline', () => {
  assert.equal(daysLeft('2026-10-31', new Date(2026, 9, 2, 23, 30)), 29);
  assert.equal(daysLeft('2026-10-31', new Date(2026, 9, 31, 0, 5)), 0);
  assert.equal(daysLeft('2026-10-31', new Date(2026, 10, 2)), -2);
  assert.equal(daysLeft('2026-11-03', new Date(2026, 9, 31)), 3);
  assert.equal(daysLeft('', new Date()), null);
  assert.equal(daysLeft('soon', new Date()), null);
  assert.equal(deadlineLabel(5), '还剩 5 天');
  assert.equal(deadlineLabel(0), '今天截止');
  assert.equal(deadlineLabel(-2), '已逾期 2 天');
  assert.equal(deadlineTone(10), 'info');
  assert.equal(deadlineTone(3), 'warn');
  assert.equal(deadlineTone(-1), 'bad');
  assert.equal(deadlineTone(-1, true), 'ok');
  assert.equal(deadlineTone(null), 'info');
});

const people = [
  { employee: 'E1', employee_name: '演示员工181', department: '研发一部', used_days: 20, limit_days: 20, status: 'full' },
  { employee: 'E2', employee_name: '演示员工132', department: '研发一部', used_days: 0, limit_days: 20, status: 'none' },
  { employee: 'E3', employee_name: '演示员工107', department: '研发二部', used_days: 12, limit_days: 20, status: 'part' },
  { employee: 'E4', employee_name: '演示员工161', department: '研发二部', used_days: 21, limit_days: 20, status: 'over' },
  { employee: 'E5', employee_name: '演示员工148', department: '', used_days: 5, limit_days: 20, status: 'part' },
];

test('board summary: server numbers win, missing ones are counted from the list', () => {
  assert.deepEqual(summarizeProgress(people, { total: 5, full: 1, part: 2, none: 1, over: 1, rate: 20 }), { total: 5, full: 1, part: 2, none: 1, over: 1, rate: 20 });
  assert.deepEqual(summarizeProgress(people, null), { total: 5, full: 1, part: 2, none: 1, over: 1, rate: 20 });
  assert.deepEqual(summarizeProgress([], { total: 1, full: 1, part: 0, none: 0, over: 0, rate: 100 }), { total: 1, full: 1, part: 0, none: 0, over: 0, rate: 100 });
  assert.equal(summarizeProgress([], null).rate, 0);
});

test('board grouping: per department counts and completion rate, blank department kept apart', () => {
  const groups = groupByDepartment(people);
  assert.deepEqual(groups.map((g) => g.department), ['研发一部', '研发二部', '未分配部门']);
  assert.deepEqual(groups[0], { department: '研发一部', total: 2, full: 1, part: 0, none: 1, over: 0, rate: 50 });
  assert.deepEqual(groups[1], { department: '研发二部', total: 2, full: 0, part: 1, none: 0, over: 1, rate: 0 });
  assert.equal(groups[2].total, 1);
  assert.deepEqual(groupByDepartment([]), []);
});

test('follow-up list: unfilled first, then partly filled by lowest progress; full and over are left out', () => {
  assert.deepEqual(followUpList(people).map((p) => p.employee), ['E2', 'E5', 'E3']);
  assert.deepEqual(followUpList([]), []);
});

test('names preview and reminder texts', () => {
  assert.equal(namesText([]), '无');
  assert.equal(namesText(people.slice(0, 2)), '演示员工181、演示员工132');
  assert.equal(namesText(people, 3), '演示员工181、演示员工132、演示员工107…');
  assert.equal(remindResultText({ sent: 3, skipped_today: 1, skipped_done: 2 }), '已催办 3 人，1 人今天已催办过，2 人已填满，无需催办');
  assert.equal(remindResultText({ sent: 0, skipped_today: 2, skipped_done: 0 }), '没有发出催办，2 人今天已催办过');
  assert.equal(remindResultText(null), '没有发出催办');
  assert.equal(lastRemindedText('2026-10-02 09:30', new Date(2026, 9, 2, 18)), '今天 09:30');
  assert.equal(lastRemindedText('2026-09-30 09:30', new Date(2026, 9, 2)), '09-30 09:30');
  assert.equal(lastRemindedText('', new Date()), '');
});

test('roster: items from progress, counts and filtering', () => {
  const items = rosterItemsFromProgress(people);
  assert.equal(items[0].name, '演示员工181');
  assert.equal(items[0].used, 20);
  assert.deepEqual(rosterCounts(items), { all: 5, full: 1, todo: 3, over: 1 });
  assert.deepEqual(filterRoster(items, { filter: 'todo' }).map((i) => i.employee), ['E2', 'E3', 'E5']);
  assert.deepEqual(filterRoster(items, { filter: 'over' }).map((i) => i.employee), ['E4']);
  assert.deepEqual(filterRoster(items, { query: 'e3' }).map((i) => i.employee), ['E3']);
  assert.deepEqual(filterRoster(items, { query: '陈' }).map((i) => i.employee), ['E1']);
  assert.deepEqual(filterRoster(items, { department: '研发二部', filter: 'todo' }).map((i) => i.employee), ['E3']);
});

test('copy previous month: only still-selectable projects, de-duplicated, positive days, no remarks', () => {
  const entries = [
    { project: 'P1', project_code: 'RD14', project_name: 'ACONCA 7961', occurrence_days: 5.5, remark: '上月备注' },
    { project: 'P1', project_code: 'RD14', project_name: 'ACONCA 7961', occurrence_days: 1 },
    { project: 'GONE', project_code: 'RD01', project_name: '已结项', occurrence_days: 3 },
    { project: 'P2', project_code: 'RD16', project_name: 'EFEM 机械手', occurrence_days: 0 },
  ];
  const result = rowsFromPrevious(entries, { employee: 'E1', projects });
  assert.equal(result.rows.length, 1);
  assert.equal(result.skipped, 1);
  assert.equal(result.rows[0].project, 'P1');
  assert.equal(result.rows[0].occurrence_days, '5.5');
  assert.equal(result.rows[0].hours, 44);
  assert.equal(result.rows[0].remark, '');
  assert.equal(result.rows[0].monthly_entry_id, '');
  assert.equal(result.rows[0].employee, 'E1');
});

test('validation keeps the original row rules and messages', () => {
  const ok = [row('A', '1.5'), row('B', '2')];
  const base = { employee: 'E1', dayLimit: 20 };
  assert.equal(validateEntryRows(ok, base), '');
  assert.equal(validateEntryRows(ok, { ...base, employee: '' }), '请选择研发人员');
  assert.equal(validateEntryRows(ok, { ...base, hasLegacy: true }), '历史按日记录不能在月度视图中直接修改');
  assert.equal(validateEntryRows([row('', 1, { project: '' })], base), '第 1 行请选择项目');
  assert.equal(validateEntryRows([row('A', 1), row('A', 2)], base), '第 2 行项目重复');
  assert.equal(validateEntryRows([row('A', '1.234')], base), '第 1 行发生天数最多保留两位小数');
  assert.equal(validateEntryRows([row('A', '')], base), '第 1 行发生天数最多保留两位小数');
  assert.equal(validateEntryRows([row('A', '0')], base), '第 1 行发生天数必须大于 0');
  assert.equal(validateEntryRows([row('A', '-1')], base), '第 1 行发生天数最多保留两位小数');
  assert.equal(validateEntryRows([row('A', 12), row('B', 8.01)], base), '当月累计发生天数不能超过 20.00 天');
  assert.equal(validateEntryRows([row('A', 12), row('B', 8)], base), '');
});

test('cap text explains the limit, leave deduction and join / leave dates', () => {
  const text = capText({ month: 4, dayLimit: 20, hourLimit: 160, baseHourLimit: 176, leaveHours: 16, joinedOn: '2026-04-08', relievedOn: '' });
  assert.ok(text.includes('4 月可填 20.0 天（160 小时）'));
  assert.ok(text.includes('日历工时 176 小时'));
  assert.ok(text.includes('已批请假 16 小时'));
  assert.ok(text.includes('2026-04-08 入职，之前的日子不计'));
  assert.ok(!text.includes('离职'));
  assert.ok(capText({ month: 4, dayLimit: 20, hourLimit: 160, relievedOn: '2026-04-20' }).includes('2026-04-20 离职，之后的日子不计'));
});

test('previous period wraps over the year boundary', () => {
  assert.equal(previousPeriod('2026-07'), '2026-06');
  assert.equal(previousPeriod('2026-01'), '2025-12');
  assert.equal(previousPeriod('bad'), '');
});

test('server messages are parsed from frappe payloads and stripped of html', () => {
  const error = { _server_messages: JSON.stringify([JSON.stringify({ message: '<b>月度工时数据已被其他用户更新</b>，请刷新后重试。' })]) };
  assert.equal(serverMessage(error, '保存失败'), '月度工时数据已被其他用户更新，请刷新后重试。');
  assert.equal(serverMessage({ messages: ['a', 'b'] }, 'x'), 'a；b');
  assert.equal(serverMessage({}, '保存失败'), '保存失败');
  assert.equal(serverMessage({ _error_message: '<i>出错</i>' }, 'x'), '出错');
});

const board = [
  { employee: 'A', employee_name: '甲', department: '研发软件部', used_days: 5, limit_days: 22, status: 'part' },
  { employee: 'B', employee_name: '乙', department: '研发软件部', used_days: 0, limit_days: 22, status: 'none' },
  { employee: 'C', employee_name: '丙', department: '研发算法部', used_days: 20, limit_days: 22, status: 'part' },
  { employee: 'D', employee_name: '丁', department: '研发算法部', used_days: 22, limit_days: 22, status: 'full' },
  { employee: 'E', employee_name: '戊', department: '', used_days: 23, limit_days: 22, status: 'over' },
  { employee: 'F', employee_name: '己', department: '研发软件部', used_days: 16, limit_days: 22, status: 'part' },
];

test('board follow-up rows: gap descending, full people left out, over included', () => {
  assert.deepEqual(followUpRows(board).map((p) => p.employee), ['B', 'A', 'F', 'C', 'E']);
  assert.deepEqual(followUpRows([]), []);
});

test('board follow-up rows: department and status filters, blank department is its own bucket', () => {
  assert.deepEqual(followUpRows(board, { department: '研发软件部' }).map((p) => p.employee), ['B', 'A', 'F']);
  assert.deepEqual(followUpRows(board, { department: '研发软件部', status: 'part' }).map((p) => p.employee), ['A', 'F']);
  assert.deepEqual(followUpRows(board, { department: '研发算法部', status: 'none' }), []);
  assert.deepEqual(followUpRows(board, { department: '未分配部门' }).map((p) => p.employee), ['E']);
  assert.deepEqual(followUpRows(board, { department: 'all', status: 'over' }).map((p) => p.employee), ['E']);
  assert.equal(matchesDepartment(board[4], '未分配部门'), true);
  assert.equal(matchesDepartment(board[0], 'all'), true);
  assert.equal(matchesDepartment(board[0], '研发算法部'), false);
});

test('board chip counts are computed inside the selected department', () => {
  assert.deepEqual(followUpCounts(board), { all: 5, none: 1, part: 3, over: 1 });
  assert.deepEqual(followUpCounts(board, '研发软件部'), { all: 3, none: 1, part: 2, over: 0 });
  assert.deepEqual(followUpCounts(board, '研发算法部'), { all: 1, none: 0, part: 1, over: 0 });
});

test('board department bars: filled / total in order of appearance, percent of full people', () => {
  assert.deepEqual(departmentBars(board), [
    { department: '研发软件部', total: 3, full: 0, percent: 0 },
    { department: '研发算法部', total: 2, full: 1, percent: 50 },
    { department: '未分配部门', total: 1, full: 0, percent: 0 },
  ]);
  assert.deepEqual(departmentBars([]), []);
});

test('gap helpers: remaining days, over shown as 超, red from 10 days', () => {
  assert.equal(gapDays(board[0]), 17);
  assert.equal(gapDays(board[3]), 0);
  assert.equal(gapDays(board[4]), 0);
  assert.equal(gapText(board[0]), '−17.0');
  assert.equal(gapText(board[2]), '−2.0');
  assert.equal(gapText(board[4]), '超 1.0');
  assert.equal(gapTone(board[0]), 'bad');
  assert.equal(gapTone(board[5]), '');
  assert.equal(gapTone({ status: 'part', used_days: 12, limit_days: 22 }), 'bad');
  assert.equal(gapTone(board[4]), 'bad');
  assert.equal(barColor('over'), 'var(--rd-bad)');
  assert.equal(barColor('part'), 'var(--rd-ok)');
});

test('reminders are closed once the deadline has passed, open on the deadline day and before', () => {
  assert.equal(remindClosed('2026-06-30', new Date(2026, 9, 8)), true);
  assert.equal(remindClosed('2026-06-30', new Date(2026, 6, 1)), true);
  assert.equal(remindClosed('2026-06-30', new Date(2026, 5, 30, 23, 59)), false);
  assert.equal(remindClosed('2026-10-31', new Date(2026, 9, 8)), false);
  assert.equal(remindClosed('', new Date()), false);
  assert.equal(remindClosed(undefined, new Date()), false);
  assert.equal(REMIND_CLOSED_TEXT, '该月已截止/已分摊，无需催办');
});

test('stacked meter: one segment per project with days, width over max(limit, total), colour by row index', () => {
  const rows = [row('A', 8), row('B', 0), row('C', 6.4), row('D', 'x'), row('E', 5)];
  const segs = stackedSegments(rows, 22);
  assert.deepEqual(segs.map((s) => s.code), ['C-A', 'C-C', 'C-E']);
  assert.deepEqual(segs.map((s) => s.index), [0, 2, 4]);
  assert.deepEqual(segs.map((s) => s.color), [PROJECT_COLORS[0], PROJECT_COLORS[2], PROJECT_COLORS[4]]);
  assert.deepEqual(segs.map((s) => s.pct), [36, 29, 23]);
  assert.equal(segs[0].width, 36.36);
  // 合计超过上限时，分母换成合计，分段加起来正好铺满
  const over = stackedSegments([row('A', 20), row('B', 5)], 22);
  assert.equal(Math.round(over.reduce((s, g) => s + g.width, 0)), 100);
  assert.equal(over[0].pct, 91);
  assert.deepEqual(stackedSegments([], 22), []);
  assert.deepEqual(stackedSegments([row('A', 3)], 0).map((s) => s.width), [100]);
});

test('project colours cycle through five muted colours', () => {
  assert.equal(PROJECT_COLORS.length, 5);
  assert.equal(projectColor(0), PROJECT_COLORS[0]);
  assert.equal(projectColor(5), PROJECT_COLORS[0]);
  assert.equal(projectColor(7), PROJECT_COLORS[2]);
  assert.equal(projectColor(-1), PROJECT_COLORS[4]);
  assert.equal(sharePercent(8, 22), 36);
  assert.equal(sharePercent('x', 22), 0);
  assert.equal(sharePercent(5, 0), 0);
});

test('remaining text: amber when short, green when full, red when over', () => {
  assert.deepEqual(remainingMeta(19.4, 22), { tone: 'warn', text: '还差 2.6 天' });
  assert.deepEqual(remainingMeta(22, 22), { tone: 'ok', text: '已分配满 ✓' });
  assert.deepEqual(remainingMeta(21.995, 22), { tone: 'ok', text: '已分配满 ✓' });
  assert.equal(remainingMeta(0, 22).text, '还差 22.0 天');
  const over = remainingMeta(23.5, 22);
  assert.equal(over.tone, 'bad');
  assert.ok(over.text.startsWith('超出上限 1.5 天'));
});

test('the project owner shown in the picker prefers the display name from the server', () => {
  assert.equal(projectOwner({ project_owner: 'zhang@example.com', project_owner_name: '演示员工132' }), '演示员工132');
  assert.equal(projectOwner({ project_owner: '演示员工107' }), '演示员工107');
});
