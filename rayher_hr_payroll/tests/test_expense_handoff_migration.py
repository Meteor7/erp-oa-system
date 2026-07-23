from rayher_hr_payroll.maintenance import expense_handoff_migration as migration


def test_build_migration_plan_only_changes_unpaid_relevant_values():
    rows = [
        {
            "name": "OA-1",
            "workflow_status": "审批中",
            "source_type": "发票下推",
            "payment_type": "对公支付",
            "department": "总经理室",
        },
        {
            "name": "OA-2",
            "workflow_status": "草稿",
            "source_type": "手工新建",
            "payment_type": "对公支付",
            "department": "总经理室",
        },
        {
            "name": "OA-3",
            "workflow_status": "已付款",
            "source_type": "发票下推",
            "payment_type": "对公支付",
            "department": "总经理室",
        },
    ]

    assert migration.build_migration_plan(rows) == [
        {
            "name": "OA-1",
            "changes": {"payment_type": "支付个人", "department": "总经办"},
        },
        {
            "name": "OA-2",
            "changes": {"department": "总经办"},
        },
    ]
