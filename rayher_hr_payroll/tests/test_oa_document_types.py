from rayher_hr_payroll.oa_document_types import (
    AMOUNT_EVENTS,
    REQUEST_DIRECT_PURCHASE,
    REQUEST_LEAVE,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
)


def test_contracts_are_stable():
    assert REQUEST_LEAVE == "请假申请"
    assert REQUEST_PROCUREMENT == "采购申请"
    assert REQUEST_DIRECT_PURCHASE == "购买申请"
    assert REQUEST_PROCUREMENT_PAYMENT == "采购付款"
    assert AMOUNT_EVENTS == ("reserve", "release", "pay", "refund", "reverse")
