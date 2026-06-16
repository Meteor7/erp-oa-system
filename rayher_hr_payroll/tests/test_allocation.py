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

# --- G2: direct_project stage classification ---

def test_direct_project_zero_hours_with_stage_classifies_correctly():
    """A direct expense to a project that has 0 logged hours this month must still
    land in that project's real capitalization stage, not 'unknown'."""
    expenses = [
        ExpenseItem(
            name="GL-EQUIP-001",
            amount=Decimal("1000.00"),
            account_level_3="equipment",
            category="depreciation",
            direct_project="RD-CAP-IDLE",
        )
    ]
    hours = [
        ProjectHour(project="RD-CAP-IDLE", hours=Decimal("0"), stage="capitalized"),
        ProjectHour(project="RD-EXP", hours=Decimal("40"), stage="expensed"),
    ]

    result = allocate_expenses(expenses=expenses, project_hours=hours)

    assert result.project_amounts["RD-CAP-IDLE"] == Decimal("1000.00")
    assert result.stage_totals["capitalized"] == Decimal("1000.00")
    assert result.stage_totals["unknown"] == Decimal("0.00")


def test_direct_project_absent_from_project_hours_raises():
    """If a direct_project is entirely missing from project_hours, the allocator must
    fail loudly instead of silently classifying the amount as 'unknown'."""
    expenses = [
        ExpenseItem(
            name="GL-EQUIP-002",
            amount=Decimal("1000.00"),
            account_level_3="equipment",
            category="depreciation",
            direct_project="RD-GHOST",
        )
    ]
    hours = [ProjectHour(project="RD-EXP", hours=Decimal("40"), stage="expensed")]

    with pytest.raises(ValueError, match="RD-GHOST"):
        allocate_expenses(expenses=expenses, project_hours=hours)


def test_merge_direct_project_stages_adds_zero_hour_entries():
    from rayher_hr_payroll.rd_cost.allocation import merge_direct_project_stages

    hours = [ProjectHour(project="RD-EXP", hours=Decimal("40"), stage="expensed")]
    merged = merge_direct_project_stages(hours, {"RD-CAP-IDLE": "capitalized", "RD-EXP": "expensed"})

    by_project = {ph.project: ph for ph in merged}
    assert by_project["RD-EXP"].hours == Decimal("40")  # unchanged
    assert by_project["RD-CAP-IDLE"].hours == Decimal("0")
    assert by_project["RD-CAP-IDLE"].stage == "capitalized"


def test_unknown_project_stage_is_preserved_for_historical_data():
    expenses = [
        ExpenseItem(
            name="GL-UNKNOWN-001",
            amount=Decimal("100.00"),
            account_level_3="power",
            category="direct_input",
        )
    ]
    hours = [ProjectHour(project="RD-UNKNOWN", hours=Decimal("8"), stage="unknown")]

    result = allocate_expenses(expenses=expenses, project_hours=hours)

    assert result.project_amounts == {"RD-UNKNOWN": Decimal("100.00")}
    assert result.lines[0].stage == "unknown"
    assert result.stage_totals["capitalized"] == Decimal("0.00")
    assert result.stage_totals["expensed"] == Decimal("0.00")
    assert result.stage_totals["unknown"] == Decimal("100.00")


def test_direct_project_expense_emits_only_the_target_project_line():
    expenses = [
        ExpenseItem(
            name="GL-DIRECT-001",
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

    assert [(line.project, line.amount) for line in result.lines] == [("RD-EXP", Decimal("500.00"))]
