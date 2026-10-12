"""看板明细接口（dashboard_home.get_detail）：没登录不行，没有这个清单或没有权限只回“看不到”，有权限才给清单。"""
from types import SimpleNamespace as NS

import pytest

from rayher_hr_payroll.api import dashboard_home
from rayher_hr_payroll.dashboard import core

call = getattr(dashboard_home.get_detail, "__wrapped__", dashboard_home.get_detail)


@pytest.fixture
def api(monkeypatch):
    def throw(message, exc=None):
        raise (exc or ValueError)(str(message))

    state = {"user": "who@example.com"}
    monkeypatch.setattr(dashboard_home, "frappe", NS(session=NS(user="who@example.com"), _=lambda text: text, throw=throw,
                                                        PermissionError=PermissionError, whitelist=lambda **kw: (lambda fn: fn)), raising=False)

    def make_ctx(period=None):
        return core.Ctx(user=state["user"], roles=frozenset({"Employee"}), positions=frozenset(), period=period or "2026-10", today="2026-10-12")

    monkeypatch.setattr(dashboard_home, "_make_ctx", make_ctx)
    monkeypatch.setattr(core, "load_providers", lambda: None)
    return state


def test_a_guest_is_refused(api, monkeypatch):
    monkeypatch.setattr(dashboard_home.frappe, "session", NS(user="Guest"))
    with pytest.raises(PermissionError):
        call("approval.stuck")


def test_an_unknown_list_or_a_list_the_user_may_not_see_is_just_unavailable(api, monkeypatch):
    seen = []
    monkeypatch.setitem(core.REGISTRY, "drill.test.hidden", core.Provider("drill.test.hidden", "drill", lambda ctx: seen.append("ran") or {}, lambda ctx: False))
    assert call("no.such.list") == {"available": False}
    assert call("test.hidden") == {"available": False} and seen == []        # 没权限时清单函数根本不会被调用
    assert call("") == {"available": False} and call(None) == {"available": False}
    assert call("../../etc/passwd") == {"available": False}


def test_a_visible_list_is_returned_with_the_period(api, monkeypatch):
    detail = core.drill("drill.test.ok", "测试清单", [("名称",), ("金额", "r")], [core.drill_row(["甲", "¥ 1"])], summary="共 1 条")
    monkeypatch.setitem(core.REGISTRY, "drill.test.ok", core.Provider("drill.test.ok", "drill", lambda ctx: detail, lambda ctx: True))
    got = call("test.ok", "2026-09")
    assert got["available"] is True and got["period"] == "2026-09" and got["title"] == "测试清单" and got["summary"] == "共 1 条"
    assert got["columns"] == [{"label": "名称", "align": ""}, {"label": "金额", "align": "r"}]
    assert got["rows"] == [{"cells": ["甲", "¥ 1"], "target": None, "tone": ""}]


def test_only_drill_providers_can_be_opened_as_a_list(api, monkeypatch):
    monkeypatch.setitem(core.REGISTRY, "drill.test.card", core.Provider("drill.test.card", "kpi", lambda ctx: {"secret": 1}, None))
    assert call("test.card") == {"available": False}
    assert call("cost.total") == {"available": False}          # 指标卡本身的名字不是清单名
