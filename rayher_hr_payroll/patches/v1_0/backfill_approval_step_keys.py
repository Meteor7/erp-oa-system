"""Backfill stable identities for existing approval route steps."""

from uuid import NAMESPACE_URL, uuid5

import frappe

STEP_DOCTYPE = "OA Approval Step"


def stable_step_key(parent, index):
    return str(uuid5(NAMESPACE_URL, f"rayher:oa-approval-step:{parent}:{int(index)}"))


def execute():
    frappe.reload_doc("rayher_hr_payroll", "doctype", "oa_approval_step")
    if not frappe.db.table_exists(STEP_DOCTYPE, cached=False):
        frappe.logger("oa_approval").info(
            "backfill_approval_step_keys skipped: table missing"
        )
        return

    rows = frappe.db.sql(
        """
        SELECT name, parent, idx, step_index, step_key, origin
        FROM `tabOA Approval Step`
        WHERE step_key IS NULL OR step_key = '' OR origin IS NULL OR origin = ''
        ORDER BY parent, idx
        """,
        as_dict=True,
    )
    updated = 0
    for row in rows:
        index = row.get("step_index") or row.get("idx") or 1
        values = {}
        if not row.get("step_key"):
            values["step_key"] = stable_step_key(row["parent"], index)
        if not row.get("origin"):
            values["origin"] = "base"
        if values:
            frappe.db.set_value(
                STEP_DOCTYPE,
                row["name"],
                values,
                update_modified=False,
            )
            updated += 1
    frappe.logger("oa_approval").info(
        "backfill_approval_step_keys scanned=%s updated=%s",
        len(rows),
        updated,
    )