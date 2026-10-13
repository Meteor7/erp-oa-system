"""“今天”和“现在”按站点时区算（系统设置里的时区，Asia/Shanghai），不按服务器操作系统的时钟。

服务器 / 容器的系统时钟通常是 UTC：北京时间 0 点到 8 点之间 date.today() 还是昨天，
看板（按站点时区）和考勤中心（按系统时钟）就会差一天。业务代码一律用这里的 today() / now()。
"""
from datetime import date, datetime


def today():
    try:
        import frappe

        return frappe.utils.getdate(frappe.utils.nowdate())
    except Exception:
        # 没有站点上下文（纯函数单测、脚本）时退回系统时钟
        return date.today()


def now():
    try:
        import frappe

        return frappe.utils.now_datetime()
    except Exception:
        return datetime.now()
