"""Server-only authorization for controlled procurement mutations."""
from contextvars import ContextVar
from functools import wraps
import frappe

_authorized = ContextVar("rayher_procurement_mutation", default=False)


def procurement_action(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _authorized.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _authorized.reset(token)
    return wrapped


def require_procurement_action(doc=None, method=None):
    # Neither ignore_permissions nor client-supplied document flags grant access.
    if not _authorized.get():
        frappe.throw("采购单据必须通过对应业务操作保存，不能直接修改审批、数量或履约状态。", frappe.PermissionError)


def require_procurement_child_action(doc, method=None):
    if getattr(doc, "parenttype", None) in {"OA Procurement Request", "OA Price Approval", "OA Purchase Order"}:
        require_procurement_action(doc, method)
