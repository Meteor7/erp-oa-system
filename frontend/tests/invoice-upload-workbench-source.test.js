import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

const componentUrl = new URL('../src/components/invoice/InvoiceUploadWorkbench.vue', import.meta.url);
const lib = readFileSync(new URL('../src/lib/invoiceOcr.js', import.meta.url), 'utf8');
const expense = readFileSync(new URL('../src/components/ExpenseWorkbench.vue', import.meta.url), 'utf8');

test('invoice upload workspace exposes record-driven reversible APIs', () => {
  for (const name of ['listWorkbenchInvoices', 'unconfirmInvoice', 'pushInvoices', 'withdrawInvoicePush']) {
    assert.match(lib, new RegExp(`export function ${name}\\b`));
  }
  assert.match(lib, /list_workbench/);
  assert.match(lib, /unconfirm_invoice/);
  assert.match(lib, /push_invoices_to_request/);
  assert.match(lib, /withdraw_invoice_push/);
  assert.match(lib, /include_pushed/);
});

test('invoice upload workspace provides batch review selection detail push and preview', () => {
  assert.equal(existsSync(componentUrl), true);
  const source = readFileSync(componentUrl, 'utf8');
  assert.match(source, /multiple/);
  assert.match(source, /accept=["'][^"']*\.pdf[^"']*\.jpg[^"']*\.jpeg[^"']*\.png/i);
  for (const label of ['发票类别', '项目名称', '开票日期', '发票号码', '税前金额', '税额', '合计金额', '费用说明', '补充附件']) {
    assert.ok(source.includes(label), label);
  }
  for (const action of ['确认内容', '撤回确认', '下推到费用报销流程', '查看发票']) {
    assert.ok(source.includes(action), action);
  }
  assert.ok(expense.includes('撤回下推'));
  assert.doesNotMatch(source, />撤回下推</);
  assert.doesNotMatch(source, /\['已下推',\s*stats\.pushed/);
  assert.match(source, /InvoicePreviewDrawer/);
  assert.match(source, /updateInvoiceExpenseContext/);
  assert.match(source, /uploadInvoiceSupplementalAttachment/);
  assert.match(source, /fetchInvoiceSupplementalAttachmentPreview/);
  assert.match(source, /ACTIVE_RECOGNITION_STATUSES/);
  assert.match(source, /clearTimeout/);
  assert.doesNotMatch(source, /<a\b|download/);
});


test('invoice push form uses readonly current applicant and canonical payment labels', () => {
  const source = readFileSync(componentUrl, 'utf8');
  assert.match(source, /current_applicant/);
  assert.ok(source.includes('申请人'));
  assert.doesNotMatch(source, /v-model="pushForm\.supervisor"/);
  assert.doesNotMatch(source, />部门主管</);
  assert.ok(source.includes('付款类型'));
  assert.match(source, /payment_type:\s*['"]支付个人['"]/);
  assert.ok(source.includes('支付方式'));
  const payee = source.indexOf('收款人');
  const method = source.indexOf('支付方式');
  const bank = source.indexOf('开户行');
  const branch = source.indexOf('支行');
  const account = source.indexOf('收款账号');
  assert.ok(method < payee && payee < bank && bank < branch && branch < account);
});

test('expense workbench uses four first-class pages and exact seven-column details', () => {
  assert.ok(expense.includes('上传发票'));
  assert.ok(expense.includes('费用报销流程'));
  assert.ok(expense.includes('费用统计'));
  assert.ok(expense.includes('审批记录'));
  assert.match(expense, /ExpenseStatistics/);
  assert.match(expense, /ExpenseApprovalRecords/);
  assert.doesNotMatch(expense, /label:\s*['"]主看板['"]|label:\s*['"]子模板['"]/);
  assert.doesNotMatch(expense, /新建消费明细|下推生成付款单/);
  assert.match(expense, /activeView\s*=\s*ref\(['"]invoices['"]\)/);
  assert.match(expense, /InvoiceUploadWorkbench/);
  for (const label of ['发票类别', '项目名称', '开票日期', '发票号码', '税前金额', '税额', '合计金额']) {
    assert.ok(expense.includes(label), label);
  }
  assert.doesNotMatch(expense, />无票原因</);
  assert.match(expense, /查看发票/);
  assert.match(expense, /withdraw_request/);
  assert.match(expense, /withdraw_payment/);
});


test('invoice upload workspace uses a responsive list and focused review panel', () => {
  const source = readFileSync(componentUrl, 'utf8');
  assert.match(source, /sticky top-0 z-10/);
  assert.match(source, /xl:grid-cols-\[minmax\(0,1fr\)_420px\]/);
  assert.match(source, /xl:sticky xl:top-4/);
  assert.match(source, /max-h-\[calc\(100vh-360px\)\]/);
  assert.match(source, /overflow-x-auto/);
  assert.match(source, /required_fields_missing/);
  assert.match(source, /field_conflict:/);
  assert.doesNotMatch(source, /min-h-\[560px\]/);
});

test('invoice warnings translate every OCR service code and hide unknown internal codes', () => {
  const source = readFileSync(componentUrl, 'utf8');
  for (const warning of [
    'invoice_category_raw_missing',
    'amount_before_tax_derived_from_total_minus_tax',
    'zero_tax_rule_applied',
    'tax_amount_missing_for_taxable_invoice',
    'amount_arithmetic_mismatch',
    'dependent_fields_cleared_due_to_conflict',
    'temporary_files_cleanup_failed:sensitive_invoice_files_may_remain',
  ]) {
    assert.ok(source.includes(warning), warning);
  }
  assert.doesNotMatch(source, /return raw \|\|/);
});
