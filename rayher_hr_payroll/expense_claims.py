"""报销单 / 付款单：关联申请、金额与补票规则。

报销付给员工本人，明细必须由已确认的发票生成；付款付给外部单位，可以先付款、后补票。
两种单据都必须关联申请人本人的一张已通过申请（购买申请或出差申请）。购买申请按金额
台账控制，已占用加已付款不能超过批准金额；出差申请不限金额。本模块不依赖 frappe，
便于单元测试；接口与钩子在 api/expense_claim_entry.py。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PAYMENT,
    REQUEST_REIMBURSEMENT,
    REQUEST_TRAVEL,
)

CLAIM_TYPES = (REQUEST_REIMBURSEMENT, REQUEST_PAYMENT)
APPLICATION_TYPES = (REQUEST_DIRECT_PURCHASE, REQUEST_TRAVEL)
# 只有购买申请有批准金额，出差申请只审批"该不该去"。
CAPPED_APPLICATION_TYPES = (REQUEST_DIRECT_PURCHASE,)
APPLICATION_COMPLETED = "已完成"
SOURCE_APPLICATION_PUSH = "申请下推"
SOURCE_KIND = {REQUEST_DIRECT_PURCHASE: "关联购买申请", REQUEST_TRAVEL: "关联出差申请"}

# 报销单 / 付款单的业务状态（workflow_status 仍用通用的 草稿/待审批/待办理/已付款）。
CLAIM_WAIT_PAY = "待付款"
CLAIM_DONE = "已完结"
CLAIM_PAID_WAIT_INVOICE = "已付款·待补票"
CLAIM_WAIT_VERIFY = "待核验"
# 购买申请随关联单据付款变化的业务状态。
APPLICATION_UNPAID = "待付款"
APPLICATION_PARTLY_PAID = "部分付款"
APPLICATION_PAID = "已付款"
TRAVEL_APPROVED = "已通过"

FOLLOWUP_PENDING = "待收票"
FOLLOWUP_RECEIVED = "已收票"
FOLLOWUP_VERIFIED = "已核验"
INVOICE_CONFIRMED = "已确认"

INVOICE_TOLERANCE = Decimal("0.02")
CENT = Decimal("0.01")
EVENT_SUBMIT = "提交申请"
EVENT_WITHDRAW_PAYMENT = "撤回付款"


class ClaimRuleError(ValueError):
    pass


def _get(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _text(value):
    return str(value or "").strip()


def money(value, label="金额"):
    try:
        result = Decimal(str(value if value not in (None, "") else 0)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ClaimRuleError(f"{label}格式无效。") from exc
    if not result.is_finite():
        raise ClaimRuleError(f"{label}格式无效。")
    return result


def parse_date(value, label):
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ClaimRuleError(f"{label}格式无效。") from exc


def check_application_link(claim_type, application, applicant_employee):
    """Return the payment_source_kind label, or raise when the link is not allowed."""
    if claim_type not in CLAIM_TYPES:
        raise ClaimRuleError("不支持的单据类型。")
    if not application:
        raise ClaimRuleError("报销单和付款单必须关联一张申请。")
    kind = _get(application, "request_type")
    if kind not in APPLICATION_TYPES:
        raise ClaimRuleError("只能关联购买申请或出差申请。")
    if _get(application, "workflow_status") != APPLICATION_COMPLETED:
        raise ClaimRuleError("关联的申请尚未审批通过。")
    employee = _text(_get(application, "employee"))
    if not _text(applicant_employee) or employee != _text(applicant_employee):
        raise ClaimRuleError("只能关联本人的申请。")
    return SOURCE_KIND[kind]


def check_cap(application_type, amount, available):
    """购买申请：本单金额不能超过剩余额度；出差申请不限金额。"""
    if application_type not in CAPPED_APPLICATION_TYPES:
        return
    amount = money(amount)
    available = money(available)
    if amount > available:
        raise ClaimRuleError(f"本单金额 {amount} 元超过关联购买申请的剩余额度 {available} 元。")


def invoice_gap(amount, invoice_total):
    return (money(amount) - money(invoice_total)).copy_abs()


def check_invoice_total(amount, invoice_total, note):
    """发票合计与付款金额相差超过 0.02 元时必须填写差异说明。"""
    if invoice_gap(amount, invoice_total) > INVOICE_TOLERANCE and not _text(note):
        raise ClaimRuleError(
            f"发票合计 {money(invoice_total)} 元与付款金额 {money(amount)} 元相差超过 0.02 元，请填写差异说明。"
        )


def application_payment_status(approved, paid):
    approved = money(approved)
    paid = money(paid)
    if paid <= 0:
        return APPLICATION_UNPAID
    if paid >= approved:
        return APPLICATION_PAID
    return APPLICATION_PARTLY_PAID


def paid_business_status(claim_type, followup_status):
    if claim_type == REQUEST_PAYMENT and followup_status == FOLLOWUP_PENDING:
        return CLAIM_PAID_WAIT_INVOICE
    return CLAIM_DONE


def submission_round(events):
    """第几次提交；用于金额台账的占用/释放幂等键，撤回后再提交会得到新键。"""
    return max(1, sum(1 for event in events or [] if _get(event, "action") == EVENT_SUBMIT))


def payment_round(events):
    """第几次付款；财务撤回付款后再付款会得到新键，保证重新记账。"""
    return 1 + sum(1 for event in events or [] if _get(event, "action") == EVENT_WITHDRAW_PAYMENT)


def check_claim_lines(claim_type, lines, invoices):
    """Validate submitted lines against the invoices linked to the claim; return the total.

    lines: dicts with line_key, source_invoice, amount, expense_description.
    invoices: invoice records linked to the claim (name, recognition_status,
    expense_line_key, total_amount); excluded invoices must already be filtered out.
    """
    if not lines:
        raise ClaimRuleError("请填写费用明细。")
    total = Decimal("0.00")
    for line in lines:
        amount = money(_get(line, "amount"), "明细金额")
        if amount <= 0:
            raise ClaimRuleError("每行明细的金额必须大于 0。")
        if not _text(_get(line, "expense_description")):
            raise ClaimRuleError("每行明细都必须填写费用说明。")
        total += amount
    by_name = {_text(_get(record, "name")): record for record in invoices or []}
    for record in by_name.values():
        if _get(record, "recognition_status") != INVOICE_CONFIRMED:
            raise ClaimRuleError(f"发票 {_get(record, 'name')} 不是已确认状态，请刷新后重试。")
    if claim_type == REQUEST_REIMBURSEMENT:
        used = set()
        for line in lines:
            invoice = _text(_get(line, "source_invoice"))
            if not invoice:
                raise ClaimRuleError("报销单的每行明细都必须来自发票。")
            record = by_name.get(invoice)
            if record is None or _text(_get(record, "expense_line_key")) != _text(_get(line, "line_key")):
                raise ClaimRuleError(f"发票 {invoice} 与报销明细的关联已变化，请刷新后重试。")
            if money(_get(record, "total_amount"), "发票金额") != money(_get(line, "amount")):
                raise ClaimRuleError(f"发票 {invoice} 的金额与报销明细不一致，请刷新后重试。")
            used.add(invoice)
        extra = sorted(set(by_name) - used)
        if extra:
            raise ClaimRuleError(f"报销单关联了明细以外的发票（{'、'.join(extra)}），请刷新后重试。")
    else:
        if any(_text(_get(line, "source_invoice")) for line in lines):
            raise ClaimRuleError("付款单的明细请手工填写，发票在单据上单独关联。")
    return total.quantize(CENT)


def payment_invoice_state(amount, invoice_total, invoice_count, *, expected_invoice_date,
                          no_invoice_reason, difference_note, today):
    """付款单提交时的补票状态：有票则核对金额，无票则必须填预计取票日期和原因。"""
    if invoice_count:
        check_invoice_total(amount, invoice_total, difference_note)
        return FOLLOWUP_RECEIVED
    if not _text(no_invoice_reason):
        raise ClaimRuleError("暂未取得发票时必须填写原因。")
    expected = parse_date(expected_invoice_date, "预计取票日期")
    if not expected:
        raise ClaimRuleError("暂未取得发票时必须填写预计取票日期。")
    if expected < today:
        raise ClaimRuleError("预计取票日期不能早于今天。")
    return FOLLOWUP_PENDING


def check_payee(claim_type, payment_method, payee_name, bank_name, account_no):
    if payment_method != "银行转账":
        return
    if claim_type == REQUEST_REIMBURSEMENT:
        if not (_text(bank_name) and _text(account_no)):
            raise ClaimRuleError("员工档案缺少开户行或银行账号，请联系人事补充，或选择现金支付。")
        return
    if not (_text(payee_name) and _text(bank_name) and _text(account_no)):
        raise ClaimRuleError("请填写收款单位、开户行和银行账号。")
