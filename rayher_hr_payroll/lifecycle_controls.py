import frappe

DEFAULT_EMPLOYEE_ROLES = ["Employee"]
RAYHER_DEFAULT_APP = "rayher_hr_payroll"


def _target_email(doc):
    return doc.company_email or doc.personal_email or None


def sync_user_for_employee(doc, method=None):
    """Keep an Employee's login account in step with employment.

    - If the Employee already has a linked User (`user_id`), keep that account's
      `enabled` flag in sync with status (Active -> enabled, otherwise disabled).
      This covers separation AND rehire (Left -> Active re-enables).
    - If the Employee has NO linked account yet and is Active with an email,
      auto-provision a least-privilege login (role `Employee` only) and bind it.

    Security: we NEVER adopt/modify a pre-existing User found by email. Employee
    emails are not unique, so a reused address (e.g. an existing System Manager's)
    must not be silently taken over and granted roles. If a User already exists for
    the email, we leave `user_id` unset and let HR link it deliberately. All User
    writes use ignore_permissions because this runs from HR-driven Employee saves,
    not necessarily as System Manager.

    Note: the auto-created account has no password set (send_welcome_email=0 to stay
    SMTP-independent); credential delivery (welcome email / password reset / SSO) is
    an HR/ops step.
    """
    if doc.user_id and frappe.db.exists("User", doc.user_id):
        want_enabled = 1 if doc.status == "Active" else 0
        if not want_enabled and frappe.db.exists(
            "Employee", {"user_id": doc.user_id, "status": "Active", "name": ["!=", getattr(doc, "name", None) or ""]}
        ):
            # 修复（2026-09-29，审查 X3-5）：复职的人新档和旧的离职档共用同一个账号时，
            # 保存旧档不能把账号停用。
            return
        user = frappe.get_doc("User", doc.user_id)
        if user.enabled != want_enabled:
            user.enabled = want_enabled
            user.flags.ignore_permissions = True
            user.save(ignore_permissions=True)
        return

    if doc.status != "Active":
        return
    email = _target_email(doc)
    if not email:
        return
    email = email.strip().lower()  # User.name is force-lowercased; match it
    if frappe.db.exists("User", email):
        return

    user = frappe.new_doc("User")
    user.email = email
    user.first_name = doc.employee_name or email.split("@")[0]
    user.send_welcome_email = 0
    user.default_app = RAYHER_DEFAULT_APP
    user.flags.ignore_permissions = True
    user.insert(ignore_permissions=True)
    # Establish the Employee->User link BEFORE granting roles: ERPNext's
    # validate_employee_role strips the Employee role from a User that has no
    # Employee linked, so order matters (this also matches ERPNext create_user,
    # which sets user_id = user.name then assigns roles). Bind user.name (the
    # normalized id), not the raw email.
    doc.db_set("user_id", user.name)
    user.add_roles(*DEFAULT_EMPLOYEE_ROLES)
    # Scope the new login like ERPNext's native Employee.update_user_permissions
    # (Employee + Company), which db_set bypasses. Without these the auto-provisioned
    # account would see every employee's (and, on multi-company sites, every company's)
    # records instead of only its own.
    # The Employee permission is scoped applicable_for="Employee" so it ONLY narrows the
    # Employee doctype (employee sees own record), NOT request doctypes -- otherwise a
    # promoted manager/finance reviewer could not open subordinate claims. Row-level
    # request visibility is handled by request_visibility (permission_query_conditions).
    for allow, value, applicable in (
        ("Employee", doc.name, "Employee"),
        ("Company", getattr(doc, "company", None), None),
    ):
        if value and not frappe.db.exists(
            "User Permission", {"user": user.name, "allow": allow, "for_value": value}
        ):
            up = {
                "doctype": "User Permission", "user": user.name,
                "allow": allow, "for_value": value,
            }
            if applicable:
                up["applicable_for"] = applicable
                up["apply_to_all_doctypes"] = 0
            frappe.get_doc(up).insert(ignore_permissions=True)
