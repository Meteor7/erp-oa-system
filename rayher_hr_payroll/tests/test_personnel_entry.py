import importlib
import sys
import types
from types import SimpleNamespace


class RuleError(Exception):
    pass


def _install_fake_frappe(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.only_for = lambda roles: None
    frappe.has_permission = lambda *args, **kwargs: True
    frappe.get_roles = lambda user=None: ["System Manager"]
    frappe.session = SimpleNamespace(user="Administrator")

    def throw(message):
        raise RuleError(str(message))

    def whitelist(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    frappe.throw = throw
    frappe.whitelist = whitelist
    frappe.db = SimpleNamespace(commit=lambda: None)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    return frappe


def _load_personnel_entry(monkeypatch):
    frappe = _install_fake_frappe(monkeypatch)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.api.personnel_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.personnel_entry")
    return mod, frappe


def test_list_employees_returns_relieving_date_without_status_filter(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))

    def get_all(doctype, fields=None, order_by=None, **kwargs):
        captured["doctype"] = doctype
        captured["fields"] = fields
        captured["order_by"] = order_by
        captured["kwargs"] = kwargs
        return []

    frappe.get_all = get_all

    assert mod.list_employees() == []

    assert captured["roles"] == mod.RD_HR_WRITE
    assert captured["doctype"] == "Employee"
    assert "relieving_date" in captured["fields"]
    assert "designation" in captured["fields"]
    assert captured["kwargs"].get("filters") in (None, {})


def test_get_designation_options_returns_position_names(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    def get_all(doctype, pluck=None, order_by=None, **kwargs):
        assert doctype == "Designation"
        assert pluck == "name"
        assert order_by == "name"
        return ["工程师", "财务主管"]

    frappe.get_all = get_all

    assert mod.get_designation_options() == ["工程师", "财务主管"]


def test_save_employee_sets_left_status_when_relieving_date_is_saved(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    class FakeDoc:
        name = "EMP-LEFT"

        def update(self, values):
            captured["values"] = dict(values)

        def save(self, ignore_permissions=False):
            captured["saved"] = ignore_permissions

    frappe.get_doc = lambda doctype, name=None: FakeDoc()

    result = mod.save_employee(
        name="EMP-LEFT",
        employee_name="Left Employee",
        relieving_date="2026-06-17",
        designation="工程师",
    )

    assert result == {"name": "EMP-LEFT"}
    assert captured["values"]["relieving_date"] == "2026-06-17"
    assert captured["values"]["status"] == "Left"
    assert captured["values"]["designation"] == "工程师"
    assert captured["saved"] is True
