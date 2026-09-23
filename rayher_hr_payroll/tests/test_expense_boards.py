from datetime import date

import pytest

from rayher_hr_payroll import expense_boards as boards

TODAY = date(2026, 9, 23)


def purchase(name, **overrides):
    row = {
        "name": name, "request_type": "购买申请", "subject": "打印纸", "employee_name": "王测试",
        "department": "研发部", "workflow_status": "已完成", "approved_amount": 1000, "amount": 1000,
        "asset_classification": "非固定资产", "paid_amount": 0, "reserved_amount": 0,
        "waited_days": 0, "approved_on": date(2026, 9, 20), "current_step_label": "",
    }
    row.update(overrides)
    return row


def travel(name, **overrides):
    row = {
        "name": name, "request_type": "出差申请", "subject": "北京展会", "employee_name": "王测试",
        "department": "研发部", "workflow_status": "已完成", "travel_destination": "北京",
        "travel_start_date": "2026-09-20", "travel_end_date": "2026-09-25", "travel_days": 6,
        "paid_amount": 0, "reserved_amount": 0, "waited_days": 0, "approved_on": date(2026, 9, 19),
        "approved_amount": 0, "amount": 0, "asset_classification": "非固定资产",
    }
    row.update(overrides)
    return row


def claim(name, request_type="报销单", **overrides):
    row = {
        "name": name, "request_type": request_type, "subject": "办公用品", "employee_name": "王测试",
        "department": "研发部", "workflow_status": "已付款", "amount": 100, "paid_on": "2026-09-10",
        "urgency": "一般", "waited_days": 0, "invoice_followup_status": "已收票",
        "expected_invoice_date": None, "payee_name": "王测试",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------- scope


@pytest.mark.parametrize("roles, positions, expected", [
    (["Accounts User"], {}, "all"),
    (["System Manager"], {}, "all"),
    (["Rayher Business Executive"], {}, "all"),
    (["Employee"], {"vice_manager": True}, "all"),
    (["Employee"], {"finance_manager": True}, "all"),
    (["Department Manager", "Employee"], {}, "department"),
    (["Employee"], {}, "none"),
    ([], {}, "none"),
    (["Employee"], {"vice_manager": False}, "none"),
])
def test_board_scope(roles, positions, expected):
    assert boards.board_scope(roles, positions) == expected


# ---------------------------------------------------------------- request board


def test_request_board_sums_the_ledger_not_the_document_amount():
    rows = [
        purchase("P1", paid_amount=400, reserved_amount=100),
        purchase("P2", approved_amount=500, paid_amount=0, approved_on=date(2026, 8, 1)),
        purchase("P3", workflow_status="待审批", waited_days=5, current_step_label="副总经理"),
    ]
    result = boards.request_board(rows, today=TODAY)
    assert result["summary"] == {
        "approved_amount": 1500.0, "reserved_amount": 100.0, "paid_amount": 400.0,
        "unpaid_amount": 1100.0, "application_count": 3,
    }
    # P2 has been approved for 53 days without a single payment; P1 已付过款，不算长期未执行
    assert [row["name"] for row in result["stale_applications"]] == ["P2"]
    assert result["stale_applications"][0]["idle_days"] == 53
    assert [(row["name"], row["overdue"]) for row in result["stuck_approvals"]] == [("P3", True)]


def test_request_board_flags_only_approvals_waiting_long_enough():
    rows = [
        purchase("P1", workflow_status="待审批", waited_days=3),
        purchase("P2", workflow_status="待办理", waited_days=1),
        purchase("P3", workflow_status="已完成"),
    ]
    result = boards.request_board(rows, today=TODAY)
    assert [(row["name"], row["overdue"]) for row in result["stuck_approvals"]] == [("P1", True), ("P2", False)]


def test_request_board_reports_travel_in_progress_and_this_month():
    rows = [
        travel("T1", paid_amount=800),
        travel("T2", travel_start_date="2026-09-01", travel_end_date="2026-09-03", paid_amount=200),
        travel("T3", travel_start_date="2026-08-01", travel_end_date="2026-08-03", paid_amount=50),
        travel("T4", workflow_status="待审批"),
    ]
    result = boards.request_board(rows, today=TODAY)
    assert [row["name"] for row in result["travel"]["ongoing"]] == ["T1"]
    assert sorted(row["name"] for row in result["travel"]["this_month"]) == ["T1", "T2"]
    assert result["travel"]["claimed_amount"] == 1000.0
    assert result["travel"]["ongoing"][0]["claimed_amount"] == 800.0


def test_request_board_groups_assets_and_departments():
    rows = [
        purchase("P1", asset_classification="固定资产-生产设备", approved_amount=2000),
        purchase("P2", asset_classification="非固定资产", department="财务部", approved_amount=300),
        travel("T1"),
    ]
    result = boards.request_board(rows, today=TODAY)
    assert [(row["label"], row["amount"]) for row in result["by_asset"]] == [("固定资产-生产设备", 2000.0), ("非固定资产", 300.0)]
    assert {row["label"]: row["count"] for row in result["by_department"]} == {"研发部": 2, "财务部": 1}


# ---------------------------------------------------------------- payment board


def test_payment_board_counts_by_payment_date_and_splits_the_two_types():
    rows = [
        claim("C1", amount=100, paid_on="2026-09-10"),
        claim("C2", "付款单", amount=250, paid_on="2026-09-22", payee_name="供应商甲"),
        claim("C3", amount=999, paid_on="2026-08-31"),
        claim("C4", workflow_status="待办理", amount=70, paid_on=None, urgency="加急"),
        claim("C5", "付款单", workflow_status="待办理", amount=30, paid_on=None, waited_days=4),
    ]
    result = boards.payment_board(rows, today=TODAY)
    assert result["summary"]["reimbursement_paid"] == 100.0
    assert result["summary"]["payment_paid"] == 250.0
    assert result["summary"]["paid_total"] == 350.0
    assert result["summary"]["cashier_pending"] == 2
    # 加急优先，其次等待久的
    assert [row["name"] for row in result["cashier_queue"]] == ["C4", "C5"]
    trend = {row["month"]: (row["reimbursement"], row["payment"]) for row in result["trend"]}
    assert trend["2026-09"] == (100.0, 250.0)
    assert trend["2026-08"] == (999.0, 0.0)
    assert len(result["trend"]) == 6
    assert [row["label"] for row in result["top_payees"]] == ["供应商甲"]


def test_payment_board_tracks_invoices_still_owed():
    rows = [
        claim("C1", "付款单", workflow_status="已付款", invoice_followup_status="待收票", expected_invoice_date="2026-09-20", amount=500),
        claim("C2", "付款单", workflow_status="已付款", invoice_followup_status="待收票", expected_invoice_date="2026-09-30", amount=200),
        claim("C3", "付款单", workflow_status="已付款", invoice_followup_status="已核验", expected_invoice_date="2026-09-01"),
        claim("C4", workflow_status="已付款", invoice_followup_status="待收票", expected_invoice_date="2026-09-01"),
    ]
    result = boards.payment_board(rows, today=TODAY)
    assert [(row["name"], row["overdue_days"], row["days_left"]) for row in result["invoice_tracking"]] == [("C1", 3, 0), ("C2", 0, 7)]
    assert result["summary"]["invoice_pending"] == 2
    assert result["summary"]["invoice_overdue"] == 1


def test_payment_board_groups_accounts_only_for_paid_documents():
    rows = [claim("C1", amount=100), claim("C2", workflow_status="待办理", paid_on=None, amount=500)]
    lines = [
        {"parent": "C1", "expense_account_level_1": "管理费用", "expense_account_level_2": "办公费", "total_amount": 60},
        {"parent": "C1", "expense_account_level_1": "管理费用", "expense_account_level_2": "办公费", "total_amount": 40},
        {"parent": "C2", "expense_account_level_1": "管理费用", "expense_account_level_2": "差旅费", "total_amount": 500},
    ]
    result = boards.payment_board(rows, lines, today=TODAY)
    assert result["by_account"] == [{"level_1": "管理费用", "level_2": "办公费", "count": 2, "amount": 100.0}]
    assert [row["label"] for row in result["by_department"]] == ["研发部"]


# ---------------------------------------------------------------- procurement board


def test_procurement_board_stays_separate_and_tracks_arrival():
    rows = [
        {"name": "PR1", "request_type": "采购申请", "workflow_status": "已完成", "business_status": "需求已批准/待询价", "approved_amount": 5000, "amount": 5000},
        {"name": "PP1", "request_type": "采购付款", "workflow_status": "已付款", "business_status": "待到货", "amount": 1500,
         "arrival_status": "未到货", "inspection_status": "未验收", "prepayment_writeoff_status": "待核销"},
        {"name": "PP2", "request_type": "采购付款", "workflow_status": "待审批", "business_status": "待审批", "amount": 800,
         "arrival_status": "未到货", "inspection_status": "未验收", "prepayment_writeoff_status": "无需核销"},
    ]
    result = boards.procurement_board(rows, today=TODAY)
    assert result["summary"] == {
        "application_count": 1, "application_amount": 5000.0, "payment_count": 2, "paid_amount": 1500.0,
        "pending_arrival": 1, "pending_inspection": 1, "pending_writeoff": 1,
    }
    assert [row["label"] for row in result["applications_by_status"]] == ["需求已批准/待询价"]
    assert {row["label"] for row in result["by_business_status"]} == {"待到货", "待审批"}


def test_recent_months_crosses_the_year_boundary():
    assert boards.recent_months(date(2026, 2, 15), 4) == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert boards.month_key("2026-09-23 10:00:00") == "2026-09"
    assert boards.month_key(None) == ""
