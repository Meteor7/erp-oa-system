from __future__ import annotations

from datetime import date
from typing import Any, Callable


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    year, month, day = str(value).split("-")
    return date(int(year), int(month), int(day))


def period_from_timesheet(doc: Any) -> str | None:
    start_date = _as_date(getattr(doc, "start_date", None))
    if not start_date:
        return None
    return f"{start_date.year}{start_date.month:02d}"


def ensure_period_unlocked(
    doc: Any,
    *,
    is_period_locked: Callable[[str | None], bool],
    throw: Callable[[str], None],
) -> None:
    period = period_from_timesheet(doc)
    if is_period_locked(period):
        throw(f"R&D period {period} is locked; timesheet changes require a correction workflow.")


def ensure_rd_projects_enabled(
    doc: Any,
    *,
    is_project_enabled: Callable[[str], bool],
    throw: Callable[[str], None],
) -> None:
    for row in getattr(doc, "time_logs", []) or []:
        project = getattr(row, "project", None)
        if project and not is_project_enabled(project):
            throw(f"Project {project} is not enabled for R&D timesheet entry.")


def _is_period_locked(period: str | None) -> bool:
    if not period:
        return False
    frappe = _get_frappe()
    return bool(
        frappe.db.exists(
            "RD Period Lock",
            {"period": period, "docstatus": 1, "lock_timesheets": 1},
        )
    )


def _is_project_enabled(project: str) -> bool:
    frappe = _get_frappe()
    return bool(frappe.db.get_value("Project", project, "allow_rd_timesheet"))


def block_locked_timesheet_change(doc: Any, method: str | None = None) -> None:
    frappe = _get_frappe()
    ensure_period_unlocked(doc, is_period_locked=_is_period_locked, throw=frappe.throw)


def validate_timesheet(doc: Any, method: str | None = None) -> None:
    frappe = _get_frappe()
    ensure_period_unlocked(doc, is_period_locked=_is_period_locked, throw=frappe.throw)
    ensure_rd_projects_enabled(doc, is_project_enabled=_is_project_enabled, throw=frappe.throw)


def on_submit_timesheet(doc: Any, method: str | None = None) -> None:
    frappe = _get_frappe()
    reviewers = set()
    for row in getattr(doc, "time_logs", []) or []:
        project = getattr(row, "project", None)
        if project:
            reviewer = frappe.db.get_value("Project", project, "project_owner")
            if reviewer:
                reviewers.add(reviewer)

    if len(reviewers) == 1 and not getattr(doc, "rd_reviewer", None):
        doc.db_set("rd_reviewer", reviewers.pop(), update_modified=False)