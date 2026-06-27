from rayher_hr_payroll.rayher_hr_payroll.report.pending_my_approval import pending_my_approval as rpt


def test_columns_cover_type_applicant_summary_status():
    cols = rpt.get_columns()
    labels = [c["label"] for c in cols]
    assert "类型" in labels and "申请人" in labels and "状态" in labels


def test_rows_from_sources_tags_each_type():
    sources = {
        "请假": [{"name": "LA-1", "employee_name": "演示员工129", "status": "Open"}],
        "报销": [{"name": "EC-1", "employee_name": "演示员工146", "workflow_state": "待经理审批"}],
    }
    rows = rpt.rows_from_sources(sources)
    types = {r[0] for r in rows}
    assert types == {"请假", "报销"}
    assert any("演示员工129" in r for r in rows)


def test_expense_claim_filter_uses_current_workflow_states():
    expense = [t for t in rpt._TYPES if t[1] == "Expense Claim"][0]
    filters = expense[2]
    assert filters["workflow_state"] == ["in", ["待经理审批", "待财务复核"]]
