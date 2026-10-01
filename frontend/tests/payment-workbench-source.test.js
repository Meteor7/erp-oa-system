import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const dir = new URL('../src/components/payment/', import.meta.url);
const component = (name) => read(`../src/components/payment/${name}`);
const allSources = () => readdirSync(dir).filter((f) => f.endsWith('.vue') || f.endsWith('.js')).map((f) => [f, component(f)]);

const page = read('../src/pages/PaymentCenter.vue');
const workbench = component('PaymentWorkbench.vue');
const workTab = component('PayWorkTab.vue');
const fulfilment = component('PayFulfilmentPanel.vue');
const card = component('PayInstallmentCard.vue');
const approvalsTab = component('PayApprovalsTab.vue');
const approvalPage = component('PayApprovalPage.vue');
const documents = component('PayDocuments.vue');
const legacy = component('PayLegacyActions.vue');
const view = read('../src/lib/paymentView.js');
const css = read('../src/styles/paymentUi.css');

test('the route page is a thin wrapper around the payment workbench', () => {
  assert.match(page, /import PaymentWorkbench from '\.\.\/components\/payment\/PaymentWorkbench\.vue'/);
  assert.match(page, /<PaymentWorkbench \/>/);
  assert.ok(page.split('\n').length < 20);
});

test('workbench keeps the two tabs, the PO-view gating and the query-driven views', () => {
  assert.match(workbench, /const canWork = canSeeProcurementPO\(\)/);
  assert.match(workbench, /canRecordPoFulfilment/);
  assert.match(workbench, /canEditProcurementPrice/);
  assert.match(workbench, /v-if="canWork"/);
  assert.match(workbench, /付款工作项/);
  assert.match(workbench, /付款审批单/);
  assert.match(workbench, /list_payment_work_items/);
  assert.match(workbench, /rayher_hr_payroll\.api\.oa_entry\.|OA_API \+ 'get_options'/);
  assert.match(workbench, /route\.query\.request/);
  assert.match(workbench, /tab: 'approvals'/);
  assert.match(workbench, /查看 PO 与合同/);
  // 30 秒 + 窗口获得焦点 + 页面重新可见时刷新
  assert.match(workbench, /setInterval\(refreshAll, 30000\)/);
  assert.match(workbench, /addEventListener\('focus'/);
  assert.match(workbench, /visibilitychange/);
  assert.match(workbench, /removeEventListener\('focus'/);
  assert.match(workbench, /import '\.\.\/\.\.\/styles\/paymentUi\.css'/);
  assert.match(workbench, /class="xp pay-root"/);
});

test('work items tab: presets, per-PO list, push to approval and jump to the new OA', () => {
  assert.match(workTab, /route\.query\.status/);
  assert.match(workTab, /route\.query\.po/);
  assert.match(workTab, /STATUS_FILTERS/);
  assert.match(workTab, /push_po_payment_request/);
  assert.match(workTab, /payment_plan_row: view\.planRow/);
  assert.match(workTab, /emit\('open-request', result\.payment_request\)/);
  assert.match(workTab, /已生成采购付款/);
  assert.match(workTab, /PayFulfilmentPanel/);
  assert.match(workTab, /PayInstallmentCard/);
  assert.match(workTab, /搜索 PO、供应商、期次/);
  assert.match(workTab, /有待办的排前面/);
  assert.match(workTab, /REFUND_NOTICE/);
  assert.match(view, /退款需线下与供应商、财务处理，系统暂不记录/);
});

test('fulfilment panel registers arrival, inspection, exchange arrival and return with evidence', () => {
  for (const endpoint of ['record_po_receipt', 'record_po_inspection', 'record_po_exchange_receipt', 'record_po_return']) {
    assert.match(fulfilment, new RegExp(`PROCUREMENT_API \\+ '${endpoint}'`), endpoint);
  }
  assert.match(fulfilment, /uploadEvidence/);
  assert.match(fulfilment, /validateFulfilment/);
  assert.match(fulfilment, /buildFulfilmentRequest/);
  assert.match(fulfilment, /fulfilmentModes/);
  assert.match(fulfilment, /canFulfil/);
  assert.match(fulfilment, /一次到齐，不分批/);
  assert.match(fulfilment, /到货、验收、换货、退货记录（只增不改/);
  assert.match(fulfilment, /emit\('changed'\)/);
  for (const label of ['登记到货', '登记验收', '登记换货到货', '登记退货发出']) assert.match(view, new RegExp(label), label);
  assert.match(view, /换货、退货必须写原因/);
  assert.match(view, /暂不支持分批到货/);
  // 上传走私有文件接口，登记接口拿 file_ref
  const api = component('paymentApi.js');
  assert.match(api, /\/api\/method\/upload_file/);
  assert.match(api, /is_private/);
  assert.match(api, /X-Frappe-CSRF-Token/);
  assert.match(view, /file_ref: meta\.fileRef/);
});

test('installment cards show the gates, the trigger text, blockers and who is awaited', () => {
  assert.match(card, /PayGateGrid/);
  assert.match(card, /view\.trigger/);
  assert.match(card, /触发条件/);
  assert.match(card, /view\.blockers/);
  assert.match(card, /当前阻塞/);
  assert.match(card, /view\.waitFor/);
  assert.match(card, /view\.regressionText/);
  assert.match(card, /view\.draftText/);
  assert.match(card, /view\.canPush/);
  assert.match(card, /提交付款审批/);
  assert.match(card, /看付款审批单/);
  const grid = component('PayGateGrid.vue');
  assert.match(grid, /tile\.k/);
  for (const text of ['合同已生效', '全部到货', '验收通过']) assert.match(view, new RegExp(text), text);
  for (const text of ['等生产主管登记到货', '等生产主管登记验收', '等供应商换货到货', '等退货发出 / 供应商补发', '等采购提交付款审批']) assert.match(view, new RegExp(text), text);
  assert.match(view, /审批过程中条件已回退/);
  assert.match(view, /已退回，存在草稿/);
});

test('approvals tab keeps queue views, paging, exact lookup and auto refresh', () => {
  assert.match(approvalsTab, /list_requests/);
  assert.match(approvalsTab, /request_type: PAYMENT_REQUEST_TYPE/);
  for (const v of ['mine', 'pending', 'all']) assert.match(approvalsTab, new RegExp(`params\\('${v}'\\)`), v);
  assert.match(approvalsTab, /const pageSize = 50/);
  assert.match(approvalsTab, /procurement_global_access/);
  assert.match(approvalsTab, /if \(globalAccess\.value\) await allLoader\.reload\(\)/);
  assert.match(approvalsTab, /exactLoader\.fetch\(\{ view: 'all'/);
  assert.match(approvalsTab, /route\.query\.request/);
  assert.match(approvalsTab, /30000/);
  assert.match(approvalsTab, /正在读取申请和待办/);
  assert.match(approvalsTab, /业务单据加载失败/);
  assert.match(approvalsTab, /上一页/);
  assert.match(approvalsTab, /下一页/);
  assert.doesNotMatch(approvalsTab, /Loader[^\n]+auto: true/);
});

test('approval page: approve / reject with step guard, withdraw, five-step route, live review', () => {
  assert.match(approvalPage, /action_request/);
  assert.match(approvalPage, /expected_step_key: props\.request\.current_step_key/);
  assert.match(approvalPage, /params\.reject_target = rejectTarget\.value/);
  assert.match(approvalPage, /validateReject/);
  assert.match(approvalPage, /驳回原因/);
  assert.match(approvalPage, /审批意见（可选）/);
  assert.match(approvalPage, /withdraw_request/);
  assert.match(approvalPage, /撤回原因（可选）/);
  assert.match(approvalPage, /确认撤回/);
  assert.match(approvalPage, /approveLabel/);
  assert.match(view, /'确认付款'/);
  assert.match(view, /'办理完成'/);
  assert.match(view, /总经理付款/);
  assert.match(approvalPage, /本期付款条件复核/);
  assert.match(approvalPage, /liveReview/);
  assert.match(approvalPage, /PO 物料与到货验收进度/);
  assert.match(approvalPage, /付款来源/);
  assert.match(approvalPage, /审批进度/);
  assert.match(approvalPage, /操作记录/);
  assert.match(approvalPage, /PayDocuments/);
  assert.match(approvalPage, /PayRecordList/);
  assert.match(approvalPage, /去看到货与验收/);
});

test('business documents: list / attach / remove with the reason typed inline', () => {
  assert.match(documents, /list_approval_business_documents/);
  assert.match(documents, /attach_approval_business_document/);
  assert.match(documents, /remove_approval_business_document/);
  assert.match(documents, /poPaymentChecklist/);
  assert.match(documents, /legacyChecklist/);
  assert.match(documents, /作废原因/);
  assert.match(documents, /上传补充资料/);
  assert.match(documents, /报价和合同属于 PO/);
  assert.match(view, /付款前提供/);
});

test('legacy 采购付款 without a source PO keeps the old lifecycle, PO payments never show it', () => {
  for (const endpoint of ['record_arrival', 'record_inspection', 'record_prepayment_followup', 'complete_supplier_refund', 'writeoff_prepayment', 'close_procurement']) {
    assert.match(legacy, new RegExp(`OA_API \\+ '${endpoint}'`), endpoint);
  }
  for (const label of ['登记到货', '登记验收', '记录跟进', '确认供应商退款', '预付款核销', '关闭采购']) assert.match(legacy, new RegExp(label), label);
  assert.match(legacy, /legacyActions/);
  assert.match(view, /canManageExpense/);
  assert.match(view, /if \(isPoSourced\(request\)\) return \{ show: false \}/);
  for (const fn of ['canRecordArrival', 'canRecordInspection', 'canWriteoffPrepayment', 'canCompleteSupplierRefund', 'canCloseProcurement']) assert.match(view, new RegExp(fn), fn);
  assert.match(approvalsTab, /can_manage_expense/);
});

test('no browser dialogs, emoji or hard-coded names in the payment UI', () => {
  for (const [name, source] of allSources()) {
    assert.doesNotMatch(source, /window\.(prompt|confirm|alert)\(/, name);
    assert.doesNotMatch(source, /\b(prompt|confirm)\(/, name);
    assert.doesNotMatch(source, /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u, name);
    for (const person of ['演示员工241', '何静', '演示员工16', '演示员工19', '演示员工21', '演示员工29', '演示员工32']) assert.ok(!source.includes(person), `${name} ${person}`);
  }
  assert.doesNotMatch(view, /演示员工241|何静|演示员工16/);
});

test('api calls go through createResource and errors through frappeError', () => {
  for (const [name, source] of allSources()) {
    if (name.endsWith('.vue') && /createResource\(/.test(source)) assert.match(source, /import \{[^}]*createResource[^}]*\} from 'frappe-ui'/, name);
    assert.doesNotMatch(source, /axios/, name);
  }
  assert.match(component('paymentApi.js'), /extractFrappeError/);
});

test('payment styles stay under .xp and use the pay- prefix', () => {
  const selectors = css.replace(/\/\*[\s\S]*?\*\//g, '').split('{').slice(0, -1).map((chunk) => chunk.split('}').pop().trim()).filter(Boolean);
  assert.ok(selectors.length > 20);
  for (const group of selectors) {
    if (group.startsWith('@media')) continue;
    for (const selector of group.split(',').map((s) => s.trim())) {
      assert.ok(selector.startsWith('.xp'), selector);
      assert.ok(/\.xp\.pay-|\.xp \.pay-|\.xp\s+\.banner\.pay-/.test(selector), selector);
    }
  }
});

test('the fulfilment success note survives the automatic switch to the next registration type', () => {
  assert.match(fulfilment, /function selectMode\(key\) \{ mode\.value = key; ok\.value = ''; \}/);
  assert.match(fulfilment, /@click="selectMode\(item\.key\)"/);
  assert.doesNotMatch(fulfilment, /watch\(mode, \(\) => \{[^}]*ok\.value/);
});
