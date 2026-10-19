import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import importlib
from rayher_hr_payroll.procurement_workflow import (
    ProcurementWorkflowError,
    contract_copy_recipients,
    plan_contract_delivery,
)


@pytest.fixture
def oa_entry():
    return importlib.import_module("rayher_hr_payroll.api.oa_entry")


class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class Request(SimpleNamespace):
    def append(self, fieldname, values):
        row = Row(values)
        getattr(self, fieldname).append(row)
        return row


def historical_step(index, key, label, user):
    return Row(
        step_index=index,
        step_key=key,
        origin="base",
        label=label,
        mode="approve",
        approvers=json.dumps([user]),
        approved_by=json.dumps([user]),
        status="已通过",
        action_by=user,
        acted_on="2026-08-10 10:00:00",
        note="",
    )


def procurement(scope="项目采购"):
    return Request(
        doctype="OA Approval Request",
        name="PROC-CONTRACT-1",
        owner="applicant@example.com",
        request_type="采购申请",
        workflow_status="已完成",
        business_status="演示员工116待登记",
        expected_delivery_date="2026-09-10",
        procurement_scope=scope,
        purchaser_user="buyer@example.com",
        project_owner="project@example.com" if scope == "项目采购" else "",
        project_owner_name="项目主管" if scope == "项目采购" else "",
        contract_delivery_date="",
        pending_contract_delivery_date="",
        delivery_change_reason="",
        copied_to="[]",
        operation_log="[]",
        current_step_index=0,
        current_step_label="",
        steps=[
            historical_step(1, "pmc", "PMC：演示员工178", "pmc@example.com"),
            historical_step(2, "supervisor", "直属主管：演示员工132", "boss@example.com"),
            historical_step(3, "project", "项目主管：项目主管", "project@example.com"),
        ],
    )


def test_contract_plan_confirms_on_time_and_requires_late_reason():
    on_time = plan_contract_delivery("2026-09-10", "2026-09-10", "项目采购")
    assert on_time == {"contract_delivery_date": "2026-09-10", "requires_reapproval": False, "approval_roles": []}

    with pytest.raises(ProcurementWorkflowError, match="原因"):
        plan_contract_delivery("2026-09-10", "2026-09-11", "项目采购")

    project_late = plan_contract_delivery("2026-09-10", "2026-09-11", "项目采购", "供应商排产")
    non_project_late = plan_contract_delivery("2026-09-10", "2026-09-11", "非项目采购", "供应商排产")
    assert project_late["approval_roles"] == ["pmc", "project_owner"]
    assert non_project_late["approval_roles"] == ["pmc"]


def test_contract_copy_recipients_collapses_users_but_preserves_all_role_labels():
    recipients = contract_copy_recipients({
        "applicant": {"label": "申请人", "user": "same@example.com"},
        "purchaser": {"label": "采购经办人", "user": "buyer@example.com"},
        "pmc": {"label": "PMC", "user": "pmc@example.com"},
        "supervisor": {"label": "直属上级", "user": "same@example.com"},
        "project_owner": {"label": "项目主管", "user": "project@example.com"},
    })
    assert [item["user"] for item in recipients] == [
        "same@example.com", "buyer@example.com", "pmc@example.com", "project@example.com"
    ]
    assert recipients[0]["roles"] == ["申请人", "直属上级"]
    assert recipients[0]["label"] == "申请人、直属上级"


def install_endpoint(monkeypatch, doc, oa_entry):
    events = {"saved": 0, "synced": 0, "notified": 0}
    oa_entry.frappe.local.flags = SimpleNamespace(in_test=True)
    oa_entry.frappe.local.session = SimpleNamespace(user="applicant@example.com")
    monkeypatch.setattr(oa_entry, "require_request_type_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(oa_entry, "now_datetime", lambda: "2026-08-15 12:00:00")
    monkeypatch.setattr(oa_entry.invoice_service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_load_request", lambda *_args, **_kwargs: doc)
    monkeypatch.setattr(oa_entry, "_require_contract_registration_access", lambda current: None, raising=False)
    monkeypatch.setattr(oa_entry, "_save_document", lambda current: events.__setitem__("saved", events["saved"] + 1))
    monkeypatch.setattr(oa_entry, "_sync_assignments_after_save", lambda current: events.__setitem__("synced", events["synced"] + 1))
    monkeypatch.setattr(oa_entry, "_notify_copied_users", lambda current: events.__setitem__("notified", events["notified"] + 1))
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda current, authorized_expense_lines=None: {
        "business_status": current.business_status,
        "contract_delivery_date": current.contract_delivery_date,
        "pending_contract_delivery_date": current.pending_contract_delivery_date,
        "steps": list(current.steps),
    })
    return events


def test_on_time_contract_is_confirmed_immediately_and_copies_five_flow_roles(monkeypatch, oa_entry):
    doc = procurement()
    events = install_endpoint(monkeypatch, doc, oa_entry)

    result = oa_entry.register_contract_delivery(doc.name, "2026-09-09")

    assert result["business_status"] == "采购执行中"
    assert result["contract_delivery_date"] == "2026-09-09"
    assert len(result["steps"]) == 3
    copied = json.loads(doc.copied_to)
    assert [item["user"] for item in copied] == [
        "applicant@example.com", "buyer@example.com", "pmc@example.com", "boss@example.com", "project@example.com"
    ]
    assert events == {"saved": 1, "synced": 1, "notified": 1}


def test_late_contract_appends_confirmation_steps_and_preserves_history(monkeypatch, oa_entry):
    doc = procurement()
    events = install_endpoint(monkeypatch, doc, oa_entry)

    result = oa_entry.register_contract_delivery(doc.name, "2026-09-15", "供应商排产延期")

    assert result["business_status"] == "演示员工116交期待确认"
    assert result["contract_delivery_date"] == ""
    assert result["pending_contract_delivery_date"] == "2026-09-15"
    assert [row.label for row in doc.steps] == [
        "PMC：演示员工178", "直属主管：演示员工132", "项目主管：项目主管",
        "演示员工116交期确认-PMC：演示员工178", "演示员工116交期确认-项目主管：项目主管",
    ]
    assert all(row.status == "已通过" for row in doc.steps[:3])
    assert doc.current_step_index == 4
    assert events == {"saved": 1, "synced": 1, "notified": 0}

    # A later revision appends another auditable cycle instead of overwriting history.
    for row in doc.steps[3:]:
        row.status = "已通过"
    doc.workflow_status = "已完成"
    doc.business_status = "采购执行中"
    doc.contract_delivery_date = "2026-09-15"
    doc.pending_contract_delivery_date = ""
    oa_entry.register_contract_delivery(doc.name, "2026-09-20", "再次调整排产")
    assert len(doc.steps) == 7
    assert json.loads(doc.operation_log)[-1]["details"]["previous_contract_delivery_date"] == "2026-09-15"


def test_non_project_late_contract_only_adds_pmc_confirmation(monkeypatch, oa_entry):
    doc = procurement("非项目采购")
    install_endpoint(monkeypatch, doc, oa_entry)
    oa_entry.register_contract_delivery(doc.name, "2026-09-15", "供应商排产延期")
    assert [row.label for row in doc.steps[3:]] == ["演示员工116交期确认-PMC：演示员工178"]

def test_last_late_delivery_confirmation_commits_date_and_prepares_copy(monkeypatch, oa_entry):
    doc = procurement()
    install_endpoint(monkeypatch, doc, oa_entry)
    oa_entry.register_contract_delivery(doc.name, "2026-09-15", "供应商排产延期")
    final_step = doc.steps[-1]
    for row in doc.steps[-2:]:
        row.status = "已通过"
    doc.workflow_status = "已完成"
    doc.current_step_index = 0
    doc.current_step_label = ""

    assert oa_entry._finalize_contract_delivery_if_complete(doc, final_step) is True
    assert doc.contract_delivery_date == "2026-09-15"
    assert doc.pending_contract_delivery_date == ""
    assert doc.business_status == "采购执行中"
    assert len(json.loads(doc.copied_to)) == 5
    assert json.loads(doc.operation_log)[-1]["action"] == "确认演示员工116交期"

def test_late_confirmation_deduplicates_same_pmc_and_project_owner_account(monkeypatch, oa_entry):
    doc = procurement()
    doc.project_owner = "pmc@example.com"
    install_endpoint(monkeypatch, doc, oa_entry)
    oa_entry.register_contract_delivery(doc.name, "2026-09-15", "供应商排产延期")
    assert [row.label for row in doc.steps[3:]] == ["演示员工116交期确认-PMC：演示员工178"]


def test_completed_base_procurement_moves_to_pr_and_price_inquiry(oa_entry):
    doc = procurement()
    doc.workflow_status = "待审批"
    doc.business_status = "待审批"
    doc.current_step_index = 3
    current = doc.steps[-1]
    oa_entry._advance_after_step(doc, current)
    assert doc.workflow_status == "已完成"
    assert doc.business_status == "需求已批准/待询价"
