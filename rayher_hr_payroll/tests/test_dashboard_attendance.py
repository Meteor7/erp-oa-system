"""看板人事页的“考勤”一段：只有汇总，没有人名。"""
import json

import pytest

from rayher_hr_payroll.dashboard import attendance, core, layout, people


def make_ctx(**kw):
    base = dict(user="hr@example.com", roles=frozenset({"HR Manager", "Employee"}), positions=frozenset({"hr_manager"}), period="2026-10", today="2026-10-12")
    base.update(kw)
    return core.Ctx(**base)


def run(key, ctx):
    provider = core.REGISTRY[key]
    if provider.visible is not None and not provider.visible(ctx):
        return None
    return provider.fn(ctx)


def summary(trip=2, rate=0.974):
    days = [{"date": f"2026-10-{12 + i:02d}", "label": f"10/{12 + i}", "day": 12 + i, "weekday": "一", "off_day": i in (5, 6, 12, 13),
             "off": (0 if i in (5, 6, 12, 13) else 3 + i % 3)} for i in range(14)]
    return {"stats": {"today": {"off": 4, "trip": trip, "in": 67, "rest_day": False}, "rate": rate, "days": days,
                      "month": {"hours": 232, "per_capita": 3.2, "by_kind": {}}},
            "departments": [{"department": "RD - X", "label": "研发软件部", "headcount": 30, "today_off": 2, "today_trip": 1},
                            {"department": "SV - X", "label": "客服部", "headcount": 8, "today_off": 1, "today_trip": 1},
                            {"department": "HR - X", "label": "人事部", "headcount": 3, "today_off": 1, "today_trip": 0}], "pending": 9}


def waiting_rows(total=9, old=3):
    return [{"name": f"OA-{i}", "request_type": "请假申请" if i % 2 else "加班申请", "employee_name": f"员工{i}", "department": "研发软件部 - RAY",
             "from_date": "2026-10-13", "to_date": "2026-10-14", "duration_hours": 8, "current_step_label": "直属主管", "waited": 5 if i < old else 1}
            for i in range(total)]


def month_rows():
    return [{"request_type": "请假申请", "department": "研发软件部 - RAY", "duration_hours": 16.0}, {"request_type": "请假申请", "department": "客服部 - RAY", "duration_hours": 4.0},
            {"request_type": "请假申请", "department": "研发软件部 - RAY", "duration_hours": 8.0}, {"request_type": "调休申请", "department": "客服部 - RAY", "duration_hours": 8.0},
            {"request_type": "加班申请", "department": "客服部 - RAY", "duration_hours": 12.0}]


@pytest.fixture
def state(monkeypatch):
    data = {"summary": summary(), "waiting": {"total": 9, "old": 3}, "stats": {
        "totals": {"leave_days": 29.0, "leave_count": 20, "overtime_days": 29.5, "comp_days": 6.0},
        "by_type": [{"label": "年假", "days": 12.0}, {"label": "事假", "days": 8.0}],
        "by_department": [{"label": "研发软件部", "leave": 16.0, "overtime": 5.0}, {"label": "客服部", "leave": 0.0, "overtime": 2.0},
                          {"label": "研发算法部", "leave": 9.0, "overtime": 1.0}]}, "calls": {"summary": 0}}

    def load_summary(ctx):
        data["calls"]["summary"] += 1
        return data["summary"]

    monkeypatch.setattr(attendance, "_load_summary", load_summary)
    monkeypatch.setattr(attendance, "_load_waiting", lambda ctx: data["waiting"])
    monkeypatch.setattr(attendance, "_load_waiting_rows", lambda ctx: data["waiting_rows"])
    monkeypatch.setattr(attendance, "_load_month_rows", lambda ctx: data["month_rows"])
    monkeypatch.setattr(people, "_fetch_leave_stats", lambda ctx: data["stats"])
    data["waiting_rows"], data["month_rows"] = waiting_rows(), month_rows()
    return data


KEYS = ["att.trip", "att.pending", "att.leave", "att.overtime", "att.rate", "alert.att_pending", "block.att_depts", "block.att_trend"]


@pytest.mark.parametrize("key", KEYS)
def test_a_user_without_hr_or_leadership_never_reaches_the_company_attendance(key, state, monkeypatch):
    monkeypatch.setattr(attendance, "_load_summary", lambda ctx: pytest.fail("没有权限不能取公司考勤"))
    assert run(key, make_ctx(roles=frozenset({"Department Manager", "Employee"}), positions=frozenset(), has_reports=True)) is None
    assert run(key, make_ctx(roles=frozenset({"Accounts User"}), positions=frozenset({"finance_manager"}))) is None
    assert people._hr_view(make_ctx(roles=frozenset({"Employee"}), positions=frozenset({"vice_manager"})))


def test_every_attendance_key_is_in_a_layout_with_the_right_kind():
    for key in KEYS:
        assert key in core.REGISTRY and key in layout.all_block_keys(), key
        expected = "alert" if key.startswith("alert.") else "block" if key.startswith("block.") else "kpi"
        assert core.REGISTRY[key].kind == expected, key


def test_trip_pending_leave_overtime_and_rate_cards(state):
    ctx = make_ctx()
    assert (run("att.trip", ctx)["value"], run("att.trip", ctx)["sub"]) == ("2", "不算请假，不进出勤率")
    pending = run("att.pending", ctx)
    assert (pending["value"], pending["sub"], pending["tone"]) == ("9", "其中 3 张超过 3 天", "hot")
    leave = run("att.leave", ctx)
    assert (leave["label"], leave["value"], leave["unit"], leave["sub"]) == ("本月请假", "29", "天", "另有调休 6 天")
    assert (run("att.overtime", ctx)["value"], run("att.overtime", ctx)["unit"]) == ("29.5", "天")
    rate = run("att.rate", ctx)
    assert (rate["value"], rate["unit"], rate["tone"], rate["sub"]) == ("97.4", "%", "ok", "未来 14 天 · 10 个工作日")
    assert run("att.rate", make_ctx())["tone"] == "ok" and run("att.rate", make_ctx(), ) is not None
    state["summary"] = summary(rate=0.9)
    assert run("att.rate", make_ctx())["tone"] == "warn"
    state["waiting"] = {"total": 4, "old": 0}
    quiet = run("att.pending", make_ctx())
    assert (quiet["sub"], quiet["tone"]) == ("没有等得久的", "")
    assert run("alert.att_pending", make_ctx()) is None


def test_the_pending_alert_says_how_many_waited_too_long(state):
    item = run("alert.att_pending", make_ctx())
    assert item["title"] == "3 张考勤申请等了超过 3 天" and item["sub"] == "共 9 张在审批中" and item["tone"] == "warn"
    assert item["target"] == {"key": "drill", "params": {"item": "att.pending_old", "period": "2026-10"}}


def test_every_card_opens_a_list_that_adds_up_to_the_number_on_the_card(state):
    """点进去的清单和卡片是同一份数据：条数 / 天数对得上，每一行再进真实的页面。"""
    ctx = make_ctx()

    def open_list(key):
        card = run(key, ctx)
        assert card["target"]["key"] == "drill", key
        detail = core.get_detail_for(ctx, card["target"]["params"]["item"])
        assert detail is not None, key
        return card, detail

    card, detail = open_list("att.pending")
    assert detail["summary"] == "共 9 张" and len(detail["rows"]) == int(card["value"]) == 9
    assert detail["rows"][0]["target"] == {"key": "attendance.detail", "params": {"request": "OA-0"}} and detail["rows"][0]["tone"] == "bad"
    old = core.get_detail_for(ctx, "att.pending_old")
    assert len(old["rows"]) == 3 and old["summary"] == "共 3 张，都等了超过 3 天"
    assert all(row["tone"] == "bad" for row in old["rows"])

    card, detail = open_list("att.leave")
    assert [row["cells"] for row in detail["rows"]] == [["研发软件部", "2 张", "3 天"], ["客服部", "1 张", "0.5 天"]]
    assert detail["summary"] == "共 3 张，合计 3.5 天"
    card, detail = open_list("att.overtime")
    assert [row["cells"] for row in detail["rows"]] == [["客服部", "1 张", "1.5 天"]] and detail["summary"] == "共 1 张，合计 1.5 天"
    card, detail = open_list("att.trip")
    assert [row["cells"] for row in detail["rows"]] == [["客服部", "1 人", "8 人"], ["研发软件部", "1 人", "30 人"]]
    assert detail["summary"] == f"共 {card['value']} 人"
    assert all(row["target"] == {"key": "attendance.home", "params": {}} for row in detail["rows"])


def test_a_card_with_nothing_behind_it_does_not_link_to_an_empty_list(state):
    state["waiting"] = {"total": 0, "old": 0}
    state["summary"] = summary(trip=0)
    state["stats"] = {**state["stats"], "totals": {"leave_days": 0.0, "leave_count": 0, "overtime_days": 0.0, "comp_days": 0.0}}
    ctx = make_ctx()
    for key in ("att.pending", "att.trip", "att.leave", "att.overtime"):
        assert run(key, ctx)["target"] is None, key


def test_the_company_summary_is_fetched_once(state):
    ctx = make_ctx()
    for key in ("att.trip", "att.rate", "block.att_trend"):
        run(key, ctx)
    assert state["calls"]["summary"] == 1


def test_departments_bars_rank_by_leave_days_and_hide_departments_without_leave(state):
    block = run("block.att_depts", make_ctx())
    assert [(r["label"], r["value"], r["pct"]) for r in block["rows"]] == [("研发软件部", "16 天", 100.0), ("研发算法部", "9 天", 56.2)]
    assert "没有人名" in block["sub"] and block["target"]["key"] == "attendance.home"
    state["stats"] = {**state["stats"], "by_department": []}
    assert run("block.att_depts", make_ctx()) is None


def test_the_trend_columns_cover_fourteen_days_and_mark_today(state):
    block = run("block.att_trend", make_ctx())
    assert block["type"] == "cols" and len(block["rows"]) == 14
    assert block["rows"][0]["last"] is True and block["rows"][1]["last"] is False
    assert block["rows"][5]["value"] == "0"                                           # 周末


def test_nothing_in_the_company_attendance_carries_a_person_name(state):
    ctx = make_ctx()
    text = json.dumps([run(key, ctx) for key in KEYS], ensure_ascii=False, default=str)
    for name in ("演示员工130", "演示员工147", "杨员工", "演示员工120"):
        assert name not in text


def test_the_people_tab_has_a_people_and_an_attendance_section():
    for profile in ("hr_manager", "general_manager", "vice_manager"):
        tab = next(item for item in layout.LAYOUTS[profile]["tabs"] if item["key"] == "people")
        assert [section["title"] for section in tab["sections"]] == ["人员", "考勤"], profile
        attendance_section = tab["sections"][1]
        assert {"hr.away_today", "att.pending", "att.leave", "att.overtime", "att.rate", "att.trip"} <= set(attendance_section["kpis"])
        assert {"block.att_depts", "block.att_trend", "block.leave_types"} <= set(attendance_section["blocks"])


def test_sections_are_assembled_and_empty_ones_are_left_out(monkeypatch):
    monkeypatch.setattr(core, "REGISTRY", {})

    @core.provider("a.one", "kpi")
    def _one(ctx):
        return core.kpi("a.one", "一", 1)

    @core.provider("a.none", "kpi")
    def _none(ctx):
        return None

    spec = {"tabs": [layout.tab("overview", "总览", sections=[layout.section("有内容", "副标题", kpis=["a.one"]), layout.section("空的", kpis=["a.none"])])]}
    out = core.assemble(make_ctx(), spec)
    sections = out["pages"]["overview"]["sections"]
    assert [(s["title"], s["sub"], [k["key"] for k in s["kpis"]]) for s in sections] == [("有内容", "副标题", ["a.one"])]
    only = {"tabs": [layout.tab("overview", "总览"), layout.tab("people", "人事", sections=[layout.section("段", kpis=["a.one"])]), layout.tab("none", "空", sections=[layout.section("空", kpis=["a.none"])])]}
    assert [t["key"] for t in core.assemble(make_ctx(), only)["tabs"]] == ["overview", "people"]
