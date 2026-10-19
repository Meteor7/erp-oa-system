"""Build linked procurement-chain data for manual acceptance testing."""
from __future__ import annotations

import base64 
import json
import secrets
from datetime import date, timedelta

import frappe
from rayher_hr_payroll.procurement_mutation_guard import procurement_action
from frappe.utils.password import update_password
from frappe.utils.file_manager import save_file

from rayher_hr_payroll.approval_center import save_draft
from rayher_hr_payroll.api.oa_entry import action_request, submit_request
from rayher_hr_payroll.api.procurement_chain import (
    approve_price_approval, close_po, confirm_po, create_price_approval, create_pr,
    push_po_payment_request, record_po_inspection, record_po_receipt,
    review_po_contract, save_po_contract_information, save_supplier_comparison,
    seal_po_contract, select_supplier_comparison, submit_price_approval,
    update_price_approval_summary,
)
from rayher_hr_payroll.oa_role_resolver import resolve_role
from rayher_hr_payroll.maintenance.test_data_guard import require_test_data_site

PREFIX = "[OA正式链路验收:20260907]"
LEGACY_PREFIXES = (
    "[OA链路验收:%", "[OA测试:%", "[OA正式链路验收:%", "采购节点验收-%",
    "E2E验收-%", "流程演示%", "采购全流程验收%",
)
APPLICANT = "HR-EMP-90013"
PROJECTS = ("RD03", "RD02")
MATERIAL_CODES = (
    "1.ELC.1.1.01.003", "1.ELC.1.1.03.001", "1.ELC.1.1.03.002",
    "1.ELC.1.1.99.001", "1.ELC.1.1.99.002",
)
SUPPLIERS = ("示例企业030有限公司", "示例企业031有限公司")
TEST_PASSWORD = secrets.token_urlsafe(24)
PRICE_APPROVER_USER = "person046@staff.example.invalid"
SEAL_USER = "person033@staff.example.invalid"


def _text(value):
    return str(value or "").strip()


def _delete_many(doctype, names):
    deleted = 0
    for name in sorted(set(names or []), reverse=True):
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            deleted += 1
    return deleted


def _source_names():
    rows = frappe.get_all("OA Approval Request", fields=["name", "subject"], limit_page_length=0)
    return {
        row.name for row in rows
        if any(_text(row.subject).startswith(p[:-1] if p.endswith("%") else p) for p in LEGACY_PREFIXES)
    }


def _orphan_progress_names():
    return {
        row.name for row in frappe.get_all(
            "OA Material Progress", fields=["name", "source_request"], limit_page_length=0
        ) if not row.source_request or not frappe.db.exists("OA Approval Request", row.source_request)
    }


@procurement_action
def cleanup(dry_run=True):
    """Delete old acceptance chains and material-progress rows with no source OA."""
    if not dry_run:
        require_test_data_site()
    sources = _source_names()
    prs = set(frappe.get_all(
        "OA Procurement Request Line", filters={"source_request": ["in", list(sources)]},
        pluck="parent", limit_page_length=0,
    )) if sources else set()
    approvals = set(frappe.get_all(
        "OA Price Approval Line", filters={"source_request": ["in", list(sources)]},
        pluck="parent", limit_page_length=0,
    )) if sources else set()
    if prs:
        approvals.update(frappe.get_all(
            "OA Price Approval Line", filters={"source_pr": ["in", list(prs)]},
            pluck="parent", limit_page_length=0,
        ))
    pos = set(frappe.get_all(
        "OA Purchase Order Line", filters={"source_request": ["in", list(sources)]},
        pluck="parent", limit_page_length=0,
    )) if sources else set()
    if prs:
        pos.update(frappe.get_all(
            "OA Purchase Order Line", filters={"source_pr": ["in", list(prs)]},
            pluck="parent", limit_page_length=0,
        ))
    payments = set(frappe.get_all(
        "OA Approval Request",
        filters={"request_type": "采购付款", "source_purchase_order": ["in", list(pos)]},
        pluck="name", limit_page_length=0,
    )) if pos else set()
    requests = sources | payments
    progress = set(frappe.get_all(
        "OA Material Progress", filters={"source_request": ["in", list(sources)]},
        pluck="name", limit_page_length=0,
    )) if sources else set()
    orphan_progress = _orphan_progress_names()
    progress.update(orphan_progress)
    quotes = set(frappe.get_all(
        "OA Price Approval Quote", filters={"price_approval": ["in", list(approvals)]},
        pluck="name", limit_page_length=0,
    )) if approvals else set()
    references = requests | approvals | pos
    todos = set(frappe.get_all(
        "ToDo", filters={
            "reference_type": ["in", ["OA Approval Request", "OA Price Approval", "OA Purchase Order"]],
            "reference_name": ["in", list(references)],
        }, pluck="name", limit_page_length=0,
    )) if references else set()
    documents = frappe.get_all(
        "OA Business Document", filters={"request": ["in", list(requests)]},
        fields=["name", "file"], limit_page_length=0,
    ) if requests else []
    files = {row.file for row in documents if row.file}
    fulfillment = frappe.get_all(
        "OA PO Fulfillment Record", filters={"purchase_order": ["in", list(pos)]},
        fields=["name", "evidence_file"], limit_page_length=0,
    ) if pos and frappe.db.exists("DocType", "OA PO Fulfillment Record") else []
    files.update(row.evidence_file for row in fulfillment if row.evidence_file)
    counts = {
        "requests": len(requests), "prs": len(prs), "price_approvals": len(approvals),
        "quotes": len(quotes), "pos": len(pos), "progress": len(progress),
        "orphan_progress": len(orphan_progress), "todos": len(todos), "documents": len(documents),
        "fulfillment_records": len(fulfillment),
    }
    if dry_run:
        return {"dry_run": True, **counts, "deleted_count": 0}
    original = frappe.session.user
    try:
        frappe.set_user("Administrator")
        if references | progress:
            frappe.db.delete("Notification Log", {"document_name": ["in", list(references | progress)]})
        _delete_many("ToDo", todos)
        if documents:
            frappe.db.delete("OA Business Document", {"name": ["in", [row.name for row in documents]]})
        if fulfillment:
            frappe.db.delete("OA PO Fulfillment Record", {"name": ["in", [row.name for row in fulfillment]]})
        _delete_many("File", files)
        if requests:
            frappe.db.delete("OA Approval Amount Ledger", {"linked_request": ["in", list(requests)]})
        _delete_many("OA Price Approval Quote", quotes)
        _delete_many("OA Purchase Order", pos)
        _delete_many("OA Price Approval", approvals)
        _delete_many("OA Procurement Request", prs)
        _delete_many("OA Material Progress", progress)
        _delete_many("OA Approval Request", requests)
        frappe.db.commit()
        return {"dry_run": False, **counts, "deleted_count": sum(
            value for key, value in counts.items() if key != "orphan_progress"
        )}
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.set_user(original)


def _material_line(code, quantity, marker):
    material = frappe.get_doc("OA Procurement Material", code)
    return {
        "material_code": material.material_code, "category_code": material.category_code,
        "category_path": getattr(material, "category_path", None) or "",
        "item_name": material.material_name, "specification": material.specification,
        "product_desc": material.product_desc or "", "brand": material.brand or "通用",
        "material_attr": getattr(material, "material_attr", None) or "外购",
        "quantity": quantity, "unit": material.unit or "个", "unit_price": 0,
        "remarks": f"正式采购全链路手工验收 · {marker}",
    }


def _materials(seed_index, count=4):
    return [
        _material_line(
            MATERIAL_CODES[(seed_index + offset) % len(MATERIAL_CODES)],
            3 + ((seed_index + offset * 2) % 7),
            f"批次{seed_index:03d}-物料{offset + 1}",
        ) for offset in range(count)
    ]


def _advance_request(name, completed_steps=None):
    completed = 0
    for _ in range(30):
        doc = frappe.get_doc("OA Approval Request", name)
        if doc.workflow_status in {"已完成", "已付款"}:
            return doc
        if completed_steps is not None and completed >= completed_steps:
            return doc
        step = next((row for row in doc.steps if int(row.step_index or 0) == int(doc.current_step_index or 0)), None)
        if not step:
            frappe.throw(f"{name} 缺少当前审批步骤")
        approvers = json.loads(step.approvers or "[]")
        approved = set(json.loads(step.approved_by or "[]"))
        for user in [item for item in approvers if item not in approved]:
            frappe.set_user(user)
            action_request(name, "approve", "正式链路验收推进")
        completed += 1
    frappe.throw(f"{name} 审批步骤超过安全上限")


def _create_oa(stage, slot, part, seed_index, completed_steps=None):
    applicant = frappe.db.get_value("Employee", APPLICANT, "user_id")
    purchaser = resolve_role("procurement_manager")["user"]
    frappe.set_user(applicant)
    payload = {
        "subject": f"{PREFIX}{stage}-{slot:02d}-来源{part}",
        "reason": f"正式采购全链路手工验收：{stage}；后续单据全部由此前置 OA 推进生成",
        "urgency": "一般", "asset_nature": "非固定资产",
        "procurement_scope": "项目采购", "project": PROJECTS[(seed_index + part) % len(PROJECTS)],
        "expected_delivery_date": (date.today() + timedelta(days=25 + seed_index)).isoformat(),
        "purchaser_user": purchaser, "business_lines": _materials(seed_index, 4),
    }
    doc = save_draft("采购申请", payload)
    submit_request(doc.name)
    return _advance_request(doc.name, completed_steps)


def _create_prs(sources):
    frappe.set_user(resolve_role("pmc")["user"])
    result = []
    for source in sources:
        lines = [
            {"source_request": source.name, "source_line": row.name, "quantity": float(row.quantity)}
            for row in source.business_lines
        ]
        result.append(create_pr(json.dumps(lines, ensure_ascii=False)))
    return result


def _create_price(prs):
    frappe.set_user(resolve_role("procurement_manager")["user"])
    selected = [
        {"source_pr": pr["name"], "source_pr_line": row["name"], "quantity": row["quantity"]}
        for pr in prs for row in pr["lines"]
    ]
    return create_price_approval(json.dumps(selected, ensure_ascii=False))


def _prepare_price(approval, seed_index, submit=False, plan_kind="full"):
    frappe.set_user(resolve_role("procurement_manager")["user"])
    for supplier_index, supplier in enumerate(SUPPLIERS):
        prices = [
            {
                "price_line": row["name"],
                "unit_price": 180 + seed_index * 3 + line_index * 27 + supplier_index * 11,
                "delivery_date": (date.today() + timedelta(days=15 + line_index + supplier_index)).isoformat(),
            } for line_index, row in enumerate(approval["lines"])
        ]
        supplier_total = sum(
            float(item["unit_price"]) * float(row["quantity"])
            for item, row in zip(prices, approval["lines"])
        )
        if plan_kind == "split":
            payment_plan = [
                {"installment_name": "第1期预付款", "payment_stage": "预付款", "percentage": 30,
                 "amount": round(supplier_total * 0.30, 2),
                 "planned_date": date.today().isoformat(),
                 "trigger_condition": "演示员工116生效后", "invoice_requirement": "付款前提供"},
                {"installment_name": "第2期尾款", "payment_stage": "尾款", "percentage": 70,
                 "amount": round(supplier_total - round(supplier_total * 0.30, 2), 2),
                 "planned_date": (date.today() + timedelta(days=45)).isoformat(),
                 "trigger_condition": "全部到货并验收通过", "invoice_requirement": "付款前提供"},
            ]
        else:
            payment_plan = [{
                "installment_name": "验收合格后全额付款", "payment_stage": "到货后全额付款",
                "percentage": 100, "amount": supplier_total,
                "planned_date": (date.today() + timedelta(days=45)).isoformat(),
                "trigger_condition": "全部到货并验收通过", "invoice_requirement": "无需发票",
            }]
        save_supplier_comparison(
            approval["name"], supplier, json.dumps(prices, ensure_ascii=False),
            payment_method="验收合格后付款", currency="CNY", tax_rate=13,
            contract_entity="示例企业032有限公司", is_recommended=1 if supplier_index == 0 else 0,
            note="正式链路验收报价",
            payment_plan=json.dumps(payment_plan, ensure_ascii=False),
        )
    update_price_approval_summary(
        approval["name"], "同一价格审批单从两张真实 PR 选择多项物料，综合价格、交期和付款条件进行比价。"
    )
    return submit_price_approval(approval["name"]) if submit else approval


def _approve_price_to_po(approval):
    frappe.set_user(PRICE_APPROVER_USER)
    select_supplier_comparison(approval["name"], SUPPLIERS[0])
    return approve_price_approval(approval["name"], "正式链路验收通过")["po_names"][0]


def _ensure_payment_plan(po_name):
    po = frappe.get_doc("OA Purchase Order", po_name)
    if not po.payment_plan:
        frappe.throw(f"{po_name} 未从成交供应商方案继承付款计划")
    if abs(sum(float(row.percentage or 0) for row in po.payment_plan) - 100) > 0.0001:
        frappe.throw(f"{po_name} 付款计划比例不等于 100%")
    if abs(sum(float(row.amount or 0) for row in po.payment_plan) - float(po.total_amount or 0)) > 0.01:
        frappe.throw(f"{po_name} 付款计划金额不等于 PO 总额")
    return po


def _confirm(po_name):
    frappe.set_user(resolve_role("procurement_manager")["user"])
    return confirm_po(po_name)


def _save_contract(po_name):
    frappe.set_user(resolve_role("procurement_manager")["user"])
    po = frappe.get_doc("OA Purchase Order", po_name)
    return save_po_contract_information(
        po_name, SEAL_USER,
        contract_delivery_date=str(po.contract_delivery_date or (date.today() + timedelta(days=30))),
        supplier_legal_name=po.supplier, credit_code="91440300TEST202609",
        supplier_address="示例市示例区演示路2号", contract_contact="验收联系人 0755-00000000",
        contract_bank_name="测试银行深圳分行", contract_bank_account="TEST202609070001",
        contract_template="标准采购演示员工116",
    )


def _review_contract(po_name):
    frappe.set_user(resolve_role("procurement_manager")["user"])
    return review_po_contract(po_name, "正式链路验收演示员工116复核")


def _seal_contract(po_name):
    # 用印人由岗位决定（save_po_contract_information 写在 PO 上），按 PO 上记的人用印，账号改名、换人演示员工177受影响。
    frappe.set_user(frappe.db.get_value("OA Purchase Order", po_name, "contract_seal_user") or SEAL_USER)
    return seal_po_contract(po_name, "正式链路验收电子用印")


def _evidence_file(po_name, kind):
    content = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=") 
    return save_file(f"{po_name}-{kind}.png", content, None, None, is_private=1) 


def _receive_all(po_name):
    frappe.set_user(resolve_role("production_asset_owner")["user"])
    po = frappe.get_doc("OA Purchase Order", po_name)
    evidence = _evidence_file(po_name, "delivery")
    return record_po_receipt(po_name, json.dumps([
        {"line": row.name, "quantity": float(row.quantity)} for row in po.lines
    ], ensure_ascii=False), arrival_date=date.today().isoformat(), file_ref=evidence.name)


def _inspect_all(po_name):
    # 验收和到货一样只能由生产主管登记（procurement_chain._require_production_receipt）。
    frappe.set_user(resolve_role("production_asset_owner")["user"])
    po = frappe.get_doc("OA Purchase Order", po_name)
    evidence = _evidence_file(po_name, "inspection")
    return record_po_inspection(po_name, json.dumps([
        {"line": row.name, "status": "已通过"} for row in po.lines
    ], ensure_ascii=False), inspection_date=date.today().isoformat(), file_ref=evidence.name)


def _push_payment(po_name):
    frappe.set_user(resolve_role("procurement_manager")["user"])
    po = frappe.get_doc("OA Purchase Order", po_name)
    return push_po_payment_request(po_name, po.payment_plan[0].name)["payment_request"]


def _assert_paid_po_synced(po_name):
    """Fail when the production payment callback did not update the PO."""
    po = frappe.get_doc("OA Purchase Order", po_name)
    paid = sum(float(row.paid_amount or 0) for row in po.payment_plan)
    if abs(paid - float(po.paid_amount or 0)) > 0.01 or abs(paid - float(po.total_amount or 0)) > 0.01:
        frappe.throw(f"{po_name} 付款审批完成后未自动汇总 PO 付款金额")
    if po.payment_status != "已付款":
        frappe.throw(f"{po_name} 付款审批完成后未自动更新为已付款")


def _downstream_chain(stage, slot, seed_index, target, payment_steps=None):
    sources = [_create_oa(stage, slot, part, seed_index + part, None) for part in (1, 2)]
    prs = _create_prs(sources)
    record = {"oa": [row.name for row in sources], "pr": [row["name"] for row in prs]}
    if target == "pr":
        return record
    approval = _create_price(prs)
    record["price_approval"] = approval["name"]
    if target == "price_draft":
        return record
    # Slot 1 exercises a real 30/70 plan.  The closed node stays full-payment
    # so the seed itself proves the close guard rather than bypassing it.
    plan_kind = "split" if slot == 1 and stage != "20 全流程已关闭" else "full"
    approval = _prepare_price(approval, seed_index, submit=True, plan_kind=plan_kind)
    if target == "price_pending":
        return record
    po_name = _approve_price_to_po(approval)
    record["po"] = po_name
    _ensure_payment_plan(po_name)
    if target == "po_draft":
        return record
    _confirm(po_name)
    if target == "contract_info":
        return record
    _save_contract(po_name)
    if target == "contract_review":
        return record
    _review_contract(po_name)
    if target == "seal":
        return record
    _seal_contract(po_name)
    if target == "production":
        return record
    _receive_all(po_name)
    if target == "inspection":
        return record
    _inspect_all(po_name)
    if target == "payment_ready":
        return record
    payment_name = _push_payment(po_name)
    record["payment_request"] = payment_name
    if target == "payment":
        _advance_request(payment_name, payment_steps)
        return record
    _advance_request(payment_name, None)
    _assert_paid_po_synced(po_name)
    frappe.set_user(resolve_role("procurement_manager")["user"])
    close_po(po_name)
    return record


def _reset_node_passwords(request_names):
    users = {
        frappe.db.get_value("Employee", APPLICANT, "user_id"), resolve_role("pmc")["user"],
        resolve_role("procurement_manager")["user"], resolve_role("production_asset_owner")["user"], SEAL_USER,
    }
    users.update(frappe.get_all(
        "OA Approval Step", filters={"parent": ["in", list(request_names)]},
        pluck="approvers", limit_page_length=0,
    ))
    expanded = set()
    for value in users:
        if not value:
            continue
        expanded.update(json.loads(value)) if isinstance(value, str) and value.lstrip().startswith("[") else expanded.add(value)
    accounts = []
    for user in sorted({_text(value).lower() for value in expanded if _text(value)}):
        if not frappe.db.exists("User", {"name": user, "enabled": 1}):
            frappe.throw(f"验收节点账号不存在或未启用：{user}")
        update_password(user, TEST_PASSWORD, logout_all_sessions=True)
        accounts.append({
            "name": frappe.db.get_value("User", user, "full_name") or user,
            "account": user, "password": TEST_PASSWORD,
        })
    frappe.db.commit()
    return accounts


def _audit_references(source_names):
    errors = []
    for row in frappe.get_all(
        "OA Procurement Request Line", filters={"source_request": ["in", list(source_names)]},
        fields=["parent", "name", "source_request", "source_line"], limit_page_length=0,
    ):
        if not frappe.db.exists("OA Approval Request", row.source_request):
            errors.append(f"{row.parent}/{row.name} 缺少来源 OA")
        if not frappe.db.exists("OA Purchase Request Line", row.source_line):
            errors.append(f"{row.parent}/{row.name} 缺少来源 OA 明细")
    for row in frappe.get_all(
        "OA Price Approval Line", filters={"source_request": ["in", list(source_names)]},
        fields=["parent", "name", "source_pr", "source_pr_line"], limit_page_length=0,
    ):
        if not frappe.db.exists("OA Procurement Request", row.source_pr):
            errors.append(f"{row.parent}/{row.name} 缺少来源 PR")
        if not frappe.db.exists("OA Procurement Request Line", row.source_pr_line):
            errors.append(f"{row.parent}/{row.name} 缺少来源 PR 明细")
    for row in frappe.get_all(
        "OA Purchase Order Line", filters={"source_request": ["in", list(source_names)]},
        fields=["parent", "name", "source_price_approval", "source_pr", "source_request"],
        limit_page_length=0,
    ):
        if not frappe.db.exists("OA Price Approval", row.source_price_approval):
            errors.append(f"{row.parent}/{row.name} 缺少来源价格审批")
        if not frappe.db.exists("OA Procurement Request", row.source_pr):
            errors.append(f"{row.parent}/{row.name} 缺少来源 PR")
        if not frappe.db.exists("OA Approval Request", row.source_request):
            errors.append(f"{row.parent}/{row.name} 缺少来源 OA")
    po_names = set(frappe.get_all(
        "OA Purchase Order Line", filters={"source_request": ["in", list(source_names)]},
        pluck="parent", limit_page_length=0,
    ))
    for po_name in po_names:
        po = frappe.get_doc("OA Purchase Order", po_name)
        if not po.payment_plan:
            errors.append(f"{po_name} 缺少成交供应商付款计划")
        elif abs(sum(float(row.percentage or 0) for row in po.payment_plan) - 100) > 0.0001:
            errors.append(f"{po_name} 付款计划比例不等于 100%")
        elif abs(sum(float(row.amount or 0) for row in po.payment_plan) - float(po.total_amount or 0)) > 0.01:
            errors.append(f"{po_name} 付款计划金额不等于 PO 总额")
        if po.status in {"到货验收中", "付款中", "已关闭"}:
            record_types = set(frappe.get_all(
                "OA PO Fulfillment Record", filters={"purchase_order": po_name},
                pluck="record_type", limit_page_length=0,
            ))
            if any(float(line.received_quantity or 0) > 0 for line in po.lines) and "到货" not in record_types:
                errors.append(f"{po_name} 有到货数量但缺少到货资料流水")
            if any(_text(line.inspection_status) == "已通过" for line in po.lines) and "验收" not in record_types:
                errors.append(f"{po_name} 已验收但缺少验收资料流水")
    return {"ok": not errors, "errors": errors}


def _blocked(results, case, action, expected):
    try:
        action()
    except Exception as exc:
        message = _text(exc)
        if expected not in message:
            raise
        results.append({"case": case, "result": "通过", "observed": message})
        return
    frappe.throw(f"条件验收失败：{case} 未被系统拦截")


@procurement_action
def run_payment_condition_acceptance():
    """Exercise payment gates against a real seeded 30/70 PO.

    This intentionally changes one seeded scenario. Run ``seed`` afterwards
    to restore the manual acceptance nodes.
    """
    original = frappe.session.user
    results = []
    try:
        candidates = frappe.get_all(
            "OA Procurement Payment Plan Row",
            filters={"installment_name": "第1期预付款", "status": "待审批"},
            fields=["parent"], order_by="creation desc", limit_page_length=100,
        )
        po = next((frappe.get_doc("OA Purchase Order", row.parent) for row in candidates
                   if frappe.db.get_value("OA Purchase Order", row.parent, "status") == "供应商制作中"), None)
        if not po:
            frappe.throw("没有找到可执行条件验收的30/70测试 PO，请先运行 seed")
        prepayment = next(row for row in po.payment_plan if row.installment_name == "第1期预付款")
        balance = next(row for row in po.payment_plan if row.installment_name == "第2期尾款")

        frappe.set_user(resolve_role("procurement_manager")["user"])
        prepayment_request = push_po_payment_request(po.name, prepayment.name)["payment_request"]
        results.append({"case": "未到货时30%预付款可提交审批", "result": "通过", "observed": prepayment_request})
        _blocked(results, "未到货时70%尾款不可提交", lambda: push_po_payment_request(po.name, balance.name), "全部到货")
        _blocked(results, "30%预付款最终付款前缺少发票必须拦截",
                 lambda: _advance_request(prepayment_request, None), "发票")
        from rayher_hr_payroll.api.oa_entry import attach_approval_business_document
        frappe.set_user("Administrator")
        prepayment_invoice = _evidence_file(po.name, "prepayment-invoice")
        attach_approval_business_document(prepayment_request, "发票", prepayment_invoice.name)
        _advance_request(prepayment_request, None)
        po.reload()
        if abs(float(po.paid_amount or 0) - float(prepayment.amount or 0)) > 0.01 or po.payment_status != "部分付款":
            frappe.throw("条件验收失败：30%预付款完成后未正确回写 PO 部分付款")
        results.append({"case": "30%实际付款后PO累计金额和部分付款状态正确", "result": "通过",
                        "observed": f"paid={po.paid_amount}; status={po.payment_status}"})

        frappe.set_user(resolve_role("production_asset_owner")["user"])
        po.reload()
        partial = [{"line": row.name, "quantity": max(float(row.quantity) / 2, 0.01)} for row in po.lines]
        _blocked(results, "没有到货资料不可登记到货", lambda: record_po_receipt(
            po.name, json.dumps(partial, ensure_ascii=False), arrival_date=date.today().isoformat()
        ), "上传到货资料")
        delivery_one = _evidence_file(po.name, "partial-delivery")
        record_po_receipt(po.name, json.dumps(partial, ensure_ascii=False),
                          arrival_date=date.today().isoformat(), file_ref=delivery_one.name)
        frappe.set_user(resolve_role("procurement_manager")["user"])
        _blocked(results, "部分到货时70%尾款不可提交", lambda: push_po_payment_request(po.name, balance.name), "全部到货")

        frappe.set_user(resolve_role("production_asset_owner")["user"])
        po.reload()
        remaining = [{"line": row.name, "quantity": float(row.quantity) - float(row.received_quantity or 0)} for row in po.lines]
        delivery_two = _evidence_file(po.name, "full-delivery")
        record_po_receipt(po.name, json.dumps(remaining, ensure_ascii=False),
                          arrival_date=date.today().isoformat(), file_ref=delivery_two.name)
        frappe.set_user(resolve_role("procurement_manager")["user"])
        _blocked(results, "全部到货但未验收时70%尾款不可提交", lambda: push_po_payment_request(po.name, balance.name), "验收通过")

        po.reload()
        inspections = [{"line": row.name, "status": "已通过"} for row in po.lines]
        _blocked(results, "没有验收资料不可登记验收", lambda: record_po_inspection(
            po.name, json.dumps(inspections, ensure_ascii=False), inspection_date=date.today().isoformat()
        ), "上传验收资料")
        inspection = _evidence_file(po.name, "inspection")
        record_po_inspection(po.name, json.dumps(inspections, ensure_ascii=False),
                             inspection_date=date.today().isoformat(), file_ref=inspection.name)
        balance_request = push_po_payment_request(po.name, balance.name)["payment_request"]
        results.append({"case": "全部到货且验收资料齐全后70%尾款可提交", "result": "通过", "observed": balance_request})
        _blocked(results, "同一期付款不可重复下推", lambda: push_po_payment_request(po.name, balance.name), "不可下推")
        _blocked(results, "未完成全部付款不可关闭 PO", lambda: close_po(po.name), "尚未完成付款")
        _blocked(results, "70%尾款最终付款前缺少发票必须拦截",
                 lambda: _advance_request(balance_request, None), "发票")
        frappe.set_user("Administrator")
        balance_invoice = _evidence_file(po.name, "balance-invoice")
        attach_approval_business_document(balance_request, "发票", balance_invoice.name)
        _advance_request(balance_request, None)
        po.reload()
        if abs(float(po.paid_amount or 0) - float(po.total_amount or 0)) > 0.01 or po.payment_status != "已付款":
            frappe.throw("条件验收失败：70%尾款完成后未正确汇总 PO 全额付款")
        results.append({"case": "70%实际付款后PO累计金额等于总额", "result": "通过",
                        "observed": f"paid={po.paid_amount}; total={po.total_amount}"})
        frappe.set_user(resolve_role("procurement_manager")["user"])
        close_po(po.name)
        if frappe.db.get_value("OA Purchase Order", po.name, "status") != "已关闭":
            frappe.throw("条件验收失败：全部履约付款后 PO 未关闭")
        results.append({"case": "30/70两期完成后PO允许关闭", "result": "通过", "observed": "已关闭"})

        rejected_rows = frappe.get_all(
            "OA Procurement Payment Plan Row",
            filters={"installment_name": "第2期尾款", "status": "待审批"},
            fields=["parent", "name"], order_by="creation desc", limit_page_length=100,
        )
        rejected_po = next((frappe.get_doc("OA Purchase Order", row.parent) for row in rejected_rows
                            if row.parent != po.name and frappe.db.get_value(
                                "OA Purchase Order", row.parent, "status") == "到货验收中"), None)
        if not rejected_po:
            frappe.throw("没有找到可执行验收不合格分支的30/70测试 PO")
        rejected_balance = next(row for row in rejected_po.payment_plan if row.installment_name == "第2期尾款")
        rejected_inspections = [
            {"line": line.name, "status": "不合格" if index == 0 else "已通过"}
            for index, line in enumerate(rejected_po.lines)
        ]
        rejected_evidence = _evidence_file(rejected_po.name, "rejected-inspection")
        record_po_inspection(
            rejected_po.name, json.dumps(rejected_inspections, ensure_ascii=False),
            inspection_date=date.today().isoformat(), file_ref=rejected_evidence.name,
            note="首项物料尺寸不符合演示员工116要求",
        )
        _blocked(results, "任一物料验收不合格时70%尾款不可提交",
                 lambda: push_po_payment_request(rejected_po.name, rejected_balance.name), "验收通过")
        return {"ok": True, "po": po.name, "cases": results}
    finally:
        frappe.set_user(original)


@procurement_action
def seed(reset_passwords=True):
    """Rebuild two real, forward-generated chains at every manual test node."""
    require_test_data_site()
    cleanup_result = cleanup(dry_run=False)
    original = frappe.session.user
    nodes, requests, sources = {}, set(), set()
    try:
        early_nodes = (
            ("01 OA-直属主管审批", 0), ("02 OA-PMC审批", 1),
            ("03 OA-需求终审", 2), ("04 待PMC提PR", None),
        )
        seed_index = 1
        for stage, completed_steps in early_nodes:
            records = []
            for slot in (1, 2):
                doc = _create_oa(stage, slot, 1, seed_index, completed_steps)
                records.append({"oa": [doc.name]})
                requests.add(doc.name); sources.add(doc.name); seed_index += 1
            nodes[stage] = records
        downstream_nodes = (
            ("05 PR待生成价格审批", "pr", None),
            ("06 价格审批草稿", "price_draft", None),
            ("07 价格审批待演示员工37审批", "price_pending", None),
            ("08 PO草稿待采购确认", "po_draft", None),
            ("09 PO演示员工116资料待补充", "contract_info", None),
            ("10 PO演示员工116草稿待复核", "contract_review", None),
            ("11 PO待电子用印", "seal", None),
            ("12 供应商制作中", "production", None),
            ("13 到货待验收", "inspection", None),
            ("14 验收通过待下推付款", "payment_ready", None),
            ("15 采购付款-演示员工37审批", "payment", 0),
            ("16 采购付款-演示员工135审批", "payment", 1),
            ("17 采购付款-财务主管审批", "payment", 2),
            ("18 采购付款-演示员工110审批", "payment", 3),
            ("19 采购付款-总经理确认", "payment", 4),
            ("20 全流程已关闭", "closed", None),
        )
        for stage, target, payment_steps in downstream_nodes:
            records = []
            for slot in (1, 2):
                record = _downstream_chain(stage, slot, seed_index, target, payment_steps)
                records.append(record)
                requests.update(record.get("oa", [])); sources.update(record.get("oa", []))
                if record.get("payment_request"):
                    requests.add(record["payment_request"])
                seed_index += 3
            nodes[stage] = records
        audit = _audit_references(sources)
        if not audit["ok"]:
            frappe.throw("验收数据引用审计失败：" + "；".join(audit["errors"][:20]))
        if any(len(records) < 2 for records in nodes.values()):
            frappe.throw("至少一个验收节点没有生成两条数据")
        accounts = _reset_node_passwords(requests) if reset_passwords else []
        frappe.db.commit()
        return {
            "cleanup": cleanup_result, "node_count": len(nodes), "nodes": nodes,
            "accounts": accounts, "audit": audit,
        }
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.set_user(original)
