"""Resolve the one renamed account embedded in legacy approval configuration.

Lookup is per request/site, never at module import, so a rolling identity cutover
and an isolated rehearsal site can use different account names safely.
"""
def account_user(legacy):
    if legacy != "person046@staff.example.invalid":
        return legacy
    try:
        import frappe
    except ImportError:
        return legacy
    # Pure routing tests and command-line imports do not have a connected site.
    if not getattr(frappe, "db", None):
        return legacy
    canonical = "person030@staff.example.invalid"
    bound = frappe.db.get_value("Employee", "HR-EMP-90004", "user_id")
    return canonical if bound == canonical else legacy
