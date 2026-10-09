import importlib
import sys
import types
from datetime import date
from decimal import Decimal

import pytest

from rayher_hr_payroll import approval_amount_ledger as ledger
from rayher_hr_payroll import expense_claims as rules
from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PAYMENT,
    REQUEST_PROCUREMENT,
    REQUEST_REIMBURSEMENT,
    REQUEST_TRAVEL,
)
from rayher_hr_payroll.tests.test_approval_amount_ledger import MemoryStore


def application(**overrides):
    values = {"name": "OA-1", "request_type": REQUEST_DIRECT_PURCHASE, "workflow_status": "已完成", "employee": "EMP-A"}
    values.update(overrides)
    return values


# ---------------------------------------------------------------- asset type carried down from the application


def test_claim_asset_category_follows_the_fixed_asset_purchase():
    fixed = {"asset_nature": "固定资产", "asset_category": "其他"}
    assert rules.claim_asset_category(application(**fixed, fixed_asset_category="办公家具、工具及器具")) == "非电子类固定资产（人事/行政）"
    assert rules.claim_asset_category(application(**fixed, fixed_asset_category="电子设备、研发专用设备、仪器仪表")) == "电子类固定资产（IT）"
    assert rules.claim_asset_category(application(**fixed, fixed_asset_category="生产设备、生产工具及器具")) == "生产设备、生产工具及器具"
    # 申请上已经有具体资产类型就直接用
    assert rules.claim_asset_category(application(asset_nature="固定资产", asset_category="电子类固定资产（IT）", fixed_asset_category="")) == "电子类固定资产（IT）"
    # 非固定资产、类别缺失或对不上：不带，由用户自己选
    assert rules.claim_asset_category(application(asset_nature="非固定资产", fixed_asset_category="办公家具、工具及器具")) == ""
    assert rules.claim_asset_category(application(**fixed, fixed_asset_category="")) == ""
    assert rules.claim_asset_category(application(**fixed, fixed_asset_category="别的类别")) == ""
    assert rules.claim_asset_category(None) == ""


# ---------------------------------------------------------------- linking


@pytest.mark.parametrize("claim_type", rules.CLAIM_TYPES)
def test_claim_links_own_approved_purchase_or_travel(claim_type):
    assert rules.check_application_link(claim_type, application(), "EMP-A") == "关联购买申请"
    assert rules.check_application_link(claim_type, application(request_type=REQUEST_TRAVEL), "EMP-A") == "关联出差申请"


@pytest.mark.parametrize("source, employee, message", [
    (None, "EMP-A", "必须关联一张申请"),
    (application(request_type=REQUEST_PROCUREMENT), "EMP-A", "只能关联购买申请或出差申请"),
    (application(request_type=REQUEST_PAYMENT), "EMP-A", "只能关联购买申请或出差申请"),
    (application(workflow_status="待审批"), "EMP-A", "尚未审批通过"),
    (application(workflow_status="草稿"), "EMP-A", "尚未审批通过"),
    (application(), "EMP-B", "只能关联本人的申请"),
    (application(), "", "只能关联本人的申请"),
])
def test_claim_link_is_rejected(source, employee, message):
    with pytest.raises(rules.ClaimRuleError, match=message):
        rules.check_application_link(REQUEST_REIMBURSEMENT, source, employee)


def test_purchase_amount_is_capped_but_travel_is_not():
    rules.check_cap(REQUEST_DIRECT_PURCHASE, "100.00", "100")
    with pytest.raises(rules.ClaimRuleError, match="超过关联购买申请的剩余额度"):
        rules.check_cap(REQUEST_DIRECT_PURCHASE, "100.01", "100")
    rules.check_cap(REQUEST_TRAVEL, "99999", "0")


# ---------------------------------------------------------------- invoices and lines


def test_invoice_gap_within_two_cents_needs_no_note():
    rules.check_invoice_total("100.00", "99.98", "")
    rules.check_invoice_total("100.00", "100.02", None)
    with pytest.raises(rules.ClaimRuleError, match="相差超过 0.02 元"):
        rules.check_invoice_total("100.00", "99.97", " ")
    rules.check_invoice_total("100.00", "80", "另一张发票下月开具")


def line(key="L1", invoice="INV-1", amount="120", description="打印纸"):
    return {"line_key": key, "source_invoice": invoice, "amount": amount, "expense_description": description}


def invoice(name="INV-1", key="L1", total="120", status="已确认"):
    return {"name": name, "expense_line_key": key, "total_amount": total, "recognition_status": status}


def test_reimbursement_lines_must_match_their_invoices():
    assert rules.check_claim_lines(REQUEST_REIMBURSEMENT, [line(), line("L2", "INV-2", "30.5")],
                                   [invoice(), invoice("INV-2", "L2", "30.5")]) == Decimal("150.50")


@pytest.mark.parametrize("lines, invoices, message", [
    ([], [], "请填写费用明细"),
    ([line(invoice="")], [], "每行明细都必须来自发票"),
    ([line()], [], "关联已变化"),
    ([line()], [invoice(key="L9")], "关联已变化"),
    ([line()], [invoice(total="119")], "金额与报销明细不一致"),
    ([line()], [invoice(), invoice("INV-2", "")], "明细以外的发票"),
    ([line()], [invoice(status="待确认")], "不是已确认状态"),
    ([line(amount="0")], [invoice()], "金额必须大于 0"),
    ([line(description="")], [invoice()], "必须填写费用说明"),
])
def test_invalid_reimbursement_is_rejected(lines, invoices, message):
    with pytest.raises(rules.ClaimRuleError, match=message):
        rules.check_claim_lines(REQUEST_REIMBURSEMENT, lines, invoices)


def test_payment_lines_are_manual_and_invoices_are_document_level():
    assert rules.check_claim_lines(REQUEST_PAYMENT, [line(invoice="")], [invoice(key="")]) == Decimal("120.00")
    with pytest.raises(rules.ClaimRuleError, match="手工填写"):
        rules.check_claim_lines(REQUEST_PAYMENT, [line()], [invoice()])


def test_payment_without_invoice_needs_reason_and_future_date():
    today = date(2026, 9, 22)
    kwargs = dict(expected_invoice_date="2026-10-10", no_invoice_reason="供应商月底开票", difference_note="", today=today)
    assert rules.payment_invoice_state("500", "0", 0, **kwargs) == rules.FOLLOWUP_PENDING
    assert rules.payment_invoice_state("500", "500", 1, **kwargs) == rules.FOLLOWUP_RECEIVED
    with pytest.raises(rules.ClaimRuleError, match="必须填写原因"):
        rules.payment_invoice_state("500", "0", 0, **dict(kwargs, no_invoice_reason=""))
    with pytest.raises(rules.ClaimRuleError, match="必须填写预计取票日期"):
        rules.payment_invoice_state("500", "0", 0, **dict(kwargs, expected_invoice_date=None))
    with pytest.raises(rules.ClaimRuleError, match="不能早于今天"):
        rules.payment_invoice_state("500", "0", 0, **dict(kwargs, expected_invoice_date="2026-09-21"))
    with pytest.raises(rules.ClaimRuleError, match="相差超过 0.02 元"):
        rules.payment_invoice_state("500", "400", 1, **kwargs)


def test_payee_rules():
    rules.check_payee(REQUEST_REIMBURSEMENT, "银行转账", "王测试", "招商银行", "6225")
    rules.check_payee(REQUEST_REIMBURSEMENT, "现金支付", "王测试", "", "")
    with pytest.raises(rules.ClaimRuleError, match="员工档案缺少"):
        rules.check_payee(REQUEST_REIMBURSEMENT, "银行转账", "王测试", "", "")
    with pytest.raises(rules.ClaimRuleError, match="收款单位、开户行和银行账号"):
        rules.check_payee(REQUEST_PAYMENT, "银行转账", "", "招商银行", "6225")


# ---------------------------------------------------------------- statuses and idempotency rounds


def test_purchase_status_follows_paid_amount():
    assert rules.application_payment_status("100", "0") == "待付款"
    assert rules.application_payment_status("100", "40") == "部分付款"
    assert rules.application_payment_status("100", "100") == "已付款"


def test_paid_status_depends_on_invoice_followup():
    assert rules.paid_business_status(REQUEST_REIMBURSEMENT, rules.FOLLOWUP_RECEIVED) == "已完结"
    assert rules.paid_business_status(REQUEST_PAYMENT, rules.FOLLOWUP_RECEIVED) == "已完结"
    assert rules.paid_business_status(REQUEST_PAYMENT, rules.FOLLOWUP_PENDING) == "已付款·待补票"


def test_rounds_change_after_resubmit_and_payment_withdrawal():
    events = [{"action": "提交申请"}]
    assert rules.submission_round([]) == 1
    assert rules.submission_round(events) == 1
    assert rules.payment_round(events) == 1
    events += [{"action": "确认付款"}, {"action": "撤回付款"}, {"action": "撤回申请"}, {"action": "提交申请"}]
    assert rules.submission_round(events) == 2
    assert rules.payment_round(events) == 2


# ---------------------------------------------------------------- ledger


@pytest.mark.parametrize("claim_type", rules.CLAIM_TYPES)
def test_claims_reserve_and_pay_against_a_purchase(claim_type):
    store = MemoryStore()
    source = store.source(approved_amount=100, request_type=REQUEST_DIRECT_PURCHASE)
    first = store.payment(amount=60, request_type=claim_type)
    second = store.payment(amount=50, request_type=claim_type)
    ledger.reserve(source, first, "claim-submit:PAY-1:1", store=store)
    with pytest.raises(ledger.ApprovalAmountError, match="超过来源申请可用余额"):
        ledger.reserve(source, second, "claim-submit:PAY-2:1", store=store)
    ledger.mark_paid(source, first, "claim-pay:PAY-1:1", store=store)
    assert ledger.source_balance(source, store=store)["paid_amount"] == Decimal("60.00")


def test_withdrawn_payment_is_booked_again_with_a_new_round():
    store = MemoryStore()
    source = store.source(approved_amount=100, request_type=REQUEST_DIRECT_PURCHASE)
    claim = store.payment(amount=60, request_type=REQUEST_PAYMENT)
    ledger.reserve(source, claim, "claim-submit:PAY-1:1", store=store)
    ledger.mark_paid(source, claim, "claim-pay:PAY-1:1", store=store)
    ledger.reverse(source, claim, Decimal("60"), "claim-reverse:PAY-1:1", store=store)
    ledger.reserve(source, claim, "claim-rereserve:PAY-1:1", store=store)
    ledger.mark_paid(source, claim, "claim-pay:PAY-1:2", store=store)
    assert ledger.source_balance(source, store=store) == {
        "approved_amount": Decimal("100.00"),
        "reserved_amount": Decimal("0.00"),
        "paid_amount": Decimal("60.00"),
        "available_amount": Decimal("40.00"),
    }


def test_ledger_still_rejects_mismatched_types():
    store = MemoryStore()
    purchase = store.source(approved_amount=100, request_type=REQUEST_DIRECT_PURCHASE)
    procurement_payment = store.payment(amount=10, request_type=ledger.REQUEST_PROCUREMENT_PAYMENT)
    with pytest.raises(ledger.ApprovalAmountError, match="付款类型与来源申请不匹配"):
        ledger.reserve(purchase, procurement_payment, "k1", store=store)
    procurement = store.source(approved_amount=100, request_type=REQUEST_PROCUREMENT)
    claim = store.payment(amount=10, request_type=REQUEST_REIMBURSEMENT)
    with pytest.raises(ledger.ApprovalAmountError, match="付款类型与来源申请不匹配"):
        ledger.reserve(procurement, claim, "k2", store=store)


# ---------------------------------------------------------------- access


@pytest.fixture
def access(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.session = types.SimpleNamespace(user="cashier@example.com")
    frappe.db = types.SimpleNamespace(escape=lambda value: "'" + str(value).replace("'", "''") + "'", get_value=lambda *a, **k: None)
    frappe.get_roles = lambda user=None: ["Employee", "Accounts User"]
    frappe.get_all = lambda *args, **kwargs: [{"name": "EMP-C", "employee_name": "Cashier"}]
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.oa_access", None)
    module = importlib.import_module("rayher_hr_payroll.oa_access")
    monkeypatch.setattr(module, "visible_request_types", lambda values, user=None: list(values))
    return module


@pytest.mark.parametrize("claim_type", rules.CLAIM_TYPES)
def test_finance_reads_submitted_claims_but_not_drafts(access, claim_type):
    doc = {"request_type": claim_type, "owner": "wang@example.com", "employee": "EMP-W", "workflow_status": "草稿", "steps": []}
    assert access.oa_request_has_permission(doc, "read", "cashier@example.com") is False
    assert access.oa_request_has_permission(dict(doc, workflow_status="待审批"), "read", "cashier@example.com") is None
    query = access.oa_request_query("cashier@example.com")
    assert "workflow_status != '草稿'" in query


def test_finance_reads_legacy_payment_requests_only_once_submitted(access):
    # 修复（2026-09-24）：费用付款申请草稿（含收款账户）也不再给财务看，和报销单、付款单一致。
    doc = {"request_type": "费用付款申请", "owner": "wang@example.com", "employee": "EMP-W", "workflow_status": "草稿", "steps": []}
    assert access.oa_request_has_permission(doc, "read", "cashier@example.com") is False
    assert access.oa_request_has_permission({**doc, "workflow_status": "待审批"}, "read", "cashier@example.com") is None
