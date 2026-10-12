import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { REQUIRED_FIELDS, canEditAttachments, categoryText, isRequiredField } from '../src/lib/invoiceFolderView.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('the required fields are the five the backend checks; the invoice category is optional and blank shows a dash', () => {
  assert.deepEqual(REQUIRED_FIELDS.map(([field]) => field), ['project_name', 'issue_date', 'invoice_number', 'total_amount', 'expense_description']);
  assert.equal(isRequiredField('invoice_category'), false);
  assert.equal(isRequiredField('invoice_number'), true);
  assert.equal(categoryText(''), '—');
  assert.equal(categoryText(null), '—');
  assert.equal(categoryText(' 电子发票 '), '电子发票');
});

test('supplemental attachments can be added or removed until the invoice is used by a document', () => {
  for (const status of ['待确认', '疑似重复', '可用']) assert.equal(canEditAttachments({ folder_status: status }), true, status);
  for (const status of ['已使用', '识别中', '识别失败', '已排除']) assert.equal(canEditAttachments({ folder_status: status }), false, status);
});

test('the invoice folder detail shows required stars from one list and has upload, preview and delete for attachments', () => {
  const source = read('../src/pages/InvoiceFolder.vue');
  for (const field of ['project_name', 'issue_date', 'invoice_number', 'total_amount', 'expense_description']) {
    assert.match(source, new RegExp(`star\\('${field}'\\)`), field);
  }
  assert.doesNotMatch(source, /star\('invoice_category'\)/);
  assert.match(source, /uploadInvoiceSupplementalAttachment/);
  assert.match(source, /deleteInvoiceSupplementalAttachment/);
  assert.match(source, /listInvoiceSupplementalAttachments/);
  assert.match(source, /fetchInvoiceSupplementalAttachmentPreview/);
  assert.match(source, /attachmentsEditable/);
});

test('the reimbursement / payment detail shows the invoice category and each invoice with its attachments', () => {
  const source = read('../src/components/claim/ClaimWorkbench.vue');
  assert.match(source, /<th v-if="isClaim">发票类别<\/th>/);
  assert.match(source, /categoryText\(line\.invoice_category\)/);
  assert.match(source, /invoice_entry\.get_request_invoices/);
  assert.match(source, /data-testid="doc-invoices"/);
  assert.match(source, /fetchInvoiceSupplementalAttachmentPreview/);
});

test('the invoice entry exposes the list call the folder uses', () => {
  assert.match(read('../src/lib/invoiceOcr.js'), /'list_supplemental_attachments'/);
});
