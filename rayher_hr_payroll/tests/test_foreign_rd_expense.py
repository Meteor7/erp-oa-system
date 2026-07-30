import importlib
import sys
import types
from types import SimpleNamespace


class RuleError(Exception):
    pass


def _load_foreign_rd_expense(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text

    def throw(message):
        raise RuleError(str(message))

    frappe.throw = throw
    frappe.db = SimpleNamespace(exists=lambda *args, **kwargs: False)

    model = types.ModuleType("frappe.model")
    document = types.ModuleType("frappe.model.document")

    class Document:
        def __init__(self, **values):
            self.__dict__.update(values)

    document.Document = Document
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.model", model)
    monkeypatch.setitem(sys.modules, "frappe.model.document", document)
    module_name = (
        "rayher_hr_payroll.rayher_hr_payroll.doctype."
        "foreign_rd_expense.foreign_rd_expense"
    )
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_new_foreign_rd_expense_uses_one_deterministic_name_per_period(monkeypatch):
    mod = _load_foreign_rd_expense(monkeypatch)
    doc = mod.ForeignRDExpense(year=2026, month=7, period="2026/07")

    doc.autoname()

    assert doc.period == "202607"
    assert doc.name == "FRD-2026-07"
