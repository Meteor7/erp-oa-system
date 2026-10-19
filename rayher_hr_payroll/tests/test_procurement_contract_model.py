import json
import pytest
from rayher_hr_payroll.procurement_contract import ProcurementContractError, contract_snapshot, normalize_payment_plan, price_approval_snapshot, render_contract_draft


def plan():
    return [{"payment_stage":"预付款","percentage":30,"amount":3000,"planned_date":"2026-09-01","trigger_condition":"演示员工116生效","invoice_requirement":"付款后提供"},{"payment_stage":"尾款","percentage":70,"amount":7000,"planned_date":"2026-10-01","trigger_condition":"验收通过","invoice_requirement":"付款前提供"}]


def test_payment_plan_requires_exact_percentage_and_amount_totals():
    rows = normalize_payment_plan(plan(), 10000)
    assert [row["installment_no"] for row in rows] == [1, 2]
    assert str(rows[0]["percentage"]) == "30.0000"
    assert str(rows[1]["amount"]) == "7000.00"
    bad_percentage = plan()
    bad_percentage[1]["percentage"] = 60
    with pytest.raises(ProcurementContractError, match="100%"):
        normalize_payment_plan(bad_percentage, 10000)
    bad_amount = plan()
    bad_amount[1]["amount"] = 6000
    with pytest.raises(ProcurementContractError, match="价格审批总额"):
        normalize_payment_plan(bad_amount, 10000)


def test_price_snapshot_is_fingerprinted_and_contract_embeds_locked_snapshot():
    price, rows = price_approval_snapshot(supplier="示例企业028",total_amount=10000,business_lines=[{"item_name":"激光器","quantity":1,"unit_price":10000}],tax_included=1,tax_rate=13,delivery_terms="2026-10-01 前交付",warranty_terms="质保一年",invoice_condition="增值税专用发票",payment_plan=plan(),revision=2)
    assert len(price["fingerprint"]) == 64
    assert len(rows) == 2
    contract = contract_snapshot({"supplier_legal_name":"示例企业028有限公司","credit_code":"910000000000000003","supplier_address":"示例市示例区演示路1号","contract_contact":"王测试 13800000002","contract_bank_name":"测试银行","contract_bank_account":"6200000000000001","contract_entity":"示例企业032有限公司","contract_template":"标准采购演示员工116","seal_user":"finance@example.com","contract_delivery_date":"2026-10-01"}, json.dumps(price, ensure_ascii=False), 1)
    rendered = render_contract_draft(contract)
    assert contract["price_fingerprint"] == price["fingerprint"]
    assert contract["contract_entity"] == "示例企业032有限公司"
    assert "示例企业032有限公司" in rendered
    assert "普朗克半导体" not in rendered
    assert "付款计划" in rendered
    assert "示例企业028有限公司" in rendered
