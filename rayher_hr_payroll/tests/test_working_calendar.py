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
    frappe.get_all = lambda doctype, filters=None, pluck=None: [
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