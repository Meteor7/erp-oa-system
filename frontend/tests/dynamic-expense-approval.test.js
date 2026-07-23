import assert from 'node:assert/strict';
import test from 'node:test';

import { deriveInvoiceTotal } from '../src/lib/invoiceOcr.js';

test('derives a blank invoice total from complete components using integer cents', () => {
  assert.equal(deriveInvoiceTotal({ amount_before_tax: '690.84', tax_amount: '20.73', total_amount: '' }), '711.57');
});

test('preserves supplied total and total-only invoices', () => {
  assert.equal(deriveInvoiceTotal({ amount_before_tax: '100.00', tax_amount: '6.00', total_amount: '105.00' }), '105.00');
  assert.equal(deriveInvoiceTotal({ amount_before_tax: '', tax_amount: '', total_amount: '874.00' }), '874.00');
});
