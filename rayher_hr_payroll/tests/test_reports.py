from decimal import Decimal
from types import SimpleNamespace

import pytest

from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix.rd_allocation_matrix import (
    build_allocation_matrix,
)
from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import (
    build_timesheet_exception_rows,
)


def test_build_allocation_matrix_pivots_projects_to_columns():
    lines = [
        SimpleNamespace(voucher_no="V-001", expense_item_name="ROW-001", project="RD-CAP", allocated_amount=Decimal("600.00")),
        SimpleNamespace(voucher_no="V-001", expense_item_name="ROW-001", project="RD-EXP", allocated_amount=Decimal("400.00")),
        SimpleNamespace(voucher_no="V-002", expense_item_name="ROW-002", project="RD-CAP", allocated_amount=Decimal("120.00")),
    ]

    columns, rows = build_allocation_matrix(lines)

    assert [(column["label"], column["fieldname"]) for column in columns] == [
        ("Voucher No", "voucher_no"),
        ("Expense Item", "expense_item_name"),
        ("RD-CAP", "project_1"),
        ("RD-EXP", "project_2"),
    ]
    assert rows == [
        {
            "voucher_no": "V-001",
            "expense_item_name": "ROW-001",
            "project_1": Decimal("600.00"),
            "project_2": Decimal("400.00"),
        },
        {
            "voucher_no": "V-002",
            "expense_item_name": "ROW-002",
            "project_1": Decimal("120.00"),
        },
    ]


def test_build_timesheet_exception_rows_reports_missing_hours():
    employees = [
        SimpleNamespace(name="EMP-001", employee_name="Alice"),
        SimpleNamespace(name="EMP-002", employee_name="Bob"),
    ]
    hours_by_employee = {"EMP-001": Decimal("8.0"), "EMP-002": Decimal("0")}

    rows = build_timesheet_exception_rows(
        employees,
        hours_by_employee=hours_by_employee,
        year=2026,
        month=1,
    )

    assert rows == [
        {
            "employee": "EMP-002",
            "employee_name": "Bob",
            "exception_type": "Missing Timesheet",
            "message": "2026-01 has no submitted timesheet hours.",
        }
    ]

def test_build_unclassified_rd_rows_flags_hours_without_rd_type():
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import (
        build_unclassified_rd_rows,
    )

    logs = [
        {"employee": "EMP-1", "employee_name": "Alice", "rd_personnel_type": "全时研发", "hours": Decimal("8")},
        {"employee": "EMP-2", "employee_name": "Bob", "rd_personnel_type": None, "hours": Decimal("6")},
        {"employee": "EMP-3", "employee_name": "Cara", "rd_personnel_type": "非研发", "hours": Decimal("5")},
    ]
    rows = build_unclassified_rd_rows(logs)

    assert {r["employee"] for r in rows} == {"EMP-2", "EMP-3"}
    assert all(r["exception_type"] == "Unclassified R&D Hours" for r in rows)


def test_build_allocation_matrix_translates_static_columns():
    lines = [
        SimpleNamespace(voucher_no='V-001', expense_item_name='ROW-001', project='RD-CAP', allocated_amount=Decimal('600.00')),
    ]

    columns, _rows = build_allocation_matrix(lines, translate=lambda text: f'T:{text}')

    assert columns[0]['label'] == 'T:Voucher No'
    assert columns[1]['label'] == 'T:Expense Item'


def test_build_timesheet_exception_rows_translates_labels_and_message_template():
    employees = [SimpleNamespace(name='EMP-002', employee_name='Bob')]

    rows = build_timesheet_exception_rows(
        employees,
        hours_by_employee={'EMP-002': Decimal('0')},
        year=2026,
        month=1,
        translate=lambda text: f'T:{text}',
    )

    assert rows[0]['exception_type'] == 'T:Missing Timesheet'
    assert rows[0]['message'] == 'T:2026-01 has no submitted timesheet hours.'


def test_build_unclassified_rd_rows_translates_labels_and_message_template():
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import (
        build_unclassified_rd_rows,
    )

    rows = build_unclassified_rd_rows(
        [{'employee': 'EMP-2', 'employee_name': 'Bob', 'rd_personnel_type': None, 'hours': Decimal('6')}],
        translate=lambda text: f'T:{text}',
    )

    assert rows[0]['exception_type'] == 'T:Unclassified R&D Hours'
    assert rows[0]['message'].startswith('T:Logged 6 h on R&D projects')
    assert rows[0]['message'].endswith('excluded from R&D allocation.')


def test_allocation_matrix_uses_safe_project_fieldnames_and_accumulates_duplicate_cells():
    lines = [
        SimpleNamespace(voucher_no="V-001", expense_item_name="ITEM-1", project="voucher_no", allocated_amount=Decimal("10.00")),
        SimpleNamespace(voucher_no="V-001", expense_item_name="ITEM-1", project="RD CAP", allocated_amount=Decimal("2.50")),
        SimpleNamespace(voucher_no="V-001", expense_item_name="ITEM-1", project="RD CAP", allocated_amount=Decimal("7.50")),
    ]

    columns, rows = build_allocation_matrix(lines)

    project_columns = {column["label"]: column["fieldname"] for column in columns[2:]}
    assert set(project_columns) == {"RD CAP", "voucher_no"}
    assert project_columns["voucher_no"] != "voucher_no"
    assert project_columns["RD CAP"] != "RD CAP"
    assert rows == [
        {
            "voucher_no": "V-001",
            "expense_item_name": "ITEM-1",
            project_columns["RD CAP"]: Decimal("10.00"),
            project_columns["voucher_no"]: Decimal("10.00"),
        }
    ]


class ReportRuleError(Exception):
    pass


def report_throw(message):
    raise ReportRuleError(str(message))


def test_parse_year_month_filters_requires_both_values():
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import parse_year_month_filters

    with pytest.raises(ReportRuleError, match="Year and month filters are required"):
        parse_year_month_filters({}, throw=report_throw)


def test_parse_year_month_filters_accepts_numeric_strings():
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_timesheet_exceptions.rd_timesheet_exceptions import parse_year_month_filters

    assert parse_year_month_filters({"year": "2026", "month": "1"}, throw=report_throw) == (2026, 1)
