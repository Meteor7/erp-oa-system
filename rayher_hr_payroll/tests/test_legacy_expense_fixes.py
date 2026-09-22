from rayher_hr_payroll import approval_amount_ledger as ledger
from rayher_hr_payroll.tests.test_approval_amount_ledger import MemoryStore


def test_workflow_store_skips_the_session_user_source_check():
    assert issubclass(ledger.WorkflowLedgerStore, ledger.FrappeLedgerStore)
    assert ledger.WorkflowLedgerStore().can_use_source({"owner": "someone-else@example.com"}) is True


def test_withdrawn_legacy_payment_is_booked_again_on_the_next_round():
    store = MemoryStore()
    source = store.source(approved_amount=300, request_type=ledger.REQUEST_DIRECT_PURCHASE)
    payment = store.payment(amount=120, request_type=ledger.REQUEST_EXPENSE_PAYMENT)
    ledger.reserve(source, payment, "expense-submit:PAY-1:1", store=store)
    ledger.mark_paid(source, payment, "expense-pay:PAY-1", store=store)
    # finance withdraws: reverse + re-reserve, then pays again with the round-2 key
    ledger.reverse(source, payment, 120, "expense-reverse:PAY-1", store=store)
    ledger.reserve(source, payment, "expense-rereserve:PAY-1:1", store=store)
    ledger.mark_paid(source, payment, "expense-pay:PAY-1:2", store=store)
    balance = ledger.source_balance(source, store=store)
    assert (balance["paid_amount"], balance["reserved_amount"], balance["available_amount"]) == (120, 0, 180)
    # the old fixed key would have been swallowed as a duplicate and booked nothing
    ledger.reverse(source, payment, 120, "expense-reverse:PAY-1:2", store=store)
    ledger.reserve(source, payment, "expense-rereserve:PAY-1:2", store=store)
    ledger.mark_paid(source, payment, "expense-pay:PAY-1", store=store)
    assert ledger.source_balance(source, store=store)["paid_amount"] == 0
