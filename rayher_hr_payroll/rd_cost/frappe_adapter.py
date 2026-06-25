from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
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
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).split()[0]
    year, month, day = text.split("-")
    return date(int(year), int(month), int(day))


_LEGACY_SOURCE_ROW_KEY_FIELDS = (
    "voucher_no",
    "account_level_1",
    "account_level_2",
    "account_level_3",
    "account_level_4",
    "amount",
    "direct_project",
)


def content_row_key_for_row(row: Any) -> str:
    """Content-only key that ignores any explicit source_row_key: two GL rows with the
    same voucher / account path / amount collide even when given different source_row_keys,
    so a manually re-keyed duplicate cannot slip past the submit-time dedup. NOTE: this
    treats byte-identical GL lines (same voucher+account path+amount) as duplicates; if a
    source ledger legitimately posts two identical lines distinguished only by their GL
    line id, that key would need to be folded in here."""
    parts = [str(_value(row, fieldname)).strip() for fieldname in _LEGACY_SOURCE_ROW_KEY_FIELDS]
    return "content|" + "|".join(parts)


def source_row_key_for_row(row: Any) -> str:
    raw_source_row_key = _value(row, "source_row_key")
    source_row_key = str(raw_source_row_key).strip() if raw_source_row_key is not None else ""
    if source_row_key:
        return source_row_key
    parts = [str(_value(row, fieldname)).strip() for fieldname in _LEGACY_SOURCE_ROW_KEY_FIELDS]
    return "legacy|" + "|".join(parts)


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
        source_row_key = source_row_key_for_row(row)
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
                "source_row_key": source_row_key_for_row(row),
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


def project_hours_from_rows(
    rows: Iterable[Any],
    *,
    year: int,
    month: int,
    get_project_fields=None,
) -> list[ProjectHour]:
    if get_project_fields is None:
        frappe = _get_frappe()

        def get_project_fields(project: str):
            return frappe.db.get_value(
                "Project",
                project,
                ["capitalization_start_date", "capitalization_end_date"],
                as_dict=True,
            ) or {}

    hours_by_project: dict[str, Decimal] = {}
    for row in rows:
        project = str(_value(row, "project"))
        hours_by_project[project] = hours_by_project.get(project, Decimal("0")) + Decimal(
            str(_value(row, "hours", 0) or 0)
        )

    result = []
    for project, hours in sorted(hours_by_project.items()):
        result.append(
            ProjectHour(
                project=project,
                hours=hours,
                stage=stage_for_period(get_project_fields(project), year=year, month=month),
            )
        )
    return result


def get_project_hours(*, year: int, month: int) -> list[ProjectHour]:
    return project_hours_from_rows(get_project_hour_rows(year=year, month=month), year=year, month=month)


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


def ensure_direct_project_stages(
    project_hours: list[ProjectHour],
    expenses: list[ExpenseItem],
    *,
    year: int,
    month: int,
) -> list[ProjectHour]:
    """G2: a GL line directly attributed to a project that logged no hours this
    period must still be classified by that project's real capitalization stage.
    Resolve each such project's stage from its dates and merge it in at zero hours."""
    from rayher_hr_payroll.rd_cost.allocation import merge_direct_project_stages

    frappe = _get_frappe()
    present = {ph.project for ph in project_hours}
    stage_by_project: dict[str, ProjectStage] = {}
    for expense in expenses:
        dp = expense.direct_project
        if dp and dp not in present and dp not in stage_by_project:
            fields = (
                frappe.db.get_value(
                    "Project",
                    dp,
                    ["capitalization_start_date", "capitalization_end_date"],
                    as_dict=True,
                )
                or {}
            )
            stage_by_project[dp] = stage_for_period(fields, year=year, month=month)
    if not stage_by_project:
        return project_hours
    return merge_direct_project_stages(project_hours, stage_by_project)
