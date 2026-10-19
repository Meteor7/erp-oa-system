from rayher_hr_payroll.access_control import CUSTOM_ROLES, ROLE_PROFILES


def test_department_manager_role_declared():
    names = [r["role_name"] for r in CUSTOM_ROLES]
    assert "Department Manager" in names


def test_project_scope_roles_declared():
    names = [r["role_name"] for r in CUSTOM_ROLES]
    assert "Project Owner" in names
    assert "All Project Access" in names


def test_owner_role_profile_bundles_required_roles():
    profiles = {p["role_profile"]: p for p in ROLE_PROFILES}
    assert "总控 Owner" in profiles, "Owner role profile must exist"
    owner_roles = profiles["总控 Owner"]["roles"]
    for role in (
        "System Manager",
        "HR Manager",
        "Accounts User",
        "Department Manager",
        "Employee",
        "All Project Access",
        "QIHENG Demo Business Executive",
    ):
        assert role in owner_roles


def test_role_profile_roles_are_unique():
    for p in ROLE_PROFILES:
        assert len(p["roles"]) == len(set(p["roles"])), p["role_profile"]


def test_install_calls_ensure_access_control():
    import inspect
    import rayher_hr_payroll.install as install
    src = inspect.getsource(install)
    assert "ensure_access_control" in src


def test_install_backfills_project_owner_accounts():
    import inspect
    import rayher_hr_payroll.install as install
    src = inspect.getsource(install._sync_app)
    assert "backfill_project_owner_accounts" in src


def test_role_profile_idempotent_no_save_when_roles_match(monkeypatch):
    """On a migrate re-run with the profile already correct, do NOT save —
    saving triggers update_all_users which would reset assigned users' roles."""
    import types
    import rayher_hr_payroll.access_control as ac

    saved = []

    class Row:
        def __init__(self, role):
            self.role = role

    class FakeDoc:
        def __init__(self, name, roles):
            self.name = name
            self.roles = [Row(r) for r in roles]

        def set(self, field, val):
            self.roles = []

        def append(self, field, val):
            self.roles.append(Row(val["role"]))

        def save(self, **k):
            saved.append(self.name)

    docs = {
        profile["role_profile"]: FakeDoc(profile["role_profile"], profile["roles"])
        for profile in ac.ROLE_PROFILES
    }
    monkeypatch.setattr(ac.frappe, "db", types.SimpleNamespace(exists=lambda *a, **k: True))
    monkeypatch.setattr(ac.frappe, "get_doc", lambda _doctype, name: docs[name])
    ac._ensure_role_profiles()
    assert saved == []


def test_role_profile_rebuilds_when_roles_differ(monkeypatch):
    import types
    import rayher_hr_payroll.access_control as ac

    saved = []

    class Row:
        def __init__(self, role):
            self.role = role

    class FakeDoc:
        def __init__(self, name, roles):
            self.name = name
            self.roles = [Row(r) for r in roles]

        def set(self, field, val):
            self.roles = []

        def append(self, field, val):
            self.roles.append(Row(val["role"]))

        def save(self, **k):
            saved.append(self.name)

    target = ac.ROLE_PROFILES[0]["role_profile"]
    docs = {
        profile["role_profile"]: FakeDoc(
            profile["role_profile"],
            ["System Manager"] if profile["role_profile"] == target else profile["roles"],
        )
        for profile in ac.ROLE_PROFILES
    }
    monkeypatch.setattr(ac.frappe, "db", types.SimpleNamespace(exists=lambda *a, **k: True))
    monkeypatch.setattr(ac.frappe, "get_doc", lambda _doctype, name: docs[name])
    ac._ensure_role_profiles()
    assert saved == [target]


def test_custom_role_reconciles_stale_flags(monkeypatch):
    """Existing role with wrong desk_access gets reconciled (declarative config)."""
    import types
    import rayher_hr_payroll.access_control as ac

    saved = []

    class FakeRole:
        def __init__(self, **kw):
            self._d = kw

        def get(self, k):
            return self._d.get(k)

        def set(self, k, v):
            self._d[k] = v

        def save(self, **k):
            saved.append(dict(self._d))

    role = FakeRole(role_name="Department Manager", desk_access=0)
    monkeypatch.setattr(ac.frappe, "db", types.SimpleNamespace(exists=lambda *a, **k: True))
    monkeypatch.setattr(ac.frappe, "get_doc", lambda *a, **k: role)
    ac._ensure_custom_roles()
    assert saved and saved[0]["desk_access"] == 1


def test_custom_role_no_save_when_flags_match(monkeypatch):
    import types
    import rayher_hr_payroll.access_control as ac

    saved = []

    class FakeRole:
        def __init__(self, **kw):
            self._d = kw

        def get(self, k):
            return self._d.get(k)

        def set(self, k, v):
            self._d[k] = v

        def save(self, **k):
            saved.append(True)

    role = FakeRole(role_name="Department Manager", desk_access=1)
    monkeypatch.setattr(ac.frappe, "db", types.SimpleNamespace(exists=lambda *a, **k: True))
    monkeypatch.setattr(ac.frappe, "get_doc", lambda *a, **k: role)
    ac._ensure_custom_roles()
    assert saved == []


def test_link_targets_created_before_install_and_migrate():
    # Role + workflow masters must exist before Frappe syncs the reports/workflow/
    # workspaces that reference them -- on BOTH fresh install and existing-site migrate.
    import inspect
    import rayher_hr_payroll.install as install
    from rayher_hr_payroll import hooks
    assert hooks.before_install == "rayher_hr_payroll.install.ensure_link_targets"
    assert hooks.before_migrate == "rayher_hr_payroll.install.ensure_link_targets"
    src = inspect.getsource(install.ensure_link_targets)
    assert "ensure_access_control" in src and "ensure_workflow_masters" in src


def test_business_executive_role_is_business_wide_but_not_system_admin():
    import rayher_hr_payroll.access_control as ac

    assert ac.BUSINESS_EXECUTIVE_ROLE in {row["role_name"] for row in ac.CUSTOM_ROLES}
    profile = next(
        row for row in ac.ROLE_PROFILES
        if row["role_profile"] == ac.BUSINESS_EXECUTIVE_ROLE
    )
    assert {
        "Employee",
        "HR Manager",
        "Accounts User",
        "Department Manager",
        "All Project Access",
        ac.BUSINESS_EXECUTIVE_ROLE,
    } <= set(profile["roles"])
    assert "System Manager" not in profile["roles"]
