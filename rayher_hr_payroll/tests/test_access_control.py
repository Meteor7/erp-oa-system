from rayher_hr_payroll.access_control import CUSTOM_ROLES, ROLE_PROFILES


def test_department_manager_role_declared():
    names = [r["role_name"] for r in CUSTOM_ROLES]
    assert "Department Manager" in names


def test_owner_role_profile_bundles_required_roles():
    profiles = {p["role_profile"]: p for p in ROLE_PROFILES}
    assert "总控 Owner" in profiles, "Owner role profile must exist"
    owner_roles = profiles["总控 Owner"]["roles"]
    for role in ("System Manager", "HR Manager", "Accounts User", "Department Manager"):
        assert role in owner_roles


def test_role_profile_roles_are_unique():
    for p in ROLE_PROFILES:
        assert len(p["roles"]) == len(set(p["roles"])), p["role_profile"]


def test_install_calls_ensure_access_control():
    import inspect
    import rayher_hr_payroll.install as install
    src = inspect.getsource(install)
    assert "ensure_access_control" in src
