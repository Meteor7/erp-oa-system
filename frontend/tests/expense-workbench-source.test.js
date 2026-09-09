import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const workbench = readFileSync(new URL('../src/components/ExpenseWorkbench.vue', import.meta.url), 'utf8');
const workflow = readFileSync(new URL('../src/lib/expenseWorkflow.js', import.meta.url), 'utf8');

test('employee draft keeps classification optional but requires descriptions', () => {
  assert.match(workbench, /expense_description/);
  assert.doesNotMatch(workbench, /!row\.expense_item|!clean\(line\.expense_item\)/);
  assert.match(workbench, /canEditExpenseItems/);
  assert.match(workbench, /can_edit_expense_items/);
  assert.match(workbench, /saveFinanceClassification/);
  assert.match(workbench, /expense_account_level_1/);
  assert.match(workbench, /expense_account_level_2/);
  assert.doesNotMatch(workbench, /manualExpense\.no_invoice_reason/);
});

test('expense lines expose private supplemental attachments', () => {
  assert.doesNotMatch(workbench, /handleExpenseAttachments/);
  assert.match(workbench, /fetchExpenseAttachmentPreview/);
  assert.match(workbench, /:preview-loader=/);
  assert.match(workflow, /body\.append\('is_private', '1'\)/);
  assert.match(workflow, /MAX_EXPENSE_ATTACHMENTS\s*=\s*10/);
});

test('each invoice keeps its attachments immediately to the right in pending detail', () => {
  const rowStart = workbench.indexOf('data-testid="expense-source-row"');
  const rowEnd = workbench.indexOf('</section>', rowStart);
  assert.ok(rowStart >= 0 && rowEnd > rowStart);
  const rowSource = workbench.slice(rowStart, rowEnd);
  const invoiceIndex = rowSource.indexOf('data-testid="source-invoice"');
  const attachmentIndex = rowSource.indexOf('data-testid="source-attachments"');
  const descriptionIndex = rowSource.indexOf('data-testid="source-description"');
  assert.ok(invoiceIndex >= 0);
  assert.ok(attachmentIndex > invoiceIndex);
  assert.ok(descriptionIndex > attachmentIndex);
});

test('approval actions are capability driven with targeted rejection and repeated add-sign', () => {
  for (const contract of ['can_approve', 'can_reject', 'can_add_sign', 'rejection_targets', 'add_sign_remaining']) {
    assert.match(workbench, new RegExp(contract));
  }
  assert.match(workbench, /submitReject/);
  assert.match(workbench, /addSignRequest/);
  assert.match(workbench, /add_sign_opinion/);
  assert.doesNotMatch(workbench, /act\(selectedRequest,'reject'\)/);
});

test('reimbursement detail is a responsive approval workbench with visible actions', () => {
  assert.doesNotMatch(workbench, /min-w-\[1500px\]/);
  for (const marker of [
    'data-testid="expense-detail-workbench"',
    'data-testid="expense-summary"',
    'data-testid="expense-group"',
    'data-testid="finance-classification"',
    'data-testid="approval-actions"',
  ]) {
    assert.match(workbench, new RegExp(marker));
  }
  assert.match(workbench, /sticky top-0/);
  assert.match(workbench, /sticky bottom-0/);
  assert.match(workbench, /action_scope/);
  assert.match(workbench, /&#x5B9A;&#x5411;&#x9A73;&#x56DE;/);
});


test('asset type is a required single select in manual and OCR push flows', () => {
  const upload = readFileSync(new URL('../src/components/invoice/InvoiceUploadWorkbench.vue', import.meta.url), 'utf8');
  for (const label of ['非电子类固定资产（人事/行政）', '电子类固定资产（IT）', '其他']) {
    assert.ok(workbench.includes(label) || /assetCategories/.test(workbench), `missing asset option contract: ${label}`);
  }
  assert.match(workbench, /data-testid="asset-category-select"/);
  assert.match(workbench, /!requestForm\.asset_category/);
  assert.doesNotMatch(workbench, /supervisor:\s*requestForm\.supervisor/);
  assert.doesNotMatch(workbench, /v-model="requestForm\.supervisor"/);
  assert.match(upload, /data-testid="ocr-asset-category-select"/);
  assert.match(upload, /props\.options\?\.asset_categories/);
  assert.match(upload, /!pushForm\.asset_category/);
});

test('final handle action is explicitly confirmation of payment', () => {
  assert.ok(workbench.includes('确认付款'));
  assert.doesNotMatch(workbench, /办理完成/);
});

test('payment and reimbursement share one workflow but keep their business evidence distinct', () => {
  for (const label of ['员工垫付报销', '事前申请付款', '已有发票', '暂未取得发票', '无需发票']) {
    assert.ok(workbench.includes(label), `missing payment mode: ${label}`);
  }
  assert.match(workbench, /list_expense_payment_sources/);
  assert.match(workbench, /来源购买申请（必选）/);
  assert.match(workbench, /source_request: requestForm\.source_request/);
  assert.match(workbench, /公司事前付款必须关联一张已审批通过/);
});
