"""Pure validation rules shared by the invoice OCR workflow."""

import unicodedata
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


# 全电发票（数电票）的发票号码是 20 位；老版增值税发票是"发票代码（10 或 12 位）+ 发票号码（8 位）"。
FULL_DIGITAL_NUMBER_LENGTH = 20


def normalize_invoice_number(value):
    """发票号码、发票代码的统一写法（2026-09-28）：全角转半角（NFKC）、去掉所有空白、字母转大写。"""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return "".join(text.split()).upper()


def business_key(invoice_number, invoice_code=None):
    """同一张发票的判定键。决定（2026-09-24）：只看发票号码。

    全电发票（20 位号码）只看号码；老版发票看"发票代码-发票号码"。开票日期和金额不参与：
    原来按"号码|日期|合计"判断，改一下日期或金额就能把同一张发票报两次。
    号码为空时返回 None——没有号码的发票不能确认（见 service.confirm_invoice）。
    """
    number = normalize_invoice_number(invoice_number)
    if not number:
        return None
    code = normalize_invoice_number(invoice_code)
    if code and len(number) != FULL_DIGITAL_NUMBER_LENGTH:
        return f"{code}-{number}"
    return number


def same_invoice(number_a, code_a, number_b, code_b):
    """两条记录是不是同一张发票：号码相同；老版发票两边都识别出代码时，代码也要相同。

    只有一边识别出代码时按号码算同一张——宁可多标疑似重复，由财务复核。
    """
    left = normalize_invoice_number(number_a)
    if not left or left != normalize_invoice_number(number_b):
        return False
    if len(left) == FULL_DIGITAL_NUMBER_LENGTH:
        return True
    left_code, right_code = normalize_invoice_number(code_a), normalize_invoice_number(code_b)
    return not (left_code and right_code and left_code != right_code)


def legacy_business_key(invoice_number, issue_date, total_amount):
    """2026-09-28 之前的判定键（号码|日期|合计），只用来识别当时财务已解除的疑似重复。"""
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