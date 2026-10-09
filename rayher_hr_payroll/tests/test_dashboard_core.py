import json

import pytest

from rayher_hr_payroll.dashboard import core, layout


def make_ctx(**kw):
    base = dict(user="u@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-09")
    base.update(kw)
    return core.Ctx(**base)


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(core, "REGISTRY", {})
    return core.REGISTRY


# ---------------------------------------------------------------- targets
def test_targets_file_is_well_formed():
    targets = core.load_targets()
    assert len(targets) > 30
    for key, spec in targets.items():
        assert spec["path"].startswith("/"), key
        assert isinstance(spec["query"], dict) and isinstance(spec["params"], list), key
        assert not (set(spec["query"]) & set(spec["params"])), f"{key}: a fixed query key is also a free param"
        assert spec["label"], key


def test_target_validates_key_and_params():
    assert core.target("payment.unpaid") == {"key": "payment.unpaid", "params": {}}
    assert core.target("payment.detail", request="OA-1") == {"key": "payment.detail", "params": {"request": "OA-1"}}
    assert core.target("payroll", period="2026-10", status=None) == {"key": "payroll", "params": {"period": "2026-10"}}
    with pytest.raises(core.DashboardError):
        core.target("no.such.target")
    with pytest.raises(core.DashboardError):
        core.target("payment.unpaid", request="OA-1")


def test_builders_only_accept_real_targets():
    assert core.kpi("k", "待付款", "128.6", "万", to=core.target("payment.unpaid"))["target"]["key"] == "payment.unpaid"
    with pytest.raises(core.DashboardError):
        core.kpi("k", "x", "1", to={"key": "nope", "params": {}})
    with pytest.raises(core.DashboardError):
        core.alert("a", "bad", "t", to={"key": "payment.unpaid", "params": {"junk": "1"}})
    assert core.kpi("k", "x", 5)["value"] == "5" and core.kpi("k", "x", 5)["target"] is None


def test_money_wan():
    assert core.money_wan(1286400) == ("128.6", "万")
    assert core.money_wan(9800) == ("9,800", "元")
    assert core.money_wan(None) == ("0", "元")


# ---------------------------------------------------------------- layout
def test_layout_keys_are_well_named_and_every_profile_has_an_overview():
    assert set(layout.LAYOUTS) == set(core.PROFILE_LABELS)
    for profile, spec in layout.LAYOUTS.items():
        assert spec["tabs"][0]["key"] == "overview", profile
        assert spec["tabs"][0]["todos"] is True, profile
        keys = [t["key"] for t in spec["tabs"]]
        assert len(keys) == len(set(keys)), profile
        for t in spec["tabs"]:
            assert not any(k.startswith(("alert.", "block.", "todo.")) for k in t["kpis"]), (profile, t["key"])
            assert all(k.startswith("alert.") for k in t["alerts"]), (profile, t["key"])
            assert all(k.startswith("block.") for k in t["blocks"]), (profile, t["key"])


def test_pmc_layout_has_no_money_blocks():
    keys = set()
    for t in layout.LAYOUTS["pmc"]["tabs"]:
        keys.update(t["kpis"] + t["alerts"] + t["blocks"])
    assert not {k for k in keys if k.startswith(("pay.", "cost.")) or k in ("proc.month_amount", "block.proc_suppliers", "block.proc_projects", "block.labor_cost")}


# ---------------------------------------------------------------- profile
def test_profile_priority_and_fallbacks():
    assert core.resolve_profile(make_ctx(positions=frozenset({"vice_manager", "finance_manager"}))) == "vice_manager"
    assert core.resolve_profile(make_ctx(positions=frozenset({"hr_manager"}), has_reports=True)) == "hr_manager"
    assert core.resolve_profile(make_ctx(roles=frozenset({"System Manager"}))) == "general_manager"
    assert core.resolve_profile(make_ctx(has_reports=True)) == "dept_manager"
    assert core.resolve_profile(make_ctx()) == "employee"
    assert core.resolve_profile(make_ctx(positions=frozenset({"pmc", "production_asset_owner"}))) == "pmc"


# ---------------------------------------------------------------- assemble
def test_hidden_and_empty_blocks_are_left_out_and_failures_are_isolated(registry):
    @core.provider("a.visible", "kpi")
    def _a(ctx):
        return core.kpi("a.visible", "可见", 1)

    @core.provider("a.hidden", "kpi", visible=lambda ctx: False)
    def _b(ctx):
        raise AssertionError("a hidden provider must not run")

    @core.provider("a.none", "kpi")
    def _c(ctx):
        return None

    @core.provider("a.boom", "kpi")
    def _d(ctx):
        raise RuntimeError("坏了")

    @core.provider("block.ok", "block", title="好")
    def _e(ctx):
        return core.bars("block.ok", "好", [core.bar_row("x", 1, 50)])

    @core.provider("block.boom", "block", title="会坏的块")
    def _f(ctx):
        raise RuntimeError("坏了")

    spec = {"note": "n", "tabs": [layout.tab("overview", "总览", kpis=["a.visible", "a.hidden", "a.none", "a.boom"], blocks=["block.ok", "block.boom"]),
                                  layout.tab("empty", "空的", kpis=["a.none"])]}
    out = core.assemble(make_ctx(profile="employee", full_name="演示员工186"), spec)
    page = out["pages"]["overview"]
    assert [k["key"] for k in page["kpis"]] == ["a.visible"]
    assert [b["key"] for b in page["blocks"]] == ["block.ok", "block.boom"]
    assert page["blocks"][1]["error"] and page["blocks"][1]["rows"] == [] and page["blocks"][1]["title"] == "会坏的块"
    assert [e["key"] for e in page["errors"]] == ["a.boom", "block.boom"]
    assert [t["key"] for t in out["tabs"]] == ["overview"]          # 空页签不给
    assert out["role"]["label"] == "员工" and out["role"]["person"] == "演示员工186" and out["period"] == "2026-10"


def test_kind_mismatch_is_ignored(registry):
    @core.provider("alert.x", "alert")
    def _a(ctx):
        return core.alert("alert.x", "warn", "t")

    spec = {"tabs": [layout.tab("overview", "总览", kpis=["alert.x"])]}
    assert core.assemble(make_ctx(), spec)["pages"]["overview"]["kpis"] == []


# ---------------------------------------------------------------- cache + todos
def test_cache_keeps_everything_except_todos(registry):
    calls = {"kpi": 0, "todo": 0}

    @core.provider("k.one", "kpi")
    def _k(ctx):
        calls["kpi"] += 1
        return core.kpi("k.one", "一", calls["kpi"])

    @core.provider("todo.queue", "todos")
    def _t(ctx):
        calls["todo"] += 1
        return [core.todo_item("请假", f"第 {calls['todo']} 次", to=core.target("attendance.todo"))]

    layouts = {p: {"note": "", "tabs": [layout.tab("overview", "总览", kpis=["k.one"], todos=True)]} for p in core.PROFILE_LABELS}
    store = {}
    ctx = make_ctx()
    first = core.get_home_for(ctx, layouts, cache_get=store.get, cache_set=lambda k, v, ttl: store.__setitem__(k, v), now=lambda: 100)
    second = core.get_home_for(make_ctx(), layouts, cache_get=store.get, cache_set=lambda k, v, ttl: store.__setitem__(k, v), now=lambda: 130)
    assert calls == {"kpi": 1, "todo": 2}
    assert first["pages"]["overview"]["kpis"][0]["value"] == second["pages"]["overview"]["kpis"][0]["value"] == "1"
    assert first["pages"]["overview"]["todos"][0]["title"] == "第 1 次" and second["pages"]["overview"]["todos"][0]["title"] == "第 2 次"
    assert second["generated_at"] == 130
    assert len(store) == 1
    assert json.loads(list(store.values())[0])["pages"]["overview"]["todos"] == []   # 缓存里不放待办


def test_cache_key_depends_on_user_and_period(registry):
    @core.provider("k.one", "kpi")
    def _k(ctx):
        return core.kpi("k.one", "一", ctx.user + ctx.period)

    layouts = {p: {"note": "", "tabs": [layout.tab("overview", "总览", kpis=["k.one"])]} for p in core.PROFILE_LABELS}
    store = {}
    put = lambda k, v, ttl: store.__setitem__(k, v)
    core.get_home_for(make_ctx(user="a@x"), layouts, cache_get=store.get, cache_set=put)
    core.get_home_for(make_ctx(user="b@x"), layouts, cache_get=store.get, cache_set=put)
    core.get_home_for(make_ctx(user="a@x", period="2026-09"), layouts, cache_get=store.get, cache_set=put)
    assert len(store) == 3
