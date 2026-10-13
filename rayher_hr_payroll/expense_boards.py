"""申请看板 / 付款看板 / 采购页签的统计口径（按已确认的设计稿第 5 版）。

金额一律取金额台账和单据上的实际付款日期，不用单据修改时间。采购申请和采购付款只在
各自看板的"采购"页签里单独统计，不和购买、出差、报销、付款的数字混在一起。本模块不依赖
frappe，便于单元测试：调用方负责查询和权限，这里只做归集。
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
ZERO = Decimal("0.00")
APPLICATION_TYPES = (REQUEST_DIRECT_PURCHASE, REQUEST_TRAVEL)
CLAIM_TYPES = (REQUEST_REIMBURSEMENT, REQUEST_PAYMENT)
PROCUREMENT_TYPES = (REQUEST_PROCUREMENT, REQUEST_PROCUREMENT_PAYMENT)
ACTIVE_STATUSES = ("待审批", "待办理")
COMPLETED = "已完成"
PAID = "已付款"
WAIT_HANDLE = "待办理"
# 看板范围：财务和管理层看全公司，部门主管只看本部门，普通员工不开放。
SCOPE_ALL_ROLES = {"System Manager", "Accounts User", "Rayher Business Executive"}
SCOPE_ALL_POSITIONS = {"finance_manager", "finance_auditor", "vice_manager", "general_manager"}
SCOPE_DEPARTMENT_ROLES = {"Department Manager"}
STUCK_DAYS = 3
STALE_DAYS = 30
TREND_MONTHS = 6
TRIP_LOOKBACK_DAYS = 30
# 采购付款的验收状态见 procurement_workflow.INSPECTION_STATUSES；除"验收通过"外都还要跟进。
PENDING_INSPECTION = ("未验收", "待验收", "验收不合格")


def money(value):
    try:
        return Decimal(str(value if value not in (None, "") else 0)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def _f(value):
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
    if isinstance(positions, dict):
        positions = {key for key, value in positions.items() if value}
    else:
        positions = set(positions or ())
    if roles & SCOPE_ALL_ROLES or positions & SCOPE_ALL_POSITIONS:
        return "all"
    if roles & SCOPE_DEPARTMENT_ROLES:
        return "department"
    return "none"


def totals_by(rows, key, amount_field):
    """[(label, amount)] sorted by amount, for the horizontal bar charts."""
    buckets = {}
    for row in rows:
        label = str(_get(row, key) or "").strip() or "未填写"
        buckets[label] = buckets.get(label, ZERO) + money(_get(row, amount_field))
    return [[label, float(amount)] for label, amount in sorted(buckets.items(), key=lambda item: (-item[1], item[0]))]


def _days(since, today):
    since = as_date(since)
    return max(0, (today - since).days) if since else 0


def application_status(approved, paid):
    approved, paid = money(approved), money(paid)
    if paid <= 0:
        return "待付款"
    return "已付款" if paid >= approved else "部分付款"


def trip_status(start, end, today):
    start, end = as_date(start), as_date(end)
    if start and start > today:
        return "未出发"
    if end and end >= today:
        return "出差中"
    return "已返回"


# ---------------------------------------------------------------- 申请看板


def request_board(rows, *, today, stuck_days=STUCK_DAYS, stale_days=STALE_DAYS):
    """rows: 购买申请与出差申请，需带 paid_amount / reserved_amount / waited_days / approved_on。"""
    purchases = [row for row in rows if _get(row, "request_type") == REQUEST_DIRECT_PURCHASE]
    approved = [row for row in purchases if _get(row, "workflow_status") == COMPLETED]
    month = today.strftime("%Y-%m")
    this_month = [row for row in approved if month_key(_get(row, "approved_on")) == month]

    applications = []
    for row in approved:
        amount, paid, reserved = money(_get(row, "approved_amount")), money(_get(row, "paid_amount")), money(_get(row, "reserved_amount"))
        idle = _days(_get(row, "approved_on"), today)
        used = paid + reserved
        applications.append({
            "name": _get(row, "name"), "request_type": REQUEST_DIRECT_PURCHASE, "subject": _get(row, "subject"),
            "employee_name": _get(row, "employee_name"), "department": _get(row, "department"),
            "approved_amount": float(amount), "paid_amount": float(paid), "reserved_amount": float(reserved),
            "remaining_amount": float(max(ZERO, amount - used)),
            "progress": min(100, round(float(used / amount * 100))) if amount > 0 else 0,
            "status": application_status(amount, paid),
            "idle_days": idle,
            "stale": used == 0 and idle > stale_days,
        })
    applications.sort(key=lambda item: (not item["stale"], item["status"] == "已付款", -item["idle_days"]))

    pending = []
    for row in rows:
        if _get(row, "workflow_status") not in ACTIVE_STATUSES:
            continue
        waited = int(_get(row, "waited_days") or 0)
        is_purchase = _get(row, "request_type") == REQUEST_DIRECT_PURCHASE
        pending.append({
            "name": _get(row, "name"), "request_type": _get(row, "request_type"), "subject": _get(row, "subject"),
            "employee_name": _get(row, "employee_name"), "department": _get(row, "department"),
            "amount": _f(_get(row, "amount")) if is_purchase else None,
            "current_step_label": _get(row, "current_step_label") or "",
            "waited_days": waited, "overdue": waited > stuck_days,
        })
    pending.sort(key=lambda item: -item["waited_days"])

    trips = []
    for row in rows:
        if _get(row, "request_type") != REQUEST_TRAVEL or _get(row, "workflow_status") not in (COMPLETED, "待办理"):
            continue
        start, end = as_date(_get(row, "travel_start_date")), as_date(_get(row, "travel_end_date"))
        if not start or (end and (today - end).days > TRIP_LOOKBACK_DAYS):
            continue
        trips.append({
            "name": _get(row, "name"), "subject": _get(row, "subject"), "employee_name": _get(row, "employee_name"),
            "department": _get(row, "department"), "travel_destination": _get(row, "travel_destination"),
            "travel_start_date": start.isoformat(), "travel_end_date": end.isoformat() if end else "",
            "travel_days": int(_get(row, "travel_days") or 0),
            "status": trip_status(start, end, today),
            "claimed_amount": _f(_get(row, "paid_amount")),
        })
    trips.sort(key=lambda item: item["travel_start_date"], reverse=True)

    fixed = [row for row in approved if _get(row, "asset_nature") == "固定资产"]
    return {
        "summary": {
            "month": month,
            "month_approved_amount": float(sum((money(_get(row, "approved_amount")) for row in this_month), ZERO)),
            "month_approved_count": len(this_month),
            # 已批准未付出 = 批准金额 - 已付 - 在途占用（设计稿口径，不再单独展示"占用"大数字）
            "unpaid_amount": float(sum((money(item["remaining_amount"]) for item in applications), ZERO)),
            "pending_count": len(pending),
            "longest_wait_days": max((item["waited_days"] for item in pending), default=0),
            "on_trip_count": sum(1 for trip in trips if trip["status"] == "出差中"),
            "month_trip_count": sum(1 for trip in trips if trip["travel_start_date"][:7] == month),
            "stale_count": sum(1 for item in applications if item["stale"]),
        },
        "applications": applications,
        "pending": pending,
        "trips": trips,
        "by_department": totals_by(approved, "department", "approved_amount"),
        "fixed_by_category": totals_by(fixed, "fixed_asset_category", "approved_amount"),
        "non_fixed_amount": float(sum((money(_get(row, "approved_amount")) for row in approved if row not in fixed), ZERO)),
        "stuck_days": stuck_days,
        "stale_days": stale_days,
        **month_flow(rows, today),
    }


def month_flow(rows, today):
    """本月提交的购买、出差申请（看板只取审批中和已完成的，不含驳回、撤回）：构成和走到哪一步。

    2026-09-30 看板改版：申请看板加"本月都申请了什么"环形图和"申请走到哪一步了"。
    购买申请金额取批准金额（未批准的取申请金额）；出差申请没有金额。
    """
    month = today.strftime("%Y-%m")
    mine = [row for row in rows if month_key(_get(row, "creation")) == month]
    purchases = [row for row in mine if _get(row, "request_type") == REQUEST_DIRECT_PURCHASE]
    trips = [row for row in mine if _get(row, "request_type") == REQUEST_TRAVEL]
    fixed = [row for row in purchases if _get(row, "asset_nature") == "固定资产"]
    approved = [row for row in mine if _get(row, "workflow_status") == COMPLETED]
    pending = [row for row in mine if _get(row, "workflow_status") in ACTIVE_STATUSES]

    def executed(row):
        if _get(row, "request_type") == REQUEST_DIRECT_PURCHASE:
            return money(_get(row, "paid_amount")) > 0
        start = as_date(_get(row, "travel_start_date"))
        return bool(start and start <= today)

    def amount(items):
        total = ZERO
        for row in items:
            if _get(row, "request_type") != REQUEST_DIRECT_PURCHASE:
                continue
            value = _get(row, "approved_amount") if _get(row, "workflow_status") == COMPLETED else _get(row, "amount")
            total += money(value)
        return float(total)

    done = [row for row in approved if executed(row)]
    mix = [
        ["购买申请 · 非固定资产", len(purchases) - len(fixed)],
        ["购买申请 · 固定资产", len(fixed)],
        ["出差申请", len(trips)],
    ]
    return {
        "month_mix": [item for item in mix if item[1]],
        "month_flow": [
            {"key": "submitted", "label": "本月提交", "count": len(mine), "amount": amount(mine)},
            {"key": "approved", "label": "已通过", "count": len(approved), "amount": amount(approved)},
            {"key": "executed", "label": "已付款 / 已出发", "count": len(done), "amount": amount(done)},
            {"key": "pending", "label": "还在审批", "count": len(pending), "amount": amount(pending)},
        ],
    }


# ---------------------------------------------------------------- 付款看板


def payment_board(rows, lines=(), *, today, reminders=None, months=TREND_MONTHS):
    """rows: 报销单与付款单。金额按实际付款日期（paid_on）计入月份。"""
    reminders = reminders or {}
    month, year = today.strftime("%Y-%m"), today.year
    paid = [row for row in rows if _get(row, "workflow_status") == PAID and as_date(_get(row, "paid_on"))]
    paid_this_month = [row for row in paid if month_key(_get(row, "paid_on")) == month]

    keys = recent_months(today, months)
    trend = {key: {"month": key, "reimbursement": ZERO, "payment": ZERO} for key in keys}
    for row in paid:
        key = month_key(_get(row, "paid_on"))
        if key in trend:
            field = "reimbursement" if _get(row, "request_type") == REQUEST_REIMBURSEMENT else "payment"
            trend[key][field] += money(_get(row, "amount"))

    queue = []
    for row in rows:
        if _get(row, "workflow_status") == WAIT_HANDLE:
            status = "待付款"
        elif _get(row, "request_type") == REQUEST_PAYMENT and _get(row, "business_status") == "待核验":
            status = "待核验"
        else:
            continue
        queue.append({
            "name": _get(row, "name"), "request_type": _get(row, "request_type"), "subject": _get(row, "subject"),
            "employee_name": _get(row, "employee_name"), "department": _get(row, "department"),
            "amount": _f(_get(row, "amount")), "urgency": _get(row, "urgency") or "一般",
            "waited_days": int(_get(row, "waited_days") or 0), "status": status,
        })
    queue.sort(key=lambda item: (item["urgency"] != "加急", -item["waited_days"]))
    to_pay = [item for item in queue if item["status"] == "待付款"]

    tracking = []
    for row in rows:
        if _get(row, "request_type") != REQUEST_PAYMENT or _get(row, "workflow_status") != PAID:
            continue
        if _get(row, "invoice_followup_status") != "待收票":
            continue
        expected = as_date(_get(row, "expected_invoice_date"))
        left = (expected - today).days if expected else None
        tracking.append({
            "name": _get(row, "name"), "subject": _get(row, "subject"), "employee_name": _get(row, "employee_name"),
            "department": _get(row, "department"), "payee_name": _get(row, "payee_name") or "",
            "amount": _f(_get(row, "amount")), "expected_invoice_date": expected.isoformat() if expected else "",
            "days_left": left if left is not None and left >= 0 else 0,
            "overdue_days": -left if left is not None and left < 0 else 0,
            "reminders": int(reminders.get(_get(row, "name"), 0)),
        })
    tracking.sort(key=lambda item: item["expected_invoice_date"] or "9999")

    month_names = {_get(row, "name") for row in paid_this_month}
    accounts = {}
    for line in lines:
        if _get(line, "parent") not in month_names:
            continue
        label = " / ".join(part for part in (
            str(_get(line, "expense_account_level_1") or "").strip(),
            str(_get(line, "expense_account_level_2") or "").strip(),
        ) if part) or "未填写"
        # 价税合计，没有就取金额：和首页费用概览、数据看板的「已付」同一个算法（2026-10-13 统一）
        accounts[label] = accounts.get(label, ZERO) + money(_get(line, "total_amount") or _get(line, "amount"))

    payees_this_year = [
        row for row in paid
        if _get(row, "request_type") == REQUEST_PAYMENT and as_date(_get(row, "paid_on")).year == year
    ]
    return {
        "summary": {
            "month": month,
            "reimbursement_paid": float(sum((money(_get(row, "amount")) for row in paid_this_month if _get(row, "request_type") == REQUEST_REIMBURSEMENT), ZERO)),
            "payment_paid": float(sum((money(_get(row, "amount")) for row in paid_this_month if _get(row, "request_type") == REQUEST_PAYMENT), ZERO)),
            "to_pay_amount": float(sum((money(item["amount"]) for item in to_pay), ZERO)),
            "to_pay_count": len(to_pay),
            "to_pay_urgent": sum(1 for item in to_pay if item["urgency"] == "加急"),
            "invoice_pending_amount": float(sum((money(item["amount"]) for item in tracking), ZERO)),
            "invoice_pending_count": len(tracking),
            "invoice_overdue_count": sum(1 for item in tracking if item["overdue_days"] > 0),
        },
        "trend": [{"month": key, "reimbursement": float(trend[key]["reimbursement"]), "payment": float(trend[key]["payment"])} for key in keys],
        "by_account": [[label, float(amount)] for label, amount in sorted(accounts.items(), key=lambda item: (-item[1], item[0]))],
        "by_department": totals_by(paid_this_month, "department", "amount"),
        "cashier_queue": queue,
        "invoice_tracking": tracking,
        "top_payees": totals_by(payees_this_year, "payee_name", "amount")[:5],
    }


# ---------------------------------------------------------------- 采购页签


def procurement_board(rows, *, today):
    """采购申请与采购付款单独统计：到货、验收、预付款核销。"""
    applications = [row for row in rows if _get(row, "request_type") == REQUEST_PROCUREMENT]
    payments = [row for row in rows if _get(row, "request_type") == REQUEST_PROCUREMENT_PAYMENT]
    paid = [row for row in payments if _get(row, "workflow_status") == PAID]
    month = today.strftime("%Y-%m")

    def row_of(row):
        return {
            "name": _get(row, "name"), "request_type": _get(row, "request_type"), "subject": _get(row, "subject"),
            "employee_name": _get(row, "employee_name"), "department": _get(row, "department"),
            "amount": _f(_get(row, "approved_amount") or _get(row, "amount")),
            "workflow_status": _get(row, "workflow_status"), "business_status": _get(row, "business_status") or "",
            "arrival_status": _get(row, "arrival_status") or "", "inspection_status": _get(row, "inspection_status") or "",
            "prepayment_writeoff_status": _get(row, "prepayment_writeoff_status") or "",
            "source_purchase_order": _get(row, "source_purchase_order") or "",
            "waited_days": int(_get(row, "waited_days") or 0),
        }

    return {
        "summary": {
            "application_count": len(applications),
            "application_pending": sum(1 for row in applications if _get(row, "workflow_status") in ACTIVE_STATUSES),
            "application_amount": float(sum((money(_get(row, "approved_amount") or _get(row, "amount")) for row in applications), ZERO)),
            "payment_count": len(payments),
            "month_paid_amount": float(sum((money(_get(row, "amount")) for row in paid if month_key(_get(row, "paid_on")) == month), ZERO)),
            "pending_arrival": sum(1 for row in paid if str(_get(row, "arrival_status") or "") in ("未到货", "部分到货")),
            # 修复（2026-09-23）："验收中"不是有效状态，待验收、验收不合格原来都没算进去。
            "pending_inspection": sum(1 for row in paid if str(_get(row, "inspection_status") or "") in PENDING_INSPECTION),
            "pending_writeoff": sum(1 for row in paid if str(_get(row, "prepayment_writeoff_status") or "") == "待核销"),
        },
        "applications_by_status": totals_by(applications, "business_status", "approved_amount"),
        "payments_by_status": totals_by(payments, "business_status", "amount"),
        "applications": [row_of(row) for row in applications][:200],
        "payments": [row_of(row) for row in payments][:200],
    }
