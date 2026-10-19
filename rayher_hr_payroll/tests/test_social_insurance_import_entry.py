import importlib
import sys
import types
from decimal import Decimal
from types import SimpleNamespace


def _load(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.whitelist = lambda *args, **kwargs: (args[0] if args and callable(args[0]) else lambda fn: fn)
    frappe.session = SimpleNamespace(user="Administrator")
    frappe.db = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    guards = types.ModuleType("rayher_hr_payroll.api._guards")
    guards.require_rd_access = lambda roles: None
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.api._guards", guards)
    sys.modules.pop("rayher_hr_payroll.api.social_insurance_import_entry", None)
    return importlib.import_module("rayher_hr_payroll.api.social_insurance_import_entry"), frappe


def test_employees_prefers_exact_period_social_base(monkeypatch):
    mod, frappe = _load(monkeypatch)
    def get_all(doctype, **kwargs):
        if doctype == "Employee":
            return [{"name": "EMP-1", "employee_name": "员工", "company": "QIHENG Demo", "default_social_insurance_base": 5000}]
        if doctype == "Employee Social Insurance":
            assert kwargs["filters"] == {"period": "2026-07"}
            return [{"employee": "EMP-1", "contribution_base": 6000}]
        raise AssertionError(doctype)
    frappe.get_all = get_all
    rows = mod._employees("2026-07")
    assert rows[0]["social_insurance_base"] == Decimal("6000.00")
    assert rows[0]["social_base_source"] == "2026-07月度社保记录"


def test_row_values_store_reconciliation_snapshot(monkeypatch):
    mod, _frappe = _load(monkeypatch)
    batch = SimpleNamespace(name="BATCH-1", period="2026-07")
    row = {"row_number": 1, "excel_name": "员工", "identity_number": "123", **{field: 0 for field in mod.EXCEL_FIELDS}}
    result = {
        "employee": "EMP-1", "employee_name": "员工", "company": "QIHENG Demo",
        "status": "Matched", "original_match_status": "Matched",
        "reference_base": Decimal("5000"), "base_source": "员工默认基数",
        "household_source": "深圳", "household_classification": "深户",
        "policy_version": "示例总部-2026", "calculated": {},
    }
    values = mod._row_values(batch, row, result)
    assert values["reference_base"] == Decimal("5000")
    assert values["base_source"] == "员工默认基数"
    assert values["household_source"] == "深圳"
    assert values["household_classification"] == "深户"
    assert values["policy_version"] == "示例总部-2026"


def test_resolution_apis_are_exposed(monkeypatch):
    mod, _frappe = _load(monkeypatch)
    assert callable(mod.ignore_social_row)
    assert callable(mod.cancel_social_batch)


def test_confirm_social_row_accepts_resolved_employee_dict(monkeypatch):
    mod, frappe = _load(monkeypatch)
    class RowDoc:
        name = "ROW-1"
        batch = "BATCH-1"
        period = "2026-07"
        status = "Pending"
        employee = None
        source_row = 4
        excel_name = "员工"
        identity_number = "123"
        def get(self, key):
            return getattr(self, key, 0)
        def set(self, key, value):
            setattr(self, key, value)
        def save(self, **kwargs):
            self.saved = True
    row = RowDoc()
    batch = SimpleNamespace(status="Pending Activation")
    frappe.get_doc = lambda doctype, name: row if doctype == "Social Insurance Import Row" else batch
    frappe.db = SimpleNamespace(exists=lambda *args, **kwargs: False, commit=lambda: None)
    frappe.utils = SimpleNamespace(now=lambda: "2026-08-05 12:00:00")
    monkeypatch.setattr(mod, "_employees", lambda period: [{
        "name": "EMP-1", "employee_name": "员工", "company": "QIHENG Demo",
        "id_card_number_cn": "123", "household_registration": "深圳",
        "social_insurance_base": Decimal("10000"), "social_base_source": "员工默认基数",
    }])
    monkeypatch.setattr(mod, "_refresh_batch_summary", lambda batch: None)
    monkeypatch.setattr(mod, "get_social_workbench", lambda period, company, batch: {"ok": True})
    monkeypatch.setattr(mod, "reconcile_row", lambda *args, **kwargs: {
        "calculated": {}, "difference_total": 0, "difference_reasons": "人工确认",
        "reference_base": Decimal("10000"), "base_source": "员工默认基数",
        "household_source": "深圳", "household_classification": "深户",
        "policy_version": "示例总部-2026"
    })
    assert mod.confirm_social_row("ROW-1", "EMP-1", "确认差异") == {"ok": True}
    assert row.employee == "EMP-1"
    assert row.status == "Confirmed Difference"
    assert row.reference_base == Decimal("10000")
    assert row.household_classification == "深户"


def test_pending_batch_reconciliation_is_exposed(monkeypatch):
    mod, _frappe = _load(monkeypatch)
    assert callable(mod.reconcile_pending_batch)


def test_workbench_batch_query_includes_cancel_audit(monkeypatch):
    mod, _frappe = _load(monkeypatch)
    import inspect
    source = inspect.getsource(mod.get_social_workbench)
    assert "cancel_remark" in source
    assert "canceled_by" in source
    assert "canceled_at" in source
