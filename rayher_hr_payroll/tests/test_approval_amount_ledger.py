from decimal import Decimal
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import approval_amount_ledger as ledger
from rayher_hr_payroll.rayher_hr_payroll.doctype.oa_approval_amount_ledger import (
    oa_approval_amount_ledger as ledger_controller,
)


class MemoryStore:
    def __init__(self):
        self.sources = {}
        self.payments = {}
        self.rows = []
        self.locked = []
        self.payment_locks = []
        self.allowed = True

    def source(self, approved_amount=100, status="已完成", request_type=ledger.REQUEST_PROCUREMENT, currency="CNY"):
        doc = SimpleNamespace(
            name=f"SRC-{len(self.sources) + 1}",
            request_type=request_type,
            workflow_status=status,
            approved_amount=approved_amount,
            currency=currency,
            owner="alice@example.com",
            employee="EMP-A",
        )
        self.sources[doc.name] = doc
        return doc

    def payment(self, amount=60, request_type=ledger.REQUEST_PROCUREMENT_PAYMENT):
        doc = SimpleNamespace(
            name=f"PAY-{len(self.payments) + 1}",
            request_type=request_type,
            amount=amount,
        )
        self.payments[doc.name] = doc
        return doc

    def lock_source(self, source):
        name = source if isinstance(source, str) else source.name
        self.locked.append(name)
        return self.sources[name]

    def lock_payment(self, payment):
        name = payment if isinstance(payment, str) else payment.name
        self.payment_locks.append(name)
        return self.payments[name]

    def get_request(self, request):
        if not isinstance(request, str):
            return request
        return self.payments.get(request) or self.sources[request]

    def events(self, source_name):
        return [row for row in self.rows if row["source_request"] == source_name]

    def event_by_key(self, key):
        return next((row for row in self.rows if row["idempotency_key"] == key), None)

    def append(self, values):
        if self.event_by_key(values["idempotency_key"]):
            raise AssertionError("duplicate key")
        self.rows.append(dict(values))

    def can_use_source(self, source):
        return self.allowed


def test_balance_uses_approved_amount():
    store = MemoryStore()
    source = store.source(approved_amount=100)
    assert ledger.source_balance(source, store=store) == {
        "approved_amount": Decimal("100.00"),
        "reserved_amount": Decimal("0.00"),
        "paid_amount": Decimal("0.00"),
        "available_amount": Decimal("100.00"),
    }


def test_reserve_pay_refund_lifecycle():
    store = MemoryStore()
    source = store.source(approved_amount=100)
    payment = store.payment(amount=60)
    ledger.reserve(source, payment, "submit:PAY-1", store=store)
    ledger.mark_paid(source, payment, "pay:PAY-1", store=store)
    ledger.refund(source, payment, Decimal("10.00"), "refund:PAY-1:1", store=store)
    assert ledger.source_balance(source, store=store) == {
        "approved_amount": Decimal("100.00"),
        "reserved_amount": Decimal("0.00"),
        "paid_amount": Decimal("50.00"),
        "available_amount": Decimal("50.00"),
    }


def test_idempotency_key_applies_once():
    store = MemoryStore()
    source = store.source(approved_amount=100)
    payment = store.payment(amount=30)
    first = ledger.reserve(source, payment, "submit:PAY-1", store=store)
    second = ledger.reserve(source, payment, "submit:PAY-1", store=store)
    assert first == second
    assert len(store.rows) == 1
    assert ledger.source_balance(source, store=store)["reserved_amount"] == Decimal("30.00")


def test_two_payments_cannot_reserve_more_than_approved():
    store = MemoryStore()
    source = store.source(approved_amount=100)
    ledger.reserve(source, store.payment(amount=60), "submit:PAY-1", store=store)
    with pytest.raises(ledger.ApprovalAmountError, match="可用余额"):
        ledger.reserve(source, store.payment(amount=60), "submit:PAY-2", store=store)
    assert ledger.source_balance(source, store=store)["reserved_amount"] == Decimal("60.00")
    assert store.locked == [source.name, source.name]


def test_release_and_refund_cannot_make_balances_negative():
    store = MemoryStore()
    source = store.source(approved_amount=100)
    payment = store.payment(amount=30)
    ledger.reserve(source, payment, "submit:PAY-1", store=store)
    with pytest.raises(ledger.ApprovalAmountError, match="超过现有占用"):
        ledger.release(source, payment, Decimal("40.00"), "release:bad", store=store)
    ledger.mark_paid(source, payment, "pay:PAY-1", store=store)
    with pytest.raises(ledger.ApprovalAmountError, match="超过已付金额"):
        ledger.refund(source, payment, Decimal("40.00"), "refund:bad", store=store)


def test_source_and_payment_contracts_fail_closed():
    store = MemoryStore()
    payment = store.payment(amount=10)
    for source in (
        store.source(status="待审批"),
        store.source(approved_amount=0),
        store.source(request_type="请假申请"),
    ):
        with pytest.raises(ledger.ApprovalAmountError):
            ledger.reserve(source, payment, f"bad:{source.name}", store=store)
    source = store.source()
    with pytest.raises(ledger.ApprovalAmountError, match="付款类型"):
        ledger.reserve(source, store.payment(request_type="请假申请"), "bad:payment", store=store)
    store.allowed = False
    with pytest.raises(ledger.ApprovalAmountError, match="无权"):
        ledger.reserve(source, payment, "bad:access", store=store)


def test_frappe_store_locks_source_row_for_update(monkeypatch):
    calls = []

    class DB:
        def sql(self, query, values, as_dict=False):
            calls.append((query, values, as_dict))
            return [{
                "name": "SRC-1", "request_type": ledger.REQUEST_PROCUREMENT,
                "workflow_status": "已完成", "approved_amount": 100,
                "currency": "CNY", "owner": "alice@example.com", "employee": "EMP-A",
            }]

    monkeypatch.setattr(ledger.frappe, "db", DB())
    store = ledger.FrappeLedgerStore()
    result = store.lock_source("SRC-1")
    payment = store.lock_payment("PAY-1")
    assert result["name"] == "SRC-1"
    assert payment["name"] == "SRC-1"
    assert calls[0][1] == ("SRC-1",)
    assert calls[1][1] == ("PAY-1",)
    assert all("FOR UPDATE" in query for query, _values, _as_dict in calls)



def test_currency_note_and_key_reuse_fail_closed():
    store = MemoryStore()
    payment = store.payment(amount=10)
    with pytest.raises(ledger.ApprovalAmountError, match="人民币"):
        ledger.reserve(store.source(currency=""), payment, "bad:currency", store=store)
    source = store.source()
    with pytest.raises(ledger.ApprovalAmountError, match="备注"):
        ledger.reserve(source, payment, "bad:note", store=store, note="x" * 501)
    ledger.reserve(source, payment, "same-key", store=store)
    with pytest.raises(ledger.ApprovalAmountError, match="幂等键"):
        ledger.release(source, payment, Decimal("1.00"), "same-key", store=store)
    assert store.payment_locks[-1] == payment.name


def test_ledger_controller_rejects_update_and_delete(monkeypatch):
    class PermissionError(Exception):
        pass

    monkeypatch.setattr(ledger_controller.frappe, "PermissionError", PermissionError)
    monkeypatch.setattr(
        ledger_controller.frappe,
        "throw",
        lambda message, exc=None: (_ for _ in ()).throw((exc or RuntimeError)(message)),
    )
    existing = SimpleNamespace(is_new=lambda: False)
    with pytest.raises(PermissionError, match="只允许追加"):
        ledger_controller.OAApprovalAmountLedger.validate(existing)
    with pytest.raises(PermissionError, match="不允许删除"):
        ledger_controller.OAApprovalAmountLedger.on_trash(existing)
