import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const page = read('../src/pages/PreRequestCenter.vue');
const workbench = read('../src/components/procurement/ProcurementWorkbench.vue');
const home = read('../src/components/procurement/ProcHome.vue');
const purchaseHome = read('../src/components/procurement/PurchaseHome.vue');
const list = read('../src/components/procurement/ProcList.vue');
const detail = read('../src/components/procurement/ProcDetail.vue');
const form = read('../src/components/procurement/ProcForm.vue');
const editor = read('../src/components/procurement/ProcLineEditor.vue');
const catalog = read('../src/components/procurement/ProcCatalogTools.vue');
const documents = read('../src/components/procurement/ProcDocuments.vue');
const progress = read('../src/components/MaterialExecutionProgress.vue');
const view = read('../src/lib/procurementView.js');
const css = read('../src/styles/procurementUi.css');
const all = [workbench, home, purchaseHome, list, detail, form, editor, catalog, documents].join('\n');

test('the old page is a thin wrapper that picks the request type from the route path', () => {
  assert.ok(page.split('\n').length < 40);
  assert.match(page, /ProcurementWorkbench/);
  assert.match(page, /requestTypeForPath\(route\.path\)/);
  assert.match(view, /startsWith\('\/approval\/direct-purchase'\)/);
  assert.doesNotMatch(page, /isPayment|isPriceInnerPage|isContractInnerPage/);
  assert.doesNotMatch(all, /isPayment|isPriceInnerPage|isContractInnerPage|record_arrival|record_inspection|register_contract_delivery|save_procurement_contract_information|seal_procurement_contract|submit_procurement_quote/);
});

test('views are chosen by route query like ClaimWorkbench: home, list, detail; new and PMC edit are routes', () => {
  assert.match(view, /query\.request\) return 'detail'/);
  assert.match(view, /query\.view === 'list'\) return 'list'/);
  assert.match(view, /procurement-pmc-edit/);
  assert.match(view, /procurement-new/);
  assert.match(view, /direct-purchase-new/);
  assert.match(workbench, /procurementView\(route\)/);
  for (const component of ['ProcHome', 'PurchaseHome', 'ProcList', 'ProcDetail', 'ProcForm']) assert.match(workbench, new RegExp(component));
  assert.match(workbench, /refreshSilently/);
  assert.match(workbench, /addEventListener\('focus'/);
  assert.match(workbench, /visibilitychange/);
  assert.match(workbench, /setInterval\(refreshSilently, 30000\)/);
  assert.match(workbench, /procurement-new/);
  assert.match(workbench, /procurement-pmc-edit/);
});

test('queues: mine + pending merged and de-duplicated, view=all only for global procurement access, client side filters', () => {
  assert.match(home, /procurement_global_access|globalAccess/);
  assert.match(workbench, /procurement_global_access/);
  assert.match(list, /listFor\('mine'\), listFor\('pending'\), ctx\.globalAccess \? listFor\('all'\)/);
  assert.match(list, /mergeRows\(ctx\.requestType, data\.mine, data\.pending\)/);
  assert.match(list, /LIST_LIMIT/);
  assert.match(view, /LIST_LIMIT = 200/);
  assert.match(view, /PAGE_SIZE = 50/);
  assert.match(list, /最近 \{\{ LIST_LIMIT \}\} 张/);
  assert.match(list, /每页 \{\{ PAGE_SIZE \}\} 张/);
  for (const label of ['全部阶段', '全部项目', '加急']) assert.match(list, new RegExp(label));
  assert.match(list, /filterRows\(base\.value, filters, ctx\.projectName\)/);
  assert.doesNotMatch(list, /PO 金额/);
  for (const column of ['申请人', '项目 / 归属', '物料', '阶段', '当前在哪', '等待']) assert.match(list, new RegExp(column));
});

test('home shows the stage strip only for global roles and groups non-OA work with tolerant calls', () => {
  assert.match(home, /v-if="ctx\.globalAccess" class="panel"/);
  assert.match(home, /stageDistribution/);
  assert.match(home, /material_progress\.list_material_progress/);
  assert.match(home, /procurement_chain\.list_prs/);
  assert.match(home, /procurement_chain\.list_price_approvals/);
  assert.match(home, /procurement_chain\.list_payment_work_items/);
  assert.match(home, /loadPurchaseOrders/);
  assert.match(home, /settle\(/);
  assert.match(home, /canCreatePr\(\)/);
  assert.match(home, /canEditPrice\(\)/);
  assert.match(home, /isViceManager\(\)/);
  assert.match(home, /canOpenBoard\(\)/);
  assert.match(home, /canSeePrice\(\)/);
});

test('detail keeps every old action with the new role-aware rules', () => {
  for (const api of ['oa_entry.action_request', 'oa_entry.withdraw_request']) assert.match(detail, new RegExp(api.replace('.', '\\.')));
  assert.match(detail, /expected_step_key/);
  assert.match(detail, /reject_target/);
  assert.match(detail, /canActOn\(row\.value, acted/);
  assert.match(detail, /acted\[current\.name\] = currentStepKey\(current\)/);
  assert.match(detail, /rejection_targets/);
  assert.match(detail, /请填写驳回原因/);
  assert.match(detail, /approvalButtonLabel\(row\)/);
  assert.match(detail, /:disabled="ctx\.busy \|\| Boolean\(blocker\)"/);
  assert.match(detail, /canMaintainLines\(row\.value\)/);
  assert.match(detail, /pmcButtonLabel\(row\)/);
  assert.match(detail, /编辑并重新提交/);
  assert.match(detail, /撤回原因（可选）/);
  assert.doesNotMatch(all, /window\.(prompt|confirm)/);
  assert.match(detail, /MaterialExecutionProgress/);
  assert.match(detail, /showExec/);
  assert.match(detail, /relatedDocuments\(row\.value/);
  assert.match(detail, /canOpenBoard\(\)/);
  assert.match(detail, /can_view_procurement_po/);
  assert.match(detail, /operation_log/);
  assert.match(detail, /ProcDocuments/);
  for (const text of ['需求信息', '物料明细', '购买明细', '审批进度', '关联单据', '操作记录', 'PO 与付款计划']) assert.match(detail, new RegExp(text));
  for (const field of ['product_desc', 'product_name', 'product_desc_en', 'brand_en', 'remarks', 'material_serial', 'category_path']) assert.match(detail, new RegExp(field));
});

test('documents: upload, list, void with an inline reason, copy-to recipients', () => {
  for (const api of ['list_approval_business_documents', 'attach_approval_business_document', 'remove_approval_business_document']) assert.match(documents, new RegExp(api));
  assert.match(documents, /documentChecklistForRequest/);
  assert.match(documents, /作废原因/);
  assert.match(documents, /copiedToLabels/);
  assert.match(documents, /需求附件/);
  assert.match(documents, /upload_file/);
});

test('form: header fields, draft save and submit with preflight and validation', () => {
  for (const api of ['save_approval_center_draft', 'submit_approval_center_draft', 'modify_procurement_request', 'preview_route']) assert.match(form, new RegExp(api));
  for (const text of ['organizationPreflightMessage', 'validateRequestForm', 'buildApprovalCenterPayload', 'canSubmitForOthers', 'FIXED_ASSET_CATEGORIES', 'purchase_method', 'asset_nature', 'procurement_scope', 'non_project_allocation_type', 'non_project_cost_center', 'non_project_department', 'purchaser_user']) assert.match(form, new RegExp(text));
  assert.doesNotMatch(form, /fixedCategories/);
  assert.match(form, /采购经办人/);
  assert.match(form, /申请说明/);
  assert.match(form, /expected_delivery_date: form\.expected_delivery_date/);
  assert.match(form, /reason: form\.reason/);
  assert.match(form, /subject: form\.subject/);
  assert.match(form, /pmcLines\(form\.business_lines\)/);
  assert.match(form, /canMaintainCatalog\(\)/);
  assert.match(form, /ProcCatalogTools/);
  assert.match(form, /suggest_material/);
  assert.match(form, /京东购买/);
  assert.match(form, /其他购买/);
  assert.match(view, /办公家具、工具及器具/);
  assert.match(view, /电子设备、研发专用设备、仪器仪表/);
  assert.match(view, /生产设备、生产工具及器具/);
});

test('line editor: catalog search, category tree, three-level confirm, bind existing, switch to new material', () => {
  for (const api of ['procurement_materials.list_materials', 'procurement_materials.list_categories']) assert.match(`${editor}\n${form}`, new RegExp(api.replace('.', '\\.')));
  for (const text of ['确认当前物料编号，交由 PMC 后续完善', '改为新增物料', '不绑定物料编号，交由 PMC 补充', '绑定 ', '查重复', '分类建议', '更多']) assert.match(editor, new RegExp(text));
  for (const field of ['material_code', 'item_name', 'specification', 'brand', 'quantity', 'unit', 'product_desc', 'product_name', 'product_desc_en', 'brand_en', 'remarks']) assert.match(editor, new RegExp(field));
  assert.match(catalog, /procurement_materials\.save_category/);
  assert.match(catalog, /procurement_materials\.save_material/);
});

test('price and supplier only render for roles that may see them; applicants get quantity level progress', () => {
  assert.match(progress, /canSeeProcurementPrice\(\) \|\| canSeeProcurementPO\(\)/);
  assert.match(progress, /v-if="insider && priceOf\(order, line\)"/);
  assert.match(progress, /defineProps\(\{ request: \{ type: String, required: true \}, sourceLine: \{ type: String, default: '' \}, expanded: \{ type: Boolean, default: false \} \}\)/);
  assert.match(progress, /material_execution\.get_progress/);
  assert.doesNotMatch(detail, /price_snapshot/);
  assert.match(detail, /v-if="showExec && poRows\.length"/);
  assert.match(detail, /const insider = isInsider\(\)/);
});

test('styles are scoped under .xp and prefixed pr-', () => {
  const selectors = css.split('\n').filter((rule) => /^[.@]/.test(rule) && !rule.startsWith('@media') && !rule.startsWith('@keyframes'));
  for (const rule of selectors) assert.match(rule, /^\.xp[ .]/, rule);
  assert.match(css, /\.xp \.pr-strip/);
  assert.match(css, /overflow-x: auto/);
});
