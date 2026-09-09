import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildApprovalCenterPayload,
  canCloseProcurement,
  canCompleteSupplierRefund,
  canRecordArrival,
  normalizeServerError,
  organizationPreflightMessage,
  validateProcurementRequestForm,
  validatePriceApprovalForm,
} from "../src/lib/procurementWorkflow.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("server errors are converted to plain text without rendering raw HTML", () => {
  assert.equal(normalizeServerError({ messages: ["用户<strong>admin</strong>无权访问"] }), "用户admin无权访问");
  assert.equal(normalizeServerError({ message: "<script>alert(1)</script>保存失败" }), "alert(1)保存失败");
});

test("payload separates procurement, direct purchase, and payment-only fields", () => {
  const form = {
    subject: "申请", reason: "原因", urgency: "一般", asset_nature: "非固定资产",
    fixed_asset_category: "", procurement_scope: "项目采购", expected_delivery_date: "2026-09-01",
    applicant_employee: "EMP-1",
    project: "PRJ-1", non_project_allocation_type: "部门", non_project_department: "研发部",
    purchase_method: "京东购买", source_request: "PROC-1", supplier: "SUP-1",
    prepayment_percentage: 100, expected_arrival_date: "2026-09-10",
    source_purchase_order: "PO-1", source_po_payment_plan_row: "PLAN-1",
    prepayment_risk_note: "风险已评估", business_lines: [],
  };
  const procurement = buildApprovalCenterPayload(form, "采购申请");
  const direct = buildApprovalCenterPayload(form, "购买申请");
  const payment = buildApprovalCenterPayload(form, "采购付款");
  assert.equal(procurement.project, "PRJ-1");
  assert.equal(procurement.applicant_employee, "EMP-1");
  assert.equal(procurement.purchase_method, undefined);
  assert.equal(direct.purchase_method, "京东购买");
  assert.equal(direct.non_project_allocation_type, undefined);
  assert.equal(direct.non_project_cost_center, undefined);
  assert.equal(direct.non_project_department, undefined);
  assert.equal(direct.payment_stage, undefined);
  assert.equal(payment.source_request, "PROC-1");
  assert.equal(payment.source_purchase_order, "PO-1");
  assert.equal(payment.source_po_payment_plan_row, "PLAN-1");
  assert.equal(payment.purchase_method, undefined);
  assert.equal(payment.payment_stage, undefined);
  assert.equal(payment.has_balance_payment, undefined);
});

test("evidence gates visible lifecycle actions before the server revalidates", () => {
  assert.equal(canRecordArrival({ request_type: "采购付款", workflow_status: "已付款", business_status: "待到货" }, ["送货单"]), true);
  assert.equal(canRecordArrival({ request_type: "采购付款", workflow_status: "已付款", business_status: "待到货" }, []), false);
  assert.equal(canRecordArrival({ request_type: "采购申请", workflow_status: "已完成", business_status: "采购执行中" }, ["送货单"]), true);
  assert.equal(canRecordArrival({ request_type: "采购申请", workflow_status: "待审批", business_status: "采购执行中" }, ["送货单"]), false);
  assert.equal(canRecordArrival({ request_type: "采购付款", workflow_status: "已付款", business_status: "换货中" }, ["送货单"]), true);
  assert.equal(canCompleteSupplierRefund({ request_type: "采购付款", workflow_status: "已付款", business_status: "供应商退款中" }, ["退款回单"]), true);
  const closable = { request_type: "采购付款", workflow_status: "已付款", business_status: "验收通过", inspection_status: "验收通过", prepayment_writeoff_status: "已核销", has_balance_payment: 0 };
  assert.equal(canCloseProcurement(closable, ["发票", "验收资料", "采购完成报告"]), true);
  assert.equal(canCloseProcurement({ ...closable, business_status: "已关闭" }, ["发票", "验收资料", "采购完成报告"]), false);
});

test("organization preflight blocks request forms before a doomed submit", () => {
  assert.match(organizationPreflightMessage("采购申请", {}), /在职员工/);
  assert.match(organizationPreflightMessage("购买申请", { employee: "EMP-1" }), /直属上级/);
  assert.equal(organizationPreflightMessage("采购申请", {
    employee: "EMP-1", supervisor_user: "manager@example.com",
  }), "");
  assert.equal(organizationPreflightMessage("采购申请", {
    employee: "EMP-1", supervisor_decision: "skip",
  }), "");
  assert.equal(organizationPreflightMessage("采购付款", {}), "");
});

test("procurement request lines require a searchable third-level category and complete material details", () => {
  const base = {
    business_lines: [{ category_code: "1.ELC", item_name: "物料", specification: "规格", product_desc: "描述", brand: "品牌", quantity: 1, unit: "个" }],
  };
  assert.match(validateProcurementRequestForm(base), /至少选择到三级/);
  assert.equal(validateProcurementRequestForm({ business_lines: [{ ...base.business_lines[0], category_code: "1.ELC.3", product_desc: "" }] }), "");
  assert.equal(validateProcurementRequestForm({ business_lines: [{ ...base.business_lines[0], category_code: "1.ELC.3" }] }), "");
  assert.match(validateProcurementRequestForm({ business_lines: [] }), /至少添加一项/);
});

test('procurement request accepts any category depth from third level through full material code', () => {
  const line = { item_name: '物料', specification: '规格', brand: '品牌', quantity: 1, unit: '个' };
  for (const category_code of ['1.ELC.3', '1.ELC.3.3', '1.ELC.3.3.03', '1.ELC.3.3.03.001']) {
    assert.equal(validateProcurementRequestForm({ business_lines: [{ ...line, category_code }] }), '', category_code);
  }
});

test('procurement keeps broad asset nature while detailed classes belong only to direct purchase', () => {
  const source = read('../src/pages/PreRequestCenter.vue');
  assert.match(source, /<label v-if="isProcurement \|\| isDirectPurchase" class="text-xs font-medium text-gray-700">资产属性/);
  assert.match(source, /<label v-if="isDirectPurchase && form\.asset_nature === '固定资产'"/);
});

test('purchase application does not auto-load the procurement material catalog', () => {
  const source = read('../src/pages/PreRequestCenter.vue');
  assert.match(source, /const categoryLoader = createResource\(\{ url: 'rayher_hr_payroll\.api\.procurement_materials\.list_categories'/);
  assert.doesNotMatch(source, /list_categories[^\n]+auto: true/);
  assert.match(source, /if \(requestType === '采购申请'\) await categoryLoader\.reload\(\)/);
  assert.match(source, /<div v-if="isProcurement" class="border-t border-gray-200">/);
  assert.match(source, /<div v-else class="border-t border-gray-200">/);
});


test("forms use real project options and conditional business fields", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  assert.match(source, /oa_entry\.list_approval_center_projects/);
  assert.match(source, /oa_entry\.list_procurement_payment_sources/);
  assert.match(source, /oa_entry\.list_procurement_users/);
  assert.match(source, /oa_entry\.list_procurement_applicants/);
  assert.doesNotMatch(source, /project_entry\.list_project_owners/);
  assert.match(source, /view: 'all'/);
  assert.match(source, /<select v-model=['"]form\.project/);
  assert.match(source, /form\.procurement_scope === ['"]项目采购['"]/);
  assert.match(source, /non_project_allocation_type/);
  assert.match(source, /purchase_method/);
  assert.doesNotMatch(source, /<select v-model=['"]form\.payment_stage/);
  assert.doesNotMatch(source, /<option>全额付款<\/option>/);
  assert.match(source, /付款计划期次/);
  assert.match(source, /source_payment_plan_row/);
  assert.match(source, /save_procurement_contract_information/);
  assert.match(source, /review_procurement_contract/);
  assert.match(source, /seal_procurement_contract/);
  assert.match(source, /remove_approval_business_document/);
  assert.match(source, /isProcurementOrPayment/);
  assert.match(source, /prepayment_risk_note/);
  assert.match(source, /record_arrival/);
  assert.match(source, /record_inspection/);
  assert.match(source, /writeoff_prepayment/);
  assert.match(source, /close_procurement/);
  assert.match(source, /complete_supplier_refund/);
  assert.match(source, /退款回单/);
  assert.match(source, /row\.purchaser_user === currentUser/);
  assert.match(source, /逐级选择，至少三级/);
  assert.match(source, /选择一级分类/);
  assert.match(source, /没有下一级时可停在当前级/);
  assert.match(source, /categoryLevelOptions/);
  assert.match(source, /categoryMaterialResults/);
  assert.match(source, /loadCategoryMaterials/);
  assert.match(source, /选择物料编号/);
  assert.match(source, /chooseCategoryMaterial/);
  assert.match(source, /closeCategoryPicker\(line\)/);
  assert.match(source, /startsWith\(`\$\{code\}\.\`\)/);
  assert.match(source, /inferredCategory/);
  assert.match(source, /选择物料编号会自动带出完整物料资料/);
  assert.match(source, /validateProcurementRequestForm/);
  assert.match(source, /watch\(form, \(\) => \{/);
  assert.match(source, /canManageExpense \|\| row\.purchaser_user/);
  assert.match(source, /if \(isProcurement\.value && !form\.purchaser_user/);
  assert.doesNotMatch(source, /<select v-model=['"]form\.purchaser_user/);
});

test("procurement payment is opened from PO and has no standalone new-request form", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  assert.match(source, /<button v-if="!isPayment"[^>]*>/);
  assert.match(source, /<section v-if="!isPayment && \(showCreateForm \|\| isNewRequestPage \|\| isPmcEditPage\)/);
  assert.match(source, /source_purchase_order/);
  assert.match(source, /source_po_payment_plan_row/);
});

test("structured price form validates locked commercial totals", () => {
  const valid = {
    supplier: "供应商", delivery_terms: "合同生效后30天", warranty_terms: "一年",
    invoice_condition: "专票", business_lines: [{ quantity: 1, unit_price: 10000 }],
    payment_plan: [
      { percentage: 30, amount: 3000, trigger_condition: "合同生效" },
      { percentage: 70, amount: 7000, trigger_condition: "验收通过" },
    ],
  };
  assert.equal(validatePriceApprovalForm(valid), "");
  assert.match(validatePriceApprovalForm({
    ...valid,
    payment_plan: [{ percentage: 90, amount: 10000, trigger_condition: "合同生效" }],
  }), /100%/);
});

test("business document responses cannot overwrite the newly selected request", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  assert.match(source, /const requestedName = name/);
  assert.match(source, /requestedName === activeRequestName\.value/);
  assert.match(source, /documentLoader\.fetch\(\{ request: requestedName \}\)/);
});


test("approvers see procurement decision data before approval controls", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  const details = source.indexOf("采购需求");
  const lines = source.indexOf("采购明细", details);
  const documents = source.indexOf("业务资料", lines);
  const timeline = source.indexOf("审批轨迹", lines);
  const actions = source.indexOf("价格审批待处理", timeline);
  assert.ok(details > -1);
  assert.ok(lines > details);
  assert.ok(documents > lines);
  assert.ok(timeline > lines);
  assert.ok(actions > timeline);
  assert.match(source, /selectedRequest\.employee_name/);
  assert.match(source, /selectedRequest\.department/);
  assert.match(source, /selectedRequest\.reason/);
  assert.match(source, /selectedRequest\.expected_delivery_date/);
  assert.match(source, /selectedRequest\.procurement_scope/);
  assert.match(source, /line\.item_name/);
  assert.match(source, /line\.specification/);
  assert.match(source, /line\.quantity/);
  assert.match(source, /line\.unit/);
  assert.match(source, /line\.remarks/);
  assert.match(source, /selectedRequest\.operation_log/);
});

test("approval workbench appears before the collapsible creation form", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  const formGuard = source.indexOf('v-if="!isPayment && (showCreateForm || isNewRequestPage || isPmcEditPage)');
  assert.ok(source.indexOf("申请与待办") < formGuard);
  assert.match(source, /@click="toggleCreateForm"/);
  assert.match(source, /<section v-if="false"[^>]*border-amber-200/);
});

test("new procurement payment forms cannot inherit or upload against the viewed request", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  const start = source.slice(source.indexOf("function startNewRequest()"), source.indexOf("function closeRequestForm()"));
  assert.match(source, /const creatingNew = ref\(false\)/);
  assert.match(source, /if \(creatingNew\.value\) return null/);
  assert.match(source, /creatingNew\.value \? draftName\.value/);
  assert.match(start, /resetRequestForm\(\)/);
  assert.match(start, /creatingNew\.value = true/);
  assert.match(start, /draftName\.value = ''/);
  assert.match(start, /documents\.value = \[\]/);
  assert.match(source, /@click="selectRequest\(row\.name\)"/);
  assert.match(source, /if \(creatingNew\.value\) return;/);
  const requestRowsWatcher = source.slice(source.indexOf("watch(requestRows"), source.indexOf("watch(() => route.query.request"));
  assert.match(requestRowsWatcher, /if \(creatingNew\.value\) return;/);
});


test("procurement price and contract work move to dedicated inner routes", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  assert.match(source, /procurement-price-approval/);
  assert.match(source, /procurement-contract/);
  assert.match(source, /isPriceInnerPage/);
  assert.match(source, /isContractInnerPage/);
  assert.match(source, /const routeRequestName = String\(route\.params\.name \|\| ''\)/);
  assert.match(source, /row\.name === routeRequestName/);
  assert.match(source, /返回采购主单/);
  assert.match(source, /价格审批决策/);
  assert.match(source, /contract_entity: '示例企业032有限公司'/);
  assert.doesNotMatch(source, /contract_entity: '普朗克半导体'/);
});

test("procurement OA links keep PR, price approval, and PO in one scoped chain", () => {
  const requestSource = read("../src/pages/PreRequestCenter.vue");
  const priceSource = read("../src/pages/PriceApprovalWorkbench.vue");
  assert.match(requestSource, /procurement_chain/);
  assert.match(requestSource, /procurementChainRoute\(selectedRequest/);
  assert.match(requestSource, /等待 PMC 提 PR/);
  assert.match(priceSource, /const contextRequest = computed/);
  assert.match(priceSource, /line\.source_request === contextRequest\.value/);
  assert.match(priceSource, /当前仅查看这张采购申请的完整链路/);
  assert.match(priceSource, /hasPendingPr && !actionable/);
});

test("procurement workbench uses a focused queue, decision summary, formal price review, and docked actions", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  assert.match(source, /审批队列/);
  assert.match(source, /当前审批节点/);
  const priceSummary = source.indexOf("价格决策摘要");
  const demandDetails = source.indexOf("采购需求", priceSummary);
  assert.ok(priceSummary > -1 && demandDetails > priceSummary);
  assert.match(source, /function paymentPlanSummary\(row\)/);
  assert.match(source, /本次审批总额/);
  assert.match(source, /付款安排/);
  assert.match(source, /border-blue-700 bg-blue-700 text-white/);
  assert.match(source, /border-emerald-200 bg-\[#15803d\] text-white/);
  assert.match(source, /价格审批表 V/);
  assert.match(source, /商业条件审批/);
  assert.match(source, /采购报价明细/);
  assert.match(source, /价格审批决策/);
  assert.match(source, /xl:sticky xl:top-3/);
  assert.doesNotMatch(source, /<fieldset :disabled="!showQuoteForm"/);
});

test("procurement demand and price approvals are visually distinct and price approval requires its detail page", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  assert.match(source, /function approvalStageMeta\(row\)/);
  assert.match(source, /label: '需求审批'/);
  assert.match(source, /本次需要审批采购需求/);
  assert.match(source, /label: '价格审批'/);
  assert.match(source, /本次需要审批价格及付款计划/);
  assert.match(source, /审核供应商、物品价格、付款方式和分期付款计划/);
  assert.match(source, /进入价格审批单/);
  assert.match(source, /!isPriceApprovalStep\(selectedRequest\)/);
  assert.match(source, /approvalButtonLabel\(selectedRequest\)/);
});

test('PMC can edit every procurement request at the PMC node while new-material status stays explicit', () => {
  const source = read('../src/pages/PreRequestCenter.vue');
  assert.ok(source.includes('const canPmcModify = computed'));
  assert.ok(source.includes('can_modify_procurement_request'));
  assert.ok(source.includes('const pmcModifyButtonLabel = computed'));
  assert.ok(source.includes("needsPmcMaterial(selectedRequest.value) ? '补充/修改物料' : '修改采购申请'"));
  assert.ok(source.includes('仅当前 PMC 节点的采购申请可进入 PMC 修改'));
});

test('procurement forms support clearing a material number for PMC completion while serial stays generated', () => {
  const source = read('../src/pages/PreRequestCenter.vue');
  assert.match(source, /function clearMaterialSelection\(line\)/);
  assert.match(source, /改为新增物料/);
  assert.match(source, /不绑定物料编号，交由 PMC 补充/);
  assert.match(source, /待 PMC 完善物料编号/);
  assert.match(source, /function categoryPickerCanConfirm\(line\)/);
  assert.match(source, /确认当前物料编号，交由 PMC 后续完善/);
  assert.match(source, /提交后自动生成/);
  assert.match(source, /procurement-pmc-edit/);
});
test("approval actions remain distinct and stale workflow state refreshes automatically", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  const approveGuard = source.indexOf('v-if="selectedCanApprove"');
  const approveAction = source.indexOf("act('approve')");
  const rejectGuard = source.indexOf('v-if="selectedCanReject"');
  const rejectAction = source.indexOf("act('reject')");
  assert.ok(approveGuard > -1 && approveAction > approveGuard);
  assert.ok(rejectGuard > approveAction && rejectAction > rejectGuard);
  assert.match(source, /window\.addEventListener\('focus', refreshRequestsSilently\)/);
  assert.match(source, /document\.addEventListener\('visibilitychange', refreshWhenVisible\)/);
  assert.match(source, /window\.setInterval\(refreshRequestsSilently, 30000\)/);
  assert.match(source, /:disabled="saving" @click="act\('approve'\)"/);
  assert.ok(source.includes('bg-[#15803d]'));
  assert.match(source, /:disabled="saving" @click="act\('reject'\)"/);
});

test("background queue refreshes do not overwrite an in-progress price form", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  assert.match(source, /const hydratedDetailRequestName = ref\(''\)/);
  assert.match(source, /if \(hydratedDetailRequestName\.value === row\.name\) return;/);
  assert.match(source, /hydratedDetailRequestName\.value === row\.name\) return;[\s\S]{0,180}hydrateDraftForm\(row\)/);
  assert.match(source, /hydratedDetailRequestName\.value = ''/);
});


test("PMC edit actions stay visible at the top and are not duplicated below the detail table", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  assert.match(source, /pmcEditMode \? 'sticky top-0 z-30 shadow-sm'/);
  assert.match(source, /仅 PMC 可编辑/);
  assert.match(source, /<div v-if=\"!pmcEditMode\" class=\"flex flex-wrap items-center gap-3 border-t/);
  assert.match(source, /const isUnauthorizedPmcEdit = computed/);
  assert.match(source, /当前账号无 PMC 编辑权限/);
  assert.match(source, /!isMissingInnerRequest && !isUnauthorizedPmcEdit/);
});

test("procurement withdrawal is exposed only through the applicant approval-stage action", () => {
  const source = read("../src/pages/PreRequestCenter.vue");
  assert.match(source, /const requestWithdrawer = createResource\(\{ url: 'rayher_hr_payroll\.api\.oa_entry\.withdraw_request' \}\)/);
  assert.match(source, /const canWithdrawSelected = computed\(\(\) => \{/);
  assert.match(source, /await requestWithdrawer\.submit\(\{ name: selectedRequest\.value\.name, note \}\)/);
  assert.match(source, /撤回申请/);
  assert.match(source, /编辑并重新提交/);
  assert.match(source, /business_status === '已撤回'/);
});
