from rayher_hr_payroll.rayher_hr_payroll.report.pending_my_approval import pending_my_approval as rpt


def test_columns_cover_type_applicant_status_and_hidden_doctype():
    cols = rpt.get_columns()
    labels = [c["label"] for c in cols]
    assert "类型" in labels and "申请人" in labels and "状态" in labels
    dt = [c for c in cols if c["fieldname"] == "doctype"][0]
    assert dt.get("hidden") == 1  # backs the Dynamic Link 单号 column


def test_rows_are_dicts_with_doctype_for_dynamic_link():
    sources = [
        ("请假", "Leave Application", [{"name": "LA-1", "employee_name": "演示员工129", "status": "Open"}]),
        ("报销", "Expense Claim", [{"name": "EC-1", "employee_name": "演示员工146", "workflow_state": "待经理审批"}]),
    ]
    rows = rpt.rows_from_sources(sources)
    assert {r["type"] for r in rows} == {"请假", "报销"}
    la = [r for r in rows if r["type"] == "请假"][0]
    assert la["doctype"] == "Leave Application" and la["applicant"] == "演示员工129"
    ec = [r for r in rows if r["type"] == "报销"][0]
    assert ec["doctype"] == "Expense Claim" and ec["state"] == "待经理审批"


def test_expense_pending_states_are_current_workflow_states():
    assert rpt.MANAGER_STATE == "待经理审批"
    assert rpt.FINANCE_STATE == "待财务复核"


def test_report_refs_expense_claim_so_approvers_can_run_it():
    import json
    import os
    import rayher_hr_payroll
    p = os.path.join(os.path.dirname(rayher_hr_payroll.__file__), "rayher_hr_payroll",
                     "report", "pending_my_approval", "pending_my_approval.json")
    d = json.load(open(p, encoding="utf-8"))
    assert d["ref_doctype"] == "Expense Claim"
    roles = {r["role"] for r in d["roles"]}
    assert {"Department Manager", "Accounts User"} <= roles
