from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe

from rayher_hr_payroll.oa_approval import REQUEST_EXPENSE_PAYMENT
from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
)


CENT = Decimal("0.01")
SOURCE_TYPES = {REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE}
EXPECTED_PAYMENT_TYPE = {
    REQUEST_PROCUREMENT: REQUEST_PROCUREMENT_PAYMENT,
    REQUEST_DIRECT_PURCHASE: REQUEST_EXPENSE_PAYMENT,
}
COMPLETED_STATUS = "已完成"


class ApprovalAmountError(ValueError):
    pass


def _get(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    getter = getattr(value, "get", None)
    if callable(getter):
        result = getter(key)
        return default if result is None else result
    return getattr(value, key, default)


def _name(value):
    return str(value if isinstance(value, str) else _get(value, "name") or "").strip()


def _money(value, label="金额", *, positive=False):
    try:
        result = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ApprovalAmountError(f"{label}格式无效")
    if not result.is_finite():
        raise ApprovalAmountError(f"{label}格式无效")
    if positive and result <= 0:
        raise ApprovalAmountError(f"{label}必须大于0")
    return result


def _key(value):
    result = str(value or "").strip()
    if not result or len(result) > 140 or "\x00" in result:
        raise ApprovalAmountError("幂等键格式无效")
    return result


def _note(value):
    result = str(value or "").strip()
    if len(result) > 500 or "\x00" in result:
        raise ApprovalAmountError("金额事件备注格式无效")
    return result


class FrappeLedgerStore:
    def lock_source(self, source):
        name = _name(source)
        rows = frappe.db.sql(
            """SELECT name, request_type, workflow_status, approved_amount,
                      currency, owner, employee, purchaser_user, modified
                 FROM `tabOA Approval Request`
                WHERE name = %s
                FOR UPDATE""",
            (name,),
            as_dict=True,
        )
        if len(rows) != 1:
            raise ApprovalAmountError("来源申请不存在")
        return rows[0]

    def lock_payment(self, payment):
        name = _name(payment)
        rows = frappe.db.sql(
            """SELECT name, request_type, workflow_status, amount,
                      currency, owner, employee, modified, source_request,
                      approved_amount_snapshot
                 FROM `tabOA Approval Request`
                WHERE name = %s
                FOR UPDATE""",
            (name,),
            as_dict=True,
        )
        if len(rows) != 1:
            raise ApprovalAmountError("付款申请不存在")
        return rows[0]

    def get_request(self, request):
        if not isinstance(request, str):
            return request
        return frappe.get_doc("OA Approval Request", request)

    def events(self, source_name):
        return frappe.get_all(
            "OA Approval Amount Ledger",
            filters={"source_request": source_name},
            fields=[
                "source_request", "linked_request", "event_type",
                "reserved_delta", "paid_delta", "idempotency_key",
            ],
            order_by="creation asc, name asc",
        )

    def event_by_key(self, key):
        name = frappe.db.get_value(
            "OA Approval Amount Ledger", {"idempotency_key": key}, "name"
        )
        return frappe.get_doc("OA Approval Amount Ledger", name) if name else None

    def append(self, values):
        return frappe.get_doc({"doctype": "OA Approval Amount Ledger", **values}).insert(
            ignore_permissions=True
        )

    def can_use_source(self, source):
        user = str(frappe.session.user or "")
        roles = set(frappe.get_roles(user) or [])
        if user == "Administrator" or roles & {"System Manager", "Accounts User"}:
            return True
        if _get(source, "owner") == user or _get(source, "purchaser_user") == user:
            return True
        rows = frappe.get_all(
            "Employee",
            filters={"user_id": user, "status": "Active"},
            fields=["name"],
            limit_page_length=2,
        )
        return len(rows) == 1 and _get(source, "employee") == _get(rows[0], "name")

    def actor(self):
        return frappe.session.user

    def now(self):
        return frappe.utils.now_datetime()


def _store(store):
    return store or FrappeLedgerStore()


def _validate_source(source, store):
    source_type = _get(source, "request_type")
    if source_type not in SOURCE_TYPES:
        raise ApprovalAmountError("来源申请类型无效")
    if _get(source, "workflow_status") != COMPLETED_STATUS:
        raise ApprovalAmountError("来源申请尚未审批完成")
    if str(_get(source, "currency") or "") != "CNY":
        raise ApprovalAmountError("当前仅支持人民币来源申请")
    _money(_get(source, "approved_amount"), "批准金额", positive=True)
    if not store.can_use_source(source):
        raise ApprovalAmountError("无权使用该来源申请")


def _validate_payment(source, payment):
    expected = EXPECTED_PAYMENT_TYPE[_get(source, "request_type")]
    if _get(payment, "request_type") != expected:
        raise ApprovalAmountError("付款类型与来源申请不匹配")
    if not _name(payment):
        raise ApprovalAmountError("付款申请不存在")
    if _name(_get(payment, "source_request")) != _name(source):
        raise ApprovalAmountError("付款申请关联的来源申请不匹配")
    snapshot = _money(_get(payment, "approved_amount_snapshot"), "批准金额快照")
    approved = _money(_get(source, "approved_amount"), "批准金额")
    if snapshot != approved:
        raise ApprovalAmountError("付款申请批准金额快照与来源申请不一致")


def _event_totals(events, linked_request=None):
    reserved = Decimal("0.00")
    paid = Decimal("0.00")
    for row in events:
        if linked_request and _get(row, "linked_request") != linked_request:
            continue
        reserved += _money(_get(row, "reserved_delta") or 0)
        paid += _money(_get(row, "paid_delta") or 0)
    return reserved.quantize(CENT), paid.quantize(CENT)


def _balance(source, events):
    approved = _money(_get(source, "approved_amount"), "批准金额")
    reserved, paid = _event_totals(events)
    available = (approved - reserved - paid).quantize(CENT)
    if reserved < 0 or paid < 0 or available < 0:
        raise ApprovalAmountError("金额流水余额不合法")
    return {
        "approved_amount": approved,
        "reserved_amount": reserved,
        "paid_amount": paid,
        "available_amount": available,
    }


def source_balance(source, *, store=None):
    store = _store(store)
    current = store.get_request(source)
    return _balance(current, store.events(_name(current)))


def linked_payment_balance(payment, *, store=None):
    store = _store(store)
    current_payment = store.get_request(payment)
    payment_name = _name(current_payment)
    source_name = _name(_get(current_payment, "source_request"))
    if not payment_name or not source_name:
        raise ApprovalAmountError("付款申请未关联来源申请")
    amount = _money(_get(current_payment, "amount"), "付款金额")
    reserved, paid = _event_totals(store.events(source_name), payment_name)
    available = (amount - reserved - paid).quantize(CENT)
    if reserved < 0 or paid < 0 or available < 0:
        raise ApprovalAmountError("付款申请金额流水余额不合法")
    approved = amount if _get(current_payment, "workflow_status") in {"待办理", "已完成", "已付款"} else Decimal("0.00")
    return {
        "approved_amount": approved,
        "reserved_amount": reserved,
        "paid_amount": paid,
        "available_amount": available,
    }


def _same_event(existing, source_name, linked_name, event_type):
    return (
        _get(existing, "source_request") == source_name
        and _get(existing, "linked_request") == linked_name
        and _get(existing, "event_type") == event_type
    )


def _apply(source, payment, event_type, key, *, amount=None, store=None, note=""):
    store = _store(store)
    current_source = store.lock_source(source)
    _validate_source(current_source, store)
    current_payment = store.lock_payment(payment)
    _validate_payment(current_source, current_payment)
    source_name = _name(current_source)
    linked_name = _name(current_payment)
    key = _key(key)
    note = _note(note)

    existing = store.event_by_key(key)
    if existing:
        if not _same_event(existing, source_name, linked_name, event_type):
            raise ApprovalAmountError("幂等键已被其他金额事件使用")
        return _balance(current_source, store.events(source_name))

    events = list(store.events(source_name))
    balance = _balance(current_source, events)
    linked_reserved, linked_paid = _event_totals(events, linked_name)
    reserved_delta = Decimal("0.00")
    paid_delta = Decimal("0.00")

    if event_type == "reserve":
        reserved_delta = _money(_get(current_payment, "amount"), "付款金额", positive=True)
        if reserved_delta > balance["available_amount"]:
            raise ApprovalAmountError("付款金额超过来源申请可用余额")
    elif event_type == "release":
        release_amount = _money(amount, "释放金额", positive=True)
        if release_amount > linked_reserved:
            raise ApprovalAmountError("释放金额超过现有占用")
        reserved_delta = -release_amount
    elif event_type == "pay":
        if linked_reserved <= 0:
            raise ApprovalAmountError("付款申请没有可支付的占用金额")
        reserved_delta = -linked_reserved
        paid_delta = linked_reserved
    elif event_type in {"refund", "reverse"}:
        refund_amount = _money(amount, "退款金额", positive=True)
        if refund_amount > linked_paid:
            raise ApprovalAmountError("退款金额超过已付金额")
        paid_delta = -refund_amount
    else:
        raise ApprovalAmountError("不支持的金额事件")

    candidate = events + [{
        "source_request": source_name,
        "linked_request": linked_name,
        "event_type": event_type,
        "reserved_delta": reserved_delta,
        "paid_delta": paid_delta,
        "idempotency_key": key,
    }]
    result = _balance(current_source, candidate)
    actor = store.actor() if hasattr(store, "actor") else "test"
    event_time = store.now() if hasattr(store, "now") else None
    store.append({
        "source_request": source_name,
        "linked_request": linked_name,
        "event_type": event_type,
        "reserved_delta": reserved_delta,
        "paid_delta": paid_delta,
        "idempotency_key": key,
        "actor": actor,
        "event_time": event_time,
        "note": note,
    })
    return result


def reserve(source, payment, idempotency_key, *, store=None, note=""):
    return _apply(source, payment, "reserve", idempotency_key, store=store, note=note)


def release(source, payment, amount, idempotency_key, *, store=None, note=""):
    return _apply(source, payment, "release", idempotency_key, amount=amount, store=store, note=note)


def mark_paid(source, payment, idempotency_key, *, store=None, note=""):
    return _apply(source, payment, "pay", idempotency_key, store=store, note=note)


def refund(source, payment, amount, idempotency_key, *, store=None, note=""):
    return _apply(source, payment, "refund", idempotency_key, amount=amount, store=store, note=note)


def reverse(source, payment, amount, idempotency_key, *, store=None, note=""):
    return _apply(source, payment, "reverse", idempotency_key, amount=amount, store=store, note=note)

def release_all_reserved(source, payment, idempotency_key, *, store=None, note=""):
    store = _store(store)
    current_source = store.lock_source(source)
    _validate_source(current_source, store)
    current_payment = store.lock_payment(payment)
    _validate_payment(current_source, current_payment)
    key = _key(idempotency_key)
    existing = store.event_by_key(key)
    if existing:
        if not _same_event(existing, _name(current_source), _name(current_payment), "release"):
            raise ApprovalAmountError("幂等键已被其他金额事件使用")
        return _balance(current_source, store.events(_name(current_source)))
    events = list(store.events(_name(current_source)))
    linked_reserved, _linked_paid = _event_totals(events, _name(current_payment))
    if linked_reserved <= 0:
        return _balance(current_source, events)
    return _apply(
        current_source,
        current_payment,
        "release",
        key,
        amount=linked_reserved,
        store=store,
        note=note,
    )
