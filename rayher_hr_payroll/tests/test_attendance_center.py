"""请假 / 加班 / 调休页面的展示规则（模块 4，2026-09-29）。"""
import json
from datetime import date

from rayher_hr_payroll import attendance_center as center
from rayher_hr_payroll import attendance_requests as att


def row(name, request_type, status, days, leave_type="", **extra):
    return {"name": name, "request_type": request_type, "workflow_status": status, "leave_type": leave_type,
            "attendance_days": json.dumps([{"work_date": d, "hours": h} for d, h in days]), **extra}


def test_period_bounds_defaults_to_the_current_month_and_ignores_bad_input():
    today = date(2026, 9, 29)
    assert center.period_bounds("2026-10", today) == (2026, 10, date(2026, 10, 1), date(2026, 10, 31))
    assert center.period_bounds("", today)[:2] == (2026, 9)
    assert center.period_bounds("2026-13", today)[:2] == (2026, 9)
    assert center.period_bounds("abc", today)[:2] == (2026, 9)
    assert center.period_bounds("2028-02", today)[3] == date(2028, 2, 29)


def test_calendar_shows_each_day_of_each_request_and_marks_pending():
    rows = [
        row("OA-1", att.REQUEST_LEAVE, "已完成", [("2026-09-30", 8), ("2026-10-01", 4)], "事假"),
        row("OA-2", att.REQUEST_OVERTIME, "待审批", [("2026-10-03", 6)]),
        row("OA-3", att.REQUEST_COMP_TIME, "草稿", [("2026-10-05", 8)]),
        row("OA-4", att.REQUEST_LEAVE, "已拒绝", [("2026-10-06", 8)], "年假"),
    ]
    entries = center.calendar_entries(rows, date(2026, 10, 1), date(2026, 10, 31))
    assert [(e["date"], e["kind"], e["label"], e["hours"], e["pending"]) for e in entries] == [
        ("2026-10-01", "leave", "事假", 4, False),
        ("2026-10-03", "overtime", "加班", 6, True),
    ]


def test_month_totals_split_types_and_keep_pending_leave_apart_for_the_cap():
    rows = [
        row("OA-1", att.REQUEST_LEAVE, "已完成", [("2026-10-13", 8)], "事假"),
        row("OA-2", att.REQUEST_LEAVE, "待审批", [("2026-10-14", 8), ("2026-10-15", 4)], "事假"),
        row("OA-3", att.REQUEST_LEAVE, "待审批", [("2026-10-16", 8)], "年假"),
        row("OA-4", att.REQUEST_OVERTIME, "已完成", [("2026-10-17", 6.5)]),
        row("OA-5", att.REQUEST_COMP_TIME, "待审批", [("2026-10-19", 4)]),
        row("OA-6", att.REQUEST_LEAVE, "草稿", [("2026-10-20", 8)], "事假"),
    ]
    totals = center.month_totals(rows, date(2026, 10, 1), date(2026, 10, 31))
    assert totals["leave_hours"] == 28 and totals["leave_days"] == 3.5
    assert totals["leave_days_by_type"] == {"事假": 2.5, "年假": 1}
    assert totals["overtime_hours"] == 6.5 and totals["comp_hours"] == 4
    assert totals["pending_cap_hours"] == 12  # 事假审批中的 12 小时，通过后才扣当月上限


def test_hints_for_annual_leave_show_the_balance_before_and_after():
    annual = {"available_hours": 8}
    request = row("OA-1", att.REQUEST_LEAVE, "待审批", [("2026-10-20", 8), ("2026-10-21", 8), ("2026-10-22", 8), ("2026-10-23", 8)], "年假")
    hints = center.review_hints(request, annual=annual, teammates_off=1)
    assert hints[0] == {"tone": "ok", "text": "年假够：40h → 8h"}
    assert hints[-1] == {"tone": "warn", "text": "同期 1 人请假或调休"}
    short = center.review_hints(request, annual={"available_hours": -8})
    assert short[0] == {"tone": "warn", "text": "年假不够：还差 8h"}


def test_hints_for_personal_leave_show_the_count_and_the_cap_per_month():
    request = row("OA-1", att.REQUEST_LEAVE, "待审批", [("2026-09-30", 8), ("2026-10-01", 8)], "事假")
    hints = center.review_hints(request, year_leave_count=3)
    assert {"tone": "warn", "text": "今年第 3 次事假"} in hints
    assert {"tone": "info", "text": "通过后 9 月工时上限 −8h"} in hints
    assert {"tone": "info", "text": "通过后 10 月工时上限 −8h"} in hints
    assert hints[-1] == {"tone": "ok", "text": "同期部门无人请假"}
    assert center.review_hints(request, year_leave_count=1)[0] == {"tone": "info", "text": "今年第 1 次事假"}


def test_hints_for_comp_time_and_overtime():
    comp = row("OA-1", att.REQUEST_COMP_TIME, "待审批", [("2026-10-20", 8)])
    assert center.review_hints(comp, comp={"available_hours": 8})[0]["text"] == "调休余额 16h → 8h"
    assert center.review_hints(comp, comp={"available_hours": -4})[0] == {"tone": "warn", "text": "调休不够：还差 4h"}
    overtime = row("OA-2", att.REQUEST_OVERTIME, "待审批", [("2026-10-17", 6)])
    hints = center.review_hints(overtime)
    assert hints == [{"tone": "info", "text": "提交时已计入调休额度 +6h，驳回或撤回后冲回"}]
    sick = row("OA-3", att.REQUEST_LEAVE, "待审批", [("2026-10-20", 8)], "病假")
    assert center.review_hints(sick)[0]["text"] == "不扣年假和工时上限"


def test_impact_text_matches_the_type():
    assert center.impact_text(row("A", att.REQUEST_LEAVE, "待审批", [("2026-10-13", 8), ("2026-10-14", 8)], "事假")) == "10 月工时上限 −16h"
    assert center.impact_text(row("A", att.REQUEST_LEAVE, "待审批", [("2026-10-13", 8)], "年假"), annual={"available_hours": 32}) == "年假余额 40h → 32h"
    assert center.impact_text(row("A", att.REQUEST_COMP_TIME, "待审批", [("2026-10-13", 4)]), comp={"available_hours": 12}) == "调休余额 16h → 12h"
    assert center.impact_text(row("A", att.REQUEST_OVERTIME, "待审批", [("2026-10-17", 6)])) == "调休额度 +6h"
    assert center.impact_text(row("A", att.REQUEST_LEAVE, "待审批", [("2026-10-13", 8)], "婚假")) == "不扣年假和工时上限"


def test_team_absence_lists_names_and_dates_only_and_flags_crowded_days():
    first = date(2026, 10, 12)  # 周一
    work = {date(2026, 10, 12 + i) for i in range(14) if (first.toordinal() + i) % 7 not in (6, 0)}
    employees = [{"name": "E1", "employee_name": "演示员工14"}, {"name": "E2", "employee_name": "演示员工151"}, {"name": "E3", "employee_name": "演示员工118"}]
    rows = [
        row("OA-1", att.REQUEST_LEAVE, "已完成", [("2026-10-20", 8), ("2026-10-21", 8)], "病假", employee="E1"),
        row("OA-2", att.REQUEST_COMP_TIME, "待审批", [("2026-10-21", 4)], employee="E2"),
        row("OA-3", att.REQUEST_OVERTIME, "已完成", [("2026-10-21", 8)], employee="E3"),
        row("OA-4", att.REQUEST_LEAVE, "待审批", [("2026-10-20", 8)], "年假", employee="E1"),
        row("OA-5", att.REQUEST_LEAVE, "草稿", [("2026-10-22", 8)], "年假", employee="E3"),
    ]
    info = center.team_absence(first, work, employees, rows)
    days = {item["date"]: item for item in info["days"]}
    assert info["headcount"] == 3 and len(info["days"]) == 14
    assert days["2026-10-20"]["approved"] == ["演示员工14"] and days["2026-10-20"]["pending"] == []
    assert days["2026-10-21"]["approved"] == ["演示员工14"] and days["2026-10-21"]["pending"] == ["演示员工151"]
    assert days["2026-10-22"]["approved"] == [] and days["2026-10-22"]["pending"] == []
    assert days["2026-10-17"]["off_day"] is True and days["2026-10-19"]["off_day"] is False
    assert "10/21" in info["note"] and "演示员工14" in info["note"] and "演示员工151" in info["note"]
    assert not any(key in json.dumps(info, ensure_ascii=False) for key in ("病假", "年假", "事假", "调休"))
