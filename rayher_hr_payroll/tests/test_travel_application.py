import importlib
import sys
import types

import pytest

from rayher_hr_payroll.oa_approval import (
    REQUEST_EXPENSE_PAYMENT,
    ApprovalRouteError,
    build_expense_payment_route,
    build_route,
    build_travel_route,
)
from rayher_hr_payroll.oa_document_types import (
    OPT_IN_REQUEST_TYPES,
    REQUEST_PAYMENT,
    REQUEST_REIMBURSEMENT,
    REQUEST_TRAVEL,
)
from rayher_hr_payroll.tests.test_oa_approval_routes import procurement_roles, role
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


def travel_roles():
    return {**procurement_roles(), "front_desk": role("front_desk", "前台办理", "desk@example.com", "演示员工30")}


def route(**kw):
    values = dict(department="研发软件部", supervisor="张主管", supervisor_user="zhang@example.com", supervisor_decision="approve",
                  applicant_user="wang@example.com", roles=travel_roles())
    values.update(kw)
    return build_travel_route(**values)


def shape(steps):
    return [(step["label"], step["mode"], step["approvers"]) for step in steps]


def test_trip_goes_direct_supervisor_then_vice_manager_then_front_desk():
    """决定 2026-10-13：直属上级 → 演示员工113经理（演示员工37）→ 前台办理（行政专员），前台是办理不是审批。"""
    assert shape(route()) == [
        ("直属部门主管：张主管", "approve", ["zhang@example.com"]),
        ("演示员工113经理：演示员工21", "approve", ["vice@example.com"]),
        ("前台办理：演示员工30", "handle", ["desk@example.com"]),
    ]
    # build_route 分到同一条路线
    assert build_route(REQUEST_TRAVEL, department="研发软件部", supervisor="张主管", supervisor_user="zhang@example.com",
                       supervisor_decision="approve", applicant_user="wang@example.com", roles=travel_roles()) == route()


def test_finance_department_goes_to_the_general_manager_instead():
    assert [step["label"] for step in route(department="财务部 - RAY")] == ["直属部门主管：张主管", "总经理：演示员工29", "前台办理：演示员工30"]


@pytest.mark.parametrize("name, user, department", [
    ("演示员工21", "vice@example.com", "研发软件部"),
    ("演示员工29", "general@example.com", "研发软件部"),
    ("演示员工21", "vice@example.com", "财务部 - RAY"),
])
def test_a_direct_supervisor_who_is_vice_or_general_manager_approves_alone(name, user, department):
    for decision in ("approve", "skip"):           # 组织关系里高管当直属上级时 decision 常是 skip，照样由他批这一步
        assert [step["label"] for step in route(supervisor=name, supervisor_user=user, supervisor_decision=decision, department=department)] == [
            f"直属部门主管：{name}", "前台办理：演示员工30"]


@pytest.mark.parametrize("applicant", ["vice@example.com", "general@example.com"])
def test_vice_and_general_manager_trips_need_no_approval_and_go_straight_to_the_front_desk(applicant):
    steps = route(applicant_user=applicant, supervisor="", supervisor_user="", supervisor_decision="skip")
    assert shape(steps) == [("前台办理：演示员工30", "handle", ["desk@example.com"])]


def test_the_front_desk_never_handles_her_own_trip():
    assert [step["label"] for step in route(applicant_user="desk@example.com")] == ["直属部门主管：张主管", "演示员工113经理：演示员工21"]


def test_a_missing_direct_supervisor_is_refused_with_a_readable_message():
    with pytest.raises(ApprovalRouteError, match="出差申请缺少直属上级"):
        route(supervisor="", supervisor_user="")
    with pytest.raises(ApprovalRouteError, match="没有关联可用账号"):
        route(supervisor_user="")


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
