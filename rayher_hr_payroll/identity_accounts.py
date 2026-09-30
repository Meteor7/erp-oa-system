"""Resolve legacy account references against the current site's employee binding."""
LEGACY_ACCOUNTS = {
    "person046@staff.example.invalid": ("演示员工21", "person030@staff.example.invalid"),
    "person046@business.example.invalid": ("演示员工21", "person030@staff.example.invalid"),
    "person007@staff.example.invalid": ("演示员工30", "person059@staff.example.invalid"),
}

def account_user(legacy):
    try:
        import frappe
    except ImportError:
        return legacy
    if not getattr(frappe, "db", None):
        return legacy
    aliases = getattr(frappe, "conf", {}).get("company_email_account_aliases", {})
    if legacy in aliases:
        return aliases[legacy]
    if legacy not in LEGACY_ACCOUNTS:
        return legacy
    person, canonical = LEGACY_ACCOUNTS[legacy]
    bound = frappe.db.get_value("Employee", {"employee_name": person}, "user_id")
    return bound or legacy
