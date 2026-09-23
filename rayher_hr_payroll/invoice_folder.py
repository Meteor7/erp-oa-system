"""发票夹：发票状态归类与付款单补票提醒规则。

发票夹里的一张发票就是一条 OA Invoice Record。识别、核对、确认、查重沿用发票识别
服务；这里只把识别状态和"是否已被单据使用"合成员工看到的发票夹状态，并给出补票
提醒的时间规则。本模块不依赖 frappe，便于单元测试。
"""
from __future__ import annotations

from datetime import date, datetime

FOLDER_RECOGNIZING = "识别中"
FOLDER_TO_CONFIRM = "待确认"
FOLDER_AVAILABLE = "可用"
FOLDER_USED = "已使用"
FOLDER_DUPLICATE = "疑似重复"
FOLDER_FAILED = "识别失败"
FOLDER_EXCLUDED = "已排除"
FOLDER_STATUSES = (
    FOLDER_RECOGNIZING, FOLDER_TO_CONFIRM, FOLDER_AVAILABLE, FOLDER_USED,
    FOLDER_DUPLICATE, FOLDER_FAILED, FOLDER_EXCLUDED,
)
_BY_RECOGNITION = {
    "排队中": FOLDER_RECOGNIZING,
    "识别中": FOLDER_RECOGNIZING,
    "待确认": FOLDER_TO_CONFIRM,
    "疑似重复": FOLDER_DUPLICATE,
    "失败": FOLDER_FAILED,
    "已排除": FOLDER_EXCLUDED,
}

# 付款单先付款后补票：到期前 3 天内提醒一次，到期当天提醒一次，逾期后每天提醒一次。
DUE_SOON_DAYS = 3
REMIND_DUE_SOON = "即将到期"
REMIND_DUE_TODAY = "今天到期"
REMIND_OVERDUE = "已逾期"


def folder_status(recognition_status, request=None):
    status = str(recognition_status or "").strip()
    if status == "已确认":
        return FOLDER_USED if str(request or "").strip() else FOLDER_AVAILABLE
    return _BY_RECOGNITION.get(status, FOLDER_FAILED if status else FOLDER_RECOGNIZING)


def status_case_sql(escape):
    """SQL CASE giving the same 发票夹状态 as folder_status(); escape quotes a literal (frappe.db.escape)."""
    confirmed = escape("已确认")
    whens = [
        f"WHEN `recognition_status` = {confirmed} AND IFNULL(`request`, '') <> '' THEN {escape(FOLDER_USED)}",
        f"WHEN `recognition_status` = {confirmed} THEN {escape(FOLDER_AVAILABLE)}",
        f"WHEN IFNULL(`recognition_status`, '') = '' THEN {escape(FOLDER_RECOGNIZING)}",
    ]
    whens += [f"WHEN `recognition_status` = {escape(source)} THEN {escape(target)}" for source, target in _BY_RECOGNITION.items()]
    return "CASE " + " ".join(whens) + f" ELSE {escape(FOLDER_FAILED)} END"


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    return date.fromisoformat(text[:10]) if text else None


def days_left(expected_invoice_date, today):
    expected = _as_date(expected_invoice_date)
    return None if expected is None else (expected - _as_date(today)).days


def reminder(expected_invoice_date, today):
    """Return (kind, idempotency key suffix) for today's reminder, or (None, None)."""
    left = days_left(expected_invoice_date, today)
    if left is None or left > DUE_SOON_DAYS:
        return None, None
    expected = _as_date(expected_invoice_date).isoformat()
    if left > 0:
        return REMIND_DUE_SOON, f"soon:{expected}"
    if left == 0:
        return REMIND_DUE_TODAY, f"today:{expected}"
    return REMIND_OVERDUE, f"overdue:{expected}:{_as_date(today).isoformat()}"


def due_state(expected_invoice_date, today):
    """Label shown on a 付款单 that is still waiting for invoices."""
    left = days_left(expected_invoice_date, today)
    if left is None:
        return ""
    if left < 0:
        return f"已逾期 {-left} 天"
    if left == 0:
        return "今天到期"
    if left <= DUE_SOON_DAYS:
        return f"{left} 天后到期"
    return ""


def reminder_text(kind, name, expected_invoice_date, today):
    expected = _as_date(expected_invoice_date).isoformat()
    left = days_left(expected_invoice_date, today)
    if kind == REMIND_OVERDUE:
        return f"付款单 {name} 预计取票日期 {expected}，已逾期 {-left} 天，请尽快补录发票。"
    if kind == REMIND_DUE_TODAY:
        return f"付款单 {name} 预计取票日期是今天（{expected}），请补录发票。"
    return f"付款单 {name} 预计取票日期 {expected}，还有 {left} 天到期，请按时补录发票。"
