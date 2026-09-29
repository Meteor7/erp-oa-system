from types import SimpleNamespace

import pytest

from rayher_hr_payroll.maintenance import business_account_bootstrap as bootstrap


def specs_by_user():
    return {row["user_id"]: row for row in bootstrap.ACCOUNT_SPECS}


def test_account_specs_preserve_admin_system_manager_and_limit_business_executives():
    specs = specs_by_user()
    assert specs["admin@staff.example.invalid"]["employee"] is None
    assert specs["person067@staff.example.invalid"]["employee"] == "HR-EMP-90008"
    assert specs["person065@staff.example.invalid"]["employee"] == "HR-EMP-90016"
    assert specs["person072@staff.example.invalid"]["employee"] == "HR-EMP-90007"
    assert specs["person047@staff.example.invalid"]["employee"] == "HR-EMP-90011"
    assert specs["person068@staff.example.invalid"]["employee"] == "HR-EMP-90012"
    assert "Department Manager" in specs["person047@staff.example.invalid"]["roles"]
    assert "Department Manager" in specs["person068@staff.example.invalid"]["roles"]
    assert specs["person046@staff.example.invalid"]["employee"] == "HR-EMP-90004"
    assert specs["person046@staff.example.invalid"]["legacy_user_id"] == "person046@business.example.invalid"
    assert specs["person060@staff.example.invalid"]["employee"] == "HR-EMP-90003"
    assert specs["person060@staff.example.invalid"]["legacy_user_id"] == "person058@staff.example.invalid"
    assert "person058@staff.example.invalid" not in specs
    assert specs["admin@staff.example.invalid"]["roles"] == ("System Manager",)
    for user in ("person046@staff.example.invalid", "person060@staff.example.invalid"):
        assert "System Manager" not in specs[user]["roles"]
        assert bootstrap.BUSINESS_EXECUTIVE_ROLE in specs[user]["roles"]


def test_active_employee_account_specs_use_stable_temporary_login_names():
    rows = [
        {"name": "HR-EMP-90009", "employee_name": "演示员工158", "user_id": ""},
        {"name": "HR-EMP-90010", "employee_name": "已有账号", "user_id": "user@example.com"},
    ]

    assert bootstrap.active_employee_account_specs(rows) == [{
        "user_id": "person018@staff.example.invalid",
        "full_name": "演示员工158",
        "employee": "HR-EMP-90009",
        "employee_name": "演示员工158",
        "roles": ("Employee",),
    }]


def test_build_account_plan_is_idempotent_and_additive():
    specs = [
        {
            "user_id": "person042@staff.example.invalid",
            "full_name": "Person",
            "employee": "EMP-1",
            "employee_name": "Person",
            "roles": ("Employee", "Accounts User"),
        }
    ]
    plan = bootstrap.build_account_plan(
        specs,
        existing_users={"person042@staff.example.invalid"},
        employees={"EMP-1": {"employee_name": "Person", "status": "Active", "user_id": "person042@staff.example.invalid"}},
        roles_by_user={"person042@staff.example.invalid": {"Employee", "Accounts User", "All"}},
        employee_by_user={"person042@staff.example.invalid": "EMP-1"},
    )
    assert plan[0]["create_user"] is False
    assert plan[0]["link_employee"] is False
    assert plan[0]["roles_to_add"] == []
    assert plan[0]["conflicts"] == []


def test_build_account_plan_renames_legacy_user_instead_of_creating_duplicate():
    specs = [
        {
            "user_id": "person060@staff.example.invalid",
            "legacy_user_id": "person058@staff.example.invalid",
            "full_name": "\u6f14\u793a\u5458\u5de529",
            "employee": "HR-EMP-90003",
            "employee_name": "\u6f14\u793a\u5458\u5de529",
            "roles": ("Employee", "Rayher Business Executive"),
        }
    ]
    plan = bootstrap.build_account_plan(
        specs,
        existing_users={"person058@staff.example.invalid"},
        employees={"HR-EMP-90003": {"employee_name": "\u6f14\u793a\u5458\u5de529", "status": "Active", "user_id": None}},
        roles_by_user={"person058@staff.example.invalid": {"Rayher Business Executive"}},
        employee_by_user={},
    )

    assert plan[0]["create_user"] is False
    assert plan[0]["rename_user"] is True
    assert plan[0]["roles_to_add"] == ["Employee"]
    assert plan[0]["link_employee"] is True
    assert plan[0]["conflicts"] == []


def test_build_account_plan_reports_link_and_identity_conflicts_before_writes():
    specs = [
        {
            "user_id": "person042@staff.example.invalid",
            "full_name": "Person",
            "employee": "EMP-1",
            "employee_name": "Person",
            "roles": ("Employee",),
        }
    ]
    plan = bootstrap.build_account_plan(
        specs,
        existing_users={"person042@staff.example.invalid"},
        employees={"EMP-1": {"employee_name": "Someone Else", "status": "Active", "user_id": "person040@staff.example.invalid"}},
        roles_by_user={"person042@staff.example.invalid": set()},
        employee_by_user={"person042@staff.example.invalid": "EMP-2"},
    )
    assert plan[0]["conflicts"] == [
        "EMP-1 employee name does not match Person",
        "EMP-1 is already linked to person040@staff.example.invalid",
        "person042@staff.example.invalid is already linked to EMP-2",
    ]


def test_ensure_business_accounts_dry_run_never_writes(monkeypatch):
    plan = [{"user_id": "person036@staff.example.invalid", "conflicts": [], "create_user": True}]
    calls = []
    monkeypatch.setattr(bootstrap, "plan_business_accounts", lambda: plan)
    monkeypatch.setattr(
        bootstrap,
        "frappe",
        SimpleNamespace(
            new_doc=lambda *_args: calls.append("new_doc"),
            db=SimpleNamespace(commit=lambda: calls.append("commit"), rollback=lambda: calls.append("rollback")),
        ),
    )

    result = bootstrap.ensure_business_accounts(dry_run=True)

    assert result == {"dry_run": True, "count": 1, "accounts": plan, "created_credentials": []}
    assert calls == []


def test_ensure_business_accounts_aborts_on_preflight_conflict(monkeypatch):
    plan = [{"user_id": "person004@staff.example.invalid", "conflicts": ["collision"], "create_user": False}]
    monkeypatch.setattr(bootstrap, "plan_business_accounts", lambda: plan)
    monkeypatch.setattr(bootstrap, "frappe", SimpleNamespace(throw=lambda message: (_ for _ in ()).throw(ValueError(message))))

    with pytest.raises(ValueError, match="collision"):
        bootstrap.ensure_business_accounts(dry_run=False)


def test_ensure_business_accounts_renames_legacy_user_and_updates_identity(monkeypatch):
    events = []
    plan = [{
        "user_id": "person060@staff.example.invalid",
        "legacy_user_id": "person058@staff.example.invalid",
        "full_name": "\u6f14\u793a\u5458\u5de529",
        "conflicts": [],
        "create_user": False,
        "rename_user": True,
        "link_employee": False,
        "roles_to_add": [],
    }]

    class User:
        email = "person058@staff.example.invalid"
        first_name = "\u6f14\u793a\u5458\u5de528"
        middle_name = None
        last_name = None

        def save(self, **_kwargs):
            events.append(("save", self.email, self.first_name))

    monkeypatch.setattr(bootstrap, "plan_business_accounts", lambda: plan)
    monkeypatch.setattr(
        bootstrap,
        "frappe",
        SimpleNamespace(
            rename_doc=lambda doctype, old, new, **_kwargs: events.append(("rename", doctype, old, new)),
            get_doc=lambda doctype, name: User(),
            db=SimpleNamespace(commit=lambda: events.append("commit"), rollback=lambda: events.append("rollback")),
        ),
    )

    from rayher_hr_payroll.maintenance import account_domain_migration

    monkeypatch.setattr(account_domain_migration, "rewrite_user_references", lambda mapping: events.append(("rewrite", mapping)))
    bootstrap.ensure_business_accounts(dry_run=False)

    # 审查 X3-3：改名后同步改审批记录里的账号，再提交。
    assert events == [
        ("rename", "User", "person058@staff.example.invalid", "person060@staff.example.invalid"),
        ("save", "person060@staff.example.invalid", "\u6f14\u793a\u5458\u5de529"),
        ("rewrite", {"person058@staff.example.invalid": "person060@staff.example.invalid"}),
        "commit",
    ]
