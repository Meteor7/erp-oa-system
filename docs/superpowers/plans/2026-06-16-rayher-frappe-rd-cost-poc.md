# Rayher Frappe RD Cost PoC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Frappe/ERPNext/Frappe HR proof of concept that proves Rayher's HR-backed R&D timesheet and R&D expense allocation flow can run end to end without moving payroll into this system.

**Architecture:** Use ERPNext/Frappe HR standard Employee, Project, Timesheet, Leave, Expense Claim, Workflow, Notification, and Assignment objects wherever possible. Add a custom app named `rayher_hr_payroll` for Rayher-specific fields, R&D expense import, allocation calculation, source-data snapshots, period locking, project-owner review routing, and compliance reports. Put allocation math in pure Python first so denominator and capitalized/expensed subtotal behavior is tested before connecting Frappe documents. Treat submitted allocation documents as immutable versions: they must read from Timesheet/GL/project-stage snapshots, not live reports.

**Tech Stack:** Frappe Framework v15, ERPNext v15, HRMS v15, Python 3.10+, MariaDB, Redis, Node/Yarn, pytest, Frappe bench, WSL on Windows.

---

## Scope

This PoC proves this chain:

```text
Employee / Project / Timesheet
-> RD Expense Import
-> RD Cost Allocation
-> capitalized / expensed subtotals
-> allocation matrix report
-> missing-timesheet and period-lock controls
```

This PoC does not implement payroll calculation, salary slips, bank payment files, tax filing, social insurance calculation, CRM, or full ERP rollout.

## Runtime Layout

Use this repository as the custom app repository:

```text
E:\Rayher\Logistics
/mnt/e/Rayher/Logistics
```

Run Frappe bench from WSL outside the repo:

```text
~/frappe-bench
```

Custom app files will be created in this repo:

```text
pyproject.toml
MANIFEST.in
rayher_hr_payroll/
  __init__.py
  hooks.py
  modules.txt
  patches.txt
  custom_fields.py
  install.py
  rd_cost/
    __init__.py
    types.py
    allocation.py
    frappe_adapter.py
  doctype/
    rd_expense_import/
    rd_expense_item/
    rd_cost_allocation/
    rd_cost_allocation_line/
    rd_period_lock/
    rd_work_ratio_snapshot/
    accommodation_deduction/
  report/
    rd_allocation_matrix/
    rd_timesheet_exceptions/
  tests/
    test_allocation.py
    test_custom_fields.py
    test_frappe_adapter.py
```

## Data Model Summary

Use code names without ampersands for Frappe DocTypes. UI labels can show `R&D` or Chinese labels.

| Object | Purpose |
|---|---|
| `RD Expense Import` | Monthly GL import batch from finance system, including source file hash. |
| `RD Expense Item` | One GL row: period, voucher, account levels, category, amount, optional direct project, and `source_row_key` for duplicate prevention. |
| `RD Cost Allocation` | One immutable calculation version for a period and scope. |
| `RD Cost Allocation Line` | One allocated amount for one expense item and one project. |
| `RD Allocation Source Hour` | Snapshot of each Timesheet Detail row used in an allocation, including historical department/designation. |
| `RD Allocation Source Expense` | Snapshot of each GL row used in an allocation, including `source_row_key`. |
| `RD Period Lock` | Custom R&D closing period; locks timesheets, GL imports, project stages, and allocation versions. |
| `RD Work Ratio Snapshot` | Monthly personal R&D ratio snapshot using submitted Timesheet hours only. |
| `Rayher HR Settings` | Company-level constants such as `standard_daily_hours`. |
| `Accommodation Deduction` | Dorm/rent/water/electric registration for finance export. |

---

### Task 1: Scaffold Custom App And Pure Allocation Engine

**Files:**
- Create: `pyproject.toml`
- Create: `MANIFEST.in`
- Create: `rayher_hr_payroll/__init__.py`
- Create: `rayher_hr_payroll/hooks.py`
- Create: `rayher_hr_payroll/modules.txt`
- Create: `rayher_hr_payroll/patches.txt`
- Create: `rayher_hr_payroll/rd_cost/__init__.py`
- Create: `rayher_hr_payroll/rd_cost/types.py`
- Create: `rayher_hr_payroll/rd_cost/allocation.py`
- Create: `rayher_hr_payroll/tests/test_allocation.py`

- [ ] **Step 1: Write failing allocation tests**

Create `rayher_hr_payroll/tests/test_allocation.py`:

```python
from decimal import Decimal

import pytest

from rayher_hr_payroll.rd_cost.allocation import allocate_expenses
from rayher_hr_payroll.rd_cost.types import ExpenseItem, ProjectHour


def test_capitalized_filter_does_not_recalculate_denominator():
    expenses = [ExpenseItem(name="GL-POWER-001", amount=Decimal("1200.00"), account_level_3="??", category="direct_input")]
    hours = [
        ProjectHour(project="RD-CAP", hours=Decimal("60"), stage="capitalized"),
        ProjectHour(project="RD-EXP", hours=Decimal("40"), stage="expensed"),
    ]
    result = allocate_expenses(expenses=expenses, project_hours=hours)
    assert result.project_amounts == {"RD-CAP": Decimal("720.00"), "RD-EXP": Decimal("480.00")}
    assert result.stage_totals == {"capitalized": Decimal("720.00"), "expensed": Decimal("480.00"), "unknown": Decimal("0.00")}


def test_direct_project_expense_bypasses_hour_ratio():
    expenses = [ExpenseItem(name="GL-TEST-001", amount=Decimal("500.00"), account_level_3="???????", category="direct_input", direct_project="RD-EXP")]
    hours = [
        ProjectHour(project="RD-CAP", hours=Decimal("99"), stage="capitalized"),
        ProjectHour(project="RD-EXP", hours=Decimal("1"), stage="expensed"),
    ]
    result = allocate_expenses(expenses=expenses, project_hours=hours)
    assert result.project_amounts == {"RD-CAP": Decimal("0.00"), "RD-EXP": Decimal("500.00")}
    assert result.stage_totals["expensed"] == Decimal("500.00")


def test_zero_hours_without_direct_project_is_rejected():
    expenses = [ExpenseItem(name="GL-POWER-001", amount=Decimal("1200.00"), account_level_3="??", category="direct_input")]
    with pytest.raises(ValueError, match="project_hours total must be greater than zero"):
        allocate_expenses(expenses=expenses, project_hours=[])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest rayher_hr_payroll/tests/test_allocation.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `rayher_hr_payroll.rd_cost.allocation`.
﻿
- [ ] **Step 3: Create package metadata**

Create `pyproject.toml`:

```toml
[project]
name = "rayher_hr_payroll"
version = "0.1.0"
description = "Rayher HR, R&D timesheet, and R&D cost allocation custom Frappe app"
requires-python = ">=3.10"
dependencies = []

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["rayher_hr_payroll/tests"]
```

Create `MANIFEST.in`:

```text
include rayher_hr_payroll/modules.txt
include rayher_hr_payroll/patches.txt
recursive-include rayher_hr_payroll *.json *.js *.py *.html *.css
```

Create `rayher_hr_payroll/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `rayher_hr_payroll/hooks.py`:

```python
app_name = "rayher_hr_payroll"
app_title = "Rayher HR Payroll"
app_publisher = "Rayher"
app_description = "Rayher HR, R&D timesheet, and R&D cost allocation customizations"
app_email = "admin@example.com"
app_license = "MIT"

required_apps = ["erpnext", "hrms"]
after_install = "rayher_hr_payroll.install.after_install"

doc_events = {
    "Timesheet": {
        "validate": "rayher_hr_payroll.timesheet_controls.validate_timesheet",
        "before_submit": "rayher_hr_payroll.timesheet_controls.validate_timesheet",
        "on_submit": "rayher_hr_payroll.timesheet_controls.on_submit_timesheet",
        "before_cancel": "rayher_hr_payroll.timesheet_controls.block_locked_timesheet_change",
        "on_trash": "rayher_hr_payroll.timesheet_controls.block_locked_timesheet_change",
    },
    "Compensatory Leave Request": {
        "validate": "rayher_hr_payroll.leave_controls.validate_compensatory_leave_request",
    },
}
```

Create `rayher_hr_payroll/modules.txt`:

```text
Rayher HR Payroll
```

Create `rayher_hr_payroll/patches.txt` and `rayher_hr_payroll/rd_cost/__init__.py` as empty files.

- [ ] **Step 4: Implement allocation types**

Create `rayher_hr_payroll/rd_cost/types.py`:

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ProjectStage = Literal["capitalized", "expensed", "unknown"]


@dataclass(frozen=True)
class ExpenseItem:
    name: str
    amount: Decimal
    account_level_3: str
    category: str
    direct_project: str | None = None


@dataclass(frozen=True)
class ProjectHour:
    project: str
    hours: Decimal
    stage: ProjectStage


@dataclass(frozen=True)
class AllocationLine:
    expense_item: str
    project: str
    stage: ProjectStage
    amount: Decimal
    basis_hours: Decimal
    ratio: Decimal


@dataclass(frozen=True)
class AllocationResult:
    lines: list[AllocationLine]
    project_amounts: dict[str, Decimal]
    stage_totals: dict[ProjectStage, Decimal]
```

- [ ] **Step 5: Implement allocation engine**

Create `rayher_hr_payroll/rd_cost/allocation.py`:

```python
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from rayher_hr_payroll.rd_cost.types import AllocationLine, AllocationResult, ExpenseItem, ProjectHour, ProjectStage

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _stage_by_project(project_hours: list[ProjectHour]) -> dict[str, ProjectStage]:
    return {row.project: row.stage for row in project_hours}


def _sum_hours(project_hours: list[ProjectHour]) -> Decimal:
    total = sum((row.hours for row in project_hours), Decimal("0"))
    if total <= 0:
        raise ValueError("project_hours total must be greater than zero")
    return total


def _weighted_amounts(amount: Decimal, project_hours: list[ProjectHour]) -> dict[str, Decimal]:
    total_hours = _sum_hours(project_hours)
    raw_rows = []
    rounded = {}
    for row in project_hours:
        raw = amount * row.hours / total_hours
        rounded_amount = _money(raw)
        raw_rows.append((row.project, raw, rounded_amount))
        rounded[row.project] = rounded_amount
    remainder = _money(amount - sum(rounded.values(), Decimal("0")))
    if remainder:
        project, _raw, _rounded = max(raw_rows, key=lambda item: (abs(item[1] - item[2]), item[0]))
        rounded[project] = _money(rounded[project] + remainder)
    return rounded


def allocate_expenses(*, expenses: list[ExpenseItem], project_hours: list[ProjectHour]) -> AllocationResult:
    stages = _stage_by_project(project_hours)
    lines = []
    project_amounts = defaultdict(lambda: ZERO)
    stage_totals = {"capitalized": ZERO, "expensed": ZERO, "unknown": ZERO}

    for expense in expenses:
        amount = _money(expense.amount)
        if expense.direct_project:
            allocations = {project: ZERO for project in stages}
            allocations[expense.direct_project] = amount
        else:
            allocations = _weighted_amounts(amount, project_hours)

        total_hours = sum((row.hours for row in project_hours), Decimal("0")) or Decimal("1")
        hours_by_project = {row.project: row.hours for row in project_hours}
        for project in sorted(allocations):
            allocated_amount = _money(allocations[project])
            stage = stages.get(project, "unknown")
            basis_hours = hours_by_project.get(project, Decimal("0"))
            ratio = (basis_hours / total_hours) if not expense.direct_project else Decimal("0")
            lines.append(AllocationLine(expense.name, project, stage, allocated_amount, basis_hours, ratio))
            project_amounts[project] = _money(project_amounts[project] + allocated_amount)
            stage_totals[stage] = _money(stage_totals[stage] + allocated_amount)

    return AllocationResult(lines=lines, project_amounts=dict(project_amounts), stage_totals=stage_totals)
```

- [ ] **Step 6: Run allocation tests**

Run:

```bash
python -m pytest rayher_hr_payroll/tests/test_allocation.py -q
```

Expected: `3 passed`.

- [ ] **Step 7: Commit**

Run:

```bash
git add pyproject.toml MANIFEST.in rayher_hr_payroll
git commit -m "feat: scaffold rayher app allocation engine"
```

Expected: commit succeeds.

---

### Task 2: Add Custom Field Definitions For Standard ERPNext/Frappe HR Objects

**Files:**
- Create: `rayher_hr_payroll/custom_fields.py`
- Create: `rayher_hr_payroll/install.py`
- Create: `rayher_hr_payroll/tests/test_custom_fields.py`
- Modify: `rayher_hr_payroll/hooks.py`

- [ ] **Step 1: Write custom field structure test**

Create `rayher_hr_payroll/tests/test_custom_fields.py`:

```python
from rayher_hr_payroll.custom_fields import CUSTOM_FIELDS


def test_employee_rd_personnel_type_exists():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Employee"]}
    assert fields["rd_personnel_type"]["fieldtype"] == "Select"
    assert "????" in fields["rd_personnel_type"]["options"]


def test_project_capitalization_fields_exist():
    fields = {field["fieldname"]: field for field in CUSTOM_FIELDS["Project"]}
    assert fields["allow_rd_timesheet"]["fieldtype"] == "Check"
    assert fields["capitalization_start_date"]["fieldtype"] == "Date"
    assert fields["capitalization_end_date"]["fieldtype"] == "Date"


def test_custom_fieldnames_are_unique_per_doctype():
    for doctype, fields in CUSTOM_FIELDS.items():
        names = [field["fieldname"] for field in fields]
        assert len(names) == len(set(names)), doctype
```
﻿
- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest rayher_hr_payroll/tests/test_custom_fields.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `rayher_hr_payroll.custom_fields`.

- [ ] **Step 3: Add field definitions**

Create `rayher_hr_payroll/custom_fields.py`:

```python
CUSTOM_FIELDS = {
    "Employee": [
        {"fieldname": "rd_section", "label": "????????", "fieldtype": "Section Break", "insert_after": "department"},
        {"fieldname": "rd_personnel_type", "label": "??????", "fieldtype": "Select", "options": "\n????\n?????\n???\n????", "insert_after": "rd_section"},
        {"fieldname": "archive_status", "label": "??????", "fieldtype": "Select", "options": "???\n???\n???", "default": "???", "insert_after": "rd_personnel_type"},
        {"fieldname": "id_card_number_cn", "label": "????", "fieldtype": "Data", "insert_after": "archive_status", "permlevel": 1},
        {"fieldname": "education_level_cn", "label": "??", "fieldtype": "Data", "insert_after": "id_card_number_cn"},
        {"fieldname": "graduation_school", "label": "????", "fieldtype": "Data", "insert_after": "education_level_cn"},
        {"fieldname": "major_cn", "label": "??", "fieldtype": "Data", "insert_after": "graduation_school"},
    ],
    "Project": [
        {"fieldname": "rd_project_section", "label": "??????", "fieldtype": "Section Break", "insert_after": "project_name"},
        {"fieldname": "rd_project_code", "label": "??????", "fieldtype": "Data", "insert_after": "rd_project_section"},
        {"fieldname": "allow_rd_timesheet", "label": "????????", "fieldtype": "Check", "default": 0, "insert_after": "rd_project_code"},
        {"fieldname": "rd_stage", "label": "????", "fieldtype": "Select", "options": "\n???\n???\n????", "insert_after": "allow_rd_timesheet"},
        {"fieldname": "capitalization_start_date", "label": "???????", "fieldtype": "Date", "insert_after": "rd_stage"},
        {"fieldname": "capitalization_end_date", "label": "???????", "fieldtype": "Date", "insert_after": "capitalization_start_date"},
        {"fieldname": "supervising_leader", "label": "????", "fieldtype": "Link", "options": "Employee", "insert_after": "capitalization_end_date"},
        {"fieldname": "ip_reference", "label": "?? IP / ?? / ??", "fieldtype": "Data", "insert_after": "supervising_leader"},
    ],
    "Timesheet": [
        {"fieldname": "rd_review_section", "label": "??????", "fieldtype": "Section Break", "insert_after": "total_hours"},
        {"fieldname": "rd_review_status", "label": "??????", "fieldtype": "Select", "options": "???\n???\n???", "default": "???", "insert_after": "rd_review_section"},
        {"fieldname": "rd_reviewer", "label": "?????", "fieldtype": "Link", "options": "User", "insert_after": "rd_review_status"},
    ],
}
```

- [ ] **Step 4: Add install hook**

Create `rayher_hr_payroll/install.py`:

```python
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from rayher_hr_payroll.custom_fields import CUSTOM_FIELDS


def after_install():
    create_custom_fields(CUSTOM_FIELDS, update=True)
```

Confirm `rayher_hr_payroll/hooks.py` contains:

```python
after_install = "rayher_hr_payroll.install.after_install"
```

- [ ] **Step 5: Run custom field tests**

Run:

```bash
python -m pytest rayher_hr_payroll/tests/test_custom_fields.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

Run:

```bash
git add rayher_hr_payroll/custom_fields.py rayher_hr_payroll/install.py rayher_hr_payroll/hooks.py rayher_hr_payroll/tests/test_custom_fields.py
git commit -m "feat: define rayher custom fields"
```

Expected: commit succeeds.

---

### Task 3: Create Frappe Bench And Install The App

**Files:**
- Modify: none in repository
- Runtime: `~/frappe-bench`

- [ ] **Step 1: Install bench dependencies in WSL**

Run in WSL Ubuntu:

```bash
sudo apt update
sudo apt install -y python3-dev python3-pip python3-venv redis-server mariadb-server mariadb-client libmariadb-dev nodejs npm yarnpkg git wkhtmltopdf
python3 -m pip install --user frappe-bench
```

Expected: packages install and `~/.local/bin/bench --version` prints a bench version.

- [ ] **Step 2: Set local MariaDB root password for the PoC**

Run:

```bash
sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'admin'; FLUSH PRIVILEGES;"
printf '%s\n' 'admin' > ~/.mariadb-root-password
chmod 600 ~/.mariadb-root-password
```

Expected: `cat ~/.mariadb-root-password` prints `admin`.

- [ ] **Step 3: Create bench and install standard apps**

Run:

```bash
~/.local/bin/bench init ~/frappe-bench --frappe-branch version-15
cd ~/frappe-bench
bench get-app erpnext --branch version-15
bench get-app hrms --branch version-15
bench new-site rayher.localhost --admin-password admin --mariadb-root-password "$(cat ~/.mariadb-root-password)"
bench --site rayher.localhost install-app erpnext
bench --site rayher.localhost install-app hrms
```

Expected: `apps/frappe`, `apps/erpnext`, `apps/hrms`, and `sites/rayher.localhost` exist.

- [ ] **Step 4: Install Rayher app from this repository**

Run:

```bash
cd ~/frappe-bench
bench get-app /mnt/e/Rayher/Logistics
bench --site rayher.localhost install-app rayher_hr_payroll
bench --site rayher.localhost list-apps
```

Expected: output includes `frappe`, `erpnext`, `hrms`, and `rayher_hr_payroll`.

- [ ] **Step 5: Start bench**

Run:

```bash
bench start
```

Expected: site opens at `http://localhost:8000`.

---

### Task 4: Add Core DocTypes For GL Import, Allocation, Locks, And Snapshots

**Files:**
- Create under `rayher_hr_payroll/doctype/`: `rd_expense_import`, `rd_expense_item`, `rd_cost_allocation`, `rd_cost_allocation_line`, `rd_allocation_source_hour`, `rd_allocation_source_expense`, `rd_period_lock`, `rd_work_ratio_snapshot`, `accommodation_deduction`, `rayher_hr_settings`

- [ ] **Step 1: Create DocType folders**

Run:

```bash
mkdir -p rayher_hr_payroll/doctype/rd_expense_import
mkdir -p rayher_hr_payroll/doctype/rd_expense_item
mkdir -p rayher_hr_payroll/doctype/rd_cost_allocation
mkdir -p rayher_hr_payroll/doctype/rd_cost_allocation_line
mkdir -p rayher_hr_payroll/doctype/rd_allocation_source_hour
mkdir -p rayher_hr_payroll/doctype/rd_allocation_source_expense
mkdir -p rayher_hr_payroll/doctype/rd_period_lock
mkdir -p rayher_hr_payroll/doctype/rd_work_ratio_snapshot
mkdir -p rayher_hr_payroll/doctype/accommodation_deduction
mkdir -p rayher_hr_payroll/doctype/rayher_hr_settings
```
﻿
- [ ] **Step 2: Create DocTypes with these exact fields**

Use Frappe Desk Developer > DocType or JSON files generated by Frappe. The field definitions are:

`RD Expense Import`, submittable:

| fieldname | label | type | options | required |
|---|---|---|---|---|
| `period` | ?? | Data |  | yes |
| `year` | ?? | Int |  | yes |
| `month` | ?? | Int |  | yes |
| `source_file` | ???? | Attach |  | no |
| `source_file_hash` | source file hash | Data |  | yes |
| `status` | ?? | Select | Draft\nImported\nAllocated\nCancelled | yes |
| `items` | ???? | Table | RD Expense Item | no |

`RD Expense Item`, child table:

| fieldname | label | type | options | required |
|---|---|---|---|---|
| `source_row_key` | source row key | Data |  | yes |
| `voucher_no` | ??? | Data |  | yes |
| `account_level_1` | 1????? | Data |  | yes |
| `account_level_2` | 2????? | Data |  | yes |
| `account_level_3` | 3????? | Data |  | yes |
| `account_level_4` | 4????? | Data |  | no |
| `category` | ??????? | Select | personnel\ndirect_input\ndepreciation\namortization\nother\ndesign | yes |
| `amount` | ???? | Currency |  | yes |
| `direct_project` | ?????? | Link | Project | no |

`RD Cost Allocation`, submittable:

| fieldname | label | type | options | required |
|---|---|---|---|---|
| `period` | ?? | Data |  | yes |
| `year` | ?? | Int |  | yes |
| `month` | ?? | Int |  | yes |
| `expense_import` | ???????? | Link | RD Expense Import | yes |
| `allocation_basis` | ???? | Select | rd_project_hours | yes |
| `calculation_version` | ???? | Data |  | yes |
| `scope` | ???? | Select | ??\n???\n??? | yes |
| `status` | ?? | Select | Draft\nCalculated\nSubmitted\nCancelled | yes |
| `capitalized_total` | ????? | Currency |  | no |
| `expensed_total` | ????? | Currency |  | no |
| `lines` | ???? | Table | RD Cost Allocation Line | no |
| `hour_snapshots` | hour snapshots | Table | RD Allocation Source Hour | no |
| `expense_snapshots` | GL snapshots | Table | RD Allocation Source Expense | no |

`RD Cost Allocation Line`, child table:

| fieldname | label | type | options | required |
|---|---|---|---|---|
| `expense_item_name` | ??? | Data |  | yes |
| `voucher_no` | ??? | Data |  | yes |
| `project` | ?? | Link | Project | yes |
| `project_stage` | ?????? | Select | capitalized\nexpensed\nunknown | yes |
| `basis_hours` | ???? | Float |  | yes |
| `ratio` | ???? | Percent |  | yes |
| `allocated_amount` | ???? | Currency |  | yes |

`RD Allocation Source Hour`, child table:

| fieldname | label | type | options | required |
|---|---|---|---|---|
| `timesheet` | Timesheet | Link | Timesheet | yes |
| `timesheet_detail` | Timesheet Detail | Data |  | yes |
| `employee` | employee | Link | Employee | yes |
| `employee_department` | historical department | Link | Department | no |
| `employee_designation` | historical designation | Link | Designation | no |
| `project` | project | Link | Project | yes |
| `posting_date` | date | Date |  | yes |
| `hours` | hours | Float |  | yes |

`RD Allocation Source Expense`, child table:

| fieldname | label | type | options | required |
|---|---|---|---|---|
| `expense_item` | expense item | Data |  | yes |
| `source_row_key` | source row key | Data |  | yes |
| `voucher_no` | voucher | Data |  | yes |
| `account_level_1` | account level 1 | Data |  | yes |
| `account_level_2` | account level 2 | Data |  | yes |
| `account_level_3` | account level 3 | Data |  | yes |
| `account_level_4` | account level 4 | Data |  | no |
| `amount` | amount | Currency |  | yes |
| `direct_project` | direct project | Link | Project | no |

`RD Period Lock`, submittable:

| fieldname | label | type | options | required |
|---|---|---|---|---|
| `period` | ?? | Data |  | yes |
| `year` | ?? | Int |  | yes |
| `month` | ?? | Int |  | yes |
| `lock_timesheets` | ???? | Check |  | no |
| `lock_project_stage` | ?????? | Check |  | no |
| `lock_gl_import` | ??GL?? | Check |  | no |
| `lock_allocations` | lock allocations | Check |  | no |
| `locked_by` | ??? | Link | User | no |
| `locked_on` | ???? | Datetime |  | no |

`RD Work Ratio Snapshot`:

| fieldname | label | type | options | required |
|---|---|---|---|---|
| `period` | ?? | Data |  | yes |
| `employee` | ?? | Link | Employee | yes |
| `employee_name` | ???? | Data |  | no |
| `total_submitted_timesheet_hours` | total submitted timesheet hours | Float |  | yes |
| `rd_project_hours` | ?????? | Float |  | yes |
| `rd_ratio` | ?????? | Percent |  | yes |
| `recognized_rd_type` | ?????? | Select | ????\n?????\n??? | yes |

`Rayher HR Settings`, single doctype:

| fieldname | label | type | options | required |
|---|---|---|---|---|
| `standard_daily_hours` | standard daily hours | Float |  | yes |

`Accommodation Deduction`:

| fieldname | label | type | options | required |
|---|---|---|---|---|
| `period` | ?? | Data |  | yes |
| `employee` | ?? | Link | Employee | yes |
| `rent_amount` | ?? | Currency |  | no |
| `water_amount` | ?? | Currency |  | no |
| `electricity_amount` | ?? | Currency |  | no |
| `total_amount` | ?? | Currency |  | no |
| `exported_to_finance` | ????? | Check |  | no |

- [ ] **Step 3: Migrate and commit**

Run:

```bash
cd ~/frappe-bench
bench --site rayher.localhost migrate
cd /mnt/e/Rayher/Logistics
git add rayher_hr_payroll/doctype
git commit -m "feat: add rd cost doctypes"
```

Expected: migrate succeeds and commit succeeds.

---

### Task 5: Implement Allocation Generation From Timesheet And GL Import

Critical implementation note: allocation generation must write hour and expense snapshots before submit. Submitted allocation reports must read those snapshots, not live Timesheet rows or current Employee department fields.
Also enrich hour snapshots with historical department/designation from `Employee Internal Work History` according to each source row date. GL duplicate checks must be across the same period, not only inside one uploaded file.

**Files:**
- Create: `rayher_hr_payroll/rd_cost/frappe_adapter.py`
- Modify: `rayher_hr_payroll/doctype/rd_cost_allocation/rd_cost_allocation.py`
- Create: `rayher_hr_payroll/tests/test_frappe_adapter.py`

- [ ] **Step 1: Write stage helper tests**

Create `rayher_hr_payroll/tests/test_frappe_adapter.py`:

```python
from rayher_hr_payroll.rd_cost.frappe_adapter import stage_for_period


def test_stage_for_period_inside_capitalization_window():
    project = {"capitalization_start_date": "2026-01-01", "capitalization_end_date": "2026-12-31"}
    assert stage_for_period(project, year=2026, month=6) == "capitalized"


def test_stage_for_period_outside_capitalization_window():
    project = {"capitalization_start_date": "2026-03-01", "capitalization_end_date": "2026-12-31"}
    assert stage_for_period(project, year=2026, month=1) == "expensed"


def test_stage_for_period_without_dates_is_unknown():
    assert stage_for_period({}, year=2026, month=1) == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest rayher_hr_payroll/tests/test_frappe_adapter.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `rayher_hr_payroll.rd_cost.frappe_adapter`.

- [ ] **Step 3: Implement Frappe adapter**

Create `rayher_hr_payroll/rd_cost/frappe_adapter.py` with:

```python
from datetime import date
from decimal import Decimal

import frappe

from rayher_hr_payroll.rd_cost.types import ExpenseItem, ProjectHour


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    year, month, day = str(value).split("-")
    return date(int(year), int(month), int(day))


def stage_for_period(project: dict, *, year: int, month: int) -> str:
    start = _parse_date(project.get("capitalization_start_date"))
    end = _parse_date(project.get("capitalization_end_date"))
    if not start or not end:
        return "unknown"
    current = date(int(year), int(month), 1)
    return "capitalized" if start <= current <= end else "expensed"


def get_project_hour_rows(*, year: int, month: int) -> list[dict]:
    return frappe.db.sql(
        """
        select ts.name as timesheet, tsd.name as timesheet_detail, ts.employee,
               tsd.project, date(tsd.from_time) as posting_date, tsd.hours
        from `tabTimesheet Detail` tsd
        inner join `tabTimesheet` ts on ts.name = tsd.parent
        inner join `tabProject` p on p.name = tsd.project
        inner join `tabEmployee` e on e.name = ts.employee
        where ts.docstatus = 1
          and month(ts.start_date) = %(month)s
          and year(ts.start_date) = %(year)s
          and coalesce(p.allow_rd_timesheet, 0) = 1
          and e.rd_personnel_type in ('????', '?????', '????')
        """,
        {'year': year, 'month': month},
        as_dict=True,
    )


def get_project_hours(*, year: int, month: int) -> list[ProjectHour]:
    rows = frappe.db.sql(
        """
        select tsd.project as project, sum(tsd.hours) as hours
        from `tabTimesheet Detail` tsd
        inner join `tabTimesheet` ts on ts.name = tsd.parent
        inner join `tabProject` p on p.name = tsd.project
        inner join `tabEmployee` e on e.name = ts.employee
        where ts.docstatus = 1
          and month(ts.start_date) = %(month)s
          and year(ts.start_date) = %(year)s
          and coalesce(p.allow_rd_timesheet, 0) = 1
          and e.rd_personnel_type in ('????', '?????', '????')
        group by tsd.project
        """,
        {"year": year, "month": month},
        as_dict=True,
    )
    result = []
    for row in rows:
        project = frappe.db.get_value("Project", row.project, ["capitalization_start_date", "capitalization_end_date"], as_dict=True) or {}
        result.append(ProjectHour(project=row.project, hours=Decimal(str(row.hours or 0)), stage=stage_for_period(project, year=year, month=month)))
    return result


def get_expense_items(expense_import: str) -> list[ExpenseItem]:
    doc = frappe.get_doc('RD Expense Import', expense_import)
    seen = set()
    result = []
    for row in doc.items:
        if row.source_row_key in seen:
            frappe.throw(f'Duplicate GL source row in import: {row.source_row_key}')
        seen.add(row.source_row_key)
        result.append(ExpenseItem(name=row.name, amount=Decimal(str(row.amount or 0)), account_level_3=row.account_level_3, category=row.category, direct_project=row.direct_project or None))
    return result
```
﻿
- [ ] **Step 4: Implement allocation controller method**

Create `rayher_hr_payroll/doctype/rd_cost_allocation/rd_cost_allocation.py`:

```python
import frappe
from frappe.model.document import Document

from rayher_hr_payroll.rd_cost.allocation import allocate_expenses
from rayher_hr_payroll.rd_cost.frappe_adapter import get_expense_items, get_project_hour_rows, get_project_hours


class RDCostAllocation(Document):
    def calculate(self):
        expenses = get_expense_items(self.expense_import)
        source_hour_rows = get_project_hour_rows(year=self.year, month=self.month)
        project_hours = get_project_hours(year=self.year, month=self.month)
        result = allocate_expenses(expenses=expenses, project_hours=project_hours)
        self.set('hour_snapshots', [])
        self.set('expense_snapshots', [])
        for row in source_hour_rows:
            self.append('hour_snapshots', row)
        for row in frappe.get_doc('RD Expense Import', self.expense_import).items:
            self.append('expense_snapshots', {
                'expense_item': row.name,
                'source_row_key': row.source_row_key,
                'voucher_no': row.voucher_no,
                'account_level_1': row.account_level_1,
                'account_level_2': row.account_level_2,
                'account_level_3': row.account_level_3,
                'account_level_4': row.account_level_4,
                'amount': row.amount,
                'direct_project': row.direct_project,
            })
        self.set("lines", [])
        for line in result.lines:
            source = frappe.get_doc("RD Expense Item", line.expense_item)
            self.append("lines", {
                "expense_item_name": line.expense_item,
                "voucher_no": source.voucher_no,
                "project": line.project,
                "project_stage": line.stage,
                "basis_hours": float(line.basis_hours),
                "ratio": float(line.ratio * 100),
                "allocated_amount": line.amount,
            })
        self.capitalized_total = result.stage_totals["capitalized"]
        self.expensed_total = result.stage_totals["expensed"]
        self.status = "Calculated"
```

- [ ] **Step 5: Run pure tests again**

Run:

```bash
python -m pytest rayher_hr_payroll/tests/test_allocation.py rayher_hr_payroll/tests/test_frappe_adapter.py -q
```

Expected: all pure tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add rayher_hr_payroll/rd_cost/frappe_adapter.py rayher_hr_payroll/doctype/rd_cost_allocation/rd_cost_allocation.py rayher_hr_payroll/tests/test_frappe_adapter.py
git commit -m "feat: calculate rd cost allocation from frappe data"
```

Expected: commit succeeds.

---

### Task 6: Add Timesheet Quality Controls And Period Lock Checks

**Files:**
- Create: `rayher_hr_payroll/timesheet_controls.py`
- Create: `rayher_hr_payroll/leave_controls.py`
- Modify: `rayher_hr_payroll/hooks.py`

- [ ] **Step 1: Create timesheet validation hooks**

Create `rayher_hr_payroll/timesheet_controls.py`:

```python
import frappe
from frappe import _


def _period_from_timesheet(doc):
    if not doc.start_date:
        return None
    return f"{doc.start_date.year}{doc.start_date.month:02d}"


def _is_period_locked(period: str) -> bool:
    if not period:
        return False
    return bool(frappe.db.exists("RD Period Lock", {"period": period, "docstatus": 1, "lock_timesheets": 1}))


def block_locked_timesheet_change(doc, method=None):
    period = _period_from_timesheet(doc)
    if _is_period_locked(period):
        frappe.throw(_("R&D period {0} is locked; timesheet changes require a correction workflow.").format(period))


def validate_timesheet(doc, method=None):
    block_locked_timesheet_change(doc, method=method)
    for row in doc.time_logs:
        if row.project and not frappe.db.get_value("Project", row.project, "allow_rd_timesheet"):
            frappe.throw(_("Project {0} is not enabled for R&D timesheet entry.").format(row.project))


def on_submit_timesheet(doc, method=None):
    reviewers = set()
    for row in doc.time_logs:
        if row.project:
            reviewer = frappe.db.get_value("Project", row.project, "project_owner")
            if reviewer:
                reviewers.add(reviewer)
    if len(reviewers) == 1 and not getattr(doc, "rd_reviewer", None):
        doc.db_set("rd_reviewer", reviewers.pop(), update_modified=False)
```

- [ ] **Step 2: Create compensatory leave legal guard**

Create `rayher_hr_payroll/leave_controls.py`:

```python
import frappe
from frappe import _


def _is_statutory_holiday(attendance_date) -> bool:
    return bool(frappe.db.exists("Holiday", {"holiday_date": attendance_date, "weekly_off": 0}))


def validate_compensatory_leave_request(doc, method=None):
    work_date = getattr(doc, "work_from_date", None) or getattr(doc, "work_end_date", None)
    if work_date and _is_statutory_holiday(work_date):
        frappe.throw(_("Statutory holiday overtime cannot be converted into compensatory leave; it must be paid according to policy."))
```

- [ ] **Step 3: Migrate and manually verify**

Run:

```bash
cd ~/frappe-bench
bench --site rayher.localhost migrate
```

Manual check in Desk:

```text
Project NON-RD has Allow R&D Timesheet Entry = 0
Submitting a Timesheet against NON-RD is blocked
Submitting compensatory leave for a statutory holiday is blocked
```

- [ ] **Step 4: Commit**

Run:

```bash
git add rayher_hr_payroll/timesheet_controls.py rayher_hr_payroll/leave_controls.py rayher_hr_payroll/hooks.py
git commit -m "feat: add rd timesheet and compensatory leave controls"
```

Expected: commit succeeds.

---

### Task 7: Add Allocation Matrix And Timesheet Exception Reports

**Files:**
- Create: `rayher_hr_payroll/report/rd_allocation_matrix/rd_allocation_matrix.py`
- Create: `rayher_hr_payroll/report/rd_allocation_matrix/rd_allocation_matrix.json`
- Create: `rayher_hr_payroll/report/rd_timesheet_exceptions/rd_timesheet_exceptions.py`
- Create: `rayher_hr_payroll/report/rd_timesheet_exceptions/rd_timesheet_exceptions.json`

- [ ] **Step 1: Create allocation matrix report**

Create `rayher_hr_payroll/report/rd_allocation_matrix/rd_allocation_matrix.py`:

```python
import frappe


def execute(filters=None):
    filters = filters or {}
    allocation = filters.get("allocation")
    if not allocation:
        return [], []
    lines = frappe.get_all("RD Cost Allocation Line", filters={"parent": allocation}, fields=["voucher_no", "expense_item_name", "project", "project_stage", "allocated_amount"], order_by="voucher_no, expense_item_name, project")
    projects = sorted({row.project for row in lines})
    columns = [
        {"label": "???", "fieldname": "voucher_no", "fieldtype": "Data", "width": 140},
        {"label": "???", "fieldname": "expense_item_name", "fieldtype": "Data", "width": 180},
    ]
    columns.extend({"label": project, "fieldname": project, "fieldtype": "Currency", "width": 130} for project in projects)
    rows_by_key = {}
    for line in lines:
        key = (line.voucher_no, line.expense_item_name)
        rows_by_key.setdefault(key, {"voucher_no": line.voucher_no, "expense_item_name": line.expense_item_name})
        rows_by_key[key][line.project] = line.allocated_amount
    return columns, list(rows_by_key.values())
```

Create `rayher_hr_payroll/report/rd_allocation_matrix/rd_allocation_matrix.json`:

```json
{"doctype":"Report","name":"RD Allocation Matrix","ref_doctype":"RD Cost Allocation","report_type":"Script Report","is_standard":"Yes","module":"Rayher HR Payroll"}
```
﻿
- [ ] **Step 2: Create timesheet exceptions report**

Create `rayher_hr_payroll/report/rd_timesheet_exceptions/rd_timesheet_exceptions.py`:

```python
import frappe


def execute(filters=None):
    filters = filters or {}
    year = int(filters.get("year"))
    month = int(filters.get("month"))
    columns = [
        {"label": "??", "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
        {"label": "????", "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
        {"label": "????", "fieldname": "exception_type", "fieldtype": "Data", "width": 160},
        {"label": "??", "fieldname": "message", "fieldtype": "Data", "width": 360},
    ]
    employees = frappe.get_all("Employee", filters={"status": "Active", "rd_personnel_type": ["in", ["????", "?????", "????"]]}, fields=["name", "employee_name"])
    rows = []
    for employee in employees:
        hours = frappe.db.sql(
            """
            select coalesce(sum(tsd.hours), 0)
            from `tabTimesheet Detail` tsd
            inner join `tabTimesheet` ts on ts.name = tsd.parent
            where ts.employee = %(employee)s
              and ts.docstatus = 1
              and year(ts.start_date) = %(year)s
              and month(ts.start_date) = %(month)s
            """,
            {"employee": employee.name, "year": year, "month": month},
        )[0][0]
        if not hours:
            rows.append({"employee": employee.name, "employee_name": employee.employee_name, "exception_type": "??", "message": f"{year}-{month:02d} ???????"})
    return columns, rows
```

Create `rayher_hr_payroll/report/rd_timesheet_exceptions/rd_timesheet_exceptions.json`:

```json
{"doctype":"Report","name":"RD Timesheet Exceptions","ref_doctype":"Timesheet","report_type":"Script Report","is_standard":"Yes","module":"Rayher HR Payroll"}
```

- [ ] **Step 3: Migrate and verify reports load**

Run:

```bash
cd ~/frappe-bench
bench --site rayher.localhost migrate
bench --site rayher.localhost clear-cache
```

Expected: reports appear in Desk search as `RD Allocation Matrix` and `RD Timesheet Exceptions`.

- [ ] **Step 4: Commit**

Run:

```bash
git add rayher_hr_payroll/report
git commit -m "feat: add rd allocation and exception reports"
```

Expected: commit succeeds.

---

### Task 8: Seed Demo Data And Run End-To-End PoC

**Files:**
- Create: `rayher_hr_payroll/demo.py`

- [ ] **Step 1: Create demo data loader**

Create `rayher_hr_payroll/demo.py`:

```python
import frappe


def upsert_doc(doctype, name, values):
    if frappe.db.exists(doctype, name):
        doc = frappe.get_doc(doctype, name)
        doc.update(values)
        doc.save(ignore_permissions=True)
        return doc
    doc = frappe.get_doc({"doctype": doctype, "name": name, **values})
    doc.insert(ignore_permissions=True)
    return doc


def create_demo_data():
    company = frappe.defaults.get_global_default("company")
    emp = upsert_doc("Employee", "EMP-RD-001", {"employee_name": "Demo RD Engineer", "first_name": "Demo", "gender": "Male", "date_of_birth": "1990-01-01", "date_of_joining": "2026-01-01", "company": company, "status": "Active", "rd_personnel_type": "????", "archive_status": "???"})
    for project_name, start, end in [("RD-CAP", "2026-01-01", "2026-12-31"), ("RD-EXP", None, None)]:
        upsert_doc("Project", project_name, {"project_name": project_name, "status": "Open", "company": company, "allow_rd_timesheet": 1, "capitalization_start_date": start, "capitalization_end_date": end})
    ts = frappe.get_doc({"doctype": "Timesheet", "employee": emp.name, "company": company, "time_logs": [
        {"activity_type": "Development", "from_time": "2026-01-05 09:00:00", "to_time": "2026-01-05 15:00:00", "hours": 6, "project": "RD-CAP"},
        {"activity_type": "Development", "from_time": "2026-01-05 15:00:00", "to_time": "2026-01-05 19:00:00", "hours": 4, "project": "RD-EXP"},
    ]})
    ts.insert(ignore_permissions=True)
    ts.submit()
    imp = frappe.get_doc({"doctype": "RD Expense Import", "period": "202601", "year": 2026, "month": 1, "status": "Imported", "items": [{"voucher_no": "V-001", "account_level_1": "????", "account_level_2": "??????", "account_level_3": "??", "category": "direct_input", "amount": 1200}]})
    imp.insert(ignore_permissions=True)
    imp.submit()
    alloc = frappe.get_doc({"doctype": "RD Cost Allocation", "period": "202601", "year": 2026, "month": 1, "expense_import": imp.name, "allocation_basis": "rd_project_hours", "calculation_version": "202601-v1", "scope": "??", "status": "Draft"})
    alloc.calculate()
    alloc.insert(ignore_permissions=True)
    alloc.submit()
    return alloc.name
```

- [ ] **Step 2: Run demo loader**

Run:

```bash
cd ~/frappe-bench
bench --site rayher.localhost execute rayher_hr_payroll.demo.create_demo_data
```

Expected: command returns an `RD Cost Allocation` document name.

- [ ] **Step 3: Verify allocation math in Desk**

Open the generated `RD Cost Allocation` document. Expected:

```text
RD-CAP allocated amount = 720.00
RD-EXP allocated amount = 480.00
capitalized_total = 720.00
expensed_total = 480.00
```

- [ ] **Step 4: Commit**

Run:

```bash
git add rayher_hr_payroll/demo.py
git commit -m "test: add rd cost allocation demo data"
```

Expected: commit succeeds.

---

### Task 9: Add Runbook And Link It From The Spec

**Files:**
- Create: `docs/frappe-poc-runbook.md`
- Modify: `docs/superpowers/specs/2026-06-15-rayher-hr-rd-payroll-design.md`

- [ ] **Step 1: Create runbook**

Create `docs/frappe-poc-runbook.md`:

```markdown
# Rayher Frappe PoC Runbook

## What This PoC Proves

This PoC proves the R&D cost allocation chain:

Employee -> Project -> Timesheet -> RD Expense Import -> RD Cost Allocation -> allocation matrix report.

Payroll is not calculated in this PoC.

## Demo Scenario

1. Open Project `RD-CAP` and confirm it is enabled for R&D timesheet entry.
2. Open Project `RD-EXP` and confirm it is enabled for R&D timesheet entry.
3. Open the submitted Timesheet for `EMP-RD-001`.
4. Open the generated `RD Cost Allocation` document for period `202601`.
5. Confirm `RD-CAP = 720.00` and `RD-EXP = 480.00`.
6. Open `RD Allocation Matrix` report and confirm the same amounts.

## Key Controls

- Capitalized / expensed filtering is a subtotal view, not a denominator recalculation.
- Timesheets in locked periods cannot be saved, submitted, cancelled, deleted, or amended.
- Allocation reports read saved source snapshots, not live Timesheet rows.
- GL imports reject duplicate `source_row_key` values for the same period.
- Legal holiday compensatory leave is blocked by custom validation.
- Project-owner review routing is custom logic in `rayher_hr_payroll`.
```

- [ ] **Step 2: Add PoC status link to spec**

Append this paragraph under the spec decision conclusion:

```markdown
PoC execution is tracked in `docs/frappe-poc-runbook.md` and `docs/superpowers/plans/2026-06-16-rayher-frappe-rd-cost-poc.md`. The PoC acceptance test is the 2026-01 demo allocation: total GL amount 1200.00, RD-CAP 60% / RD-EXP 40%, capitalized subtotal 720.00, expensed subtotal 480.00.
```

- [ ] **Step 3: Verify markdown files are readable**

Run:

```bash
git diff --check -- docs/frappe-poc-runbook.md docs/superpowers/specs/2026-06-15-rayher-hr-rd-payroll-design.md
```

Expected: no whitespace errors.

- [ ] **Step 4: Commit**

Run:

```bash
git add docs/frappe-poc-runbook.md docs/superpowers/specs/2026-06-15-rayher-hr-rd-payroll-design.md
git commit -m "docs: add frappe poc runbook"
```

Expected: commit succeeds.

---

## Self-Review

### Spec Coverage

| Spec requirement | Covered by task |
|---|---|
| Frappe/ERPNext/Frappe HR + custom app route | Tasks 1, 3 |
| Employee R&D fields and Project capitalization fields | Task 2 |
| R&D GL import | Task 4 |
| R&D cost allocation without denominator recalculation | Tasks 1, 5, 8 |
| Capitalized / expensed subtotal reporting | Tasks 1, 5, 7, 8 |
| Project-owner timesheet review as custom work | Task 6 |
| Compensatory leave legal guard | Task 6 |
| Timesheet data quality and lock controls | Tasks 6, 7 |
| Source snapshots and GL duplicate guards | Tasks 4, 5, 8 |
| Runbook for stakeholder demo | Task 9 |

### Acceptance Criteria

The PoC is accepted when all of these are true:

```text
python -m pytest rayher_hr_payroll/tests -q passes
bench --site rayher.localhost migrate succeeds
bench --site rayher.localhost execute rayher_hr_payroll.demo.create_demo_data returns allocation name
RD-CAP allocated amount is 720.00
RD-EXP allocated amount is 480.00
capitalized_total is 720.00
expensed_total is 480.00
RD Allocation Matrix shows the same amounts
Timesheet validation blocks non-R&D projects
Locked-period Timesheet cancel/delete/amend attempts are blocked server-side
GL import duplicate source rows are rejected
Allocation document stores source hour and source expense snapshots
Compensatory Leave validation blocks statutory holiday compensatory leave
```
