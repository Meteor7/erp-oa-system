# Invoice Upload and Reimbursement Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver two first-class workspaces—上传发票 and 费用报销流—with one seven-field reimbursement line per confirmed invoice, retained no-invoice entry, and controlled reversible actions.

**Architecture:** Keep legacy consumption and expense fields for backward compatibility, while introducing record-driven invoice workbench APIs and seven-field expense-line extensions. A focused Vue upload component manages OCR review and pushdown; the existing reimbursement kanban consumes pushed drafts and displays the same seven fields.

**Tech Stack:** Frappe/Python, MariaDB DocTypes, Vue 3, frappe-ui, Vite, Node test runner, pytest, Docker Compose, local PaddleOCR.

## Global Constraints

- No external OCR or invoice-authenticity API.
- Exact expense fields: `invoice_category`, `project_name`, `issue_date`, `invoice_number`, `amount_before_tax`, `tax_amount`, `total_amount`.
- One selected invoice produces one expense line; multiple selected invoices produce one draft request.
- Existing request and legacy consumption data must remain readable.
- Private files and POST-token preview remain unchanged.
- Paid reversal requires finance.
- Every state reversal writes an audit event.
- Project files must be written through a TipRay-safe trusted writer and verified not to start with `%TSD-Header`.

---

### Task 1: Seven-field schema and compatibility mapping

**Files:**
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_expense_line/oa_approval_expense_line.json`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.json`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_invoice_record/oa_invoice_record.json`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Test: `rayher_hr_payroll/tests/test_doctype_json.py`
- Test: `rayher_hr_payroll/tests/test_invoice_request_integration.py`

**Interfaces:**
- Produces: `_normalize_expense_lines(expense_lines, fallback_amount=0, fallback_subject=None) -> tuple[list[dict], float]`
- Produces: `_serialize_expense_line(row) -> dict` containing all seven fields and legacy fallbacks.
- Produces: read-only `operation_log` fields on request and invoice records.

- [ ] **Step 1: Write failing schema tests**

Assert that `source_invoice` plus all seven OCR fields exist on `OA Approval Expense Line`, `发票下推` exists in request source options, and both request/record have read-only Long Text `operation_log`.

- [ ] **Step 2: Run schema tests and verify RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_doctype_json.py -q`  
Expected: FAIL because the fields and source option do not exist.

- [ ] **Step 3: Write failing normalization tests**

Use a row with:
```python
{
    "source_invoice": "OIR-1",
    "invoice_category": "电子发票（普通发票）",
    "project_name": "文具印章",
    "issue_date": "2026-07-14",
    "invoice_number": "26322000005753891281",
    "amount_before_tax": "35.62",
    "tax_amount": "0.36",
    "total_amount": "35.98",
}
```
Assert exact seven-field retention, `amount == 35.98`, compatibility category/date/description mapping, and a stable line key. Assert legacy rows serialize into the new display keys without data loss.

- [ ] **Step 4: Run normalization tests and verify RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_invoice_request_integration.py -q`  
Expected: FAIL because normalization and serialization omit seven-field values.

- [ ] **Step 5: Add schema and minimal compatibility implementation**

Add nullable fields, preserve existing fields and order, map `total_amount` to compatibility `amount`, and use explicit null checks so an OCR value of `0.00` is not treated as blank.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run both commands from Steps 2 and 4.  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add rayher_hr_payroll/rayher_hr_payroll/doctype rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests
git commit -m "feat: add seven-field reimbursement details"
```

### Task 2: Record-driven invoice workbench and reversible backend

**Files:**
- Modify: `rayher_hr_payroll/api/invoice_entry.py`
- Modify: `rayher_hr_payroll/invoice_ocr/service.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Create: `rayher_hr_payroll/tests/test_invoice_workbench_flow.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`

**Interfaces:**
- Produces: `list_workbench_invoices(view="mine", status=None, limit=200) -> list[dict]`
- Produces: `unconfirm_invoice(invoice_name, note=None) -> dict`
- Produces: `push_invoices_to_request(invoice_names, payment_info=None) -> dict`
- Produces: `withdraw_invoice_push(invoice_names, note=None) -> dict`
- Produces: `withdraw_request(name, note=None) -> dict`
- Produces: `withdraw_payment(name, note=None) -> dict`

- [ ] **Step 1: Write failing workbench listing tests**

Verify an ordinary user sees owned records only, privileged roles can use `view="all"`, status and limit are bounded, and serialized records expose request/push state without raw OCR payload.

- [ ] **Step 2: Run listing tests and verify RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_invoice_workbench_flow.py -q`  
Expected: FAIL because the workbench API is absent.

- [ ] **Step 3: Implement scoped listing**

Use owner filters for ordinary users, privileged scope for authorized users, `limit <= 300`, `_serialize_record`, and existing row-level permission checks.

- [ ] **Step 4: Write failing pushdown tests**

Assert two confirmed records create one draft request with exactly two lines; each line equals its source invoice’s seven values; each record links to its own line key; cross-batch selection works; unconfirmed, duplicate, already-linked, unauthorized, and concurrent second push are rejected; a failing second link rolls the transaction back.

- [ ] **Step 5: Run pushdown tests and verify RED**

Run the test module from Step 2.  
Expected: FAIL because `push_invoices_to_request` is absent.

- [ ] **Step 6: Implement transactional pushdown**

Parse and bound a unique invoice-name list, lock record names in sorted order, re-read current rows, validate `已确认` and empty request, call `_build_request_doc(..., submit=False, source_type="发票下推")`, append one line per invoice, link records directly without batch-level single-request coupling, recompute the request summary, append audit events, and return `_summarize_doc`.

- [ ] **Step 7: Write failing reversal tests**

Verify unconfirm only works before push; unpush withdraws an active non-paid request to draft and removes only selected invoice lines; ordinary users cannot reverse paid requests; finance can withdraw payment to completed; request withdrawal preserves the row and records prior workflow state in `operation_log`.

- [ ] **Step 8: Run reversal tests and verify RED**

Run the test module from Step 2.  
Expected: FAIL because reversal endpoints are absent.

- [ ] **Step 9: Implement audit and reversal transitions**

Append bounded JSON audit entries:
```python
{
    "action": action,
    "actor": frappe.session.user,
    "acted_on": str(now_datetime()),
    "from_status": from_status,
    "to_status": to_status,
    "note": note,
}
```
Reset approval steps only after preserving their state in the audit entry. Never delete invoice files or requests.

- [ ] **Step 10: Run all backend tests and verify GREEN**

Run: `python -m pytest rayher_hr_payroll/tests -q`  
Expected: PASS with no warnings introduced.

- [ ] **Step 11: Commit**

```bash
git add rayher_hr_payroll/api rayher_hr_payroll/invoice_ocr rayher_hr_payroll/tests
git commit -m "feat: add reversible invoice pushdown workflow"
```

### Task 3: Invoice upload workspace

**Files:**
- Modify: `frontend/src/lib/invoiceOcr.js`
- Create: `frontend/src/components/invoice/InvoiceUploadWorkbench.vue`
- Modify: `frontend/tests/invoice-ocr.test.js`
- Modify: `frontend/tests/invoice-ocr-source.test.js`
- Create: `frontend/tests/invoice-upload-workbench-source.test.js`

**Interfaces:**
- Consumes: backend list, unconfirm, push, and unpush endpoints from Task 2.
- Produces: component event `request-created(name: string)`.
- Produces: API wrappers `listWorkbenchInvoices`, `unconfirmInvoice`, `pushInvoices`, and `withdrawInvoicePush`.

- [ ] **Step 1: Write failing API and component source tests**

Assert wrappers use POST JSON via `invoiceApi`; component has PDF/JPG/JPEG/PNG multiple input, seven labels, list/detail panes, confirm/unconfirm, selection, push, unpush, private preview drawer, polling cleanup, and no direct download link.

- [ ] **Step 2: Run frontend tests and verify RED**

Run: `node --test frontend/tests/*.test.js`  
Expected: FAIL because wrappers and component do not exist.

- [ ] **Step 3: Add API wrappers**

Implement thin calls using the existing CSRF/error transport and preserve the 20-file/10MB/concurrency limits.

- [ ] **Step 4: Implement upload workbench**

Create batch on first file selection, upload concurrently, poll active recognition statuses, merge all user-visible records from the list API, retain current selection after reload, show a left table and right seven-field detail panel, require confirmation before selection, and open the existing tokenized preview drawer.

- [ ] **Step 5: Implement push and reversal interactions**

Collect selected confirmed invoice names; open payment-info push dialog; create one draft; show returned request number; refresh rows. Make unconfirm and unpush explicit confirmation actions with clear state-dependent errors.

- [ ] **Step 6: Run frontend tests and verify GREEN**

Run the command from Step 2.  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/invoiceOcr.js frontend/src/components/invoice frontend/tests
git commit -m "feat: add invoice upload workspace"
```

### Task 4: Reimbursement flow UI and seven-field forms

**Files:**
- Modify: `frontend/src/components/ExpenseWorkbench.vue`
- Modify: `frontend/tests/oa-source.test.js`
- Modify: `frontend/tests/invoice-ocr-source.test.js`

**Interfaces:**
- Consumes: `InvoiceUploadWorkbench` and request reversal endpoints.
- Produces: navigation keys `invoices` and `board` labeled 上传发票 and 费用报销流.
- Produces: manual line shape with the exact seven fields plus stable `line_key`.

- [ ] **Step 1: Write failing navigation and seven-column tests**

Assert main/sub labels and 消费明细 UI are absent; upload is first/default; request modal has no OCR panel; create/detail tables contain the seven exact labels; no-invoice reason remains; each request detail line has 查看发票; withdrawal buttons are state gated.

- [ ] **Step 2: Run frontend tests and verify RED**

Run: `node --test frontend/tests/*.test.js`  
Expected: FAIL against the legacy navigation and columns.

- [ ] **Step 3: Replace navigation and remove legacy consumption UI**

Mount `InvoiceUploadWorkbench` for `activeView === "invoices"`; keep the board for `board`; leave flow/stats/records features intact; remove consumption resources, forms, push modal, and embedded request-form OCR upload.

- [ ] **Step 4: Replace create and detail tables**

Use the same seven-column order in both places. Manual lines are editable; pushed invoice lines are read-only and derived from confirmed OCR values. Sum `total_amount`, and serialize all seven values on create.

- [ ] **Step 5: Add withdrawal controls**

Expose request withdrawal for applicant-visible non-draft/non-paid states and finance payment withdrawal for paid states. After success reload the kanban and detail invoices without closing context.

- [ ] **Step 6: Run tests and production build**

Run:
```bash
node --test frontend/tests/*.test.js
yarn --cwd frontend build
```
Expected: all tests PASS and Vite build exits 0.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ExpenseWorkbench.vue frontend/tests
git commit -m "feat: split invoice upload and reimbursement flow"
```

### Task 5: Migration, deployment, and live acceptance

**Files:**
- Modify only if required: `deploy/docker-compose.invoice-ocr.yml`
- Verify: deployed Frappe site and OCR sidecar.

**Interfaces:**
- Consumes: tested commits from Tasks 1–4.
- Produces: live, directly usable upload/OCR/push/reimbursement/withdraw flow.

- [ ] **Step 1: Verify project files are plaintext**

Check changed files for `%TSD-Header`, NUL bytes, valid UTF-8/JSON, and compile Python modules.  
Expected: no encrypted header, no NUL, JSON parse succeeds, Python compile succeeds.

- [ ] **Step 2: Run full isolated verification**

Stage plaintext source into a disposable Docker volume, run backend pytest, frontend Node tests, Vite build, and Frappe migration against an isolated site/backup.  
Expected: all pass; existing two request rows and their expense lines remain.

- [ ] **Step 3: Take a predeployment backup**

Create a timestamped database/site backup and record the volume/path before migration.

- [ ] **Step 4: Deploy and migrate**

Copy tested plaintext files into the live app volume, run `bench --site <site> migrate`, build assets, clear cache, and restart only affected services.

- [ ] **Step 5: Perform live browser acceptance**

Verify:
1. 上传发票 is the first navigation item.
2. Multiple sample invoices upload and OCR.
3. Seven fields can be corrected, confirmed, and immediately selected.
4. Push creates one draft with one line per invoice.
5. 费用报销流 displays seven values and private 查看发票.
6. No-invoice manual draft still submits with a reason.
7. Confirm withdrawal, request withdrawal, push withdrawal, and finance payment withdrawal follow permissions.
8. Existing two requests still display.

- [ ] **Step 6: Verify clean live data**

Remove only acceptance records/files created for testing through application APIs or restore the isolated test state; do not delete business data. Confirm service health and no OCR errors.

- [ ] **Step 7: Final verification commit**

```bash
git status --short
git log --oneline -5
```
Expected: clean feature branch; no merge to main.
