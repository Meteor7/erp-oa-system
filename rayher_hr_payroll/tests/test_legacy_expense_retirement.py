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


def test_legacy_expense_stays_open_until_a_new_type_is_switched_on(entry):
    module, conf = entry
    assert module.legacy_expense_closed() is False
    module._require_legacy_expense_entry()
    conf["reimbursement_request_enabled"] = 1
    assert module.legacy_expense_closed() is True
    with pytest.raises(ValueError, match="已停用"):
        module._require_legacy_expense_entry()
    conf.clear()
    conf["payment_request_enabled"] = 1
    assert module.legacy_expense_closed() is True
    conf.clear()
    assert module.legacy_expense_closed() is False


def test_the_consumption_push_is_gone(entry):
    module, _conf = entry
    for removed in ("list_consumption_details", "save_consumption_detail", "add_invoice",
                    "push_consumption_to_request", "_load_consumption", "_serialize_consumption",
                    "_consumption_filters", "SOURCE_PUSH", "CD_PUSHED"):
        assert not hasattr(module, removed), removed
    assert sys.modules["rayher_hr_payroll.api.oa_entry"] is module
    assert isinstance(module.SOURCE_INVOICE_PUSH, str)
