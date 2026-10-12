"""项目负责人换人：这个项目名下的采购申请 / 购买申请跟着换成现在的负责人（决定 2026-10-12）。"""
from types import SimpleNamespace

from rayher_hr_payroll import project_controls as pc


def doc(owner, name="演示员工132", before_owner="person038@tests-x.example.invalid", has_before=True):
    before = SimpleNamespace(project_owner=before_owner) if has_before else None
    return SimpleNamespace(name="RD02", project_owner=owner, project_owner_name=name, get_doc_before_save=lambda: before)


def test_changing_the_owner_moves_the_applications_of_that_project(monkeypatch):
    seen = []
    monkeypatch.setattr(pc.frappe, "db", SimpleNamespace(sql=lambda query, args=None: seen.append((query, args))), raising=False)
    assert pc.sync_request_project_owner(doc("person036@tests-x.example.invalid")) == 1
    query, args = seen[0]
    assert "UPDATE `tabOA Approval Request`" in query and "project = %(project)s" in query and "request_type IN %(types)s" in query
    assert args == {"owner": "person036@tests-x.example.invalid", "name": "演示员工132", "project": "RD02", "types": ("采购申请", "购买申请")}
    # 申请本身的审批节点、状态不动：只更新项目负责人两个字段
    assert "workflow_status" not in query and "steps" not in query


def test_nothing_happens_when_the_owner_did_not_change_or_the_project_is_new(monkeypatch):
    monkeypatch.setattr(pc.frappe, "db", SimpleNamespace(sql=lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该更新"))), raising=False)
    assert pc.sync_request_project_owner(doc("person038@tests-x.example.invalid")) == 0
    assert pc.sync_request_project_owner(doc("person036@tests-x.example.invalid", has_before=False)) == 0


def test_clearing_the_owner_clears_it_on_the_applications(monkeypatch):
    seen = []
    monkeypatch.setattr(pc.frappe, "db", SimpleNamespace(sql=lambda query, args=None: seen.append(args)), raising=False)
    pc.sync_request_project_owner(doc("", name=""))
    assert seen[0]["owner"] is None and seen[0]["name"] is None


def test_the_project_hook_is_registered():
    from rayher_hr_payroll import hooks

    assert hooks.doc_events["Project"]["on_update"] == "rayher_hr_payroll.project_controls.sync_request_project_owner"
