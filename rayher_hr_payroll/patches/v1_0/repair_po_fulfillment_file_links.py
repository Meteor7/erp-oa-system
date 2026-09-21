"""Repair only Files linked to a fulfillment ID using the wrong parent type."""
import frappe


def execute():
    frappe.db.sql("""
        UPDATE `tabFile` f
        JOIN `tabOA PO Fulfillment Record` r
          ON r.name = f.attached_to_name AND r.evidence_file = f.file_url
        SET f.attached_to_doctype = 'OA PO Fulfillment Record',
            f.attached_to_field = 'evidence_file'
        WHERE f.attached_to_doctype = 'OA Business Document'
          AND NOT EXISTS (SELECT 1 FROM `tabOA Business Document` d WHERE d.name = f.attached_to_name)
    """)
