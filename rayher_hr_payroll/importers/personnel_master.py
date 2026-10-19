from collections import Counter, defaultdict
from datetime import date, datetime

from rayher_hr_payroll.department_structure import department_for_employee


SOURCE_FIELDS = {
    "employee_number", "employee_name", "english_name", "date_of_birth", "gender",
    "date_of_joining", "department", "designation", "reports_to_name", "employment_type",
    "labour_contract_start_date", "probation_months", "probation_end_date",
    "first_contract_period_years", "first_contract_end_date", "contract_renewal_status",
    "second_contract_period_years", "second_contract_end_date", "education_level_cn",
    "degree_cn", "education_completion_type", "graduation_school", "major_cn",
    "cell_number", "household_registration", "id_type_cn", "id_card_number_cn",
    "bank_ac_no", "bank_name", "social_insurance_number", "housing_fund_number",
}
DATE_FIELDS = {
    "date_of_birth", "date_of_joining", "labour_contract_start_date",
    "probation_end_date", "first_contract_end_date", "second_contract_end_date",
}
TEXT_IDENTIFIER_FIELDS = {
    "employee_number", "bank_ac_no", "id_card_number_cn",
    "social_insurance_number", "housing_fund_number",
}

def normalize_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    try:
        repaired = text.encode("latin1").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired.strip()


def _identifier(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return normalize_text(value).replace(" ", "") if not isinstance(value, str) else normalize_text(value)


def _date_value(value):
    if value in (None, ""):
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = normalize_text(value)
    return text[:10] if len(text) >= 10 else text


def _gender(value):
    label = normalize_text(value)
    return {"男": "Male", "女": "Female", "Male": "Male", "Female": "Female"}.get(label, label)


def normalize_record(record):
    normalized = {}
    for key in SOURCE_FIELDS:
        value = record.get(key)
        if value in (None, ""):
            continue
        if key in DATE_FIELDS:
            value = _date_value(value)
        elif key == "gender":
            value = _gender(value)
        elif key in TEXT_IDENTIFIER_FIELDS:
            value = _identifier(value)
        elif key in {"probation_months", "first_contract_period_years", "second_contract_period_years"}:
            value = int(value) if isinstance(value, float) and value.is_integer() else value
        else:
            value = normalize_text(value)
        if value not in (None, ""):
            normalized[key] = value
    department = department_for_employee(
        normalized.get("employee_name"),
        normalized.get("designation"),
        normalized.get("department"),
    )
    if department:
        normalized["department"] = department
    else:
        normalized.pop("department", None)
    return normalized


def plan_personnel_import(records, existing):
    by_number = defaultdict(list)
    by_name = defaultdict(list)
    for row in existing:
        number = _identifier(row.get("employee_number"))
        name = normalize_text(row.get("employee_name"))
        if number:
            by_number[number].append(row)
        if name:
            by_name[name].append(row)

    items = []
    for source in records:
        record = normalize_record(source)
        number = record.get("employee_number", "")
        name = record.get("employee_name", "")
        matches = by_number.get(number, []) if number else []
        if len(matches) == 1:
            items.append({"action": "update", "target": matches[0]["name"], "record": record})
            continue
        if len(matches) > 1:
            items.append({"action": "skip", "reason": "ambiguous_employee_number", "record": record})
            continue
        name_matches = by_name.get(name, []) if name else []
        # 修复（2026-09-29，审查 X3-2，决定 D2）：按姓名匹配只用于"没有工号可比"的在职员工。
        # 原来会把新员工的身份证、银行卡写进同名演示员工166员工的档案（演示员工138自己没有档案），
        # 或覆盖工号不同的同名在职同事。复职请在人员页清空原档的演示员工166日期。
        if len(name_matches) == 1 and (name_matches[0].get("status") or "Active") != "Active":
            items.append({"action": "skip", "reason": "name_matches_left_employee", "record": record})
        elif len(name_matches) == 1 and number and _identifier(name_matches[0].get("employee_number")):
            items.append({"action": "skip", "reason": "employee_number_conflict", "record": record})
        elif len(name_matches) == 1:
            items.append({"action": "update", "target": name_matches[0]["name"], "record": record})
        elif len(name_matches) > 1:
            items.append({"action": "skip", "reason": "ambiguous_name", "record": record})
        elif name:
            items.append({"action": "create", "record": record})
        else:
            items.append({"action": "skip", "reason": "missing_name", "record": record})

    counts = Counter(item["action"] for item in items)
    return {
        "items": items,
        "counts": {key: counts.get(key, 0) for key in ("create", "update", "skip")},
    }


def summarize_plan(plan):
    reasons = Counter(
        item.get("reason", "unknown")
        for item in plan["items"]
        if item["action"] == "skip"
    )
    return {
        "counts": dict(plan["counts"]),
        "skip_reasons": dict(sorted(reasons.items())),
    }


def _existing_employees(frappe):
    return frappe.get_all(
        "Employee",
        fields=["name", "employee_number", "employee_name", "status"],
        limit_page_length=0,
    )


def preview_personnel_import(records):
    import frappe

    return summarize_plan(plan_personnel_import(records, _existing_employees(frappe)))


def _ensure_department(frappe, department_name, company, cache):
    if not department_name:
        return None
    key = (department_name, company)
    if key in cache:
        return cache[key]
    name = frappe.db.get_value(
        "Department",
        {"department_name": department_name, "company": company, "is_group": 0},
        "name",
    )
    if not name:
        doc = frappe.get_doc({
            "doctype": "Department", "department_name": department_name,
            "company": company, "is_group": 0,
        })
        doc.insert(ignore_permissions=True)
        name = doc.name
    cache[key] = name
    return name


def _ensure_named_master(frappe, doctype, label, fieldname, cache):
    if not label:
        return None
    key = (doctype, label)
    if key in cache:
        return cache[key]
    name = frappe.db.get_value(doctype, {fieldname: label}, "name")
    if not name:
        doc = frappe.get_doc({"doctype": doctype, fieldname: label})
        doc.insert(ignore_permissions=True)
        name = doc.name
    cache[key] = name
    return name


def _employee_values(frappe, record, company, master_cache):
    values = {
        key: value for key, value in record.items()
        if key in SOURCE_FIELDS and key not in {"reports_to_name", "department", "designation", "employment_type"}
    }
    if record.get("department"):
        values["department"] = _ensure_department(
            frappe, record["department"], company, master_cache
        )
    if record.get("designation"):
        values["designation"] = _ensure_named_master(
            frappe, "Designation", record["designation"], "designation_name", master_cache
        )
    if record.get("employment_type"):
        values["employment_type"] = _ensure_named_master(
            frappe, "Employment Type", record["employment_type"], "employee_type_name", master_cache
        )
    if values.get("employee_name"):
        values["first_name"] = values["employee_name"]
    return values


def apply_personnel_import(records, company="QIHENG Demo"):
    import frappe

    plan = plan_personnel_import(records, _existing_employees(frappe))
    applied = Counter()
    skipped = Counter()
    employee_by_source_index = {}
    master_cache = {}
    try:
        for index, item in enumerate(plan["items"]):
            if item["action"] == "skip":
                skipped[item.get("reason", "unknown")] += 1
                continue
            record = item["record"]
            if item["action"] == "create":
                missing = [
                    field for field in ("employee_name", "gender", "date_of_birth", "date_of_joining")
                    if not record.get(field)
                ]
                if missing:
                    skipped["missing_create_fields"] += 1
                    continue
            values = _employee_values(frappe, record, company, master_cache)
            if item["action"] == "update":
                doc = frappe.get_doc("Employee", item["target"])
                doc.update(values)
                doc.save(ignore_permissions=True)
            else:
                doc = frappe.get_doc({
                    "doctype": "Employee", "company": company, "status": "Active", **values,
                })
                doc.insert(ignore_permissions=True)
            employee_by_source_index[index] = doc.name
            applied[item["action"]] += 1

        # 主管只在在职员工里按姓名找（修复 2026-09-29，审查 X3-2）。
        all_employees = frappe.get_all(
            "Employee", filters={"status": "Active"}, fields=["name", "employee_name"], limit_page_length=0
        )
        by_name = defaultdict(list)
        for row in all_employees:
            by_name[normalize_text(row.get("employee_name"))].append(row.get("name"))
        for index, employee in employee_by_source_index.items():
            supervisor_name = plan["items"][index]["record"].get("reports_to_name")
            matches = by_name.get(normalize_text(supervisor_name), []) if supervisor_name else []
            if len(matches) == 1 and matches[0] != employee:
                frappe.db.set_value("Employee", employee, "reports_to", matches[0], update_modified=False)

        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    return {
        "counts": {
            "create": applied.get("create", 0),
            "update": applied.get("update", 0),
            "skip": sum(skipped.values()),
        },
        "skip_reasons": dict(sorted(skipped.items())),
    }


def apply_personnel_import_file(path, company="QIHENG Demo", dry_run=True):
    import json

    with open(path, encoding="utf-8") as stream:
        records = json.load(stream)
    return preview_personnel_import(records) if dry_run else apply_personnel_import(records, company=company)
