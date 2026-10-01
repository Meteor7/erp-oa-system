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
// 采购申请 / 购买申请页面（2026-09-30 改版）：旧的 PreRequestCenter.vue 只剩一层壳，页面在 components/procurement 下。
const part = (name) => read(`../src/components/procurement/${name}.vue`);
const workbench = part("ProcurementWorkbench");
const detail = part("ProcDetail");
const form = part("ProcForm");
const editor = part("ProcLineEditor");
const documents = part("ProcDocuments");
const home = part("ProcHome");
const view = read("../src/lib/procurementView.js");

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
  // 两种申请都选固定 / 非固定资产；固定资产类别（三选一）只有购买申请出现，采购申请没有。
  assert.match(form, /aria-label="资产属性"/);
  assert.match(form, /<div v-if="!isProcurement && form\.asset_nature === '固定资产'" class="f">/);
  assert.match(form, /v-for="item in FIXED_ASSET_CATEGORIES"/);
  assert.match(view, /FIXED_ASSET_CATEGORIES = Object\.freeze\(\[/);
  assert.doesNotMatch(form, /fixedCategories/);
});

test('purchase application does not auto-load the procurement material catalog', () => {
  assert.match(form, /procurement_materials\.list_categories/);
  assert.match(form, /async function loadCategories\(\) \{\s*if \(!isProcurement\) return;/);
  assert.doesNotMatch(form, /list_categories[^\n]+auto: true/);
  assert.match(form, /<ProcLineEditor\s+v-if="isProcurement"/);
  assert.match(form, /<div v-else class="pr-lines">/);
});

test("forms use real project options and conditional business fields", () => {
  assert.match(workbench, /oa_entry\.list_approval_center_projects/);
  assert.match(workbench, /oa_entry\.list_procurement_users/);
  assert.match(workbench, /oa_entry\.list_procurement_applicants/);
  assert.match(workbench, /oa_entry\.get_options/);
  assert.doesNotMatch(form, /project_entry\.list_project_owners/);
  assert.match(detail, /view: 'all'/);
  assert.match(form, /<select v-model="form\.project"/);
  assert.match(form, /form\.procurement_scope === '项目采购'/);
  assert.match(form, /non_project_allocation_type/);
  assert.match(form, /purchase_method/);
  assert.match(documents, /remove_approval_business_document/);
  assert.match(documents, /attach_approval_business_document/);
  assert.match(editor, /按分类逐级选择物料编号/);
  assert.match(editor, /选择一级分类/);
  assert.match(editor, /没有下一级时可停在当前级/);
  assert.match(editor, /categoryChildren/);
  assert.match(editor, /catMaterials/);
  assert.match(editor, /loadCatMaterials/);
  assert.match(editor, /选择物料编号/);
  assert.match(editor, /closePicker\(line\)/);
  assert.match(view, /startsWith\(`\$\{code\}\.`\)/);
  assert.match(view, /const inferred = /);
  assert.match(editor, /名称、规格等自动带出、不能改/);
  assert.match(form, /validateRequestForm/);
  assert.match(view, /validateProcurementRequestForm/);
  assert.match(form, /watch\(form, \(\) => \{/);
  // 采购经办人由系统默认指定，表单里只读
  assert.match(form, /if \(!form\.purchaser_user && ctx\.purchasers\.length\)/);
  assert.doesNotMatch(form, /<select v-model=['"]form\.purchaser_user/);
});

test("the procurement pages no longer carry payment, price or contract screens", () => {
  const all = [workbench, detail, form, editor, documents, home, part("ProcList"), part("PurchaseHome")].join("\n");
  assert.doesNotMatch(all, /isPayment|paymentSources|source_payment_plan_row|list_procurement_payment_sources/);
  assert.doesNotMatch(all, /save_procurement_contract_information|review_procurement_contract|seal_procurement_contract|submit_procurement_quote/);
  assert.doesNotMatch(all, /record_arrival|record_inspection|writeoff_prepayment|complete_supplier_refund|close_procurement/);
  assert.match(view, /name: 'procurement-price-approvals'/);
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
  assert.match(documents, /const name = props\.request/);
  assert.match(documents, /requested = name/);
  assert.match(documents, /if \(requested === name\) docs\.value = rows/);
  assert.match(documents, /list_approval_business_documents', \{ request: name \}/);
});

test("approvers see procurement decision data before the progress and attachments", () => {
  const template = detail.slice(detail.indexOf("<template>"));
  const facts = template.indexOf("需求信息");
  const lines = template.indexOf("物料明细", facts);
  const progress = template.indexOf("审批进度", lines);
  const attachments = template.indexOf("<ProcDocuments", progress);
  const log = template.indexOf("操作记录", attachments);
  assert.ok(facts > -1);
  assert.ok(lines > facts);
  assert.ok(progress > lines);
  assert.ok(attachments > progress);
  assert.ok(log > attachments);
  assert.match(detail, /row\.employee_name/);
  assert.match(detail, /row\.department/);
  assert.match(view, /row\?\.reason/);
  assert.match(view, /row\?\.expected_delivery_date/);
  assert.match(view, /row\?\.procurement_scope/);
  for (const field of ["line.item_name", "line.specification", "line.quantity", "line.unit", "line.remarks"]) assert.ok(detail.includes(field), field);
  assert.match(detail, /row\.value\?\.operation_log/);
});

test("home links to separate new-request pages and the form is its own route", () => {
  assert.match(home, /ctx\.goNew\(\)/);
  assert.match(workbench, /name: isProcurement\.value \? 'procurement-new' : 'direct-purchase-new'/);
  assert.match(workbench, /router\.push\(\{ name: 'procurement-pmc-edit', params: \{ name \} \}\)/);
  assert.match(form, /route\.name === 'procurement-pmc-edit'/);
});

test("a new form starts blank and only saved drafts get attachments", () => {
  assert.match(form, /const draftName = ref\(isPmc \? '' : String\(route\.query\.draft \|\| ''\)\)/);
  assert.match(form, /<ProcDocuments v-if="draftName \|\| isPmc"/);
  assert.match(form, /const form = reactive\(blankForm\(\)\)/);
});

test("procurement OA links keep PR, price approval, and PO in one scoped chain", () => {
  assert.match(view, /procurement_chain/);
  assert.match(view, /export function chainRoute/);
  assert.match(detail, /chainRoute\(current\)/);
  assert.match(view, /等待提 PR/);
  assert.match(view, /relatedDocuments/);
  assert.match(detail, /can_view_procurement_po/);
});

test("procurement detail shows who is waiting, the stage strip and role aware primary actions", () => {
  assert.match(detail, /pr-strip/);
  assert.match(detail, /chainStrip\(row\.value\)/);
  assert.match(detail, /<span class="muted">\{\{ isProcurement \? '物料' : '预计金额' \}\}<\/span>/);
  assert.match(view, /轮到你审批/);
  assert.match(view, /审批中：当前在/);
  assert.match(view, /function approvalButtonLabel/);
  assert.match(view, /需求审批通过/);
  assert.match(view, /function approveBlocker/);
  assert.match(detail, /:disabled="ctx\.busy \|\| Boolean\(blocker\)"/);
});

test('PMC can edit every procurement request at the PMC node while new-material status stays explicit', () => {
  assert.match(view, /can_modify_procurement_request/);
  assert.match(view, /export function canMaintainLines/);
  assert.match(view, /'补充\/修改物料' : '修改采购申请'/);
  assert.match(detail, /canMaintainLines\(row\.value\)/);
  assert.match(form, /当前账号没有 PMC 编辑权限/);
  assert.match(form, /modify_procurement_request/);
});

test('procurement forms support clearing a material number for PMC completion while serial stays generated', () => {
  assert.match(editor, /function unbind\(line\)/);
  assert.match(editor, /改为新增物料/);
  assert.match(editor, /不绑定物料编号，交由 PMC 补充/);
  assert.match(editor, /待 PMC 完善/);
  assert.match(editor, /function canConfirm\(line\)/);
  assert.match(editor, /确认当前物料编号，交由 PMC 后续完善/);
  assert.match(detail, /提交后自动生成/);
  assert.match(view, /procurement-pmc-edit/);
  assert.match(view, /material_serial: line\.material_serial/);
});

test("approval actions remain distinct and stale workflow state refreshes automatically", () => {
  const approveGuard = detail.indexOf('v-if="canApprove"');
  const approveAction = detail.indexOf("act('approve')");
  const rejectGuard = detail.indexOf('v-if="canReject"');
  const rejectAction = detail.indexOf("act('reject')");
  assert.ok(approveGuard > -1 && approveAction > approveGuard);
  assert.ok(rejectGuard > -1 && rejectAction > rejectGuard);
  assert.match(workbench, /window\.addEventListener\('focus', refreshSilently\)/);
  assert.match(workbench, /document\.addEventListener\('visibilitychange', refreshWhenVisible\)/);
  assert.match(workbench, /window\.setInterval\(refreshSilently, 30000\)/);
  assert.match(detail, /await load\(\{ silent: true \}\)/);
});

test("background refreshes do not wipe what the approver is typing", () => {
  // 审批意见、驳回原因、撤回原因都是单独的 ref，刷新只换单据；换单据时才清空。
  assert.match(detail, /const note = ref\(''\)/);
  assert.match(detail, /const rejectReason = ref\(''\)/);
  assert.match(detail, /watch\(name, \(\) => \{ withdrawOpen\.value = false; note\.value = ''; rejectReason\.value = ''; load\(\); \}/);
  assert.match(workbench, /if \(refreshing \|\| busy\.value \|\| !\['home', 'list', 'detail'\]\.includes\(view\.value\)\) return;/);
});

test("PMC edit page keeps one save button and explains missing or forbidden requests", () => {
  assert.match(form, /保存修改/);
  assert.equal(form.split("@click=\"savePmc\"").length - 1, 1);
  assert.match(form, /采购申请不存在或已被删除/);
  assert.match(form, /problem\.value = 'forbidden'/);
  assert.match(form, /只有 PMC 在 PMC 节点能改/);
});

test("procurement withdrawal is exposed only through the applicant approval-stage action", () => {
  assert.match(detail, /oa_entry\.withdraw_request/);
  assert.match(view, /export function canWithdrawRow/);
  assert.match(view, /if \(!isActive\(row\)\) return false;/);
  assert.match(detail, /撤回申请/);
  assert.match(detail, /编辑并重新提交/);
  assert.match(detail, /撤回原因（可选）/);
  assert.match(detail, /const canResume = computed\(\(\) => row\.value\?\.workflow_status === '草稿' && ownDraft\.value\)/);
});
