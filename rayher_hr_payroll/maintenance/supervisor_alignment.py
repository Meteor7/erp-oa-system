"""Gated reports_to alignment from a reviewed local Employee snapshot."""
import json
from pathlib import Path
import secrets

from rayher_hr_payroll.maintenance.identity_alignment import digest


def build_plan(source, current):
    if len(source) != 85:
        raise ValueError("Expected reviewed 85-person source")
    source_by_id = {row["name"]: row for row in source}
    current_by_id = {row["name"]: row for row in current}
    if len(source_by_id) != len(source):
        raise ValueError("Duplicate source identity")
    changes = []
    for row in source:
        existing = current_by_id.get(row["name"])
        if not existing or existing["employee_name"] != row["employee_name"]:
            raise ValueError("Employee identity differs: " + row["name"])
        parent = row.get("reports_to") or None
        if parent:
            if parent not in source_by_id or parent not in current_by_id:
                raise ValueError("Supervisor missing: " + parent)
            if source_by_id[parent]["employee_name"] != current_by_id[parent]["employee_name"]:
                raise ValueError("Supervisor identity mismatch")
            if row["status"] == "Active" and source_by_id[parent]["status"] != "Active":
                raise ValueError("Active employee has inactive supervisor")
        visited = {row["name"]}
        cursor = parent
        while cursor:
            if cursor in visited:
                raise ValueError("Supervisor cycle")
            visited.add(cursor)
            cursor = source_by_id[cursor].get("reports_to")
        old = existing.get("reports_to") or None
        if old != parent:
            changes.append({"employee": row["name"], "person": row["employee_name"],
                            "before": old, "after": parent})
    return {"changes": changes, "fingerprint": digest([source, current])}


def snapshot():
    import frappe
    return [dict(row) for row in frappe.db.sql("SELECT * FROM tabEmployee ORDER BY name", as_dict=True)]


def apply(source, fingerprint, backup, rehearsal=False):
    import frappe
    from rayher_hr_payroll.maintenance.identity_alignment import business_snapshot, verify_backup
    frappe.only_for("System Manager")
    if not frappe.conf.get("maintenance_mode"):
        raise ValueError("Maintenance required")
    verify_backup(backup, expected_database=frappe.conf.db_name)
    before_employees = snapshot()
    plan = build_plan(source, before_employees)
    if plan["fingerprint"] != fingerprint:
        raise ValueError("Employee data changed since review")
    before_business = business_snapshot({})
    expected = {row["name"]: dict(row) for row in before_employees}
    report = {"state": "prepared", "backup": backup, **plan,
              "business_before": before_business, "employee_before": digest(before_employees)}
    path = Path(frappe.get_site_path("private", "supervisor-alignment"))
    path.mkdir(parents=True, exist_ok=True)
    report_path = path / (secrets.token_hex(8) + ".json")
    committed = False
    try:
        for change in plan["changes"]:
            frappe.db.set_value("Employee", change["employee"], "reports_to",
                                change["after"], update_modified=False)
            expected[change["employee"]]["reports_to"] = change["after"]
        after_employees = snapshot()
        if after_employees != [expected[k] for k in sorted(expected)]:
            raise ValueError("Unexpected Employee field modification")
        after_business = business_snapshot({})
        if after_business != before_business:
            raise ValueError("Historical business data changed")
        report.update(business_after=after_business, employee_after=digest(after_employees))
        if rehearsal:
            frappe.db.rollback()
            assert snapshot() == before_employees
            report["state"] = "rehearsed-and-rolled-back"
        else:
            report["state"] = "commit-started"
            report_path.write_text(json.dumps(report, ensure_ascii=False, default=str))
            report_path.chmod(0o600)
            frappe.db.commit()
            committed = True
            report["state"] = "committed"
        report_path.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2))
        report_path.chmod(0o600)
        frappe.clear_cache()
        return {"state": report["state"], "changes": len(plan["changes"]), "report": str(report_path)}
    except Exception:
        frappe.db.rollback()
        report["state"] = "committed-verification-error" if committed else (
            "commit-outcome-unknown" if report["state"] == "commit-started" else "rolled-back")
        report_path.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2))
        report_path.chmod(0o600)
        raise
