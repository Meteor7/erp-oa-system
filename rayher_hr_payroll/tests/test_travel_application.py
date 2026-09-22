import importlib
import sys
import types

import pytest

from rayher_hr_payroll.oa_approval import (
    REQUEST_EXPENSE_PAYMENT,
    build_direct_purchase_route,
    build_expense_payment_route,
    build_route,
)
from rayher_hr_payroll.oa_document_types import (
    OPT_IN_REQUEST_TYPES,
    REQUEST_PAYMENT,
    REQUEST_REIMBURSEMENT,
    REQUEST_TRAVEL,
)
from rayher_hr_payroll.tests.test_oa_approval_routes import procurement_roles
from rayher_hr_payroll.travel_requests import TravelRequestError, normalize_travel


def travel(**overrides):
    payload = {
        "subject": "北京展会参展",
        "travel_destination": "北京",
        "travel_start_date": "2026-10-21",
        "travel_end_date": "2026-10-23",
        "reason": "参加展会并拜访客户",
        "project": "",
    }
    payload.update(overrides)
    return payload


def test_travel_days_are_inclusive_and_project_is_optional():
    values = normalize_travel(travel())
    assert values["travel_days"] == 3
    assert values["project"] is None
    assert normalize_travel(travel(travel_end_date="2026-10-21"))["travel_days"] == 1


@pytest.mark.parametrize("overrides, message", [
    ({"travel_end_date": "2026-10-20"}, "返回日期不能早于出发日期"),
    ({"travel_destination": " "}, "请填写出差地点"),
    ({"reason": ""}, "请填写出差事由"),
    ({"subject": ""}, "请填写主题"),
    ({"travel_start_date": "明天"}, "出发日期格式无效"),
    ({"travel_end_date": "2027-12-31"}, "出差天数不能超过"),
])
def test_invalid_travel_is_rejected_with_a_readable_message(overrides, message):
    with pytest.raises(TravelRequestError, match=message):
        normalize_travel(travel(**overrides))


ROUTE_KW = dict(
    supervisor="张主管",
    supervisor_user="zhang@example.com",
    applicant_user="wang@example.com",
    upper_supervisor="",
    upper_supervisor_user="",
)


def test_travel_route_matches_direct_purchase_other_method():
    roles = procurement_roles()
    steps = build_route(REQUEST_TRAVEL, roles=roles, **ROUTE_KW)
    assert steps == build_direct_purchase_route(purchase_method="其他购买", roles=roles, **ROUTE_KW)
    assert [step["approvers"] for step in steps] == [["zhang@example.com"], ["vice@example.com"]]


@pytest.mark.parametrize("request_type", [REQUEST_REIMBURSEMENT, REQUEST_PAYMENT])
def test_claim_and_payment_routes_match_existing_expense_route(request_type):
    kw = dict(department="研发部", supervisor="张主管", supervisor_user="zhang@example.com", asset_category="其他", roles=procurement_roles())
    assert build_route(request_type, **kw) == build_route(REQUEST_EXPENSE_PAYMENT, **kw) == build_expense_payment_route(**kw)


@pytest.fixture
def gate(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.conf = {}
    frappe.session = types.SimpleNamespace(user="employee@example.com")
    frappe.db = types.SimpleNamespace(escape=lambda value: "'" + str(value) + "'")
    frappe.PermissionError = type("PermissionError", (Exception,), {})
    frappe.throw = lambda message, exc=None: (_ for _ in ()).throw((exc or RuntimeError)(message))
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.oa_feature_gate", None)
    return importlib.import_module("rayher_hr_payroll.oa_feature_gate"), frappe


def test_new_request_types_are_closed_until_enabled(gate):
    module, frappe = gate
    for request_type in OPT_IN_REQUEST_TYPES:
        assert module.can_access_request_type(request_type, "employee@example.com") is False
        assert module.can_access_request_type(request_type, "Administrator") is True
    frappe.conf.update(travel_application_enabled=1)
    assert module.can_access_request_type(REQUEST_TRAVEL, "employee@example.com") is True
    assert module.can_access_request_type(REQUEST_REIMBURSEMENT, "employee@example.com") is False


def test_existing_request_types_keep_their_default_open_switches(gate):
    module, _frappe = gate
    for request_type in (REQUEST_EXPENSE_PAYMENT, module.REQUEST_LEAVE, module.REQUEST_DIRECT_PURCHASE,
                         module.REQUEST_PROCUREMENT, module.REQUEST_PROCUREMENT_PAYMENT):
        assert module.can_access_request_type(request_type, "employee@example.com") is True
