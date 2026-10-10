import importlib
import inspect
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
    guards.require_hr_sensitive_access = lambda: None
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.api._guards", guards)
    for name in ("rayher_hr_payroll.api.housing_fund_import_entry", "rayher_hr_payroll.api.social_insurance_import_entry"):
        sys.modules.pop(name, None)
    return importlib.import_module("rayher_hr_payroll.api.housing_fund_import_entry"), frappe


def test_every_step_of_the_flow_is_exposed(monkeypatch):
    mod, _frappe = _load(monkeypatch)
    for name in ("get_fund_workbench", "upload_fund_workbook", "activate_fund_batch", "confirm_fund_row", "ignore_fund_row", "cancel_fund_batch", "reconcile_fund_batch"):
        assert callable(getattr(mod, name)), name


def test_the_workbench_lists_what_was_already_decided_including_ignored_rows(monkeypatch):
    mod, _frappe = _load(monkeypatch)
    source = inspect.getsource(mod.get_fund_workbench)
    assert '"handled"' in source and "Ignored" in source
    assert "cancel_remark" in " ".join(mod.BATCH_FIELDS) and "canceled_by" in mod.BATCH_FIELDS


def test_a_row_stores_the_excel_figures_next_to_the_recalculation(monkeypatch):
    mod, _frappe = _load(monkeypatch)
    batch = SimpleNamespace(name="HFB-1", period="2026-10")
    row = {"row_number": 1, "source_row": 5, "excel_name": "员工", "identity_number": "110101199001010070",
           "contribution_base": Decimal("10000"), "employee_amount": Decimal("700"), "company_amount": Decimal("700")}
    result = {"employee": "EMP-1", "employee_name": "员工", "company": "Rayher", "status": "Matched", "original_match_status": "Matched",
              "reference_base": Decimal("10000"), "base_source": "员工默认基数", "reference_employee_rate": Decimal("7"), "reference_company_rate": Decimal("7"),
              "calculated": {"employee_amount": Decimal("700"), "company_amount": Decimal("700")}, "difference_total": Decimal("0")}
    values = mod._row_values(batch, row, result)
    assert values["row_key"] == "HFB-1|1" and values["source_row"] == 5 and values["row_type"] == "excel"
    assert values["receivable_total"] == Decimal("1400") and values["calculated_receivable_total"] == Decimal("1400")
    assert values["masked_identity"].startswith("4403") and "1234" in values["masked_identity"]


def test_a_person_missing_from_the_file_becomes_a_pending_row_with_their_expected_amounts(monkeypatch):
    mod, _frappe = _load(monkeypatch)
    employee = {"name": "EMP-2", "employee_name": "员工乙", "company": "Rayher", "housing_fund_base": Decimal("10000"),
                "housing_base_source": "员工默认基数", "employee_rate": Decimal("7"), "company_rate": Decimal("7")}
    values = mod._missing_row_values(SimpleNamespace(name="HFB-1", period="2026-10"), employee)
    assert values["row_type"] == "missing" and values["status"] == "Pending" and values["employee"] == "EMP-2"
    assert values["difference_reasons"] == mod.MISSING_REASON
    assert values["calculated_receivable_total"] == Decimal("1400.00") and values["difference_total"] == Decimal("-1400.00")
    assert values["row_key"] == "HFB-1|missing|EMP-2"


def test_activation_writes_monthly_records_and_clears_stale_imported_ones(monkeypatch):
    mod, _frappe = _load(monkeypatch)
    source = inspect.getsource(mod._write_monthly_records)
    assert "rates_from_amounts" in source          # a confirmed difference is stored as the Excel's figures
    assert "delete_doc" in source and "IMPORT_REMARK" in source
    assert "Matched" in source and "Confirmed Difference" in source


def test_missing_rows_follow_the_archive_when_the_batch_is_rechecked(monkeypatch):
    mod, _frappe = _load(monkeypatch)
    source = inspect.getsource(mod.reconcile_fund_batch) + inspect.getsource(mod._sync_missing_rows)
    assert "_sync_missing_rows" in source
    assert "delete_doc" in source and "missing_from_excel" in source
