from types import SimpleNamespace as NS
import pytest


def test_social_import_trust_cannot_be_supplied_in_document_flags(monkeypatch):
    from rayher_hr_payroll import social_import_mutation_guard as guard
    def deny(message, *args): raise PermissionError(message)
    monkeypatch.setattr(guard, "frappe", NS(throw=deny, PermissionError=PermissionError))
    doc = NS(flags=NS(ignore_permissions=True, social_import_action=True))
    with pytest.raises(PermissionError): guard.require_social_import_action(doc)
    guard.social_import_action(lambda: guard.require_social_import_action(doc))()
    with pytest.raises(PermissionError): guard.require_social_import_action(doc)
    def fails(): raise ValueError("transaction aborted")
    with pytest.raises(ValueError): guard.social_import_action(fails)()
    with pytest.raises(PermissionError): guard.require_social_import_action(doc)


def test_full_time_type_change_is_blocked_for_used_locked_period(monkeypatch):
    from rayher_hr_payroll import employee_controls as rules
    import frappe
    doc = NS(name="EMP1", is_new=lambda: False, has_value_changed=lambda key: True,
             get_doc_before_save=lambda: {"rd_personnel_type": "全时研发"},
             get=lambda key: "非全时研发")
    monkeypatch.setattr(frappe, "get_all", lambda *a, **kw: [NS(period="202607")], raising=False)
    monkeypatch.setattr(rules, "_employee_has_rd_hours", lambda employee, period: True)
    monkeypatch.setattr(frappe, "_", lambda x: x, raising=False)
    def deny(message): raise ValueError(message)
    monkeypatch.setattr(frappe, "throw", deny, raising=False)
    with pytest.raises(ValueError, match="已锁定期间"):
        rules.validate_employee_rd_lock(doc)
    doc.get_doc_before_save = lambda: {"rd_personnel_type": "研发辅助"}
    rules.validate_employee_rd_lock(doc)
