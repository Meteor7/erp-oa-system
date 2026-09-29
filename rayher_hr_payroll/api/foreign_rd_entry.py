import json
from calendar import monthrange
from datetime import date

import frappe

from rayher_hr_payroll.api._guards import (
    RD_FINANCE_ROLES, ensure_not_locked, parse_period, period_has_submitted_allocation, require_rd_access,
)
from rayher_hr_payroll.api.allocation_entry import STAGE_LABELS, _project_summaries
from rayher_hr_payroll.rd_cost.frappe_adapter import (
    foreign_commissioned_expense_rows,
    source_row_key_for_row,
    stage_for_period,
)

RD_FOREIGN_FINANCE_ROLES = (*RD_FINANCE_ROLES, "All Project Access")
MAX_DAILY_HOURS = 8
DEFAULT_FOREIGN_ENTITY = "QIHENG DEMO OVERSEAS"
# 没有境外工时可分的境外公共费用，在汇总和矩阵里单独列成这一"项目"，计入未判定（审查 X2-1，决定 D4）。
UNALLOCATED_COMMON_PROJECT = "\u672a\u5206\u644a\u5883\u5916\u516c\u5171\u8d39\u7528"

STAGE_ALIASES = {
    "capitalized": "capitalized", "Capitalized": "capitalized", "\u8d44\u672c\u5316": "capitalized",
    "expensed": "expensed", "Expensed": "expensed", "\u8d39\u7528\u5316": "expensed",
    "unknown": "unknown", "Unknown": "unknown", "\u672a\u5224\u5b9a": "unknown",
}


def _value(row, fieldname, default=None):
    if isinstance(row, dict):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def _set_value(row, fieldname, value):
    if isinstance(row, dict):
        row[fieldname] = value
    else:
        setattr(row, fieldname, value)


def _clean(value):
    return str(value or "").strip()


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        # 修复（2026-09-29，审查 17-d）：非数字原来直接抛 ValueError，页面上是 500。
        frappe.throw(frappe._("\u5883\u5916\u7814\u53d1\u6570\u5b57\u683c\u5f0f\u4e0d\u6b63\u786e\uff1a{0}").format(value))


def _money(value):
    return round(_number(value), 2)


def _normalize_stage(stage):
    return STAGE_ALIASES.get(_clean(stage), "unknown")


def _period_string(year, month):
    return f"{year:04d}-{month:02d}"


def _parse_work_date(value):
    text = _clean(value).replace("/", "-")
    if not text:
        frappe.throw(frappe._("\u8bf7\u586b\u5199\u5883\u5916\u5de5\u65f6\u65e5\u671f\u3002"))
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u65e5\u671f\u683c\u5f0f\u4e0d\u6b63\u786e\u3002"))


def _monthly_foreign_rows(rows, year, month):
    grouped = {}
    for row in rows or []:
        project = _clean(_value(row, "project"))
        if not project:
            continue
        entity = _clean(_value(row, "foreign_entity")) or DEFAULT_FOREIGN_ENTITY
        hours = _number(_value(row, "hours"))
        raw_days = _value(row, "occurrence_days", None)
        submitted_days = _number(raw_days) if raw_days not in (None, "") else 0.0
        has_monthly_days = submitted_days > 0
        occurrence_days = submitted_days if has_monthly_days else hours / MAX_DAILY_HOURS
        if has_monthly_days:
            hours = occurrence_days * MAX_DAILY_HOURS
        key = (entity, project)
        description = _clean(_value(row, "remark")) or _clean(_value(row, "description"))
        if key not in grouped:
            grouped[key] = {
                "foreign_entity": entity,
                "project": project,
                "project_code": _clean(_value(row, "project_code")) or project,
                "project_name": _clean(_value(row, "project_name")) or project,
                "work_date": f"{int(year):04d}-{int(month):02d}-01",
                "activity_type": _clean(_value(row, "activity_type")),
                "occurrence_days": 0.0,
                "hours": 0.0,
                "description": "",
            }
            saved_stage = _clean(_value(row, "project_stage"))
            if saved_stage:
                # 保存时的阶段快照，读取时沿用（修复 2026-09-29，审查 17-a）。
                grouped[key]["project_stage"] = saved_stage
        item = grouped[key]
        item["occurrence_days"] = item["occurrence_days"] + occurrence_days
        item["hours"] = round(item["hours"] + hours, 2)
        if description:
            descriptions = [part for part in item["description"].split("\uFF1B") if part]
            if description not in descriptions:
                descriptions.append(description)
            item["description"] = "\uFF1B".join(descriptions)
    return list(grouped.values())

def _foreign_project_info(project_names):
    names = sorted({name for name in project_names if name})
    if not names:
        return {}
    rows = frappe.get_all(
        "Project",
        filters={"name": ["in", names]},
        fields=["name", "project_name", "rd_project_code", "rd_stage",
                "capitalization_start_date", "capitalization_end_date"],
        limit_page_length=len(names),
    )
    return {_clean(_value(row, "name")): row for row in rows}


def _info_stage(info, year=None, month=None):
    """项目在某个月的研发阶段，和国内分摊同一个规则（frappe_adapter.stage_for_period）。

    修复（2026-09-29，审查 R3-48-2）：境外只看 rd_stage，国内在 rd_stage 为空或"未判定"时
    还会按起止日期判断，同一个项目两边可能分到不同阶段。现在都是：显式阶段优先，
    没有显式阶段时才看日期。日期字段在页面上是"立项时间/结项时间"，不是资本化窗口，
    所以不让日期盖过显式阶段。
    """
    if not info:
        return "unknown"
    explicit = _normalize_stage(_value(info, "rd_stage"))
    if explicit != "unknown" or not (year and month):
        return explicit
    return stage_for_period(
        {
            "capitalization_start_date": _value(info, "capitalization_start_date"),
            "capitalization_end_date": _value(info, "capitalization_end_date"),
        },
        year=int(year),
        month=int(month),
    )


def _project_code(info, project):
    return _clean(_value(info, "rd_project_code")) or _clean(_value(info, "name")) or project


def _project_name(info, project):
    return _clean(_value(info, "project_name")) or _clean(_value(info, "name")) or project


def _resolve_projects_from_identity(rows):
    project_names = set()
    unresolved = []
    for row in rows or []:
        project = _clean(_value(row, "project"))
        if project:
            project_names.add(project)
            continue
        has_content = bool(
            _clean(_value(row, "project_code"))
            or _clean(_value(row, "project_name"))
            or _clean(_value(row, "description"))
            or _number(_value(row, "hours"))
        )
        if has_content:
            unresolved.append(row)
    if not unresolved:
        return project_names

    catalog = frappe.get_all(
        "Project",
        filters={"allow_rd_timesheet": 1},
        fields=["name", "project_name", "rd_project_code", "rd_stage"],
        limit_page_length=1000,
    )
    for row in unresolved:
        code = _clean(_value(row, "project_code"))
        project_name = _clean(_value(row, "project_name"))
        if not code or not project_name:
            frappe.throw(frappe._("\u8bf7\u586b\u5199\u5883\u5916\u5de5\u65f6\u7684\u9879\u76ee\u4ee3\u7801\u548c\u9879\u76ee\u540d\u79f0\u3002"))
        matches = [
            item for item in catalog
            if _clean(_value(item, "rd_project_code")) == code and _clean(_value(item, "project_name")) == project_name
        ]
        if len(matches) > 1:
            frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u9879\u76ee\u4ee3\u7801\u548c\u540d\u79f0\u5339\u914d\u5230\u591a\u4e2a\u9879\u76ee\uff0c\u8bf7\u5148\u6e05\u7406\u9879\u76ee\u4e3b\u6570\u636e\u3002"))
        if not matches:
            frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u9879\u76ee\u4ee3\u7801\u548c\u540d\u79f0\u5fc5\u987b\u5339\u914d\u9879\u76ee\u7ba1\u7406\u4e2d\u7684\u53ef\u586b\u62a5\u9879\u76ee\u3002"))
        project = _clean(_value(matches[0], "name"))
        _set_value(row, "project", project)
        project_names.add(project)
    return project_names


def _validate_project_identity(row, info):
    canonical_code = _project_code(info, _clean(_value(info, "name")))
    canonical_name = _project_name(info, _clean(_value(info, "name")))
    submitted_code = _clean(_value(row, "project_code"))
    submitted_name = _clean(_value(row, "project_name"))
    if submitted_code and submitted_code != canonical_code:
        frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u9879\u76ee\u4ee3\u7801\u4e0e\u9879\u76ee\u4e0d\u5339\u914d\u3002"))
    if submitted_name and submitted_name != canonical_name:
        frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u9879\u76ee\u540d\u79f0\u4e0e\u9879\u76ee\u4e0d\u5339\u914d\u3002"))
    return canonical_code, canonical_name


def _foreign_expense_import_name(year, month):
    return frappe.db.get_value(
        "RD Expense Import",
        {"year": int(year), "month": int(month), "docstatus": ["<", 2]},
        "name",
        order_by="creation desc",
    )


def _foreign_expense_rows(year, month):
    name = _foreign_expense_import_name(year, month)
    if not name:
        return None, []
    doc = frappe.get_doc("RD Expense Import", name)
    return name, foreign_commissioned_expense_rows(list(doc.items or []))


def _foreign_expense_context_from_rows(rows, project_info=None, expense_import=None):
    project_info = project_info or {}
    common_amount = 0.0
    direct_amount = 0.0
    direct_amounts_by_project = {}
    expense_sources = []

    for row in foreign_commissioned_expense_rows(rows or []):
        amount = _money(_value(row, "amount"))
        direct_project = _clean(_value(row, "direct_project"))
        allocation_type = "project" if direct_project else "common"
        if direct_project:
            direct_amount += amount
            direct_amounts_by_project[direct_project] = _money(direct_amounts_by_project.get(direct_project, 0.0) + amount)
        else:
            common_amount += amount

        info = project_info.get(direct_project) if direct_project else None
        expense_sources.append({
            "expense_item": _clean(_value(row, "name")),
            "source_row_key": source_row_key_for_row(row),
            "voucher_no": _clean(_value(row, "voucher_no")),
            "account_level_1": _clean(_value(row, "account_level_1")),
            "account_level_2": _clean(_value(row, "account_level_2")),
            "account_level_3": _clean(_value(row, "account_level_3")),
            "account_level_4": _clean(_value(row, "account_level_4")),
            "amount": amount,
            "allocation_type": allocation_type,
            "direct_project": direct_project or None,
            "project_code": _project_code(info, direct_project) if info else direct_project,
            "project_name": _project_name(info, direct_project) if info else direct_project,
        })

    common_amount = _money(common_amount)
    direct_amount = _money(direct_amount)
    return {
        "expense_import": expense_import,
        "total_amount": _money(common_amount + direct_amount),
        "common_amount": common_amount,
        "direct_amount": direct_amount,
        "direct_amounts_by_project": direct_amounts_by_project,
        "expense_sources": expense_sources,
    }


def _foreign_expense_context(year, month):
    expense_import, rows = _foreign_expense_rows(year, month)
    direct_projects = {_clean(_value(row, "direct_project")) for row in rows if _clean(_value(row, "direct_project"))}
    return _foreign_expense_context_from_rows(rows, _foreign_project_info(direct_projects), expense_import=expense_import)


def _allocate_foreign_rows(common_amount, rows, project_info, direct_amounts_by_project=None, year=None, month=None, strict=True):
    """按工时比例分境外公共费用。

    strict=True 是保存路径：项目必须存在、代码和名称必须和项目一致，阶段按当前项目算。
    修复（2026-09-29，审查 R3-51-1 / 17-a）：读取路径传 strict=False——项目改名、改编码或被删后，
    已保存的境外工时照样能显示（原来整月、整年的境外页面和分摊页面都会报错）；
    代码、名称和阶段用保存时的值，和国内已提交分摊一样是快照。
    """
    prepared = []
    for row in rows or []:
        project = _clean(_value(row, "project"))
        raw_days = _value(row, "occurrence_days", None)
        is_monthly = raw_days not in (None, "")
        occurrence_days = _number(raw_days) if is_monthly else 0.0
        hours = occurrence_days * MAX_DAILY_HOURS if is_monthly else _number(_value(row, "hours"))
        description = _clean(_value(row, "remark")) or _clean(_value(row, "description"))
        has_content = bool(project or _clean(_value(row, "project_code")) or _clean(_value(row, "project_name")) or _clean(_value(row, "activity_type")) or description or hours)
        if not has_content:
            continue
        if not project:
            frappe.throw(frappe._("\u8bf7\u9009\u62e9\u5883\u5916\u5de5\u65f6\u7684\u9879\u76ee\u3002"))
        if is_monthly:
            work_day = date(int(year), int(month), 1) if year and month else _parse_work_date(_value(row, "work_date"))
            activity_type = _clean(_value(row, "activity_type"))
        else:
            work_day = _parse_work_date(_value(row, "work_date"))
            if year and month and (work_day.year != int(year) or work_day.month != int(month)):
                frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u65e5\u671f\u5fc5\u987b\u5728\u5f53\u524d\u4f1a\u8ba1\u671f\u95f4\u5185\u3002"))
            activity_type = _clean(_value(row, "activity_type"))
            if not activity_type:
                frappe.throw(frappe._("\u8bf7\u9009\u62e9\u5883\u5916\u5de5\u65f6\u7684\u6d3b\u52a8\u7c7b\u578b\u3002"))
            if not description:
                frappe.throw(frappe._("\u8bf7\u586b\u5199\u5883\u5916\u5de5\u65f6\u7684\u5de5\u4f5c\u5185\u5bb9\u3002"))
        if hours <= 0:
            frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u5fc5\u987b\u5927\u4e8e 0\u3002"))
        if not is_monthly and hours > MAX_DAILY_HOURS:
            frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u5355\u65e5\u4e0d\u80fd\u8d85\u8fc7 8 \u5c0f\u65f6\u3002"))
        # 修复（2026-09-29，审查 17-d，决定 D13）：发生天数不能超过当月自然日数，和国内一致。
        if strict and is_monthly and year and month and occurrence_days > monthrange(int(year), int(month))[1]:
            frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u53d1\u751f\u5929\u6570\u4e0d\u80fd\u8d85\u8fc7\u6240\u9009\u6708\u4efd\u7684\u81ea\u7136\u65e5\u5929\u6570\u3002"))
        info = project_info.get(project)
        if strict:
            if not info:
                frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u9879\u76ee {0} \u4e0d\u5b58\u5728\u6216\u672a\u542f\u7528\u3002").format(project))
            project_code, project_name = _validate_project_identity(row, info)
            stage = _info_stage(info, year, month)
        else:
            project_code = _clean(_value(row, "project_code")) or (_project_code(info, project) if info else project)
            project_name = _clean(_value(row, "project_name")) or (_project_name(info, project) if info else project)
            saved_stage = _clean(_value(row, "project_stage"))
            stage = _normalize_stage(saved_stage) if saved_stage else _info_stage(info, year, month)
        prepared_row = {"project": project, "project_code": project_code, "project_name": project_name, "project_stage": stage, "stage_label": STAGE_LABELS.get(stage, STAGE_LABELS["unknown"]), "work_date": work_day.isoformat(), "activity_type": activity_type, "hours": float(hours), "description": description}
        if is_monthly:
            prepared_row["foreign_entity"] = _clean(_value(row, "foreign_entity")) or DEFAULT_FOREIGN_ENTITY
            prepared_row["occurrence_days"] = round(occurrence_days, 5)
        prepared.append(prepared_row)

    total_hours = sum(row["hours"] for row in prepared)
    common_amount = _money(common_amount)
    if common_amount < 0:
        frappe.throw(frappe._("\u5883\u5916\u59d4\u6258\u7814\u53d1\u516c\u5171\u8d39\u7528\u4e0d\u80fd\u4e3a\u8d1f\u6570\u3002"))
    if common_amount > 0 and total_hours <= 0:
        frappe.throw(frappe._("\u6709\u5883\u5916\u516c\u5171\u8d39\u7528\u65f6\uff0c\u5fc5\u987b\u5f55\u5165\u81f3\u5c11\u4e00\u6761\u5de5\u65f6\u3002"))
    direct_remaining = {project: _money(amount) for project, amount in (direct_amounts_by_project or {}).items()}
    running = 0.0
    for index, row in enumerate(prepared):
        row["ratio"] = round(row["hours"] / total_hours * 100, 2) if total_hours else 0.0
        if common_amount and index == len(prepared) - 1:
            common_allocated = _money(common_amount - running)
        else:
            common_allocated = _money(common_amount * row["hours"] / total_hours) if total_hours else 0.0
            running += common_allocated
        direct_allocated = _money(direct_remaining.pop(row["project"], 0.0))
        row["common_allocated_amount"] = common_allocated
        row["direct_allocated_amount"] = direct_allocated
        row["allocated_amount"] = _money(common_allocated + direct_allocated)
    return prepared

def _serialize_line(line):
    stage = _normalize_stage(_value(line, "project_stage"))
    project = _clean(_value(line, "project"))
    allocated = _money(_value(line, "allocated_amount"))
    common_raw = _value(line, "common_allocated_amount", None)
    direct_raw = _value(line, "direct_allocated_amount", None)
    if common_raw is None and direct_raw is None:
        common_amount = allocated
        direct_amount = 0.0
    else:
        common_amount = _money(common_raw)
        direct_amount = _money(direct_raw)
    return {
        "project": project,
        "project_code": _clean(_value(line, "project_code")) or project,
        "project_name": _clean(_value(line, "project_name")) or project,
        "project_stage": stage,
        "stage_label": STAGE_LABELS.get(stage, STAGE_LABELS["unknown"]),
        "foreign_entity": _clean(_value(line, "foreign_entity")) or DEFAULT_FOREIGN_ENTITY,
        "work_date": _clean(_value(line, "work_date")),
        "activity_type": _clean(_value(line, "activity_type")),
        "occurrence_days": _number(_value(line, "occurrence_days")) if _value(line, "occurrence_days", None) not in (None, "") else None,
        "hours": _number(_value(line, "hours")),
        "ratio": _number(_value(line, "ratio")),
        "common_allocated_amount": common_amount,
        "direct_allocated_amount": direct_amount,
        "allocated_amount": _money(common_amount + direct_amount),
        "description": _clean(_value(line, "description")),
    }


def _summary_seed(project, project_info, year=None, month=None):
    info = project_info.get(project)
    stage = _info_stage(info, year, month)
    return {
        "project": project,
        "project_code": _project_code(info, project) if info else project,
        "project_name": _project_name(info, project) if info else project,
        "project_stage": stage,
        "stage_label": STAGE_LABELS.get(stage, STAGE_LABELS["unknown"]),
        "hours": 0.0,
        "ratio": 0.0,
        "common_allocated_amount": 0.0,
        "direct_allocated_amount": 0.0,
        "allocated_amount": 0.0,
        "line_count": 0,
    }


def _foreign_project_summaries(lines, direct_amounts_by_project=None, project_info=None, year=None, month=None):
    project_info = project_info or {}
    grouped = {}
    for line in lines or []:
        row = _serialize_line(line)
        key = (row["project"], row["project_stage"])
        target = grouped.setdefault(key, {
            "project": row["project"], "project_code": row["project_code"], "project_name": row["project_name"],
            "project_stage": row["project_stage"], "stage_label": row["stage_label"],
            "hours": 0.0, "ratio": 0.0, "common_allocated_amount": 0.0,
            "direct_allocated_amount": 0.0, "allocated_amount": 0.0, "line_count": 0,
        })
        target["hours"] += row["hours"]
        target["common_allocated_amount"] += row["common_allocated_amount"]
        target["direct_allocated_amount"] += row["direct_allocated_amount"]
        target["allocated_amount"] += row["allocated_amount"]
        target["line_count"] += 1

    direct_amounts_by_project = direct_amounts_by_project or {}
    current_direct_by_project = {}
    for row in grouped.values():
        current_direct_by_project[row["project"]] = current_direct_by_project.get(row["project"], 0.0) + row["direct_allocated_amount"]
    for project, amount in direct_amounts_by_project.items():
        missing = _money(amount - current_direct_by_project.get(project, 0.0))
        if not missing:
            continue
        info = project_info.get(project)
        stage = _info_stage(info, year, month)
        key = (project, stage)
        target = grouped.setdefault(key, _summary_seed(project, project_info, year, month))
        target["direct_allocated_amount"] += missing
        target["allocated_amount"] += missing

    total_hours = sum(row["hours"] for row in grouped.values())
    data = []
    for row in grouped.values():
        row["hours"] = round(row["hours"], 2)
        row["common_allocated_amount"] = _money(row["common_allocated_amount"])
        row["direct_allocated_amount"] = _money(row["direct_allocated_amount"])
        row["allocated_amount"] = _money(row["allocated_amount"])
        row["ratio"] = round(row["hours"] / total_hours * 100, 2) if total_hours else 0.0
        data.append(row)
    return sorted(data, key=lambda row: (row["project_code"], row["project_stage"]))


def _stage_summaries_from_projects(rows, amount_key="allocated_amount"):
    totals = {stage: 0.0 for stage in STAGE_LABELS}
    for row in rows or []:
        stage = _normalize_stage(_value(row, "project_stage"))
        totals[stage] += _number(_value(row, amount_key))
    return [
        {"stage": stage, "label": STAGE_LABELS[stage], "total": _money(totals[stage])}
        for stage in ("capitalized", "expensed", "unknown")
    ]


def _combined_project_summaries(domestic, foreign):
    grouped = {}

    def target_for(row):
        stage = _normalize_stage(_value(row, "project_stage"))
        project = _clean(_value(row, "project"))
        key = (project, stage)
        return grouped.setdefault(key, {
            "project": project,
            "project_code": _clean(_value(row, "project_code")) or project,
            "project_name": _clean(_value(row, "project_name")) or project,
            "project_stage": stage,
            "stage_label": STAGE_LABELS.get(stage, STAGE_LABELS["unknown"]),
            "domestic_amount": 0.0,
            "foreign_amount": 0.0,
            "total_amount": 0.0,
            "domestic_hours": 0.0,
            "foreign_hours": 0.0,
        })

    for row in domestic or []:
        target = target_for(row)
        target["domestic_amount"] += _number(_value(row, "allocated_amount"))
        target["domestic_hours"] += _number(_value(row, "basis_hours"))
    for row in foreign or []:
        target = target_for(row)
        target["foreign_amount"] += _number(_value(row, "allocated_amount"))
        target["foreign_hours"] += _number(_value(row, "hours"))
    result = []
    for row in grouped.values():
        row["domestic_amount"] = _money(row["domestic_amount"])
        row["foreign_amount"] = _money(row["foreign_amount"])
        row["total_amount"] = _money(row["domestic_amount"] + row["foreign_amount"])
        row["domestic_hours"] = round(row["domestic_hours"], 2)
        row["foreign_hours"] = round(row["foreign_hours"], 2)
        result.append(row)
    return sorted(result, key=lambda row: (row["project_code"], row["project_stage"]))


def _combined_stage_summaries(domestic, foreign):
    totals = {stage: {"domestic_total": 0.0, "foreign_total": 0.0} for stage in STAGE_LABELS}
    for row in domestic or []:
        totals[_normalize_stage(_value(row, "project_stage"))]["domestic_total"] += _number(_value(row, "allocated_amount"))
    for row in foreign or []:
        totals[_normalize_stage(_value(row, "project_stage"))]["foreign_total"] += _number(_value(row, "allocated_amount"))
    result = []
    for stage in ("capitalized", "expensed", "unknown"):
        domestic_total = _money(totals[stage]["domestic_total"])
        foreign_total = _money(totals[stage]["foreign_total"])
        result.append({
            "stage": stage,
            "label": STAGE_LABELS[stage],
            "domestic_total": domestic_total,
            "foreign_total": foreign_total,
            "total": _money(domestic_total + foreign_total),
        })
    return result


def _domestic_project_summaries(year, month):
    name = frappe.db.get_value(
        "RD Cost Allocation",
        {"year": year, "month": month, "docstatus": 1},
        "name",
        order_by="creation desc",
    )
    return _project_summaries(name) if name else []


def _foreign_doc_name(year, month):
    return frappe.db.get_value(
        "Foreign RD Expense",
        {"year": year, "month": month, "docstatus": ["<", 2]},
        "name",
        order_by="creation desc",
    )


def _response(period, year, month, domestic_projects, expense_context, name=None, status="Draft", lines=None, saved_total=None):
    lines = lines or []
    project_names = {row["project"] for row in lines if row.get("project")}
    project_names.update(expense_context.get("direct_amounts_by_project", {}).keys())
    project_info = _foreign_project_info(project_names)
    if lines:
        allocated_lines = _allocate_foreign_rows(
            expense_context["common_amount"],
            lines,
            project_info,
            direct_amounts_by_project=expense_context.get("direct_amounts_by_project"),
            year=year,
            month=month,
            strict=False,
        )
    else:
        allocated_lines = []
    foreign_projects = _foreign_project_summaries(
        allocated_lines,
        direct_amounts_by_project=expense_context.get("direct_amounts_by_project"),
        project_info=project_info,
        year=year,
        month=month,
    )
    unallocated_common = expense_context["common_amount"] if expense_context["common_amount"] and not allocated_lines else 0.0
    if _money(unallocated_common):
        # 修复（2026-09-29，审查 X2-1，决定 D4）：没有境外工时时，公共费用原来只在本页黄条里出现，
        # 分摊页、全年、看板、导出的合计都少这笔钱。现在单列一行，计入未判定，合计和导入单对得上。
        foreign_projects.append({
            "project": UNALLOCATED_COMMON_PROJECT, "project_code": UNALLOCATED_COMMON_PROJECT,
            "project_name": UNALLOCATED_COMMON_PROJECT, "project_stage": "unknown",
            "stage_label": STAGE_LABELS["unknown"], "hours": 0.0, "ratio": 0.0,
            "common_allocated_amount": _money(unallocated_common), "direct_allocated_amount": 0.0,
            "allocated_amount": _money(unallocated_common), "line_count": 0,
        })
    # 修复（2026-09-29，审查 R3-48-3，决定 D5）：读取时按最新导入重算；保存后导入变了要提示重新保存。
    stale = bool(name and saved_total is not None and _money(saved_total) != _money(expense_context["total_amount"]))
    return {
        "name": name,
        "period": period,
        "year": year,
        "month": month,
        "status": status,
        "expense_import": expense_context.get("expense_import"),
        "total_amount": _money(expense_context["total_amount"]),
        "common_amount": _money(expense_context["common_amount"]),
        "direct_amount": _money(expense_context["direct_amount"]),
        "unallocated_common_amount": _money(unallocated_common),
        "stale": stale,
        "saved_total_amount": _money(saved_total) if saved_total is not None else None,
        "expense_sources": expense_context.get("expense_sources", []),
        "total_hours": round(sum(row["hours"] for row in allocated_lines), 2),
        "lines": allocated_lines,
        "foreign_project_summaries": foreign_projects,
        "foreign_stage_summaries": _stage_summaries_from_projects(foreign_projects),
        "domestic_project_summaries": domestic_projects,
        "combined_project_summaries": _combined_project_summaries(domestic_projects, foreign_projects),
        "combined_stage_summaries": _combined_stage_summaries(domestic_projects, foreign_projects),
    }


def _get_foreign_rd_month(year, month):
    period_text = _period_string(year, month)
    domestic_projects = _domestic_project_summaries(year, month)
    expense_context = _foreign_expense_context(year, month)
    name = _foreign_doc_name(year, month)
    if not name:
        return _response(period_text, year, month, domestic_projects, expense_context)
    doc = frappe.get_doc("Foreign RD Expense", name)
    lines = _monthly_foreign_rows([_serialize_line(line) for line in (doc.lines or [])], year, month)
    return _response(period_text, year, month, domestic_projects, expense_context, name=doc.name, status=doc.status, lines=lines,
                     saved_total=_value(doc, "total_amount"))


def _get_foreign_rd_year(year):
    months = [_get_foreign_rd_month(year, month) for month in range(1, 13)]
    lines = []
    expense_sources = []
    for payload in months:
        for line in payload.get("lines", []):
            line = dict(line)
            line["period"] = payload.get("period")
            lines.append(line)
        for source in payload.get("expense_sources", []):
            source = dict(source)
            source["period"] = payload.get("period")
            expense_sources.append(source)
    total_amount = _money(sum(_number(payload.get("total_amount")) for payload in months))
    common_amount = _money(sum(_number(payload.get("common_amount")) for payload in months))
    direct_amount = _money(sum(_number(payload.get("direct_amount")) for payload in months))
    unallocated_common = _money(sum(_number(payload.get("unallocated_common_amount")) for payload in months))
    total_hours = round(sum(_number(line.get("hours")) for line in lines), 2)
    return {
        "name": None,
        "period": str(year),
        "year": year,
        "month": None,
        "scope": "year",
        "status": "Yearly",
        "expense_import": None,
        "total_amount": total_amount,
        "common_amount": common_amount,
        "direct_amount": direct_amount,
        "unallocated_common_amount": unallocated_common,
        "expense_sources": expense_sources,
        "total_hours": total_hours,
        "lines": lines,
    }


@frappe.whitelist()
def get_foreign_rd(period, scope="month"):
    require_rd_access(RD_FOREIGN_FINANCE_ROLES)
    year, month = parse_period(period)
    if str(scope or "month") == "year":
        return _get_foreign_rd_year(year)
    payload = _get_foreign_rd_month(year, month)
    # 本期国内分摊已提交时境外工时冻结（修复 2026-09-29），页面据此禁用保存。
    payload["allocation_submitted"] = bool(
        frappe.db.exists("RD Cost Allocation", {"year": year, "month": month, "docstatus": 1})
    )
    return payload


@frappe.whitelist(methods=["POST"])
def save_foreign_rd(period, total_amount=0, rows=None):
    require_rd_access(RD_FOREIGN_FINANCE_ROLES)
    year, month = parse_period(period)
    period_text = _period_string(year, month)
    ensure_not_locked(period_text, "lock_allocations", "\u5206\u644a")
    # 修复（2026-09-29，审查 R3-48-3，决定 D5）：国内分摊提交后导入单就冻结了，境外工时原来还能改，
    # 合计跟着变。现在和国内工时一样：先撤销分摊才能改。锁住期间导入单后当前读，和分摊提交互斥。
    if period_has_submitted_allocation(year, month):
        frappe.throw(frappe._("\u672c\u671f\u56fd\u5185\u7814\u53d1\u8d39\u7528\u5206\u644a\u5df2\u63d0\u4ea4\uff0c\u5883\u5916\u5de5\u65f6\u4e0d\u80fd\u518d\u4fee\u6539\uff0c\u8bf7\u5148\u64a4\u9500\u5206\u644a\u3002"))
    if isinstance(rows, str):
        try:
            rows = json.loads(rows or "[]")
        except ValueError:
            frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u6570\u636e\u683c\u5f0f\u4e0d\u6b63\u786e\u3002"))
    rows = rows or []
    if not isinstance(rows, list):
        frappe.throw(frappe._("\u5883\u5916\u5de5\u65f6\u6570\u636e\u683c\u5f0f\u4e0d\u6b63\u786e\u3002"))
    expense_context = _foreign_expense_context(year, month)
    project_names = _resolve_projects_from_identity(rows)
    project_names.update(expense_context.get("direct_amounts_by_project", {}).keys())
    allocated = _allocate_foreign_rows(
        expense_context["common_amount"],
        rows,
        _foreign_project_info(project_names),
        direct_amounts_by_project=expense_context.get("direct_amounts_by_project"),
        year=year,
        month=month,
    )
    name = _foreign_doc_name(year, month)
    calculated = bool(allocated or expense_context["total_amount"])
    if name:
        doc = frappe.get_doc("Foreign RD Expense", name)
        doc.total_amount = _money(expense_context["total_amount"])
        doc.total_hours = round(sum(row["hours"] for row in allocated), 2)
        doc.status = "Calculated" if calculated else "Draft"
        doc.set("lines", [])
    else:
        doc = frappe.get_doc({
            "doctype": "Foreign RD Expense",
            "period": period_text,
            "year": year,
            "month": month,
            "total_amount": _money(expense_context["total_amount"]),
            "total_hours": round(sum(row["hours"] for row in allocated), 2),
            "status": "Calculated" if calculated else "Draft",
            "lines": [],
        })
    for row in allocated:
        doc.append("lines", {
            "foreign_entity": row.get("foreign_entity", DEFAULT_FOREIGN_ENTITY),
            "occurrence_days": row.get("occurrence_days", round(row["hours"] / MAX_DAILY_HOURS, 2)),
            "work_date": row["work_date"],
            "activity_type": row["activity_type"],
            "project": row["project"],
            "project_code": row["project_code"],
            "project_name": row["project_name"],
            "project_stage": row["project_stage"],
            "hours": row["hours"],
            "ratio": row["ratio"],
            "common_allocated_amount": row["common_allocated_amount"],
            "direct_allocated_amount": row["direct_allocated_amount"],
            "allocated_amount": row["allocated_amount"],
            "description": row["description"],
        })
    if getattr(doc, "is_new", lambda: True)():
        try:
            doc.insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            frappe.throw(frappe._("\u8be5\u6708\u4efd\u5883\u5916\u7814\u53d1\u5de5\u65f6\u5df2\u88ab\u5176\u4ed6\u7528\u6237\u4fdd\u5b58\uff0c\u8bf7\u5237\u65b0\u9875\u9762\u540e\u91cd\u8bd5\u3002"))
    else:
        doc.save(ignore_permissions=True)
    frappe.db.commit()
    return get_foreign_rd(period_text)


@frappe.whitelist()
def get_foreign_project_options():
    """境外研发页面的项目下拉（修复 2026-09-29）。

    页面原来调工时模块的 get_rd_options，要求工时查看角色；只有 All Project Access 的账号
    能进境外页面，却拿不到项目列表。这里按境外页面自己的角色取同样的项目。
    """
    require_rd_access(RD_FOREIGN_FINANCE_ROLES)
    return {
        "projects": frappe.get_all(
            "Project", filters={"allow_rd_timesheet": 1, "status": ["not in", ["Completed", "Cancelled"]]},
            fields=["name", "project_name", "rd_project_code", "rd_project_key"], order_by="project_name",
        ),
    }
