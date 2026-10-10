"""考勤中心图表接口的权限：员工只拿到自己的，部门主管只拿到自己的部门，人事和管理层的汇总里没有人名。

这里不碰数据库：用一张内存里的员工表和申请表代替，看接口在不同身份下取了什么、返回了什么。
"""
import importlib
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import attendance_requests as att

TODAY = date.today()
IN_TWO_DAYS = (TODAY + timedelta(days=2)).isoformat()

EMPLOYEES = [
    {"name": "E1", "employee_name": "张主管", "department": "研发软件部 - RAY", "user_id": "mgr@tests-x.example.invalid", "reports_to": ""},
    {"name": "E2", "employee_name": "杨员工", "department": "研发软件部 - RAY", "user_id": "emp@tests-x.example.invalid", "reports_to": "E1"},
    {"name": "E3", "employee_name": "演示员工120", "department": "研发软件部 - RAY", "user_id": "mate@tests-x.example.invalid", "reports_to": "E1"},
    {"name": "E4", "employee_name": "演示员工144", "department": "财务部 - RAY", "user_id": "fin@tests-x.example.invalid", "reports_to": ""},
    {"name": "E5", "employee_name": "演示员工111", "department": "人事行政部 - RAY", "user_id": "hr@tests-x.example.invalid", "reports_to": ""},
    {"name": "E6", "employee_name": "演示员工160", "department": "总经办 - RAY", "user_id": "person014@tests-x.example.invalid", "reports_to": ""},
]
LEAVES = [
    {"name": "OA-1", "employee": "E2", "request_type": att.REQUEST_LEAVE, "leave_type": "年假", "workflow_status": "已完成",
     "attendance_days": json.dumps([{"work_date": IN_TWO_DAYS, "hours": 8}]), "from_date": IN_TWO_DAYS, "to_date": IN_TWO_DAYS},
    {"name": "OA-2", "employee": "E3", "request_type": att.REQUEST_LEAVE, "leave_type": "病假", "workflow_status": "已完成",
     "attendance_days": json.dumps([{"work_date": IN_TWO_DAYS, "hours": 8}]), "from_date": IN_TWO_DAYS, "to_date": IN_TWO_DAYS},
    {"name": "OA-3", "employee": "E4", "request_type": att.REQUEST_LEAVE, "leave_type": "事假", "workflow_status": "待审批",
     "attendance_days": json.dumps([{"work_date": IN_TWO_DAYS, "hours": 8}]), "from_date": IN_TWO_DAYS, "to_date": IN_TWO_DAYS},
]
NAMES = [item["employee_name"] for item in EMPLOYEES]


@pytest.fixture
def api(monkeypatch):
    entry = importlib.import_module("rayher_hr_payroll.api.attendance_board_entry")
    scope = importlib.import_module("rayher_hr_payroll.attendance_scope")
    state = SimpleNamespace(user="emp@tests-x.example.invalid", sql=[])

    def throw(message, exc=None):
        raise (exc or ValueError)(str(message))

    def get_all(doctype, filters=None, fields=None, **_kwargs):
        assert doctype == "Employee"
        rows = [row for row in EMPLOYEES if all(row.get(key) == value for key, value in (filters or {}).items() if key != "status")]
        return [{field: row.get(field) for field in fields} for row in rows]

    def sql(query, args=None, as_dict=False):
        state.sql.append((query, args))
        if "GROUP BY" in query:
            counts = {}
            for leave in LEAVES:
                person = next(item for item in EMPLOYEES if item["name"] == leave["employee"])
                if leave["workflow_status"] in args["statuses"] and ("employees" not in args or leave["employee"] in args["employees"]):
                    counts[person["department"]] = counts.get(person["department"], 0) + 1
            return [{"department": department, "n": n} for department, n in counts.items()]
        return [dict(leave) for leave in LEAVES if leave["employee"] in args["employees"]]

    def exists(doctype, filters):
        return any(row["reports_to"] == filters["reports_to"] for row in EMPLOYEES)

    for module in (entry, scope):
        monkeypatch.setattr(module.frappe, "_", lambda text, *args, **kwargs: text, raising=False)
        monkeypatch.setattr(module.frappe, "throw", throw, raising=False)
        monkeypatch.setattr(module.frappe, "get_all", get_all, raising=False)
        monkeypatch.setattr(module.frappe, "session", SimpleNamespace(user=state.user), raising=False)
    monkeypatch.setattr(scope.frappe, "db", SimpleNamespace(exists=exists), raising=False)
    monkeypatch.setattr(entry.frappe, "db", SimpleNamespace(sql=sql), raising=False)
    monkeypatch.setattr(scope, "position_users", lambda *keys: {"hr@tests-x.example.invalid", "person014@tests-x.example.invalid"})
    monkeypatch.setattr(entry, "can_access_request_type", lambda _type: True)
    monkeypatch.setattr(entry, "resolve_monthly_calendar", lambda year, month: {
        "work_dates": [date(year, month, day) for day in range(1, 29) if date(year, month, day).weekday() < 5]})

    def login(user):
        state.user = user
        for module in (entry, scope):
            monkeypatch.setattr(module.frappe, "session", SimpleNamespace(user=user), raising=False)

    state.login = login
    return entry, scope, state


def board(api, user):
    entry, _scope, state = api
    state.login(user)
    return entry.get_attendance_board.__wrapped__() if hasattr(entry.get_attendance_board, "__wrapped__") else entry.get_attendance_board()


def department(api, user, name=""):
    entry, _scope, state = api
    state.login(user)
    raw = getattr(entry.get_department_attendance, "__wrapped__", entry.get_department_attendance)
    return raw(name)


def test_who_is_which_level(api):
    _entry, scope, state = api
    for user, level in [("emp@tests-x.example.invalid", "employee"), ("mgr@tests-x.example.invalid", "manager"), ("fin@tests-x.example.invalid", "employee"),
                        ("hr@tests-x.example.invalid", "company"), ("person014@tests-x.example.invalid", "company"), ("Administrator", "company"), ("nobody@tests-x.example.invalid", "employee")]:
        state.login(user)
        assert scope.resolve_scope()["level"] == level, user
    state.login("Guest")
    with pytest.raises(Exception, match="请先登录"):
        scope.resolve_scope()


def test_an_employee_gets_only_their_own_numbers_and_no_colleague(api):
    entry, _scope, state = api
    result = board(api, "emp@tests-x.example.invalid")
    assert result["level"] == "employee" and set(result) == {"level", "personal"}
    assert result["personal"]["strip"][2]["kind"] == "annual"
    text = json.dumps(result, ensure_ascii=False)
    for name in NAMES:
        assert name not in text
    rows_query = [args for query, args in state.sql if "FROM `tabOA Approval Request`" in query and "GROUP BY" not in query]
    assert rows_query and all(args["employees"] == ("E2",) for args in rows_query)        # 只查了自己的申请


def test_an_employee_cannot_ask_for_any_department(api):
    for target in ("", "研发软件部 - RAY", "财务部 - RAY"):
        with pytest.raises(Exception, match="只有部门主管、人事和管理层"):
            department(api, "emp@tests-x.example.invalid", target)
    with pytest.raises(Exception, match="只有部门主管、人事和管理层"):
        department(api, "fin@tests-x.example.invalid", "财务部 - RAY")                  # 自己的部门也不行：没有下属的人不看团队
    _entry, _scope, state = api
    assert state.sql == []


def test_a_user_without_an_employee_record_sees_nothing(api):
    result = board(api, "nobody@tests-x.example.invalid")
    assert result["level"] == "employee" and result["personal"]["strip"] == []


def test_a_manager_gets_their_own_department_with_names_and_is_refused_any_other(api):
    result = board(api, "mgr@tests-x.example.invalid")
    assert result["level"] == "manager"
    detail = result["detail"]
    assert detail["department"] == "研发软件部 - RAY" and detail["label"] == "研发软件部" and detail["headcount"] == 3
    assert [member["name"] for member in detail["members"]] == ["张主管", "杨员工", "演示员工120"]
    assert detail["stats"]["days"][2]["off"] == 2
    assert department(api, "mgr@tests-x.example.invalid", "")["detail"]["department"] == "研发软件部 - RAY"
    assert department(api, "mgr@tests-x.example.invalid", "研发软件部 - RAY")["level"] == "manager"
    for other in ("财务部 - RAY", "总经办 - RAY", "不存在的部门"):
        with pytest.raises(Exception, match="只能查看自己所在部门"):
            department(api, "mgr@tests-x.example.invalid", other)
    assert "演示员工144" not in json.dumps(result, ensure_ascii=False)


def test_the_company_summary_has_no_names_at_all(api):
    for user in ("hr@tests-x.example.invalid", "person014@tests-x.example.invalid", "Administrator"):
        result = board(api, user)
        assert result["level"] == "company" and set(result) == {"level", "summary"}
        summary = result["summary"]
        assert {item["label"] for item in summary["departments"]} == {"研发软件部", "财务部", "人事行政部", "总经办"}
        software = next(item for item in summary["departments"] if item["label"] == "研发软件部")
        assert software["headcount"] == 3 and software["trend"][2] == 2 and software["pending"] == 0
        finance = next(item for item in summary["departments"] if item["label"] == "财务部")
        assert finance["pending"] == 1 and finance["trend"][2] == 0                     # 审批中的不进趋势
        text = json.dumps(result, ensure_ascii=False)
        for name in NAMES:
            assert name not in text, (user, name)
        assert "members" not in text and "employee_name" not in text


def test_the_company_levels_see_names_only_after_choosing_a_department(api):
    for user in ("hr@tests-x.example.invalid", "person014@tests-x.example.invalid"):
        result = department(api, user, "研发软件部 - RAY")
        assert result["level"] == "company"
        assert [member["name"] for member in result["detail"]["members"]] == ["张主管", "杨员工", "演示员工120"]
        finance = department(api, user, "财务部 - RAY")["detail"]
        assert [member["name"] for member in finance["members"]] == ["演示员工144"] and finance["pending"] == 1
    with pytest.raises(Exception, match="请选择要查看的部门"):
        department(api, "hr@tests-x.example.invalid", "")
    with pytest.raises(Exception, match="找不到这个部门"):
        department(api, "hr@tests-x.example.invalid", "不存在的部门")


def test_the_feature_gate_still_applies(api, monkeypatch):
    entry, _scope, _state = api
    monkeypatch.setattr(entry, "can_access_request_type", lambda _type: False)
    with pytest.raises(Exception, match="暂未开放"):
        board(api, "hr@tests-x.example.invalid")
