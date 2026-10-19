from datetime import date

import pytest

from rayher_hr_payroll import expense_boards as boards

TODAY = date(2026, 9, 23)


def purchase(name, **overrides):
    row = {
        "name": name, "request_type": "购买申请", "subject": "打印纸", "employee_name": "王测试",
        "department": "研发部", "workflow_status": "已完成", "approved_amount": 1000, "amount": 1000,
        "asset_nature": "非固定资产", "fixed_asset_category": "", "paid_amount": 0, "reserved_amount": 0,
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
        "approved_amount": 0, "amount": 0,
    }
    row.update(overrides)
    return row


def claim(name, request_type="报销单", **overrides):
    row = {
        "name": name, "request_type": request_type, "subject": "办公用品", "employee_name": "王测试",
        "department": "研发部", "workflow_status": "已付款", "business_status": "已完结", "amount": 100,
        "paid_on": "2026-09-10", "urgency": "一般", "waited_days": 0, "invoice_followup_status": "已收票",
        "expected_invoice_date": None, "payee_name": "王测试",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize("roles, positions, expected", [
    (["Accounts User"], {}, "all"),
    (["System Manager"], {}, "all"),
    (["QIHENG Demo Business Executive"], {}, "all"),
    (["Employee"], {"vice_manager": True}, "all"),
    (["Employee"], {"finance_manager": True}, "all"),
    (["Department Manager", "Employee"], {}, "department"),
    (["Employee"], {}, "none"),
    ([], {}, "none"),
    (["Employee"], {"vice_manager": False}, "none"),
])
def test_board_scope(roles, positions, expected):
    assert boards.board_scope(roles, positions) == expected


# ---------------------------------------------------------------- 申请看板


def test_request_board_kpis_follow_the_design():
    rows = [
        purchase("P1", paid_amount=400, reserved_amount=100),
        purchase("P2", approved_amount=500, approved_on=date(2026, 8, 1)),
        purchase("P3", workflow_status="待审批", waited_days=5, current_step_label="演示员工113经理", amount=300),
        travel("T1"),
        travel("T2", workflow_status="待审批", waited_days=1, current_step_label="直属主管"),
    ]
    result = boards.request_board(rows, today=TODAY)
    summary = result["summary"]
    assert (summary["month_approved_amount"], summary["month_approved_count"]) == (1000.0, 1)
    # 已批准未付出 = 批准 - 已付 - 在途占用：P1 剩 500，P2 剩 500
    assert summary["unpaid_amount"] == 1000.0
    assert (summary["pending_count"], summary["longest_wait_days"]) == (2, 5)
    assert (summary["on_trip_count"], summary["month_trip_count"]) == (1, 1)
    assert "reserved_amount" not in summary, "设计稿去掉了单独的占用大数字"


def test_request_board_lists_purchase_execution_with_progress_and_stale_flag():
    rows = [
        purchase("P1", paid_amount=400, reserved_amount=100),
        purchase("P2", approved_amount=500, approved_on=date(2026, 8, 1)),
        purchase("P3", paid_amount=1000),
    ]
    applications = {row["name"]: row for row in boards.request_board(rows, today=TODAY)["applications"]}
    assert applications["P1"]["progress"] == 50 and applications["P1"]["status"] == "部分付款"
    assert applications["P1"]["remaining_amount"] == 500.0
    assert applications["P2"]["stale"] is True and applications["P2"]["idle_days"] == 53
    assert applications["P3"]["status"] == "已付款" and applications["P3"]["stale"] is False
    assert [row["name"] for row in boards.request_board(rows, today=TODAY)["applications"]][0] == "P2"


def test_request_board_flags_approvals_waiting_more_than_three_days():
    rows = [
        purchase("P1", workflow_status="待审批", waited_days=4, amount=200),
        purchase("P2", workflow_status="待办理", waited_days=3, amount=100),
        travel("T1", workflow_status="待审批", waited_days=9),
    ]
    pending = boards.request_board(rows, today=TODAY)["pending"]
    assert [(row["name"], row["overdue"]) for row in pending] == [("T1", True), ("P1", True), ("P2", False)]
    assert pending[0]["amount"] is None, "出差申请没有金额"


def test_request_board_trips_have_status_and_claimed_amount():
    rows = [
        travel("T1", paid_amount=800),
        travel("T2", travel_start_date="2026-10-05", travel_end_date="2026-10-06"),
        travel("T3", travel_start_date="2026-09-01", travel_end_date="2026-09-03", paid_amount=200),
        travel("T4", travel_start_date="2026-06-01", travel_end_date="2026-06-03"),
    ]
    trips = {row["name"]: row for row in boards.request_board(rows, today=TODAY)["trips"]}
    assert set(trips) == {"T1", "T2", "T3"}, "一个月前就回来的出差不再列出"
    assert (trips["T1"]["status"], trips["T1"]["claimed_amount"]) == ("出差中", 800.0)
    assert trips["T2"]["status"] == "未出发"
    assert trips["T3"]["status"] == "已返回"


def test_request_board_groups_departments_and_fixed_assets():
    rows = [
        purchase("P1", asset_nature="固定资产", fixed_asset_category="电子设备", approved_amount=2000),
        purchase("P2", department="财务部", approved_amount=300),
    ]
    result = boards.request_board(rows, today=TODAY)
    assert result["by_department"] == [["研发部", 2000.0], ["财务部", 300.0]]
    assert result["fixed_by_category"] == [["电子设备", 2000.0]]
    assert result["non_fixed_amount"] == 300.0


# ---------------------------------------------------------------- 付款看板


def test_payment_board_splits_this_month_by_type_and_payment_date():
    rows = [
        claim("C1", amount=100, paid_on="2026-09-10"),
        claim("C2", "付款单", amount=250, paid_on="2026-09-22", payee_name="供应商甲"),
        claim("C3", amount=999, paid_on="2026-08-31"),
    ]
    result = boards.payment_board(rows, today=TODAY)
    assert (result["summary"]["reimbursement_paid"], result["summary"]["payment_paid"]) == (100.0, 250.0)
    trend = {row["month"]: (row["reimbursement"], row["payment"]) for row in result["trend"]}
    assert trend["2026-09"] == (100.0, 250.0) and trend["2026-08"] == (999.0, 0.0)
    assert len(result["trend"]) == 6 and result["trend"][-1]["month"] == "2026-09"
    assert result["top_payees"] == [["供应商甲", 250.0]]


def test_cashier_queue_has_payments_due_and_invoices_to_verify_urgent_first():
    rows = [
        claim("C1", workflow_status="待办理", business_status="待付款", paid_on=None, amount=70, waited_days=1),
        claim("C2", "付款单", workflow_status="待办理", business_status="待付款", paid_on=None, amount=30, urgency="加急"),
        claim("C3", "付款单", business_status="待核验", amount=40, waited_days=6),
        claim("C4", workflow_status="待审批", business_status="待审批", paid_on=None),
    ]
    result = boards.payment_board(rows, today=TODAY)
    assert [(row["name"], row["status"]) for row in result["cashier_queue"]] == [("C2", "待付款"), ("C3", "待核验"), ("C1", "待付款")]
    assert (result["summary"]["to_pay_amount"], result["summary"]["to_pay_count"], result["summary"]["to_pay_urgent"]) == (100.0, 2, 1)


def test_invoice_tracking_counts_overdue_and_reminders():
    rows = [
        claim("C1", "付款单", business_status="已付款·待补票", invoice_followup_status="待收票", expected_invoice_date="2026-09-20", amount=500, payee_name="甲"),
        claim("C2", "付款单", business_status="已付款·待补票", invoice_followup_status="待收票", expected_invoice_date="2026-09-30", amount=200),
        claim("C3", "付款单", invoice_followup_status="已核验", expected_invoice_date="2026-09-01"),
        claim("C4", "付款单", workflow_status="待审批", invoice_followup_status="待收票", expected_invoice_date="2026-09-01", paid_on=None),
    ]
    result = boards.payment_board(rows, today=TODAY, reminders={"C1": 4})
    assert [(row["name"], row["overdue_days"], row["days_left"], row["reminders"]) for row in result["invoice_tracking"]] == [
        ("C1", 3, 0, 4), ("C2", 0, 7, 0),
    ]
    assert result["invoice_tracking"][0]["payee_name"] == "甲"
    summary = result["summary"]
    assert (summary["invoice_pending_amount"], summary["invoice_pending_count"], summary["invoice_overdue_count"]) == (700.0, 2, 1)


def test_account_and_department_bars_only_count_this_month():
    rows = [claim("C1", amount=100), claim("C2", amount=500, paid_on="2026-08-02", department="财务部")]
    lines = [
        {"parent": "C1", "expense_account_level_1": "管理费用", "expense_account_level_2": "办公费", "total_amount": 60},
        {"parent": "C1", "expense_account_level_1": "管理费用", "expense_account_level_2": "办公费", "total_amount": 40},
        {"parent": "C2", "expense_account_level_1": "管理费用", "expense_account_level_2": "差旅费", "total_amount": 500},
    ]
    result = boards.payment_board(rows, lines, today=TODAY)
    assert result["by_account"] == [["管理费用 / 办公费", 100.0]]
    assert result["by_department"] == [["研发部", 100.0]]


# ---------------------------------------------------------------- 采购页签


def test_procurement_numbers_stay_separate():
    rows = [
        {"name": "PR1", "request_type": "采购申请", "workflow_status": "已完成", "business_status": "需求已批准/待询价", "approved_amount": 5000, "amount": 5000},
        {"name": "PR2", "request_type": "采购申请", "workflow_status": "待审批", "business_status": "待审批", "approved_amount": None, "amount": 800},
        {"name": "PP1", "request_type": "采购付款", "workflow_status": "已付款", "business_status": "待到货", "amount": 1500, "paid_on": "2026-09-05",
         "arrival_status": "未到货", "inspection_status": "未验收", "prepayment_writeoff_status": "待核销"},
    ]
    summary = boards.procurement_board(rows, today=TODAY)["summary"]
    assert summary == {
        "application_count": 2, "application_pending": 1, "application_amount": 5800.0, "payment_count": 1,
        "month_paid_amount": 1500.0, "pending_arrival": 1, "pending_inspection": 1, "pending_writeoff": 1,
    }


def test_procurement_payment_rows_carry_their_purchase_order():
    rows = [
        {"name": "PP1", "request_type": "采购付款", "workflow_status": "已付款", "amount": 100, "paid_on": "2026-09-05",
         "source_purchase_order": "PO-1"},
        {"name": "PP2", "request_type": "采购付款", "workflow_status": "已付款", "amount": 100, "paid_on": "2026-09-05"},
    ]
    payments = boards.procurement_board(rows, today=TODAY)["payments"]
    assert [row["source_purchase_order"] for row in payments] == ["PO-1", ""]


def test_recent_months_crosses_the_year_boundary():
    assert boards.recent_months(date(2026, 2, 15), 4) == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert boards.month_key("2026-09-23 10:00:00") == "2026-09"
    assert boards.trip_status("2026-09-24", "2026-09-25", TODAY) == "未出发"


def test_every_inspection_status_except_passed_is_pending():
    rows = [
        {"name": f"PP{index}", "request_type": "采购付款", "workflow_status": "已付款", "amount": 1, "paid_on": "2026-09-05",
         "inspection_status": status}
        for index, status in enumerate(["未验收", "待验收", "验收不合格", "验收通过", ""])
    ]
    assert boards.procurement_board(rows, today=TODAY)["summary"]["pending_inspection"] == 3



def test_request_board_month_mix_and_flow():
    # 2026-09-30 看板改版：本月提交的申请构成和走到哪一步。
    rows = [
        purchase("P1", creation="2026-09-02 10:00:00", paid_amount=400),
        purchase("P2", creation="2026-09-05 10:00:00", asset_nature="固定资产", approved_amount=3000),
        purchase("P3", creation="2026-09-21 10:00:00", workflow_status="待审批", amount=500, approved_amount=0),
        travel("T1", creation="2026-09-10 10:00:00"),
        purchase("OLD", creation="2026-08-30 10:00:00"),
    ]
    board = boards.request_board(rows, today=TODAY)
    assert board["month_mix"] == [["购买申请 · 非固定资产", 2], ["购买申请 · 固定资产", 1], ["出差申请", 1]]
    flow = {step["key"]: (step["count"], step["amount"]) for step in board["month_flow"]}
    assert flow == {"submitted": (4, 4500.0), "approved": (3, 4000.0), "executed": (2, 1000.0), "pending": (1, 500.0)}
