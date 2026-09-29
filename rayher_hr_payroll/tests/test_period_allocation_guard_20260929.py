"""研发期间分摊守卫：加锁后当前读（模块 5，2026-09-29）。"""
import importlib
import sys
import types
from types import SimpleNamespace


def _load(monkeypatch, *, import_name="RDI-1", status="Draft", allocated=False):
    frappe = types.ModuleType("frappe")
    calls = []

    def get_value(doctype, filters, field, **kwargs):
        calls.append((doctype, filters, field, kwargs))
        if isinstance(filters, dict):
            return import_name
        if field == "status":
            return status
        return filters

    frappe.db = SimpleNamespace(get_value=get_value, exists=lambda doctype, filters=None: allocated)
    frappe.only_for = lambda roles: None
    frappe._ = lambda text: text
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    return importlib.import_module("rayher_hr_payroll.api._guards"), calls


def test_import_marked_allocated_is_seen_through_a_locking_read(monkeypatch):
    # 审查第一轮 #9：快照里还没有分摊，但导入单已被并发提交的分摊标成 Allocated。
    guards, calls = _load(monkeypatch, status="Allocated", allocated=False)
    assert guards.period_has_submitted_allocation(2026, 9) is True
    assert ("RD Expense Import", "RDI-1", "status", {"for_update": True}) in calls


def test_no_allocation_means_hours_may_change(monkeypatch):
    guards, _calls = _load(monkeypatch, status="Submitted", allocated=False)
    assert guards.period_has_submitted_allocation(2026, 9) is False


def test_existing_check_is_kept_as_a_fallback(monkeypatch):
    guards, _calls = _load(monkeypatch, import_name=None, allocated=True)
    assert guards.period_has_submitted_allocation(2026, 9) is True
