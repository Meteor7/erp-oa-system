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
});

test('invoice upload workspace provides batch review selection detail push and preview', () => {
  assert.equal(existsSync(componentUrl), true);
  const source = readFileSync(componentUrl, 'utf8');
  assert.match(source, /multiple/);
  assert.match(source, /accept=["'][^"']*\.pdf[^"']*\.jpg[^"']*\.jpeg[^"']*\.png/i);
  for (const label of ['发票类别', '项目名称', '开票日期', '发票号码', '税前金额', '税额', '合计金额']) {
    assert.ok(source.includes(label), label);
  }
  for (const action of ['确认内容', '撤回确认', '下推到费用报销流', '撤回下推', '查看发票']) {
    assert.ok(source.includes(action), action);
  }
  assert.match(source, /InvoicePreviewDrawer/);
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
  assert.ok(expense.includes('费用报销流'));
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
  assert.match(expense, /无票原因/);
  assert.match(expense, /查看发票/);
  assert.match(expense, /withdraw_request/);
  assert.match(expense, /withdraw_payment/);
});
