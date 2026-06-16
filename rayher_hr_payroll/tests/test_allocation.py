from decimal import Decimal

import pytest

from rayher_hr_payroll.rd_cost.allocation import allocate_expenses
from rayher_hr_payroll.rd_cost.types import ExpenseItem, ProjectHour


def test_capitalized_filter_does_not_recalculate_denominator():
    expenses = [
        ExpenseItem(
            name="GL-POWER-001",
            amount=Decimal("1200.00"),
            account_level_3="power",
            category="direct_input",
        )
    ]
    hours = [
        ProjectHour(project="RD-CAP", hours=Decimal("60"), stage="capitalized"),
        ProjectHour(project="RD-EXP", hours=Decimal("40"), stage="expensed"),
    ]

    result = allocate_expenses(expenses=expenses, project_hours=hours)

    assert result.project_amounts == {
        "RD-CAP": Decimal("720.00"),
        "RD-EXP": Decimal("480.00"),
    }
    assert result.stage_totals == {
        "capitalized": Decimal("720.00"),
        "expensed": Decimal("480.00"),
        "unknown": Decimal("0.00"),
    }


def test_direct_project_expense_bypasses_hour_ratio():
    expenses = [
        ExpenseItem(
            name="GL-TEST-001",
            amount=Decimal("500.00"),
            account_level_3="testing",
            category="direct_input",
            direct_project="RD-EXP",
        )
    ]
    hours = [
        ProjectHour(project="RD-CAP", hours=Decimal("99"), stage="capitalized"),
        ProjectHour(project="RD-EXP", hours=Decimal("1"), stage="expensed"),
    ]

    result = allocate_expenses(expenses=expenses, project_hours=hours)

    assert result.project_amounts == {
        "RD-CAP": Decimal("0.00"),
        "RD-EXP": Decimal("500.00"),
    }
    assert result.stage_totals["expensed"] == Decimal("500.00")


def test_zero_hours_without_direct_project_is_rejected():
    expenses = [
        ExpenseItem(
            name="GL-POWER-001",
            amount=Decimal("1200.00"),
            account_level_3="power",
            category="direct_input",
        )
    ]

    with pytest.raises(ValueError, match="project_hours total must be greater than zero"):
        allocate_expenses(expenses=expenses, project_hours=[])