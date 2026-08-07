from pathlib import Path


def test_planck_is_registered_as_visible_app_entry_without_renaming_internal_app():
    from rayher_hr_payroll import hooks

    entry = hooks.add_to_apps_screen[0]
    assert entry["name"] == "rayher_hr_payroll"
    assert entry["route"] == "/planck-semicon"
    assert entry["title"] == "QIHENG DEMO"
    routes = {(rule["from_route"], rule["to_route"]) for rule in hooks.website_route_rules}
    assert ("/planck-semicon", "rayher") in routes
    assert ("/planck-semicon/<path:app_path>", "rayher") in routes
    assert ("/rayher/<path:app_path>", "rayher") in routes


def test_guest_login_returns_to_planck_visible_route():
    source = Path("rayher_hr_payroll/www/rayher.py").read_text(encoding="utf-8")

    assert 'redirect_location = "/login?redirect-to=/planck-semicon"' in source
    assert 'redirect_location = "/login?redirect-to=/rayher"' not in source


def test_install_sets_rayher_as_default_app():
    source = Path("rayher_hr_payroll/install.py").read_text(encoding="utf-8")

    assert "ensure_default_rayher_app()" in source
    assert "default_app" in source
    assert "rayher_hr_payroll" in source


def test_new_employee_users_default_to_rayher():
    source = Path("rayher_hr_payroll/lifecycle_controls.py").read_text(encoding="utf-8")

    assert "RAYHER_DEFAULT_APP" in source
    assert "user.default_app = RAYHER_DEFAULT_APP" in source
