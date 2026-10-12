"""催一下：申请人（或项目负责人）对等得久的采购 / 购买申请，提醒当前审批人（决定 2026-10-12）。

只发提醒，不改单据：给当前节点还没审批的人各发一条站内通知。规则：
- 只管采购申请和购买申请，且单据还在审批中（待审批 / 待办理）；
- 只有申请人本人（所有人或员工是本人）或这张申请所属项目的项目负责人可以催；审批人自己、别的人不行；
- 等了超过 3 天才能催（从最近一次签批起算，没有就从提交起算，和看板的“等待”同一个口径）；
- 同一张申请一天只催一次（谁催的都算），免得变成骚扰。
"""
from __future__ import annotations

import json
from datetime import date, datetime

import frappe

REQUEST_DOCTYPE = "OA Approval Request"
NUDGE_TYPES = ("采购申请", "购买申请")
ACTIVE_STATUSES = ("待审批", "待办理")
NUDGE_AFTER_DAYS = 3
TOKEN_PREFIX = "nudge:"


def _clean(value):
    return str(value or "").strip()


def _as_date(value):
    text = _clean(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def waited_days(doc, today):
    """从最近一次签批起算，没有就从提交（再没有就从最后修改、创建）起算。"""
    stamps = sorted(
        _clean(getattr(step, "acted_on", None) or (step.get("acted_on") if isinstance(step, dict) else ""))
        for step in (getattr(doc, "steps", None) or [])
    )
    stamps = [stamp for stamp in stamps if stamp]
    since = _as_date(stamps[-1]) if stamps else None
    since = since or _as_date(getattr(doc, "submitted_on", None)) or _as_date(getattr(doc, "modified", None)) or _as_date(getattr(doc, "creation", None))
    return max(0, (today - since).days) if since else 0


def _current_approvers(doc):
    """当前节点还没处理的审批人账号。"""
    current = int(getattr(doc, "current_step_index", 0) or 0)
    for step in getattr(doc, "steps", None) or []:
        if int(getattr(step, "step_index", 0) or 0) != current:
            continue
        try:
            approvers = json.loads(_clean(getattr(step, "approvers", "")) or "[]")
            done = set(json.loads(_clean(getattr(step, "approved_by", "")) or "[]"))
        except (TypeError, ValueError):
            return []
        return [_clean(user).lower() for user in approvers if _clean(user) and user not in done]
    return []


def nudge_problem(doc, user, employee, today):
    """能不能催；不能就返回原因（页面上按钮的显示和接口的校验用同一套规则）。"""
    if getattr(doc, "request_type", "") not in NUDGE_TYPES:
        return "只有采购申请和购买申请可以催办。"
    if getattr(doc, "workflow_status", "") not in ACTIVE_STATUSES:
        return "这张申请已经不在审批中，不需要催。"
    user = _clean(user).lower()
    is_applicant = _clean(getattr(doc, "owner", "")).lower() == user or bool(employee and _clean(getattr(doc, "employee", "")) == employee)
    is_project_owner = _clean(getattr(doc, "project_owner", "")).lower() == user
    if not (is_applicant or is_project_owner):
        return "只有申请人或项目负责人可以催办。"
    days = waited_days(doc, today)
    if days < NUDGE_AFTER_DAYS:
        return f"等待还不到 {NUDGE_AFTER_DAYS} 天，先别催。"
    if not [approver for approver in _current_approvers(doc) if approver != user]:
        return "当前节点没有可提醒的审批人（只剩你自己）。"
    return ""


def _already_today(name, today):
    return bool(frappe.get_all(
        "Notification Log",
        filters={"document_type": REQUEST_DOCTYPE, "document_name": name, "subject": ["like", f"%[{TOKEN_PREFIX}{today.isoformat()}]"]},
        limit_page_length=1,
    ))


@frappe.whitelist(methods=["POST"])
def nudge_request(name):
    name = _clean(name)
    if not name or len(name) > 140:
        frappe.throw(frappe._("申请单号无效。"))
    doc = frappe.get_doc(REQUEST_DOCTYPE, name)
    if not frappe.has_permission(REQUEST_DOCTYPE, "read", doc=doc):
        frappe.throw(frappe._("找不到这张申请，或你没有权限查看。"), frappe.PermissionError)
    user = frappe.session.user
    employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name") or ""
    today = date.today()
    problem = nudge_problem(doc, user, employee, today)
    if problem:
        frappe.throw(frappe._(problem))
    if _already_today(name, today):
        frappe.throw(frappe._("今天已经催过了，明天再催。"))
    sender = frappe.utils.get_fullname(user) if hasattr(frappe.utils, "get_fullname") else user
    token = f"[{TOKEN_PREFIX}{today.isoformat()}]"
    days = waited_days(doc, today)
    sent = []
    for approver in _current_approvers(doc):
        if approver == user.lower() or not frappe.db.exists("User", approver):
            continue
        frappe.get_doc({
            "doctype": "Notification Log", "for_user": approver, "type": "Alert",
            "document_type": REQUEST_DOCTYPE, "document_name": name,
            "subject": f"{sender} 催你审批：{doc.subject or name}（已等 {days} 天） {token}",
            "email_content": f"{sender} 提醒你：{doc.request_type} {name}「{doc.subject or ''}」已经等了 {days} 天，请尽快审批。",
            "link": f"/planck-semicon/approval/{'procurement' if doc.request_type == '采购申请' else 'direct-purchase'}?request={name}",
        }).insert(ignore_permissions=True)
        sent.append(approver)
    if not sent:
        frappe.throw(frappe._("当前节点没有可提醒的审批人。"))
    frappe.db.commit()
    return {"sent": len(sent), "waited_days": days}
