# Invoice Expense Context and Account Tree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture required expense descriptions and optional supplemental attachments on invoice OCR records, preserve them through reimbursement approval, and replace the flat expense list with the approved two-level account tree.

**Architecture:** Keep invoice supplemental Files permanently attached to `OA Invoice Record` and expose them in request serialization through `source_invoice`; preserve legacy request-line attachments. Store canonical level-one and level-two account fields while maintaining derived `expense_item` text for compatibility. The backend owns all validation and capability decisions.

**Tech Stack:** Python/Frappe, Vue 3, frappe-ui, pytest, Node `node:test`, Vite/Yarn, Docker-hosted Frappe bench.

## Global Constraints

- Work only on `feat/ocr-monthly-timesheet-integration`; do not push or merge `main`.
- Do not delete or rewrite existing invoices, request lines, request attachments, approvals, totals, or payment data.
- Use the exact normalized account tree in the approved design.
- `费用说明` is required for invoice confirmation and push; supplemental attachments remain optional.
- Keep project-name aggregation.
- Use private PDF/JPG/JPEG/PNG attachments, maximum 10 files per invoice and 10 MB per file.
- Begin each behavior with a failing test.
- Reject `%TSD-Header` from every source, staged blob, and deployed asset.

---

### Task 1: Canonical expense-account domain

**Files:**
- Create: `rayher_hr_payroll/expense_accounts.py`
- Create: `rayher_hr_payroll/tests/test_expense_accounts.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`

**Interfaces:**
- Produces: `EXPENSE_ACCOUNT_TREE: tuple[tuple[str, tuple[str, ...]], ...]`
- Produces: `account_options() -> list[dict[str, object]]`
- Produces: `normalize_account_pair(level_1, level_2) -> tuple[str, str, str]`
- `normalize_account_pair` returns `(level_1, level_2, expense_item_display)`

- [ ] **Step 1: Write the failing domain tests**

```python
def test_account_tree_preserves_workbook_hierarchy_and_normalizes_duplicates():
    rows = expense_accounts.account_options()
    assert rows[0] == {
        "level_1": "差旅费",
        "level_2": ["飞机票", "高铁\\火车票", "市内交通费", "乘车费", "住宿费", "出差补助", "过路/停车费", "Philippe", "Sabri"],
    }
    assert [row["level_1"] for row in rows].count("信息技术服务费") == 1
    assert "广告宣传费" in {row["level_1"] for row in rows}


def test_account_pair_requires_child_only_when_children_exist():
    assert expense_accounts.normalize_account_pair("办公费", "") == ("办公费", "", "办公费")
    assert expense_accounts.normalize_account_pair("差旅费", "住宿费") == ("差旅费", "住宿费", "差旅费 / 住宿费")
    with pytest.raises(ValueError):
        expense_accounts.normalize_account_pair("差旅费", "")
```

- [ ] **Step 2: Run `python -m pytest rayher_hr_payroll/tests/test_expense_accounts.py -q` and confirm import/test failure.**
- [ ] **Step 3: Implement the immutable normalized workbook tree and strict pair validator.**
- [ ] **Step 4: Expose `expense_account_tree` from `get_options` without removing legacy option keys.**
- [ ] **Step 5: Re-run the focused tests and confirm they pass.**
- [ ] **Step 6: Commit the domain contract.**

---

### Task 2: Invoice expense context and supplemental attachment storage

**Files:**
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_invoice_record/oa_invoice_record.json`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_invoice_supplemental_attachment/__init__.py`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_invoice_supplemental_attachment/oa_invoice_supplemental_attachment.py`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_invoice_supplemental_attachment/oa_invoice_supplemental_attachment.json`
- Create: `rayher_hr_payroll/invoice_supplemental_attachments.py`
- Modify: `rayher_hr_payroll/api/invoice_entry.py`
- Modify: `rayher_hr_payroll/invoice_ocr/service.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_ocr_service.py`
- Create: `rayher_hr_payroll/tests/test_invoice_supplemental_attachments.py`

**Interfaces:**
- Produces: invoice serialized properties `expense_description` and `supplemental_attachments`
- Produces: `service.update_expense_context(invoice_name, expense_description)`
- Produces APIs `update_expense_context`, `upload_supplemental_attachment`, `delete_supplemental_attachment`, `preview_supplemental_attachment`, `serve_supplemental_attachment_preview`

- [ ] **Step 1: Add failing service tests for blank description rejection, confirmed-unpushed edit, pushed edit rejection, confirmation gate, and serialized attachments.**

```python
def test_confirm_requires_expense_description(monkeypatch, pending_record):
    pending_record.expense_description = ""
    with pytest.raises(Exception, match="费用说明"):
        service.confirm_invoice(pending_record.name)


def test_confirmed_unpushed_context_is_editable_but_pushed_is_not(monkeypatch, confirmed_record):
    updated = service.update_expense_context(confirmed_record.name, "客户拜访交通费")
    assert updated["expense_description"] == "客户拜访交通费"
    confirmed_record.request = "OA-2026-00001"
    with pytest.raises(Exception, match="撤回"):
        service.update_expense_context(confirmed_record.name, "changed")
```

- [ ] **Step 2: Add failing attachment tests for private ownership, magic-byte validation, maximum 10, invoice linkage, single-use preview, delete, and post-push read-only writes.**
- [ ] **Step 3: Run the focused files and confirm failures.**
- [ ] **Step 4: Add the invoice field and standalone attachment DocType with invoice/file metadata and a unique File link.**
- [ ] **Step 5: Implement locked context update and attachment lifecycle by reusing the existing attachment validation and preview-token conventions.**
- [ ] **Step 6: Add bounded whitelisted API entry points and serialization.**
- [ ] **Step 7: Re-run focused tests and confirm they pass.**
- [ ] **Step 8: Commit invoice context storage.**

---

### Task 3: Push, withdrawal, request serialization, and compatibility

**Files:**
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_expense_line/oa_approval_expense_line.json`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Create: `rayher_hr_payroll/patches/v1_0/backfill_invoice_expense_context.py`
- Modify: `rayher_hr_payroll/patches.txt`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/tests/test_expense_handoff_migration.py`

**Interfaces:**
- Adds line fields `expense_account_level_1`, `expense_account_level_2`
- Request line serialization returns merged invoice supplemental attachments plus legacy `OA Expense Line Attachment` rows.

- [ ] **Step 1: Write failing integration tests proving push copies description, rejects missing description, exposes invoice attachments, and withdrawal leaves invoice context/Files intact.**

```python
def test_push_copies_invoice_expense_description(monkeypatch, confirmed_invoice):
    confirmed_invoice.expense_description = "上海客户拜访交通"
    result = oa_entry.push_invoices_to_request([confirmed_invoice.name], payment_info={...})
    request = fake_requests[result["name"]]
    assert request.expense_lines[0].expense_description == "上海客户拜访交通"
```

- [ ] **Step 2: Write failing compatibility tests proving legacy request-line attachments still serialize and the backfill writes only empty invoice descriptions from linked lines.**
- [ ] **Step 3: Run focused integration tests and confirm failures.**
- [ ] **Step 4: Copy invoice description during push, add account fields to line serialization/setters, and merge both attachment sources.**
- [ ] **Step 5: Implement the idempotent empty-only backfill patch and register it.**
- [ ] **Step 6: Re-run focused tests and confirm they pass.**
- [ ] **Step 7: Commit handoff and compatibility.**

---

### Task 4: Manual expense and Finance account validation

**Files:**
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/tests/test_expense_entry.py`

**Interfaces:**
- Manual source accepts `project_name`, `expense_account_level_1`, `expense_account_level_2`, `issue_date`, `total_amount`, and `expense_description`.
- Finance save accepts `line_key`, `expense_account_level_1`, and `expense_account_level_2`.

- [ ] **Step 1: Write failing tests that keep project name, remove no-invoice-reason validation, require the canonical account pair for manual expense, and allow Finance to replace it.**
- [ ] **Step 2: Add failing same-project tests requiring one consistent validated account pair across grouped lines.**
- [ ] **Step 3: Run focused tests and confirm failures.**
- [ ] **Step 4: Update `_manual_expense_source`, `_updated_invoice_source`, submission validation, classification readiness, and `save_finance_expense_items` to use `normalize_account_pair`.**
- [ ] **Step 5: Preserve legacy `expense_item` read compatibility but derive it on every new canonical save.**
- [ ] **Step 6: Re-run focused tests and confirm they pass.**
- [ ] **Step 7: Commit backend account workflow.**

---

### Task 5: Upload workbench expense context UI

**Files:**
- Modify: `frontend/src/lib/invoiceOcr.js`
- Modify: `frontend/src/lib/expenseWorkflow.js`
- Modify: `frontend/src/components/invoice/InvoiceUploadWorkbench.vue`
- Modify: `frontend/tests/invoice-ocr.test.js`
- Modify: `frontend/tests/invoice-upload-workbench-source.test.js`

**Interfaces:**
- Produces client methods for invoice context save and attachment upload/delete/preview.
- Selected invoice card owns required description and optional attachment controls.

- [ ] **Step 1: Write failing client tests for bounded description API payloads, private upload registration, delete, and preview token fetch.**
- [ ] **Step 2: Write failing source tests requiring `费用说明`, `补充附件`, attachment preview/delete, and blocking confirmation/push when description is blank.**
- [ ] **Step 3: Run the focused Node tests and confirm failures.**
- [ ] **Step 4: Add client functions and update upload workbench state so context is editable for pending, duplicate, and confirmed-unpushed records.**
- [ ] **Step 5: Add the full-width description and attachment section with existing validation/count conventions.**
- [ ] **Step 6: Save context before confirmation, keep it editable after confirmation until push, and include description in push selection eligibility.**
- [ ] **Step 7: Re-run focused tests and production frontend build.**
- [ ] **Step 8: Commit upload workbench changes.**

---

### Task 6: Manual-expense two-level account UI

**Files:**
- Modify: `frontend/src/lib/expenseWorkflow.js`
- Modify: `frontend/src/components/ExpenseWorkbench.vue`
- Modify: `frontend/tests/expense-workflow.test.js`
- Modify: `frontend/tests/expense-workbench-source.test.js`

**Interfaces:**
- Consumes `options.expense_account_tree`.
- Manual modal submits both account levels and preserves project-name grouping.

- [ ] **Step 1: Add failing tests for dependent children, leaf-account completion, retained project name, removed no-invoice reason, and canonical Finance payload.**
- [ ] **Step 2: Run focused tests and confirm failures.**
- [ ] **Step 3: Replace flat manual `费用项目` control with level-one and conditional level-two selects named `费用科目`.**
- [ ] **Step 4: Keep project name, date, amount, and required description; remove the no-invoice-reason control and frontend validation.**
- [ ] **Step 5: Replace Finance classification input with the same dependent pair and submit both fields.**
- [ ] **Step 6: Re-run focused tests and frontend build.**
- [ ] **Step 7: Commit the account UI.**

---

### Task 7: Approval one-to-one review redesign

**Files:**
- Modify: `frontend/src/components/ExpenseWorkbench.vue`
- Modify: `frontend/tests/expense-workbench-source.test.js`

**Interfaces:**
- Consumes per-source `expense_description`, `supplemental_attachments`, and legacy `attachments`.
- Produces a `min(96vw, 1720px)` responsive approval dialog without the wide invoice table.

- [ ] **Step 1: Add failing source tests requiring the wider dialog, per-invoice review unit, `查看发票`, `费用说明`, `补充附件`, and no `min-w-[1500px]`.**
- [ ] **Step 2: Run the focused source test and confirm failure.**
- [ ] **Step 3: Render each project group as a responsive section and every source invoice as one visual row/card containing fields, preview, description, and attachment chips.**
- [ ] **Step 4: Make pushed invoice context read-only, keep manual draft editing where applicable, and preserve the sticky action footer/capability buttons.**
- [ ] **Step 5: Re-run source tests and frontend build.**
- [ ] **Step 6: Commit approval detail redesign.**

---

### Task 8: Deployment, migration, and acceptance

**Files:**
- No planned source changes; any discovered defect returns to its focused failing test.

- [ ] **Step 1: Run `git diff --check`, all backend tests, all frontend tests, and `yarn --cwd frontend build`; confirm zero failures.**
- [ ] **Step 2: Verify every changed/staged file and generated build asset is plaintext and does not begin with `%TSD-Header`.**
- [ ] **Step 3: Back up the site database and private files before migration.**
- [ ] **Step 4: Copy exact reviewed source/build bytes to `rayher-bench`, verify container headers, run `bench --site rayher.localhost migrate`, and clear caches.**
- [ ] **Step 5: Browser-test one new invoice through upload, OCR edit, description, attachment, confirm, push, Finance classification, approval preview, and withdrawal.**
- [ ] **Step 6: Verify a leaf account needs no second level; 差旅费 requires a valid second level; invalid pairs fail through direct API calls.**
- [ ] **Step 7: Verify existing pushed requests and legacy request attachments remain readable and no business records changed unexpectedly.**
- [ ] **Step 8: Verify the approval dialog at 1366x768 and a narrower viewport has no page-level horizontal overflow, clipped action, or console error.**
- [ ] **Step 9: Re-run focused backend/frontend regressions after deployment.**
- [ ] **Step 10: Stage only reviewed files, inspect staged blobs for plaintext/NUL anomalies, and commit to the current branch only.**
