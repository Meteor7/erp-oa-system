"""请假 / 调休申请表的每日选项接口：全天 8 / 上午 3 / 下午 5 小时，按已有申请灰掉被占的那一半。"""
import importlib
import json
import types
from datetime import date

import pytest

from rayher_hr_payroll import attendance_requests as att


@pytest.fixture
def options(monkeypatch):
    module = importlib.import_module("rayher_hr_payroll.api.oa_entry")
    annual = importlib.import_module("rayher_hr_payroll.annual_leave")
    monkeypatch.setattr(module.frappe, "_", lambda text, *args, **kwargs: text, raising=False)

    def throw(message, exc=None):
        raise ValueError(str(message))

    monkeypatch.setattr(module.frappe, "throw", throw, raising=False)
    monkeypatch.setattr(module, "require_request_type_access", lambda request_type: None)
    monkeypatch.setattr(module, "_leave_employee_context", lambda: {"employee": "EMP-1"})
    monkeypatch.setattr(att, "get_balance", lambda employee: {"available_hours": 0})
    monkeypatch.setattr(annual, "get_annual_balance", lambda employee: {"available_hours": 40})
    work_days = {date(2026, 10, day) for day in (12, 13, 14, 15, 16)}
    monkeypatch.setattr(att, "work_dates_for_range", lambda employee, start, end: work_days)
    rows = []
    monkeypatch.setattr(att, "active_rows", lambda employee, start, end, **kwargs: rows)
    # frappe.whitelist wraps the function with argument type validation that needs a request context.
    raw = getattr(module.get_attendance_options, "__wrapped__", module.get_attendance_options)
    return types.SimpleNamespace(get_attendance_options=raw), rows


def row(name, request_type, status, day, hours):
    return {"name": name, "request_type": request_type, "workflow_status": status,
            "attendance_days": json.dumps([{"work_date": day, "hours": hours}])}


def test_day_options_carry_the_taken_halves_and_a_default_that_fits(options):
    module, rows = options
    rows += [row("A", att.REQUEST_LEAVE, "待审批", "2026-10-13", 3),
             row("B", att.REQUEST_COMP_TIME, "已完成", "2026-10-14", 5),
             row("C", att.REQUEST_LEAVE, "已完成", "2026-10-15", 4),
             row("D", att.REQUEST_LEAVE, "已完成", "2026-10-16", 8)]
    result = module.get_attendance_options(att.REQUEST_LEAVE, "2026-10-12", "2026-10-16")
    days = {item["work_date"]: item for item in result["days"]}
    assert [(d["hours"], d["max_hours"], d["am_taken"], d["pm_taken"], bool(d["conflict"])) for d in days.values()] == [
        (8.0, 8.0, False, False, False),   # 12 日：空着，默认全天
        (5.0, 5.0, True, False, False),    # 13 日：上午被占，默认下午
        (3.0, 3.0, False, True, False),    # 14 日：下午被占，默认上午
        (3.0, 4.0, False, False, False),   # 15 日：旧的 4 小时半天，还剩 4 小时，只能再加上午 3 小时
        (0.0, 0, True, True, True),        # 16 日：全天被占
    ]
    assert days["2026-10-16"]["conflict"]["request"] == "D"


def test_overtime_options_are_still_hours(options):
    module, rows = options
    rows.append(row("OT", att.REQUEST_OVERTIME, "已完成", "2026-10-17", 20))
    result = module.get_attendance_options(att.REQUEST_OVERTIME, "2026-10-17", "2026-10-18")
    by_day = {item["work_date"]: item for item in result["days"]}
    assert (by_day["2026-10-17"]["hours"], by_day["2026-10-17"]["max_hours"]) == (4.0, 4.0)
    assert (by_day["2026-10-18"]["hours"], by_day["2026-10-18"]["max_hours"]) == (8.0, 24.0)
    assert not by_day["2026-10-17"]["am_taken"] and not by_day["2026-10-17"]["pm_taken"]
