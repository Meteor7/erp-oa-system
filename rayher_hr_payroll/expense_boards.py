"""申请看板 / 付款看板 / 采购看板的统计口径。

金额一律取金额台账和单据上的实际付款日期，不用单据修改时间。采购申请和采购付款单独一个
看板，不和购买、报销、付款的数字混在一起。本模块不依赖 frappe，便于单元测试：调用方负责
查询和权限，这里只做归集。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PAYMENT,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
    REQUEST_REIMBURSEMENT,
    REQUEST_TRAVEL,
)

CENT = Decimal("0.01")
APPLICATION_TYPES = (REQUEST_DIRECT_PURCHASE, REQUEST_TRAVEL)
CLAIM_TYPES = (REQUEST_REIMBURSEMENT, REQUEST_PAYMENT)
PROCUREMENT_TYPES = (REQUEST_PROCUREMENT, REQUEST_PROCUREMENT_PAYMENT)
ACTIVE_STATUSES = ("待审批", "待办理")
COMPLETED = "已完成"
PAID = "已付款"
# 看板范围：财务和管理层看全公司，部门主管只看本部门，普通员工不开放。
SCOPE_ALL_ROLES = {"System Manager", "Accounts User", "Rayher Business Executive"}
SCOPE_ALL_POSITIONS = {"finance_manager", "finance_auditor", "vice_manager", "general_manager"}
SCOPE_DEPARTMENT_ROLES = {"Department Manager"}
STUCK_DAYS = 3
STALE_DAYS = 30
TREND_MONTHS = 6


def money(value):
    try:
        return Decimal(str(value if value not in (None, "") else 0)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _float(value):
    return float(money(value))


def _get(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def month_key(value):
    parsed = as_date(value)
    return parsed.strftime("%Y-%m") if parsed else ""


def recent_months(today, count=TREND_MONTHS):
    year, month = today.year, today.month
    keys = []
    for _ in range(count):
        keys.append("%04d-%02d" % (year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(keys))


def board_scope(roles=(), positions=()):
    roles = set(roles or ())
    positions = {key for key, value in dict(positions or {}).items() if value} if isinstance(positions, dict) else set(positions or ())
    if roles & SCOPE_ALL_ROLES or positions & SCOPE_ALL_POSITIONS:
        return "all"
    if roles & SCOPE_DEPARTMENT_ROLES:
        return "department"
    return "none"


def _bucket(rows, key, amount_field):
    buckets = {}
    for row in rows:
        label = str(_get(row, key) or "").strip() or "未填写"
        item = buckets.setdefault(label, {"label": label, "count": 0, "amount": Decimal("0.00"), "names": []})
        item["count"] += 1
        item["amount"] += money(_get(row, amount_field))
        item["names"].append(_get(row, "name"))
    result = [{**item, "amount": float(item["amount"])} for item in buckets.values()]
    result.sort(key=lambda item: (-item["amount"], item["label"]))
    return result


def request_board(rows, *, today, stuck_days=STUCK_DAYS, stale_days=STALE_DAYS):
    """购买申请与出差申请。rows 需带 paid_amount / reserved_amount / waited_days / approved_on。"""
    purchases = [row for row in rows if _get(row, "request_type") == REQUEST_DIRECT_PURCHASE]
    travels = [row for row in rows if _get(row, "request_type") == REQUEST_TRAVEL]
    approved = [row for row in purchases if _get(row, "workflow_status") == COMPLETED]
    summary = {
        "approved_amount": _float(sum((money(_get(row, "approved_amount")) for row in approved), Decimal("0.00"))),
        "reserved_amount": _float(sum((money(_get(row, "reserved_amount")) for row in approved), Decimal("0.00"))),
        "paid_amount": _float(sum((money(_get(row, "paid_amount")) for row in approved), Decimal("0.00"))),
    }
    # 已批准但还没付出去的额度：批准金额减已付，占用的部分也算没付出去。
    summary["unpaid_amount"] = _float(
        sum((money(_get(row, "approved_amount")) - money(_get(row, "paid_amount")) for row in approved), Decimal("0.00"))
    )
    summary["application_count"] = len(rows)
    stale = [
        {
            "name": _get(row, "name"), "subject": _get(row, "subject"), "employee_name": _get(row, "employee_name"),
            "department": _get(row, "department"), "approved_amount": _float(_get(row, "approved_amount")),
            "idle_days": (today - as_date(_get(row, "approved_on"))).days if as_date(_get(row, "approved_on")) else None,
        }
        for row in approved
        if money(_get(row, "paid_amount")) == 0
        and as_date(_get(row, "approved_on")) is not None
        and (today - as_date(_get(row, "approved_on"))).days >= stale_days
    ]
    stale.sort(key=lambda item: -(item["idle_days"] or 0))
    stuck = [
        {
            "name": _get(row, "name"), "request_type": _get(row, "request_type"), "subject": _get(row, "subject"),
            "employee_name": _get(row, "employee_name"), "department": _get(row, "department"),
            "current_step_label": _get(row, "current_step_label"), "waited_days": int(_get(row, "waited_days") or 0),
            "overdue": int(_get(row, "waited_days") or 0) >= stuck_days,
        }
        for row in rows if _get(row, "workflow_status") in ACTIVE_STATUSES
    ]
    stuck.sort(key=lambda item: -item["waited_days"])
    ongoing = []
    this_month = []
    for row in travels:
        if _get(row, "workflow_status") != COMPLETED:
            continue
        start, end = as_date(_get(row, "travel_start_date")), as_date(_get(row, "travel_end_date"))
        item = {
            "name": _get(row, "name"), "subject": _get(row, "subject"), "employee_name": _get(row, "employee_name"),
            "department": _get(row, "department"), "travel_destination": _get(row, "travel_destination"),
            "travel_start_date": _get(row, "travel_start_date"), "travel_end_date": _get(row, "travel_end_date"),
            "travel_days": int(_get(row, "travel_days") or 0),
            # 每次出差已报销 / 已付款的金额，取关联单据的实际付款额。
            "claimed_amount": _float(_get(row, "paid_amount")),
        }
        if start and end and start <= today <= end:
            ongoing.append(item)
        if start and start.strftime("%Y-%m") == today.strftime("%Y-%m"):
            this_month.append(item)
    return {
        "summary": summary,
        "stale_applications": stale,
        "stuck_approvals": stuck,
        "travel": {
            "ongoing": ongoing,
            "this_month": this_month,
            "claimed_amount": _float(sum((money(item["claimed_amount"]) for item in this_month), Decimal("0.00"))),
        },
        "by_asset": _bucket([row for row in approved], "asset_classification", "approved_amount"),
        "by_department": _bucket(approved + [row for row in travels if _get(row, "workflow_status") == COMPLETED], "department", "approved_amount"),
        "stuck_days": stuck_days,
        "stale_days": stale_days,
    }


def payment_board(rows, lines=(), *, today, months=TREND_MONTHS):
    """报销单与付款单。金额按实际付款日期（paid_on）计入月份。"""
    paid = [row for row in rows if _get(row, "workflow_status") == PAID and as_date(_get(row, "paid_on"))]
    current = today.strftime("%Y-%m")
    keys = recent_months(today, months)
    trend = {key: {"month": key, REQUEST_REIMBURSEMENT: Decimal("0.00"), REQUEST_PAYMENT: Decimal("0.00")} for key in keys}
    month_totals = {REQUEST_REIMBURSEMENT: Decimal("0.00"), REQUEST_PAYMENT: Decimal("0.00")}
    for row in paid:
        key = month_key(_get(row, "paid_on"))
        kind = _get(row, "request_type")
        if key in trend and kind in trend[key]:
            trend[key][kind] += money(_get(row, "amount"))
        if key == current and kind in month_totals:
            month_totals[kind] += money(_get(row, "amount"))
    cashier_queue = [
        {
            "name": _get(row, "name"), "request_type": _get(row, "request_type"), "subject": _get(row, "subject"),
            "employee_name": _get(row, "employee_name"), "department": _get(row, "department"),
            "amount": _float(_get(row, "amount")), "urgency": _get(row, "urgency") or "一般",
            "waited_days": int(_get(row, "waited_days") or 0),
        }
        for row in rows
        if _get(row, "workflow_status") == "待办理"
    ]
    # 加急优先，其次等待时间长的在前。
    cashier_queue.sort(key=lambda item: (item["urgency"] != "加急", -item["waited_days"]))
    tracking = []
    for row in rows:
        if _get(row, "request_type") != REQUEST_PAYMENT or _get(row, "invoice_followup_status") != "待收票":
            continue
        expected = as_date(_get(row, "expected_invoice_date"))
        overdue_days = (today - expected).days if expected and expected < today else 0
        tracking.append({
            "name": _get(row, "name"), "subject": _get(row, "subject"), "employee_name": _get(row, "employee_name"),
            "department": _get(row, "department"), "amount": _float(_get(row, "amount")),
            "expected_invoice_date": _get(row, "expected_invoice_date"),
            "overdue_days": overdue_days,
            "days_left": (expected - today).days if expected and expected >= today else 0,
        })
    tracking.sort(key=lambda item: (-item["overdue_days"], item["days_left"]))
    paid_names = {_get(row, "name") for row in paid}
    paid_lines = [line for line in lines if _get(line, "parent") in paid_names]
    accounts = {}
    for line in paid_lines:
        level_1 = str(_get(line, "expense_account_level_1") or "").strip() or "未填写"
        level_2 = str(_get(line, "expense_account_level_2") or "").strip() or "未填写"
        item = accounts.setdefault((level_1, level_2), {"level_1": level_1, "level_2": level_2, "count": 0, "amount": Decimal("0.00")})
        item["count"] += 1
        item["amount"] += money(_get(line, "total_amount"))
    by_account = [{**item, "amount": float(item["amount"])} for item in accounts.values()]
    by_account.sort(key=lambda item: (-item["amount"], item["level_1"], item["level_2"]))
    payees = _bucket([row for row in paid if _get(row, "request_type") == REQUEST_PAYMENT], "payee_name", "amount")
    return {
        "summary": {
            "month": current,
            "reimbursement_paid": float(month_totals[REQUEST_REIMBURSEMENT]),
            "payment_paid": float(month_totals[REQUEST_PAYMENT]),
            "paid_total": float(month_totals[REQUEST_REIMBURSEMENT] + month_totals[REQUEST_PAYMENT]),
            "cashier_pending": len(cashier_queue),
            "invoice_pending": len(tracking),
            "invoice_overdue": sum(1 for item in tracking if item["overdue_days"] > 0),
        },
        "cashier_queue": cashier_queue,
        "invoice_tracking": tracking,
        "trend": [
            {"month": key, "reimbursement": float(trend[key][REQUEST_REIMBURSEMENT]), "payment": float(trend[key][REQUEST_PAYMENT])}
            for key in keys
        ],
        "by_account": by_account,
        "by_department": _bucket(paid, "department", "amount"),
        "top_payees": payees[:5],
    }


def procurement_board(rows, *, today):
    """采购申请与采购付款单独统计：到货、验收、预付款核销。"""
    applications = [row for row in rows if _get(row, "request_type") == REQUEST_PROCUREMENT]
    payments = [row for row in rows if _get(row, "request_type") == REQUEST_PROCUREMENT_PAYMENT]
    paid_payments = [row for row in payments if _get(row, "workflow_status") == PAID]
    return {
        "summary": {
            "application_count": len(applications),
            "application_amount": _float(sum((money(_get(row, "approved_amount")) or money(_get(row, "amount")) for row in applications), Decimal("0.00"))),
            "payment_count": len(payments),
            "paid_amount": _float(sum((money(_get(row, "amount")) for row in paid_payments), Decimal("0.00"))),
            "pending_arrival": sum(1 for row in paid_payments if str(_get(row, "arrival_status") or "") in ("未到货", "部分到货")),
            "pending_inspection": sum(1 for row in paid_payments if str(_get(row, "inspection_status") or "") in ("未验收", "验收中")),
            "pending_writeoff": sum(1 for row in paid_payments if str(_get(row, "prepayment_writeoff_status") or "") == "待核销"),
        },
        "by_business_status": _bucket(payments, "business_status", "amount"),
        "by_arrival": _bucket(paid_payments, "arrival_status", "amount"),
        "by_inspection": _bucket(paid_payments, "inspection_status", "amount"),
        "applications_by_status": _bucket(applications, "business_status", "approved_amount"),
    }
