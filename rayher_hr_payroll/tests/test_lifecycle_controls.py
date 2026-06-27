import types
from rayher_hr_payroll import lifecycle_controls as lc


class FakeEmp(dict):
    def __getattr__(self, k):
        return self.get(k)


def test_target_email_prefers_company_then_personal():
    assert lc._target_email(FakeEmp(company_email="a@tests-x.example.invalid", personal_email="b@tests-y.example.invalid")) == "a@tests-x.example.invalid"
    assert lc._target_email(FakeEmp(personal_email="b@tests-y.example.invalid")) == "b@tests-y.example.invalid"
    assert lc._target_email(FakeEmp()) is None


def test_should_disable_only_when_left():
    assert lc._should_disable(FakeEmp(status="Left")) is True
    assert lc._should_disable(FakeEmp(status="Active")) is False


def test_default_role_is_employee_only():
    assert lc.DEFAULT_EMPLOYEE_ROLES == ["Employee"]


def test_hooks_register_user_sync():
    from rayher_hr_payroll import hooks
    ev = hooks.doc_events["Employee"]
    flat = str(ev)
    assert "lifecycle_controls.sync_user_for_employee" in flat
