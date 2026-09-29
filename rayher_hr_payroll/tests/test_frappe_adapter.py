from decimal import Decimal
from datetime import date
from types import SimpleNamespace

import pytest

from rayher_hr_payroll.rd_cost.frappe_adapter import (
    content_row_key_for_row,
    expense_items_from_rows,
    foreign_commissioned_expense_rows,
    historical_org_for_date,
    is_foreign_commissioned_expense,
    non_foreign_expense_rows,
    source_expense_rows_from_rows,
    stage_for_period,
)
from rayher_hr_payroll.rd_cost import frappe_adapter


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


def test_generated_monthly_hours_use_month_end_for_org_history(monkeypatch):
    captured = {}

    class FakeDB:
        @staticmethod
        def sql(query, values, as_dict=False):
            captured["query"] = query
            return [
                SimpleNamespace(
                    timesheet="TS-MONTHLY",
                    timesheet_detail="TSD-1",
                    employee="EMP-1",
                    fallback_department="Current",
                    fallback_designation="Current Role",
                    employee_rd_personnel_type="非全时研发",
                    project="PROJ-1",
                    posting_date=date(2026, 7, 1),
                    rd_system_generated=1,
                    hours=8,
                )
            ]

    fake_frappe = SimpleNamespace(
        db=FakeDB(),
        get_all=lambda *args, **kwargs: [
            SimpleNamespace(from_date="2026-07-15", department="New Department", designation="New Role")
        ],
    )
    monkeypatch.setattr(frappe_adapter, "_get_frappe", lambda: fake_frappe)

    rows = frappe_adapter.get_project_hour_rows(year=2026, month=7)

    assert "ts.rd_system_generated" in captured["query"]
    assert rows[0]["posting_date"] == date(2026, 7, 31)
    assert rows[0]["employee_department"] == "New Department"
    assert rows[0]["employee_designation"] == "New Role"
    # 审查 X2-6：快照带分摊时的人员类型；17-c：历史按研发项目编号取，不看 allow_rd_timesheet。
    assert rows[0]["employee_rd_personnel_type"] == "非全时研发"
    assert "p.rd_project_code" in captured["query"] and "allow_rd_timesheet" not in captured["query"]


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


def legacy_row(name, source_row_key=None):
    return SimpleNamespace(
        name=name,
        amount="100",
        voucher_no="V-001",
        account_level_1="RD Expense",
        account_level_2="Direct Input",
        account_level_3="Power",
        account_level_4="Electricity",
        category="direct_input",
        direct_project=None,
        source_row_key=source_row_key,
    )


def test_expense_items_from_rows_rejects_duplicate_legacy_rows_without_source_row_key():
    rows = [legacy_row("ROW-001"), legacy_row("ROW-002", source_row_key="   ")]

    with pytest.raises(ValueError, match="Duplicate GL source row in import: legacy"):
        expense_items_from_rows(rows)


def test_source_expense_rows_from_rows_populates_fallback_source_row_key():
    rows = [legacy_row("ROW-001")]

    snapshots = source_expense_rows_from_rows(rows)

    assert snapshots[0]["source_row_key"].startswith("legacy|V-001|RD Expense|Direct Input|Power|Electricity|100|None")


def test_historical_org_for_date_accepts_datetime_strings_with_time():
    history_rows = [SimpleNamespace(from_date="2026-01-01 00:00:00", department="RD", designation="Engineer")]

    org = historical_org_for_date(
        history_rows,
        "2026-01-05 09:30:00",
        fallback_department="Current",
        fallback_designation="Current",
    )

    assert org == {"employee_department": "RD", "employee_designation": "Engineer"}


def _gl_row(amount="100", source_row_key=""):
    return SimpleNamespace(
        voucher_no="V-001", account_level_1="A", account_level_2="B",
        account_level_3="C", account_level_4="D", amount=amount,
        direct_project=None, source_row_key=source_row_key,
    )


def test_content_row_key_ignores_explicit_source_row_key():
    # identical content with DIFFERENT explicit source_row_keys must collide so the
    # import submit dedup catches a re-keyed duplicate
    assert content_row_key_for_row(_gl_row(source_row_key="R1")) == content_row_key_for_row(_gl_row(source_row_key="R2"))


def test_content_row_key_differs_on_amount():
    assert content_row_key_for_row(_gl_row(amount="100")) != content_row_key_for_row(_gl_row(amount="200"))


def test_content_row_key_normalizes_amount():
    # "100" / 100 / "100.00" are the same GL amount and must collide
    assert content_row_key_for_row(_gl_row(amount="100")) == content_row_key_for_row(_gl_row(amount=100))
    assert content_row_key_for_row(_gl_row(amount="100")) == content_row_key_for_row(_gl_row(amount="100.00"))
    assert content_row_key_for_row(_gl_row(amount="100")) != content_row_key_for_row(_gl_row(amount="100.01"))


def test_content_row_key_treats_none_and_blank_optional_field_the_same():
    a = SimpleNamespace(voucher_no="V-001", account_level_1="A", account_level_2="B",
                        account_level_3="C", account_level_4=None, amount="100",
                        direct_project=None, source_row_key="")
    b = SimpleNamespace(voucher_no="V-001", account_level_1="A", account_level_2="B",
                        account_level_3="C", account_level_4="", amount="100",
                        direct_project="", source_row_key="")
    # one leaves optional fields unset (None), the other sends them blank ("") -> still a duplicate
    assert content_row_key_for_row(a) == content_row_key_for_row(b)


def test_stage_for_period_prefers_backend_rd_stage():
    assert stage_for_period({"rd_stage": "资本化"}, year=2026, month=7) == "capitalized"
    assert stage_for_period({"rd_stage": "费用化", "capitalization_start_date": "2026-01-01", "capitalization_end_date": "2026-12-31"}, year=2026, month=7) == "expensed"



def _commission_row(name, level_2, level_3, amount="100", direct_project=None):
    return SimpleNamespace(
        name=name,
        voucher_no=f"V-{name}",
        account_level_1="\u7814\u53d1\u652f\u51fa",
        account_level_2=level_2,
        account_level_3=level_3,
        account_level_4="Sabri\u8d39\u7528",
        amount=amount,
        category="other",
        direct_project=direct_project,
        source_row_key=f"KEY-{name}",
    )


def test_foreign_commissioned_expense_rows_are_classified_and_removed_from_domestic_allocation():
    foreign_common = _commission_row("FOREIGN-COMMON", " \u59d4\u6258\u7814\u53d1 ", " \u5883\u5916 ")
    foreign_direct = _commission_row("FOREIGN-DIRECT", "\u59d4\u6258\u7814\u53d1", "\u5883\u5916", direct_project="RD15")
    domestic_commission = _commission_row("DOMESTIC", "\u59d4\u6258\u7814\u53d1", "\u5883\u5185")
    other_row = _commission_row("OTHER", "\u5176\u4ed6\u76f8\u5173\u8d39\u7528", "\u5dee\u65c5\u8d39")
    rows = [foreign_common, domestic_commission, foreign_direct, other_row]

    assert is_foreign_commissioned_expense(foreign_common) is True
    assert is_foreign_commissioned_expense(domestic_commission) is False
    assert [row.name for row in foreign_commissioned_expense_rows(rows)] == ["FOREIGN-COMMON", "FOREIGN-DIRECT"]
    assert [row.name for row in non_foreign_expense_rows(rows)] == ["DOMESTIC", "OTHER"]
