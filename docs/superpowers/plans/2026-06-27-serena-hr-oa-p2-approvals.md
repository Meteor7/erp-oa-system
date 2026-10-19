# Serena HR/OA Platform — P2 Approvals + Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Route the four request types (请假/出差/报销/调休) to the right approvers and fire reminders (需求#1 整合 + #3 提醒) — leave/travel/comp-leave via HRMS-native approvers, expense via a two-stage Frappe Workflow, all reminders via Frappe Notification.

**Architecture:** Configuration shipped as code+fixtures in `rayher_hr_payroll`. A new `approval_config.py` module declares the Notification set and is applied on migrate; the Expense Claim two-stage workflow ships as a fixture. Single-stage approvals reuse HRMS Department approvers (no workflow needed).

**Tech Stack:** Frappe Workflow engine, Frappe Notification, HRMS Expense Claim / Leave Application / Travel Request / Compensatory Leave Request. **Part 2 of 5.**

**Spec:** `docs/superpowers/specs/2026-06-27-serena-hr-oa-platform-design.md` (§P2). **Prereq:** Foundation plan (P0+P1) merged — `Department Manager`/`Leave Approver` roles + test users exist.

> Conventions (file-write rule, two-repo bench sync, test commands) are identical to the Foundation plan's "Conventions" section — follow them.

---

## File Structure

- Create: `rayher_hr_payroll/approval_config.py` — `NOTIFICATIONS` (list of Notification doc dicts) + `ensure_notifications()`. One responsibility: reminder config.
- Modify: `rayher_hr_payroll/install.py` — call `ensure_notifications()` in `after_install`.
- Create: `rayher_hr_payroll/fixtures/workflow.json` — the `Expense Claim Approval` two-stage workflow (states + transitions).
- Modify: `rayher_hr_payroll/hooks.py` — add `Workflow`, `Workflow State`, `Workflow Action Master` to `fixtures`.
- Create tests: `rayher_hr_payroll/tests/test_approval_config.py`, `rayher_hr_payroll/tests/test_expense_workflow_fixture.py`.

---

## Task 1: Reminder Notifications (config + tests)

**Files:**
- Create: `rayher_hr_payroll/approval_config.py`
- Test: `rayher_hr_payroll/tests/test_approval_config.py`

- [ ] **Step 1: Write the failing test** — author `rayher_hr_payroll/tests/test_approval_config.py`:
```python
from rayher_hr_payroll.approval_config import NOTIFICATIONS


def _by_name():
    return {n["name"]: n for n in NOTIFICATIONS}


def test_each_request_type_has_submit_and_decision_reminders():
    names = set(_by_name())
    for doctype in ("Leave Application", "Travel Request", "Expense Claim", "Compensatory Leave Request"):
        assert f"{doctype} 提交提醒" in names, doctype
        assert f"{doctype} 结果提醒" in names, doctype


def test_notifications_enabled_with_document_type():
    for n in NOTIFICATIONS:
        assert n["enabled"] == 1
        assert n["document_type"]
        assert n["channel"] in ("Email", "Notification")


def test_notification_names_unique():
    names = [n["name"] for n in NOTIFICATIONS]
    assert len(names) == len(set(names))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && /home/rayher/frappe-bench/env/bin/python -m pytest rayher_hr_payroll/tests/test_approval_config.py -q"`
Expected: FAIL — `ModuleNotFoundError: rayher_hr_payroll.approval_config`.

- [ ] **Step 3: Write the module** — author `rayher_hr_payroll/approval_config.py`. Each request type gets a submit reminder (notify approver) and a decision reminder (notify applicant). The Expense Claim decision watches `workflow_state`; the others watch `status`.
```python
import frappe

_TYPES = [
    ("Leave Application", "请假", "leave_approver", "status"),
    ("Travel Request", "出差", None, "status"),
    ("Expense Claim", "报销", "expense_approver", "workflow_state"),
    ("Compensatory Leave Request", "调休", "leave_approver", "status"),
]


def _submit(doctype, label, approver_field):
    recipients = [{"receiver_by_document_field": approver_field}] if approver_field else []
    return {
        "doctype": "Notification",
        "name": doctype + " 提交提醒",
        "subject": "新的" + label + "申请待审批: {{ doc.name }}",
        "document_type": doctype,
        "event": "Submit",
        "channel": "Notification",
        "enabled": 1,
        "is_standard": 1,
        "module": "Rayher HR Payroll",
        "recipients": recipients,
        "message": "{{ doc.owner }} 提交了" + label + "申请 {{ doc.name }},请及时处理。",
    }


def _decision(doctype, label, state_field):
    return {
        "doctype": "Notification",
        "name": doctype + " 结果提醒",
        "subject": "你的" + label + "申请已更新: {{ doc.name }}",
        "document_type": doctype,
        "event": "Value Change",
        "value_changed": state_field,
        "channel": "Notification",
        "enabled": 1,
        "is_standard": 1,
        "module": "Rayher HR Payroll",
        "recipients": [{"receiver_by_document_field": "owner"}],
        "message": "你的" + label + "申请 {{ doc.name }} 状态已更新。",
    }


NOTIFICATIONS = []
for _dt, _label, _appr, _state in _TYPES:
    NOTIFICATIONS.append(_submit(_dt, _label, _appr))
    NOTIFICATIONS.append(_decision(_dt, _label, _state))


def ensure_notifications():
    for n in NOTIFICATIONS:
        name = n["name"]
        skip = ("doctype", "name", "recipients")
        if frappe.db.exists("Notification", name):
            doc = frappe.get_doc("Notification", name)
            doc.update({k: v for k, v in n.items() if k not in skip})
            doc.set("recipients", [])
        else:
            doc = frappe.new_doc("Notification")
            doc.update({k: v for k, v in n.items() if k not in ("doctype", "recipients")})
        for r in n.get("recipients", []):
            doc.append("recipients", r)
        doc.save(ignore_permissions=True)
```

- [ ] **Step 4: Run the test to verify it passes** — same pytest command as Step 2. Expected: PASS (3 passed).

- [ ] **Step 5: Commit**
```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/approval_config.py rayher_hr_payroll/tests/test_approval_config.py
git commit -m "feat: declare approval reminder notifications

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

## Task 2: Wire `ensure_notifications()` into install

**Files:** Modify `rayher_hr_payroll/install.py`; extend `tests/test_approval_config.py`.

- [ ] **Step 1: Add failing wiring test** — append to `tests/test_approval_config.py`:
```python
def test_install_calls_ensure_notifications():
    import inspect, rayher_hr_payroll.install as install
    assert "ensure_notifications" in inspect.getsource(install)
```
- [ ] **Step 2: Run → FAIL.** `pytest rayher_hr_payroll/tests/test_approval_config.py::test_install_calls_ensure_notifications -q`
- [ ] **Step 3: Edit install.py** — add top import `from rayher_hr_payroll.approval_config import ensure_notifications`; inside `after_install`, after `ensure_access_control()`, add `ensure_notifications()`.
- [ ] **Step 4: Run tests → PASS; `bench migrate`; verify count:**
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench && echo 'import frappe; print(\"N:\", frappe.db.count(\"Notification\", {\"module\":\"Rayher HR Payroll\"}))' | sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console" 2>&1 | grep "N:"
```
Expected: `N: 8`.
- [ ] **Step 5: Commit**
```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/install.py rayher_hr_payroll/tests/test_approval_config.py
git commit -m "feat: apply approval notifications on install/migrate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

## Task 3: Expense Claim two-stage Workflow (fixture)

Two stages: `草稿 → 经理已批 → 财务已审 → 完成`. Manager (Department Manager) approves first; Accounts User does the final 复核 (review-only, no payment).

**Files:**
- Create: `rayher_hr_payroll/fixtures/workflow.json`
- Modify: `rayher_hr_payroll/hooks.py` (`fixtures` list)
- Test: `rayher_hr_payroll/tests/test_expense_workflow_fixture.py`

- [ ] **Step 1: Write the failing test** — author `tests/test_expense_workflow_fixture.py`:
```python
import json, os
import rayher_hr_payroll

WF = os.path.join(os.path.dirname(rayher_hr_payroll.__file__), "fixtures", "workflow.json")


def _load():
    with open(WF, encoding="utf-8") as f:
        data = json.load(f)
    return next(w for w in data if w["name"] == "Expense Claim Approval")


def test_workflow_targets_expense_claim():
    wf = _load()
    assert wf["document_type"] == "Expense Claim"
    assert wf["is_active"] == 1


def test_workflow_has_two_stage_states():
    states = {s["state"] for s in _load()["states"]}
    assert {"草稿", "经理已批", "财务已审", "已拒绝"} <= states


def test_transitions_are_role_gated_manager_then_finance():
    tr = _load()["transitions"]
    appr = {(t["state"], t["next_state"]): t["allowed"] for t in tr}
    assert appr[("草稿", "经理已批")] == "Department Manager"
    assert appr[("经理已批", "财务已审")] == "Accounts User"
```

- [ ] **Step 2: Run → FAIL** (`FileNotFoundError`). `pytest rayher_hr_payroll/tests/test_expense_workflow_fixture.py -q`

- [ ] **Step 3: Author `rayher_hr_payroll/fixtures/workflow.json`**
```json
[
 {
  "doctype": "Workflow",
  "name": "Expense Claim Approval",
  "workflow_name": "Expense Claim Approval",
  "document_type": "Expense Claim",
  "is_active": 1,
  "send_email_alert": 1,
  "workflow_state_field": "workflow_state",
  "states": [
   {"state": "草稿", "doc_status": "0", "allow_edit": "Employee"},
   {"state": "经理已批", "doc_status": "0", "allow_edit": "Department Manager"},
   {"state": "财务已审", "doc_status": "1", "allow_edit": "Accounts User"},
   {"state": "已拒绝", "doc_status": "0", "allow_edit": "Employee"}
  ],
  "transitions": [
   {"state": "草稿", "action": "提交审批", "next_state": "经理已批", "allowed": "Department Manager"},
   {"state": "草稿", "action": "拒绝", "next_state": "已拒绝", "allowed": "Department Manager"},
   {"state": "经理已批", "action": "财务复核", "next_state": "财务已审", "allowed": "Accounts User"},
   {"state": "经理已批", "action": "拒绝", "next_state": "已拒绝", "allowed": "Accounts User"}
  ]
 }
]
```

- [ ] **Step 4: Add the workflow doctypes to `hooks.py` `fixtures`** — the list becomes:
```python
fixtures = [
    {"dt": "Report", "filters": [["module", "=", "Rayher HR Payroll"], ["is_standard", "=", "No"]]},
    {"dt": "Workflow", "filters": [["name", "=", "Expense Claim Approval"]]},
    {"dt": "Workflow State", "filters": [["workflow_state_name", "in", ["草稿", "经理已批", "财务已审", "已拒绝"]]]},
    {"dt": "Workflow Action Master", "filters": [["workflow_action_name", "in", ["提交审批", "财务复核", "拒绝"]]]},
]
```

- [ ] **Step 5: Run test → PASS; load + verify on site:**
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench && sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost migrate && echo 'import frappe; w=frappe.get_doc(\"Workflow\",\"Expense Claim Approval\"); print(\"STATES:\", len(w.states), \"ACTIVE:\", w.is_active)' | sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console" 2>&1 | grep STATES
```
Expected: `STATES: 4 ACTIVE: 1`.

- [ ] **Step 6: Commit**
```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/fixtures/workflow.json rayher_hr_payroll/hooks.py rayher_hr_payroll/tests/test_expense_workflow_fixture.py
git commit -m "feat: add Expense Claim two-stage approval workflow (manager then finance review)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

## Task 4: HRMS Department approvers + end-to-end acceptance

**Files:** none in git — site config + verification (real approver routing is HRMS-native).

- [ ] **Step 1: Set the 研发部 leave/expense approver to the manager test user** — author `/tmp/set_approvers.py`:
```python
import frappe
dept = frappe.get_all("Department", filters={"department_name": ["like", "%研发%"]}, limit=1, pluck="name")[0]
d = frappe.get_doc("Department", dept)
d.set("leave_approvers", [{"approver": "mgr@test"}])
d.set("expense_approvers", [{"approver": "mgr@test"}])
d.save(ignore_permissions=True)
frappe.db.commit()
print("APPROVERS_SET:", dept)
```
Run via bench console. Expected: `APPROVERS_SET: <dept>`.

- [ ] **Step 2: End-to-end — submit a leave as 员工, assert routing + reminder** — author `/tmp/e2e_leave.py`:
```python
import frappe
frappe.set_user("emp@test")
emp = frappe.db.get_value("Employee", {"user_id": "emp@test"}, "name")
lt = frappe.get_all("Leave Type", limit=1, pluck="name")[0]
la = frappe.get_doc({"doctype": "Leave Application", "employee": emp, "leave_type": lt,
    "from_date": "2026-07-01", "to_date": "2026-07-01", "leave_approver": "mgr@test",
    "status": "Open"}).insert()
frappe.set_user("Administrator")
print("LEAVE_APPROVER:", la.leave_approver)  # expect mgr@test
# submit notification exists for this doctype
print("HAS_SUBMIT_NOTIF:", frappe.db.exists("Notification", "Leave Application 提交提醒") is not None)
```
Run via bench console. Expected: `LEAVE_APPROVER: mgr@test` and `HAS_SUBMIT_NOTIF: True`.

- [ ] **Step 3: End-to-end — drive the expense workflow manager→finance** — author `/tmp/e2e_expense.py`:
```python
import frappe
from frappe.model.workflow import apply_workflow
emp = frappe.db.get_value("Employee", {"user_id": "emp@test"}, "name")
ec = frappe.get_doc({"doctype": "Expense Claim", "employee": emp,
    "expense_approver": "mgr@test", "approval_status": "Draft",
    "expenses": [{"expense_date": "2026-07-01", "expense_type": frappe.get_all("Expense Claim Type", limit=1, pluck="name")[0], "amount": 100, "sanctioned_amount": 100}]}).insert(ignore_permissions=True)
frappe.set_user("mgr@test"); apply_workflow(ec, "提交审批")
frappe.set_user("fin@test"); ec.reload(); apply_workflow(ec, "财务复核")
frappe.set_user("Administrator"); ec.reload()
print("FINAL_STATE:", ec.workflow_state, "DOCSTATUS:", ec.docstatus)  # expect 财务已审 / 1
```
Run via bench console. Expected: `FINAL_STATE: 财务已审 DOCSTATUS: 1`.
If finance cannot act before manager (try `fin@test` applying `提交审批` → should raise), the role gating is correct.

- [ ] **Step 4: Full suite green + push**

Run pytest over `rayher_hr_payroll/tests` → all pass (Foundation + P2 tests, 0 failures). Then `git push` from the worktree.

- [ ] **Step 5: Confirm P2 acceptance against spec §P2 验证标准** — leave routes to manager + reminder fires; expense requires manager before finance; locked-period / cross-role acts blocked. P2 done.

---

## Self-Review

**Spec coverage:** 请假/出差/报销/调休 routing → Task 4 (HRMS approvers) + Task 3 (expense workflow); 两段报销 经理→财务 → Task 3 transitions; 提醒(铃铛+邮件)→ Task 1/2 Notifications (channel Notification + `send_email_alert` on the workflow); end-to-end proof → Task 4. Email channel note: each Notification ships as `channel="Notification"` (bell) and the workflow's `send_email_alert=1` covers email on transition; if per-type email reminders are also wanted, duplicate each dict with `channel="Email"` (out of scope for first pass — call it out, don't silently drop).

**Placeholder scan:** none — full code/JSON in every step.

**Type/name consistency:** `ensure_notifications`, `NOTIFICATIONS`, workflow `Expense Claim Approval`, states `草稿/经理已批/财务已审/已拒绝`, roles `Department Manager`/`Accounts User`, test users `emp@test`/`mgr@test`/`fin@test` (from Foundation Task 1.5) — consistent throughout.
