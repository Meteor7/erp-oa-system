import importlib
import sys
import types
from types import SimpleNamespace


def _load(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.whitelist = lambda *args, **kwargs: args[0] if args and callable(args[0]) else (lambda fn: fn)
    frappe.db = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.api.hr_contribution_entry", None)
    module = importlib.import_module("rayher_hr_payroll.api.hr_contribution_entry")
    return module, frappe


def test_employee_options_returns_kind_specific_default_bases(monkeypatch):
    module, frappe = _load(monkeypatch)
    captured = {}

    def get_all(doctype, filters=None, fields=None, order_by=None):
        captured.update(doctype=doctype, filters=filters, fields=fields, order_by=order_by)
        return [{"name": "EMP-1", "employee_name": "员工", "default_social_insurance_base": 8000, "default_housing_fund_base": 9000}]

    frappe.get_all = get_all
    rows = module.employee_options()

    assert captured == {
        "doctype": "Employee",
        "filters": {"status": "Active"},
        "fields": ["name", "employee_name", "default_social_insurance_base", "default_housing_fund_base"],
        "order_by": "employee_name",
    }
    assert rows[0]["default_social_insurance_base"] == 8000
    assert rows[0]["default_housing_fund_base"] == 9000