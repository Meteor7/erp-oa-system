from rayher_hr_payroll.patches.v1_0 import (
    backfill_oa_business_and_asset_status as migration,
)


def test_expense_asset_and_business_status_backfill():
    assert migration.changes_for({
        "request_type": "费用付款申请",
        "workflow_status": "已付款",
        "business_status": "",
        "asset_category": "电子类固定资产（IT）",
        "asset_nature": "",
        "fixed_asset_category": "",
    }) == {
        "asset_nature": "固定资产",
        "fixed_asset_category": "电子设备、研发专用设备、仪器仪表",
        "business_status": "已付款",
    }
    assert migration.changes_for({
        "request_type": "费用付款申请",
        "workflow_status": "待办理",
        "business_status": "待审批",
        "asset_category": "其他",
        "asset_nature": "",
        "fixed_asset_category": "",
    }) == {
        "asset_nature": "非固定资产",
        "business_status": "待付款",
    }


def test_leave_business_status_backfill():
    assert migration.changes_for({
        "request_type": "请假申请",
        "workflow_status": "已完成",
        "business_status": "",
    }) == {"business_status": "已完成"}
