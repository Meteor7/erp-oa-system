"""Idempotent migration from legacy Rayher login domains to QIHENG DEMO."""

from __future__ import annotations

import json

import frappe

OLD_LOCAL_DOMAIN = "legacy.example.invalid"
TARGET_LOCAL_DOMAIN = "staff.example.invalid"
LEGACY_MANAGEMENT_USER = "admin@legacy-business.example.invalid"
TARGET_MANAGEMENT_USER = "admin@staff.example.invalid"
SAVEPOINT = "planck_account_domain_migration"
# 审批流程里以文本（JSON）保存的账号。rename_doc 只改 Link 字段，这些要自己改。
# 修复（2026-09-29，审查 X3-3）：补上 action_by 和抄送人 copied_to。
OA_TEXT_FIELDS = (
    ("OA Approval Step", "approvers"),
    ("OA Approval Step", "approved_by"),
    ("OA Approval Step", "action_by"),
    ("OA Approval Request", "paid_by"),
    ("OA Approval Request", "copied_to"),
)


def build_domain_mappings(user_ids):
    mappings = []
    for raw in sorted({str(value or "").strip().lower() for value in user_ids or []}):
        if raw == LEGACY_MANAGEMENT_USER:
            mappings.append(
                {
                    "old_user": raw,
                    "new_user": TARGET_MANAGEMENT_USER,
                    "management": True,
                }
            )
        elif raw.endswith("@" + OLD_LOCAL_DOMAIN):
            local_part = raw[: -len(OLD_LOCAL_DOMAIN) - 1]
            if local_part:
                mappings.append(
                    {
                        "old_user": raw,
                        "new_user": f"{local_part}@{TARGET_LOCAL_DOMAIN}",
                        "management": False,
                    }
                )
    return mappings


def _replace_json_value(value, mapping):
    if isinstance(value, str):
        return mapping.get(value.lower(), value)
    if isinstance(value, list):
        return [_replace_json_value(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: _replace_json_value(item, mapping) for key, item in value.items()}
    return value


def replace_exact_user_ids(value, mapping):
    text = str(value or "")
    normalized = {str(key).lower(): target for key, target in (mapping or {}).items()}
    if text.lower() in normalized:
        return normalized[text.lower()]
    try:
        decoded = json.loads(text)
    except (TypeError, ValueError):
        return text
    replaced = _replace_json_value(decoded, normalized)
    if replaced == decoded:
        return text
    return json.dumps(replaced, ensure_ascii=False, separators=(",", ":"))


def _old_reference_counts(mappings):
    counts = {}
    for row in mappings:
        old_user = row["old_user"]
        total = 0
        for doctype, fieldname in OA_TEXT_FIELDS:
            total += frappe.db.count(doctype, {fieldname: ["like", f"%{old_user}%"]})
        counts[old_user] = total
    return counts


def plan_account_domain_migration():
    users = frappe.get_all("User", pluck="name")
    mappings = build_domain_mappings(users)
    collisions = [
        row["new_user"]
        for row in mappings
        if frappe.db.exists("User", row["new_user"])
    ]
    employee_links = {
        row["old_user"]: frappe.get_all(
            "Employee", filters={"user_id": row["old_user"]}, pluck="name"
        )
        for row in mappings
    }
    return {
        "count": len(mappings),
        "mappings": mappings,
        "collisions": collisions,
        "employee_links": employee_links,
        "old_reference_counts": _old_reference_counts(mappings),
    }


def rewrite_user_references(mapping):
    """把审批步骤、抄送人、付款人里的旧账号改成新账号（任何改账号的脚本都要调用）。

    只改完全相同的账号值（JSON 里逐项比较），不做子串替换。返回改动的行数。
    """
    return _repair_oa_text_references(mapping)


def stale_user_reference_counts(old_users):
    """改完之后复查：旧账号还出现在这些字段里的行数（按 LIKE 粗查，应为 0）。"""
    return _old_reference_counts([{"old_user": user} for user in old_users])


def _repair_oa_text_references(mapping):
    changed = 0
    for doctype, fieldname in OA_TEXT_FIELDS:
        rows = frappe.get_all(doctype, fields=["name", fieldname])
        for row in rows:
            old_value = row.get(fieldname) if isinstance(row, dict) else getattr(row, fieldname, None)
            new_value = replace_exact_user_ids(old_value, mapping)
            if new_value != str(old_value or ""):
                frappe.db.set_value(doctype, row["name"] if isinstance(row, dict) else row.name, fieldname, new_value, update_modified=False)
                changed += 1
    return changed


def migrate_account_domains(dry_run=True, management_password=None):
    plan = plan_account_domain_migration()
    result = {**plan, "dry_run": bool(dry_run)}
    if dry_run:
        return result
    if plan["collisions"]:
        frappe.throw("Account domain migration target collision: " + ", ".join(plan["collisions"]))
    if not management_password:
        frappe.throw("A new management password is required for account domain migration.")

    mapping = {row["old_user"]: row["new_user"] for row in plan["mappings"]}
    frappe.db.savepoint(SAVEPOINT)
    try:
        for row in plan["mappings"]:
            frappe.rename_doc(
                "User",
                row["old_user"],
                row["new_user"],
                force=True,
                show_alert=False,
            )
            frappe.db.set_value(
                "User", row["new_user"], "email", row["new_user"], update_modified=False
            )

        from frappe.utils.password import update_password

        update_password(TARGET_MANAGEMENT_USER, management_password)
        repaired = _repair_oa_text_references(mapping)

        stale_users = [row["old_user"] for row in plan["mappings"] if frappe.db.exists("User", row["old_user"])]
        missing_targets = [row["new_user"] for row in plan["mappings"] if not frappe.db.exists("User", row["new_user"])]
        stale_references = _old_reference_counts(plan["mappings"])
        if stale_users or missing_targets or any(stale_references.values()):
            frappe.throw(
                "Account domain migration postcondition failed: "
                f"stale_users={stale_users}; missing_targets={missing_targets}; "
                f"stale_references={stale_references}"
            )
        frappe.db.commit()
    except Exception:
        frappe.db.rollback(save_point=SAVEPOINT)
        raise

    return {
        "dry_run": False,
        "count": len(plan["mappings"]),
        "mappings": plan["mappings"],
        "repaired_reference_rows": repaired,
        "stale_reference_counts": stale_references,
    }