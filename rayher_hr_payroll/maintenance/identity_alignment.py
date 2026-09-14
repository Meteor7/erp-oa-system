"""Explicit, gated identity migration; never restore or replace a business database.

Run plan() first. apply() is internal-only and requires maintenance mode, a verified
backup, and the exact reviewed plan fingerprint. No patch registration is used.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import secrets
from unittest.mock import patch

import frappe

MANIFEST = Path(__file__).with_name("identity_alignment_manifest.json")
BUSINESS_PREFIXES = (
    "Accommodation", "Timesheet", "RD ", "OA ", "Project", "Expense",
    "Salary", "Payroll", "Leave", "GL Entry", "Payment", "File", "Contact",
    "Address", "ToDo", "DocShare",
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str,
                                     ensure_ascii=True).encode()).hexdigest()


def replace_value(value, mapping):
    """Replace exact identifiers, including JSON tokens; never substring-replace prose."""
    if isinstance(value, dict):
        return {mapping.get(k, k): replace_value(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_value(v, mapping) for v in value]
    if not isinstance(value, str):
        return value
    if value in mapping:
        return mapping[value]
    if value[:1] in ("[", "{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        changed = replace_value(parsed, mapping)
        if changed != parsed:
            return json.dumps(changed, ensure_ascii=False, separators=(",", ":"))
    return value


def normalize(value, mapping):
    if isinstance(value, dict):
        return {mapping.get(k, k): normalize(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v, mapping) for v in value]
    if isinstance(value, str):
        if value in mapping:
            return mapping[value]
        if value[:1] in ("[", "{"):
            try:
                return normalize(json.loads(value), mapping)
            except ValueError:
                pass
    return value


def load_manifest():
    result = json.loads(MANIFEST.read_text(encoding="utf-8"))
    people = result["people"]
    for field in ("name", "employee_name", "target_user"):
        values = [p[field] for p in people]
        if len(values) != len(set(values)):
            raise ValueError("Duplicate manifest " + field)
    if len(people) != 85:
        raise ValueError("Expected the reviewed 85-person manifest")
    return result


def build_plan(manifest, employees, users):
    users_by_id = {u["name"]: u for u in users}
    by_id = {e["name"]: e for e in employees}
    result = []
    for source in manifest["people"]:
        matches = [e for e in employees if e["employee_name"] == source["employee_name"]]
        if len(matches) > 1:
            raise ValueError("Ambiguous person: " + source["employee_name"])
        employee = matches[0] if matches else None
        linked = employee.get("user_id") if employee else None
        candidates = [u["name"] for u in users if (
            u["name"] == linked or u.get("full_name") == source["employee_name"]
            or (source["employee_name"] == "演示员工247"
                and u["name"] == "person050@staff.example.invalid")
        )]
        target = source["target_user"]
        if target in users_by_id and target not in candidates:
            raise ValueError("Account occupied by another identity: " + target)
        for candidate in candidates:
            foreign = [e for e in employees if e.get("user_id") == candidate
                       and e["employee_name"] != source["employee_name"]]
            if foreign:
                raise ValueError("Account linked to another employee: " + candidate)
        primary = target if target in candidates else linked if linked in candidates else (
            candidates[0] if len(candidates) == 1 else None)
        if candidates and not primary:
            raise ValueError("Ambiguous primary account: " + source["employee_name"])
        current_id = employee["name"] if employee else None
        occupant = by_id.get(source["name"])
        if occupant and occupant["employee_name"] != source["employee_name"]:
            if occupant["employee_name"] not in {p["employee_name"] for p in manifest["people"]}:
                raise ValueError("Target employee ID occupied outside reviewed roster")
        result.append({
            "person": source["employee_name"], "employee": current_id,
            "target_employee": source["name"], "primary_user": primary,
            "target_user": target, "aliases": sorted(candidates),
            "status": source["status"], "relieving_date": source.get("relieving_date"),
            "roles": sorted(source["roles"] or ["Employee"]),
        })
    return result


def plan():
    manifest = load_manifest()
    employees = frappe.get_all("Employee",
        fields=["name", "employee_name", "user_id", "status", "relieving_date"], order_by="name")
    users = frappe.get_all("User",
        fields=["name", "full_name", "enabled", "user_type"], order_by="name")
    rows = build_plan(manifest, employees, users)
    roles = frappe.get_all("Has Role", filters={"parenttype": "User"},
                           fields=["parent", "role"], order_by="parent,role")
    return {"rows": rows, "fingerprint": digest({
        "manifest": manifest, "employees": employees, "users": users, "roles": roles})}


def mappings(rows):
    employee = {r["employee"]: r["target_employee"] for r in rows
                if r["employee"] and r["employee"] != r["target_employee"]}
    user = {old: r["target_user"] for r in rows for old in r["aliases"]
            if old != r["target_user"]}
    return employee, user


def business_snapshot(mapping):
    result = {}
    for table in sorted(frappe.db.get_tables()):
        if not table.startswith("tab") or not table[3:].startswith(BUSINESS_PREFIXES):
            continue
        columns = frappe.db.get_table_columns(table)
        if "name" not in columns:
            continue
        rows = frappe.db.sql("SELECT * FROM " + quote(table) + " ORDER BY name", as_dict=True)
        canonical = [normalize(dict(row), mapping) for row in rows]
        result[table] = {"count": len(rows), "digest": digest(canonical)}
    return result


def quote(identifier):
    return "`" + identifier.replace("`", "``") + "`"


def repair_text_references(mapping):
    # Link/Dynamic Link are handled by Frappe rename. These exact-token repairs cover
    # Data/JSON fields such as step.approvers, action_by, _assign and source snapshots.
    changed = {}
    user_children = {"tab" + f.options for f in frappe.get_meta("User").get_table_fields()}
    excluded = {"tabUser", "tabSessions", "tabVersion", "tabComment", "tabActivity Log"} | user_children
    for table in frappe.db.get_tables():
        if not table.startswith("tab") or table in excluded:
            continue
        descriptions = frappe.db.get_table_columns_description(table)
        if not any(c["name"] == "name" for c in descriptions):
            continue
        fields = [c["name"] for c in descriptions
                  if c["name"] != "name" and any(t in str(c.get("type", "")).lower()
                                               for t in ("char", "text", "json"))]
        if not fields:
            continue
        for row in frappe.db.sql("SELECT " + ",".join(quote(c) for c in ["name", *fields])
                                + " FROM " + quote(table), as_dict=True):
            for field in fields:
                old = row[field]
                new = replace_value(old, mapping)
                if new != old:
                    frappe.db.sql("UPDATE " + quote(table) + " SET " + quote(field)
                                  + "=%s WHERE name=%s", (new, row["name"]))
                    key = table + "." + field
                    changed[key] = changed.get(key, 0) + 1
    return changed


def redirect_alias(old, new):
    """Keep the secondary User record disabled, while reassigning its references."""
    from frappe.model.rename_doc import get_link_fields, update_link_field_values, rename_dynamic_links
    update_link_field_values(get_link_fields("User"), old, new, "User")
    rename_dynamic_links("User", old, new)
    for table in frappe.db.get_tables():
        columns = frappe.db.get_table_columns(table)
        for field in ("owner", "modified_by"):
            if field in columns:
                frappe.db.sql("UPDATE " + quote(table) + " SET " + quote(field)
                              + "=%s WHERE " + quote(field) + "=%s", (new, old))
    frappe.db.set_value("User", old, "enabled", 0, update_modified=False)


def auth_fingerprints(rows):
    result = {}
    for row in rows:
        if row["primary_user"]:
            hashes = frappe.db.sql(
                "SELECT fieldname,password,encrypted FROM __Auth WHERE doctype='User' AND name=%s ORDER BY fieldname,encrypted",
                row["primary_user"])
            result[row["target_user"]] = digest(hashes)
    return result


def verify_backup(path):
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("A fresh database backup is required")
    with gzip.open(path, "rb") as stream:
        header = stream.read(2048)
        if b"MySQL" not in header and b"MariaDB" not in header:
            raise ValueError("Unexpected database backup header")
        while stream.read(1024 * 1024):
            pass
    return str(path)


def _write_private(path, payload):
    with open(path, "x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(payload, stream, ensure_ascii=False, default=str, indent=2)


def apply(expected_fingerprint, backup_path, seed_path=None, rehearsal=False,
          fail_after_users=False):
    """Apply a reviewed plan. Rehearsal exercises real writes then rolls them back."""
    frappe.only_for("System Manager")
    if not frappe.conf.get("maintenance_mode"):
        raise ValueError("Identity cutover requires maintenance mode")
    if rehearsal and "identity-qa" not in frappe.local.site:
        raise ValueError("Rehearsal is restricted to an isolated identity-qa site")
    backup = verify_backup(backup_path)
    reviewed = plan()
    if reviewed["fingerprint"] != expected_fingerprint:
        raise ValueError("Identity data changed since preflight; review the new plan")
    rows = reviewed["rows"]
    employee_map, user_map = mappings(rows)
    full_map = {**employee_map, **user_map}
    missing = [r for r in rows if not r["employee"]]
    seeds = json.loads(Path(seed_path).read_text()) if seed_path else {}
    if any(r["target_employee"] not in seeds for r in missing):
        raise ValueError("Private seed records missing for new employees")
    before = business_snapshot(full_map)
    auth = auth_fingerprints(rows)
    transaction_id = secrets.token_hex(8)
    folder = Path(frappe.get_site_path("private", "identity-alignment"))
    folder.mkdir(parents=True, exist_ok=True)
    credentials_path = folder / (transaction_id + "-new-credentials.json")
    report_path = folder / (transaction_id + "-report.json")
    report = {"state": "prepared", "site": frappe.local.site, "backup": backup,
              "plan": reviewed, "before": before, "rehearsal": bool(rehearsal)}
    _write_private(report_path, report)
    credentials = []
    commit = frappe.db.commit
    original_user = frappe.session.user
    try:
        # Frappe User.after_rename clears sessions through a helper that commits.
        # Defer ALL such commits until every preservation assertion has passed.
        with patch.object(frappe.db, "commit", lambda *a, **k: None):
            temp_names = {}
            for old, target in employee_map.items():
                temp = "IDENTITY-TMP-" + transaction_id + "-" + old
                frappe.rename_doc("Employee", old, temp, force=True, show_alert=False,
                                  rebuild_search=False, ignore_permissions=True)
                temp_names[temp] = target
            for temp, target in temp_names.items():
                frappe.rename_doc("Employee", temp, target, force=True, show_alert=False,
                                  rebuild_search=False, ignore_permissions=True)
                if frappe.db.has_column("Employee", "employee"):
                    frappe.db.set_value("Employee", target, "employee", target, update_modified=False)
            for row in rows:
                old, new = row["primary_user"], row["target_user"]
                if old and old != new:
                    frappe.rename_doc("User", old, new, force=True, show_alert=False,
                                      rebuild_search=False, ignore_permissions=True)
                if not old:
                    password = secrets.token_urlsafe(24)
                    doc = frappe.get_doc({"doctype": "User", "email": new,
                        "first_name": row["person"], "enabled": 0, "user_type": "System User",
                        "send_welcome_email": 0, "new_password": password})
                    doc.insert(ignore_permissions=True)
                    credentials.append({"user": new, "password": password,
                                        "enabled": row["status"] == "Active"})
                for alias in row["aliases"]:
                    if alias not in (old, new):
                        redirect_alias(alias, new)
            if fail_after_users:
                raise RuntimeError("Injected failure after users")
            for row in missing:
                data = dict(seeds[row["target_employee"]])
                data.update(doctype="Employee", first_name=row["person"],
                            employee_name=row["person"], status=row["status"],
                            employee=row["target_employee"])
                data.pop("user_id", None)
                data.pop("reports_to", None)
                data.pop("name", None)
                frappe.get_doc(data).insert(ignore_permissions=True,
                                           set_name=row["target_employee"])
            for row in rows:
                for role in row["roles"]:
                    if not frappe.db.exists("Role", role):
                        frappe.get_doc({"doctype": "Role", "role_name": role,
                                        "desk_access": 1}).insert(ignore_permissions=True)
                user = frappe.get_doc("User", row["target_user"])
                user.first_name, user.middle_name, user.last_name = row["person"], None, None
                user.enabled = int(row["status"] == "Active")
                user.send_welcome_email = 0
                user.set("roles", [{"role": role} for role in row["roles"]])
                user.save(ignore_permissions=True)
                frappe.db.set_value("Employee", row["target_employee"],
                    {"user_id": row["target_user"], "status": row["status"],
                     "relieving_date": row["relieving_date"]}, update_modified=False)
            admin = frappe.get_doc("User", "admin@staff.example.invalid")
            for role in load_manifest()["admin_roles"]:
                if not frappe.db.exists("Role", role):
                    frappe.get_doc({"doctype": "Role", "role_name": role,
                                    "desk_access": 1}).insert(ignore_permissions=True)
            admin.set("roles", [{"role": r} for r in load_manifest()["admin_roles"]])
            admin.save(ignore_permissions=True)
            report["text_repairs"] = repair_text_references(full_map)
            maximum = max(int(r["target_employee"].rsplit("-", 1)[1]) for r in rows)
            frappe.db.sql("""INSERT INTO tabSeries (name,current) VALUES ('HR-EMP-',%s)
                ON DUPLICATE KEY UPDATE current=GREATEST(current,VALUES(current))""", maximum)
            after = business_snapshot({})
            if before != after:
                changed = [t for t in set(before) | set(after) if before.get(t) != after.get(t)]
                raise ValueError("Business preservation mismatch: " + ", ".join(changed))
            for target, expected in auth.items():
                actual = frappe.db.sql(
                    "SELECT fieldname,password,encrypted FROM __Auth WHERE doctype='User' AND name=%s",
                    target)
                if digest(actual) != expected:
                    raise ValueError("Existing password changed: " + target)
            for row in rows:
                actual = frappe.db.get_value("Employee", row["target_employee"],
                                             ["employee_name", "user_id", "status"], as_dict=True)
                if actual.employee_name != row["person"] or actual.user_id != row["target_user"]:
                    raise ValueError("Employee account identity mismatch")
                if actual.status != row["status"]:
                    raise ValueError("Employee status mismatch")
                if bool(frappe.db.get_value("User", row["target_user"], "enabled")) != (
                        row["status"] == "Active"):
                    raise ValueError("Login state mismatch")
            report["after"] = after
            report["passwords_preserved"] = len(auth)
            # Store only new credentials in a private 0600 file, never in tool output.
            _write_private(credentials_path, credentials)
        if rehearsal:
            frappe.db.rollback()
            report["state"] = "rehearsed-and-rolled-back"
        else:
            commit()
            report["state"] = "committed"
        report["new_accounts"] = len(credentials)
        report["credentials_file"] = str(credentials_path) if not rehearsal else None
        report_path.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2))
        frappe.clear_cache()
        return {"state": report["state"], "report": str(report_path),
                "new_accounts": len(credentials), "passwords_preserved": len(auth)}
    except Exception:
        frappe.db.rollback()
        report["state"] = "rolled-back-on-error"
        report_path.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2))
        raise
    finally:
        frappe.set_user(original_user)
