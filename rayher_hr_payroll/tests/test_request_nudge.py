"""催一下：申请人 / 项目负责人对等得久的采购、购买申请，提醒当前审批人。"""
import json
from datetime import date
from types import SimpleNamespace

import pytest

from rayher_hr_payroll.api import request_nudge as nudge

TODAY = date(2026, 10, 12)
call = getattr(nudge.nudge_request, "__wrapped__", nudge.nudge_request)   # 绕过 whitelist 的请求环境校验


def step(index, approvers, approved=(), acted_on=None):
    return SimpleNamespace(step_index=index, approvers=json.dumps(list(approvers)), approved_by=json.dumps(list(approved)), acted_on=acted_on)


def make_doc(**kw):
    base = dict(name="OA-1", request_type="采购申请", workflow_status="待审批", owner="applicant@tests-x.example.invalid", employee="E1",
                project_owner="person041@tests-x.example.invalid", subject="伺服电机", submitted_on="2026-10-05 09:00:00", modified="2026-10-05 09:00:00",
                creation="2026-10-05 09:00:00", current_step_index=2,
                steps=[step(1, ["boss@tests-x.example.invalid"], ["boss@tests-x.example.invalid"], "2026-10-08 10:00:00"), step(2, ["pmc@tests-x.example.invalid", "vice@tests-x.example.invalid"], ["vice@tests-x.example.invalid"])])
    base.update(kw)
    return SimpleNamespace(**base)


def test_waiting_counts_from_the_last_signature_then_from_the_submission():
    assert nudge.waited_days(make_doc(), TODAY) == 4                                   # 10/08 签的 -> 10/12
    assert nudge.waited_days(make_doc(steps=[step(1, ["boss@tests-x.example.invalid"])]), TODAY) == 7    # 没人签过：从 10/05 提交起算
    assert nudge.waited_days(make_doc(steps=[], submitted_on=None, modified="2026-10-11 08:00:00"), TODAY) == 1
    assert nudge.waited_days(make_doc(steps=[], submitted_on=None, modified=None, creation=None), TODAY) == 0


def test_only_approvers_who_have_not_signed_yet_are_reminded():
    assert nudge._current_approvers(make_doc()) == ["pmc@tests-x.example.invalid"]
    assert nudge._current_approvers(make_doc(current_step_index=9)) == []
    assert nudge._current_approvers(make_doc(steps=[SimpleNamespace(step_index=2, approvers="不是 json", approved_by="[]", acted_on=None)])) == []


@pytest.mark.parametrize("kw, who, expected", [
    ({}, ("applicant@tests-x.example.invalid", ""), ""),                                         # 申请人本人（所有人）
    ({}, ("someone@tests-x.example.invalid", "E1"), ""),                                         # 申请人本人（员工号对上，代人提交时所有人不是他）
    ({}, ("person041@tests-x.example.invalid", ""), ""),                                             # 项目负责人
    ({}, ("pmc@tests-x.example.invalid", ""), "只有申请人或项目负责人可以催办。"),               # 审批人自己不能催自己
    ({}, ("stranger@tests-x.example.invalid", "E9"), "只有申请人或项目负责人可以催办。"),
    ({"workflow_status": "已完成"}, ("applicant@tests-x.example.invalid", ""), "这张申请已经不在审批中，不需要催。"),
    ({"request_type": "出差申请"}, ("applicant@tests-x.example.invalid", ""), "只有采购申请和购买申请可以催办。"),
    ({"request_type": "购买申请"}, ("applicant@tests-x.example.invalid", ""), ""),
    ({"steps": [step(1, ["boss@tests-x.example.invalid"], ["boss@tests-x.example.invalid"], "2026-10-11 10:00:00"), step(2, ["pmc@tests-x.example.invalid"])]}, ("applicant@tests-x.example.invalid", ""), "等待还不到 3 天，先别催。"),
    ({"steps": [step(2, ["pmc@tests-x.example.invalid"], ["pmc@tests-x.example.invalid"])]}, ("applicant@tests-x.example.invalid", ""), "当前节点没有可提醒的审批人。"),
])
def test_who_can_nudge_and_when(kw, who, expected):
    assert nudge.nudge_problem(make_doc(**kw), who[0], who[1], TODAY) == expected


@pytest.fixture
def api(monkeypatch):
    logs, state = [], {"doc": make_doc(), "perm": True, "nudged_today": False, "users": {"pmc@tests-x.example.invalid", "vice@tests-x.example.invalid"}}

    def throw(message, exc=None):
        raise (exc or ValueError)(str(message))

    class Log(dict):
        def insert(self, ignore_permissions=False):
            logs.append(dict(self))

    f = nudge.frappe
    monkeypatch.setattr(f, "_", lambda text, *a, **k: text, raising=False)
    monkeypatch.setattr(f, "throw", throw, raising=False)
    monkeypatch.setattr(f, "PermissionError", PermissionError, raising=False)
    monkeypatch.setattr(f, "get_doc", lambda *args: state["doc"] if len(args) == 2 else Log(args[0]), raising=False)
    monkeypatch.setattr(f, "has_permission", lambda doctype, ptype, doc=None: state["perm"], raising=False)
    monkeypatch.setattr(f, "session", SimpleNamespace(user="applicant@tests-x.example.invalid"), raising=False)
    monkeypatch.setattr(f, "db", SimpleNamespace(get_value=lambda *a, **k: "E1", exists=lambda doctype, name: name in state["users"], commit=lambda: None), raising=False)
    monkeypatch.setattr(f, "get_all", lambda doctype, **k: [{"name": "NL"}] if state["nudged_today"] else [], raising=False)
    monkeypatch.setattr(f, "utils", SimpleNamespace(get_fullname=lambda user: "何志凌"), raising=False)
    monkeypatch.setattr(nudge, "date", SimpleNamespace(today=lambda: TODAY, fromisoformat=date.fromisoformat), raising=False)
    return logs, state


def test_nudging_notifies_the_current_approvers_who_have_not_signed(api):
    logs, _state = api
    result = call("OA-1")
    assert result == {"sent": 1, "waited_days": 4}
    assert len(logs) == 1 and logs[0]["for_user"] == "pmc@tests-x.example.invalid"
    assert "何志凌 催你审批：伺服电机（已等 4 天）" in logs[0]["subject"] and logs[0]["subject"].endswith("[nudge:2026-10-12]")
    assert logs[0]["document_name"] == "OA-1" and logs[0]["link"].endswith("/approval/procurement?request=OA-1")


def test_a_request_can_be_nudged_only_once_a_day(api):
    _logs, state = api
    state["nudged_today"] = True
    with pytest.raises(Exception, match="今天已经催过了"):
        call("OA-1")


def test_no_permission_no_nudge_and_nothing_is_sent(api):
    logs, state = api
    state["perm"] = False
    with pytest.raises(PermissionError):
        call("OA-1")
    state["perm"] = True
    nudge.frappe.session = SimpleNamespace(user="stranger@tests-x.example.invalid")
    nudge.frappe.db.get_value = lambda *a, **k: "E9"
    with pytest.raises(Exception, match="只有申请人或项目负责人"):
        call("OA-1")
    assert logs == []


def test_approvers_without_an_account_are_skipped_and_nobody_to_remind_is_an_error(api):
    logs, state = api
    state["users"] = set()
    with pytest.raises(Exception, match="没有可提醒的审批人"):
        call("OA-1")
    assert logs == []


def test_a_bad_name_is_refused(api):
    for bad in ("", "x" * 141):
        with pytest.raises(Exception, match="申请单号无效"):
            call(bad)
