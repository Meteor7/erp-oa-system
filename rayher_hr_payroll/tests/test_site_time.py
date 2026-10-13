"""“今天 / 现在”按站点时区（2026-10-14）：服务器系统时钟是 UTC 时，北京时间早上 8 点前不能还算成昨天。"""
import subprocess

from rayher_hr_payroll import site_time


def test_today_and_now_follow_the_site_timezone(monkeypatch):
    import frappe
    from datetime import date, datetime

    monkeypatch.setattr(frappe.utils, "nowdate", lambda: "2026-10-14", raising=False)
    monkeypatch.setattr(frappe.utils, "getdate", lambda value=None: date.fromisoformat(value), raising=False)
    monkeypatch.setattr(frappe.utils, "now_datetime", lambda: datetime(2026, 10, 14, 7, 30), raising=False)
    assert site_time.today() == date(2026, 10, 14)
    assert site_time.now() == datetime(2026, 10, 14, 7, 30)


def test_business_code_never_reads_the_system_clock():
    """业务代码里不能再出现 date.today() / datetime.now()（测试和维护脚本除外）。"""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for folder, _dirs, files in os.walk(root):
        if os.sep + "tests" in folder or os.sep + "maintenance" in folder or os.sep + "patches" in folder:
            continue
        for name in files:
            if not name.endswith(".py") or name == "site_time.py":
                continue
            text = open(os.path.join(folder, name), encoding="utf-8").read()
            for bad in ("date.today()", "datetime.today()", "datetime.utcnow()"):
                if bad in text.replace("site_time.today()", ""):
                    offenders.append(f"{name}: {bad}")
            if "datetime.now()" in text.replace("site_time.now()", "") and 'hasattr(frappe.utils, "nowdate")' not in text:
                offenders.append(f"{name}: datetime.now()")
    assert offenders == []
