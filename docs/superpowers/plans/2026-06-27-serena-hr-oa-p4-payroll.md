# Serena HR/OA Platform — P4 Payroll + R&D Labor Cost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Run real HRMS payroll, replace the static `rd_mock_*` salary display with the period's Salary Slip, and feed 研发人工费 (each R&D employee's salary × their per-project hour share) into the existing cost allocation (decision Q6 = C/ii).

**Architecture:** HRMS computes Salary Slips. A new `payroll_bridge.py` resolver reads the period Salary Slip (replacing `rd_mock_*` reads in `dashboard_entry.py` and the 08 page). Labor allocation is **DRY** — it reuses the already-tested `allocate_expenses` by treating each employee's salary as a one-item expense allocated against *that employee's own* `ProjectHour` list, then merges the result with the expense allocation via a new `combine_results`.

**Tech Stack:** HRMS Payroll (Salary Component/Structure/Assignment/Payroll Entry/Salary Slip), `rayher_hr_payroll.rd_cost` (allocation engine), pytest. **Part 4 of 5 — the only phase with substantial code.**

**Spec:** `…/2026-06-27-serena-hr-oa-platform-design.md` (§5). **Prereq:** Foundation+P2+P3 merged. Conventions per Foundation plan.

---

## File Structure
- Modify: `rayher_hr_payroll/rd_cost/allocation.py` — add `allocate_labor(...)` and `combine_results(a, b)`. Pure functions, no frappe import.
- Create: `rayher_hr_payroll/payroll_bridge.py` — `get_period_salary(employee, ym)` + `period_salaries(period)` reading Salary Slip; the only new frappe-touching module.
- Modify: `rayher_hr_payroll/api/dashboard_entry.py` — read salary via `payroll_bridge` instead of `rd_mock_*`.
- Modify: `rayher_hr_payroll/rd_cost/document_builder.py` (and its caller) — append labor lines to the allocation document.
- Create tests: `tests/test_allocate_labor.py`, `tests/test_payroll_bridge.py`; extend `tests/test_allocation.py` if needed.

---

## Task 1: HRMS payroll config + smoke (site config)

**Files:** none in git — Salary Components/Structure are site master data created once. (Could be fixtured later; first pass configures on the bench.)

- [ ] **Step 1: Create minimal salary components + structure + assignment** — author `/tmp/payroll_setup.py`:
```python
import frappe
company = frappe.defaults.get_global_default("company")
def comp(name, typ, abbr):
    if not frappe.db.exists("Salary Component", name):
        frappe.get_doc({"doctype":"Salary Component","salary_component":name,
            "salary_component_abbr":abbr,"type":typ}).insert(ignore_permissions=True)
comp("基本工资","Earning","BASE"); comp("社保","Deduction","SOC"); comp("个税","Deduction","TAX")
if not frappe.db.exists("Salary Structure","标准月薪"):
    ss = frappe.get_doc({"doctype":"Salary Structure","name":"标准月薪","company":company,
        "payroll_frequency":"Monthly",
        "earnings":[{"salary_component":"基本工资","abbr":"BASE","amount":0}],
        "deductions":[{"salary_component":"社保","abbr":"SOC","amount":0},
                      {"salary_component":"个税","abbr":"TAX","amount":0}]})
    ss.insert(ignore_permissions=True); ss.submit()
print("PAYROLL_SETUP_OK")
```
Run via bench console. Expected: `PAYROLL_SETUP_OK`.

- [ ] **Step 2: Assign a base salary + run one Salary Slip** — author `/tmp/payroll_run.py`:
```python
import frappe
emp = frappe.get_all("Employee", filters={"status":"Active"}, limit=1, pluck="name")[0]
if not frappe.db.exists("Salary Structure Assignment", {"employee":emp,"salary_structure":"标准月薪"}):
    a = frappe.get_doc({"doctype":"Salary Structure Assignment","employee":emp,
        "salary_structure":"标准月薪","from_date":"2026-07-01","base":20000,
        "company":frappe.defaults.get_global_default("company")})
    a.insert(ignore_permissions=True); a.submit()
slip = frappe.get_doc({"doctype":"Salary Slip","employee":emp,
    "start_date":"2026-07-01","end_date":"2026-07-31"})
slip.insert(ignore_permissions=True); slip.submit()
print("GROSS:", slip.gross_pay, "NET:", slip.net_pay)
```
Run via bench console. Expected: `GROSS: 20000.0 NET: ...` (a real computed slip). No commit (site data).

## Task 2: Salary resolver `payroll_bridge.py`

**Files:** Create `rayher_hr_payroll/payroll_bridge.py`; test `tests/test_payroll_bridge.py`.

- [ ] **Step 1: Write the failing test** (pure helper only):
```python
from rayher_hr_payroll.payroll_bridge import month_bounds


def test_month_bounds_returns_first_and_last_day():
    assert month_bounds("2026-07") == ("2026-07-01", "2026-07-31")
    assert month_bounds("2026-02") == ("2026-02-01", "2026-02-28")


def test_month_bounds_rejects_bad_period():
    import pytest
    with pytest.raises(ValueError):
        month_bounds("2026/07")
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError`).

- [ ] **Step 3: Write the module**:
```python
import calendar

import frappe


def month_bounds(ym):
    parts = ym.split("-")
    if len(parts) != 2:
        raise ValueError("period must be YYYY-MM")
    year, month = int(parts[0]), int(parts[1])
    last = calendar.monthrange(year, month)[1]
    return (f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}")


def get_period_salary(employee, ym):
    """Submitted Salary Slip gross_pay for an employee in period 'YYYY-MM' (0.0 if none)."""
    start, end = month_bounds(ym)
    rows = frappe.get_all(
        "Salary Slip",
        filters={"employee": employee, "docstatus": 1, "start_date": ["between", [start, end]]},
        fields=["gross_pay"], limit=1,
    )
    return float(rows[0].gross_pay) if rows else 0.0


def period_salaries(ym):
    """{employee: gross_pay} for all submitted slips in the period."""
    start, end = month_bounds(ym)
    rows = frappe.get_all(
        "Salary Slip",
        filters={"docstatus": 1, "start_date": ["between", [start, end]]},
        fields=["employee", "gross_pay"],
    )
    return {r.employee: float(r.gross_pay) for r in rows}
```

- [ ] **Step 4: Run test → PASS** (2 passed).

- [ ] **Step 5: Integration-verify against the slip from Task 1** — bench console:
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench && echo 'import frappe; from rayher_hr_payroll.payroll_bridge import period_salaries; print(\"SAL:\", period_salaries(\"2026-07\"))' | sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console" 2>&1 | grep "SAL:"
```
Expected: a non-empty dict like `SAL: {'HR-EMP-0000X': 20000.0}`.

- [ ] **Step 6: Commit**
```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/payroll_bridge.py rayher_hr_payroll/tests/test_payroll_bridge.py
git commit -m "feat: add payroll_bridge salary resolver (reads submitted Salary Slip)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

## Task 3: Labor allocation `allocate_labor` + `combine_results` (pure, DRY)

Reuses the tested `allocate_expenses`: each employee's salary is a one-item expense allocated against *their own* `ProjectHour` list; results are summed.

**Files:** Modify `rayher_hr_payroll/rd_cost/allocation.py`; test `tests/test_allocate_labor.py`.

- [ ] **Step 1: Write the failing test** — author `tests/test_allocate_labor.py`:
```python
from decimal import Decimal
from rayher_hr_payroll.rd_cost.allocation import allocate_labor, combine_results
from rayher_hr_payroll.rd_cost.types import ExpenseItem, ProjectHour


def _sal(emp, amount):
    return ExpenseItem(name="labor:" + emp, amount=Decimal(amount), account_level_3="人工费", category="人工费")


def test_labor_allocated_by_each_employees_own_hours():
    res = allocate_labor(
        salaries=[_sal("E1", "10000")],
        employee_hours={"labor:E1": [
            ProjectHour(project="P1", hours=Decimal("3"), stage="capitalized"),
            ProjectHour(project="P2", hours=Decimal("1"), stage="expensed"),
        ]},
    )
    assert res.project_amounts["P1"] == Decimal("7500.00")
    assert res.project_amounts["P2"] == Decimal("2500.00")
    assert res.stage_totals["capitalized"] == Decimal("7500.00")
    assert res.stage_totals["expensed"] == Decimal("2500.00")


def test_employee_without_hours_is_skipped():
    res = allocate_labor(salaries=[_sal("E9", "5000")], employee_hours={})
    assert res.lines == []
    assert res.stage_totals["capitalized"] == Decimal("0.00")


def test_combine_results_sums_two_allocations():
    a = allocate_labor(salaries=[_sal("E1", "100")],
                       employee_hours={"labor:E1": [ProjectHour("P1", Decimal("1"), "capitalized")]})
    b = allocate_labor(salaries=[_sal("E2", "200")],
                       employee_hours={"labor:E2": [ProjectHour("P1", Decimal("1"), "capitalized")]})
    c = combine_results(a, b)
    assert c.project_amounts["P1"] == Decimal("300.00")
    assert len(c.lines) == 2
```

- [ ] **Step 2: Run → FAIL** (`ImportError: cannot import name 'allocate_labor'`).

- [ ] **Step 3: Append to `rd_cost/allocation.py`** (after `allocate_expenses`):
```python
def combine_results(a, b):
    project_amounts = dict(a.project_amounts)
    for proj, amt in b.project_amounts.items():
        project_amounts[proj] = _money(project_amounts.get(proj, ZERO) + amt)
    stage_totals = dict(a.stage_totals)
    for stage, amt in b.stage_totals.items():
        stage_totals[stage] = _money(stage_totals.get(stage, ZERO) + amt)
    return AllocationResult(
        lines=list(a.lines) + list(b.lines),
        project_amounts=project_amounts,
        stage_totals=stage_totals,
    )


def allocate_labor(*, salaries, employee_hours):
    """Allocate each employee's salary across THEIR own project hours (reusing
    allocate_expenses), then sum. `salaries` are ExpenseItem(name='labor:<emp>');
    `employee_hours` maps that same name -> list[ProjectHour]."""
    result = AllocationResult(
        lines=[], project_amounts={},
        stage_totals={"capitalized": ZERO, "expensed": ZERO, "unknown": ZERO},
    )
    for item in salaries:
        hours = employee_hours.get(item.name)
        if not hours:
            continue
        result = combine_results(result, allocate_expenses(expenses=[item], project_hours=hours))
    return result
```

- [ ] **Step 4: Run test → PASS** (3 passed). Also re-run `tests/test_allocation.py` to confirm no regression in `allocate_expenses`.

- [ ] **Step 5: Commit**
```bash
cd /e/QIHENG Demo/Logistics-hroa
git add rayher_hr_payroll/rd_cost/allocation.py rayher_hr_payroll/tests/test_allocate_labor.py
git commit -m "feat: add R&D labor cost allocation (salary by per-employee hours)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

## Task 4: Swap dashboard salary display from `rd_mock_*` to Salary Slip

`dashboard_entry.py` currently sums `rd_mock_base/social/fund/tax` (lines ~13, ~54-55). Source the real numbers from `payroll_bridge`.

**Files:** Modify `rayher_hr_payroll/payroll_bridge.py` (add `period_pay_totals`); Modify `rayher_hr_payroll/api/dashboard_entry.py`; test `tests/test_payroll_bridge.py`.

- [ ] **Step 1: Add failing test for the aggregate shape** — append to `tests/test_payroll_bridge.py`:
```python
def test_period_pay_totals_shape(monkeypatch):
    import rayher_hr_payroll.payroll_bridge as pb
    monkeypatch.setattr(pb.frappe, "get_all", lambda *a, **k: [
        {"gross_pay": 100.0, "total_deduction": 30.0},
        {"gross_pay": 200.0, "total_deduction": 40.0},
    ])
    out = pb.period_pay_totals("2026-07")
    assert out == {"gross": 300.0, "deductions": 70.0}
```

- [ ] **Step 2: Run → FAIL.** Add to `payroll_bridge.py`:
```python
def period_pay_totals(ym):
    """Aggregate {gross, deductions} from submitted Salary Slips in the period."""
    start, end = month_bounds(ym)
    rows = frappe.get_all(
        "Salary Slip",
        filters={"docstatus": 1, "start_date": ["between", [start, end]]},
        fields=["gross_pay", "total_deduction"],
    )
    return {
        "gross": float(sum((r["gross_pay"] or 0) for r in rows)),
        "deductions": float(sum((r["total_deduction"] or 0) for r in rows)),
    }
```
- [ ] **Step 3: Run test → PASS.**

- [ ] **Step 4: Read then edit `dashboard_entry.py`** — first read it (`git show` or open) to confirm the exact lines. Replace the salary block (the part that builds `gross`/`deductions` from `rd_mock_*`) with:
```python
    from rayher_hr_payroll.payroll_bridge import period_pay_totals
    pay = period_pay_totals(period)
    gross = pay["gross"]
    deductions = pay["deductions"]
```
Remove `rd_mock_base/social/fund/tax` from the `fields=[...]` Employee fetch on line ~13 (they are no longer read here). Leave the role gate (`# payroll/salary aggregates are only exposed to HR/Accounts roles`) intact.

- [ ] **Step 5: Verify on bench** — the dashboard salary now reflects the Task-1 slip, not `rd_mock`:
```bash
wsl -e bash -lc "cd /home/rayher/frappe-bench && echo 'import frappe; from rayher_hr_payroll.api.dashboard_entry import *; from rayher_hr_payroll.payroll_bridge import period_pay_totals; print(\"PAY:\", period_pay_totals(\"2026-07\"))' | sudo -u rayher /home/rayher/.local/bin/bench --site qatest.localhost console" 2>&1 | grep "PAY:"
```
Expected: gross matches the submitted slip total (e.g. `PAY: {'gross': 20000.0, ...}`).

- [ ] **Step 6: Commit** (`payroll_bridge.py`, `api/dashboard_entry.py`, test) with message `feat: dashboard salary reads Salary Slip instead of rd_mock`.

## Task 5: Feed 研发人工费 into the allocation document (integration)

When allocation is (re)computed, also allocate labor and merge it in, so capitalized/expensed totals include R&D salaries.

**Files:** Modify `rayher_hr_payroll/rd_cost/document_builder.py` and its caller `rayher_hr_payroll/api/allocation_entry.py` (`recalc_allocation`). Test: extend `tests/test_allocation_document.py`.

- [ ] **Step 1: Read the build path** — open `rd_cost/document_builder.py` (`populate_allocation_document`) and `api/allocation_entry.py::recalc_allocation` to find where `allocate_expenses(...)` is called and where `project_hours` / per-employee hours are assembled. Confirm the period variable name and the timesheet source that yields per-employee, per-project hours.

- [ ] **Step 2: Write the failing integration test** — in `tests/test_allocation_document.py`, add a case that builds a document for a period with one R&D employee who has a submitted Salary Slip and logged hours on a capitalized project, and asserts a labor line (`expense_item` starting `labor:`) appears and the capitalized total includes the salary share. (Mirror the existing document-test fixtures in that file for setup.)

- [ ] **Step 3: Implement the merge** — in the build path, after the existing expense allocation:
```python
from rayher_hr_payroll.payroll_bridge import period_salaries
from rayher_hr_payroll.rd_cost.allocation import allocate_labor, combine_results
from rayher_hr_payroll.rd_cost.types import ExpenseItem
from decimal import Decimal

salaries = [
    ExpenseItem(name="labor:" + emp, amount=Decimal(str(gross)),
                account_level_3="人工费", category="人工费")
    for emp, gross in period_salaries(period).items()
]
labor = allocate_labor(salaries=salaries, employee_hours=employee_project_hours)
result = combine_results(result, labor)
```
where `employee_project_hours` is the per-employee `{ "labor:"+emp: [ProjectHour,...] }` map assembled from the same timesheet rows the expense allocation already reads (build it alongside the existing `project_hours`).

- [ ] **Step 4: Run the integration test → PASS;** re-run the full `tests/` suite → 0 failures (no regression to expense-only allocation).

- [ ] **Step 5: Bench acceptance** — recalc a period that has both imported expenses and R&D salaries; confirm the capitalized total rose by the labor share and labor lines are persisted on the `RD Cost Allocation` document.

- [ ] **Step 6: Commit** with message `feat: include R&D labor cost in cost allocation document`.

---

## Self-Review

**Spec coverage (§5):** 正式算薪 → Task 1; 真工资替换模拟(看板/08)→ Task 4 (dashboard) — **08 月末工资计算表 page swap is the same resolver call; if that page has a separate backend, repeat Task 4's swap there (call it out, do not skip)**; 研发人工费进分摊 → Task 3 (engine) + Task 5 (wiring). Employee-card `rd_mock_base>0` validation in `employee_controls.py` should be relaxed once real payroll is the source — add a follow-up to drop that check when `rd_mock_*` is fully retired.

**Placeholder scan:** Task 5 Steps 1-3 intentionally require reading `document_builder.py` to locate the exact insertion point (its internals were not pre-read); the data to build and functions to call are fully specified, only the line location is discovered. All pure-function tasks (2,3,4) have complete code.

**Type/name consistency:** `month_bounds`, `get_period_salary`, `period_salaries`, `period_pay_totals`, `allocate_labor`, `combine_results`, labor key convention `"labor:"+emp` — used identically in Tasks 2-5; `ExpenseItem`/`ProjectHour`/`AllocationResult` match `rd_cost/types.py`.
