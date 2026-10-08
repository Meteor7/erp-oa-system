"""每日任务：月初提醒财务主管给上个月的研发费用分摊定版。

每月 1–5 日，如果上个月有（未取消的）费用导入单、但还没有已提交（定版）的分摊单，
给财务主管岗位的持有人发一条站内通知，告诉他还有多少人的研发工时没填满。
同一个人、同一个上月、同一天最多发一条（通知主题里带确定性的 key，重复运行不会重复发送）。
整个任务不会抛错：出错只记错误日志。

这里的 frappe 都在函数内部导入，方便测试替换。
"""
from __future__ import annotations

import logging
from datetime import date, datetime

REMINDER_FIRST_DAY = 1
REMINDER_LAST_DAY = 5
POSITION_KEY = "finance_manager"
KEY_PREFIX = "alloc-finalize"
LINK = "/planck-semicon/allocation"
# Notification Log 的 document_type / document_name 是动态链接，必须指向真实存在的单据：用上个月的费用导入单。
DOCUMENT_TYPE = "RD Expense Import"

logger = logging.getLogger(__name__)


def _today(today=None):
    """today 可以是 date / datetime / 'YYYY-MM-DD'；不传就取站点今天。"""
    if today is None:
        from frappe.utils import getdate, nowdate

        return getdate(nowdate())
    if isinstance(today, datetime):
        return today.date()
    if isinstance(today, date):
        return today
    return datetime.strptime(str(today)[:10], "%Y-%m-%d").date()


def previous_month(today):
    """today 所在月的上一个月 (year, month)。"""
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


def in_reminder_window(today):
    """只在每月 1–5 日提醒。"""
    return REMINDER_FIRST_DAY <= today.day <= REMINDER_LAST_DAY


def reminder_key(year, month, today):
    """同一个人、同一个上月、同一天只发一条：key 里带上月和当天日期。"""
    return "%s:%04d-%02d:%s" % (KEY_PREFIX, year, month, date(today.year, today.month, today.day).isoformat())


def reminder_text(year, month, unfilled):
    head = "%d年%d月的研发费用分摊还没有定版：" % (year, month)
    if unfilled > 0:
        head += "还有 %d 人工时没填满，" % unfilled
    else:
        head += "工时都已填满，"
    return head + "请到「研发费用台账」检查后定版。"


def _previous_import(year, month):
    """上个月最新的未取消费用导入单（和分摊预览同一个口径）；没有返回 None。"""
    from rayher_hr_payroll.api._guards import find_period_import

    return find_period_import(year, month)


def _has_submitted_allocation(year, month):
    import frappe

    return bool(frappe.db.exists("RD Cost Allocation", {"year": year, "month": month, "docstatus": 1}))


def _unfilled_people(year, month):
    """工时没填满的人数 = 一天没填（none）+ 没填满（part）；口径和「工时填报进度」页一样，scope=None 即全部研发人员。"""
    from rayher_hr_payroll.api import monthly_timesheet_entry

    rows = monthly_timesheet_entry._fill_rows(year, month, None)
    return sum(1 for row in rows if row.get("status") in ("none", "part"))


def _finance_managers():
    from rayher_hr_payroll.position_access import position_users

    return sorted(user for user in position_users(POSITION_KEY) if user)


def _enabled(user):
    import frappe

    return bool(frappe.db.exists("User", {"name": user, "enabled": 1}))


def _already_sent(user, import_name, key):
    import frappe

    return bool(frappe.db.exists(
        "Notification Log",
        {
            "for_user": user,
            "document_type": DOCUMENT_TYPE,
            "document_name": import_name,
            "subject": ["like", "%%[%s]%%" % key],
        },
    ))


def _send(user, import_name, key, subject, content):
    import frappe

    frappe.get_doc({
        "doctype": "Notification Log",
        "for_user": user,
        "type": "Alert",
        "document_type": DOCUMENT_TYPE,
        "document_name": import_name,
        "subject": "%s [%s]" % (subject, key),
        "email_content": content,
        "link": LINK,
    }).insert(ignore_permissions=True)


def _log_failure():
    import frappe

    try:
        frappe.log_error(title="研发费用定版提醒发送失败", message=frappe.get_traceback())
    except Exception:  # 记日志本身也不能让定时任务报错
        logger.exception("allocation finalize reminder failed")


def remind_finance_manager_to_finalize(today=None):
    """每日任务入口。返回本次发出的提醒条数。永远不抛错。"""
    try:
        today = _today(today)
        if not in_reminder_window(today):
            return 0
        year, month = previous_month(today)
        import_name = _previous_import(year, month)
        if not import_name or _has_submitted_allocation(year, month):
            return 0
        users = _finance_managers()
        if not users:
            logger.warning("allocation finalize reminder skipped: no %s position holder", POSITION_KEY)
            return 0
        unfilled = _unfilled_people(year, month)
    except Exception:
        _log_failure()
        return 0

    key = reminder_key(year, month, today)
    subject = "%d年%d月研发费用分摊待定版" % (year, month)
    content = reminder_text(year, month, unfilled)
    sent = 0
    for user in users:
        try:
            if not _enabled(user) or _already_sent(user, import_name, key):
                continue
            _send(user, import_name, key, subject, content)
            sent += 1
        except Exception:
            _log_failure()
    return sent
