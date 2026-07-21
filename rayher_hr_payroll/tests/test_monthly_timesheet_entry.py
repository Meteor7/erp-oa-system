import importlib
import sys
import types
from decimal import Decimal

import pytest


class RuleError(Exception):
    pass


@pytest.fixture
def monthly_module(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.throw = lambda message: (_ for _ in ()).throw(RuleError(str(message)))

    def whitelist(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    frappe.whitelist = whitelist
    frappe.utils = types.ModuleType("frappe.utils")
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", frappe.utils)
    sys.modules.pop("rayher_hr_payroll.api.monthly_timesheet_entry", None)
    return importlib.import_module("rayher_hr_payroll.api.monthly_timesheet_entry"), frappe


def test_two_decimal_days_split_into_full_and_partial_hours(monthly_module):
    mod, _frappe = monthly_module

    days = mod.parse_occurrence_days("2.35", 2026, 7)

    assert days == Decimal("2.35")
    assert mod.calculated_hours(days) == Decimal("18.80")
    assert mod.split_day_hours(days) == [Decimal("8.00"), Decimal("8.00"), Decimal("2.80")]


@pytest.mark.parametrize("value", ["0", "-1", "1.001", "abc", ""])
def test_invalid_days_are_rejected(monthly_module, value):
    mod, _frappe = monthly_module

    with pytest.raises(RuleError):
        mod.parse_occurrence_days(value, 2026, 7)


def test_days_cannot_exceed_calendar_month(monthly_module):
    mod, _frappe = monthly_module

    with pytest.raises(RuleError):
        mod.parse_occurrence_days("29.01", 2026, 2)


def test_leap_year_allows_twenty_nine_days(monthly_module):
    mod, _frappe = monthly_module

    assert mod.parse_occurrence_days("29.00", 2028, 2) == Decimal("29.00")
