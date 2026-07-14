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
  assert.ok(source.includes('\\u5ba1\\u6279'));
  assert.ok(source.includes("to: '/approval/leave'"));
  assert.ok(source.includes("to: '/approval/purchase'"));
  assert.ok(source.includes('\\u8bf7\\u5047\\u5ba1\\u6279'));
  assert.ok(source.includes('\\u8d39\\u7528\\u4ed8\\u6b3e/\\u62a5\\u9500'));
  assert.ok(source.includes('\\u9879\\u76ee\\u7ba1\\u7406'));
  assert.ok(source.includes('/projects'));
});

test('R&D ledger navigation uses the timesheet report and R&D expense import names', () => {
  assert.ok(source.includes("to: '/timesheet', step: '05', label: '\\u7814\\u53d1\\u5de5\\u65f6\\u62a5\\u8868'"));
  assert.ok(source.includes("to: '/expense', step: '06', label: '\\u7814\\u53d1\\u8d39\\u7528\\u5bfc\\u5165'"));
  assert.doesNotMatch(source, /\\u7814\\u53d1\\u5de5\\u65f6\\u8868/);
  assert.doesNotMatch(source, /\\u7814\\u53d1\\u5de5\\u65f6\\u62a5\\u544a/);
  assert.doesNotMatch(source, /\\u8d22\\u52a1\\u8d39\\u7528\\u5bfc\\u5165/);
});

test('app shell hides the redundant R and D personnel ledger', () => {
  assert.doesNotMatch(source, /to: ['\"]\/ledger['\"]/);
  assert.ok(source.includes("label: '\\u7814\\u53d1\\u5de5\\u65f6\\u586b\\u62a5'"));
  assert.ok(source.includes("step: '04', label: '\\u7814\\u53d1\\u5de5\\u65f6\\u586b\\u62a5'"));
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
test('app shell keeps the Rayher subtitle readable', () => {
  assert.ok(source.includes('Rayher &middot; frappe-ui'));
  assert.doesNotMatch(source, /Rayher \? frappe-ui/);
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
  assert.ok(source.includes("to: '/foreign-rd', step: '07'"));
  assert.ok(source.includes("to: '/allocation', step: '08'"));
  assert.ok(source.includes("label: '\\u7814\\u53d1\\u8d39\\u7528\\u53f0\\u8d26'"));
});

test('nav adds the allocation dashboard immediately after the allocation table', () => {
  const allocationIndex = source.indexOf("to: '/allocation'");
  const dashboardIndex = source.indexOf("to: '/allocation-dashboard'");
  assert.ok(allocationIndex > -1);
  assert.ok(dashboardIndex > -1);
  assert.ok(allocationIndex < dashboardIndex);
  assert.ok(source.includes("to: '/allocation-dashboard', step: '09'"));
  assert.ok(source.includes("label: '\\u7814\\u53d1\\u8d39\\u7528\\u6c47\\u603b'"));
  assert.match(source, /WIDE_PAGE_PATHS[\s\S]*['"]\/allocation-dashboard['"]/);
});
