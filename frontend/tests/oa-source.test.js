import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const routerSource = readFileSync(new URL('../src/router.js', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
const accessSource = readFileSync(new URL('../src/lib/access.js', import.meta.url), 'utf8');
const pageSource = readFileSync(new URL('../src/pages/OAApprovals.vue', import.meta.url), 'utf8');
const workbenchSource = readFileSync(new URL('../src/components/ExpenseWorkbench.vue', import.meta.url), 'utf8');
const uploadSource = readFileSync(new URL('../src/components/invoice/InvoiceUploadWorkbench.vue', import.meta.url), 'utf8');
const invoiceLibSource = readFileSync(new URL('../src/lib/invoiceOcr.js', import.meta.url), 'utf8');
const apiSource = readFileSync(new URL('../../rayher_hr_payroll/api/oa_entry.py', import.meta.url), 'utf8');
const invoiceApiSource = readFileSync(new URL('../../rayher_hr_payroll/api/invoice_entry.py', import.meta.url), 'utf8');

const C = {
  upload: '\u4e0a\u4f20\u53d1\u7968',
  flow: '\u8d39\u7528\u62a5\u9500\u6d41',
  statistics: '\u8d39\u7528\u7edf\u8ba1',
  audit: '\u5ba1\u6279\u8bb0\u5f55',
  viewInvoice: '\u67e5\u770b\u53d1\u7968',
  noInvoiceReason: '\u65e0\u7968\u539f\u56e0',
  withdrawRequest: '\u64a4\u56de\u7533\u8bf7',
  withdrawPayment: '\u64a4\u56de\u4ed8\u6b3e',
};
const sevenFields = [
  '\u53d1\u7968\u7c7b\u522b', '\u9879\u76ee\u540d\u79f0', '\u5f00\u7968\u65e5\u671f',
  '\u53d1\u7968\u53f7\u7801', '\u7a0e\u524d\u91d1\u989d', '\u7a0e\u989d', '\u5408\u8ba1\u91d1\u989d',
];
const removedViews = [
  '\u4e3b\u770b\u677f', '\u5b50\u770b\u677f', '\u6d88\u8d39\u660e\u7ec6\u770b\u677f',
  '\u5ba1\u6279\u6d41\u914d\u7f6e',
];

test('rayher SPA registers split approval pages', () => {
  assert.match(routerSource, /path:\s*['"]\/approval\/leave['"]/);
  assert.match(routerSource, /path:\s*['"]\/approval\/purchase['"]/);
  assert.match(routerSource, /path:\s*['"]\/oa['"],\s*redirect:\s*['"]\/approval\/leave['"]/);
  assert.match(accessSource, /['"]\/approval\/leave['"]/);
  assert.match(accessSource, /['"]\/approval\/purchase['"]/);
  assert.match(appSource, /\\u5ba1\\u6279/);
  assert.match(appSource, /\\u8bf7\\u5047\\u5ba1\\u6279/);
  assert.match(appSource, /\\u8d39\\u7528\\u4ed8\\u6b3e\/\\u62a5\\u9500/);
});

test('approval page keeps leave behavior and delegates expense reimbursement to its workbench', () => {
  assert.match(pageSource, /useRoute/);
  assert.match(pageSource, /PAGE_CONFIG/);
  assert.match(pageSource, /\/approval\/leave/);
  assert.match(pageSource, /\/approval\/purchase/);
  assert.match(pageSource, /request_type:\s*currentRequestType\.value/);
  assert.match(pageSource, /<ExpenseWorkbench\s+v-else\s*\/>/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.preview_route/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.create_request/);
  assert.doesNotMatch(pageSource, /<select\s+v-model='form\.request_type'/);
});

test('expense workbench exposes four focused expense pages', () => {
  for (const label of [C.upload, C.flow, C.statistics, C.audit]) {
    assert.ok(workbenchSource.includes(label), `missing expense page: ${label}`);
  }
  assert.match(workbenchSource, /InvoiceUploadWorkbench/);
  assert.match(workbenchSource, /ExpenseStatistics/);
  assert.match(workbenchSource, /ExpenseApprovalRecords/);
  assert.match(workbenchSource, /activeView === 'statistics'/);
  assert.match(workbenchSource, /activeView === 'audit'/);
  assert.match(workbenchSource, /@open-request="openRequest"/);
  assert.match(workbenchSource, /STATUS_COLUMNS/);
  assert.match(workbenchSource, /grid-cols-5/);
  for (const label of removedViews) assert.ok(!workbenchSource.includes(label), `removed view remains: ${label}`);
});

test('report rows load an exact permission-scoped request detail', () => {
  assert.match(workbenchSource, /const requestDetail = createResource/);
  assert.match(workbenchSource, /view:\s*'all'/);
  assert.match(workbenchSource, /limit:\s*1/);
  assert.match(workbenchSource, /request_type:\s*REQUEST_TYPE/);
  assert.match(workbenchSource, /name:\s*detailRequestName\.value/);
  assert.match(workbenchSource, /async function openRequest\(name\)/);
  assert.match(workbenchSource, /requestDetail\.reload/);
  assert.ok(workbenchSource.includes('\u65e0\u6743\u9650\u6216\u5355\u636e\u4e0d\u5b58\u5728'));
});

test('upload page supports batch upload confirmation pushdown and private preview', () => {
  assert.match(uploadSource, /type="file"/);
  assert.match(uploadSource, /multiple/);
  assert.match(uploadSource, /accept="\.pdf,\.jpg,\.jpeg,\.png"/);
  assert.match(uploadSource, /uploadFiles/);
  assert.match(uploadSource, /confirmInvoice/);
  assert.match(uploadSource, /unconfirmInvoice/);
  assert.match(uploadSource, /pushInvoices/);
  assert.doesNotMatch(uploadSource, /withdrawInvoicePush/);
  assert.match(workbenchSource, /withdrawInvoicePush/);
  assert.match(uploadSource, /InvoicePreviewDrawer/);
  assert.doesNotMatch(uploadSource, /download\s*=|target="_blank"/);
  assert.match(invoiceLibSource, /\/api\/method\/upload_file/);
  assert.match(uploadSource, /selectionReason\(row\)/);
  assert.match(uploadSource, /:title="selectionReason\(row\)"/);
  assert.ok(uploadSource.includes('\u53ef\u4e0b\u63a8'));
});

test('OCR details and manual rows preserve their required fields', () => {
  for (const label of sevenFields) {
    assert.ok(uploadSource.includes(label), `upload page missing field: ${label}`);
    assert.ok(workbenchSource.includes(label), `reimbursement page missing field: ${label}`);
  }
  assert.match(workbenchSource, /line_key/);
  assert.match(workbenchSource, /getRequestInvoices/);
  assert.match(workbenchSource, /invoicesForLine/);
  assert.ok(workbenchSource.includes(C.viewInvoice));
  assert.match(workbenchSource, /no_invoice_reason/);
  assert.ok(workbenchSource.includes(C.noInvoiceReason));
});



test('reimbursement draft edits project groups and manual no-invoice sources', () => {
  assert.match(workbenchSource, /save_draft_expense_sources/);
  assert.match(workbenchSource, /draftSources/);
  assert.match(workbenchSource, /project_groups/);
  assert.match(workbenchSource, /expense_item/);
  assert.match(workbenchSource, /datalist/);
  assert.ok(workbenchSource.includes('费用项目'));
  assert.ok(workbenchSource.includes('手动增加'));
  for (const label of ['项目名称', '费用项目', '日期', '税后金额', '费用说明', '无票原因']) {
    assert.ok(workbenchSource.includes(label), label);
  }
  assert.match(workbenchSource, /invoicesForGroup/);
  assert.match(workbenchSource, /source_line_keys/);
  assert.match(workbenchSource, /查看发票/);
  assert.match(workbenchSource, /审批记录/);
  assert.match(workbenchSource, /付款信息/);
});

test('approval and invoice APIs expose pushdown and reversible operations', () => {
  assert.match(apiSource, /def push_invoices_to_request\(invoice_names, payment_info=None\):/);
  assert.match(apiSource, /def withdraw_request\(name, note=None\):/);
  assert.match(apiSource, /def withdraw_payment\(name, note=None\):/);
  assert.match(apiSource, /def withdraw_invoice_push\(invoice_names, note=None\):/);
  assert.match(apiSource, /def action_request\(/);
  assert.match(apiSource, /def mark_paid\(name, note=None\):/);
  assert.match(apiSource, /operation_log/);
  assert.match(invoiceApiSource, /def list_workbench\(/);
  assert.match(invoiceApiSource, /def unconfirm_invoice\(/);
  assert.match(invoiceLibSource, /export function pushInvoices/);
  assert.match(invoiceLibSource, /export function withdrawInvoicePush/);
});

test('reimbursement board supports approval payment and both withdrawal paths', () => {
  assert.match(workbenchSource, /action_request/);
  assert.match(workbenchSource, /mark_paid/);
  assert.match(workbenchSource, /withdraw_request/);
  assert.match(workbenchSource, /withdraw_payment/);
  assert.ok(workbenchSource.includes(C.withdrawRequest));
  assert.ok(workbenchSource.includes(C.withdrawPayment));
  assert.match(workbenchSource, /operation_log/);
});
