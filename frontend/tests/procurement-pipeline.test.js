import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { NUDGE_AFTER_DAYS, PIPE_LABELS, PURCHASE_PIPE_LABELS, arrivalOf, canNudge, pipeline, waitedDays } from '../src/lib/procurementView.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const NOW = Date.parse('2026-10-12T10:00:00');
const procurement = (extra = {}) => ({ request_type: '采购申请', workflow_status: '待审批', business_status: '待审批', ...extra });
const direct = (extra = {}) => ({ request_type: '购买申请', workflow_status: '待审批', business_status: '待审批', ...extra });
const chain = (stage, extra = {}) => procurement({ workflow_status: '已完成', business_status: '需求已批准/待询价', procurement_chain: { stage, po_numbers: stage === 'po' ? ['PO-1'] : [] }, ...extra });

test('a procurement request has six steps and the current one follows the chain stage', () => {
  assert.deepEqual(PIPE_LABELS, ['需求审批', '提 PR', '比价', '价格审批', 'PO 执行', '完成']);
  assert.deepEqual(pipeline(procurement()).cells, ['cur', 'todo', 'todo', 'todo', 'todo', 'todo']);
  assert.equal(pipeline(procurement()).current, '需求审批');
  assert.deepEqual(pipeline(chain('await_pr')).cells, ['done', 'cur', 'todo', 'todo', 'todo', 'todo']);
  assert.deepEqual(pipeline(chain('price')).cells, ['done', 'done', 'done', 'cur', 'todo', 'todo']);
  assert.deepEqual(pipeline(chain('po')).cells, ['done', 'done', 'done', 'done', 'cur', 'todo']);
  assert.equal(pipeline(chain('po')).current, 'PO 执行');
});

test('a closed request is all green; drafts, withdrawn and rejected ones have no bar', () => {
  assert.deepEqual(pipeline(procurement({ workflow_status: '已完成', business_status: '已关闭' })).cells, Array(6).fill('done'));
  assert.equal(pipeline(procurement({ workflow_status: '草稿' })), null);
  assert.equal(pipeline(procurement({ workflow_status: '已拒绝' })), null);
  assert.equal(pipeline(null), null);
});

test('a purchase request has three steps: approval, payment, done', () => {
  assert.deepEqual(PURCHASE_PIPE_LABELS, ['审批', '付款', '完成']);
  assert.deepEqual(pipeline(direct()).cells, ['cur', 'todo', 'todo']);
  assert.deepEqual(pipeline(direct({ workflow_status: '已完成', business_status: '待付款' })).cells, ['done', 'cur', 'todo']);
  assert.deepEqual(pipeline(direct({ workflow_status: '已完成', business_status: '部分付款' })).cells, ['done', 'cur', 'todo']);
  assert.deepEqual(pipeline(direct({ workflow_status: '已完成', business_status: '已付款' })).cells, ['done', 'done', 'done']);
  assert.equal(pipeline(direct({ workflow_status: '草稿' })), null);
});

test('arrival progress is received over ordered quantity and never exceeds one hundred percent', () => {
  assert.deepEqual(arrivalOf({ ordered_quantity: 40, received_quantity: 24 }), { got: 24, total: 40, pct: 60 });
  assert.deepEqual(arrivalOf({ ordered_quantity: 8, received_quantity: 9 }), { got: 8, total: 8, pct: 100 });
  assert.equal(arrivalOf({ ordered_quantity: 0, received_quantity: 0 }), null);
  assert.equal(arrivalOf({}), null);
  assert.equal(arrivalOf(null), null);
});

test('waiting days count calendar days like the server does, so the button and the endpoint agree around midnight', () => {
  const since = (stamp) => ({ steps: [{ acted_on: stamp }] });
  // 10 月 9 日 23:30 签的，10 月 12 日 00:30：满 24 小时只有 2 天 1 小时，但日历上已经是第 3 天（后端就是这么算的）
  assert.equal(waitedDays(since('2026-10-09 23:30:00'), Date.parse('2026-10-12T00:30:00')), 3);
  assert.equal(waitedDays(since('2026-10-09 00:30:00'), Date.parse('2026-10-12T23:30:00')), 3);
  assert.equal(waitedDays(since('2026-10-12 08:00:00'), Date.parse('2026-10-12T23:59:00')), 0);
  assert.equal(waitedDays(since('2026-10-13 08:00:00'), Date.parse('2026-10-12T10:00:00')), 0, 'never negative');
  assert.equal(canNudge(procurement({ owner: 'a@tests-x.example.invalid', steps: [{ acted_on: '2026-10-09 23:30:00' }] }), { user: 'a@tests-x.example.invalid', now: Date.parse('2026-10-12T00:30:00') }), true);
});

test('the nudge button is for the applicant or the project owner after three days of waiting, never for approvers or others', () => {
  assert.equal(NUDGE_AFTER_DAYS, 3);
  const waited = (days, extra = {}) => procurement({
    owner: 'applicant@tests-x.example.invalid', employee: 'E1', project_owner: 'person041@tests-x.example.invalid',
    steps: [{ acted_on: new Date(NOW - days * 86400000).toISOString().slice(0, 19).replace('T', ' ') }], ...extra,
  });
  assert.equal(canNudge(waited(4), { user: 'applicant@tests-x.example.invalid', now: NOW }), true);
  assert.equal(canNudge(waited(4), { user: 'someone@tests-x.example.invalid', employee: 'E1', now: NOW }), true, 'on behalf of: the employee is the applicant');
  assert.equal(canNudge(waited(4), { user: 'Owner@tests-x.example.invalid', now: NOW }), true, 'the project owner');
  assert.equal(canNudge(waited(4), { user: 'pmc@tests-x.example.invalid', employee: 'E7', now: NOW }), false, 'an approver cannot nudge');
  assert.equal(canNudge(waited(2), { user: 'applicant@tests-x.example.invalid', now: NOW }), false, 'not waiting long enough');
  assert.equal(canNudge(waited(9, { workflow_status: '已完成' }), { user: 'applicant@tests-x.example.invalid', now: NOW }), false);
  assert.equal(canNudge(waited(9, { request_type: '出差申请' }), { user: 'applicant@tests-x.example.invalid', now: NOW }), false);
  assert.equal(canNudge(waited(9), { user: '', now: NOW }), false);
  // 当前节点只剩提交人 / 项目负责人自己：没人可催
  const onlyMe = waited(9, { current_step_index: 2, steps: [{ step_index: 2, approvers: ['person041@tests-x.example.invalid'], approved_by: [], acted_on: '2026-10-01 10:00:00' }] });
  assert.equal(canNudge(onlyMe, { user: 'person041@tests-x.example.invalid', now: NOW }), false);
  assert.equal(canNudge(onlyMe, { user: 'applicant@tests-x.example.invalid', now: NOW }), true, 'the applicant can still nudge the owner');
  assert.equal(canNudge(null, { user: 'applicant@tests-x.example.invalid' }), false);
});

test('the pages show the pipeline bar, the nudge button and the read-only owner hint', () => {
  const bar = read('../src/components/procurement/PipelineBar.vue');
  assert.match(bar, /class="pr-pipe"/);
  assert.match(bar, /现在在：/);
  assert.match(bar, /超过 \$\{STUCK_AFTER_DAYS\} 天/);
  assert.match(bar, /isWaitingTooLong\(wait\)/);
  assert.match(bar, /pr-arrive/);
  assert.match(read('../src/components/procurement/ProcList.vue'), /<PipelineBar :row="row" :now="now" \/>/);
  assert.match(read('../src/components/procurement/ProcHome.vue'), /<PipelineBar :row="row" :now="now" where \/>/);
  const detail = read('../src/components/procurement/ProcDetail.vue');
  assert.match(detail, /request_nudge\.nudge_request/);
  assert.match(detail, /@click="nudge">催一下</);
  assert.match(detail, /项目负责人，可以看到这张申请的进度（只读）/);
  assert.match(detail, /<PipelineBar :row="row" where foot-only \/>/);
  const css = read('../src/styles/procurementUi.css');
  for (const rule of ['.xp .pr-pipe i.done', '.xp .pr-pipe i.cur', '.xp .pr-arrive .t']) assert.ok(css.includes(rule), rule);
});
