import frappe

# Roles allowed to use the R&D cost SPA management endpoints.
RD_MANAGE_ROLES = ("System Manager", "Accounts User", "HR User", "HR Manager")
# Finance-only endpoints (GL import / allocation) — these DocTypes grant write/cancel
# only to Accounts User + System Manager.
RD_FINANCE_ROLES = ("System Manager", "Accounts User")
# Tighter set for endpoints exposing PII / salary.
RD_HR_ROLES = ("System Manager", "HR User", "HR Manager", "Accounts User")


def require_rd_access(roles=RD_MANAGE_ROLES):
    """Block any session whose user lacks a relevant management role.
    Prevents arbitrary logged-in users from reaching the privileged SPA APIs."""
    frappe.only_for(list(roles))


def parse_period(period):
    """Parse a strict 'YYYY-MM' / 'YYYYMM' period into (year, month); raise on malformed."""
    import re as _re
    text = str(period or "").strip()
    m = _re.fullmatch(r"(\d{4})-?(\d{2})", text)
    if not m:
        frappe.throw(frappe._("期间格式应为 YYYY-MM"))
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        frappe.throw(frappe._("月份必须在 01-12 之间"))
    return year, month


def lock_period(period):
    digits = "".join(c for c in str(period or "") if c.isdigit())
    return digits[:6]


def ensure_not_locked(period, flag, label):
    p = lock_period(period)
    if p and frappe.db.exists("RD Period Lock", {"period": p, "docstatus": 1, flag: 1}):
        frappe.throw(frappe._("会计期间 {0} 已{1}锁定，操作被阻止。").format(p, label))
