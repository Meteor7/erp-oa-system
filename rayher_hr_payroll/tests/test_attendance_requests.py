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


LEAVE_DAY_RULE = "请假和调休按天填：全天 8 小时、上午 3 小时、下午 5 小时，也可以自定义小时（每次 0.5）。"


@pytest.mark.parametrize("hours", ["NaN", "Infinity", -1, -0.5, 8.01, 8.5, 9, 24, 0.001, 0.25, 0.75, 1.25, 2.3, True])
def test_invalid_daily_leave_hours_are_rejected(hours):
    with pytest.raises(ValueError):
        hr.normalize_days([{"work_date": "2026-09-01", "hours": hours}], "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)])


@pytest.mark.parametrize("hours", [3, 5, 8, 3.0, "5", "8.00"])
def test_leave_and_comp_time_presets_are_full_8_morning_3_or_afternoon_5(hours):
    # 公司规定：一天 8 小时，上午 3 小时，下午 5 小时（预设不变）。
    result = hr.normalize_days([{"work_date": "2026-09-01", "hours": hours}], "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)])
    assert result == [{"work_date": "2026-09-01", "hours": float(hours)}]
    assert hr.LEAVE_DAY_HOURS == (Decimal("3"), Decimal("5"), Decimal("8"))


@pytest.mark.parametrize("hours", [0.5, 1, 1.5, 2, 2.5, 4, 4.5, 6, 7, 7.5, "0.5", "6.50"])
def test_leave_and_comp_time_days_can_be_any_multiple_of_half_an_hour_up_to_a_full_day(hours):
    # 2026-10 起：自定义小时，每次 0.5，0.5–8 小时；旧的 4 小时半天现在也是合法的自定义小时。
    result = hr.normalize_days([{"work_date": "2026-09-01", "hours": hours}], "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)])
    assert result == [{"work_date": "2026-09-01", "hours": float(hours)}]


def test_the_refusal_message_names_the_presets_and_the_custom_step():
    with pytest.raises(ValueError) as caught:
        hr.normalize_days([{"work_date": "2026-09-01", "hours": 8.5}], "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)])
    assert str(caught.value) == LEAVE_DAY_RULE
    assert hr.LEAVE_DAY_MESSAGE == LEAVE_DAY_RULE
    assert [hr.valid_leave_hours(hours) for hours in (0, 0.5, 8, 8.5, 0.25, "NaN")] == [False, True, True, False, False, False]


def test_zero_hours_means_the_day_is_not_taken_and_is_dropped():
    days = [{"work_date": "2026-09-01", "hours": 3}, {"work_date": "2026-09-02", "hours": 0}]
    assert hr.normalize_days(days, "2026-09-01", "2026-09-02", work_dates=[date(2026, 9, 1), date(2026, 9, 2)]) == [
        {"work_date": "2026-09-01", "hours": 3.0}]
    with pytest.raises(ValueError, match="大于0"):
        hr.normalize_days([{"work_date": "2026-09-01", "hours": 0}], "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)])


def test_daily_details_validate_range_duplicates_workday_and_fraction():
    day = {"work_date": "2026-09-01", "hours": 3}
    assert hr.normalize_days([day], "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)]) == [day]
    for rows in [[day, day], [dict(day, work_date="2026-09-02")], []]:
        with pytest.raises(ValueError):
            hr.normalize_days(rows, "2026-09-01", "2026-09-01", work_dates=[date(2026, 9, 1)])
    assert hr.normalize_days(None, "2026-09-06", "2026-09-06", overtime=True)[0]["hours"] == 8
    with pytest.raises(ValueError):
        hr.normalize_days(None, "2026-09-06", "2026-09-06", work_dates=[])


@pytest.mark.parametrize("hours", [0.25, 1, 4, 5.5, 8, 24])
def test_overtime_stays_by_hours(hours):
    day = {"work_date": "2026-09-06", "hours": hours}
    assert hr.normalize_days([day], "2026-09-06", "2026-09-06", overtime=True) == [day]


@pytest.mark.parametrize("hours", [-1, 24.01, 0.001, "NaN", "Infinity"])
def test_overtime_hours_still_limited_to_24_with_two_decimals(hours):
    with pytest.raises(ValueError, match="加班"):
        hr.normalize_days([{"work_date": "2026-09-06", "hours": hours}], "2026-09-06", "2026-09-06", overtime=True)


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


# ---------------------------------------------------------------- 模块 4（2026-09-29）

def att_request(name, request_type, status, days, **extra):
    return {"name": name, "request_type": request_type, "workflow_status": status,
            "attendance_days": json.dumps([{"work_date": d, "hours": h} for d, h in days]), **extra}


@pytest.mark.parametrize("request_type", [hr.REQUEST_LEAVE, hr.REQUEST_OVERTIME, hr.REQUEST_COMP_TIME])
def test_only_approved_attendance_is_final(request_type):
    # 审查 R3-56-1：已批准的请假、加班、调休不能撤回；审批中的仍可以。
    assert hr.approved_attendance({"request_type": request_type, "workflow_status": "已完成"})
    assert hr.approved_attendance({"request_type": request_type, "workflow_status": "已通过"})
    for status in ("草稿", "待审批", "待办理"):
        assert not hr.approved_attendance({"request_type": request_type, "workflow_status": status})
    assert not hr.approved_attendance({"request_type": "购买申请", "workflow_status": "已完成"})


def test_a_day_cannot_be_booked_twice_by_leave_and_comp_time():
    others = [att_request("OA-1", hr.REQUEST_LEAVE, "待审批", [("2026-10-13", 8)])]
    message = hr.find_day_conflict(hr.REQUEST_LEAVE, [{"work_date": "2026-10-13", "hours": 8}], others)
    assert "10月13日已有请假申请 OA-1（审批中）" in message and "不能超过 8 小时" in message
    # 已有全天，再请上午也不行
    assert "10月13日已有请假申请 OA-1（审批中）" in hr.find_day_conflict(hr.REQUEST_LEAVE, [{"work_date": "2026-10-13", "hours": 3}], others)
    assert hr.find_day_conflict(hr.REQUEST_COMP_TIME, [{"work_date": "2026-10-13", "hours": 1}], others)
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, [{"work_date": "2026-10-14", "hours": 8}], others) is None


def test_morning_and_afternoon_are_separate_slots_across_requests():
    day = "2026-10-13"
    morning = [att_request("OA-1", hr.REQUEST_LEAVE, "待审批", [(day, 3)])]
    afternoon = [att_request("OA-2", hr.REQUEST_COMP_TIME, "已完成", [(day, 5)])]
    wanted = lambda hours: [{"work_date": day, "hours": hours}]  # noqa: E731
    # 上午 + 上午：拒绝；下午 + 下午：拒绝（请假和调休合在一起算）
    message = hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(3), morning)
    assert "10月13日已有请假申请 OA-1（审批中）" in message and "上午已被占用" in message
    assert "上午已被占用" in hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(3), morning)
    message = hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(5), afternoon)
    assert "10月13日已有调休申请 OA-2（已通过）" in message and "下午已被占用" in message
    # 上午 + 下午：可以，哪张先申请都行
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(5), morning) is None
    assert hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(3), afternoon) is None
    # 全天和这天任何已有的请假、调休冲突；已有全天时上午、下午也都不行
    for others in (morning, afternoon):
        assert "合计不能超过 8 小时" in hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(8), others)
    full = [att_request("OA-3", hr.REQUEST_LEAVE, "已完成", [(day, 8)])]
    assert "上午已被占用" in hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(3), full)
    assert "下午已被占用" in hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(5), full)
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(8), full)
    # 上午被请假占了、下午被调休占了：这天满了，再申请什么都不行
    both = morning + afternoon
    for hours in (3, 5, 8):
        assert hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(hours), both)
    # 不同的日子互不影响
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, [{"work_date": "2026-10-14", "hours": 3}], morning) is None


@pytest.mark.parametrize("status", ["草稿", "已拒绝", "已撤回"])
def test_a_dead_morning_request_frees_the_morning(status):
    others = [att_request("OA-1", hr.REQUEST_LEAVE, status, [("2026-10-13", 3)])]
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, [{"work_date": "2026-10-13", "hours": 3}], others) is None


def test_legacy_four_hour_half_days_only_take_capacity_and_do_not_claim_a_slot():
    # 历史上审批通过的半天按 4 小时存，不迁移；分不出上午下午，只按剩余容量判断：8 - 4 = 4 小时。
    day = "2026-10-13"
    legacy = [att_request("OA-OLD", hr.REQUEST_LEAVE, "已完成", [(day, 4)])]
    wanted = lambda hours: [{"work_date": day, "hours": hours}]  # noqa: E731
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(3), legacy) is None
    assert "合计不能超过 8 小时" in hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(5), legacy)
    assert "合计不能超过 8 小时" in hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(8), legacy)
    # 两个旧半天合起来就是满的
    legacy.append(att_request("OA-OLD2", hr.REQUEST_COMP_TIME, "已完成", [(day, 4)]))
    for hours in (3, 5, 8):
        assert hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(hours), legacy)
    # 旧半天 + 旧半天仍然是允许的（比如还没提交的老草稿按 4 小时提交时）
    assert hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(4), legacy[:1]) is None


def test_custom_hours_only_count_against_the_8_hour_day_and_never_claim_a_slot():
    # 自定义小时（不是恰好 3 / 5 / 8）只占当天的 8 小时容量，不占上午或下午。
    day = "2026-10-13"
    wanted = lambda hours: [{"work_date": day, "hours": hours}]  # noqa: E731
    custom = [att_request("OA-C", hr.REQUEST_LEAVE, "待审批", [(day, 2.5)])]
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(3), custom) is None      # 上午没被占，剩 5.5 小时放得下
    assert hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(5), custom) is None  # 下午也没被占
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(5.5), custom) is None    # 刚好填满 8 小时
    assert "合计不能超过 8 小时" in hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(6), custom)
    assert "合计不能超过 8 小时" in hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(8), custom)
    # 反过来：已有上午 3 小时，新申请自定义小时不受"上午被占"限制，只看容量
    morning = [att_request("OA-1", hr.REQUEST_LEAVE, "待审批", [(day, 3)])]
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(4), morning) is None
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(5), morning) is None     # 恰好 5 小时是下午，下午没被占
    assert "合计不能超过 8 小时" in hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(5.5), morning)
    # 已有下午 5 小时：新申请恰好 5 小时（下午）被拒；4.5 这样的自定义小时只受容量限制（5 + 4.5 > 8）
    afternoon = [att_request("OA-2", hr.REQUEST_LEAVE, "待审批", [(day, 5)])]
    assert "下午已被占用" in hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(5), afternoon)
    assert "合计不能超过 8 小时" in hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(4.5), afternoon)
    assert hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(3), afternoon) is None
    assert hr.find_day_conflict(hr.REQUEST_COMP_TIME, wanted(2.5), afternoon) is None
    # 两张自定义小时合起来满 8 小时：这天满了
    pair = custom + [att_request("OA-D", hr.REQUEST_COMP_TIME, "已完成", [(day, 5.5)])]
    for hours in (0.5, 3, 5):
        assert hr.find_day_conflict(hr.REQUEST_LEAVE, wanted(hours), pair)


def test_day_limits_for_custom_hours_leave_the_half_days_free():
    day = "2026-10-13"
    days = [date(2026, 10, 13)]
    limit = lambda *rows: hr.day_limits(hr.REQUEST_LEAVE, days, list(rows))[days[0]]  # noqa: E731
    assert limit(att_request("A", hr.REQUEST_LEAVE, "待审批", [(day, 2.5)])) == {
        "max_hours": 5.5, "am_taken": False, "pm_taken": False, "conflict": None}
    assert limit(att_request("A", hr.REQUEST_LEAVE, "待审批", [(day, 6)])) == {
        "max_hours": 2.0, "am_taken": False, "pm_taken": False, "conflict": None}
    # 自定义小时加上一个预设：上午 3 + 自定义 2 = 剩 3，上午被占、下午没被占
    both = limit(att_request("A", hr.REQUEST_LEAVE, "待审批", [(day, 3)]), att_request("B", hr.REQUEST_COMP_TIME, "已完成", [(day, 2)]))
    assert both == {"max_hours": 3.0, "am_taken": True, "pm_taken": False, "conflict": None}
    # 自定义小时把整天占满：和全天一样，上午下午都算被占
    full = limit(att_request("A", hr.REQUEST_LEAVE, "待审批", [(day, 4.5)]), att_request("B", hr.REQUEST_COMP_TIME, "已完成", [(day, 3.5)]))
    assert full["max_hours"] == 0 and full["am_taken"] and full["pm_taken"] and full["conflict"]["request"] == "B"


def test_default_hours_never_pick_a_preset_that_does_not_fit():
    days = [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)]
    others = [att_request("A", hr.REQUEST_LEAVE, "待审批", [("2026-10-13", 2.5)]),   # 剩 5.5：默认下午 5
              att_request("B", hr.REQUEST_LEAVE, "待审批", [("2026-10-14", 6)]),     # 剩 2：没有能放下的整半天，默认不请
              att_request("C", hr.REQUEST_LEAVE, "待审批", [("2026-10-15", 4.5)])]   # 剩 3.5：默认上午 3
    limits = hr.day_limits(hr.REQUEST_LEAVE, days, others)
    assert [hr.default_day_hours(hr.REQUEST_LEAVE, limits[d]) for d in days] == [8.0, 5.0, 0.0, 3.0]


def test_overtime_cannot_share_a_day_with_leave_or_comp_time_or_exceed_24_hours():
    leave_day = [att_request("OA-1", hr.REQUEST_LEAVE, "待审批", [("2026-10-13", 3)])]
    assert "不能再申请加班" in hr.find_day_conflict(hr.REQUEST_OVERTIME, [{"work_date": "2026-10-13", "hours": 2}], leave_day)
    overtime_day = [att_request("OA-3", hr.REQUEST_OVERTIME, "已完成", [("2026-10-17", 20)])]
    assert "不能再申请请假" in hr.find_day_conflict(hr.REQUEST_LEAVE, [{"work_date": "2026-10-17", "hours": 5}], overtime_day)
    assert "不能再申请调休" in hr.find_day_conflict(hr.REQUEST_COMP_TIME, [{"work_date": "2026-10-17", "hours": 3}], overtime_day)
    assert "不能超过 24 小时" in hr.find_day_conflict(hr.REQUEST_OVERTIME, [{"work_date": "2026-10-17", "hours": 5}], overtime_day)
    assert hr.find_day_conflict(hr.REQUEST_OVERTIME, [{"work_date": "2026-10-17", "hours": 4}], overtime_day) is None


@pytest.mark.parametrize("status", ["草稿", "已拒绝", "已撤回"])
def test_drafts_and_dead_requests_do_not_block_days(status):
    others = [att_request("OA-1", hr.REQUEST_LEAVE, status, [("2026-10-13", 8)])]
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, [{"work_date": "2026-10-13", "hours": 8}], others) is None


def test_legacy_date_only_requests_book_their_weekdays():
    legacy = {"name": "OA-OLD", "request_type": hr.REQUEST_LEAVE, "workflow_status": "已完成",
              "from_date": "2026-10-09", "to_date": "2026-10-12", "attendance_days": ""}
    assert [d.isoformat() for d, _ in hr.expand_days(legacy)] == ["2026-10-09", "2026-10-12"]
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, [{"work_date": "2026-10-10", "hours": 8}], [legacy]) is None
    assert hr.find_day_conflict(hr.REQUEST_LEAVE, [{"work_date": "2026-10-12", "hours": 1}], [legacy])


def test_window_hours_splits_a_cross_month_request_by_day():
    row = att_request("OA-1", hr.REQUEST_LEAVE, "已完成", [("2026-09-30", 8), ("2026-10-01", 4), ("2026-10-02", 8)])
    assert hr.window_hours(row, date(2026, 9, 1), date(2026, 9, 30)) == Decimal("8")
    assert hr.window_hours(row, date(2026, 10, 1), date(2026, 10, 31)) == Decimal("12")
    assert hr.window_hours(row, date(2026, 11, 1), date(2026, 11, 30)) == Decimal("0")


def test_day_limits_tell_the_form_how_many_hours_are_left():
    others = [att_request("OA-1", hr.REQUEST_LEAVE, "待审批", [("2026-10-13", 3)]),
              att_request("OA-2", hr.REQUEST_OVERTIME, "已完成", [("2026-10-17", 6)])]
    days = [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 17)]
    leave = hr.day_limits(hr.REQUEST_LEAVE, days, others)
    assert leave[days[0]] == {"max_hours": 8.0, "am_taken": False, "pm_taken": False, "conflict": None}
    assert leave[days[1]] == {"max_hours": 5.0, "am_taken": True, "pm_taken": False, "conflict": None}
    assert leave[days[2]]["max_hours"] == 0 and leave[days[2]]["conflict"]["request"] == "OA-2"
    assert leave[days[2]]["am_taken"] and leave[days[2]]["pm_taken"]
    overtime = hr.day_limits(hr.REQUEST_OVERTIME, days, others)
    assert overtime[days[1]]["max_hours"] == 0 and overtime[days[1]]["conflict"]["request"] == "OA-1"
    assert overtime[days[2]] == {"max_hours": 18.0, "am_taken": False, "pm_taken": False, "conflict": None}
    assert overtime[days[0]] == {"max_hours": 24.0, "am_taken": False, "pm_taken": False, "conflict": None}


def test_day_limits_flag_the_taken_half_of_the_day():
    day = "2026-10-13"
    days = [date(2026, 10, 13)]
    limit = lambda *rows: hr.day_limits(hr.REQUEST_COMP_TIME, days, list(rows))[days[0]]  # noqa: E731
    assert limit(att_request("A", hr.REQUEST_LEAVE, "待审批", [(day, 3)])) == {
        "max_hours": 5.0, "am_taken": True, "pm_taken": False, "conflict": None}
    assert limit(att_request("A", hr.REQUEST_COMP_TIME, "已完成", [(day, 5)])) == {
        "max_hours": 3.0, "am_taken": False, "pm_taken": True, "conflict": None}
    # 上午、下午各一张：这天满了，说明是哪张占的
    both = limit(att_request("A", hr.REQUEST_LEAVE, "待审批", [(day, 3)]), att_request("B", hr.REQUEST_COMP_TIME, "已完成", [(day, 5)]))
    assert both["max_hours"] == 0 and both["am_taken"] and both["pm_taken"] and both["conflict"]["request"] == "B"
    full = limit(att_request("A", hr.REQUEST_LEAVE, "已完成", [(day, 8)]))
    assert full["max_hours"] == 0 and full["am_taken"] and full["pm_taken"] and "请假申请 A（已通过）" in full["conflict"]["text"]
    # 历史上的 4 小时：还剩 4 小时，上午下午都不算被占（表单只让再加 3 小时的上午）
    assert limit(att_request("OLD", hr.REQUEST_LEAVE, "已完成", [(day, 4)])) == {
        "max_hours": 4.0, "am_taken": False, "pm_taken": False, "conflict": None}
    # 两个旧半天加起来 8 小时，满了
    old_pair = limit(att_request("O1", hr.REQUEST_LEAVE, "已完成", [(day, 4)]), att_request("O2", hr.REQUEST_COMP_TIME, "已完成", [(day, 4)]))
    assert old_pair["max_hours"] == 0 and old_pair["am_taken"] and old_pair["pm_taken"]
    # 没有生效的申请（草稿、已驳回、已撤回）不占位
    assert limit(att_request("D", hr.REQUEST_LEAVE, "草稿", [(day, 8)]))["max_hours"] == 8.0
    # 加班那天不能请假：上午下午都灰掉
    blocked = limit(att_request("OT", hr.REQUEST_OVERTIME, "已完成", [(day, 2)]))
    assert blocked["max_hours"] == 0 and blocked["am_taken"] and blocked["pm_taken"] and blocked["conflict"]["request"] == "OT"


def test_default_hours_for_the_form_pick_what_still_fits():
    day = "2026-10-13"
    days = [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)]
    others = [att_request("A", hr.REQUEST_LEAVE, "待审批", [("2026-10-13", 3)]),
              att_request("B", hr.REQUEST_LEAVE, "待审批", [("2026-10-14", 5)]),
              att_request("C", hr.REQUEST_LEAVE, "已完成", [("2026-10-15", 4)]),
              att_request("D", hr.REQUEST_LEAVE, "已完成", [("2026-10-16", 8)])]
    limits = hr.day_limits(hr.REQUEST_LEAVE, days, others)
    assert [hr.default_day_hours(hr.REQUEST_LEAVE, limits[d]) for d in days] == [8.0, 5.0, 3.0, 3.0, 0.0]
    overtime = hr.day_limits(hr.REQUEST_OVERTIME, days, others)
    assert [hr.default_day_hours(hr.REQUEST_OVERTIME, overtime[d]) for d in days[:1]] == [8.0]
    ot_row = [att_request("OT", hr.REQUEST_OVERTIME, "已完成", [(day, 20)])]
    assert hr.default_day_hours(hr.REQUEST_OVERTIME, hr.day_limits(hr.REQUEST_OVERTIME, [date(2026, 10, 13)], ot_row)[date(2026, 10, 13)]) == 4.0


def test_leave_hours_by_date_uses_stored_hours_for_new_and_legacy_days():
    # 上午 3 + 下午 5 = 8（一天的上限）；旧的 4 小时半天照存的小时数扣，不改成 3 或 5。
    morning = leave(attendance_days=[{"work_date": "2026-09-01", "hours": 3}])
    afternoon = leave(attendance_days=[{"work_date": "2026-09-01", "hours": 5}])
    legacy = leave(attendance_days=[{"work_date": "2026-09-01", "hours": 4}])
    assert hr.leave_hours_by_date([morning], [date(2026, 9, 1)]) == {date(2026, 9, 1): Decimal("3")}
    assert hr.leave_hours_by_date([afternoon], [date(2026, 9, 1)]) == {date(2026, 9, 1): Decimal("5")}
    assert hr.leave_hours_by_date([morning, afternoon], [date(2026, 9, 1)]) == {date(2026, 9, 1): Decimal("8")}
    assert hr.leave_hours_by_date([legacy], [date(2026, 9, 1)]) == {date(2026, 9, 1): Decimal("4")}
