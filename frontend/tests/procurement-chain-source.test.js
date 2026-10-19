import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// 价格审批 + PO 页面（2026-10-01 改版）：PriceApprovalWorkbench.vue 只剩一层壳，页面在 components/price 下。
const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const procurement = [
  'PriceWorkbench', 'PriceSourceTab', 'PriceApprovalList', 'PriceApprovalDetail', 'PriceMatrix', 'SupplierDrawer', 'PoList', 'PoDetail',
].map((name) => read(`../src/components/price/${name}.vue`)).concat(read('../src/components/price/usePriceApi.js'), read('../src/lib/priceView.js')).join('\n');
const priceDetail = read('../src/components/price/PriceApprovalDetail.vue');
const priceMatrix = read('../src/components/price/PriceMatrix.vue');
const priceSource = read('../src/components/price/PriceSourceTab.vue');
const progress = readFileSync(new URL('../src/pages/MaterialProgress.vue', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
// 采购申请页面（2026-09-30 改版）：旧的 PreRequestCenter.vue 只剩一层壳，页面在 components/procurement 下。
const requestCenter = [
  'ProcurementWorkbench', 'ProcHome', 'PurchaseHome', 'ProcList', 'ProcDetail', 'ProcForm', 'ProcLineEditor', 'ProcDocuments',
].map((name) => readFileSync(new URL(`../src/components/procurement/${name}.vue`, import.meta.url), 'utf8')).join('\n');
const requestView = readFileSync(new URL('../src/lib/procurementView.js', import.meta.url), 'utf8');
// 采购付款页面（2026-10-01 改版）：PaymentCenter.vue 只剩一层壳，页面在 components/payment 下。
const paymentCenter = [
  'PaymentWorkbench', 'PayWorkTab', 'PayFulfilmentPanel', 'PayInstallmentCard', 'PayApprovalsTab', 'PayApprovalPage',
].map((name) => read(`../src/components/payment/${name}.vue`)).concat(read('../src/lib/paymentView.js')).join('\n');
const backend = readFileSync(new URL('../../rayher_hr_payroll/api/procurement_chain.py', import.meta.url), 'utf8');

test('PR selection belongs to material progress and price approval keeps line quantities', () => {
  assert.match(progress, /prQuantities/);
  assert.match(progress, /create_pr/);
  assert.match(progress, /本次 PR 数量/);
  assert.match(procurement, /create_price_approval/);
  assert.match(priceSource, /本次比价数量/);
  assert.match(procurement, /source_pr_line/);
});

test('price approval compares supplier packages with optional line quotes', () => {
  assert.match(procurement, /save_supplier_comparison/);
  assert.match(procurement, /delete_supplier_comparison/);
  assert.match(procurement, /select_supplier_comparison/);
  assert.match(procurement, /供应商比价/);
  assert.match(priceMatrix, /pa-matrix/);
  assert.match(procurement, /报价合计/);
  assert.match(procurement, /付款方式/);
  assert.match(procurement, /货期/);
  assert.match(procurement, /物料编号/);
  assert.match(procurement, /采购推荐/);
  assert.match(procurement, /已选成交/);
  assert.doesNotMatch(procurement, /演示员工37审批通过/);
  // 演示员工113经理：只有选定成交供应商并通过，没有退回 / 拒绝（决定 2026-10-01）。
  const approveButton = priceDetail.match(/<button[^>]+>审批通过，生成 PO<\/button>/)?.[0];
  assert.ok(approveButton);
  assert.match(approveButton, /v-if="canDecide"/);
  assert.match(approveButton, /!chosen/);
  assert.match(priceDetail, /Boolean\(props\.approval\.can_select_quote\) && status\.value === '待审批'/);
  assert.match(procurement, /采购推荐仅供参考，需要您确认成交供应商/);
  assert.doesNotMatch(procurement, /reject_price_approval|退回采购/);
  // 未报全的供应商不比总价、不标最低价
  assert.match(procurement, /未报全，不比总价/);
  assert.match(backend, /未问到的物料可留空/);
  assert.match(backend, /成交供应商/);
});

test('PR source selection groups materials under each PR before approval creation', () => {
  assert.match(priceSource, /pa-pr-row/);
  assert.match(priceSource, /\{\{ pr\.name \}\}/);
  assert.match(priceSource, /项物料/);
  assert.doesNotMatch(priceSource, /pr\.lines\[0\]/);
  assert.match(priceSource, /v-for="[^"]*in pr\.lines"/);
  assert.doesNotMatch(backend, /"pr_groups":/);
  assert.match(priceSource, /可提价格审批/);
  assert.match(procurement, /availableLineCount/);
  assert.match(backend, /"can_create_price_approval": 1 if available_line_count else 0/);
  assert.match(backend, /sorted\(summaries, key=lambda item: 0 if item\["can_create_price_approval"\] else 1\)/);
});

test('procurement queue distinguishes loading from a real empty result and avoids duplicate global loads', () => {
  assert.match(requestCenter, /正在读取申请和待办/);
  assert.match(requestCenter, /业务单据加载失败/);
  assert.match(requestCenter, /重新加载/);
  assert.match(requestCenter, /procurement_global_access/);
  // mine + pending + all 一起取（all 服务端按权限限定：非全局角色只拿到自己提的、经手的、自己负责的项目里别人提的），按单号去重
  assert.match(requestCenter, /listFor\('mine'\), listFor\('pending'\), listFor\('all'\)/);
  assert.match(requestCenter, /mergeRows\(ctx\.requestType, data\.mine, data\.pending, data\.all\)/);
  assert.doesNotMatch(requestCenter, /createResource/);
  assert.doesNotMatch(requestCenter, /auto: true/);
});

test('price review puts summary and approval trail after the supplier matrix', () => {
  assert.match(priceDetail, /需求单号/);
  assert.match(priceDetail, /使用部门/);
  assert.match(priceDetail, /pa-requirement/);
  assert.match(priceDetail, /需求内容/);
  assert.match(priceDetail, /采购比价总结/);
  assert.match(priceDetail, /审批轨迹/);
  assert.ok(priceDetail.indexOf('<PriceMatrix') < priceDetail.indexOf('pa-summary'));
  assert.ok(priceDetail.indexOf('pa-summary') < priceDetail.indexOf('pa-trail'));
  assert.match(backend, /提交价格审批前必须填写采购比价总结/);
});

test('PO payment push is the only visible payment entry and keeps PO provenance', () => {
  // 价格审批 / PO 页面不再办理付款，只留一个跳转；提交付款审批在采购付款页面（2026-10-01）。
  assert.doesNotMatch(procurement, /push_po_payment_request/);
  assert.match(paymentCenter, /push_po_payment_request/);
  assert.match(procurement, /\/approval\/procurement-payment/);
  // 采购付款不再由采购申请页面展示（2026-09-30）：它有自己的页面，申请页面里不留付款新建入口。
  assert.doesNotMatch(requestCenter, /采购付款单由 PO 付款计划下推生成/);
  assert.match(backend, /PO_PAYMENT_PUSH_SOURCE = \"PO付款下推\"/);
  assert.match(backend, /payment_doc\.source_type = PO_PAYMENT_PUSH_SOURCE/);
  assert.match(backend, /source_purchase_order: po\.name/);
  assert.match(backend, /source_po_payment_plan_row: _text\(row\.name\)/);
});

test('procurement payment workbench owns payment conditions, receipt, inspection, and approval entry', () => {
  // PO 的演示员工116和关闭在价格审批 / PO 页面；到货、验收、换货到货、退货、提交付款审批在采购付款页面。
  for (const endpoint of ['update_po_delivery', 'close_po']) {
    assert.match(procurement, new RegExp(endpoint));
    assert.match(backend, new RegExp('def ' + endpoint));
  }
  for (const endpoint of ['record_po_receipt', 'record_po_inspection', 'record_po_exchange_receipt', 'record_po_return', 'push_po_payment_request']) {
    assert.match(paymentCenter, new RegExp(endpoint));
    assert.match(backend, new RegExp('def ' + endpoint));
    assert.doesNotMatch(procurement, new RegExp(endpoint));
  }
  assert.match(paymentCenter, /list_payment_work_items/);
  assert.match(paymentCenter, /登记到货/);
  assert.match(paymentCenter, /登记验收/);
  assert.match(paymentCenter, /提交付款审批/);
  assert.match(paymentCenter, /本期付款金额/);
  assert.match(paymentCenter, /unit_price/);
  assert.match(backend, /Create the visible 采购付款 OA from a PO payment-plan row/);
  assert.match(backend, /def list_payment_work_items/);
  assert.match(backend, /payment_doc\.amount = float\(row\.amount or 0\)/);
  assert.match(backend, /尚未全部到货，不能关闭/);
  assert.match(backend, /尚未全部验收通过，不能关闭/);
  assert.match(backend, /尚未完成付款，不能关闭/);
  assert.match(backend, /只有生产主管或系统演示员工170可以登记到货资料/);
  assert.match(backend, /PO 演示员工116生效并进入供应商制作后，才能登记到货资料/);
  assert.match(paymentCenter, /can_record_receipt/);
  assert.match(paymentCenter, /can_record_inspection/);
  // 到货和验收都由生产主管登记（2026-10-01）：服务端不再允许采购登记验收。
  assert.match(backend, /def _can_record_inspection\(\):\n    return _can_record_receipt\(\)/);
  assert.doesNotMatch(backend, /def record_po_inspection[\s\S]{0,400}_require_purchase\(\)/);
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
  assert.match(requestCenter, /物料编号 \/ 流水号/);
  assert.match(requestCenter, /提交后自动生成/);
});

test('procurement request delivery wording and execution links follow the PR chain', () => {
  assert.match(requestCenter, /预计交期/);
  assert.ok(!requestCenter.includes('>期望交期<'));
  assert.ok(!requestCenter.includes('>意向交期<input'));
  // 阶段条和跳转来自后端 procurement_chain 的 stage / label / summary
  assert.match(requestView, /procurement_chain/);
  assert.match(requestView, /等待提 PR/);
  assert.match(requestView, /等 PMC 在物料看板提 PR/);
  assert.match(requestCenter, /去物料看板提 PR/);
  assert.match(requestCenter, /处理询价 \/ 比价/);
  assert.match(requestCenter, /打开价格审批单/);
});
