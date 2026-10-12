import assert from 'node:assert/strict';
import test from 'node:test';

import {
  PROJECT_COLORS, REMIND_CLOSED_TEXT, barColor, departmentBars, followUpCounts, followUpRows, gapDays, gapText, gapTone, matchesDepartment,
  projectColor, remainingMeta, remindClosed, sharePercent, stackedSegments,
  projectOwner,
  averageFill, canStepDown, capText, daysLeft, daysOfHours, deadlineLabel, deadlineTone, defaultNewHours, deriveStatus, filterRoster, followUpList,
  groupByDepartment, isValidHoursText, lastRemindedText, namesText, pickerOptions, previousPeriod, remindResultText, rosterCounts,
  rosterItemsFromProgress, rowFromProject, rowHours, rowsFromPrevious, serverMessage, stepHours, sumDays, sumHours, summarizeProgress,
  validateEntryRows, fmtDaysExact, fmtHours, remainingHours, topUpRow, trimHours,
} from '../src/lib/timesheetEntryView.js';

// 一行月度工时：hours 是填的小时（字符串），occurrence_days 是反推的天数（显示用）
const row = (project, hours, extra = {}) => ({ project, project_code: `C-${project}`, project_name: `N-${project}`, hours: String(hours), ...extra });

test('status is exact in hours: over beats everything, none for zero, full only when the hours equal the limit', () => {
  assert.equal(deriveStatus(0, 0), 'full');
  assert.equal(deriveStatus(0, 160), 'none');
  assert.equal(deriveStatus(100, 160), 'part');
  assert.equal(deriveStatus(160, 160), 'full');
  assert.equal(deriveStatus(159.99, 160), 'part');            // 没有零头容差：差 0.01 小时也是没填满
  assert.equal(deriveStatus(160.01, 160), 'over');
  assert.equal(deriveStatus('161', '160'), 'over');
  assert.equal(deriveStatus(undefined, 160), 'none');
});

test('hours are the source and days are derived from them (hours / 8, two decimals)', () => {
  assert.equal(daysOfHours(160), 20);
  assert.equal(daysOfHours(173), 21.63);                       // 21.625，只是显示
  assert.equal(daysOfHours(3), 0.38);
  assert.equal(daysOfHours('x'), 0);
  assert.equal(rowHours({ hours: '12.5' }), 12.5);
  assert.equal(rowHours({ hours: 'x' }), 0);
  assert.equal(rowHours({ hours: '-3' }), 0);
  assert.equal(sumHours([row('A', 100), row('B', 73)]), 173);
  assert.equal(sumDays([row('A', 100), row('B', 73)]), 21.63);
  assert.equal(trimHours(10), '10');
  assert.equal(trimHours(10.5), '10.5');
});

test('the stepper moves by one hour and never goes below half an hour', () => {
  assert.equal(stepHours('10', 1), '11');
  assert.equal(stepHours('10', -1), '9');
  assert.equal(stepHours('1', -1), '0.5');
  assert.equal(stepHours('0.5', 1), '1.5');
  assert.equal(stepHours('', 1), '1.5');
  assert.equal(stepHours('abc', 1), '1.5');
  assert.equal(stepHours('2.25', 1), '3.25');
  assert.equal(canStepDown('1'), true);
  assert.equal(canStepDown('0.5'), false);
  assert.equal(canStepDown(''), false);
});

test('hour input: at most two decimals and greater than zero', () => {
  for (const ok of ['1', '8', '172.5', '0.25', '10.00']) assert.equal(isValidHoursText(ok), true, ok);
  for (const bad of ['', '0', '0.00', '-1', '1.234', 'abc', '1e2', ' ']) assert.equal(isValidHoursText(bad), false, bad);
});

test('new rows default to a day of hours, less when little room is left, never below half an hour', () => {
  assert.equal(defaultNewHours(100), 8);
  assert.equal(defaultNewHours(8), 8);
  assert.equal(defaultNewHours(5), 5);
  assert.equal(defaultNewHours(5.7), 5);
  assert.equal(defaultNewHours(1), 1);
  assert.equal(defaultNewHours(0.75), 0.5);
  assert.equal(defaultNewHours(0), 0.5);
  assert.equal(defaultNewHours(-3), 0.5);
  const made = rowFromProject({ name: 'P1', rd_project_code: 'RD14', project_name: 'ACONCA' }, 'E1', 8);
  assert.deepEqual([made.hours, made.occurrence_days, made.project, made.employee, made.monthly_entry_id], ['8', 1, 'P1', 'E1', '']);
});

test('average fill: whole hours first, the leftover goes to the last row so the total reaches the limit', () => {
  const rows = [row('A', 8), row('B', 8), row('C', 8)];
  // 上限 160：剩余 136，每行 floor(136/3) = 45，合计 24 + 135 = 159，零头 1 小时加在最后一行 -> 正好 160
  const result = averageFill(rows, 160);
  assert.deepEqual(result.rows.map((r) => r.hours), ['53', '53', '54']);
  assert.deepEqual(result.rows.map((r) => r.occurrence_days), [6.63, 6.63, 6.75]);
  assert.equal(result.added, 136);
  assert.equal(sumHours(result.rows), 160);
  assert.equal(deriveStatus(sumHours(result.rows), 160), 'full');
});

test('average fill: nothing to do when full, over or empty; a thin leftover goes to the last row; the input is not changed', () => {
  assert.equal(averageFill([row('A', 80), row('B', 80)], 160).added, 0);
  assert.equal(averageFill([row('A', 80), row('B', 80)], 150).added, 0);
  assert.equal(averageFill([], 160).added, 0);
  const thin = averageFill([row('A', 79.5), row('B', 79.75)], 160);                  // 剩 0.75 小时：每行整数小时是 0，零头全给最后一行
  assert.equal(thin.added, 0.75);
  assert.deepEqual(thin.rows.map((r) => r.hours), ['79.5', '80.5']);
  const input = [row('A', 1)];
  averageFill(input, 5);
  assert.equal(input[0].hours, '1');
  assert.deepEqual(averageFill([row('A', 'x'), row('B', 2)], 6).rows.map((r) => r.hours), ['2', '4']);   // 填错的当 0 算
});

// 请假 3 小时后上限 173 小时：小时是精确的，不再有"最多 21.62 天"的取整
const CAP = 173;

test('cap 173 h: 173 is full, 172.5 is part, 173.5 is over, remaining is exact', () => {
  assert.equal(remainingHours(168, CAP), 5);
  assert.equal(remainingHours(172.5, CAP), 0.5);
  assert.equal(remainingHours(173, CAP), 0);
  assert.equal(remainingHours(180, CAP), 0);
  assert.equal(deriveStatus(173, CAP), 'full');
  assert.equal(deriveStatus(172.5, CAP), 'part');
  assert.equal(deriveStatus(173.5, CAP), 'over');
  assert.equal(deriveStatus(0, CAP), 'none');
});

test('cap 173 h: validation accepts exactly 173 hours and rejects more, saying the maximum in hours', () => {
  const base = { employee: 'E1', hourLimit: CAP };
  assert.equal(validateEntryRows([row('A', 100), row('B', 73)], base), '');
  assert.equal(validateEntryRows([row('A', '173')], base), '');
  assert.equal(validateEntryRows([row('A', 172.5)], base), '');
  const message = validateEntryRows([row('A', 100), row('B', 73.5)], base);
  assert.equal(message, '当月累计工时不能超过 173 小时：当前 173.5 小时，本月最多 173 小时');
});

test('remaining text: hours first, the derived days in brackets', () => {
  assert.deepEqual(remainingMeta(168, CAP), { tone: 'warn', days: 0.63, hours: 5, text: '还差 5 小时（约 0.63 天）' });
  assert.equal(remainingMeta(172.5, CAP).text, '还差 0.5 小时（约 0.06 天）');
  assert.equal(remainingMeta(0, 160).text, '还差 160 小时（约 20.0 天）');
  assert.deepEqual(remainingMeta(173, CAP), { tone: 'ok', days: 0, hours: 0, text: '已分配满 ✓' });
  const over = remainingMeta(173.5, CAP);
  assert.equal(over.tone, 'bad');
  assert.equal(over.text, '超出上限 0.5 小时，最多 173 小时，请调整后再保存');
  // 照着"还差 N 小时"填，一定能保存
  for (const used of [0, 5, 13.5, 100, 172.5]) {
    const typed = remainingMeta(used, CAP).hours;
    assert.notEqual(deriveStatus(Number((used + typed).toFixed(2)), CAP), 'over', `used ${used}`);
  }
  assert.equal(fmtDaysExact(20), '20.0');
  assert.equal(fmtDaysExact(21.63), '21.63');
  assert.equal(fmtHours(173), '173');
  assert.equal(fmtHours(172.5), '172.5');
});

test('top up: one click puts the remaining hours on the chosen row and reaches full', () => {
  const rows = [row('A', 80), row('B', 88)];
  const last = topUpRow(rows, CAP, 1);
  assert.equal(last.added, 5);
  assert.deepEqual(last.rows.map((r) => r.hours), ['80', '93']);
  assert.equal(last.rows[1].occurrence_days, 11.63);
  assert.equal(deriveStatus(sumHours(last.rows), CAP), 'full');
  const first = topUpRow(rows, CAP, 0);
  assert.deepEqual(first.rows.map((r) => r.hours), ['85', '88']);
  assert.equal(first.index, 0);
  assert.equal(topUpRow(rows, CAP).index, 1);                 // 没指定 / 越界：补最后一行
  assert.equal(topUpRow(rows, CAP, 9).index, 1);
  assert.equal(topUpRow([row('A', 173)], CAP, 0).added, 0);   // 已填满、超上限、没有行：什么都不做
  assert.equal(topUpRow([row('A', 180)], CAP, 0).added, 0);
  assert.equal(topUpRow([], CAP, 0).added, 0);
  assert.equal(rows[1].hours, '88');                          // 不改入参
});

test('average fill with a 173 hour cap still reaches exactly full', () => {
  const result = averageFill([row('A', 8), row('B', 8)], CAP);
  assert.deepEqual(result.rows.map((r) => r.hours), ['86', '87']);
  assert.equal(result.added, 157);
  assert.equal(deriveStatus(sumHours(result.rows), CAP), 'full');
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
  assert.deepEqual([items[0].used, items[0].limit, items[0].usedDays, items[0].limitDays], [160, 160, 20, 20]);   // 进度接口没给小时时按 天 × 8
  assert.deepEqual(rosterCounts(items), { all: 5, full: 1, todo: 3, over: 1 });
  assert.deepEqual(filterRoster(items, { filter: 'todo' }).map((i) => i.employee), ['E2', 'E3', 'E5']);
  assert.deepEqual(filterRoster(items, { filter: 'over' }).map((i) => i.employee), ['E4']);
  assert.deepEqual(filterRoster(items, { query: 'e3' }).map((i) => i.employee), ['E3']);
  assert.deepEqual(filterRoster(items, { query: '陈' }).map((i) => i.employee), ['E1']);
  assert.deepEqual(filterRoster(items, { department: '研发二部', filter: 'todo' }).map((i) => i.employee), ['E3']);
});

test('copy previous month: only still-selectable projects, de-duplicated, positive hours (old day-only records times eight), no remarks', () => {
  const entries = [
    { project: 'P1', project_code: 'RD14', project_name: 'ACONCA 7961', hours: 44, occurrence_days: 5.5, remark: '上月备注' },
    { project: 'P1', project_code: 'RD14', project_name: 'ACONCA 7961', hours: 8 },
    { project: 'GONE', project_code: 'RD01', project_name: '已结项', hours: 24 },
    { project: 'P2', project_code: 'RD16', project_name: 'EFEM 机械手', hours: 0 },
    { project: 'P3', project_code: 'RD17', project_name: '真空腔体', occurrence_days: 2 },
  ];
  const result = rowsFromPrevious(entries, { employee: 'E1', projects });
  assert.equal(result.rows.length, 2);
  assert.equal(result.skipped, 1);
  assert.equal(result.rows[0].project, 'P1');
  assert.equal(result.rows[0].hours, '44');
  assert.equal(result.rows[0].occurrence_days, 5.5);
  assert.equal(result.rows[1].hours, '16');                  // 老记录只有天数：2 天 × 8
  assert.equal(result.rows[0].remark, '');
  assert.equal(result.rows[0].monthly_entry_id, '');
  assert.equal(result.rows[0].employee, 'E1');
});

test('validation: one message per kind of mistake, by row', () => {
  const ok = [row('A', '12'), row('B', '20')];
  const base = { employee: 'E1', hourLimit: 160 };
  assert.equal(validateEntryRows(ok, base), '');
  assert.equal(validateEntryRows(ok, { ...base, employee: '' }), '请选择研发人员');
  assert.equal(validateEntryRows(ok, { ...base, hasLegacy: true }), '历史按日记录不能在月度视图中直接修改');
  assert.equal(validateEntryRows([row('', 8, { project: '' })], base), '第 1 行请选择项目');
  assert.equal(validateEntryRows([row('A', 8), row('A', 16)], base), '第 2 行项目重复');
  assert.equal(validateEntryRows([row('A', '1.234')], base), '第 1 行工时必须是不超过两位小数的数字');
  assert.equal(validateEntryRows([row('A', '')], base), '第 1 行请填写工时');
  assert.equal(validateEntryRows([row('A', '0')], base), '第 1 行工时必须大于 0');
  assert.equal(validateEntryRows([row('A', '-1')], base), '第 1 行工时必须是不超过两位小数的数字');
  assert.equal(validateEntryRows([row('A', 100), row('B', 60.01)], base), '当月累计工时不能超过 160 小时：当前 160.01 小时，本月最多 160 小时');
  assert.equal(validateEntryRows([row('A', 100), row('B', 60)], base), '');
});

test('cap text explains the limit in hours, the derived days, the leave deduction and join / leave dates', () => {
  const text = capText({ month: 4, hourLimit: 160, baseHourLimit: 176, leaveHours: 16, joinedOn: '2026-04-08', relievedOn: '' });
  assert.ok(text.includes('4 月可填 160 小时（约 20.0 天）'));
  assert.ok(text.includes('日历工时 176 小时'));
  assert.ok(text.includes('已批请假 16 小时'));
  assert.ok(text.includes('2026-04-08 入职，之前的日子不计'));
  // 请假 3 小时：173 小时，天数只是 小时 ÷ 8 反推出来的（21.625 -> 21.63），小时数不被取整
  const cut = capText({ month: 10, hourLimit: 173, baseHourLimit: 176, leaveHours: 3 });
  assert.ok(cut.includes('10 月可填 173 小时（约 21.63 天）'));
  assert.ok(cut.includes('已批请假 3 小时'));
  assert.ok(capText({ month: 10, hourLimit: 172.5, baseHourLimit: 176, leaveHours: 3.5 }).includes('可填 172.5 小时（约 21.56 天）'));
  assert.ok(!text.includes('离职'));
  assert.ok(capText({ month: 4, hourLimit: 160, relievedOn: '2026-04-20' }).includes('2026-04-20 离职，之后的日子不计'));
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

test('stacked meter: one segment per project with hours, width over max(limit, total), colour by row index', () => {
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
  assert.deepEqual(remainingMeta(155.2, 176), { tone: 'warn', days: 2.6, hours: 20.8, text: '还差 20.8 小时（约 2.6 天）' });
  assert.deepEqual(remainingMeta(176, 176), { tone: 'ok', days: 0, hours: 0, text: '已分配满 ✓' });
  assert.equal(remainingMeta(0, 176).text, '还差 176 小时（约 22.0 天）');
  const over = remainingMeta(188, 176);
  assert.equal(over.tone, 'bad');
  assert.ok(over.text.startsWith('超出上限 12 小时'));
});

test('the project owner shown in the picker prefers the display name from the server', () => {
  assert.equal(projectOwner({ project_owner: 'zhang@example.com', project_owner_name: '演示员工132' }), '演示员工132');
  assert.equal(projectOwner({ project_owner: '演示员工107' }), '演示员工107');
});

test('the sheet offers a top-up button next to the remaining text and keeps the even split', async () => {
  const { readFileSync } = await import('node:fs');
  const sheet = readFileSync(new URL('../src/components/timesheet/EntrySheet.vue', import.meta.url), 'utf8');
  assert.ok(sheet.includes('补满剩余'));
  assert.match(sheet, /topUpRow/);
  assert.match(sheet, /@click="fillRemaining"/);
  assert.ok(sheet.includes('把剩余小时平均分给现有项目'));
  assert.match(sheet, /remainingHours\(hours\.value, props\.hourLimit\)/);     // 剩余按小时算，天数是反推出来的
  assert.match(sheet, /daysOfHours\(hours\.value\)/);
  assert.doesNotMatch(sheet, /maxEntryDays|remainingDays|dayLimit/);
});