import frappe

# Roles allowed to use the R&D cost SPA management endpoints.
RD_MANAGE_ROLES = ("System Manager", "Accounts User", "HR User", "HR Manager")
# Finance-only endpoints (GL import / allocation) — these DocTypes grant write/cancel
# only to Accounts User + System Manager.
RD_FINANCE_ROLES = ("System Manager", "Accounts User")
# Tighter set for endpoints exposing PII / salary.
RD_HR_ROLES = ("System Manager", "HR User", "HR Manager", "Accounts User")

# Temporary restriction for a test account. Remove the account from this set
# when the sensitive HR permissions should be restored.
HR_SENSITIVE_HIDDEN_USERS = {"person046@staff.example.invalid", "person030@staff.example.invalid"}


def is_hr_sensitive_hidden():
    session = getattr(frappe, "session", None)
    return str(getattr(session, "user", "") or "").strip().lower() in HR_SENSITIVE_HIDDEN_USERS


def require_hr_sensitive_access():
    if is_hr_sensitive_hidden():
        frappe.throw(frappe._("当前测试账号暂未开放社保和公积金信息。"))


def require_rd_access(roles=RD_MANAGE_ROLES):
    """Block any session whose user lacks a relevant management role.
    Prevents arbitrary logged-in users from reaching the privileged SPA APIs."""
    frappe.only_for(list(roles))


def lock_period_import(year, month):
    """Resolve the period's newest non-cancelled RD Expense Import and lock its row FOR
    UPDATE, so every hour-mutation path (save/delete, the global Timesheet hook) and
    recalc_allocation serialize on the SAME row. Returns the import name or None. The
    order_by is fixed here so all callers resolve+lock an identical row (no drift)."""
    name = frappe.db.get_value(
        "RD Expense Import", {"year": year, "month": month, "docstatus": ["<", 2]},
        "name", order_by="creation desc",
    )
    if name:
        frappe.db.get_value("RD Expense Import", name, "name", for_update=True)
    # KNOWN CONCURRENCY RESIDUALS (narrow; opus-rated P3, codex-rated higher). Row-locking
    # the newest import serializes hour-edit vs allocate only AFTER the period's first
    # import exists, and only for the API paths (a concurrent Desk timesheet edit, and the
    # one-submitted-import-per-period uniqueness check, are not covered — a non-indexed
    # multi-row FOR UPDATE there would lock the whole table and deadlock, so it was not
    # added). All these cases require a process violation (mutating a period while it is
    # being allocated) plus precise concurrency. Fully closing them needs ONE deterministic
    # period-level lock row that every path (hour save/delete, import submit, allocate, and
    # the Desk Timesheet hook) takes before acting — which requires a schema/migration
    # (an index or a per-period sentinel row) and a workflow decision (auto-lock-on-
    # allocation). That is a dedicated backend-concurrency change, tracked separately.
    return name


def period_has_submitted_allocation(year, month):
    """这个期间是不是已经有提交的研发分摊（当前读，修复 2026-09-29）。

    审查第一轮 #9：加锁之后的复查原来用普通读（exists / get_all）。MariaDB 的可重复读下，
    同一事务在加锁前已经读过别的表，快照就固定了；等锁期间别的请求刚提交的分摊，这里看不到，
    工时就会写进已分摊的期间。现在先锁住期间的导入单，再按主键当前读它的状态：
    分摊提交时会在同一事务里把导入单标成 Allocated，撤销时再改回去。原来的 exists 保留兜底。
    """
    name = lock_period_import(year, month)
    if name and frappe.db.get_value("RD Expense Import", name, "status", for_update=True) == "Allocated":
        return True
    return bool(frappe.db.exists("RD Cost Allocation", {"year": year, "month": month, "docstatus": 1}))


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
