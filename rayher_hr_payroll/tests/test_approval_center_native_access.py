import importlib
import sys
import types

import pytest


@pytest.fixture
def access(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.session = types.SimpleNamespace(user="alice@example.com")
    frappe.db = types.SimpleNamespace(
        escape=lambda value: "'" + str(value).replace("'", "''") + "'",
        get_value=lambda *args, **kwargs: None,
    )
    frappe.get_roles = lambda user=None: ["Employee"]
    frappe.get_all = lambda *args, **kwargs: [
        {"name": "EMP-A", "employee_name": "Alice"}
    ]
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.oa_access", None)
    module = importlib.import_module("rayher_hr_payroll.oa_access")
    monkeypatch.setattr(
        module,
        "visible_request_types",
        lambda values, user=None: list(values) if user == "Administrator" else [module.REQUEST_LEAVE, module.REQUEST_EXPENSE_PAYMENT],
    )
    return module, frappe


def test_native_query_combines_type_gate_and_row_scope(access):
    module, _frappe = access
    query = module.oa_request_query("alice@example.com")
    assert "request_type in" in query
    assert "owner = 'alice@example.com'" in query
    assert "employee = 'EMP-A'" in query
    assert "tabOA Approval Step" in query
    assert "JSON_VALID" in query
    assert "department" not in query.lower()


def test_unknown_or_duplicate_employee_link_falls_back_to_owner(access):
    module, frappe = access
    frappe.get_all = lambda *args, **kwargs: [
        {"name": "EMP-A", "employee_name": "Alice"},
        {"name": "EMP-DUP", "employee_name": "Alice Duplicate"},
    ]
    query = module.oa_request_query("alice@example.com")
    assert "owner = 'alice@example.com'" in query
    assert "employee = 'EMP-A'" not in query
    assert "employee = 'EMP-DUP'" not in query


def test_closed_new_type_is_invisible_to_employee_but_visible_to_administrator(access):
    module, _frappe = access
    doc = {"request_type": module.REQUEST_PROCUREMENT, "owner": "alice@example.com", "workflow_status": "草稿"}
    assert module.oa_request_has_permission(doc, "read", "alice@example.com") is False
    assert module.oa_request_has_permission(doc, "write", "alice@example.com") is False
    assert module.oa_request_has_permission(doc, "read", "Administrator") is None


def test_owner_can_read_and_write_only_existing_draft(access):
    module, _frappe = access
    draft = {"request_type": module.REQUEST_LEAVE, "owner": "alice@example.com", "employee": "EMP-A", "workflow_status": "草稿", "steps": []}
    pending = dict(draft, workflow_status="待审批")
    assert module.oa_request_has_permission(draft, "read", "alice@example.com") is None
    assert module.oa_request_has_permission(draft, "write", "alice@example.com") is None
    assert module.oa_request_has_permission(pending, "write", "alice@example.com") is False


def test_current_approver_reads_but_cannot_write_directly(access, monkeypatch):
    module, _frappe = access
    monkeypatch.setattr(module, "_actor_names", lambda user, identity=None: {user})
    doc = {
        "request_type": module.REQUEST_LEAVE,
        "owner": "bob@example.com",
        "employee": "EMP-B",
        "workflow_status": "待审批",
        "current_step_index": 1,
        "steps": [{"step_index": 1, "approvers": '["alice@example.com"]'}],
    }
    assert module.oa_request_has_permission(doc, "read", "alice@example.com") is None
    assert module.oa_request_has_permission(doc, "write", "alice@example.com") is False


def test_finance_has_existing_read_scope_but_no_direct_write(access):
    module, frappe = access
    frappe.get_roles = lambda user=None: ["Accounts User"]
    other = {"request_type": module.REQUEST_EXPENSE_PAYMENT, "owner": "bob@example.com", "workflow_status": "待审批", "steps": []}
    assert module.oa_request_has_permission(other, "read", "finance@example.com") is None
    assert module.oa_request_has_permission(other, "write", "finance@example.com") is False



def test_owner_cannot_forge_another_employee_on_create_or_write(access):
    module, _frappe = access
    forged = {
        "request_type": module.REQUEST_LEAVE,
        "owner": "alice@example.com",
        "employee": "EMP-B",
        "workflow_status": "草稿",
        "steps": [],
    }
    assert module.oa_request_has_permission(forged, "create", "alice@example.com") is False
    assert module.oa_request_has_permission(forged, "write", "alice@example.com") is False


def test_ambiguous_employee_link_cannot_write_even_when_owner_matches(access):
    module, frappe = access
    frappe.get_all = lambda *args, **kwargs: [
        {"name": "EMP-A", "employee_name": "Alice"},
        {"name": "EMP-DUP", "employee_name": "Alice Duplicate"},
    ]
    doc = {
        "request_type": module.REQUEST_LEAVE,
        "owner": "alice@example.com",
        "employee": "EMP-A",
        "workflow_status": "草稿",
        "steps": [],
    }
    assert module.oa_request_has_permission(doc, "write", "alice@example.com") is False
