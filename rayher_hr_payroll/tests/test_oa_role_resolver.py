import json
from pathlib import Path

import pytest

from rayher_hr_payroll.oa_role_resolver import (
    ApprovalRoleResolutionError,
    ROLE_SPECS,
    bootstrap_pmc,
    resolve_role,
)


class MemoryStore:
    def __init__(self):
        self.assignments = {}
        self.by_designation = {}
        self.enabled_users = set()
        self.employees = {}
        self.users = {}
        self.created_users = []
        self.bindings = []
        self.saved_assignments = []

    def get_assignment(self, role_key):
        return self.assignments.get(role_key)

    def employees_for_designation(self, designation):
        return list(self.by_designation.get(designation, []))

    def is_user_enabled(self, user):
        return user in self.enabled_users

    def get_employee(self, employee):
        return self.employees.get(employee)

    def get_user(self, user):
        return self.users.get(user)

    def create_user(self, values):
        self.created_users.append(dict(values))
        self.users[values["email"]] = {**values, "enabled": 1}
        self.enabled_users.add(values["email"])

    def bind_employee_user(self, employee, user):
        self.bindings.append((employee, user))
        self.employees[employee]["user_id"] = user

    def upsert_assignment(self, role_key, role_label, employee, user):
        row = {
            "role_key": role_key,
            "role_label": role_label,
            "employee": employee,
            "user": user,
            "enabled": 1,
        }
        self.assignments[role_key] = row
        self.saved_assignments.append(row)


def employee(name="EMP-1", employee_name="演示员工16", user="zhang@example.com", designation="财务主管"):
    return {
        "name": name,
        "employee_name": employee_name,
        "user_id": user,
        "designation": designation,
        "status": "Active",
    }


def test_designation_role_resolves_unique_active_employee_snapshot():
    store = MemoryStore()
    row = employee()
    store.by_designation["财务主管"] = [row]
    store.enabled_users.add("zhang@example.com")
    assert resolve_role("finance_manager", store=store) == {
        "role_key": "finance_manager",
        "role_label": "财务主管",
        "user": "zhang@example.com",
        "employee": "EMP-1",
        "employee_name": "演示员工16",
    }


def test_pmc_requires_explicit_role_assignment_and_preserves_role_label():
    store = MemoryStore()
    store.assignments["pmc"] = {
        "role_key": "pmc", "role_label": "PMC", "employee": "EMP-PMC",
        "employee_name": "演示员工178", "user": "pmc@example.com", "enabled": 1,
    }
    store.enabled_users.add("pmc@example.com")
    assert resolve_role("pmc", store=store)["user"] == "pmc@example.com"
    assert resolve_role("pmc", store=store)["role_label"] == "PMC"


def test_missing_disabled_and_duplicate_role_holders_block_submission():
    store = MemoryStore()
    with pytest.raises(ApprovalRoleResolutionError, match="财务主管.*没有找到"):
        resolve_role("finance_manager", store=store)
    store.by_designation["财务主管"] = [employee()]
    with pytest.raises(ApprovalRoleResolutionError, match="账号未启用"):
        resolve_role("finance_manager", store=store)
    store.by_designation["财务主管"] = [employee(), employee("EMP-2", "财务主管二", "two@example.com")]
    store.enabled_users.update({"zhang@example.com", "two@example.com"})
    with pytest.raises(ApprovalRoleResolutionError, match="找到多个"):
        resolve_role("finance_manager", store=store)


def test_designation_role_ignores_people_without_an_enabled_account():
    store = MemoryStore()
    eligible = employee()
    unbound = employee("EMP-2", "未绑定账号", "")
    disabled = employee("EMP-3", "停用账号", "disabled@example.com")
    store.by_designation["财务主管"] = [eligible, unbound, disabled]
    store.enabled_users.add("zhang@example.com")

    assert resolve_role("finance_manager", store=store)["employee"] == "EMP-1"


def test_unknown_role_key_is_rejected():
    with pytest.raises(ApprovalRoleResolutionError, match="未知审批角色"):
        resolve_role("unknown", store=MemoryStore())


def test_bootstrap_pmc_creates_account_binds_employee_and_is_idempotent():
    store = MemoryStore()
    store.employees["HR-EMP-90017"] = {
        "name": "HR-EMP-90017", "employee_name": "演示员工178", "status": "Active", "user_id": "",
    }
    first = bootstrap_pmc(store=store)
    assert first["user"] == "person076@staff.example.invalid"
    assert store.created_users == [{
        "email": "person076@staff.example.invalid",
        "first_name": "演示员工178",
        "enabled": 1,
        "send_welcome_email": 0,
        "roles": ["Employee"],
    }]
    assert store.bindings == [("HR-EMP-90017", "person076@staff.example.invalid")]
    assert store.saved_assignments[-1]["role_key"] == "pmc"

    second = bootstrap_pmc(store=store)
    assert second == first
    assert len(store.created_users) == 1
    assert len(store.bindings) == 1


def test_bootstrap_refuses_wrong_or_inactive_employee():
    store = MemoryStore()
    store.employees["HR-EMP-90017"] = {
        "name": "HR-EMP-90017", "employee_name": "其他人", "status": "Active", "user_id": "",
    }
    with pytest.raises(ApprovalRoleResolutionError, match="演示员工178"):
        bootstrap_pmc(store=store)


def test_role_assignment_doctype_has_unique_role_and_user_links():
    root = Path(__file__).resolve().parents[2]
    path = root / "rayher_hr_payroll" / "rayher_hr_payroll" / "doctype" / "oa_approval_role_assignment" / "oa_approval_role_assignment.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = {row["fieldname"]: row for row in data["fields"]}
    assert data["field_order"] == [row["fieldname"] for row in data["fields"]]
    assert fields["role_key"]["unique"] == 1
    assert fields["user"]["options"] == "User"
    assert fields["employee"]["options"] == "Employee"
    assert set(ROLE_SPECS) == {
        "pmc", "hr_manager", "finance_auditor", "finance_manager",
        "vice_manager", "general_manager", "production_asset_owner",
    }
