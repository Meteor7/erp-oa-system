"""请假 / 加班 / 调休页面的"全部"栏目：人事和老板只读查看所有已提交的申请，其他人不行。"""
import importlib
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import attendance_requests as att


@pytest.fixture
def entry(monkeypatch):
    module = importlib.import_module("rayher_hr_payroll.api.attendance_entry")
    monkeypatch.setattr(module.frappe, "_", lambda text, *args, **kwargs: text, raising=False)

    def throw(message, exc=None):
        raise (exc or ValueError)(str(message))

    monkeypatch.setattr(module.frappe, "throw", throw, raising=False)
    state = SimpleNamespace(user="hr@tests-x.example.invalid", roles=["HR Manager"], sql=[], summaries={})
    monkeypatch.setattr(module.frappe, "session", SimpleNamespace(user=state.user), raising=False)
    monkeypatch.setattr(module.frappe, "get_roles", lambda user=None: list(state.roles), raising=False)
    monkeypatch.setattr(module, "_require_types", lambda: list(att.ATTENDANCE_TYPES))

    def sql(query, args=None, as_dict=False):
        state.sql.append((query, args))
        return [{"name": "OA-2"}, {"name": "OA-1"}]

    monkeypatch.setattr(module.frappe, "db", SimpleNamespace(sql=sql), raising=False)
    monkeypatch.setattr(module, "_load_summaries", lambda names: [state.summaries.get(name, {"name": name, "steps": []}) for name in names])
    monkeypatch.setattr(module, "_names", lambda users: {user: user.split("@")[0] for user in users})
    raw = getattr(module.list_attendance_all, "__wrapped__", module.list_attendance_all)
    return module, raw, state


@pytest.mark.parametrize("roles,expected", [
    (["HR Manager"], True), (["HR User"], True), (["System Manager"], True), (["Rayher Business Executive"], True),
    (["Employee"], False), (["Accounts User", "Employee"], False), ([], False),
])
def test_only_hr_and_executives_can_view_all(entry, roles, expected):
    module, _raw, state = entry
    state.roles = roles
    assert module.can_view_all() is expected


def test_the_administrator_and_guests(entry, monkeypatch):
    module, _raw, state = entry
    state.roles = []
    monkeypatch.setattr(module.frappe, "session", SimpleNamespace(user="Administrator"))
    assert module.can_view_all() is True
    monkeypatch.setattr(module.frappe, "session", SimpleNamespace(user="Guest"))
    assert module.can_view_all() is False


def test_everyone_else_is_refused(entry):
    module, raw, state = entry
    state.roles = ["Employee"]
    with pytest.raises(Exception) as caught:
        raw()
    assert "只有人事或管理员" in str(caught.value)
    assert state.sql == []


def test_all_lists_submitted_requests_and_never_drafts(entry):
    module, raw, state = entry
    state.summaries = {"OA-1": {"name": "OA-1", "steps": [{"step_index": 1, "approvers": ["boss@tests-x.example.invalid"]}], "current_step_index": 1}}
    result = raw(att.REQUEST_OVERTIME, limit=500)
    assert [row["name"] for row in result["items"]] == ["OA-2", "OA-1"]
    assert result["names"] == {"boss@tests-x.example.invalid": "boss"}
    query, args = state.sql[0]
    assert "workflow_status <> '草稿'" in query and "ORDER BY modified DESC" in query
    assert args["types"] == (att.REQUEST_OVERTIME,)
    assert args["limit"] == 200
    state.sql.clear()
    raw()
    assert state.sql[0][1]["types"] == tuple(att.ATTENDANCE_TYPES) and state.sql[0][1]["limit"] == module.ALL_LIMIT


def test_an_unknown_type_is_refused(entry):
    _module, raw, _state = entry
    with pytest.raises(Exception, match="不支持的申请类型"):
        raw("购买申请")


def test_a_single_request_by_name_still_excludes_drafts(entry):
    module, _raw, state = entry
    module._attendance_names(None, 1, name="OA-9")
    query, args = state.sql[0]
    assert "name = %(name)s" in query and "<> '草稿'" in query and args["name"] == "OA-9"


def test_the_reviewed_list_carries_day_details_as_a_list():
    module = importlib.import_module("rayher_hr_payroll.api.attendance_entry")
    assert module._days_of('[{"work_date": "2026-10-13", "hours": 3}]') == [{"work_date": "2026-10-13", "hours": 3}]
    assert module._days_of([{"work_date": "2026-10-13", "hours": 5}, "x"]) == [{"work_date": "2026-10-13", "hours": 5}]
    assert module._days_of("not json") == [] and module._days_of(None) == [] and module._days_of('{"a": 1}') == []
