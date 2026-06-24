from __future__ import annotations

from typing import Any, Callable


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def _identity(text: str) -> str:
    return text


def _to_date(value: Any):
    from datetime import date as _date
    if value is None:
        return None
    if isinstance(value, _date):
        return value
    try:
        return _date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _work_dates(doc: Any):
    from datetime import timedelta as _timedelta
    start = getattr(doc, 'work_from_date', None)
    end = getattr(doc, 'work_end_date', None)
    if not start and not end:
        return []
    if not end or end == start:
        return [start or end]
    s, e = _to_date(start), _to_date(end)
    if s is None or e is None:
        return [d for d in (start, end) if d]
    if e < s:
        s, e = e, s
    out, cur = [], s
    while cur <= e:
        out.append(cur.isoformat())
        cur += _timedelta(days=1)
    return out


def validate_compensatory_leave_dates(
    doc: Any,
    *,
    is_statutory_holiday: Callable[[Any], bool],
    throw: Callable[[str], None],
    translate: Callable[[str], str] = _identity,
) -> None:
    for work_date in _work_dates(doc):
        if is_statutory_holiday(work_date):
            throw(
                translate(
                    'Statutory holiday overtime cannot be converted into compensatory leave; '
                    'it must be paid according to policy.'
                )
            )
            return


def _is_statutory_holiday(attendance_date: Any) -> bool:
    frappe = _get_frappe()
    return bool(
        frappe.db.exists(
            'Holiday',
            {'holiday_date': attendance_date, 'weekly_off': 0},
        )
    )


def validate_compensatory_leave_request(doc: Any, method: str | None = None) -> None:
    frappe = _get_frappe()
    validate_compensatory_leave_dates(
        doc,
        is_statutory_holiday=_is_statutory_holiday,
        throw=frappe.throw,
        translate=frappe._,
    )
