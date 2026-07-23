# Expense Approval Accounts, Executive Access, and Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link real Finance and executive accounts to OA approvals, grant non-system business-wide authority, migrate only unresolved approval nodes, and deliver a responsive reimbursement approval workbench.

**Architecture:** Keep Frappe User IDs as the authorization identity and Chinese names as display labels. Add one custom business-executive role, an explicit idempotent account bootstrap service, and an idempotent active-step migration. Keep backend capabilities authoritative and render the existing Vue dialog as responsive grouped sections with a sticky action footer.

**Tech Stack:** Python/Frappe, Vue 3, frappe-ui, pytest, Node `node:test`, Vite/Yarn, Docker-hosted Frappe bench.

## Global Constraints

- Work only on `feat/ocr-monthly-timesheet-integration`; do not push or merge `main`.
- Do not create a Wang Bo Employee record without verified HR data.
- Do not grant Li Qinggele or Wang Bo `System Manager`.
- Do not rewrite completed approval steps, approval history, invoices, attachments, amounts, or payment data.
- Use trusted cmd/certutil or Docker writers and reject `%TSD-Header` from every staged blob.
- Begin every behavior with a failing test and deploy backend, migration, and exact frontend assets together.
- No external OCR or document API.

---

### Task 1: Business-executive role contract

**Files:**
- Modify: `rayher_hr_payroll/tests/test_access_control.py`
- Modify: `rayher_hr_payroll/access_control.py`

**Interfaces:**
- Produces: `BUSINESS_EXECUTIVE_ROLE = "Rayher Business Executive"`
- Produces: an idempotently created desk role and a business role bundle that excludes `System Manager`

- [ ] **Step 1: Write the failing role test**

```python
def test_business_executive_role_is_business_wide_but_not_system_admin():
    assert ac.BUSINESS_EXECUTIVE_ROLE in {r["role_name"] for r in ac.CUSTOM_ROLES}
    profile = next(p for p in ac.ROLE_PROFILES if p["role_profile"] == "Rayher Business Executive")
    assert ac.BUSINESS_EXECUTIVE_ROLE in profile["roles"]
    assert {"HR Manager", "Accounts User", "Department Manager", "All Project Access"} <= set(profile["roles"])
    assert "System Manager" not in profile["roles"]
```

- [ ] **Step 2: Run `python -m pytest rayher_hr_payroll/tests/test_access_control.py -q` and confirm the new test fails because the role constant/profile do not exist.**
- [ ] **Step 3: Add the role and exact profile bundle in `access_control.py`; preserve the existing total-control profile.**
- [ ] **Step 4: Re-run the focused test and confirm it passes.**
- [ ] **Step 5: Commit the independently testable role contract.**

---

### Task 2: Idempotent Finance and executive account bootstrap

**Files:**
- Create: `rayher_hr_payroll/maintenance/business_account_bootstrap.py`
- Create: `rayher_hr_payroll/tests/test_business_account_bootstrap.py`

**Interfaces:**
- Consumes: `BUSINESS_EXECUTIVE_ROLE`
- Produces: `ACCOUNT_SPECS`, `plan_business_accounts() -> dict`, `ensure_business_accounts(dry_run=True) -> dict`
- Returns temporary passwords only for users created during `dry_run=False`

- [ ] **Step 1: Write failing pure tests for the account specifications.**

```python
def test_account_specs_cover_finance_and_executives_without_system_manager():
    specs = {row["user_id"]: row for row in bootstrap.ACCOUNT_SPECS}
    assert specs["person067@legacy.example.invalid"]["employee"] == "HR-EMP-90008"
    assert specs["person065@legacy.example.invalid"]["employee"] == "HR-EMP-90016"
    assert specs["person072@legacy.example.invalid"]["employee"] == "HR-EMP-90007"
    assert specs["person046@business.example.invalid"]["employee"] == "HR-EMP-90004"
    assert specs["person058@legacy.example.invalid"]["employee"] is None
    assert all("System Manager" not in row["roles"] for row in specs.values())
```

- [ ] **Step 2: Add failing adapter tests proving dry-run makes no writes, existing users/passwords remain untouched, new users are enabled System Users, exact Employees are linked, role additions are idempotent, and collisions abort before any commit.**
- [ ] **Step 3: Run `python -m pytest rayher_hr_payroll/tests/test_business_account_bootstrap.py -q` and confirm failures.**
- [ ] **Step 4: Implement `ACCOUNT_SPECS` with these exact IDs: `admin@legacy-business.example.invalid`, `person067@legacy.example.invalid`, `person065@legacy.example.invalid`, `person072@legacy.example.invalid`, `person046@business.example.invalid`, and `person058@legacy.example.invalid`.**
- [ ] **Step 5: Implement preflight validation, User insert/update, `Employee.user_id` linking, additive role assignment, random temporary password generation using `secrets`, transaction rollback, and a result that never returns existing passwords.**
- [ ] **Step 6: Re-run the focused tests and confirm they pass.**
- [ ] **Step 7: Commit the account bootstrap module and tests.**

---

### Task 3: Stable User IDs in all future approval routes

**Files:**
- Modify: `rayher_hr_payroll/tests/test_oa_approval_routes.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/oa_approval.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`

**Interfaces:**
- Produces route constants `FINANCE_AUDITOR_USER`, `VICE_MANAGER_USER`, `GENERAL_MANAGER_USER`
- Produces `_resolve_route_approver(value: str) -> str`

- [ ] **Step 1: Replace legacy route expectations with failing tests for Finance -> supervisor -> optional specialist -> executive -> Finance handling using User IDs and Chinese display labels.**
- [ ] **Step 2: Add failing tests for leave supervisor -> Li Qinggele -> Wang Bo, sales all-sign Li Qinggele + Wang Bo, non-sales Wang Bo, and Employee-name supervisor resolution to linked User ID.**
- [ ] **Step 3: Run the two focused test files and confirm failures against legacy Ren Feifan/Qing Bo names.**
- [ ] **Step 4: Refactor route constants and builders so fixed approvers are stable User IDs while labels remain names.**
- [ ] **Step 5: Resolve dynamic supervisors by enabled User name/full name and then active Employee `user_id`; keep the original value only when unresolved.**
- [ ] **Step 6: Re-run focused tests and confirm all pass.**
- [ ] **Step 7: Commit future-route identity changes.**

---

### Task 4: Active-step migration and audited executive override

**Files:**
- Create: `rayher_hr_payroll/patches/v1_0/migrate_active_oa_approvers.py`
- Modify: `rayher_hr_payroll/patches.txt`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`

**Interfaces:**
- Produces: `build_step_migration(label, approvers, status) -> dict | None`
- Produces: `execute(dry_run=False) -> dict`
- Extends request summary with `is_override_actor` and `action_scope`

- [ ] **Step 1: Add failing migration tests for Ye Liwei, Ren Feifan, Qing Bo, Wang Bo, and legacy joint Qing Bo/Wang Bo mappings. Assert completed steps return no change and repeated execution is a no-op.**
- [ ] **Step 2: Add failing capability/action tests for ordinary assigned approver, unrelated user, `Administrator`, `admin@legacy-business.example.invalid` with `Rayher Business Executive`, Finance classification at Finance audit, all-mode override completion, stale/completed denial, and real `action_by` audit identity.**
- [ ] **Step 3: Run focused tests and confirm the new cases fail.**
- [ ] **Step 4: Implement the unresolved-only migration patch with dry-run counts, unresolved diagnostics, and no historical-field mutation.**
- [ ] **Step 5: Implement `_is_oa_override_user`, capability metadata, and override-aware checks in approve, targeted reject, add-sign, and Finance classification. Preserve all existing transaction locks and validation.**
- [ ] **Step 6: Re-run focused backend tests and confirm all pass.**
- [ ] **Step 7: Commit migration and override behavior.**

---

### Task 5: Responsive reimbursement approval workbench

**Files:**
- Modify: `frontend/tests/expense-workbench-source.test.js`
- Modify: `frontend/tests/expense-workflow.test.js`
- Modify: `frontend/src/components/ExpenseWorkbench.vue`

**Interfaces:**
- Consumes backend capability flags and grouped expense data without deriving permissions
- Produces a sticky header/footer, summary strip, grouped expense sections, Finance classification panel, workflow timeline, and explicit action controls

- [ ] **Step 1: Add failing source/behavior tests that reject `min-w-[1500px]`, require a sticky detail header and footer, require grouped responsive fields, and require visible labels for Save classification, Add sign, Targeted reject, and Approve.**
- [ ] **Step 2: Run `node --test frontend/tests/expense-workbench-source.test.js frontend/tests/expense-workflow.test.js` and confirm failures.**
- [ ] **Step 3: Replace only the reimbursement detail dialog markup with the approved workbench structure. Reuse existing state, API methods, buttons, preview drawers, attachment controls, and dialogs.**
- [ ] **Step 4: Add explicit status/current-node/total summary, highlighted editable Finance category, read-only fallback, compact timeline states, and backend-driven action scope notice.**
- [ ] **Step 5: Ensure 1366x768 has no document-level horizontal overflow and narrow widths stack fields without hiding primary actions.**
- [ ] **Step 6: Re-run focused frontend tests and production build.**
- [ ] **Step 7: Commit the UI workbench.**

---

### Task 6: Pre-deployment data safety and live provisioning

**Files:**
- No source changes unless verification exposes a defect.

**Interfaces:**
- Consumes `plan_business_accounts`, `ensure_business_accounts`, and the active-step migration patch
- Produces a database/private-files backup, dry-run report, created/linked users, temporary credentials, and migrated unresolved steps

- [ ] **Step 1: Plaintext-check all changed files, staged blobs, and generated build assets for `%TSD-Header`.**
- [ ] **Step 2: Run full backend tests, full frontend tests, `git diff --check`, and `yarn --cwd frontend build`.**
- [ ] **Step 3: Back up the site database and private files before any live User or approval-step mutation.**
- [ ] **Step 4: Run account bootstrap and active-step migration in dry-run mode; inspect exact accounts, Employee links, role additions, changed step counts, and unresolved identities. Abort on any unexpected target.**
- [ ] **Step 5: Deploy source and exact build, run `bench --site rayher.localhost migrate`, then run explicit account provisioning once. Capture temporary passwords outside Git.**
- [ ] **Step 6: Verify role memberships, Employee links, no System Manager on Li Qinggele/Wang Bo, and active-step User IDs directly from Frappe.**

---

### Task 7: Browser acceptance and final branch commit

**Files:**
- No source changes unless acceptance finds a reproducible defect, in which case return to the corresponding test-first task.

- [ ] **Step 1: Use the in-app Browser at `http://203.0.113.88:8000/rayher/approval/purchase` as `admin@legacy-business.example.invalid`; verify all requests are visible and the current approval exposes classification, targeted reject, add-sign, and approve.**
- [ ] **Step 2: Verify a Finance account sees classification/actions only when assigned to the active Finance node.**
- [ ] **Step 3: Verify Li Qinggele and Wang Bo see all business requests and can perform audited approval actions without System Manager UI/permissions.**
- [ ] **Step 4: Exercise Finance classification save, approve, targeted reject, repeated add-sign, invoice/attachment preview, and close/reopen. Use disposable test requests only and restore/withdraw them afterward.**
- [ ] **Step 5: Check 1366x768 and a narrow viewport for horizontal overflow, clipped controls, sticky footer behavior, readable amounts, and console errors. Capture screenshots.**
- [ ] **Step 6: Run full backend/frontend suites again after deployment and inspect deployed asset hashes.**
- [ ] **Step 7: Stage only reviewed source/schema/tests/build files; inspect every staged blob for plaintext and unexpected NULs; commit to the current branch only.**
- [ ] **Step 8: Report commit hash, backup location, test counts, created accounts/role links, live URL, browser evidence, and temporary-password handoff separately from Git.**