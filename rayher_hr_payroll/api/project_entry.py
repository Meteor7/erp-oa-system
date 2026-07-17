from __future__ import annotations

import frappe

from rayher_hr_payroll.api._guards import require_rd_access

RD_PROJECT_ADMIN_ROLES = ("System Manager", "HR User", "HR Manager", "Accounts User")
RD_PROJECT_OWNER_ROLE = "Project Owner"
RD_PROJECT_ALL_ACCESS_ROLE = "All Project Access"
RD_PROJECT_ACCESS_ROLES = (*RD_PROJECT_ADMIN_ROLES, RD_PROJECT_OWNER_ROLE)
# Compatibility alias for integrations that imported the former constant.
RD_PROJECT_MANAGE_ROLES = RD_PROJECT_ADMIN_ROLES

DEFAULT_RAYHER_PROJECTS = [
    {"project_code": "RD19", "project_name": "KIBO 4895C", "start_date": "2026-07-01", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD18", "project_name": "KIBO 4895", "start_date": "2026-07-01", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD17", "project_name": "EFEM-12-2LP-EG-A", "start_date": "2026-05-09", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD16", "project_name": "EFEM-8-2LP-EG-A", "start_date": "2026-05-09", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD15", "project_name": "DRAKENS 4482", "start_date": "2026-05-06", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD14", "project_name": "ACONCA 7961", "start_date": "2026-01-05", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD13", "project_name": "KIBO 5895H", "start_date": "2026-01-05", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD12", "project_name": "Self-developed EFEM", "start_date": "2025-06-05", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD11", "project_name": "RMS", "start_date": "2025-06-01", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD10", "project_name": "NANSI 1266", "start_date": "2025-04-01", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD09", "project_name": "Result Viewer", "start_date": "2024-05-06", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD08", "project_name": "KIBO 5895", "start_date": "2024-01-02", "end_date": "2025-12-31", "status": "Completed", "rd_stage": "资本化"},
    {"project_code": "RD07", "project_name": "CANIGO 2785", "start_date": "2024-01-02", "end_date": "", "status": "Open", "rd_stage": "资本化"},
    {"project_code": "RD06", "project_name": "MUSHI 7546", "start_date": "2024-01-02", "end_date": "", "status": "Open", "rd_stage": "资本化"},
    {"project_code": "RD05", "project_name": "DRAKENS 3482", "start_date": "2023-10-25", "end_date": "2026-04-30", "status": "Completed", "rd_stage": "资本化"},
    {"project_code": "RD04", "project_name": "VEYMONT 2341", "start_date": "2023-09-11", "end_date": "2026-04-30", "status": "Completed", "rd_stage": "资本化"},
    {"project_code": "RD02", "project_name": "ADC", "start_date": "2022-12-01", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD03", "project_name": "Automation platform", "start_date": "2022-12-01", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD01", "project_name": "ACONCA 6961", "start_date": "2022-12-01", "end_date": "2025-12-31", "status": "Completed", "rd_stage": "资本化"},
]

_STATUS_LABELS = {
    "Open": "进行中",
    "Completed": "已结束",
    "Cancelled": "已取消",
}
_STATUS_VALUES = {value: key for key, value in _STATUS_LABELS.items()}
_STATUS_VALUES.update({key: key for key in _STATUS_LABELS})
_STAGE_LABELS = {"资本化": "资本化", "费用化": "费用化", "未判定": "未判定"}
_STAGE_VALUES = {key: key for key in _STAGE_LABELS}
_STAGE_VALUES.update({"capitalized": "资本化", "expensed": "费用化", "unknown": "未判定", "Capitalized": "资本化", "Expensed": "费用化"})
PROJECT_REPORT_FIELDS = {
    "project_initiation_report",
    "project_completion_report",
    "capitalization_confirmation_file",
}
_UNSET = object()


def _project_roles():
    return set(frappe.get_roles(frappe.session.user))


def _is_project_admin(roles=None):
    roles = roles if roles is not None else _project_roles()
    return bool(set(RD_PROJECT_ADMIN_ROLES) & set(roles))


def _can_view_all_projects(roles=None):
    roles = roles if roles is not None else _project_roles()
    return _is_project_admin(roles) or (
        RD_PROJECT_OWNER_ROLE in roles and RD_PROJECT_ALL_ACCESS_ROLE in roles
    )


def _require_project_access():
    require_rd_access(RD_PROJECT_ACCESS_ROLES)
    return _project_roles()


def _require_project_admin():
    require_rd_access(RD_PROJECT_ADMIN_ROLES)


def _existing_project_for_edit(name, status, project_owner, roles):
    if _is_project_admin(roles):
        return None
    doc_name = _clean(name)
    if not doc_name or not frappe.db.exists("Project", doc_name):
        frappe.throw(frappe._("\u9879\u76ee\u8d1f\u8d23\u4eba\u4e0d\u80fd\u65b0\u589e\u9879\u76ee\u3002"))
    project = frappe.db.get_value(
        "Project",
        doc_name,
        ["project_owner", "project_owner_name", "status"],
        as_dict=True,
    )
    if not project:
        frappe.throw(frappe._("\u9879\u76ee\u4e0d\u5b58\u5728\u3002"))
    if not _can_view_all_projects(roles) and project.get("project_owner") != frappe.session.user:
        frappe.throw(frappe._("\u60a8\u65e0\u6743\u7f16\u8f91\u8be5\u9879\u76ee\u3002"))
    requested_owner = _clean(project_owner)
    if requested_owner and requested_owner != project.get("project_owner"):
        frappe.throw(frappe._("\u9879\u76ee\u8d1f\u8d23\u4eba\u4e0d\u80fd\u53d8\u66f4\u9879\u76ee\u8d1f\u8d23\u4eba\u3002"))
    if _status_value(status) == "Cancelled" and project.get("status") != "Cancelled":
        frappe.throw(frappe._("\u9879\u76ee\u8d1f\u8d23\u4eba\u4e0d\u80fd\u53d6\u6d88\u9879\u76ee\u3002"))
    return project


def _resolve_project_owner(project_owner, project_owner_name):
    user = _clean(project_owner)
    if not user:
        return None, _clean(project_owner_name) or None
    employee_name = frappe.db.get_value(
        "Employee",
        {"user_id": user, "status": "Active"},
        "employee_name",
    )
    if not employee_name:
        frappe.throw(frappe._("\u8bf7\u9009\u62e9\u5df2\u5173\u8054\u5728\u804c\u5458\u5de5\u7684\u9879\u76ee\u8d1f\u8d23\u4eba\u3002"))
    return user, employee_name


def ensure_project_owner_role(user):
    user = _clean(user)
    if not user or not frappe.db.exists("User", user):
        return False
    if frappe.db.exists("Has Role", {"parent": user, "parenttype": "User", "role": RD_PROJECT_OWNER_ROLE}):
        return False
    frappe.get_doc("User", user).add_roles(RD_PROJECT_OWNER_ROLE)
    return True


def _company():
    return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all(
        "Company", pluck="name", limit=1
    )[0]


def _clean(value):
    return (value or "").strip() if isinstance(value, str) else value


def _date_or_none(value):
    value = _clean(value)
    return value or None


def _project_key(project_code, project_name):
    code = _clean(project_code)
    name = _clean(project_name)
    return f"{code} | {name}" if code and name else code or name


def _status_value(status):
    status = _clean(status) or "Open"
    if status not in _STATUS_VALUES:
        frappe.throw(frappe._("项目状态无效。"))
    return _STATUS_VALUES[status]


def _stage_value(stage):
    stage = _clean(stage) or "费用化"
    if stage not in _STAGE_VALUES:
        frappe.throw(frappe._("研发阶段无效。"))
    return _STAGE_VALUES[stage]


def _serialize(row):
    data = dict(row)
    data["status_label"] = _STATUS_LABELS.get(data.get("status"), data.get("status") or "")
    data["rd_stage"] = _stage_value(data.get("rd_stage"))
    data["rd_stage_label"] = _STAGE_LABELS.get(data.get("rd_stage"), data.get("rd_stage") or "")
    data["start_date"] = data.get("capitalization_start_date")
    data["end_date"] = data.get("capitalization_end_date")
    return data


@frappe.whitelist()
def list_projects(search=None, status=None):
    roles = _require_project_access()
    filters = {"rd_project_code": ["!=", ""]}
    if not _can_view_all_projects(roles):
        filters["project_owner"] = frappe.session.user
    if _clean(status):
        filters["status"] = _status_value(status)
    rows = frappe.get_all(
        "Project",
        filters=filters,
        fields=[
            "name", "project_name", "rd_project_code", "rd_project_key", "status", "rd_stage",
            "allow_rd_timesheet", "capitalization_start_date", "capitalization_end_date",
            "project_owner_name", "project_owner", "project_initiation_report", "project_completion_report",
            "capitalization_confirmation_file",
        ],
        order_by="rd_project_code desc",
    )
    query = (_clean(search) or "").lower()
    data = [_serialize(row) for row in rows]
    if query:
        data = [
            row for row in data
            if query in " ".join([
                str(row.get("rd_project_code") or ""),
                str(row.get("project_name") or ""),
            ]).lower()
        ]
    return data


def _accessible_project(project, roles):
    project_name = _clean(project)
    if not project_name:
        frappe.throw(frappe._("项目不存在。"))
    row = frappe.db.get_value(
        "Project",
        project_name,
        ["name", "project_owner", *sorted(PROJECT_REPORT_FIELDS)],
        as_dict=True,
    )
    if not row:
        frappe.throw(frappe._("项目不存在。"))
    if not _can_view_all_projects(roles) and row.get("project_owner") != frappe.session.user:
        frappe.throw(frappe._("您无权查看该项目报告。"))
    return row


@frappe.whitelist()
def download_project_report(project, fieldname):
    roles = _require_project_access()
    fieldname = _clean(fieldname)
    if fieldname not in PROJECT_REPORT_FIELDS:
        frappe.throw(frappe._("无效的项目报告类型。"))

    row = _accessible_project(project, roles)
    file_url = row.get(fieldname)
    if not file_url:
        frappe.throw(frappe._("该项目尚未上传此报告。"))

    file_name = frappe.db.get_value(
        "File",
        {
            "attached_to_doctype": "Project",
            "attached_to_name": row.get("name"),
            "attached_to_field": fieldname,
            "file_url": file_url,
            "is_private": 1,
        },
        "name",
    )
    if not file_name:
        frappe.throw(frappe._("项目报告附件不存在或关联不正确。"))

    file_doc = frappe.get_doc("File", file_name)
    frappe.local.response.filename = file_doc.file_name
    frappe.local.response.filecontent = file_doc.get_content()
    frappe.local.response.type = "download"


@frappe.whitelist()
def list_project_owners():
    _require_project_admin()
    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active", "user_id": ["!=", ""]},
        fields=["user_id", "employee_name"],
        order_by="employee_name asc, user_id asc",
    )
    return [
        {"name": row.get("user_id"), "full_name": row.get("employee_name")}
        for row in employees
        if row.get("user_id")
    ]


def _project_values(
    project_code,
    project_name,
    start_date=None,
    end_date=None,
    status="Open",
    rd_stage="费用化",
    project_owner_name=_UNSET,
    project_owner=_UNSET,
    project_initiation_report=_UNSET,
    project_completion_report=_UNSET,
    capitalization_confirmation_file=_UNSET,
):
    code = _clean(project_code)
    name = _clean(project_name)
    if not code or not name:
        frappe.throw(frappe._("请填写项目编号和项目名称。"))
    status_value = _status_value(status)
    stage_value = _stage_value(rd_stage)
    values = {
        "project_name": name,
        "rd_project_code": code,
        "rd_project_key": _project_key(code, name),
        "status": status_value,
        "rd_stage": stage_value,
        "company": _company(),
        "allow_rd_timesheet": 0 if status_value == "Cancelled" else 1,
        "capitalization_start_date": _date_or_none(start_date),
        "capitalization_end_date": _date_or_none(end_date),
    }
    optional_values = {
        "project_owner_name": project_owner_name,
        "project_owner": project_owner,
        "project_initiation_report": project_initiation_report,
        "project_completion_report": project_completion_report,
        "capitalization_confirmation_file": capitalization_confirmation_file,
    }
    for fieldname, value in optional_values.items():
        if value is not _UNSET:
            values[fieldname] = _clean(value) or None
    return values


def _save_project_doc(
    project_code,
    project_name,
    start_date=None,
    end_date=None,
    status="Open",
    name=None,
    rd_stage="费用化",
    project_owner_name=_UNSET,
    project_owner=_UNSET,
    project_initiation_report=_UNSET,
    project_completion_report=_UNSET,
    capitalization_confirmation_file=_UNSET,
):
    code = _clean(project_code)
    doc_name = _clean(name) or code
    values = _project_values(
        code,
        project_name,
        start_date,
        end_date,
        status,
        rd_stage,
        project_owner_name=project_owner_name,
        project_owner=project_owner,
        project_initiation_report=project_initiation_report,
        project_completion_report=project_completion_report,
        capitalization_confirmation_file=capitalization_confirmation_file,
    )
    if frappe.db.exists("Project", doc_name):
        doc = frappe.get_doc("Project", doc_name)
        doc.update(values)
        doc.save(ignore_permissions=True)
        return doc.name
    doc = frappe.get_doc({"doctype": "Project", "name": doc_name, **values})
    doc.insert(ignore_permissions=True, set_name=doc_name)
    return doc.name


@frappe.whitelist(methods=["POST"])
def save_project(
    project_code,
    project_name,
    start_date=None,
    end_date=None,
    status="Open",
    name=None,
    english_name=None,
    rd_stage="费用化",
    project_owner_name=None,
    project_owner=None,
    project_initiation_report=None,
    project_completion_report=None,
    capitalization_confirmation_file=None,
):
    roles = _require_project_access()
    project_name = _clean(project_name) or _clean(english_name)
    existing = _existing_project_for_edit(name, status, project_owner, roles)
    if existing is not None:
        project_owner = existing.get("project_owner")
        project_owner_name = existing.get("project_owner_name")
    else:
        project_owner, project_owner_name = _resolve_project_owner(
            project_owner,
            project_owner_name,
        )
    saved = _save_project_doc(
        project_code,
        project_name,
        start_date,
        end_date,
        status,
        name=name,
        rd_stage=rd_stage,
        project_owner_name=project_owner_name,
        project_owner=project_owner,
        project_initiation_report=project_initiation_report,
        project_completion_report=project_completion_report,
        capitalization_confirmation_file=capitalization_confirmation_file,
    )
    if project_owner:
        ensure_project_owner_role(project_owner)
    frappe.db.commit()
    return {"name": saved}


@frappe.whitelist(methods=["POST"])
def cancel_project(name):
    _require_project_admin()
    doc = frappe.get_doc("Project", name)
    doc.update({"status": "Cancelled", "allow_rd_timesheet": 0})
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


def backfill_project_owner_accounts():
    required = ("project_owner", "project_owner_name")
    if not all(frappe.db.has_column("Project", fieldname) for fieldname in required):
        return {"linked": 0, "role_grants": 0, "unmatched": 0}

    linked = 0
    role_grants = 0
    unmatched = 0
    projects = frappe.get_all(
        "Project",
        filters={"rd_project_code": ["!=", ""]},
        fields=["name", "project_owner", "project_owner_name"],
    )
    for project in projects:
        owner = _clean(project.get("project_owner"))
        owner_name = _clean(project.get("project_owner_name"))
        if not owner and owner_name:
            matches = frappe.get_all(
                "Employee",
                filters={
                    "employee_name": owner_name,
                    "status": "Active",
                    "user_id": ["!=", ""],
                },
                fields=["user_id"],
                limit=2,
            )
            users = {row.get("user_id") for row in matches if row.get("user_id")}
            if len(users) == 1:
                candidate = users.pop()
                if frappe.db.exists("User", candidate):
                    frappe.db.set_value(
                        "Project",
                        project.get("name"),
                        "project_owner",
                        candidate,
                        update_modified=False,
                    )
                    owner = candidate
                    linked += 1
            if not owner:
                unmatched += 1
        if owner and ensure_project_owner_role(owner):
            role_grants += 1
    return {"linked": linked, "role_grants": role_grants, "unmatched": unmatched}


def ensure_default_projects():
    for item in DEFAULT_RAYHER_PROJECTS:
        _save_project_doc(**item)
    frappe.db.commit()
    return len(DEFAULT_RAYHER_PROJECTS)
