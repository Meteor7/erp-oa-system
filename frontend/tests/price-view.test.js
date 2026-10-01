import assert from 'node:assert/strict';
import test from 'node:test';
import {
  approvalGuide, approvalTimeline, availableLineCount, buildMatrix, contextApprovals, contextPos, contextPrs, contextSummary,
  contractDraftFor, contractMode, contractPayload, contractStepper, createApprovalLines, defaultTab, emptySupplierDraft,
  fillPlanAmounts, filterApprovals, filterPos, filterPrs, money, occupiedQuantity, planStatus, poCloseBlockers, poMainAction,
  poNextStep, poProgress, quantityError, resolveTab, selectedLines, selectionConsequence, selectionSummary, sourceKey,
  submitBlockers, supplierDraftFromGroup, supplierPayload, tabQuery, usageByPrLine, usageText, validateSupplierDraft,
  maskAccount, missingDelivery, deliveryPayload, poTrail,
} from '../src/lib/priceView.js';

const prs = [
  { name: 'PR-1', status: '部分转PO', lines: [
    { name: 'L1', source_request: 'OA-1', project: 'P1', material_serial: 'MAT-1', item_name: '铝件', quantity: 30, remaining_quantity: 0, unit: '件' },
    { name: 'L2', source_request: 'OA-1', project: 'P1', material_serial: 'MAT-2', item_name: '垫片', quantity: 40, remaining_quantity: 40, unit: '片' },
  ] },
  { name: 'PR-2', status: '待采购', lines: [
    { name: 'L3', source_request: 'OA-2', project: 'P2', material_serial: 'MAT-3', item_name: '螺丝', quantity: 5, remaining_quantity: 0, unit: '套' },
  ] },
];

test('money is always CNY with two decimals', () => {
  assert.equal(money(6275), '¥ 6,275.00');
  assert.equal(money('1718'), '¥ 1,718.00');
  assert.equal(money(null), '¥ 0.00');
  assert.equal(maskAccount('6222 0212 3456 3321'), '**** **** 3321');
});

test('page selection keeps tab=po, view=source|approvals, approval, po and pr links working', () => {
  assert.equal(resolveTab({ tab: 'po' }), 'po');
  assert.equal(resolveTab({ po: 'PO-1' }), 'po');
  assert.equal(resolveTab({ view: 'source' }), 'source');
  assert.equal(resolveTab({ pr: 'PR-1', view: 'source' }), 'source');
  assert.equal(resolveTab({ approval: 'PA-1' }), 'approvals');
  assert.equal(resolveTab({ view: 'approvals' }), 'approvals');
  assert.equal(resolveTab({ request: 'OA-1' }), '');
  assert.equal(resolveTab({ tab: 'po' }, { canPrice: true, canPo: false }), 'approvals');
  assert.equal(resolveTab({ view: 'source' }, { canPrice: false, canPo: true }), 'po');
  assert.equal(resolveTab({ view: 'source' }, { canPrice: false, canPo: false }), '');
  assert.deepEqual(tabQuery('po', { request: 'OA-1' }), { request: 'OA-1', tab: 'po' });
  assert.deepEqual(tabQuery('source', {}), { view: 'source' });
  assert.deepEqual(tabQuery('approvals', { request: '' }), { view: 'approvals' });
});

test('default tab sends buyers to PR source when nothing is actionable', () => {
  assert.equal(defaultTab({ hasPendingPr: true, hasActionable: false }), 'source');
  assert.equal(defaultTab({ hasPendingPr: true, hasActionable: true }), 'approvals');
  assert.equal(defaultTab({ hasPendingPr: false, hasActionable: false }), 'approvals');
  assert.equal(defaultTab({ canPrice: false, canPo: true }), 'po');
});

test('request context only keeps the chain of that OA', () => {
  const scoped = contextPrs(prs, 'OA-2');
  assert.equal(scoped.length, 1);
  assert.equal(scoped[0].name, 'PR-2');
  assert.equal(contextPrs(prs, '').length, 2);
  const approvals = [{ name: 'PA-1', source_requests: 'OA-1,OA-2' }, { name: 'PA-2', source_requests: 'OA-3' }];
  assert.deepEqual(contextApprovals(approvals, 'OA-2').map((item) => item.name), ['PA-1']);
  const pos = [{ name: 'PO-1', lines: [{ source_request: 'OA-3' }] }, { name: 'PO-2', lines: [{ source_request: 'OA-1' }] }];
  assert.deepEqual(contextPos(pos, 'OA-3').map((item) => item.name), ['PO-1']);
  assert.match(contextSummary({ request: 'OA-1', prs: contextPrs(prs, 'OA-1'), approvals: [], pos: [] }), /OA-1 · 1 张 PR · 待比价 1 项 · 0 张价格审批单 · 0 张 PO/);
  assert.equal(contextSummary({ request: '' }), '');
});

test('PR source: occupied = PR quantity minus selectable quantity, filters and search', () => {
  assert.equal(occupiedQuantity(prs[0].lines[0]), 30);
  assert.equal(occupiedQuantity(prs[0].lines[1]), 0);
  assert.equal(availableLineCount(prs[0]), 1);
  assert.deepEqual(filterPrs(prs, { availability: 'available' }).map((pr) => pr.name), ['PR-1']);
  assert.deepEqual(filterPrs(prs, { availability: 'exhausted' }).map((pr) => pr.name), ['PR-2']);
  assert.deepEqual(filterPrs(prs, { availability: 'all' }).map((pr) => pr.name), ['PR-1', 'PR-2']);
  assert.deepEqual(filterPrs(prs, { availability: 'all', query: '螺丝' }).map((pr) => pr.name), ['PR-2']);
  assert.deepEqual(filterPrs(prs, { availability: 'all', query: 'oa-1' }).map((pr) => pr.name), ['PR-1']);
  assert.deepEqual(filterPrs(prs, { availability: 'all', focusPr: 'PR-2' }).map((pr) => pr.name), ['PR-2']);
});

test('PR occupancy explains which approval or PO holds the quantity', () => {
  const approvals = [
    { name: 'PA-1', status: '待审批', lines: [{ source_pr_line: 'L1' }] },
    { name: 'PA-2', status: '已取消', lines: [{ source_pr_line: 'L2' }] },
  ];
  const pos = [{ name: 'PO-1', status: '草稿', lines: [{ source_pr_line: 'L1' }] }, { name: 'PO-9', status: '已取消', lines: [{ source_pr_line: 'L2' }] }];
  const usage = usageByPrLine(approvals, pos);
  assert.equal(usageText(usage.get('L1')), 'PA-1 待审批、PO-1 草稿');
  assert.equal(usage.get('L2'), undefined);
});

test('selected lines produce create_price_approval payload with per-line quantity and validate against remaining', () => {
  const key = sourceKey(prs[0], prs[0].lines[1]);
  const rows = selectedLines(prs, new Set([key]), { [key]: 15 });
  assert.equal(rows.length, 1);
  assert.deepEqual(createApprovalLines(rows), [{ source_pr: 'PR-1', source_pr_line: 'L2', quantity: 15 }]);
  assert.deepEqual(selectionSummary(rows), { count: 1, prs: 1, requests: 1, invalid: 0 });
  assert.equal(quantityError(prs[0].lines[1], 40), '');
  assert.match(quantityError(prs[0].lines[1], 41), /最多 40/);
  assert.match(quantityError(prs[0].lines[1], 0), /大于 0/);
  assert.match(quantityError(prs[0].lines[1], ''), /大于 0/);
});

const approval = {
  name: 'PA-1', status: '待审批', can_select_quote: true,
  lines: [
    { name: 'A1', item_name: '铝合金结构件', quantity: 30, unit: '件', selected_supplier: '' },
    { name: 'A2', item_name: '紧固件套装', quantity: 5, unit: '套', selected_supplier: '' },
  ],
  supplier_comparisons: [
    { supplier: '甲', is_recommended: 1, is_selected: 0, payment_method: '预付', prices: [
      { price_line: 'A1', unit_price: 180, delivery_date: '2026-10-15' }, { price_line: 'A2', unit_price: 175, delivery_date: '2026-10-15' }] },
    { supplier: '乙', is_recommended: 0, is_selected: 0, payment_method: '款到发货', prices: [
      { price_line: 'A1', unit_price: 172, delivery_date: '2026-10-18' }] },
    { supplier: '丙', is_recommended: 0, is_selected: 0, payment_method: '月结', prices: [
      { price_line: 'A1', unit_price: 186, delivery_date: '' }, { price_line: 'A2', unit_price: 168, delivery_date: '' }] },
  ],
};

test('comparison matrix only compares totals between suppliers who quoted every line', () => {
  const matrix = buildMatrix(approval);
  const [a, b, c] = matrix.suppliers;
  assert.equal(a.complete, true);
  assert.equal(b.complete, false);
  assert.equal(c.complete, true);
  assert.equal(a.total, 6275);
  assert.equal(b.total, 5160);
  assert.equal(c.total, 6420);
  // 乙总价最低但只报了一部分，不能标成最低；完整报价里甲最低。
  assert.equal(b.lowestComplete, false);
  assert.equal(a.lowestComplete, true);
  assert.equal(c.lowestComplete, false);
  assert.equal(matrix.rows[0].cells[1].best, true);
  assert.equal(matrix.rows[0].cells[0].best, false);
  assert.equal(matrix.rows[1].cells[1].quoted, false);
  // 第二项只有甲、丙报价：丙 168 最低。
  assert.equal(matrix.rows[1].cells[2].best, true);
  assert.equal(matrix.rows[1].cells[0].best, false);
});

test('a single complete quote is not labelled lowest and a single quote per line has no best price', () => {
  const only = {
    ...approval,
    supplier_comparisons: [approval.supplier_comparisons[0], approval.supplier_comparisons[1]],
  };
  const matrix = buildMatrix(only);
  assert.equal(matrix.suppliers[0].lowestComplete, false);
  assert.equal(matrix.rows[1].cells[0].best, false);
});

test('choosing a supplier shows the consequence: unquoted lines go back to the PR', () => {
  const picked = { ...approval, supplier_comparisons: approval.supplier_comparisons.map((group) => ({ ...group, is_selected: group.supplier === '乙' ? 1 : 0 })) };
  const info = selectionConsequence(picked, picked.supplier_comparisons[1]);
  assert.deepEqual({ quoted: info.quoted, returned: info.returned, total: info.total }, { quoted: 1, returned: 1, total: 5160 });
  const guide = approvalGuide(picked);
  assert.match(guide.text, /它没报价的 1 项物料会退回 PR/);
  assert.match(guide.text, /生成 1 张 PO 草稿/);
  assert.match(approvalGuide(approval).text, /选择成交供应商/);
  assert.match(approvalGuide({ ...approval, can_select_quote: false }).text, /等待副总经理审批/);
  assert.match(approvalGuide({ ...approval, status: '草稿' }, { canEdit: true }).text, /提交会重新占用 PR 数量/);
});

test('submit needs a summary and at least one supplier', () => {
  assert.deepEqual(submitBlockers({ supplier_comparisons: [] }, ''), ['填写采购比价总结', '至少录入一家供应商报价']);
  assert.deepEqual(submitBlockers(approval, '推荐甲'), []);
});

test('approval timeline has no reject step and keeps the draft state readable', () => {
  const draft = approvalTimeline({ status: '草稿', steps: [] });
  assert.equal(draft[0].state, 'todo');
  assert.equal(draft[1].sub, '未开始');
  const pending = approvalTimeline({ status: '待审批', steps: [{ name: 's1', label: '价格审批：副总经理', status: '待审批' }] });
  assert.equal(pending[0].state, 'done');
  assert.equal(pending[1].state, 'now');
  const passed = approvalTimeline({ status: '已转PO', steps: [{ name: 's1', label: '价格审批：副总经理', status: '已通过', action_by: 'vp', acted_on: '2026-09-29 16:10:00' }] });
  assert.equal(passed[1].state, 'done');
  assert.match(passed[1].sub, /2026-09-29 16:10/);
});

test('approval list filters by status and search', () => {
  const items = [
    { name: 'PA-1', status: '草稿', source_prs: 'PR-1', supplier_comparisons: [{ supplier: '甲' }] },
    { name: 'PA-2', status: '待审批', source_prs: 'PR-2', supplier_comparisons: [] },
    { name: 'PA-3', status: '已转PO', source_prs: 'PR-3', supplier_comparisons: [] },
  ];
  assert.deepEqual(filterApprovals(items, 'draft').map((item) => item.name), ['PA-1']);
  assert.deepEqual(filterApprovals(items, 'done').map((item) => item.name), ['PA-3']);
  assert.deepEqual(filterApprovals(items, 'all', '甲').map((item) => item.name), ['PA-1']);
});

test('supplier draft: blank slots, validation mirrors the server rules and payload carries the payment plan', () => {
  const draft = emptySupplierDraft(approval);
  assert.equal(draft.currency, 'CNY');
  assert.equal(draft.payment_plan.length, 1);
  assert.deepEqual(validateSupplierDraft(approval, draft).slice(0, 3), ['请先填写供应商名称', '请填写付款方式', '至少给一项物料报价（没有报价的物料留空）']);

  draft.supplier = '丁';
  draft.payment_method = '预付 30%，验收后 70%';
  draft.prices.A1.unit_price = 100;
  draft.prices.A1.delivery_date = '2026-10-20';
  draft.payment_plan = [
    { installment_name: '第1期', payment_stage: '预付款', percentage: 30, amount: 0, planned_date: '', trigger_condition: '合同生效', invoice_requirement: '付款后提供' },
    { installment_name: '第2期', payment_stage: '尾款', percentage: 70, amount: 0, planned_date: '', trigger_condition: '全部到货并验收通过', invoice_requirement: '付款前提供' },
  ];
  assert.ok(validateSupplierDraft(approval, draft).some((item) => /金额/.test(item)));
  fillPlanAmounts(draft, 3000);
  assert.deepEqual(draft.payment_plan.map((row) => row.amount), [900, 2100]);
  assert.deepEqual(validateSupplierDraft(approval, draft), []);

  const payload = supplierPayload(approval, draft);
  assert.equal(payload.price_approval, 'PA-1');
  assert.equal(payload.original_supplier, '');
  assert.equal(payload.currency, 'CNY');
  assert.equal(payload.is_recommended, 0);
  const prices = JSON.parse(payload.prices);
  assert.deepEqual(prices[0], { price_line: 'A1', unit_price: 100, delivery_date: '2026-10-20' });
  assert.deepEqual(prices[1], { price_line: 'A2', unit_price: '', delivery_date: '' });
  assert.equal(JSON.parse(payload.payment_plan).length, 2);

  draft.payment_plan[1].percentage = 60;
  assert.ok(validateSupplierDraft(approval, draft).some((item) => /比例合计必须为 100%/.test(item)));
});

test('editing an existing supplier keeps its original name for renames and copies the plan', () => {
  const group = { supplier: '甲', payment_method: '预付', currency: 'CNY', tax_rate: 13, contract_entity: '主体', is_recommended: 1, note: '现货',
    payment_plan: [{ installment_name: '全款', payment_stage: '到货后全额付款', percentage: 100, amount: 6275, trigger_condition: '全部到货', invoice_requirement: '付款前提供' }],
    prices: approval.supplier_comparisons[0].prices };
  const draft = supplierDraftFromGroup(approval, group);
  assert.equal(draft.original_supplier, '甲');
  assert.equal(draft.is_recommended, true);
  assert.equal(draft.prices.A2.unit_price, 175);
  draft.supplier = '甲公司';
  assert.equal(supplierPayload(approval, draft).original_supplier, '甲');
  assert.equal(supplierPayload(approval, draft).supplier, '甲公司');
});

const po = (patch = {}) => ({
  name: 'PO-1', status: '草稿', contract_status: '待补充信息', supplier: '甲', total_amount: 1718, paid_amount: 0,
  can_manage_purchase: 1, can_seal_contract: 0, source_price_approvals: 'PA-1',
  lines: [
    { name: 'P1', quantity: 4, received_quantity: 0, inspection_status: '未验收', contract_delivery_date: '' },
    { name: 'P2', quantity: 10, received_quantity: 0, inspection_status: '未验收', contract_delivery_date: '' },
  ],
  payment_plan: [{ name: 'R1', amount: 515.4, paid_amount: 0, status: '待审批' }, { name: 'R2', amount: 1202.6, paid_amount: 0, status: '待审批' }],
  ...patch,
});

test('contract steps follow contract_status and the main action depends on the viewer', () => {
  assert.equal(contractMode(po()), 'draft');
  assert.equal(contractMode(po({ status: '待合同复核' })), 'fill');
  assert.equal(contractMode(po({ status: '待合同复核', contract_status: '草稿待复核' })), 'review');
  assert.equal(contractMode(po({ status: '待电子用印', contract_status: '待电子用印' })), 'seal');
  assert.equal(contractMode(po({ status: '供应商制作中', contract_status: '已生效' })), 'effective');

  assert.deepEqual(poMainAction(po()), { key: 'confirm', text: '确认 PO' });
  assert.equal(poMainAction(po({ can_manage_purchase: 0 })).key, '');
  assert.equal(poMainAction(po({ status: '待合同复核' })).key, 'generate');
  assert.equal(poMainAction(po({ status: '待合同复核', contract_status: '草稿待复核' })).key, 'review');
  const sealing = po({ status: '待电子用印', contract_status: '待电子用印' });
  assert.equal(poMainAction(sealing).key, '');
  assert.match(poMainAction(sealing).wait, /副总经理电子用印/);
  assert.equal(poMainAction({ ...sealing, can_seal_contract: 1 }).key, 'seal');
  assert.equal(poMainAction(po({ status: '供应商制作中', contract_status: '已生效' })).key, '');

  const steps = contractStepper(po({ status: '待合同复核', contract_status: '草稿待复核' }));
  assert.deepEqual(steps.map((step) => [step.done, step.now]), [[true, false], [false, true], [false, false], [false, false]]);
  const sealed = contractStepper(po({ status: '供应商制作中', contract_status: '已生效' }));
  assert.ok(sealed.every((step) => step.done && !step.now));
  assert.match(poNextStep(po()), /确认/);
});

test('close PO lists everything still missing: all received, all passed, paid in full', () => {
  const running = po({ status: '供应商制作中', contract_status: '已生效' });
  assert.deepEqual(poCloseBlockers(running), ['全部到货', '全部验收通过', '付款结清']);
  const received = po({
    status: '到货验收中', contract_status: '已生效',
    lines: [{ name: 'P1', quantity: 4, received_quantity: 4, inspection_status: '已通过' }, { name: 'P2', quantity: 10, received_quantity: 10, inspection_status: '待验收' }],
  });
  assert.deepEqual(poCloseBlockers(received), ['全部验收通过', '付款结清']);
  const done = po({
    status: '付款中', contract_status: '已生效', paid_amount: 1718,
    lines: [{ name: 'P1', quantity: 4, received_quantity: 4, inspection_status: '已通过' }, { name: 'P2', quantity: 10, received_quantity: 10, inspection_status: '已通过' }],
    payment_plan: [{ amount: 515.4, paid_amount: 515.4 }, { amount: 1202.6, paid_amount: 1202.6 }],
  });
  assert.deepEqual(poCloseBlockers(done), []);
  const partial = poProgress({ ...done, payment_plan: [{ amount: 515.4, paid_amount: 515.4 }, { amount: 1202.6, paid_amount: 0 }] });
  assert.equal(partial.paidFull, false);
  assert.deepEqual({ lines: poProgress(received).lineCount, received: poProgress(received).received, passed: poProgress(received).passed }, { lines: 2, received: 2, passed: 1 });
});

test('payment plan rows show real statuses', () => {
  assert.deepEqual(planStatus({ status: '待审批', amount: 10, paid_amount: 0 }), { text: '待审批（未发起）', tone: 'gray' });
  assert.deepEqual(planStatus({ status: '审批中', payment_request: 'OA-9', amount: 10, paid_amount: 0 }), { text: '付款审批中', tone: 'cobalt' });
  assert.deepEqual(planStatus({ status: '已付款', amount: 10, paid_amount: 10 }), { text: '已付款', tone: 'jade' });
  assert.deepEqual(planStatus({ status: '待生成' }), { text: '待生成', tone: 'gray' });
});

test('contract draft exposes every field the backend accepts and only sends what was filled', () => {
  const sample = po({
    status: '待合同复核', contract_supplier_legal_name: '甲有限公司', contract_credit_code: '9132', contract_supplier_address: '苏州',
    contract_contact: '周工 138', contract_bank_name: '某银行', contract_bank_account: '6222333344443321', contract_delivery_date: '2026-10-15',
  });
  const draft = contractDraftFor(sample);
  assert.equal(draft.supplier_legal_name, '甲有限公司');
  assert.equal(draft.contract_bank_account, '6222333344443321');
  assert.deepEqual(contractPayload(sample, draft), {
    name: 'PO-1', supplier_legal_name: '甲有限公司', credit_code: '9132', supplier_address: '苏州', contract_contact: '周工 138',
    contract_bank_name: '某银行', contract_bank_account: '6222333344443321', contract_delivery_date: '2026-10-15',
  });
  const sparse = contractPayload(po({ status: '待合同复核' }), { supplier_legal_name: ' 乙 ', credit_code: '', contract_delivery_date: '' });
  assert.deepEqual(sparse, { name: 'PO-1', supplier_legal_name: '乙' });
});

test('confirming a PO needs a contract delivery date on every line', () => {
  const sample = po();
  assert.equal(missingDelivery(sample, { P1: '2026-10-15', P2: '' }), 1);
  assert.equal(missingDelivery(sample, { P1: '2026-10-15', P2: '2026-10-16' }), 0);
  assert.deepEqual(deliveryPayload(sample, { P1: '2026-10-15' }), [
    { line: 'P1', contract_delivery_date: '2026-10-15' }, { line: 'P2', contract_delivery_date: '' },
  ]);
});

test('PO list filters and contract trail read real timestamps', () => {
  const items = [po(), po({ name: 'PO-2', status: '已关闭' }), po({ name: 'PO-3', status: '供应商制作中', supplier: '乙' })];
  assert.deepEqual(filterPos(items, 'contract').map((item) => item.name), ['PO-1']);
  assert.deepEqual(filterPos(items, 'running').map((item) => item.name), ['PO-3']);
  assert.deepEqual(filterPos(items, 'all', '乙').map((item) => item.name), ['PO-3']);
  const trail = poTrail(po({ creation: '2026-09-22 10:02:00.1', contract_reviewed_on: '2026-09-22 16:05:00', contract_reviewed_by: 'a', contract_sealed_on: '2026-09-22 17:30:00', contract_sealed_by: 'b' }));
  assert.equal(trail.length, 3);
  assert.match(trail[0].text, /电子用印/);
  assert.match(trail[2].text, /价格审批通过，生成 PO 草稿/);
});
