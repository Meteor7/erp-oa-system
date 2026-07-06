import frappe


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/rayher"
        raise frappe.Redirect
    context.no_cache = 1
    context.boot = {
        "csrf_token": frappe.sessions.get_csrf_token(),
        "sitename": frappe.local.site,
        "site_name": frappe.local.site,
        "user": frappe.session.user,
        "full_name": frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user,
        "roles": frappe.get_roles(),
    }
    return context
