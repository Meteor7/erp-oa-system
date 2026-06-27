import frappe

DEFAULT_EMPLOYEE_ROLES = ["Employee"]


def _target_email(doc):
    return doc.company_email or doc.personal_email or None


def _should_disable(doc):
    return doc.status == "Left"


def sync_user_for_employee(doc, method=None):
    """Onboarding/HR creates the Employee; ensure a matching login account.
    Active + has email + no user  -> create User (Employee role only) and bind user_id.
    Left                          -> disable the linked User. New management roles are
    NEVER auto-granted here (least privilege); HR adds them by hand afterwards."""
    if _should_disable(doc):
        if doc.user_id and frappe.db.exists("User", doc.user_id):
            user = frappe.get_doc("User", doc.user_id)
            if user.enabled:
                user.enabled = 0
                user.save(ignore_permissions=True)
        return

    if doc.status != "Active" or doc.user_id:
        return
    email = _target_email(doc)
    if not email:
        return
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
    else:
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = doc.employee_name or email.split("@")[0]
        user.send_welcome_email = 0
        user.insert(ignore_permissions=True)
    user.add_roles(*DEFAULT_EMPLOYEE_ROLES)
    doc.db_set("user_id", email)
