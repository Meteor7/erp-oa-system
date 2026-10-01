import assert from 'node:assert/strict';
import test from 'node:test';

import {
  INSPECT_CHOICES, MODE_CONFIG, REFUND_NOTICE, STATUS_FILTERS, WORK_STATUSES,
  activeDocumentTypes, approvalBanner, approveLabel, buildFulfilmentRequest, buildPoGroups, computeWorkStatus,
  conditionsRegressed, contractReady, currentStepKey, defaultQuantity, defaultRejectTarget, eligibleLines,
  evaluateItem, filterGroups, findWorkItem, fulfilmentModes, fulfilmentRoleNote, gateTiles, installmentView,
  invoiceDocCount, isFinalPayStep, isPoSourced, latestInspectionReason, legacyActions, lineHint, lineState,
  liveReview, money, normalizeRecords, paymentBlockers, paymentFacts, pickMode, poLinesView, poPaymentChecklist,
  quantity, queueFilter, recordDetailText, rejectionTargets, requestRecords, requiresInspection, requiresReceipt,
  sortGroups, sortQueue, sortRecordsDesc, statusCounts, stepRows, summarizeLines, todayString, triggerFlags,
  validateFulfilment, validateReject, validateRemoveReason, waitText, waitedDays, waitingFor,
} from '../src/lib/paymentView.js';

// ------------------------------------------------------------------ builders
let seq = 0;
const line = (over = {}) => {
  seq += 1;
  return {
    name: `L${seq}`, item_name: `物料${seq}`, material_serial: `S${seq}`, specification: 'spec', unit: '个',
    quantity: 10, received_quantity: 0, inspection_status: '', unit_price: 100, amount: 1000, ...over,
  };
};
const received = (over = {}) => line({ received_quantity: 10, inspection_status: '待验收', ...over });
const passed = (over = {}) => line({ received_quantity: 10, inspection_status: '已通过', ...over });
const exchanging = (over = {}) => line({ received_quantity: 10, inspection_status: '换货中', ...over });
const returning = (over = {}) => line({ received_quantity: 10, inspection_status: '退货中', ...over });
const item = (lines, over = {}) => ({
  key: 'PO1:R1', po: 'PO1', payment_plan_row: 'R1', installment_no: 1, installment_name: '第1期', payment_stage: '预付款',
  trigger_condition: '合同生效', invoice_requirement: '付款后提供', percentage: 30, amount: 600, paid_amount: 0, currency: 'CNY',
  supplier: '供应商甲', po_status: '供应商制作中', contract_status: '已生效', source_price_approvals: 'PA-1',
  payment_request: '', lines, fulfillment_records: [], ...over,
});

// ------------------------------------------------------------------ 触发条件
test('trigger text decides whether receipt and inspection are required', () => {
  const rows = [
    ['合同生效', false, false], ['', false, false], ['到货', true, false], ['全部到货', true, false],
    ['验收通过', false, true], ['全部到货并验收通过', true, true], ['到货后验收', true, true],
  ];
  for (const [trigger, receipt, inspection] of rows) {
    assert.equal(requiresReceipt(trigger), receipt, trigger);
    assert.equal(requiresInspection(trigger), inspection, trigger);
    const flags = triggerFlags({ trigger_condition: trigger });
    assert.deepEqual([flags.receipt, flags.inspection, flags.allReceived], [receipt, inspection, receipt || inspection], trigger);
  }
});

test('server requires_* flags win over the text when present', () => {
  const flags = triggerFlags({ trigger_condition: '合同生效', requires_receipt: 1, requires_inspection: 0 });
  assert.equal(flags.receipt, true);
  assert.equal(flags.inspection, false);
  assert.equal(triggerFlags({ trigger_condition: '验收通过', requires_inspection: 0 }).inspection, false);
});

// ------------------------------------------------------------------ 物料行结果
test('line result chips: 未到 / 待验收 / 已通过 / 换货中 / 退货中 (+ legacy 不合格)', () => {
  const rows = [
    [{ quantity: 10, received_quantity: 0, inspection_status: '' }, 'none', '未到', 10],
    [{ quantity: 10, received_quantity: 0, inspection_status: '未验收' }, 'none', '未到', 10],
    [{ quantity: 10, received_quantity: 10, inspection_status: '待验收' }, 'pending', '待验收', 0],
    [{ quantity: 10, received_quantity: 10, inspection_status: '' }, 'pending', '待验收', 0],
    [{ quantity: 10, received_quantity: 10, inspection_status: '已通过' }, 'passed', '已通过', 0],
    [{ quantity: 10, received_quantity: 10, inspection_status: '换货中' }, 'exchanging', '换货中', 0],
    [{ quantity: 10, received_quantity: 10, inspection_status: '退货中' }, 'returning', '退货中', 0],
    [{ quantity: 10, received_quantity: 10, inspection_status: '不合格' }, 'failed', '不合格', 0],
    // 部分到货（旧数据）：已到一部分，仍显示待验收，未到数量保留
    [{ quantity: 10, received_quantity: 4, inspection_status: '待验收' }, 'pending', '待验收', 6],
    // 退货发出之后：已到数量清零，回到未到
    [{ quantity: 10, received_quantity: 0, inspection_status: '未验收' }, 'none', '未到', 10],
  ];
  for (const [input, key, label, left] of rows) {
    const state = lineState(input);
    assert.equal(state.key, key, JSON.stringify(input));
    assert.equal(state.label, label);
    assert.equal(state.left, left);
  }
  assert.equal(lineState({ quantity: 10, received_quantity: 4 }).partial, true);
  assert.equal(lineState({ quantity: 10, received_quantity: 10 }).received, true);
  assert.equal(lineState({ quantity: 10, received_quantity: 9.9999999 }).received, true);
  assert.equal(lineState({ quantity: 10, received_quantity: 9 }).received, false);
});

test('summarizeLines counts received / passed / exchange / return lines', () => {
  const summary = summarizeLines([passed(), received(), exchanging(), returning(), line(), line({ received_quantity: 3 })]);
  assert.equal(summary.total, 6);
  assert.equal(summary.recvN, 4);
  assert.equal(summary.inspN, 1);
  assert.equal(summary.allReceived, false);
  assert.equal(summary.allInspected, false);
  assert.equal(summary.hasExchange, true);
  assert.equal(summary.hasReturn, true);
  assert.equal(summary.unreceivedN, 2);
  assert.equal(summary.anyPartial, true);
  const empty = summarizeLines([]);
  assert.equal(empty.allReceived, false);
  assert.equal(empty.allInspected, false);
  assert.equal(summarizeLines([passed(), passed()]).allInspected, true);
});

// ------------------------------------------------------------------ 付款条件 / 工作状态（表驱动）
const GATE_CASES = [
  { name: '合同生效 + 什么都没到 -> 可提交', trigger: '合同生效', lines: () => [line(), line()], status: '可提交付款审批', blockers: [] },
  { name: '合同未生效 -> 待合同生效', trigger: '合同生效', contract: '待电子用印', lines: () => [line()], status: '待合同生效', blockers: ['PO 合同尚未生效'] },
  { name: 'PO 状态是待合同复核 -> 合同未就绪', trigger: '合同生效', po_status: '待合同复核', lines: () => [line()], status: '待合同生效', blockers: ['PO 合同尚未生效'] },
  { name: '全部到货 + 没到 -> 待到货资料', trigger: '全部到货', lines: () => [line(), line()], status: '待到货资料', blockers: ['本期要求全部到货'] },
  { name: '全部到货 + 到了一半 -> 待到货资料', trigger: '全部到货', lines: () => [received(), line()], status: '待到货资料', blockers: ['本期要求全部到货'] },
  { name: '全部到货 + 部分到货的行 -> 待到货资料', trigger: '全部到货', lines: () => [received(), line({ received_quantity: 4, inspection_status: '待验收' })], status: '待到货资料', blockers: ['本期要求全部到货'] },
  { name: '全部到货 + 到齐（未验收） -> 可提交', trigger: '全部到货', lines: () => [received(), received()], status: '可提交付款审批', blockers: [] },
  { name: '到货条件 + 有退货中的行（数量还在） -> 不拦（按到货数量判断）', trigger: '到货', lines: () => [received(), returning()], status: '可提交付款审批', blockers: [] },
  { name: '到货条件 + 退货发出后数量清零 -> 待到货资料', trigger: '到货', lines: () => [received(), line({ inspection_status: '未验收' })], status: '待到货资料', blockers: ['本期要求全部到货'] },
  { name: '全部到货并验收通过 + 没到 -> 待到货资料（三个阻塞）', trigger: '全部到货并验收通过', lines: () => [line()], status: '待到货资料', blockers: ['本期要求全部到货', '验收前需全部到货', '本期要求验收通过'] },
  { name: '全部到货并验收通过 + 到齐未验收 -> 待验收', trigger: '全部到货并验收通过', lines: () => [received(), received()], status: '待验收', blockers: ['本期要求验收通过'] },
  { name: '全部到货并验收通过 + 一项通过一项换货中 -> 待验收', trigger: '全部到货并验收通过', lines: () => [passed(), exchanging()], status: '待验收', blockers: ['本期要求验收通过'] },
  { name: '全部到货并验收通过 + 一项退货中 -> 待验收', trigger: '全部到货并验收通过', lines: () => [passed(), returning()], status: '待验收', blockers: ['本期要求验收通过'] },
  { name: '全部到货并验收通过 + 全部通过 -> 可提交', trigger: '全部到货并验收通过', lines: () => [passed(), passed()], status: '可提交付款审批', blockers: [] },
  { name: '仅验收 + 没到 -> 待到货资料（验收前需全部到货含“到货”）', trigger: '验收通过', lines: () => [passed(), line()], status: '待到货资料', blockers: ['验收前需全部到货', '本期要求验收通过'] },
  { name: '仅验收 + 到齐、换货中 -> 待验收', trigger: '验收通过', lines: () => [passed(), exchanging()], status: '待验收', blockers: ['本期要求验收通过'] },
  { name: '仅验收 + 全部通过 -> 可提交', trigger: '验收通过', lines: () => [passed()], status: '可提交付款审批', blockers: [] },
  { name: '空 PO（没有物料）+ 到货条件 -> 不满足', trigger: '到货', lines: () => [], status: '待到货资料', blockers: ['本期要求全部到货'] },
];
for (const c of GATE_CASES) {
  test(`gate: ${c.name}`, () => {
    const row = item(c.lines(), { trigger_condition: c.trigger, contract_status: c.contract || '已生效', po_status: c.po_status || '供应商制作中' });
    const ev = evaluateItem(row);
    assert.deepEqual(ev.blockers, c.blockers);
    assert.equal(ev.status, c.status);
    // 同一套规则：直接用纯函数算也是一样
    const blockers = paymentBlockers({ contractOk: ev.contractOk, trigger: c.trigger, summary: summarizeLines(row.lines) });
    assert.deepEqual(blockers, c.blockers);
  });
}

test('the gate is all-or-nothing across the PO and independent of the installment percentage', () => {
  for (const percentage of [1, 30, 70, 100]) {
    const ev = evaluateItem(item([received(), line()], { trigger_condition: '全部到货', percentage }));
    assert.equal(ev.status, '待到货资料', `percentage ${percentage}`);
  }
});

test('contractReady mirrors the server rule', () => {
  assert.equal(contractReady({ contract_status: '已生效', po_status: '供应商制作中' }), true);
  assert.equal(contractReady({ contract_status: '已生效', po_status: '付款中' }), true);
  assert.equal(contractReady({ contract_status: '已生效', po_status: '待电子用印' }), false);
  assert.equal(contractReady({ contract_status: '已生效', po_status: '已取消' }), false);
  assert.equal(contractReady({ contract_status: '待复核', po_status: '供应商制作中' }), false);
  assert.equal(contractReady({ contract_ready: 1, contract_status: '' }), true);
  assert.equal(contractReady({ contract_ready: 0, contract_status: '已生效', po_status: '供应商制作中' }), false);
});

test('work status: paid, in flight (step label decides), blockers, ready', () => {
  const base = { paid: false, paymentRequest: '', requestSummary: {}, blockers: [], contractOk: true };
  const rows = [
    [{ paid: true, paymentRequest: 'OA1' }, '已付款'],
    [{ paymentRequest: 'OA1', requestSummary: { current_step_label: '财务主管：张' } }, '付款审批中'],
    [{ paymentRequest: 'OA1', requestSummary: { current_step_label: '副总经理：李' } }, '付款审批中'],
    [{ paymentRequest: 'OA1', requestSummary: { current_step_label: '总经理付款：王' } }, '待实际付款'],
    [{ paymentRequest: 'OA1', requestSummary: { current_step_label: '', workflow_status: '已通过' } }, '待实际付款'],
    [{ paymentRequest: 'OA1', requestSummary: { current_step_label: '出纳', workflow_status: '待审批' } }, '付款审批中'],
    [{ blockers: ['PO 合同尚未生效'], contractOk: false }, '待合同生效'],
    [{ blockers: ['本期要求全部到货'] }, '待到货资料'],
    [{ blockers: ['验收前需全部到货', '本期要求验收通过'] }, '待到货资料'],
    [{ blockers: ['本期要求验收通过'] }, '待验收'],
    [{}, '可提交付款审批'],
  ];
  for (const [over, status] of rows) assert.equal(computeWorkStatus({ ...base, ...over }), status, JSON.stringify(over));
  // 审批已发起时，即使条件现在不满足，状态仍是审批中（只会出现“条件已回退”提醒）
  assert.equal(computeWorkStatus({ ...base, paymentRequest: 'OA1', blockers: ['本期要求全部到货'], requestSummary: { current_step_label: '财务主管' } }), '付款审批中');
});

test('server work_status and blockers are authoritative when present', () => {
  const row = item([line()], { trigger_condition: '全部到货', work_status: '待验收', blockers: ['服务端的原话'] });
  const ev = evaluateItem(row);
  assert.equal(ev.status, '待验收');
  assert.deepEqual(ev.blockers, ['服务端的原话']);
});

test('paid installments are recognised from status or amounts', () => {
  assert.equal(evaluateItem(item([passed()], { status: '已付款' })).status, '已付款');
  assert.equal(evaluateItem(item([passed()], { amount: 600, paid_amount: 600 })).status, '已付款');
  assert.equal(evaluateItem(item([passed()], { amount: 600, paid_amount: 100 })).status, '可提交付款审批');
});

// ------------------------------------------------------------------ 审批中条件回退
test('in-flight regression: only when an OA exists and blockers reappear', () => {
  const inflight = { trigger_condition: '全部到货并验收通过', payment_request: 'OA9', payment_request_summary: { current_step_label: '财务主管：x' } };
  const okLines = () => [passed(), passed()];
  assert.equal(conditionsRegressed(item(okLines(), inflight)), false);
  // 又登记了新的到货：新到的物料验收结果重置为待验收
  const regressed = item([passed(), received()], inflight);
  assert.equal(evaluateItem(regressed).status, '付款审批中');
  assert.equal(conditionsRegressed(regressed), true);
  // 验收结果变成换货 / 退货
  assert.equal(conditionsRegressed(item([passed(), exchanging()], inflight)), true);
  assert.equal(conditionsRegressed(item([passed(), returning()], inflight)), true);
  // 退货发出后到货数量清零
  assert.equal(conditionsRegressed(item([passed(), line({ inspection_status: '未验收' })], inflight)), true);
  // 没有发起审批时不是“回退”，只是普通阻塞
  assert.equal(conditionsRegressed(item([passed(), received()], { trigger_condition: '验收通过' })), false);
  // 服务端标记优先
  assert.equal(conditionsRegressed(item(okLines(), { ...inflight, conditions_regressed: 1 })), true);
  assert.equal(conditionsRegressed(item([passed(), received()], { ...inflight, conditions_regressed: 0 })), false);
});

test('installmentView surfaces the regression warning, draft link and push gating', () => {
  const inflightRow = item([passed(), exchanging()], {
    trigger_condition: '验收通过', payment_request: 'OA9', payment_request_summary: { current_step_label: '出纳：x' }, can_push_payment: 0,
  });
  const view = installmentView(inflightRow, null, { canPurchase: true });
  assert.equal(view.status, '付款审批中');
  assert.equal(view.regressed, true);
  assert.match(view.regressionText, /审批过程中条件已回退/);
  assert.match(view.regressionText, /本期要求验收通过/);
  assert.equal(view.canPush, false);
  assert.equal(view.paymentRequest, 'OA9');
  assert.equal(view.waitFor, '审批中：出纳：x');

  // 被退回的草稿：状态是“可提交”，但不给提交按钮，只给草稿链接
  const draftRow = item([received()], { trigger_condition: '到货', draft_request: 'OA-DRAFT', can_push_payment: 1 });
  const draftView = installmentView(draftRow, null, { canPurchase: true });
  assert.equal(draftView.status, '可提交付款审批');
  assert.equal(draftView.canPush, false);
  assert.equal(draftView.draft, 'OA-DRAFT');
  assert.equal(draftView.draftText, '已退回，存在草稿 OA-DRAFT');

  // 能提交：采购 + 无阻塞 + 无审批 + 无草稿
  const readyView = installmentView(item([received()], { trigger_condition: '到货', can_push_payment: 1 }), null, { canPurchase: true });
  assert.equal(readyView.canPush, true);
  assert.equal(readyView.waitFor, '');
  // 服务端说不能提交就不能
  assert.equal(installmentView(item([received()], { trigger_condition: '到货', can_push_payment: 0 }), null, { canPurchase: true }).canPush, false);
  // 旧服务端没有 can_push_payment：按角色 + 状态判断
  assert.equal(installmentView(item([received()], { trigger_condition: '到货' }), null, { canPurchase: true }).canPush, true);
  assert.equal(installmentView(item([received()], { trigger_condition: '到货' }), null, { canPurchase: false }).canPush, false);
  // 非采购看到“等采购提交付款审批”
  assert.equal(installmentView(item([received()], { trigger_condition: '到货', can_push_payment: 0 }), null).waitFor, '等采购提交付款审批');
});

// ------------------------------------------------------------------ 在等谁
test('waiting-for text follows who has to act next', () => {
  const sum = (lines) => summarizeLines(lines);
  const rows = [
    [{ status: '待合同生效', summary: sum([line()]) }, '等 PO 合同电子用印生效'],
    [{ status: '待到货资料', summary: sum([line()]) }, '等生产主管登记到货'],
    [{ status: '待到货资料', summary: sum([line(), exchanging()]) }, '等供应商换货到货'],
    [{ status: '待到货资料', summary: sum([line(), returning()]) }, '等退货发出 / 供应商补发'],
    [{ status: '待到货资料', summary: sum([exchanging(), returning()]) }, '等退货发出 / 供应商补发'],
    [{ status: '待验收', summary: sum([received(), received()]) }, '等生产主管登记验收'],
    [{ status: '待验收', summary: sum([passed(), exchanging()]) }, '等供应商换货到货'],
    [{ status: '待验收', summary: sum([passed(), returning()]) }, '等退货发出 / 供应商补发'],
    [{ status: '可提交付款审批', summary: sum([passed()]), canPush: false }, '等采购提交付款审批'],
    [{ status: '可提交付款审批', summary: sum([passed()]), canPush: true }, ''],
    [{ status: '可提交付款审批', summary: sum([passed()]), draft: 'OA1' }, ''],
    [{ status: '付款审批中', summary: sum([passed()]), requestSummary: { current_step_label: '总账会计：x' } }, '审批中：总账会计：x'],
    [{ status: '待实际付款', summary: sum([passed()]), requestSummary: { current_step_label: '总经理付款：x' } }, '等 总经理付款：x'],
    [{ status: '已付款', summary: sum([passed()]) }, ''],
  ];
  for (const [input, text] of rows) assert.equal(waitingFor(input), text, JSON.stringify(input.status));
});

test('gate tiles: contract, receipt, inspection and invoice with their states', () => {
  const summary = summarizeLines([passed(), received(), line()]);
  const tiles = gateTiles({ contractOk: true, trigger: '全部到货并验收通过', summary, invoiceRequirement: '付款前提供', invoiceDocs: 0 });
  assert.deepEqual(tiles.map((t) => t.key), ['contract', 'receipt', 'inspection', 'invoice']);
  assert.deepEqual(tiles.map((t) => t.state), [1, 0, 0, 0]);
  assert.equal(tiles[1].v, '还差 1 项未到齐');
  assert.equal(tiles[2].v, '须先全部到货');
  assert.equal(tiles[3].v, '付款前须上传发票');

  const done = gateTiles({ contractOk: true, trigger: '全部到货并验收通过', summary: summarizeLines([passed(), passed()]), invoiceRequirement: '付款前提供', invoiceDocs: 2 });
  assert.deepEqual(done.map((t) => t.state), [1, 1, 1, 1]);
  assert.equal(done[1].v, '已满足（2/2 项）');
  assert.equal(done[3].v, '已上传 2 份');

  const notRequired = gateTiles({ contractOk: true, trigger: '合同生效', summary: summarizeLines([passed(), received()]), invoiceRequirement: '付款后提供', invoiceDocs: 0 });
  assert.deepEqual(notRequired.map((t) => t.state), [1, -1, -1, -1]);
  assert.equal(notRequired[1].v, '本期不要求');
  assert.equal(notRequired[2].v, '本期不要求（已通过 1/2）');
  assert.equal(notRequired[3].v, '付款后提供，现在不用');

  const exchange = gateTiles({ contractOk: false, trigger: '验收通过', summary: summarizeLines([passed(), exchanging()]) });
  assert.equal(exchange[0].state, 0);
  assert.equal(exchange[2].v, '还有 1 项未通过');
  // 工作项卡片里没有文件列表，发票只做提示
  assert.deepEqual(exchange[3], { key: 'invoice', k: '发票要求', v: '未约定', state: -1 });
});

// ------------------------------------------------------------------ 按 PO 分组 / 过滤
const worldItems = () => {
  const a = [passed(), received(), exchanging()];
  const b = [line(), line()];
  const c = [passed()];
  return [
    item(a, { po: 'PO-A', key: 'PO-A:R1', payment_plan_row: 'R1', installment_no: 1, installment_name: '第1期', trigger_condition: '合同生效', can_record_inspection: 1, can_record_receipt: 0, can_record_exchange: 1, can_record_return: 0 }),
    item(a, { po: 'PO-A', key: 'PO-A:R2', payment_plan_row: 'R2', installment_no: 2, installment_name: '第2期', payment_stage: '尾款', trigger_condition: '全部到货并验收通过' }),
    item(b, { po: 'PO-B', key: 'PO-B:R1', payment_plan_row: 'R1', supplier: '供应商乙', trigger_condition: '合同生效', can_push_payment: 1 }),
    item(c, { po: 'PO-C', key: 'PO-C:R1', payment_plan_row: 'R1', supplier: '供应商丙', po_status: '已关闭', trigger_condition: '到货', status: '已付款', paid_amount: 600, amount: 600 }),
  ];
};

test('buildPoGroups groups installments per PO and summarises the PO', () => {
  const groups = buildPoGroups(worldItems());
  assert.deepEqual(groups.map((g) => g.po), ['PO-A', 'PO-B', 'PO-C']);
  const a = groups[0];
  assert.equal(a.items.length, 2);
  assert.equal(a.summary.recvN, 3);
  assert.equal(a.summary.inspN, 1);
  assert.equal(a.total, 3000);
  assert.deepEqual(a.statuses, ['可提交付款审批', '待验收']);
  assert.equal(a.openCount, 2);
  assert.equal(a.flags.inspect, true);
  assert.equal(a.flags.receipt, false);
  assert.equal(a.flags.exchange, true);
  assert.equal(groups[1].canPushAny, true);
  assert.equal(groups[1].flags.receipt, null);
  assert.equal(groups[2].openCount, 0);
  assert.equal(groups[2].paid, 600);
});

test('status chips count installments; filter and search work on PO level', () => {
  const items = worldItems();
  const counts = statusCounts(items);
  assert.equal(counts.all, 4);
  assert.equal(counts.unfinished, 3);
  assert.equal(counts.counts['可提交付款审批'], 2);
  assert.equal(counts.counts['待验收'], 1);
  assert.equal(counts.counts['已付款'], 1);
  const groups = buildPoGroups(items);
  assert.deepEqual(filterGroups(groups, '未完成', '').map((g) => g.po), ['PO-A', 'PO-B']);
  assert.deepEqual(filterGroups(groups, '全部', '').map((g) => g.po), ['PO-A', 'PO-B', 'PO-C']);
  assert.deepEqual(filterGroups(groups, '待验收', '').map((g) => g.po), ['PO-A']);
  assert.deepEqual(filterGroups(groups, '可提交付款审批', '').map((g) => g.po), ['PO-A', 'PO-B']);
  assert.deepEqual(filterGroups(groups, '全部', '供应商丙').map((g) => g.po), ['PO-C']);
  assert.deepEqual(filterGroups(groups, '全部', 'po-b').map((g) => g.po), ['PO-B']);
  assert.deepEqual(filterGroups(groups, '全部', '尾款').map((g) => g.po), ['PO-A']);
  assert.deepEqual(filterGroups(groups, '全部', '不存在'), []);
  for (const status of WORK_STATUSES) assert.ok(STATUS_FILTERS.includes(status));
  assert.deepEqual(STATUS_FILTERS.slice(0, 2), ['未完成', '全部']);
});

test('POs with something to do come first', () => {
  const groups = buildPoGroups(worldItems());
  const order = sortGroups(groups, { canFulfil: false }).map((g) => g.po);
  assert.equal(order[0], 'PO-B'); // 采购能提交
  const prod = sortGroups(groups, { canFulfil: true }).map((g) => g.po);
  assert.deepEqual(prod.slice(0, 2).sort(), ['PO-A', 'PO-B']);
  assert.equal(prod[2], 'PO-C');
});

// ------------------------------------------------------------------ 登记模式的可用性
const groupOf = (lines, over = {}) => buildPoGroups([item(lines, over)])[0];

test('registration modes depend on role, PO status, server flags and the lines', () => {
  const modeKeys = (group, canFulfil = true) => fulfilmentModes(group, { canFulfil }).map((m) => m.key);
  assert.deepEqual(modeKeys(groupOf([line(), line()])), ['arrive']);
  assert.deepEqual(modeKeys(groupOf([received(), received()])), ['inspect']);
  assert.deepEqual(modeKeys(groupOf([received(), line()])), ['arrive', 'inspect']);
  assert.deepEqual(modeKeys(groupOf([passed(), passed()])), []);
  assert.deepEqual(modeKeys(groupOf([passed(), exchanging()])), ['exchange']);
  assert.deepEqual(modeKeys(groupOf([passed(), returning()])), ['return']);
  assert.deepEqual(modeKeys(groupOf([received(), exchanging(), returning(), line()])), ['arrive', 'inspect', 'exchange', 'return']);
  // 退货发出之后这一行已到数量清零，回到“登记到货”
  assert.deepEqual(modeKeys(groupOf([passed(), line({ inspection_status: '未验收' })])), ['arrive']);
  // 角色
  assert.deepEqual(modeKeys(groupOf([line()]), false), []);
  // PO 状态：付款中也能登记验收 / 换货 / 退货；已关闭 / 待合同 不行
  assert.deepEqual(modeKeys(groupOf([received()], { po_status: '付款中' })), ['inspect']);
  assert.deepEqual(modeKeys(groupOf([line()], { po_status: '已关闭' })), []);
  assert.deepEqual(modeKeys(groupOf([line()], { po_status: '待电子用印' })), []);
  // 服务端标记为 0 的登记不显示
  assert.deepEqual(modeKeys(groupOf([received(), line()], { can_record_inspection: 0, can_record_receipt: 1 })), ['arrive']);
  assert.deepEqual(modeKeys(groupOf([exchanging()], { can_record_exchange: 0 })), []);
  assert.equal(fulfilmentModes(groupOf([line()]), { canFulfil: true })[0].label, '登记到货');
  assert.deepEqual(fulfilmentModes(null, { canFulfil: true }), []);
});

test('pickMode keeps the selection while it stays available', () => {
  const modes = [{ key: 'arrive' }, { key: 'inspect' }];
  assert.equal(pickMode(modes, 'inspect'), 'inspect');
  assert.equal(pickMode(modes, 'return'), 'arrive');
  assert.equal(pickMode([], 'arrive'), '');
});

test('eligible lines per mode and default quantities', () => {
  const lines = [line({ name: 'new' }), received({ name: 'wait' }), passed({ name: 'ok' }), exchanging({ name: 'ex' }), returning({ name: 'rt' }), received({ name: 'part', received_quantity: 4 })];
  const names = (mode) => eligibleLines(mode, lines).map((l) => l.name);
  assert.deepEqual(names('arrive'), ['new', 'part']);
  assert.deepEqual(names('inspect'), ['wait', 'part']);
  assert.deepEqual(names('exchange'), ['ex']);
  assert.deepEqual(names('return'), ['rt']);
  assert.equal(defaultQuantity('arrive', lines[0]), 10);
  assert.equal(defaultQuantity('arrive', lines[5]), 6);
  assert.equal(defaultQuantity('exchange', lines[3]), 10);
  assert.equal(defaultQuantity('return', lines[4]), 10);
});

// ------------------------------------------------------------------ 登记表单校验
const meta = { date: '2026-10-01', fileRef: 'FILE-1' };

test('arrival form: defaults to the remaining quantity and blocks partial delivery', () => {
  const group = groupOf([line({ name: 'A', quantity: 20 }), line({ name: 'B', quantity: 5 })]);
  // 不改数量：每行按剩余数量登记
  const ok = validateFulfilment('arrive', group, {}, meta);
  assert.equal(ok.error, '');
  assert.deepEqual(ok.lines, [{ line: 'A', quantity: 20 }, { line: 'B', quantity: 5 }]);
  // 留空 / 0 = 这行本次不登记
  assert.deepEqual(validateFulfilment('arrive', group, { A: '', B: '5' }, meta).lines, [{ line: 'B', quantity: 5 }]);
  assert.deepEqual(validateFulfilment('arrive', group, { A: 0 }, meta).lines.map((l) => l.line), ['B']);
  // 分批到货不支持
  assert.match(validateFulfilment('arrive', group, { A: '10' }, meta).error, /暂不支持分批到货/);
  // 超过未到数量
  assert.match(validateFulfilment('arrive', group, { A: '21' }, meta).error, /不能超过未到数量/);
  // 负数 / 非数字
  assert.match(validateFulfilment('arrive', group, { A: '-1' }, meta).error, /大于 0 的数字/);
  assert.match(validateFulfilment('arrive', group, { A: 'abc' }, meta).error, /大于 0 的数字/);
  // 全部留空
  assert.match(validateFulfilment('arrive', group, { A: '', B: '' }, meta).error, /至少一项本次到货数量/);
  // 日期 / 文件
  assert.match(validateFulfilment('arrive', group, {}, { ...meta, date: '' }).error, /请填写到货日期/);
  assert.match(validateFulfilment('arrive', group, {}, { ...meta, fileRef: '' }).error, /请上传送货单/);
  // 旧数据里已经到了一部分：剩余数量一次到齐
  const legacy = groupOf([line({ name: 'P', quantity: 10, received_quantity: 4, inspection_status: '待验收' })]);
  assert.deepEqual(validateFulfilment('arrive', legacy, {}, meta).lines, [{ line: 'P', quantity: 6 }]);
});

test('inspection form: every picked line needs a status; 换货 / 退货 need a reason', () => {
  const group = groupOf([received({ name: 'A' }), received({ name: 'B' }), passed({ name: 'C' })]);
  assert.match(validateFulfilment('inspect', group, {}, meta).error, /至少选择一项验收结果/);
  const good = validateFulfilment('inspect', group, { A: { result: '已通过' }, B: { result: '换货中', reason: '  插损超标 ' } }, meta);
  assert.equal(good.error, '');
  assert.deepEqual(good.lines, [{ line: 'A', status: '已通过', reason: '' }, { line: 'B', status: '换货中', reason: '插损超标' }]);
  assert.match(validateFulfilment('inspect', group, { A: { result: '退货中', reason: '' } }, meta).error, /必须填写原因/);
  assert.match(validateFulfilment('inspect', group, { A: { result: '换货中' } }, meta).error, /必须填写原因/);
  assert.match(validateFulfilment('inspect', group, { A: { result: '乱写' } }, meta).error, /验收结果无效/);
  // 已通过的行不在可选范围内
  assert.deepEqual(validateFulfilment('inspect', group, { C: { result: '退货中', reason: 'x' } }, meta).lines, []);
  assert.match(validateFulfilment('inspect', group, { A: { result: '已通过' } }, { ...meta, date: '' }).error, /请填写验收日期/);
  assert.match(validateFulfilment('inspect', group, { A: { result: '已通过' } }, { ...meta, fileRef: '' }).error, /请上传验收记录/);
  assert.deepEqual(INSPECT_CHOICES.map((c) => c.value), ['已通过', '换货中', '退货中']);
});

test('exchange and return forms default to the received quantity and cannot exceed it', () => {
  const ex = groupOf([exchanging({ name: 'E', received_quantity: 8, quantity: 10 }), passed()]);
  assert.deepEqual(validateFulfilment('exchange', ex, {}, meta).lines, [{ line: 'E', quantity: 8 }]);
  assert.deepEqual(validateFulfilment('exchange', ex, { E: '5' }, meta).lines, [{ line: 'E', quantity: 5 }]);
  assert.match(validateFulfilment('exchange', ex, { E: '9' }, meta).error, /不能超过已到数量/);
  assert.match(validateFulfilment('exchange', ex, { E: '' }, meta).error, /至少一项/);
  assert.match(validateFulfilment('exchange', ex, {}, { ...meta, fileRef: '' }).error, /请上传换货送货单/);
  const rt = groupOf([returning({ name: 'R' }), passed()]);
  assert.deepEqual(validateFulfilment('return', rt, {}, meta).lines, [{ line: 'R', quantity: 10 }]);
  assert.match(validateFulfilment('return', rt, { R: '11' }, meta).error, /不能超过已到数量/);
  assert.match(validateFulfilment('return', rt, {}, { ...meta, date: '' }).error, /请填写退货日期/);
  assert.match(validateFulfilment('return', rt, {}, { ...meta, fileRef: '' }).error, /请上传退货单/);
});

test('request payloads use the endpoint contract (names, date params, JSON lines)', () => {
  const lines = [{ line: 'A', quantity: 3 }];
  assert.deepEqual(buildFulfilmentRequest('arrive', 'PO1', lines, { ...meta, note: '' }), {
    method: 'record_po_receipt', params: { name: 'PO1', lines: JSON.stringify(lines), arrival_date: '2026-10-01', file_ref: 'FILE-1' },
  });
  const inspect = buildFulfilmentRequest('inspect', 'PO1', [{ line: 'A', status: '换货中', reason: 'x' }], { ...meta, note: '备注' });
  assert.equal(inspect.method, 'record_po_inspection');
  assert.equal(inspect.params.inspection_date, '2026-10-01');
  assert.equal(inspect.params.note, '备注');
  assert.equal(JSON.parse(inspect.params.lines)[0].reason, 'x');
  const exchange = buildFulfilmentRequest('exchange', 'PO1', lines, meta);
  assert.equal(exchange.method, 'record_po_exchange_receipt');
  assert.equal(exchange.params.arrival_date, '2026-10-01');
  const ret = buildFulfilmentRequest('return', 'PO1', lines, meta);
  assert.equal(ret.method, 'record_po_return');
  assert.equal(ret.params.return_date, '2026-10-01');
  assert.equal('arrival_date' in ret.params, false);
  assert.match(MODE_CONFIG.return.warn, new RegExp(REFUND_NOTICE));
  assert.equal(REFUND_NOTICE, '退款需线下与供应商、财务处理，系统暂不记录');
});

test('role notes explain why there is no registration form', () => {
  assert.equal(fulfilmentRoleNote({ canFulfil: true, modeCount: 2 }), '');
  assert.match(fulfilmentRoleNote({ canFulfil: true, modeCount: 0, poStatus: '已关闭' }), /已关闭/);
  assert.match(fulfilmentRoleNote({ canFulfil: true, modeCount: 0, poStatus: '付款中' }), /没有需要登记/);
  assert.match(fulfilmentRoleNote({ canFulfil: false, canPurchase: true }), /到货和验收由生产主管登记/);
  assert.match(fulfilmentRoleNote({ canFulfil: false, canPurchase: true }), /提交付款审批/);
  assert.match(fulfilmentRoleNote({ canFulfil: false, canPurchase: false }), /只能查看/);
});

// ------------------------------------------------------------------ 履约记录
const records = () => [
  { name: 'R3', record_type: '退货', record_date: '2026-09-30', creation: '2026-09-30 10:00:00', details: [{ line: 'L-R', item_name: '线材', quantity: 5, unit: '米' }] },
  { name: 'R2', record_type: '验收', record_date: '2026-09-27', creation: '2026-09-27 09:00:00', details_json: JSON.stringify([{ line: 'L-R', item_name: '线材', status: '退货中', reason: '损坏' }, { line: 'L-E', item_name: '耦合头', status: '换货中', reason: '插损超标' }, { line: 'L-OK', item_name: '夹具', status: '已通过' }]) },
  { name: 'R1', record_type: '到货', record_date: '2026-09-26', creation: '2026-09-26 09:00:00', details_json: '[{"line":"L-R","item_name":"线材","quantity":5,"unit":"米"}]' },
];

test('record details are built from the structured data in the record', () => {
  const rows = normalizeRecords(records());
  assert.equal(rows[1].details.length, 3);
  assert.equal(recordDetailText(rows[0]), '线材 5 米');
  assert.equal(recordDetailText(rows[1]), '线材：退货（损坏）；耦合头：换货（插损超标）；夹具：已通过');
  assert.equal(recordDetailText(rows[2]), '线材 5 米');
  assert.equal(recordDetailText({ record_type: '到货', details: [] }), '');
});

test('the reason chip comes from the latest 验收 record of the line', () => {
  const rows = records();
  assert.equal(latestInspectionReason(rows, 'L-E'), '插损超标');
  assert.equal(latestInspectionReason(rows, 'L-OK'), '');
  assert.equal(latestInspectionReason(rows, 'nope'), '');
  // 后来又有一次验收把原因改了：以最新的为准（不看数组顺序，看 creation）
  const newer = [...rows, { name: 'R4', record_type: '验收', creation: '2026-10-01 08:00:00', details: [{ line: 'L-E', status: '换货中', reason: '外观划伤' }] }];
  assert.equal(latestInspectionReason(newer, 'L-E'), '外观划伤');
  assert.deepEqual(sortRecordsDesc(newer).map((r) => r.name), ['R4', 'R3', 'R2', 'R1']);
  // 提示：有原因给原因；没有原因时，只读的人看到“等谁登记”
  const ex = exchanging({ name: 'L-E' });
  assert.equal(lineHint(ex, rows, true), '插损超标');
  assert.equal(lineHint(exchanging({ name: 'x' }), rows, true), '');
  assert.equal(lineHint(exchanging({ name: 'x' }), rows, false), '等生产主管登记换货到货');
  assert.equal(lineHint(returning({ name: 'x' }), rows, false), '等生产主管登记退货发出');
  assert.equal(lineHint(passed({ name: 'L-OK' }), rows, false), '');
});

// ------------------------------------------------------------------ 审批单
test('approve button: 审批通过 / 办理完成 / 确认付款 (总经理付款 handle step)', () => {
  const steps = [
    { step_index: 1, label: '副总经理：甲', mode: 'approve', step_key: 'k1' },
    { step_index: 4, label: '出纳：乙', mode: 'approve', step_key: 'k4' },
    { step_index: 5, label: '总经理付款：丙', mode: 'handle', step_key: 'k5' },
    { step_index: 6, label: '其他办理', mode: 'handle', step_key: 'k6' },
  ];
  const at = (i) => ({ steps, current_step_index: i });
  assert.equal(approveLabel(at(1)), '审批通过');
  assert.equal(approveLabel(at(4)), '审批通过');
  assert.equal(approveLabel(at(5)), '确认付款');
  assert.equal(approveLabel(at(6)), '办理完成');
  assert.equal(isFinalPayStep(at(5)), true);
  assert.equal(isFinalPayStep(at(1)), false);
  assert.equal(currentStepKey(at(5)), 'k5');
  assert.equal(currentStepKey({ steps: [], current_step_key: 'zz' }), 'zz');
  assert.equal(approveLabel({ steps: [], current_step_label: '总经理付款', current_step_mode: 'handle' }), '确认付款');
});

test('directed reject: targets, default, and the required reason', () => {
  const request = { rejection_targets: [{ target: 'applicant', label: '申请人' }, { target: 'step:1', label: '副总经理' }, { target: 'step:2' }] };
  assert.deepEqual(rejectionTargets(request).map((t) => t.label), ['申请人', '副总经理', 'step:2']);
  assert.equal(defaultRejectTarget(request), 'applicant');
  assert.equal(defaultRejectTarget({ rejection_targets: [{ target: 'step:3', label: 'x' }] }), 'step:3');
  assert.equal(defaultRejectTarget({}), 'applicant');
  assert.match(validateReject({ reason: '  ', target: 'applicant' }), /必须填写原因/);
  assert.equal(validateReject({ reason: '金额不对', target: 'step:1' }), '');
  assert.match(validateReject({ reason: 'x', target: '' }), /请选择驳回到哪里/);
});

test('the five steps render as done / now / todo, and a draft shows none as current', () => {
  const steps = [
    { step_index: 1, label: '副总经理', status: '已通过', action_by: '甲', acted_on: '2026-09-30 09:40:00', mode: 'approve' },
    { step_index: 2, label: '总账会计', status: '已审批', mode: 'approve' },
    { step_index: 3, label: '财务主管', status: '待审批', mode: 'approve' },
    { step_index: 4, label: '出纳', status: '', mode: 'approve' },
    { step_index: 5, label: '总经理付款', status: '', mode: 'handle' },
  ];
  const rows = stepRows({ steps, current_step_index: 3, workflow_status: '待审批' });
  assert.deepEqual(rows.map((r) => r.state), ['done', 'done', 'now', 'todo', 'todo']);
  assert.equal(rows[0].sub, '已通过 · 甲 · 2026-09-30 09:40');
  assert.equal(rows[2].sub, '待审批');
  assert.equal(rows[4].sub, '未开始');
  const final = stepRows({ steps: steps.map((s, i) => (i < 4 ? { ...s, status: '已通过' } : s)), current_step_index: 5, workflow_status: '待办理' });
  assert.equal(final[4].state, 'now');
  assert.equal(final[4].sub, '待办理');
  const draft = stepRows({ steps, current_step_index: 3, workflow_status: '草稿' });
  assert.ok(draft.every((r) => r.state !== 'now'));
  const rejected = stepRows({ steps: [{ step_index: 1, label: 'a', status: '已拒绝', note: '金额不对' }], current_step_index: 1, workflow_status: '已驳回' });
  assert.equal(rejected[0].state, 'rejected');
  assert.equal(rejected[0].note, '金额不对');
});

test('document checklist for PO payments: only the invoice, only when it must come first', () => {
  const none = poPaymentChecklist([], '');
  assert.deepEqual(none, []);
  const before = poPaymentChecklist([], '付款前提供');
  assert.equal(before.length, 1);
  assert.equal(before[0].key, 'invoice');
  assert.equal(before[0].required, true);
  assert.equal(before[0].satisfied, false);
  assert.equal(before[0].state, '待补资料');
  assert.deepEqual(before[0].uploadTypes, ['发票']);
  // 没有报价 / 合同 / 到货 / 验收 这些旧条目
  assert.ok(!before.some((c) => ['quote', 'contract', 'arrival', 'inspection'].includes(c.key)));
  const uploaded = poPaymentChecklist([{ name: 'D1', document_type: '发票', version_no: 1, status: '有效' }], '付款前提供');
  assert.equal(uploaded[0].satisfied, true);
  assert.equal(uploaded[0].state, '已满足');
  // 作废的发票不算
  const voided = poPaymentChecklist([{ name: 'D1', document_type: '发票', version_no: 1, status: '已作废' }], '付款前提供');
  assert.equal(voided[0].satisfied, false);
  const after = poPaymentChecklist([], '付款后提供');
  assert.equal(after[0].required, false);
  assert.equal(after[0].state, '付款后提供');
  assert.equal(invoiceDocCount([{ document_type: '发票', status: '有效' }, { document_type: '发票', status: '已作废' }, { document_type: '其他补充资料', status: '有效' }]), 1);
  assert.deepEqual(activeDocumentTypes([{ document_type: '发票', status: '有效', version_no: 1 }, { document_type: '送货单', status: '已作废', version_no: 1 }]), ['发票']);
});

test('removing a document needs a reason once the approval started', () => {
  assert.match(validateRemoveReason({ workflow_status: '待审批' }, ''), /请填写作废原因/);
  assert.equal(validateRemoveReason({ workflow_status: '待审批' }, '传错了'), '');
  assert.equal(validateRemoveReason({ workflow_status: '草稿' }, ''), '');
});

const payRequest = (over = {}) => ({
  name: 'OA-1', request_type: '采购付款', source_purchase_order: 'PO-A', source_po_payment_plan_row: 'R2', workflow_status: '待办理',
  current_step_index: 5, steps: [{ step_index: 5, label: '总经理付款', mode: 'handle', step_key: 'k5' }], ...over,
});

test('live review finds the work item of the OA and recomputes the gates with the invoice documents', () => {
  const items = worldItems();
  const groups = buildPoGroups(items);
  const request = payRequest();
  assert.equal(findWorkItem(items, request).installment_name, '第2期');
  const review = liveReview(request, items, groups, []);
  assert.equal(review.available, true);
  assert.equal(review.group.po, 'PO-A');
  assert.deepEqual(review.blockers, ['本期要求验收通过']);
  assert.deepEqual(review.tiles.map((t) => t.state), [1, 1, 0, -1]);
  // 条件复核里发票也一起看
  const invoiceItems = items.map((i) => (i.payment_plan_row === 'R2' ? { ...i, invoice_requirement: '付款前提供' } : i));
  const withInvoice = liveReview(request, invoiceItems, buildPoGroups(invoiceItems), [{ document_type: '发票', status: '有效' }]);
  assert.equal(withInvoice.tiles[3].state, 1);
  // 找不到工作项（比如没有 PO 查看权限）
  const missing = liveReview(payRequest({ source_po_payment_plan_row: 'zzz', name: 'OA-2' }), items, groups, []);
  assert.equal(missing.available, false);
  // 兜底：用付款单名字匹配
  const byName = items.map((i) => (i.payment_plan_row === 'R1' && i.po === 'PO-B' ? { ...i, payment_request: 'OA-77' } : i));
  assert.equal(findWorkItem(byName, { name: 'OA-77', source_purchase_order: '', source_po_payment_plan_row: '' }).po, 'PO-B');
});

test('banner tells the approver what is blocking the final payment step', () => {
  const blocked = { available: true, blockers: ['本期要求验收通过'] };
  const clear = { available: true, blockers: [] };
  assert.equal(approvalBanner({ workflow_status: '草稿' }).tone, 'warn');
  assert.match(approvalBanner({ workflow_status: '草稿' }).text, /草稿/);
  assert.equal(approvalBanner(payRequest(), { canAct: true, finalPay: true, review: clear }).tone, 'act');
  const warn = approvalBanner(payRequest(), { canAct: true, finalPay: true, review: blocked });
  assert.equal(warn.tone, 'warn');
  assert.match(warn.text, /本期要求验收通过/);
  assert.equal(approvalBanner(payRequest(), { canAct: true, finalPay: false, review: blocked }).tone, 'warn');
  assert.equal(approvalBanner(payRequest({ can_withdraw: true })).tone, 'plain');
  assert.match(approvalBanner(payRequest({ can_withdraw: true })).text, /撤回/);
  assert.match(approvalBanner(payRequest()).text, /只读/);
});

test('PO lines and records on the approval page come from the PO, not the OA copy', () => {
  const groups = buildPoGroups(worldItems());
  const view = poLinesView(payRequest(), groups[0]);
  assert.equal(view.length, 3);
  assert.deepEqual(view.map((l) => l.state.label), ['已通过', '待验收', '换货中']);
  assert.equal(view[0].qty, '10 个');
  // 没有 PO 查看权限：只有 OA 上的明细，没有到货验收状态
  const fallback = poLinesView(payRequest({ business_lines: [{ item_name: 'x', specification: 's', quantity: 3, unit: '个', unit_price: 5 }] }), null);
  assert.equal(fallback[0].state, null);
  assert.equal(fallback[0].recv, '—');
  assert.equal(fallback[0].amount, 15);
  // 服务端另给了 PO 物料状态时直接用
  const given = poLinesView(payRequest({ po_lines: [{ name: 'q', item_name: 'y', quantity: 2, received_quantity: 2, inspection_status: '已通过', unit: '套', unit_price: 1 }] }), null);
  assert.equal(given[0].state.label, '已通过');
  // 记录：两种字段拼写都认，details_json 也认
  const own = requestRecords({ po_fulfilment_records: records() });
  assert.deepEqual(own.map((r) => r.name), ['R3', 'R2', 'R1']);
  assert.equal(requestRecords({ po_fulfillment_records: records() }).length, 3);
  assert.equal(requestRecords({}, { records: normalizeRecords(records()) }).length, 3);
  assert.equal(requestRecords({}, null).length, 0);
});

test('payment facts list the stage, ratio, source and plan', () => {
  const groups = buildPoGroups(worldItems());
  const row = worldItems()[1];
  const facts = Object.fromEntries(paymentFacts(payRequest({ payment_stage: '尾款', supplier: '供应商甲' }), row, groups[0]).map((f) => [f.k, f.v]));
  assert.equal(facts['付款阶段'], '尾款');
  assert.equal(facts['本期比例'], '30%');
  assert.equal(facts['来源类型'], 'PO付款下推');
  assert.equal(facts['来源 PO'], 'PO-A');
  assert.equal(facts['付款计划'], '预付款 30% / 尾款 30%');
  assert.equal(facts['供应商'], '供应商甲');
});

// ------------------------------------------------------------------ 旧数据流程
test('legacy lifecycle actions exist only for payments without a source PO', () => {
  const legacy = { name: 'OA-OLD', request_type: '采购付款', workflow_status: '已付款', payment_stage: '预付款', business_status: '待到货', arrival_status: '', inspection_status: '', prepayment_percentage: 100 };
  const docs = [{ document_type: '送货单', status: '有效', version_no: 1 }];
  const out = legacyActions(legacy, docs, { canManageExpense: true });
  assert.equal(out.show, true);
  assert.equal(out.arrival, true);
  assert.equal(out.followup, true);
  assert.equal(out.refund, false);
  // 来源 PO 的付款：一个都不给（服务端会拒绝）
  assert.deepEqual(legacyActions({ ...legacy, source_purchase_order: 'PO-A' }, docs, { canManageExpense: true }), { show: false });
  assert.equal(isPoSourced(legacy), false);
  assert.equal(isPoSourced({ source_purchase_order: 'PO-A' }), true);
  // 确认供应商退款只给财务
  const refundRow = { ...legacy, business_status: '退货中' };
  const refundDocs = [{ document_type: '退款回单', status: '有效', version_no: 1 }];
  assert.equal(legacyActions(refundRow, refundDocs, { canManageExpense: true }).refund, true);
  assert.equal(legacyActions(refundRow, refundDocs, { canManageExpense: false }).refund, false);
  // 没付款之前不显示
  assert.equal(legacyActions({ ...legacy, workflow_status: '待审批' }, docs).show, false);
  // 预付款核销 / 关闭采购沿用旧规则
  const closing = { ...legacy, inspection_status: '验收通过', prepayment_writeoff_status: '已核销', has_balance_payment: 0 };
  const closeDocs = ['发票', '验收资料', '采购完成报告'].map((t) => ({ document_type: t, status: '有效', version_no: 1 }));
  assert.equal(legacyActions(closing, closeDocs).close, true);
  assert.equal(legacyActions({ ...closing, source_purchase_order: 'PO-A' }, closeDocs).close, undefined);
});

// ------------------------------------------------------------------ 队列
test('the approval queue puts what needs me first and keeps server order otherwise', () => {
  const rows = [{ name: 'A' }, { name: 'B', can_approve: 1 }, { name: 'C' }, { name: 'D', can_reject: 1 }];
  assert.deepEqual(sortQueue(rows).map((r) => r.name), ['B', 'D', 'A', 'C']);
  assert.deepEqual(queueFilter(rows, 'todo').map((r) => r.name), ['B', 'D']);
  assert.equal(queueFilter(rows, 'all').length, 4);
  const mine = [{ name: 'A', employee: 'E1' }, { name: 'B', employee: 'E2' }];
  assert.deepEqual(queueFilter(mine, 'mine', { employee: 'E2' }).map((r) => r.name), ['B']);
});

test('waiting time text', () => {
  const now = Date.parse('2026-10-01T12:00:00');
  assert.equal(waitedDays({ creation: '2026-09-30 11:00:00' }, now), 1);
  assert.equal(waitedDays({ creation: '2026-10-01 09:00:00' }, now), 0);
  assert.equal(waitedDays({ steps: [{ acted_on: '2026-09-28 10:00:00' }], creation: '2026-09-01 10:00:00' }, now), 3);
  assert.equal(waitedDays({}, now), null);
  assert.equal(waitText(null), '—');
  assert.equal(waitText(0), '今天');
  assert.equal(waitText(3), '等了 3 天');
});

// ------------------------------------------------------------------ 格式
test('money, quantity and today formatting', () => {
  assert.equal(money(1234.5), '¥ 1,234.50');
  assert.equal(money(0), '¥ 0.00');
  assert.equal(money(10, 'USD'), 'USD 10.00');
  assert.equal(quantity(1.25), '1.25');
  assert.equal(quantity('20'), '20');
  assert.equal(todayString(new Date(2026, 9, 1)), '2026-10-01');
  assert.equal(todayString(new Date(2026, 0, 9)), '2026-01-09');
});
