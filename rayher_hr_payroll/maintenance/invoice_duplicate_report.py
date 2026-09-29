"""只读报告（2026-09-28，模块 3 发票查重）：按新的查重规则列出已确认发票里的重复组。

规则：只看发票号码；老版发票两边都有代码时代码也要相同（见 invoice_ocr.domain.same_invoice）。
只查询，不改任何数据；这些发票要不要处理由财务决定。

用法：bench --site <site> execute rayher_hr_payroll.maintenance.invoice_duplicate_report.report
"""
import frappe

from rayher_hr_payroll.invoice_ocr.domain import normalize_invoice_number, same_invoice

FIELDS = ["name", "owner", "invoice_number", "invoice_code", "issue_date", "total_amount", "request"]


def report():
    rows = frappe.get_all(
        "OA Invoice Record",
        filters={"recognition_status": "已确认"},
        fields=FIELDS,
        order_by="creation asc",
        limit_page_length=0,
    )
    by_number = {}
    for row in rows:
        number = normalize_invoice_number(row.get("invoice_number"))
        if number:
            by_number.setdefault(number, []).append(row)
    groups = []
    for number, items in by_number.items():
        while len(items) > 1:
            first, rest = items[0], items[1:]
            same = [row for row in rest if same_invoice(number, first.get("invoice_code"), row.get("invoice_number"), row.get("invoice_code"))]
            if same:
                group = [first] + same
                groups.append({
                    "invoice_number": number,
                    "records": [{key: ("" if row.get(key) is None else str(row.get(key))) for key in FIELDS} for row in group],
                })
            items = [row for row in rest if row not in same]
    return {"confirmed": len(rows), "duplicate_groups": len(groups), "groups": groups}
