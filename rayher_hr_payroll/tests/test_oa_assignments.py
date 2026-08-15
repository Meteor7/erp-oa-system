import json
from types import SimpleNamespace

from rayher_hr_payroll.oa_assignments import close_request_assignments, sync_current_assignments


class MemoryAssignmentStore:
    def __init__(self):
        self.rows = []
        self.created = 0

    def list_open(self, reference_type, reference_name):
        return [row for row in self.rows if row["reference_type"] == reference_type and row["reference_name"] == reference_name and row["status"] == "Open"]

    def create(self, *, reference_type, reference_name, allocated_to, description):
        self.created += 1
        row = {
            "name": f"TODO-{self.created}",
            "reference_type": reference_type,
            "reference_name": reference_name,
            "allocated_to": allocated_to,
            "description": description,
            "status": "Open",
        }
        self.rows.append(row)
        return row

    def close(self, name):
        next(row for row in self.rows if row["name"] == name)["status"] = "Closed"


def step(index, key, approvers, *, status="待审批", approved_by=None, mode="approve"):
    return SimpleNamespace(
        step_index=index,
        step_key=key,
        label=f"节点{index}",
        approvers=json.dumps(approvers),
        approved_by=json.dumps(approved_by or []),
        status=status,
        mode=mode,
    )


def request(*steps):
    return SimpleNamespace(
        doctype="OA Approval Request",
        name="OA-REQ-1",
        workflow_status="待审批",
        current_step_index=1,
        current_step_label="节点1",
        steps=list(steps),
    )


def open_users(store):
    return sorted(row["allocated_to"] for row in store.rows if row["status"] == "Open")


def test_sync_creates_one_assignment_per_current_approver_and_is_idempotent():
    store = MemoryAssignmentStore()
    doc = request(step(1, "pmc", ["pmc@example.com", "backup@example.com"], mode="all"))

    sync_current_assignments(doc, store=store)
    sync_current_assignments(doc, store=store)

    assert open_users(store) == ["backup@example.com", "pmc@example.com"]
    assert store.created == 2
    assert all("oa-assignment:OA-REQ-1:pmc" in row["description"] for row in store.rows)


def test_sync_closes_completed_approver_and_reassigns_on_advance_and_targeted_rejection():
    store = MemoryAssignmentStore()
    first = step(1, "pmc", ["pmc@example.com", "backup@example.com"], mode="all")
    second = step(2, "supervisor", ["boss@example.com"], status="待流转")
    doc = request(first, second)
    sync_current_assignments(doc, store=store)

    first.approved_by = json.dumps(["pmc@example.com"])
    sync_current_assignments(doc, store=store)
    assert open_users(store) == ["backup@example.com"]

    first.status = "已通过"
    second.status = "待审批"
    doc.current_step_index = 2
    doc.current_step_label = "节点2"
    sync_current_assignments(doc, store=store)
    assert open_users(store) == ["boss@example.com"]

    first.status = "待审批"
    first.approved_by = "[]"
    second.status = "待流转"
    doc.current_step_index = 1
    doc.current_step_label = "节点1"
    sync_current_assignments(doc, store=store)
    assert open_users(store) == ["backup@example.com", "pmc@example.com"]
    assert store.created == 5


def test_completion_draft_and_explicit_close_leave_no_open_assignments():
    store = MemoryAssignmentStore()
    doc = request(step(1, "pmc", ["pmc@example.com"]))
    sync_current_assignments(doc, store=store)

    doc.workflow_status = "已完成"
    sync_current_assignments(doc, store=store)
    assert open_users(store) == []

    doc.workflow_status = "待审批"
    sync_current_assignments(doc, store=store)
    assert open_users(store) == ["pmc@example.com"]
    close_request_assignments(doc, store=store)
    assert open_users(store) == []
