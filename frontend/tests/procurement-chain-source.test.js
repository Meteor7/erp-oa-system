import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const procurement = readFileSync(new URL('../src/pages/PriceApprovalWorkbench.vue', import.meta.url), 'utf8');
const progress = readFileSync(new URL('../src/pages/MaterialProgress.vue', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
const requestCenter = readFileSync(new URL('../src/pages/PreRequestCenter.vue', import.meta.url), 'utf8');
const paymentCenter = readFileSync(new URL('../src/pages/PaymentCenter.vue', import.meta.url), 'utf8');
const backend = readFileSync(new URL('../../rayher_hr_payroll/api/procurement_chain.py', import.meta.url), 'utf8');

test('PR selection belongs to material progress and price approval keeps line quantities', () => {
  assert.match(progress, /prQuantities/);
  assert.match(progress, /create_pr/);
  assert.match(progress, /本次 PR 数量/);
  assert.match(procurement, /priceQuantities/);
  assert.match(procurement, /create_price_approval/);
  assert.match(procurement, /本次比价数量/);
});

test('price approval compares supplier packages with optional line quotes', () => {
  assert.match(procurement, /supplierComparisons/);
  assert.match(procurement, /save_supplier_comparison/);
  assert.match(procurement, /delete_supplier_comparison/);
  assert.match(procurement, /select_supplier_comparison/);
assert.match(procurement, /供应商比价/);
  assert.match(procurement, /supplierSlots/);
  assert.match(procurement, /approvalView/);
  assert.match(procurement, /新增供应商栏位/);
  assert.match(procurement, /供应商 \${index \+ 1}/);
  assert.match(procurement, /quote-matrix/);
  assert.match(procurement, /供应商报价|报价单价/);
  assert.match(procurement, /报价合计/);
  assert.match(procurement, /付款方式/);
  assert.match(procurement, /货期/);
  for (const field of ['sticky-index', 'sticky-serial', 'sticky-code', 'sticky-name', 'sticky-quantity', 'col-quantity']) assert.match(procurement, new RegExp(field));
  assert.doesNotMatch(procurement, /sticky-category/);
  assert.match(procurement, /sticky-code/);
  assert.match(procurement, /物料编号/);
  assert.doesNotMatch(procurement, /supplier-overview-table/);
  assert.doesNotMatch(procurement, /supplier-editor/);
  assert.match(procurement, /采购推荐/);
  assert.match(procurement, /已选成交/);
  assert.doesNotMatch(procurement, /演示员工37审批通过/);
  const approveButton = procurement.match(/<button[^>]+@click="approveCurrent"[^>]*>/)?.[0];
  assert.ok(approveButton);
  assert.match(approveButton, /v-if="activeApproval.can_select_quote && activeApproval.status === '待审批'"/);
  assert.match(approveButton, /:disabled="!selectedSupplier"/);
  assert.match(procurement, /采购推荐仅供参考，需要您确认成交供应商/);
  assert.match(procurement, /if \(!selectedSupplier\.value\)/);
  assert.match(backend, /未问到的物料可留空/);
  assert.match(backend, /成交供应商/);
});

test('PR source selection groups materials under each PR before approval creation', () => {
  const sourceView = procurement.slice(procurement.indexOf('从 PR 选择物料'), procurement.indexOf('<div v-else class="master-detail">'));
  assert.match(sourceView, /source-pr-group-row/);
  assert.match(sourceView, /\{\{ pr\.name \}\}/);
  assert.match(sourceView, /\{\{ pr\.lines\.length \}\} 项物料/);
  assert.doesNotMatch(sourceView, /pr\.lines\[0\]/);
  assert.match(sourceView, /v-for="\(line, lineIndex\) in pr\.lines"/);
  assert.ok(sourceView.indexOf('source-pr-group-row') < sourceView.indexOf('v-for="(line, lineIndex) in pr.lines"'));
  assert.doesNotMatch(procurement, /approvalPrGroups|class="pr-group-row"/);
  assert.doesNotMatch(backend, /"pr_groups":/);
  assert.match(procurement, /prAvailability/);
  assert.match(procurement, /可提价格审批/);
  assert.match(procurement, /availableLineCount\(pr\)/);
  assert.match(backend, /"can_create_price_approval": 1 if available_line_count else 0/);
  assert.match(backend, /sorted\(summaries, key=lambda item: 0 if item\["can_create_price_approval"\] else 1\)/);
});

test('procurement queue distinguishes loading from a real empty result and avoids duplicate global loads', () => {
  assert.match(requestCenter, /正在读取申请和待办/);
  assert.match(requestCenter, /业务单据加载失败/);
  assert.match(requestCenter, /procurement_global_access/);
  assert.match(requestCenter, /if \(hasGlobalQueueAccess\(\)\) await allLoader\.reload\(\)/);
  assert.doesNotMatch(requestCenter, /mineLoader[^\n]+auto: true/);
  assert.doesNotMatch(requestCenter, /pendingLoader[^\n]+auto: true/);
  assert.doesNotMatch(requestCenter, /allLoader[^\n]+auto: true/);
});

test('price review puts summary and approval trail after the supplier matrix', () => {
  assert.match(procurement, /需求单号/);
  assert.match(procurement, /使用部门/);
  assert.match(procurement, /requirement-content/);
  assert.match(procurement, /需求内容/);
  assert.match(procurement, /价格审批单内容/);
  assert.match(procurement, /approvalView === 'requirement'/);
  assert.match(procurement, /采购比价总结/);
  assert.match(procurement, /会签 \/ 审批轨迹/);
  assert.ok(procurement.indexOf('quote-matrix') < procurement.indexOf('review-summary bottom-section'));
  assert.ok(procurement.indexOf('review-summary bottom-section') < procurement.indexOf('approval-trail bottom-section'));
  assert.match(backend, /提交价格审批前必须填写采购比价总结/);
});

test('PO payment push is the only visible payment entry and keeps PO provenance', () => {
  assert.match(procurement, /push_po_payment_request/);
  assert.match(procurement, /下推采购付款/);
  assert.match(requestCenter, /采购付款单由 PO 付款计划下推生成，不能单独新建/);
  assert.match(requestCenter, /isPayment \? '采购付款明细'/);
  assert.match(backend, /PO_PAYMENT_PUSH_SOURCE = \"PO付款下推\"/);
  assert.match(backend, /payment_doc\.source_type = PO_PAYMENT_PUSH_SOURCE/);
  assert.match(backend, /source_purchase_order: po\.name/);
  assert.match(backend, /source_po_payment_plan_row: _text\(row\.name\)/);
  assert.match(requestCenter, /isPayment \? '本期付款金额' : '当前总金额'/);
  assert.doesNotMatch(requestCenter, /isPayment \? '-' : \(Number\(line\.unit_price/);
});

test('procurement payment workbench owns payment conditions, receipt, inspection, and approval entry', () => {
  for (const endpoint of ['update_po_delivery', 'record_po_receipt', 'record_po_inspection', 'push_po_payment_request', 'record_po_payment', 'close_po']) {
    assert.match(procurement, new RegExp(endpoint));
    assert.match(backend, new RegExp('def ' + endpoint));
  }
  assert.match(paymentCenter, /list_payment_work_items/);
  assert.match(paymentCenter, /到货资料登记/);
  assert.match(paymentCenter, /验收资料登记/);
  assert.match(paymentCenter, /提交付款审批/);
  assert.match(paymentCenter, /本期付款金额/);
  assert.match(paymentCenter, /line\.unit_price/);
  assert.match(paymentCenter, /line\.amount/);
  assert.match(procurement, /付款条件与执行已移至采购付款工作台/);
  assert.match(backend, /Create the visible 采购付款 OA from a PO payment-plan row/);
  assert.match(backend, /def list_payment_work_items/);
  assert.match(backend, /payment_doc\.amount = float\(row\.amount or 0\)/);
  assert.match(backend, /尚未全部到货，不能关闭/);
  assert.match(backend, /尚未全部验收通过，不能关闭/);
  assert.match(backend, /尚未完成付款，不能关闭/);
  assert.match(backend, /只有生产主管或系统管理员可以登记到货资料/);
  assert.match(backend, /PO 合同生效并进入供应商制作后，才能登记到货资料/);
  assert.match(paymentCenter, /activeItem\.can_record_receipt/);
  assert.match(paymentCenter, /activeItem\.can_record_inspection/);
});

test('material progress keeps seven derived stages, PR action, and source approval trail', () => {
  for (const status of ['OA审批中', '采购确认中', 'PO处理中', '供应商制作中', '到货验收中', '付款中', '已关闭']) {
    assert.match(progress, new RegExp(status));
  }
  assert.match(progress, /createPrFromBoard/);
  assert.match(progress, /oa_approval_trail/);
  assert.match(progress, /流程状态由关联单据自动更新/);
});

test('navigation removes redundant procurement chain and places price approval under procurement', () => {
  assert.doesNotMatch(app, /采购链路看板/);
  assert.match(app, /approval\/procurement\/price-approvals/);
});

test('procurement request separates category, material code, and generated material serial', () => {
  assert.match(requestCenter, /物料编号/);
  assert.doesNotMatch(requestCenter, /物料科目/);
  assert.match(requestCenter, /物料编号/);
  assert.match(requestCenter, /物料流水号/);
  assert.match(requestCenter, /提交后自动生成/);
});

test('procurement request delivery wording and execution links follow the PR chain', () => {
  assert.match(requestCenter, /预计交期/);
  assert.ok(!requestCenter.includes('>期望交期<'));
  assert.ok(!requestCenter.includes('>意向交期<input'));
  assert.ok(requestCenter.includes('从 PR 选择物料生成 / 查看'));
  assert.ok(requestCenter.includes('价格审批通过后自动生成'));
});


