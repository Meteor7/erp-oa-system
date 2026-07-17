# Account, Project File, And Zero-Hour Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Deliver pinyin employee accounts, in-app password changes, Zhang Jun's account-specific access, securely readable project reports, and zero-hour leave/comp-time records.

**Architecture:** Keep the existing Admin / Project Owner / Employee hierarchy. Reuse the existing All Project Access capability only as Zhang Jun's exception, add a scope-checked report download endpoint, preserve private attachments, store zero-hour leave/comp-time as explicitly marked draft Timesheets, and perform user renames through a tested maintenance module.

**Tech Stack:** Frappe/ERPNext/HRMS, Python, Vue 3, frappe-ui, Vitest/Node tests, pytest, MariaDB, Docker Compose.

## Global Constraints

- Do not broaden native Project or File permissions for every Project Owner.
- Frontend route visibility and backend API authorization must match.
- Keep all 33 existing project report files private and attached to their original Project fields.
- Only 请假 and 调休 may use zero hours; zero-hour records must never enter allocation ratios.
- Rename only active Employee-linked accounts matching hr-emp-*@rayher.local.
- Preserve existing passwords and all Link fields during user rename.
- Back up the site before schema or account data changes.
- Use trusted shell/container writers because TipRay makes native patch writers unsafe.

---

### Task 1: Secure Project Report Authorization

**Files:**
- Modify: rayher_hr_payroll/api/project_entry.py
- Modify: rayher_hr_payroll/tests/test_project_entry.py
- Modify: frontend/src/pages/Projects.vue
- Modify: frontend/tests/project-page-source.test.js

**Interfaces:**
- Produces: download_project_report(project: str, fieldname: str) -> Frappe download response
- Consumes: existing _require_project_access(), _can_view_all_projects(), and Project.project_owner

- [ ] **Step 1: Write backend failing tests**

Add tests proving that the endpoint rejects unknown fields, rejects an unrelated Project Owner, accepts an owner for their own project, accepts Admin/All Project Access, and requires a File attached to the requested Project and field.

~~~python
def test_download_report_rejects_unrelated_owner(monkeypatch):
    frappe.session.user = "owner@example.com"
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner"]
    monkeypatch.setattr(mod.frappe.db, "get_value", project_and_file_fixture(owner="other@example.com"))
    with pytest.raises(Exception):
        mod.download_project_report("RD04", "project_initiation_report")
~~~

- [ ] **Step 2: Run the focused backend test and verify RED**

Run:
    docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench/apps/rayher_hr_payroll && ../../env/bin/python -m pytest rayher_hr_payroll/tests/test_project_entry.py -q"

Expected: new download tests fail because download_project_report does not exist.

- [ ] **Step 3: Implement the scoped endpoint**

Add an allowlist and one shared project-scope helper. Resolve the File by all of attached_to_doctype, attached_to_name, attached_to_field, and file_url before loading its content.

~~~python
PROJECT_REPORT_FIELDS = {
    "project_initiation_report",
    "project_completion_report",
    "capitalization_confirmation_file",
}

@frappe.whitelist()
def download_project_report(project, fieldname):
    roles = _require_project_access()
    fieldname = _clean(fieldname)
    if fieldname not in PROJECT_REPORT_FIELDS:
        frappe.throw(frappe._("无效的项目报告类型。"))
    row = _accessible_project(project, roles)
    file_url = row.get(fieldname)
    if not file_url:
        frappe.throw(frappe._("该项目尚未上传此报告。"))
    file_name = frappe.db.get_value("File", {
        "attached_to_doctype": "Project",
        "attached_to_name": row.get("name"),
        "attached_to_field": fieldname,
        "file_url": file_url,
        "is_private": 1,
    }, "name")
    if not file_name:
        frappe.throw(frappe._("项目报告附件不存在或关联不正确。"))
    file_doc = frappe.get_doc("File", file_name)
    frappe.local.response.filename = file_doc.file_name
    frappe.local.response.filecontent = file_doc.get_content()
    frappe.local.response.type = "download"
~~~

- [ ] **Step 4: Run backend tests and verify GREEN**

Run the Task 1 focused test command. Expected: all test_project_entry.py tests pass.

- [ ] **Step 5: Write frontend failing source tests**

Assert that Projects.vue no longer links row[field] directly and that report URLs call download_project_report with encoded Project and field names.

- [ ] **Step 6: Update Projects.vue**

Add reportDownloadUrl(row, fieldname), keep buttons close to the project identity columns, display uploaded/not-uploaded state, and preserve horizontal scrolling for the remaining columns.

- [ ] **Step 7: Run frontend focused tests**

Run:
    docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench/apps/rayher_hr_payroll/frontend && node --test tests/project-page-source.test.js"

Expected: pass.

### Task 2: Zhang Jun Account Exception And Foreign R&D

**Files:**
- Modify: frontend/src/lib/access.js
- Modify: frontend/tests/access.test.js
- Modify: rayher_hr_payroll/api/foreign_rd_entry.py
- Modify: rayher_hr_payroll/tests/test_access_control.py or the existing foreign-R&D authorization test module

**Interfaces:**
- Consumes: existing All Project Access role attached only to Zhang Jun's linked account
- Produces: finance roles OR All Project Access for /foreign-rd and its APIs

- [ ] **Step 1: Write failing frontend/backend tests**

~~~javascript
window.roles = ['Employee', 'Project Owner', 'All Project Access']
assert.equal(canSee('/foreign-rd'), true)
assert.equal(canSee('/expense'), false)
~~~

~~~python
def test_foreign_rd_accepts_all_project_access():
    assert "All Project Access" in mod.RD_FOREIGN_FINANCE_ROLES
~~~

- [ ] **Step 2: Run focused tests and verify RED**

Run access.test.js and the focused backend test. Expected: foreign route/API excludes All Project Access.

- [ ] **Step 3: Implement additive access**

Create FOREIGN_RD_ACCESS = [...FINANCE, 'All Project Access'] in access.js and set RD_FOREIGN_FINANCE_ROLES = (*RD_FINANCE_ROLES, "All Project Access") in foreign_rd_entry.py. Do not add Accounts/HR access to any unrelated page.

- [ ] **Step 4: Run focused tests and verify GREEN**

Expected: Zhang exception passes while a normal Project Owner remains denied.

### Task 3: In-App Password Change

**Files:**
- Modify: frontend/src/App.vue
- Modify: frontend/tests/app-shell-source.test.js

**Interfaces:**
- Consumes: Frappe stock POST method frappe.core.doctype.user.user.update_password
- Produces: header button and modal with old_password, new_password, confirmation

- [ ] **Step 1: Write failing source tests**

Assert the app shell contains 修改密码, old/new/confirmation password inputs, the stock method name, mismatch validation, and form clearing after close/success.

- [ ] **Step 2: Run the source test and verify RED**

Run:
    docker exec rayher-bench bash -lc "cd /workspace/development/frappe-bench/apps/rayher_hr_payroll/frontend && node --test tests/app-shell-source.test.js"

- [ ] **Step 3: Implement the modal**

Use Vue refs and frappe-ui createResource. Validate non-empty current password, matching new passwords, and server-side password policy. Submit only:

~~~javascript
await passwordUpdater.submit({
  old_password: passwordForm.old_password,
  new_password: passwordForm.new_password,
  logout_all_sessions: 1,
})
~~~

Clear all password refs on close and success. Never print payloads.

- [ ] **Step 4: Run the focused test and build**

Expected: app shell tests pass and yarn build succeeds.

### Task 4: Zero-Hour Leave And Comp Time

**Files:**
- Modify: rayher_hr_payroll/api/timesheet_entry.py
- Modify: rayher_hr_payroll/tests/test_timesheet_entry.py
- Modify: frontend/src/pages/TimesheetEntry.vue
- Modify: frontend/src/lib/timesheetImport.js
- Modify: frontend tests for timesheet source/import behavior

**Interfaces:**
- Produces: ZERO_HOUR_ACTIVITY_TYPES = {"请假", "调休"}
- Persists: rd_spa_managed=1, docstatus=0 draft Timesheet only for a zero-hour special activity
- Preserves: submitted Timesheets for positive hours

- [ ] **Step 1: Write backend failing tests**

Cover zero-hour 请假 and 调休 draft insertion without submit, zero-hour normal activity rejection, negative-hour rejection, list query inclusion of marked special drafts only, delete support, and positive-hour submit behavior unchanged.

~~~python
def test_zero_hour_leave_is_saved_as_draft(monkeypatch):
    saved = capture_timesheet(monkeypatch)
    mod._save_rd_hours_row(
        period="2026-07", employee="EMP-1", project="RD04",
        work_date="2026-07-01", activity_type="请假", hours=0,
        description="annual leave",
    )
    assert saved.docstatus == 0
    assert saved.rd_spa_managed == 1
    assert saved.time_logs[0].hours == 0
    assert saved.submit_calls == 0
~~~

- [ ] **Step 2: Run test_timesheet_entry.py and verify RED**

Expected: current hours=0 path deletes/does not insert and list query excludes drafts.

- [ ] **Step 3: Implement backend behavior**

Validate with:
    is_zero_special = hours == 0 and activity in ZERO_HOUR_ACTIVITY_TYPES

Reject hours == 0 for every other activity. For a special zero record, create a draft with from_time equal to to_time, insert it, do not submit it, and return it through list_rd_hours. Keep allocation/report SQL restricted to docstatus=1.

Change list_rd_hours only to include:
    ts.docstatus = 1
    OR (ts.docstatus = 0 AND ts.rd_spa_managed = 1 AND tsd.hours = 0 AND tsd.activity_type IN ('请假','调休'))

- [ ] **Step 4: Run backend focused tests and verify GREEN**

- [ ] **Step 5: Write frontend failing tests**

Assert dynamic minimum is zero for 请假/调休, normal activities reject zero, and paste/Excel validation follows the same rule.

- [ ] **Step 6: Implement frontend validation**

Use a shared isZeroHourActivity(activity) helper in manual entry and import parsing. Set input min dynamically to 0 for special activities and 0.5 otherwise.

- [ ] **Step 7: Run frontend focused tests**

Expected: manual and batch zero-hour cases pass.

### Task 5: Pinyin Account Rename Maintenance Module

**Files:**
- Modify: pyproject.toml
- Create: rayher_hr_payroll/maintenance/user_account_migration.py
- Create: rayher_hr_payroll/tests/test_user_account_migration.py

**Interfaces:**
- Produces: build_username(employee_name, employee_id, used_names) -> lowercase @legacy.example.invalid username
- Produces: rename_generated_rd_users(dry_run=True) -> mapping/count summary without passwords

- [ ] **Step 1: Write failing pure-function tests**

Cover 演示员工132 -> person070@legacy.example.invalid, non-Chinese characters, duplicate pinyin suffix with Employee ID last four digits, collision with an existing User, and only generated hr-emp-*@legacy.example.invalid targets.

- [ ] **Step 2: Run focused tests and verify RED**

- [ ] **Step 3: Add pypinyin and implement dry-run planning**

Add pypinyin>=0.50,<1 to pyproject dependencies. Normalize lazy_pinyin output to lowercase ASCII letters/digits, then apply deterministic suffixes.

- [ ] **Step 4: Implement transactional rename**

For every planned row call frappe.rename_doc("User", old_user, new_user, force=True, show_alert=False). Verify after each rename that Employee.user_id changed and that no Project.project_owner still contains old_user. Do not reset passwords in this module.

- [ ] **Step 5: Run focused tests and verify GREEN**

### Task 6: Full Verification, Backup, Data Migration, And Workbook

**Files:**
- Regenerate: D:/rayher/交付文件/Rayher在职研发员工账号密码_2026-07-17.xlsx
- Build output: rayher_hr_payroll/public/frontend/**

**Interfaces:**
- Consumes: tested code from Tasks 1-5 and the existing account workbook
- Produces: deployed site, renamed accounts, verified project links, updated workbook

- [ ] **Step 1: Run all tests before deployment**

Frontend:
    node --test tests/*.test.js
Backend:
    ../../env/bin/python -m pytest rayher_hr_payroll/tests -q
Build:
    yarn build

Record any unrelated pre-existing failure separately; do not hide it.

- [ ] **Step 2: Create an official full backup**

Run:
    bench --site rayher.localhost backup --with-files --compress

Record the database, public files, private files, and config backup names.

- [ ] **Step 3: Deploy code and migrate required schema/dependencies**

Sync trusted plaintext files into the running app, install app requirements, run bench --site rayher.localhost migrate, rebuild assets, and restart the bench container/processes.

- [ ] **Step 4: Execute account rename dry run and validate**

Confirm exactly the generated active R&D account set is planned, person070@legacy.example.invalid is collision-free, and no existing unrelated User is targeted.

- [ ] **Step 5: Execute rename and verify references**

Check:
- active Employee.user_id values use pinyin usernames;
- no targeted hr-emp-*@legacy.example.invalid User remains;
- Project.project_owner values point to current Users;
- Zhang Jun retains Employee, Project Owner, and All Project Access;
- 18 linked projects remain linked and the unmatched RD10 behavior is unchanged;
- all 33 Project File records and physical files remain intact.

- [ ] **Step 6: Regenerate and verify the workbook**

Use the spreadsheet skill and @oai/artifact-tool to read the current workbook without printing passwords, replace usernames by Employee ID mapping, preserve temporary passwords, authenticate every renamed username/password pair, render a password-masked copy for visual QA, import/inspect the final workbook, and verify its first bytes are PK rather than a TipRay TSD marker.

- [ ] **Step 7: Perform role-based runtime checks**

Verify:
- Rayher Admin downloads all available reports;
- a normal owner downloads an own-project report and receives denial for another project;
- Zhang Jun lists all 19 projects, downloads reports, and opens /foreign-rd;
- an Employee cannot access /projects or a report URL;
- 请假/调休 with 0 saves and appears without affecting allocation totals;
- a normal activity with 0 is rejected;
- password change succeeds with the correct old password and rejects the wrong old password.

- [ ] **Step 8: Final integrity checks**

Run health/port checks, compare host/runtime hashes for changed source files, run gzip/tar checks on the fresh backup, and report any content that could not be verified.