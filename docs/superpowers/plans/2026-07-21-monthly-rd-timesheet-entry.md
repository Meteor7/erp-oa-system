# Monthly R&D Timesheet Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace daily employee time entry with team-leader monthly project/day entry while preserving ERPNext Timesheet-backed allocation and locking.

**Architecture:** A monthly entry is one submitted ERPNext Timesheet parent carrying immutable monthly metadata and one or more generated Timesheet Detail rows of at most eight hours each. A dedicated monthly API owns grouped CRUD and atomic table replacement, while the existing raw detail API remains available to pivot/allocation consumers.

**Tech Stack:** Python 3.10+, Frappe/ERPNext Timesheet, MariaDB, Vue 3, frappe-ui, Node test runner, pytest.

## Global Constraints

- Occurrence days use exact decimal arithmetic, accept at most two decimal places, and convert at exactly 8 hours per day.
- Technical dates stay inside the selected month, are system-generated, and are never shown as real work dates.
- The employee/month total cannot exceed the selected month’s calendar-day count.
- Daily and monthly entry modes cannot coexist for the same employee and month.
- Monthly mutation is atomic and period/allocation locks remain authoritative.
- Cost allocation continues reading submitted Timesheet Detail hours; no parallel monthly cost source is introduced.
- Employees and finance users are view-only; team leaders and HR/admin roles write only within existing employee scope.

---

### Task 1: Add Monthly Timesheet Metadata

**Files:**
- Modify: `rayher_hr_payroll/custom_fields.py` (`CUSTOM_FIELDS["Timesheet"]`)
- Modify: `rayher_hr_payroll/tests/test_custom_fields.py` (`test_timesheet_review_fields_exist` and new metadata test)

**Interfaces:**
- Produces Timesheet fields `rd_monthly_entry_id`, `rd_entry_period`, `rd_occurrence_days`, `rd_calculated_hours`, and `rd_system_generated`.
- Existing `after_migrate` custom-field synchronization consumes the new definitions without a separate schema patch.

- [ ] **Step 1: Write the failing custom-field test**

```python
def test_timesheet_monthly_entry_fields_exist():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Timesheet"]}
    assert fields["rd_monthly_entry_id"]["fieldtype"] == "Data"
    assert fields["rd_monthly_entry_id"]["unique"] == 1
    assert fields["rd_entry_period"]["fieldtype"] == "Data"
    assert fields["rd_occurrence_days"]["fieldtype"] == "Float"
    assert fields["rd_occurrence_days"]["precision"] == 2
    assert fields["rd_calculated_hours"]["precision"] == 2
    assert fields["rd_system_generated"]["fieldtype"] == "Check"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_custom_fields.py::test_timesheet_monthly_entry_fields_exist -q`
Expected: FAIL because `rd_monthly_entry_id` is absent.

- [ ] **Step 3: Add the five hidden/read-only fields**

Add the field definitions after `rd_spa_managed`, with precision 2 for days/hours and `unique: 1` for the monthly ID.

- [ ] **Step 4: Run the custom-field suite and verify GREEN**

Run: `python -m pytest rayher_hr_payroll/tests/test_custom_fields.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rayher_hr_payroll/custom_fields.py rayher_hr_payroll/tests/test_custom_fields.py
git commit -m "feat: add monthly timesheet metadata"
```

### Task 2: Implement Exact Monthly Domain Rules

**Files:**
- Create: `rayher_hr_payroll/api/monthly_timesheet_entry.py`
- Create: `rayher_hr_payroll/tests/test_monthly_timesheet_entry.py`

**Interfaces:**
- Produces `parse_occurrence_days(value, year, month) -> Decimal`.
- Produces `calculated_hours(days) -> Decimal`.
- Produces `split_day_hours(days) -> list[Decimal]`.
- Later persistence functions consume these pure helpers.

- [ ] **Step 1: Write failing tests for precision and splitting**

```python
def test_two_decimal_days_split_into_full_and_partial_hours():
    days = mod.parse_occurrence_days("2.35", 2026, 7)
    assert days == Decimal("2.35")
    assert mod.calculated_hours(days) == Decimal("18.80")
    assert mod.split_day_hours(days) == [Decimal("8.00"), Decimal("8.00"), Decimal("2.80")]

@pytest.mark.parametrize("value", ["0", "-1", "1.001", "abc"])
def test_invalid_days_are_rejected(value, fake_frappe):
    with pytest.raises(FakeThrow):
        mod.parse_occurrence_days(value, 2026, 7)

def test_days_cannot_exceed_calendar_month(fake_frappe):
    with pytest.raises(FakeThrow):
        mod.parse_occurrence_days("29.01", 2026, 2)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_monthly_timesheet_entry.py -q`
Expected: collection/import failure because the module does not exist.

- [ ] **Step 3: Implement the pure Decimal helpers**

Use `Decimal`, `InvalidOperation`, `ROUND_HALF_UP`, and `calendar.monthrange`. Reject more than two input decimal places before quantizing.

- [ ] **Step 4: Run the domain tests and verify GREEN**

Run: `python -m pytest rayher_hr_payroll/tests/test_monthly_timesheet_entry.py -q`
Expected: PASS for the pure helper tests.

- [ ] **Step 5: Commit**

```bash
git add rayher_hr_payroll/api/monthly_timesheet_entry.py rayher_hr_payroll/tests/test_monthly_timesheet_entry.py
git commit -m "feat: define monthly timesheet day rules"
```

### Task 3: Add Atomic Monthly Persistence and Grouped Read API

**Files:**
- Modify: `rayher_hr_payroll/api/monthly_timesheet_entry.py`
- Modify: `rayher_hr_payroll/tests/test_monthly_timesheet_entry.py`
- Modify: `rayher_hr_payroll/api/timesheet_entry.py` (`RD_TIMESHEET_ENTRY_ROLES`, `_save_rd_hours_row`)
- Modify: `rayher_hr_payroll/tests/test_timesheet_entry.py`

**Interfaces:**
- Produces whitelisted `get_monthly_options()` or reuses `get_rd_options()` for scoped employees/projects.
- Produces whitelisted `list_monthly_entries(period, employee=None) -> dict` with `entries`, `total_days`, `total_hours`, `day_limit`, and `legacy_daily_present`.
- Produces whitelisted `save_monthly_entries(period, employee, rows) -> dict` that atomically replaces the selected employee/month table.
- Produces whitelisted `delete_monthly_entry(monthly_entry_id) -> dict`.

- [ ] **Step 1: Write failing tests for one grouped parent and exact child rows**

```python
def test_save_four_days_creates_one_parent_with_four_details(fake_frappe):
    result = mod.save_monthly_entries("2026-07", "EMP-1", [{
        "project": "PROJ-1", "project_code": "RD14",
        "project_name": "ACONCA 7961", "occurrence_days": "4.00",
        "remark": "monthly work",
    }])
    assert len(fake_frappe.inserted_timesheets) == 1
    doc = fake_frappe.inserted_timesheets[0]
    assert doc.rd_occurrence_days == 4
    assert [row["hours"] for row in doc.time_logs] == [8, 8, 8, 8]
    assert result["total_days"] == 4
    assert result["total_hours"] == 32
```

- [ ] **Step 2: Run the persistence test and verify RED**

Expected: FAIL because `save_monthly_entries` is absent.

- [ ] **Step 3: Implement validation, locking, technical-slot allocation, and parent creation**

The bulk endpoint must parse every row before mutation, resolve real Project identity, detect duplicate projects, acquire the period/import and Employee locks, reject daily-mode rows, cancel/delete existing monthly parents, rebuild parents with preserved IDs when supplied, submit every parent, and commit once.

- [ ] **Step 4: Write and run failing tests for grouped listing, fractional rows, edit, delete, rollback, duplicate projects, monthly capacity, locks, and daily/monthly mixing**

Each test asserts a single invariant, including `2.35 -> [8, 8, 2.8]`, replacement leaving no old parent, rollback restoring old state, and technical dates remaining inside the month.

- [ ] **Step 5: Implement grouped read/delete and make all new backend tests GREEN**

`list_monthly_entries` selects one row per parent and never returns child `from_time`. `delete_monthly_entry` resolves only a system-generated monthly parent and runs lock checks before cancel/delete.

- [ ] **Step 6: Add a failing regression test that daily save is rejected when monthly data exists**

```python
def test_daily_save_rejects_employee_month_with_monthly_entries(monkeypatch):
    monkeypatch.setattr(mod, "_month_has_monthly_entries", lambda *args: True)
    with pytest.raises(FakeThrow):
        mod._save_rd_hours_row(period="2026-07", employee="EMP-1", work_date="2026-07-01", project="PROJ-1", hours=8)
```

- [ ] **Step 7: Implement the daily-side guard and manager-only write roles**

Remove Employee and Accounts User from the write tuple, retain them in the view tuple, and reject daily writes when a generated monthly parent exists.

- [ ] **Step 8: Run focused backend suites**

Run: `python -m pytest rayher_hr_payroll/tests/test_monthly_timesheet_entry.py rayher_hr_payroll/tests/test_timesheet_entry.py rayher_hr_payroll/tests/test_timesheet_controls.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add rayher_hr_payroll/api/monthly_timesheet_entry.py rayher_hr_payroll/api/timesheet_entry.py rayher_hr_payroll/tests/test_monthly_timesheet_entry.py rayher_hr_payroll/tests/test_timesheet_entry.py
git commit -m "feat: persist monthly R&D timesheets atomically"
```

### Task 4: Convert Import Parsing to Monthly Days

**Files:**
- Modify: `frontend/src/lib/timesheetImport.js`
- Modify: `frontend/tests/timesheet-import.test.js`

**Interfaces:**
- Produces `parseTimesheetPaste(text, options)` rows containing employee, resolved project identity, `occurrence_days`, calculated `hours`, and remark.
- Produces `importTimesheetWorkbookFile(file, options)` with the same normalized shape.

- [ ] **Step 1: Replace daily test fixtures with failing monthly fixtures**

```javascript
test('parses two-decimal monthly occurrence days and calculates hours', () => {
  const result = parseTimesheetRows([
    ['演示员工132', 'RD14', 'ACONCA 7961', '2.35', 'monthly work'],
  ], options());
  assert.equal(result.rows[0].occurrence_days, 2.35);
  assert.equal(result.rows[0].hours, 18.8);
});
```

Add failures for `1.001`, duplicate employee/project, and employee total above the month calendar-day limit.

- [ ] **Step 2: Run and verify RED**

Run the Node test command for `frontend/tests/timesheet-import.test.js`; expected assertions fail against daily columns.

- [ ] **Step 3: Implement monthly headers and exact two-decimal validation**

Accepted headers are employee, project code, project name, occurrence days, and remark. The selected accounting period supplies the month; activity and date columns are removed.

- [ ] **Step 4: Run and verify GREEN**

Run the same Node test; expected PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/timesheetImport.js frontend/tests/timesheet-import.test.js
git commit -m "feat: import monthly R&D occurrence days"
```

### Task 5: Rebuild the Entry Page Around Monthly Rows

**Files:**
- Modify: `frontend/src/pages/TimesheetEntry.vue`
- Modify: `frontend/src/lib/access.js`
- Modify: `frontend/tests/timesheet-entry-source.test.js`
- Modify: `frontend/tests/access.test.js`

**Interfaces:**
- Consumes monthly list/save/delete endpoints from Task 3.
- Consumes monthly import rows from Task 4.
- Produces the screenshot-style employee/year/month/project/days/hours/remark workflow.

- [ ] **Step 1: Write failing source tests for the monthly UI**

Assert that the page calls `list_monthly_entries` and `save_monthly_entries`, contains `occurrence_days`, uses input step `0.01`, calculates `occurrence_days * 8`, contains no `type="date"`, does not display activity type, and never renders `from_time` or technical dates.

- [ ] **Step 2: Write a failing access test**

Assert `canEditTimesheetEntry()` allows System Manager/HR/Department Manager and rejects Employee/Accounts User while route visibility still includes them.

- [ ] **Step 3: Run the focused frontend tests and verify RED**

Expected: FAIL on the old daily page and old edit-role tuple.

- [ ] **Step 4: Implement the monthly page**

Use separate year and month controls synchronized to the shared `period`. Load one selected employee’s monthly table, keep project rows editable, display days/hours with two decimals, show `当月合计 / 上限`, allow add/delete, and submit the full table atomically. Preserve compact Excel import/export using monthly columns.

- [ ] **Step 5: Implement the frontend write-role change**

Split entry view roles from write roles; keep Employee and Accounts User able to open and view scoped data.

- [ ] **Step 6: Run focused frontend tests and verify GREEN**

Run monthly entry/import/access tests; expected PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/TimesheetEntry.vue frontend/src/lib/access.js frontend/tests/timesheet-entry-source.test.js frontend/tests/timesheet-import.test.js frontend/tests/access*.test.js
git commit -m "feat: add team-leader monthly timesheet UI"
```

### Task 6: Verify Reports, Allocation Compatibility, and Production Build

**Files:**
- Test: `rayher_hr_payroll/tests/test_frappe_adapter.py`
- Test: `rayher_hr_payroll/tests/test_reports.py`
- Test: `frontend/tests/timesheet-entry-source.test.js`
- Generated by build: `rayher_hr_payroll/public/frontend/**`

**Interfaces:**
- Existing allocation adapter must consume generated details exactly like daily details.
- Business entry/export and exception summaries must not expose technical dates as real dates.

- [ ] **Step 1: Add a failing allocation compatibility test**

Create generated detail fixtures totaling 18.80 hours and assert project-hour rows and allocation ratios use 18.80 exactly and the selected month only.

- [ ] **Step 2: Run and verify RED or confirm existing behavior**

If the test passes immediately because the adapter already sums hours by month, retain it as a regression characterization test and do not modify production allocation code.

- [ ] **Step 3: Add report/source assertions that technical dates are not displayed by the entry page/export**

Keep monthly missing-timesheet and dashboard totals based on hours; do not convert generated dates into daily attendance evidence.

- [ ] **Step 4: Run the complete backend suite**

Run: `python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 5: Run the complete frontend suite**

Run all `frontend/tests/*.test.js` with the bundled Node executable.
Expected: all tests PASS.

- [ ] **Step 6: Build the frontend**

Run Vite production build from `frontend`.
Expected: build succeeds and outputs updated assets under `rayher_hr_payroll/public/frontend`.

- [ ] **Step 7: Verify plaintext and Git diff**

Check every generated/edited text file begins with its expected plaintext header and not the TipRay `TSD Header` marker. Run `git diff --check` and review `git diff --stat`.

- [ ] **Step 8: Commit the verified build**

```bash
git add frontend rayher_hr_payroll
git commit -m "build: publish monthly timesheet frontend"
```

- [ ] **Step 9: Run final smoke verification**

Re-run the focused monthly backend tests, complete frontend tests, and build command from the committed tree; record exact pass counts before reporting completion.
