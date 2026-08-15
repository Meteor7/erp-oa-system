import re

import pytest

from rayher_hr_payroll.maintenance import approval_center_test_data as seed_data


def test_seed_catalog_has_ten_real_workflow_scenarios():
    rows = seed_data.scenario_catalog("BATCH-20260815")
    assert len(rows) == 10
    assert {row["request_type"] for row in rows} == {"采购申请", "购买申请", "采购付款"}
    assert sum(row["request_type"] == "采购付款" for row in rows) == 4
    assert all(row["subject"].startswith("[OA测试:BATCH-20260815]") for row in rows)
    assert all(row["submit_through_workflow"] is True for row in rows)
    assert all(row["writes_outside_approval_center"] is False for row in rows)


@pytest.mark.parametrize("batch_id", ["", "../bad", "有空格 batch", "x" * 49])
def test_batch_id_is_strictly_bounded(batch_id):
    with pytest.raises(seed_data.ApprovalCenterTestDataError):
        seed_data.scenario_catalog(batch_id)


def test_dry_run_reports_prerequisites_and_performs_no_writes():
    store = seed_data.MemorySeedStore(prerequisites=seed_data.example_prerequisites())
    result = seed_data.seed("DRY-20260815", dry_run=True, store=store)
    assert result["dry_run"] is True
    assert result["scenario_count"] == 10
    assert result["existing_count"] == 0
    assert store.writes == []


def test_missing_prerequisite_refuses_before_any_write():
    prerequisites = seed_data.example_prerequisites()
    prerequisites["project"] = None
    store = seed_data.MemorySeedStore(prerequisites=prerequisites)
    with pytest.raises(seed_data.ApprovalCenterTestDataError, match="所属项目"):
        seed_data.seed("MISS-20260815", dry_run=False, store=store)
    assert store.writes == []


def test_seed_is_idempotent_and_records_generated_steps_and_current_approvers():
    store = seed_data.MemorySeedStore(prerequisites=seed_data.example_prerequisites())
    first = seed_data.seed("LIVE-20260815", dry_run=False, store=store)
    second = seed_data.seed("LIVE-20260815", dry_run=False, store=store)

    assert first["created_count"] == 10
    assert second["created_count"] == 0
    assert second["existing_count"] == 10
    assert len(store.writes) == 10
    assert all(row["steps"] for row in first["records"])
    assert all(row["current_approvers"] for row in first["records"])
    procurement = next(row for row in first["records"] if row["scenario_key"] == "project_production_asset")
    assert procurement["step_labels"][:3] == ["PMC审批", "直属上级审批", "项目主管审批"]
    assert procurement["step_labels"][-1] == "生产设备负责人审批"
    payment = next(row for row in first["records"] if row["request_type"] == "采购付款")
    assert payment["step_labels"] == ["财务审核", "演示员工21审批", "演示员工29审批", "财务付款"]


def test_cleanup_is_dry_by_default_and_exactly_scoped_to_batch():
    store = seed_data.MemorySeedStore(prerequisites=seed_data.example_prerequisites())
    seed_data.seed("KEEP-20260815", dry_run=False, store=store)
    seed_data.seed("DROP-20260815", dry_run=False, store=store)

    preview = seed_data.cleanup("DROP-20260815", store=store)
    assert preview["dry_run"] is True
    assert preview["matched_count"] == 10
    assert len(store.records) == 20

    deleted = seed_data.cleanup("DROP-20260815", dry_run=False, store=store)
    assert deleted["deleted_count"] == 10
    assert len(store.records) == 10
    assert all(row["batch_id"] == "KEEP-20260815" for row in store.records)
