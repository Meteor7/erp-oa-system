import { oaApi } from './invoiceOcr.js';

export const MAX_EXPENSE_ATTACHMENTS = 10;
export const MAX_EXPENSE_ATTACHMENT_SIZE = 10 * 1024 * 1024;
export const ADD_SIGN_POSITIONS = Object.freeze(['before', 'after']);
const ACCEPTED_EXTENSIONS = new Set(['pdf', 'jpg', 'jpeg', 'png']);
const ACCEPTED_MIME_TYPES = new Set(['application/pdf', 'image/jpeg', 'image/png']);

function extensionOf(file) {
  const name = String(file?.name || '');
  return name.includes('.') ? name.split('.').pop().toLowerCase() : '';
}

function csrfHeaders(extra = {}) {
  const token = globalThis.window?.csrf_token;
  return token ? { ...extra, 'X-Frappe-CSRF-Token': token } : extra;
}

function apiError(payload, fallback) {
  if (typeof payload?.message === 'string') return payload.message;
  if (typeof payload?.exception === 'string') return payload.exception;
  return fallback;
}

export function validateExpenseAttachments(fileList, existingCount = 0) {
  const files = Array.from(fileList || []);
  const count = Number(existingCount || 0);
  if (!files.length) throw new Error('\u8bf7\u9009\u62e9\u8865\u5145\u9644\u4ef6');
  if (!Number.isInteger(count) || count < 0 || count + files.length > MAX_EXPENSE_ATTACHMENTS) {
    throw new Error(`\u6bcf\u884c\u6700\u591a ${MAX_EXPENSE_ATTACHMENTS} \u4e2a\u9644\u4ef6`);
  }
  for (const file of files) {
    if (!ACCEPTED_EXTENSIONS.has(extensionOf(file))) {
      throw new Error('\u9644\u4ef6\u53ea\u652f\u6301 PDF\u3001JPG\u3001JPEG \u6216 PNG');
    }
    if (!Number.isFinite(Number(file?.size)) || Number(file.size) <= 0 || Number(file.size) > MAX_EXPENSE_ATTACHMENT_SIZE) {
      throw new Error('\u6bcf\u4e2a\u9644\u4ef6\u4e0d\u80fd\u8d85\u8fc7 10MB');
    }
  }
  return files;
}

export async function uploadPrivateFile(file, { signal, fetcher = globalThis.fetch } = {}) {
  const body = new FormData();
  body.append('file', file);
  body.append('is_private', '1');
  const response = await fetcher('/api/method/upload_file', {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrfHeaders(),
    body,
    signal,
  });
  let payload = {};
  try { payload = await response.json(); } catch { /* bounded error below */ }
  const fileUrl = payload?.message?.file_url;
  if (!response.ok || !fileUrl) throw new Error(apiError(payload, '\u9644\u4ef6\u4e0a\u4f20\u5931\u8d25'));
  return { file_url: fileUrl };
}

export async function uploadExpenseAttachment(name, lineKey, file, {
  signal,
  api = oaApi,
  upload = uploadPrivateFile,
} = {}) {
  validateExpenseAttachments([file], 0);
  const uploaded = await upload(file, { signal, isPrivate: true });
  return api('upload_expense_attachment', {
    name,
    line_key: lineKey,
    file_url: uploaded.file_url,
  }, { signal });
}

export function deleteExpenseAttachment(name, attachment, { api = oaApi, signal } = {}) {
  return api('delete_expense_attachment', { name, attachment }, { signal });
}

export function saveFinanceExpenseItems(name, lines, { api = oaApi, signal } = {}) {
  const values = Array.from(lines || []).map((line) => ({
    line_key: String(line?.line_key || '').trim(),
    expense_account_level_1: String(line?.expense_account_level_1 || '').trim(),
    expense_account_level_2: String(line?.expense_account_level_2 || '').trim(),
  }));
  return api('save_finance_expense_items', { name, lines: JSON.stringify(values) }, { signal });
}

export function rejectRequest(name, rejectTarget, reason, { api = oaApi, signal } = {}) {
  return api('action_request', {
    name,
    action: 'reject',
    note: String(reason || '').trim(),
    reject_target: String(rejectTarget || '').trim(),
  }, { signal });
}

export function addSignRequest(name, approver, position, opinion, { api = oaApi, signal } = {}) {
  if (!ADD_SIGN_POSITIONS.includes(position)) throw new Error('\u52a0\u7b7e\u4f4d\u7f6e\u65e0\u6548');
  return api('add_sign_request', {
    name,
    approver: String(approver || '').trim(),
    position,
    opinion: String(opinion || '').trim(),
  }, { signal });
}

export function listApprovalPeople(query = '', { api = oaApi, signal, limit = 20, name = '' } = {}) {
  // 只有这张单据当前节点的审批人能查可加签的人（服务端按 name 校验）。
  return api('list_approval_people', { query: String(query || '').trim(), limit, name: String(name || '').trim() }, { signal });
}

export async function fetchExpenseAttachmentPreview(attachment, {
  signal,
  api = oaApi,
  fetcher = globalThis.fetch,
} = {}) {
  const metadata = await api('preview_expense_attachment', { attachment }, { signal });
  if (metadata?.preview_method !== 'POST' || !metadata?.token || !metadata?.preview_url) {
    throw new Error('\u9644\u4ef6\u9884\u89c8\u51ed\u8bc1\u65e0\u6548');
  }
  const response = await fetcher(metadata.preview_url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ token: metadata.token }),
    signal,
  });
  if (!response.ok) throw new Error('\u9644\u4ef6\u9884\u89c8\u52a0\u8f7d\u5931\u8d25');
  const blob = await response.blob();
  const mime = String(blob.type || metadata.mime_type || '').split(';')[0].trim().toLowerCase();
  if (!ACCEPTED_MIME_TYPES.has(mime)) throw new Error('\u9644\u4ef6\u9884\u89c8\u683c\u5f0f\u65e0\u6548');
  return { metadata, blob };
}
