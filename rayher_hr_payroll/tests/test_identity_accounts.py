from types import SimpleNamespace
import sys
from rayher_hr_payroll.identity_accounts import account_user

def test_resolution_follows_current_site_binding_without_import_cache(monkeypatch):
    old = "person046@staff.example.invalid"
    new = "person030@staff.example.invalid"
    binding = [old]
    monkeypatch.setitem(sys.modules, "frappe", SimpleNamespace(
        db=SimpleNamespace(get_value=lambda *args: binding[0])))
    assert account_user(old) == old
    binding[0] = new
    assert account_user(old) == new
    binding[0] = old
    assert account_user(old) == old
    assert account_user("person047@staff.example.invalid") == "person047@staff.example.invalid"
