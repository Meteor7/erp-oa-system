import importlib
import sys
import types

import pytest


@pytest.fixture
def entry(monkeypatch):
    """oa_entry with a stub frappe: only the legacy switch is exercised here."""
    module = importlib.import_module("rayher_hr_payroll.api.oa_entry")
    gate = importlib.import_module("rayher_hr_payroll.oa_feature_gate")
    conf = {}
    monkeypatch.setattr(gate.frappe, "conf", conf, raising=False)
    # Keep this unit test off frappe's translation and logging machinery: there is no site here.
    monkeypatch.setattr(module.frappe, "_", lambda text, *args, **kwargs: text, raising=False)

    def throw(message, exc=None):
        raise ValueError(str(message))

    monkeypatch.setattr(module.frappe, "throw", throw, raising=False)
    return module, conf


def test_legacy_expense_stays_open_until_both_new_types_are_switched_on(entry):
    module, conf = entry
    assert module.legacy_expense_closed() is False
    module._require_legacy_expense_entry()
    # 只开一类时旧入口还在，否则另一类付款没有地方提交
    conf["reimbursement_request_enabled"] = 1
    assert module.legacy_expense_closed() is False
    conf.clear()
    conf["payment_request_enabled"] = 1
    assert module.legacy_expense_closed() is False
    conf["reimbursement_request_enabled"] = 1
    assert module.legacy_expense_closed() is True
    with pytest.raises(ValueError, match="已停用"):
        module._require_legacy_expense_entry()
    conf.clear()
    assert module.legacy_expense_closed() is False


def _unwrapped(function):
    # frappe.whitelist wraps the endpoint with a type check that needs a site
    return importlib.import_module("inspect").unwrap(function)


def test_create_request_refuses_the_types_with_their_own_entry(entry):
    module, _conf = entry
    for request_type in ("出差申请", "报销单", "付款单"):
        with pytest.raises(ValueError, match="各自的页面"):
            _unwrapped(module.create_request)(request_type, submit=1)


def test_only_creating_a_legacy_request_is_switched_off(entry):
    """被驳回的旧草稿走 _prepare_request_doc 重建，不能被停用开关拦下。"""
    module, conf = entry
    conf["reimbursement_request_enabled"] = 1
    conf["payment_request_enabled"] = 1
    with pytest.raises(ValueError, match="已停用"):
        _unwrapped(module.create_request)("费用付款申请", submit=0)
    source = importlib.import_module("inspect").getsource(module._prepare_request_doc)
    assert "_require_legacy_expense_entry" not in source


def test_the_consumption_push_is_gone(entry):
    module, _conf = entry
    for removed in ("list_consumption_details", "save_consumption_detail", "add_invoice",
                    "push_consumption_to_request", "_load_consumption", "_serialize_consumption",
                    "_consumption_filters", "SOURCE_PUSH", "CD_PUSHED"):
        assert not hasattr(module, removed), removed
    assert sys.modules["rayher_hr_payroll.api.oa_entry"] is module
    assert isinstance(module.SOURCE_INVOICE_PUSH, str)
