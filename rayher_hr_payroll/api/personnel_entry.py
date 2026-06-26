import frappe

from rayher_hr_payroll.api._guards import require_rd_access

RD_HR_WRITE = ("System Manager", "HR User", "HR Manager")


@frappe.whitelist()
def list_employees():
    require_rd_access(RD_HR_WRITE)
    fields = ["name", "employee_name", "gender", "date_of_joining",
              "rd_personnel_type", "archive_status", "department",
              "rd_mock_base", "rd_mock_social", "rd_mock_fund", "rd_mock_tax"]
    # id_card_number_cn is permlevel:1 PII — only HR-level roles may see it
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
    return frappe.get_all("Department", filters={"is_group": 0},
                          fields=["name", "department_name"], order_by="department_name")


def _birth(idc):
    from datetime import date as _date
    idc = (idc or "").strip()
    if len(idc) == 18 and idc[6:14].isdigit():       # YYYYMMDD at 6:14
        y, m, d = idc[6:10], idc[10:12], idc[12:14]
    elif len(idc) == 15 and idc[6:12].isdigit():     # old 15-digit: YYMMDD at 6:12 (19xx)
        y, m, d = "19" + idc[6:8], idc[8:10], idc[10:12]
    else:
        return None
    try:
        _date(int(y), int(m), int(d))                # reject impossible months/days (e.g. 13)
    except ValueError:
        return None
    return "%s-%s-%s" % (y, m, d)


@frappe.whitelist(methods=["POST"])
def save_employee(name=None, employee_name=None, id_card_number_cn=None, gender=None,
                  date_of_joining=None, rd_personnel_type=None, archive_status=None, department=None,
                  rd_mock_base=None, rd_mock_social=None, rd_mock_fund=None, rd_mock_tax=None):
    require_rd_access(RD_HR_WRITE)
    provided = {
        "employee_name": employee_name, "id_card_number_cn": id_card_number_cn,
        "gender": gender, "date_of_joining": date_of_joining,
        "rd_personnel_type": rd_personnel_type, "archive_status": archive_status,
        "department": department,
        "rd_mock_base": rd_mock_base, "rd_mock_social": rd_mock_social,
        "rd_mock_fund": rd_mock_fund, "rd_mock_tax": rd_mock_tax,
    }
    # The SPA edit form submits the full field set, so "" means the user cleared
    # the field (e.g. selecting 部门 "(未设置)" or clearing a wrong id_card). Drop
    # only None (truly omitted by a partial API caller); persist "" so editable
    # fields can be cleared. Numeric salary fields coerce "" -> 0.
    vals = {}
    for k, v in provided.items():
        if v is None:
            continue
        vals[k] = float(v or 0) if k.startswith("rd_mock_") else v
    if employee_name:
        vals["first_name"] = employee_name  # rename must update first_name (employee_name is derived)
    is_hr = bool(set(frappe.get_roles()) & {"System Manager", "HR User", "HR Manager"})
    if not is_hr:
        vals.pop("id_card_number_cn", None)  # only HR may write permlevel-1 PII

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
            doctype="Employee", company=company, status="Active",
            employee_name=employee_name, first_name=employee_name,
            id_card_number_cn=id_card_number_cn,
            gender=gender or "Male",
            date_of_birth=_birth(id_card_number_cn) or "1990-01-01",
            date_of_joining=date_of_joining or frappe.utils.today(),
            rd_personnel_type=rd_personnel_type or "",
            archive_status=archive_status or "待完善", department=department or None,
            rd_mock_base=float(rd_mock_base or 0), rd_mock_social=float(rd_mock_social or 0),
            rd_mock_fund=float(rd_mock_fund or 0), rd_mock_tax=float(rd_mock_tax or 0),
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
