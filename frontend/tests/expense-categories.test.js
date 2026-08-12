import assert from 'node:assert/strict';
import test from 'node:test';

import { EXPENSE_ACCOUNT_PATHS, accountOptions, validateExpenseAccount } from '../src/lib/expenseAccounts.js';

test('expense account hierarchy follows the research category workbook', () => {
  assert.equal(EXPENSE_ACCOUNT_PATHS.length, 43);
  assert.deepEqual(accountOptions({}, 1), ['研发支出']);
  assert.deepEqual(accountOptions({ account_level_1: '研发支出' }, 2), [
    '人员人工费用',
    '直接投入费用',
    '折旧费用',
    '无形资产摊销',
    '其他相关费用',
    '委托研发',
  ]);
  assert.ok(accountOptions({ account_level_1: '研发支出', account_level_2: '直接投入费用' }, 3).includes('仪器、设备的运行维护、调整、检验、维修等费用'));
  assert.deepEqual(accountOptions({ account_level_1: '研发支出', account_level_2: '人员人工费用', account_level_3: '社会保险费用（单位）' }, 4), [
    '养老保险',
    '医疗保险',
    '生育保险',
    '工伤保险',
    '失业保险',
  ]);  assert.deepEqual(accountOptions({ account_level_1: '研发支出', account_level_2: '其他相关费用', account_level_3: '职工福利费' }, 4), [
    '员工工服',
    '日常零食',
    '集体宿舍',
    '团建活动',
    '节日福利',
    '员工聚餐',
  ]);
  assert.deepEqual(accountOptions({ account_level_1: '研发支出', account_level_2: '委托研发', account_level_3: '境外' }, 4), [
    'QIHENG DEMO OVERSEAS',
    'Kontron AIS GmbH',
    'Sabri费用',
  ]);
});

test('expense account validation accepts workbook paths and rejects mismatched levels', () => {
  assert.deepEqual(validateExpenseAccount({
    account_level_1: '研发支出',
    account_level_2: '直接投入费用',
    account_level_3: '研发材料',
    account_level_4: '',
  }, 1), []);
  assert.deepEqual(validateExpenseAccount({
    account_level_1: '研发支出',
    account_level_2: '其他相关费用',
    account_level_3: '职工福利费',
    account_level_4: '节日福利',
  }, 2), []);

  assert.deepEqual(validateExpenseAccount({
    account_level_1: '研发支出',
    account_level_2: '委托研发',
    account_level_3: '境外',
    account_level_4: 'Sabri费用',
  }, 5), []);
  assert.deepEqual(validateExpenseAccount({
    account_level_1: '研发支出',
    account_level_2: '人员人工费用',
    account_level_3: '社会保险费用（单位）',
    account_level_4: '养老保险',
  }, 3), []);
  assert.match(validateExpenseAccount({
    account_level_1: '研发支出',
    account_level_2: '人员人工费用',
    account_level_3: '社会保险费用（单位）',
    account_level_4: '',
  }, 6).join('\n'), /第 6 行：4级费用科目必须选择/);

  assert.match(validateExpenseAccount({
    account_level_1: '研发支出',
    account_level_2: '其他相关费用',
    account_level_3: '职工福利费',
    account_level_4: '',
  }, 4).join('\n'), /第 4 行：4级费用科目必须选择/);
});

test('dynamic lower-level paths can be discovered without relaxing fixed levels', async () => {
  const module = await import('../src/lib/expenseAccounts.js');
  const paths = [...EXPENSE_ACCOUNT_PATHS, {
    account_level_1: '研发支出', account_level_2: '人员人工费用',
    account_level_3: '年终一次性奖金', account_level_4: '',
  }];
  const row = { account_level_1: '研发支出', account_level_2: '人员人工费用', account_level_3: '年终一次性奖金', account_level_4: '' };
  assert.deepEqual(module.validateExpenseAccount(row, 1, paths), []);
  assert.deepEqual(module.unknownExpenseAccountPaths([row], EXPENSE_ACCOUNT_PATHS), [row]);
  assert.match(module.validateExpenseAccount({ ...row, account_level_2: '新增二级' }, 2, EXPENSE_ACCOUNT_PATHS, true).join('\n'), /2级费用科目/);
});
