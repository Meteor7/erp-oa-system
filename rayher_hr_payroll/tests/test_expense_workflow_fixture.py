import json
import os

import rayher_hr_payroll

WF = os.path.join(os.path.dirname(rayher_hr_payroll.__file__), "fixtures", "workflow.json")


def _load():
    with open(WF, encoding="utf-8") as f:
        data = json.load(f)
    return next(w for w in data if w["name"] == "Expense Claim Approval")


def _states():
    return {s["state"]: s for s in _load()["states"]}


def _transitions():
    return {(t["state"], t["next_state"]): t for t in _load()["transitions"]}


def test_workflow_targets_expense_claim_and_active():
    wf = _load()
    assert wf["document_type"] == "Expense Claim"
    assert wf["is_active"] == 1


def test_five_stage_states_present():
    assert set(_states()) == {"草稿", "待经理审批", "待财务复核", "财务已审", "已拒绝"}


def test_approved_state_submits_and_sets_approval_status():
    # HRMS Expense Claim.on_submit rejects approval_status == "Draft"; the approved
    # state must flip approval_status to Approved AND set doc_status 1.
    approved = _states()["财务已审"]
    assert approved["doc_status"] == "1"
    assert approved["update_field"] == "approval_status"
    assert approved["update_value"] == "Approved"
    rejected = _states()["已拒绝"]
    assert rejected["update_field"] == "approval_status"
    assert rejected["update_value"] == "Rejected"


def test_employee_submits_manager_then_finance_approve():
    tr = _transitions()
    assert tr[("草稿", "待经理审批")]["allowed"] == "Employee"
    assert tr[("待经理审批", "待财务复核")]["allowed"] == "Department Manager"
    assert tr[("待财务复核", "财务已审")]["allowed"] == "Accounts User"


def test_approval_transitions_forbid_self_approval():
    tr = _transitions()
    assert tr[("待经理审批", "待财务复核")]["allow_self_approval"] == 0
    assert tr[("待财务复核", "财务已审")]["allow_self_approval"] == 0


def test_rejected_can_be_resubmitted():
    tr = _transitions()
    assert ("已拒绝", "草稿") in tr
    assert tr[("已拒绝", "草稿")]["allowed"] == "Employee"


def test_manager_approval_scoped_to_expense_approver():
    # The 经理批准 transition must be conditioned on the viewer being the claim's
    # expense_approver, not merely holding the Department Manager role.
    cond = _transitions()[("待经理审批", "待财务复核")].get("condition", "")
    assert "expense_approver" in cond and "session.user" in cond
