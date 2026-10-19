from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONEY = Decimal("0.01")
PERCENT = Decimal("0.0001")
PAYMENT_STAGES = {"预付款", "到货款", "尾款", "到货后全额付款"}
INVOICE_REQUIREMENTS = {"付款前提供", "付款后提供", "无需发票"}


class ProcurementContractError(ValueError):
    pass


def _text(value, label, limit=1000, required=False):
    result = str(value or "").strip()
    if required and not result:
        raise ProcurementContractError(f"{label}不能为空")
    if len(result) > limit:
        raise ProcurementContractError(f"{label}不能超过{limit}个字符")
    return result


def _decimal(value, label, *, positive=False, places=MONEY):
    try:
        result = Decimal(str(value if value not in (None, "") else 0)).quantize(places, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ProcurementContractError(f"{label}格式无效")
    if positive and result <= 0:
        raise ProcurementContractError(f"{label}必须大于零")
    if result < 0:
        raise ProcurementContractError(f"{label}不能小于零")
    return result


def _date(value, label, required=False):
    result = _text(value, label, 10, required)
    if result:
        try:
            date.fromisoformat(result)
        except ValueError:
            raise ProcurementContractError(f"{label}格式无效")
    return result


def _rows(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            raise ProcurementContractError("付款计划格式无效")
    if not isinstance(value, list):
        raise ProcurementContractError("付款计划格式无效")
    return value


def normalize_payment_plan(value, total_amount):
    total = _decimal(total_amount, "价格审批总额", positive=True)
    rows = _rows(value)
    if not rows:
        raise ProcurementContractError("至少填写一期付款计划")
    if len(rows) > 20:
        raise ProcurementContractError("付款计划不能超过20期")
    normalized = []
    percentage_total = Decimal("0")
    amount_total = Decimal("0")
    prepayment_count = 0
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            raise ProcurementContractError(f"第{index}期付款计划格式无效")
        stage = _text(raw.get("payment_stage"), f"第{index}期付款阶段", 20, True)
        if stage not in PAYMENT_STAGES:
            raise ProcurementContractError(f"第{index}期付款阶段无效")
        if stage == "预付款":
            prepayment_count += 1
        percentage = _decimal(raw.get("percentage"), f"第{index}期比例", positive=True, places=PERCENT)
        amount = _decimal(raw.get("amount"), f"第{index}期金额", positive=True)
        planned_date = _date(raw.get("planned_date"), f"第{index}期计划日期")
        trigger = _text(raw.get("trigger_condition"), f"第{index}期触发条件", 500, True)
        invoice_requirement = _text(raw.get("invoice_requirement") or "付款前提供", f"第{index}期发票条件", 30, True)
        if invoice_requirement not in INVOICE_REQUIREMENTS:
            raise ProcurementContractError(f"第{index}期发票条件无效")
        normalized.append({
            "installment_no": index,
            "installment_name": _text(raw.get("installment_name") or f"第{index}期", f"第{index}期名称", 80, True),
            "payment_stage": stage,
            "percentage": percentage,
            "amount": amount,
            "planned_date": planned_date or None,
            "trigger_condition": trigger,
            "invoice_requirement": invoice_requirement,
            "status": "待生成",
        })
        percentage_total += percentage
        amount_total += amount
    if prepayment_count > 1:
        raise ProcurementContractError("预付款只能设置一期")
    if abs(percentage_total - Decimal("100")) > PERCENT:
        raise ProcurementContractError("付款计划比例合计必须为100%")
    if abs(amount_total - total) > MONEY:
        raise ProcurementContractError("付款计划金额合计必须等于价格审批总额")
    return normalized


def price_approval_snapshot(*, supplier, total_amount, business_lines, tax_included, tax_rate,
                            delivery_terms, warranty_terms, invoice_condition, payment_plan, revision):
    supplier = _text(supplier, "供应商", 140, True)
    normalized_plan = normalize_payment_plan(payment_plan, total_amount)
    snapshot = {
        "revision": int(revision or 1),
        "supplier": supplier,
        "amount": float(_decimal(total_amount, "价格审批总额", positive=True)),
        "tax_included": 1 if tax_included in (1, "1", True, "true") else 0,
        "tax_rate": float(_decimal(tax_rate, "税率", places=PERCENT)),
        "delivery_terms": _text(delivery_terms, "交付条件", 1000, True),
        "warranty_terms": _text(warranty_terms, "质保条件", 1000, True),
        "invoice_condition": _text(invoice_condition, "开票条件", 1000, True),
        "business_lines": business_lines,
        "payment_plan": [{key: (float(value) if isinstance(value, Decimal) else value) for key, value in row.items()} for row in normalized_plan],
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot["fingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return snapshot, normalized_plan


OFFICIAL_CONTRACT_ENTITY = "示例企业032有限公司"
LEGACY_CONTRACT_ENTITIES = {"普朗克半导体", "示例企业022有限公司", "QIHENG Demo", "QIHENG Demo Technology Co., Ltd."}


def contract_snapshot(values, approved_price_snapshot, version):
    values = dict(values or {})
    if not _text(values.get("contract_entity"), "我方签约主体", 140) or values.get("contract_entity") in LEGACY_CONTRACT_ENTITIES:
        values["contract_entity"] = OFFICIAL_CONTRACT_ENTITY
    if not approved_price_snapshot:
        raise ProcurementContractError("缺少已批准的价格审批快照")
    if isinstance(approved_price_snapshot, str):
        try:
            approved_price_snapshot = json.loads(approved_price_snapshot)
        except (TypeError, ValueError):
            raise ProcurementContractError("已批准的价格审批快照无效")
    required = {
        "supplier_legal_name": ("供应商法定名称", 140), "credit_code": ("统一社会信用代码", 40),
        "supplier_address": ("供应商地址", 500), "contract_contact": ("演示员工116联系人", 140),
        "contract_bank_name": ("收款银行", 140), "contract_bank_account": ("收款账号", 80),
        "contract_entity": ("我方签约主体", 140), "contract_template": ("演示员工116模板", 140),
        "seal_user": ("用印账号", 140),
    }
    result = {"version": int(version or 1), "price_fingerprint": approved_price_snapshot.get("fingerprint")}
    for key, (label, limit) in required.items():
        result[key] = _text(values.get(key), label, limit, True)
    result["contract_delivery_date"] = _date(values.get("contract_delivery_date"), "演示员工116交付日期", True)
    result["price"] = approved_price_snapshot
    return result


def render_contract_draft(snapshot):
    price = snapshot["price"]
    lines = [
        f"电子采购演示员工116（测试模板 V{snapshot['version']}）", f"我方主体：{snapshot['contract_entity']}",
        f"供应商：{snapshot['supplier_legal_name']}", f"统一社会信用代码：{snapshot['credit_code']}",
        f"供应商地址：{snapshot['supplier_address']}", f"演示员工116联系人：{snapshot['contract_contact']}",
        f"收款银行：{snapshot['contract_bank_name']}", f"收款账号：{snapshot['contract_bank_account']}",
        f"演示员工116总额：CNY {price['amount']:.2f}", f"交付日期：{snapshot['contract_delivery_date']}",
        f"交付条件：{price['delivery_terms']}", f"质保条件：{price['warranty_terms']}",
        f"开票条件：{price['invoice_condition']}", "付款计划：",
    ]
    for row in price["payment_plan"]:
        lines.append(f"{row['installment_no']}. {row['installment_name']} / {row['payment_stage']} / {row['percentage']:.2f}% / CNY {row['amount']:.2f} / {row['trigger_condition']}")
    lines.append(f"价格审批指纹：{snapshot['price_fingerprint']}")
    return "\n".join(lines)
