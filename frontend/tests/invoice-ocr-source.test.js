import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const lib = readFileSync(new URL('../src/lib/invoiceOcr.js', import.meta.url), 'utf8');
const panel = readFileSync(new URL('../src/components/invoice/InvoiceRecognitionPanel.vue', import.meta.url), 'utf8');
const preview = readFileSync(new URL('../src/components/invoice/InvoicePreviewDrawer.vue', import.meta.url), 'utf8');
const workbench = readFileSync(new URL('../src/components/invoice/InvoiceUploadWorkbench.vue', import.meta.url), 'utf8');

test('invoice API contract is private, bounded and controlled', () => {
  assert.match(lib, /MAX_FILES\s*=\s*20/);
  assert.match(lib, /MAX_FILE_SIZE\s*=\s*10\s*\*\s*1024\s*\*\s*1024/);
  assert.match(lib, /UPLOAD_CONCURRENCY\s*=\s*3/);
  assert.match(lib, /body\.append\(['"]file['"]/);
  assert.match(lib, /body\.append\(['"]is_private['"],\s*['"]1['"]\)/);
  assert.doesNotMatch(lib, /body\.append\(['"](?:doctype|docname)['"]/);
  assert.match(lib, /register_file/);
  assert.match(lib, /preview_invoice/);
  assert.match(lib, /preview_url/);
  assert.doesNotMatch(lib, /Math\.random|\.file_url\s*\)|method:\s*['"]GET['"]|download/);
});

test('panel and drawer expose lifecycle, field and preview protections', () => {
  for (const field of ['invoice_category', 'project_name', 'issue_date', 'invoice_number', 'amount_before_tax', 'tax_amount', 'total_amount']) {
    assert.match(panel, new RegExp(field));
  }
  assert.match(panel, /batch-created/);
  assert.match(panel, /busy-change/);
  assert.match(panel, /watch\(\(\) => props\.request/);
  assert.match(panel, /hasRegisteredInvoiceUpload/);
  assert.match(panel, /invoices-change/);
  assert.match(panel, /link-change/);
  assert.match(panel, /AbortController/);
  assert.match(panel, /clearTimeout/);
  assert.match(preview, /preview_invoice/);
  assert.match(preview, /URL\.createObjectURL/);
  assert.match(preview, /URL\.revokeObjectURL/);
  assert.match(preview, /AbortController/);
  assert.match(preview, /pdfjs-dist/);
  assert.match(preview, /shallowRef/);
  assert.match(preview, /const pdfDocument = shallowRef\(null\)/);
  assert.match(preview, /getDocument/);
  assert.match(preview, /renderTask/);
  assert.match(preview, /cancelPdfRender/);
  assert.doesNotMatch(preview, /<iframe|sandbox/);
  assert.match(preview, /close/);
  assert.match(preview, /watermark/i);
  assert.doesNotMatch(preview, /<a\b|download|:src=['"]invoice/);
});

test('invoice upload control uses supported palette', () => { assert.match(panel, /bg-blue-600/); assert.doesNotMatch(panel, /bg-sky-600/); });

test('invoice edit panel derives total immediately when money components change', () => {
  assert.match(workbench, /deriveInvoiceTotal/);
  assert.match(workbench, /syncDerivedTotal/);
  assert.match(workbench, /@input="syncDerivedTotal/);
});
