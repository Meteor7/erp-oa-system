"""看板排版规则（决定 2026-10-13）：指标卡张数、首屏顺序、去重、研发并进经营。数字和权限不在这里测。"""
import pytest

from rayher_hr_payroll.dashboard import core, layout

WATCH = ("general_manager", "vice_manager", "finance_manager", "hr_manager")
# 找不到合适的第 4 张卡、宁可少一张也不硬凑的页签（前端按 3 南通工厂8行排）
ALLOWED_SHORT = {("projects", "我负责的项目")}


@pytest.fixture(scope="module", autouse=True)
def providers():
    core.load_providers()


def make_ctx(**kw):
    base = dict(user="u@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-13")
    base.update(kw)
    return core.Ctx(**base)


def all_tabs():
    for profile, spec in layout.LAYOUTS.items():
        for item in spec["tabs"]:
            yield profile, item
    yield "extra", layout.TEAM_TAB
    yield "extra", layout.PROJECT_TAB


def tab_of(profile, key):
    return next(item for item in layout.LAYOUTS[profile]["tabs"] if item["key"] == key)


def test_every_tab_and_section_fills_its_card_rows():
    # 指标卡排满整排：4 南通工厂8排、6 张 3 列 × 2 排、8 张 4 列 × 2 排（列数规则见 frontend/src/lib/dashboardLayout.js）
    for profile, item in all_tabs():
        groups = [(item["label"], item["kpis"])] + [(part["title"], part["kpis"]) for part in item["sections"]]
        for title, kpis in groups:
            if not kpis or (item["key"], title) in ALLOWED_SHORT:
                continue
            assert len(kpis) in (4, 6, 8), (profile, item["key"], title, kpis)
            assert len(kpis) == len(set(kpis)), (profile, item["key"], title)


def test_watch_roles_put_kpis_first_and_working_roles_put_their_todos_first():
    for profile, spec in layout.LAYOUTS.items():
        overview = spec["tabs"][0]
        assert overview["kpis_first"] is (profile in WATCH), profile
        for item in spec["tabs"][1:]:
            assert not item["todos"], (profile, item["key"])


def test_build_tab_tells_the_page_which_comes_first(monkeypatch):
    monkeypatch.setattr(core, "REGISTRY", {})
    ctx = make_ctx()
    assert core.build_tab(ctx, layout.tab("overview", "总览", todos=True), include_todos=False)["kpis_first"] is False
    assert core.build_tab(ctx, layout.tab("overview", "总览", todos=True, kpis_first=True), include_todos=False)["kpis_first"] is True
    # 没有「要我处理」的页签一律先放指标卡
    assert core.build_tab(ctx, layout.tab("team", "团队"), include_todos=False)["kpis_first"] is True


def test_the_dorm_summary_is_only_where_there_is_no_dorm_tab():
    hr = {item["key"]: item for item in layout.LAYOUTS["hr_manager"]["tabs"]}
    assert "block.dorm_summary" not in hr["overview"]["blocks"]
    assert all("block.dorm_summary" not in part["blocks"] for part in hr["people"]["sections"])
    assert "dorm" in hr and hr["dorm"]["kpis"] == ["hr.dorm_rate", "hr.dorm_vacant", "hr.dorm_lease", "hr.dorm_leaver"]
    for profile in ("general_manager", "vice_manager"):
        people = tab_of(profile, "people")
        assert "block.dorm_summary" in people["sections"][0]["blocks"], profile
        assert "dorm" not in [item["key"] for item in layout.LAYOUTS[profile]["tabs"]], profile


def test_people_sections_fill_their_rows():
    for profile in ("hr_manager", "general_manager", "vice_manager"):
        persons, attendance = tab_of(profile, "people")["sections"]
        assert persons["kpis"] == ["hr.active", "hr.joined_left", "hr.left_month", "hr.expiring"], profile
        assert attendance["kpis"] == ["hr.away_today", "att.trip", "att.pending", "att.rate", "att.leave", "att.overtime"], profile


def test_leaders_have_four_tabs_and_rd_is_a_section_of_the_business_tab():
    for profile in ("general_manager", "vice_manager"):
        tabs = layout.LAYOUTS[profile]["tabs"]
        assert [item["key"] for item in tabs] == ["overview", "cost", "proc", "people"], profile
        assert [item["label"] for item in tabs] == ["总览", "经营", "采购", "人事"], profile
        cost = tab_of(profile, "cost")
        assert "block.pay_wait_dist" not in cost["blocks"] and "block.pay_wait_dist" in tabs[0]["blocks"]
        assert len(cost["blocks"]) % 2 == 0, cost["blocks"]
        (rd,) = cost["sections"]
        assert rd["title"] == "研发"
        assert rd["kpis"] == ["ts.rate", "ts.rd_count", "cost.rd_pending", "hr.rd_gap"]
        assert rd["blocks"] == ["block.ts_by_dept", "block.alloc_mix"]


def test_department_manager_cards():
    tabs = {item["key"]: item for item in layout.LAYOUTS["dept_manager"]["tabs"]}
    assert tabs["overview"]["kpis"] == ["me.approvals", "team.away", "team.leave", "ts.team"]
    assert {"team.away2w", "team.overtime"} <= set(tabs["team"]["kpis"]) and len(tabs["team"]["kpis"]) == 4
    assert len(tabs["ts"]["kpis"]) == 4
    assert len(layout.TEAM_TAB["kpis"]) == 4 and "team.away" in layout.TEAM_TAB["kpis"]


def test_accountant_invoice_tab_has_four_cards():
    invoice = tab_of("finance_accountant", "invoice")
    assert invoice["kpis"] == ["invoice.review", "claim.todo", "pay.todo", "me.processed"]


def test_every_attendance_number_on_the_people_tab_has_a_card_that_opens():
    """考勤段 6 张卡（3 列 × 2 排）：本月请假 / 本月加班都有卡片，点进去是各自的明细。"""
    for profile in ("hr_manager", "vice_manager", "general_manager"):
        people_tab = tab_of(profile, "people")
        attendance = next(part for part in people_tab["sections"] if part["title"] == "考勤")
        assert len(attendance["kpis"]) == 6 and {"att.leave", "att.overtime"} <= set(attendance["kpis"])
    for key in ("att.leave", "att.overtime"):
        assert core.REGISTRY[core.DRILL_PREFIX + key].kind == "drill"
