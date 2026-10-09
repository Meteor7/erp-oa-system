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
             "block.ts_projects", "dept.projects"]
DEPT_KEYS = ["dept.away2w", "dept.active", "dept.overtime", "dept.leave", "alert.dept_attendance"]


@pytest.mark.parametrize("key", FILL_KEYS)
def test_plain_employee_never_reaches_the_fill_progress_blocks(key, calls):
    ctx = make_ctx()
    assert run(key, ctx) is None
    assert calls["fill"] == 0, "没有权限的人不能调用底层接口"


@pytest.mark.parametrize("roles", [HR, FINANCE, DEPT_MANAGER, frozenset({"System Manager"}), frozenset({"HR User"})])
def test_fill_progress_roles_match_the_underlying_api(roles):
    assert timesheet._fill_visible(make_ctx(roles=roles))


@pytest.mark.parametrize("key", DEPT_KEYS)
def test_department_blocks_follow_hr_scope(key, monkeypatch):
    monkeypatch.setattr(timesheet, "_load_absence_rows", lambda *a: pytest.fail("无权限不能取数"))
    monkeypatch.setattr(timesheet, "_load_department_staff", lambda *a: pytest.fail("无权限不能取数"))
    monkeypatch.setattr(timesheet, "_load_attendance_rows", lambda *a: pytest.fail("无权限不能取数"))
    assert run(key, make_ctx()) is None                                                  # 纯员工
    assert run(key, make_ctx(roles=DEPT_MANAGER, department="")) is None                 # 没有所属部门，不知道看谁
    assert run(key, make_ctx(roles=FINANCE)) is None                                    # 财务角色不是 hr_scope 的一部分
    for ctx in (make_ctx(roles=DEPT_MANAGER), make_ctx(roles=HR), make_ctx(positions=frozenset({"vice_manager"}))):
        assert timesheet._dept_visible(ctx)


def test_every_timesheet_and_department_key_in_the_layout_has_a_provider():
    mine = {key for key in layout.all_block_keys() if key.startswith(("ts.", "dept.", "alert.ts_", "alert.dept_", "block.ts_"))}
    assert mine == set(FILL_KEYS + DEPT_KEYS)
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
    assert run("ts.rate", ctx)["label"] == "本部门工时填报率"
    team = run("ts.team", ctx)
    assert (team["label"], team["value"], team["sub"], team["tone"]) == ("本部门工时已填满", "1 / 2", "1 人没填满", "hot")
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
    assert (kpi["value"], kpi["sub"]) == ("52", "填工时 4 人")
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
    assert block["title"] == "本部门工时填报进度"
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


# ---------------------------------------------------------------- 部门
def absence(employee, name, days, kind="请假申请"):
    return {"employee": employee, "employee_name": name, "request_type": kind, "from_date": days[0], "to_date": days[-1],
            "attendance_days": json.dumps([{"work_date": day, "hours": 8} for day in days])}


@pytest.fixture
def dept(monkeypatch):
    state = {"absence": [], "staff": [], "att": {}}
    seen = []

    def load_absence(department, start, end):
        seen.append((department, str(start), str(end)))
        return state["absence"]

    monkeypatch.setattr(timesheet, "_load_absence_rows", load_absence)
    monkeypatch.setattr(timesheet, "_load_department_staff", lambda department: state["staff"])
    monkeypatch.setattr(timesheet, "_load_attendance_rows", lambda year, month, department: state["att"].get((year, month), []))
    state["seen"] = seen
    return state


def test_away_in_two_weeks_counts_people_not_requests_and_ignores_days_outside_the_window(dept):
    dept["absence"] = [
        absence("E1", "演示员工129", ["2026-10-12", "2026-10-13"]), absence("E1", "演示员工129", ["2026-10-15"], "调休申请"),
        absence("E2", "演示员工146", ["2026-10-09"]), absence("E3", "演示员工157", ["2026-10-26"]),
    ]
    kpi = run("dept.away2w", make_ctx(roles=DEPT_MANAGER))
    assert (kpi["value"], kpi["unit"], kpi["sub"]) == ("2", "人", "10-09 · 10-12")
    assert dept["seen"] == [("研发软件部 - RAY", "2026-10-09", "2026-10-22")]
    assert kpi["target"] == {"key": "attendance.home", "params": {}}
    dept["absence"] = []
    assert run("dept.away2w", make_ctx(roles=DEPT_MANAGER))["sub"] == "两周内没有人请假或调休"


def test_attendance_alert_needs_two_people_off_tomorrow(dept):
    ctx = make_ctx(roles=DEPT_MANAGER)
    dept["absence"] = [absence("E1", "演示员工129", ["2026-10-10"]), absence("E2", "演示员工146", ["2026-10-10", "2026-10-12"])]
    run("dept.away2w", ctx)
    item = run("alert.dept_attendance", ctx)
    assert item["title"] == "10-10 有 2 人请假或调休" and item["sub"] == "演示员工129、演示员工146" and item["tone"] == "info"
    assert len(dept["seen"]) == 1, "和 dept.away2w 共用一次查询"
    dept["absence"] = [absence("E1", "演示员工129", ["2026-10-10"]), absence("E2", "演示员工146", ["2026-10-12"])]
    assert run("alert.dept_attendance", make_ctx(roles=DEPT_MANAGER)) is None


def test_department_headcount_and_new_joiners(dept):
    dept["staff"] = [{"name": "E1", "date_of_joining": "2026-10-05"}, {"name": "E2", "date_of_joining": "2024-01-02"}, {"name": "E3", "date_of_joining": None}]
    kpi = run("dept.active", make_ctx(roles=DEPT_MANAGER))
    assert (kpi["value"], kpi["sub"]) == ("3", "本月入职 1")
    assert kpi["target"] is None, "部门主管打不开员工信息页，不给跳转"
    assert run("dept.active", make_ctx(roles=HR))["target"] == {"key": "personnel.list", "params": {"status": "active"}}
    dept["staff"] = [{"name": "E2", "date_of_joining": "2024-01-02"}]
    assert run("dept.active", make_ctx(roles=DEPT_MANAGER))["sub"] == "本月无人入职"


def test_overtime_in_hours_with_change_against_last_month_and_leave_in_days(dept):
    dept["att"] = {
        (2026, 10): [{"request_type": "加班申请", "duration_hours": 30}, {"request_type": "加班申请", "duration_hours": 16},
                     {"request_type": "请假申请", "leave_type": "事假", "duration_hours": 40}, {"request_type": "请假申请", "leave_type": "年假", "duration_hours": 36},
                     {"request_type": "调休申请", "duration_hours": 8}],
        (2026, 9): [{"request_type": "加班申请", "duration_hours": 41}],
    }
    ctx = make_ctx(roles=DEPT_MANAGER)
    overtime = run("dept.overtime", ctx)
    assert (overtime["label"], overtime["value"], overtime["unit"], overtime["sub"]) == ("本月加班", "46", "小时", "▲ 12% 较上月")
    leave = run("dept.leave", ctx)
    assert (leave["value"], leave["unit"], leave["sub"]) == ("9.5", "天", "事假 5 · 年假 4.5")
    assert "不含调休" in leave["hint"] and "汇报关系" in leave["hint"]


def test_overtime_and_leave_when_there_is_nothing_and_in_january(dept):
    ctx = make_ctx(roles=DEPT_MANAGER, period="2026-01", today="2026-01-15")
    assert run("dept.overtime", ctx)["sub"] == "本月没有加班"
    assert run("dept.leave", ctx)["sub"] == "本月没有请假" and run("dept.leave", ctx)["value"] == "0"
    dept["att"] = {(2025, 12): [{"request_type": "加班申请", "duration_hours": 10}]}
    assert run("dept.overtime", make_ctx(roles=DEPT_MANAGER, period="2026-01", today="2026-01-15"))["sub"] == "▼ 100% 较上月"
    assert timesheet._prev_period("2026-01") == (2025, 12) and timesheet._prev_period("2026-10") == (2026, 9)
    assert run("dept.overtime", make_ctx(roles=DEPT_MANAGER, period="2026-09", today="2026-10-09"))["label"] == "9 月加班"


# ---------------------------------------------------------------- 取数函数确实接到了现有接口
def test_loaders_call_the_real_apis(monkeypatch):
    import frappe
    from rayher_hr_payroll.api import monthly_timesheet_entry, overview_entry, timesheet_entry

    seen = {}
    monkeypatch.setattr(monthly_timesheet_entry, "get_fill_progress", lambda period: {"kind": "all", "period": period})
    assert timesheet._load_fill("2026-10") == {"kind": "all", "period": "2026-10"}
    monkeypatch.setattr(monthly_timesheet_entry, "list_monthly_entries", lambda period, employee=None: {"entries": [], "period": period})
    assert timesheet._load_entries("2026-10")["period"] == "2026-10"
    monkeypatch.setattr(overview_entry, "_attendance_rows", lambda months, department=None: seen.update(att=(months, department)) or [])
    timesheet._load_attendance_rows(2026, 10, "研发部 - RAY")
    assert seen["att"] == ([(2026, 10)], "研发部 - RAY")

    def count(doctype, filters):
        seen["count"] = (doctype, filters)
        return 52

    monkeypatch.setattr(frappe, "db", type("DB", (), {"count": staticmethod(count)}), raising=False)
    assert timesheet._load_rd_headcount() == 52
    assert seen["count"] == ("Employee", {"status": "Active", "rd_personnel_type": ["in", list(timesheet_entry.RD_TYPES)]})

    def get_all(doctype, **kw):
        seen.setdefault("all", []).append((doctype, kw))
        return []

    monkeypatch.setattr(frappe, "get_all", get_all, raising=False)
    timesheet._load_absence_rows("研发部 - RAY", "2026-10-09", "2026-10-22")
    timesheet._load_department_staff("研发部 - RAY")
    (doctype, kw), (staff_doctype, staff_kw) = seen["all"]
    assert doctype == "OA Approval Request" and kw["filters"]["department"] == "研发部 - RAY"
    assert kw["filters"]["request_type"] == ["in", ["请假申请", "调休申请"]] and kw["filters"]["workflow_status"] == ["in", ["已完成", "已通过"]]
    assert kw["filters"]["from_date"] == ["<=", "2026-10-22"] and kw["filters"]["to_date"] == [">=", "2026-10-09"]
    assert staff_doctype == "Employee" and staff_kw["filters"] == {"status": "Active", "department": "研发部 - RAY"}
