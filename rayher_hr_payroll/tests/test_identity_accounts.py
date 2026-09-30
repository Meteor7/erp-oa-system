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


def test_old_server_domain_and_wang_account_follow_same_person(monkeypatch):
    def value(doctype, filters, field):
        return {"演示员工21": "person030@staff.example.invalid",
                "演示员工30": "person059@staff.example.invalid"}[filters["employee_name"]]
    monkeypatch.setitem(sys.modules, "frappe", SimpleNamespace(db=SimpleNamespace(get_value=value)))
    assert account_user("person046@business.example.invalid") == "person030@staff.example.invalid"
    assert account_user("person007@staff.example.invalid") == "person059@staff.example.invalid"


def test_site_aliases_keep_historical_approval_constants_usable(monkeypatch):
    # 2026-09-30 账号按企业邮箱前缀改名后，旧账号名通过 site_config 的对照表找到新账号。
    monkeypatch.setitem(sys.modules, "frappe", SimpleNamespace(
        conf={"company_email_account_aliases": {
            "person060@staff.example.invalid": "person066@staff.example.invalid"}},
        db=SimpleNamespace()))
    assert account_user("person060@staff.example.invalid") == "person066@staff.example.invalid"
    assert account_user("person056@staff.example.invalid") == "person056@staff.example.invalid"
