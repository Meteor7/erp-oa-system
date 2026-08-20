from __future__ import annotations

import base64
import json
import re
from datetime import date, timedelta
from decimal import Decimal

import frappe

from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
)
from rayher_hr_payroll.oa_role_resolver import resolve_role


BATCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
PREFIX = "[OA测试:{batch_id}]"
FIXED_OFFICE = "办公家具、工具及器具"
FIXED_ELECTRONIC = "电子设备、研发专用设备、仪器仪表"
FIXED_PRODUCTION = "生产设备、生产工具及器具"


class ApprovalCenterTestDataError(ValueError):
    pass


def _batch_id(value):
    result = str(value or "").strip()
    if not BATCH_PATTERN.fullmatch(result):
        raise ApprovalCenterTestDataError("测试批次编号只能包含字母、数字、下划线和连字符，且不超过48位")
    return result


def _subject(batch_id, label):
    return PREFIX.format(batch_id=batch_id) + label


def scenario_catalog(batch_id):
    batch_id = _batch_id(batch_id)
    base = [
        ("project_production_asset", REQUEST_PROCUREMENT, "项目生产设备采购", "固定资产", FIXED_PRODUCTION),
        ("project_non_fixed", REQUEST_PROCUREMENT, "项目非固定资产采购", "非固定资产", ""),
        ("nonproject_electronic_asset", REQUEST_PROCUREMENT, "非项目电子设备采购", "固定资产", FIXED_ELECTRONIC),
        ("nonproject_non_fixed", REQUEST_PROCUREMENT, "非项目常规采购", "非固定资产", ""),
        ("jd_office_asset", REQUEST_DIRECT_PURCHASE, "京东办公资产购买", "固定资产", FIXED_OFFICE),
        ("other_direct_purchase", REQUEST_DIRECT_PURCHASE, "其他渠道购买", "非固定资产", ""),
        ("full_prepayment_overdue", REQUEST_PROCUREMENT_PAYMENT, "100%预付款已付待到货", "固定资产", FIXED_PRODUCTION),
        ("partial_prepayment_paid", REQUEST_PROCUREMENT_PAYMENT, "部分预付款已付且验收通过", "非固定资产", ""),
        ("tail_payment_pending", REQUEST_PROCUREMENT_PAYMENT, "尾款待财务审核", "非固定资产", ""),
        ("post_arrival_full_payment_pending", REQUEST_PROCUREMENT_PAYMENT, "无预付款到货验收后全额付款", "固定资产", FIXED_ELECTRONIC),
    ]
    rows = []
    for key, request_type, label, asset_nature, category in base:
        rows.append({
            "batch_id": batch_id,
            "scenario_key": key,
            "request_type": request_type,
            "subject": _subject(batch_id, label),
            "asset_nature": asset_nature,
            "fixed_asset_category": category,
            "submit_through_workflow": True,
            "writes_outside_approval_center": False,
        })
    return rows


def example_prerequisites():
    return {
        "applicant": {
            "employee": "HR-EMP-TEST", "employee_name": "测试申请人",
            "user": "applicant@example.com", "department": "研发部 - TEST",
            "company": "TEST", "supervisor": "测试主管", "supervisor_user": "supervisor@example.com",
        },
        "project": {
            "name": "PROJ-TEST", "project_name": "测试项目",
            "project_owner": "project@example.com", "project_owner_name": "测试项目主管",
        },
        "supplier": "示例企业028",
        "roles": {
            "pmc": {"user": "pmc@example.com", "employee_name": "演示员工178"},
            "hr_manager": {"user": "hr@example.com", "employee_name": "人事经理"},
            "finance_auditor": {"user": "finance@example.com", "employee_name": "财务审核"},
            "finance_manager": {"user": "manager@example.com", "employee_name": "财务主管"},
            "vice_manager": {"user": "vice@example.com", "employee_name": "演示员工21"},
            "general_manager": {"user": "general@example.com", "employee_name": "演示员工29"},
            "production_asset_owner": {"user": "production@example.com", "employee_name": "生产设备负责人"},
        },
    }


def _validate_prerequisites(values):
    missing = []
    applicant = (values or {}).get("applicant") or {}
    if not applicant.get("user"):
        missing.append("申请人账号")
    if not applicant.get("supervisor_user"):
        missing.append("直属上级账号")
    project = (values or {}).get("project") or {}
    if not project.get("name") or not project.get("project_owner"):
        missing.append("所属项目及项目主管")
    if not (values or {}).get("supplier"):
        missing.append("供应商")
    roles = (values or {}).get("roles") or {}
    for key, label in (
        ("pmc", "PMC"), ("hr_manager", "人事经理"), ("finance_auditor", "财务确认付款"),
        ("finance_manager", "财务主管"), ("vice_manager", "演示员工21"), ("general_manager", "演示员工29"),
        ("production_asset_owner", "生产设备负责人"),
    ):
        if not (roles.get(key) or {}).get("user"):
            missing.append(label)
    if missing:
        raise ApprovalCenterTestDataError("缺少测试前置资料：" + "、".join(missing))


def _memory_steps(scenario, prerequisites):
    roles = prerequisites["roles"]
    applicant = prerequisites["applicant"]
    if scenario["request_type"] == REQUEST_PROCUREMENT:
        rows = [
            ("PMC审批", roles["pmc"]["user"]),
            ("直属上级审批", applicant["supervisor_user"]),
        ]
        if scenario["scenario_key"].startswith("project_"):
            rows.append(("项目主管审批", prerequisites["project"]["project_owner"]))
        if scenario["fixed_asset_category"] == FIXED_PRODUCTION:
            rows.append(("生产设备负责人审批", roles["production_asset_owner"]["user"]))
    elif scenario["request_type"] == REQUEST_DIRECT_PURCHASE:
        if scenario["scenario_key"].startswith("jd_"):
            return [{
                "label": "京东购买会签：人事经理、演示员工21",
                "mode": "all",
                "approvers": [roles["hr_manager"]["user"], roles["vice_manager"]["user"]],
            }]
        rows = [("直属上级审批", applicant["supervisor_user"])]
    else:
        rows = [
            ("财务主管审核", roles["finance_manager"]["user"]),
            ("演示员工21", roles["vice_manager"]["user"]),
            ("演示员工29", roles["general_manager"]["user"]),
            ("财务确认付款", roles["finance_auditor"]["user"]),
        ]
    return [{"label": label, "approvers": [user]} for label, user in rows]


class MemorySeedStore:
    def __init__(self, *, prerequisites=None):
        self._prerequisites = prerequisites or {}
        self.records = []
        self.writes = []

    def prerequisites(self):
        return self._prerequisites

    def existing(self, batch_id):
        return [row for row in self.records if row["batch_id"] == batch_id]

    def seed_batch(self, batch_id, scenarios, prerequisites):
        created = []
        for scenario in scenarios:
            steps = _memory_steps(scenario, prerequisites)
            row = {
                **scenario,
                "name": "OA-TEST-{0:05d}".format(len(self.records) + 1),
                "steps": steps,
                "step_labels": [step["label"] for step in steps],
                "current_approvers": list(steps[0]["approvers"]),
            }
            self.records.append(row)
            self.writes.append(row)
            created.append(row)
        return created

    def cleanup_batch(self, batch_id, dry_run):
        matches = self.existing(batch_id)
        if not dry_run:
            self.records = [row for row in self.records if row["batch_id"] != batch_id]
        return {"matched_count": len(matches), "deleted_count": 0 if dry_run else len(matches)}


class FrappeSeedStore:
    def prerequisites(self):
        roles = {}
        for role_key in (
            "pmc", "hr_manager", "finance_auditor", "finance_manager", "vice_manager",
            "general_manager", "production_asset_owner",
        ):
            snapshot = resolve_role(role_key)
            roles[role_key] = snapshot

        applicant = None
        candidates = frappe.db.sql(
            """
            select e.name, e.employee_name, e.user_id, e.department, e.company,
                   e.reports_to, s.employee_name as supervisor,
                   s.user_id as supervisor_user
            from tabEmployee e
            join tabEmployee s on s.name=e.reports_to and s.status='Active'
            join tabUser u on u.name=e.user_id and u.enabled=1
            join tabUser su on su.name=s.user_id and su.enabled=1
            where e.status='Active' and coalesce(e.user_id, '') != ''
            order by case when s.user_id in (
                'person046@staff.example.invalid', 'person060@staff.example.invalid'
            ) then 1 else 0 end, e.name
            limit 1
            """,
            as_dict=True,
        )
        if candidates:
            row = candidates[0]
            applicant = {
                "employee": row.name, "employee_name": row.employee_name,
                "user": row.user_id, "department": row.department,
                "company": row.company, "supervisor": row.supervisor,
                "supervisor_user": row.supervisor_user,
            }

        project = None
        fallback_project = None
        applicant_user = str((applicant or {}).get("user") or "").strip()
        project_fields = ["name", "project_name", "project_owner", "project_owner_name"]
        for row in frappe.get_all("Project", fields=project_fields, order_by="modified desc", limit_page_length=0):
            owner = str(row.get("project_owner") or "").strip()
            if not owner or not frappe.db.get_value("User", owner, "enabled"):
                continue
            fallback_project = fallback_project or dict(row)
            if owner != applicant_user:
                project = dict(row)
                break
        project = project or fallback_project

        supplier_master = frappe.db.get_value("Supplier", {}, "name")
        supplier = supplier_master or "OA示例企业028（仅审批中心）"
        return {
            "applicant": applicant,
            "project": project,
            "supplier": supplier,
            "supplier_master_exists": bool(supplier_master),
            "roles": roles,
        }

    def existing(self, batch_id):
        prefix = PREFIX.format(batch_id=batch_id) + "%"
        return frappe.get_all(
            "OA Approval Request",
            filters={"subject": ["like", prefix]},
            fields=["name", "request_type", "subject", "workflow_status", "current_step_label"],
            order_by="creation asc",
            limit_page_length=0,
        )

    @staticmethod
    def _lines(index):
        return [{
            "item_name": "OA审批测试物料-{0}".format(index),
            "specification": "仅用于审批中心验收",
            "quantity": 1,
            "unit": "项",
            "unit_price": 100 + index * 10,
            "remarks": "批次隔离测试数据",
        }]

    @staticmethod
    def _step_snapshot(doc):
        steps = []
        for step in list(doc.steps or []):
            approvers = json.loads(step.approvers or "[]")
            steps.append({"label": step.label, "approvers": approvers, "mode": step.mode})
        current = next((row for row in steps if row["label"] == doc.current_step_label), steps[0] if steps else None)
        return steps, list((current or {}).get("approvers") or [])

    @staticmethod
    def _approve_to_end(name):
        from rayher_hr_payroll.api.oa_entry import action_request

        for _ in range(30):
            doc = frappe.get_doc("OA Approval Request", name)
            if doc.workflow_status in {"已完成", "已付款"}:
                return
            if doc.workflow_status not in {"待审批", "待办理"}:
                raise ApprovalCenterTestDataError("{0}无法继续审批，当前状态：{1}".format(name, doc.workflow_status))
            current = next(
                (row for row in doc.steps if int(row.step_index or 0) == int(doc.current_step_index or 0)),
                None,
            )
            if not current:
                raise ApprovalCenterTestDataError("{0}缺少当前审批步骤".format(name))
            approvers = json.loads(current.approvers or "[]")
            approved = set(json.loads(current.approved_by or "[]"))
            pending = [user for user in approvers if user not in approved]
            if not pending:
                raise ApprovalCenterTestDataError("{0}当前审批节点没有待处理人".format(name))
            frappe.set_user(pending[0])
            action_request(name, "approve", "OA测试批次自动流转")
        raise ApprovalCenterTestDataError("{0}审批步骤超过安全上限".format(name))

    @staticmethod
    def _create_evidence(request_name, batch_id, document_type, index):
        from rayher_hr_payroll.business_documents import attach

        filename = "oa-test-{0}-{1}-{2}.png".format(batch_id, index, document_type)
        content = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": filename,
            "is_private": 1,
            "content": content,
        })
        file_doc.insert(ignore_permissions=True)
        attach(request_name, document_type, file_doc.name)
        return file_doc.name

    def _payload(self, scenario, prerequisites, index, sources):
        project = prerequisites["project"]
        applicant = prerequisites["applicant"]
        payload = {
            "subject": scenario["subject"],
            "reason": "审批中心隔离测试数据；批次可精确清理",
            "urgency": "一般",
            "asset_nature": scenario["asset_nature"],
            "fixed_asset_category": scenario["fixed_asset_category"],
            "business_lines": self._lines(index),
        }
        key = scenario["scenario_key"]
        future = (date.today() + timedelta(days=30)).isoformat()
        if scenario["request_type"] == REQUEST_PROCUREMENT:
            payload.update({
                "expected_delivery_date": future,
                "purchaser_user": prerequisites["roles"]["production_asset_owner"]["user"],
            })
            if key.startswith("project_"):
                payload.update({"procurement_scope": "项目采购", "project": project["name"]})
            else:
                payload.update({
                    "procurement_scope": "非项目采购",
                    "non_project_allocation_type": "部门",
                    "non_project_department": applicant["department"] or "测试部门",
                })
        elif scenario["request_type"] == REQUEST_DIRECT_PURCHASE:
            payload.update({
                "expected_delivery_date": future,
                "purchase_method": "京东购买" if key.startswith("jd_") else "其他购买",
            })
            if key.startswith("jd_"):
                payload["project"] = project["name"]
            else:
                payload.update({
                    "non_project_allocation_type": "部门",
                    "non_project_department": applicant["department"] or "测试部门",
                })
        else:
            from rayher_hr_payroll import approval_amount_ledger

            source_key = {
                "full_prepayment_overdue": "project_production_asset",
                "partial_prepayment_paid": "project_non_fixed",
                "tail_payment_pending": "project_non_fixed",
                "post_arrival_full_payment_pending": "nonproject_electronic_asset",
            }[key]
            source_name = sources[source_key]
            balance = approval_amount_ledger.source_balance(source_name)
            available = Decimal(str(balance["available_amount"]))
            amount = available
            if key == "partial_prepayment_paid":
                amount = (Decimal(str(balance["approved_amount"])) / Decimal("2")).quantize(Decimal("0.01"))
            payload["business_lines"] = [{
                "item_name": "OA审批测试付款-{0}".format(index),
                "specification": "关联采购申请付款",
                "quantity": 1,
                "unit": "笔",
                "unit_price": amount,
                "remarks": "批次隔离测试数据",
            }]
            payload.update({
                "source_request": source_name,
                "supplier": prerequisites["supplier"],
                "prepayment_percentage": 100 if key == "full_prepayment_overdue" else 50 if key == "partial_prepayment_paid" else 0,
                "expected_arrival_date": (date.today() - timedelta(days=5)).isoformat() if key == "full_prepayment_overdue" else future,
                "prepayment_risk_note": "100%预付款逾期预警与催办测试" if key == "full_prepayment_overdue" else "",
            })
        return payload

    def seed_batch(self, batch_id, scenarios, prerequisites):
        from rayher_hr_payroll.approval_center import save_draft
        from rayher_hr_payroll.api.oa_entry import (
            record_arrival,
            record_inspection,
            submit_request,
        )

        original_user = frappe.session.user
        applicant_user = prerequisites["applicant"]["user"]
        sources = {}
        payments = {}
        created = []
        try:
            for index, scenario in enumerate(scenarios, 1):
                frappe.set_user(applicant_user)
                key = scenario["scenario_key"]

                if key in {"tail_payment_pending", "post_arrival_full_payment_pending"}:
                    if key == "tail_payment_pending":
                        fulfillment_name = payments["partial_prepayment_paid"]
                    else:
                        fulfillment_name = sources["nonproject_electronic_asset"]
                    fulfillment_doc = frappe.get_doc("OA Approval Request", fulfillment_name)
                    if fulfillment_doc.arrival_status not in {"全部到货", "关闭未交数量"}:
                        self._create_evidence(fulfillment_name, batch_id, "送货单", index)
                        record_arrival(
                            fulfillment_name,
                            fulfillment_doc.ordered_quantity,
                            date.today().isoformat(),
                            "测试到货",
                        )
                        self._create_evidence(fulfillment_name, batch_id, "验收资料", index)
                        record_inspection(fulfillment_name, "通过", "测试验收通过")

                payload = self._payload(scenario, prerequisites, index, sources)
                if scenario["request_type"] == REQUEST_PROCUREMENT_PAYMENT:
                    source = frappe.get_doc("OA Approval Request", payload["source_request"])
                    purchaser = str(source.purchaser_user or "").strip()
                    if not purchaser:
                        raise ApprovalCenterTestDataError(
                            "{0}来源采购申请缺少采购经办人".format(source.name)
                        )
                    frappe.set_user(purchaser)
                doc = save_draft(scenario["request_type"], payload)

                if scenario["request_type"] == REQUEST_PROCUREMENT_PAYMENT:
                    if key in {"full_prepayment_overdue", "partial_prepayment_paid"}:
                        self._create_evidence(doc.name, batch_id, "合同", index)
                        self._create_evidence(doc.name, batch_id, "付款计划", index)
                    else:
                        self._create_evidence(doc.name, batch_id, "验收资料", index)
                        self._create_evidence(doc.name, batch_id, "发票", index)

                submit_request(doc.name)
                submitted = frappe.get_doc("OA Approval Request", doc.name)
                steps, current = self._step_snapshot(submitted)
                row = {
                    **scenario,
                    "name": doc.name,
                    "steps": steps,
                    "step_labels": [step["label"] for step in steps],
                    "current_approvers": current,
                    "workflow_status": submitted.workflow_status,
                    "payment_stage": getattr(submitted, "payment_stage", None),
                }
                created.append(row)

                if scenario["request_type"] == REQUEST_PROCUREMENT:
                    self._approve_to_end(doc.name)
                    sources[key] = doc.name
                elif key in {"full_prepayment_overdue", "partial_prepayment_paid"}:
                    self._approve_to_end(doc.name)
                    payments[key] = doc.name
            frappe.db.commit()
            return created
        except Exception:
            frappe.db.rollback()
            raise
        finally:
            frappe.set_user(original_user)

    def cleanup_batch(self, batch_id, dry_run):
        prefix = PREFIX.format(batch_id=batch_id) + "%"
        names = frappe.get_all(
            "OA Approval Request", filters={"subject": ["like", prefix]},
            pluck="name", limit_page_length=0,
        )
        documents = frappe.get_all(
            "OA Business Document", filters={"request": ["in", names]},
            fields=["name", "file"], limit_page_length=0,
        ) if names else []
        todos = frappe.get_all(
            "ToDo",
            filters={"reference_type": "OA Approval Request", "reference_name": ["in", names]},
            pluck="name", limit_page_length=0,
        ) if names else []
        ledgers = frappe.get_all(
            "OA Approval Amount Ledger",
            filters=[["OA Approval Amount Ledger", "linked_request", "in", names]],
            pluck="name", limit_page_length=0,
        ) if names else []
        batch_files = frappe.get_all(
            "File",
            filters={"file_name": ["like", "oa-test-{0}-%".format(batch_id)]},
            pluck="name",
            limit_page_length=0,
        )
        counts = {
            "matched_count": len(names),
            "document_count": len(documents),
            "todo_count": len(todos),
            "ledger_count": len(ledgers),
            "file_count": len(batch_files),
        }
        if dry_run:
            return {**counts, "deleted_count": 0}
        if not names and not batch_files:
            return {**counts, "deleted_count": 0}
        original_user = frappe.session.user
        try:
            frappe.set_user("Administrator")
            for name in todos:
                frappe.delete_doc("ToDo", name, ignore_permissions=True, force=True)
            if ledgers:
                frappe.db.delete("OA Approval Amount Ledger", {"name": ["in", ledgers]})
            if documents:
                frappe.db.delete(
                    "OA Business Document",
                    {"name": ["in", [row.name for row in documents]]},
                )
            for name in reversed(names):
                frappe.delete_doc("OA Approval Request", name, ignore_permissions=True, force=True)
            for file_name in batch_files:
                if frappe.db.exists("File", file_name):
                    frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
            frappe.db.commit()
            return {**counts, "deleted_count": len(names), "deleted_file_count": len(batch_files)}
        except Exception:
            frappe.db.rollback()
            raise
        finally:
            frappe.set_user(original_user)


def _store(store=None):
    return store or FrappeSeedStore()


def seed(batch_id, dry_run=True, *, store=None):
    batch_id = _batch_id(batch_id)
    store = _store(store)
    prerequisites = store.prerequisites()
    _validate_prerequisites(prerequisites)
    scenarios = scenario_catalog(batch_id)
    existing = list(store.existing(batch_id))
    if existing and len(existing) != len(scenarios):
        raise ApprovalCenterTestDataError(
            "批次已存在{0}条，预期{1}条；请先精确清理该批次".format(len(existing), len(scenarios))
        )
    if existing:
        return {
            "batch_id": batch_id, "dry_run": bool(dry_run), "scenario_count": len(scenarios),
            "created_count": 0, "existing_count": len(existing), "records": existing,
        }
    if dry_run:
        return {
            "batch_id": batch_id, "dry_run": True, "scenario_count": len(scenarios),
            "created_count": 0, "existing_count": 0, "records": scenarios,
            "prerequisites": prerequisites,
        }
    records = store.seed_batch(batch_id, scenarios, prerequisites)
    return {
        "batch_id": batch_id, "dry_run": False, "scenario_count": len(scenarios),
        "created_count": len(records), "existing_count": 0, "records": records,
    }


def cleanup(batch_id, dry_run=True, *, store=None):
    batch_id = _batch_id(batch_id)
    result = _store(store).cleanup_batch(batch_id, bool(dry_run))
    return {"batch_id": batch_id, "dry_run": bool(dry_run), **result}
