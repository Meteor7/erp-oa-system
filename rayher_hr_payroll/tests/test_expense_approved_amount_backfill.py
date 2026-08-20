from rayher_hr_payroll.patches.v1_0 import (
    backfill_expense_approved_amount as migration,
)


def test_completed_expense_approved_amount_is_backfilled():
    assert migration.approved_amount_change({
        "request_type": "费用付款申请",
        "workflow_status": "已付款",
        "amount": 200,
        "approved_amount": 0,
    }) == {"approved_amount": 200.0}
    assert migration.approved_amount_change({
        "request_type": "费用付款申请",
        "workflow_status": "待审批",
        "amount": 200,
        "approved_amount": 0,
    }) == {}
    assert migration.approved_amount_change({
        "request_type": "费用付款申请",
        "workflow_status": "已完成",
        "amount": 200,
        "approved_amount": 180,
    }) == {}
