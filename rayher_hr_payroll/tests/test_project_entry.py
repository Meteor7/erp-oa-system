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

    assert captured["roles"] == mod.RD_PROJECT_ACCESS_ROLES
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
    # 报告附件要是本人上传、尚未挂到别处的私有文件（2026-09-29）。
    frappe.get_all = lambda doctype, *args, **kwargs: (
        [{"owner": "Administrator", "attached_to_doctype": None, "attached_to_name": None}] if doctype == "File" else ["Rayher"]
    )

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


def test_list_project_owners_returns_active_employee_accounts(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))

    def get_all(doctype, filters=None, fields=None, order_by=None, **kwargs):
        captured.update({"doctype": doctype, "filters": filters, "fields": fields, "order_by": order_by})
        return [{"user_id": "owner@example.com", "employee_name": "Owner"}]

    frappe.get_all = get_all
    result = mod.list_project_owners()

    assert result == [{"name": "owner@example.com", "full_name": "Owner"}]
    assert captured["roles"] == mod.RD_PROJECT_ADMIN_ROLES
    assert captured["doctype"] == "Employee"
    assert captured["filters"] == {"status": "Active", "user_id": ["!=", ""]}


def test_project_owner_list_is_scoped_to_session_user(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner"]
    frappe.session.user = "owner@example.com"
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))

    def get_all(doctype, filters=None, **kwargs):
        captured.update({"doctype": doctype, "filters": filters})
        return []

    frappe.get_all = get_all
    assert mod.list_projects() == []
    assert captured["roles"] == mod.RD_PROJECT_ACCESS_ROLES
    assert captured["filters"]["project_owner"] == "owner@example.com"


def test_all_project_access_role_removes_owner_filter(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner", "All Project Access"]
    frappe.session.user = "portfolio@example.com"
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))

    def get_all(doctype, filters=None, **kwargs):
        captured.update({"doctype": doctype, "filters": filters})
        return []

    frappe.get_all = get_all
    assert mod.list_projects() == []
    assert "project_owner" not in captured["filters"]


def test_project_owner_cannot_create_project(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner"]
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    with pytest.raises(RuleError):
        mod.save_project(project_code="RD20", project_name="NEW", name=None)


def test_project_owner_cannot_reassign_project(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner"]
    frappe.session.user = "owner@example.com"
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.exists = lambda doctype, name_or_filters=None: doctype == "Project"

    def get_value(doctype, name, fields, as_dict=False):
        assert doctype == "Project"
        return {
            "project_owner": "owner@example.com",
            "project_owner_name": "Owner",
            "status": "Open",
        }

    frappe.db.get_value = get_value
    with pytest.raises(RuleError):
        mod.save_project(
            project_code="RD01",
            project_name="PROJECT",
            name="RD01",
            project_owner="other@example.com",
        )


def test_all_project_access_can_edit_other_project_without_reassigning(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner", "All Project Access"]
    frappe.session.user = "portfolio@example.com"
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.exists = lambda doctype, name_or_filters=None: doctype == "Project" and isinstance(name_or_filters, str)
    frappe.db.get_value = lambda *args, **kwargs: {
        "project_owner": "owner@example.com",
        "project_owner_name": "Owner",
        "status": "Open",
    }
    frappe.db.commit = lambda: None
    captured = {}
    monkeypatch.setattr(
        mod,
        "_save_project_doc",
        lambda *args, **kwargs: captured.setdefault("call", (args, kwargs)) and "RD01",
    )

    result = mod.save_project(
        project_code="RD01",
        project_name="UPDATED",
        name="RD01",
        project_owner="owner@example.com",
    )

    assert result == {"name": "RD01"}
    assert captured["call"][1]["project_owner"] == "owner@example.com"
    assert captured["call"][1]["project_owner_name"] == "Owner"


def test_project_owner_cannot_cancel_project(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    frappe.db.commit = lambda: None

    class Doc:
        def update(self, values):
            pass
        def save(self, **kwargs):
            pass

    frappe.get_doc = lambda *args, **kwargs: Doc()
    mod.cancel_project("RD01")
    assert captured["roles"] == mod.RD_PROJECT_ADMIN_ROLES


def test_employee_without_project_role_is_denied(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee"]

    def guard(roles):
        if not set(roles) & set(frappe.get_roles()):
            raise RuleError("forbidden")

    monkeypatch.setattr(mod, "require_rd_access", guard)
    with pytest.raises(RuleError, match="forbidden"):
        mod.list_projects()


def test_project_owner_can_edit_own_project_and_owner_is_preserved(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner"]
    frappe.session.user = "owner@example.com"
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.exists = lambda doctype, name_or_filters=None: doctype == "Project" and isinstance(name_or_filters, str)
    frappe.db.get_value = lambda *args, **kwargs: {
        "project_owner": "owner@example.com",
        "project_owner_name": "Owner",
        "status": "Open",
    }
    frappe.db.commit = lambda: None
    captured = {}
    monkeypatch.setattr(
        mod,
        "_save_project_doc",
        lambda *args, **kwargs: captured.setdefault("kwargs", kwargs) and "RD01",
    )

    result = mod.save_project(
        project_code="RD01",
        project_name="UPDATED",
        name="RD01",
        project_owner="",
        project_owner_name="",
    )

    assert result == {"name": "RD01"}
    assert captured["kwargs"]["project_owner"] == "owner@example.com"
    assert captured["kwargs"]["project_owner_name"] == "Owner"


def test_backfill_links_unique_employee_accounts_and_skips_unmatched(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    changed = []
    granted = []

    frappe.db.has_column = lambda doctype, fieldname: True

    def exists(doctype, filters=None):
        if doctype == "User":
            return filters == "owner@example.com"
        if doctype == "Has Role":
            return False
        return False

    frappe.db.exists = exists
    frappe.db.set_value = lambda *args, **kwargs: changed.append((args, kwargs))

    def get_all(doctype, filters=None, fields=None, **kwargs):
        if doctype == "Project":
            return [
                {"name": "RD01", "project_owner": "", "project_owner_name": "Owner"},
                {"name": "RD10", "project_owner": "", "project_owner_name": "Missing"},
            ]
        if doctype == "Employee" and filters.get("employee_name") == "Owner":
            return [{"user_id": "owner@example.com"}]
        if doctype == "Employee":
            return []
        raise AssertionError(doctype)

    frappe.get_all = get_all
    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        add_roles=lambda role: granted.append((name, role))
    )

    result = mod.backfill_project_owner_accounts()

    assert result == {"linked": 1, "role_grants": 1, "unmatched": 1}
    assert changed[0][0][:4] == ("Project", "RD01", "project_owner", "owner@example.com")
    assert granted == [("owner@example.com", "Project Owner")]


def _install_report_fixture(mod, frappe, owner="owner@example.com"):
    frappe.local = SimpleNamespace(response=SimpleNamespace())

    def get_value(doctype, name_or_filters, fields=None, as_dict=False):
        if doctype == "Project":
            return {
                "name": "RD04",
                "project_owner": owner,
                "project_initiation_report": "/private/files/RD04-initiation.pdf",
                "project_completion_report": None,
                "capitalization_confirmation_file": None,
            }
        if doctype == "File":
            assert name_or_filters == {
                "attached_to_doctype": "Project",
                "attached_to_name": "RD04",
                "attached_to_field": "project_initiation_report",
                "file_url": "/private/files/RD04-initiation.pdf",
                "is_private": 1,
            }
            return "FILE-RD04-INIT"
        raise AssertionError(doctype)

    frappe.db.get_value = get_value
    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        file_name="RD04-initiation.pdf",
        get_content=lambda: b"%PDF-report",
    )


def test_download_project_report_rejects_unknown_field(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    with pytest.raises(RuleError, match="无效"):
        mod.download_project_report("RD04", "project_owner")


def test_download_project_report_rejects_unrelated_project_owner(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner"]
    frappe.session.user = "owner@example.com"
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    _install_report_fixture(mod, frappe, owner="other@example.com")

    with pytest.raises(RuleError, match="无权"):
        mod.download_project_report("RD04", "project_initiation_report")


def test_download_project_report_streams_own_private_file(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner"]
    frappe.session.user = "owner@example.com"
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    _install_report_fixture(mod, frappe)

    mod.download_project_report("RD04", "project_initiation_report")

    assert frappe.local.response.filename == "RD04-initiation.pdf"
    assert frappe.local.response.filecontent == b"%PDF-report"
    assert frappe.local.response.type == "download"


def test_all_project_access_can_download_another_owners_report(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner", "All Project Access"]
    frappe.session.user = "portfolio@example.com"
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    _install_report_fixture(mod, frappe, owner="owner@example.com")

    mod.download_project_report("RD04", "project_initiation_report")

    assert frappe.local.response.filecontent == b"%PDF-report"


def test_default_project_seed_preserves_existing_business_state(monkeypatch):
    mod, frappe = _load_project_entry(monkeypatch)
    monkeypatch.setattr(mod, "DEFAULT_RAYHER_PROJECTS", [
        {"project_code": "EXISTING", "project_name": "Existing"},
        {"project_code": "RENAMED", "project_name": "Renamed"},
        {"project_code": "NEW", "project_name": "New"},
    ])
    frappe.db.exists = lambda dt, key: key == "EXISTING" or key == {"rd_project_code": "RENAMED"}
    frappe.db.commit = lambda: None
    created = []
    monkeypatch.setattr(mod, "_save_project_doc", lambda **values: created.append(values["project_code"]))
    mod.ensure_default_projects()
    assert created == ["NEW"]


# ---------------------------------------------------------------- 模块 5（2026-09-29）

def _owner_env(monkeypatch, status="Open", files=None, codes=()):
    mod, frappe = _load_project_entry(monkeypatch)
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner"]
    frappe.session.user = "owner@example.com"
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    def exists(doctype, filters=None):
        if isinstance(filters, dict):
            return filters.get("rd_project_code") in codes
        return doctype == "Project" and filters == "RD01"

    frappe.db.exists = exists
    project = {"project_owner": "owner@example.com", "project_owner_name": "Owner", "status": status,
               "rd_stage": "资本化", "capitalization_start_date": "2026-01-01", "capitalization_end_date": "2026-12-31",
               "project_initiation_report": "/private/files/old.pdf"}
    frappe.db.get_value = lambda doctype, name, fields, as_dict=False: {key: project.get(key) for key in fields}
    frappe.get_all = lambda doctype, **kwargs: list(files or [])
    frappe.db.commit = lambda: None
    captured = {}
    monkeypatch.setattr(mod, "_save_project_doc", lambda *args, **kwargs: captured.setdefault("call", (args, kwargs)) and "RD01")
    return mod, captured


def test_report_attachment_must_be_the_users_own_private_upload(monkeypatch):
    # R3-48-1：原来能填任意私有文件地址，之后通过项目报告下载读出别人的文件。
    mod, _ = _owner_env(monkeypatch, files=[{"owner": "someone@example.com", "attached_to_doctype": "Employee", "attached_to_name": "E1"}])
    with pytest.raises(RuleError, match="不是您本人"):
        mod.save_project(project_code="RD01", project_name="P", name="RD01", project_initiation_report="/private/files/salary.xlsx")
    with pytest.raises(RuleError, match="私有文件"):
        mod.save_project(project_code="RD01", project_name="P", name="RD01", project_initiation_report="/files/x.pdf")
    mod, captured = _owner_env(monkeypatch, files=[{"owner": "owner@example.com", "attached_to_doctype": None, "attached_to_name": None}])
    mod.save_project(project_code="RD01", project_name="P", name="RD01", project_initiation_report="/private/files/mine.pdf")
    assert captured["call"][1]["project_initiation_report"] == "/private/files/mine.pdf"


def test_unchanged_report_attachment_is_not_rechecked(monkeypatch):
    mod, captured = _owner_env(monkeypatch, files=[])
    mod.save_project(project_code="RD01", project_name="P", name="RD01", project_initiation_report="/private/files/old.pdf")
    assert captured["call"]


def test_project_codes_are_unique_and_new_projects_do_not_overwrite(monkeypatch):
    # R3-48-4：编号不唯一，两个同编号项目会让工时填报报"匹配到多个项目"；新增时同名项目被直接覆盖。
    mod, _ = _owner_env(monkeypatch, codes=("RD02",))
    with pytest.raises(RuleError, match="编号已被其他项目使用"):
        mod.save_project(project_code="RD02", project_name="P", name="RD01")
    mod, frappe = _load_project_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.exists = lambda doctype, filters=None: isinstance(filters, str)
    frappe.db.get_value = lambda *args, **kwargs: {}
    frappe.get_all = lambda *args, **kwargs: []
    with pytest.raises(RuleError, match="不能新增"):
        mod.save_project(project_code="RD01", project_name="P")


def test_owner_cannot_change_stage_or_dates_or_reopen_a_cancelled_project(monkeypatch):
    mod, captured = _owner_env(monkeypatch)
    mod.save_project(project_code="RD01", project_name="P", name="RD01", rd_stage="费用化", start_date="2027-01-01", end_date="2027-02-01")
    kwargs = captured["call"][1]
    assert kwargs["rd_stage"] == "资本化"
    assert captured["call"][0][2:4] == ("2026-01-01", "2026-12-31")
    mod, _ = _owner_env(monkeypatch, status="Cancelled")
    with pytest.raises(RuleError, match="重新启用"):
        mod.save_project(project_code="RD01", project_name="P", name="RD01", status="Open")
