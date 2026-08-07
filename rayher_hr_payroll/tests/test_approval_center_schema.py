import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCTYPE_ROOT = ROOT / "rayher_hr_payroll" / "rayher_hr_payroll" / "doctype"


def meta(slug):
    path = DOCTYPE_ROOT / slug / f"{slug}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fields(slug):
    return {row["fieldname"]: row for row in meta(slug)["fields"]}


def test_request_amount_source_and_line_contracts():
    request = meta("oa_approval_request")
    result = fields("oa_approval_request")
    assert request["allow_rename"] == 0
    assert result["workflow_status"]["default"] == "草稿"
    assert result["amount"]["fieldtype"] == "Currency"
    assert result["currency"]["default"] == "CNY"
    assert result["currency"]["options"] == "CNY"
    assert result["approved_amount"]["read_only"] == 1
    assert result["approved_amount"]["options"] == "currency"
    assert result["source_request"]["options"] == "OA Approval Request"
    assert result["approved_amount_snapshot"]["read_only"] == 1
    assert result["source_modified"]["read_only"] == 1
    assert result["business_lines"]["options"] == "OA Purchase Request Line"
    assert result["copied_to"]["fieldtype"] == "Small Text"
    assert result["copied_to"]["read_only"] == 1

    line = fields("oa_purchase_request_line")
    assert line["quantity"]["fieldtype"] == "Float"
    assert line["unit_price"]["fieldtype"] == "Currency"
    assert line["amount"]["read_only"] == 1


def test_ledger_is_immutable_and_idempotent_by_schema():
    ledger_meta = meta("oa_approval_amount_ledger")
    result = fields("oa_approval_amount_ledger")
    assert ledger_meta["allow_rename"] == 0
    assert result["source_request"]["options"] == "OA Approval Request"
    assert result["linked_request"]["options"] == "OA Approval Request"
    assert result["reserved_delta"]["fieldtype"] == "Currency"
    assert result["paid_delta"]["fieldtype"] == "Currency"
    assert result["idempotency_key"]["unique"] == 1
    assert result["actor"]["options"] == "User"
    assert ledger_meta["permissions"]
    assert all(
        not permission.get(action)
        for permission in ledger_meta["permissions"]
        for action in ("create", "write", "delete")
    )


def test_business_documents_are_private_versioned_references():
    document_meta = meta("oa_business_document")
    result = fields("oa_business_document")
    assert document_meta["allow_rename"] == 0
    assert result["request"]["options"] == "OA Approval Request"
    assert result["file"]["fieldtype"] == "Attach"
    assert result["file_sha256"]["read_only"] == 1
    assert result["version_no"]["read_only"] == 1
    assert result["supersedes"]["options"] == "OA Business Document"
    assert {row["role"] for row in document_meta["permissions"]} >= {
        "System Manager", "Employee", "Department Manager", "Accounts User", "HR User", "HR Manager",
        "Rayher Business Executive",
    }
    assert all(
        not permission.get(action)
        for permission in document_meta["permissions"]
        for action in ("create", "write", "delete")
    )



def test_foundation_patch_only_reloads_schema_and_never_guesses_history(monkeypatch):
    from rayher_hr_payroll.patches.v1_0 import add_approval_center_safe_foundation as migration

    calls = []

    class FrappeStub:
        @staticmethod
        def reload_doc(module, kind, slug):
            calls.append((module, kind, slug))

    monkeypatch.setitem(__import__("sys").modules, "frappe", FrappeStub())
    migration.execute()
    migration.execute()
    assert calls == [
        ("rayher_hr_payroll", "doctype", "oa_approval_request"),
        ("rayher_hr_payroll", "doctype", "oa_purchase_request_line"),
        ("rayher_hr_payroll", "doctype", "oa_approval_amount_ledger"),
        ("rayher_hr_payroll", "doctype", "oa_business_document"),
    ] * 2
