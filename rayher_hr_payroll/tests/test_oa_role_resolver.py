import json
from pathlib import Path

import pytest

from rayher_hr_payroll.oa_role_resolver import (
    ApprovalRoleResolutionError,
    ROLE_SPECS,
    bootstrap_pmc,
    bootstrap_procurement_manager,
    designation_suggestion,
    resolve_role,
    seed_missing_assignments,
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
        self.ensured_roles = []
        self.ensured_permissions = []

    def get_assignment(self, role_key):
        return self.assignments.get(role_key)

    def assignment_exists(self, role_key):
        return role_key in self.assignments

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

    def ensure_user_roles(self, user, roles):
        self.ensured_roles.append((user, list(roles)))

    def ensure_employee_permissions(self, employee, user):
        self.ensured_permissions.append((employee, user))

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


def test_designation_only_suggests_a_holder_and_never_grants_approval():
    # 审查 R3-55-2（决定 D4）：改职务不能让人成为审批人，只有岗位任命算数。
    store = MemoryStore()
    row = employee()
    store.by_designation["财务主管"] = [row]
    store.enabled_users.add("zhang@example.com")
    with pytest.raises(ApprovalRoleResolutionError, match="没有找到有效配置"):
        resolve_role("finance_manager", store=store)
    assert designation_suggestion("finance_manager", store=store) == {
        "role_key": "finance_manager",
        "role_label": "财务主管",
        "user": "zhang@example.com",
        "employee": "EMP-1",
        "employee_name": "演示员工16",
    }


def test_hr_manager_uses_ordered_designation_fallback():
    store = MemoryStore()
    current = employee("EMP-HR-OLD", "演示员工10", "old@example.com", "人事行政经理")
    successor = employee("EMP-HR-NEW", "演示员工38", "new@example.com", "人事经理")
    store.by_designation["人事行政经理"] = [current]
    store.by_designation["人事经理"] = [successor]
    store.enabled_users.update({"old@example.com", "new@example.com"})

    assert designation_suggestion("hr_manager", store=store)["employee"] == "EMP-HR-OLD"

    store.by_designation["人事行政经理"] = []
    assert designation_suggestion("hr_manager", store=store)["employee"] == "EMP-HR-NEW"


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
    store.assignments["finance_manager"] = {
        "role_key": "finance_manager", "role_label": "财务主管", "employee": "EMP-1",
        "employee_name": "演示员工16", "user": "zhang@example.com", "enabled": 1,
    }
    with pytest.raises(ApprovalRoleResolutionError, match="账号未启用"):
        resolve_role("finance_manager", store=store)
    store.by_designation["财务主管"] = [employee(), employee("EMP-2", "财务主管二", "two@example.com")]
    store.enabled_users.update({"zhang@example.com", "two@example.com"})
    with pytest.raises(ApprovalRoleResolutionError, match="找到多个"):
        designation_suggestion("finance_manager", store=store)


def test_designation_role_ignores_people_without_an_enabled_account():
    store = MemoryStore()
    eligible = employee()
    unbound = employee("EMP-2", "未绑定账号", "")
    disabled = employee("EMP-3", "停用账号", "disabled@example.com")
    store.by_designation["财务主管"] = [eligible, unbound, disabled]
    store.enabled_users.add("zhang@example.com")

    assert designation_suggestion("finance_manager", store=store)["employee"] == "EMP-1"


def test_unknown_role_key_is_rejected():
    with pytest.raises(ApprovalRoleResolutionError, match="未知审批角色"):
        resolve_role("unknown", store=MemoryStore())


@pytest.mark.parametrize("bootstrap", [bootstrap_pmc, bootstrap_procurement_manager])
def test_bootstrap_without_config_does_not_recreate_predecessor(bootstrap):
    store = MemoryStore()
    with pytest.raises(ApprovalRoleResolutionError):
        bootstrap(store=store)
    assert store.created_users == []
    assert store.bindings == []


def test_bootstrap_pmc_keeps_the_configured_successor():
    store = MemoryStore()
    store.assignments["pmc"] = {
        "role_key": "pmc", "role_label": "PMC", "employee": "NEW-PMC",
        "employee_name": "接任人", "user": "successor@example.com", "enabled": 1,
    }
    store.enabled_users.add("successor@example.com")
    result = bootstrap_pmc(store=store)
    assert result["user"] == "successor@example.com"
    assert store.created_users == []
    assert store.saved_assignments == []
    assert store.ensured_permissions == [("NEW-PMC", "successor@example.com")]


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
        "pmc", "hr_manager", "finance_auditor", "finance_accountant", "finance_manager",
        "vice_manager", "general_manager", "production_asset_owner",
        "procurement_manager", "it_asset_owner", "front_desk",
    }

def test_hr_assignment_overrides_designation_until_employee_profile_is_available():
    store = MemoryStore()
    store.by_designation["人事经理"] = [employee(user="other@example.com")]
    store.assignments["hr_manager"] = {
        "role_key": "hr_manager", "role_label": "人事经理", "employee": "",
        "employee_name": "William Liu", "user": "liuwilliam@example.com", "enabled": 1,
    }
    store.enabled_users.update({"other@example.com", "liuwilliam@example.com"})
    assert resolve_role("hr_manager", store=store)["user"] == "liuwilliam@example.com"
    assert resolve_role("hr_manager", store=store)["employee"] == ""
    store.enabled_users.remove("liuwilliam@example.com")
    with pytest.raises(ApprovalRoleResolutionError, match="账号未启用"):
        resolve_role("hr_manager", store=store)


def test_seed_fills_only_positions_without_any_assignment():
    # 新站点：没有任何任命的岗位按职务补建一次；已有（包括停用的）任命不动；职务后来再变不影响审批人。
    store = MemoryStore()
    store.by_designation["出纳"] = [employee(user="first@example.com")]
    store.by_designation["财务主管"] = [employee("EMP-FM", "主管", "fm@example.com")]
    store.enabled_users.update({"first@example.com", "second@example.com", "fm@example.com"})
    store.assignments["finance_manager"] = {"role_key": "finance_manager", "user": "keep@example.com", "enabled": 0}
    assert seed_missing_assignments(store=store) == ["finance_auditor"]
    assert store.assignments["finance_manager"]["user"] == "keep@example.com"
    assert resolve_role("finance_auditor", store=store)["user"] == "first@example.com"
    store.by_designation["出纳"] = [employee(user="second@example.com")]
    assert resolve_role("finance_auditor", store=store)["user"] == "first@example.com"
