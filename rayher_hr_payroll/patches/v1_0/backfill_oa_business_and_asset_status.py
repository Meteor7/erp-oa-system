"""Backfill dashboard asset fields and business states for existing OA records."""


EXPENSE_ASSET_FIELDS = {
    "非电子类固定资产（人事/行政）": ("固定资产", "办公家具、工具及器具"),
    "电子类固定资产（IT）": ("固定资产", "电子设备、研发专用设备、仪器仪表"),
    "生产设备、生产工具及器具": ("固定资产", "生产设备、生产工具及器具"),
    "其他": ("非固定资产", ""),
    "其它": ("非固定资产", ""),
}


def changes_for(row):
    request_type = str(row.get("request_type") or "").strip()
    workflow_status = str(row.get("workflow_status") or "").strip()
    changes = {}
    if request_type == "费用付款申请":
        asset_category = str(row.get("asset_category") or "").strip()
        asset_nature, fixed_category = EXPENSE_ASSET_FIELDS.get(
            asset_category, ("非固定资产", "")
        )
        if row.get("asset_nature") != asset_nature:
            changes["asset_nature"] = asset_nature
        if (row.get("fixed_asset_category") or "") != fixed_category:
            changes["fixed_asset_category"] = fixed_category
        target_status = {
            "待审批": "待审批",
            "待办理": "待付款",
            "已完成": "待付款",
            "已付款": "已付款",
        }.get(workflow_status)
        if target_status and row.get("business_status") != target_status:
            changes["business_status"] = target_status
    elif request_type == "请假申请":
        target_status = {
            "待审批": "待审批",
            "已完成": "已完成",
        }.get(workflow_status)
        if target_status and row.get("business_status") != target_status:
            changes["business_status"] = target_status
    return changes


def execute():
    import frappe

    rows = frappe.get_all(
        "OA Approval Request",
        filters={"request_type": ["in", ["费用付款申请", "请假申请"]]},
        fields=[
            "name",
            "request_type",
            "workflow_status",
            "business_status",
            "asset_category",
            "asset_nature",
            "fixed_asset_category",
        ],
        limit_page_length=0,
    )
    for row in rows:
        changes = changes_for(row)
        if changes:
            frappe.db.set_value(
                "OA Approval Request",
                row.name,
                changes,
                update_modified=False,
            )
