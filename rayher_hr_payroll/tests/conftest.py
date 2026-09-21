"""Isolate framework mocks and application imports between unit-test modules.

Several legacy suites install fake frappe modules while being imported. Restoring
sys.modules only in a fixture is too late: pytest imports every suite before it
runs any test. Give each module its own import graph during collection AND test
execution. Tests still run normally in one pytest process, without deselection,
subprocess pass aggregation, or suppression of failures.
"""
import sys
import gc

import pytest

_PREFIXES = ("frappe", "erpnext", "hrms", "rayher_hr_payroll")


def _scoped(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _PREFIXES)


def _snapshot():
    return {name: module for name, module in list(sys.modules.items()) if _scoped(name)}


def _install(modules):
    for name in list(sys.modules):
        if _scoped(name):
            del sys.modules[name]
    sys.modules.update(modules)


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    if not isinstance(collector, pytest.Module):
        yield
        return
    previous = _snapshot()
    thresholds = gc.get_threshold()
    _install({})
    try:
        yield
        collector._isolated_imports = _snapshot()
    finally:
        _install(previous)
        gc.set_threshold(*thresholds)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    module = item.getparent(pytest.Module)
    graph = getattr(module, "_isolated_imports", None)
    if graph is None:
        yield
        return
    previous = _snapshot()
    thresholds = gc.get_threshold()
    _install(graph)
    try:
        yield
        module._isolated_imports = _snapshot()
    finally:
        _install(previous)
        gc.set_threshold(*thresholds)
