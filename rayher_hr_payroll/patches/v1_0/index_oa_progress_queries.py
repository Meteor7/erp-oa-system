import frappe


def execute():
    for doctype, fields, name in (
        ("OA Approval Request", ["workflow_status", "modified", "name"], "oa_status_modified"),
        ("OA Approval Request", ["employee", "modified"], "oa_employee_modified"),
        ("OA Approval Step", ["parent", "step_index"], "oa_parent_step"),
        ("OA Material Progress", ["source_request", "source_line"], "oa_material_source"),
        ("OA Material Progress", ["modified", "name"], "oa_material_modified"),
        ("OA Procurement Request Line", ["source_request", "source_line"], "pr_source_line"),
        ("OA Price Approval Line", ["source_request", "source_line"], "price_source_line"),
        ("OA Purchase Order Line", ["source_request", "source_line"], "po_source_line"),
    ):
        frappe.db.add_index(doctype, fields, index_name=name)
