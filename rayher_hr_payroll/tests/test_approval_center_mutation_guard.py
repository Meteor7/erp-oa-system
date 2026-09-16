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


def test_procurement_route_advances_only_inside_authorized_context(guard):
    module, frappe = guard
    doc = Doc({"request_type": module.REQUEST_PROCUREMENT, "workflow_status": "待审批", "current_step_index": 1})
    with pytest.raises(frappe.PermissionError, match="服务端字段|审批服务"):
        module.validate_request_mutation(doc)
    with module.authorized_oa_action():
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


@pytest.mark.parametrize(
    ("field", "before_value", "after_value"),
    [
        ("supplier", "供应商A", "供应商B"),
        ("payment_stage", "预付款", "尾款"),
        ("expected_delivery_date", "2026-09-01", "2026-10-01"),
        ("project", "PROJ-A", "PROJ-B"),
        ("business_lines", [{"item_name": "A"}], [{"item_name": "B"}]),
    ],
)
def test_active_request_rejects_business_content_changes(guard, field, before_value, after_value):
    module, frappe = guard
    before = Doc({
        "request_type": module.REQUEST_PROCUREMENT_PAYMENT,
        "workflow_status": "待审批",
        field: before_value,
    })
    changed = Doc(dict(before, **{field: after_value}), before=before)

    with pytest.raises(frappe.PermissionError, match="审批中业务字段"):
        module.validate_request_mutation(changed)


def test_draft_business_content_remains_editable(guard):
    module, _frappe = guard
    before = Doc({
        "request_type": module.REQUEST_PROCUREMENT_PAYMENT,
        "workflow_status": "草稿",
        "supplier": "供应商A",
    })
    changed = Doc(dict(before, supplier="供应商B"), before=before)

    module.validate_request_mutation(changed)


@pytest.mark.parametrize("field,value", [("attendance_days", '[{"work_date":"2026-09-01","hours":24}]'), ("duration_hours", 999)])
def test_client_cannot_forge_attendance_credit(guard, field, value):
    module, frappe = guard
    before = Doc({"request_type": "加班申请", "employee": "EMP-A", "workflow_status": "草稿"})
    changed = Doc(dict(before, **{field: value}), before=before)
    with pytest.raises(frappe.PermissionError):
        module.validate_request_mutation(changed)


@pytest.mark.parametrize("field,value", [("from_date", "2026-09-02"), ("to_date", "2026-09-30"), ("leave_type", "事假")])
def test_active_leave_dates_and_type_cannot_be_changed_directly(guard, field, value):
    module, frappe = guard
    before = Doc({"request_type": "请假申请", "workflow_status": "已完成"})
    with pytest.raises(frappe.PermissionError):
        module.validate_request_mutation(Doc(dict(before, **{field: value}), before=before))
