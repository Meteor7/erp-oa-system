"""Regression tests for the 2026-09-23 review fixes that need a stubbed frappe."""
import importlib
from datetime import date

import pytest


def test_ledger_events_are_read_with_a_lock_once_the_source_is_locked(monkeypatch):
    ledger = importlib.import_module("rayher_hr_payroll.approval_amount_ledger")
    calls = []

    class DB:
        def sql(self, query, values=None, as_dict=False):
            text = " ".join(query.split())
            calls.append(text)
            if "FROM `tabOA Approval Request`" in text:
                return [{"name": values[0], "request_type": "购买申请", "workflow_status": "已完成", "approved_amount": 1000}]
            return []

        def get_value(self, doctype, filters, fieldname, for_update=False):
            calls.append(("get_value", for_update))
            return None

    monkeypatch.setattr(ledger.frappe, "db", DB(), raising=False)
    monkeypatch.setattr(ledger.frappe, "get_all", lambda *args, **kwargs: calls.append("get_all") or [], raising=False)
    store = ledger.FrappeLedgerStore()
    store.events("OA-1")
    store.event_by_key("k")
    assert calls == ["get_all", ("get_value", False)]
    calls.clear()
    store.lock_source("OA-1")
    store.events("OA-1")
    store.event_by_key("k")
    assert calls[0].endswith("FOR UPDATE")
    assert calls[1].startswith("SELECT source_request") and calls[1].endswith("FOR UPDATE")
    assert calls[2] == ("get_value", True)
    # 别的来源申请没有锁，照常普通读取
    calls.clear()
    store.events("OA-2")
    assert calls == ["get_all"]


@pytest.mark.parametrize("function, field", [("_expense_rows", "paid_on"), ("_po_rows", "creation")])
def test_cost_overview_month_ends_on_its_last_day(monkeypatch, function, field):
    overview = importlib.import_module("rayher_hr_payroll.api.overview_entry")
    seen = []
    monkeypatch.setattr(overview.frappe, "get_all", lambda doctype, **kwargs: seen.append(kwargs.get("filters")) or [], raising=False)
    getattr(overview, function)([(2026, 9)])
    assert seen[0][field] == ["between", [date(2026, 9, 1), date(2026, 9, 30)]]
