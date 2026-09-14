from types import SimpleNamespace
import sys

import pytest

from rayher_hr_payroll import position_access, oa_approval, oa_organization
from rayher_hr_payroll.oa_role_resolver import ApprovalRoleResolutionError


def test_position_handover_updates_permissions_and_new_routes_only(monkeypatch):
    incumbent = {"user": "old@example.com"}
    def resolve(key):
        return {"role_key": key, "role_label": key, "employee_name": key,
                "user": incumbent["user"] if key == "hr_manager" else key + "@example.com"}
    monkeypatch.setattr(position_access, "resolve_role", resolve)
    monkeypatch.setattr(oa_approval, "resolve_role", resolve)
    old = oa_approval.build_expense_payment_route("研发部", "主管", oa_approval.ADMIN_ASSET, supervisor_user="supervisor@example.com")
    assert "old@example.com" in position_access.position_users("hr_manager")
    incumbent["user"] = "new@example.com"
    new = oa_approval.build_expense_payment_route("研发部", "主管", oa_approval.ADMIN_ASSET, supervisor_user="supervisor@example.com")
    assert "old@example.com" not in position_access.position_users("hr_manager")
    assert "new@example.com" in position_access.position_users("hr_manager")
    assert old[2]["approvers"] == ["old@example.com"]
    assert new[2]["approvers"] == ["new@example.com"]


def test_missing_position_never_falls_back_to_a_person(monkeypatch):
    def missing(key):
        raise ApprovalRoleResolutionError("position unassigned")
    monkeypatch.setattr(position_access, "resolve_role", missing)
    monkeypatch.setattr(oa_approval, "resolve_role", missing)
    assert position_access.position_users("hr_manager") == set()
    with pytest.raises((ApprovalRoleResolutionError, oa_approval.ApprovalRouteError)):
        oa_approval.build_expense_payment_route("研发部", "主管")


def test_supervisor_relationship_comes_from_employee_records(monkeypatch):
    rows = [
        SimpleNamespace(name="E1", employee_name="员工", reports_to="E2"),
        SimpleNamespace(name="E2", employee_name="新主管", reports_to=None),
    ]
    monkeypatch.setitem(sys.modules, "frappe", SimpleNamespace(get_all=lambda *a, **k: rows))
    assert position_access.current_supervisors()["员工"] == "新主管"
    monkeypatch.setattr(oa_organization, "executive_names", lambda: {"总经理"})
    result = oa_organization.resolve_stage_two_supervisor("员工", lambda name: name + "@example.com")
    assert result.supervisor_name == "新主管"
