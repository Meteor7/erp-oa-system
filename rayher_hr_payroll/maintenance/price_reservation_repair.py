"""Guarded repair for the audited local legacy double-withdrawal record.

Not an automatic patch: run only on the audited local site after schema reload.
"""
import json
import os
from pathlib import Path

import frappe


def repair(apply=False):
    approval = frappe.get_doc("OA Price Approval", "PA-2026-18164", for_update=True)
    pr = frappe.get_doc("OA Procurement Request", "PR-2026-18163", for_update=True)
    line = next(row for row in pr.lines if row.name == "kgo6d6156j")
    if approval.status != "草稿" or len(approval.lines) != 1:
        frappe.throw("Repair precondition changed: approval status or lines.")
    source = approval.lines[0]
    if (source.source_pr, source.source_pr_line, source.source_request, float(source.quantity)) != (
            pr.name, line.name, "OA-2026-18161", 1.0):
        frappe.throw("Repair precondition changed: source references.")
    if float(line.quantity) != 1 or float(line.po_quantity or 0) != 0:
        frappe.throw("Repair precondition changed: quantities.")
    if frappe.db.count("OA Purchase Order Line", {"source_pr_line": line.name}):
        frappe.throw("Repair aborted: linked purchase order exists.")
    linked = frappe.get_all("OA Price Approval Line", filters={"source_pr_line": line.name},
                            pluck="parent")
    if set(linked) != {approval.name}:
        frappe.throw("Repair aborted: another price approval exists.")
    if float(line.remaining_quantity) == 1 and approval.pr_quantities_released:
        return {"changed": False, "already_repaired": True}
    if float(line.remaining_quantity) != 2 or approval.pr_quantities_released:
        frappe.throw("Repair precondition changed: legacy balance.")
    withdrawals = frappe.get_all("Notification Log", filters={
        "document_type": "OA Price Approval", "document_name": approval.name,
        "subject": ["like", "价格审批单已撤回：%"]}, fields=["subject", "creation"])
    if len({row.subject for row in withdrawals}) != 2:
        frappe.throw("Repair aborted: expected two withdrawal events.")
    result = {"approval": approval.name, "pr": pr.name, "line": line.name,
              "remaining_before": 2, "remaining_after": 1, "changed": False}
    if not apply:
        return result
    path = Path(frappe.get_site_path("private", "price-reservation-repair"))
    path.mkdir(parents=True, exist_ok=True)
    backup = path / "PA-2026-18164-before.json"
    # Exclusive creation prevents a repeated repair from replacing the evidence.
    with backup.open("x", encoding="utf-8") as handle:
        json.dump({"approval": approval.as_dict(), "pr": pr.as_dict(),
                   "withdrawals": withdrawals, "repair": result}, handle,
                  ensure_ascii=False, default=str, indent=2)
    os.chmod(backup, 0o600)
    frappe.db.set_value("OA Procurement Request Line", line.name, "remaining_quantity", 1,
                        update_modified=False)
    frappe.db.set_value("OA Price Approval", approval.name, "pr_quantities_released", 1,
                        update_modified=False)
    result.update(changed=True, backup=str(backup))
    # Caller owns the transaction and must verify before committing.
    return result
