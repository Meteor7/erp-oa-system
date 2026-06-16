from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

RD_PERSONNEL_TYPES = ("全时研发", "非全时研发", "研发辅助")


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def _value(row: Any, fieldname: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def build_timesheet_exception_rows(
    employees: Iterable[Any],
    *,
    hours_by_employee: Mapping[str, Decimal],
    year: int,
    month: int,
) -> list[dict[str, Any]]:
    rows = []
    for employee in employees:
        employee_id = str(_value(employee, "name"))
        hours = Decimal(str(hours_by_employee.get(employee_id, Decimal("0")) or 0))
        if hours <= 0:
            rows.append(
                {
                    "employee": employee_id,
                    "employee_name": _value(employee, "employee_name"),
                    "exception_type": "Missing Timesheet",
                    "message": f"{year}-{month:02d} has no submitted timesheet hours.",
                }
            )
    return rows


def build_unclassified_rd_rows(rd_hour_logs: Iterable[Any]) -> list[dict[str, Any]]:
    """G1: employees who logged hours on R&D projects but whose rd_personnel_type is
    unset or non-R&D are silently dropped from the allocation SQL. Surface them so the
    data trap is visible instead of producing a quietly wrong allocation."""
    rows = []
    for log in rd_hour_logs:
        ptype = _value(log, "rd_personnel_type")
        hours = Decimal(str(_value(log, "hours", 0) or 0))
        if hours > 0 and ptype not in RD_PERSONNEL_TYPES:
            rows.append(
                {
                    "employee": str(_value(log, "employee")),
                    "employee_name": _value(log, "employee_name"),
                    "exception_type": "Unclassified R&D Hours",
                    "message": (
                        f"Logged {hours} h on R&D projects but rd_personnel_type is "
                        f"'{ptype or '(unset)'}'; excluded from R&D allocation."
                    ),
                }
            )
    return rows


def _columns() -> list[dict[str, Any]]:
    return [
        {"label": "Employee", "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
        {"label": "Employee Name", "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
        {"label": "Exception Type", "fieldname": "exception_type", "fieldtype": "Data", "width": 180},
        {"label": "Message", "fieldname": "message", "fieldtype": "Data", "width": 420},
    ]


def execute(filters=None):
    filters = filters or {}
    year = int(filters.get("year"))
    month = int(filters.get("month"))
    frappe = _get_frappe()

    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active", "rd_personnel_type": ["in", RD_PERSONNEL_TYPES]},
        fields=["name", "employee_name"],
        order_by="employee_name",
    )
    hour_rows = frappe.db.sql(
        """
        select ts.employee, coalesce(sum(tsd.hours), 0) as hours
          from `tabTimesheet Detail` tsd
          inner join `tabTimesheet` ts on ts.name = tsd.parent
         where ts.docstatus = 1
           and year(tsd.from_time) = %(year)s
           and month(tsd.from_time) = %(month)s
         group by ts.employee
        """,
        {"year": year, "month": month},
        as_dict=True,
    )
    hours_by_employee = {str(row.employee): Decimal(str(row.hours or 0)) for row in hour_rows}

    # G1: anyone with R&D-project hours whose personnel type excludes them from allocation
    rd_hour_logs = frappe.db.sql(
        """
        select e.name as employee, e.employee_name, e.rd_personnel_type,
               coalesce(sum(tsd.hours), 0) as hours
          from `tabTimesheet Detail` tsd
          inner join `tabTimesheet` ts on ts.name = tsd.parent
          inner join `tabEmployee` e on e.name = ts.employee
          inner join `tabProject` p on p.name = tsd.project
         where ts.docstatus = 1
           and year(tsd.from_time) = %(year)s
           and month(tsd.from_time) = %(month)s
           and coalesce(p.allow_rd_timesheet, 0) = 1
         group by e.name
        """,
        {"year": year, "month": month},
        as_dict=True,
    )

    rows = build_timesheet_exception_rows(
        employees, hours_by_employee=hours_by_employee, year=year, month=month
    )
    rows += build_unclassified_rd_rows(rd_hour_logs)
    return _columns(), rows
