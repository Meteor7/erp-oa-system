// PR #79 审查：PMC、生产主管看不到金额时，报价 / 货期 / 付清状态照常，金额显示“—”不当成 0；物料看板阶段和地址同步；
// 采购申请列表「我负责的项目」按服务端全部取。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  amountText, approvalGuide, buildMatrix, isQuoted, planStatus, poCloseBlockers, poNextStep, poProgress, selectionConsequence,
} from '../src/lib/priceView.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

// 服务端去掉金额之后的价格审批单（unit_price / total_price 是 null，带 quoted 标志和货期）
const hiddenApproval = {
  name: 'PA-H', status: '待审批', amounts_hidden: 1, can_select_quote: true,
  lines: [{ name: 'A1', quantity: 30 }, { name: 'A2', quantity: 5 }],
  supplier_comparisons: [
    { supplier: '甲', is_selected: 1, prices: [
      { price_line: 'A1', quoted: 1, unit_price: null, total_price: null, delivery_date: '2026-10-15' },
      { price_line: 'A2', quoted: 1, unit_price: null, total_price: null, delivery_date: '2026-10-20' }] },
    { supplier: '乙', is_selected: 0, prices: [
      { price_line: 'A1', quoted: 1, unit_price: null, total_price: null, delivery_date: '2026-10-18' }] },
  ],
};

test('#79-2 隐藏单价时按 quoted 判断已报价，货期照常、金额是 null、不标最低', () => {
  const matrix = buildMatrix(hiddenApproval);
  const [a, b] = matrix.suppliers;
  assert.deepEqual([a.quotedCount, a.complete, b.quotedCount, b.complete], [2, true, 1, false]);
  assert.equal(a.total, null);
  assert.equal(a.lowestComplete, false);
  const first = matrix.rows[0].cells;
  assert.deepEqual(first.map((cell) => [cell.quoted, cell.delivery, cell.unit, cell.total, cell.best]),
    [[true, '2026-10-15', null, null, false], [true, '2026-10-18', null, null, false]]);
  assert.equal(matrix.rows[1].cells[1].quoted, false);
  assert.equal(amountText(a.total, hiddenApproval.amounts_hidden), '—');
});

test('#79-2 isQuoted：有标志用标志，没有标志的老数据按单价 > 0', () => {
  assert.equal(isQuoted(null), false);
  assert.equal(isQuoted({ quoted: 1, unit_price: null }), true);
  assert.equal(isQuoted({ quoted: 0, unit_price: 12 }), false);
  assert.equal(isQuoted({ unit_price: 12 }), true);
  assert.equal(isQuoted({ unit_price: 0 }), false);
});

test('#79-2 选定供应商的后果：隐藏金额时条数照算、总额是 null，引导里显示“—”', () => {
  const info = selectionConsequence(hiddenApproval, hiddenApproval.supplier_comparisons[1]);
  assert.deepEqual({ quoted: info.quoted, returned: info.returned, total: info.total }, { quoted: 1, returned: 1, total: null });
  const guide = approvalGuide(hiddenApproval);
  assert.match(guide.text, /成交总额 —/);
  assert.doesNotMatch(guide.text, /¥ 0\.00/);
});

const hiddenPo = (patch = {}) => ({
  name: 'PO-H', status: '付款中', contract_status: '已生效', amounts_hidden: 1,
  total_amount: null, paid_amount: null, outstanding_amount: null,
  lines: [{ quantity: 2, received_quantity: 2, inspection_status: '已通过', amount: null, unit_price: null }],
  payment_plan: [{ amount: null, paid_amount: null, status: '已付款', paid_full: 1 }],
  ...patch,
});

test('#79-3 隐藏金额的 PO：付清与否看服务端的 paid_full，不再因为金额是 null 卡在“付款结清”', () => {
  const paid = hiddenPo({ paid_full: 1 });
  assert.equal(poProgress(paid).paidFull, true);
  assert.deepEqual(poCloseBlockers(paid), []);
  assert.equal(poNextStep(paid), '可校验并关闭');
  assert.equal(poProgress(paid).paid, null);
  assert.equal(poProgress(paid).total, null);
  const unpaid = hiddenPo({ paid_full: 0 });
  assert.deepEqual(poCloseBlockers(unpaid), ['付款结清']);
  assert.equal(poNextStep(unpaid), '到货 / 验收 / 付款进行中');
});

test('#79-3 看得到金额的 PO 仍按金额算（老规则不变）', () => {
  const open = { status: '付款中', contract_status: '已生效', total_amount: 100, paid_amount: 100,
    lines: [{ quantity: 1, received_quantity: 1, inspection_status: '已通过' }], payment_plan: [{ amount: 100, paid_amount: 100 }] };
  assert.equal(poProgress(open).paidFull, true);
  assert.equal(poProgress({ ...open, paid_full: 0, paid_amount: 50 }).paidFull, false);
});

test('#79-3 付款期次：金额去掉后按 paid_full / 状态显示已付款', () => {
  assert.equal(planStatus({ amount: null, paid_amount: null, paid_full: 1, status: '部分付款' }).text, '已付款');
  assert.equal(planStatus({ amount: null, paid_amount: null, paid_full: 0, status: '待审批' }).text, '待审批（未发起）');
});

test('#79-3 采购申请详情、执行进度：隐藏金额显示“—”，不显示 ¥ 0.00', () => {
  const detail = read('../src/components/procurement/ProcDetail.vue');
  assert.match(detail, /if \(po\.amounts_hidden\) return null;/);
  assert.match(detail, /poCash\(po, poAmount\(po\)\)/);
  assert.match(detail, /poCash\(po, plan\.amount\)/);
  assert.doesNotMatch(detail, /¥ \{\{ money\(poAmount\(po\)\) \}\}/);
  assert.doesNotMatch(detail, /¥ \{\{ money\(plan\.amount\) \}\}/);
  const exec = read('../src/components/MaterialExecutionProgress.vue');
  assert.match(exec, /if \(po\.amounts_hidden\) return \{ supplier: po\.supplier \|\| '—', unit: null, amount: null, hidden: true \};/);
  assert.match(exec, /amountText\(value, price\.hidden\)/);
  assert.doesNotMatch(exec, /¥ \{\{ money\(priceOf/);
});

test('#79-5 「我负责的项目」页签按服务端全部取，取不到时才退回到“全部”里筛', () => {
  const list = read('../src/components/procurement/ProcList.vue');
  assert.match(list, /apiGet\('procurement_owned\.list_owned_requests', \{ request_type: ctx\.requestType \}\)/);
  assert.match(list, /ownedRows\(data\.owned \|\| data\.all, ctx\.currentUser, ctx\.currentEmployee\)/);
  assert.match(list, /scope\.value === 'owned'\s*\n\s*\? !data\.owned && data\.all\.length >= LIST_LIMIT/);
});

test('#79-6 物料看板：点阶段把 ?status= 写进地址，地址和页面上的阶段一致', () => {
  const page = read('../src/pages/MaterialProgress.vue');
  const fn = page.slice(page.indexOf('function setStatus('), page.indexOf('function selectStage('));
  assert.match(fn, /status\.value = value;/);
  assert.match(fn, /if \(value\) next\.status = value;\s*\n\s*else delete next\.status;/);
  assert.match(fn, /router\.replace\(\{ path: route\.path, query: next \}\)/);
  assert.match(page, /function selectStage\(value\) \{\s*\n\s*setStatus\(status\.value === value \? '' : value\);/);
  assert.match(page, /@click="setStatus\(''\)"/);
  assert.doesNotMatch(page, /status = ''; query\(\)/);
});
