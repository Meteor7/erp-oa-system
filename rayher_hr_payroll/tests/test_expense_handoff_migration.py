from rayher_hr_payroll.maintenance import expense_handoff_migration as migration


def test_build_migration_plan_canonicalizes_legacy_payment_type_without_rewriting_paid_business_values():
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
        {
            "name": "OA-4",
            "workflow_status": "待审批",
            "source_type": "手工新建",
            "payment_type": "付款申请",
            "department": "研发部",
        },
        {
            "name": "OA-5",
            "workflow_status": "已付款",
            "source_type": "手工新建",
            "payment_type": "付款申请",
            "department": "总经理室",
        },
    ]

    assert migration.build_migration_plan(rows) == [
        {
            "name": "OA-1",
            "changes": {"department": "总经办"},
        },
        {
            "name": "OA-2",
            "changes": {"department": "总经办"},
        },
        {
            "name": "OA-4",
            "changes": {"payment_type": "支付个人"},
        },
        {
            "name": "OA-5",
            "changes": {"payment_type": "支付个人"},
        },
    ]
