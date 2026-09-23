"""停用旧费用付款申请前后的对账报表（只读）。

用法（在 bench 容器里）：
    bench --site <site> execute rayher_hr_payroll.maintenance.legacy_expense_report.report

列出还没走完的旧费用付款申请和旧消费明细。不删除、不修改任何数据：测试单据要不要删，
由使用方自己决定。
"""
from __future__ import annotations

import frappe

LEGACY_TYPE = "费用付款申请"
OPEN_STATUSES = ("草稿", "待审批", "待办理", "待流转", "已完成")


def report():
    rows = frappe.get_all(
        "OA Approval Request",
        filters={"request_type": LEGACY_TYPE},
        fields=["name", "workflow_status", "business_status", "employee_name", "subject", "amount",
                "invoice_followup_status", "paid_on", "creation"],
        order_by="creation asc",
        limit_page_length=0,
    )
    open_rows = [row for row in rows if row["workflow_status"] in OPEN_STATUSES]
    pending_invoices = [row for row in rows if row.get("invoice_followup_status") == "待收票"]
    consumption = frappe.db.count("OA Consumption Detail")
    print(f"旧费用付款申请共 {len(rows)} 张，其中未走完 {len(open_rows)} 张，待补票 {len(pending_invoices)} 张；旧消费明细 {consumption} 条。")
    for row in open_rows:
        print(f"  未走完：{row['name']} {row['workflow_status']}/{row['business_status'] or '-'} "
              f"{row['employee_name']} {row['subject']} {row['amount']}")
    for row in pending_invoices:
        print(f"  待补票：{row['name']} 付款日 {row['paid_on']} {row['subject']}")
    return {"total": len(rows), "open": [row["name"] for row in open_rows],
            "pending_invoices": [row["name"] for row in pending_invoices], "consumption_details": consumption}
