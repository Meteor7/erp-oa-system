"""考勤中心图表 / 日历的统计（attendance_board.py）：只算已通过的，日历上审批中的也画；部门概况表只有数字，
首页一张申请一行的明细（request_rows）带人名（决定 2026-10-14：人事和管理层在首页直接看到是谁）。"""
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


def test_request_rows_one_per_request_with_names_days_and_month_hours():
    employees = [{"name": key, "employee_name": f"员工{key}", "department": "研发软件部 - RAY" if key != "C" else "财务部 - RAY"} for key in "ABCD"]
    rows = {item["name"]: item for item in board.request_rows(employees, ROWS, month_first=MONTH[0], month_last=MONTH[1], work_dates=WORK)}
    assert set(rows) == {"OA-A-2026-10-15", "OA-B-2026-10-16", "OA-C-2026-10-19", "T-D", "OA-A-2026-10-20", "OA-A-2026-10-17"}   # X 不在这批人里
    first = rows["OA-A-2026-10-15"]
    assert (first["employee_name"], first["department_label"], first["kind"], first["leave_type"], first["approved"]) == ("员工A", "研发软件部", "annual", "年假", True)
    assert first["days"] == [["2026-10-15", 8], ["2026-10-16", 8]] and first["month_hours"] == 16
    assert rows["OA-A-2026-10-20"]["approved"] is False                                       # 审批中：列出来，标好
    assert (rows["T-D"]["from_date"], rows["T-D"]["to_date"], rows["T-D"]["month_hours"]) == ("2026-10-15", "2026-10-16", 16)
    assert rows["OA-A-2026-10-17"]["kind"] == "ot" and rows["OA-A-2026-10-17"]["leave_type"] == ""
    # 已批准的按类型加起来 = leave_figures（看板的本月请假 / 调休 / 加班）
    figures = board.leave_figures(board.month_window([item for item in ROWS if board.is_approved(item)], *MONTH), [item["name"] for item in employees])
    total = lambda request_type: sum(item["month_hours"] for item in rows.values() if item["approved"] and item["request_type"] == request_type)
    assert (total(att.REQUEST_LEAVE), total(att.REQUEST_COMP_TIME), total(att.REQUEST_OVERTIME)) == (figures["leave_hours"], figures["comp_hours"], figures["overtime_hours"]) == (19, 8, 6)
    # 草稿、撤回的不要
    dropped = [row("A", att.REQUEST_LEAVE, "草稿", [("2026-10-21", 8)], "事假"), row("B", att.REQUEST_LEAVE, "已撤回", [("2026-10-21", 8)], "事假")]
    assert board.request_rows(employees, dropped, month_first=MONTH[0], month_last=MONTH[1], work_dates=WORK) == []


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
    assert result["today"] == {"off": 1, "trip": 1, "in": 2, "rest_day": False, "off_by_kind": {"annual": 1}}
    assert result["month"]["by_kind"] == {"annual": 16, "personal": 3, "sick": 0, "comp": 8, "other": 0}
    # 本月请假只算请假（决定 2026-10-13）：16 + 3 = 19 小时；调休 8 小时单独算
    assert result["month"]["hours"] == 19 and result["month"]["per_capita"] == 4.8
    assert result["month"]["comp_hours"] == 8 and result["month"]["leave_days"] == 2.38 and result["month"]["comp_days"] == 1
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
    assert saturday["today"] == {"off": 0, "trip": 0, "in": 1, "rest_day": True, "off_by_kind": {}}
    empty = stats([], [])
    assert empty["headcount"] == 0 and empty["rate"] == 1.0 and empty["month"]["per_capita"] == 0 and empty["today"]["in"] == 0


def test_a_person_on_a_trip_and_on_leave_the_same_day_counts_once():
    rows = [row("A", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8)], "年假"), trip("A", "2026-10-15", "2026-10-15")]
    assert stats(["A"], rows)["today"] == {"off": 1, "trip": 0, "in": 0, "rest_day": False, "off_by_kind": {"annual": 1}}


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
    assert set(software) == {"department", "label", "headcount", "today_off", "today_trip", "trend", "month_hours", "per_capita", "rate", "pending",
                            "month_leave_days", "month_comp_hours"}


def test_today_trips_is_the_same_group_as_the_trip_number_in_the_stats():
    """看板“出差中”的人数和点进去的名单是同一批人：已批准、今天在出差期间且是工作日，今天已请假 / 调休的人不重复算。"""
    employees = [{"name": name, "employee_name": f"员工{name}", "department": "RD - X"} for name in "ABCDE"]
    rows = [
        trip("A", "2026-10-14", "2026-10-16"),
        trip("B", "2026-10-15", "2026-10-15"),
        row("B", att.REQUEST_LEAVE, "已完成", [("2026-10-15", 8)], "年假"),            # B 今天已经请假：不算出差
        trip("C", "2026-10-16", "2026-10-20"),                                       # 明天才出发
        trip("D", "2026-10-10", "2026-10-20", status="待审批"),                       # 审批中不算
        {**trip("E", "2026-10-13", "2026-10-15"), "travel_destination": "上海"},
        {**trip("E", "2026-10-15", "2026-10-30"), "name": "T-E2", "travel_destination": "北京"},   # 同一个人两张：只出现一次
        trip("Z", "2026-10-15", "2026-10-15"),                                       # 不在员工名单里
    ]
    result = board.today_trips(employees, rows, first=TODAY, work_dates=WORK)
    assert [item["employee"] for item in result] == ["A", "E"]
    assert [item["name"] for item in result] == ["T-A", "T-E"] and result[1]["destination"] == "上海"
    assert result[0]["start"] == "2026-10-14" and result[0]["end"] == "2026-10-16" and result[0]["employee_name"] == "员工A"
    assert len(result) == stats([e["name"] for e in employees], rows)["today"]["trip"]
    # 周末今天不是工作日：没有人在出差（和人数口径一致）
    saturday = date(2026, 10, 17)
    assert board.today_trips(employees, rows, first=saturday, work_dates=WORK) == []
    assert stats([e["name"] for e in employees], rows, first=saturday)["today"]["trip"] == 0


def test_a_trip_counts_by_its_dates_once_approved_even_while_the_front_desk_has_not_clicked_yet():
    """决定 2026-10-13：出差按出差时间算人。两级审批通过后在前台办理（待办理）就算；请假没有办理节点，“待办理”不算。"""
    at_desk = trip("A", "2026-10-15", "2026-10-16", status="待办理")
    pending = trip("B", "2026-10-15", "2026-10-16", status="待审批")
    assert board.is_approved(at_desk) is True and board.is_approved(pending) is False
    assert board.is_approved(row("C", att.REQUEST_LEAVE, "待办理", [("2026-10-15", 8)], "年假")) is False
    result = stats(["A", "B"], [at_desk, pending])
    assert result["today"]["trip"] == 1
    employees = [{"name": "A", "employee_name": "员工A", "department": "RD"}, {"name": "B", "employee_name": "员工B", "department": "RD"}]
    assert [item["employee"] for item in board.today_trips(employees, [at_desk, pending], first=TODAY, work_dates=WORK)] == ["A"]
