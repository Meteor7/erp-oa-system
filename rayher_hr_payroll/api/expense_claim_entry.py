"""报销单 / 付款单接口。

草稿保存、从申请下推、出纳填写科目、付款单补票与核验、财务撤回付款在这里。
提交、审批、驳回和撤回沿用 oa_entry 的通用接口；oa_entry 在对应位置调用本模块的
validate_submit / reserve / release / mark_paid 钩子。规则本身在 expense_claims.py。
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import date
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from rayher_hr_payroll import approval_amount_ledger
from rayher_hr_payroll import expense_claims as rules
from rayher_hr_payroll.api import oa_entry
from rayher_hr_payroll.oa_document_types import REQUEST_PAYMENT, REQUEST_REIMBURSEMENT
from rayher_hr_payroll.oa_feature_gate import require_request_type_access

invoice_service = oa_entry.invoice_service

MAX_LINES = 200
MAX_INVOICES = 200
PAYMENT_PERSONAL = "支付个人"
PAYMENT_CORPORATE = "对公支付"


class _TrustedLedgerStore(approval_amount_ledger.FrappeLedgerStore):
    """本模块在每次记账前已校验申请归属和当前操作人，台账不再按会话用户重复判断。

    否则直属主管驳回、出纳付款这类非申请人操作会被台账的"无权使用来源申请"拦下。
    """

    def can_use_source(self, source):
        return True


def _ledger(operation, *args, **kwargs):
    try:
        return operation(*args, store=_TrustedLedgerStore(), **kwargs)
    except approval_amount_ledger.ApprovalAmountError as exc:
        frappe.throw(str(exc))


def _rule(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except rules.ClaimRuleError as exc:
        frappe.throw(str(exc))


def _clean(value):
    return str(value or "").strip()


def _text(value, label, limit):
    return oa_entry._bounded_optional_text(value, label, limit) or ""


def _payload(value):
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except ValueError:
            frappe.throw("单据数据格式无效。")
    if not isinstance(value, dict):
        frappe.throw("单据数据格式无效。")
    return value


def _rows(value, label, limit):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            frappe.throw(f"{label}格式无效。")
    if not isinstance(value, list) or len(value) > limit:
        frappe.throw(f"{label}格式无效，最多 {limit} 行。")
    return value


def is_claim(doc):
    return getattr(doc, "request_type", None) in rules.CLAIM_TYPES


def _require_claim_type(request_type):
    if request_type not in rules.CLAIM_TYPES:
        frappe.throw("只支持报销单和付款单。")
    require_request_type_access(request_type)


def _events(doc):
    return oa_entry._operation_events(doc)


def _capped(doc):
    source = _clean(getattr(doc, "source_request", None))
    if not source:
        return False
    return frappe.db.get_value("OA Approval Request", source, "request_type") in rules.CAPPED_APPLICATION_TYPES


def _load_application(name):
    name = _text(name, "关联申请", 140)
    if not name:
        frappe.throw("报销单和付款单必须关联一张申请。")
    if not frappe.db.exists("OA Approval Request", name):
        frappe.throw("关联的申请不存在。")
    return frappe.get_doc("OA Approval Request", name)


def _application_balance(application):
    if application.request_type not in rules.CAPPED_APPLICATION_TYPES:
        return None
    return _ledger(approval_amount_ledger.source_balance, application)


def _link_application(doc, application, *, amount=None):
    """Check the link rules and copy the application snapshot onto the claim."""
    kind = _rule(rules.check_application_link, doc.request_type, application, doc.employee)
    balance = _application_balance(application)
    if balance is not None and amount is not None:
        _rule(rules.check_cap, application.request_type, amount, balance["available_amount"])
    doc.source_request = application.name
    doc.payment_source_kind = kind
    doc.approved_amount_snapshot = getattr(application, "approved_amount", None)
    doc.source_modified = getattr(application, "modified", None)
    return balance


def _is_applicant(doc, user=None):
    user = _clean(user or frappe.session.user)
    if user == "Administrator" or _clean(getattr(doc, "owner", None)) == user:
        return True
    employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
    return bool(employee and employee == _clean(getattr(doc, "employee", None)))


def _employee_payee(doc):
    values = frappe.db.get_value(
        "Employee", doc.employee, ["employee_name", "bank_name", "bank_ac_no"], as_dict=True
    ) or {}
    doc.payee_name = _clean(values.get("employee_name")) or doc.employee_name or ""
    doc.bank_name = _clean(values.get("bank_name"))
    doc.account_no = _clean(values.get("bank_ac_no"))
    doc.branch = ""
    doc.payment_type = PAYMENT_PERSONAL


def _project(value):
    project = _text(value, "所属项目", 140)
    if project and not frappe.db.exists("Project", project):
        frappe.throw(f"所属项目 {project} 不存在。")
    return project


def _apply_header(doc, values):
    if "source_request" in values:
        source = _clean(values.get("source_request"))
        locked = _clean(getattr(doc, "source_type", None)) == rules.SOURCE_APPLICATION_PUSH
        if locked and source != _clean(doc.source_request):
            frappe.throw("从申请下推的单据不能更换关联申请。")
        if not locked:
            if source:
                _link_application(doc, _load_application(source))
            else:
                doc.source_request = None
                doc.payment_source_kind = ""
                doc.approved_amount_snapshot = None
                doc.source_modified = None
    if "subject" in values:
        doc.subject = _text(values.get("subject"), "主题", 140) or doc.request_type
    if "reason" in values:
        doc.reason = _text(values.get("reason"), "申请说明", 1000)
    if "urgency" in values:
        urgency = _clean(values.get("urgency")) or oa_entry.URGENCY[0]
        if urgency not in oa_entry.URGENCY:
            frappe.throw("紧急程度无效。")
        doc.urgency = urgency
    if "doc_type" in values or "asset_category" in values:
        classification = oa_entry._expense_classification(
            values.get("doc_type", doc.doc_type), values.get("asset_category", doc.asset_category)
        )
        for fieldname, value in classification.items():
            setattr(doc, fieldname, value)
    if "payment_method" in values:
        method = _clean(values.get("payment_method")) or oa_entry.PAYMENT_METHODS[0]
        if method not in oa_entry.PAYMENT_METHODS:
            frappe.throw("付款方式无效。")
        doc.payment_method = method
    if doc.request_type == REQUEST_REIMBURSEMENT:
        _employee_payee(doc)
        return
    doc.payment_type = PAYMENT_CORPORATE
    for fieldname, label in (("payee_name", "收款单位"), ("bank_name", "开户行"), ("branch", "开户支行"), ("account_no", "银行账号")):
        if fieldname in values:
            setattr(doc, fieldname, _text(values.get(fieldname), label, 140))
    if "expected_invoice_date" in values:
        expected = _rule(rules.parse_date, values.get("expected_invoice_date"), "预计取票日期")
        doc.expected_invoice_date = expected.isoformat() if expected else None
    if "no_invoice_reason" in values:
        doc.no_invoice_reason = _text(values.get("no_invoice_reason"), "暂未取得发票原因", 1000)
    if "invoice_difference_note" in values:
        doc.invoice_difference_note = _text(values.get("invoice_difference_note"), "发票差异说明", 1000)


def _record_total(record):
    total = invoice_service._decimal_money(invoice_service._record_money(record, "total_amount"))
    if total is None or total <= 0:
        frappe.throw(f"发票 {record.name} 没有有效的合计金额，请先在发票中补全。")
    return total


def _relink_invoices(doc, wanted, line_keys=None, *, finance_release=False):
    """Point exactly the `wanted` invoices at `doc`; release invoices no longer wanted.

    Returns {invoice_name: record} for the wanted invoices, all locked and writable.
    finance_release: the caller is finance returning a supplement; it may release
    the applicant's invoices without owning them.
    """
    line_keys = line_keys or {}
    current = {
        _clean(invoice_service._get(row, "name"))
        for row in invoice_service._request_invoice_records(doc.name, current=True)
    }
    records = {}
    with ExitStack() as locks:
        for name in sorted(current | set(wanted)):
            locks.enter_context(invoice_service._transaction_lock("record", name))
        for name in sorted(current - set(wanted)):
            record = (
                invoice_service._current_doc(invoice_service.RECORD_DOCTYPE, name)
                if finance_release
                else invoice_service._require_record(name, write=True, current=True)
            )
            record.request = ""
            record.expense_line_key = ""
            invoice_service._append_record_event(record, "移出" + doc.request_type, record.recognition_status, record.recognition_status, doc.name)
            invoice_service._save(record)
        for name in wanted:
            record = invoice_service._require_record(name, write=True, current=True)
            if record.recognition_status != rules.INVOICE_CONFIRMED:
                frappe.throw(f"发票 {name} 还未确认，不能使用。")
            linked = _clean(record.request)
            if linked and linked != doc.name:
                frappe.throw(f"发票 {name} 已被 {linked} 使用。")
            key = line_keys.get(name, "")
            if linked != doc.name or _clean(record.expense_line_key) != key:
                record.request = doc.name
                record.expense_line_key = key
                invoice_service._append_record_event(record, "用于" + doc.request_type, record.recognition_status, record.recognition_status, doc.name)
                invoice_service._save(record)
            records[name] = record
    return records


def _invoice_list(value, label):
    names = []
    for row in _rows(value, label, MAX_INVOICES):
        name = _clean(row.get("invoice") if isinstance(row, dict) else row)
        if not name:
            frappe.throw(f"{label}格式无效。")
        if name in names:
            frappe.throw(f"发票 {name} 重复选择。")
        names.append(name)
    return names


def _set_reimbursement_lines(doc, values):
    rows = _rows(values.get("invoices"), "报销发票", MAX_INVOICES)
    wanted = _invoice_list(rows, "报销发票")
    projects = {
        _clean(row.get("invoice")): _project(row.get("claim_project"))
        for row in rows if isinstance(row, dict) and "claim_project" in row
    }
    existing = {_clean(line.source_invoice): line for line in doc.expense_lines if _clean(line.source_invoice)}
    line_keys = {name: _clean(existing[name].line_key) if name in existing else str(uuid4()) for name in wanted}
    records = _relink_invoices(doc, wanted, line_keys)
    lines = []
    for name in wanted:
        record = records[name]
        total = _record_total(record)
        previous = existing.get(name)
        description = _clean(record.expense_description)
        lines.append({
            "source_invoice": name,
            "line_key": line_keys[name],
            "invoice_category": _clean(record.invoice_category),
            "project_name": _clean(record.project_name),
            "claim_project": projects[name] if name in projects else _clean(getattr(previous, "claim_project", None)),
            "expense_account_level_1": _clean(getattr(previous, "expense_account_level_1", None)),
            "expense_account_level_2": _clean(getattr(previous, "expense_account_level_2", None)),
            "expense_item": _clean(getattr(previous, "expense_item", None)),
            "issue_date": record.issue_date,
            "invoice_number": _clean(record.invoice_number),
            "amount_before_tax": record.amount_before_tax,
            "tax_amount": record.tax_amount,
            "total_amount": total,
            "amount": total,
            "start_date": record.issue_date,
            "end_date": record.issue_date,
            "category": _clean(record.invoice_category) or doc.request_type,
            "description": description,
            "expense_description": description,
            "attachment_count": 1,
            "invoice_status": rules.INVOICE_CONFIRMED,
        })
    oa_entry._set_expense_lines(doc, lines)
    doc.amount = float(sum(rules.money(line["amount"]) for line in lines))


def _set_payment_lines(doc, values):
    if "lines" in values:
        existing = {_clean(line.line_key): line for line in doc.expense_lines}
        lines = []
        for row in _rows(values.get("lines"), "付款明细", MAX_LINES):
            if not isinstance(row, dict):
                frappe.throw("付款明细格式无效。")
            key = _clean(row.get("line_key"))
            if key and key not in existing:
                frappe.throw("付款明细不属于该单据，请刷新后重试。")
            previous = existing.get(key)
            amount = _rule(rules.money, row.get("total_amount"), "明细金额")
            if amount < 0:
                frappe.throw("明细金额不能为负数。")
            issue_date = _rule(rules.parse_date, row.get("issue_date"), "费用日期")
            description = _text(row.get("expense_description"), "费用说明", 1000)
            content = _text(row.get("project_name"), "付款内容", 1000)
            lines.append({
                "line_key": key or str(uuid4()),
                "project_name": content,
                "claim_project": _project(row.get("claim_project")),
                "expense_account_level_1": _clean(getattr(previous, "expense_account_level_1", None)),
                "expense_account_level_2": _clean(getattr(previous, "expense_account_level_2", None)),
                "expense_item": _clean(getattr(previous, "expense_item", None)),
                "issue_date": issue_date.isoformat() if issue_date else None,
                "total_amount": float(amount),
                "amount": float(amount),
                "start_date": issue_date.isoformat() if issue_date else None,
                "end_date": issue_date.isoformat() if issue_date else None,
                "category": content or doc.request_type,
                "description": description,
                "expense_description": description,
                "attachment_count": 0,
                "invoice_status": "",
            })
        oa_entry._set_expense_lines(doc, lines)
        doc.amount = float(sum(rules.money(line["amount"]) for line in lines))
    if "invoices" in values:
        _relink_invoices(doc, _invoice_list(values.get("invoices"), "付款发票"))


def _apply_lines(doc, values):
    if doc.request_type == REQUEST_REIMBURSEMENT:
        if "invoices" in values:
            _set_reimbursement_lines(doc, values)
    else:
        _set_payment_lines(doc, values)
    invoice_service._apply_request_invoice_summary(doc, save=False, current=True)


def _new_claim(request_type, application=None, *, pushed=False):
    ctx = oa_entry._route_context(request_type=request_type)
    if not ctx.get("employee"):
        frappe.throw("当前账号未关联在职员工，不能填写报销单或付款单。")
    doc = frappe.get_doc({
        "doctype": "OA Approval Request",
        "request_type": request_type,
        "workflow_status": oa_entry.STATUS_DRAFT,
        "employee": ctx.get("employee"),
        "employee_name": ctx.get("employee_name"),
        "department": ctx.get("department"),
        "supervisor": ctx.get("supervisor"),
        "company": oa_entry.COMPANIES[0],
        "subject": request_type,
        "doc_type": "非固定资产",
        "urgency": oa_entry.URGENCY[0],
        "asset_category": oa_entry.OTHER_ASSET,
        "asset_nature": "非固定资产",
        "fixed_asset_category": "",
        "amount": 0,
        "currency": "CNY",
        "business_status": "",
        "source_type": rules.SOURCE_APPLICATION_PUSH if pushed else oa_entry.SOURCE_MANUAL,
        "payment_method": oa_entry.PAYMENT_METHODS[0],
        "payment_type": PAYMENT_PERSONAL if request_type == REQUEST_REIMBURSEMENT else PAYMENT_CORPORATE,
        "invoice_count": 0,
        "invoice_status": "无发票",
        "invoice_handling_mode": oa_entry.INVOICE_MODE_AVAILABLE if request_type == REQUEST_REIMBURSEMENT else "",
        "invoice_followup_status": "",
        "operation_log": "[]",
        "current_step_index": 0,
        "current_step_label": "",
    })
    if request_type == REQUEST_REIMBURSEMENT:
        _employee_payee(doc)
    if application is not None:
        _link_application(doc, application)
        doc.subject = _clean(application.subject) or request_type
        doc.reason = _clean(getattr(application, "reason", None))
        if getattr(application, "asset_nature", None) == "固定资产" and getattr(application, "asset_category", None):
            classification = oa_entry._expense_classification("固定资产", application.asset_category)
            for fieldname, value in classification.items():
                setattr(doc, fieldname, value)
    return doc


@frappe.whitelist(methods=["POST"])
def save_claim_draft(request_type, payload, name=None):
    _require_claim_type(request_type)
    values = _payload(payload)
    draft_name = _text(name, "草稿编号", 140) if name else ""
    if draft_name:
        with invoice_service._transaction_lock("request", draft_name):
            doc = oa_entry._load_request(draft_name, current=True)
            if doc.request_type != request_type:
                frappe.throw("单据类型不一致。")
            invoice_service._request_permission(doc, "edit", current=True)
            if doc.workflow_status != oa_entry.STATUS_DRAFT:
                frappe.throw("只有草稿可以修改。")
            _apply_header(doc, values)
            _apply_lines(doc, values)
            oa_entry._save_document(doc)
            return oa_entry._summarize_doc(doc)
    doc = _new_claim(request_type)
    _apply_header(doc, values)
    oa_entry._insert_document(doc)
    with invoice_service._transaction_lock("request", doc.name):
        _apply_lines(doc, values)
        oa_entry._append_request_event(doc, "新建" + request_type, oa_entry.STATUS_DRAFT, oa_entry.STATUS_DRAFT)
        oa_entry._save_document(doc)
        return oa_entry._summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def push_from_application(source_request, request_type):
    """从已通过的申请下推一张报销单或付款单草稿；关联申请锁定不能更换。"""
    _require_claim_type(request_type)
    application = _load_application(source_request)
    doc = _new_claim(request_type, application, pushed=True)
    balance = _application_balance(application)
    if balance is not None and balance["available_amount"] <= 0:
        frappe.throw("该购买申请已没有剩余额度。")
    oa_entry._insert_document(doc)
    oa_entry._append_request_event(doc, "申请下推", oa_entry.STATUS_DRAFT, oa_entry.STATUS_DRAFT, application.name)
    oa_entry._save_document(doc)
    return oa_entry._summarize_doc(doc)


@frappe.whitelist()
def list_linkable_applications(request_type):
    """本人已通过、可以关联的申请；购买申请只列出还有剩余额度的。"""
    _require_claim_type(request_type)
    ctx = oa_entry._employee_context()
    if not ctx.get("employee"):
        return []
    rows = frappe.get_all(
        "OA Approval Request",
        filters={
            "employee": ctx["employee"],
            "request_type": ["in", list(rules.APPLICATION_TYPES)],
            "workflow_status": rules.APPLICATION_COMPLETED,
        },
        fields=["name", "request_type", "subject", "project", "business_status",
                "travel_destination", "travel_start_date", "travel_end_date", "modified"],
        order_by="modified desc",
        limit_page_length=500,
    )
    result = []
    for row in rows:
        item = {key: row.get(key) for key in ("name", "request_type", "subject", "project", "business_status",
                                              "travel_destination", "travel_start_date", "travel_end_date")}
        if row.get("request_type") in rules.CAPPED_APPLICATION_TYPES:
            try:
                balance = approval_amount_ledger.source_balance(row["name"], store=_TrustedLedgerStore())
            except approval_amount_ledger.ApprovalAmountError:
                continue
            if balance["available_amount"] <= 0:
                continue
            item.update({key: float(value) for key, value in balance.items()})
        result.append(item)
    return result


@frappe.whitelist()
def list_available_invoices(request_type=REQUEST_REIMBURSEMENT):
    """本人已确认、还没被任何单据使用的发票。"""
    _require_claim_type(request_type)
    return frappe.get_all(
        "OA Invoice Record",
        filters={"owner": frappe.session.user, "recognition_status": rules.INVOICE_CONFIRMED, "request": ["is", "not set"]},
        fields=["name", "invoice_category", "project_name", "issue_date", "invoice_number",
                "amount_before_tax", "tax_amount", "total_amount", "expense_description"],
        order_by="issue_date desc, name desc",
        limit_page_length=500,
    )


# ---------------------------------------------------------------- hooks called by oa_entry


def validate_submit(doc):
    """Called from oa_entry._submit_draft before the route is built."""
    application = _load_application(doc.source_request)
    lines = [oa_entry._serialize_expense_line(row) for row in doc.expense_lines]
    records = [
        row for row in invoice_service._request_invoice_records(doc.name, current=True)
        if invoice_service._get(row, "recognition_status") != "已排除"
    ]
    invoices = [
        {
            "name": invoice_service._get(row, "name"),
            "recognition_status": invoice_service._get(row, "recognition_status"),
            "expense_line_key": invoice_service._get(row, "expense_line_key"),
            "total_amount": invoice_service._record_money(row, "total_amount"),
        }
        for row in records
    ]
    total = _rule(rules.check_claim_lines, doc.request_type, lines, invoices)
    doc.amount = float(total)
    _link_application(doc, application, amount=total)
    classification = oa_entry._expense_classification(doc.doc_type, doc.asset_category, submitting=True)
    for fieldname, value in classification.items():
        setattr(doc, fieldname, value)
    if doc.request_type == REQUEST_REIMBURSEMENT:
        _employee_payee(doc)
    _rule(rules.check_payee, doc.request_type, doc.payment_method, doc.payee_name, doc.bank_name, doc.account_no)
    if doc.request_type == REQUEST_REIMBURSEMENT:
        doc.invoice_handling_mode = oa_entry.INVOICE_MODE_AVAILABLE
        doc.invoice_followup_status = rules.FOLLOWUP_RECEIVED
        doc.expected_invoice_date = None
    else:
        invoice_total = sum((rules.money(item["total_amount"]) for item in invoices), rules.money(0))
        state = _rule(
            rules.payment_invoice_state, total, invoice_total, len(invoices),
            expected_invoice_date=doc.expected_invoice_date,
            no_invoice_reason=doc.no_invoice_reason,
            difference_note=getattr(doc, "invoice_difference_note", None),
            today=date.today(),
        )
        doc.invoice_followup_status = state
        if state == rules.FOLLOWUP_RECEIVED:
            doc.invoice_handling_mode = oa_entry.INVOICE_MODE_AVAILABLE
            doc.expected_invoice_date = None
        else:
            doc.invoice_handling_mode = oa_entry.INVOICE_MODE_PENDING
    invoice_service._apply_request_invoice_summary(doc, save=False, current=True)


def reserve(doc):
    """Called from oa_entry.submit_request after _submit_draft: occupy the purchase amount."""
    if not is_claim(doc) or not _capped(doc):
        return None
    # The ledger reads the claim row from the database, so persist the submitted amount first.
    oa_entry._save_document(doc)
    return _ledger(
        approval_amount_ledger.reserve, doc.source_request, doc.name,
        "claim-submit:{0}:{1}".format(doc.name, rules.submission_round(_events(doc))),
        note=doc.request_type + "提交占用",
    )


def release(doc, note=""):
    """Called when a submitted claim returns to draft (withdraw or reject to applicant)."""
    if not is_claim(doc) or not _capped(doc):
        return None
    return _ledger(
        approval_amount_ledger.release_all_reserved, doc.source_request, doc.name,
        "claim-release:{0}:{1}".format(doc.name, rules.submission_round(_events(doc))),
        note=note or doc.request_type + "退回释放占用",
    )


def refresh_application_status(source_name):
    """购买申请：按台账已付金额更新为 待付款 / 部分付款 / 已付款。"""
    source_name = _clean(source_name)
    if not source_name or frappe.db.get_value("OA Approval Request", source_name, "request_type") not in rules.CAPPED_APPLICATION_TYPES:
        return None
    balance = _ledger(approval_amount_ledger.source_balance, source_name)
    status = rules.application_payment_status(balance["approved_amount"], balance["paid_amount"])
    if frappe.db.get_value("OA Approval Request", source_name, "business_status") != status:
        frappe.db.set_value("OA Approval Request", source_name, "business_status", status, update_modified=False)
    return status


def mark_paid(doc, actor, from_status, note, step):
    """Called from oa_entry.action_request when the cashier completes the payment step."""
    if _capped(doc):
        _ledger(
            approval_amount_ledger.mark_paid, doc.source_request, doc.name,
            "claim-pay:{0}:{1}".format(doc.name, rules.payment_round(_events(doc))),
            note=doc.request_type + "确认付款",
        )
    doc.workflow_status = oa_entry.STATUS_PAID
    doc.business_status = rules.paid_business_status(doc.request_type, _clean(doc.invoice_followup_status))
    doc.paid_by = actor
    doc.paid_on = step.acted_on or now_datetime()
    oa_entry._append_request_event(doc, "确认付款", from_status, oa_entry.STATUS_PAID, note)
    refresh_application_status(doc.source_request)


def capabilities(doc):
    """Extra summary keys for 报销单 / 付款单 (empty for every other request type)."""
    if not is_claim(doc):
        return {}
    finance = oa_entry._is_finance_user()
    paid = doc.workflow_status == oa_entry.STATUS_PAID
    followup = _clean(getattr(doc, "invoice_followup_status", None))
    business = _clean(getattr(doc, "business_status", None))
    return {
        "source_locked": _clean(getattr(doc, "source_type", None)) == rules.SOURCE_APPLICATION_PUSH,
        "invoice_difference_note": getattr(doc, "invoice_difference_note", None) or "",
        "claim_line_projects": {
            _clean(line.line_key): _clean(getattr(line, "claim_project", None)) for line in doc.expense_lines
        },
        "can_supplement_claim_invoices": bool(
            doc.request_type == REQUEST_PAYMENT and paid and followup == rules.FOLLOWUP_PENDING
            and _is_applicant(doc)
        ),
        "can_verify_claim_invoices": bool(
            doc.request_type == REQUEST_PAYMENT and paid and business == rules.CLAIM_WAIT_VERIFY and finance
        ),
        "can_withdraw_claim_payment": bool(paid and finance),
    }


# ---------------------------------------------------------------- finance and follow-up actions


def _locked_claim(name, request_type=None):
    request_name = _text(name, "单号", 140)
    doc = oa_entry._load_request(request_name, current=True)
    if not is_claim(doc) or (request_type and doc.request_type != request_type):
        frappe.throw("这张单据不是" + (request_type or "报销单或付款单") + "。")
    require_request_type_access(doc.request_type)
    return doc


@frappe.whitelist(methods=["POST"])
def save_claim_accounts(name, lines):
    """出纳审核时逐行填写一、二级科目。"""
    request_name = _text(name, "单号", 140)
    rows = _rows(lines, "费用科目", MAX_LINES)
    if not rows:
        frappe.throw("没有要保存的费用科目。")
    with invoice_service._transaction_lock("request", request_name):
        doc = _locked_claim(request_name)
        step = oa_entry._current_step(doc)
        if (
            doc.workflow_status not in oa_entry.ACTIVE_STATUSES
            or not oa_entry._is_finance_audit_step(step)
            or not oa_entry._can_act_on_current_step(doc)
            or not (oa_entry._is_finance_user() or oa_entry._is_oa_override_user())
        ):
            frappe.throw("只有当前出纳审核人可以填写费用科目。")
        by_key = {_clean(line.line_key): line for line in doc.expense_lines}
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) - {"line_key", "expense_account_level_1", "expense_account_level_2"}:
                frappe.throw("费用科目只能修改一级、二级科目。")
            key = _clean(row.get("line_key"))
            if key not in by_key or key in seen:
                frappe.throw("费用明细不属于该单据，请刷新后重试。")
            seen.add(key)
            level_1, level_2, display = oa_entry._expense_account_pair(
                row.get("expense_account_level_1"), row.get("expense_account_level_2"), required=True
            )
            line = by_key[key]
            line.expense_account_level_1 = level_1
            line.expense_account_level_2 = level_2
            line.expense_item = display
        oa_entry._append_request_event(doc, "填写费用科目", doc.workflow_status, doc.workflow_status, details={"line_count": len(seen)})
        oa_entry._save_document(doc)
        return oa_entry._summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def supplement_payment_invoices(name, invoice_names, difference_note=None):
    """付款单先付款后补票：关联已确认发票，金额差超过 0.02 元须说明，然后等财务核验。"""
    request_name = _text(name, "单号", 140)
    names = _invoice_list(invoice_names, "补录发票")
    if not names:
        frappe.throw("请选择要补录的发票。")
    note = _text(difference_note, "发票差异说明", 1000)
    with invoice_service._transaction_lock("request", request_name):
        doc = _locked_claim(request_name, REQUEST_PAYMENT)
        if doc.workflow_status != oa_entry.STATUS_PAID or _clean(doc.invoice_followup_status) != rules.FOLLOWUP_PENDING:
            frappe.throw("只有已付款、待补票的付款单可以补录发票。")
        if not _is_applicant(doc):
            frappe.throw("只有申请人可以补录发票。")
        with ExitStack() as locks:
            for invoice in sorted(names):
                locks.enter_context(invoice_service._transaction_lock("record", invoice))
            records = [invoice_service._require_record(invoice, write=True, current=True) for invoice in names]
            for record in records:
                if record.recognition_status != rules.INVOICE_CONFIRMED:
                    frappe.throw(f"发票 {record.name} 还未确认，不能补录。")
                if _clean(record.request) and _clean(record.request) != doc.name:
                    frappe.throw(f"发票 {record.name} 已被 {record.request} 使用。")
            total = sum((_record_total(record) for record in records), rules.money(0))
            _rule(rules.check_invoice_total, doc.amount, total, note)
            for record in records:
                record.request = doc.name
                record.expense_line_key = ""
                invoice_service._append_record_event(record, "补录到付款单", record.recognition_status, record.recognition_status, doc.name)
                invoice_service._save(record)
        doc.invoice_difference_note = note
        doc.invoice_followup_status = rules.FOLLOWUP_RECEIVED
        doc.invoice_handling_mode = oa_entry.INVOICE_MODE_AVAILABLE
        old = doc.business_status
        doc.business_status = rules.CLAIM_WAIT_VERIFY
        oa_entry._append_request_event(doc, "补录发票", old, doc.business_status, note, {"invoices": names, "invoice_total": str(total)})
        invoice_service._apply_request_invoice_summary(doc, save=False, current=True)
        oa_entry._save_document(doc)
        return oa_entry._summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def verify_claim_invoices(name, note=None):
    """财务核验补录的发票，付款单完结。"""
    oa_entry._require_finance_user()
    request_name = _text(name, "单号", 140)
    with invoice_service._transaction_lock("request", request_name):
        doc = _locked_claim(request_name, REQUEST_PAYMENT)
        if doc.workflow_status != oa_entry.STATUS_PAID or _clean(doc.business_status) != rules.CLAIM_WAIT_VERIFY:
            frappe.throw("只有待核验的付款单可以核验发票。")
        old = doc.business_status
        doc.invoice_followup_status = rules.FOLLOWUP_VERIFIED
        doc.business_status = rules.CLAIM_DONE
        oa_entry._append_request_event(doc, "核验发票", old, doc.business_status, _text(note, "核验说明", 500))
        oa_entry._save_document(doc)
        return oa_entry._summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def return_claim_invoices(name, note):
    """财务退回补录的发票：发票解除关联，付款单回到"已付款·待补票"。"""
    oa_entry._require_finance_user()
    request_name = _text(name, "单号", 140)
    reason = _text(note, "退回原因", 500)
    if not reason:
        frappe.throw("请填写退回原因。")
    with invoice_service._transaction_lock("request", request_name):
        doc = _locked_claim(request_name, REQUEST_PAYMENT)
        if doc.workflow_status != oa_entry.STATUS_PAID or _clean(doc.business_status) != rules.CLAIM_WAIT_VERIFY:
            frappe.throw("只有待核验的付款单可以退回发票。")
        released = sorted(
            _clean(invoice_service._get(row, "name"))
            for row in invoice_service._request_invoice_records(doc.name, current=True)
        )
        _relink_invoices(doc, [], finance_release=True)
        old = doc.business_status
        doc.invoice_followup_status = rules.FOLLOWUP_PENDING
        doc.invoice_handling_mode = oa_entry.INVOICE_MODE_PENDING
        doc.business_status = rules.CLAIM_PAID_WAIT_INVOICE
        oa_entry._append_request_event(doc, "退回补录发票", old, doc.business_status, reason, {"invoices": released})
        invoice_service._apply_request_invoice_summary(doc, save=False, current=True)
        oa_entry._save_document(doc)
        return oa_entry._summarize_doc(doc)


@frappe.whitelist(methods=["POST"])
def withdraw_claim_payment(name, note=None):
    """财务撤回付款：冲回台账已付、重新占用额度，单据回到出纳付款节点，可再次付款。"""
    oa_entry._require_finance_user()
    request_name = _text(name, "单号", 140)
    reason = _text(note, "撤回说明", 500)
    with invoice_service._transaction_lock("request", request_name):
        doc = _locked_claim(request_name)
        if doc.workflow_status != oa_entry.STATUS_PAID:
            frappe.throw("只有已付款的报销单或付款单可以撤回付款。")
        pay_step = next((step for step in sorted(doc.steps, key=lambda row: -int(row.step_index or 0)) if step.mode == "handle"), None)
        if not pay_step:
            frappe.throw("找不到出纳付款节点。")
        round_no = rules.payment_round(_events(doc))
        if _capped(doc):
            _ledger(
                approval_amount_ledger.reverse, doc.source_request, doc.name, doc.amount,
                "claim-reverse:{0}:{1}".format(doc.name, round_no), note=reason or "撤回付款",
            )
            _ledger(
                approval_amount_ledger.reserve, doc.source_request, doc.name,
                "claim-rereserve:{0}:{1}".format(doc.name, round_no), note="撤回付款后重新占用",
            )
        pay_step.status = oa_entry.STATUS_WAIT_HANDLE
        pay_step.action_by = ""
        pay_step.acted_on = None
        pay_step.approved_by = "[]"
        old = doc.workflow_status
        doc.workflow_status = oa_entry.STATUS_WAIT_HANDLE
        doc.current_step_index = pay_step.step_index
        doc.current_step_label = pay_step.label
        doc.business_status = rules.CLAIM_WAIT_PAY
        doc.paid_by = ""
        doc.paid_on = None
        oa_entry._append_request_event(doc, rules.EVENT_WITHDRAW_PAYMENT, old, doc.workflow_status, reason)
        oa_entry._save_document(doc)
        oa_entry._sync_assignments_after_save(doc)
        refresh_application_status(doc.source_request)
        return oa_entry._summarize_doc(doc)
