import importlib
import sys
import types
from datetime import date

import pytest


@pytest.fixture
def calendar_module(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.utils = types.ModuleType("frappe.utils")
    frappe.utils.getdate = lambda value: value if isinstance(value, date) else date.fromisoformat(str(value))
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", frappe.utils)
    sys.modules.pop("rayher_hr_payroll.working_calendar", None)
    return importlib.import_module("rayher_hr_payroll.working_calendar"), frappe


def test_holiday_list_excludes_listed_dates_and_keeps_makeup_saturday(calendar_module):
    mod, _ = calendar_module
    holidays = {date(2026, 7, 4), date(2026, 7, 5), date(2026, 7, 12)}

    work_dates = mod.count_work_dates(2026, 7, holidays)

    assert date(2026, 7, 11) in work_dates
    assert date(2026, 7, 12) not in work_dates


def test_weekday_fallback_excludes_saturday_and_sunday(calendar_module):
    mod, _ = calendar_module

    work_dates = mod.count_work_dates(2026, 7, None)

    assert len(work_dates) == 23
    assert all(value.weekday() < 5 for value in work_dates)


def test_employee_holiday_list_takes_priority_and_returns_hours(calendar_module):
    mod, frappe = calendar_module
    frappe.db = types.SimpleNamespace(
        get_value=lambda doctype, key, fields=None, as_dict=False: {
            ("Employee", "EMP-1"): {
                "holiday_list": "Employee Calendar",
                "company": "Planck",
            },
            ("Company", "Planck"): {"default_holiday_list": "Company Calendar"},
            ("Holiday List", "Employee Calendar"): {
                "from_date": date(2026, 1, 1),
                "to_date": date(2026, 12, 31),
            },
        }.get((doctype, key))
    )
    frappe.get_all = lambda doctype, filters=None, pluck=None, **kwargs: [
        date(2026, 7, 4),
        date(2026, 7, 5),
    ] if doctype == "Holiday" and filters == {"parent": "Employee Calendar"} else []

    result = mod.resolve_monthly_work_limit(2026, 7, employee="EMP-1")

    assert result["calendar_source"] == "employee_holiday_list"
    assert result["holiday_list"] == "Employee Calendar"
    assert result["day_limit"] == 29
    assert result["hour_limit"] == 232


def test_incomplete_holiday_list_uses_weekday_fallback(calendar_module):
    mod, frappe = calendar_module
    frappe.db = types.SimpleNamespace(
        get_value=lambda doctype, key, fields=None, as_dict=False: {
            ("Company", "Planck"): {"default_holiday_list": "Old Calendar"},
            ("Holiday List", "Old Calendar"): {
                "from_date": date(2025, 1, 1),
                "to_date": date(2025, 12, 31),
            },
        }.get((doctype, key))
    )
    frappe.get_all = lambda *args, **kwargs: []

    result = mod.resolve_monthly_work_limit(2026, 7, company="Planck")

    assert result["calendar_source"] == "weekday_fallback"
    assert result["holiday_list"] == ""
    assert result["day_limit"] == 23
    assert result["hour_limit"] == 184


def test_personal_approved_leave_reduces_cap_and_withdrawal_restores_it(calendar_module, monkeypatch):
    mod, frappe = calendar_module
    dates = [date(2026, 9, 1), date(2026, 9, 2)]
    monkeypatch.setattr(mod, "resolve_monthly_calendar", lambda *a, **k: {
        "day_limit": 2, "hour_limit": 16, "work_dates": dates,
        "calendar_source": "employee_holiday_list", "holiday_list": "Calendar",
    })
    rows = [{"request_type": "请假申请", "workflow_status": "已完成", "leave_type": "事假", "from_date": "2026-09-01", "to_date": "2026-09-02",
             "attendance_days": [{"work_date": "2026-09-01", "hours": 4.25}, {"work_date": "2026-09-02", "hours": 8}]}]
    def get_all(doctype, *, filters, **kwargs):
        assert filters["employee"] == "EMP-1"
        assert filters["request_type"] == "请假申请"
        assert filters["workflow_status"] == ["in", ["已完成", "已通过"]]
        assert filters["from_date"] == ["<=", date(2026, 9, 30)]
        return rows
    frappe.get_all = get_all
    result = mod.resolve_monthly_work_limit(2026, 9, employee="EMP-1")
    assert result["base_hour_limit"] == 16
    assert result["leave_hours"] == 12.25
    assert result["hour_limit"] == 3.75
    rows.clear()
    assert mod.resolve_monthly_work_limit(2026, 9, employee="EMP-1")["hour_limit"] == 16


def test_all_workdays_on_leave_means_zero_cap(calendar_module, monkeypatch):
    mod, frappe = calendar_module
    monkeypatch.setattr(mod, "resolve_monthly_calendar", lambda *a, **k: {
        "day_limit": 1, "hour_limit": 8, "work_dates": [date(2026, 9, 1)],
        "calendar_source": "weekday_fallback", "holiday_list": "",
    })
    frappe.get_all = lambda *a, **k: [{"request_type": "请假申请", "workflow_status": "已完成", "leave_type": "事假", "from_date": "2026-09-01", "to_date": "2026-09-01"}]
    result = mod.resolve_monthly_work_limit(2026, 9, employee="EMP-1")
    assert result["hour_limit"] == result["day_limit"] == 0


def test_save_cap_uses_current_read_instead_of_stale_snapshot(calendar_module, monkeypatch):
    mod, frappe = calendar_module
    monkeypatch.setattr(mod, "resolve_monthly_calendar", lambda *a, **k: {
        "day_limit": 1, "hour_limit": 8, "work_dates": [date(2026, 9, 1)],
    })
    frappe.get_all = lambda *a, **k: []
    def sql(query, args, **kwargs):
        assert query.endswith("FOR UPDATE")
        assert args[0] == "EMP-1"
        return [{"request_type": "请假申请", "workflow_status": "已完成", "leave_type": "事假", "from_date": "2026-09-01", "to_date": "2026-09-01"}]
    frappe.db = types.SimpleNamespace(sql=sql)
    assert mod.resolve_monthly_work_limit(2026, 9, employee="EMP-1", lock=True)["hour_limit"] == 0


def test_joining_and_relieving_dates_trim_the_month(calendar_module):
    # 审查 #51 / X3-6：月中入职、演示员工166的人按整月算上限，工时会摊到入职前、演示员工166后。
    mod, frappe = calendar_module
    frappe.db = types.SimpleNamespace(
        get_value=lambda doctype, key, fields=None, as_dict=False: {
            ("Employee", "EMP-1"): {
                "company": "Planck",
                "date_of_joining": date(2026, 7, 15),
                "relieving_date": date(2026, 7, 20),
            },
        }.get((doctype, key))
    )
    frappe.get_all = lambda *args, **kwargs: []

    result = mod.resolve_monthly_calendar(2026, 7, employee="EMP-1")

    assert result["work_dates"] == [date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17), date(2026, 7, 20)]
    assert result["day_limit"] == 4
    assert result["hour_limit"] == 32
    assert result["joined_on"] == "2026-07-15"
    assert result["relieved_on"] == "2026-07-20"


def test_stale_relieving_date_of_a_rehired_employee_is_ignored(calendar_module):
    mod, frappe = calendar_module
    frappe.db = types.SimpleNamespace(
        get_value=lambda doctype, key, fields=None, as_dict=False: {
            ("Employee", "EMP-1"): {
                "company": "Planck",
                "date_of_joining": date(2026, 3, 1),
                "relieving_date": date(2025, 12, 31),
            },
        }.get((doctype, key))
    )
    frappe.get_all = lambda *args, **kwargs: []

    result = mod.resolve_monthly_calendar(2026, 7, employee="EMP-1")

    assert result["day_limit"] == 23
    assert result["joined_on"] is None and result["relieved_on"] is None
