import assert from 'node:assert/strict';
import test from 'node:test';

import {
  amountMismatch,
  createOperationContext,
  editableInvoiceValues,
  fetchInvoicePreview,
  invoiceBlockers,
  invoicesForLine,
  moneyToCents,
  newLineKey,
  validateInvoiceFiles,
} from '../src/lib/invoiceOcr.js';

test('groups many invoices under one stable expense line', () => {
  const rows = invoicesForLine([
    { name: 'I1', expense_line_key: 'L1' },
    { name: 'I2', expense_line_key: 'L1' },
    { name: 'I3', expense_line_key: 'L2' },
  ], 'L1');
  assert.deepEqual(rows.map((row) => row.name), ['I1', 'I2']);
});

test('blocks unconfirmed and duplicate records', () => {
  assert.deepEqual(
    invoiceBlockers([{ recognition_status: '\u5f85\u786e\u8ba4' }, { recognition_status: '\u7591\u4f3c\u91cd\u590d' }]),
    ['\u5b58\u5728\u672a\u786e\u8ba4\u53d1\u7968', '\u5b58\u5728\u7591\u4f3c\u91cd\u590d\u53d1\u7968'],
  );
});

test('money comparisons use integer cents', () => {
  assert.equal(moneyToCents('0.10'), 10);
  assert.equal(moneyToCents('35.985'), 3599);
  assert.equal(amountMismatch({ total_amount: '0.30' }, '0.1'), 20);
  assert.equal(amountMismatch({ amount_before_tax: '35.62', tax_amount: '0.36', total_amount: '35.98' }), 0);
});

test('editable values enforce the exact seven-field whitelist', () => {
  const values = editableInvoiceValues({ invoice_number: '001', total_amount: '8.00', recognition_status: '\u5df2\u786e\u8ba4', duplicate_of: 'other' });
  assert.deepEqual(values, { invoice_number: '001', total_amount: '8.00' });
});

test('line keys use crypto and file validation enforces batch limits', () => {
  assert.match(newLineKey(), /^[0-9a-f-]{36}$/i);
  assert.equal(validateInvoiceFiles([{ name: 'a.pdf', size: 1 }]).length, 1);
  assert.throws(() => validateInvoiceFiles(Array.from({ length: 21 }, (_, i) => ({ name: `${i}.pdf`, size: 1 }))));
  assert.throws(() => validateInvoiceFiles([{ name: 'bad.gif', size: 1 }]));
  assert.throws(() => validateInvoiceFiles([{ name: 'big.pdf', size: 10 * 1024 * 1024 + 1 }]));
});
test('operation context aborts stale work and prevents late commits after batch switch', async () => {
  const context = createOperationContext();
  const generation = context.current();
  const controller = context.controller();
  let release;
  let committed = false;
  const delayed = new Promise((resolve) => { release = resolve; }).then(() => {
    if (context.isCurrent(generation)) committed = true;
  });

  context.invalidate();
  release();
  await delayed;

  assert.equal(controller.signal.aborted, true);
  assert.equal(context.isCurrent(generation), false);
  assert.equal(committed, false);
});

test('preview rejects successful non-invoice MIME responses', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    if (calls === 1) {
      return {
        ok: true,
        json: async () => ({
          message: {
            preview_method: 'POST',
            preview_url: '/api/method/rayher_hr_payroll.api.invoice_entry.serve_invoice_preview',
            token: 'token',
            mime_type: 'application/pdf',
          },
        }),
      };
    }
    return {
      ok: true,
      blob: async () => new Blob(['not an invoice'], { type: 'text/html' }),
    };
  };
  try {
    await assert.rejects(
      () => fetchInvoicePreview('INV-1'),
      /PDF|JPEG|PNG|type|format/i,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
