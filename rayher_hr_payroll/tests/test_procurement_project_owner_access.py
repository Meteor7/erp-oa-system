"""项目主管只读可见自己负责的项目里别人提的采购申请 / 购买申请（决定 2026-10-12）。"""
import importlib
import sys
import types

import pytest


@pytest.fixture
def access(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.session = types.SimpleNamespace(user="owner@example.com")
    frappe.db = types.SimpleNamespace(
        escape=lambda value: "'" + str(value).replace("'", "''") + "'",
        get_value=lambda *args, **kwargs: None,
    )
    frappe.get_roles = lambda user=None: ["Employee"]
    frappe.get_all = lambda *args, **kwargs: [{"name": "EMP-O", "employee_name": "Owner"}]
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.oa_access", None)
    module = importlib.import_module("rayher_hr_payroll.oa_access")
    monkeypatch.setattr(module, "visible_request_types", lambda values, user=None: list(values))
    monkeypatch.setattr(module, "_actor_names", lambda user, identity=None: {user})
    return module


def _request(module, request_type, **values):
    doc = {
        "request_type": request_type, "owner": "applicant@example.com", "employee": "EMP-A",
        "project_owner": "owner@example.com", "workflow_status": "已完成", "current_step_index": 0, "steps": [],
    }
    doc.update(values)
    return doc


def test_project_owner_can_read_both_application_types_of_their_project(access):
    for request_type in (access.REQUEST_PROCUREMENT, access.REQUEST_DIRECT_PURCHASE):
        for status in ("待审批", "已完成", "已驳回"):
            doc = _request(access, request_type, workflow_status=status)
            assert access.oa_request_has_permission(doc, "read", "owner@example.com") is None, (request_type, status)


def test_project_owner_is_read_only_and_does_not_see_drafts(access):
    doc = _request(access, access.REQUEST_PROCUREMENT, workflow_status="待审批")
    assert access.oa_request_has_permission(doc, "write", "owner@example.com") is False
    draft = _request(access, access.REQUEST_PROCUREMENT, workflow_status="草稿")
    assert access.oa_request_has_permission(draft, "read", "owner@example.com") is False


def test_other_users_and_other_projects_stay_hidden(access):
    doc = _request(access, access.REQUEST_PROCUREMENT)
    assert access.oa_request_has_permission(doc, "read", "stranger@example.com") is False
    other = _request(access, access.REQUEST_PROCUREMENT, project_owner="someone@example.com")
    assert access.oa_request_has_permission(other, "read", "owner@example.com") is False


def test_project_owner_scope_does_not_extend_to_payment_documents(access):
    doc = _request(access, access.REQUEST_PROCUREMENT_PAYMENT)
    assert access.oa_request_has_permission(doc, "read", "owner@example.com") is False


def test_list_query_carries_the_project_owner_clause_for_applications_only(access):
    query = access.oa_request_query("owner@example.com")
    assert "project_owner = 'owner@example.com'" in query
    assert "workflow_status != '草稿'" in query
