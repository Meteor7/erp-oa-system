import assert from 'node:assert/strict';
import test from 'node:test';

import {
  daysOfHours, monthHourLimit, parseHoursText, payloadRow, savedDays, stepHours, validateForeignRows,
} from '../src/lib/foreignRdHours.js';

const ENTITIES = ['QIHENG DEMO OVERSEAS'];
const row = (extra = {}) => ({
  foreign_entity: 'QIHENG DEMO OVERSEAS', project: 'P1', project_code: 'RD14', project_name: 'ACONCA 7961', hours: '8', remark: '', ...extra,
});
const check = (rows, extra = {}) => validateForeignRows(rows, { period: '2026-06', entities: ENTITIES, ...extra });

test('days are the hours divided by eight, shown with at most two decimals', () => {
  assert.equal(daysOfHours(8), 1);
  assert.equal(daysOfHours(18.8), 2.35);
  assert.equal(daysOfHours(172.96), 21.62);
  assert.equal(daysOfHours(''), 0);
  assert.equal(savedDays(18.8), 2.35);
  assert.equal(savedDays(1), 0.125);
});

test('hours parse with at most two decimals and must be above zero', () => {
  assert.deepEqual(parseHoursText('12.5'), { value: 12.5, error: '' });
  assert.equal(parseHoursText('8.001').error, 'precision');
  assert.equal(parseHoursText('0').error, 'zero');
  assert.equal(parseHoursText('').error, 'format');
  assert.equal(parseHoursText('abc').error, 'format');
  assert.equal(parseHoursText('-1').error, 'format');
});

test('the stepper moves by whole hours and never goes below zero', () => {
  assert.equal(stepHours(8, 1), 9);
  assert.equal(stepHours('7.5', -1), 6.5);
  assert.equal(stepHours(0.5, -1), 0);
  assert.equal(stepHours('', 1), 1);
});

test('the monthly limit is the calendar days of the month times eight hours', () => {
  assert.equal(monthHourLimit('2026-06'), 240);
  assert.equal(monthHourLimit('2026-07'), 248);
  assert.equal(monthHourLimit('2026-02'), 224);
  assert.equal(monthHourLimit(''), 248);
});

test('validation reports the first problem row by row', () => {
  assert.equal(check([]), '请至少填写一条境外工时');
  assert.equal(check([], { commonAmount: 100 }), '有境外公共费用时，必须录入至少一条工时');
  assert.equal(check([row()]), '');
  assert.equal(check([row({ foreign_entity: 'X' })]), '1. 请选择研发主体');
  assert.equal(check([row({ project: '' })]), '1. 请选择项目');
  assert.equal(check([row({ hours: '8.001' })]), '1. 工时最多保留两位小数');
  assert.equal(check([row({ hours: '0' })]), '1. 工时必须大于 0（单位：小时）');
  assert.match(check([row({ hours: '240.01' })]), /工时不能超过当月自然日数 × 8 = 240 小时/);
  assert.equal(check([row({ hours: '240' })]), '');
  assert.equal(check([row(), row({ hours: '4' })]), '2. 同一主体和项目只能填写一行');
});

test('the saved row carries the hours and the derived days', () => {
  assert.deepEqual(payloadRow(row({ hours: '18.8', remark: ' 验收 ' })), {
    foreign_entity: 'QIHENG DEMO OVERSEAS', project: 'P1', project_code: 'RD14', project_name: 'ACONCA 7961',
    hours: 18.8, occurrence_days: 2.35, remark: '验收',
  });
});
