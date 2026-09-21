"""Only the reviewed social-import operations may change imported evidence."""
from contextvars import ContextVar
from functools import wraps
import frappe

_authorized = ContextVar("rayher_social_import_action", default=False)


def social_import_action(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _authorized.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _authorized.reset(token)
    return wrapped


def require_social_import_action(doc=None, method=None):
    if not _authorized.get():
        frappe.throw("社保导入记录必须通过上传、核对和生效操作维护，不能直接修改导入金额或状态。", frappe.PermissionError)
