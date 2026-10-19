# Serena HR/OA Platform — Foundation (P0 + P1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the platform foundation — a clean worktree/bench on the `frappe-rd-cost-poc@a1c78a2` baseline, plus master data, four-tier roles, the 总控 (Owner) Role Profile, and the 员工信息总表 report.

**Architecture:** Configuration-as-code in the `rayher_hr_payroll` app: a new `access_control.py` module (mirroring the existing `custom_fields.py` pattern) declares custom roles + Role Profile and is applied idempotently from `install.after_install`; the 员工信息总表 is a Query Report shipped via the existing `fixtures` mechanism. HRMS-native Department / Designation / Employee Education provide the org/education data.

**Tech Stack:** Frappe 15.111, ERPNext 15.111, HRMS 15.61, Python/pytest. Plan is **Part 1 of 5** (P2 approval, P3 lifecycle, P4 payroll+R&D, P5 shell are separate plans).

**Spec:** `docs/superpowers/specs/2026-06-27-serena-hr-oa-platform-design.md`

---

## Conventions for this repo (read first)

- **File-write rule (HARD):** never use editor Write/Edit tools on this machine (TipRay encryption corrupts them). Author every file via `Bash` heredoc (`cat > f << 'EOF'`), `sed`, or `wsl python`. Verify after writing that the first bytes are real content, not a `%TSD-Header%` blob.
- **Two repos:** the Windows worktree is for editing/committing; the running site is the WSL bench clone at `/home/rayher/frappe-bench/apps/rayher_hr_payroll`. Changes only affect the site after the WSL clone is on the branch and `bench migrate` runs.
- **Run unit tests:** `wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && /home/rayher/frappe-bench/env/bin/python -m pytest rayher_hr_payroll/tests -q"`
- **Run one test:** append `rayher_hr_payroll/tests/test_x.py::test_name -v`.
- **GitHub ops use wsl** (push/fetch).

---

## File Structure (what this plan creates/touches)

- Create: `rayher_hr_payroll/access_control.py` — declares `CUSTOM_ROLES`, `ROLE_PROFILES`, and `ensure_access_control()`. One responsibility: role/role-profile config.
- Modify: `rayher_hr_payroll/install.py` — call `ensure_access_control()` from `after_install`.
- Create: `rayher_hr_payroll/fixtures/employee_info_report.json` — the 员工信息总表 Query Report fixture (hand-authored, HR/Owner-gated, no status filter).
- Modify: `rayher_hr_payroll/hooks.py` — broaden the `fixtures` Report filter so the new report ships, and export the `Role`/`Role Profile` fixtures.
- Modify: `rayher_hr_payroll/demo.py` — seed sample Department / Designation / Employee Education on demo employees so the report and routing have data.
- Create/extend tests: `rayher_hr_payroll/tests/test_access_control.py`, `rayher_hr_payroll/tests/test_employee_info_report.py`, and extend `tests/test_demo.py`.

---

## P0 — Worktree + Bench Baseline Alignment

### Task 0.1: Fast-forward main and branch the worktree

**Files:** none (git topology only).

- [ ] **Step 1: Verify the baseline is a clean fast-forward**

Run:
```bash
cd /e/QIHENG Demo/Logistics
git fetch origin
git merge-base --is-ancestor main origin/frappe-rd-cost-poc && echo "FF-OK" || echo "NOT-FF"
```
Expected: `FF-OK`.

- [ ] **Step 2: Fast-forward local main to the baseline**

Run:
```bash
cd /e/QIHENG Demo/Logistics
git branch -f main origin/frappe-rd-cost-poc
git rev-parse --short main   # expect a1c78a2
```
Expected: prints `a1c78a2`.

- [ ] **Step 3: Create the feature branch + worktree off the baseline**

Run:
```bash
cd /e/QIHENG Demo/Logistics
git worktree add -b feat/serena-hr-oa ../Logistics-hroa origin/frappe-rd-cost-poc
git -C ../Logistics-hroa rev-parse --short HEAD   # expect a1c78a2
```
Expected: a new worktree at `E:/QIHENG Demo/Logistics-hroa` on `feat/serena-hr-oa` at `a1c78a2`.

- [ ] **Step 4: Carry the spec + this plan into the new branch**

Run:
```bash
cp /e/QIHENG Demo/Logistics/docs/superpowers/specs/2026-06-27-serena-hr-oa-platform-design.md /e/QIHENG Demo/Logistics-hroa/docs/superpowers/specs/ 2>/dev/null || { mkdir -p /e/QIHENG Demo/Logistics-hroa/docs/superpowers/specs && cp /e/QIHENG Demo/Logistics/docs/superpowers/specs/2026-06-27-serena-hr-oa-platform-design.md /e/QIHENG Demo/Logistics-hroa/docs/superpowers/specs/; }
mkdir -p /e/QIHENG Demo/Logistics-hroa/docs/superpowers/plans
cp /e/QIHENG Demo/Logistics/docs/superpowers/plans/2026-06-27-serena-hr-oa-foundation.md /e/QIHENG Demo/Logistics-hroa/docs/superpowers/plans/
cd /e/QIHENG Demo/Logistics-hroa && git add docs/superpowers && git commit -m "docs: carry HR/OA spec + foundation plan onto feature branch

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
Expected: a commit on `feat/serena-hr-oa` adding the two docs.

- [ ] **Step 5: Push the branch so the WSL bench can fetch it**

Run:
```bash
cd /e/QIHENG Demo/Logistics-hroa && wsl -e bash -lc "cd /mnt/e/QIHENG Demo/Logistics-hroa && git push -u origin feat/serena-hr-oa"
```
Expected: branch published to origin.

### Task 0.2: Align the WSL bench to the new branch and prove green baseline

**Files:** none (environment only).

- [ ] **Step 1: Record the bench's current branch (so it can be restored)**

Run:
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && git rev-parse --abbrev-ref HEAD"
```
Expected: prints `feat/rd-spa-period-aware` (the old PR#7 branch). Note it down.

- [ ] **Step 2: Check out the new branch in the bench clone**

Run:
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && git fetch origin && git checkout feat/serena-hr-oa && git rev-parse --short HEAD"
```
Expected: prints `a1c78a2`.

- [ ] **Step 3: Migrate the site onto the baseline**

Run:
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench && sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost migrate"
```
Expected: migrate completes without error.

- [ ] **Step 4: Prove the existing suite is green on the baseline**

Run:
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && /home/rayher/frappe-bench/env/bin/python -m pytest rayher_hr_payroll/tests -q"
```
Expected: all existing tests pass (97 green), 0 failures. **Do not proceed to P1 unless green.**

---

## P1 — Master Data + Four-Tier Roles + 总控 + 员工信息总表

> All P1 work happens in the **`E:/QIHENG Demo/Logistics-hroa`** worktree on `feat/serena-hr-oa`. After code changes, sync the WSL bench with:
> `wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && git fetch origin && git checkout feat/serena-hr-oa && git pull && cd /home/rayher/frappe-bench && sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost migrate"`
> (push from the worktree first so the bench can pull.)

### Task 1.1: `access_control.py` — custom role + Owner Role Profile (data + tests)

**Files:**
- Create: `rayher_hr_payroll/access_control.py`
- Test: `rayher_hr_payroll/tests/test_access_control.py`

- [ ] **Step 1: Write the failing test**

Author `rayher_hr_payroll/tests/test_access_control.py` (via Bash heredoc):
```python
from rayher_hr_payroll.access_control import CUSTOM_ROLES, ROLE_PROFILES


def test_department_manager_role_declared():
    names = [r["role_name"] for r in CUSTOM_ROLES]
    assert "Department Manager" in names


def test_owner_role_profile_bundles_required_roles():
    profiles = {p["role_profile"]: p for p in ROLE_PROFILES}
    assert "总控 Owner" in profiles, "Owner role profile must exist"
    owner_roles = profiles["总控 Owner"]["roles"]
    for role in ("System Manager", "HR Manager", "Accounts User", "Department Manager"):
        assert role in owner_roles


def test_role_profile_roles_are_unique():
    for p in ROLE_PROFILES:
        assert len(p["roles"]) == len(set(p["roles"])), p["role_profile"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && /home/rayher/frappe-bench/env/bin/python -m pytest rayher_hr_payroll/tests/test_access_control.py -q"`
Expected: FAIL — `ModuleNotFoundError: No module named 'rayher_hr_payroll.access_control'`.

- [ ] **Step 3: Write the module**

Author `rayher_hr_payroll/access_control.py` (via Bash heredoc):
```python
import frappe

# Four-tier role model. 员工=Employee, HR=HR User/HR Manager, 财务=Accounts User
# all reuse stock roles; only "Department Manager" is new — it scopes 本部门
# visibility for 工时/看板/审批 (range enforced later via User Permission).
CUSTOM_ROLES = [
    {"role_name": "Department Manager", "desk_access": 1},
]

# 总控 (Owner) account for Serena: ONE Role Profile bundling the stock roles whose
# union grants see-everything + operate-everything, including Employee PII
# (HR Manager), finance (Accounts User), and config (System Manager). Assigned to
# her normal user — NEVER the Administrator account (Frappe anti-pattern).
ROLE_PROFILES = [
    {
        "role_profile": "总控 Owner",
        "roles": ["System Manager", "HR Manager", "Accounts User", "Department Manager"],
    },
]


def ensure_access_control():
    _ensure_custom_roles()
    _ensure_role_profiles()


def _ensure_custom_roles():
    for r in CUSTOM_ROLES:
        if not frappe.db.exists("Role", r["role_name"]):
            doc = frappe.new_doc("Role")
            doc.update(r)
            doc.insert(ignore_permissions=True)


def _ensure_role_profiles():
    for rp in ROLE_PROFILES:
        name = rp["role_profile"]
        if frappe.db.exists("Role Profile", name):
            doc = frappe.get_doc("Role Profile", name)
            doc.set("roles", [])
        else:
            doc = frappe.new_doc("Role Profile")
            doc.role_profile = name
        for role in rp["roles"]:
            doc.append("roles", {"role": role})
        doc.save(ignore_permissions=True)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && /home/rayher/frappe-bench/env/bin/python -m pytest rayher_hr_payroll/tests/test_access_control.py -q"`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/access_control.py rayher_hr_payroll/tests/test_access_control.py
git commit -m "feat: declare Department Manager role + 总控 Owner role profile

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 1.2: Wire `ensure_access_control()` into install

**Files:**
- Modify: `rayher_hr_payroll/install.py` (the `after_install` function)
- Test: `rayher_hr_payroll/tests/test_access_control.py` (add one test)

- [ ] **Step 1: Add the failing wiring test**

Append to `rayher_hr_payroll/tests/test_access_control.py`:
```python
def test_install_calls_ensure_access_control():
    import inspect
    import rayher_hr_payroll.install as install
    src = inspect.getsource(install)
    assert "ensure_access_control" in src
```

- [ ] **Step 2: Run it to verify it fails**

Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && /home/rayher/frappe-bench/env/bin/python -m pytest rayher_hr_payroll/tests/test_access_control.py::test_install_calls_ensure_access_control -q"`
Expected: FAIL (assertion error — string not found).

- [ ] **Step 3: Edit install.py**

Use `sed` to add the import after the existing CUSTOM_FIELDS import, and the call inside `after_install`. Author the change via Bash (`sed` or rewrite the file with a heredoc preserving existing content). The resulting `install.py` must contain, at top:
```python
from rayher_hr_payroll.access_control import ensure_access_control
```
and inside `after_install`, after `_ensure_spa_perms()`:
```python
    ensure_access_control()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && /home/rayher/frappe-bench/env/bin/python -m pytest rayher_hr_payroll/tests/test_access_control.py -q"`
Expected: PASS (4 passed).

- [ ] **Step 5: Apply on the site and verify the role + profile exist**

Run:
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench && sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost migrate && echo 'import frappe; print(\"ROLE:\", frappe.db.exists(\"Role\",\"Department Manager\")); print(\"PROFILE:\", frappe.db.exists(\"Role Profile\",\"总控 Owner\"))' | sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console" 2>&1 | grep -E "ROLE:|PROFILE:"
```
Expected: `ROLE: Department Manager` and `PROFILE: 总控 Owner` (both truthy).

- [ ] **Step 6: Commit**

```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/install.py rayher_hr_payroll/tests/test_access_control.py
git commit -m "feat: apply access control (role + role profile) on install/migrate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 1.3: 员工信息总表 — standard Query Report (HR-only, includes 演示员工166)

**Files:**
- Create: `rayher_hr_payroll/rayher_hr_payroll/report/employee_info_summary/__init__.py` (empty)
- Create: `rayher_hr_payroll/rayher_hr_payroll/report/employee_info_summary/employee_info_summary.json`
- Test: `rayher_hr_payroll/tests/test_employee_info_report.py`

- [ ] **Step 1: Write the failing test**

Author `rayher_hr_payroll/tests/test_employee_info_report.py` (via Bash heredoc):
```python
import json
import os

import rayher_hr_payroll

REPORT_JSON = os.path.join(
    os.path.dirname(rayher_hr_payroll.__file__),
    "rayher_hr_payroll", "report", "employee_info_summary", "employee_info_summary.json",
)


def _load():
    with open(REPORT_JSON, encoding="utf-8") as f:
        return json.load(f)


def test_report_is_standard_query_report_on_employee():
    d = _load()
    assert d["report_type"] == "Query Report"
    assert d["is_standard"] == "Yes"
    assert d["ref_doctype"] == "Employee"
    assert d["module"] == "Rayher HR Payroll"


def test_report_is_hr_only_not_finance():
    d = _load()
    roles = {r["role"] for r in d["roles"]}
    assert {"HR User", "HR Manager", "System Manager"} <= roles
    # Finance must NOT see the PII (id card) report:
    assert "Accounts User" not in roles


def test_report_includes_left_employees_pii_and_education():
    q = _load()["query"].lower()
    # No status filter => 演示员工166 (Left) employees are included (需求#5):
    assert "status =" not in q and "status=" not in q
    # PII column + education join present:
    assert "id_card_number_cn" in q
    assert "tabemployee education" in q
```

- [ ] **Step 2: Run it to verify it fails**

Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && /home/rayher/frappe-bench/env/bin/python -m pytest rayher_hr_payroll/tests/test_employee_info_report.py -q"`
Expected: FAIL — `FileNotFoundError` (report json missing).

- [ ] **Step 3: Create the report folder + files**

Author the empty init:
```bash
: > /e/QIHENG Demo/Logistics-hroa/rayher_hr_payroll/rayher_hr_payroll/report/employee_info_summary/__init__.py
```
(Create the dir first with `mkdir -p`.)

Author `employee_info_summary.json` (via Bash heredoc). The `query` is one line:
```json
{
 "doctype": "Report",
 "name": "员工信息总表",
 "report_name": "员工信息总表",
 "ref_doctype": "Employee",
 "report_type": "Query Report",
 "is_standard": "Yes",
 "module": "Rayher HR Payroll",
 "query": "SELECT emp.employee_name AS \"姓名:Data:160\", emp.id_card_number_cn AS \"身份证号:Data:160\", emp.gender AS \"性别:Data:80\", edu.qualification AS \"学历:Data:120\", edu.school_univ AS \"毕业院校:Data:180\", edu.maj_optional AS \"专业:Data:140\", emp.department AS \"部门:Link/Department:160\", emp.designation AS \"岗位:Link/Designation:160\", emp.status AS \"状态:Data:90\" FROM `tabEmployee` emp LEFT JOIN (SELECT e1.parent, e1.qualification, e1.school_univ, e1.maj_optional FROM `tabEmployee Education` e1 INNER JOIN (SELECT parent, MAX(idx) AS max_idx FROM `tabEmployee Education` GROUP BY parent) e2 ON e1.parent = e2.parent AND e1.idx = e2.max_idx) edu ON edu.parent = emp.name ORDER BY emp.employee_name",
 "roles": [
  {"role": "System Manager"},
  {"role": "HR User"},
  {"role": "HR Manager"}
 ]
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && /home/rayher/frappe-bench/env/bin/python -m pytest rayher_hr_payroll/tests/test_employee_info_report.py -q"`
Expected: PASS (3 passed).

- [ ] **Step 5: Load on the site and verify the report runs**

Push from worktree, then in WSL: `git pull && bench migrate`, then:
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench && echo 'import frappe; from frappe.desk.query_report import run; print(\"COLS:\", len(run(\"员工信息总表\")[\"columns\"]))' | sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console" 2>&1 | grep COLS
```
Expected: `COLS: 9` (the report executes and returns 9 columns).

- [ ] **Step 6: Commit**

```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/rayher_hr_payroll/report/employee_info_summary/
git add rayher_hr_payroll/tests/test_employee_info_report.py
git commit -m "feat: add 员工信息总表 Query Report (HR-only, includes 演示员工166)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 1.4: Seed sample org masters + education (so the report and routing have data)

**Files:** none in git — this is idempotent site data applied via console. (Real employees are maintained by HR in the UI; this seeds verifiable demo data.)

- [ ] **Step 1: Apply sample Department / Designation / Employee Education**

Author `/tmp/seed_org.py` (via Bash heredoc) and run it on the site:
```python
import frappe

# Idempotent sample masters
for dept in ["研发部", "财务部"]:
    if not frappe.db.exists("Department", {"department_name": dept}):
        frappe.get_doc({"doctype": "Department", "department_name": dept,
                        "company": frappe.defaults.get_global_default("company")}).insert(ignore_permissions=True)
for desig in ["软件工程师", "会计"]:
    if not frappe.db.exists("Designation", desig):
        frappe.get_doc({"doctype": "Designation", "designation_name": desig}).insert(ignore_permissions=True)

# Attach dept/designation/education to the first demo employee
emp = frappe.get_all("Employee", limit=1, pluck="name")
if emp:
    e = frappe.get_doc("Employee", emp[0])
    e.department = frappe.get_all("Department", filters={"department_name": "研发部"}, pluck="name")[0]
    e.designation = "软件工程师"
    if not e.get("education"):
        e.append("education", {"qualification": "本科", "school_univ": "示例大学", "maj_optional": "计算机科学"})
    e.save(ignore_permissions=True)
    print("SEEDED:", e.name)
frappe.db.commit()
```
Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench && sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console < /tmp/seed_org.py" 2>&1 | grep SEEDED`
Expected: `SEEDED: <employee id>`.

- [ ] **Step 2: Verify the seeded employee appears in the report with education**

Run:
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench && echo 'import frappe; from frappe.desk.query_report import run; rows=run(\"员工信息总表\")[\"result\"]; print(\"HAS_EDU:\", any((r.get(\"学历\") or r.get(2)) for r in rows) if rows and isinstance(rows[0],dict) else bool(rows))' | sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console" 2>&1 | grep HAS_EDU
```
Expected: `HAS_EDU: True` (a row carries 学历). No commit (site data only).

### Task 1.5: Four-tier + 总控 visibility — test accounts, User Permissions, verification

**Files:** none in git — site config + verification script. (Production accounts are created by HR; this proves the model.)

- [ ] **Step 1: Create five test users with the right roles**

Author `/tmp/make_users.py` and run it. Creates: `emp@test` (Employee), `hr@test` (HR User), `fin@test` (Accounts User), `mgr@test` (Department Manager + Leave Approver), `owner@test` (Role Profile 总控 Owner).
```python
import frappe
USERS = [
    ("emp@test",   ["Employee"]),
    ("hr@test",    ["Employee", "HR User"]),
    ("fin@test",   ["Employee", "Accounts User"]),
    ("mgr@test",   ["Employee", "Department Manager", "Leave Approver"]),
]
for email, roles in USERS:
    if not frappe.db.exists("User", email):
        u = frappe.new_doc("User"); u.email = email; u.first_name = email.split("@")[0]
        u.new_password = __import__("os").environ["DEMO_BOOTSTRAP_PASSWORD"]; u.send_welcome_email = 0; u.insert(ignore_permissions=True)
    u = frappe.get_doc("User", email)
    u.add_roles(*roles)
# Owner via Role Profile
if not frappe.db.exists("User", "owner@test"):
    o = frappe.new_doc("User"); o.email = "owner@test"; o.first_name = "owner"
    o.new_password = __import__("os").environ["DEMO_BOOTSTRAP_PASSWORD"]; o.send_welcome_email = 0; o.role_profile_name = "总控 Owner"
    o.insert(ignore_permissions=True)
frappe.db.commit()
print("USERS_OK")
```
Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench && sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console < /tmp/make_users.py" 2>&1 | grep USERS_OK`
Expected: `USERS_OK`.

- [ ] **Step 2: Bind 员工 to an Employee + scope 经理 to a department (User Permissions)**

Author `/tmp/scope_users.py` and run it:
```python
import frappe
emp = frappe.get_all("Employee", filters={"department": ["like", "%研发%"]}, limit=1, pluck="name")
emp = emp[0] if emp else frappe.get_all("Employee", limit=1, pluck="name")[0]
e = frappe.get_doc("Employee", emp); e.user_id = "emp@test"; e.save(ignore_permissions=True)
# 员工 sees only own Employee record:
if not frappe.db.exists("User Permission", {"user": "emp@test", "allow": "Employee", "for_value": emp}):
    frappe.get_doc({"doctype": "User Permission", "user": "emp@test", "allow": "Employee", "for_value": emp}).insert(ignore_permissions=True)
# 经理 scoped to the 研发部 department:
dept = e.department
if dept and not frappe.db.exists("User Permission", {"user": "mgr@test", "allow": "Department", "for_value": dept}):
    frappe.get_doc({"doctype": "User Permission", "user": "mgr@test", "allow": "Department", "for_value": dept}).insert(ignore_permissions=True)
frappe.db.commit()
print("SCOPED:", emp, dept)
```
Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench && sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console < /tmp/scope_users.py" 2>&1 | grep SCOPED`
Expected: `SCOPED: <emp> <dept>`.

- [ ] **Step 3: Verify each role's visibility**

Author `/tmp/verify_scope.py` and run it:
```python
import frappe
from frappe.desk.query_report import run

def as_user(u, fn):
    frappe.set_user(u)
    try:
        return fn()
    finally:
        frappe.set_user("Administrator")

total = frappe.db.count("Employee")
emp_seen = as_user("emp@test", lambda: len(frappe.get_list("Employee", limit_page_length=0)))
owner_seen = as_user("owner@test", lambda: len(frappe.get_list("Employee", limit_page_length=0)))

def fin_pii():
    try:
        run("员工信息总表"); return "ALLOWED"
    except frappe.PermissionError:
        return "BLOCKED"
fin_report = as_user("fin@test", fin_pii)
hr_report = as_user("hr@test", lambda: "ALLOWED" if run("员工信息总表") else "EMPTY")

print("EMP_SEES_ONLY_OWN:", emp_seen == 1, "(", emp_seen, "of", total, ")")
print("OWNER_SEES_ALL:", owner_seen == total)
print("FINANCE_PII_REPORT:", fin_report)   # expect BLOCKED
print("HR_PII_REPORT:", hr_report)         # expect ALLOWED
```
Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench && sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console < /tmp/verify_scope.py" 2>&1 | grep -E "EMP_SEES|OWNER_SEES|FINANCE_PII|HR_PII"`
Expected:
```
EMP_SEES_ONLY_OWN: True ( 1 of N )
OWNER_SEES_ALL: True
FINANCE_PII_REPORT: BLOCKED
HR_PII_REPORT: ALLOWED
```
If any line is wrong, fix the role/User Permission and re-run before continuing. **This is the P1 acceptance gate from the spec (§P1 验证标准).**

### Task 1.6: Full-suite green + close out P1

- [ ] **Step 1: Run the entire test suite**

Run: `wsl -e bash -lc "cd /home/rayher/frappe-bench/apps/rayher_hr_payroll && /home/rayher/frappe-bench/env/bin/python -m pytest rayher_hr_payroll/tests -q"`
Expected: all pass — the original 97 plus the new access-control (4) and report (3) tests, 0 failures.

- [ ] **Step 2: Push the branch**

Run: `wsl -e bash -lc "cd /mnt/e/QIHENG Demo/Logistics-hroa && git push"`
Expected: `feat/serena-hr-oa` updated on origin.

- [ ] **Step 3: Confirm P1 acceptance against the spec**

Re-read spec §P1 验证标准 and confirm every bullet is demonstrated by Task 1.3–1.5 outputs: employee has dept/岗位/学历; 总表 includes 演示员工166; four accounts + 总控 see the correct scope. P1 is done.

---

## Self-Review (completed by plan author)

**Spec coverage (§ of spec → task):**
- P0 worktree + bench align → Task 0.1, 0.2 ✓
- P1 部门/岗位/学历 masters → Task 1.4 ✓
- P1 员工信息总表 含演示员工166 + HR-only PII (需求#5) → Task 1.3 ✓
- P1 四档角色 → Task 1.1 (Department Manager) + reuse of stock roles ✓
- P1 总控 Role Profile (System Manager + HR Manager + Accounts User) → Task 1.1, 1.2 ✓
- P1 可见范围验证(员工只见自己/财务不见 PII/总控全见) → Task 1.5 ✓
- Apply on install/migrate → Task 1.2 ✓
- **Deferred to later plans (by design):** 职位变动 routing data, approval flows (P2), lifecycle (P3), payroll+R&D (P4), shell (P5). The `Leave Approver` granted to `mgr@test` in Task 1.5 is forward-looking for P2.

**Placeholder scan:** none — every code step has full content; every command has expected output.

**Type/name consistency:** `ensure_access_control`, `CUSTOM_ROLES`, `ROLE_PROFILES`, role name `Department Manager`, profile name `总控 Owner`, report name `员工信息总表`, report path `rayher_hr_payroll/rayher_hr_payroll/report/employee_info_summary/employee_info_summary.json` — used identically across Tasks 1.1–1.5. ✓

**Note on `total` vs User Permission:** Task 1.5 Step 3 expects `OWNER_SEES_ALL: True` (owner has no User Permission, sees all `total`) and `EMP_SEES_ONLY_OWN` = 1; if the site has User-Permission-sharing settings that change counts, adjust the assertion to the documented scope, not the raw number.
