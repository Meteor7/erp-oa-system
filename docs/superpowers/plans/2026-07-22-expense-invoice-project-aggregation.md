# Expense Invoice Project Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver project-name aggregation, editable expense items, manual no-invoice expenses, corrected payment fields, single-amount OCR behavior, responsive upload UI, and compatible reporting without losing existing invoice or approval data.

**Architecture:** Persist one auditable source row per invoice or manual expense, then compute project groups on the server for every consumer. Draft mutations operate on source rows under request and invoice locks; UI, statistics, export, withdrawal, and submission use the same grouped serializer. OCR single-amount normalization remains in the OCR parser where the raw labeled evidence is available.

**Tech Stack:** Frappe/ERPNext Python APIs and DocTypes, Vue 3, frappe-ui, Tailwind CSS, Node built-in test runner, pytest, PaddleOCR service.

## Global Constraints

- Group only by normalized non-empty project name; blank project names remain independent.
- Expense item is editable from existing category suggestions and also accepts free text.
- Single unlabeled monetary value populates total amount only; pre-tax and tax stay blank.
- Existing invoices, attachments, duplicate state, request links, approvals, statistics, and audit records must not be deleted or bulk-rewritten.
- Manual expense fields are project name, expense item, date, total amount, description, and no-invoice reason.
- Applicant is the current login and read-only; approval supervisor remains server-derived.
- Payment types are 支付个人 and 对公支付; legacy 付款申请 remains readable.
- Invoice authenticity verification and encrypted-file whitelist work are out of scope.
- All project-file writes must pass plaintext header verification because TipRay transparent encryption is active.
- Work remains on feat/ocr-monthly-timesheet-integration; do not merge to main or push a remote.

---

### Task 1: Expense source schema and project grouping domain

**Files:**
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_expense_line/oa_approval_expense_line.json`
- Modify: `rayher_hr_payroll/custom_fields.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Test: `rayher_hr_payroll/tests/test_doctype_json.py`
- Test: `rayher_hr_payroll/tests/test_invoice_request_integration.py`

**Interfaces:**
- Produces: `_group_expense_sources(rows: list, invoices_by_key: dict[str, list] | None = None) -> list[dict]`
- Produces: serialized source fields `expense_item` and `no_invoice_reason`.
- Consumes: existing `line_key`, `source_invoice`, seven OCR fields, and attachment lookup.

- [ ] **Step 1: Write failing schema and grouping tests**

Add assertions that the child DocType contains `expense_item: Data` and `no_invoice_reason: Small Text`. Add cases with two same-project invoices, two blank-project invoices, and one manual source:

```python
groups = mod._group_expense_sources([
    {"line_key": "a", "project_name": "项目甲", "amount_before_tax": 100, "tax_amount": 6, "total_amount": 106},
    {"line_key": "b", "project_name": "项目甲", "amount_before_tax": 50, "tax_amount": 3, "total_amount": 53},
    {"line_key": "c", "project_name": "", "total_amount": 10},
    {"line_key": "d", "project_name": "", "total_amount": 20},
])
assert len(groups) == 3
assert groups[0]["project_name"] == "项目甲"
assert groups[0]["total_amount"] == 159
assert groups[0]["source_line_keys"] == ["a", "b"]
assert groups[1]["group_key"] != groups[2]["group_key"]
```

- [ ] **Step 2: Run tests and verify failure**

Run each file in a fresh process:

```powershell
python -m pytest rayher_hr_payroll/tests/test_doctype_json.py -q
python -m pytest rayher_hr_payroll/tests/test_invoice_request_integration.py -q
```

Expected: FAIL because the fields and grouping helper do not exist.

- [ ] **Step 3: Add fields and the minimal pure grouping helper**

Add the two DocType/custom-field definitions after `project_name`. Implement a pure helper that trims project names, uses `project:<name>` for non-empty groups and `line:<line_key>` for blank rows, sums optional amounts without turning all-null columns into zero, preserves source keys, and reports conflicting expense items as `needs_expense_item=True`.

- [ ] **Step 4: Serialize source and grouped data**

Extend `_serialize_expense_line` and request summaries with `expense_item`, `no_invoice_reason`, and `project_groups`. Keep `expense_lines` as source rows for compatibility.

- [ ] **Step 5: Re-run tests**

Expected: both files PASS.

- [ ] **Step 6: Commit**

```powershell
git add rayher_hr_payroll/custom_fields.py rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_expense_line/oa_approval_expense_line.json rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests/test_doctype_json.py rayher_hr_payroll/tests/test_invoice_request_integration.py
git commit -m "feat: add grouped expense source model"
```

### Task 2: Safe draft source mutation and manual expenses

**Files:**
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `rayher_hr_payroll/invoice_ocr/service.py`
- Test: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Test: `rayher_hr_payroll/tests/test_invoice_ocr_service.py`

**Interfaces:**
- Produces: whitelisted POST `save_draft_expense_sources(name: str, source_lines: str | list) -> dict`.
- Consumes: Task 1 grouping and serialization helpers.

- [ ] **Step 1: Write failing authorization and mutation tests**

Cover draft owner success, non-owner rejection, non-draft rejection, same-project regrouping, manual source creation, manual source deletion, required no-invoice reason, positive amount, invoice project-name synchronization, and request total recalculation.

```python
result = mod.save_draft_expense_sources("OA-1", [
    {"line_key": "invoice-a", "project_name": "项目甲", "expense_item": "交通费"},
    {"line_key": "", "project_name": "项目甲", "expense_item": "交通费",
     "issue_date": "2026-07-22", "total_amount": "80.00",
     "description": "出差津贴", "no_invoice_reason": "出差津贴无发票"},
])
assert result["amount"] == 186
assert len(result["project_groups"]) == 1
assert result["project_groups"][0]["manual_source_count"] == 1
```

- [ ] **Step 2: Run both test files and verify failure**

Expected: endpoint missing.

- [ ] **Step 3: Implement locked draft mutation**

Acquire the request lock, load the current document, enforce edit permission and draft status, reject unknown invoice-backed line keys, create UUIDv4 line keys for new manual rows, validate manual fields, set expense lines, synchronize invoice record project names, recalculate `doc.amount`, refresh invoice summary, append an operation event, and save once.

- [ ] **Step 4: Re-run tests**

Expected: PASS with invoice link invariants unchanged.

- [ ] **Step 5: Commit**

```powershell
git add rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/invoice_ocr/service.py rayher_hr_payroll/tests/test_invoice_request_integration.py rayher_hr_payroll/tests/test_invoice_ocr_service.py
git commit -m "feat: edit draft expense sources safely"
```

### Task 3: Partial withdrawal and grouped validation

**Files:**
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `rayher_hr_payroll/invoice_ocr/service.py`
- Test: `rayher_hr_payroll/tests/test_invoice_request_integration.py`

**Interfaces:**
- Consumes: source-level line keys from Tasks 1-2.
- Produces: partial withdrawal that removes only selected invoice sources and recomputes groups.

- [ ] **Step 1: Add a failing two-invoice same-project withdrawal test**

Push two invoices under one project group, withdraw one invoice, and assert the request retains one source, one project group, the remaining attachment, and the reduced amount.

- [ ] **Step 2: Run the test and confirm the current whole-line deletion behavior fails**

- [ ] **Step 3: Change withdrawal to source-level deletion**

Delete only rows whose source invoice is selected. Do not delete by a shared display group key. Rebuild summaries, preserve manual sources, and append selected invoice names to the operation event.

- [ ] **Step 4: Add submission validation**

Before submitting, reject groups missing project name or expense item and manual rows missing no-invoice reason. Keep existing invoice amount-difference checks source-level.

- [ ] **Step 5: Run integration tests and commit**

```powershell
python -m pytest rayher_hr_payroll/tests/test_invoice_request_integration.py -q
git add rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/invoice_ocr/service.py rayher_hr_payroll/tests/test_invoice_request_integration.py
git commit -m "fix: preserve grouped expenses on partial withdrawal"
```

### Task 4: Payment options and applicant identity

**Files:**
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Test: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Test: `frontend/tests/invoice-upload-workbench-source.test.js`

**Interfaces:**
- Produces: options payload `current_applicant: {employee, employee_name, user}`.
- Produces: canonical payment type `支付个人` with legacy read mapping from `付款申请`.

- [ ] **Step 1: Add failing backend and source tests**

Assert new options, current applicant serialization, legacy display mapping, and absence of editable supervisor input in the push modal.

- [ ] **Step 2: Run tests and confirm failure**

- [ ] **Step 3: Implement canonical options and compatibility mapping**

Use the session user to resolve Employee. Keep the stored supervisor field server-derived for routing. Accept legacy `付款申请` input only for existing records and serialize it as `支付个人`.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m pytest rayher_hr_payroll/tests/test_invoice_request_integration.py -q
cd frontend
node --test tests/invoice-upload-workbench-source.test.js
cd ..
git add rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests/test_invoice_request_integration.py frontend/tests/invoice-upload-workbench-source.test.js
git commit -m "feat: align reimbursement payment fields"
```

### Task 5: Expense draft editor UI and manual-add dialog

**Files:**
- Modify: `frontend/src/components/ExpenseWorkbench.vue`
- Modify: `frontend/src/pages/OAApprovals.vue`
- Test: `frontend/tests/oa-source.test.js`
- Test: `frontend/tests/expense-reporting.test.js`

**Interfaces:**
- Consumes: `selectedRequest.project_groups`, expense category options, and `save_draft_expense_sources`.
- Produces: inline project/expense-item editing and a manual expense dialog.

- [ ] **Step 1: Add failing source-contract tests**

Assert the new API resource URL, 9-column table, editable draft controls, datalist/free-text expense item, manual-add button, six confirmed manual fields, and preservation of approval/payment/audit sections.

- [ ] **Step 2: Run Node tests and verify failure**

- [ ] **Step 3: Implement draft-local state**

Clone source rows when a draft opens. Render project groups, fan group edits back to all member source lines, and submit the complete source list through `save_draft_expense_sources`. Disable these controls outside draft status.

- [ ] **Step 4: Implement manual dialog**

Require project name, expense item, date, positive total, description, and no-invoice reason. Append a local manual source and save through the same endpoint. Render 无票 in the file column.

- [ ] **Step 5: Preserve multi-invoice preview**

Use every invoice returned for the group and render 查看发票 1…N. Keep `InvoicePreviewDrawer` close, escape, and overlay behavior.

- [ ] **Step 6: Run tests, build, and commit**

```powershell
cd frontend
node --test tests/oa-source.test.js tests/expense-reporting.test.js tests/invoice-preview-close-source.test.js
npm run build
cd ..
git add frontend/src/components/ExpenseWorkbench.vue frontend/src/pages/OAApprovals.vue frontend/tests/oa-source.test.js frontend/tests/expense-reporting.test.js
git commit -m "feat: edit grouped reimbursement drafts"
```

### Task 6: Invoice push modal and responsive workbench

**Files:**
- Modify: `frontend/src/components/invoice/InvoiceUploadWorkbench.vue`
- Test: `frontend/tests/invoice-upload-workbench-source.test.js`
- Test: `frontend/tests/invoice-preview-close-source.test.js`

**Interfaces:**
- Consumes: Task 4 current applicant and payment options.
- Produces: responsive list/editor layout with unchanged OCR actions.

- [ ] **Step 1: Expand failing source tests**

Assert read-only applicant, 支付个人/对公支付, 支付方式 label, required field order, responsive breakpoints, no page-level fixed `min-width`, and retained upload/confirm/preview/push/withdraw controls.

- [ ] **Step 2: Run tests and verify failure**

- [ ] **Step 3: Recompose header and split layout**

Use a stable action header, equal KPI cards, `grid-cols-1 2xl:grid-cols-[minmax(0,1fr)_420px]`, an internally scrollable record table, and a sticky confirmation panel. Collapse to one column below 2xl without page-level horizontal scrolling.

- [ ] **Step 4: Reorder push fields**

Render rows in the confirmed order and remove the supervisor input. Submit only applicant-independent payment data; routing stays on the backend.

- [ ] **Step 5: Run focused tests and build**

Expected: tests PASS and Vite build exits 0.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/components/invoice/InvoiceUploadWorkbench.vue frontend/tests/invoice-upload-workbench-source.test.js frontend/tests/invoice-preview-close-source.test.js
git commit -m "feat: refine invoice upload workbench"
```

### Task 7: Single-amount OCR normalization

**Files:**
- Modify: `services/invoice_ocr/invoice_ocr/parser.py`
- Test: `services/invoice_ocr/tests/test_parser.py`
- Test: `services/invoice_ocr/tests/test_pipeline.py`

**Interfaces:**
- Produces: parser result where one unlabeled amount yields `amount_before_tax=None`, `tax_amount=None`, and `total_amount=value`.

- [ ] **Step 1: Add failing railway/single-amount parser tests**

Use OCR lines containing one amount and no 税额/金额/合计 labels, plus control fixtures for zero-tax invoices and labeled pre-tax amounts.

```python
result = parse_invoice(["铁路电子客票", "票价：10.00", "发票号码：01117014"])
assert result.amount_before_tax is None
assert result.tax_amount is None
assert result.total_amount == Decimal("10.00")
```

- [ ] **Step 2: Run parser and pipeline tests and verify failure**

```powershell
cd services/invoice_ocr
python -m pytest tests/test_parser.py tests/test_pipeline.py -q
cd ../..
```

- [ ] **Step 3: Implement evidence-based fallback**

Count normalized monetary candidates after excluding dates, identifiers, tax rates, and quantities. Apply total-only fallback only when exactly one candidate remains and no explicit pre-tax/tax labels were recognized. Do not infer from equal numeric values.

- [ ] **Step 4: Run the full OCR service suite**

Expected: all service tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add services/invoice_ocr/invoice_ocr/parser.py services/invoice_ocr/tests/test_parser.py services/invoice_ocr/tests/test_pipeline.py
git commit -m "fix: classify single invoice amount as total"
```

### Task 8: Statistics, exports, and compatibility regression

**Files:**
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `frontend/src/components/expense/ExpenseStatistics.vue`
- Modify: `frontend/src/lib/expenseReporting.js`
- Test: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Test: `frontend/tests/expense-reporting.test.js`
- Test: `frontend/tests/expense-categories.test.js`

**Interfaces:**
- Consumes: Task 1 project groups.
- Produces: expense-item filter/column and grouped report/export rows.

- [ ] **Step 1: Add failing grouped reporting tests**

Assert one report row per project group, summed amounts, expense item, manual no-invoice inclusion, paid/unpaid totals, and unchanged approval history.

- [ ] **Step 2: Implement grouped report rows and frontend filter/export**

Keep request-level totals derived from source rows and present group rows for detail reporting. Add 费用项目 to filter and export mappings.

- [ ] **Step 3: Run backend and frontend regression files**

Expected: all focused tests PASS.

- [ ] **Step 4: Commit**

```powershell
git add rayher_hr_payroll/api/oa_entry.py frontend/src/components/expense/ExpenseStatistics.vue frontend/src/lib/expenseReporting.js rayher_hr_payroll/tests/test_invoice_request_integration.py frontend/tests/expense-reporting.test.js frontend/tests/expense-categories.test.js
git commit -m "feat: report grouped reimbursement expenses"
```

### Task 9: Full verification and deployment

**Files:**
- Generated: `rayher_hr_payroll/public/frontend/**`
- Update only if required: `docs/invoice-ocr-runbook.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified branch and deployed live application.

- [ ] **Step 1: Run every changed backend test file in a separate Python process**

Expected: each exits 0.

- [ ] **Step 2: Run all frontend Node tests and Vite build**

```powershell
cd frontend
node --test tests/*.test.js
npm run build
cd ..
```

Expected: all tests PASS and build succeeds.

- [ ] **Step 3: Run the full OCR service test suite**

Expected: PASS.

- [ ] **Step 4: Verify TipRay plaintext and Git cleanliness**

Check every changed text file for `%TSD-Header-`, run `git diff --check`, and inspect `git status --short`.

- [ ] **Step 5: Back up site and deployed files**

Create a timestamped backup before copying application or schema changes.

- [ ] **Step 6: Deploy schema, backend, OCR service, and frontend build**

Run migrations, clear cache, restart only affected services, and wait for healthy status.

- [ ] **Step 7: Run live API and browser acceptance**

Complete upload → OCR → confirm → push → edit project/expense item → add manual allowance → save → preview every invoice → withdraw one invoice. Verify statistics and approval records. Capture 1366 and 1920 screenshots.

- [ ] **Step 8: Verify data preservation**

Record before/after counts and identities for OCR invoices, linked requests, attachments, and approvals; expected difference is zero except deliberate acceptance-test records.

- [ ] **Step 9: Commit generated assets if repository policy tracks them**

```powershell
git add rayher_hr_payroll/public/frontend
git commit -m "build: publish grouped expense workflow"
```
