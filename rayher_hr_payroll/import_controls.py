from __future__ import annotations

from typing import Any, Callable


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def ensure_unique_submitted_period(
    period: str | None,
    *,
    current_name: str | None,
    find_conflict: Callable[[str, str | None], Any],
    throw: Callable[[str], None],
) -> None:
    """G3: reject a GL import for a period that already has another submitted import.
    Without this, the same period imported twice is allocated twice and double-counts
    R&D cost."""
    if not period:
        return
    conflict = find_conflict(period, current_name)
    if conflict:
        throw(
            f"A submitted RD Expense Import already exists for period {period} "
            f"({conflict}); importing the same period twice would double-count R&D cost."
        )


def validate_expense_import(doc: Any, method: str | None = None) -> None:
    frappe = _get_frappe()

    def _find_conflict(period: str, current_name: str | None):
        return frappe.db.exists(
            "RD Expense Import",
            {"period": period, "docstatus": 1, "name": ["!=", current_name or "__new__"]},
        )

    ensure_unique_submitted_period(
        getattr(doc, "period", None),
        current_name=getattr(doc, "name", None),
        find_conflict=_find_conflict,
        throw=frappe.throw,
    )
