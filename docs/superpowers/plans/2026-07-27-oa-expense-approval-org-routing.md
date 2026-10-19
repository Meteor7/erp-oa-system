# OA Expense Approval and Organization Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local OA reimbursement workflow follow the approved six-stage route, use department supervisors from the organization chart, and align Docker with the tested PR #24 commit.

**Architecture:** Keep route construction pure in `oa_approval.py`, add a focused organization resolver in `oa_organization.py`, and let `oa_entry.py` supply the authenticated applicant context and enabled User lookup. Recover Docker-only fixes through failing regression tests before adding new behavior. Store route snapshots on submitted requests; do not recalculate active routes from later organization changes.

**Tech Stack:** Python 3.12, Frappe/ERPNext, pytest, Vue 3, Vitest, Vite, MariaDB, Docker Compose.

## Global Constraints

- Docker is the local deployment and acceptance environment; `feat/ocr-monthly-timesheet-integration` is the source of truth.
- Approval steps store stable User IDs; Chinese names are display labels only.
- Philippe and Sabri are organization nodes without accounts and never receive approval steps.
- Employee lists under a team are peers reporting to the named team supervisor, not a vertical employee chain.
- The whole reimbursement request has exactly one required asset type.
- Applicant self-approval is retained when the applicant owns a later route node.
- Existing invoices, private attachments, audit events, and completed approval history must remain intact.
- No password or temporary credential is written to Git.

---

### Task 1: Recover Docker-only OA fixes with regressions

**Files:**
- Modify: `rayher_hr_payroll/tests/test_oa_approval_routes.py`
- Modify: `rayher_hr_payroll/tests/test_active_oa_approver_migration.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_ocr_service.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `rayher_hr_payroll/invoice_ocr/permissions.py`
- Modify: `rayher_hr_payroll/oa_approval.py`
- Modify: `rayher_hr_payroll/patches/v1_0/migrate_active_oa_approvers.py`

**Interfaces:**
- Consumes: current PR #24 OA and invoice APIs.
- Produces: Docker-only Ren Feifan routing, canonical identity migration, executive invoice visibility, corrected Chinese validation text, and authorized expense-line serialization in the clean worktree.

- [ ] **Step 1: Add the failing regression tests**

Add literal behavior assertions:

```python
def test_non_electronic_fixed_asset_routes_to_ren_feifan():
    steps = build_expense_payment_route(
        department="研发部 - RAY",
        supervisor="演示员工132",
        asset_category="非电子类固定资产（人事/行政）",
    )
    asset_step = next(step for step in steps if step["label"] == "演示员工10")
    assert asset_step["approvers"] == ["person047@legacy.example.invalid"]


def test_legacy_ren_approver_stays_ren_feifan():
    assert migration.LEGACY_USER_MAP["演示员工10"] == "person047@legacy.example.invalid"


def test_business_executive_can_view_invoice_records():
    assert permissions.has_record_permission(
        {"request": "OA-REQ-1"},
        user="executive@example.com",
        roles={"QIHENG Demo Business Executive"},
    )
```

Add an API serialization regression that supplies two expense lines but authorizes only one and asserts the summary returns only that line.

- [ ] **Step 2: Run the targeted tests and verify RED**

Run:

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_oa_approval_routes.py rayher_hr_payroll/tests/test_active_oa_approver_migration.py rayher_hr_payroll/tests/test_invoice_ocr_service.py rayher_hr_payroll/tests/test_invoice_request_integration.py"
```

Expected: failures for Ren Feifan routing/migration, executive visibility, or restricted expense-line serialization against PR #24 code.

- [ ] **Step 3: Recover only the verified Docker behavior**

Apply the semantic Docker changes to the four production files. Preserve LF endings and replace any corrupted `????` literals with the confirmed Chinese text. Do not copy generated caches or the Docker worktree's old Git metadata.

- [ ] **Step 4: Run the targeted tests and verify GREEN**

Run the command from Step 2.

Expected: all targeted tests pass.

- [ ] **Step 5: Commit the recovery**

```bash
git add rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/invoice_ocr/permissions.py rayher_hr_payroll/oa_approval.py rayher_hr_payroll/patches/v1_0/migrate_active_oa_approvers.py rayher_hr_payroll/tests
git commit -m "fix: recover active OA approval corrections"
```

---

### Task 2: Add department-supervisor organization resolution

**Files:**
- Create: `rayher_hr_payroll/oa_organization.py`
- Create: `rayher_hr_payroll/tests/test_oa_organization.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`

**Interfaces:**
- Consumes: applicant Employee name, department, the approved organization-chart mapping, and a callback `resolve_user(employee_name) -> str | None`.
- Produces: `resolve_stage_two_supervisor(employee_name, resolve_user) -> SupervisorResolution`, where the result contains `decision` (`approve` or `skip`), display label, User ID, traversed manager names, and diagnostic reason.

- [ ] **Step 1: Write failing resolver tests**

Use hand-derived fixtures:

```python
def test_software_employee_resolves_to_jun_zhang():
    result = resolve_stage_two_supervisor("演示员工150", resolve_user)
    assert result.decision == "approve"
    assert result.supervisor_name == "演示员工132"
    assert result.user_id == "person024@business.example.invalid"


def test_jun_zhang_bypasses_philippe_and_skips_stage_two():
    result = resolve_stage_two_supervisor("演示员工132", resolve_user)
    assert result.decision == "skip"
    assert result.traversed == ("Philippe", "演示员工21")


def test_bu_manager_bypasses_sabri_and_skips_stage_two():
    result = resolve_stage_two_supervisor("南通工厂7", resolve_user)
    assert result.decision == "skip"
    assert result.traversed == ("Sabri", "演示员工21")


def test_peer_names_do_not_become_a_vertical_chain():
    assert direct_supervisor_name("演示员工117") == "演示员工132"
    assert direct_supervisor_name("演示员工112") == "演示员工132"
```

Include Finance (`演示员工13 -> 演示员工16`), HR/Admin (`演示员工30 -> 演示员工10`), and ordinary Algorithm member (`演示员工206 -> 演示员工108`) cases.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_oa_organization.py"
```

Expected: import failure because `oa_organization.py` does not exist.

- [ ] **Step 3: Implement the minimal organization resolver**

Define:

```python
@dataclass(frozen=True)
class SupervisorResolution:
    decision: str
    supervisor_name: str = ""
    user_id: str = ""
    traversed: tuple[str, ...] = ()
    reason: str = ""


EXCLUDED_MANAGERS = {"Philippe", "Sabri"}
TOP_EXECUTIVES = {"演示员工21", "演示员工29"}
```

Store one explicit `DIRECT_SUPERVISOR_BY_EMPLOYEE` mapping derived from the approved chart. Ordinary team members map to their named team supervisor. Team supervisors map to the parent department supervisor. Philippe and Sabri map upward to Li Qinggele for the stage-two decision; reaching either top executive returns `skip`.

Raise `OrganizationResolutionError` for an active employee absent from the mapping, a cycle, or a chain that ends without an enabled supervisor/top executive.

- [ ] **Step 4: Integrate authenticated Employee context**

Extend `_employee_context()` to return the Employee name and resolved supervisor result. Ignore caller-supplied free-text supervisor during submit and route preview for authenticated applicants. Allow explicit fixture context only in pure unit tests.

- [ ] **Step 5: Run resolver and API tests**

Run:

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_oa_organization.py rayher_hr_payroll/tests/test_oa_approval_routes.py rayher_hr_payroll/tests/test_invoice_request_integration.py"
```

Expected: all pass.

- [ ] **Step 6: Commit organization resolution**

```bash
git add rayher_hr_payroll/oa_organization.py rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests/test_oa_organization.py rayher_hr_payroll/tests/test_invoice_request_integration.py
git commit -m "feat: resolve OA department supervisors"
```

---

### Task 3: Implement the canonical six-stage route

**Files:**
- Modify: `rayher_hr_payroll/oa_approval.py`
- Modify: `rayher_hr_payroll/tests/test_oa_approval_routes.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`

**Interfaces:**
- Consumes: canonical department class, `SupervisorResolution`, and one canonical asset category.
- Produces: ordered route-step dictionaries with stable User IDs and modes `approve`, `all`, or `handle`.

- [ ] **Step 1: Replace old route expectations with failing canonical cases**

Add exact route assertions for:

```python
assert route_labels(r_and_d_employee_other_asset) == [
    "财务审核：演示员工13",
    "直属主管：演示员工132",
    "财务主管：演示员工16",
    "副总经理：演示员工21",
    "总经理：演示员工29",
    "确认付款：演示员工13",
]

assert route_labels(r_and_d_manager_non_electronic_asset) == [
    "财务审核：演示员工13",
    "固定资产审批：演示员工10",
    "财务主管：演示员工16",
    "副总经理：演示员工21",
    "总经理：演示员工29",
    "确认付款：演示员工13",
]

assert route_modes(customer_service_electronic_asset) == [
    "approve", "approve", "approve", "all", "handle"
]
```

Also assert Finance routes to Wang Yansong only at Stage 5, Sales/customer-service uses a two-user `all` step, other departments use sequential Li Qinggele then Wang Yansong, and self-owned later nodes are retained.

- [ ] **Step 2: Run route tests and verify RED**

Run:

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_oa_approval_routes.py"
```

Expected: old route lacks Zhang Meng, uses the wrong department branches, or inserts the wrong supervisor/asset node.

- [ ] **Step 3: Implement canonical identities and labels**

Use:

```python
ADMIN_ASSET = "非电子类固定资产（人事/行政）"
IT_ASSET = "电子类固定资产（IT）"
OTHER_ASSET = "其他"
FINANCE_MANAGER_USER = "person072@legacy.example.invalid"
IT_APPROVER_USER = "person068@legacy.example.invalid"
```

Build Stage 1, optional Stage 2, optional Stage 3, mandatory Stage 4, department Stage 5, and final Stage 6 in that order. Do not deduplicate self-approval nodes.

- [ ] **Step 4: Enforce route inputs and snapshot behavior**

Validate that the asset category is one of the three canonical values and required accounts are enabled before route activation. Persist the generated route on submission and retain it on later reads/actions.

- [ ] **Step 5: Run route and workflow tests**

Run:

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_oa_approval_routes.py rayher_hr_payroll/tests/test_invoice_request_integration.py"
```

Expected: all pass.

- [ ] **Step 6: Commit the route**

```bash
git add rayher_hr_payroll/oa_approval.py rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests/test_oa_approval_routes.py rayher_hr_payroll/tests/test_invoice_request_integration.py
git commit -m "feat: implement six-stage expense approval route"
```

---

### Task 4: Update request UI and final confirmation semantics

**Files:**
- Modify: `frontend/src/components/ExpenseWorkbench.vue`
- Modify: `frontend/src/pages/OAApprovals.vue`
- Modify: `frontend/tests/expense-workbench-source.test.js`
- Modify: `frontend/tests/oa-source.test.js`
- Modify: `frontend/tests/dynamic-expense-approval.test.js`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`

**Interfaces:**
- Consumes: backend `asset_categories`, route preview, current-step mode, and capability flags.
- Produces: required request-level asset selection, backend-owned supervisor display, and explicit `确认付款` action for the final `handle` step.

- [ ] **Step 1: Write failing frontend and backend tests**

Assert:

- exactly the three canonical asset choices render;
- the submit action rejects an empty asset category;
- no editable free-text supervisor is submitted;
- a `handle` current step renders `确认付款`;
- approving earlier Finance audit does not mark payment complete;
- only Ye Liwei can confirm the final handle step.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree/frontend frappe/bench:latest bash -lc "yarn install --frozen-lockfile && yarn test --run tests/expense-workbench-source.test.js tests/oa-source.test.js tests/dynamic-expense-approval.test.js"
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_invoice_request_integration.py"
```

Expected: old labels, free-text supervisor field, or generic `办理完成` action causes failures.

- [ ] **Step 3: Implement the UI contract**

Render the single-select after OCR confirmation and in the manual request form. Use backend context for the supervisor summary. Label the final action `确认付款` and keep reject/add-sign hidden for `handle`.

- [ ] **Step 4: Implement backend final-confirmation checks**

Require the current step to be `handle`, the assigned User to be Ye Liwei, and the action to come from the authenticated matching actor or authorized audited override. Record a distinct confirmation event and set the terminal paid/completed state atomically.

- [ ] **Step 5: Run targeted tests and production build**

Run:

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree/frontend frappe/bench:latest bash -lc "yarn test --run && yarn build"
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_invoice_request_integration.py"
```

Expected: tests and build pass.

- [ ] **Step 6: Commit UI and confirmation**

```bash
git add frontend/src frontend/tests rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests/test_invoice_request_integration.py rayher_hr_payroll/public/frontend
git commit -m "feat: finalize OA asset selection and payment confirmation"
```

---

### Task 5: Add diagnostics and idempotent live-data preparation

**Files:**
- Create: `rayher_hr_payroll/maintenance/oa_routing_diagnostics.py`
- Create: `rayher_hr_payroll/tests/test_oa_routing_diagnostics.py`
- Modify: `rayher_hr_payroll/maintenance/business_account_bootstrap.py`
- Modify: `rayher_hr_payroll/tests/test_business_account_bootstrap.py`
- Modify: `rayher_hr_payroll/patches/v1_0/migrate_active_oa_approvers.py`

**Interfaces:**
- Consumes: active Employee records, organization mapping, User links, account enabled state, and unresolved active OA steps.
- Produces: dry-run diagnostics and idempotent preparation/migration counts without passwords or destructive document changes.

- [ ] **Step 1: Write failing diagnostics tests**

Use controlled employees to assert the diagnostic reports:

- an employee absent from the organization map;
- a required approver with no linked/enabled User;
- an accountless excluded manager that successfully resolves upward;
- zero errors for the canonical six required approvers;
- no mutation in dry-run mode.

- [ ] **Step 2: Run diagnostics tests and verify RED**

Run:

```powershell
docker run --rm --volumes-from rayher-bench --mount "type=bind,source=D:\rayher\.worktrees\ocr-monthly-timesheet-integration,target=/worktree" -w /worktree frappe/bench:latest bash -lc "/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_oa_routing_diagnostics.py rayher_hr_payroll/tests/test_business_account_bootstrap.py rayher_hr_payroll/tests/test_active_oa_approver_migration.py"
```

Expected: import failure for the new diagnostics module.

- [ ] **Step 3: Implement diagnostics and account assertions**

The live command must list every active applicant, resolved Stage 2 decision, canonical department class, and missing mapping/account errors. It must verify the existing Ren Feifan, Yi Jiawei, Zhang Meng, Li Qinggele, Wang Yansong, and Ye Liwei accounts without changing existing passwords.

- [ ] **Step 4: Run dry-run against `rayher.localhost`**

Run:

```powershell
docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench && bench --site rayher.localhost execute rayher_hr_payroll.maintenance.oa_routing_diagnostics.run --kwargs '{\"dry_run\": true}'"
```

Expected: every active employee in scope resolves; required approver accounts are enabled and linked; no business documents change.

- [ ] **Step 5: Run migration dry-run and apply only after clean diagnostics**

Run the existing approver migration in dry-run mode, inspect counts, then apply it. Because authorized cleanup left no draft/pending requests, expected active-step mutation count is zero unless new acceptance fixtures exist.

- [ ] **Step 6: Commit diagnostics**

```bash
git add rayher_hr_payroll/maintenance rayher_hr_payroll/patches/v1_0/migrate_active_oa_approvers.py rayher_hr_payroll/tests
git commit -m "feat: add OA routing readiness diagnostics"
```

---

### Task 6: Deploy exact worktree state and run full acceptance

**Files:**
- Modify only if a failing test requires it: files from Tasks 1-5.
- Verify: Docker app checkout, MariaDB site, OCR container, built frontend assets, PR #24.

**Interfaces:**
- Consumes: clean tested worktree commits.
- Produces: local Docker running the exact tested commit, clean Git status, live acceptance evidence, and updated PR #24.

- [ ] **Step 1: Run the full pre-deployment suite**

Run backend unit/integration tests, all frontend tests, and production build. Record exact pass counts and commit SHA.

- [ ] **Step 2: Back up live local state**

Create a Frappe site backup including private files and record the backup path. Do not expose credentials in logs.

- [ ] **Step 3: Deploy the exact commit to Docker**

Synchronize only tracked files from the clean worktree, run `bench migrate`, clear cache, rebuild/restart required services, and verify the app/OCR health endpoints. Do not retain the old copied-file working state.

- [ ] **Step 4: Run five real-account acceptance scenarios**

Use isolated fixture request subjects with a unique `OA-E2E-20260727-` prefix:

1. R&D ordinary employee + `其他`;
2. R&D supervisor under Philippe + non-electronic fixed asset;
3. customer-service employee + electronic fixed asset + two-person co-sign;
4. Finance employee + `其他`;
5. applicant who owns a later approval node.

For each, assert exact route labels/User IDs, complete every node with the assigned account, and finish with Ye Liwei clicking `确认付款`.

- [ ] **Step 5: Clean only acceptance fixtures**

Delete requests, steps, lines, logs, and uploaded files whose subject/prefix exactly matches the acceptance prefix. Recount to prove no unrelated business document was removed.

- [ ] **Step 6: Verify repository alignment**

Require:

```bash
git status --porcelain
git rev-parse HEAD
```

to show a clean Docker checkout at the same SHA as the clean worktree. Recheck the host main repository and all worktrees are clean.

- [ ] **Step 7: Push and update PR #24**

Push `feat/ocr-monthly-timesheet-integration`, verify PR #24 points to the tested SHA, and report its checks, mergeability, test evidence, and remaining review status. Do not merge without explicit user instruction.
