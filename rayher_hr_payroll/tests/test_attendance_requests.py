import json
import sys
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import attendance_requests as hr
from rayher_hr_payroll.oa_approval import build_route


def leave(**extra):
    return {"request_type": hr.REQUEST_LEAVE, "workflow_status": "已完成", "leave_type": "事假",
            "from_date": "2026-08-31", "to_date": "2026-09-02", **extra}


def test_cross_month_hourly_leave_and_calendar_intersection():
    row = leave(attendance_days=json.dumps([
        {"work_date": "2026-08-31", "hours": 4},
        {"work_date": "2026-09-01", "hours": 2.5},
        {"work_date": "2026-09-02", "hours": 8},
    ]))
    assert hr.leave_hours_by_date([row], [date(2026, 8, 31)]) == {date(2026, 8, 31): Decimal("4")}
    assert hr.leave_hours_by_date([row], [date(2026, 9, 1)]) == {date(2026, 9, 1): Decimal("2.5")}


@pytest.mark.parametrize("status", ["草稿", "待审批", "已拒绝", "已撤回"])
def test_unapproved_or_withdrawn_leave_does_not_reduce_cap(status):
    assert hr.leave_hours_by_date([leave(workflow_status=status)], [date(2026, 9, 1)]) == {}


@pytest.mark.parametrize("request_type", [hr.REQUEST_OVERTIME, hr.REQUEST_COMP_TIME])
def test_overtime_and_comp_time_never_reduce_cap(request_type):
    assert hr.leave_hours_by_date([leave(request_type=request_type)], [date(2026, 9, 1)]) == {}


def test_legacy_leave_and_overlap_are_capped_at_workday():
    rows = [leave(), leave(attendance_days=[{"work_date": "2026-09-01", "hours": 4}])]
    assert hr.leave_hours_by_date(rows, [date(2026, 9, 1)]) == {date(2026, 9, 1): 8}
    assert hr.leave_hours_by_date([leave(leave_type="调休")], [date(2026, 9, 1)]) == {}


@pytest.mark.parametrize("hours", ["NaN", "Infinity", -1, 8.01, 0.001, True])
def test_invalid_daily_leave_hours_are_rejected(hours):
    with pytest.raises(ValueError):
        hr.normalize_days([{"work_date": "2026-09-01", "hours": hours}], "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)])


def test_daily_details_validate_range_duplicates_workday_and_fraction():
    day = {"work_date": "2026-09-01", "hours": 0.25}
    assert hr.normalize_days([day], "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)]) == [day]
    for rows in [[day, day], [dict(day, work_date="2026-09-02")], []]:
        with pytest.raises(ValueError):
            hr.normalize_days(rows, "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)])
    assert hr.normalize_days(None, "2026-09-06", "2026-09-06", overtime=True)[0]["hours"] == 8
    with pytest.raises(ValueError):
        hr.normalize_days(None, "2026-09-06", "2026-09-06", work_dates=[])


def test_overtime_credit_is_on_submission_and_comp_time_reserves_then_consumes():
    assert hr.balance_effect(hr.REQUEST_OVERTIME, "草稿", 8) == (0, 0, 0)
    assert hr.balance_effect(hr.REQUEST_OVERTIME, "待审批", 8) == (8, 0, 0)
    assert hr.balance_effect(hr.REQUEST_COMP_TIME, "待审批", 3.5) == (0, 3.5, 0)
    assert hr.balance_effect(hr.REQUEST_COMP_TIME, "已完成", 3.5) == (0, 0, 3.5)
    assert hr.balance_effect(hr.REQUEST_COMP_TIME, "草稿", 3.5) == (0, 0, 0)


@pytest.fixture
def ledger(monkeypatch):
    records, locks, warnings = [], [], []
    def sql(query, args, as_dict=False):
        assert "FOR UPDATE" in query
        assert locks and locks[-1] == ("Employee", args[0], True)
        return [r for r in records if r.employee == args[0]]
    def set_value(doctype, name, values):
        row = next(r for r in records if r.name == name)
        row.__dict__.update(values)
    class Record(SimpleNamespace):
        def insert(self, **kwargs):
            assert not any(r.source_request == self.source_request for r in records)
            self.name = str(len(records) + 1)
            records.append(self)
            return self
    def throw(message, *args):
        raise ValueError(message)
    frappe = SimpleNamespace(db=SimpleNamespace(
        get_value=lambda dt, name, field, for_update=False: locks.append((dt, name, for_update)),
        sql=sql, set_value=set_value), get_doc=lambda values: Record(**values),
        throw=throw, msgprint=lambda message, **kwargs: warnings.append(message))
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    return records, warnings


def request(name, kind, status, hours, employee="EMP-1"):
    return SimpleNamespace(name=name, employee=employee, request_type=kind, workflow_status=status, duration_hours=hours)


def test_balance_lifecycle_is_idempotent_and_employee_scoped(ledger):
    records, _ = ledger
    overtime = request("OT-1", hr.REQUEST_OVERTIME, "待审批", 8)
    hr.sync_balance(overtime)
    hr.sync_balance(overtime)
    comp = request("CT-1", hr.REQUEST_COMP_TIME, "待审批", 6)
    hr.sync_balance(comp)
    assert hr.summarize_balance(records)["available_hours"] == 2
    with pytest.raises(ValueError, match="余额不足"):
        hr.sync_balance(request("CT-2", hr.REQUEST_COMP_TIME, "待审批", 3))
    with pytest.raises(ValueError, match="余额不足"):
        hr.sync_balance(request("CT-3", hr.REQUEST_COMP_TIME, "待审批", 1, employee="EMP-2"))
    comp.workflow_status = "已完成"
    hr.sync_balance(comp)
    hr.sync_balance(comp)
    assert hr.summarize_balance(records) == dict(credit_hours=8, reserved_hours=0, used_hours=6, available_hours=2)
    comp.workflow_status = "草稿"
    hr.sync_balance(comp)
    assert hr.summarize_balance(records)["available_hours"] == 8
    hr.sync_balance(comp)
    assert len(records) == 2


def test_overtime_rejection_preserves_used_hours_and_blocks_further_comp_time(ledger):
    records, warnings = ledger
    overtime = request("OT-1", hr.REQUEST_OVERTIME, "待审批", 8)
    hr.sync_balance(overtime)
    hr.sync_balance(request("CT-1", hr.REQUEST_COMP_TIME, "已完成", 8))
    overtime.workflow_status = "草稿"
    hr.sync_balance(overtime)
    balance = hr.summarize_balance(records)
    assert balance["used_hours"] == 8 and balance["available_hours"] == -8
    assert warnings
    with pytest.raises(ValueError):
        hr.sync_balance(request("CT-2", hr.REQUEST_COMP_TIME, "待审批", 1))


@pytest.mark.parametrize("department", ["研发部", "财务部"])
def test_overtime_and_comp_time_use_exact_leave_approval_route(department):
    kwargs = dict(department=department, supervisor="主管", supervisor_user="manager@example.com", applicant_user="worker@example.com", roles={key: {"user": key+"@example.com", "employee_name": key, "role_label": key} for key in ["hr_manager", "vice_manager", "general_manager"]})
    expected = build_route(hr.REQUEST_LEAVE, **kwargs)
    assert build_route(hr.REQUEST_OVERTIME, **kwargs) == expected
    assert build_route(hr.REQUEST_COMP_TIME, **kwargs) == expected



def test_hr_mutations_lock_employee_before_request_action(monkeypatch):
    calls = []
    def get_value(doctype, key, fields, **kwargs):
        if doctype == "OA Approval Request":
            return {"request_type": hr.REQUEST_COMP_TIME, "employee": "EMP-1"}
        assert kwargs["for_update"] is True
        calls.append("employee-lock")
    monkeypatch.setitem(sys.modules, "frappe", SimpleNamespace(db=SimpleNamespace(get_value=get_value)))
    @hr.attendance_request_transaction
    def operation(name, action="approve"):
        calls.append("request-action")
        return name, action
    assert operation("REQ-1", action="reject") == ("REQ-1", "reject")
    assert calls == ["employee-lock", "request-action"]


def test_legacy_empty_string_details_use_work_calendar():
    assert hr.normalize_days("", "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)]) == [{"work_date": "2026-09-01", "hours": 8}]
