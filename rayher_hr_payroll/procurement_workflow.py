from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation


PROJECT_PROCUREMENT = "项目采购"
NON_PROJECT_PROCUREMENT = "非项目采购"
PROCUREMENT_SCOPES = {PROJECT_PROCUREMENT, NON_PROJECT_PROCUREMENT}
NON_PROJECT_ALLOCATION_TYPES = {"成本中心", "部门", "非项目采购"}
PAYMENT_STAGES = {"预付款", "到货款", "尾款", "到货后全额付款"}
ARRIVAL_STATUSES = {"未到货", "部分到货", "全部到货", "关闭未交数量", "退货中", "换货中"}
INSPECTION_STATUSES = {"未验收", "待验收", "验收通过", "验收不合格"}
WRITE_OFF_STATUSES = {"无需核销", "待核销", "已核销"}
REFUND_EVIDENCE = "退款回单"
ARRIVAL_EVIDENCE = {"送货单", "收料单", "入库单"}
ACCEPTANCE_EVIDENCE = "验收资料"
FOLLOWUP_STATUSES = {"催办中", "供应商退款中", "退货中", "换货中"}


class ProcurementWorkflowError(ValueError):
    pass


def _get(source, key, default=None):
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _text(value):
    return str(value or "").strip()


def _decimal(value, label):
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError, TypeError):
        raise ProcurementWorkflowError(f"{label}格式无效")


def _date(value, label):
    text = _text(value)
    if not text:
        raise ProcurementWorkflowError(f"{label}不能为空")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ProcurementWorkflowError(f"{label}格式无效")


def _evidence_types(evidence):
    result = set()
    for item in evidence or ():
        if isinstance(item, dict):
            value = item.get("document_type") or item.get("doc_type") or item.get("type")
        else:
            value = item
        value = _text(value)
        if value:
            result.add(value)
    return result


def validate_procurement_submission(doc, evidence=None):
    scope = _text(_get(doc, "procurement_scope"))
    if scope not in PROCUREMENT_SCOPES:
        raise ProcurementWorkflowError("采购范围必须选择项目采购或非项目采购")
    _date(_get(doc, "expected_delivery_date"), "意向交期")
    if scope == PROJECT_PROCUREMENT:
        if not _text(_get(doc, "project")):
            raise ProcurementWorkflowError("所属项目不能为空")
        if not _text(_get(doc, "project_owner")):
            raise ProcurementWorkflowError("项目负责人没有关联有效账号")
        return
    allocation = _text(_get(doc, "non_project_allocation_type"))
    if allocation not in NON_PROJECT_ALLOCATION_TYPES:
        raise ProcurementWorkflowError("非项目归属必须选择成本中心、部门或非项目采购")
    if allocation == "成本中心" and not _text(_get(doc, "non_project_cost_center")):
        raise ProcurementWorkflowError("非项目采购选择成本中心时必须填写成本中心")
    if allocation == "部门" and not _text(_get(doc, "non_project_department")):
        raise ProcurementWorkflowError("非项目采购选择部门时必须填写所属部门")


def derive_payment_stage(doc):
    percentage = _decimal(_get(doc, "prepayment_percentage"), "预付款比例")
    if percentage < 0 or percentage > 100:
        raise ProcurementWorkflowError("预付款比例必须在0到100之间")
    arrival_complete = _text(_get(doc, "arrival_status")) in {"全部到货", "关闭未交数量"}
    inspection_passed = _text(_get(doc, "inspection_status")) == "验收通过"
    if arrival_complete:
        if not inspection_passed:
            raise ProcurementWorkflowError("到货后付款提交前必须验收通过")
        paid = _decimal(_get(doc, "source_paid_amount"), "来源已付金额")
        available = _decimal(_get(doc, "source_available_amount"), "来源可用金额")
        amount = _decimal(_get(doc, "amount"), "本次付款金额")
        if paid > 0:
            return "尾款"
        if available > 0 and amount == available:
            return "到货后全额付款"
        return "到货款"
    if percentage <= 0:
        raise ProcurementWorkflowError("来源采购尚未完成到货验收且预付款比例为0，当前无需提交付款申请")
    return "预付款"


def validate_payment_submission(doc, evidence=None):
    if not _text(_get(doc, "source_request")):
        raise ProcurementWorkflowError("采购付款必须关联采购申请")
    if not _text(_get(doc, "supplier")):
        raise ProcurementWorkflowError("采购付款必须选择供应商")
    stage = derive_payment_stage(doc)
    evidence_types = _evidence_types(evidence)
    percentage = _decimal(_get(doc, "prepayment_percentage"), "预付款比例")
    if stage == "预付款":
        if not ({"合同", "PO"} & evidence_types):
            raise ProcurementWorkflowError("预付款必须提供合同或PO")
        if "付款计划" not in evidence_types:
            raise ProcurementWorkflowError("预付款必须提供付款计划")
        if percentage == 100:
            _date(_get(doc, "expected_arrival_date"), "预计到货日期")
            if not _text(_get(doc, "prepayment_risk_note")):
                raise ProcurementWorkflowError("100%预付款必须填写预付款风险说明")
        return stage
    if ACCEPTANCE_EVIDENCE not in evidence_types:
        raise ProcurementWorkflowError("到货后付款必须提供验收资料")
    if "发票" not in evidence_types:
        raise ProcurementWorkflowError("到货后付款必须提供发票")
    return stage


def transition_business_state(doc, action, payload=None, evidence=None):
    payload = payload or {}
    evidence_types = _evidence_types(evidence)
    business_status = _text(_get(doc, "business_status"))
    arrival_status = _text(_get(doc, "arrival_status")) or "未到货"
    if action == "record_arrival":
        if business_status not in {
            "合同待登记", "采购执行中", "待到货", "部分到货", "预付款逾期", "催办中", "换货中"
        }:
            raise ProcurementWorkflowError("当前状态不能登记到货")
        if not (ARRIVAL_EVIDENCE & evidence_types):
            raise ProcurementWorkflowError("登记到货必须提供送货单、收料单或入库单作为到货证明")
        arrival_date = _date(payload.get("arrival_date"), "到货日期").isoformat()
        quantity = _decimal(payload.get("quantity"), "到货数量")
        ordered = _decimal(_get(doc, "ordered_quantity"), "订单数量")
        received = _decimal(_get(doc, "received_quantity"), "累计到货数量")
        if quantity <= 0:
            raise ProcurementWorkflowError("到货数量必须大于0")
        if ordered <= 0:
            raise ProcurementWorkflowError("订单数量必须大于0")
        total = received + quantity
        if total > ordered:
            raise ProcurementWorkflowError("累计到货数量不能超过订单数量")
        complete = total == ordered
        result = {
            "business_status": "待验收" if complete else "部分到货",
            "arrival_status": "全部到货" if complete else "部分到货",
            "received_quantity": int(total) if total == total.to_integral() else float(total),
            "arrival_date": arrival_date,
            "inspection_status": "未验收",
        }
        if business_status == "换货中":
            result["followup_status"] = ""
        return result
    if action in {"pass_inspection", "fail_inspection"}:
        if arrival_status not in {"全部到货", "关闭未交数量"}:
            raise ProcurementWorkflowError("货物未全部到货或关闭未交数量，不能登记验收结果")
        if business_status not in {"待验收", "全部到货", "关闭未交数量", "验收不合格"}:
            raise ProcurementWorkflowError("当前状态不能登记验收结果")
        if ACCEPTANCE_EVIDENCE not in evidence_types:
            raise ProcurementWorkflowError("登记验收结果必须提供验收资料")
        if action == "pass_inspection":
            return {
                "business_status": "验收通过",
                "inspection_status": "验收通过",
                "inspection_failure_reason": "",
                "exception_direction": "",
            }
        reason = _text(payload.get("reason"))
        direction = _text(payload.get("direction"))
        if not reason:
            raise ProcurementWorkflowError("验收不合格必须填写原因")
        if direction not in {"退货", "换货"}:
            raise ProcurementWorkflowError("验收不合格必须选择退货或换货方向")
        replacement = direction == "换货"
        return {
            "business_status": "换货中" if replacement else "退货中",
            "arrival_status": "换货中" if replacement else "退货中",
            "received_quantity": 0 if replacement else _get(doc, "received_quantity"),
            "inspection_status": "验收不合格",
            "inspection_failure_reason": reason,
            "exception_direction": direction,
            "followup_status": "换货中" if replacement else "退货中",
        }
    if action == "record_followup":
        status = _text(payload.get("status"))
        if status not in FOLLOWUP_STATUSES:
            raise ProcurementWorkflowError("预付款异常状态无效")
        if not _text(payload.get("reason")):
            raise ProcurementWorkflowError("预付款异常跟进必须填写说明")
        if _text(_get(doc, "payment_stage")) != "预付款":
            raise ProcurementWorkflowError("只有预付款可以登记异常跟进")
        return {"business_status": status, "followup_status": status}
    if action == "complete_supplier_refund":
        if business_status not in {"供应商退款中", "退货中"}:
            raise ProcurementWorkflowError("只有供应商退款中或退货中的付款可以确认退款")
        if REFUND_EVIDENCE not in evidence_types:
            raise ProcurementWorkflowError("确认供应商退款必须提供退款回单")
        return {
            "business_status": "已退款",
            "arrival_status": "关闭未交数量",
            "followup_status": "供应商退款完成",
            "prepayment_writeoff_status": "无需核销",
        }
    if action == "writeoff_prepayment":
        if _text(_get(doc, "payment_stage")) != "预付款" or _decimal(_get(doc, "prepayment_percentage"), "预付款比例") != 100:
            raise ProcurementWorkflowError("只有100%预付款可以执行预付款核销")
        if arrival_status not in {"全部到货", "关闭未交数量"} or _text(_get(doc, "inspection_status")) != "验收通过":
            raise ProcurementWorkflowError("预付款核销前必须完成到货和验收")
        if "发票" not in evidence_types:
            raise ProcurementWorkflowError("预付款核销必须提供发票")
        if ACCEPTANCE_EVIDENCE not in evidence_types:
            raise ProcurementWorkflowError("预付款核销必须提供验收资料")
        return {"business_status": "已核销", "prepayment_writeoff_status": "已核销"}
    if action == "close_procurement":
        if bool(int(_get(doc, "has_balance_payment") or 0)):
            raise ProcurementWorkflowError("存在后续尾款的采购不能按无尾款流程关闭")
        if arrival_status not in {"全部到货", "关闭未交数量"} or _text(_get(doc, "inspection_status")) != "验收通过":
            raise ProcurementWorkflowError("关闭采购前必须完成到货和验收")
        if _text(_get(doc, "payment_stage")) == "预付款" and _decimal(_get(doc, "prepayment_percentage"), "预付款比例") == 100:
            if _text(_get(doc, "prepayment_writeoff_status")) != "已核销":
                raise ProcurementWorkflowError("100%预付款关闭前必须完成预付款核销")
        required = {"发票", "验收资料", "采购完成报告"}
        missing = required - evidence_types
        if missing:
            raise ProcurementWorkflowError("关闭采购缺少" + "、".join(sorted(missing)))
        return {"business_status": "已关闭"}
    raise ProcurementWorkflowError(f"不支持的采购状态操作：{_text(action)}")


def derive_prepayment_overdue(doc, *, today=None):
    if _text(_get(doc, "payment_stage")) != "预付款":
        return False
    if _decimal(_get(doc, "prepayment_percentage"), "预付款比例") != 100:
        return False
    if _text(_get(doc, "arrival_status")) in {"全部到货", "关闭未交数量"}:
        return False
    expected = _text(_get(doc, "expected_arrival_date"))
    if not expected:
        return False
    expected_date = _date(expected, "预计到货日期")
    return expected_date < (today or date.today())

def plan_contract_delivery(expected_delivery_date, contract_delivery_date, procurement_scope, reason=None):
    expected = _date(expected_delivery_date, "意向交期")
    contract = _date(contract_delivery_date, "合同约定交期")
    scope = _text(procurement_scope)
    if scope not in PROCUREMENT_SCOPES:
        raise ProcurementWorkflowError("采购范围必须选择项目采购或非项目采购")
    requires_reapproval = contract > expected
    if requires_reapproval and not _text(reason):
        raise ProcurementWorkflowError("合同交期晚于意向交期时必须填写变更原因")
    approval_roles = []
    if requires_reapproval:
        approval_roles.append("pmc")
        if scope == PROJECT_PROCUREMENT:
            approval_roles.append("project_owner")
    return {
        "contract_delivery_date": contract.isoformat(),
        "requires_reapproval": requires_reapproval,
        "approval_roles": approval_roles,
    }


def contract_copy_recipients(snapshot):
    recipients = []
    by_user = {}
    for role_key in ("applicant", "purchaser", "pmc", "supervisor", "project_owner"):
        role = (snapshot or {}).get(role_key) or {}
        user = _text(_get(role, "user"))
        label = _text(_get(role, "label")) or role_key
        if not user:
            continue
        if user not in by_user:
            row = {"label": label, "user": user, "roles": [label]}
            by_user[user] = row
            recipients.append(row)
        elif label not in by_user[user]["roles"]:
            by_user[user]["roles"].append(label)
            by_user[user]["label"] = "、".join(by_user[user]["roles"])
    return recipients
