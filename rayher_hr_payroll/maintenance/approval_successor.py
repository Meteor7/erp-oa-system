"""Explicitly configure the reviewed approval successor without inventing an Employee."""
import json
import secrets
from functools import partial
from pathlib import Path
from unittest.mock import patch

import frappe

from rayher_hr_payroll.maintenance.identity_alignment import (
    business_snapshot, enqueue_without_contact_sync, verify_backup,
)
from rayher_hr_payroll.oa_role_resolver import resolve_role

WILLIAM = "person031@staff.example.invalid"


def provision(backup_path):
    frappe.only_for("System Manager")
    if not frappe.conf.get("maintenance_mode"):
        raise ValueError("Maintenance mode required")
    verify_backup(backup_path, expected_database=frappe.conf.db_name)
    before = business_snapshot({})
    before.pop("tabOA Approval Role Assignment", None)
    existing = frappe.db.get_value("User", WILLIAM, ["name", "full_name"], as_dict=True)
    if existing and existing.full_name != "William Liu":
        raise ValueError("William target account belongs to another name")
    if frappe.db.exists("Employee", {"user_id": WILLIAM}):
        raise ValueError("William already has an Employee; review that binding first")
    credential = None
    try:
        with patch.object(frappe, "enqueue",
                          partial(enqueue_without_contact_sync, frappe.enqueue)):
            if not existing:
                password = secrets.token_urlsafe(24)
                doc = frappe.get_doc({
                    "doctype": "User", "email": WILLIAM, "first_name": "William Liu",
                    "enabled": 1, "user_type": "System User", "send_welcome_email": 0,
                    "new_password": password, "roles": [{"role": "HR User"}],
                }).insert(ignore_permissions=True)
                credential = {"user": WILLIAM, "password": password}
            else:
                doc = frappe.get_doc("User", WILLIAM)
                if not doc.enabled:
                    raise ValueError("Existing William account disabled; review before enabling")
                if "HR User" not in {r.role for r in doc.roles}:
                    doc.append("roles", {"role": "HR User"})
                    doc.save(ignore_permissions=True)
            name = frappe.db.get_value("OA Approval Role Assignment",
                                       {"role_key": "hr_manager"}, "name")
            assignment = (frappe.get_doc("OA Approval Role Assignment", name)
                          if name else frappe.new_doc("OA Approval Role Assignment"))
            assignment.update({"role_key": "hr_manager", "role_label": "人事经理",
                               "employee": None, "user": WILLIAM, "enabled": 1})
            assignment.save(ignore_permissions=True)
            finance_employee = frappe.db.get_value(
                "Employee", {"employee_name": "演示员工32", "status": "Active"}, "name")
            if not finance_employee:
                raise ValueError("Reviewed finance successor has no active Employee")
            finance_name = frappe.db.get_value("OA Approval Role Assignment",
                                              {"role_key": "finance_auditor"}, "name")
            finance = (frappe.get_doc("OA Approval Role Assignment", finance_name)
                       if finance_name else frappe.new_doc("OA Approval Role Assignment"))
            finance.update({"role_key": "finance_auditor", "role_label": "出纳",
                            "employee": finance_employee, "user": "person055@staff.example.invalid",
                            "enabled": 1})
            finance.save(ignore_permissions=True)
        assert resolve_role("hr_manager")["user"] == WILLIAM
        assert resolve_role("finance_auditor")["user"] == "person055@staff.example.invalid"
        after = business_snapshot({})
        after.pop("tabOA Approval Role Assignment", None)
        # User.insert may create exactly its own new DocShare; no old share is changed.
        if not existing:
            after = business_snapshot({}, {WILLIAM})
            after.pop("tabOA Approval Role Assignment", None)
        if before != after:
            raise ValueError("Business data changed while configuring approval successor")
        private = Path(frappe.get_site_path("private", "identity-alignment"))
        private.mkdir(parents=True, exist_ok=True)
        if credential:
            path = private / "william-initial-credential.json"
            with path.open("x", encoding="utf-8") as stream:
                path.chmod(0o600)
                json.dump(credential, stream)
        frappe.db.commit()
        frappe.clear_cache()
        return {"user": WILLIAM, "created": not bool(existing),
                "employee_pending": True, "hr_role": resolve_role("hr_manager"),
                "finance_role": resolve_role("finance_auditor")}
    except Exception:
        frappe.db.rollback()
        raise
