import importlib
import sys
import types


def module(monkeypatch):
    monkeypatch.setitem(sys.modules, "frappe", types.ModuleType("frappe"))
    sys.modules.pop(
        "rayher_hr_payroll.patches.v1_0.migrate_demo_executive_account", None
    )
    return importlib.import_module(
        "rayher_hr_payroll.patches.v1_0.migrate_demo_executive_account"
    )


def test_replaces_only_exact_demo_executive_user_ids(monkeypatch):
    migration = module(monkeypatch)

    assert migration.replace_user_id_list(
        '["person046@business.example.invalid", "other@example.com"]'
    ) == '["person046@staff.example.invalid", "other@example.com"]'
    assert migration.replace_user_id_list(
        '["person044@business.example.invalid"]'
    ) == '["person044@business.example.invalid"]'
    assert migration.replace_user_id_list("not-json") == "not-json"
