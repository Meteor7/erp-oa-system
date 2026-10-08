import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  NO_VOUCHER_LABEL, accountPathKey, account2Options, activeFilterChips, amountOf, ariaSort, buildDisplayRows, computeStripState,
  duplicateVoucherRows, emptyFilters, errorFields, expenseFilterCounts, expenseRowKey, expenseTotals, filterExpenseEntries,
  filterExpenseRows, groupByVoucher, groupTitle, isForeignRow, nextSort, projectFilterOptions, pruneAcks, rowSearchText,
  saveBlockReason, scopeCounts, sortExpenseEntries, sortIndicator, statusCounts, stripLinePrefix, sumAmounts,
} from '../src/lib/rdExpense.js';

const row = (voucher, l2, l3, l4, amount, type = 'common', project = '') => ({
  voucher_no: voucher, account_level_1: '研发支出', account_level_2: l2, account_level_3: l3, account_level_4: l4,
  amount, allocation_type: type, direct_project: project,
});

test('amountOf ignores blanks and non numbers', () => {
  assert.equal(amountOf({ amount: '12.5' }), 12.5);
  assert.equal(amountOf({ amount: -3 }), -3);
  assert.equal(amountOf({ amount: '' }), 0);
  assert.equal(amountOf({ amount: 'abc' }), 0);
  assert.equal(amountOf({}), 0);
});

test('expenseTotals splits common and project expenses with shares', () => {
  const t = expenseTotals([
    row('1', 'a', 'b', '', 600, 'common'),
    row('2', 'a', 'b', '', '300', 'project', 'RD1'),
    row('3', 'a', 'b', '', 100, 'project', 'RD2'),
    row('4', 'a', 'b', '', '', 'common'),
  ]);
  assert.deepEqual(t, { total: 1000, common: 600, project: 400, commonShare: 60, projectShare: 40 });
  assert.deepEqual(expenseTotals([]), { total: 0, common: 0, project: 0, commonShare: 0, projectShare: 0 });
});

test('duplicateVoucherRows only flags rows with the same voucher, account path, amount and project', () => {
  const rows = [
    row('V1', 'x', 'y', 'z', 100),
    row('V1', 'x', 'y', 'z', '100.00'),
    row('V1', 'x', 'y', 'z', 200),
    row('V1', 'x', 'y', 'z', 100, 'project', 'RD1'),
    row('V1', 'x', 'y', '', 100),
    row('V2', 'x', 'y', 'z', 100),
    row('', 'x', 'y', 'z', 5),
    row('', 'x', 'y', 'z', 5),
    row(' V3 ', 'a', 'b', 'c', 7, 'project', 'RD2'),
    row('V3', 'a', 'b', 'c', 7, 'project', 'RD2'),
    row('V3', 'a', 'b', 'c', 7, 'project', 'RD3'),
  ];
  const { groups, keys, indexes } = duplicateVoucherRows(rows);
  assert.deepEqual(groups, [[0, 1], [8, 9]]);
  assert.deepEqual(indexes.get(0), [1]);
  assert.deepEqual(indexes.get(9), [8]);
  [2, 3, 4, 5, 6, 7, 10].forEach((index) => assert.equal(indexes.has(index), false));
  assert.notEqual(accountPathKey(rows[0]), accountPathKey(rows[4]));
  // 每组带一个内容键，等于组内任意一行的内容键；没有凭证号的行没有键
  assert.equal(keys.length, 2);
  assert.equal(keys[0], expenseRowKey(rows[0]));
  assert.equal(keys[0], expenseRowKey(rows[1]));
  assert.equal(keys[1], expenseRowKey(rows[9]));
  assert.notEqual(keys[0], keys[1]);
  assert.equal(expenseRowKey(rows[6]), '');
});

test('acknowledgement keys follow row content, not row position', () => {
  const a = row('V1', 'x', 'y', 'z', 100);
  const b = row('V1', 'x', 'y', 'z', '100.00');
  const before = duplicateVoucherRows([a, b]);
  // 在前面插入一行、再删掉：组的键不变，确认无误不会指到别的行上
  const after = duplicateVoucherRows([row('V9', 'x', 'y', 'z', 1), a, b]);
  assert.deepEqual(after.groups, [[1, 2]]);
  assert.deepEqual(after.keys, before.keys);
  // 改了金额，就是另一个键
  const edited = duplicateVoucherRows([a, { ...b, amount: 101 }, { ...b, amount: 101 }]);
  assert.notDeepEqual(edited.keys, before.keys);

  const acked = new Set(before.keys);
  assert.equal(pruneAcks(acked, before.keys), acked, '没有变化时原样返回');
  const pruned = pruneAcks(acked, edited.keys);
  assert.deepEqual([...pruned], []);
  assert.deepEqual([...pruneAcks(new Set(['k1', 'k2']), ['k2', 'k3'])], ['k2']);
});

test('stripLinePrefix removes the leading line number from validation messages', () => {
  assert.equal(stripLinePrefix('第 12 行：费用金额必须是有效数字'), '费用金额必须是有效数字');
  assert.equal(stripLinePrefix('第3行:所属项目无效'), '所属项目无效');
  assert.equal(stripLinePrefix('没有行号'), '没有行号');
});

test('errorFields marks which cells a validation message is about', () => {
  assert.deepEqual(errorFields(['费用金额必须是有效数字']), { amount: true, project: false, levels: [] });
  assert.deepEqual(errorFields(['项目费用请选择所属项目']), { amount: false, project: true, levels: [] });
  assert.deepEqual(errorFields(['1级费用科目不能为空', '2级费用科目不能为空', '1级费用科目不在固定分类中']), { amount: false, project: false, levels: [1, 2] });
  assert.deepEqual(errorFields([]), { amount: false, project: false, levels: [] });
});

test('filterExpenseRows filters by kind, problems and voucher / account text', () => {
  const entries = [
    { row: row('V001', '直接投入费用', '差旅费', '', 1, 'common'), index: 0, problems: [] },
    { row: row('V002', '人员人工', '工资薪金', '基本工资', 2, 'project', 'RD1'), index: 1, problems: ['费用金额必须是有效数字'] },
    { row: row('V003', '折旧', '设备折旧', '', 3, 'project', 'RD2'), index: 2, problems: [] },
  ];
  assert.deepEqual(expenseFilterCounts(entries), { all: 3, common: 1, project: 2, bad: 1 });
  assert.equal(filterExpenseRows(entries).length, 3);
  assert.deepEqual(filterExpenseRows(entries, { kind: 'common' }).map((e) => e.index), [0]);
  assert.deepEqual(filterExpenseRows(entries, { kind: 'project' }).map((e) => e.index), [1, 2]);
  assert.deepEqual(filterExpenseRows(entries, { kind: 'bad' }).map((e) => e.index), [1]);
  assert.deepEqual(filterExpenseRows(entries, { query: 'v003' }).map((e) => e.index), [2]);
  assert.deepEqual(filterExpenseRows(entries, { query: ' 工资 ' }).map((e) => e.index), [1]);
  assert.deepEqual(filterExpenseRows(entries, { kind: 'project', query: '折旧' }).map((e) => e.index), [2]);
  assert.ok(rowSearchText(entries[1].row).includes('基本工资'));
});

// 工具栏用的样例：行号 = 下标
const sample = () => {
  const rows = [
    row('39', '直接投入费用', '研发材料', '', 86.74, 'project', 'RD13'),
    row('39', '直接投入费用', '研发材料', '', 494.69, 'project', 'RD06'),
    row('39', '直接投入费用', '研发材料', '', '', 'common'),
    row('22', '其他相关费用', '装修费', '', '8800', 'common'),
    row('22', '直接投入费用', '研发材料', '', 3500, 'project', 'RD13'),
    row('', '委托研发', '境外', 'Kontron AIS GmbH', 12000.5, 'common'),
    row('41', '委托研发', '境内', '', 1280, 'common'),
  ];
  return rows.map((r, index) => ({
    row: r,
    index,
    errors: index === 2 ? ['费用金额必须是有效数字'] : [],
    notice: index === 0 || index === 1 ? { key: 'k' } : null,
    isNew: index === 3,
    projectText: r.direct_project ? `${r.direct_project} | 项目${r.direct_project}` : '',
  }));
};
const idx = (list) => list.map((e) => e.index);

test('filterExpenseEntries combines search, scope, account2, project and status', () => {
  const entries = sample();
  assert.deepEqual(idx(filterExpenseEntries(entries, emptyFilters())), [0, 1, 2, 3, 4, 5, 6]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { scope: 'project' })), [0, 1, 4]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { scope: 'common' })), [2, 3, 5, 6]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { account2: '直接投入费用' })), [0, 1, 2, 4]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { project: 'RD13' })), [0, 4]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { status: 'bad' })), [2]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { status: 'notice' })), [0, 1]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { status: 'new' })), [3]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { status: 'foreign' })), [5]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { scope: 'project', account2: '直接投入费用', project: 'RD13' })), [0, 4]);
  // 搜索：凭证号、科目、项目编号 / 名称、金额（原文、两位小数、千分位）
  assert.deepEqual(idx(filterExpenseEntries(entries, { query: '41' })), [6]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { query: ' kontron ' })), [5]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { query: '项目RD06' })), [1]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { query: '8,800.00' })), [3]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { query: '494.69' })), [1]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { query: '12,000.50' })), [5]);
  assert.deepEqual(idx(filterExpenseEntries(entries, { query: '没有这个' })), []);
});

test('foreign rows are 委托研发 / 境外 only', () => {
  assert.equal(isForeignRow(row('1', '委托研发', '境外', 'x', 1)), true);
  assert.equal(isForeignRow(row('1', '委托研发', '境内', '', 1)), false);
  assert.equal(isForeignRow(row('1', '直接投入费用', '境外', '', 1)), false);
});

test('scope and status counts, filter option lists and subtotal', () => {
  const entries = sample();
  assert.deepEqual(scopeCounts(entries), { all: 7, common: 4, project: 3 });
  assert.deepEqual(statusCounts(entries), { bad: 1, notice: 2, new: 1, foreign: 1 });
  assert.deepEqual(account2Options(entries), ['直接投入费用', '其他相关费用', '委托研发']);
  assert.deepEqual(projectFilterOptions(entries, (v) => `P-${v}`), [{ value: 'RD13', label: 'P-RD13' }, { value: 'RD06', label: 'P-RD06' }]);
  assert.equal(Math.round(sumAmounts(entries) * 100) / 100, 26161.93);
  assert.equal(Math.round(sumAmounts(filterExpenseEntries(entries, { scope: 'project' })) * 100) / 100, 4081.43);
  assert.equal(sumAmounts([]), 0);
});

test('sortExpenseEntries sorts by line, amount and voucher without touching the input', () => {
  const entries = sample();
  const shuffled = [entries[4], entries[0], entries[6], entries[2], entries[5], entries[3], entries[1]];
  assert.deepEqual(idx(sortExpenseEntries(shuffled, 'line')), [0, 1, 2, 3, 4, 5, 6]);
  assert.deepEqual(idx(sortExpenseEntries(entries, 'amount_desc')), [5, 3, 4, 6, 1, 0, 2]);
  assert.deepEqual(idx(sortExpenseEntries(entries, 'amount_asc')), [2, 0, 1, 6, 4, 3, 5]);
  // 凭证号按数字顺序，没有凭证号的排最后，相同凭证号按行号
  assert.deepEqual(idx(sortExpenseEntries(entries, 'voucher')), [3, 4, 0, 1, 2, 6, 5]);
  assert.deepEqual(idx(entries), [0, 1, 2, 3, 4, 5, 6]);
  // 数字凭证号 2 排在 10 前面
  const two = [{ row: row('10', 'a', 'b', '', 1), index: 0 }, { row: row('2', 'a', 'b', '', 1), index: 1 }];
  assert.deepEqual(idx(sortExpenseEntries(two, 'voucher')), [1, 0]);
});

test('column header sorting cycles through amount and voucher orders', () => {
  assert.equal(nextSort('line', 'amount'), 'amount_desc');
  assert.equal(nextSort('amount_desc', 'amount'), 'amount_asc');
  assert.equal(nextSort('amount_asc', 'amount'), 'line');
  assert.equal(nextSort('voucher', 'amount'), 'amount_desc');
  assert.equal(nextSort('line', 'voucher'), 'voucher');
  assert.equal(nextSort('voucher', 'voucher'), 'line');
  assert.equal(sortIndicator('amount_desc', 'amount'), '↓');
  assert.equal(sortIndicator('amount_asc', 'amount'), '↑');
  assert.equal(sortIndicator('voucher', 'voucher'), '↑');
  assert.equal(sortIndicator('line', 'amount'), '');
  assert.equal(ariaSort('amount_desc', 'amount'), 'descending');
  assert.equal(ariaSort('amount_asc', 'amount'), 'ascending');
  assert.equal(ariaSort('line', 'voucher'), 'none');
});

test('groupByVoucher keeps first-appearance order, subtotals and a no-voucher group', () => {
  const entries = sample();
  const groups = groupByVoucher(entries);
  assert.deepEqual(groups.map((g) => g.key), ['39', '22', '', '41']);
  assert.deepEqual(groups.map((g) => g.count), [3, 2, 1, 1]);
  assert.deepEqual(idx(groups[0].entries), [0, 1, 2]);
  assert.equal(Math.round(groups[0].subtotal * 100) / 100, 581.43);
  assert.equal(groups[1].subtotal, 12300);
  assert.equal(groups[2].label, NO_VOUCHER_LABEL);
  assert.equal(groupTitle(groups[0]), '凭证 39');
  assert.equal(groupTitle(groups[2]), NO_VOUCHER_LABEL);
  // 固定的分组依据：改了凭证号的行仍留在原来的组里
  const pinned = groupByVoucher(entries, (e) => (e.index === 1 ? '22' : e.row.voucher_no));
  assert.deepEqual(idx(pinned.find((g) => g.key === '22').entries), [1, 3, 4]);
});

test('buildDisplayRows flattens rows or groups and keeps the original row index', () => {
  const entries = sortExpenseEntries(sample(), 'amount_desc');
  const flat = buildDisplayRows(entries);
  assert.deepEqual(flat.map((d) => d.index), [5, 3, 4, 6, 1, 0, 2]);
  assert.ok(flat.every((d) => d.type === 'row' && d.row === entries.find((e) => e.index === d.index).row));
  const grouped = buildDisplayRows(entries, { group: true });
  assert.deepEqual(grouped.map((d) => (d.type === 'group' ? `g${d.group.key}` : d.index)), ['g', 5, 'g22', 3, 4, 'g41', 6, 'g39', 1, 0, 2]);
  assert.equal(new Set(grouped.map((d) => d.key)).size, grouped.length);
});

test('active filter chips list only the filters that are on', () => {
  assert.deepEqual(activeFilterChips(emptyFilters()), []);
  const chips = activeFilterChips({ query: ' 差旅 ', scope: 'project', account2: '折旧', project: 'RD1', status: 'bad' }, { projectLabel: (v) => `${v} | 名称` });
  assert.deepEqual(chips.map((c) => c.key), ['query', 'scope', 'account2', 'project', 'status']);
  assert.deepEqual(chips.map((c) => c.label), ['搜索：差旅', '归属：项目', '二级科目：折旧', '项目：RD1 | 名称', '状态：有问题']);
  assert.equal(activeFilterChips({ ...emptyFilters(), scope: 'common' })[0].label, '归属：公共');
});

test('status strip is red for errors, amber for pending new accounts or reminders, green when clear', () => {
  const red = computeStripState({ errorRows: 2, newCount: 1, noticePending: 2 });
  assert.equal(red.tone, 'bad');
  assert.equal(red.title, '有问题，暂时不能保存');
  assert.equal(red.summary, '2 个问题 · 1 个新科目待确认 · 2 条提醒');
  assert.equal(red.hasList, true);

  const newOnly = computeStripState({ newCount: 1, noticePending: 1 });
  assert.equal(newOnly.tone, 'warn');
  assert.equal(newOnly.title, '确认新科目后才能保存');
  assert.equal(newOnly.summary, '1 个新科目待确认 · 1 条提醒');

  const noticeOnly = computeStripState({ newCount: 1, newConfirmed: true, noticePending: 1 });
  assert.equal(noticeOnly.tone, 'warn');
  assert.equal(noticeOnly.title, '有提醒，不影响保存');
  assert.equal(noticeOnly.summary, '1 个新科目已确认 · 1 条提醒');

  const green = computeStripState({});
  assert.equal(green.tone, 'ok');
  assert.equal(green.title, '检查通过');
  assert.equal(green.summary, '金额、归属、项目都已填写 · 科目都在目录里 · 没有完全相同的行');
  assert.equal(green.hasList, false);

  const greenAcked = computeStripState({ newCount: 2, newConfirmed: true, noticeAcked: 1 });
  assert.equal(greenAcked.tone, 'ok');
  assert.equal(greenAcked.summary, '金额、归属、项目都已填写 · 新科目已确认 · 提醒已确认');
});

test('save is blocked for year view, loading, missing catalog, saving, row errors and unconfirmed new accounts', () => {
  assert.equal(saveBlockReason({}), '');
  assert.match(saveBlockReason({ isYear: true }), /年度视图只读/);
  assert.match(saveBlockReason({ loading: true }), /加载中/);
  assert.match(saveBlockReason({ catalogReady: false }), /目录/);
  assert.match(saveBlockReason({ saving: true }), /正在保存/);
  assert.match(saveBlockReason({ errorRows: 3 }), /3 行有问题/);
  assert.match(saveBlockReason({ newPending: true }), /确认新科目/);
  // 提醒从不挡保存：这里根本没有提醒这个参数
  assert.equal(saveBlockReason({ errorRows: 0, newPending: false }), '');
});

const page = readFileSync(new URL('../src/pages/ExpenseImport.vue', import.meta.url), 'utf8');

test('expense page uses the shared page shell with period control and KPI cards', () => {
  assert.match(page, /<RdPage title="研发费用导入"/);
  assert.match(page, /<RdPeriod/);
  assert.match(page, /<RdSeg/);
  assert.match(page, /本期费用合计/);
  assert.match(page, /label="公共费用"/);
  assert.match(page, /label="项目费用"/);
  assert.doesNotMatch(page, /较上月/);
});

test('save button sits in the page header and the old check card and save bar are gone', () => {
  assert.doesNotMatch(page, /保存前检查/);
  assert.doesNotMatch(page, /class="savebar"/);
  assert.doesNotMatch(page, /checksPassed/);
  const header = page.slice(page.indexOf('<template #ctl>'), page.indexOf('</template>', page.indexOf('<template #ctl>')));
  assert.match(header, /<RdPeriod \/>[\s\S]*class="btn pri"[\s\S]*:disabled="saveBlocked"[\s\S]*:title="saveTip"[\s\S]*@click="save"/);
  assert.ok(header.includes('保存本月费用'));
  assert.ok(page.includes('保存会整月覆盖本月已有费用'));
});

test('status strip with a floating to-do popover, reminders and row problems under the row', () => {
  assert.match(page, /class="ei-strip"/);
  assert.match(page, /computeStripState/);
  assert.ok(page.includes('处理清单'));
  assert.match(page, /class="ei-pop" role="dialog"/);
  assert.ok(page.includes('跳到该行'));
  assert.ok(page.includes('我已核对，保存时创建'));
  assert.ok(page.includes('确认无误'));
  assert.ok(page.includes('已确认无误（只对本次编辑有效）'));
  assert.ok(page.includes('撤回'));
  assert.match(page, /duplicateVoucherRows/);
  assert.match(page, /rowValidationErrors\(row, index\)/);
  assert.match(page, /rowerr: entry\.errors\.length/);
  assert.match(page, /<tr v-if="entry\.errors\.length" class="rowerr ei-msg"/);
  assert.ok(page.includes('新科目'));
  assert.match(page, /@keydown|key !== 'Escape'/);
});

test('toolbar filters, sorting and grouping all keep edits bound to the original row index', () => {
  assert.match(page, /filterExpenseEntries/);
  assert.match(page, /sortExpenseEntries/);
  assert.match(page, /buildDisplayRows/);
  assert.ok(page.includes('按凭证号分组'));
  assert.ok(page.includes('清除全部'));
  assert.match(page, /显示 <b>\{\{ shownEntries\.length \}\}<\/b> \/ \{\{ items\.length \}\} 行 · 小计/);
  assert.match(page, /aria-label="二级科目"/);
  assert.match(page, /aria-label="排序"/);
  assert.match(page, /clickSort\('amount'\)/);
  assert.match(page, /clickSort\('voucher'\)/);
  // v-model goes through the original row object and the original index, never the display position
  assert.match(page, /v-for="\{ type, key, row: it, index: i, entry, group \} in displayRows"/);
  assert.match(page, /@click="delRow\(i\)"/);
  assert.match(page, /<td class="num muted">\{\{ i \+ 1 \}\}<\/td>/);
  assert.match(page, /ei-scroll/);
});

test('replacing the table asks for an inline confirmation first', () => {
  assert.ok(page.includes('确认覆盖'));
  assert.ok(page.includes('覆盖现有费用…'));
  assert.ok(page.includes('追加到现有费用'));
  assert.match(page, /confirmWorkbookOverwrite/);
  assert.match(page, /confirmPasteOverwrite/);
  assert.match(page, /@click="confirmWorkbookReplace"/);
  // the Excel replace menu item only asks; it does not open the file picker directly
  assert.match(page, /function importOverwrite\(\) \{\s*closeImportMenu\(\);\s*requestWorkbookReplace\(\);/);
  assert.doesNotMatch(page, /@click="chooseWorkbook\(true\)"/);
});

test('paste import lives in a teleported drawer and Excel import is a two-item menu', () => {
  assert.match(page, /<Teleport to="body">/);
  assert.match(page, /<div v-if="pasteOpen" class="rd">/);
  assert.match(page, /aria-haspopup="menu"/);
  assert.match(page, /role="menuitem" class="ei-mi" @click="importAppend"/);
  assert.match(page, /role="menuitem" class="ei-mi" @click="importOverwrite"/);
  assert.match(page, /function importAppend\(\) \{\s*closeImportMenu\(\);\s*chooseWorkbook\(false\);/);
  assert.match(page, /@click="openPaste"/);
  assert.ok(page.includes('粘贴导入'));
  assert.ok(page.includes('添加一行'));
  assert.ok(page.includes('导出 Excel'));
});

test('saving keeps whole-month overwrite semantics and the new-account confirmation gate', () => {
  assert.match(page, /new_account_paths: JSON\.stringify\(pendingAccountPaths\.value\)/);
  assert.match(page, /pendingAccountPaths\.value\.length > 0 && !confirmNewAccounts\.value/);
  assert.match(page, /saveBlockReason\(/);
  assert.match(page, /clearInvalidLowerLevels\(row, level, expenseAccountPaths\.value\)/);
});

test('acknowledgements are session state, reset when rows are replaced or reloaded', () => {
  assert.match(page, /const ackedKeys = ref\(new Set\(\)\)/);
  assert.match(page, /function resetEditingSession\(\) \{\s*ackedKeys\.value = new Set\(\);/);
  assert.match(page, /pruneAcks\(ackedKeys\.value/);
  // reloaded from the server, saved and re-read, overwritten by an import
  assert.match(page, /items\.value = normalizeRows\(d\.items \|\| \[\]\);\s*resetEditingSession\(\);/);
  assert.match(page, /items\.value = rows;\s*resetEditingSession\(\);/);
});
