import frappe

DEFAULT_EMPLOYEE_ROLES = ["Employee"]


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
    user.flags.ignore_permissions = True
    user.insert(ignore_permissions=True)
    # Establish the Employee->User link BEFORE granting roles: ERPNext's
    # validate_employee_role strips the Employee role from a User that has no
    # Employee linked, so order matters (this also matches ERPNext create_user,
    # which sets user_id = user.name then assigns roles). Bind user.name (the
    # normalized id), not the raw email.
    doc.db_set("user_id", user.name)
    user.add_roles(*DEFAULT_EMPLOYEE_ROLES)
    # Scope the new login to its own Employee record. HRMS adds this User Permission
    # from Employee.on_update (create_user_permission), which db_set bypasses, so an
    # auto-provisioned account would otherwise see every employee's records. Create it
    # here so "employee sees only their own" holds.
    if not frappe.db.exists(
        "User Permission", {"user": user.name, "allow": "Employee", "for_value": doc.name}
    ):
        frappe.get_doc({
            "doctype": "User Permission", "user": user.name,
            "allow": "Employee", "for_value": doc.name,
        }).insert(ignore_permissions=True)
