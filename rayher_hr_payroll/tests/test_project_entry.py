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
    frappe.db = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    return frappe


def _load_project_entry(monkeypatch):
    frappe = _install_fake_frappe(monkeypatch)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.api.project_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.project_entry")
    return mod, frappe


def test_project_manage_roles_include_finance(monkeypatch):
    mod, _frappe = _load_project_entry(monkeypatch)

    assert "Accounts User" in mod.RD_PROJECT_MANAGE_ROLES


def test_save_project_creates_timesheet_enabled_project(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    frappe.db.exists = lambda doctype, name_or_filters=None: False
    frappe.db.get_single_value = lambda *args, **kwargs: "Rayher"
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    def get_doc(arg, name=None):
        if isinstance(arg, dict) and arg.get("doctype") == "Project":
            captured["doc"] = arg
            return SimpleNamespace(
                name=arg["name"],
                insert=lambda ignore_permissions=False, set_name=None: captured.setdefault("insert", (ignore_permissions, set_name)),
            )
        raise AssertionError(arg)

    frappe.get_doc = get_doc
    frappe.get_all = lambda *args, **kwargs: ["Rayher"]

    result = mod.save_project(
        project_code="RD18",
        project_name="NEW PROJECT",
        start_date="2026-07-01",
        end_date="",
        status="Open",
        rd_stage="费用化",
    )

    assert captured["roles"] == mod.RD_PROJECT_MANAGE_ROLES
    assert result == {"name": "RD18"}
    assert captured["doc"] == {
        "doctype": "Project",
        "name": "RD18",
        "project_name": "NEW PROJECT",
        "rd_project_code": "RD18",
        "rd_project_key": "RD18 | NEW PROJECT",
        "status": "Open",
        "company": "Rayher",
        "allow_rd_timesheet": 1,
        "rd_stage": "费用化",
        "capitalization_start_date": "2026-07-01",
        "capitalization_end_date": None,
        "project_owner_name": None,
        "project_owner": None,
        "project_initiation_report": None,
        "project_completion_report": None,
        "capitalization_confirmation_file": None,
    }
    assert captured["insert"] == (True, "RD18")
    assert captured["committed"] is True


def test_cancel_project_keeps_project_but_disables_timesheet_options(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))

    class Doc:
        name = "RD18"
        def update(self, values):
            captured["values"] = values
        def save(self, ignore_permissions=False):
            captured["save"] = ignore_permissions

    frappe.get_doc = lambda doctype, name: Doc() if doctype == "Project" and name == "RD18" else (_ for _ in ()).throw(AssertionError(name))
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    assert mod.cancel_project("RD18") == {"ok": True}
    assert captured["roles"] == mod.RD_PROJECT_MANAGE_ROLES
    assert captured["values"] == {"status": "Cancelled", "allow_rd_timesheet": 0}
    assert captured["save"] is True
    assert captured["committed"] is True


def test_default_project_seed_contains_screenshot_projects(monkeypatch):
    mod, _frappe = _load_project_entry(monkeypatch)

    by_code = {item["project_code"]: item for item in mod.DEFAULT_RAYHER_PROJECTS}
    assert by_code["RD17"]["project_name"] == "EFEM-12-2LP-EG-A"
    assert by_code["RD12"]["project_name"] == "Self-developed EFEM"
    assert by_code["RD18"] == {
        "project_code": "RD18",
        "project_name": "KIBO 4895",
        "start_date": "2026-07-01",
        "end_date": "",
        "status": "Open",
        "rd_stage": "费用化",
    }
    assert by_code["RD19"] == {
        "project_code": "RD19",
        "project_name": "KIBO 4895C",
        "start_date": "2026-07-01",
        "end_date": "",
        "status": "Open",
        "rd_stage": "费用化",
    }
    assert by_code["RD08"]["end_date"] == "2025-12-31"
    assert by_code["RD01"]["status"] == "Completed"
    assert by_code["RD01"]["rd_stage"] == "资本化"
    assert by_code["RD16"]["rd_stage"] == "费用化"


def test_list_projects_returns_rd_stage(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    frappe.get_all = lambda *args, **kwargs: [{
        "name": "RD18",
        "project_name": "KIBO 4895",
        "rd_project_code": "RD18",
        "rd_project_key": "RD18 | KIBO 4895",
        "status": "Open",
        "rd_stage": "费用化",
        "allow_rd_timesheet": 1,
        "capitalization_start_date": "2026-07-01",
        "capitalization_end_date": None,
    }]

    rows = mod.list_projects()

    assert rows[0]["rd_stage"] == "费用化"
    assert rows[0]["rd_stage_label"] == "费用化"


def test_save_project_keeps_owner_and_project_document_links(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.exists = lambda *args, **kwargs: False
    frappe.db.get_single_value = lambda *args, **kwargs: "Rayher"
    frappe.db.commit = lambda: None
    frappe.get_all = lambda *args, **kwargs: ["Rayher"]

    def get_doc(arg, name=None):
        if isinstance(arg, dict):
            captured["doc"] = arg
            return SimpleNamespace(name=arg["name"], insert=lambda **kwargs: None)
        raise AssertionError(arg)

    frappe.get_doc = get_doc

    mod.save_project(
        project_code="RD20",
        project_name="OWNER PROJECT",
        project_owner_name="演示员工107",
        project_initiation_report="/private/files/initiation.pdf",
        project_completion_report="/private/files/completion.pdf",
        capitalization_confirmation_file="/private/files/capitalization.pdf",
    )

    assert captured["doc"]["project_owner_name"] == "演示员工107"
    assert captured["doc"]["project_initiation_report"] == "/private/files/initiation.pdf"
    assert captured["doc"]["project_completion_report"] == "/private/files/completion.pdf"
    assert captured["doc"]["capitalization_confirmation_file"] == "/private/files/capitalization.pdf"


def test_default_project_sync_preserves_optional_owner_and_document_fields(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    captured = {}

    frappe.db.exists = lambda *args, **kwargs: True
    frappe.db.get_single_value = lambda *args, **kwargs: "Rayher"
    frappe.get_all = lambda *args, **kwargs: ["Rayher"]

    class Doc:
        name = "RD01"

        def update(self, values):
            captured["values"] = values

        def save(self, **kwargs):
            captured["saved"] = kwargs

    frappe.get_doc = lambda *args, **kwargs: Doc()

    mod._save_project_doc("RD01", "ACONCA 6961")

    assert "project_owner_name" not in captured["values"]
    assert "project_owner" not in captured["values"]
    assert "project_initiation_report" not in captured["values"]
    assert "project_completion_report" not in captured["values"]
    assert "capitalization_confirmation_file" not in captured["values"]


def test_list_projects_requests_owner_and_document_fields(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    def get_all(doctype, filters=None, fields=None, **kwargs):
        captured["fields"] = fields
        return []

    frappe.get_all = get_all
    mod.list_projects()

    assert "project_owner" in captured["fields"]
    assert "project_owner_name" in captured["fields"]
    assert "project_initiation_report" in captured["fields"]
    assert "project_completion_report" in captured["fields"]
    assert "capitalization_confirmation_file" in captured["fields"]


def test_list_project_owners_returns_enabled_system_users(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    captured = {}

    def get_all(doctype, filters=None, fields=None, order_by=None, **kwargs):
        captured.update({"doctype": doctype, "filters": filters, "fields": fields, "order_by": order_by})
        return [{"name": "owner@example.com", "full_name": "Owner"}]

    frappe.get_all = get_all
    result = mod.list_project_owners()

    assert result == [{"name": "owner@example.com", "full_name": "Owner"}]
    assert captured["doctype"] == "User"
    assert captured["filters"] == {"enabled": 1, "user_type": "System User"}
