"""Move unresolved legacy OA approvers to stable User IDs."""

from __future__ import annotations

import json

import frappe

ACTIVE_REQUEST_STATUSES = {"\u5f85\u5ba1\u6279", "\u5f85\u529e\u7406"}
UNRESOLVED_STEP_STATUSES = {"\u5f85\u5ba1\u6279", "\u5f85\u529e\u7406", "\u5f85\u6d41\u8f6c"}

YE = "\u6f14\u793a\u5458\u5de513"
REN = "\u6f14\u793a\u5458\u5de510"
QING = "\u6f14\u793a\u5458\u5de537"
WANG = "\u6f14\u793a\u5458\u5de528"
VICE = "\u6f14\u793a\u5458\u5de521"
GENERAL = "\u6f14\u793a\u5458\u5de529"

YE_USER = "person067@staff.example.invalid"
REN_USER = "person047@staff.example.invalid"
VICE_USER = "person046@staff.example.invalid"
LEGACY_GENERAL_USER = "person058@staff.example.invalid"
GENERAL_USER = "person060@staff.example.invalid"

LEGACY_USER_MAP = {
    YE: YE_USER,
    REN: REN_USER,
    QING: VICE_USER,
    WANG: GENERAL_USER,
    GENERAL: GENERAL_USER,
    "person046@business.example.invalid": VICE_USER,
    LEGACY_GENERAL_USER: GENERAL_USER,
}


def _list(value):
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return [str(value)]
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def build_step_migration(label, approvers, status):
    if str(status or "") not in UNRESOLVED_STEP_STATUSES:
        return None
    label = str(label or "")
    approvers = _list(approvers)
    legacy_joint_label = QING + "\u3001" + WANG
    legacy_joint_approvers = set(approvers) == {QING, WANG} and len(approvers) == 2
    if legacy_joint_label in label or legacy_joint_approvers:
        next_label = label.replace(
            legacy_joint_label,
            VICE + "\u3001" + GENERAL,
        )
        next_approvers = (
            [VICE_USER, GENERAL_USER]
            if legacy_joint_approvers
            else list(
                dict.fromkeys(LEGACY_USER_MAP.get(value, value) for value in approvers)
            )
        )
        result = {"label": next_label, "approvers": next_approvers}
        return result if result != {"label": label, "approvers": approvers} else None

    next_label = label.replace(QING, VICE).replace(WANG, GENERAL)
    next_approvers = list(dict.fromkeys(LEGACY_USER_MAP.get(value, value) for value in approvers))
    result = {"label": next_label, "approvers": next_approvers}
    return result if result != {"label": label, "approvers": approvers} else None


def _resolve_user(value):
    # Never infer account identity from mutable profile or employee names.
    # The explicit historical map above is reviewed migration data.
    candidate = str(value or "").strip()
    return LEGACY_USER_MAP.get(candidate, candidate)


def execute(dry_run=False):
    request_names = frappe.get_all(
        "OA Approval Request",
        filters={"workflow_status": ["in", sorted(ACTIVE_REQUEST_STATUSES)]},
        pluck="name",
    )
    report = {
        "dry_run": bool(dry_run),
        "request_count": len(request_names),
        "changed_requests": 0,
        "changed_steps": 0,
        "unresolved": [],
    }
    for request_name in request_names:
        doc = frappe.get_doc("OA Approval Request", request_name)
        changed = False
        for step in list(getattr(doc, "steps", []) or []):
            if str(getattr(step, "status", "") or "") not in UNRESOLVED_STEP_STATUSES:
                continue
            current = _list(getattr(step, "approvers", None))
            migration = build_step_migration(step.label, current, step.status)
            next_label = migration["label"] if migration else str(step.label or "")
            next_approvers = migration["approvers"] if migration else current
            next_approvers = list(dict.fromkeys(_resolve_user(value) for value in next_approvers))
            if any(value and "@" not in value for value in next_approvers):
                report["unresolved"].append(
                    {
                        "request": request_name,
                        "step_index": int(step.step_index or 0),
                        "label": next_label,
                        "approvers": next_approvers,
                    }
                )
            if next_label == step.label and next_approvers == current:
                continue
            # 修复（2026-09-29，审查 #12）：映射表里的演示员工13、演示员工10已离职。把待办步骤改到不存在或
            # 已停用的账号，这一步就没人能审批，整张单卡住。这种情况保留原步骤，列入 unresolved。
            unusable = [
                value for value in next_approvers
                if value not in current and not frappe.db.get_value("User", value, "enabled")
            ]
            if unusable:
                report["unresolved"].append(
                    {
                        "request": request_name,
                        "step_index": int(step.step_index or 0),
                        "label": next_label,
                        "approvers": next_approvers,
                        "unusable_accounts": unusable,
                    }
                )
                continue
            changed = True
            report["changed_steps"] += 1
            if not dry_run:
                step.label = next_label
                step.approvers = json.dumps(next_approvers, ensure_ascii=False)
                if int(doc.current_step_index or 0) == int(step.step_index or 0):
                    doc.current_step_label = next_label
        if changed:
            report["changed_requests"] += 1
            if not dry_run:
                from rayher_hr_payroll.oa_mutation_guard import authorized_oa_action
                with authorized_oa_action():
                    doc.save(ignore_permissions=True)
    return report
