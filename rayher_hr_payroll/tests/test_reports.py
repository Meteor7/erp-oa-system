from decimal import Decimal
from types import SimpleNamespace

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

    assert [column["fieldname"] for column in columns] == [
        "voucher_no",
        "expense_item_name",
        "RD-CAP",
        "RD-EXP",
    ]
    assert rows == [
        {
            "voucher_no": "V-001",
            "expense_item_name": "ROW-001",
            "RD-CAP": Decimal("600.00"),
            "RD-EXP": Decimal("400.00"),
        },
        {
            "voucher_no": "V-002",
            "expense_item_name": "ROW-002",
            "RD-CAP": Decimal("120.00"),
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
