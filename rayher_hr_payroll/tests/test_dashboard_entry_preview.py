"""研发看板（get_dashboard）：本月没有定版的分摊单时，用预览顶上三个阶段合计并标出 preview。"""
import importlib
import sys
import types
from decimal import Decimal
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _forget_modules_bound_to_the_fake_frappe():
    yield
    for name in ("rayher_hr_payroll.api._guards", "rayher_hr_payroll.api.dashboard_entry"):
        sys.modules.pop(name, None)
    package = sys.modules.get("rayher_hr_payroll.api")
    for attribute in ("_guards", "dashboard_entry"):
        if package is not None and hasattr(package, attribute):
            delattr(package, attribute)


def _load(monkeypatch, *, roles=("Accounts User",), alloc=None, imp="IMP-1"):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.whitelist = lambda *args, **kwargs: (args[0] if args and callable(args[0]) else (lambda fn: fn))
    frappe.get_roles = lambda user=None: list(roles)
    frappe.only_for = lambda roles: None
    frappe.session = SimpleNamespace(user="finance@example.com")

    def throw(message):
        raise AssertionError(message)

    frappe.throw = throw

    def get_value(doctype, filters=None, fieldname=None, **kwargs):
        if doctype == "RD Expense Import":
            return imp
        if doctype == "RD Cost Allocation":
            return alloc
        return None

    def get_all(doctype, **kwargs):
        if doctype == "Employee":
            return []
        if doctype == "RD Expense Item":
            return []
        if doctype == "Accommodation Deduction":
            return []
        raise AssertionError(doctype)

    frappe.db = SimpleNamespace(
        get_value=get_value, count=lambda *args, **kwargs: 0, sql=lambda *args, **kwargs: [],
    )
    frappe.get_all = get_all
    utils = types.ModuleType("frappe.utils")
    utils.getdate = lambda value=None: value
    utils.nowdate = lambda: "2026-10-08"
    frappe.utils = utils
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    for name in ("rayher_hr_payroll.api._guards", "rayher_hr_payroll.api.dashboard_entry"):
        sys.modules.pop(name, None)
    mod = importlib.import_module("rayher_hr_payroll.api.dashboard_entry")
    monkeypatch.setattr(mod, "require_rd_access", lambda *args: None)
    payroll_bridge = importlib.import_module("rayher_hr_payroll.payroll_bridge")
    monkeypatch.setattr(payroll_bridge, "period_pay_totals", lambda period: {"gross": 1, "deductions": 2})
    return mod


def _patch_preview(monkeypatch, result):
    from rayher_hr_payroll.rd_cost import allocation_preview

    calls = []

    def build(period, year, month):
        calls.append((period, year, month))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(allocation_preview, "build_preview", build)
    return calls


def test_dashboard_without_a_finalized_allocation_uses_the_preview(monkeypatch):
    mod = _load(monkeypatch)
    doc = SimpleNamespace(capitalized_total=Decimal("70"), expensed_total=Decimal("30"), unknown_total=Decimal("5"))
    calls = _patch_preview(monkeypatch, SimpleNamespace(import_name="IMP-1", doc=doc, warnings=[], error=None))

    result = mod.get_dashboard("2026-09")

    assert calls == [("2026-09", 2026, 9)]
    assert result["preview"] is True
    assert result["alloc"] == {"capitalized": Decimal("70"), "expensed": Decimal("30"), "unknown": Decimal("5")}


def test_dashboard_with_a_finalized_allocation_never_previews(monkeypatch):
    mod = _load(monkeypatch, alloc={"capitalized_total": 1, "expensed_total": 2, "unknown_total": 3})
    calls = _patch_preview(monkeypatch, AssertionError("must not preview"))

    result = mod.get_dashboard("2026-09")

    assert calls == []
    assert result["preview"] is False
    assert result["alloc"] == {"capitalized": 1, "expensed": 2, "unknown": 3}


@pytest.mark.parametrize("outcome", [None, "failed", "raises"])
def test_dashboard_keeps_zero_alloc_when_the_preview_is_unavailable(monkeypatch, outcome):
    mod = _load(monkeypatch)
    result_value = {
        None: None,
        "failed": SimpleNamespace(import_name="IMP-1", doc=None, warnings=[], error="本月还没有研发工时"),
        "raises": RuntimeError("boom"),
    }[outcome]
    _patch_preview(monkeypatch, result_value)

    result = mod.get_dashboard("2026-09")

    assert result["preview"] is False
    assert result["alloc"] == {"capitalized": 0, "expensed": 0, "unknown": 0}


def test_dashboard_without_an_import_does_not_preview(monkeypatch):
    mod = _load(monkeypatch, imp=None)
    calls = _patch_preview(monkeypatch, AssertionError("must not preview"))

    assert mod.get_dashboard("2026-09")["preview"] is False
    assert calls == []


def test_dashboard_hides_the_preview_from_non_finance_users(monkeypatch):
    mod = _load(monkeypatch, roles=("HR User",))
    calls = _patch_preview(monkeypatch, AssertionError("must not preview"))

    result = mod.get_dashboard("2026-09")

    assert calls == []
    assert result["preview"] is False
    assert result["alloc"] == {"capitalized": 0, "expensed": 0, "unknown": 0}