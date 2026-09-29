"""发票号码统一写法（2026-09-28，模块 3 发票查重）。

查重改成只看发票号码（老版发票含代码），号码按统一写法比较：全角转半角、去掉空白、字母转大写。
这里把已有记录的号码改成统一写法，新旧记录才能对得上；只改写法，不改状态、不重新查重。
已确认发票里号码相同的，用 maintenance/invoice_duplicate_report.report() 只读列出，由财务决定怎么处理。
"""
import frappe

from rayher_hr_payroll.invoice_ocr.domain import normalize_invoice_number

DOCTYPE = "OA Invoice Record"


def execute():
    frappe.reload_doc("rayher_hr_payroll", "doctype", "oa_invoice_record")
    if not frappe.db.table_exists(DOCTYPE, cached=False):
        return
    rows = frappe.get_all(
        DOCTYPE,
        filters={"invoice_number": ["is", "set"]},
        fields=["name", "invoice_number"],
        limit_page_length=0,
    )
    changed = 0
    for row in rows:
        value = normalize_invoice_number(row.get("invoice_number"))
        if value != row.get("invoice_number"):
            frappe.db.set_value(DOCTYPE, row["name"], "invoice_number", value, update_modified=False)
            changed += 1
    frappe.logger("invoice_ocr").info("normalize_invoice_numbers scanned=%s changed=%s", len(rows), changed)
