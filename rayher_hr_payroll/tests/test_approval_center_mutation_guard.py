import importlib
import sys
import types

import pytest


class Doc(dict):
    def __init__(self, values, before=None):
        super().__init__(values)
        self._before = before

    def get_doc_before_save(self):
        return self._before


@pytest.fixture
def guard(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.flags = types.SimpleNamespace()
    frappe.PermissionError = type("PermissionError", (Exception,), {})

    def throw(message, exc=None):
        raise (exc or RuntimeError)(message)

    frappe.throw = throw
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.oa_mutation_guard", None)
    return importlib.import_module("rayher_hr_payroll.oa_mutation_guard"), frappe


def test_client_cannot_change_server_owned_fields(guard):
    module, frappe = guard
    before = Doc({
        "request_type": module.REQUEST_LEAVE,
        "workflow_status": "草稿",
        "approved_amount": None,
        "current_step_index": 0,
        "steps": [],
    })
    changed = Doc(dict(before, approved_amount=1), before=before)
    with pytest.raises(frappe.PermissionError, match="服务端字段"):
        module.validate_request_mutation(changed)


def test_client_cannot_change_request_identity_or_amount(guard):
    module, frappe = guard
    before = Doc({
        "request_type": module.REQUEST_LEAVE,
        "employee": "EMP-A",
        "amount": 10,
        "workflow_status": "草稿",
    })
    for field, value in (("request_type", module.REQUEST_PROCUREMENT), ("employee", "EMP-B"), ("amount", 999), ("copied_to", "forged@example.com")):
        changed = Doc(dict(before, **{field: value}), before=before)
        with pytest.raises(frappe.PermissionError, match="服务端字段"):
            module.validate_request_mutation(changed)


def test_closed_route_cannot_advance_even_inside_authorized_context(guard):
    module, frappe = guard
    for status in ("待审批", ""):
        doc = Doc({"request_type": module.REQUEST_PROCUREMENT, "workflow_status": status})
        with module.authorized_oa_action():
            with pytest.raises(frappe.PermissionError, match="尚未启用"):
                module.validate_request_mutation(doc)


def test_authorized_existing_action_can_change_state_and_context_clears(guard):
    module, frappe = guard
    before = Doc({"request_type": module.REQUEST_LEAVE, "workflow_status": "草稿", "current_step_index": 0})
    changed = Doc({"request_type": module.REQUEST_LEAVE, "workflow_status": "待审批", "current_step_index": 1}, before=before)
    with module.authorized_oa_action():
        module.validate_request_mutation(changed)
        assert frappe.flags.oa_authorized_action is True
    assert not getattr(frappe.flags, "oa_authorized_action", False)
    with pytest.raises(frappe.PermissionError, match="服务端字段"):
        module.validate_request_mutation(changed)


def test_new_native_document_must_be_an_empty_draft(guard):
    module, frappe = guard
    module.validate_request_mutation(Doc({"request_type": module.REQUEST_LEAVE, "workflow_status": "草稿"}))
    with pytest.raises(frappe.PermissionError, match="服务端字段"):
        module.validate_request_mutation(Doc({"request_type": module.REQUEST_LEAVE, "workflow_status": "草稿", "amount": 1}))
