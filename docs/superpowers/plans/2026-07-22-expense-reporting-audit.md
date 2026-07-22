# Expense Reporting and Audit Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore independent expense statistics and approval-record views, explain invoice checkbox eligibility, and preserve confirmed-invoice push/withdraw behavior without changing existing business data.

**Architecture:** Keep `ExpenseWorkbench.vue` as the four-view shell and the single request-detail owner. Add two read-only Vue views backed by permission-scoped Frappe endpoints. Reuse the current seven-field lines, approval steps, operation log, invoice preview, push and withdrawal services. Apply filters/limits server-side; no DocType or database migration is required.

**Tech Stack:** Python/Frappe, Vue 3, frappe-ui, Node `node:test`, pytest, Vite/Yarn, Docker-hosted Frappe bench.

## Global Constraints

- Work only on `feat/invoice-ocr-reimbursement`; never merge or push `main`.
- Never delete/rewrite invoice, request, batch, attachment, approval, or payment data.
- Keep manual/no-invoice reimbursement, confirmation-before-push, one invoice per seven-field line, and all withdrawal paths.
- Keep TipRay whitelist work out of this feature.
- Use trusted Docker/Linux writers and reject `%TSD-Header-###%` files.
- Begin each behavior change with a failing test and run complete suites before deployment.

---

## Task 1: Permission-scoped backend queries

**Files:**
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`

- [ ] **Step 1: Test exact request visibility**

Add a failing test for:

```python
oa_entry.list_requests(
    view="all", limit=1,
    request_type=oa_entry.REQUEST_EXPENSE_PAYMENT,
    name="REQ-ALICE",
)
```

Assert an owner sees their request, a normal employee cannot read another employee's request, and `Accounts User` can. Run:

```powershell
python -m pytest rayher_hr_payroll/tests/test_invoice_request_integration.py -k "list_requests and exact_name" -q
```

Expected: failure because `name` is unsupported.

- [ ] **Step 2: Extend `list_requests` compatibly**

Use:

```python
@frappe.whitelist()
def list_requests(view="mine", limit=50, request_type=None, name=None):
```

Normalize/bound `name`, add it only when nonempty, and retain the current privileged-role versus owner/employee scope, ordering, summary, and 200-row cap.

- [ ] **Step 3: Test statistics filters, totals, and permissions**

Create requests covering two invoice lines, manual/no-invoice, paid/unpaid, other employee, departments, dates, categories, projects, statuses, and sources. Add a failing call to:

```python
oa_entry.get_expense_statistics(
    from_date="2026-07-01", to_date="2026-07-31",
    department="研发部", employee="EMP-1",
    invoice_category="电子发票（普通发票）",
    project_name="文具印章",
    workflow_status=oa_entry.STATUS_PAID,
    payment_status="已付款",
    source_type=oa_entry.SOURCE_INVOICE_PUSH,
)
```

Require `{"totals", "rows", "truncated"}`, with totals for unique requests, unique invoices, pre-tax, tax, total, paid, and unpaid. Prove normal users cannot aggregate another user's request and privileged users can with `view="all"`.

- [ ] **Step 4: Test approval records and permissions**

Create an acted step, a pending step, and operation events for invoice push, submit, request withdrawal, payment, and payment withdrawal. Add failing tests filtering request keyword, applicant, department, approver, action, workflow status, and dates. Require each record to include request, subject, employee, department, source, current status, event type, step, approvers, action, actor, time, and note. Repeat normal versus privileged visibility assertions.

Run:

```powershell
python -m pytest rayher_hr_payroll/tests/test_invoice_request_integration.py -k "expense_statistics or approval_records" -q
```

Expected: endpoints are absent.

- [ ] **Step 5: Implement shared scoped-query helpers**

Add private helpers that build `REQUEST_EXPENSE_PAYMENT` filters, apply existing `PRIVILEGED_ROLES`/owner/employee scope, normalize bounded text/dates, clamp to 1,000 documents, and report truncation. Never accept client field names or SQL fragments.

- [ ] **Step 6: Implement statistics**

Add:

```python
@frappe.whitelist()
def get_expense_statistics(
    view="mine", from_date=None, to_date=None, department=None, employee=None,
    invoice_category=None, project_name=None, workflow_status=None,
    payment_status=None, source_type=None, limit=1000,
):
```

Return a row per matching request/expense-line with request metadata, source/status, category/project/invoice number, and pre-tax/tax/total/paid/unpaid. Emit a zero-safe row for a manual request with no lines. Count unique requests and `source_invoice` values; use request invoice count only as fallback. Sum with `Decimal`.

- [ ] **Step 7: Implement approval records**

Add:

```python
@frappe.whitelist()
def list_expense_approval_records(
    view="mine", request_keyword=None, employee=None, department=None,
    approver=None, action=None, workflow_status=None,
    from_date=None, to_date=None, limit=1000,
):
```

Flatten approval steps and `operation_log` into a stable shape. Filter only permission-scoped documents, sort newest acted records first and pending steps last, cap at 1,000 records, and return `{"records": ..., "truncated": ...}`.

- [ ] **Step 8: Verify and commit**

Run:

```powershell
python -m pytest rayher_hr_payroll/tests/test_invoice_request_integration.py -q
python -m pytest rayher_hr_payroll/tests -q
git diff --check
```

Plaintext-check modified files, then commit:

```powershell
git add rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests/test_invoice_request_integration.py
git commit -m "feat: add expense reporting APIs"
```

---

## Task 2: Explain disabled invoice checkboxes

**Files:**
- Modify: `frontend/src/lib/invoiceOcr.js`
- Modify: `frontend/src/components/invoice/InvoiceUploadWorkbench.vue`
- Modify: `frontend/tests/invoice-ocr.test.js`
- Modify: `frontend/tests/oa-source.test.js`

- [ ] **Step 1: Add failing helper/UI tests**

Require:

```javascript
invoiceSelectionReason({ recognition_status: '已确认', request: '' }) === ''
invoiceSelectionReason({ recognition_status: '待确认', request: '' }) === '请先确认发票内容'
invoiceSelectionReason({ recognition_status: '疑似重复', request: '' }) === '疑似重复发票不能下推'
invoiceSelectionReason({ recognition_status: '失败', request: '' }) === '识别失败，不能下推'
invoiceSelectionReason({ recognition_status: '已确认', request: 'OA-1' }) === '已下推到 OA-1'
```

Require visible `selectionReason(row)` beside disabled rows. Run focused tests and confirm failure.

- [ ] **Step 2: Implement helper and display**

Export `invoiceSelectionReason`; define `canCheck(row)` as no reason. Show the reason under status and in checkbox `title`. Keep selection restricted to exactly confirmed/unlinked rows and show `可下推 N 张`.

- [ ] **Step 3: Verify and commit**

Run focused tests, plaintext checks, and `git diff --check`; commit:

```powershell
git add frontend/src/lib/invoiceOcr.js frontend/src/components/invoice/InvoiceUploadWorkbench.vue frontend/tests/invoice-ocr.test.js frontend/tests/oa-source.test.js
git commit -m "fix: explain invoice push eligibility"
```

---

## Task 3: Independent expense statistics view

**Files:**
- Create: `frontend/src/components/expense/ExpenseStatistics.vue`
- Create: `frontend/src/lib/expenseReporting.js`
- Create: `frontend/tests/expense-reporting.test.js`
- Modify: `frontend/tests/oa-source.test.js`

- [ ] **Step 1: Add failing helper/component tests**

Test `toExpenseStatisticsParams` maps filters, trims strings, omits empties, and adds `view: "all"` plus `limit: 1000`. Test `money(null) === "?0.00"` and `money("35.98") === "?35.98"`. Require date, department, applicant, category, project, workflow/payment, source filters; seven metric cards; search/reset/refresh; table; loading/error/empty/truncated; and `open-request`.

- [ ] **Step 2: Implement helpers**

Export `toExpenseStatisticsParams`, `toApprovalRecordParams`, `money`, and `dateTime` from `expenseReporting.js`.

- [ ] **Step 3: Implement `ExpenseStatistics.vue`**

Use a read-only `createResource` for `get_expense_statistics`. Display the server-provided request count, invoice count, pre-tax, tax, total, paid, and unpaid totals. Render filtered rows and emit only the request number on open. Do not recompute cross-request totals in the browser.

- [ ] **Step 4: Verify and commit**

Run focused tests, plaintext checks, and `git diff --check`; commit:

```powershell
git add frontend/src/components/expense/ExpenseStatistics.vue frontend/src/lib/expenseReporting.js frontend/tests/expense-reporting.test.js frontend/tests/oa-source.test.js
git commit -m "feat: add expense statistics view"
```

---

## Task 4: Independent approval-record view

**Files:**
- Create: `frontend/src/components/expense/ExpenseApprovalRecords.vue`
- Modify: `frontend/tests/expense-reporting.test.js`
- Modify: `frontend/tests/oa-source.test.js`

- [ ] **Step 1: Add failing component tests**

Require `list_expense_approval_records`, all approved filters, the full audit columns, `open-request`, and loading/error/empty/truncated states.

- [ ] **Step 2: Implement the component**

Use a read-only resource and `toApprovalRecordParams`. Render pending steps, acted steps, and operation events. Do not expose OCR payloads, private attachment paths, or payment account values.

- [ ] **Step 3: Verify and commit**

Run focused tests, plaintext checks, and `git diff --check`; commit:

```powershell
git add frontend/src/components/expense/ExpenseApprovalRecords.vue frontend/tests/expense-reporting.test.js frontend/tests/oa-source.test.js
git commit -m "feat: add expense approval records view"
```

---

## Task 5: Four-view integration and exact detail loading

**Files:**
- Modify: `frontend/src/components/ExpenseWorkbench.vue`
- Modify: `frontend/tests/oa-source.test.js`

- [ ] **Step 1: Add failing integration contracts**

Require exactly 上传发票 / 费用报销流 / 费用统计 / 审批记录, imports/mounts for both new views, and reuse of the existing detail modal. Continue rejecting 主看板/子看板 language.

Require report rows absent from the current 200-card board cache to query `list_requests` with:

```javascript
{ view: 'all', limit: 1, request_type: REQUEST_TYPE, name }
```

and show permission/not-found feedback.

- [ ] **Step 2: Implement navigation**

Use:

```javascript
const NAV_ITEMS = [
  { key: 'invoices', label: '上传发票' },
  { key: 'board', label: '费用报销流' },
  { key: 'statistics', label: '费用统计' },
  { key: 'audit', label: '审批记录' },
];
```

Keep existing board cards, manual/no-invoice creation, seven fields, invoice preview, approval timeline, logs, payment, and withdrawals.

- [ ] **Step 3: Implement exact request opening**

Look in board data first; otherwise fetch the exact permitted request. Reuse the single detail modal. After mutations refresh board plus the active report and invoice linkage where relevant.

- [ ] **Step 4: Verify and commit**

Run:

```powershell
yarn --cwd frontend test --test-name-pattern "four views|exact request|expense workbench"
yarn --cwd frontend test
git diff --check
```

Plaintext-check and commit:

```powershell
git add frontend/src/components/ExpenseWorkbench.vue frontend/tests/oa-source.test.js
git commit -m "feat: restore expense reporting navigation"
```

---

## Task 6: Complete verification and live deployment

- [ ] **Step 1: Scope/plaintext checks**

Run `git status --short`, `git diff --check`, and `git diff --stat`; reject any changed file beginning `%TSD-Header-###%`.

- [ ] **Step 2: Complete suites**

Run:

```powershell
python -m pytest rayher_hr_payroll/tests -q
yarn --cwd frontend test
```

Record actual pass counts.

- [ ] **Step 3: Build/deploy in the existing Frappe container**

Copy only reviewed branch source into `rayher-bench`, run `yarn build`, clear site cache, and restart services. Do not migrate. Sync back only reviewed generated manifests/bundles, plaintext-check them, and exclude runtime files.

- [ ] **Step 4: Live browser acceptance**

At `http://203.0.113.88:8000/rayher/approval/purchase`, verify:

1. exactly four navigation entries;
2. disabled checkbox reasons;
3. confirmed unlinked selection;
4. one invoice to one seven-field line on push;
5. linked preview opens and closes;
6. push withdrawal unlinks without deletion;
7. manual/no-invoice creation remains;
8. statistics filters and seven totals;
9. statistics row opens full detail;
10. approval steps/events include actor/time/note;
11. approval row opens full detail;
12. unauthorized requests remain hidden;
13. existing approval/payment/withdrawal behavior remains;
14. no console or reporting API errors.

Use reversible test records only and delete no history.

- [ ] **Step 5: Final regression and report**

Rerun complete suites and Git checks. Commit reviewed generated assets as `build: deploy expense reporting views`. Report branch/commits, pass counts, live URL, acceptance results, separate TipRay whitelist limitation, `main` untouched, and no business-data deletion.
