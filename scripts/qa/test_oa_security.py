"""Real Frappe/DB security regressions; isolated review site only."""
import json

import frappe
import pytest
from frappe.client import set_value

from test_transaction_locks import connect


@pytest.fixture(autouse=True)
def isolated_site():
    connect()
    frappe.flags.in_test = True
    try:
        yield
    finally:
        frappe.db.rollback()
        frappe.destroy()


def ordinary_user():
    for employee in frappe.get_all("Employee", filters={"status": "Active"}, fields=["user_id"]):
        user = employee.user_id
        if user and set(frappe.get_roles(user)) <= {"Employee", "All", "Guest", "Desk User"}:
            return user
    raise AssertionError("Review snapshot must include an ordinary Employee account")


def test_actual_profile_edit_cannot_impersonate_current_approver():
    from rayher_hr_payroll.api import oa_entry as oa
    from rayher_hr_payroll.invoice_ocr import permissions
    from rayher_hr_payroll.oa_access import oa_request_has_permission
    attacker = ordinary_user()
    frappe.set_user(attacker)
    target = None
    for name in frappe.get_all("OA Approval Request", filters={"workflow_status": ["in", list(oa.ACTIVE_STATUSES)]}, pluck="name"):
        candidate = frappe.get_doc("OA Approval Request", name)
        step = oa._current_step(candidate)
        if step and oa_request_has_permission(candidate, "read", attacker) is False:
            accounts = json.loads(step.approvers or "[]")
            if accounts and accounts[0] != attacker:
                target, victim = candidate, accounts[0]
                break
    assert target is not None, "Review snapshot must include an unrelated active request"
    before_index = target.current_step_index
    before_signatures = [s.approved_by for s in target.steps]
    # Use the actual self-service endpoint, not a privileged direct DB edit.
    set_value("User", attacker, {"first_name": victim, "last_name": ""})
    assert frappe.db.get_value("User", attacker, "full_name") == victim
    assert oa._actor_names() == {attacker}
    assert oa_request_has_permission(target, "read", attacker) is False
    assert target.name not in {r["name"] for r in oa.list_requests(view="all", limit=200)}
    with pytest.raises((frappe.PermissionError, frappe.ValidationError)):
        oa.action_request(target.name, action="approve")
    after = frappe.get_doc("OA Approval Request", target.name)
    assert after.current_step_index == before_index
    assert [s.approved_by for s in after.steps] == before_signatures
    assert permissions._identity(attacker)["actors"] == {attacker}
    assert not permissions.can_read_invoice(frappe._dict(
        doctype="OA Invoice Record", owner=victim, request=target.name, batch=""), attacker)
    # Authorized self-approval is still allowed at one's own current node.
    own_step = frappe._dict(step_index=1, approvers=json.dumps([attacker]), approved_by="[]")
    assert oa._can_act_on_current_step(frappe._dict(
        workflow_status=oa.STATUS_PENDING, current_step_index=1, steps=[own_step]))


def test_full_draft_update_and_submit_normalizes_financial_report_label():
    from rayher_hr_payroll.api import oa_entry as oa
    attacker = ordinary_user()
    frappe.set_user(attacker)
    # Establish an approved direct-purchase fixture in this isolated transaction.
    # Expense creation, updates, submission and report reads use real public APIs.
    ctx = oa._employee_context()
    source = frappe.get_doc(dict(doctype="OA Approval Request", request_type=oa.REQUEST_DIRECT_PURCHASE,
        subject="REVIEW approved purchase fixture", amount=100, approved_amount=100,
        workflow_status=oa.STATUS_COMPLETED, employee=ctx["employee"], employee_name=ctx["employee_name"],
        department=ctx["department"], company=frappe.db.get_value("Employee", ctx["employee"], "company")))
    oa._insert_document(source)
    payload = dict(subject="REVIEW expense normalization", doc_type="非固定资产",
        invoice_handling_mode=oa.INVOICE_MODE_NOT_REQUIRED,
        no_invoice_reason="Review fixture requires no invoice", source_request=source.name,
        expense_lines=[dict(project_name="Review project", issue_date="2026-09-21",
            expense_account_level_1="差旅费", expense_account_level_2="住宿费",
            expense_item="FORGED LABEL", category="FORGED LABEL", amount=10,
            expense_description="Review expense")])
    result = oa.create_request(request_type=oa.REQUEST_EXPENSE_PAYMENT, submit=0, **payload)
    name = result["name"]
    count = frappe.db.count("OA Approval Request")
    for _ in range(3):
        oa.update_manual_expense_draft(name, payload)
    assert frappe.db.count("OA Approval Request") == count
    draft = frappe.get_doc("OA Approval Request", name)
    assert draft.expense_lines[0].expense_item == "差旅费 / 住宿费"
    # Simulate an existing pre-fix draft to verify submit repairs stored values too.
    frappe.db.set_value(draft.expense_lines[0].doctype, draft.expense_lines[0].name,
                        {"expense_item": "LEGACY FORGED", "category": "LEGACY FORGED"})
    oa.submit_request(name)
    submitted = frappe.get_doc("OA Approval Request", name)
    assert submitted.workflow_status in oa.ACTIVE_STATUSES
    assert submitted.expense_lines[0].expense_item == "差旅费 / 住宿费"
    assert submitted.expense_lines[0].category == "差旅费 / 住宿费"
    rows = oa.get_expense_statistics(view="all", expense_item="差旅费 / 住宿费")["rows"]
    assert any(row["request_name"] == name for row in rows)
    forged = oa.get_expense_statistics(view="all", expense_item="LEGACY FORGED")["rows"]
    assert not any(row["request_name"] == name for row in forged)
