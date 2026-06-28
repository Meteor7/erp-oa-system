import types

import rayher_hr_payroll.request_visibility as rv


class Doc(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


# ---- _in_scope (direct doc access) ----

def test_employee_sees_only_own_expense_claim():
    own = Doc(employee="E1", owner="e1@co", expense_approver="m@co")
    other = Doc(employee="E2", owner="e2@co", expense_approver="m@co")
    roles = {"Employee"}
    assert rv._in_scope("Expense Claim", own, "e1@co", roles, "E1") is True
    assert rv._in_scope("Expense Claim", other, "e1@co", roles, "E1") is False


def test_manager_sees_assigned_claim_not_unassigned():
    roles = {"Employee", "Department Manager"}
    mine = Doc(employee="E2", owner="e2@co", expense_approver="mgr@co")
    theirs = Doc(employee="E3", owner="e3@co", expense_approver="other@co")
    assert rv._in_scope("Expense Claim", mine, "mgr@co", roles, "M1") is True
    assert rv._in_scope("Expense Claim", theirs, "mgr@co", roles, "M1") is False


def test_finance_sees_all_expense_claims():
    roles = {"Employee", "Accounts User"}
    any_claim = Doc(employee="E9", owner="e9@co", expense_approver="x@co")
    assert rv._in_scope("Expense Claim", any_claim, "fin@co", roles, "F1") is True
    # but finance is NOT special for Leave (not 费用)
    leave = Doc(employee="E9", owner="e9@co", leave_approver="x@co")
    assert rv._in_scope("Leave Application", leave, "fin@co", roles, "F1") is False


def test_hr_and_admin_see_all():
    claim = Doc(employee="E9", owner="e9@co", expense_approver="x@co")
    assert rv._in_scope("Expense Claim", claim, "hr@co", {"HR User"}, "H1") is True
    assert rv._in_scope("Expense Claim", claim, "Administrator", set(), None) is True


def test_travel_without_approver_is_owner_or_employee_only():
    roles = {"Employee", "Department Manager"}  # manager has no approver field to match
    mine = Doc(employee="M1", owner="mgr@co")
    others = Doc(employee="E5", owner="e5@co")
    assert rv._in_scope("Travel Request", mine, "mgr@co", roles, "M1") is True
    assert rv._in_scope("Travel Request", others, "mgr@co", roles, "M1") is False


# ---- _scope_sql (list scoping) ----

def test_scope_sql_unrestricted_for_see_all_and_finance(monkeypatch):
    monkeypatch.setattr(rv.frappe, "db", types.SimpleNamespace(escape=lambda v: "'%s'" % v))
    assert rv._scope_sql("Expense Claim", "hr@co", {"HR Manager"}, "H1") == ""
    assert rv._scope_sql("Expense Claim", "fin@co", {"Accounts User"}, "F1") == ""
    assert rv._scope_sql("Expense Claim", "Administrator", set(), None) == ""


def test_scope_sql_employee_and_manager(monkeypatch):
    monkeypatch.setattr(rv.frappe, "db", types.SimpleNamespace(escape=lambda v: "'%s'" % v))
    emp = rv._scope_sql("Expense Claim", "e1@co", {"Employee"}, "E1")
    assert "employee = 'E1'" in emp and "expense_approver" not in emp
    mgr = rv._scope_sql("Expense Claim", "mgr@co", {"Department Manager"}, "M1")
    assert "expense_approver = 'mgr@co'" in mgr and "employee = 'M1'" in mgr
