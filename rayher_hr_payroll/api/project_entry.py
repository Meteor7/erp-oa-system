from __future__ import annotations

import frappe

from rayher_hr_payroll.api._guards import require_rd_access

RD_PROJECT_MANAGE_ROLES = ("System Manager", "HR User", "HR Manager", "Accounts User")

DEFAULT_RAYHER_PROJECTS = [
    {"project_code": "RD19", "project_name": "无图形晶圆缺陷检测系统（KIBO 4895C）", "start_date": "2026-07-01", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD18", "project_name": "无图形晶圆颗粒检测系统（KIBO 4895）", "start_date": "2026-07-01", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD17", "project_name": "EFEM-12-2LP-EG-A", "start_date": "2026-05-09", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD16", "project_name": "EFEM-8-2LP-EG-A", "start_date": "2026-05-09", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD15", "project_name": "DRAKENS 4482", "start_date": "2026-05-06", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD14", "project_name": "ACONCA 7961", "start_date": "2026-01-05", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD13", "project_name": "KIBO 5895H", "start_date": "2026-01-05", "end_date": "", "status": "Open", "rd_stage": "费用化"},
    {"project_code": "RD12", "project_name": "EFEM", "start_date": "2025-06-05", "end_date": "", "status": "Open", "rd_stage": "费用化"},
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
    data["english_name"] = data.get("project_name") or ""
    data["status_label"] = _STATUS_LABELS.get(data.get("status"), data.get("status") or "")
    data["rd_stage"] = _stage_value(data.get("rd_stage"))
    data["rd_stage_label"] = _STAGE_LABELS.get(data.get("rd_stage"), data.get("rd_stage") or "")
    data["start_date"] = data.get("capitalization_start_date")
    data["end_date"] = data.get("capitalization_end_date")
    return data


@frappe.whitelist()
def list_projects(search=None, status=None):
    require_rd_access(RD_PROJECT_MANAGE_ROLES)
    filters = {"rd_project_code": ["!=", ""]}
    if _clean(status):
        filters["status"] = _status_value(status)
    rows = frappe.get_all(
        "Project",
        filters=filters,
        fields=[
            "name", "project_name", "rd_project_code", "rd_project_key", "status", "rd_stage",
            "allow_rd_timesheet", "capitalization_start_date", "capitalization_end_date",
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
                str(row.get("english_name") or ""),
            ]).lower()
        ]
    return data


def _project_values(project_code, project_name, start_date=None, end_date=None, status="Open", rd_stage="费用化"):
    code = _clean(project_code)
    name = _clean(project_name)
    if not code or not name:
        frappe.throw(frappe._("请填写项目编号和项目名称。"))
    status_value = _status_value(status)
    stage_value = _stage_value(rd_stage)
    return {
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


def _save_project_doc(project_code, project_name, start_date=None, end_date=None, status="Open", name=None, rd_stage="费用化"):
    code = _clean(project_code)
    doc_name = _clean(name) or code
    values = _project_values(code, project_name, start_date, end_date, status, rd_stage)
    if frappe.db.exists("Project", doc_name):
        doc = frappe.get_doc("Project", doc_name)
        doc.update(values)
        doc.save(ignore_permissions=True)
        return doc.name
    doc = frappe.get_doc({"doctype": "Project", "name": doc_name, **values})
    doc.insert(ignore_permissions=True, set_name=doc_name)
    return doc.name


@frappe.whitelist(methods=["POST"])
def save_project(project_code, project_name, start_date=None, end_date=None, status="Open", name=None, english_name=None, rd_stage="费用化"):
    require_rd_access(RD_PROJECT_MANAGE_ROLES)
    project_name = _clean(project_name) or _clean(english_name)
    saved = _save_project_doc(project_code, project_name, start_date, end_date, status, name=name, rd_stage=rd_stage)
    frappe.db.commit()
    return {"name": saved}


@frappe.whitelist(methods=["POST"])
def cancel_project(name):
    require_rd_access(RD_PROJECT_MANAGE_ROLES)
    doc = frappe.get_doc("Project", name)
    doc.update({"status": "Cancelled", "allow_rd_timesheet": 0})
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


def ensure_default_projects():
    for item in DEFAULT_RAYHER_PROJECTS:
        _save_project_doc(**item)
    frappe.db.commit()
    return len(DEFAULT_RAYHER_PROJECTS)
