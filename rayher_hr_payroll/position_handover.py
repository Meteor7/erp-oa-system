"""Transactional position handover. Historical business records are never reassigned."""
import json

def role_delta(existing, relinquished, required, retained=()):
    """A role shared with another responsibility must not be revoked."""
    existing, relinquished, required, retained = map(set, (existing, relinquished, required, retained))
    desired = (existing - relinquished) | required | retained
    return sorted(desired - existing), sorted(existing - desired)

def reporting_plan(rows, previous, incoming, supervisor):
    by_id = {r["name"]: dict(r) for r in rows}
    if incoming not in by_id or by_id[incoming]["status"] != "Active":
        raise ValueError("New holder must be an active employee")
    if supervisor and (supervisor not in by_id or by_id[supervisor]["status"] != "Active"):
        raise ValueError("Parent position must have an active employee")
    changes = {}
    if (by_id[incoming].get("reports_to") or None) != (supervisor or None):
        changes[incoming] = supervisor or None
    if previous and previous != incoming:
        for r in rows:
            if r.get("reports_to") == previous and r["status"] == "Active" and r["name"] != incoming:
                changes[r["name"]] = incoming
    for employee, parent in changes.items():
        by_id[employee]["reports_to"] = parent
    for employee in by_id:
        seen = {employee}
        cursor = by_id[employee].get("reports_to")
        while cursor:
            if cursor in seen:
                raise ValueError("Handover would create a reporting cycle")
            if cursor not in by_id:
                raise ValueError("Missing supervisor")
            seen.add(cursor)
            cursor = by_id[cursor].get("reports_to")
    return changes

def profile_roles(profile):
    import frappe
    if not profile:
        return set()
    return {r.role for r in frappe.get_doc("Role Profile", profile).roles}

def independent_roles(user, excluding):
    import frappe
    required = set()
    for row in frappe.get_all("OA Approval Role Assignment",
            filters={"user": user, "enabled": 1, "name": ["!=", excluding]},
            fields=["role_profile"], limit_page_length=0):
        required |= profile_roles(row.role_profile)
    employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
    if employee:
        required.add("Employee")
        if frappe.db.exists("Employee", {"reports_to": employee, "status": "Active"}):
            required.add("Department Manager")
    if frappe.get_meta("Project").has_field("project_owner") and frappe.db.exists("Project", {"project_owner": user}):
        required.add("Project Owner")
    # Explicit, audited temporary authorizations, separate from position profiles.
    if frappe.db.exists("DocType", "Position Permission Exception"):
        for row in frappe.get_all("Position Permission Exception",
                filters={"user": user, "enabled": 1}, fields=["role"], limit_page_length=0):
            required.add(row.role)
    return required

def sync_roles(user, relinquished, required, retained):
    import frappe
    if not user:
        return
    existing = set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))
    add, remove = role_delta(existing, relinquished, required, retained | {"Employee"} & existing)
    for role in remove:
        frappe.db.delete("Has Role", {"parent": user, "parenttype": "User", "role": role})
    for role in add:
        if not frappe.db.exists("Role", role):
            raise ValueError("Unknown role: " + role)
        frappe.get_doc({"doctype": "Has Role", "parent": user, "parenttype": "User",
                        "parentfield": "roles", "role": role}).insert(ignore_permissions=True)
    frappe.clear_cache(user=user)

PROCUREMENT_REQUEST_TYPES = ("采购申请", "购买申请", "采购付款")
FINISHED_BUSINESS_STATUSES = ("验收通过", "已关闭", "已取消")
FINISHED_WORKFLOW_STATUSES = ("已付款", "已撤回", "已取消")


def transfer_purchaser_requests(old_user, new_user):
    """采购经理交接：把还没办完的采购单的采购经办人改成新任（修复 2026-09-29，审查 X3-9，决定 D6）。

    原来交接不动历史单据，新采购经理看不到旧采购单、也不能下推采购付款，通知还发给前任。
    已验收、已关闭、已取消、已付款、已撤回的单据保持原样；每张改动的单据留一条备注。
    """
    import frappe
    if not old_user or not new_user or old_user == new_user:
        return []
    names = frappe.get_all(
        "OA Approval Request",
        filters={
            "request_type": ["in", list(PROCUREMENT_REQUEST_TYPES)],
            "purchaser_user": old_user,
            "business_status": ["not in", list(FINISHED_BUSINESS_STATUSES)],
            "workflow_status": ["not in", list(FINISHED_WORKFLOW_STATUSES)],
        },
        pluck="name", limit_page_length=0,
    )
    for name in names:
        frappe.db.set_value("OA Approval Request", name, "purchaser_user", new_user, update_modified=False)
        frappe.get_doc({
            "doctype": "Comment", "comment_type": "Info",
            "reference_doctype": "OA Approval Request", "reference_name": name,
            "content": f"采购经理岗位交接：采购经办人由 {old_user} 改为 {new_user}",
        }).insert(ignore_permissions=True)
    return names


def apply_assignment(doc):
    """Called inside the assignment's save transaction; never commits."""
    import frappe
    if not doc.get("role_profile"):
        return
    old = doc.get_doc_before_save()
    previous = old.employee if old else None
    if not doc.enabled:
        if doc.employee and frappe.db.exists("Employee", {"reports_to": doc.employee, "status": "Active"}):
            frappe.throw("岗位仍有在职下属，请先完成岗位交接")
        if old:
            sync_roles(old.user, profile_roles(old.role_profile), set(), independent_roles(old.user, doc.name))
        return
    if not doc.employee:
        frappe.throw("启用岗位交接需要关联员工档案；个人资料可后续补齐")
    # Shared incumbency makes employee-level subordinates ambiguous; require explicit separation.
    if previous and previous != doc.employee and frappe.db.exists("OA Approval Role Assignment",
            {"employee": previous, "enabled": 1, "name": ["!=", doc.name]}):
        frappe.throw("原任兼任多个岗位，请先明确各岗位的下属归属再交接")
    if doc.get("designation"):
        frappe.db.set_value("Employee", doc.employee, "designation", doc.designation)
    supervisor = None
    if doc.get("parent_position"):
        parent = frappe.get_doc("OA Approval Role Assignment", doc.parent_position)
        if not parent.enabled or not parent.employee:
            frappe.throw("上级岗位必须有有效任职员工")
        supervisor = parent.employee
    elif old and previous:
        supervisor = frappe.db.get_value("Employee", previous, "reports_to")
    else:
        supervisor = frappe.db.get_value("Employee", doc.employee, "reports_to")
    rows = frappe.db.sql("SELECT name, status, reports_to FROM tabEmployee ORDER BY name FOR UPDATE", as_dict=True)
    changes = reporting_plan(rows, previous, doc.employee, supervisor)
    for employee, parent in changes.items():
        frappe.db.set_value("Employee", employee, "reports_to", parent)
    if changes:
        from frappe.utils.nestedset import rebuild_tree
        rebuild_tree("Employee", "reports_to")
    if old and old.user != doc.user:
        sync_roles(old.user, profile_roles(old.role_profile), set(), independent_roles(old.user, doc.name))
    relinquished = profile_roles(old.role_profile) if old and old.user == doc.user else set()
    sync_roles(doc.user, relinquished, profile_roles(doc.role_profile), independent_roles(doc.user, doc.name))
    if doc.get("role_key") == "procurement_manager" and old and old.user and old.user != doc.user:
        transfer_purchaser_requests(old.user, doc.user)
    # Parent-position links are stable; update child holders when their parent changes.
    if previous != doc.employee:
        for row in frappe.get_all("OA Approval Role Assignment",
                filters={"parent_position": doc.name, "enabled": 1}, fields=["name", "employee"], limit_page_length=0):
            if row.employee and row.employee != doc.employee:
                child = frappe.get_doc("OA Approval Role Assignment", row.name)
                apply_assignment(child)
    frappe.clear_cache()

def validate_parent_chain(doc):
    import frappe
    seen = {doc.name or doc.role_key}
    cursor = doc.get("parent_position")
    while cursor:
        if cursor in seen:
            frappe.throw("岗位上级不能形成循环")
        seen.add(cursor)
        cursor = frappe.db.get_value("OA Approval Role Assignment", cursor, "parent_position")

def on_profile_update(doc, method=None):
    """Changing the shared position template updates all its current holders."""
    import frappe
    if not frappe.get_meta("OA Approval Role Assignment").has_field("role_profile"):
        return
    old = doc.get_doc_before_save()
    previous = {r.role for r in old.roles} if old else set()
    required = {r.role for r in doc.roles}
    for assignment in frappe.get_all("OA Approval Role Assignment",
            filters={"role_profile": doc.name, "enabled": 1},
            fields=["name", "user"], limit_page_length=0):
        sync_roles(assignment.user, previous, required,
                   independent_roles(assignment.user, assignment.name))
