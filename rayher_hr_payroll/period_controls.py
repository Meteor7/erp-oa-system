from __future__ import annotations

from typing import Any, Callable


def _identity(text: str) -> str:
    return text


def normalize_period_fields(
    doc: Any,
    *,
    throw: Callable[[str], None],
    translate: Callable[[str], str] = _identity,
) -> None:
    year = getattr(doc, "year", None)
    month = getattr(doc, "month", None)
    if year in (None, "") or month in (None, ""):
        return

    try:
        year_int = int(year)
        month_int = int(month)
    except (TypeError, ValueError):
        throw(translate("Year and month must be valid numbers."))
        return

    if month_int < 1 or month_int > 12:
        throw(translate("Month must be between 1 and 12."))
        return

    doc.year = year_int
    doc.month = month_int
    doc.period = f"{year_int}{month_int:02d}"
