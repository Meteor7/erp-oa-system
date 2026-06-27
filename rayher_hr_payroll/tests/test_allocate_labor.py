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
