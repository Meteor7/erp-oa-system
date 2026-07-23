import assert from 'node:assert/strict';
import test from 'node:test';

import {
  amountMismatch,
  createGenerationBusyTracker,
  createInvoiceRequestLoadContext,
  createOperationContext,
  editableInvoiceValues,
  fetchInvoicePreview,
  fetchInvoiceSupplementalAttachmentPreview,
  getRequestInvoices,
  hasRegisteredInvoiceUpload,
  invoiceBlockers,
  invoiceFieldWarnings,
  invoiceSelectionReason,
  invoiceSaveGuard,
  invoicesForLine,
  moneyToCents,
  newLineKey,
  persistInvoiceRequest,
  updateInvoiceExpenseContext,
  uploadInvoiceSupplementalAttachment,
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

test('explains why an invoice can or cannot be selected for pushdown', () => {
  assert.equal(invoiceSelectionReason({ recognition_status: '\u5df2\u786e\u8ba4', request: '', expense_description: '客户拜访' }), '');
  assert.equal(invoiceSelectionReason({ recognition_status: '\u5df2\u786e\u8ba4', request: '', expense_description: ' ' }), '请先填写费用说明');
  assert.equal(invoiceSelectionReason({ recognition_status: '\u5f85\u786e\u8ba4', request: '' }), '\u8bf7\u5148\u786e\u8ba4\u53d1\u7968\u5185\u5bb9');
  assert.equal(invoiceSelectionReason({ recognition_status: '\u7591\u4f3c\u91cd\u590d', request: '' }), '\u7591\u4f3c\u91cd\u590d\u53d1\u7968\u4e0d\u80fd\u4e0b\u63a8');
  assert.equal(invoiceSelectionReason({ recognition_status: '\u5931\u8d25', request: '' }), '\u8bc6\u522b\u5931\u8d25\uff0c\u4e0d\u80fd\u4e0b\u63a8');
  assert.equal(invoiceSelectionReason({ recognition_status: '\u5df2\u786e\u8ba4', request: 'OA-2026-0001' }), '\u5df2\u4e0b\u63a8\u5230 OA-2026-0001');
});

test('invoice context and supplemental attachments use synchronized backend endpoints', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    if (url === '/api/method/upload_file') {
      return { ok: true, json: async () => ({ message: { file_url: '/private/files/route.pdf' } }) };
    }
    return { ok: true, json: async () => ({ message: { name: 'ISA-1' } }) };
  };
  try {
    await updateInvoiceExpenseContext('INV-1', '客户拜访交通费');
    const attachment = Object.assign(new Blob(['route']), { name: 'route.pdf' });
    await uploadInvoiceSupplementalAttachment('INV-1', attachment);
    assert.match(calls[0].url, /update_expense_context$/);
    assert.deepEqual(JSON.parse(calls[0].options.body), {
      invoice_name: 'INV-1',
      expense_description: '客户拜访交通费',
    });
    assert.equal(calls[1].url, '/api/method/upload_file');
    assert.match(calls[2].url, /upload_supplemental_attachment$/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('supplemental attachment preview consumes a POST token', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (_url, options) => {
    calls += 1;
    if (calls === 1) {
      return {
        ok: true,
        json: async () => ({
          message: {
            token: 'secure-token',
            preview_method: 'POST',
            preview_url: '/supplemental-preview',
            mime_type: 'application/pdf',
          },
        }),
      };
    }
    assert.equal(options.method, 'POST');
    return { ok: true, blob: async () => new Blob(['%PDF-'], { type: 'application/pdf' }) };
  };
  try {
    const result = await fetchInvoiceSupplementalAttachmentPreview('ISA-1');
    assert.equal(result.blob.type, 'application/pdf');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('normalizes JSON warning payloads without rendering brackets as warnings', () => {
  assert.deepEqual(invoiceFieldWarnings('[]'), []);
  assert.deepEqual(invoiceFieldWarnings('["required_fields_missing"]'), ['required_fields_missing']);
  assert.deepEqual(invoiceFieldWarnings([{ message: 'needs review' }]), [{ message: 'needs review' }]);
  assert.deepEqual(invoiceFieldWarnings('plain warning'), ['plain warning']);
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

test('request invoice workflow creates a draft, links confirmed invoices, then submits', async () => {
  const events = [];
  const result = await persistInvoiceRequest({
    createDraft: async () => { events.push('create'); return { name: 'REQ-1' }; },
    link: async (invoice, request, line) => { events.push(`link:${invoice}:${request}:${line}`); },
    submitDraft: async (name) => { events.push(`submit:${name}`); return { name }; },
    invoices: [
      { name: 'INV-1', recognition_status: '已确认', expense_line_key: 'LINE-1' },
      { name: 'INV-2', recognition_status: '已排除', expense_line_key: 'LINE-1' },
    ],
    payload: { submit: 0 },
    shouldSubmit: true,
  });
  assert.deepEqual(events, ['create', 'link:INV-1:REQ-1:LINE-1', 'submit:REQ-1']);
  assert.equal(result.requestName, 'REQ-1');
});

test('request invoice workflow keeps the draft and never submits after a link failure', async () => {
  const events = [];
  let retained = '';
  await assert.rejects(() => persistInvoiceRequest({
    createDraft: async () => ({ name: 'REQ-2' }),
    onDraftCreated: (row) => { retained = row.name; events.push('created'); },
    link: async () => { events.push('link'); throw new Error('link failed'); },
    submitDraft: async () => { events.push('submit'); },
    invoices: [{ name: 'INV-1', recognition_status: '已确认', expense_line_key: 'LINE-1' }],
    shouldSubmit: true,
  }), /link failed/);
  assert.equal(retained, 'REQ-2');
  assert.deepEqual(events, ['created', 'link']);

  await persistInvoiceRequest({
    requestName: retained,
    createDraft: async () => { events.push('duplicate-create'); },
    link: async () => { events.push('retry-link'); },
    submitDraft: async () => { events.push('retry-submit'); },
    invoices: [{ name: 'INV-1', recognition_status: '已确认', expense_line_key: 'LINE-1' }],
    shouldSubmit: true,
  });
  assert.deepEqual(events, ['created', 'link', 'retry-link', 'retry-submit']);
});

test('getRequestInvoices uses the bounded invoice endpoint', async () => {
  const originalFetch = globalThis.fetch;
  let body;
  globalThis.fetch = async (_url, options) => {
    body = JSON.parse(options.body);
    return { ok: true, json: async () => ({ message: [{ name: 'INV-1' }] }) };
  };
  try {
    assert.deepEqual(await getRequestInvoices('REQ-1'), [{ name: 'INV-1' }]);
    assert.deepEqual(body, { request: 'REQ-1' });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('unknown invoice states are blocked instead of being treated as confirmed', () => {
  assert.deepEqual(invoiceBlockers([{ recognition_status: '未知状态' }]), ['存在状态异常发票']);
});

test('save guard blocks every save during upload or an unresolved empty batch but permits queued draft rows', () => {
  assert.ok(invoiceSaveGuard({ busy: true, batch: '', invoices: [] }));
  assert.ok(invoiceSaveGuard({ busy: false, batch: { name: 'BATCH-1' }, invoices: [] }));
  assert.equal(invoiceSaveGuard({
    busy: false,
    batch: 'BATCH-1',
    invoices: [{ name: 'INV-1', recognition_status: '\u6392\u961f\u4e2d' }],
  }), '');
  assert.equal(invoiceSaveGuard({ busy: false, batch: '', invoices: [] }), '');
});

test('generation busy tracker balances invalidation and prevents stale work clearing newer busy state', () => {
  const changes = [];
  const tracker = createGenerationBusyTracker((busy) => changes.push(busy));
  const stale = tracker.begin();
  tracker.invalidate();
  const current = tracker.begin();
  assert.equal(tracker.finish(stale), false);
  assert.equal(tracker.isBusy(), true);
  assert.equal(tracker.finish(current), true);
  assert.equal(tracker.isBusy(), false);
  assert.deepEqual(changes, [true, false, true, false]);
});

test('request invoice load context clears on switch, ignores stale completion, and preserves multi-batch rows as an error', () => {
  const states = [];
  const context = createInvoiceRequestLoadContext((state) => states.push(state));
  const first = context.begin('REQ-1');
  const second = context.begin('REQ-2');
  assert.equal(context.resolve(first, [{ name: 'OLD', batch: 'BATCH-OLD' }]).applied, false);
  assert.equal(context.snapshot().request, 'REQ-2');
  assert.equal(context.snapshot().status, 'loading');
  assert.deepEqual(context.snapshot().rows, []);

  const multi = context.resolve(second, [
    { name: 'INV-1', batch: 'BATCH-1' },
    { name: 'INV-2', batch: 'BATCH-2' },
  ]);
  assert.equal(multi.applied, true);
  assert.equal(multi.state.status, 'error');
  assert.ok(multi.state.error);
  assert.equal(multi.state.batch, '');
  assert.deepEqual(multi.state.rows.map((row) => row.name), ['INV-1', 'INV-2']);

  const retry = context.begin('REQ-2');
  assert.deepEqual(context.snapshot().rows, []);
  context.reject(retry, new Error('network failed'));
  assert.equal(context.snapshot().status, 'error');
  assert.match(context.snapshot().error, /network failed/);

  const success = context.begin('REQ-2');
  const loaded = context.resolve(success, [{ name: 'INV-3', batch: 'BATCH-3' }]);
  assert.equal(loaded.state.status, 'loaded');
  assert.equal(loaded.state.batch, 'BATCH-3');
  assert.ok(states.some((state) => state.status === 'loading' && state.rows.length === 0));
});

test('only a successfully registered upload may trigger draft batch attachment', () => {
  assert.equal(hasRegisteredInvoiceUpload([{ file: { name: 'bad.pdf' }, error: new Error('failed') }]), false);
  assert.equal(hasRegisteredInvoiceUpload([
    { file: { name: 'bad.pdf' }, error: new Error('failed') },
    { file: { name: 'ok.pdf' }, value: { name: 'INV-1' } },
  ]), true);
});
