"""看板的“我负责的项目”和多个身份的拼装。"""
import pytest

from rayher_hr_payroll.dashboard import core, layout, projects


def make_ctx(**kw):
    base = dict(user="owner@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-12",
                employee="E1", owns_projects=True)
    base.update(kw)
    return core.Ctx(**base)


def run(key, ctx):
    provider = core.REGISTRY[key]
    if provider.visible is not None and not provider.visible(ctx):
        return None
    return provider.fn(ctx)


def req(name, stage_status, subject="申请", project="RD02", owner="owner@example.com", **extra):
    row = {"name": name, "request_type": "采购申请", "workflow_status": stage_status, "business_status": "", "subject": subject,
           "project": project, "project_owner": owner, "employee_name": "演示员工147", "current_step_label": "", "modified": f"2026-10-{len(name):02d}",
           "procurement_chain": {"stage": "demand"}, "can_approve": False}
    row.update(extra)
    return row


@pytest.fixture
def state(monkeypatch):
    data = {"requests": [
        req("A", "待审批", "伺服电机", current_step_label="项目主管", can_approve=True),
        req("BB", "已完成", "导轨滑块", procurement_chain={"stage": "po"}),
        req("CCC", "已完成", "真空吸盘", project="RD03", procurement_chain={"stage": "closed"}),
        req("DDDD", "已完成", "光学镜头", project="RD03", procurement_chain={"stage": "price"}),
        req("E", "草稿", "草稿不看"), req("FF", "已驳回", "驳回不算"),
        req("G", "待审批", "别人项目的", owner="other@example.com"),
        req("HH", "已完成", "耗材", request_type="购买申请", business_status="待付款", procurement_chain=None, project="RD02"),
        req("III", "已完成", "已付款的", request_type="购买申请", business_status="已付款", procurement_chain=None, project="RD02"),
    ], "projects": [{"name": "RD02", "project_name": "ACONCA 7961", "rd_project_code": "RD02", "status": "Open"},
                    {"name": "RD03", "project_name": "EFEM-8", "rd_project_code": "RD03", "status": "Open"}], "calls": 0}

    def load(ctx):
        data["calls"] += 1
        return data["requests"]

    monkeypatch.setattr(projects, "_load_requests", load)
    monkeypatch.setattr(projects, "_load_projects", lambda ctx: data["projects"])
    return data


KEYS = ["prj.count", "prj.exec", "prj.sign", "block.prj_stage", "block.prj_requests", "block.prj_by_project"]


@pytest.mark.parametrize("key", KEYS)
def test_only_a_project_owner_gets_the_project_blocks(key, state, monkeypatch):
    monkeypatch.setattr(projects, "_load_requests", lambda ctx: pytest.fail("不是项目负责人不能取项目申请"))
    assert run(key, make_ctx(owns_projects=False)) is None


def test_every_project_key_has_a_provider_and_is_in_a_layout():
    for key in KEYS:
        assert key in core.REGISTRY and key in layout.all_block_keys(), key
        expected = "block" if key.startswith("block.") else "kpi"
        assert core.REGISTRY[key].kind == expected, key


def test_stages_ignore_drafts_rejections_and_other_peoples_projects(state):
    assert projects.stage_of(req("a", "待审批")) == "demand"
    assert projects.stage_of(req("a", "已完成", procurement_chain={"stage": "po"})) == "exec"
    assert projects.stage_of(req("a", "已完成", procurement_chain={"stage": "closed"})) == "done"
    assert projects.stage_of(req("a", "已完成", request_type="购买申请", business_status="待付款")) == "exec"
    assert projects.stage_of(req("a", "已完成", request_type="购买申请", business_status="部分付款")) == "exec"
    assert projects.stage_of(req("a", "已完成", request_type="购买申请", business_status="已付款")) == "done"
    assert projects.stage_of(req("a", "草稿")) is None and projects.stage_of(req("a", "已驳回")) is None


def test_the_cards_count_the_owners_requests_by_stage(state):
    ctx = make_ctx()
    count = run("prj.count", ctx)
    assert (count["value"], count["sub"]) == ("2", "共 6 张采购 / 购买申请")
    assert count["target"] == {"key": "procurement.list", "params": {"scope": "owned"}}
    execution = run("prj.exec", ctx)
    assert (execution["value"], execution["sub"]) == ("3", "需求审批中 1 · 已完成 2")
    assert execution["target"]["params"] == {"scope": "owned", "stage": "exec"}
    sign = run("prj.sign", ctx)
    assert (sign["value"], sign["sub"], sign["tone"]) == ("1", "伺服电机", "hot")
    assert state["calls"] == 1, "几个块共用一次取数"


def test_nothing_waits_for_the_owner_when_no_request_needs_the_signature(state):
    state["requests"][0]["can_approve"] = False
    sign = run("prj.sign", make_ctx())
    assert (sign["value"], sign["sub"], sign["tone"]) == ("0", "没有要你会签的", "")


def test_the_stage_stack_and_project_bars(state):
    ctx = make_ctx()
    block = run("block.prj_stage", ctx)
    assert [(r["label"], r["value"]) for r in block["rows"]] == [("需求审批", "1 张"), ("采购执行", "3 张"), ("已完成", "2 张")]
    assert block["sub"] == "共 6 张"
    by_project = run("block.prj_by_project", ctx)
    assert [(r["label"], r["value"]) for r in by_project["rows"]] == [("RD02 · ACONCA 7961", "4 张 · 执行中 2"), ("RD03 · EFEM-8", "2 张 · 执行中 1")]
    assert by_project["rows"][0]["pct"] == 100.0


def test_the_recent_requests_list_links_to_the_read_only_detail(state):
    block = run("block.prj_requests", make_ctx())
    assert len(block["rows"]) == projects.MAX_ROWS
    first = block["rows"][0]
    assert first["target"]["key"] == "procurement.detail" and first["target"]["params"]["request"]
    waiting = next(row for row in block["rows"] if row["label"] == "伺服电机")
    assert waiting["sub"] == "演示员工147 · RD02 · ACONCA 7961 · 在 项目主管" and waiting["value"] == "需求审批" and waiting["tone"] == "warn"
    assert block["sub"] == "只读"


# ---------------------------------------------------------------- 多个身份拼装
def ctx_for(profile, **kw):
    ctx = make_ctx(**kw)
    ctx.profile = profile
    return ctx


def tab_keys(spec):
    return [item["key"] for item in spec["tabs"]]


def test_a_department_manager_who_owns_projects_gets_both_without_losing_either():
    spec = layout.layout_for(ctx_for("dept_manager", has_reports=True))
    assert tab_keys(spec) == ["overview", "team", "ts", "projects"]
    overview = spec["tabs"][0]
    assert "block.team_calendar" in overview["blocks"] and overview["todos"] is True


def test_an_employee_who_owns_projects_gets_a_project_tab_only():
    assert tab_keys(layout.layout_for(ctx_for("employee"))) == ["overview", "projects"]
    assert tab_keys(layout.layout_for(ctx_for("employee", owns_projects=False))) == ["overview"]


def test_other_managers_with_reports_get_the_team_tab_added():
    for profile in ("production_asset_owner", "finance_manager", "procurement_manager", "pmc", "finance_accountant", "employee"):
        spec = layout.layout_for(ctx_for(profile, has_reports=True, owns_projects=False))
        assert tab_keys(spec)[-1] == "team", profile
    for profile in ("general_manager", "vice_manager", "hr_manager", "dept_manager"):
        keys = tab_keys(layout.layout_for(ctx_for(profile, has_reports=True, owns_projects=False)))
        assert keys.count("team") == (1 if profile == "dept_manager" else 0), profile


def test_the_layout_is_never_mutated_by_composing():
    before = tab_keys(layout.LAYOUTS["employee"])
    layout.layout_for(ctx_for("employee", has_reports=True))
    assert tab_keys(layout.LAYOUTS["employee"]) == before


def test_get_home_composes_the_layout_and_keys_the_cache_by_identity(monkeypatch, state):
    monkeypatch.setattr(core, "REGISTRY", dict(core.REGISTRY))
    store = {}
    put = lambda k, v, ttl: store.__setitem__(k, v)
    first = core.get_home_for(make_ctx(has_reports=False), None, cache_get=store.get, cache_set=put)
    second = core.get_home_for(make_ctx(has_reports=True), None, cache_get=store.get, cache_set=put)
    assert len(store) == 2
    assert "projects" in [t["key"] for t in first["tabs"]]
    assert first["role"]["key"] == "employee" or first["role"]["key"] == "dept_manager"
    assert second["role"]["key"] == "dept_manager"
