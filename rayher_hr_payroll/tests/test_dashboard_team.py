"""看板的团队部分：范围是汇报关系向下，显示人名；可见性只看有没有直接下属。"""
import pytest

from rayher_hr_payroll.dashboard import core, layout, team


def make_ctx(**kw):
    base = dict(user="boss@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-12",
                employee="E1", has_reports=True)
    base.update(kw)
    return core.Ctx(**base)


def run(key, ctx):
    provider = core.REGISTRY[key]
    if provider.visible is not None and not provider.visible(ctx):
        return None
    return provider.fn(ctx)


def cell(kind, pending=False):
    return {"kind": kind, "pending": pending, "hours": 8}


def days(count=14, off=None):
    off = off or {}
    out = []
    for index in range(count):
        day = 12 + index
        out.append({"date": f"2026-10-{day:02d}", "label": f"10/{day}", "day": day, "weekday": "一", "off_day": index in (5, 6, 12, 13), "off": off.get(index, 0)})
    return out


def detail(members, headcount=None, rest_day=False):
    # today_away：考勤中心团队明细里“今天不在岗 / 出差中”的人（口径见 attendance_board.today_away），这里按第 0 天已批准的格子造
    def first(kinds):
        return [{"employee": m["id"], "employee_name": m["name"], "kind": m["cells"][0]["kind"], "request": f"OA-{m['id']}"}
                for m in members if not rest_day and m["cells"][0] and m["cells"][0]["kind"] in kinds and not m["cells"][0]["pending"]]
    away = {"off": first(("annual", "personal", "sick", "comp", "other")), "trip": first(("trip",))}
    return {"headcount": headcount or len(members), "label": "我的团队", "stats": {"days": days(), "today": {"rest_day": rest_day},
            "month": {"hours": 64, "per_capita": 4.3, "by_kind": {}}}, "members": members, "today_away": away}


def member(name, **cells):
    row = [None] * 14
    for index, value in cells.items():
        row[int(index[1:])] = value
    return {"id": name, "name": name, "cells": row}


@pytest.fixture
def state(monkeypatch):
    data = {"ids": ["E1", "E2", "E3", "E4"], "detail": detail([member("张主管"), member("杨员工", d0=cell("annual"), d3=cell("personal")),
            member("演示员工120", d0=cell("trip"), d3=cell("personal"), d1=cell("comp", True)), member("演示员工181", d3=cell("sick"), d4=cell("annual"))]),
            "staff": [{"name": "E1", "rd_personnel_type": "", "date_of_joining": "2020-01-01"},
                      {"name": "E2", "rd_personnel_type": "全时研发", "date_of_joining": "2026-10-05"},
                      {"name": "E3", "rd_personnel_type": "辅助", "date_of_joining": "2024-03-01"},
                      {"name": "E4", "rd_personnel_type": "全时研发", "date_of_joining": "2023-03-01"}],
            "rows": {}, "calls": {"detail": 0, "rows": 0}}

    def load_rows(year, month, ids):
        data["calls"]["rows"] += 1
        return data["rows"].get((year, month), [])

    def load_detail(ctx):
        data["calls"]["detail"] += 1
        return data["detail"]

    monkeypatch.setattr(team, "_load_team_ids", lambda ctx: data["ids"])
    monkeypatch.setattr(team, "_load_team_detail", load_detail)
    monkeypatch.setattr(team, "_load_team_staff", lambda ids: data["staff"])
    monkeypatch.setattr(team, "_load_team_rows", load_rows)
    monkeypatch.setattr(team, "_load_rd_types", lambda: ("全时研发", "非全时研发", "辅助"))
    return data


KEYS = ["team.headcount", "team.away", "team.away2w", "team.leave", "team.overtime", "alert.team_low_staff", "block.team_calendar",
        "block.team_leave_types", "block.team_people_hours"]


@pytest.mark.parametrize("key", KEYS)
def test_only_someone_with_direct_reports_gets_the_team_blocks(key, state, monkeypatch):
    monkeypatch.setattr(team, "_load_team_detail", lambda ctx: pytest.fail("没有下属的人不能取团队数据"))
    assert run(key, make_ctx(has_reports=False)) is None
    # 角色名不决定：有“部门主管”角色但没有下属的人也没有团队
    assert run(key, make_ctx(has_reports=False, roles=frozenset({"Department Manager"}))) is None


def test_every_team_key_has_a_provider_of_the_right_kind_and_is_in_a_layout():
    for key in KEYS:
        assert key in core.REGISTRY, key
        expected = "alert" if key.startswith("alert.") else "block" if key.startswith("block.") else "kpi"
        assert core.REGISTRY[key].kind == expected, key
        assert key in layout.all_block_keys(), key


def test_headcount_counts_research_staff_and_new_joiners(state):
    kpi = run("team.headcount", make_ctx())
    assert (kpi["value"], kpi["unit"], kpi["sub"]) == ("4", "人", "研发 3 · 本月入职 1")
    assert "汇报关系向下" in kpi["hint"]


def test_away_today_names_who_and_why_and_counts_trips_apart(state):
    kpi = run("team.away", make_ctx())
    assert (kpi["value"], kpi["sub"]) == ("1", "杨员工（年假） · 另有出差 1")
    assert kpi["target"] == {"key": "drill", "params": {"item": "team.away", "period": "2026-10"}}
    state["detail"] = detail([member("张主管"), member("杨员工")])
    assert run("team.away", make_ctx())["sub"] == "全员在岗"
    state["detail"] = detail([member("张主管")], rest_day=True)
    assert run("team.away", make_ctx())["sub"] == "今天休息"
    assert state["calls"]["detail"] >= 1


def test_the_calendar_detail_is_fetched_once_for_all_the_blocks(state):
    ctx = make_ctx()
    for key in ("team.away", "team.away2w", "alert.team_low_staff", "block.team_calendar"):
        run(key, ctx)
    assert state["calls"]["detail"] == 1


def test_away_in_two_weeks_counts_people_with_approved_absence_only(state):
    kpi = run("team.away2w", make_ctx())
    # 杨员工（年假、事假）、演示员工181（病假、年假）、演示员工120（只有事假；调休还在审批、出差不算）
    assert (kpi["value"], kpi["sub"]) == ("3", "10/12 · 10/15 · 10/15")
    state["detail"] = detail([member("张主管")])
    assert run("team.away2w", make_ctx())["sub"] == "两周内没有人请假或调休"


def test_leave_and_overtime_follow_the_selected_month_and_compare_with_the_last_one(state):
    state["rows"] = {
        (2026, 10): [{"request_type": "请假申请", "leave_type": "事假", "duration_hours": 24, "employee_name": "杨员工"},
                     {"request_type": "调休申请", "duration_hours": 8, "employee_name": "杨员工"},
                     {"request_type": "加班申请", "duration_hours": 30, "employee_name": "演示员工120"},
                     {"request_type": "加班申请", "duration_hours": 16, "employee_name": "杨员工"}],
        (2026, 9): [{"request_type": "加班申请", "duration_hours": 41, "employee_name": "演示员工120"}],
    }
    ctx = make_ctx()
    leave = run("team.leave", ctx)
    # 2026-10-13：本月请假按天、只算请假（24 小时 = 3 天），调休单独说
    assert (leave["label"], leave["value"], leave["unit"], leave["sub"]) == ("本月请假", "3", "天", "人均 0.75 天 · 另有调休 1 天")
    assert leave["target"] == {"key": "drill", "params": {"item": "team.leave", "period": "2026-10"}}
    overtime = run("team.overtime", ctx)
    assert (overtime["value"], overtime["sub"]) == ("46", "▲ 12% 较上月")
    assert run("team.leave", make_ctx(period="2026-09", today="2026-10-12"))["label"] == "9 月请假"
    assert state["calls"]["rows"] == 3                                    # 10 月、9 月（上月加班对比）、9 月（换了期间）各取一次，同一期间共用
    state["rows"] = {}
    assert run("team.overtime", make_ctx())["sub"] == "本月没有加班"


def test_low_staff_alert_picks_the_worst_workday_and_names_the_people(state):
    members = [member("张主管")] + [member(f"人{i}", d3=cell("annual")) for i in range(1, 6)] + [member("休息日", d5=cell("annual"))]
    state["detail"] = detail(members, headcount=15)
    item = run("alert.team_low_staff", make_ctx())
    assert item["title"] == "10/15 有 5 人不在岗，占团队 33%" and item["tone"] == "warn"
    assert item["sub"] == "人1、人2、人3、人4等" and item["target"] == {"key": "attendance.home", "params": {}}
    state["detail"] = detail(members, headcount=10)
    assert run("alert.team_low_staff", make_ctx())["tone"] == "bad"      # 占 50%
    state["detail"] = detail([member("张主管"), member("杨员工", d3=cell("annual"))], headcount=15)
    assert run("alert.team_low_staff", make_ctx()) is None                   # 缺 1 人不提醒；周末的格子不算


def test_the_calendar_block_has_names_cells_and_the_present_count(state):
    block = run("block.team_calendar", make_ctx())
    assert block["type"] == "calendar" and block["title"] == "团队日历 · 谁哪天不在" and block["rows"] == []
    assert [person["name"] for person in block["people"]] == ["张主管", "杨员工", "演示员工120", "演示员工181"]
    assert block["people"][1]["cells"][0] == {"kind": "annual", "pending": False}
    assert block["people"][2]["cells"][1] == {"kind": "comp", "pending": True}
    assert block["people"][0]["cells"][0] is None
    assert [day["label"] for day in block["days"]][:2] == ["10/12", "10/13"] and len(block["days"]) == 14
    totals = block["totals"]
    assert totals[0] == {"off": 1, "present": 3}                              # 杨员工年假；演示员工120出差不算不在岗（2026-10-13）
    assert totals[1] == {"off": 0, "present": 4}                              # 调休还在审批：不算不在岗
    assert totals[3] == {"off": 3, "present": 1}
    assert totals[5] == {"off": 0, "present": None}                           # 周末没有在岗人数
    assert block["target"]["key"] == "attendance.home" and "含人名" in block["sub"]


def test_leave_types_stack_uses_the_attendance_center_colours(state):
    state["rows"] = {(2026, 10): [{"request_type": "请假申请", "leave_type": "年假", "duration_hours": 24},
                                  {"request_type": "请假申请", "leave_type": "事假", "duration_hours": 16},
                                  {"request_type": "调休申请", "duration_hours": 20}, {"request_type": "加班申请", "duration_hours": 99}]}
    block = run("block.team_leave_types", make_ctx())
    # 2026-10-13：按天、只有请假；调休不是请假，写在副标题里
    assert [(r["label"], r["value"], r["color"]) for r in block["rows"]] == [("年假", "3 天", "#78c3a2"), ("事假", "2 天", "#8db4ee")]
    assert [r["pct"] for r in block["rows"]] == [60.0, 40.0] and block["sub"] == "天 · 另有调休 2.5 天"
    state["rows"] = {}
    assert run("block.team_leave_types", make_ctx()) is None


def test_people_hours_bars_show_names_leave_and_overtime(state):
    state["rows"] = {(2026, 10): [{"request_type": "请假申请", "leave_type": "事假", "duration_hours": 18, "employee_name": "演示员工130"},
                                  {"request_type": "加班申请", "duration_hours": 4, "employee_name": "演示员工130"},
                                  {"request_type": "请假申请", "leave_type": "年假", "duration_hours": 8, "employee_name": "演示员工147"},
                                  {"request_type": "加班申请", "duration_hours": 12, "employee_name": "演示员工147"}]}
    block = run("block.team_people_hours", make_ctx())
    assert [(r["label"], r["value"], r["pct"]) for r in block["rows"]] == [("演示员工130", "请假 18 · 加班 4", 100.0), ("演示员工147", "请假 8 · 加班 12", 90.9)]
    assert "含人名" in block["sub"]
    many = [{"request_type": "请假申请", "leave_type": "事假", "duration_hours": 8 + i, "employee_name": f"人{i}"} for i in range(12)]
    state["rows"] = {(2026, 10): many}
    assert len(run("block.team_people_hours", make_ctx())["rows"]) == team.MAX_ROWS
