from __future__ import annotations

from typing import Any, Callable


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def _work_date(doc: Any):
    return getattr(doc, "work_from_date", None) or getattr(doc, "work_end_date", None)


def validate_compensatory_leave_dates(
    doc: Any,
    *,
    is_statutory_holiday: Callable[[Any], bool],
    throw: Callable[[str], None],
) -> None:
    work_date = _work_date(doc)
    if work_date and is_statutory_holiday(work_date):
        throw(
            "Statutory holiday overtime cannot be converted into compensatory leave; "
            "it must be paid according to policy."
        )


def _is_statutory_holiday(attendance_date: Any) -> bool:
    frappe = _get_frappe()
    return bool(
        frappe.db.exists(
            "Holiday",
            {"holiday_date": attendance_date, "weekly_off": 0},
        )
    )


def validate_compensatory_leave_request(doc: Any, method: str | None = None) -> None:
    frappe = _get_frappe()
    validate_compensatory_leave_dates(
        doc,
        is_statutory_holiday=_is_statutory_holiday,
        throw=frappe.throw,
    )