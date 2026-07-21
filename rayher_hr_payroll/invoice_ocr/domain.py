"""Pure validation rules shared by the invoice OCR workflow."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_CENT = Decimal("0.01")
_TOLERANCE = Decimal("0.02")


def _money(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        return number.quantize(_CENT)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _iso_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def business_key(invoice_number, issue_date, total_amount):
    """Return the normalized business duplicate key, or ``None`` if incomplete."""
    number = str(invoice_number or "").strip()
    normalized_date = _iso_date(issue_date)
    amount = _money(total_amount)
    if not number or not normalized_date or amount is None:
        return None
    return f"{number}|{normalized_date}|{amount:.2f}"


def amount_difference(before_tax, tax, total):
    """Return signed ``total - (before_tax + tax)`` when beyond two cents.

    Missing and invalid inputs intentionally return ``None``. This keeps an absent OCR
    candidate distinct from a proven mismatch; required-field handling belongs to the
    confirmation workflow.
    """
    before = _money(before_tax)
    tax_value = _money(tax)
    total_value = _money(total)
    if before is None or tax_value is None or total_value is None:
        return None
    difference = (total_value - (before + tax_value)).quantize(_CENT)
    return None if abs(difference) <= _TOLERANCE else difference


def submission_blockers(records, no_invoice_reason):
    """Return stable, de-duplicated blockers for invoice submission."""
    rows = list(records or [])
    if not rows:
        return [] if str(no_invoice_reason or "").strip() else ["未上传发票，请填写无票原因"]

    messages = {
        "排队中": "发票正在处理中",
        "识别中": "发票正在处理中",
        "待确认": "存在未确认发票",
        "疑似重复": "存在疑似重复发票",
        "失败": "存在识别失败发票",
    }
    resolved = {"已确认", "已排除"}
    blockers = []
    for row in rows:
        status = row.get("recognition_status") if hasattr(row, "get") else getattr(row, "recognition_status", None)
        message = messages.get(status)
        if message is None and status not in resolved:
            message = "存在状态异常发票"
        if message and message not in blockers:
            blockers.append(message)
    return blockers