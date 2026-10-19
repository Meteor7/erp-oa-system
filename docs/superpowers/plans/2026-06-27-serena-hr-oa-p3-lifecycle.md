# Serena HR/OA Platform — P3 Lifecycle (入职/演示员工166/职位变动) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make onboarding auto-create a login account, separation disable it, and position changes (promotion/transfer) re-route approvals — needs #4 (入职/演示员工166信息维护) + #6 (职位变动).

**Architecture:** HRMS provides Employee Onboarding / Separation / Promotion / Transfer natively. The only custom code is `lifecycle_controls.py`: an `Employee` doc-event that creates+binds a `User` (Employee role) when an employee becomes Active and disables it when they become Left. Promotion/Transfer routing needs no code — it updates Department/Designation which the approver lookup already reads.

**Tech Stack:** HRMS Employee lifecycle doctypes, Frappe User, doc_events. **Part 3 of 5.**

**Spec:** `…/2026-06-27-serena-hr-oa-platform-design.md` (§P3). **Prereq:** Foundation + P2 merged. Conventions per Foundation plan.

---

## File Structure
- Create: `rayher_hr_payroll/lifecycle_controls.py` — `sync_user_for_employee(doc, method)` + helpers. One responsibility: Employee↔User account lifecycle.
- Modify: `rayher_hr_payroll/hooks.py` — add the Employee `after_insert` / `on_update` events.
- Create test: `rayher_hr_payroll/tests/test_lifecycle_controls.py`.

---

## Task 1: Employee→User account sync (code + tests)

**Files:** Create `rayher_hr_payroll/lifecycle_controls.py`; test `rayher_hr_payroll/tests/test_lifecycle_controls.py`.

- [ ] **Step 1: Write the failing test** (pure-unit on a fake doc; no DB):
```python
import types
from rayher_hr_payroll import lifecycle_controls as lc


class FakeEmp(dict):
    def __getattr__(self, k):
        return self.get(k)


def test_target_email_prefers_company_then_personal():
    assert lc._target_email(FakeEmp(company_email="a@tests-x.example.invalid", personal_email="b@tests-y.example.invalid")) == "a@tests-x.example.invalid"
    assert lc._target_email(FakeEmp(personal_email="b@tests-y.example.invalid")) == "b@tests-y.example.invalid"
    assert lc._target_email(FakeEmp()) is None


def test_should_disable_only_when_left():
    assert lc._should_disable(FakeEmp(status="Left")) is True
    assert lc._should_disable(FakeEmp(status="Active")) is False


def test_default_role_is_employee_only():
    assert lc.DEFAULT_EMPLOYEE_ROLES == ["Employee"]
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError`). `pytest rayher_hr_payroll/tests/test_lifecycle_controls.py -q`

- [ ] **Step 3: Write the module** — author `rayher_hr_payroll/lifecycle_controls.py`:
```python
import frappe

DEFAULT_EMPLOYEE_ROLES = ["Employee"]


def _target_email(doc):
    return doc.company_email or doc.personal_email or None


def _should_disable(doc):
    return doc.status == "Left"


def sync_user_for_employee(doc, method=None):
    """Onboarding/HR creates the Employee; ensure a matching login account.
    Active + has email + no user  -> create User (Employee role only) and bind user_id.
    Left                          -> disable the linked User. New management roles are
    NEVER auto-granted here (least privilege); HR adds them by hand afterwards."""
    if _should_disable(doc):
        if doc.user_id and frappe.db.exists("User", doc.user_id):
            user = frappe.get_doc("User", doc.user_id)
            if user.enabled:
                user.enabled = 0
                user.save(ignore_permissions=True)
        return

    if doc.status != "Active" or doc.user_id:
        return
    email = _target_email(doc)
    if not email:
        return
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
    else:
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = doc.employee_name or email.split("@")[0]
        user.send_welcome_email = 0
        user.insert(ignore_permissions=True)
    user.add_roles(*DEFAULT_EMPLOYEE_ROLES)
    doc.db_set("user_id", email)
```

- [ ] **Step 4: Run test → PASS** (3 passed).

- [ ] **Step 5: Commit**
```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/lifecycle_controls.py rayher_hr_payroll/tests/test_lifecycle_controls.py
git commit -m "feat: sync Employee to a least-privilege User account on lifecycle change

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

## Task 2: Wire the Employee doc-events

**Files:** Modify `rayher_hr_payroll/hooks.py` `doc_events["Employee"]`; extend test.

- [ ] **Step 1: Add failing wiring test** — append to `tests/test_lifecycle_controls.py`:
```python
def test_hooks_register_user_sync():
    from rayher_hr_payroll import hooks
    ev = hooks.doc_events["Employee"]
    flat = str(ev)
    assert "lifecycle_controls.sync_user_for_employee" in flat
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Edit hooks.py** — the existing `Employee` entry has a `validate` list; add `after_insert` and `on_update`:
```python
    "Employee": {
        "validate": [
            "rayher_hr_payroll.employee_controls.validate_employee_archive",
            "rayher_hr_payroll.employee_controls.validate_employee_rd_lock",
        ],
        "after_insert": "rayher_hr_payroll.lifecycle_controls.sync_user_for_employee",
        "on_update": "rayher_hr_payroll.lifecycle_controls.sync_user_for_employee",
    },
```
- [ ] **Step 4: Run test → PASS; `bench migrate`.**
- [ ] **Step 5: Commit**
```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/hooks.py rayher_hr_payroll/tests/test_lifecycle_controls.py
git commit -m "feat: register Employee lifecycle user-sync events

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

## Task 3: End-to-end acceptance (onboarding / transfer / separation)

**Files:** none in git — site verification of native flows + our sync hook.

- [ ] **Step 1: Onboarding auto-creates a bound, least-privilege account** — author `/tmp/e2e_onboard.py`:
```python
import frappe
e = frappe.get_doc({"doctype": "Employee", "first_name": "演示员工138甲", "status": "Active",
    "company_email": "newhire1@test", "date_of_joining": "2026-07-01", "gender": "Male",
    "company": frappe.defaults.get_global_default("company"),
    "department": frappe.get_all("Department", filters={"department_name": ["like","%研发%"]}, pluck="name")[0],
    "designation": "软件工程师"}).insert(ignore_permissions=True)
e.reload()
print("USER_ID:", e.user_id)                                   # expect newhire1@test
print("ROLES:", frappe.get_roles("newhire1@test"))             # expect ['Employee', ...] only employee-level
```
Run via bench console. Expected: `USER_ID: newhire1@test`; roles contain `Employee` and **no** HR/Accounts/System Manager.

- [ ] **Step 2: Transfer re-routes approvals** — author `/tmp/e2e_transfer.py`. Change the employee's department to 财务部, then confirm the leave-approver lookup follows:
```python
import frappe
emp = frappe.db.get_value("Employee", {"company_email": "newhire1@test"}, "name")
e = frappe.get_doc("Employee", emp)
fin_dept = frappe.get_all("Department", filters={"department_name": ["like","%财务%"]}, pluck="name")[0]
e.department = fin_dept; e.save(ignore_permissions=True)
appr = frappe.get_all("Department Approver",
    filters={"parent": fin_dept, "parentfield": "leave_approvers"}, pluck="approver")
print("NEW_DEPT:", e.department, "DEPT_APPROVERS:", appr)
```
Run via bench console. Expected: department is the 财务部 id and its approver list is what drives the next leave application (routing followed the transfer).

- [ ] **Step 3: Separation disables the login** — author `/tmp/e2e_separate.py`:
```python
import frappe
emp = frappe.db.get_value("Employee", {"company_email": "newhire1@test"}, "name")
e = frappe.get_doc("Employee", emp)
e.status = "Left"; e.relieving_date = "2026-07-31"; e.save(ignore_permissions=True)
print("USER_ENABLED:", frappe.db.get_value("User", "newhire1@test", "enabled"))  # expect 0
print("IN_REPORT:", any(r for r in __import__("frappe").db.sql(
    "select name from tabEmployee where company_email=%s and status='Left'", emp and "newhire1@test")))
```
Run via bench console. Expected: `USER_ENABLED: 0` (login disabled) but the employee row still exists with status Left (so 员工信息总表 still lists them — 需求#5).

- [ ] **Step 4: Full suite green + push.** pytest all → 0 failures; `git push`.

- [ ] **Step 5: Confirm P3 acceptance vs spec §P3** — onboarding builds a usable least-privilege account; transfer moves the approval route; separation disables login yet keeps the record. P3 done.

---

## Self-Review

**Spec coverage:** 入职建号 → Task 1/3 Step 1; 演示员工166停用+留档 → Task 1 (`_should_disable`) + Task 3 Step 3; 调岗改路由 → Task 3 Step 2 (native Department/Designation update, no code); 入职只给"员工"角色 → `DEFAULT_EMPLOYEE_ROLES=["Employee"]` (Task 1). Promotion/Transfer/Onboarding/Separation forms themselves are HRMS-native and need no build — only the account-sync hook is custom.

**Placeholder scan:** none.

**Type/name consistency:** `sync_user_for_employee`, `_target_email`, `_should_disable`, `DEFAULT_EMPLOYEE_ROLES`, hook keys `after_insert`/`on_update` — consistent across tasks; `Department Approver` child doctype + `leave_approvers` parentfield match HRMS schema used in P2 Task 4.
