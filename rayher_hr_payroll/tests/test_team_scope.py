"""“我的团队”= 汇报关系向下的在职员工（决定 2026-10-12）。"""
import importlib
import sys
import types
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import team_scope


def children_of(tree):
    """tree: {上级: [(员工, 状态)]} → fetch_children(names)。"""
    def fetch(names):
        return [{"name": name, "status": status} for boss in names for name, status in tree.get(boss, [])]
    return fetch


def test_the_team_is_everyone_below_in_the_reporting_line_not_the_department():
    tree = {"M": [("A", "Active"), ("B", "Active")], "A": [("C", "Active")], "C": [("D", "Active")]}
    found = team_scope.collect_team("M", children_of(tree))
    assert [row["name"] for row in found] == ["A", "B", "C", "D"]          # 先近后远，直接和间接下属都算
    assert team_scope.collect_team("D", children_of(tree)) == []
    assert team_scope.collect_team("", children_of(tree)) == []


def test_a_cycle_and_a_deep_chain_do_not_loop_forever():
    cyclic = {"M": [("A", "Active")], "A": [("M", "Active"), ("B", "Active")], "B": [("A", "Active")]}
    assert [row["name"] for row in team_scope.collect_team("M", children_of(cyclic))] == ["A", "B"]
    chain = {f"E{i}": [(f"E{i + 1}", "Active")] for i in range(50)}
    assert len(team_scope.collect_team("E0", children_of(chain), max_depth=5)) == 5
    wide = {"M": [(f"E{i}", "Active") for i in range(30)]}
    assert len(team_scope.collect_team("M", children_of(wide), limit=10)) == 10


def test_someone_who_left_in_the_middle_does_not_hide_the_people_below_them(monkeypatch):
    tree = {"M": [("A", "Left")], "A": [("C", "Active")]}
    monkeypatch.setattr(team_scope, "_fetch_children", children_of(tree))
    assert team_scope.team_names("M") == ["C"]                                   # 离职的人不在结果里，但他名下的人还在
    assert team_scope.team_names("M", include_self=True) == ["M", "C"]
    assert team_scope.team_names("M", statuses=("Active", "Left")) == ["A", "C"]  # 按月份看工时时带上本月离职的


@pytest.fixture
def fake_frappe(monkeypatch):
    frappe = types.ModuleType("frappe")
    state = SimpleNamespace(
        employees=[{"name": "E1", "user_id": "boss@tests-x.example.invalid", "status": "Active", "reports_to": ""},
                   {"name": "E2", "user_id": "a@tests-x.example.invalid", "status": "Active", "reports_to": "E1"},
                   {"name": "E3", "user_id": "dup@tests-x.example.invalid", "status": "Active", "reports_to": ""},
                   {"name": "E4", "user_id": "dup@tests-x.example.invalid", "status": "Active", "reports_to": ""}],
        roles={"boss@tests-x.example.invalid": []}, users={"boss@tests-x.example.invalid", "a@tests-x.example.invalid"})

    def get_all(doctype, filters=None, fields=None, **_kwargs):
        rows = state.employees
        for key, value in (filters or {}).items():
            if isinstance(value, list) and value and value[0] == "in":
                rows = [row for row in rows if row.get(key) in value[1]]
            elif isinstance(value, list):
                continue
            else:
                rows = [row for row in rows if row.get(key) == value]
        return [{field: row.get(field) for field in fields} for row in rows]

    def exists(doctype, filters):
        if doctype == "User":
            return filters in state.users
        if doctype == "Has Role":
            return filters["role"] in state.roles.get(filters["parent"], [])
        return any(all(row.get(k) == v for k, v in filters.items()) for row in state.employees)

    def get_value(doctype, name, field):
        return next((row.get(field) for row in state.employees if row["name"] == name), None)

    class UserDoc:
        def __init__(self, name):
            self.name = name

        def add_roles(self, role):
            state.roles.setdefault(self.name, []).append(role)

    frappe.get_all = get_all
    frappe.db = SimpleNamespace(exists=exists, get_value=get_value)
    frappe.get_doc = lambda doctype, name: UserDoc(name)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    return state


def test_a_user_without_exactly_one_active_employee_has_no_team(fake_frappe):
    assert team_scope.active_employee_of("boss@tests-x.example.invalid") == "E1"
    assert team_scope.active_employee_of("dup@tests-x.example.invalid") == ""                      # 关联了两个员工：当作没有，不猜
    assert team_scope.active_employee_of("nobody@tests-x.example.invalid") == ""
    assert team_scope.team_of_user("boss@tests-x.example.invalid") == {"employee": "E1", "names": ["E1", "E2"]}
    assert team_scope.team_of_user("a@tests-x.example.invalid") == {"employee": "E2", "names": []}  # 没有下属的人没有团队
    assert team_scope.team_of_user("dup@tests-x.example.invalid") == {"employee": "", "names": []}


def test_the_manager_role_follows_the_reporting_line_and_never_takes_roles_away(fake_frappe):
    # 员工档案里新设“汇报给”：他的上级账号补上“部门主管”角色
    assert team_scope.ensure_manager_role(SimpleNamespace(reports_to="E1", status="Active")) is True
    assert fake_frappe.roles["boss@tests-x.example.invalid"] == ["Department Manager"]
    assert team_scope.ensure_manager_role(SimpleNamespace(reports_to="E1", status="Active")) is False   # 已经有了不重复加
    assert team_scope.ensure_manager_role(SimpleNamespace(reports_to="", status="Active")) is False
    assert team_scope.ensure_manager_role(SimpleNamespace(reports_to="E1", status="Left")) is False      # 离职的人不触发
    assert team_scope.grant_manager_role("nobody@tests-x.example.invalid") is False                                       # 没有账号的不处理


def test_the_backfill_grants_every_current_supervisor_once(fake_frappe):
    fake_frappe.employees.append({"name": "E5", "user_id": "a@tests-x.example.invalid", "status": "Active", "reports_to": "E1"})
    assert team_scope.grant_manager_role_to_all_supervisors() == ["boss@tests-x.example.invalid"]
    assert team_scope.grant_manager_role_to_all_supervisors() == []


def test_the_employee_hook_is_registered():
    hooks = importlib.import_module("rayher_hr_payroll.hooks")
    employee = hooks.doc_events["Employee"]
    assert "rayher_hr_payroll.team_scope.ensure_manager_role" in employee["on_update"]
    assert "rayher_hr_payroll.team_scope.ensure_manager_role" in employee["after_insert"]
    assert "rayher_hr_payroll.lifecycle_controls.sync_user_for_employee" in employee["on_update"]


def test_the_backfill_patch_is_listed():
    from pathlib import Path

    patches = (Path(team_scope.__file__).parent / "patches.txt").read_text(encoding="utf-8")
    assert "rayher_hr_payroll.patches.v1_0.grant_department_manager_to_supervisors" in patches
