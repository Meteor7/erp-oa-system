from pathlib import Path


def test_rayher_is_registered_as_app_entry():
    from rayher_hr_payroll import hooks

    entry = hooks.add_to_apps_screen[0]
    assert entry["name"] == "rayher_hr_payroll"
    assert entry["route"] == "/rayher"
    assert entry["title"] == "Rayher"


def test_install_sets_rayher_as_default_app():
    source = Path("rayher_hr_payroll/install.py").read_text(encoding="utf-8")

    assert "ensure_default_rayher_app()" in source
    assert "default_app" in source
    assert "rayher_hr_payroll" in source


def test_new_employee_users_default_to_rayher():
    source = Path("rayher_hr_payroll/lifecycle_controls.py").read_text(encoding="utf-8")

    assert "RAYHER_DEFAULT_APP" in source
    assert "user.default_app = RAYHER_DEFAULT_APP" in source
