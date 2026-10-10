"""公积金导入记录只能通过上传、核对和生效这几个操作改动（和社保导入同一套做法）。"""
from contextvars import ContextVar
from functools import wraps

import frappe

_authorized = ContextVar("rayher_housing_import_action", default=False)


def housing_import_action(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _authorized.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _authorized.reset(token)
    return wrapped


def require_housing_import_action(doc=None, method=None):
    if not _authorized.get():
        frappe.throw("公积金导入记录必须通过上传、核对和生效操作维护，不能直接修改导入金额或状态。", frappe.PermissionError)
