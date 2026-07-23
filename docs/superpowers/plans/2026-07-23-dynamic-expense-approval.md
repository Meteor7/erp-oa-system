# Dynamic Expense Approval Implementation Plan

> **For implementation:** Execute task-by-task in the current feature branch. Follow test-driven development and verification-before-completion. Do not merge or push `main`.

**Goal:** Deliver synchronized frontend/backend support for derived invoice totals, employee descriptions and line attachments, Finance classification, targeted rejection, recursive before/after add-sign, and working secure invoice preview.

**Architecture:** Extend the existing Frappe request/step/line models and transaction-locked APIs. Store supplemental files as private Frappe Files linked through a dedicated attachment DocType. Keep server-generated capability and rejection-target data authoritative. Replace sandboxed PDF plugin preview with local PDF rendering while retaining one-time tokens.

**Tech Stack:** Python/Frappe, Vue 3, frappe-ui, Node `node:test`, pytest, Vite/Yarn, Docker-hosted Frappe bench.

## Global Constraints

- Work only on `feat/ocr-monthly-timesheet-integration`; keep `main` unchanged.
- Do not delete or rewrite existing invoice, reimbursement, approval, attachment, or payment history.
- Use trusted WSL/Docker/cmd writers and reject files with `%TSD-Header-`.
- Begin each behavior with a failing test.
- Deploy backend, schema migration, and exact frontend build together after backup.
- No external OCR or document API.

---

## Task 1: Amount derivation and safe historical backfill

**Files:**
- Modify: `rayher_hr_payroll/tests/test_invoice_ocr_service.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/invoice_ocr/service.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Create: `rayher_hr_payroll/patches/v1_0/derive_missing_invoice_totals.py`
- Modify: `rayher_hr_payroll/patches.txt`
- Modify: `frontend/tests/invoice-ocr.test.js`
- Modify: `frontend/src/lib/invoiceOcr.js`
- Modify: `frontend/src/components/invoice/InvoiceUploadWorkbench.vue`

- [ ] Add failing tests: blank total plus complete pre-tax/tax derives exact cents; supplied total stays unchanged; mismatch warning remains; railway total-only remains valid; reimbursement normalization derives before summing.
- [ ] Run focused tests and confirm failures.
- [ ] Add one decimal-safe backend helper shared by OCR normalization/updates and reimbursement normalization.
- [ ] Add frontend derived-total helper and update the edit panel immediately when components change.
- [ ] Add an idempotent patch that updates only records with null/blank total and both components present; log counts only.
- [ ] Run focused backend/frontend tests and `git diff --check`.

---

## Task 2: Schema for descriptions, attachments, and stable dynamic steps

**Files:**
- Modify: `rayher_hr_payroll/tests/test_doctype_json.py`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_expense_line/oa_approval_expense_line.json`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_step/oa_approval_step.json`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_expense_line_attachment/__init__.py`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_expense_line_attachment/oa_expense_line_attachment.py`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_expense_line_attachment/oa_expense_line_attachment.json`
- Create: `rayher_hr_payroll/patches/v1_0/backfill_approval_step_keys.py`
- Modify: `rayher_hr_payroll/patches.txt`

- [ ] Add failing DocType contract tests for `expense_description`, attachment ownership/metadata, and step identity/add-sign fields.
- [ ] Add nullable fields and the new attachment DocType with useful indexes and no destructive defaults.
- [ ] Add deterministic step-key backfill for existing route instances.
- [ ] Verify JSON parsing, field order, uniqueness/search indexes, and patch idempotency.

---

## Task 3: Employee draft rules and Finance classification

**Files:**
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `frontend/tests/oa-source.test.js`
- Modify: `frontend/src/components/ExpenseWorkbench.vue`

- [ ] Add failing tests proving employee submission permits blank expense items but rejects missing descriptions.
- [ ] Add failing tests for `save_finance_expense_items`: only active Finance audit approver can edit existing line keys; amounts/source/description cannot be changed.
- [ ] Add capability tests for employee, active Finance, other active approver, and non-approver.
- [ ] Change draft normalization/validation and legacy-description fallback without breaking manual/no-invoice rules.
- [ ] Implement Finance classification API and Finance approval blocker.
- [ ] Return `can_approve`, `can_reject`, `can_add_sign`, `can_edit_expense_items`, and classification readiness from summaries.
- [ ] Run focused integration tests.

---

## Task 4: Private supplemental line attachments

**Files:**
- Create: `rayher_hr_payroll/expense_attachments.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `frontend/src/lib/expenseWorkflow.js`
- Modify: `frontend/tests/expense-workflow.test.js`
- Modify: `frontend/src/components/ExpenseWorkbench.vue`

- [ ] Add failing backend tests for upload registration, line membership, private File ownership, PDF/JPEG/PNG signatures, 10 MB limit, 10-per-line limit, read permissions, draft-only delete, and cleanup on registration failure.
- [ ] Reuse hardened private-file/token primitives where safe; keep attachment authorization separate from invoice ownership.
- [ ] Implement upload/register/delete/list/preview APIs under request locks.
- [ ] Add frontend upload validation/API helpers and unit tests.
- [ ] Add per-line description, attachment list, upload, preview, and draft-only delete controls.
- [ ] Verify original invoice files remain separate and unchanged.

---

## Task 5: Targeted rejection state machine

**Files:**
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `frontend/src/lib/expenseWorkflow.js`
- Modify: `frontend/tests/expense-workflow.test.js`
- Modify: `frontend/src/components/ExpenseWorkbench.vue`

- [ ] Add failing tests for backend-computed eligible targets.
- [ ] Add failing tests for reject-to-applicant, reject-to-earlier-step, preserved earlier steps, reset downstream base/add-sign steps, required reason, and invalid/stale targets.
- [ ] Implement stable target lookup and atomic reset/current-pointer logic.
- [ ] Preserve approve call compatibility; require target for reject.
- [ ] Add structured operation events.
- [ ] Add rejection dialog with only server-provided targets and required reason.
- [ ] Run focused backend/frontend tests.

---

## Task 6: Recursive before/after add-sign

**Files:**
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `frontend/src/lib/expenseWorkflow.js`
- Modify: `frontend/tests/expense-workflow.test.js`
- Modify: `frontend/src/components/ExpenseWorkbench.vue`

- [ ] Add failing tests for before/after insertion, reindexing, current pointer, enabled-user resolution, required opinion, recursive add-sign, self-add rejection, unresolved duplicate rejection, 20-operation limit, and stale/double requests.
- [ ] Implement `add_sign_request` under the request lock using stable step keys.
- [ ] Return add-sign count/remaining allowance and step metadata.
- [ ] Add add-sign dialog with person selection, before/after, opinion, and remaining count.
- [ ] Update timeline to distinguish base/add-sign steps and rejection paths.
- [ ] Run focused backend/frontend tests.

---

## Task 7: Secure working PDF preview

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/yarn.lock`
- Modify: `frontend/tests/invoice-ocr-source.test.js`
- Modify: `frontend/src/components/invoice/InvoicePreviewDrawer.vue`
- Create: `frontend/src/lib/pdfPreview.js`
- Create: `frontend/tests/pdf-preview.test.js`

- [ ] Consult official PDF.js documentation for the current pinned package and worker setup.
- [ ] Add failing tests that reject sandboxed PDF iframe use and require renderer cleanup/page controls.
- [ ] Add pinned local PDF renderer dependency and worker integration; do not call external CDNs.
- [ ] Render PDF pages to canvas, keep images on blob/image path, preserve watermark, and release loading tasks/object URLs on close/reopen.
- [ ] Show bounded loading/error/page state.
- [ ] Run focused tests and production build.

---

## Task 8: Full verification, backup, migration, deployment, and branch commit

- [ ] Plaintext-check every changed/generated file and run `git diff --check`.
- [ ] Run full backend suite: `python -m pytest rayher_hr_payroll/tests -q`.
- [ ] Run full frontend suite: `node --test frontend/tests/*.test.js`.
- [ ] Build: `yarn --cwd frontend build`.
- [ ] Create a database/private-files backup before migration.
- [ ] Copy reviewed source/build to `rayher-bench`, run `bench --site rayher.localhost migrate`, clear cache, and restart required services.
- [ ] Run container backend suites and verify OCR readiness.
- [ ] Browser acceptance at `http://203.0.113.88:8000/rayher/approval/purchase`: amount derivation, employee draft, attachments, Finance classification, approve/reject/add-sign, PDF/image preview, close/reopen, timeline, console, and existing statistics/audit/navigation.
- [ ] Re-run full suites after deployment.
- [ ] Commit only reviewed source/schema/tests/build assets to the current feature branch. Do not push or merge.
- [ ] Report backup location, commit hash, test counts, live URL, browser acceptance evidence, and any remaining limitation.
