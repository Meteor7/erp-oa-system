from pathlib import Path
from types import SimpleNamespace

import rayher_hr_payroll.maintenance.user_account_migration as mod


def romanize(value):
    mapping = {
        "演示员工132": ["zhang", "jun"],
        "演示员工133": ["zhang", "jun"],
        "Sabri K.": ["Sabri", " ", "K", "."],
    }
    return mapping[value]


def test_user_account_migration_module_exists():
    assert Path("rayher_hr_payroll/maintenance/user_account_migration.py").is_file()


def test_build_username_uses_lowercase_full_pinyin():
    assert mod.build_username("演示员工132", "HR-EMP-90005", set(), romanize=romanize) == "person070@staff.example.invalid"


def test_build_username_adds_employee_suffix_for_collision():
    used = {"person070@staff.example.invalid"}
    assert mod.build_username("演示员工133", "HR-EMP-90023", used, romanize=romanize) == "person071@staff.example.invalid"


def test_build_username_keeps_ascii_name_characters_only():
    assert mod.build_username("Sabri K.", "HR-EMP-90021", set(), romanize=romanize) == "person048@staff.example.invalid"


def test_generated_account_filter_is_narrow():
    assert mod.is_generated_rd_user("person017@staff.example.invalid") is True
    assert mod.is_generated_rd_user("person069@legacy-business.example.invalid") is False
    assert mod.is_generated_rd_user("Administrator") is False


def test_build_rename_plan_targets_only_active_generated_accounts():
    employees = [
        {"name": "HR-EMP-90005", "employee_name": "演示员工132", "user_id": "person017@staff.example.invalid", "status": "Active"},
        {"name": "HR-EMP-90023", "employee_name": "演示员工133", "user_id": "person020@staff.example.invalid", "status": "Active"},
        {"name": "HR-EMP-90021", "employee_name": "Sabri K.", "user_id": "sabri@example.com", "status": "Active"},
        {"name": "HR-EMP-90022", "employee_name": "演示员工132", "user_id": "person019@staff.example.invalid", "status": "Left"},
    ]

    result = mod.build_rename_plan(employees, {"Administrator"}, romanize=romanize)

    assert result == [
        {
            "employee": "HR-EMP-90005",
            "employee_name": "演示员工132",
            "old_user": "person017@staff.example.invalid",
            "new_user": "person070@staff.example.invalid",
        },
        {
            "employee": "HR-EMP-90023",
            "employee_name": "演示员工133",
            "old_user": "person020@staff.example.invalid",
            "new_user": "person071@staff.example.invalid",
        },
    ]


def test_rename_generated_users_supports_dry_run(monkeypatch):
    planned = [{"employee": "HR-EMP-90005", "old_user": "person038@staff.example.invalid", "new_user": "person036@staff.example.invalid"}]
    monkeypatch.setattr(mod, "plan_generated_rd_user_renames", lambda: planned)
    renamed = []
    monkeypatch.setattr(mod, "frappe", SimpleNamespace(rename_doc=lambda *args, **kwargs: renamed.append((args, kwargs))))

    result = mod.rename_generated_rd_users(dry_run=True)

    assert result == {"dry_run": True, "count": 1, "mappings": planned}
    assert renamed == []


def test_pypinyin_is_declared_as_an_app_dependency():
    source = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "pypinyin" in source
