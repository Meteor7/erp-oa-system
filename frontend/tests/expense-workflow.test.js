import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ADD_SIGN_POSITIONS,
  MAX_EXPENSE_ATTACHMENTS,
  addSignRequest,
  deleteExpenseAttachment,
  fetchExpenseAttachmentPreview,
  listApprovalPeople,
  rejectRequest,
  saveFinanceExpenseItems,
  uploadExpenseAttachment,
  validateExpenseAttachments,
} from '../src/lib/expenseWorkflow.js';

test('validates private supplemental attachment limits and types', () => {
  const pdf = { name: 'receipt.pdf', size: 1024 };
  assert.deepEqual(validateExpenseAttachments([pdf], 0), [pdf]);
  assert.throws(() => validateExpenseAttachments([{ name: 'receipt.exe', size: 1 }], 0), /PDF|JPG|JPEG|PNG/);
  assert.throws(() => validateExpenseAttachments([pdf], MAX_EXPENSE_ATTACHMENTS), /10/);
  assert.throws(() => validateExpenseAttachments([{ name: 'big.pdf', size: 10 * 1024 * 1024 + 1 }], 0), /10MB/);
});

test('exports stable workflow position choices', () => {
  assert.deepEqual(ADD_SIGN_POSITIONS, ['before', 'after']);
});

test('workflow API wrappers send the synchronized backend payload', async () => {
  const calls = [];
  const api = async (action, args) => { calls.push({ action, args }); return { ok: true }; };
  await saveFinanceExpenseItems('OA-1', [{
    line_key: 'L1',
    expense_account_level_1: '差旅费',
    expense_account_level_2: '住宿费',
  }], { api });
  await rejectRequest('OA-1', 'applicant', 'Fix it', { api });
  await addSignRequest('OA-1', 'finance@example.com', 'before', 'Review tax', { api });
  await listApprovalPeople('fin', { api });
  await deleteExpenseAttachment('OA-1', 'ATT-1', { api });
  assert.deepEqual(calls, [
    {
      action: 'save_finance_expense_items',
      args: {
        name: 'OA-1',
        lines: JSON.stringify([{
          line_key: 'L1',
          expense_account_level_1: '差旅费',
          expense_account_level_2: '住宿费',
        }]),
      },
    },
    { action: 'action_request', args: { name: 'OA-1', action: 'reject', note: 'Fix it', reject_target: 'applicant', expected_step_key: '' } },
    { action: 'add_sign_request', args: { name: 'OA-1', approver: 'finance@example.com', position: 'before', opinion: 'Review tax', expected_step_key: '' } },
    { action: 'list_approval_people', args: { query: 'fin', limit: 20, name: '' } },
    { action: 'delete_expense_attachment', args: { name: 'OA-1', attachment: 'ATT-1' } },
  ]);
});

test('attachment upload is private and registers only the returned file URL', async () => {
  const uploadCalls = [];
  const apiCalls = [];
  const file = { name: 'receipt.png', size: 10 };
  const result = await uploadExpenseAttachment('OA-1', 'L1', file, {
    upload: async (value, options) => { uploadCalls.push({ value, options }); return { file_url: '/private/files/receipt.png' }; },
    api: async (action, args) => { apiCalls.push({ action, args }); return { name: 'ATT-1' }; },
  });
  assert.deepEqual(result, { name: 'ATT-1' });
  assert.equal(uploadCalls[0].value, file);
  assert.equal(uploadCalls[0].options.isPrivate, true);
  assert.deepEqual(apiCalls[0], { action: 'upload_expense_attachment', args: { name: 'OA-1', line_key: 'L1', file_url: '/private/files/receipt.png' } });
});

test('attachment preview consumes the one-time token with POST', async () => {
  const api = async (action) => {
    assert.equal(action, 'preview_expense_attachment');
    return { token: 'secure-token', preview_method: 'POST', preview_url: '/preview', mime_type: 'application/pdf', display_name: 'receipt.pdf' };
  };
  const fetcher = async (url, options) => {
    assert.equal(url, '/preview');
    assert.equal(options.method, 'POST');
    assert.match(options.body, /secure-token/);
    return { ok: true, blob: async () => new Blob(['%PDF-'], { type: 'application/pdf' }) };
  };
  const value = await fetchExpenseAttachmentPreview('ATT-1', { api, fetcher });
  assert.equal(value.metadata.display_name, 'receipt.pdf');
  assert.equal(value.blob.type, 'application/pdf');
});


test('stale-step errors are recognised so pages reload', async () => {
  const { isStaleStepError } = await import('../src/lib/expenseWorkflow.js');
  assert.equal(isStaleStepError(new Error('这张单据已经变化，现在在「总经理」这一步')), true);
  assert.equal(isStaleStepError(new Error('页面版本过旧，请刷新后再操作。')), true);
  assert.equal(isStaleStepError(new Error('驳回原因必填')), false);
});
