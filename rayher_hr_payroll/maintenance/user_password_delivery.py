"""Reset enabled System User passwords and create a private credential delivery."""

from __future__ import annotations

import csv
import os
import secrets
from pathlib import Path

def read_known_credentials(path):
    """Read whitespace-delimited credentials while ignoring comments and headers."""
    credentials = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        user_id, password = parts
        if "@" not in user_id and user_id != "Administrator":
            continue
        if user_id in credentials:
            raise ValueError(f"duplicate credential user: {user_id}")
        credentials[user_id] = password.strip()
    return credentials


def build_reset_plan(users, *, known_credentials=None, password_factory=None):
    known_credentials = dict(known_credentials or {})
    password_factory = password_factory or (lambda: secrets.token_urlsafe(18))
    plan = []
    for user in sorted(users or [], key=lambda item: str(item.get("name") or "").lower()):
        user_id = str(user.get("name") or "").strip()
        if not user_id:
            continue
        preserved = user_id in known_credentials
        plan.append(
            {
                "user_id": user_id,
                "full_name": str(user.get("full_name") or user_id).strip(),
                "temporary_password": (
                    known_credentials[user_id] if preserved else password_factory()
                ),
                "reset_required": not preserved,
            }
        )
    return plan


def _validate_private_output_path(output_path):
    import frappe

    output = Path(output_path).resolve()
    private_root = Path(frappe.get_site_path("private")).resolve()
    if private_root != output and private_root not in output.parents:
        raise ValueError("credential output must stay below the site private directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _write_delivery(path, plan):
    pending = path.with_suffix(path.suffix + ".pending")
    with pending.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "账号",
                "姓名",
                "临时密码",
                "本次是否重置",
            ],
        )
        writer.writeheader()
        for item in plan:
            writer.writerow(
                {
                    "账号": item["user_id"],
                    "姓名": item["full_name"],
                    "临时密码": item["temporary_password"],
                    "本次是否重置": "是" if item["reset_required"] else "否（保留已知临时密码）",
                }
            )
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(pending, 0o600)
    return pending


def deliver_enabled_system_user_passwords(
    known_credentials_path,
    output_path,
    dry_run=True,
):
    """Reset missing credentials and atomically publish a complete private CSV."""
    import frappe
    from frappe.utils.password import update_password

    users = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User"},
        fields=["name", "full_name"],
        order_by="name asc",
        limit_page_length=0,
    )
    known = read_known_credentials(known_credentials_path)
    enabled_ids = {str(user.get("name") or "") for user in users}
    unknown_preserved = sorted(set(known) - enabled_ids)
    if unknown_preserved:
        raise ValueError(
            "known credential file contains non-enabled users: "
            + ", ".join(unknown_preserved)
        )
    plan = build_reset_plan(users, known_credentials=known)
    result = {
        "dry_run": bool(dry_run),
        "account_count": len(plan),
        "preserved_count": sum(not item["reset_required"] for item in plan),
        "reset_count": sum(item["reset_required"] for item in plan),
        "output_path": str(output_path),
    }
    if dry_run:
        return result

    output = _validate_private_output_path(output_path)
    pending = _write_delivery(output, plan)
    try:
        for item in plan:
            if item["reset_required"]:
                update_password(
                    item["user_id"],
                    item["temporary_password"],
                    logout_all_sessions=True,
                )
        frappe.db.commit()
        os.replace(pending, output)
        os.chmod(output, 0o600)
    except Exception:
        frappe.db.rollback()
        if pending.exists():
            pending.unlink()
        raise
    return result
