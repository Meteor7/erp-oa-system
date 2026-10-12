"""HR 概览（overview_entry）对部门主管的范围：团队 = 汇报关系向下（决定 2026-10-12）。"""
from rayher_hr_payroll.api import overview_entry as ov


def test_hr_and_leaders_see_the_whole_company(monkeypatch):
    monkeypatch.setattr(ov, "_is_leader", lambda: False)
    monkeypatch.setattr(ov, "_roles", lambda: {"HR Manager"})
    assert ov.hr_scope() == (True, None, None)
    monkeypatch.setattr(ov, "_is_leader", lambda: True)
    monkeypatch.setattr(ov, "_roles", lambda: set())
    assert ov.hr_scope() == (True, None, None)


def test_a_department_manager_sees_only_the_team_below_them(monkeypatch):
    from rayher_hr_payroll import team_scope

    monkeypatch.setattr(ov, "_is_leader", lambda: False)
    monkeypatch.setattr(ov, "_roles", lambda: {"Department Manager", "Employee"})
    monkeypatch.setattr(ov, "_user", lambda: "boss@tests-x.example.invalid")
    monkeypatch.setattr(team_scope, "team_of_user", lambda user, include_self=True: {"employee": "E1", "names": ["E1", "E2", "E7"]})
    assert ov.hr_scope() == (True, None, ["E1", "E2", "E7"])


def test_a_department_manager_without_a_team_sees_nothing(monkeypatch):
    from rayher_hr_payroll import team_scope

    monkeypatch.setattr(ov, "_is_leader", lambda: False)
    monkeypatch.setattr(ov, "_roles", lambda: {"Department Manager"})
    monkeypatch.setattr(ov, "_user", lambda: "boss@tests-x.example.invalid")
    monkeypatch.setattr(team_scope, "team_of_user", lambda user, include_self=True: {"employee": "E1", "names": []})
    assert ov.hr_scope() == (False, None, None)
    monkeypatch.setattr(ov, "_roles", lambda: {"Employee"})
    assert ov.hr_scope() == (False, None, None)


def test_the_team_filters_reach_the_attendance_queries(monkeypatch):
    seen = []
    monkeypatch.setattr(ov.frappe, "get_all", lambda doctype, filters=None, **kwargs: seen.append((doctype, filters)) or [], raising=False)
    ov._attendance_rows([(2026, 10)], None, ["E1", "E2"])
    ov._attendance_rows([(2026, 10)], None, [])
    ov._away_today(None, ["E1"])
    assert seen[0][1]["employee"] == ["in", ["E1", "E2"]]
    assert seen[1][1]["employee"] == ["in", ["__none__"]]           # 空团队不能变成“不过滤”
    assert seen[2][1]["employee"] == ["in", ["E1"]]
    assert "department" not in seen[0][1]
