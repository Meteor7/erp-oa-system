import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const page = read('../src/pages/PriceApprovalWorkbench.vue');
const root = read('../src/components/price/PriceWorkbench.vue');
const api = read('../src/components/price/usePriceApi.js');
const source = read('../src/components/price/PriceSourceTab.vue');
const approvalList = read('../src/components/price/PriceApprovalList.vue');
const detail = read('../src/components/price/PriceApprovalDetail.vue');
const matrix = read('../src/components/price/PriceMatrix.vue');
const drawer = read('../src/components/price/SupplierDrawer.vue');
const poList = read('../src/components/price/PoList.vue');
const poDetail = read('../src/components/price/PoDetail.vue');
const view = read('../src/lib/priceView.js');
const css = read('../src/styles/priceUi.css');
const router = read('../src/router.js');
const all = [page, root, api, source, approvalList, detail, matrix, drawer, poList, poDetail, view].join('\n');

test('the page file is a thin wrapper around the price workbench component', () => {
  assert.ok(page.split('\n').length < 40);
  assert.match(page, /components\/price\/PriceWorkbench\.vue/);
  assert.match(router, /pages\/PriceApprovalWorkbench\.vue/);
});

test('one level of tabs with counts: PR 待比价物料 | 价格审批单 | PO 与合同', () => {
  assert.match(view, /PR 待比价物料/);
  assert.match(view, /价格审批单/);
  assert.match(view, /PO 与合同/);
  assert.match(root, /role="tablist"/);
  assert.match(root, /item\.count/);
  assert.match(root, /pendingLineCount\(prs\.value\)/);
  assert.doesNotMatch(root, /sub-tabs|main-tabs/);
});

test('route query keeps working: tab=po, view, request, approval, po and notification pr links', () => {
  for (const key of ['request', 'approval', 'po', 'pr']) assert.match(root, new RegExp(`route\\.query\\.${key}`));
  assert.match(view, /query\.tab === 'po'/);
  assert.match(view, /query\.view === 'source'/);
  assert.match(view, /query\.view === 'approvals'/);
  assert.match(root, /resolveTab\(route\.query/);
  assert.match(root, /const contextRequest = computed/);
  assert.match(root, /当前仅查看这张采购申请的完整链路/);
  assert.match(root, /查看全部采购链路/);
  assert.match(view, /line\.source_request === request/);
  assert.match(root, /hasPendingPr: pendingLineCount\(prs\.value\) > 0/);
  assert.match(root, /hasActionable/);
});

test('every old backend call is still wired and arrival / inspection registration is not ported', () => {
  for (const endpoint of [
    'list_prs', 'list_price_approvals', 'list_purchase_orders', 'create_price_approval', 'save_supplier_comparison',
    'delete_supplier_comparison', 'select_supplier_comparison', 'update_price_approval_summary', 'submit_price_approval',
    'approve_price_approval', 'withdraw_price_approval', 'cancel_price_approval', 'update_po_delivery', 'confirm_po',
    'save_po_contract_information', 'review_po_contract', 'seal_po_contract', 'close_po',
  ]) assert.match(api, new RegExp(endpoint));
  assert.match(api, /createResource/);
  assert.doesNotMatch(api, /record_po_receipt|record_po_inspection|record_po_payment/);
  assert.doesNotMatch(all, /v-if="false/);
  assert.match(poDetail, /\/采购付款|采购付款/);
  assert.match(view, /PAYMENT_PAGE = '\/approval\/procurement-payment'/);
  assert.match(poDetail, /router-link :to="PAYMENT_PAGE"/);
});

test('PR source keeps grouping per PR, quantity per line, filters, search and the occupied semantics', () => {
  assert.match(source, /pa-pr-row/);
  assert.match(source, /\{\{ pr\.name \}\}/);
  assert.match(source, /\{\{ pr\.lines\.length \}\} 项物料/);
  assert.match(source, /v-for="line in pr\.lines"/);
  assert.match(source, /本次比价数量/);
  assert.match(source, /可提价格审批/);
  assert.match(source, /全部 PR/);
  assert.match(source, /已无可选物料/);
  assert.match(source, /搜索 PR、OA、项目或物料/);
  assert.match(source, /已被占用/);
  assert.match(source, /PR 数量 − 可选数量/);
  assert.match(source, /availableLineCount\(pr\)/);
  assert.match(source, /emit\('create'/);
  assert.match(source, /!canEdit/);
  assert.match(source, /生成价格审批单/);
  assert.match(view, /source_pr: row\.pr\.name, source_pr_line: row\.line\.name, quantity: Number\(row\.quantity\)/);
  assert.match(root, /create_price_approval|actions\.createApproval/);
  assert.match(root, /lines: JSON\.stringify\(lines\)/);
});

test('approval list and detail keep submit / cancel / withdraw / summary and role gating', () => {
  assert.match(approvalList, /价格审批单/);
  assert.match(detail, /提交价格审批/);
  assert.match(detail, /取消价格审批/);
  assert.match(detail, /撤回修改/);
  assert.match(detail, /保存总结/);
  assert.match(detail, /采购比价总结/);
  assert.match(detail, /审批轨迹/);
  assert.match(detail, /需求内容/);
  for (const label of ['需求单号', '来源 PR', '使用部门', '需求人', '项目']) assert.match(detail, new RegExp(label));
  assert.match(detail, /const editable = computed\(\(\) => props\.canEdit && isDraft\.value\)/);
  assert.match(detail, /const canWithdraw = computed\(\(\) => props\.canEdit && status\.value === '待审批'\)/);
  assert.match(root, /canEditProcurementPrice\(\)/);
  assert.match(root, /canSeeProcurementPrice\(\)/);
  assert.match(root, /canSeeProcurementPO\(\)/);
  // 提交前先保存总结，再提交。
  assert.match(root, /actions\.updateSummary\.submit\(\{ name: approval\.name, summary: value \}\)[\s\S]*actions\.submitApproval\.submit/);
  // 没有 window.confirm / prompt：用页面里的确认条。
  assert.doesNotMatch(all, /window\.confirm|window\.prompt|\bconfirm\(/);
  assert.match(detail, /role="alertdialog"/);
});

test('the vice general manager only selects a supplier and approves; no reject or return action', () => {
  assert.match(detail, /props\.approval\.can_select_quote\) && status\.value === '待审批'/);
  assert.match(detail, /审批通过，生成 PO/);
  assert.match(detail, /:disabled="busy \|\| !chosen"/);
  assert.match(matrix, /选择成交供应商/);
  assert.match(matrix, /canSelect/);
  assert.match(detail, /没有退回或拒绝/);
  assert.doesNotMatch(all, /reject_price|return_price|拒绝价格|退回采购/);
  assert.match(view, /它没报价的 \$\{info\.returned\} 项物料会退回 PR/);
  assert.match(view, /生成 1 张 PO 草稿/);
  assert.match(view, /采购推荐仅供参考，需要您确认成交供应商/);
  assert.match(root, /select_supplier_comparison|actions\.chooseSupplier/);
  assert.match(root, /actions\.approveApproval/);
});

test('comparison matrix: per-line best price, totals only between complete quotes, commercial terms table', () => {
  assert.match(matrix, /pa-matrix/);
  assert.match(matrix, /本项最低/);
  assert.match(matrix, /报价合计/);
  assert.match(matrix, /supplierTotalNote/);
  assert.match(view, /未报全，不比总价/);
  assert.match(view, /完整报价中最低/);
  assert.match(matrix, /采购推荐/);
  assert.match(matrix, /已选成交/);
  assert.match(matrix, /商务条件对比/);
  for (const label of ['付款方式', '付款计划', '币种 / 税率', '合同主体', '最晚货期', '报价说明']) assert.match(matrix, new RegExp(label));
  assert.match(matrix, /MIN_SUPPLIER_SLOTS/);
  assert.match(view, /MIN_SUPPLIER_SLOTS = 3/);
  assert.match(matrix, /新增供应商/);
  assert.match(matrix, /编辑此供应商/);
  assert.match(matrix, /选它则退回 PR/);
  assert.match(matrix, /总价只在"每家都报了全部物料"时才比较/);
});

test('supplier quote drawer keeps price, delivery, payment method, payment plan, tax, entity, note and recommendation', () => {
  assert.match(drawer, /role="dialog"/);
  for (const label of ['报价', '商务条件', '付款计划', '说明', '付款方式', '币种', '税率', '合同主体', '增加期次', '按报价总额', '采购推荐这家', '删除这家供应商', '计划付款日期', '触发条件', '发票要求', '期次', '付款阶段', '比例', '金额', '货期', '单价']) {
    assert.match(drawer, new RegExp(label));
  }
  assert.match(drawer, /CNY（暂只支持人民币）/);
  assert.match(view, /PAYMENT_STAGES = \['预付款', '到货款', '尾款', '到货后全额付款'\]/);
  assert.match(view, /INVOICE_REQUIREMENTS = \['付款前提供', '付款后提供', '无需发票'\]/);
  assert.match(drawer, /supplierPayload\(props\.approval, draft\.value\)/);
  assert.match(view, /payment_plan: JSON\.stringify/);
  assert.match(view, /prices: JSON\.stringify\(prices\)/);
  assert.match(view, /original_supplier: draft\.original_supplier/);
  assert.match(root, /actions\.saveSupplier\.submit\(payload\)/);
  assert.match(root, /actions\.deleteSupplier\.submit/);
  assert.doesNotMatch(drawer, /<option>USD<\/option>/);
});

test('PO tab: list, delivery dates, confirm, contract fields, review, seal, close with missing items', () => {
  assert.match(poList, /PO 总额/);
  for (const text of ['保存合同交期', '确认 PO', '合同信息', '物料明细', '到货与验收', '校验并关闭 PO', '还差', '付款计划', '合同审批轨迹']) assert.match(poDetail + view, new RegExp(text));
  assert.match(view, /生成合同草稿/);
  assert.match(view, /复核合同/);
  assert.match(view, /电子用印/);
  assert.match(poDetail, /po\.can_manage_purchase/);
  assert.match(view, /po\.can_seal_contract/);
  assert.match(view, /待补充信息/);
  assert.match(view, /草稿待复核/);
  // 合同信息输入：后端接受的全部字段。
  for (const field of ['supplier_legal_name', 'credit_code', 'supplier_address', 'contract_contact', 'contract_bank_name', 'contract_bank_account', 'contract_delivery_date']) assert.match(view, new RegExp(field));
  assert.match(poDetail, /v-model="contractDraft\[field\.key\]"/);
  assert.match(root, /actions\.savePoContract\.submit\(payload\)/);
  assert.match(root, /actions\.confirmPo\.submit/);
  assert.match(root, /actions\.updateDelivery\.submit/);
  assert.match(root, /actions\.reviewPoContract\.submit/);
  assert.match(root, /actions\.sealPoContract\.submit/);
  assert.match(root, /actions\.closePo\.submit/);
  // 关闭条件按行字段计算，不满足时按钮禁用并列出还差什么。
  assert.match(poDetail, /:disabled="busy \|\| blockers\.length > 0"/);
  assert.match(view, /'全部到货'/);
  assert.match(view, /'全部验收通过'/);
  assert.match(view, /'付款结清'/);
  // 每行带自己的来源 OA / PR / 项目。
  assert.match(poDetail, /line\.source_request/);
  assert.match(poDetail, /line\.source_pr/);
  assert.match(poDetail, /line\.project/);
  // 到货 / 验收只读，去采购付款登记。
  assert.match(poDetail, /由生产主管登记/);
  assert.match(poDetail, /received_quantity/);
  assert.match(poDetail, /inspection_status/);
});

test('no hard-coded person names, CSS stays under .xp with the pa- prefix', () => {
  assert.doesNotMatch(all, /演示员工21|何静|演示员工178|演示员工37/);
  const selectors = css.split('\n').filter((line) => /^[.@a-z]/.test(line) && line.includes('{') && !line.startsWith('@media') && !line.startsWith('@keyframes'));
  assert.ok(selectors.length > 40);
  for (const line of selectors) assert.match(line, /^\.xp[ .]/, line);
  assert.match(css, /\.xp \.pa-/);
  assert.match(root, /import '\.\.\/\.\.\/styles\/priceUi\.css'/);
  assert.match(root, /class="xp pa"/);
});
