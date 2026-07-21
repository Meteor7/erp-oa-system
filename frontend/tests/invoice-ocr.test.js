import assert from 'node:assert/strict';
import test from 'node:test';

import {
  amountMismatch,
  editableInvoiceValues,
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
