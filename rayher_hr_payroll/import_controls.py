from __future__ import annotations

from typing import Any, Callable


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def _identity(text: str) -> str:
    return text


def ensure_unique_submitted_period(
    period: str | None,
    *,
    current_name: str | None,
    find_conflict: Callable[[str, str | None], Any],
    throw: Callable[[str], None],
    translate: Callable[[str], str] = _identity,
) -> None:
    if not period:
        return
    conflict = find_conflict(period, current_name)
    if conflict:
        template = (
            'A submitted RD Expense Import already exists for period {0} ({1}); '
            'importing the same period twice would double-count R&D cost.'
        )
        throw(translate(template).format(period, conflict))


def validate_expense_import(doc: Any, method: str | None = None) -> None:
    frappe = _get_frappe()

    def _find_conflict(period: str, current_name: str | None):
        return frappe.db.exists(
            'RD Expense Import',
            {'period': period, 'docstatus': 1, 'name': ['!=', current_name or '__new__']},
        )

    ensure_unique_submitted_period(
        getattr(doc, 'period', None),
        current_name=getattr(doc, 'name', None),
        find_conflict=_find_conflict,
        throw=frappe.throw,
        translate=frappe._,
    )
    # Keep the friendly early error; the derived unique active_period_key on
    # RD Expense Import also arbitrates concurrent inserts at the database.
    period = getattr(doc, 'period', None)
    if period:
        other = frappe.db.exists('RD Expense Import', {
            'period': period,
            'docstatus': ['<', 2],
            'name': ['!=', getattr(doc, 'name', None) or '__new__'],
        })
        if other:
            frappe.throw(frappe._(
                '本期已存在未取消的费用导入单（{0}）；每个会计期间只能有一张，请先取消原单再重建。'
            ).format(other))
