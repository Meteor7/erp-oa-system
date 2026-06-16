import json
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = APP_ROOT / "rayher_hr_payroll"
DOCTYPE_ROOT = MODULE_ROOT / "doctype"


def load_doctype(folder: str) -> dict:
    path = DOCTYPE_ROOT / folder / f"{folder}.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def fieldnames(doc: dict) -> set[str]:
    return {field["fieldname"] for field in doc["fields"] if "fieldname" in field}


def test_frappe_module_package_exists_for_modules_txt():
    assert (MODULE_ROOT / "__init__.py").exists()
    assert DOCTYPE_ROOT.exists()


def test_rd_expense_item_has_source_row_key_for_duplicate_guard():
    doc = load_doctype("rd_expense_item")

    assert doc["istable"] == 1
    assert {"source_row_key", "voucher_no", "amount", "direct_project"}.issubset(fieldnames(doc))


def test_rd_cost_allocation_has_source_snapshot_tables():
    doc = load_doctype("rd_cost_allocation")
    fields = {field["fieldname"]: field for field in doc["fields"]}

    assert doc["is_submittable"] == 1
    assert fields["hour_snapshots"]["options"] == "RD Allocation Source Hour"
    assert fields["expense_snapshots"]["options"] == "RD Allocation Source Expense"


def test_rd_period_lock_locks_timesheets_gl_and_allocations():
    doc = load_doctype("rd_period_lock")

    assert doc["is_submittable"] == 1
    assert {"lock_timesheets", "lock_project_stage", "lock_gl_import", "lock_allocations"}.issubset(fieldnames(doc))


def test_rayher_hr_settings_contains_standard_daily_hours():
    doc = load_doctype("rayher_hr_settings")

    assert doc["issingle"] == 1
    assert "standard_daily_hours" in fieldnames(doc)