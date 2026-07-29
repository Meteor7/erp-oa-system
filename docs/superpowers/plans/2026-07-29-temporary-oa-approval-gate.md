# Temporary OA Approval Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two reversible site switches that make leave approval and expense reimbursement available only to the exact `Administrator` account while leaving other modules and stored OA data unchanged.

**Architecture:** A new backend policy module owns both switches. The page boot payload exposes server-derived flags to the SPA, and OA/invoice entry points plus DocType permission hooks enforce the same decision server-side. Disabling a switch automatically restores the existing role and row-level rules.

**Tech Stack:** Frappe/Python, Vue 3, Node test runner, Pytest, Vite, Docker Bench site `rayher.localhost`.

## Global Constraints

- Independent keys: `leave_approval_admin_only` and `expense_reimbursement_admin_only`.
- A truthy key allows only exact user `Administrator`; `System Manager` alone is insufficient.
- A false or missing key defers to existing permissions.
- Do not mutate or delete any existing leave, reimbursement, invoice, step, audit, or attachment data.
- Do not change R&D timesheet, ledger, personnel, accommodation, project, or payroll permissions.
- Frontend hiding is not a security boundary; routes, APIs, OA requests, and invoice records must agree.
- Use TDD and finish with host, remote, and Docker on one clean exact commit.
- QIHENG DEMO branding is a separate next feature and is not part of this security change.

## File Map

- Create `rayher_hr_payroll/oa_feature_gate.py` for switch and permission decisions.
- Create `rayher_hr_payroll/tests/test_oa_feature_gate.py` for policy tests.
- Modify `rayher_hr_payroll/www/rayher.py` to expose boot flags.
- Modify `frontend/src/lib/access.js` and `frontend/tests/access.test.js` for menus/routes.
- Modify `rayher_hr_payroll/api/oa_entry.py` and its integration tests for OA API enforcement.
- Modify `rayher_hr_payroll/api/invoice_entry.py`, `invoice_ocr/permissions.py`, and invoice tests.
- Modify `rayher_hr_payroll/hooks.py` to protect direct OA Request access.
- Regenerate `rayher_hr_payroll/public/frontend/` and `rayher_hr_payroll/www/rayher.html`.
- Set both keys in Docker site config using Bench; do not commit site secrets.

---

### Task 1: Canonical OA feature policy

**Files:**
- Create: `rayher_hr_payroll/oa_feature_gate.py`
- Create: `rayher_hr_payroll/tests/test_oa_feature_gate.py`

**Interfaces:**
- Consumes: `REQUEST_LEAVE`, `REQUEST_EXPENSE_PAYMENT`, `frappe.conf`, and `frappe.session.user`.
- Produces: `is_admin_only(request_type)`, `can_access_request_type(request_type, user=None)`, `require_request_type_access(request_type, user=None)`, `visible_request_types(request_types, user=None)`, `boot_access_flags(user=None)`, `oa_request_query(user=None)`, and `oa_request_has_permission(doc, ptype=None, user=None)`.

- [ ] **Step 1: Write failing policy tests**

```python
def test_truthy_switch_allows_only_exact_administrator(monkeypatch):
    configure(monkeypatch, leave=1, expense=1)
    assert gate.can_access_request_type(gate.REQUEST_LEAVE, "Administrator") is True
    assert gate.can_access_request_type(gate.REQUEST_EXPENSE_PAYMENT, "Administrator") is True
    assert gate.can_access_request_type(gate.REQUEST_LEAVE, "manager@example.com") is False
    assert gate.can_access_request_type(gate.REQUEST_EXPENSE_PAYMENT, "finance@example.com") is False


def test_switches_are_independent(monkeypatch):
    configure(monkeypatch, leave=1, expense=0)
    assert gate.visible_request_types(
        [gate.REQUEST_LEAVE, gate.REQUEST_EXPENSE_PAYMENT], "employee@example.com"
    ) == [gate.REQUEST_EXPENSE_PAYMENT]
```

Also assert false/missing keys allow the existing layer, unknown request types raise `ValueError`, denial raises `frappe.PermissionError`, boot flags use `leave_approval` and `expense_reimbursement`, a fully denied query returns `1=0`, and an allowed document returns `None` to defer to Frappe.

- [ ] **Step 2: Run tests and verify RED**

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_oa_feature_gate.py"
```

Expected: import failure because the policy module does not exist.

- [ ] **Step 3: Implement the policy**

```python
ADMIN_USER = "Administrator"
FEATURE_CONFIG_BY_REQUEST_TYPE = {
    REQUEST_LEAVE: "leave_approval_admin_only",
    REQUEST_EXPENSE_PAYMENT: "expense_reimbursement_admin_only",
}
BOOT_FLAG_BY_REQUEST_TYPE = {
    REQUEST_LEAVE: "leave_approval",
    REQUEST_EXPENSE_PAYMENT: "expense_reimbursement",
}


def is_admin_only(request_type):
    return bool(cint(frappe.conf.get(_feature_key(request_type), 0)))


def can_access_request_type(request_type, user=None):
    user = user or frappe.session.user
    return user == ADMIN_USER or not is_admin_only(request_type)


def require_request_type_access(request_type, user=None):
    if not can_access_request_type(request_type, user):
        frappe.throw("当前审批功能暂未开放。", frappe.PermissionError)
```

Implement `visible_request_types` and `boot_access_flags` from the two maps. Implement `oa_request_query` to return `1=0` when none are visible, `""` when both are visible, or an escaped `request_type in (...)` condition when one is visible. Implement `oa_request_has_permission` to return `False` for a denied known type and `None` otherwise.

- [ ] **Step 4: Run tests and verify GREEN**

Run the same Pytest command. Expected: all policy tests pass.

- [ ] **Step 5: Commit**

```bash
git add rayher_hr_payroll/oa_feature_gate.py rayher_hr_payroll/tests/test_oa_feature_gate.py
git commit -m "feat(oa): add reversible approval feature gates"
```

---

### Task 2: Boot flags, menus, and route 403

**Files:**
- Modify: `rayher_hr_payroll/www/rayher.py`
- Modify: `frontend/src/lib/access.js`
- Modify: `frontend/tests/access.test.js`
- Modify: `frontend/tests/app-shell-source.test.js`

**Interfaces:**
- Consumes: `boot_access_flags()` and `window.oa_access`.
- Produces: `canSee()` decisions that combine the current role matrix with the server flag.

- [ ] **Step 1: Write failing frontend tests**

```javascript
function asRoles(roles, oaAccess = { leave_approval: true, expense_reimbursement: true }) {
  globalThis.window = { roles, oa_access: oaAccess };
}

test('temporary OA flags hide both pages from non-admin roles', () => {
  for (const roles of [['Employee'], ['Employee', 'Department Manager'], ['Accounts User'], ['HR Manager'], ['System Manager']]) {
    asRoles(roles, { leave_approval: false, expense_reimbursement: false });
    assert.equal(canSee('/approval/leave'), false);
    assert.equal(canSee('/approval/purchase'), false);
  }
});

test('OA flags restore modules independently', () => {
  asRoles(['Employee'], { leave_approval: true, expense_reimbursement: false });
  assert.equal(canSee('/approval/leave'), true);
  assert.equal(canSee('/approval/purchase'), false);
});
```

Assert `App.vue` continues to filter every menu item through `canSee(n.to)` and the direct route through `allowed`.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
$node='C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
& $node --test frontend/tests/access.test.js frontend/tests/app-shell-source.test.js
```

Expected: flag cases fail because `canSee` checks roles only.

- [ ] **Step 3: Add boot and access checks**

In `rayher.py` add:

```python
from rayher_hr_payroll.oa_feature_gate import boot_access_flags
# inside context.boot
"oa_access": boot_access_flags(frappe.session.user),
```

In `access.js` add:

```javascript
const OA_FLAG_BY_PATH = {
  '/approval/leave': 'leave_approval',
  '/approval/purchase': 'expense_reimbursement',
};

function hasEnabledFeature(path) {
  const flag = OA_FLAG_BY_PATH[path];
  if (!flag) return true;
  const access = (typeof window !== 'undefined' && window.oa_access) || {};
  return access[flag] !== false;
}

export function canSee(path) {
  if (!hasEnabledFeature(path)) return false;
  const need = PAGE_ROLES[path] || MANAGE;
  return myRoles().some((role) => need.includes(role));
}
```

The compatibility default preserves old cached HTML; backend gates remain authoritative.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same Node command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rayher_hr_payroll/www/rayher.py frontend/src/lib/access.js frontend/tests/access.test.js frontend/tests/app-shell-source.test.js
git commit -m "feat(frontend): gate OA routes from boot flags"
```

---

### Task 3: Enforce both gates at OA API boundaries

**Files:**
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `rayher_hr_payroll/hooks.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/tests/test_oa_feature_gate.py`

**Interfaces:**
- Consumes: policy functions from Task 1.
- Produces: denial before reads or mutations for explicit types, loaded documents, expense-only endpoints, and mixed lists.

- [ ] **Step 1: Write failing OA boundary tests**

Add tests proving:

```python
def test_preview_route_requires_explicit_type_gate(monkeypatch):
    seen = []
    monkeypatch.setattr(oa_entry, "require_request_type_access", seen.append)
    monkeypatch.setattr(oa_entry, "_route_context", lambda **kw: context())
    monkeypatch.setattr(oa_entry, "build_route", lambda **kw: [])
    oa_entry.preview_route(oa_entry.REQUEST_LEAVE)
    assert seen == [oa_entry.REQUEST_LEAVE]
```

Also test:

- `create_request` checks its explicit type before insert.
- `list_requests(request_type=...)` checks that type before query.
- `list_requests(request_type=None)` filters by `visible_request_types(REQUEST_TYPES)` and returns `[]` without querying when empty.
- `submit_request`, `action_request`, `withdraw_request`, and `add_sign_request` check the loaded document type before mutation.
- false/missing switches still reach existing role and row rules.
- each expense-only API has an immediate reimbursement gate.

Expense-only list:

```text
save_draft_expense_sources, save_finance_expense_items,
update_draft_invoice_details, get_expense_statistics,
list_expense_approval_records, list_consumption_details,
save_consumption_detail, add_invoice, push_consumption_to_request,
mark_paid, push_invoices_to_request, withdraw_payment,
withdraw_invoice_push, upload_expense_attachment,
delete_expense_attachment, preview_expense_attachment,
serve_expense_attachment_preview
```

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_oa_feature_gate.py rayher_hr_payroll/tests/test_invoice_request_integration.py"
```

Expected: new assertions fail because OA endpoints do not consult the policy.

- [ ] **Step 3: Add the three enforcement patterns**

1. Explicit type, before validation/query: `require_request_type_access(request_type)`.
2. Loaded request, before mutation: `require_request_type_access(doc.request_type)`.
3. Expense-only endpoint, first business check: `require_request_type_access(REQUEST_EXPENSE_PAYMENT)`.

For `get_options`, expose only `visible_request_types(REQUEST_TYPES)` and deny if empty. For mixed lists:

```python
allowed_types = visible_request_types(REQUEST_TYPES)
if request_type:
    require_request_type_access(request_type)
    allowed_types = [request_type]
if not allowed_types:
    return []
filters["request_type"] = request_type if request_type else ["in", allowed_types]
```

Do not alter existing applicant, approver, finance, HR, or executive scoping.

Register hooks:

```python
permission_query_conditions["OA Approval Request"] = "rayher_hr_payroll.oa_feature_gate.oa_request_query"
has_permission["OA Approval Request"] = "rayher_hr_payroll.oa_feature_gate.oa_request_has_permission"
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same containerized tests. Expected: all pass without database mutation.

- [ ] **Step 5: Commit**

```bash
git add rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/hooks.py rayher_hr_payroll/tests/test_invoice_request_integration.py rayher_hr_payroll/tests/test_oa_feature_gate.py
git commit -m "feat(oa): enforce approval gates server-side"
```

---

### Task 4: Close invoice/OCR bypass paths

**Files:**
- Modify: `rayher_hr_payroll/api/invoice_entry.py`
- Modify: `rayher_hr_payroll/invoice_ocr/permissions.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_ocr_domain.py`
- Create: `rayher_hr_payroll/tests/test_invoice_entry_gate.py`

**Interfaces:**
- Consumes: `require_request_type_access` and `can_access_request_type` for `REQUEST_EXPENSE_PAYMENT`.
- Produces: shared invoice API denial plus `1=0` query conditions and `False` read/edit decisions.

- [ ] **Step 1: Write failing invoice tests**

```python
def test_authenticated_guard_requires_expense_feature(monkeypatch):
    seen = []
    monkeypatch.setattr(invoice_entry, "require_request_type_access", seen.append)
    monkeypatch.setattr(invoice_entry, "frappe", SimpleNamespace(session=SimpleNamespace(user="employee@example.com")))
    invoice_entry._authenticated()
    assert seen == [invoice_entry.REQUEST_EXPENSE_PAYMENT]
```

Add permission cases:

```python
def test_restricted_gate_blocks_invoice_query_and_read(permissions_module, monkeypatch):
    monkeypatch.setattr(permissions_module, "can_access_request_type", lambda request_type, user=None: user == "Administrator")
    record = {"doctype": "OA Invoice Record", "owner": "employee@example.com"}
    assert permissions_module.invoice_record_query("employee@example.com") == "1=0"
    assert permissions_module.can_read_invoice(record, "employee@example.com") is False
```

Also assert Administrator remains allowed and an open switch preserves existing row SQL.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_invoice_entry_gate.py rayher_hr_payroll/tests/test_invoice_ocr_domain.py"
```

Expected: new tests fail.

- [ ] **Step 3: Gate shared entry and permission functions**

Call `require_request_type_access(REQUEST_EXPENSE_PAYMENT)` in `_authenticated()` after Guest rejection. Every invoice endpoint already calls that guard.

In `invoice_ocr/permissions.py`, deny before row logic in `can_read_invoice` and `can_edit_request`. Make `_query_context` return a distinct denied sentinel when reimbursement is restricted, and make all three invoice query hooks return `1=0` for it. Never confuse denial with `identity is None`, which currently means valid unrestricted high privilege.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same focused tests. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rayher_hr_payroll/api/invoice_entry.py rayher_hr_payroll/invoice_ocr/permissions.py rayher_hr_payroll/tests/test_invoice_entry_gate.py rayher_hr_payroll/tests/test_invoice_ocr_domain.py
git commit -m "feat(oa): gate invoice paths with reimbursement switch"
```

---

### Task 5: Build, activate, deploy, and verify

**Files:**
- Regenerate: `rayher_hr_payroll/public/frontend/`
- Regenerate: `rayher_hr_payroll/www/rayher.html`
- Runtime only: `sites/rayher.localhost/site_config.json`

**Interfaces:**
- Consumes all prior tasks.
- Produces a deployed site where only `Administrator` can access either OA module and both can later be independently restored.

- [ ] **Step 1: Run full backend tests**

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests"
```

Expected: zero failures.

- [ ] **Step 2: Run full frontend tests**

```powershell
$node='C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$tests=(Get-ChildItem frontend/tests/*.test.js).FullName
& $node --test $tests
```

Expected: zero failures and at least the prior 165 tests plus new cases.

- [ ] **Step 3: Build and commit production assets**

```bash
cd /workspace/development/frappe-bench/apps/rayher_hr_payroll/frontend
yarn build
```

Copy generated files back with trusted writers, verify no file begins with TipRay `TSD-Header`, run `git diff --check`, then:

```bash
git add rayher_hr_payroll/public/frontend rayher_hr_payroll/www/rayher.html
git commit -m "build: publish temporary OA gate assets"
```

- [ ] **Step 4: Push and deploy exact commit**

```bash
git push origin feat/ocr-monthly-timesheet-integration
```

Use the existing Git bundle procedure to switch `rayher-bench` to the exact commit without `git reset --hard`. Verify host, remote, and Docker HEADs match and both worktrees are clean.

- [ ] **Step 5: Enable both current-site switches**

```bash
cd /workspace/development/frappe-bench
bench --site rayher.localhost set-config leave_approval_admin_only 1 --parse
bench --site rayher.localhost set-config expense_reimbursement_admin_only 1 --parse
bench --site rayher.localhost clear-cache
bench --site rayher.localhost clear-website-cache
```

Restart the container. Verify both values are numeric `1` without exposing unrelated site configuration.

- [ ] **Step 6: Verify live allow/deny and data preservation**

With the existing administrator session, verify both menus and routes load. With one existing ordinary R&D test account, loading credentials without logging them, verify both menus are absent, both direct routes show the SPA 403 state, both explicit OA API types return a permission error, and `/entry` plus `/timesheet` retain prior access.

Read-only counts before and after activation must match for `OA Approval Request`, `OA Approval Step`, `OA Invoice Record`, and attachment DocTypes.

- [ ] **Step 7: Verify independent recovery in tests**

Verify these combinations without reopening the live site:

```text
leave=0, expense=1 -> leave restored only
leave=1, expense=0 -> reimbursement restored only
leave=0, expense=0 -> complete previous access matrix restored
```

Keep the live site at `1 / 1`.

- [ ] **Step 8: Final verification report**

Require all evidence:

```text
backend tests: 0 failed
frontend tests: 0 failed
Vite build: exit 0
host HEAD = remote HEAD = Docker HEAD
host and Docker worktrees clean
site switches = 1 / 1
Administrator allow paths pass
ordinary R&D deny paths pass
OA/invoice counts unchanged
```

Report commit, PR, both switch names, and the simple recovery commands. Note that QIHENG DEMO branding is queued separately.

