from types import SimpleNamespace

import pytest

from rayher_hr_payroll.maintenance import business_account_bootstrap as bootstrap


def specs_by_user():
    return {row["user_id"]: row for row in bootstrap.ACCOUNT_SPECS}


def test_account_specs_preserve_admin_system_manager_and_limit_business_executives():
    specs = specs_by_user()
    assert specs["admin@legacy-business.example.invalid"]["employee"] is None
    assert specs["person067@legacy.example.invalid"]["employee"] == "HR-EMP-90008"
    assert specs["person065@legacy.example.invalid"]["employee"] == "HR-EMP-90016"
    assert specs["person072@legacy.example.invalid"]["employee"] == "HR-EMP-90007"
    assert specs["person046@business.example.invalid"]["employee"] == "HR-EMP-90004"
    assert specs["person060@legacy.example.invalid"]["employee"] == "HR-EMP-90003"
    assert specs["person060@legacy.example.invalid"]["legacy_user_id"] == "person058@legacy.example.invalid"
    assert "person058@legacy.example.invalid" not in specs
    assert specs["admin@legacy-business.example.invalid"]["roles"] == ("System Manager",)
    for user in ("person046@business.example.invalid", "person060@legacy.example.invalid"):
        assert "System Manager" not in specs[user]["roles"]
        assert bootstrap.BUSINESS_EXECUTIVE_ROLE in specs[user]["roles"]


def test_build_account_plan_is_idempotent_and_additive():
    specs = [
        {
            "user_id": "person042@legacy.example.invalid",
            "full_name": "Person",
            "employee": "EMP-1",
            "employee_name": "Person",
            "roles": ("Employee", "Accounts User"),
        }
    ]
    plan = bootstrap.build_account_plan(
        specs,
        existing_users={"person042@legacy.example.invalid"},
        employees={"EMP-1": {"employee_name": "Person", "status": "Active", "user_id": "person042@legacy.example.invalid"}},
        roles_by_user={"person042@legacy.example.invalid": {"Employee", "Accounts User", "All"}},
        employee_by_user={"person042@legacy.example.invalid": "EMP-1"},
    )
    assert plan[0]["create_user"] is False
    assert plan[0]["link_employee"] is False
    assert plan[0]["roles_to_add"] == []
    assert plan[0]["conflicts"] == []


def test_build_account_plan_renames_legacy_user_instead_of_creating_duplicate():
    specs = [
        {
            "user_id": "person060@legacy.example.invalid",
            "legacy_user_id": "person058@legacy.example.invalid",
            "full_name": "\u6f14\u793a\u5458\u5de529",
            "employee": "HR-EMP-90003",
            "employee_name": "\u6f14\u793a\u5458\u5de529",
            "roles": ("Employee", "Rayher Business Executive"),
        }
    ]
    plan = bootstrap.build_account_plan(
        specs,
        existing_users={"person058@legacy.example.invalid"},
        employees={"HR-EMP-90003": {"employee_name": "\u6f14\u793a\u5458\u5de529", "status": "Active", "user_id": None}},
        roles_by_user={"person058@legacy.example.invalid": {"Rayher Business Executive"}},
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
            "user_id": "person042@legacy.example.invalid",
            "full_name": "Person",
            "employee": "EMP-1",
            "employee_name": "Person",
            "roles": ("Employee",),
        }
    ]
    plan = bootstrap.build_account_plan(
        specs,
        existing_users={"person042@legacy.example.invalid"},
        employees={"EMP-1": {"employee_name": "Someone Else", "status": "Active", "user_id": "history.d9298a10d1@legacy.example.invalid"}},
        roles_by_user={"person042@legacy.example.invalid": set()},
        employee_by_user={"person042@legacy.example.invalid": "EMP-2"},
    )
    assert plan[0]["conflicts"] == [
        "EMP-1 employee name does not match Person",
        "EMP-1 is already linked to history.d9298a10d1@legacy.example.invalid",
        "person042@legacy.example.invalid is already linked to EMP-2",
    ]


def test_ensure_business_accounts_dry_run_never_writes(monkeypatch):
    plan = [{"user_id": "person036@legacy.example.invalid", "conflicts": [], "create_user": True}]
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
    plan = [{"user_id": "history.2f05d4b689@legacy.example.invalid", "conflicts": ["collision"], "create_user": False}]
    monkeypatch.setattr(bootstrap, "plan_business_accounts", lambda: plan)
    monkeypatch.setattr(bootstrap, "frappe", SimpleNamespace(throw=lambda message: (_ for _ in ()).throw(ValueError(message))))

    with pytest.raises(ValueError, match="collision"):
        bootstrap.ensure_business_accounts(dry_run=False)


def test_ensure_business_accounts_renames_legacy_user_and_updates_identity(monkeypatch):
    events = []
    plan = [{
        "user_id": "person060@legacy.example.invalid",
        "legacy_user_id": "person058@legacy.example.invalid",
        "full_name": "\u6f14\u793a\u5458\u5de529",
        "conflicts": [],
        "create_user": False,
        "rename_user": True,
        "link_employee": False,
        "roles_to_add": [],
    }]

    class User:
        email = "person058@legacy.example.invalid"
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

    bootstrap.ensure_business_accounts(dry_run=False)

    assert events == [
        ("rename", "User", "person058@legacy.example.invalid", "person060@legacy.example.invalid"),
        ("save", "person060@legacy.example.invalid", "\u6f14\u793a\u5458\u5de529"),
        "commit",
    ]
