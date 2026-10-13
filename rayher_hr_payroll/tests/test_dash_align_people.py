"""看板数字和点进去看到的东西对齐（人事 / 考勤 / 团队 / 个人 / 工时，决定 2026-10-13）。

每个数字点进去看到的行数 / 合计必须和卡片一样；同一个口径只有一个函数：
- 本月请假：attendance_board.leave_figures（按天、只算请假、调休单独、只算在职）；
- 今天不在岗：attendance_board.today_away（请假 / 调休，工作日，一人一条；出差另算“出差中”）；
- 考勤待审批：不含前台待办理的出差（已经批准）。
"""
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import attendance_board as board
from rayher_hr_payroll import attendance_requests as att
from rayher_hr_payroll import hr_read_access
from rayher_hr_payroll.api import attendance_board_entry, overview_entry
from rayher_hr_payroll.dashboard import attendance, core, people, personal, team, timesheet
from rayher_hr_payroll.oa_document_types import REQUEST_TRAVEL

TODAY = date(2026, 10, 15)   # 周四
WORK = {date(2026, 9, 1) + timedelta(days=offset) for offset in range(122) if (date(2026, 9, 1) + timedelta(days=offset)).weekday() < 5}
MONTH = (date(2026, 10, 1), date(2026, 10, 31))


def row(employee, request_type, days, leave_type="", status="已完成", name=None, **extra):
    return {"name": name or f"OA-{employee}-{request_type}-{days[0][0]}", "employee": employee, "employee_name": f"员工{employee}",
            "request_type": request_type, "workflow_status": status, "leave_type": leave_type,
            "attendance_days": json.dumps([{"work_date": d, "hours": h} for d, h in days]), **extra}


def trip(employee, start, end, status="已完成", name=None):
    return {"name": name or f"T-{employee}", "employee": employee, "request_type": REQUEST_TRAVEL, "workflow_status": status,
            "travel_start_date": start, "travel_end_date": end, "leave_type": "", "attendance_days": None}


def make_ctx(**kw):
    base = dict(user="hr@example.com", roles=frozenset({"HR Manager", "Employee"}), positions=frozenset({"hr_manager"}),
                period="2026-10", today="2026-10-15")
    base.update(kw)
    return core.Ctx(**base)


def run(key, ctx):
    provider = core.REGISTRY[key]
    if provider.visible is not None and not provider.visible(ctx):
        return None
    return provider.fn(ctx)


def detail_of(ctx, card):
    assert card["target"]["key"] == "drill", card
    return core.get_detail_for(ctx, card["target"]["params"]["item"])


# ================================================================ 本月请假：一个函数
def test_month_leave_counts_leave_only_in_days_and_keeps_comp_time_apart():
    rows = board.month_window([
        row("A", att.REQUEST_LEAVE, [("2026-10-15", 8), ("2026-10-16", 4)], "年假"),
        row("B", att.REQUEST_LEAVE, [("2026-09-30", 8), ("2026-10-01", 8)], "事假"),          # 跨月：只算 10-01 那天
        row("A", att.REQUEST_COMP_TIME, [("2026-10-20", 8)]),
        row("C", att.REQUEST_OVERTIME, [("2026-10-17", 6)]),
        row("Z", att.REQUEST_LEAVE, [("2026-10-15", 8)], "病假"),                             # 不在职：不算
    ], *MONTH)
    figures = board.leave_figures(rows, ["A", "B", "C"])
    assert (figures["leave_hours"], figures["leave_days"], figures["leave_count"]) == (20.0, 2.5, 2)
    assert (figures["comp_hours"], figures["comp_days"], figures["overtime_hours"]) == (8.0, 1.0, 6.0)
    assert figures["by_type"] == {"年假": 12.0, "事假": 8.0}                                  # 调休不是请假的假别
    assert figures["by_kind"] == {"annual": 12.0, "personal": 8.0, "comp": 8.0}
    assert sum(item["hours"] for item in figures["requests"] if item["request_type"] == att.REQUEST_LEAVE) == figures["leave_hours"]


def test_an_old_request_without_daily_detail_counts_its_hours_in_the_start_month():
    # 审查修正（2026-10-13）：没有逐日明细的旧申请按 duration_hours 记在开始日期所在的月，不按工作日 8 小时拆
    legacy = {"name": "OLD", "employee": "A", "request_type": att.REQUEST_LEAVE, "leave_type": "事假", "workflow_status": "已完成",
              "from_date": "2026-09-29", "to_date": "2026-10-02", "attendance_days": None, "duration_hours": 32}
    assert board.month_window([legacy], *MONTH) == []
    assert board.month_window([legacy], date(2026, 9, 1), date(2026, 9, 30))[0]["duration_hours"] == 32.0


def test_the_attendance_centre_home_month_figure_is_the_same_function():
    rows = [row("A", att.REQUEST_LEAVE, [("2026-10-15", 8)], "年假"), row("B", att.REQUEST_COMP_TIME, [("2026-10-16", 8)]),
            row("A", att.REQUEST_LEAVE, [("2026-10-20", 8)], "病假", status="待审批")]
    stats = board.build_stats(["A", "B"], rows, first=TODAY, work_dates=WORK, month_first=MONTH[0], month_last=MONTH[1])
    figures = board.leave_figures(board.month_window([item for item in rows if board.is_approved(item)], *MONTH), ["A", "B"])
    assert stats["month"]["leave_days"] == figures["leave_days"] == 1.0
    assert stats["month"]["comp_days"] == figures["comp_days"] == 1.0
    assert stats["month"]["hours"] == 8 and stats["month"]["per_capita_days"] == 0.5


def test_month_leave_groups_by_the_employee_record_department_and_skips_people_who_left(monkeypatch):
    staff = [{"name": "A", "department": "研发软件部 - RAY"}, {"name": "B", "department": "客服部 - RAY"}]
    windowed = [{"name": "L1", "employee": "A", "employee_name": "甲", "request_type": att.REQUEST_LEAVE, "leave_type": "年假",
                 "duration_hours": 16.0, "department": "旧部门 - RAY"},                         # 单据上的部门快照不用
                {"name": "L2", "employee": "B", "employee_name": "乙", "request_type": att.REQUEST_LEAVE, "leave_type": "事假", "duration_hours": 4.0},
                {"name": "C1", "employee": "B", "employee_name": "乙", "request_type": att.REQUEST_COMP_TIME, "duration_hours": 8.0},
                {"name": "O1", "employee": "A", "employee_name": "甲", "request_type": att.REQUEST_OVERTIME, "duration_hours": 12.0},
                {"name": "X1", "employee": "GONE", "employee_name": "离职", "request_type": att.REQUEST_LEAVE, "leave_type": "年假", "duration_hours": 80.0}]
    seen = {}

    def get_all(doctype, filters=None, **kwargs):
        seen["filters"] = filters
        return staff

    monkeypatch.setattr(overview_entry.frappe, "get_all", get_all, raising=False)
    monkeypatch.setattr(overview_entry, "_attendance_rows", lambda months, department=None, employees=None: windowed)
    result = overview_entry.month_leave([(2026, 10)])
    assert seen["filters"] == {"status": "Active"}
    assert result["totals"] == {"leave_days": 2.5, "leave_count": 2, "comp_days": 1.0, "overtime_days": 1.5}
    assert result["by_type"] == [{"label": "年假", "days": 2.0}, {"label": "事假", "days": 0.5}]
    assert [(item["department"], item["leave"], item["comp"], item["leave_count"]) for item in result["by_department"]] == [
        ("研发软件部 - RAY", 2.0, 0.0, 1), ("客服部 - RAY", 0.5, 1.0, 1)]


@pytest.fixture
def company_leave(monkeypatch):
    stats = {"totals": {"leave_days": 2.5, "leave_count": 3, "comp_days": 1.0, "overtime_days": 1.5},
             "by_type": [{"label": "年假", "days": 2.0}, {"label": "事假", "days": 0.5}],
             "by_department": [{"department": "研发软件部 - RAY", "leave": 2.0, "comp": 0.0, "overtime": 1.5, "leave_count": 2, "overtime_count": 1},
                               {"department": "客服部 - SHGL", "leave": 0.5, "comp": 1.0, "overtime": 0.0, "leave_count": 1, "overtime_count": 0}]}
    monkeypatch.setattr(overview_entry, "month_leave", lambda months, employees=None: json.loads(json.dumps(stats)))
    return stats


def test_every_company_leave_number_adds_up_to_the_same_total(company_leave):
    ctx = make_ctx()
    card = run("att.leave", ctx)
    assert (card["value"], card["unit"], card["sub"]) == ("2.5", "天", "另有调休 1 天")
    drill = detail_of(ctx, card)
    assert drill["summary"] == "共 3 张，合计 2.5 天"
    assert [row_["cells"] for row_ in drill["rows"]] == [["研发软件部", "2 张", "2 天"], ["客服部", "1 张", "0.5 天"]]
    depts = run("block.att_depts", ctx)
    assert sum(float(item["value"].split()[0]) for item in depts["rows"]) == 2.5
    assert depts["target"] == card["target"] and "不含调休" in depts["hint"] and "员工档案" in depts["hint"]
    types = run("block.leave_types", ctx)
    assert sum(float(item["value"]) for item in types["rows"]) == 2.5 and "另有调休 1 天" in types["sub"]
    assert all(item["label"] != "调休" for item in types["rows"])
    # 别的月份：考勤中心只看当月，明细里的行就不能再点
    other = core.get_detail_for(make_ctx(period="2026-09"), "att.leave")
    assert all(row_["target"] is None for row_ in other["rows"])


# ================================================================ 今天不在岗：一个函数
def test_today_away_is_per_person_on_work_days_and_trips_are_counted_apart():
    rows = [
        row("A", att.REQUEST_LEAVE, [("2026-10-15", 8)], "年假", name="L-A"),
        row("A", att.REQUEST_COMP_TIME, [("2026-10-15", 0)], name="C-A0"),                      # 当天 0 小时：不算
        row("B", att.REQUEST_COMP_TIME, [("2026-10-15", 3)], name="C-B"),
        row("B", att.REQUEST_LEAVE, [("2026-10-15", 5)], "事假", name="L-B"),                 # 同一个人第二张：只算一次
        row("C", att.REQUEST_LEAVE, [("2026-10-15", 8)], "病假", status="待审批"),              # 审批中不算
        trip("D", "2026-10-14", "2026-10-16", status="待办理"),                                 # 前台待办理 = 已批准：出差中
        trip("A", "2026-10-15", "2026-10-15"),                                                  # 已经请假的不再算出差
        row("Z", att.REQUEST_LEAVE, [("2026-10-15", 8)], "年假"),                               # 不在这批人里
    ]
    away = board.today_away(["A", "B", "C", "D"], rows, first=TODAY, work_dates=WORK)
    assert sorted((item["employee"], item["kind"]) for item in away["off"]) == [("A", "annual"), ("B", "comp")]
    assert [item["employee"] for item in away["trip"]] == ["D"]
    stats = board.build_stats(["A", "B", "C", "D"], rows, first=TODAY, work_dates=WORK, month_first=MONTH[0], month_last=MONTH[1])
    assert stats["today"]["off"] == len(away["off"]) and stats["today"]["trip"] == len(away["trip"])
    assert stats["today"]["off_by_kind"] == {"annual": 1, "comp": 1}
    assert board.today_away(["A"], rows, first=date(2026, 10, 17), work_dates=WORK) == {"off": [], "trip": []}   # 周六


def test_company_away_today_card_and_list_are_the_same_people(monkeypatch):
    monkeypatch.setattr(attendance_board_entry, "today_away", lambda today=None, employees=None: {
        "off": [{"employee": "A", "employee_name": "甲", "kind": "annual", "request": "L-A"}, {"employee": "B", "employee_name": "乙", "kind": "comp", "request": "C-B"},
                {"employee": "E", "employee_name": "戊", "kind": "annual", "request": "L-E"}],
        "trip": [{"employee": "D", "employee_name": "丁", "request": "T-D"}]})
    card = run("hr.away_today", make_ctx())
    assert (card["value"], card["sub"]) == ("3", "年假 2 · 调休 1 · 另有出差 1")
    assert card["target"] == {"key": "attendance.today", "params": {}}
    assert "一人只算一次" in card["hint"] and "出差不算不在岗" in card["hint"]


def test_the_away_today_list_api_gives_one_request_per_person(monkeypatch):
    from rayher_hr_payroll.api import attendance_entry

    monkeypatch.setattr(attendance_entry, "_user", lambda: "hr@example.com")
    monkeypatch.setattr(attendance_entry, "_require_types", lambda: ["请假申请"])
    monkeypatch.setattr(attendance_entry, "can_view_all", lambda: True)
    monkeypatch.setattr(attendance_board_entry, "today_away", lambda today=None, employees=None: {
        "off": [{"employee": "A", "request": "L-A", "kind": "annual"}, {"employee": "B", "request": "C-B", "kind": "comp"}], "trip": [{"employee": "D", "request": "T-D"}]})
    monkeypatch.setattr(attendance_entry, "_load_summaries", lambda names: [{"name": name, "steps": []} for name in names])
    monkeypatch.setattr(attendance_entry, "_names", lambda users: {})
    api = getattr(attendance_entry.list_attendance_away_today, "__wrapped__", attendance_entry.list_attendance_away_today)
    result = api()
    assert [item["name"] for item in result["items"]] == ["L-A", "C-B"] and result["trip"] == 1
    monkeypatch.setattr(attendance_entry, "can_view_all", lambda: False)
    with pytest.raises(Exception):
        api()


# ================================================================ 考勤待审批：不含前台待办理的出差，已等从最近一次处理算
def test_pending_sql_leaves_out_trips_waiting_at_the_front_desk():
    text = attendance_board_entry.pending_sql("r")
    assert "r.workflow_status = '待审批'" in text and "r.workflow_status = '待办理' AND r.request_type <> '出差申请'" in text


def test_the_attendance_centre_pending_counts_use_the_same_rule(monkeypatch):
    seen = []
    monkeypatch.setattr(attendance_board_entry.frappe, "db", SimpleNamespace(sql=lambda query, args=None, as_dict=False: seen.append(query) or []), raising=False)
    attendance_board_entry._pending()
    assert attendance_board_entry.pending_sql("r") in seen[0]


def test_waiting_days_count_from_the_last_action_then_the_last_submit_then_creation():
    log = json.dumps([{"action": "提交申请", "acted_on": "2026-10-01 09:00:00"}, {"action": "提交申请", "acted_on": "2026-10-10 09:00:00"}])
    assert attendance._waited_days({"last_acted": "2026-10-13 18:00:00", "operation_log": log, "creation": "2026-09-01"}, "2026-10-15") == 2
    assert attendance._waited_days({"last_acted": None, "operation_log": log, "creation": "2026-09-01"}, "2026-10-15") == 5
    assert attendance._waited_days({"last_acted": None, "operation_log": "[]", "creation": "2026-10-11 08:00:00"}, "2026-10-15") == 4


def test_pending_card_and_alert_count_from_the_same_rows(monkeypatch):
    rows = [{"name": f"OA-{i}", "request_type": "请假申请", "waited": waited} for i, waited in enumerate([5, 4, 1, 0])]
    calls = []
    monkeypatch.setattr(attendance, "_load_waiting_rows", lambda ctx: calls.append(1) or rows)
    ctx = make_ctx()
    assert run("att.pending", ctx)["value"] == "4" and run("alert.att_pending", ctx)["title"].startswith("2 张")
    assert len(core.get_detail_for(ctx, "att.pending_old")["rows"]) == 2 and len(calls) == 1


# ================================================================ 团队
def _team_ctx(**kw):
    return core.Ctx(**{**dict(user="boss@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10",
                              today="2026-10-15", employee="E1", has_reports=True), **kw})


def _member(name, first_kind=None):
    cells = [None] * 14
    if first_kind:
        cells[0] = {"kind": first_kind, "pending": False, "hours": 8}
    return {"id": name, "name": name, "cells": cells}


@pytest.fixture
def team_state(monkeypatch):
    members = [_member("张主管"), _member("杨员工", "annual"), _member("演示员工120", "trip"), _member("演示员工181", "comp")]
    days = [{"date": f"2026-10-{15 + i:02d}", "label": f"10/{15 + i}", "day": 15 + i, "weekday": "四", "off_day": i in (2, 3, 9, 10)} for i in range(14)]
    detail = {"headcount": 4, "label": "我的团队", "members": members, "stats": {"days": days, "today": {"rest_day": False}},
              "today_away": {"off": [{"employee": "E2", "employee_name": "杨员工", "kind": "annual", "request": "L-2"},
                                     {"employee": "E4", "employee_name": "演示员工181", "kind": "comp", "request": "C-4"}],
                             "trip": [{"employee": "E3", "employee_name": "演示员工120", "request": "T-3"}]}}
    rows = {(2026, 10): [{"name": "L-2", "employee": "E2", "employee_name": "杨员工", "request_type": att.REQUEST_LEAVE, "leave_type": "年假",
                          "duration_hours": 12, "from_date": "2026-10-15", "to_date": "2026-10-16"},
                         {"name": "C-4", "employee": "E4", "employee_name": "演示员工181", "request_type": att.REQUEST_COMP_TIME, "duration_hours": 8,
                          "from_date": "2026-10-15", "to_date": "2026-10-15"},
                         {"name": "O-3", "employee": "E3", "employee_name": "演示员工120", "request_type": att.REQUEST_OVERTIME, "duration_hours": 6,
                          "from_date": "2026-10-11", "to_date": "2026-10-11"}]}
    monkeypatch.setattr(team, "_load_team_ids", lambda ctx: ["E1", "E2", "E3", "E4"])
    monkeypatch.setattr(team, "_load_team_detail", lambda ctx: detail)
    monkeypatch.setattr(team, "_load_team_rows", lambda year, month, ids: rows.get((year, month), []))
    monkeypatch.setattr(team, "_load_team_staff", lambda ids: [{"name": i, "employee_name": i, "rd_personnel_type": "全时研发", "date_of_joining": "2020-01-01"} for i in ids])
    monkeypatch.setattr(team, "_load_rd_types", lambda: ("全时研发",))
    return detail


def test_team_leave_is_days_of_leave_only_and_its_list_opens_each_request(team_state):
    ctx = _team_ctx()
    card = run("team.leave", ctx)
    assert (card["value"], card["unit"], card["sub"]) == ("1.5", "天", "人均 0.38 天 · 另有调休 1 天")
    drill = detail_of(ctx, card)
    assert drill["summary"] == "请假 1 张，合计 1.5 天"
    assert drill["rows"][0]["target"] == {"key": "attendance.detail", "params": {"request": "L-2"}}
    assert drill["rows"][1]["tone"] == "info" and drill["rows"][1]["cells"][1] == "调休"            # 调休浅色列在后面，不进合计
    overtime = run("team.overtime", ctx)
    assert detail_of(ctx, overtime)["summary"] == "加班 1 张，合计 6 小时" and overtime["value"] == "6"
    # 别的月份：明细按那个月取，不再跳到只看当月的考勤中心首页
    assert run("team.leave", _team_ctx(period="2026-09"))["target"] is None


def test_team_away_excludes_trips_everywhere_and_opens_one_row_per_person(team_state):
    ctx = _team_ctx()
    card = run("team.away", ctx)
    assert (card["value"], card["sub"]) == ("2", "杨员工（年假）、演示员工181（调休） · 另有出差 1")
    drill = detail_of(ctx, card)
    assert drill["summary"] == "不在岗 2 人，另有出差 1 人"
    assert [r["target"]["params"]["request"] for r in drill["rows"]] == ["L-2", "C-4", "T-3"] and drill["rows"][2]["tone"] == "info"
    calendar = run("block.team_calendar", ctx)
    assert calendar["totals"][0] == {"off": 2, "present": 2}                                       # 出差的人算在岗
    assert calendar["people"][2]["cells"][0]["kind"] == "trip"                                     # 日历上照样画出差
    assert "出差画在日历上，但不算不在岗" in calendar["hint"]


def test_low_staff_alert_does_not_count_people_on_a_trip(team_state):
    team_state["members"] = [_member("张主管")] + [_member(f"出差{i}", "trip") for i in range(4)]
    team_state["headcount"] = 5
    assert run("alert.team_low_staff", _team_ctx()) is None


def test_team_headcount_opens_the_member_list(team_state):
    ctx = _team_ctx()
    card = run("team.headcount", ctx)
    assert detail_of(ctx, card)["summary"] == "共 4 人，研发 4 人" and card["value"] == "4"


# ================================================================ 工资：只算已确认
SLIPS = [{"employee": "A", "docstatus": 1, "gross_pay": 20000, "department": "研发软件部 - RAY"},
         {"employee": "B", "docstatus": 1, "gross_pay": 15000, "department": "客服部 - RAY"},
         {"employee": "C", "docstatus": 0, "gross_pay": 9000, "department": "研发软件部 - RAY"},
         {"employee": "B", "docstatus": 0, "gross_pay": 1, "department": "客服部 - RAY"}]           # B 也有一张草稿：已确认优先
STAFF = [{"name": n, "employee_name": n, "status": "Active", "department": d, "date_of_joining": "2020-01-01"}
         for n, d in (("A", "研发软件部 - RAY"), ("B", "客服部 - RAY"), ("C", "研发软件部 - RAY"), ("D", "客服部 - RAY"))]


@pytest.fixture
def payroll(monkeypatch):
    monkeypatch.setattr(people, "_fetch_employees", lambda ctx: STAFF)
    monkeypatch.setattr(people, "_fetch_slips", lambda period: SLIPS if period == "2026-10" else [])
    monkeypatch.setattr(people, "_fetch_pay_totals", lambda period: {"gross": 35000.0} if period == "2026-10" else {"gross": 30000.0})
    monkeypatch.setattr(people, "_fetch_salaries", lambda period: {"A": 20000.0, "B": 15000.0})
    monkeypatch.setattr(people, "_fetch_contribution_records", lambda ctx: {key: {"any": set(), "confirmed": set()} for key in ("si", "hf")})


def test_pay_total_counts_confirmed_slips_only_and_its_drill_adds_up_to_it(payroll):
    ctx = make_ctx()
    summary = people.summarize_payroll(STAFF, SLIPS, "2026-10")
    assert (summary["confirmed"], summary["draft"], summary["missing"], summary["draft_gross"]) == (2, 1, 1, 9000)
    card = run("hr.pay_total", ctx)
    assert (card["value"], card["unit"]) == ("3.5", "万") and card["sub"].startswith("还有 1 人没确认（草稿 约 9,000 元）")
    drill = detail_of(ctx, card)
    total = sum(float(r["cells"][3].replace("¥", "").replace(",", "")) for r in drill["rows"])
    assert total == 35000.0 and drill["summary"] == "已确认 2 人，应发合计 ¥ 35,000.00"
    assert [r["cells"] for r in drill["rows"]] == [["研发软件部", "1 人", "1 人", "¥ 20,000.00"], ["客服部", "1 人", "0 人", "¥ 15,000.00"]]


def test_drafts_are_left_out_of_the_department_bars(payroll):
    block = run("block.pay_by_dept", make_ctx())
    assert block["title"] == "部门应发工资（已确认）"
    assert [(r["label"], r["value"]) for r in block["rows"]] == [("研发软件部", "2.0"), ("客服部", "1.5")]   # C 的草稿 9000 不算
    payroll_card = run("hr.payroll", make_ctx())
    assert (payroll_card["value"], payroll_card["sub"]) == ("2 / 4", "草稿 1 · 未生成 1")
    assert payroll_card["target"] == {"key": "payroll", "params": {"period": "2026-10", "status": "draft"}}
    alert_ = run("alert.payroll_draft", make_ctx())
    assert (alert_["title"], alert_["go"]) == ("1 人工资条还没确认", "去确认")
    rows = run("block.pay_progress", make_ctx())["rows"]
    assert [r["label"] for r in rows[:3]] == ["工资条已确认", "工资条草稿", "工资条未生成"]


# ================================================================ 员工信息、宿舍
def test_file_pending_subtitle_explains_the_number(monkeypatch):
    staff = [{"name": "A", "status": "Active", "archive_status": None}, {"name": "B", "status": "Active", "archive_status": "待完善"},
             {"name": "C", "status": "Active", "archive_status": "待确认"}, {"name": "D", "status": "Active", "archive_status": "乱写"}]
    monkeypatch.setattr(people, "_fetch_employees", lambda ctx: staff)
    card = run("hr.file_pending", make_ctx())
    assert (card["value"], card["sub"]) == ("3", "2 人还没填档案状态 · 1 人标了待完善")
    assert card["target"]["key"] == "personnel.file"


def test_probation_and_contract_alerts_open_their_own_kind(monkeypatch):
    staff = [{"name": "A", "employee_name": "甲", "status": "Active", "probation_end_date": "2026-10-20"},
             {"name": "B", "employee_name": "乙", "status": "Active", "first_contract_end_date": "2026-11-01"}]
    monkeypatch.setattr(people, "_fetch_employees", lambda ctx: staff)
    ctx = make_ctx()
    # targets.json 里没有专门的目标时，点进去是同一份名单的明细
    targets = {key: value for key, value in core.load_targets().items() if key not in ("personnel.probation", "personnel.contract")}
    monkeypatch.setattr(core, "_TARGETS", targets)
    probation = run("alert.probation", ctx)
    assert probation["target"] == {"key": "drill", "params": {"item": "hr.probation", "period": "2026-10"}}
    drill = core.get_detail_for(ctx, "hr.probation")
    assert [r["cells"][0] for r in drill["rows"]] == ["甲"] and drill["summary"] == "共 1 人"
    assert [r["cells"][0] for r in core.get_detail_for(ctx, "hr.contract")["rows"]] == ["乙"]
    # targets.json 现在有 personnel.probation / personnel.contract：直接去员工页（只看那一种）
    monkeypatch.setattr(core, "_TARGETS", None)  # 重新读 targets.json
    assert core.load_targets()["personnel.contract"]["query"] == {"status": "active", "reminder": "contract"}
    assert run("alert.probation", ctx)["target"] == {"key": "personnel.probation", "params": {}}
    assert run("alert.contract", ctx)["target"] == {"key": "personnel.contract", "params": {}}


def test_dorm_lease_card_counts_what_the_renewal_list_shows(monkeypatch):
    monkeypatch.setattr(people, "_fetch_dorm", lambda ctx: {"lease_alert": {"count": 2, "expired_count": 1, "earliest_date": "2026-10-20"},
                                                             "leavers_in_rooms": [], "rooms": [], "occupancy": {}, "cost": {}})
    card = run("hr.dorm_lease", make_ctx())
    assert (card["value"], card["sub"]) == ("3", "其中已过期 1 间 · 最早 10-20 到期")
    assert card["target"]["key"] == "dorm.lease"


def test_dorm_cost_for_a_month_opens_that_month(monkeypatch):
    monkeypatch.setattr(people, "_fetch_dorm", lambda ctx: {"cost": {"registered": True, "total": 100.0, "company": 60.0, "personal": 40.0,
                                                                      "components": [{"label": "房租", "company": 60.0, "personal": 40.0}]}})
    block = run("block.dorm_cost", make_ctx(period="2026-08"))
    assert block["target"] == {"key": "dorm.monthly", "params": {"period": "2026-08"}}


# ================================================================ 个人
def test_my_approvals_send_travel_to_the_attendance_todo_list(monkeypatch):
    summary = {"total": 3, "categories": [{"key": "travel", "label": "出差", "count": 1}, {"key": "leave", "label": "请假", "count": 2}]}
    monkeypatch.setattr(personal, "_load_approval_summary", lambda: summary)
    assert run("me.approvals", make_ctx(employee="E1"))["target"] == {"key": "attendance.todo", "params": {}}
    summary["categories"] = [{"key": "travel", "label": "出差", "count": 1}]
    assert run("me.approvals", make_ctx(employee="E1"))["target"] == {"key": "attendance.todo", "params": {"type": "出差"}}


def test_my_claims_card_opens_the_same_in_flight_list(monkeypatch):
    claims = [{"name": "C1", "amount": 100, "approved_amount": 0, "workflow_status": "待审批", "current_step_label": "财务"},
              {"name": "C0", "amount": 50, "approved_amount": 0, "workflow_status": "草稿", "current_step_label": ""}]
    monkeypatch.setattr(personal, "_load_my_claims", lambda user, employee: claims)
    ctx = make_ctx(employee="E1")
    card = run("me.claim", ctx)
    drill = detail_of(ctx, card)
    assert card["value"] == "1" and drill["summary"].startswith("在途 1 张")
    assert [r["target"]["params"]["request"] for r in drill["rows"]] == ["C1", "C0"] and drill["rows"][1]["tone"] == "info"


def test_my_requests_and_notifications_have_lists(monkeypatch):
    monkeypatch.setattr(personal, "_load_my_requests", lambda limit: [{"name": "R1", "subject": "请假", "request_type": "请假申请", "status": "待审批",
                                                                       "route": "/approval/leave", "step_label": "主管"}])
    monkeypatch.setattr(personal, "_load_notification_counts", lambda: {"cc": 3, "mine": 1, "biz": 0, "sys": 0})
    monkeypatch.setattr(personal, "_load_notification_items", lambda category: [{"event": "抄送", "title": "单据", "route": "/approval/claim",
                                                                               "query": {"request": "BX-1"}, "created": "2026-10-14 10:00:00"}] if category == "cc" else [])
    ctx = make_ctx(employee="E1")
    requests = run("me.requests", ctx)
    assert detail_of(ctx, requests)["rows"][0]["target"] == {"key": "attendance.detail", "params": {"request": "R1"}}
    cc = run("me.cc", ctx)
    assert detail_of(ctx, cc)["summary"].startswith("共 3 条未读") and run("me.unread", ctx)["target"]["params"]["item"] == "me.unread"


def test_my_timesheet_uses_the_fill_progress_rule_in_hours(monkeypatch):
    monkeypatch.setattr(personal, "_load_is_rd", lambda user, employee: True)
    monkeypatch.setattr(personal, "_load_my_entries", lambda period, employee: {"max_day_limit": 21.63, "total_days": 21.56, "hour_limit": 173,
                                                                                "total_hours": 172.5, "entries": []})
    card = run("me.timesheet", make_ctx(employee="E1"))
    assert card["value"].startswith("还差")                                                        # 172.5 / 173 小时：填报进度算“未填满”
    monkeypatch.setattr(personal, "_load_my_entries", lambda period, employee: {"max_day_limit": 21.63, "total_days": 21.63, "hour_limit": 173,
                                                                                "total_hours": 173, "entries": []})
    assert run("me.timesheet", make_ctx(employee="E1"))["value"] == "已填满"


def test_my_overtime_card_does_not_link_to_the_current_month_for_another_month(monkeypatch):
    monkeypatch.setattr(personal, "_load_attendance_home", lambda period: {"employee": {"name": "E1"}, "month": {"overtime_hours": 4, "leave_days": 0}})
    assert run("me.overtime_month", make_ctx(employee="E1"))["target"] == {"key": "attendance.home", "params": {}}
    assert run("me.overtime_month", make_ctx(employee="E1", period="2026-09"))["target"] is None


# ================================================================ 工时
def _fill(kind="team"):
    employees = [{"employee": "E1", "employee_name": "甲", "department": "研发一部", "status": "full", "used_days": 20, "limit_days": 20},
                 {"employee": "E2", "employee_name": "乙", "department": "研发二部", "status": "none", "used_days": 0, "limit_days": 20}]
    return {"kind": kind, "can_remind": True, "deadline": "2026-10-31", "employees": employees,
            "summary": {"total": 2, "full": 1, "part": 0, "none": 1, "over": 0, "rate": 50.0}}


def test_timesheet_blocks_show_for_people_with_reports_not_for_a_role_name(monkeypatch):
    monkeypatch.setattr(timesheet, "_load_fill", lambda period: _fill())
    with_reports = core.Ctx(user="m@tests-x.example.invalid", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-15", has_reports=True)
    role_only = core.Ctx(user="m@tests-x.example.invalid", roles=frozenset({"Department Manager", "Employee"}), positions=frozenset(), period="2026-10", today="2026-10-15")
    assert timesheet._fill_visible(with_reports) and not timesheet._fill_visible(role_only)


def test_project_numbers_count_only_the_roster_and_open_a_list_with_the_same_total(monkeypatch):
    monkeypatch.setattr(timesheet, "_load_fill", lambda period: _fill())
    monkeypatch.setattr(timesheet, "_load_entries", lambda period: {"entries": [
        {"employee": "E1", "project": "P1", "project_name": "项目一", "hours": 80}, {"employee": "E2", "project": "P1", "project_name": "项目一", "hours": 8},
        {"employee": "E2", "project": "P2", "project_name": "项目二", "hours": 16}, {"employee": "X", "project": "P3", "project_name": "名单外", "hours": 99}]})
    ctx = core.Ctx(user="m@tests-x.example.invalid", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-15", has_reports=True)
    card = run("dept.projects", ctx)
    drill = detail_of(ctx, card)
    assert card["value"] == "2" and drill["summary"] == "共 2 个项目，合计 104 小时"
    assert [r["cells"] for r in drill["rows"]] == [["项目一", "2 人", "88", "11"], ["项目二", "1 人", "16", "2"]]
    assert run("block.ts_projects", ctx)["target"] == card["target"]


def test_department_progress_rows_open_the_board_for_that_department(monkeypatch):
    monkeypatch.setattr(timesheet, "_load_fill", lambda period: _fill("all"))
    ctx = make_ctx()
    block = run("block.ts_by_dept", ctx)
    drill = detail_of(ctx, block)
    assert drill["summary"] == "共 2 人，已填满 1 人"
    assert drill["rows"][0]["target"] == {"key": "timesheet.board", "params": {"period": "2026-10", "dept": "研发二部", "status": "open"}}


def test_fill_progress_reads_filled_hours_for_the_roster_including_people_who_left(monkeypatch):
    from rayher_hr_payroll.api import monthly_timesheet_entry as mt

    seen = {}
    monkeypatch.setattr(mt, "_employees_for_scope", lambda scope, start=None: [{"name": "E1", "employee_name": "甲"}, {"name": "LEFT", "employee_name": "走了"}])
    monkeypatch.setattr(mt.frappe, "get_all", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(mt, "resolve_monthly_work_limit", lambda year, month, employee=None, **k: {"hour_limit": 160}, raising=False)

    def query(period, employee=None, employees=None):
        seen.setdefault("employees", []).append(employees)
        return [{"employee": "LEFT", "hours": 40, "project": "P", "employee_name": "走了"}] if employees else []

    monkeypatch.setattr(mt, "_query_monthly_entries", query)
    monkeypatch.setattr(mt, "_query_legacy_monthly_entries", lambda period, employee=None, employees=None: [])
    rows = {item["employee"]: item for item in mt._fill_rows(2026, 10, ["E1", "LEFT"])}
    assert seen["employees"] == [["E1", "LEFT"]]
    assert rows["LEFT"]["status"] == "part" and rows["LEFT"]["used_hours"] == 40       # 本月离职的人填了的不再显示成“一点没填”


def test_the_summary_filter_takes_the_month_into_account(monkeypatch):
    from rayher_hr_payroll.api import monthly_timesheet_entry as mt

    seen = []
    monkeypatch.setattr(mt, "_monthly_employee_scope", lambda mode, period_start=None: seen.append(period_start) or ["E1"])
    assert mt._monthly_summary_employee_filter(None, date(2026, 10, 1))[2] == ("E1",)
    assert seen == [date(2026, 10, 1)]
    assert mt._monthly_summary_employee_filter(None, None, ["A", "B"]) == ("and ts.employee in %(employees)s", None, ("A", "B"))


# ================================================================ 总经理、副总经理只读
def test_leaders_pass_the_read_check_and_others_fall_back_to_roles(monkeypatch):
    from rayher_hr_payroll import position_access

    monkeypatch.setattr(position_access, "position_users", lambda *keys: {"person014@tests-x.example.invalid"} if "general_manager" in keys else set())
    checked = []
    monkeypatch.setattr(hr_read_access.frappe, "session", SimpleNamespace(user="GM@tests-x.example.invalid"), raising=False)
    hr_read_access.require_hr_read(("HR Manager",), lambda roles: checked.append(roles))
    assert checked == [] and hr_read_access.is_hr_leader()
    monkeypatch.setattr(hr_read_access.frappe, "session", SimpleNamespace(user="someone@tests-x.example.invalid"), raising=False)
    hr_read_access.require_hr_read(("HR Manager",), lambda roles: checked.append(roles))
    assert checked == [("HR Manager",)]

    def broken(*keys):
        raise RuntimeError("岗位查不出来")

    monkeypatch.setattr(position_access, "position_users", broken)
    assert hr_read_access.is_hr_leader("person014@tests-x.example.invalid") is False                             # 查不出来就不放行


def test_only_read_endpoints_let_leaders_in():
    import inspect
    from rayher_hr_payroll.api import (
        accommodation_master_entry, contribution_workbench_entry, dormitory_board, housing_fund_import_entry, hr_contribution_entry, personnel_entry,
        social_insurance_import_entry,
    )

    reads = {personnel_entry: ["list_employees", "get_dept_options", "get_company_options"], dormitory_board: ["get_dormitory_board"],
             accommodation_master_entry: ["list_rooms"], social_insurance_import_entry: ["get_social_workbench"],
             housing_fund_import_entry: ["get_fund_workbench"], hr_contribution_entry: ["list_social_insurance", "list_housing_fund"],
             contribution_workbench_entry: ["get_base_table"]}
    writes = {personnel_entry: [], accommodation_master_entry: ["save_room"], social_insurance_import_entry: ["upload_social_workbook", "confirm_social_row"],
              housing_fund_import_entry: ["confirm_fund_row"], hr_contribution_entry: ["save_social_insurance"], contribution_workbench_entry: ["save_employee_base"]}
    for module, names in reads.items():
        for name in names:
            assert "require_hr_read(" in inspect.getsource(getattr(module, name)), (module.__name__, name)
    for module, names in writes.items():
        for name in names:
            source = inspect.getsource(getattr(module, name))
            assert "require_hr_read(" not in source and "require_rd_access(" in source, (module.__name__, name)


def test_leaders_can_open_the_whole_attendance_list(monkeypatch):
    from rayher_hr_payroll.api import attendance_entry

    monkeypatch.setattr(attendance_entry.frappe, "session", SimpleNamespace(user="vp@tests-x.example.invalid"), raising=False)
    monkeypatch.setattr(attendance_entry.frappe, "get_roles", lambda user=None: ["Employee"], raising=False)
    monkeypatch.setattr(hr_read_access, "is_hr_leader", lambda user=None: True)
    assert attendance_entry.can_view_all() is True
    monkeypatch.setattr(hr_read_access, "is_hr_leader", lambda user=None: False)
    assert attendance_entry.can_view_all() is False
    # 看板上“人事”页的可见性用同一组岗位
    assert people._hr_view(make_ctx(roles=frozenset({"Employee"}), positions=frozenset({"vice_manager"})))
    assert set(people.LEADER_POSITIONS) == set(hr_read_access.LEADER_POSITIONS)
