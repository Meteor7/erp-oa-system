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
    (["HR Manager"], True), (["HR User"], True), (["System Manager"], True), (["QIHENG Demo Business Executive"], True),
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


def test_the_attendance_centre_lists_cover_trips_but_the_leave_engine_does_not():
    """出差在考勤中心里和请假、加班、调休同一个入口；额度、日历这些请假专用的计算仍然只认原来三种。"""
    module = importlib.import_module("rayher_hr_payroll.api.attendance_entry")
    assert module.LIST_TYPES == (*att.ATTENDANCE_TYPES, "出差申请")
    assert "出差申请" not in att.ATTENDANCE_TYPES


def test_a_user_gets_the_trip_type_only_when_the_travel_feature_is_open(monkeypatch):
    module = importlib.import_module("rayher_hr_payroll.api.attendance_entry")
    open_types = {"请假申请", "加班申请", "调休申请", "出差申请"}
    monkeypatch.setattr(module, "can_access_request_type", lambda item: item in open_types)
    assert module._types() == ["请假申请", "加班申请", "调休申请", "出差申请"]
    open_types.remove("出差申请")
    assert module._types() == ["请假申请", "加班申请", "调休申请"]


def test_hr_opens_any_submitted_trip_read_only_but_a_plain_employee_cannot(entry, monkeypatch):
    module, _raw, state = entry
    detail = getattr(module.get_attendance_request, "__wrapped__", module.get_attendance_request)
    monkeypatch.setattr(module.oa_entry, "list_requests", lambda **kwargs: [])             # 出差申请的“全部”只给系统管理员、高管：人事走下面的只读通道
    monkeypatch.setattr(module, "_balances", lambda employee, cache: {"annual": None, "comp": None})
    monkeypatch.setattr(module, "_linked_documents", lambda trip: [{"name": "BX-1", "request_type": "报销单"}] if trip == "OA-2" else [])
    state.summaries = {"OA-2": {"name": "OA-2", "request_type": "出差申请", "employee": "E1", "employee_name": "演示员工117", "steps": [],
                                "travel_start_date": "2026-10-12", "travel_end_date": "2026-10-13", "travel_destination": "上海"}}
    state.roles = ["HR User"]
    result = detail("OA-2")
    assert result["request"]["travel_destination"] == "上海" and "关联报销" in result["impact"]
    assert result["mine"] is False                                                           # 人事只读，不是自己的：不显示“发起报销”
    assert result["linked"] == [{"name": "BX-1", "request_type": "报销单"}]
    monkeypatch.setattr(module.oa_entry, "list_requests", lambda view="mine", **kwargs: [{"name": "OA-2"}] if view == "mine" else [])
    assert detail("OA-2")["mine"] is True
    assert "workflow_status <> '草稿'" in state.sql[0][0]                                  # 草稿只有本人看得到
    state.roles = ["Employee"]
    with pytest.raises(Exception, match="找不到这张申请"):
        detail("OA-2")


def test_the_default_list_of_submitted_requests_includes_trips(entry):
    module, _raw, state = entry
    module._attendance_names(None, 5)
    assert state.sql[0][1]["types"] == module.LIST_TYPES and "出差申请" in state.sql[0][1]["types"]


def test_a_trip_lists_the_reimbursements_and_payments_linked_to_it_that_the_viewer_may_open(monkeypatch):
    """出差详情里的“关联的报销和付款”：按 source_request 反查报销单、付款单，只留当前登录人自己能打开的。"""
    module = importlib.import_module("rayher_hr_payroll.api.attendance_entry")
    seen = {}

    def get_all(doctype, filters=None, pluck=None, **kwargs):
        seen["filters"] = filters
        return ["BX-1", "FK-2", "BX-3"]

    visible = {"BX-1": {"name": "BX-1", "request_type": "报销单", "subject": "上海打车", "employee_name": "演示员工117", "amount": 86,
                        "workflow_status": "待审批", "business_status": "", "steps": [1]},
               "FK-2": {"name": "FK-2", "request_type": "付款单", "subject": "酒店", "employee_name": "演示员工117", "amount": 640,
                        "workflow_status": "已付款", "business_status": "已付款"}}
    monkeypatch.setattr(module.frappe, "get_all", get_all, raising=False)
    monkeypatch.setattr(module.oa_entry, "list_requests", lambda view="all", name=None, limit=1, **kw: [visible[name]] if name in visible else [])
    rows = module._linked_documents("OA-T1")
    assert seen["filters"] == {"source_request": "OA-T1", "request_type": ["in", ["报销单", "付款单"]]}
    assert [row["name"] for row in rows] == ["BX-1", "FK-2"], "BX-3 is not visible to this viewer"
    assert rows[0] == {"name": "BX-1", "request_type": "报销单", "subject": "上海打车", "employee_name": "演示员工117", "amount": 86,
                       "workflow_status": "待审批", "business_status": ""}
