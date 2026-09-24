"""Regression tests for the 2026-09-24 procurement review fixes (pure parts)."""
import importlib
import types

import pytest


def _row(**values):
    return types.SimpleNamespace(**values)


def test_closed_prepayments_cannot_be_reopened_by_a_followup():
    workflow = importlib.import_module("rayher_hr_payroll.procurement_workflow")
    open_doc = {"payment_stage": "预付款", "business_status": "待到货", "prepayment_writeoff_status": "待核销"}
    assert workflow.transition_business_state(open_doc, "record_followup", payload={"status": "催办中", "reason": "催"}, evidence=[])["business_status"] == "催办中"
    for status in ("已退款", "验收通过", "已关闭"):
        with pytest.raises(workflow.ProcurementWorkflowError, match="不能再登记异常跟进"):
            workflow.transition_business_state({**open_doc, "business_status": status}, "record_followup",
                                               payload={"status": "供应商退款中", "reason": "x"}, evidence=[])
    with pytest.raises(workflow.ProcurementWorkflowError, match="不能再登记异常跟进"):
        workflow.transition_business_state({**open_doc, "prepayment_writeoff_status": "已核销"}, "record_followup",
                                           payload={"status": "供应商退款中", "reason": "x"}, evidence=[])


@pytest.mark.parametrize("lines, expected", [
    ([(2, 0, ""), (3, 0, "")], ("未到货", "未验收", "待到货")),
    ([(2, 1, "待验收"), (3, 0, "")], ("部分到货", "待验收", "部分到货")),
    ([(2, 2, "待验收"), (3, 3, "已通过")], ("全部到货", "待验收", "待验收")),
    ([(2, 2, "已通过"), (3, 3, "已通过")], ("全部到货", "验收通过", "验收通过")),
    ([(2, 2, "不合格"), (3, 3, "已通过")], ("全部到货", "验收不合格", "待验收")),
])
def test_po_fulfilment_state_follows_the_po_lines(lines, expected):
    chain = importlib.import_module("rayher_hr_payroll.api.procurement_chain")
    po = _row(lines=[_row(quantity=q, received_quantity=r, inspection_status=s) for q, r, s in lines])
    state = chain.po_fulfilment_state(po)
    assert (state["arrival_status"], state["inspection_status"], state["business_status"]) == expected


def test_only_cny_is_accepted_for_quotes_and_orders(monkeypatch):
    chain = importlib.import_module("rayher_hr_payroll.api.procurement_chain")
    monkeypatch.setattr(chain.frappe, "throw", lambda message, *a, **k: (_ for _ in ()).throw(ValueError(message)), raising=False)
    assert chain._require_cny("") == "CNY"
    assert chain._require_cny("CNY") == "CNY"
    for currency in ("USD", "EUR", "JPY"):
        with pytest.raises(ValueError, match="只支持人民币"):
            chain._require_cny(currency)


def test_new_procurement_fields_are_server_owned():
    guard = importlib.import_module("rayher_hr_payroll.oa_mutation_guard")
    for field in ("payment_plan", "source_purchase_order", "source_po_payment_plan_row", "source_payment_plan_row",
                  "price_snapshot", "contract_bank_account", "contract_seal_user", "pmc_change_version"):
        assert field in guard.SERVER_OWNED_FIELDS, field
