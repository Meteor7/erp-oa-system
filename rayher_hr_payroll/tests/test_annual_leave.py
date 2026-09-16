from datetime import date
from types import SimpleNamespace
import sys

import pytest

from rayher_hr_payroll import annual_leave as annual
from rayher_hr_payroll import attendance_requests as hr


def request(name="A", hours=4, status="待审批", day="2026-09-16", **extra):
    return {"name": name, "employee": "EMP-1", "request_type": hr.REQUEST_LEAVE,
            "leave_type": "年假", "workflow_status": status,
            "attendance_days": [{"work_date": day, "hours": hours}], **extra}


@pytest.mark.parametrize("day,credit,next_date", [
    ("2026-07-14", 0, "2026-07-15"), ("2026-07-15", 40, "2027-07-15"),
    ("2027-07-14", 40, "2027-07-15"), ("2027-07-15", 80, "2028-07-15"),
    ("2029-08-01", 160, "2030-07-15"),
])
def test_exact_anniversary_and_unexpired_carry_forward(day, credit, next_date):
    balance = annual.summarize_annual("2025-07-15", [], day)
    assert balance["credit_hours"] == balance["available_hours"] == credit
    assert balance["next_grant_date"] == next_date
    assert balance["carry_forward"] is True


def test_leap_day_joining_and_missing_joining_date():
    assert annual.entitlement("2024-02-29", "2025-02-27")["credit_hours"] == 0
    assert annual.entitlement("2024-02-29", "2025-02-28")["credit_hours"] == 40
    assert annual.entitlement("2024-02-29", "2028-02-28")["credit_hours"] == 120
    assert annual.entitlement("2024-02-29", "2028-02-29")["credit_hours"] == 160
    for joining in [None, "", "2027-01-01"]:
        result = annual.entitlement(joining, "2026-09-16")
        assert result["credit_hours"] == 0 and not result["eligible"]
        assert result["eligibility_message"]


def test_reservations_usage_and_releases_are_derived_once_from_requests():
    rows = [request(hours=4), request("B", 8, "已完成"),
            request("C", 8, "草稿"), request("D", 8, "已撤回"),
            request("E", 8, leave_type="事假"), request("F", 8, request_type=hr.REQUEST_COMP_TIME)]
    result = annual.summarize_annual("2024-07-15", rows, "2026-09-16")
    assert (result["credit_hours"], result["reserved_hours"], result["used_hours"], result["available_hours"]) == (80, 4, 8, 68)
    rows[0]["workflow_status"] = "已完成"
    result = annual.summarize_annual("2024-07-15", rows, "2026-09-16")
    assert (result["reserved_hours"], result["used_hours"], result["available_hours"]) == (0, 12, 68)
    rows[0]["workflow_status"] = "已撤回"
    assert annual.summarize_annual("2024-07-15", rows, "2026-09-16")["available_hours"] == 72


def test_exhausted_balance_and_no_borrowing_future_grants():
    rows = [request(hours=40)]
    annual.validate_annual_capacity("2025-07-15", rows, "2026-09-16")
    with pytest.raises(ValueError, match="余额不足"):
        annual.validate_annual_capacity("2025-07-15", rows + [request("B", 4, day="2027-08-02")], "2026-09-16")
    with pytest.raises(ValueError, match="未满12个月"):
        annual.validate_annual_capacity("2026-01-01", [request(day="2027-01-04")], "2026-09-16")


def test_backdated_leave_cannot_spend_grants_before_anniversary():
    with pytest.raises(ValueError, match="尚未发放"):
        annual.validate_annual_capacity("2025-07-15", [request(day="2026-07-14")], "2026-09-16")
    annual.validate_annual_capacity("2025-07-15", [request(day="2026-07-15")], "2026-09-16")


def test_old_used_leave_reduces_carried_balance():
    result = annual.summarize_annual("2023-07-15", [request(hours=8,status="已完成",day="2024-08-01")], "2026-09-16")
    assert result["credit_hours"] == 120 and result["available_hours"] == 112


@pytest.mark.parametrize("leave_type", ["病假", "年假", "婚假", "产假", "陪产假", "丧假", "其他假", "", None, "调休"])
def test_only_personal_leave_reduces_monthly_cap(leave_type):
    row = request(status="已完成", leave_type=leave_type)
    assert hr.leave_hours_by_date([row], [date(2026, 9, 16)]) == {}
    row["leave_type"] = "事假"
    assert hr.leave_hours_by_date([row], [date(2026, 9, 16)])[date(2026, 9, 16)] == 4


def test_annual_balance_is_scoped_to_employee_with_current_read(monkeypatch):
    calls = []
    def sql(query, args, **kwargs):
        assert "FOR UPDATE" in query
        assert "WHERE employee=%s" in query and args[0] == "EMP-1"
        assert calls == ["employee-lock"]
        return [request("OTHER", 40)]
    def get_value(dt, emp, field, for_update=False):
        assert dt == "Employee" and emp == "EMP-1" and for_update
        calls.append("employee-lock")
        return "2025-07-15"
    def throw(message):
        raise ValueError(message)
    monkeypatch.setitem(sys.modules, "frappe", SimpleNamespace(db=SimpleNamespace(sql=sql, get_value=get_value),throw=throw))
    monkeypatch.setitem(sys.modules, "frappe.utils", SimpleNamespace(today=lambda: "2026-09-16"))
    with pytest.raises(ValueError,match="余额不足"):
        annual.validate_annual_request(SimpleNamespace(**request(hours=4)))


def test_approval_does_not_charge_same_reservation_again():
    before = request(hours=4)
    annual.validate_annual_request(request(hours=4, status="已完成"), before)
