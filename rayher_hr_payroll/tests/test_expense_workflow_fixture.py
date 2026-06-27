import json, os
import rayher_hr_payroll

WF = os.path.join(os.path.dirname(rayher_hr_payroll.__file__), "fixtures", "workflow.json")


def _load():
    with open(WF, encoding="utf-8") as f:
        data = json.load(f)
    return next(w for w in data if w["name"] == "Expense Claim Approval")


def test_workflow_targets_expense_claim():
    wf = _load()
    assert wf["document_type"] == "Expense Claim"
    assert wf["is_active"] == 1


def test_workflow_has_two_stage_states():
    states = {s["state"] for s in _load()["states"]}
    assert {"草稿", "经理已批", "财务已审", "已拒绝"} <= states


def test_transitions_are_role_gated_manager_then_finance():
    tr = _load()["transitions"]
    appr = {(t["state"], t["next_state"]): t["allowed"] for t in tr}
    assert appr[("草稿", "经理已批")] == "Department Manager"
    assert appr[("经理已批", "财务已审")] == "Accounts User"
