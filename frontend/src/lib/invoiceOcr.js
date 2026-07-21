export const INVOICE_FIELDS = Object.freeze([
  'invoice_category',
  'project_name',
  'issue_date',
  'invoice_number',
  'amount_before_tax',
  'tax_amount',
  'total_amount',
]);

export const MAX_FILES = 20;
export const MAX_FILE_SIZE = 10 * 1024 * 1024;
export const UPLOAD_CONCURRENCY = 3;
export function createOperationContext() {
  let generation = 0;
  const controllers = new Set();
  return {
    current: () => generation,
    isCurrent: (version) => version === generation,
    controller() {
      const controller = new AbortController();
      controllers.add(controller);
      return controller;
    },
    finish(controller) {
      controllers.delete(controller);
    },
    invalidate() {
      generation += 1;
      controllers.forEach((controller) => controller.abort());
      controllers.clear();
      return generation;
    },
  };
}
export const ACCEPTED_INVOICE_EXTENSIONS = Object.freeze(['pdf', 'jpg', 'jpeg', 'png']);
export const ACTIVE_RECOGNITION_STATUSES = Object.freeze(['\u6392\u961f\u4e2d', '\u8bc6\u522b\u4e2d']);

const API_PREFIX = '/api/method/rayher_hr_payroll.api.invoice_entry.';

function csrfHeaders(extra = {}) {
  const token = globalThis.window?.csrf_token;
  return token ? { ...extra, 'X-Frappe-CSRF-Token': token } : extra;
}

function errorText(payload, fallback) {
  if (typeof payload?.message === 'string') return payload.message;
  if (typeof payload?.exception === 'string') return payload.exception;
  try {
    const messages = JSON.parse(payload?._server_messages || '[]');
    const parsed = messages.map((item) => JSON.parse(item)?.message).filter(Boolean);
    if (parsed.length) return parsed.join('\n');
  } catch {
    // Keep the bounded fallback; malformed server errors are not user-controlled actions.
  }
  return fallback;
}

export async function invoiceApi(action, args = {}, { signal } = {}) {
  const response = await fetch(`${API_PREFIX}${action}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(args),
    signal,
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    // A non-JSON error is still surfaced with a stable message.
  }
  if (!response.ok || payload.exc) {
    throw new Error(errorText(payload, `Invoice API ${action} failed`));
  }
  return payload.message;
}

function uuidFromBytes(bytes) {
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function newLineKey() {
  const secureCrypto = globalThis.crypto;
  if (typeof secureCrypto?.randomUUID === 'function') return secureCrypto.randomUUID();
  if (typeof secureCrypto?.getRandomValues === 'function') {
    return uuidFromBytes(secureCrypto.getRandomValues(new Uint8Array(16)));
  }
  throw new Error('Secure random UUID generation is unavailable');
}

export function moneyToCents(value) {
  if (value === null || value === undefined || value === '') return 0;
  const source = String(value).trim();
  const match = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(source);
  if (!match || (!match[2] && !match[3])) throw new TypeError(`Invalid money value: ${source}`);
  const negative = match[1] === '-';
  const whole = BigInt(match[2] || '0');
  const fraction = (match[3] || '').padEnd(3, '0');
  let cents = whole * 100n + BigInt(fraction.slice(0, 2) || '0');
  if (Number(fraction[2] || '0') >= 5) cents += 1n;
  if (negative) cents = -cents;
  const result = Number(cents);
  if (!Number.isSafeInteger(result)) throw new RangeError('Money value exceeds safe integer cents');
  return result;
}

export function amountMismatch(invoice, expectedAmount) {
  if (!invoice) return 0;
  const actual = moneyToCents(invoice.total_amount);
  const expected = expectedAmount === undefined
    ? moneyToCents(invoice.amount_before_tax) + moneyToCents(invoice.tax_amount)
    : moneyToCents(expectedAmount);
  return actual - expected;
}

export function invoicesForLine(invoices, lineKey) {
  return Array.isArray(invoices)
    ? invoices.filter((invoice) => invoice?.expense_line_key === lineKey)
    : [];
}

export function invoiceBlockers(invoices) {
  const statuses = new Set((Array.isArray(invoices) ? invoices : [])
    .filter((invoice) => invoice?.recognition_status !== '\u5df2\u6392\u9664')
    .map((invoice) => invoice?.recognition_status));
  const blockers = [];
  if (statuses.has('\u6392\u961f\u4e2d') || statuses.has('\u8bc6\u522b\u4e2d')) blockers.push('\u5b58\u5728\u6b63\u5728\u8bc6\u522b\u7684\u53d1\u7968');
  if (statuses.has('\u5f85\u786e\u8ba4')) blockers.push('\u5b58\u5728\u672a\u786e\u8ba4\u53d1\u7968');
  if (statuses.has('\u7591\u4f3c\u91cd\u590d')) blockers.push('\u5b58\u5728\u7591\u4f3c\u91cd\u590d\u53d1\u7968');
  if (statuses.has('\u5931\u8d25')) blockers.push('\u5b58\u5728\u8bc6\u522b\u5931\u8d25\u53d1\u7968');
  return blockers;
}

function extensionOf(file) {
  const name = String(file?.name || '');
  return name.includes('.') ? name.split('.').pop().toLowerCase() : '';
}

export function validateInvoiceFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) throw new Error('\u8bf7\u9009\u62e9\u53d1\u7968\u6587\u4ef6');
  if (files.length > MAX_FILES) throw new Error(`\u6bcf\u6279\u6700\u591a ${MAX_FILES} \u4e2a\u6587\u4ef6`);
  for (const file of files) {
    if (!ACCEPTED_INVOICE_EXTENSIONS.includes(extensionOf(file))) {
      throw new Error(`\u4e0d\u652f\u6301\u7684\u6587\u4ef6\u7c7b\u578b: ${file?.name || ''}`);
    }
    if (!Number.isFinite(Number(file?.size)) || Number(file.size) < 0 || Number(file.size) > MAX_FILE_SIZE) {
      throw new Error(`\u6587\u4ef6\u4e0d\u80fd\u8d85\u8fc7 10MB: ${file?.name || ''}`);
    }
  }
  return files;
}

export function editableInvoiceValues(values) {
  return Object.fromEntries(INVOICE_FIELDS
    .filter((field) => Object.prototype.hasOwnProperty.call(values || {}, field))
    .map((field) => [field, values[field]]));
}

export function createInvoiceBatch(options) {
  return invoiceApi('create_batch', {}, options);
}

export function getInvoiceBatch(batch, options) {
  return invoiceApi('get_batch', { batch }, options);
}

export async function uploadInvoiceFile(file, batch, { signal } = {}) {
  const body = new FormData();
  body.append('file', file);
  body.append('is_private', '1');
  const response = await fetch('/api/method/upload_file', {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrfHeaders(),
    body,
    signal,
  });
  const payload = await response.json();
  const fileUrl = payload?.message?.file_url;
  if (!response.ok || !fileUrl) throw new Error(errorText(payload, '\u53d1\u7968\u4e0a\u4f20\u5931\u8d25'));
  return invoiceApi('register_file', { batch, file_url: fileUrl }, { signal });
}

export async function uploadInvoiceFiles(fileList, batch, { signal, onSettled } = {}) {
  const files = validateInvoiceFiles(fileList);
  const results = new Array(files.length);
  let cursor = 0;
  async function worker() {
    while (cursor < files.length) {
      const index = cursor;
      cursor += 1;
      try {
        results[index] = { file: files[index], value: await uploadInvoiceFile(files[index], batch, { signal }) };
      } catch (error) {
        results[index] = { file: files[index], error };
      }
      onSettled?.(results[index], index, results.filter(Boolean).length, files.length);
    }
  }
  await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, files.length) }, () => worker()));
  return results;
}

export function updateInvoice(invoiceName, values, options) {
  return invoiceApi('update_invoice', { invoice_name: invoiceName, values: editableInvoiceValues(values) }, options);
}

export function confirmInvoice(invoiceName, values, options) {
  return invoiceApi('confirm_invoice', { invoice_name: invoiceName, values: editableInvoiceValues(values) }, options);
}

export function retryInvoice(invoiceName, options) {
  return invoiceApi('retry_invoice', { invoice_name: invoiceName }, options);
}

export function excludeInvoice(invoiceName, reason, options) {
  return invoiceApi('exclude_invoice', { invoice_name: invoiceName, reason: String(reason || '').trim() }, options);
}

export function resolveDuplicate(invoiceName, reason, options) {
  return invoiceApi('resolve_duplicate', { invoice_name: invoiceName, reason: String(reason || '').trim() }, options);
}

export function linkInvoice(invoiceName, request, expenseLineKey, options) {
  if (!request) return Promise.resolve({ invoice_name: invoiceName, expense_line_key: expenseLineKey, persisted: false });
  return invoiceApi('link_invoice', { invoice_name: invoiceName, request, expense_line_key: expenseLineKey }, options);
}

export function previewInvoice(invoiceName, options) {
  return invoiceApi('preview_invoice', { invoice_name: invoiceName }, options);
}

export async function fetchInvoicePreview(invoiceName, { signal } = {}) {
  const metadata = await previewInvoice(invoiceName, { signal });
  if (metadata?.preview_method !== 'POST' || !metadata?.token || !metadata?.preview_url) {
    throw new Error('\u9884\u89c8\u51ed\u8bc1\u65e0\u6548');
  }
  const response = await fetch(metadata.preview_url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ token: metadata.token }),
    signal,
  });
  if (!response.ok) throw new Error('\u53d1\u7968\u9884\u89c8\u52a0\u8f7d\u5931\u8d25');
  const blob = await response.blob();
  const normalizeMime = (value) => String(value || '').split(';')[0].trim().toLowerCase();
  const allowed = new Set(['application/pdf', 'image/jpeg', 'image/png']);
  const responseMime = normalizeMime(blob.type);
  const metadataMime = normalizeMime(metadata.mime_type);
  if ((responseMime && !allowed.has(responseMime)) || (!responseMime && !allowed.has(metadataMime))) {
    throw new Error('\u53d1\u7968\u9884\u89c8\u53ea\u652f\u6301 PDF\u3001JPEG \u6216 PNG \u683c\u5f0f');
  }
  if (responseMime && metadataMime && responseMime !== metadataMime) {
    throw new Error('\u53d1\u7968\u9884\u89c8\u6587\u4ef6\u7c7b\u578b\u4e0d\u4e00\u81f4');
  }
  return { metadata, blob };
}
