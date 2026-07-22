# Unified Monthly Timesheet View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show historical daily and new monthly R&D timesheets in one month-based view, restore the all-employees option, and eliminate the “daily data exists but table is empty” state.

**Architecture:** Normalize both storage forms into the same monthly row contract on the server. The query derives YYYY-MM from legacy daily dates, groups by employee and project, and merges those rows with generated monthly entries without rewriting source data. The Vue page treats blank employee as the authorized all-employees view and enables editing only for an explicitly selected employee backed by editable monthly rows.

**Tech Stack:** Frappe Python APIs, MariaDB SQL, Vue 3, frappe-ui, Node built-in test runner, pytest.

## Global Constraints

- Historical daily Timesheet and Timesheet Detail documents are never deleted or converted by the display path.
- Monthly display groups by month, employee, and project.
- Legacy occurrence days equal monthly project hours divided by 8 and are rounded to two decimals.
- Original hours remain the authoritative total and must not be double-counted.
- The yellow “daily data exists” empty-state must not appear.
- The empty message appears only when no visible daily or monthly rows exist.
- All-employees results obey existing System/HR/Finance/Department Manager/Employee visibility rules.
- Blank employee is read-only and can never be sent to the save endpoint.
- Work remains on feat/ocr-monthly-timesheet-integration; do not merge to main or push a remote.
- Project text files must be verified as plaintext because TipRay transparent encryption is active.

---

### Task 1: Legacy daily rows normalized to the monthly contract

**Files:**
- Modify: `rayher_hr_payroll/api/monthly_timesheet_entry.py`
- Test: `rayher_hr_payroll/tests/test_monthly_timesheet_entry.py`

**Interfaces:**
- Produces: `_query_legacy_monthly_entries(period: str, employee: str | None = None) -> list`.
- Produces: `_merge_monthly_entry_rows(monthly_rows: list, legacy_rows: list) -> list[dict]`.
- Consumes: existing `timesheet_entry._summary_employee_filter` visibility boundary.

- [ ] **Step 1: Add failing legacy aggregation tests**

Stub SQL rows for June daily entries across two employees and projects. Assert the normalized output includes employee, employee_name, project, project_code, project_name, occurrence_days, hours, remark, and `source_kind="legacy_daily"`.

```python
rows = mod._merge_monthly_entry_rows([], [
    {"employee": "HR-EMP-90014", "employee_name": "演示员工112", "project": "P-1",
     "project_code": "RD01", "project_name": "项目甲", "hours": 12.0,
     "occurrence_days": 1.5, "remark": "需求；开发", "source_kind": "legacy_daily"},
])
assert rows[0]["period"] == "2026-06"
assert rows[0]["occurrence_days"] == 1.5
assert rows[0]["hours"] == 12.0
```

Also assert system-generated monthly rows are excluded from the legacy SQL and that current permission filters are present.

- [ ] **Step 2: Run the monthly test file and verify failure**

```powershell
python -m pytest rayher_hr_payroll/tests/test_monthly_timesheet_entry.py -q
```

Expected: missing helpers or missing legacy rows.

- [ ] **Step 3: Implement the legacy query**

Query submitted non-system-generated Timesheet Detail rows where year/month match the selected period, project allows R&D timesheet, and employee type is eligible. Group by employee and project; calculate `sum(tsd.hours)`, `round(sum(tsd.hours)/8, 2)`, and a deterministic distinct remark summary.

- [ ] **Step 4: Implement merge without duplicate counting**

Normalize both sources to the same fields. Use source Timesheet identity sets so generated monthly details cannot re-enter the legacy result. Sort by employee name, project code, and project name.

- [ ] **Step 5: Re-run tests and commit**

```powershell
git add rayher_hr_payroll/api/monthly_timesheet_entry.py rayher_hr_payroll/tests/test_monthly_timesheet_entry.py
git commit -m "feat: normalize legacy timesheets by month"
```

### Task 2: Monthly endpoint returns unified totals and truthful empty state

**Files:**
- Modify: `rayher_hr_payroll/api/monthly_timesheet_entry.py`
- Test: `rayher_hr_payroll/tests/test_monthly_timesheet_entry.py`
- Test: `rayher_hr_payroll/tests/test_timesheet_entry.py`

**Interfaces:**
- Consumes: Task 1 helpers.
- Produces: `list_monthly_entries(period, employee=None)` with `entries`, `total_days`, `total_hours`, `employee_count`, and `has_legacy_sources`.

- [ ] **Step 1: Add failing endpoint tests**

Cover June with legacy-only rows, July with monthly-only rows, all-employees mode, employee filter, no-row month, and unauthorized employee rejection.

```python
result = mod.list_monthly_entries("2026-06", employee="HR-EMP-90014")
assert result["entries"][0]["project_name"] == "项目甲"
assert result["total_days"] == 1.5
assert result["total_hours"] == 12.0
assert result["employee_count"] == 1
assert result["has_legacy_sources"] is True
```

- [ ] **Step 2: Run tests and verify the legacy-only case fails with an empty list**

- [ ] **Step 3: Call both queries and return unified totals**

Do not use `legacy_daily_present` to suppress entries. Keep it only as compatibility metadata if another caller still consumes it. Compute employee count from distinct returned employees.

- [ ] **Step 4: Re-run both backend files**

Expected: PASS and current visibility tests remain unchanged.

- [ ] **Step 5: Commit**

```powershell
git add rayher_hr_payroll/api/monthly_timesheet_entry.py rayher_hr_payroll/tests/test_monthly_timesheet_entry.py rayher_hr_payroll/tests/test_timesheet_entry.py
git commit -m "fix: return historical hours in monthly endpoint"
```

### Task 3: Restore all-employees mode and render unified rows

**Files:**
- Modify: `frontend/src/pages/TimesheetEntry.vue`
- Test: `frontend/tests/timesheet-entry-source.test.js`

**Interfaces:**
- Consumes: Task 2 endpoint contract.
- Produces: `selectedEmployee=""` all-employees mode and an employee column.

- [ ] **Step 1: Add failing source-contract tests**

Assert:

```javascript
assert.match(source, /<option value="">全部员工<\/option>/)
assert.match(source, /employee_name/)
assert.doesNotMatch(source, /该员工本月已有按日工时/)
assert.match(source, /employee_count/)
assert.match(source, /isAllEmployees/)
```

Also assert add/save/import/delete controls are hidden or disabled when `isAllEmployees` is true.

- [ ] **Step 2: Run the test and verify failure**

```powershell
cd frontend
node --test tests/timesheet-entry-source.test.js
cd ..
```

- [ ] **Step 3: Remove the empty-employee early return**

Always call `list_monthly_entries`; pass an empty employee for all-employees mode. When multiple employees are visible, default selection to empty rather than the first employee.

- [ ] **Step 4: Render the all-employees summary**

Add KPI values for employee count, total occurrence days, and total hours. Add 研发人员 as the first table column only in all mode. Render source rows exactly like monthly rows and remove the yellow blocking banner.

- [ ] **Step 5: Preserve safe editing**

Set `canEditSelection = canEdit && selectedEmployee && !monthly.data?.has_legacy_sources`. Use it for add/save/import/delete. Do not show an empty table when legacy rows exist; legacy rows remain visible with no destructive controls.

- [ ] **Step 6: Run test and build**

Expected: source test PASS and Vite build succeeds.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/pages/TimesheetEntry.vue frontend/tests/timesheet-entry-source.test.js
git commit -m "feat: restore all-employee monthly timesheets"
```

### Task 4: Import/export compatibility

**Files:**
- Modify: `frontend/src/pages/TimesheetEntry.vue`
- Modify: `frontend/src/lib/timesheetImport.js`
- Test: `frontend/tests/timesheet-import.test.js`
- Test: `frontend/tests/timesheet-entry-source.test.js`

**Interfaces:**
- Consumes: explicit employee selection for mutations.
- Produces: all-employee export with an employee column and single-employee import guards.

- [ ] **Step 1: Add failing tests**

Assert all-employee export includes every unified row and employee name. Assert paste/Excel import is rejected before parsing when no single employee is selected.

- [ ] **Step 2: Implement export source selection**

Export `monthly.data.entries` in all mode and the editable local `entries` in single-employee mode. Include 研发人员, 项目代码, 项目名称, 发生天数, 工时, and 备注.

- [ ] **Step 3: Keep import single-employee only**

Hide the import area in all mode and retain existing employee equality checks for selected-employee imports.

- [ ] **Step 4: Run tests and commit**

```powershell
cd frontend
node --test tests/timesheet-import.test.js tests/timesheet-entry-source.test.js
cd ..
git add frontend/src/pages/TimesheetEntry.vue frontend/src/lib/timesheetImport.js frontend/tests/timesheet-import.test.js frontend/tests/timesheet-entry-source.test.js
git commit -m "feat: export unified monthly timesheets"
```

### Task 5: Full verification and live June acceptance

**Files:**
- Generated: `rayher_hr_payroll/public/frontend/**`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: deployed, verified monthly view.

- [ ] **Step 1: Run focused backend files in separate processes**

```powershell
python -m pytest rayher_hr_payroll/tests/test_monthly_timesheet_entry.py -q
python -m pytest rayher_hr_payroll/tests/test_timesheet_entry.py -q
```

Expected: PASS.

- [ ] **Step 2: Run all frontend tests and build**

```powershell
cd frontend
node --test tests/*.test.js
npm run build
cd ..
```

Expected: all PASS and build succeeds.

- [ ] **Step 3: Verify text files are plaintext and Git diff is clean**

Check changed files for `%TSD-Header-`, run `git diff --check`, and review `git status --short`.

- [ ] **Step 4: Back up the live application and database**

Record the backup path and current Timesheet counts before deployment.

- [ ] **Step 5: Deploy backend and frontend, migrate if needed, clear cache, and restart**

Wait until `rayher-bench` and affected services are healthy.

- [ ] **Step 6: Verify the exact screenshot regression**

Open 2026 年 6 月 for 演示员工112 / HR-EMP-90014. Expected: no yellow blocking banner, non-empty project rows, correct monthly days/hours, and non-zero top totals.

- [ ] **Step 7: Verify all-employees and permission boundaries**

Admin/HR sees 全部员工; Department Manager sees only allowed staff; Employee sees only self. An actually empty month still displays 本月暂无工时记录.

- [ ] **Step 8: Verify no source mutation**

Compare pre/post Timesheet and Timesheet Detail counts and identities; deployment and viewing must not delete or convert historical daily records.

- [ ] **Step 9: Commit generated frontend assets**

```powershell
git add rayher_hr_payroll/public/frontend
git commit -m "build: publish unified monthly timesheet view"
```
