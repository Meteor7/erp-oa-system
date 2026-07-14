import frappe

from rayher_hr_payroll.api._guards import require_rd_access

RD_HR_WRITE = ("System Manager", "HR User", "HR Manager")
EXPENSE_ACCOUNT_CATEGORIES = ("研发费用", "管理费用", "销售费用", "生产成本")


@frappe.whitelist()
def list_employees():
    require_rd_access(RD_HR_WRITE)
    fields = [
        "name", "employee_name", "gender", "date_of_joining", "relieving_date",
        "rd_personnel_type", "archive_status", "expense_account_category", "department", "designation",
        "rd_mock_base", "rd_mock_social", "rd_mock_fund", "rd_mock_tax",
    ]
    # id_card_number_cn is permlevel:1 PII - only HR-level roles may see it.
    if set(frappe.get_roles()) & {"System Manager", "HR User", "HR Manager"}:
        fields.insert(2, "id_card_number_cn")
    # Role-gated org-wide view: the app uses role-based access (not per-user Employee User
    # Permissions), and HR-level roles are deliberately allowed to see id_card_number_cn
    # (permlevel-1 PII). NOTE: get_all bypasses both DocPerm and permlevel field filtering, so
    # the require_rd_access gate above -- NOT the permission model -- is the access control
    # here. To make this model-driven/auditable, add a permlevel-1 read DocPerm for these roles
    # and switch to get_list.
    return frappe.get_all("Employee", fields=fields, order_by="employee_name")


@frappe.whitelist()
def get_dept_options():
    require_rd_access(RD_HR_WRITE)
    return frappe.get_all(
        "Department",
        filters={"is_group": 0},
        fields=["name", "department_name"],
        order_by="department_name",
    )


@frappe.whitelist()
def get_designation_options():
    require_rd_access(RD_HR_WRITE)
    return frappe.get_all("Designation", pluck="name", order_by="name")


def _birth(idc):
    from datetime import date as _date

    idc = (idc or "").strip()
    if len(idc) == 18 and idc[6:14].isdigit():
        y, m, d = idc[6:10], idc[10:12], idc[12:14]
    elif len(idc) == 15 and idc[6:12].isdigit():
        y, m, d = "19" + idc[6:8], idc[8:10], idc[10:12]
    else:
        return None
    try:
        _date(int(y), int(m), int(d))
    except ValueError:
        return None
    return "%s-%s-%s" % (y, m, d)


def _clean_expense_category(value):
    category = (value or "").strip()
    if category and category not in EXPENSE_ACCOUNT_CATEGORIES:
        frappe.throw(frappe._("费用科目必须是研发费用、管理费用、销售费用或生产成本。"))
    return category


@frappe.whitelist(methods=["POST"])
def save_employee(name=None, employee_name=None, id_card_number_cn=None, gender=None,
                  date_of_joining=None, relieving_date=None, rd_personnel_type=None, archive_status=None, department=None,
                  designation=None, expense_account_category=None,
                  rd_mock_base=None, rd_mock_social=None, rd_mock_fund=None, rd_mock_tax=None):
    require_rd_access(RD_HR_WRITE)
    provided = {
        "employee_name": employee_name,
        "id_card_number_cn": id_card_number_cn,
        "gender": gender,
        "date_of_joining": date_of_joining,
        "relieving_date": relieving_date,
        "rd_personnel_type": rd_personnel_type,
        "archive_status": archive_status,
        "department": department,
        "designation": designation,
        "expense_account_category": _clean_expense_category(expense_account_category) if expense_account_category is not None else None,
        "rd_mock_base": rd_mock_base,
        "rd_mock_social": rd_mock_social,
        "rd_mock_fund": rd_mock_fund,
        "rd_mock_tax": rd_mock_tax,
    }
    # The SPA edit form submits the full field set, so "" means the user cleared the field.
    # Drop only None (truly omitted by a partial API caller). Numeric salary fields coerce "" -> 0.
    vals = {}
    for k, v in provided.items():
        if v is None:
            continue
        vals[k] = float(v or 0) if k.startswith("rd_mock_") else v
    if "relieving_date" in vals:
        vals["relieving_date"] = vals["relieving_date"] or None
        vals["status"] = "Left" if vals["relieving_date"] else "Active"
    if employee_name:
        vals["first_name"] = employee_name
    is_hr = bool(set(frappe.get_roles()) & {"System Manager", "HR User", "HR Manager"})
    if not is_hr:
        vals.pop("id_card_number_cn", None)

    if name:
        if not frappe.has_permission("Employee", "write", doc=name):
            frappe.throw(frappe._("您无权修改该员工。"))
        d = frappe.get_doc("Employee", name)
        d.update(vals)
        d.save(ignore_permissions=True)
    else:
        if not frappe.has_permission("Employee", "create"):
            frappe.throw(frappe._("您无权新增员工。"))
        company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", pluck="name", limit=1)[0]
        d = frappe.get_doc(dict(
            doctype="Employee",
            company=company,
            status="Left" if relieving_date else "Active",
            relieving_date=relieving_date or None,
            employee_name=employee_name,
            first_name=employee_name,
            id_card_number_cn=id_card_number_cn,
            gender=gender or "Male",
            date_of_birth=_birth(id_card_number_cn) or "1990-01-01",
            date_of_joining=date_of_joining or frappe.utils.today(),
            rd_personnel_type=rd_personnel_type or "",
            archive_status=archive_status or "待完善",
            department=department or None,
            designation=designation or None,
            expense_account_category=_clean_expense_category(expense_account_category),
            rd_mock_base=float(rd_mock_base or 0),
            rd_mock_social=float(rd_mock_social or 0),
            rd_mock_fund=float(rd_mock_fund or 0),
            rd_mock_tax=float(rd_mock_tax or 0),
        ))
        d.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": d.name}


@frappe.whitelist(methods=["POST"])
def delete_employee(name):
    require_rd_access(("System Manager", "HR Manager"))
    if not frappe.has_permission("Employee", "delete", doc=name):
        frappe.throw(frappe._("您无权删除该员工。"))
    frappe.delete_doc("Employee", name, ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}
