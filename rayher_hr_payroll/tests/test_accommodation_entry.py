import importlib
import sys
import types
from types import SimpleNamespace

import pytest


class RuleError(Exception):
    pass


def _install_fake_frappe(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.only_for = lambda roles: None
    frappe.has_permission = lambda *args, **kwargs: True

    def throw(message):
        raise RuleError(str(message))

    def whitelist(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    frappe.throw = throw
    frappe.whitelist = whitelist
    frappe.db = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    return frappe


def _load_accommodation_entry(monkeypatch):
    frappe = _install_fake_frappe(monkeypatch)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.api.accommodation_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.accommodation_entry")
    return mod, frappe


def test_get_emp_options_exposes_employee_expense_category(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))

    def get_all(doctype, fields=None, order_by=None, **kwargs):
        assert doctype == "Employee"
        captured["fields"] = fields
        return [{"name": "EMP-1", "employee_name": "演示员工129", "expense_account_category": "研发费用"}]

    frappe.get_all = get_all

    data = mod.get_emp_options()

    assert captured["roles"] == ("System Manager", "HR User", "HR Manager")
    assert "expense_account_category" in captured["fields"]
    assert data[0]["expense_account_category"] == "研发费用"


def test_get_room_options_returns_distinct_nonempty_rooms(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.get_all = lambda *args, **kwargs: ["A315", "A316"]

    assert mod.get_room_options() == ["A315", "A316"]


def test_save_accommodation_persists_room_split_and_expense_category_snapshot(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "list_accommodation", lambda period: [{"period": period, "ok": True}])

    def get_value(doctype, name_or_filters, fieldname=None, **kwargs):
        if doctype == "Employee" and fieldname == "name":
            return name_or_filters
        if doctype == "Employee" and fieldname == "expense_account_category":
            return "研发费用"
        if doctype == "Accommodation Deduction":
            return None
        return None

    def get_doc(arg, name=None):
        if isinstance(arg, dict) and arg.get("doctype") == "Accommodation Deduction":
            captured["doc"] = arg
            return SimpleNamespace(insert=lambda ignore_permissions=False: captured.setdefault("insert", ignore_permissions))
        raise AssertionError((arg, name))

    frappe.db.get_value = get_value
    frappe.get_doc = get_doc
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    result = mod.save_accommodation(
        period="2026-07",
        employee="EMP-1",
        room_no="A315",
        rent_amount=1000,
        water_amount=30,
        electricity_amount=20,
        personal_rent_amount=200,
        personal_water_amount=10,
        personal_electricity_amount=5,
        company_rent_amount=800,
        company_water_amount=20,
        company_electricity_amount=15,
    )

    assert result == [{"period": "2026-07", "ok": True}]
    doc = captured["doc"]
    assert doc["room_no"] == "A315"
    assert doc["rent_amount"] == 1000
    assert doc["water_amount"] == 30
    assert doc["electricity_amount"] == 20
    assert doc["personal_rent_amount"] == 200
    assert doc["personal_water_amount"] == 10
    assert doc["personal_electricity_amount"] == 5
    assert doc["personal_total_amount"] == 215
    assert doc["company_rent_amount"] == 800
    assert doc["company_water_amount"] == 20
    assert doc["company_electricity_amount"] == 15
    assert doc["company_total_amount"] == 835
    assert doc["expense_account_category"] == "研发费用"
    assert doc["total_amount"] == 1050
    assert captured["insert"] is True
    assert captured["committed"] is True


def test_save_accommodation_rejects_split_amounts_above_totals(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    frappe.db.get_value = lambda doctype, name_or_filters, fieldname=None, **kwargs: "研发费用" if fieldname == "expense_account_category" else name_or_filters
    frappe.get_doc = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not insert"))

    with pytest.raises(RuleError, match="不能超过总费用"):
        mod.save_accommodation(
            period="2026-07",
            employee="EMP-1",
            room_no="A315",
            rent_amount=100,
            water_amount=0,
            electricity_amount=0,
            personal_rent_amount=60,
            company_rent_amount=50,
        )


def test_save_special_occupant_uses_management_expense_without_employee(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "list_accommodation", lambda period: [{"period": period}])

    def get_value(doctype, filters, fieldname=None, **kwargs):
        if doctype == "Accommodation Deduction":
            captured["lookup"] = filters
            return None
        raise AssertionError("special occupant must not query Employee")

    def get_doc(arg, name=None):
        assert isinstance(arg, dict)
        captured["doc"] = arg
        return SimpleNamespace(insert=lambda ignore_permissions=False: None)

    frappe.db.get_value = get_value
    frappe.get_doc = get_doc
    frappe.db.commit = lambda: None

    mod.save_accommodation(
        period="2026-07",
        employee="",
        occupant_type="客房",
        room_no="A316",
        rent_amount=100,
        company_rent_amount=100,
    )

    assert captured["doc"]["employee"] is None
    assert captured["doc"]["occupant_type"] == "客房"
    assert captured["doc"]["expense_account_category"] == "管理费用"
    assert captured["lookup"] == {
        "period": "2026-07",
        "occupant_type": "客房",
        "room_no": "A316",
        "employee": ["is", "not set"],
    }


def test_get_accommodation_summary_groups_company_amount_by_employee_expense_category(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    def get_all(doctype, filters=None, fields=None, order_by=None, **kwargs):
        assert doctype == "Accommodation Deduction"
        assert filters == {"period": "2026-07"}
        return [
            {"expense_account_category": "研发费用", "company_rent_amount": 800, "company_water_amount": 20, "company_electricity_amount": 15, "company_total_amount": 835},
            {"expense_account_category": "管理费用", "company_rent_amount": 100, "company_water_amount": 5, "company_electricity_amount": 5, "company_total_amount": 110},
            {"expense_account_category": "研发费用", "company_rent_amount": 200, "company_water_amount": 10, "company_electricity_amount": 10, "company_total_amount": 220},
        ]

    frappe.get_all = get_all

    summary = mod.get_accommodation_summary("2026-07")

    assert [row["expense_account_category"] for row in summary] == ["研发费用", "管理费用", "销售费用", "生产成本"]
    assert summary[0] == {
        "expense_account_category": "研发费用",
        "company_rent_amount": 1000.0,
        "company_water_amount": 30.0,
        "company_electricity_amount": 25.0,
        "company_total_amount": 1055.0,
    }
    assert summary[1]["company_total_amount"] == 110.0
    assert summary[2]["company_total_amount"] == 0.0
    assert summary[3]["company_total_amount"] == 0.0
