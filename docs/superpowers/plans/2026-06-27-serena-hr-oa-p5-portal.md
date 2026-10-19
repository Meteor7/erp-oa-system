# Serena HR/OA Platform — P5 Portal Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship the employee 工作台 and the manager 审批中心 as a zero-compile first version (Frappe Workspaces + a 待我审批 Script Report), reusing HRMS forms underneath. Owner/HR/Finance keep the official Desk workspace (no build).

**Architecture:** Two Frappe Workspaces (员工工作台, 审批中心) shipped as fixtures, plus a 待我审批 Script Report that aggregates everything pending the session user across the four request doctypes. The quick-action shortcuts deep-link to the native HRMS new-document forms. This is the "美化层" — optional and last; the frappe-ui SPA reskin (matching `test/portal-mockups/portal-c.html`) is a future follow-up, NOT in this plan.

**Tech Stack:** Frappe Workspace, Frappe Script Report, HRMS forms. **Part 5 of 5.**

**Spec:** `…/2026-06-27-serena-hr-oa-platform-design.md` (§6.1). **Prereq:** Foundation+P2+P3 merged (roles, workflow, approvers exist). Conventions per Foundation plan.

---

## File Structure
- Create: `rayher_hr_payroll/rayher_hr_payroll/report/pending_my_approval/` — `__init__.py`, `pending_my_approval.json`, `pending_my_approval.py` (Script Report, session-user aware).
- Create: `rayher_hr_payroll/fixtures/workspace.json` — `员工工作台` + `审批中心` Workspaces.
- Modify: `rayher_hr_payroll/hooks.py` — add `Workspace` to `fixtures`.
- Create tests: `tests/test_pending_approval_report.py`, `tests/test_portal_workspaces.py`.

---

## Task 1: 待我审批 Script Report (aggregates all pending for the session user)

**Files:** Create the report folder; test `tests/test_pending_approval_report.py`.

- [ ] **Step 1: Write the failing test** (pure — exercises the row-builder with injected rows):
```python
from rayher_hr_payroll.rayher_hr_payroll.report.pending_my_approval import pending_my_approval as rpt


def test_columns_cover_type_applicant_summary_status():
    cols = rpt.get_columns()
    labels = [c["label"] for c in cols]
    assert "类型" in labels and "申请人" in labels and "状态" in labels


def test_rows_from_sources_tags_each_type():
    sources = {
        "请假": [{"name": "LA-1", "employee_name": "南通工厂9", "status": "Open"}],
        "报销": [{"name": "EC-1", "employee_name": "演示员工146", "workflow_state": "经理已批"}],
    }
    rows = rpt.rows_from_sources(sources)
    types = {r[0] for r in rows}
    assert types == {"请假", "报销"}
    assert any("南通工厂9" in r for r in rows)
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError`). `pytest rayher_hr_payroll/tests/test_pending_approval_report.py -q`

- [ ] **Step 3: Create the report folder + files**

`mkdir -p` the folder, then `: >` the `__init__.py`. Author `pending_my_approval.py`:
```python
import frappe

_TYPES = [
    ("请假", "Leave Application", {"leave_approver": None, "status": "Open", "docstatus": 0}, "status"),
    ("出差", "Travel Request", {"docstatus": 0}, "status"),
    ("报销", "Expense Claim", {"workflow_state": ["in", ["草稿", "经理已批"]]}, "workflow_state"),
    ("调休", "Compensatory Leave Request", {"docstatus": 0}, "status"),
]


def get_columns():
    return [
        {"label": "类型", "fieldname": "type", "fieldtype": "Data", "width": 80},
        {"label": "单号", "fieldname": "name", "fieldtype": "Dynamic Link", "options": "doctype", "width": 160},
        {"label": "申请人", "fieldname": "applicant", "fieldtype": "Data", "width": 120},
        {"label": "状态", "fieldname": "state", "fieldtype": "Data", "width": 120},
    ]


def rows_from_sources(sources):
    rows = []
    for label, docs in sources.items():
        for d in docs:
            state = d.get("workflow_state") or d.get("status") or ""
            rows.append([label, d.get("name"), d.get("employee_name") or d.get("owner") or "", state])
    return rows


def _fetch():
    user = frappe.session.user
    sources = {}
    for label, doctype, filters, _state in _TYPES:
        f = dict(filters)
        if "leave_approver" in f:
            f["leave_approver"] = user
        sources[label] = frappe.get_all(
            doctype, filters=f,
            fields=["name", "employee_name", "owner", "status"] +
                   (["workflow_state"] if doctype == "Expense Claim" else []),
        )
    return sources


def execute(filters=None):
    return get_columns(), rows_from_sources(_fetch())
```

- [ ] **Step 4: Author `pending_my_approval.json`**:
```json
{
 "doctype": "Report",
 "name": "待我审批",
 "report_name": "待我审批",
 "ref_doctype": "Leave Application",
 "report_type": "Script Report",
 "is_standard": "Yes",
 "module": "Rayher HR Payroll",
 "roles": [
  {"role": "Department Manager"},
  {"role": "Accounts User"},
  {"role": "HR User"},
  {"role": "HR Manager"},
  {"role": "System Manager"}
 ]
}
```

- [ ] **Step 5: Run test → PASS** (2 passed).

- [ ] **Step 6: Commit**
```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/rayher_hr_payroll/report/pending_my_approval/ rayher_hr_payroll/tests/test_pending_approval_report.py
git commit -m "feat: add 待我审批 script report (pending items for the session user)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

## Task 2: 员工工作台 + 审批中心 Workspaces (fixture)

**Files:** Create `rayher_hr_payroll/fixtures/workspace.json`; Modify `hooks.py` `fixtures`; test `tests/test_portal_workspaces.py`.

- [ ] **Step 1: Write the failing test** — author `tests/test_portal_workspaces.py`:
```python
import json, os
import rayher_hr_payroll

WS = os.path.join(os.path.dirname(rayher_hr_payroll.__file__), "fixtures", "workspace.json")


def _load():
    with open(WS, encoding="utf-8") as f:
        return {w["name"]: w for w in json.load(f)}


def test_two_portal_workspaces_present():
    ws = _load()
    assert "员工工作台" in ws and "审批中心" in ws


def test_employee_workspace_has_four_quick_actions():
    sc = _load()["员工工作台"]["shortcuts"]
    targets = {(s["link_to"], s.get("doc_view")) for s in sc}
    for dt in ("Leave Application", "Travel Request", "Expense Claim", "Compensatory Leave Request"):
        assert (dt, "New") in targets


def test_approval_center_links_pending_report():
    sc = _load()["审批中心"]["shortcuts"]
    assert any(s["link_to"] == "待我审批" and s["type"] == "Report" for s in sc)
```

- [ ] **Step 2: Run → FAIL** (`FileNotFoundError`).

- [ ] **Step 3: Author `rayher_hr_payroll/fixtures/workspace.json`**:
```json
[
 {
  "doctype": "Workspace", "name": "员工工作台", "label": "员工工作台", "title": "员工工作台",
  "public": 1, "module": "Rayher HR Payroll",
  "content": "[{\"type\":\"header\",\"data\":{\"text\":\"快捷申请\"}}]",
  "shortcuts": [
   {"type": "DocType", "link_to": "Leave Application", "label": "请假申请", "doc_view": "New"},
   {"type": "DocType", "link_to": "Travel Request", "label": "出差申请", "doc_view": "New"},
   {"type": "DocType", "link_to": "Expense Claim", "label": "报销申请", "doc_view": "New"},
   {"type": "DocType", "link_to": "Compensatory Leave Request", "label": "加班/调休", "doc_view": "New"},
   {"type": "Report", "link_to": "待我审批", "label": "我的待办"}
  ]
 },
 {
  "doctype": "Workspace", "name": "审批中心", "label": "审批中心", "title": "审批中心",
  "public": 1, "module": "Rayher HR Payroll",
  "content": "[{\"type\":\"header\",\"data\":{\"text\":\"待我审批\"}}]",
  "shortcuts": [
   {"type": "Report", "link_to": "待我审批", "label": "待我审批"}
  ]
 }
]
```

- [ ] **Step 4: Add `Workspace` to `hooks.py` `fixtures`**:
```python
    {"dt": "Workspace", "filters": [["name", "in", ["员工工作台", "审批中心"]]]},
```

- [ ] **Step 5: Run test → PASS;** `bench migrate`; verify both workspaces load:
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench && echo 'import frappe; print(\"WS:\", frappe.db.exists(\"Workspace\",\"员工工作台\"), frappe.db.exists(\"Workspace\",\"审批中心\"))' | sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console" 2>&1 | grep "WS:"
```
Expected: both truthy.

- [ ] **Step 6: Commit** (`workspace.json`, `hooks.py`, test) with message `feat: add 员工工作台 + 审批中心 portal workspaces`.

## Task 3: Acceptance + future-SPA note

- [ ] **Step 1: Manual smoke per role** — log into `/app` as `emp@test` (sees 员工工作台 with the four quick-action shortcuts opening native HRMS forms) and as `mgr@test` (sees 审批中心 with 待我审批 listing items pending them). Owner/HR/Finance still get the official Desk workspace from Foundation P1.
- [ ] **Step 2: Full suite green + push.** pytest all → 0 failures; `git push`.
- [ ] **Step 3: Confirm P5 acceptance vs spec §6.1** — each role lands on the right surface; quick actions open HRMS forms; 待办 comes from real pending docs. P5 (zero-compile version) done.
- [ ] **Step 4: Record the follow-up** — the frappe-ui SPA reskin matching `test/portal-mockups/portal-c.html` (employee 工作台 + 审批中心 as Vue pages under the existing `/rayher` app) is a separate future plan; this Workspace version is the shippable interim and can be cut entirely if time-constrained without losing platform function.

---

## Self-Review

**Spec coverage (§6.1):** 员工工作台 + 快捷入口 → Task 2 (员工工作台 shortcuts → native forms); 经理审批中心 → Task 1 (待我审批 report) + Task 2 (审批中心 workspace); HR/财务/总控 用官方 Desk → inherited from P1 (no build); 先零编译后 SPA → Tasks 1-2 are zero-compile, SPA noted as Task 3 Step 4 follow-up. 待办数据来自 P2 → the report reads the same docs the P2 workflow/approvers drive.

**Placeholder scan:** none — report code, JSON, and tests are complete.

**Type/name consistency:** report `待我审批` / folder `pending_my_approval` / functions `get_columns`,`rows_from_sources`,`execute`; workspaces `员工工作台`,`审批中心`; shortcut targets are the same four HRMS doctypes used in P2 — consistent throughout.
