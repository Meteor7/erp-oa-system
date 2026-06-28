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


def test_finance_approval_confirms_without_submitting():
    # Spec L33/L155: finance does 复核确认 only; 报销实际付款/记账 is out of scope. The
    # approved state must NOT submit the claim (doc_status 0) so HRMS on_submit ->
    # make_gl_entries never runs (no accounting posting on review).
    approved = _states()["财务已审"]
    assert approved["doc_status"] == "0"
    assert approved["update_field"] == "approval_status"
    assert approved["update_value"] == "Approved"
    # 已拒绝 must NOT set approval_status=Rejected: HRMS zeroes every row sanctioned_amount
    # while approval_status==Rejected, and 重新提交 never restores it -> a resubmitted
    # claim would approve/pay 0. Rejection is carried by workflow_state alone.
    rejected = _states()["已拒绝"]
    assert not rejected.get("update_field")


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


def test_manager_reject_also_scoped_to_approver():
    cond = _transitions()[("待经理审批", "已拒绝")].get("condition", "")
    assert "expense_approver" in cond and "session.user" in cond


def test_draft_state_resets_approval_status():
    # A rejected claim resubmitted (已拒绝 -> 草稿) must clear HRMS approval_status
    # back to Draft, else it keeps Rejected behavior after re-entering the flow.
    draft = _states()["草稿"]
    assert draft.get("update_field") == "approval_status"
    assert draft.get("update_value") == "Draft"
