from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from rayher_hr_payroll.rd_cost.types import ExpenseItem, ProjectHour, ProjectStage

RD_PERSONNEL_TYPES = ("全时研发", "非全时研发", "研发辅助")


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def _value(row: Any, fieldname: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    year, month, day = str(value).split("-")
    return date(int(year), int(month), int(day))


def stage_for_period(project: Mapping[str, Any], *, year: int, month: int) -> ProjectStage:
    start = _parse_date(project.get("capitalization_start_date"))
    end = _parse_date(project.get("capitalization_end_date"))
    if not start or not end:
        return "unknown"
    current = date(int(year), int(month), 1)
    return "capitalized" if start <= current <= end else "expensed"


def historical_org_for_date(
    history_rows: Iterable[Any],
    posting_date: Any,
    *,
    fallback_department: str | None = None,
    fallback_designation: str | None = None,
) -> dict[str, str | None]:
    posting = _parse_date(posting_date)
    chosen = None
    chosen_from_date = None

    if posting:
        for row in history_rows:
            from_date = _parse_date(_value(row, "from_date"))
            if from_date and from_date <= posting:
                if chosen_from_date is None or from_date > chosen_from_date:
                    chosen = row
                    chosen_from_date = from_date

    if chosen is None:
        return {
            "employee_department": fallback_department,
            "employee_designation": fallback_designation,
        }

    return {
        "employee_department": _value(chosen, "department", fallback_department),
        "employee_designation": _value(chosen, "designation", fallback_designation),
    }


def expense_items_from_rows(rows: Iterable[Any], *, on_duplicate=None) -> list[ExpenseItem]:
    seen: set[str] = set()
    result: list[ExpenseItem] = []

    for row in rows:
        source_row_key = _value(row, "source_row_key")
        if source_row_key in seen:
            message = f"Duplicate GL source row in import: {source_row_key}"
            if on_duplicate:
                on_duplicate(message)
            raise ValueError(message)
        seen.add(source_row_key)

        direct_project = _value(row, "direct_project") or None
        result.append(
            ExpenseItem(
                name=str(_value(row, "name")),
                amount=Decimal(str(_value(row, "amount") or 0)),
                account_level_3=str(_value(row, "account_level_3") or ""),
                category=str(_value(row, "category") or ""),
                direct_project=direct_project,
            )
        )

    return result


def source_expense_rows_from_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        result.append(
            {
                "expense_item": str(_value(row, "name")),
                "source_row_key": _value(row, "source_row_key"),
                "voucher_no": _value(row, "voucher_no"),
                "account_level_1": _value(row, "account_level_1"),
                "account_level_2": _value(row, "account_level_2"),
                "account_level_3": _value(row, "account_level_3"),
                "account_level_4": _value(row, "account_level_4"),
                "amount": _value(row, "amount"),
                "direct_project": _value(row, "direct_project") or None,
            }
        )
    return result


def _employee_history_rows(employee: str) -> list[dict[str, Any]]:
    frappe = _get_frappe()
    return frappe.get_all(
        "Employee Internal Work History",
        filters={"parent": employee},
        fields=["from_date", "department", "designation"],
        order_by="from_date asc",
    )


def get_project_hour_rows(*, year: int, month: int) -> list[dict[str, Any]]:
    frappe = _get_frappe()
    rows = frappe.db.sql(
        """
        select ts.name as timesheet,
               tsd.name as timesheet_detail,
               ts.employee,
               e.department as fallback_department,
               e.designation as fallback_designation,
               tsd.project,
               date(tsd.from_time) as posting_date,
               tsd.hours
          from `tabTimesheet Detail` tsd
          inner join `tabTimesheet` ts on ts.name = tsd.parent
          inner join `tabProject` p on p.name = tsd.project
          inner join `tabEmployee` e on e.name = ts.employee
         where ts.docstatus = 1
           and month(tsd.from_time) = %(month)s
           and year(tsd.from_time) = %(year)s
           and coalesce(p.allow_rd_timesheet, 0) = 1
           and e.rd_personnel_type in %(rd_personnel_types)s
        """,
        {"year": year, "month": month, "rd_personnel_types": RD_PERSONNEL_TYPES},
        as_dict=True,
    )

    snapshot_rows = []
    for row in rows:
        org = historical_org_for_date(
            _employee_history_rows(row.employee),
            row.posting_date,
            fallback_department=row.fallback_department,
            fallback_designation=row.fallback_designation,
        )
        snapshot_rows.append(
            {
                "timesheet": row.timesheet,
                "timesheet_detail": row.timesheet_detail,
                "employee": row.employee,
                "employee_department": org["employee_department"],
                "employee_designation": org["employee_designation"],
                "project": row.project,
                "posting_date": row.posting_date,
                "hours": row.hours,
            }
        )
    return snapshot_rows


def get_project_hours(*, year: int, month: int) -> list[ProjectHour]:
    frappe = _get_frappe()
    hours_by_project: dict[str, Decimal] = {}
    for row in get_project_hour_rows(year=year, month=month):
        project = str(row["project"])
        hours_by_project[project] = hours_by_project.get(project, Decimal("0")) + Decimal(
            str(row["hours"] or 0)
        )

    result = []
    for project, hours in sorted(hours_by_project.items()):
        project_fields = frappe.db.get_value(
            "Project",
            project,
            ["capitalization_start_date", "capitalization_end_date"],
            as_dict=True,
        ) or {}
        result.append(
            ProjectHour(
                project=project,
                hours=hours,
                stage=stage_for_period(project_fields, year=year, month=month),
            )
        )
    return result


def _expense_import_rows(expense_import: str) -> list[Any]:
    frappe = _get_frappe()
    doc = frappe.get_doc("RD Expense Import", expense_import)
    return list(doc.items)


def get_expense_items(expense_import: str) -> list[ExpenseItem]:
    frappe = _get_frappe()
    return expense_items_from_rows(_expense_import_rows(expense_import), on_duplicate=frappe.throw)


def get_source_expense_rows(expense_import: str) -> list[dict[str, Any]]:
    frappe = _get_frappe()
    rows = _expense_import_rows(expense_import)
    expense_items_from_rows(rows, on_duplicate=frappe.throw)
    return source_expense_rows_from_rows(rows)
