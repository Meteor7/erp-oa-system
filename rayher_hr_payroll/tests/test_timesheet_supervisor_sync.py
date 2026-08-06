from copy import deepcopy

import pytest

from rayher_hr_payroll.timesheet_supervisor_sync import (
    build_sync_plan,
    synchronize_timesheet_supervisors,
)


def employee(name, employee_name, *, user_id="", status="Active", rd_type="全时研发", reports_to=None):
    return {
        "name": name,
        "employee_name": employee_name,
        "user_id": user_id,
        "status": status,
        "rd_personnel_type": rd_type,
        "reports_to": reports_to,
    }


def software_rows(*, cao_reports_to=None):
    return [
        employee("EMP-JUN", "演示员工132", user_id="jun@example.com"),
        employee("EMP-CAO", "演示员工142", user_id="cao@example.com", reports_to=cao_reports_to),
        employee("EMP-GAO", "演示员工184", user_id="gao@example.com"),
    ]


def software_mapping():
    return {"演示员工132": "Philippe", "演示员工142": "演示员工132", "演示员工184": "演示员工132"}


def test_plan_links_software_staff_and_promotes_jun_zhang():
    plan = build_sync_plan(
        software_rows(),
        {"jun@example.com", "cao@example.com", "gao@example.com"},
        roles_by_user={},
        mapping=software_mapping(),
    )

    assert plan["report_updates"] == [
        {"employee": "EMP-CAO", "employee_name": "演示员工142", "reports_to": "EMP-JUN"},
        {"employee": "EMP-GAO", "employee_name": "演示员工184", "reports_to": "EMP-JUN"},
    ]
    assert plan["role_additions"] == [
        {
            "employee": "EMP-JUN",
            "employee_name": "演示员工132",
            "user": "jun@example.com",
            "role": "Department Manager",
        }
    ]
    assert plan["conflicts"] == []


def test_plan_records_existing_different_manager_as_conflict_without_update():
    plan = build_sync_plan(
        software_rows(cao_reports_to="EMP-OTHER"),
        {"jun@example.com"},
        roles_by_user={},
        mapping=software_mapping(),
    )

    assert plan["conflicts"] == [
        {
            "type": "reports_to_mismatch",
            "employee": "EMP-CAO",
            "employee_name": "演示员工142",
            "current": "EMP-OTHER",
            "expected": "EMP-JUN",
        }
    ]
    assert all(row["employee"] != "EMP-CAO" for row in plan["report_updates"])


def test_external_supervisor_and_non_rd_employee_are_not_mutated():
    rows = [
        employee("EMP-JUN", "演示员工132", user_id="jun@example.com"),
        employee("EMP-FIN", "财务员工", rd_type="非研发"),
    ]
    plan = build_sync_plan(
        rows,
        {"jun@example.com"},
        roles_by_user={},
        mapping={"演示员工132": "Philippe", "财务员工": "演示员工132"},
    )

    assert plan["report_updates"] == []
    assert plan["role_additions"] == []
    assert plan["skipped_external"] == [
        {"employee": "EMP-JUN", "employee_name": "演示员工132", "supervisor_name": "Philippe"}
    ]


def test_already_correct_link_and_existing_role_are_unchanged():
    rows = software_rows(cao_reports_to="EMP-JUN")
    rows[2]["reports_to"] = "EMP-JUN"
    plan = build_sync_plan(
        rows,
        {"jun@example.com"},
        roles_by_user={"jun@example.com": {"Employee", "Department Manager"}},
        mapping=software_mapping(),
    )

    assert plan["report_updates"] == []
    assert plan["role_additions"] == []
    assert [row["employee"] for row in plan["unchanged"]] == ["EMP-CAO", "EMP-GAO"]


def test_disabled_supervisor_user_skips_role_but_keeps_safe_relationship():
    plan = build_sync_plan(
        software_rows(),
        {"cao@example.com", "gao@example.com"},
        roles_by_user={},
        mapping=software_mapping(),
    )

    assert len(plan["report_updates"]) == 2
    assert plan["role_additions"] == []
    assert plan["skipped_user"] == [
        {
            "employee": "EMP-JUN",
            "employee_name": "演示员工132",
            "user": "jun@example.com",
            "reason": "user_not_enabled",
        }
    ]


def test_duplicate_active_supervisor_name_is_a_conflict():
    rows = software_rows()
    rows.append(employee("EMP-JUN-2", "演示员工132", user_id="jun2@example.com"))
    plan = build_sync_plan(
        rows,
        {"jun@example.com", "jun2@example.com"},
        roles_by_user={},
        mapping=software_mapping(),
    )

    assert plan["report_updates"] == []
    assert plan["role_additions"] == []
    assert [row["type"] for row in plan["conflicts"]] == [
        "supervisor_name_not_unique",
        "supervisor_name_not_unique",
    ]


def test_inactive_employee_is_out_of_scope_and_output_is_deterministic():
    rows = software_rows()
    rows[2]["status"] = "Left"
    reversed_rows = list(reversed(deepcopy(rows)))
    kwargs = {
        "enabled_users": {"jun@example.com", "cao@example.com", "gao@example.com"},
        "roles_by_user": {},
        "mapping": software_mapping(),
    }

    assert build_sync_plan(rows, **kwargs) == build_sync_plan(reversed_rows, **kwargs)
    assert [row["employee"] for row in build_sync_plan(rows, **kwargs)["report_updates"]] == ["EMP-CAO"]
class FakeDB:
    def __init__(self):
        self.set_value_calls = []

    def set_value(self, doctype, name, fieldname, value, *, update_modified):
        self.set_value_calls.append((doctype, name, fieldname, value, update_modified))


class FakeUserDoc:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user

    def add_roles(self, role):
        self.parent.add_role_calls.append((self.user, role))
        self.parent.roles.setdefault(self.user, set()).add(role)


class FakeFrappe:
    def __init__(self, employees, *, enabled_users, roles=None):
        self.employees = deepcopy(employees)
        self.enabled_users = set(enabled_users)
        self.roles = {user: set(values) for user, values in (roles or {}).items()}
        self.db = FakeDB()
        self.add_role_calls = []

    def get_all(self, doctype, *, filters=None, fields=None, pluck=None, order_by=None):
        if doctype == "Employee":
            return deepcopy(self.employees)
        if doctype == "User":
            assert filters == {"enabled": 1}
            assert pluck == "name"
            return sorted(self.enabled_users)
        raise AssertionError(doctype)

    def get_roles(self, user):
        return sorted(self.roles.get(user, set()))

    def get_doc(self, doctype, name):
        assert doctype == "User"
        return FakeUserDoc(self, name)

    def throw(self, message):
        raise RuntimeError(message)

    @staticmethod
    def _(message):
        return message


def test_dry_run_returns_exact_changes_without_writes(monkeypatch):
    import rayher_hr_payroll.timesheet_supervisor_sync as mod

    fake = FakeFrappe(
        software_rows(),
        enabled_users={"jun@example.com", "cao@example.com", "gao@example.com"},
    )
    monkeypatch.setattr(mod, "_get_frappe", lambda: fake, raising=False)
    monkeypatch.setattr(mod, "DIRECT_SUPERVISOR_BY_EMPLOYEE", software_mapping())

    report = synchronize_timesheet_supervisors(dry_run=True)

    assert len(report["report_updates"]) == 2
    assert len(report["role_additions"]) == 1
    assert report["applied_report_updates"] == 0
    assert report["applied_role_additions"] == 0
    assert fake.db.set_value_calls == []
    assert fake.add_role_calls == []


def test_conflict_throws_before_any_write(monkeypatch):
    import rayher_hr_payroll.timesheet_supervisor_sync as mod

    fake = FakeFrappe(
        software_rows(cao_reports_to="EMP-OTHER"),
        enabled_users={"jun@example.com"},
    )
    monkeypatch.setattr(mod, "_get_frappe", lambda: fake, raising=False)
    monkeypatch.setattr(mod, "DIRECT_SUPERVISOR_BY_EMPLOYEE", software_mapping())

    with pytest.raises(RuntimeError, match="主管关系冲突"):
        synchronize_timesheet_supervisors()

    assert fake.db.set_value_calls == []
    assert fake.add_role_calls == []


def test_apply_sets_reports_to_and_adds_only_missing_role(monkeypatch):
    import rayher_hr_payroll.timesheet_supervisor_sync as mod

    fake = FakeFrappe(
        software_rows(),
        enabled_users={"jun@example.com", "cao@example.com", "gao@example.com"},
    )
    monkeypatch.setattr(mod, "_get_frappe", lambda: fake, raising=False)
    monkeypatch.setattr(mod, "DIRECT_SUPERVISOR_BY_EMPLOYEE", software_mapping())

    report = synchronize_timesheet_supervisors()

    assert fake.db.set_value_calls == [
        ("Employee", "EMP-CAO", "reports_to", "EMP-JUN", False),
        ("Employee", "EMP-GAO", "reports_to", "EMP-JUN", False),
    ]
    assert fake.add_role_calls == [("jun@example.com", "Department Manager")]
    assert report["applied_report_updates"] == 2
    assert report["applied_role_additions"] == 1

def test_supervisor_sync_is_registered_once_and_not_repeated_after_migrate():
    from pathlib import Path

    patch = "rayher_hr_payroll.patches.v1_0.sync_timesheet_supervisor_permissions"
    patches = Path("rayher_hr_payroll/patches.txt").read_text(encoding="utf-8").splitlines()
    install_source = Path("rayher_hr_payroll/install.py").read_text(encoding="utf-8")

    assert patches.count(patch) == 1
    assert "synchronize_timesheet_supervisors" not in install_source

def test_non_rd_supervisor_gets_relationship_but_not_timesheet_manager_role():
    rows = [
        employee("EMP-MANAGER", "非研发主管", user_id="manager@example.com", rd_type="非研发"),
        employee("EMP-RD", "研发员工", user_id="rd@example.com"),
    ]
    plan = build_sync_plan(
        rows,
        {"manager@example.com", "rd@example.com"},
        roles_by_user={},
        mapping={"非研发主管": "BOARD", "研发员工": "非研发主管"},
    )

    assert plan["report_updates"] == [
        {"employee": "EMP-RD", "employee_name": "研发员工", "reports_to": "EMP-MANAGER"}
    ]
    assert plan["role_additions"] == []
    assert plan["skipped_user"] == [
        {
            "employee": "EMP-MANAGER",
            "employee_name": "非研发主管",
            "user": "manager@example.com",
            "reason": "supervisor_not_rd",
        }
    ]