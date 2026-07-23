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
});

test('expense lines expose private supplemental attachments', () => {
  assert.match(workbench, /handleExpenseAttachments/);
  assert.match(workbench, /accept="\.pdf,\.jpg,\.jpeg,\.png"/);
  assert.match(workbench, /fetchExpenseAttachmentPreview/);
  assert.match(workbench, /:preview-loader=/);
  assert.match(workflow, /body\.append\('is_private', '1'\)/);
  assert.match(workflow, /MAX_EXPENSE_ATTACHMENTS\s*=\s*10/);
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
