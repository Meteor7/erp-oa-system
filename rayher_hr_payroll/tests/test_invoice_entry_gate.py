import importlib
import sys
import types


def test_authenticated_guard_requires_expense_feature(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.session = types.SimpleNamespace(user="employee@example.com")
    frappe.ValidationError = ValueError
    frappe.throw = lambda message, exc=None: (_ for _ in ()).throw((exc or RuntimeError)(message))
    frappe.whitelist = lambda *args, **kwargs: (lambda fn: fn)
    monkeypatch.setitem(sys.modules, "frappe", frappe)

    attachments = types.ModuleType("rayher_hr_payroll.invoice_supplemental_attachments")
    service = types.ModuleType("rayher_hr_payroll.invoice_ocr.service")
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.invoice_supplemental_attachments", attachments)
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.invoice_ocr.service", service)
    sys.modules.pop("rayher_hr_payroll.api.invoice_entry", None)
    module = importlib.import_module("rayher_hr_payroll.api.invoice_entry")

    seen = []
    monkeypatch.setattr(module, "require_request_type_access", seen.append)
    module._authenticated()
    assert seen == [module.REQUEST_EXPENSE_PAYMENT]