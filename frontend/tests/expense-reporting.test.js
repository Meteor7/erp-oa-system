import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

const reportingUrl = new URL('../src/lib/expenseReporting.js', import.meta.url);
const reporting = existsSync(reportingUrl) ? await import(reportingUrl) : {};
const {
  dateTime = () => undefined,
  money = () => undefined,
  toApprovalRecordParams = () => ({}),
  toExpenseStatisticsParams = () => ({}),
} = reporting;

const statisticsUrl = new URL('../src/components/expense/ExpenseStatistics.vue', import.meta.url);
const statisticsSource = existsSync(statisticsUrl) ? readFileSync(statisticsUrl, 'utf8') : '';
const approvalUrl = new URL('../src/components/expense/ExpenseApprovalRecords.vue', import.meta.url);
const approvalSource = existsSync(approvalUrl) ? readFileSync(approvalUrl, 'utf8') : '';

test('maps statistics filters to bounded server parameters', () => {
  assert.deepEqual(toExpenseStatisticsParams({
    fromDate: '2026-07-01',
    toDate: '2026-07-31',
    department: '  \u7814\u53d1\u90e8 ',
    employee: 'EMP-1',
    invoiceCategory: '\u7535\u5b50\u53d1\u7968\uff08\u666e\u901a\u53d1\u7968\uff09',
    projectName: '\u6587\u5177\u5370\u7ae0',
    workflowStatus: '\u5df2\u4ed8\u6b3e',
    paymentStatus: '\u5df2\u4ed8\u6b3e',
    sourceType: '\u53d1\u7968\u4e0b\u63a8',
    ignored: 'never sent',
  }), {
    view: 'all',
    limit: 1000,
    from_date: '2026-07-01',
    to_date: '2026-07-31',
    department: '\u7814\u53d1\u90e8',
    employee: 'EMP-1',
    invoice_category: '\u7535\u5b50\u53d1\u7968\uff08\u666e\u901a\u53d1\u7968\uff09',
    project_name: '\u6587\u5177\u5370\u7ae0',
    workflow_status: '\u5df2\u4ed8\u6b3e',
    payment_status: '\u5df2\u4ed8\u6b3e',
    source_type: '\u53d1\u7968\u4e0b\u63a8',
  });
  assert.deepEqual(toExpenseStatisticsParams({ department: '   ' }), { view: 'all', limit: 1000 });
});

test('maps approval filters without leaking unknown keys', () => {
  assert.deepEqual(toApprovalRecordParams({
    requestKeyword: ' OA-2026 ',
    employee: 'EMP-1',
    department: '\u7814\u53d1\u90e8',
    approver: 'finance@example.com',
    action: '\u64a4\u56de\u4ed8\u6b3e',
    workflowStatus: '\u5df2\u5b8c\u6210',
    fromDate: '2026-07-01',
    toDate: '2026-07-31',
  }), {
    view: 'all',
    limit: 1000,
    request_keyword: 'OA-2026',
    employee: 'EMP-1',
    department: '\u7814\u53d1\u90e8',
    approver: 'finance@example.com',
    action: '\u64a4\u56de\u4ed8\u6b3e',
    workflow_status: '\u5df2\u5b8c\u6210',
    from_date: '2026-07-01',
    to_date: '2026-07-31',
  });
});

test('formats report money and timestamps safely', () => {
  assert.equal(money(null), '\u00a50.00');
  assert.equal(money('35.98'), '\u00a535.98');
  assert.equal(money('invalid'), '\u00a50.00');
  assert.equal(dateTime('2026-07-21T10:11:12'), '2026-07-21 10:11');
  assert.equal(dateTime(''), '-');
});

test('statistics view exposes all filters metrics table and states', () => {
  assert.match(statisticsSource, /get_expense_statistics/);
  for (const key of [
    'fromDate', 'toDate', 'department', 'employee', 'invoiceCategory',
    'projectName', 'workflowStatus', 'paymentStatus', 'sourceType',
  ]) assert.ok(statisticsSource.includes(key), `missing statistics filter: ${key}`);
  for (const label of [
    '\u7533\u8bf7\u5355\u6570', '\u53d1\u7968\u5f20\u6570', '\u7a0e\u524d\u91d1\u989d', '\u7a0e\u989d',
    '\u5408\u8ba1\u91d1\u989d', '\u5df2\u4ed8\u6b3e\u91d1\u989d', '\u672a\u4ed8\u6b3e\u91d1\u989d',
  ]) assert.ok(statisticsSource.includes(label), `missing metric: ${label}`);
  assert.match(statisticsSource, /emit\('open-request'/);
  assert.match(statisticsSource, /statistics\.loading/);
  assert.match(statisticsSource, /statistics\.error/);
  assert.match(statisticsSource, /truncated/);
  assert.ok(statisticsSource.includes('\u6682\u65e0\u7edf\u8ba1\u6570\u636e'));
  assert.ok(statisticsSource.includes('\u67e5\u8be2'));
  assert.ok(statisticsSource.includes('\u91cd\u7f6e'));
  assert.ok(statisticsSource.includes('\u5237\u65b0'));
});

test('approval records view exposes filters audit columns and states', () => {
  assert.match(approvalSource, /list_expense_approval_records/);
  for (const key of [
    'requestKeyword', 'employee', 'department', 'approver', 'action',
    'workflowStatus', 'fromDate', 'toDate',
  ]) assert.ok(approvalSource.includes(key), `missing approval filter: ${key}`);
  for (const label of [
    '\u7533\u8bf7\u5355', '\u4e8b\u4ef6\u7c7b\u578b', '\u5ba1\u6279\u8282\u70b9', '\u5ba1\u6279\u4eba',
    '\u64cd\u4f5c', '\u64cd\u4f5c\u4eba', '\u64cd\u4f5c\u65f6\u95f4', '\u5907\u6ce8', '\u5f53\u524d\u72b6\u6001',
  ]) assert.ok(approvalSource.includes(label), `missing audit column: ${label}`);
  assert.match(approvalSource, /emit\('open-request'/);
  assert.match(approvalSource, /records\.loading/);
  assert.match(approvalSource, /records\.error/);
  assert.match(approvalSource, /truncated/);
  assert.ok(approvalSource.includes('\u6682\u65e0\u5ba1\u6279\u6216\u64cd\u4f5c\u8bb0\u5f55'));
  assert.ok(approvalSource.includes('\u67e5\u8be2'));
  assert.ok(approvalSource.includes('\u91cd\u7f6e'));
  assert.ok(approvalSource.includes('\u5237\u65b0'));
});
