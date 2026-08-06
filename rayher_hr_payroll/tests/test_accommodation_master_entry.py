import importlib
import sys
import types
from types import SimpleNamespace

import pytest


class RuleError(Exception):
    pass


def _load_module(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.throw = lambda message: (_ for _ in ()).throw(RuleError(str(message)))

    def whitelist(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    frappe.whitelist = whitelist
    frappe.db = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.api.accommodation_master_entry", None)
    module = importlib.import_module("rayher_hr_payroll.api.accommodation_master_entry")
    return module, frappe


def test_room_status_uses_effective_employee_and_special_purpose(monkeypatch):
    module, _frappe = _load_module(monkeypatch)

    assert module.room_status("", SimpleNamespace(employee="EMP-1")) == "有人"
    assert module.room_status("空", None) == "空置"
    assert module.room_status("客房", None) == "客房"
    assert module.room_status("午休室", None) == "午休室"
    assert module.room_status("", None) == "空置"


def test_list_rooms_marks_ended_source_occupant_as_vacant(monkeypatch):
    module, frappe = _load_module(monkeypatch)
    monkeypatch.setattr(module, "require_rd_access", lambda roles: None)

    def get_all(doctype, **kwargs):
        if doctype == "Accommodation Room":
            return [
                {
                    "name": "B704",
                    "room_no": "B704",
                    "room_type": "一房一厅",
                    "lease_start_date": "2023-11-15",
                    "lease_end_date": "2026-10-14",
                    "monthly_rent": 1880,
                    "paid_deposit": 2000,
                    "rent_contract_attachment": "",
                    "deposit_attachment": "",
                    "occupant_label": "演示员工131",
                    "room_purpose": "",
                    "remark": "",
                    "is_active": 1,
                }
            ]
        if doctype == "Accommodation Occupancy":
            return [{
                "name": "OCC-B704", "employee": "HR-EMP-90019", "employee_name": "演示员工131",
                "room": "B704", "start_date": "2025-06-09", "end_date": "2026-06-18", "is_active": 0,
            }]
        raise AssertionError(doctype)

    frappe.get_all = get_all

    rows = module.list_rooms()

    assert rows[0]["occupancy_status"] == "空置"
    assert rows[0]["occupant_label"] == "演示员工131"
    assert rows[0]["employee"] is None
    assert rows[0]["end_date"] is None


def test_save_room_rejects_negative_master_amounts(monkeypatch):
    module, _frappe = _load_module(monkeypatch)
    monkeypatch.setattr(module, "require_rd_access", lambda roles: None)

    with pytest.raises(RuleError, match="金额不能为负数"):
        module.save_room(room_no="B702", monthly_rent=-1, paid_deposit=2000)

def test_list_checkout_history_returns_only_ended_records(monkeypatch):
    module, frappe = _load_module(monkeypatch)
    monkeypatch.setattr(module, "require_rd_access", lambda roles: None)
    captured = {}

    def get_all(doctype, **kwargs):
        captured.update({"doctype": doctype, **kwargs})
        return [{"name": "OLD-B704", "room": "B704", "employee": "HR-EMP-90019", "employee_name": "演示员工131", "start_date": "2025-06-09", "end_date": "2026-06-18", "remark": ""}]

    frappe.get_all = get_all
    rows = module.list_checkout_history()
    assert captured["filters"] == {"end_date": ["is", "set"]}
    assert captured["order_by"] == "end_date desc, modified desc"
    assert rows[0]["room"] == "B704"


def test_rejoining_same_room_creates_new_history_instead_of_overwriting_checkout(monkeypatch):
    module, frappe = _load_module(monkeypatch)
    monkeypatch.setattr(module, "require_rd_access", lambda roles: None)
    saved = []

    class FakeDoc:
        def __init__(self, name, employee=None):
            self.name = name
            self.room_no = name
            self.employee = employee
        def update(self, values):
            for key, value in values.items():
                setattr(self, key, value)
        def save(self, ignore_permissions=False):
            saved.append((self.name, getattr(self, "employee", None), getattr(self, "start_date", None), getattr(self, "end_date", None)))

    room = FakeDoc("B702")
    new_occupancy = FakeDoc("NEW-OCC")
    frappe.db.exists = lambda doctype, value: "B702" if doctype == "Accommodation Room" else True
    def get_value(doctype, filters, fieldname=None, **kwargs):
        if doctype == "Employee": return "演示员工108"
        if doctype == "Accommodation Occupancy" and kwargs.get("order_by"): return "OLD-OCC"
        if doctype == "Accommodation Occupancy": return None
        return None
    frappe.db.get_value = get_value
    frappe.get_doc = lambda doctype, name: room if doctype == "Accommodation Room" else (_ for _ in ()).throw(AssertionError("ended history must not be reopened"))
    frappe.new_doc = lambda doctype: new_occupancy
    frappe.db.commit = lambda: None

    module.save_room(room_no="B702", employee="HR-EMP-90015", start_date="2027-01-01")
    assert any(item[0] == "NEW-OCC" and item[2].isoformat() == "2027-01-01" for item in saved)