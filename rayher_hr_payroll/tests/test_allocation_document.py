from decimal import Decimal

from rayher_hr_payroll.rd_cost.document_builder import populate_allocation_document
from rayher_hr_payroll.rd_cost.types import ExpenseItem, ProjectHour


class FakeDoc:
    def set(self, fieldname, value):
        setattr(self, fieldname, value)

    def append(self, fieldname, value):
        getattr(self, fieldname).append(value)


def test_populate_allocation_document_writes_lines_and_snapshots():
    doc = FakeDoc()
    expenses = [
        ExpenseItem(
            name="ROW-001",
            amount=Decimal("1000.00"),
            account_level_3="Power",
            category="direct_input",
        )
    ]
    project_hours = [
        ProjectHour(project="RD-CAP", hours=Decimal("60"), stage="capitalized"),
        ProjectHour(project="RD-EXP", hours=Decimal("40"), stage="expensed"),
    ]
    hour_rows = [{"timesheet": "TS-1", "timesheet_detail": "TSD-1", "employee": "EMP-1", "project": "RD-CAP", "posting_date": "2026-01-05", "hours": 6}]
    expense_rows = [
        {
            "expense_item": "ROW-001",
            "source_row_key": "202601|V-001|Power|1",
            "voucher_no": "V-001",
            "account_level_1": "RD Expense",
            "account_level_2": "Direct Input",
            "account_level_3": "Power",
            "account_level_4": "",
            "amount": Decimal("1000.00"),
            "direct_project": None,
        }
    ]

    populate_allocation_document(
        doc,
        expenses=expenses,
        source_hour_rows=hour_rows,
        source_expense_rows=expense_rows,
        project_hours=project_hours,
    )

    assert doc.capitalized_total == Decimal("600.00")
    assert doc.expensed_total == Decimal("400.00")
    assert doc.unknown_total == Decimal("0.00")
    assert doc.status == "Calculated"
    assert doc.hour_snapshots == hour_rows
    assert doc.expense_snapshots == expense_rows
    assert {row["project"]: row["allocated_amount"] for row in doc.lines} == {
        "RD-CAP": Decimal("600.00"),
        "RD-EXP": Decimal("400.00"),
    }
    assert {row["project"]: row["ratio"] for row in doc.lines} == {
        "RD-CAP": 60.0,
        "RD-EXP": 40.0,
    }


def test_populate_allocation_document_writes_unknown_total():
    doc = FakeDoc()

    populate_allocation_document(
        doc,
        expenses=[ExpenseItem(name="ROW-UNKNOWN", amount=Decimal("100.00"), account_level_3="Power", category="direct_input")],
        source_hour_rows=[],
        source_expense_rows=[{"expense_item": "ROW-UNKNOWN", "voucher_no": "V-UNKNOWN"}],
        project_hours=[ProjectHour(project="RD-UNKNOWN", hours=Decimal("8"), stage="unknown")],
    )

    assert doc.capitalized_total == Decimal("0.00")
    assert doc.expensed_total == Decimal("0.00")
    assert doc.unknown_total == Decimal("100.00")
    assert doc.lines[0]["project_stage"] == "unknown"



def test_populate_allocation_document_uses_the_most_specific_expense_account_level():
    doc = FakeDoc()
    expenses = [
        ExpenseItem(
            name="ROW-PENSION",
            amount=Decimal("100.00"),
            account_level_3="\u793e\u4f1a\u4fdd\u9669\u8d39\u7528\uff08\u5355\u4f4d\uff09",
            category="personnel",
        ),
        ExpenseItem(
            name="ROW-TRAVEL",
            amount=Decimal("50.00"),
            account_level_3="\u5dee\u65c5\u8d39",
            category="other",
        ),
    ]
    project_hours = [ProjectHour(project="RD-CAP", hours=Decimal("10"), stage="capitalized")]
    expense_rows = [
        {
            "expense_item": "ROW-PENSION",
            "source_row_key": "202606|119|pension",
            "voucher_no": "119",
            "account_level_1": "\u7814\u53d1\u652f\u51fa",
            "account_level_2": "\u4eba\u5458\u4eba\u5de5\u8d39\u7528",
            "account_level_3": "\u793e\u4f1a\u4fdd\u9669\u8d39\u7528\uff08\u5355\u4f4d\uff09",
            "account_level_4": "\u517b\u8001\u4fdd\u9669",
            "amount": Decimal("100.00"),
            "direct_project": None,
        },
        {
            "expense_item": "ROW-TRAVEL",
            "source_row_key": "202606|144|travel",
            "voucher_no": "144",
            "account_level_1": "\u7814\u53d1\u652f\u51fa",
            "account_level_2": "\u5176\u4ed6\u76f8\u5173\u8d39\u7528",
            "account_level_3": "\u5dee\u65c5\u8d39",
            "account_level_4": "",
            "amount": Decimal("50.00"),
            "direct_project": None,
        },
    ]

    populate_allocation_document(
        doc,
        expenses=expenses,
        source_hour_rows=[],
        source_expense_rows=expense_rows,
        project_hours=project_hours,
    )

    by_voucher = {row["voucher_no"]: row for row in doc.lines}
    assert by_voucher["119"]["expense_item_name"] == "\u517b\u8001\u4fdd\u9669"
    assert by_voucher["119"]["account_level_3"] == "\u793e\u4f1a\u4fdd\u9669\u8d39\u7528\uff08\u5355\u4f4d\uff09"
    assert by_voucher["119"]["account_level_4"] == "\u517b\u8001\u4fdd\u9669"
    assert by_voucher["144"]["expense_item_name"] == "\u5dee\u65c5\u8d39"
    assert by_voucher["144"]["account_level_3"] == "\u5dee\u65c5\u8d39"
    assert by_voucher["144"]["account_level_4"] == ""
