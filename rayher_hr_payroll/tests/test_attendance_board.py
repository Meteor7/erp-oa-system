"""考勤中心图表 / 日历的统计（attendance_board.py）：只算已通过的，日历上审批中的也画，汇总里没有人名。"""
import json
from datetime import date, timedelta

from rayher_hr_payroll import attendance_board as board
from rayher_hr_payroll import attendance_requests as att
from rayher_hr_payroll.oa_document_types import REQUEST_TRAVEL

TODAY = date(2026, 10, 15)   # 周四
WORK = {date(2026, 9, 1) + timedelta(days=offset) for offset in range(122) if (date(2026, 9, 1) + timedelta(days=offset)).weekday() < 5}
MONTH = (date(2026, 10, 1), date(2026, 10, 31))


def row(employee, request_type, status, days, leave_type="", **extra):
    return {"name": f"OA-{employee}-{days[0][0]}", "employee": employee, "request_type": request_type, "workflow_status": status,
            "leave_type": leave_type, "attendance_days": json.dumps([{"work_date": d, "hours": h} for d, h in days]), **extra}


def trip(employee, start, end, status="已完成"):
    return {"name": f"T-{employee}", "employee": employee, "request_type": REQUEST_TRAVEL, "workflow_status": status,
            "travel_start_date": start, "travel_end_date": end, "leave_type": "", "attendance_days": None}


def stats(ids, rows, first=TODAY):
    return board.build_stats(ids, rows, first=first, work_dates=WORK, month_first=MONTH[0], month_last=MONTH[1])


ROWS = [
    row("A", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8), ("2026-10-16", 8)], "年假"),
    row("B", att.REQUEST_LEAVE, "已通过", [("2026-10-16", 3)], "事假"),
    row("C", att.REQUEST_COMP_TIME, "已完成", [("2026-10-19", 8)]),
    trip("D", "2026-10-15", "2026-10-16"),
    row("A", att.REQUEST_LEAVE, "待审批", [("2026-10-20", 8)], "病假"),                       # 审批中：不进统计
    row("X", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8)], "年假"),                       # 不在这批人里
    row("A", att.REQUEST_OVERTIME, "已完成", [("2026-10-17", 6)]),
]


def test_kinds_follow_the_request_type_and_the_leave_type():
    assert board.kind_of(row("A", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8)], "年假")) == "annual"
    assert board.kind_of(row("A", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8)], "事假")) == "personal"
    assert board.kind_of(row("A", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8)], "病假")) == "sick"
    assert board.kind_of(row("A", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8)], "婚假")) == "other"
    assert board.kind_of(row("A", att.REQUEST_COMP_TIME, "已完成", [("2026-10-15", 8)])) == "comp"
    assert board.kind_of(row("A", att.REQUEST_OVERTIME, "已完成", [("2026-10-15", 8)])) == "ot"
    assert board.kind_of(trip("A", "2026-10-15", "2026-10-15")) == "trip"
    assert board.kind_of({"request_type": "购买申请"}) is None


def test_a_trip_counts_its_work_days_and_a_broken_detail_counts_nothing():
    days = board.days_of(trip("A", "2026-10-15", "2026-10-20"), WORK)
    assert [day for day, _ in days] == [date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)]
    assert board.days_of(trip("A", "2026-10-20", "2026-10-15"), WORK) == []
    assert board.days_of({"request_type": att.REQUEST_LEAVE, "attendance_days": "not json", "from_date": "", "to_date": ""}) == []
    assert board.days_of({"request_type": att.REQUEST_LEAVE, "attendance_days": '[{"work_date": "2026-10-15"}]'}) == []


def test_stats_count_only_approved_requests_of_these_people():
    result = stats(["A", "B", "C", "D"], ROWS)
    assert result["headcount"] == 4
    assert result["today"] == {"off": 1, "trip": 1, "in": 2, "rest_day": False}
    assert result["month"]["by_kind"] == {"annual": 16, "personal": 3, "sick": 0, "comp": 8, "other": 0}
    assert result["month"]["hours"] == 27 and result["month"]["per_capita"] == 6.8
    # 14 天里 10 个工作日；请假和调休共 27 小时：1 - 27 / (4 × 8 × 10)
    assert result["rate"] == 0.9156
    days = result["days"]
    assert len(days) == 14 and days[0]["date"] == "2026-10-15" and days[0]["label"] == "10/15" and days[0]["weekday"] == "四"
    assert days[0]["off"] == 1 and days[0]["by_kind"]["annual"] == 1 and days[0]["by_kind"]["trip"] == 1
    assert days[1]["off"] == 2 and days[1]["by_kind"]["personal"] == 1
    assert days[2]["off_day"] is True and days[2]["off"] == 0 and days[2]["by_kind"]["ot"] == 1   # 周六加班：画出来，但不算不在岗
    assert days[4]["by_kind"]["comp"] == 1
    assert days[5]["off"] == 0 and days[5]["by_kind"]["sick"] == 0                                # 审批中的病假不进统计


def test_stats_on_a_rest_day_say_so_and_an_empty_group_is_fully_present():
    saturday = stats(["A"], [], first=date(2026, 10, 17))
    assert saturday["today"] == {"off": 0, "trip": 0, "in": 1, "rest_day": True}
    empty = stats([], [])
    assert empty["headcount"] == 0 and empty["rate"] == 1.0 and empty["month"]["per_capita"] == 0 and empty["today"]["in"] == 0


def test_a_person_on_a_trip_and_on_leave_the_same_day_counts_once():
    rows = [row("A", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8)], "年假"), trip("A", "2026-10-15", "2026-10-15")]
    assert stats(["A"], rows)["today"] == {"off": 1, "trip": 0, "in": 0, "rest_day": False}


def test_calendar_cells_prefer_approved_over_pending_and_leave_over_overtime():
    rows = [
        row("A", att.REQUEST_LEAVE, "待审批", [("2026-10-15", 8)], "事假"),
        row("A", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 3)], "年假"),
        row("B", att.REQUEST_LEAVE, "待审批", [("2026-10-16", 8)], "病假"),
        row("B", att.REQUEST_LEAVE, "已拒绝", [("2026-10-17", 8)], "病假"),
        row("C", att.REQUEST_OVERTIME, "已完成", [("2026-10-17", 6)]),
    ]
    members = [{"name": "A", "employee_name": "甲"}, {"name": "B", "employee_name": "乙"}, {"name": "C", "employee_name": "丙"}]
    result = {item["id"]: item for item in board.build_members(members, rows, first=TODAY, work_dates=WORK)}
    assert result["A"]["name"] == "甲" and len(result["A"]["cells"]) == 14
    assert result["A"]["cells"][0] == {"kind": "annual", "pending": False, "hours": 3}
    assert result["B"]["cells"][1] == {"kind": "sick", "pending": True, "hours": 8}
    assert result["B"]["cells"][2] is None                      # 已驳回的不画
    assert result["C"]["cells"][2] == {"kind": "ot", "pending": False, "hours": 6}


def test_personal_numbers_cover_the_year_the_last_six_months_and_the_next_two_weeks():
    rows = [
        row("A", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8), ("2026-10-16", 4)], "年假"),
        row("A", att.REQUEST_LEAVE, "待审批", [("2026-09-10", 8)], "事假"),
        row("A", att.REQUEST_COMP_TIME, "已完成", [("2026-05-04", 8)]),
        row("A", att.REQUEST_LEAVE, "已完成", [("2025-12-30", 8)], "病假"),
        row("A", att.REQUEST_OVERTIME, "已完成", [("2026-10-17", 6)]),
        row("A", att.REQUEST_LEAVE, "已驳回", [("2026-10-20", 8)], "年假"),
    ]
    result = board.build_personal("A", rows, first=TODAY, work_dates=WORK, year=2026)
    assert [item["period"] for item in result["months"]] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert [item["hours"] for item in result["months"]] == [8, 0, 0, 0, 8, 12]
    assert result["year_by_kind"] == {"annual": 12, "personal": 8, "sick": 0, "comp": 8, "other": 0}   # 去年 12 月的病假不算今年
    strip = result["strip"]
    assert [item["kind"] for item in strip[:4]] == ["annual", "annual", "ot", None] and strip[0]["hours"] == 8 and strip[1]["hours"] == 4
    assert strip[2]["off_day"] is True and strip[5]["kind"] is None


def test_months_roll_back_across_the_new_year():
    result = board.build_personal("A", [], first=date(2026, 2, 3), work_dates=WORK, year=2026)
    assert [item["period"] for item in result["months"]] == ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"]


def test_department_labels_drop_the_company_suffix_unless_that_would_make_two_the_same():
    assert board.department_labels(["研发软件部 - RAY", "客服部 - RAY", "客服部 - SHGL"]) == {
        "研发软件部 - RAY": "研发软件部", "客服部 - RAY": "客服部 - RAY", "客服部 - SHGL": "客服部 - SHGL"}


def test_the_company_summary_has_numbers_per_department_and_no_names():
    employees = [
        {"name": "A", "employee_name": "甲某某", "department": "研发软件部 - RAY"},
        {"name": "B", "employee_name": "乙某某", "department": "研发软件部 - RAY"},
        {"name": "C", "employee_name": "丙某某", "department": "财务部 - RAY"},
    ]
    rows = [row("A", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8)], "年假"), row("C", att.REQUEST_LEAVE, "已完成", [("2026-10-16", 8)], "事假")]
    result = board.summarize_departments(employees, rows, {"财务部 - RAY": 2, "研发软件部 - RAY": 1},
                                         first=TODAY, work_dates=WORK, month_first=MONTH[0], month_last=MONTH[1])
    assert [item["label"] for item in result["departments"]] == ["研发软件部", "财务部"]   # 人多的在前
    software, finance = result["departments"]
    assert software["headcount"] == 2 and software["today_off"] == 1 and software["month_hours"] == 8 and software["pending"] == 1
    assert software["trend"][0] == 1 and len(software["trend"]) == 14
    assert finance["month_hours"] == 8 and finance["per_capita"] == 8 and finance["pending"] == 2
    assert result["pending"] == 3 and result["stats"]["headcount"] == 3 and result["stats"]["today"]["off"] == 1
    text = json.dumps(result, ensure_ascii=False)
    for name in ("甲某某", "乙某某", "丙某某"):
        assert name not in text
    assert set(software) == {"department", "label", "headcount", "today_off", "today_trip", "trend", "month_hours", "per_capita", "rate", "pending"}
