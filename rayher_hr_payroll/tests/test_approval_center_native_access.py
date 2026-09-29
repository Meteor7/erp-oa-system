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


def test_procurement_purchaser_can_read_assigned_source(access, monkeypatch):
    module, _frappe = access
    monkeypatch.setattr(module, "visible_request_types", lambda values, user=None: list(values))
    doc = {
        "request_type": module.REQUEST_PROCUREMENT,
        "owner": "bob@example.com",
        "employee": "EMP-B",
        "purchaser_user": "alice@example.com",
        "workflow_status": "已完成",
        "steps": [],
    }
    assert module.oa_request_has_permission(doc, "read", "alice@example.com") is True
    assert module.oa_request_has_permission(doc, "write", "alice@example.com") is False
    query = module.oa_request_query("alice@example.com")
    assert "purchaser_user = 'alice@example.com'" in query


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


def test_hr_manager_does_not_get_unrestricted_procurement_read_scope(access, monkeypatch):
    module, frappe = access
    monkeypatch.setattr(module, "visible_request_types", lambda values, user=None: list(values))
    frappe.session.user = "hr@example.com"
    frappe.get_roles = lambda user=None: ["HR Manager"]
    query = module.oa_request_query("hr@example.com")
    assert query != "1=1"
    assert "owner = 'hr@example.com'" in query
    unrelated = {
        "request_type": module.REQUEST_PROCUREMENT,
        "owner": "bob@example.com",
        "employee": "EMP-B",
        "purchaser_user": "buyer@example.com",
        "workflow_status": "已完成",
        "steps": [],
    }
    assert module.oa_request_has_permission(unrelated, "read", "hr@example.com") is False


def test_hr_manager_can_read_related_procurement_request(access, monkeypatch):
    module, frappe = access
    monkeypatch.setattr(module, "visible_request_types", lambda values, user=None: list(values))
    frappe.session.user = "hr@example.com"
    frappe.get_roles = lambda user=None: ["HR Manager"]
    frappe.get_all = lambda *args, **kwargs: [{"name": "EMP-HR", "employee_name": "HR"}]
    own = {
        "request_type": module.REQUEST_PROCUREMENT,
        "owner": "hr@example.com",
        "employee": "EMP-HR",
        "purchaser_user": "buyer@example.com",
        "workflow_status": "已完成",
        "steps": [],
    }
    assert module.oa_request_has_permission(own, "read", "hr@example.com") is None



def test_hr_manager_does_not_get_unrestricted_expense_or_payment_read_scope(access, monkeypatch):
    module, frappe = access
    monkeypatch.setattr(module, "visible_request_types", lambda values, user=None: list(values))
    frappe.session.user = "hr@example.com"
    frappe.get_roles = lambda user=None: ["HR Manager"]
    unrelated = {
        "request_type": module.REQUEST_EXPENSE_PAYMENT,
        "owner": "bob@example.com",
        "employee": "EMP-B",
        "workflow_status": "已完成",
        "steps": [],
    }
    assert module.oa_request_has_permission(unrelated, "read", "hr@example.com") is False



def test_finance_can_read_payment_requests_globally_but_not_procurement_demands(access, monkeypatch):
    module, frappe = access
    monkeypatch.setattr(module, "visible_request_types", lambda values, user=None: list(values))
    frappe.session.user = "finance@example.com"
    frappe.get_roles = lambda user=None: ["Accounts User"]
    demand = {
        "request_type": module.REQUEST_PROCUREMENT,
        "owner": "bob@example.com", "employee": "EMP-B", "purchaser_user": "buyer@example.com",
        "workflow_status": "已完成", "steps": [],
    }
    payment = {**demand, "request_type": module.REQUEST_PROCUREMENT_PAYMENT}
    assert module.oa_request_has_permission(demand, "read", "finance@example.com") is False
    assert module.oa_request_has_permission(payment, "read", "finance@example.com") is None


@pytest.mark.parametrize("role", ["Purchase User", "Purchase Manager", "Accounts User"])
def test_business_role_cannot_read_unrelated_leave(access, monkeypatch, role):
    module, frappe = access
    monkeypatch.setattr(module, "visible_request_types", lambda values, user=None: list(values))
    frappe.get_roles = lambda user=None: ["Employee", role]
    leave = {"request_type": module.REQUEST_LEAVE, "owner": "other@example.com", "employee": "EMP-B", "workflow_status": "待审批", "current_step_index": 1, "steps": []}
    assert module.oa_request_has_permission(leave, "read", "alice@example.com") is False
    assert "AND (1=1)" not in module.oa_request_query("alice@example.com")


def test_future_node_does_not_grant_read_access(access, monkeypatch):
    module, _ = access
    monkeypatch.setattr(module, "_actor_names", lambda *args: {"alice@example.com"})
    doc = {"request_type": module.REQUEST_LEAVE, "owner": "other@example.com", "employee": "EMP-B", "workflow_status": "待审批", "current_step_index": 1, "steps": [{"step_index": 2, "approvers": '["alice@example.com"]'}]}
    assert module.oa_request_has_permission(doc, "read", "alice@example.com") is False
    doc["current_step_index"] = 2
    assert module.oa_request_has_permission(doc, "read", "alice@example.com") is None
    doc["workflow_status"] = "已撤回"
    assert module.oa_request_has_permission(doc, "read", "alice@example.com") is False


def test_profile_name_cannot_inject_list_or_detail_approver(access):
    module, frappe = access
    victim = "victim@example.com"
    frappe.db.get_value = lambda *a, **k: victim
    frappe.get_all = lambda *a, **k: [{"name": "EMP-A", "employee_name": victim}]
    actors = module._actor_names("alice@example.com")
    assert actors == {"alice@example.com"}
    assert victim not in module.oa_request_query("alice@example.com")
    doc = {"request_type": module.REQUEST_EXPENSE_PAYMENT, "owner": "bob@example.com",
           "employee": "EMP-B", "workflow_status": "待审批", "current_step_index": 1,
           "steps": [{"step_index": 1, "approvers": '["victim@example.com"]'}]}
    assert module.oa_request_has_permission(doc, "read", "alice@example.com") is False


def test_finance_does_not_read_other_peoples_legacy_expense_drafts(access, monkeypatch):
    """修复（2026-09-24，审查第三轮 Codex-A）：费用付款申请草稿里有收款账户，财务只看已提交的。"""
    module, frappe = access
    monkeypatch.setattr(module, "visible_request_types", lambda values, user=None: list(values))
    frappe.get_roles = lambda user=None: ["Accounts User"]
    draft = {"request_type": module.REQUEST_EXPENSE_PAYMENT, "owner": "bob@example.com", "employee": "EMP-B",
             "workflow_status": "草稿", "steps": []}
    assert module.oa_request_has_permission(draft, "read", "finance@example.com") is False
    assert module.oa_request_has_permission({**draft, "workflow_status": "待审批"}, "read", "finance@example.com") is None
    procurement_draft = {**draft, "request_type": module.REQUEST_PROCUREMENT_PAYMENT}
    assert module.oa_request_has_permission(procurement_draft, "read", "finance@example.com") is None



def test_copy_recipients_and_past_approvers_can_read(access, monkeypatch):
    # 审查 R3-57（决定 D3）：抄送人、审批过的人只读可见；不相干的人仍然看不到。
    module, _frappe = access
    monkeypatch.setattr(module, "_actor_names", lambda user, identity=None: {user})
    doc = {
        "request_type": module.REQUEST_LEAVE, "owner": "bob@example.com", "employee": "EMP-B",
        "workflow_status": "已完成", "current_step_index": 0,
        "copied_to": '[{"label": "人事经理", "user": "hr@example.com"}]',
        "steps": [{"step_index": 1, "approvers": '["boss@example.com"]', "approved_by": '["boss@example.com"]', "action_by": "boss@example.com"}],
    }
    assert module.oa_request_has_permission(doc, "read", "hr@example.com") is None
    assert module.oa_request_has_permission(doc, "read", "boss@example.com") is None
    assert module.oa_request_has_permission(doc, "read", "stranger@example.com") is False
    assert module.oa_request_has_permission(doc, "write", "boss@example.com") is False
    query = module.oa_request_query("alice@example.com")
    assert "copied_to" in query and "step.approved_by" in query and "step.action_by" in query
