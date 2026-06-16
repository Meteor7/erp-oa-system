from decimal import Decimal
from types import SimpleNamespace

import pytest

from rayher_hr_payroll.rd_cost.frappe_adapter import (
    expense_items_from_rows,
    historical_org_for_date,
    source_expense_rows_from_rows,
    stage_for_period,
)


def test_stage_for_period_uses_capitalization_dates():
    project = {
        "capitalization_start_date": "2026-01-01",
        "capitalization_end_date": "2026-12-31",
    }
    assert stage_for_period(project, year=2026, month=1) == "capitalized"
    assert stage_for_period(project, year=2027, month=1) == "expensed"


def test_stage_for_period_without_complete_dates_is_unknown():
    assert stage_for_period({}, year=2026, month=1) == "unknown"
    assert stage_for_period({"capitalization_start_date": "2026-01-01"}, year=2026, month=1) == "unknown"


def test_historical_org_for_date_uses_latest_effective_history_row():
    history_rows = [
        SimpleNamespace(from_date="2025-01-01", department="Sales", designation="Assistant"),
        SimpleNamespace(from_date="2026-01-10", department="RD", designation="Engineer"),
        SimpleNamespace(from_date="2026-03-01", department="Finance", designation="Analyst"),
    ]

    org = historical_org_for_date(
        history_rows,
        "2026-02-05",
        fallback_department="Current Department",
        fallback_designation="Current Designation",
    )

    assert org == {"employee_department": "RD", "employee_designation": "Engineer"}


def test_historical_org_for_date_falls_back_when_no_history_applies():
    history_rows = [SimpleNamespace(from_date="2026-03-01", department="Finance", designation="Analyst")]

    org = historical_org_for_date(
        history_rows,
        "2026-02-05",
        fallback_department="Current Department",
        fallback_designation="Current Designation",
    )

    assert org == {
        "employee_department": "Current Department",
        "employee_designation": "Current Designation",
    }


def test_expense_items_from_rows_converts_frappe_child_rows():
    rows = [
        SimpleNamespace(
            name="ROW-001",
            amount="1200.50",
            account_level_3="Power",
            category="direct_input",
            direct_project="",
            source_row_key="202601|V-001|Power|1",
        )
    ]

    items = expense_items_from_rows(rows)

    assert len(items) == 1
    assert items[0].name == "ROW-001"
    assert items[0].amount == Decimal("1200.50")
    assert items[0].direct_project is None


def test_source_expense_rows_from_rows_keeps_snapshot_fields():
    rows = [
        SimpleNamespace(
            name="ROW-001",
            source_row_key="202601|V-001|Power|1",
            voucher_no="V-001",
            account_level_1="RD Expense",
            account_level_2="Direct Input",
            account_level_3="Power",
            account_level_4="Electricity",
            amount=Decimal("1200.50"),
            direct_project="RD-CAP",
        )
    ]

    assert source_expense_rows_from_rows(rows) == [
        {
            "expense_item": "ROW-001",
            "source_row_key": "202601|V-001|Power|1",
            "voucher_no": "V-001",
            "account_level_1": "RD Expense",
            "account_level_2": "Direct Input",
            "account_level_3": "Power",
            "account_level_4": "Electricity",
            "amount": Decimal("1200.50"),
            "direct_project": "RD-CAP",
        }
    ]


def test_expense_items_from_rows_rejects_duplicate_source_row_key():
    rows = [
        SimpleNamespace(name="ROW-001", amount="100", account_level_3="Power", category="direct_input", direct_project=None, source_row_key="dup"),
        SimpleNamespace(name="ROW-002", amount="200", account_level_3="Water", category="direct_input", direct_project=None, source_row_key="dup"),
    ]

    with pytest.raises(ValueError, match="Duplicate GL source row in import: dup"):
        expense_items_from_rows(rows)
