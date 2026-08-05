import base64
import hashlib
from decimal import Decimal

import frappe

from rayher_hr_payroll.api._guards import require_rd_access
from rayher_hr_payroll.social_insurance_import import (
    can_activate_rows,
    canonical_period,
    mask_identity,
    match_employee,
    parse_social_workbook,
    reconcile_row,
    resolve_employee_bases,
    select_workbench_batches,
    summarize_rows,
)

ROLES = ("System Manager", "HR User", "HR Manager")
SUPPORTED_COMPANIES = {"Rayher": "示例总部", "示例研发中心": "示例研发中心"}
EXCEL_FIELDS = (
    "contribution_base", "employee_pension", "company_pension",
    "employee_medical", "company_medical", "company_maternity",
    "company_injury", "employee_unemployment", "company_unemployment",
    "local_pension", "employee_total", "company_total", "receivable_total",
)
CALCULATED_MAP = {
    key: f"calculated_{key}" for key in (
        "employee_pension", "company_pension", "employee_medical",
        "company_medical", "company_maternity", "company_injury",
        "employee_unemployment", "company_unemployment", "local_pension",
        "employee_total", "company_total", "receivable_total",
    )
}
ROW_FIELDS = [
    "name", "batch", "company", "period", "source_row", "excel_name",
    "masked_identity", "employee", "employee_name", *EXCEL_FIELDS,
    *CALCULATED_MAP.values(), "difference_total", "original_match_status",
    "status", "difference_reasons", "remark", "confirmed_by", "confirmed_at",
    "reference_base", "base_source", "household_source", "household_classification",
    "policy_version", "ignored_by", "ignored_at",
]


def _company(value, allow_all=False):
    value = str(value or "").strip()
    if allow_all and value in ("", "all"):
        return None
    if value not in SUPPORTED_COMPANIES or not frappe.db.exists("Company", value):
        frappe.throw(frappe._("请选择有效所属公司。"))
    return value


def _decode_content(content_base64):
    text = str(content_base64 or "")
    if "," in text and text.lstrip().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text, validate=True)
    except Exception:
        frappe.throw(frappe._("Excel文件内容无效。"))


def _employees(period):
    employees = frappe.get_all(
        "Employee",
        filters={"company": ["in", list(SUPPORTED_COMPANIES)], "status": "Active"},
        fields=[
            "name", "employee_name", "company", "id_card_number_cn",
            "household_registration", "default_social_insurance_base",
        ],
    )
    period_rows = frappe.get_all(
        "Employee Social Insurance",
        filters={"period": canonical_period(period)},
        fields=["employee", "contribution_base"],
    )
    return resolve_employee_bases(employees, period_rows, canonical_period(period))


def _row_values(batch, row, result):
    values = {
        "doctype": "Social Insurance Import Row",
        "batch": batch.name,
        "company": result.get("company"),
        "period": batch.period,
        "source_row": row["row_number"] + 3,
        "row_key": f"{batch.name}|{row['row_number']}",
        "excel_name": row["excel_name"],
        "identity_number": row["identity_number"],
        "masked_identity": mask_identity(row["identity_number"]),
        "employee": result.get("employee"),
        "employee_name": result.get("employee_name"),
        "difference_total": result.get("difference_total", 0),
        "original_match_status": result["original_match_status"],
        "status": result["status"],
        "difference_reasons": result.get("difference_reasons"),
        "reference_base": result.get("reference_base", 0),
        "base_source": result.get("base_source"),
        "household_source": result.get("household_source"),
        "household_classification": result.get("household_classification"),
        "policy_version": result.get("policy_version"),
    }
    for field in EXCEL_FIELDS:
        values[field] = row.get(field, 0)
    for source, target in CALCULATED_MAP.items():
        values[target] = (result.get("calculated") or {}).get(source, 0)
    return values


def _rows_for_batches(batch_names):
    if not batch_names:
        return []
    return frappe.get_all(
        "Social Insurance Import Row",
        filters={"batch": ["in", batch_names]},
        fields=ROW_FIELDS,
        order_by="company, source_row",
    )


def _refresh_batch_summary(batch_name):
    rows = frappe.get_all(
        "Social Insurance Import Row",
        filters={"batch": batch_name},
        fields=["status", "original_match_status", "employee", "employee_total", "company_total", "receivable_total"],
    )
    summary = summarize_rows(rows)
    frappe.db.set_value("Social Insurance Import Batch", batch_name, {
        "parsed_rows": summary["total_rows"],
        "matched_rows": summary["matched_rows"],
        "pending_rows": summary["pending_rows"],
        "unlinked_rows": summary["unlinked_rows"],
        "employee_total": summary["employee_total"],
        "company_total": summary["company_total"],
        "receivable_total": summary["receivable_total"],
    }, update_modified=False)
    return rows

def _display_batch(row):
    item = dict(row)
    item["company_display"] = SUPPORTED_COMPANIES.get(item.get("company"), "自动识别（混合公司）")
    return item


@frappe.whitelist()
def get_company_options():
    require_rd_access(ROLES)
    return [
        {"value": name, "label": label}
        for name, label in SUPPORTED_COMPANIES.items()
        if frappe.db.exists("Company", name)
    ]


@frappe.whitelist()
def get_employee_options(company=None):
    require_rd_access(ROLES)
    company = _company(company, allow_all=True)
    filters = {"status": "Active"}
    filters["company"] = company if company else ["in", list(SUPPORTED_COMPANIES)]
    return frappe.get_all(
        "Employee",
        filters=filters,
        fields=["name", "employee_name", "company"],
        order_by="employee_name",
    )

@frappe.whitelist()
def get_social_workbench(period, company=None, batch=None):
    require_rd_access(ROLES)
    period = canonical_period(period)
    company = _company(company, allow_all=True)
    batches = frappe.get_all(
        "Social Insurance Import Batch",
        filters={"period": period},
        fields=[
            "name", "company", "period", "source_file", "source_filename", "status",
            "is_current", "uploaded_by", "uploaded_at", "total_rows", "parsed_rows",
            "matched_rows", "pending_rows", "unlinked_rows", "employee_total",
            "company_total", "receivable_total", "cancel_remark", "canceled_by", "canceled_at",
        ],
        order_by="uploaded_at desc",
    )
    selected = select_workbench_batches(batches, batch)
    all_rows = _rows_for_batches(selected)
    rows = [row for row in all_rows if not company or row.get("company") == company]
    dashboard = summarize_rows(rows)
    company_summaries = []
    for name, label in SUPPORTED_COMPANIES.items():
        company_rows = [row for row in all_rows if row.get("company") == name]
        summary = summarize_rows(company_rows)
        summary.update({"company": name, "company_display": label})
        company_summaries.append(summary)
    pending = [row for row in rows if row.get("status") == "Pending"]
    details = [row for row in rows if row.get("status") in ("Matched", "Confirmed Difference")]
    return {
        "period": period,
        "company": company or "all",
        "dashboard": dashboard,
        "company_summaries": company_summaries,
        "batches": [_display_batch(row) for row in batches],
        "pending": pending,
        "details": details,
    }


@frappe.whitelist(methods=["POST"])
def upload_social_workbook(filename, content_base64, period=None, company=None):
    require_rd_access(ROLES)
    filename = str(filename or "").strip()
    if not filename.lower().endswith(".xlsx"):
        frappe.throw(frappe._("仅支持.xlsx格式社保明细。"))
    content = _decode_content(content_base64)
    try:
        parsed = parse_social_workbook(content)
    except ValueError as exc:
        frappe.throw(str(exc))
    period = parsed[0]["period_start"]
    digest = hashlib.sha256(content).hexdigest()
    batch_key = f"{period}|{digest}"
    if frappe.db.exists("Social Insurance Import Batch", {"period": period, "file_hash": digest}):
        frappe.throw(frappe._("该期间和文件已上传，请勿重复导入。"))

    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "is_private": 1,
        "content": content,
    }).insert(ignore_permissions=True)
    batch = frappe.get_doc({
        "doctype": "Social Insurance Import Batch",
        "period": period,
        "source_file": file_doc.file_url,
        "source_filename": filename,
        "file_hash": digest,
        "batch_key": batch_key,
        "status": "Parsing",
        "is_current": 0,
        "uploaded_by": frappe.session.user,
        "uploaded_at": frappe.utils.now(),
        "total_rows": len(parsed),
    }).insert(ignore_permissions=True)

    employees = _employees(period)
    seen = set()
    stored = []
    for row in parsed:
        identity = row["identity_number"]
        employee, association_reason = match_employee(row, employees)
        result = reconcile_row(row, employee, association_reason=association_reason)
        if identity and identity in seen:
            result["status"] = "Pending"
            result["original_match_status"] = "Pending"
            reasons = [result.get("difference_reasons"), "同一Excel内员工重复"]
            result["difference_reasons"] = "；".join(reason for reason in reasons if reason)
        if identity:
            seen.add(identity)
        doc = frappe.get_doc(_row_values(batch, row, result)).insert(ignore_permissions=True)
        stored.append(doc.as_dict())

    summary = summarize_rows(stored)
    batch.update({
        "status": "Pending Activation",
        "parsed_rows": summary["total_rows"],
        "matched_rows": summary["matched_rows"],
        "pending_rows": summary["pending_rows"],
        "unlinked_rows": summary["unlinked_rows"],
        "employee_total": summary["employee_total"],
        "company_total": summary["company_total"],
        "receivable_total": summary["receivable_total"],
    })
    batch.save(ignore_permissions=True)
    frappe.db.commit()
    return get_social_workbench(period, None, batch.name)


@frappe.whitelist(methods=["POST"])
def activate_social_batch(batch):
    require_rd_access(ROLES)
    doc = frappe.get_doc("Social Insurance Import Batch", batch)
    if doc.status != "Pending Activation":
        frappe.throw(frappe._("只有待确认导入批次可以生效。"))
    current_rows = frappe.get_all(
        "Social Insurance Import Row",
        filters={"batch": doc.name},
        fields=["status", "employee"],
    )
    if not can_activate_rows(current_rows):
        frappe.throw(frappe._("请先处理全部待确认社保明细，再确认导入。"))
    frappe.db.set_value(
        "Social Insurance Import Batch",
        {"period": doc.period, "is_current": 1},
        {"is_current": 0, "status": "Historical"},
        update_modified=False,
    )
    doc.is_current = 1
    doc.status = "Current"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return get_social_workbench(doc.period, None)


@frappe.whitelist(methods=["POST"])
def confirm_social_row(row, employee=None, remark=""):
    require_rd_access(ROLES)
    doc = frappe.get_doc("Social Insurance Import Row", row)
    remark = str(remark or "").strip()
    if not remark:
        frappe.throw(frappe._("确认差异前必须填写备注。"))
    employee = employee or doc.employee
    batch_doc = frappe.get_doc("Social Insurance Import Batch", doc.batch)
    if batch_doc.status != "Pending Activation":
        frappe.throw(frappe._("只能处理待确认导入批次的明细。"))
    employee_row = next((item for item in _employees(doc.period) if item.get("name") == employee), None) if employee else None
    if not employee_row or employee_row.get("company") not in SUPPORTED_COMPANIES:
        frappe.throw(frappe._("请选择示例总部或示例研发中心的在职员工。"))
    duplicate = frappe.db.exists(
        "Social Insurance Import Row",
        {"batch": doc.batch, "employee": employee_row.get("name"), "name": ["!=", doc.name]},
    )
    if duplicate:
        frappe.throw(frappe._("该员工已存在于当前导入批次。"))
    source = {
        "row_number": max(int(doc.source_row or 3) - 3, 0),
        "excel_name": doc.excel_name,
        "identity_number": doc.identity_number,
        "period_start": doc.period,
        "period_end": doc.period,
    }
    for field in EXCEL_FIELDS:
        source[field] = doc.get(field) or 0
    identity_matches = str(employee_row.get("id_card_number_cn") or "").strip().replace(" ", "").upper() == str(doc.identity_number or "").strip().replace(" ", "").upper()
    result = reconcile_row(
        source,
        employee_row,
        association_reason="" if identity_matches else "人工关联员工，证件号码不一致",
    )
    doc.employee = employee_row.get("name")
    doc.employee_name = employee_row.get("employee_name")
    doc.company = employee_row.get("company")
    for source_field, target in CALCULATED_MAP.items():
        doc.set(target, (result.get("calculated") or {}).get(source_field, 0))
    doc.difference_total = result.get("difference_total", 0)
    doc.difference_reasons = result.get("difference_reasons")
    doc.reference_base = result.get("reference_base", 0)
    doc.base_source = result.get("base_source")
    doc.household_source = result.get("household_source")
    doc.household_classification = result.get("household_classification")
    doc.policy_version = result.get("policy_version")
    doc.remark = remark
    doc.status = "Confirmed Difference"
    doc.confirmed_by = frappe.session.user
    doc.confirmed_at = frappe.utils.now()
    doc.save(ignore_permissions=True)
    _refresh_batch_summary(doc.batch)
    frappe.db.commit()
    return get_social_workbench(doc.period, None, doc.batch)

@frappe.whitelist(methods=["POST"])
def ignore_social_row(row, remark=""):
    require_rd_access(ROLES)
    doc = frappe.get_doc("Social Insurance Import Row", row)
    remark = str(remark or "").strip()
    if not remark:
        frappe.throw(frappe._("忽略明细前必须填写原因。"))
    if doc.status != "Pending":
        frappe.throw(frappe._("只有待确认明细可以忽略。"))
    batch_doc = frappe.get_doc("Social Insurance Import Batch", doc.batch)
    if batch_doc.status != "Pending Activation":
        frappe.throw(frappe._("只能处理待确认导入批次的明细。"))
    doc.status = "Ignored"
    doc.remark = remark
    doc.ignored_by = frappe.session.user
    doc.ignored_at = frappe.utils.now()
    doc.save(ignore_permissions=True)
    _refresh_batch_summary(doc.batch)
    frappe.db.commit()
    return get_social_workbench(doc.period, None, doc.batch)


@frappe.whitelist(methods=["POST"])
def cancel_social_batch(batch, remark=""):
    require_rd_access(ROLES)
    doc = frappe.get_doc("Social Insurance Import Batch", batch)
    remark = str(remark or "").strip()
    if not remark:
        frappe.throw(frappe._("取消批次前必须填写原因。"))
    if doc.status != "Pending Activation":
        frappe.throw(frappe._("只有待确认导入批次可以取消。"))
    doc.status = "Canceled"
    doc.is_current = 0
    doc.cancel_remark = remark
    doc.canceled_by = frappe.session.user
    doc.canceled_at = frappe.utils.now()
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return get_social_workbench(doc.period, None)


@frappe.whitelist(methods=["POST"])
def reconcile_pending_batch(batch):
    require_rd_access(ROLES)
    batch_doc = frappe.get_doc("Social Insurance Import Batch", batch)
    if batch_doc.status != "Pending Activation":
        frappe.throw(frappe._("只有待确认导入批次可以重新核对。"))
    employees = _employees(batch_doc.period)
    rows = frappe.get_all(
        "Social Insurance Import Row",
        filters={"batch": batch_doc.name},
        fields=["name", "source_row", "excel_name", "identity_number", "status", *EXCEL_FIELDS],
        order_by="source_row",
    )
    for stored in rows:
        if stored.get("status") in ("Confirmed Difference", "Ignored"):
            continue
        source = {
            "row_number": max(int(stored.get("source_row") or 3) - 3, 0),
            "excel_name": stored.get("excel_name"),
            "identity_number": stored.get("identity_number"),
            "period_start": batch_doc.period,
            "period_end": batch_doc.period,
        }
        for field in EXCEL_FIELDS:
            source[field] = stored.get(field) or 0
        employee, association_reason = match_employee(source, employees)
        result = reconcile_row(source, employee, association_reason=association_reason)
        row_doc = frappe.get_doc("Social Insurance Import Row", stored.get("name"))
        row_doc.employee = result.get("employee")
        row_doc.employee_name = result.get("employee_name")
        row_doc.company = result.get("company")
        row_doc.reference_base = result.get("reference_base", 0)
        row_doc.base_source = result.get("base_source")
        row_doc.household_source = result.get("household_source")
        row_doc.household_classification = result.get("household_classification")
        row_doc.policy_version = result.get("policy_version")
        row_doc.status = result.get("status")
        row_doc.original_match_status = result.get("original_match_status")
        row_doc.difference_total = result.get("difference_total", 0)
        row_doc.difference_reasons = result.get("difference_reasons")
        for source_field, target in CALCULATED_MAP.items():
            row_doc.set(target, (result.get("calculated") or {}).get(source_field, 0))
        row_doc.save(ignore_permissions=True)
    _refresh_batch_summary(batch_doc.name)
    frappe.db.commit()
    return get_social_workbench(batch_doc.period, None, batch_doc.name)
