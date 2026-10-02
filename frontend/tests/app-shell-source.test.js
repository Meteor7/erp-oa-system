import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');

test('app shell shows current account level and logout', () => {
  assert.match(source, /roleLabel\(\)/);
  assert.match(source, /currentUser/);
  assert.ok(source.includes('&#x9000;&#x51fa;&#x767b;&#x5f55;'));
  assert.ok(source.includes('/?cmd=web_logout'));
});

test('app shell exposes approval children and project management in the nav', () => {
  assert.ok(source.includes("label: '审批中心'"));
  assert.ok(source.includes("to: '/approval/leave'"));
  assert.ok(source.includes("to: '/approval/procurement'"));
  assert.ok(source.includes("to: '/approval/direct-purchase'"));
  assert.ok(source.includes("to: '/approval/procurement-payment'"));
  assert.ok(source.includes("to: '/approval/reimbursement'"));
  assert.ok(source.includes("label: '付款/报销'"));
  assert.ok(!source.includes("to: '/approval/corporate-payment'"));
  assert.ok(source.includes("label: '请假审批'"));
  assert.ok(source.includes("label: '申请看板'"));
  assert.ok(source.includes("label: '付款看板'"));
  assert.ok(source.includes('\\u9879\\u76ee\\u7ba1\\u7406'));
  assert.ok(source.includes('/projects'));
});

test('left navigation labels the personnel group as HR center', () => {
  assert.ok(source.includes("label: '人事中心'"));
  assert.ok(!source.includes("label: '\\u7814\\u53d1\\u4e2d\\u5fc3'"));
});

test('R&D ledger navigation uses the timesheet report and R&D expense import names', () => {
  assert.ok(source.includes("to: '/timesheet', step: '03', label: '\\u7814\\u53d1\\u5de5\\u65f6\\u62a5\\u8868'"));
  assert.ok(source.includes("to: '/expense', step: '04', label: '\\u7814\\u53d1\\u8d39\\u7528\\u5bfc\\u5165'"));
  assert.doesNotMatch(source, /\\u7814\\u53d1\\u5de5\\u65f6\\u8868/);
  assert.doesNotMatch(source, /\\u7814\\u53d1\\u5de5\\u65f6\\u62a5\\u544a/);
  assert.doesNotMatch(source, /\\u8d22\\u52a1\\u8d39\\u7528\\u5bfc\\u5165/);
});

test('app shell hides the redundant R and D personnel ledger', () => {
  assert.doesNotMatch(source, /to: ['"]\/ledger['"]/);
  assert.ok(source.includes("label: '\\u7814\\u53d1\\u5de5\\u65f6\\u586b\\u62a5'"));
  assert.ok(source.includes("step: '02', label: '\\u7814\\u53d1\\u5de5\\u65f6\\u586b\\u62a5'"));
});

test('dense finance pages get a wider workspace', () => {
  assert.match(source, /const WIDE_PAGE_PATHS =/);
  assert.match(source, /'\/projects'/);
  assert.match(source, /'\/timesheet'/);
  assert.match(source, /'\/expense'/);
  assert.match(source, /'\/allocation'/);
  assert.match(source, /max-w-\[1900px\]/);
  assert.match(source, /max-w-6xl/);
});

test('personnel, accommodation and expense reimbursement use the wide workspace', () => {
  assert.match(source, /['"]\/personnel['"]/);
  assert.match(source, /['"]\/accommodation['"]/);
  assert.match(source, /['"]\/approval\/purchase['"]/);
});

test('app shell uses the QIHENG DEMO brand', () => {
  // the transparent mark carries the wordmark, so the shell shows it as an image
  assert.ok(source.includes('planck-semicon-logo-mark.png'));
  assert.ok(source.includes('示例企业032有限公司'));
});

test('app shell exposes overseas commissioned R&D in the finance ledger nav', () => {
  assert.ok(source.includes("to: '/foreign-rd'"));
  assert.ok(source.includes("label: '\\u5883\\u5916\\u59d4\\u6258\\u7814\\u53d1\\u5de5\\u65f6'"));
  assert.match(source, /WIDE_PAGE_PATHS[\s\S]*['"]\/foreign-rd['"]/);
});

test('nav puts overseas commissioned before total allocation', () => {
  const foreignIndex = source.indexOf("to: '/foreign-rd'");
  const allocationIndex = source.indexOf("to: '/allocation'");
  assert.ok(foreignIndex > -1);
  assert.ok(allocationIndex > -1);
  assert.ok(foreignIndex < allocationIndex);
  assert.ok(source.includes("to: '/foreign-rd', step: '05'"));
  assert.ok(source.includes("to: '/allocation', step: '07'"));
  assert.ok(source.includes("label: '\\u7814\\u53d1\\u8d39\\u7528\\u53f0\\u8d26'"));
});

test('nav adds the allocation dashboard immediately after the allocation table', () => {
  const allocationIndex = source.indexOf("to: '/allocation'");
  const dashboardIndex = source.indexOf("to: '/allocation-dashboard'");
  assert.ok(allocationIndex > -1);
  assert.ok(dashboardIndex > -1);
  assert.ok(allocationIndex < dashboardIndex);
  assert.ok(source.includes("to: '/allocation-dashboard', step: '08'"));
  assert.ok(source.includes("label: '\\u7814\\u53d1\\u8d39\\u7528\\u6c47\\u603b'"));
  assert.match(source, /WIDE_PAGE_PATHS[\s\S]*['"]\/allocation-dashboard['"]/);
});


test('app shell exposes a secure change-password dialog', () => {
  assert.ok(source.includes('修改密码'));
  assert.match(source, /frappe\.core\.doctype\.user\.user\.update_password/);
  assert.match(source, /old_password/);
  assert.match(source, /new_password/);
  assert.match(source, /confirm_password/);
  assert.match(source, /type=['"]password['"]/);
  assert.ok(source.includes('两次输入的新密码不一致'));
  assert.match(source, /resetPasswordForm/);
  assert.doesNotMatch(source, /console\.(log|debug).*password/i);
});
