import importlib
import sys
import types

import pytest


@pytest.fixture
def gate(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.conf = {}
    frappe.session = types.SimpleNamespace(user="employee@example.com")
    frappe.db = types.SimpleNamespace(escape=lambda value: "'" + str(value).replace("'", "''") + "'")
    frappe.PermissionError = type("PermissionError", (Exception,), {})

    def throw(message, exc=None):
        raise (exc or RuntimeError)(message)

    frappe.throw = throw
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.oa_feature_gate", None)
    module = importlib.import_module("rayher_hr_payroll.oa_feature_gate")
    return module, frappe


def test_truthy_switch_allows_only_exact_administrator(gate):
    module, frappe = gate
    frappe.conf.update(leave_approval_admin_only=1, expense_reimbursement_admin_only="true")
    assert module.can_access_request_type(module.REQUEST_LEAVE, "Administrator") is True
    assert module.can_access_request_type(module.REQUEST_EXPENSE_PAYMENT, "Administrator") is True
    assert module.can_access_request_type(module.REQUEST_LEAVE, "admin@staff.example.invalid") is True
    assert module.can_access_request_type(module.REQUEST_EXPENSE_PAYMENT, "admin@staff.example.invalid") is True
    assert module.can_access_request_type(module.REQUEST_LEAVE, "manager@example.com") is False
    assert module.can_access_request_type(module.REQUEST_EXPENSE_PAYMENT, "finance@example.com") is False


def test_switches_are_independent_and_reversible(gate):
    module, frappe = gate
    frappe.conf.update(leave_approval_admin_only=1, expense_reimbursement_admin_only=0)
    assert module.visible_request_types(
        [module.REQUEST_LEAVE, module.REQUEST_EXPENSE_PAYMENT], "employee@example.com"
    ) == [module.REQUEST_EXPENSE_PAYMENT]
    assert module.boot_access_flags("employee@example.com") == {
        "leave_approval": False,
        "expense_reimbursement": True,
        "procurement_application": True,
        "direct_purchase_application": True,
        "procurement_payment": True,
    }


def test_denial_query_and_document_permissions(gate):
    module, frappe = gate
    frappe.conf.update(leave_approval_admin_only=1, expense_reimbursement_admin_only=1)
    query = module.oa_request_query("employee@example.com")
    assert query != "1=0"
    assert all(request_type in query for request_type in (
        module.REQUEST_PROCUREMENT, module.REQUEST_DIRECT_PURCHASE, module.REQUEST_PROCUREMENT_PAYMENT
    ))
    assert module.REQUEST_LEAVE not in query
    assert module.REQUEST_EXPENSE_PAYMENT not in query
    assert module.oa_request_has_permission(
        {"request_type": module.REQUEST_LEAVE}, user="employee@example.com"
    ) is False
    with pytest.raises(frappe.PermissionError):
        module.require_request_type_access(module.REQUEST_LEAVE, "employee@example.com")


def test_open_switch_defers_to_existing_permissions(gate):
    module, frappe = gate
    assert module.oa_request_query("employee@example.com") == ""
    assert module.oa_request_has_permission(
        {"request_type": module.REQUEST_LEAVE}, user="employee@example.com"
    ) is None
    with pytest.raises(ValueError):
        module.can_access_request_type("unknown", "employee@example.com")


def test_procurement_routes_are_open_without_opening_unknown_types(gate):
    module, _frappe = gate
    assert module.DRAFT_ONLY_REQUEST_TYPES == set()
    for request_type in (module.REQUEST_PROCUREMENT, module.REQUEST_DIRECT_PURCHASE, module.REQUEST_PROCUREMENT_PAYMENT):
        assert module.can_access_request_type(request_type, "employee@example.com") is True
        assert module.can_access_request_type(request_type, "manager@example.com") is True
    with pytest.raises(ValueError):
        module.can_access_request_type("unknown", "employee@example.com")
