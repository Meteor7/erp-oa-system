"""Reviewed designation alignment and unreferenced excluded employee removal."""
import json
from pathlib import Path
import secrets
from rayher_hr_payroll.maintenance.identity_alignment import digest, business_snapshot, verify_backup, quote

def plan(source, current):
    if len(source) != 85 or len({x["name"] for x in source}) != 85:
        raise ValueError("Expected 85 unique reviewed employees")
    by_id = {x["name"]: x for x in current}
    changes = []
    for row in source:
        old = by_id.get(row["name"])
        if not old or old["employee_name"] != row["employee_name"]:
            raise ValueError("Identity mismatch: " + row["name"])
        if (old.get("designation") or None) != (row.get("designation") or None):
            changes.append(dict(employee=row["name"], person=row["employee_name"],
                                before=old.get("designation"), after=row.get("designation") or None))
    extra = set(by_id) - {x["name"] for x in source}
    if extra - {"HR-EMP-90006"}:
        raise ValueError("Unexpected extra employees")
    remove = None
    if extra:
        row = by_id["HR-EMP-90006"]
        if row["employee_name"] != "演示员工182" or row.get("user_id"):
            raise ValueError("Excluded identity changed")
        remove = row["name"]
    return dict(changes=changes, remove=remove, fingerprint=digest([source, current]))

def snapshot():
    import frappe
    return [dict(r) for r in frappe.db.sql("SELECT * FROM tabEmployee ORDER BY name", as_dict=True)]

def references(employee, person):
    import frappe
    hits = []
    columns = frappe.db.sql("""SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND DATA_TYPE IN ('varchar','char','text','mediumtext','longtext','json')""", as_dict=True)
    for row in columns:
        table, col = row.TABLE_NAME, row.COLUMN_NAME
        # Own Employee row and derived search index are handled by native deletion.
        where = " WHERE (" + quote(col) + " LIKE %s OR " + quote(col) + " LIKE %s)"
        values = ["%" + employee + "%", "%" + person + "%"]
        if table == "tabEmployee":
            where += " AND name != %s"
            values.append(employee)
        if table == "__global_search":
            where += " AND NOT (doctype='Employee' AND name=%s)"
            values.append(employee)
        count = frappe.db.sql("SELECT COUNT(*) FROM " + quote(table) + where, values)[0][0]
        if count:
            hits.append([table, col, count])
    return hits

def apply(source, fingerprint, backup, rehearsal=False):
    import frappe
    from rayher_hr_payroll.oa_role_resolver import ROLE_SPECS, resolve_role
    frappe.only_for("System Manager")
    if not frappe.conf.get("maintenance_mode"):
        raise ValueError("Maintenance required")
    verify_backup(backup, expected_database=frappe.conf.db_name)
    before = snapshot()
    p = plan(source, before)
    if p["fingerprint"] != fingerprint:
        raise ValueError("Data changed since review")
    expected = {r["name"]: dict(r) for r in before}
    business = business_snapshot({})
    roles = digest(frappe.db.sql("SELECT * FROM `tabHas Role` ORDER BY name", as_dict=True))
    auth = digest(frappe.db.sql("SELECT * FROM __Auth ORDER BY doctype,name,fieldname", as_dict=True))
    positions = {key: resolve_role(key) for key in ROLE_SPECS}
    report = dict(plan=p, backup=backup, state="prepared")
    directory = Path(frappe.get_site_path("private", "designation-alignment"))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (secrets.token_hex(8) + ".json")
    committed = False
    try:
        if p["remove"]:
            hits = references(p["remove"], "演示员工182")
            if hits:
                raise ValueError("Historical references block deletion: " + repr(hits))
            frappe.delete_doc("Employee", p["remove"], ignore_permissions=True)
            expected.pop(p["remove"])
        for change in p["changes"]:
            value = change["after"]
            if value and not frappe.db.exists("Designation", value):
                frappe.get_doc({"doctype": "Designation", "designation_name": value}).insert(ignore_permissions=True)
            frappe.db.set_value("Employee", change["employee"], "designation", value, update_modified=False)
            expected[change["employee"]]["designation"] = value
        if snapshot() != [expected[k] for k in sorted(expected)]:
            raise ValueError("Unexpected Employee change")
        if business_snapshot({}) != business:
            raise ValueError("Business data changed")
        if {key: resolve_role(key) for key in ROLE_SPECS} != positions:
            raise ValueError("Position holder changed")
        if digest(frappe.db.sql("SELECT * FROM `tabHas Role` ORDER BY name", as_dict=True)) != roles:
            raise ValueError("Roles changed")
        if digest(frappe.db.sql("SELECT * FROM __Auth ORDER BY doctype,name,fieldname", as_dict=True)) != auth:
            raise ValueError("Credentials changed")
        report.update(business=business, employees_after=digest(snapshot()), positions=positions)
        if rehearsal:
            frappe.db.rollback()
            if snapshot() != before:
                raise ValueError("Rollback verification failed")
            report["state"] = "rehearsed-and-rolled-back"
        else:
            report["state"] = "commit-started"
            path.write_text(json.dumps(report, ensure_ascii=False, default=str), encoding="utf-8")
            path.chmod(0o600)
            frappe.db.commit()
            committed = True
            report["state"] = "committed"
        path.write_text(json.dumps(report, ensure_ascii=False, default=str), encoding="utf-8")
        path.chmod(0o600)
        frappe.clear_cache()
        return dict(state=report["state"], changed=len(p["changes"]), removed=p["remove"], report=str(path))
    except Exception:
        frappe.db.rollback()
        report["state"] = "committed-verification-error" if committed else ("commit-outcome-unknown" if report["state"] == "commit-started" else "rolled-back")
        path.write_text(json.dumps(report, ensure_ascii=False, default=str), encoding="utf-8")
        path.chmod(0o600)
        raise
