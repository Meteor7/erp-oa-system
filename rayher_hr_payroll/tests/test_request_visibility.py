import types

import rayher_hr_payroll.request_visibility as rv


class Doc(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)

    def get_doc_before_save(self):
        return self.get("_before")


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
    # own claims OR claims where they are the assigned approver (covers stock approver roles)
    assert "employee = 'E1'" in emp and "expense_approver = 'e1@co'" in emp
    mgr = rv._scope_sql("Expense Claim", "mgr@co", {"Department Manager"}, "M1")
    assert "expense_approver = 'mgr@co'" in mgr and "employee = 'M1'" in mgr


def test_linked_employee_cannot_open_doc_they_own_for_another(monkeypatch):
    # _in_scope must NOT fall back to owner for a LINKED employee (consistency with list scoping):
    # a linked employee who somehow owns a claim for another employee can't open it directly.
    foreign = Doc(employee="E2", owner="e1@co", expense_approver="m@co")
    assert rv._in_scope("Expense Claim", foreign, "e1@co", {"Employee"}, "E1") is False


def test_unlinked_user_owner_fallback(monkeypatch):
    own = Doc(employee="E9", owner="contractor@co", expense_approver="m@co")
    assert rv._in_scope("Expense Claim", own, "contractor@co", {"Employee"}, None) is True


def _claim_with_before(before_state, **kw):
    d = Doc(**kw)
    d["_before"] = Doc(workflow_state=before_state, employee=kw.get("employee"), owner=kw.get("owner"))
    return d


def test_claimant_cannot_write_own_claim_already_under_review(monkeypatch):
    monkeypatch.setattr(rv, "frappe", types.SimpleNamespace(
        session=types.SimpleNamespace(user="fin@co"),
        get_roles=lambda u: ["Employee", "Accounts User"],
        db=types.SimpleNamespace(get_value=lambda dt, flt, f: "F1")))  # fin@co's Employee is F1
    # claim ALREADY in 待财务复核 before this save -> finance-claimant edit denied
    claim = _claim_with_before("待财务复核", employee="F1", owner="fin@co", workflow_state="待财务复核")
    assert rv.expense_claim_has_permission(claim, "write", "fin@co") is False
    # reading is fine
    assert rv.expense_claim_has_permission(claim, "read", "fin@co") is None


def test_claimant_can_submit_their_own_draft(monkeypatch):
    # 提交审批: before-state 草稿 -> the new 待经理审批 state must NOT block the claimant's own submit.
    monkeypatch.setattr(rv, "frappe", types.SimpleNamespace(
        session=types.SimpleNamespace(user="e1@co"),
        get_roles=lambda u: ["Employee"],
        db=types.SimpleNamespace(get_value=lambda dt, flt, f: "E1")))
    submitting = _claim_with_before("草稿", employee="E1", owner="e1@co", workflow_state="待经理审批")
    assert rv.expense_claim_has_permission(submitting, "write", "e1@co") is None
    # editing a fresh draft (no before) is also fine
    draft = Doc(employee="E1", owner="e1@co", workflow_state="草稿")
    assert rv.expense_claim_has_permission(draft, "write", "e1@co") is None


def test_salary_slip_employee_own_finance_all_manager_none():
    own = Doc(employee="E1", owner="e1@co")
    other = Doc(employee="E2", owner="e2@co")
    # employee: only their own slip (fixes the leak where stock Employee read is blanket)
    assert rv._in_scope("Salary Slip", own, "e1@co", {"Employee"}, "E1") is True
    assert rv._in_scope("Salary Slip", other, "e1@co", {"Employee"}, "E1") is False
    # finance + HR see all payroll (spec L64: 财务/HR 见全员工资)
    assert rv._in_scope("Salary Slip", other, "fin@co", {"Accounts User"}, None) is True
    assert rv._in_scope("Salary Slip", other, "hr@co", {"HR User"}, "H1") is True
    # a manager is NOT special for salary -> sees only their own
    assert rv._in_scope("Salary Slip", other, "mgr@co", {"Department Manager", "Employee"}, "M1") is False
