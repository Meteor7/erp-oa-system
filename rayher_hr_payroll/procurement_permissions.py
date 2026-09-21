"""Read access for PO fulfillment evidence follows PO viewer access."""
import frappe
from rayher_hr_payroll.position_access import position_users


def _can_read_fulfillment(user=None):
    user = user or frappe.session.user
    if user == "Guest":
        return False
    roles = set(frappe.get_roles(user))
    allowed = user == "Administrator" or bool(roles & {
        "System Manager", "Accounts User", "Finance User", "Purchase User",
        "Purchase Manager", "Rayher Business Executive",
    }) or user in position_users("pmc", "procurement_manager", "vice_manager", "production_asset_owner")
    return bool(allowed)


def fulfillment_query(user=None):
    return "" if _can_read_fulfillment(user) else "1=0"


def fulfillment_has_permission(doc, ptype=None, user=None):
    return ptype in {None, "read", "select", "report", "export", "print", "email"} and _can_read_fulfillment(user) and bool(getattr(doc, "purchase_order", None))
