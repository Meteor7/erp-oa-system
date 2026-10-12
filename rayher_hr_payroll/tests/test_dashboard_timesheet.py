import json

import pytest

from rayher_hr_payroll.dashboard import core, layout, timesheet


def make_ctx(**kw):
    base = dict(user="u@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-09",
                employee="E0", department="研发软件部 - RAY")
    base.update(kw)
    return core.Ctx(**base)


def run(key, ctx):
    """和 core._run 一样：先看 visible，再调用块。"""
    provider = core.REGISTRY[key]
    if provider.visible is not None and not provider.visible(ctx):
        return None
    return provider.fn(ctx)


def person(name, department, status, used, limit=20):
    return {"employee": name, "employee_name": name, "department": department, "used_days": used, "limit_days": limit, "status": status}


def fill(kind="all", employees=None, can_remind=True, deadline="2026-10-31"):
    employees = employees if employees is not None else [
        person("演示员工181", "研发一部", "full", 20), person("演示员工149", "研发一部", "part", 12.5),
        person("演示员工185", "研发二部", "none", 0), person("演示员工119", "研发二部", "over", 21),
    ]
    counts = {key: sum(1 for e in employees if e["status"] == key) for key in ("full", "part", "none", "over")}
    total = len(employees)
    return {"period": "2026-10", "kind": kind, "can_remind": can_remind, "deadline": deadline, "employees": employees,
            "summary": {"total": total, **counts, "rate": round(counts["full"] / total * 100, 1) if total else 0}}


@pytest.fixture
def calls(monkeypatch):
    log = {"fill": 0, "entries": 0}
    state = {"fill": fill(), "entries": {"entries": []}}

    def load_fill(period):
        log["fill"] += 1
        return state["fill"]

    def load_entries(period):
        log["entries"] += 1
        return state["entries"]

    monkeypatch.setattr(timesheet, "_load_fill", load_fill)
    monkeypatch.setattr(timesheet, "_load_entries", load_entries)
    monkeypatch.setattr(timesheet, "_load_rd_headcount", lambda: 52)
    log["state"] = state
    return log


HR = frozenset({"HR Manager", "Employee"})
FINANCE = frozenset({"Accounts User", "Employee"})
DEPT_MANAGER = frozenset({"Department Manager", "Employee"})


# ---------------------------------------------------------------- 权限
FILL_KEYS = ["ts.rate", "ts.rd_count", "ts.team", "ts.none", "alert.ts_open", "alert.ts_open_team", "block.ts_by_dept", "block.ts_team",
             "block.ts_projects", "block.ts_trend", "dept.projects"]


@pytest.mark.parametrize("key", FILL_KEYS)
def test_plain_employee_never_reaches_the_fill_progress_blocks(key, calls):
    ctx = make_ctx()
    assert run(key, ctx) is None
    assert calls["fill"] == 0, "没有权限的人不能调用底层接口"


@pytest.mark.parametrize("roles", [HR, FINANCE, DEPT_MANAGER, frozenset({"System Manager"}), frozenset({"HR User"})])
def test_fill_progress_roles_match_the_underlying_api(roles):
    assert timesheet._fill_visible(make_ctx(roles=roles))


def test_every_timesheet_key_in_the_layout_has_a_provider():
    mine = {key for key in layout.all_block_keys() if key.startswith(("ts.", "dept.", "alert.ts_", "block.ts_"))}
    assert mine == set(FILL_KEYS)
    for key in mine:
        assert key in core.REGISTRY, key
        expected = "alert" if key.startswith("alert.") else "block" if key.startswith("block.") else "kpi"
        assert core.REGISTRY[key].kind == expected, key


# ---------------------------------------------------------------- 工时填报
def test_rate_for_the_whole_company_and_one_call_is_shared(calls):
    ctx = make_ctx(roles=HR)
    rate = run("ts.rate", ctx)
    assert (rate["label"], rate["value"], rate["unit"], rate["sub"], rate["tone"]) == ("工时填报率", "25", "%", "1 / 4 人已填满", "hot")
    assert rate["target"] == {"key": "timesheet.board", "params": {"period": "2026-10"}}
    assert run("ts.none", ctx)["value"] == "1" and run("ts.team", ctx)["value"] == "1 / 4"
    assert calls["fill"] == 1, "几个块共用同一次 get_fill_progress"


def test_rate_for_a_department_head_is_labelled_as_the_team(calls):
    calls["state"]["fill"] = fill("team", [person("演示员工181", "研发一部", "full", 20), person("演示员工149", "研发一部", "part", 12.5)])
    ctx = make_ctx(roles=DEPT_MANAGER)
    assert run("ts.rate", ctx)["label"] == "团队工时填报率"
    team = run("ts.team", ctx)
    assert (team["label"], team["value"], team["sub"], team["tone"]) == ("团队工时已填满", "1 / 2", "1 人没填满", "hot")
    assert team["target"]["params"] == {"status": "open", "period": "2026-10"}
    assert "汇报关系" in team["hint"]


def test_nothing_to_show_when_the_list_is_empty_or_the_user_only_sees_themselves(calls):
    calls["state"]["fill"] = fill("team", [])
    ctx = make_ctx(roles=DEPT_MANAGER)
    for key in ("ts.rate", "ts.team", "ts.none", "alert.ts_open_team", "block.ts_team", "block.ts_projects", "dept.projects"):
        assert run(key, ctx) is None, key
    calls["state"]["fill"] = fill("self", [])
    assert run("ts.rate", make_ctx(roles=HR)) is None


def test_everyone_filled_is_ok_and_no_alert(calls):
    calls["state"]["fill"] = fill("all", [person("演示员工181", "研发一部", "full", 20), person("演示员工149", "研发一部", "full", 20)])
    ctx = make_ctx(roles=HR)
    assert run("ts.rate", ctx)["tone"] == "ok" and run("ts.rate", ctx)["value"] == "100"
    team = run("ts.team", ctx)
    assert team["sub"] == "全部已填满" and team["tone"] == "ok" and team["target"]["params"] == {"period": "2026-10"}
    none = run("ts.none", ctx)
    assert none["value"] == "0" and none["tone"] == "ok" and none["sub"] == "都已开始填报"
    assert run("alert.ts_open", ctx) is None


def test_rd_count_explains_the_two_numbers(calls):
    kpi = run("ts.rd_count", make_ctx(roles=HR))
    # 数字 = 点进去填报进度里的名单人数（本月要填工时的人）；档案里的研发在册人数放在副标题里，两个数不同的原因一并写明
    assert (kpi["label"], kpi["value"], kpi["sub"]) == ("需要填工时的人", "4", "研发在册 52 人，其余免填或不在名单")
    assert "免填" in kpi["hint"] and "研发" in kpi["hint"]
    calls["state"]["fill"] = fill("team")
    assert run("ts.rd_count", make_ctx(roles=DEPT_MANAGER)) is None        # 部门主管只看得到团队，不报全公司在册人数


def test_open_alert_counts_part_and_none_and_goes_red_after_the_deadline(calls):
    ctx = make_ctx(roles=HR)
    item = run("alert.ts_open", ctx)
    assert item["title"] == "2 人本月工时没填满，1 人一点没填" and item["tone"] == "warn"
    assert item["sub"] == "截止 10-31，可以催办"
    assert item["target"] == {"key": "timesheet.board", "params": {"status": "open", "period": "2026-10"}}
    late = run("alert.ts_open", make_ctx(roles=HR, today="2026-11-02"))
    assert late["tone"] == "bad" and "已过截止" in late["sub"]
    assert run("alert.ts_open", make_ctx(roles=HR, period="2026-11")) is None          # 还没到的月份不提醒
    assert run("alert.ts_open_team", ctx)["title"].startswith("全公司 ")               # 看全公司的人用团队提醒时要写明范围


def test_open_alert_for_a_team_does_not_leak_into_the_company_alert(calls):
    calls["state"]["fill"] = fill("team", [person("演示员工149", "研发一部", "part", 12.5)], can_remind=False)
    ctx = make_ctx(roles=DEPT_MANAGER)
    assert run("alert.ts_open", ctx) is None
    item = run("alert.ts_open_team", ctx)
    assert item["title"] == "1 人本月工时没填满" and item["sub"] == "截止 10-31"


def test_by_department_puts_the_least_filled_first_and_caps_the_rows(calls):
    employees = []
    for index in range(10):
        employees.append(person(f"A{index}", f"部门{index}", "full" if index % 2 else "none", 20))
    calls["state"]["fill"] = fill("all", employees + [person("无部门", "", "part", 3)])
    block = run("block.ts_by_dept", make_ctx(roles=HR))
    assert block["type"] == "bars" and len(block["rows"]) == timesheet.MAX_ROWS
    assert block["rows"][0]["tone"] == "bad" and block["rows"][0]["value"].endswith("/ 1")
    assert "只列最需要跟进的" in block["sub"] and block["more"] == "填报进度"
    small = fill("all")
    calls["state"]["fill"] = small
    rows = run("block.ts_by_dept", make_ctx(roles=HR))["rows"]
    assert [(r["label"], r["value"], r["pct"], r["tone"]) for r in rows] == [("研发二部", "0 / 2", 0.0, "bad"), ("研发一部", "1 / 2", 50.0, "warn")]
    calls["state"]["fill"] = fill("team")
    assert run("block.ts_by_dept", make_ctx(roles=DEPT_MANAGER)) is None             # 团队范围没有"各部门"可比


def test_team_block_lists_people_who_still_owe_hours_first(calls):
    ctx = make_ctx(roles=DEPT_MANAGER)
    calls["state"]["fill"] = fill("team")
    block = run("block.ts_team", ctx)
    assert block["title"] == "团队工时填报进度"
    assert [(r["label"], r["value"], r["tone"]) for r in block["rows"]] == [
        ("演示员工185", "0 / 20", "bad"), ("演示员工149", "12.5 / 20", "warn"), ("演示员工119", "21 / 20", "warn"), ("演示员工181", "20 / 20", "ok")]
    assert [r["pct"] for r in block["rows"]] == [0.0, 62.5, 100, 100]
    assert block["target"]["key"] == "timesheet.board"


def test_projects_block_and_kpi_sum_hours_per_project(calls):
    calls["state"]["fill"] = fill("team")
    entries = [{"project": f"P{i}", "project_name": f"项目{i}", "project_code": f"C{i}", "hours": 100 - i * 10} for i in range(7)]
    entries.append({"project": "P0", "project_name": "项目0", "hours": 12.5})
    calls["state"]["entries"] = {"entries": entries}
    ctx = make_ctx(roles=DEPT_MANAGER)
    block = run("block.ts_projects", ctx)
    assert [r["label"] for r in block["rows"]] == ["项目0", "项目1", "项目2", "项目3", "项目4", "其他 2 个"]
    assert block["rows"][0]["value"] == "112.5" and block["rows"][0]["pct"] == 100
    assert block["rows"][-1]["value"] == "90"
    kpi = run("dept.projects", ctx)
    assert (kpi["value"], kpi["sub"]) == ("7", "最多的是 项目0")
    assert calls["entries"] == 1
    calls["state"]["entries"] = {"entries": []}
    ctx = make_ctx(roles=DEPT_MANAGER)
    assert run("block.ts_projects", ctx) is None
    assert run("dept.projects", ctx)["sub"] == "本月还没有工时记录"


# ---------------------------------------------------------------- 近 6 个月填报率
def test_trend_block_is_only_for_a_team_and_takes_the_rate_month_by_month(calls, monkeypatch):
    team_summary = lambda rate, total: {**fill("team", [person("演示员工181", "研发一部", "full", 20)]), "summary": {"total": total, "full": 1, "part": 0, "none": 0, "over": 0, "rate": rate}}
    months = {"2026-10": team_summary(78, 15), "2026-09": team_summary(97, 15), "2026-08": team_summary(99, 15),
              "2026-07": team_summary(94, 15), "2026-06": team_summary(96, 15), "2026-05": team_summary(92, 15)}
    calls["state"]["fill"] = months["2026-10"]
    monkeypatch.setattr(timesheet, "_load_fill", lambda period: months[period])
    block = run("block.ts_trend", make_ctx(roles=DEPT_MANAGER))
    assert block["type"] == "cols" and [r["label"] for r in block["rows"]] == ["5月", "6月", "7月", "8月", "9月", "10月"]
    assert [r["value"] for r in block["rows"]] == ["92%", "96%", "94%", "99%", "97%", "78%"]
    assert block["rows"][-1]["last"] is True and block["rows"][0]["last"] is False
    assert timesheet._trend_periods("2026-02") == ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"]


def test_trend_block_is_not_built_for_the_whole_company(calls):
    # 看全公司的人不做这一块（逐月取全公司进度太重，也不是他们要的）
    calls["state"]["fill"] = fill("all")
    assert run("block.ts_trend", make_ctx(roles=HR)) is None


def test_trend_block_is_left_out_when_no_month_has_a_team_list(calls):
    calls["state"]["fill"] = fill("team", [])
    assert run("block.ts_trend", make_ctx(roles=DEPT_MANAGER)) is None


# ---------------------------------------------------------------- 取数函数确实接到了现有接口
def test_loaders_call_the_real_apis(monkeypatch):
    import frappe
    from rayher_hr_payroll.api import monthly_timesheet_entry, overview_entry, timesheet_entry

    seen = {}
    monkeypatch.setattr(monthly_timesheet_entry, "get_fill_progress", lambda period: {"kind": "all", "period": period})
    assert timesheet._load_fill("2026-10") == {"kind": "all", "period": "2026-10"}
    monkeypatch.setattr(monthly_timesheet_entry, "list_monthly_entries", lambda period, employee=None: {"entries": [], "period": period})
    assert timesheet._load_entries("2026-10")["period"] == "2026-10"
    def count(doctype, filters):
        seen["count"] = (doctype, filters)
        return 52

    monkeypatch.setattr(frappe, "db", type("DB", (), {"count": staticmethod(count)}), raising=False)
    assert timesheet._load_rd_headcount() == 52
    assert seen["count"] == ("Employee", {"status": "Active", "rd_personnel_type": ["in", list(timesheet_entry.RD_TYPES)]})
