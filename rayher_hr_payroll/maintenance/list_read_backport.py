"""Minimal backport: preserve each server's existing OA features."""
def resolver(source):
    marker="def resolve_role(role_key, *, store=None):"
    if "def _resolve_role_uncached" in source:
        raise ValueError("Already optimized; review before reapplying")
    if source.count(marker)!=1:
        raise ValueError("Unexpected resolver source")
    source=source.replace(marker,"def _resolve_role_uncached(role_key, *, store=None):",1)
    return source+'''

def resolve_role(role_key, *, store=None):
    from rayher_hr_payroll.list_read_scope import active, reuse
    if store is not None or not active():
        return _resolve_role_uncached(role_key, store=store)
    import frappe
    key = (frappe.local.site, frappe.session.user, _text(role_key))
    return reuse(key, lambda: _resolve_role_uncached(role_key))
'''

def api(source):
    marker='@frappe.whitelist()\ndef list_requests('
    if source.count(marker)!=1:
        raise ValueError("Unexpected list source")
    return source.replace(marker,'from rayher_hr_payroll.list_read_scope import read_scope\n\n\n@frappe.whitelist()\n@read_scope\ndef list_requests(',1)
