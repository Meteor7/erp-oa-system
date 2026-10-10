"""公积金汇缴明细导入：上传 Excel → 认人并按档案复算 → 处理差异 → 确认生效（写入各人的月度公积金记录，薪酬直接读取）。

流程和社保导入一样（批次 / 明细 / 待确认 / 生效），这里多一步反向检查：档案里有基数、本月申报表里却没有的人，
也会作为"申报表里没有"的待确认行列出来。
"""
import hashlib

import frappe
from rayher_hr_payroll.api._guards import require_hr_sensitive_access, require_rd_access
from rayher_hr_payroll.api.social_insurance_import_entry import SUPPORTED_COMPANIES, _company, _decode_content
from rayher_hr_payroll.hr_contributions import housing_fund_amounts
from rayher_hr_payroll.housing_fund_import import (
    DEFAULT_COMPANY_RATE,
    DEFAULT_EMPLOYEE_RATE,
    can_activate_rows,
    canonical_period,
    mask_identity,
    match_employee,
    missing_from_excel,
    parse_housing_workbook,
    rates_from_amounts,
    reconcile_fund_row,
    resolve_fund_employees,
    select_workbench_batches,
    summarize_fund_rows,
)
from rayher_hr_payroll.housing_import_mutation_guard import housing_import_action

ROLES = ("System Manager", "HR User", "HR Manager")
BATCH = "Housing Fund Import Batch"
ROW = "Housing Fund Import Row"
IMPORT_REMARK = "公积金导入批次"
MISSING_REASON = "本月申报表里没有这个人"
CATCHUP_PREFIX = "需补缴："   # 前端对“申报表里没有”的两个答复之一（另一个是“无需缴纳：”），见 contributionView.js 的 drawerOptions
ROW_FIELDS = [
    "name", "batch", "company", "period", "row_type", "source_row", "excel_name", "masked_identity", "employee", "employee_name",
    "contribution_base", "employee_amount", "company_amount", "receivable_total",
    "calculated_employee_amount", "calculated_company_amount", "calculated_receivable_total", "difference_total",
    "original_match_status", "status", "difference_reasons", "remark", "confirmed_by", "confirmed_at",
    "reference_base", "base_source", "reference_employee_rate", "reference_company_rate", "ignored_by", "ignored_at",
]
BATCH_FIELDS = [
    "name", "company", "period", "source_file", "source_filename", "status", "is_current", "uploaded_by", "uploaded_at",
    "total_rows", "parsed_rows", "matched_rows", "pending_rows", "unlinked_rows", "missing_rows", "employee_total",
    "company_total", "receivable_total", "cancel_remark", "canceled_by", "canceled_at",
]


def _employees(period):
    period = canonical_period(period)
    employees = frappe.get_all(
        "Employee",
        filters={"company": ["in", list(SUPPORTED_COMPANIES)], "status": "Active"},
        fields=["name", "employee_name", "company", "id_card_number_cn", "default_housing_fund_base"],
    )
    records = frappe.get_all(
        "Employee Housing Fund", filters={"period": period},
        fields=["employee", "contribution_base", "employee_rate", "company_rate"],
    )
    return resolve_fund_employees(employees, records, period)


def _calculated_values(result):
    calculated = result.get("calculated") or {}
    employee_amount, company_amount = calculated.get("employee_amount", 0), calculated.get("company_amount", 0)
    return {
        "calculated_employee_amount": employee_amount,
        "calculated_company_amount": company_amount,
        "calculated_receivable_total": employee_amount + company_amount,
    }


def _row_values(batch, row, result):
    return {
        "doctype": ROW,
        "batch": batch.name,
        "company": result.get("company"),
        "period": batch.period,
        "row_type": "excel",
        "source_row": row["source_row"],
        "row_key": f"{batch.name}|{row['row_number']}",
        "excel_name": row["excel_name"],
        "identity_number": row["identity_number"],
        "masked_identity": mask_identity(row["identity_number"]),
        "employee": result.get("employee"),
        "employee_name": result.get("employee_name"),
        "contribution_base": row["contribution_base"],
        "employee_amount": row["employee_amount"],
        "company_amount": row["company_amount"],
        "receivable_total": row["employee_amount"] + row["company_amount"],
        "difference_total": result.get("difference_total", 0),
        "original_match_status": result["original_match_status"],
        "status": result["status"],
        "difference_reasons": result.get("difference_reasons"),
        "reference_base": result.get("reference_base", 0),
        "base_source": result.get("base_source"),
        "reference_employee_rate": result.get("reference_employee_rate", 0),
        "reference_company_rate": result.get("reference_company_rate", 0),
        **_calculated_values(result),
    }


def _missing_row_values(batch, employee):
    amounts = housing_fund_amounts(employee["housing_fund_base"], employee["employee_rate"], employee["company_rate"])
    total = amounts["employee_amount"] + amounts["company_amount"]
    return {
        "doctype": ROW,
        "batch": batch.name,
        "company": employee.get("company"),
        "period": batch.period,
        "row_type": "missing",
        "source_row": 0,
        "row_key": f"{batch.name}|missing|{employee['name']}",
        "excel_name": employee.get("employee_name"),
        "employee": employee["name"],
        "employee_name": employee.get("employee_name"),
        "difference_total": -total,
        "original_match_status": "Pending",
        "status": "Pending",
        "difference_reasons": MISSING_REASON,
        "reference_base": employee["housing_fund_base"],
        "base_source": employee.get("housing_base_source"),
        "reference_employee_rate": employee["employee_rate"],
        "reference_company_rate": employee["company_rate"],
        "calculated_employee_amount": amounts["employee_amount"],
        "calculated_company_amount": amounts["company_amount"],
        "calculated_receivable_total": total,
    }


def _batch_rows(batch_names):
    if not batch_names:
        return []
    return frappe.get_all(ROW, filters={"batch": ["in", batch_names]}, fields=ROW_FIELDS, order_by="company, row_type, source_row")


def _refresh_batch_summary(batch_name):
    rows = frappe.get_all(
        ROW, filters={"batch": batch_name},
        fields=["status", "original_match_status", "employee", "row_type", "employee_amount", "company_amount"],
    )
    summary = summarize_fund_rows(rows)
    frappe.db.set_value(BATCH, batch_name, {
        "parsed_rows": summary["total_rows"], "matched_rows": summary["matched_rows"],
        "pending_rows": summary["pending_rows"], "unlinked_rows": summary["unlinked_rows"],
        "missing_rows": summary["missing_rows"], "employee_total": summary["employee_total"],
        "company_total": summary["company_total"], "receivable_total": summary["receivable_total"],
    }, update_modified=False)
    return summary


def _display_batch(row):
    item = dict(row)
    item["company_display"] = SUPPORTED_COMPANIES.get(item.get("company"), "自动识别（混合公司）")
    return item


@frappe.whitelist()
def get_fund_workbench(period, company=None, batch=None):
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    period = canonical_period(period)
    company = _company(company, allow_all=True)
    batches = frappe.get_all(BATCH, filters={"period": period}, fields=BATCH_FIELDS, order_by="uploaded_at desc")
    selected = select_workbench_batches(batches, batch)
    all_rows = _batch_rows(selected)
    rows = [row for row in all_rows if not company or row.get("company") == company]
    company_summaries = []
    for name, label in SUPPORTED_COMPANIES.items():
        summary = summarize_fund_rows([row for row in all_rows if row.get("company") == name])
        summary.update({"company": name, "company_display": label})
        company_summaries.append(summary)
    return {
        "period": period,
        "company": company or "all",
        "dashboard": summarize_fund_rows(rows),
        "company_summaries": company_summaries,
        "batches": [_display_batch(row) for row in batches],
        "pending": [row for row in rows if row.get("status") == "Pending"],
        "details": [row for row in rows if row.get("status") in ("Matched", "Confirmed Difference") and row.get("row_type") != "missing"],
        # 已经人工处理过的（确认纳入 / 忽略），页面的"已处理"里要看得到，包括被忽略的。
        "handled": [row for row in rows if row.get("status") in ("Confirmed Difference", "Ignored")],
        "default_rates": {"employee": float(DEFAULT_EMPLOYEE_RATE), "company": float(DEFAULT_COMPANY_RATE)},
    }


@frappe.whitelist(methods=["POST"])
@housing_import_action
def upload_fund_workbook(filename, content_base64, period=None):
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    filename = str(filename or "").strip()
    if not filename.lower().endswith(".xlsx"):
        frappe.throw(frappe._("仅支持.xlsx格式公积金明细。"))
    content = _decode_content(content_base64)
    try:
        parsed = parse_housing_workbook(content, period)
    except ValueError as exc:
        frappe.throw(str(exc))
    period = parsed[0]["period"]
    digest = hashlib.sha256(content).hexdigest()
    if frappe.db.exists(BATCH, {"period": period, "file_hash": digest}):
        frappe.throw(frappe._("该期间和文件已上传，请勿重复导入。"))

    file_doc = frappe.get_doc({"doctype": "File", "file_name": filename, "is_private": 1, "content": content}).insert(ignore_permissions=True)
    batch = frappe.get_doc({
        "doctype": BATCH, "period": period, "source_file": file_doc.file_url, "source_filename": filename,
        "file_hash": digest, "batch_key": f"{period}|{digest}", "status": "Parsing", "is_current": 0,
        "uploaded_by": frappe.session.user, "uploaded_at": frappe.utils.now(), "total_rows": len(parsed),
    }).insert(ignore_permissions=True)

    employees = _employees(period)
    seen, stored, linked = set(), [], set()
    for row in parsed:
        identity = row["identity_number"]
        employee, association_reason = match_employee(row, employees)
        result = reconcile_fund_row(row, employee, association_reason=association_reason)
        if identity and identity in seen:
            result["status"] = "Pending"
            result["original_match_status"] = "Pending"
            result["difference_reasons"] = "；".join(reason for reason in (result.get("difference_reasons"), "同一Excel内员工重复") if reason)
        if identity:
            seen.add(identity)
        if result.get("employee"):
            linked.add(result["employee"])
        stored.append(frappe.get_doc(_row_values(batch, row, result)).insert(ignore_permissions=True).as_dict())
    for employee in missing_from_excel(employees, linked):
        stored.append(frappe.get_doc(_missing_row_values(batch, employee)).insert(ignore_permissions=True).as_dict())

    summary = summarize_fund_rows(stored)
    batch.update({
        "status": "Pending Activation", "parsed_rows": summary["total_rows"], "matched_rows": summary["matched_rows"],
        "pending_rows": summary["pending_rows"], "unlinked_rows": summary["unlinked_rows"], "missing_rows": summary["missing_rows"],
        "employee_total": summary["employee_total"], "company_total": summary["company_total"], "receivable_total": summary["receivable_total"],
    })
    batch.save(ignore_permissions=True)
    frappe.db.commit()
    return get_fund_workbench(period, None, batch.name)


def _require_pending_batch(batch_name, message):
    batch_doc = frappe.get_doc(BATCH, batch_name)
    if batch_doc.status != "Pending Activation":
        frappe.throw(frappe._(message))
    return batch_doc


def _save_monthly_record(period, employee, base, employee_rate, company_rate, remark):
    amounts = {key: float(value) for key, value in housing_fund_amounts(base, employee_rate, company_rate).items()}
    key = f"{employee}|{period}"
    name = frappe.db.get_value("Employee Housing Fund", {"employee_period_key": key})
    doc = frappe.get_doc("Employee Housing Fund", name) if name else frappe.new_doc("Employee Housing Fund")
    doc.update({
        "period": period, "employee": employee, "employee_name": frappe.db.get_value("Employee", employee, "employee_name"),
        "contribution_base": float(base), "employee_rate": float(employee_rate), "company_rate": float(company_rate), **amounts,
        "status": "Confirmed", "remark": remark, "employee_period_key": key,
    })
    doc.save(ignore_permissions=True)


def _write_monthly_records(batch_doc):
    """生效时把每个人这个月的基数和比例写进月度公积金记录；上一批导入写过、这一批已经没有的人，记录一并撤掉。"""
    rows = frappe.get_all(
        ROW,
        filters={"batch": batch_doc.name, "row_type": "excel", "status": ["in", ["Matched", "Confirmed Difference"]]},
        fields=["employee", "status", "contribution_base", "employee_amount", "company_amount", "reference_base",
                "reference_employee_rate", "reference_company_rate"],
    )
    remark = f"{IMPORT_REMARK} {batch_doc.name}"
    written = set()
    for row in rows:
        if not row.get("employee"):
            continue
        if row.get("status") == "Matched":
            base, employee_rate, company_rate = row["reference_base"], row["reference_employee_rate"], row["reference_company_rate"]
        else:
            base = row["contribution_base"]
            employee_rate, company_rate = rates_from_amounts(base, row["employee_amount"], row["company_amount"])
        _save_monthly_record(batch_doc.period, row["employee"], base, employee_rate, company_rate, remark)
        written.add(row["employee"])
    # 档案里有基数、申报表里却没有的人，HR 答复了：需补缴 → 这个月照系统复算记一笔（薪酬照常扣，申报下月补）；
    # 无需缴纳 → 记一笔 0，薪酬才不会因为缺记录而卡住。
    for row in frappe.get_all(
        ROW, filters={"batch": batch_doc.name, "row_type": "missing", "status": "Ignored"},
        fields=["employee", "remark", "reference_base", "reference_employee_rate", "reference_company_rate"],
    ):
        if not row.get("employee") or row["employee"] in written:
            continue
        answer = str(row.get("remark") or "")
        if answer.startswith(CATCHUP_PREFIX):
            base, employee_rate, company_rate = row["reference_base"], row["reference_employee_rate"], row["reference_company_rate"]
        else:
            base, employee_rate, company_rate = 0, 0, 0
        _save_monthly_record(batch_doc.period, row["employee"], base, employee_rate, company_rate, f"{remark}（{answer}）")
        written.add(row["employee"])
    stale = frappe.get_all(
        "Employee Housing Fund",
        filters={"period": batch_doc.period, "remark": ["like", f"{IMPORT_REMARK}%"]},
        fields=["name", "employee"],
    )
    for record in stale:
        if record["employee"] not in written:
            frappe.delete_doc("Employee Housing Fund", record["name"], ignore_permissions=True)
    return len(written)


@frappe.whitelist(methods=["POST"])
@housing_import_action
def activate_fund_batch(batch):
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    doc = _require_pending_batch(batch, "只有待确认导入批次可以生效。")
    rows = frappe.get_all(ROW, filters={"batch": doc.name}, fields=["status", "employee"])
    if not can_activate_rows(rows):
        frappe.throw(frappe._("请先处理全部待确认公积金明细，再确认导入。"))
    frappe.db.set_value(BATCH, {"period": doc.period, "is_current": 1}, {"is_current": 0, "status": "Historical"}, update_modified=False)
    _write_monthly_records(doc)
    doc.is_current = 1
    doc.status = "Current"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return get_fund_workbench(doc.period, None)


@frappe.whitelist(methods=["POST"])
@housing_import_action
def confirm_fund_row(row, employee=None, remark=""):
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    doc = frappe.get_doc(ROW, row)
    remark = str(remark or "").strip()
    if not remark:
        frappe.throw(frappe._("确认差异前必须填写备注。"))
    if doc.row_type == "missing":
        frappe.throw(frappe._("申报表里没有的人不能确认纳入，请选择“忽略”并写明是补缴还是无需缴纳。"))
    _require_pending_batch(doc.batch, "只能处理待确认导入批次的明细。")
    employee = employee or doc.employee
    employee_row = next((item for item in _employees(doc.period) if item.get("name") == employee), None) if employee else None
    if not employee_row or employee_row.get("company") not in SUPPORTED_COMPANIES:
        frappe.throw(frappe._("请选择示例总部或示例研发中心的在职员工。"))
    if frappe.db.exists(ROW, {"batch": doc.batch, "employee": employee_row.get("name"), "name": ["!=", doc.name]}):
        frappe.throw(frappe._("该员工已存在于当前导入批次。"))
    source = {
        "row_number": 0, "source_row": doc.source_row, "excel_name": doc.excel_name, "identity_number": doc.identity_number,
        "period": doc.period, "contribution_base": doc.contribution_base, "employee_amount": doc.employee_amount,
        "company_amount": doc.company_amount,
    }
    same_identity = str(employee_row.get("id_card_number_cn") or "").strip().replace(" ", "").upper() == str(doc.identity_number or "").strip().replace(" ", "").upper()
    result = reconcile_fund_row(source, employee_row, association_reason="" if same_identity else "人工关联员工，证件号码不一致")
    doc.employee = employee_row.get("name")
    doc.employee_name = employee_row.get("employee_name")
    doc.company = employee_row.get("company")
    for field, value in _calculated_values(result).items():
        doc.set(field, value)
    doc.difference_total = result.get("difference_total", 0)
    doc.difference_reasons = result.get("difference_reasons")
    doc.reference_base = result.get("reference_base", 0)
    doc.base_source = result.get("base_source")
    doc.reference_employee_rate = result.get("reference_employee_rate", 0)
    doc.reference_company_rate = result.get("reference_company_rate", 0)
    doc.remark = remark
    doc.status = "Confirmed Difference"
    doc.confirmed_by = frappe.session.user
    doc.confirmed_at = frappe.utils.now()
    doc.save(ignore_permissions=True)
    _refresh_batch_summary(doc.batch)
    frappe.db.commit()
    return get_fund_workbench(doc.period, None, doc.batch)


@frappe.whitelist(methods=["POST"])
@housing_import_action
def ignore_fund_row(row, remark=""):
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    doc = frappe.get_doc(ROW, row)
    remark = str(remark or "").strip()
    if not remark:
        frappe.throw(frappe._("忽略明细前必须填写原因。"))
    if doc.status != "Pending":
        frappe.throw(frappe._("只有待确认明细可以忽略。"))
    _require_pending_batch(doc.batch, "只能处理待确认导入批次的明细。")
    doc.status = "Ignored"
    doc.remark = remark
    doc.ignored_by = frappe.session.user
    doc.ignored_at = frappe.utils.now()
    doc.save(ignore_permissions=True)
    _refresh_batch_summary(doc.batch)
    frappe.db.commit()
    return get_fund_workbench(doc.period, None, doc.batch)


@frappe.whitelist(methods=["POST"])
@housing_import_action
def cancel_fund_batch(batch, remark=""):
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    doc = _require_pending_batch(batch, "只有待确认导入批次可以取消。")
    remark = str(remark or "").strip()
    if not remark:
        frappe.throw(frappe._("取消批次前必须填写原因。"))
    doc.status = "Canceled"
    doc.is_current = 0
    doc.cancel_remark = remark
    doc.canceled_by = frappe.session.user
    doc.canceled_at = frappe.utils.now()
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return get_fund_workbench(doc.period, None)


@frappe.whitelist(methods=["POST"])
@housing_import_action
def reconcile_fund_batch(batch):
    """档案基数改过以后重新核对：还没人工处理过的 Excel 明细按最新档案重算；"申报表里没有"的行基数补齐后自然仍保留。"""
    require_rd_access(ROLES)
    require_hr_sensitive_access()
    batch_doc = _require_pending_batch(batch, "只有待确认导入批次可以重新核对。")
    employees = _employees(batch_doc.period)
    rows = frappe.get_all(
        ROW, filters={"batch": batch_doc.name, "row_type": "excel"},
        fields=["name", "source_row", "excel_name", "identity_number", "status", "contribution_base", "employee_amount", "company_amount"],
        order_by="source_row",
    )
    for stored in rows:
        if stored.get("status") in ("Confirmed Difference", "Ignored"):
            continue
        source = {
            "row_number": 0, "source_row": stored.get("source_row"), "excel_name": stored.get("excel_name"),
            "identity_number": stored.get("identity_number"), "period": batch_doc.period,
            "contribution_base": stored.get("contribution_base"), "employee_amount": stored.get("employee_amount"),
            "company_amount": stored.get("company_amount"),
        }
        employee, association_reason = match_employee(source, employees)
        result = reconcile_fund_row(source, employee, association_reason=association_reason)
        row_doc = frappe.get_doc(ROW, stored["name"])
        row_doc.employee = result.get("employee")
        row_doc.employee_name = result.get("employee_name")
        row_doc.company = result.get("company")
        row_doc.reference_base = result.get("reference_base", 0)
        row_doc.base_source = result.get("base_source")
        row_doc.reference_employee_rate = result.get("reference_employee_rate", 0)
        row_doc.reference_company_rate = result.get("reference_company_rate", 0)
        row_doc.status = result.get("status")
        row_doc.original_match_status = result.get("original_match_status")
        row_doc.difference_total = result.get("difference_total", 0)
        row_doc.difference_reasons = result.get("difference_reasons")
        for field, value in _calculated_values(result).items():
            row_doc.set(field, value)
        row_doc.save(ignore_permissions=True)
    _sync_missing_rows(batch_doc, employees)
    _refresh_batch_summary(batch_doc.name)
    frappe.db.commit()
    return get_fund_workbench(batch_doc.period, None, batch_doc.name)


def _sync_missing_rows(batch_doc, employees):
    """基数补齐以后，"申报表里没有"的名单也要跟着变：已经有 Excel 行或不再有基数的撤掉，新有基数又不在表里的补上。已经人工处理过的不动。"""
    by_id = {employee["name"]: employee for employee in employees}
    linked = {row["employee"] for row in frappe.get_all(ROW, filters={"batch": batch_doc.name, "row_type": "excel"}, fields=["employee"]) if row.get("employee")}
    existing = {row["employee"]: row for row in frappe.get_all(ROW, filters={"batch": batch_doc.name, "row_type": "missing"}, fields=["name", "employee", "status"])}
    for employee_id, stored in existing.items():
        employee = by_id.get(employee_id)
        if stored["status"] == "Pending" and (employee_id in linked or not employee or employee["housing_fund_base"] <= 0):
            frappe.delete_doc(ROW, stored["name"], ignore_permissions=True, force=True)
    for employee in missing_from_excel(employees, linked):
        if employee["name"] not in existing:
            frappe.get_doc(_missing_row_values(batch_doc, employee)).insert(ignore_permissions=True)
