"""Ephemeral memoization for a single read-only list invocation."""
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps

_values = ContextVar("position_list_read_values", default=None)

def active():
    return _values.get() is not None

def read_scope(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = _values.set({})
        try:
            return fn(*args, **kwargs)
        finally:
            _values.reset(token)
    return wrapped

def reuse(key, loader):
    values = _values.get()
    if values is None:
        return loader()
    if key not in values:
        values[key] = deepcopy(loader())
    return deepcopy(values[key])
