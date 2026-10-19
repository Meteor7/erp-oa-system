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
    frappe.db = SimpleNamespace(exists=lambda *args, **kwargs: True)
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
        return [{"name": "EMP-1", "employee_name": "南通工厂9", "expense_account_category": "研发费用"}]

    frappe.get_all = get_all

    data = mod.get_emp_options()

    assert captured["roles"] == ("System Manager", "HR User", "HR Manager")
    assert "expense_account_category" in captured["fields"]
    assert "status" in captured["fields"]
    assert data[0]["expense_account_category"] == "研发费用"
    assert not hasattr(mod, "save_occupancy") and not hasattr(mod, "list_occupancies")


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
    monkeypatch.setattr(mod, "get_room_occupants", lambda *args, **kwargs: [{"value": "employee:EMP-1"}])

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
    frappe.get_all = lambda *args, **kwargs: [SimpleNamespace(end_date=None)]
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


def test_guest_room_uses_sales_expense_category(monkeypatch):
    mod, _frappe = _load_accommodation_entry(monkeypatch)

    values = mod._payload(
        "2026-08", None, "客房", "A703",
        0, 0, 0,
        0, 0, 0,
        0, 0, 0,
    )

    assert values["expense_account_category"] == "销售费用"

def test_payload_derives_totals_from_personal_and_company_amounts(monkeypatch):
    mod, _frappe = _load_accommodation_entry(monkeypatch)
    monkeypatch.setattr(mod, "_category_for_occupant", lambda *args: "研发费用")

    values = mod._payload(
        "2026-07", "EMP-1", "员工", "A315",
        1, 2, 3,
        60, 0, 0,
        50, 0, 0,
    )

    assert values["rent_amount"] == 110
    assert values["total_amount"] == 110
    assert values["personal_total_amount"] == 60
    assert values["company_total_amount"] == 50

def test_save_non_a703_guest_room_uses_management_expense_without_employee(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "list_accommodation", lambda period: [{"period": period}])
    monkeypatch.setattr(mod, "get_room_occupants", lambda *args, **kwargs: [{"value": "special:客房"}])

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
    frappe.get_all = lambda *args, **kwargs: [SimpleNamespace(end_date=None)]
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


def test_delete_accommodation_deletes_existing_record_without_unrelated_room_validation(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: captured.setdefault("lock", args))
    frappe.db.get_value = lambda doctype, name, field: "2026-07"
    frappe.delete_doc = lambda doctype, name, ignore_permissions=False: captured.setdefault(
        "deleted", (doctype, name, ignore_permissions)
    )
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    result = mod.delete_accommodation("ACC-1")

    assert result == {"ok": True}
    assert captured["roles"] == ("System Manager",)
    assert captured["lock"] == ("2026-07", "lock_timesheets", "工时")
    assert captured["deleted"] == ("Accommodation Deduction", "ACC-1", True)
    assert captured["committed"] is True

def test_get_allowed_rooms_returns_only_effective_employee_room(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    def get_all(doctype, filters=None, fields=None, order_by=None, **kwargs):
        if doctype == "Accommodation Occupancy":
            assert filters == {"employee": "HR-EMP-90015"}
            return [
                SimpleNamespace(room="B702", start_date=None, end_date=None, is_active=1),
                SimpleNamespace(room="B407", start_date="2025-06-16", end_date="2026-06-18", is_active=0),
            ]
        if doctype == "Accommodation Room":
            assert filters == {"name": ["in", ["B702"]], "is_active": 1}
            return [{"name": "B702", "room_no": "B702", "room_type": "一房一厅", "monthly_rent": 1880}]
        raise AssertionError(doctype)

    frappe.get_all = get_all

    rows = mod.get_allowed_rooms("2026-08", employee="HR-EMP-90015")

    assert rows == [{"name": "B702", "room_no": "B702", "room_type": "一房一厅", "monthly_rent": 1880}]


def test_save_rejects_room_outside_period_relation(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "get_room_occupants", lambda *args, **kwargs: [{"value": "employee:OTHER"}])
    frappe.db.exists = lambda *args, **kwargs: True

    with pytest.raises(RuleError, match="没有此房间的有效入住关系"):
        mod.save_accommodation(period="2026-08", employee="HR-EMP-90015", room_no="B407")

def test_get_room_occupants_returns_hexie_for_b702(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.get_value = lambda *args, **kwargs: {"name": "B702", "room_purpose": ""}
    frappe.get_all = lambda *args, **kwargs: [
        {"employee": "HR-EMP-90015", "employee_name": "演示员工108", "start_date": "2024-08-24", "end_date": None, "is_active": 1}
    ]

    assert mod.get_room_occupants("2026-08", "B702") == [{
        "value": "employee:HR-EMP-90015", "employee": "HR-EMP-90015",
        "occupant_type": "员工", "label": "演示员工108", "start_date": "2024-08-24", "end_date": None,
    }]


def test_get_room_occupants_returns_vacant_choice_after_checkout(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.get_value = lambda *args, **kwargs: {"name": "B704", "room_purpose": ""}
    frappe.get_all = lambda *args, **kwargs: [
        {"employee": "HR-EMP-90019", "employee_name": "演示员工131", "start_date": "2025-06-09", "end_date": "2026-06-18", "is_active": 0}
    ]

    assert mod.get_room_occupants("2026-08", "B704") == [{
        "value": "special:空", "employee": None, "occupant_type": "空",
        "label": "空（空置房间费用）", "start_date": None, "end_date": None,
    }]


def test_get_room_occupants_keeps_both_people_during_turnover_month(monkeypatch):
    mod, frappe = _load_accommodation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.get_value = lambda *args, **kwargs: {"name": "A203", "room_purpose": ""}
    frappe.get_all = lambda *args, **kwargs: [
        {"employee": "EMP-OLD", "employee_name": "旧入住人", "start_date": "2026-01-01", "end_date": "2026-08-15", "is_active": 0},
        {"employee": "EMP-NEW", "employee_name": "新入住人", "start_date": "2026-08-16", "end_date": None, "is_active": 1},
    ]

    choices = mod.get_room_occupants("2026-08", "A203")
    assert [choice["value"] for choice in choices] == ["employee:EMP-OLD", "employee:EMP-NEW"]