import types

from rayher_hr_payroll import lifecycle_controls as lc


class FakeEmp:
    def __init__(self, **kw):
        self.__dict__.update(
            {"status": "Active", "user_id": None, "company_email": None,
             "personal_email": None, "employee_name": "X", "name": "HR-EMP-TEST"}
        )
        self.__dict__.update(kw)
        self._db_set = []

    def db_set(self, field, value):
        self._db_set.append((field, value))
        setattr(self, field, value)


class FakeUser:
    def __init__(self, enabled=1):
        self.enabled = enabled
        self.flags = types.SimpleNamespace()
        self.roles_added = []
        self.saved = False
        self.email = None
        self.first_name = None
        self.send_welcome_email = None
        self.inserted = False
        self.name = None

    def insert(self, **k):
        self.inserted = True
        self.name = self.email

    def add_roles(self, *roles):
        self.roles_added.extend(roles)

    def save(self, **k):
        self.saved = True


def test_target_email_prefers_company_then_personal():
    assert lc._target_email(FakeEmp(company_email="a@tests-x.example.invalid", personal_email="b@tests-y.example.invalid")) == "a@tests-x.example.invalid"
    assert lc._target_email(FakeEmp(company_email=None, personal_email="b@tests-y.example.invalid")) == "b@tests-y.example.invalid"
    assert lc._target_email(FakeEmp(company_email=None, personal_email=None)) is None


def test_default_role_is_employee_only():
    assert lc.DEFAULT_EMPLOYEE_ROLES == ["Employee"]


def test_hooks_register_user_sync():
    from rayher_hr_payroll import hooks
    flat = str(hooks.doc_events["Employee"])
    assert "lifecycle_controls.sync_user_for_employee" in flat


def test_existing_user_is_never_adopted(monkeypatch):
    # Active employee, no link yet, but a User already exists for the email
    # (could be a privileged account on a reused address) -> must NOT create,
    # adopt, grant roles, or bind.
    created = []
    monkeypatch.setattr(lc.frappe, "db", types.SimpleNamespace(exists=lambda dt, name=None: dt == "User"))
    monkeypatch.setattr(lc.frappe, "new_doc", lambda *a, **k: created.append(a) or FakeUser())
    monkeypatch.setattr(lc.frappe, "get_doc", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not load existing user")))
    emp = FakeEmp(company_email="ceo@corp.example.invalid")
    lc.sync_user_for_employee(emp)
    assert created == []
    assert emp._db_set == []


def test_new_user_created_and_bound(monkeypatch):
    user = FakeUser()
    monkeypatch.setattr(lc.frappe, "db", types.SimpleNamespace(exists=lambda dt, name=None: False))
    monkeypatch.setattr(lc.frappe, "new_doc", lambda *a, **k: user)
    monkeypatch.setattr(lc.frappe, "get_doc", lambda d: types.SimpleNamespace(insert=lambda **k: None))
    emp = FakeEmp(company_email="newhire@corp.example.invalid", employee_name="新人")
    lc.sync_user_for_employee(emp)
    assert user.inserted and user.roles_added == ["Employee"]
    assert emp._db_set == [("user_id", "newhire@corp.example.invalid")]


def test_linked_user_disabled_on_left(monkeypatch):
    user = FakeUser(enabled=1)
    monkeypatch.setattr(lc.frappe, "db", types.SimpleNamespace(exists=lambda *a, **k: True))
    monkeypatch.setattr(lc.frappe, "get_doc", lambda *a, **k: user)
    lc.sync_user_for_employee(FakeEmp(status="Left", user_id="e@tests-x.example.invalid"))
    assert user.enabled == 0 and user.saved


def test_linked_user_reenabled_on_rehire(monkeypatch):
    user = FakeUser(enabled=0)
    monkeypatch.setattr(lc.frappe, "db", types.SimpleNamespace(exists=lambda *a, **k: True))
    monkeypatch.setattr(lc.frappe, "get_doc", lambda *a, **k: user)
    lc.sync_user_for_employee(FakeEmp(status="Active", user_id="e@tests-x.example.invalid"))
    assert user.enabled == 1 and user.saved


def test_new_user_gets_own_employee_user_permission(monkeypatch):
    # The auto-provisioned login must be scoped to its own Employee record.
    import types
    import rayher_hr_payroll.lifecycle_controls as lc

    inserted = []

    class FakeUser:
        def __init__(self): self.flags = types.SimpleNamespace(); self.name = None; self.roles_added = []
        def insert(self, **k): self.name = "newhire@corp.example.invalid"
        def add_roles(self, *r): self.roles_added.extend(r)

    user = FakeUser()
    monkeypatch.setattr(lc.frappe, "db", types.SimpleNamespace(exists=lambda *a, **k: False))
    monkeypatch.setattr(lc.frappe, "new_doc", lambda *a, **k: user)
    monkeypatch.setattr(lc.frappe, "get_doc", lambda d: inserted.append(d) or types.SimpleNamespace(insert=lambda **k: None))
    emp = FakeEmp(company_email="newhire@corp.example.invalid", employee_name="新人")
    emp.name = "HR-EMP-9001"
    lc.sync_user_for_employee(emp)
    ups = [d for d in inserted if d.get("doctype") == "User Permission"]
    assert ups and ups[0]["allow"] == "Employee" and ups[0]["for_value"] == "HR-EMP-9001"
