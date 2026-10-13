import re

import frappe

from rayher_hr_payroll.api._guards import (
    lock_period_import, period_has_submitted_allocation, require_rd_access, parse_period, ensure_not_locked,
    RD_FINANCE_ROLES,
)

# 预览 + 定版：没有定版（已提交）分摊单的月份，页面显示按当前数据现算的只读预览；
# 只有财务主管 / System Manager / Administrator 能定版、撤销定版。
FINALIZE_POSITION_KEY = "finance_manager"
PREVIEW_STATUS = "预览"
FINALIZE_DENIED = "只有财务主管可以定版本月分摊。"
CANCEL_DENIED = "只有财务主管可以撤销定版。"
ALREADY_FINALIZED = "本月分摊已定版。要重新定版，请先撤销定版。"
# 总经理、副总经理岗位可以只读分摊数据（决定 2026-10-13）：数据看板上研发分摊的数字点进去能打开。
# 只放开读（get_allocation、get_allocation_dashboard）；定版、撤销定版、定版检查仍只给财务。
LEADER_READ_POSITIONS = ("vice_manager", "general_manager")


def _is_leader_reader():
    from rayher_hr_payroll.position_access import position_users

    user = str(getattr(getattr(frappe, "session", None), "user", "") or "").strip().lower()
    return bool(user) and user in {str(name).lower() for name in (position_users(*LEADER_READ_POSITIONS) or [])}


def _require_read_access():
    """读分摊数据：财务角色（Accounts User / System Manager），或总经理、副总经理岗位（只读）。
    财务照旧走 require_rd_access；没有财务角色的人，只有岗位是总经理、副总经理才放行。"""
    if not set(frappe.get_roles() or []) & set(RD_FINANCE_ROLES) and _is_leader_reader():
        return
    require_rd_access(RD_FINANCE_ROLES)


STAGE_LABELS = {
    "capitalized": "\u8d44\u672c\u5316",
    "expensed": "\u8d39\u7528\u5316",
    "unknown": "\u672a\u5224\u5b9a",
}

DASHBOARD_MODE_LABELS = {
    "all": "\u6c47\u603b",
    "capitalized": STAGE_LABELS["capitalized"],
    "expensed": STAGE_LABELS["expensed"],
}


def _value(row, fieldname, default=None):
    if isinstance(row, dict):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def _stage_summary_values(capitalized, expensed, unknown):
    return [
        {"stage": "capitalized", "label": STAGE_LABELS["capitalized"], "total": capitalized},
        {"stage": "expensed", "label": STAGE_LABELS["expensed"], "total": expensed},
        {"stage": "unknown", "label": STAGE_LABELS["unknown"], "total": unknown},
    ]


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _clean(value):
    return str(value or "").strip()


def _money(value):
    return round(_number(value), 2)


def _normalize_stage(stage):
    text = _clean(stage)
    aliases = {
        "capitalized": "capitalized",
        "Capitalized": "capitalized",
        "\u8d44\u672c\u5316": "capitalized",
        "expensed": "expensed",
        "Expensed": "expensed",
        "\u8d39\u7528\u5316": "expensed",
        "unknown": "unknown",
        "Unknown": "unknown",
        "\u672a\u5224\u5b9a": "unknown",
    }
    return aliases.get(text, "unknown")


def _dashboard_mode(mode):
    mode = _clean(mode or "all")
    return mode if mode in DASHBOARD_MODE_LABELS else "all"


def _zero_stage_totals():
    return {"capitalized": 0.0, "expensed": 0.0, "unknown": 0.0}


def _foreign_period_state(year, month):
    from rayher_hr_payroll.api import foreign_rd_entry

    payload = foreign_rd_entry._get_foreign_rd_month(int(year), int(month))
    totals = _zero_stage_totals()
    for row in payload.get("foreign_stage_summaries", []) or []:
        stage = _value(row, "stage") or "unknown"
        if stage not in totals:
            stage = "unknown"
        totals[stage] += _number(_value(row, "total"))
    has_foreign_data = bool(payload.get("expense_sources") or payload.get("lines"))
    return totals, has_foreign_data


def _foreign_stage_totals(year, month):
    totals, _has_foreign_data = _foreign_period_state(year, month)
    return totals


def _add_foreign_totals(capitalized, expensed, unknown, foreign_totals):
    return (
        _number(capitalized) + _number(foreign_totals.get("capitalized")),
        _number(expensed) + _number(foreign_totals.get("expensed")),
        _number(unknown) + _number(foreign_totals.get("unknown")),
    )


def _stage_summaries(doc):
    return _stage_summary_values(doc.capitalized_total, doc.expensed_total, doc.unknown_total)


def _project_info(project_names):
    if not project_names:
        return {}
    rows = frappe.get_all(
        "Project",
        filters={"name": ["in", sorted(project_names)]},
        fields=["name", "project_name", "rd_project_code"],
        limit_page_length=len(project_names),
    )
    return {str(_value(row, "name")): row for row in rows}


def _project_summaries(allocation):
    """已定版分摊单：数据库按项目、阶段汇总，再交给 _summaries_from_rows 生成页面行。"""
    rows = frappe.get_all(
        "RD Cost Allocation Line",
        filters={"parent": allocation},
        fields=[
            "project",
            "project_stage",
            "sum(allocated_amount) as allocated_amount",
            "max(basis_hours) as basis_hours",
            "max(ratio) as ratio",
            "count(name) as line_count",
        ],
        group_by="project, project_stage",
        order_by="project",
    )
    return _summaries_from_rows(rows)


def _aggregate_line_rows(lines):
    """内存里的分摊明细（预览）按项目、阶段汇总，口径和上面的 SQL 一致：金额求和，工时、占比取最大，行数计数。"""
    groups = {}
    for line in lines or []:
        project = str(_value(line, "project") or "")
        stage = _value(line, "project_stage") or "unknown"
        group = groups.setdefault((project, stage), {
            "project": project, "project_stage": stage,
            "allocated_amount": 0.0, "basis_hours": 0.0, "ratio": 0.0, "line_count": 0,
        })
        group["allocated_amount"] += _number(_value(line, "allocated_amount"))
        group["basis_hours"] = max(group["basis_hours"], _number(_value(line, "basis_hours")))
        group["ratio"] = max(group["ratio"], _number(_value(line, "ratio")))
        group["line_count"] += 1
    rows = [groups[key] for key in sorted(groups)]
    for row in rows:
        row["allocated_amount"] = _money(row["allocated_amount"])
    return rows


def _project_summaries_from_lines(lines):
    return _summaries_from_rows(_aggregate_line_rows(lines))


def _summaries_from_rows(rows):
    """按项目、阶段汇总后的行 -> 页面的项目汇总（已定版和预览共用）。"""
    projects = _project_info({str(_value(row, "project")) for row in rows if _value(row, "project")})
    summaries = []
    for row in rows:
        project = str(_value(row, "project") or "")
        info = projects.get(project, {})
        stage = _value(row, "project_stage") or "unknown"
        summaries.append({
            "project": project,
            "project_code": _value(info, "rd_project_code") or project,
            "project_name": _value(info, "project_name") or project,
            "project_stage": stage,
            "stage_label": STAGE_LABELS.get(stage, "???"),
            "basis_hours": _value(row, "basis_hours") or 0,
            "ratio": _value(row, "ratio") or 0,
            "allocated_amount": _value(row, "allocated_amount") or 0,
            "line_count": _value(row, "line_count") or 0,
        })
    return summaries


def _allocation_count_lines(row):
    lines = _value(row, "lines", []) or []
    try:
        return len(lines)
    except TypeError:
        return 0


def _year_allocation(period):
    year, _month = parse_period(period)
    rows = frappe.get_all(
        "RD Cost Allocation",
        filters={"year": year, "docstatus": 1},
        fields=["name", "status", "capitalized_total", "expensed_total", "unknown_total"],
        order_by="month asc, creation desc",
    )
    allocation_names = [_value(row, "name") for row in rows if _value(row, "name")]
    line_count = 0
    if allocation_names:
        line_count = len(frappe.get_all(
            "RD Cost Allocation Line",
            filters={"parent": ["in", allocation_names]},
            pluck="name",
            limit_page_length=0,
        ))
    capitalized = sum(_value(row, "capitalized_total") or 0 for row in rows)
    expensed = sum(_value(row, "expensed_total") or 0 for row in rows)
    unknown = sum(_value(row, "unknown_total") or 0 for row in rows)
    foreign_totals = _zero_stage_totals()
    has_domestic_data = bool(allocation_names)
    has_foreign_data = False
    for month in range(1, 13):
        month_totals, month_has_foreign_data = _foreign_period_state(year, month)
        has_foreign_data = has_foreign_data or month_has_foreign_data
        for stage in foreign_totals:
            foreign_totals[stage] += _number(month_totals.get(stage))
    capitalized, expensed, unknown = _add_foreign_totals(capitalized, expensed, unknown, foreign_totals)
    return {
        "name": None,
        "period": str(year),
        "scope": "year",
        "status": "Yearly" if rows else None,
        "has_data": has_domestic_data or has_foreign_data,
        "has_domestic_data": has_domestic_data,
        "has_foreign_data": has_foreign_data,
        "allocation_names": allocation_names,
        "capitalized": capitalized,
        "expensed": expensed,
        "unknown": unknown,
        "lines": line_count,
        "stage_summaries": _stage_summary_values(capitalized, expensed, unknown),
    }


def _allocation_dashboard_context(period, scope):
    year, month = parse_period(period)
    if str(scope or "month") == "year":
        rows = frappe.get_all(
            "RD Cost Allocation",
            filters={"year": year, "docstatus": 1},
            fields=["name", "year", "month"],
            order_by="month asc, creation desc",
            limit_page_length=500,
        )
        names = [_value(row, "name") for row in rows if _value(row, "name")]
        period_by_parent = {
            _value(row, "name"): (int(_value(row, "year") or year), int(_value(row, "month") or 0))
            for row in rows
            if _value(row, "name")
        }
        periods = sorted({(y, m) for y, m in period_by_parent.values() if y and m})
        return {
            "period": str(year),
            "scope": "year",
            "year": year,
            "month": None,
            "allocation_names": names,
            "period_by_parent": period_by_parent,
            "foreign_periods": [(year, m) for m in range(1, 13)],
        }

    name = frappe.db.get_value(
        "RD Cost Allocation",
        {"year": year, "month": month, "docstatus": 1},
        "name",
        order_by="creation desc",
    )
    names = [name] if name else []
    return {
        "period": period,
        "scope": "month",
        "year": year,
        "month": month,
        "allocation_names": names,
        "period_by_parent": {name: (year, month)} if name else {},
        "foreign_periods": [(year, month)],
    }


def _parent_filter(names):
    return names[0] if len(names) == 1 else ["in", names]


def _most_specific_dashboard_account(row):
    for fieldname in ("account_level_4", "account_level_3", "account_level_2", "account_level_1", "expense_item"):
        value = _clean(_value(row, fieldname))
        if value:
            return value
    return ""


def _snapshot_lookup(rows):
    lookup = {}
    for row in rows or []:
        parent = _clean(_value(row, "parent"))
        voucher = _clean(_value(row, "voucher_no"))
        if not parent or not voucher:
            continue
        for account in {_clean(_value(row, "expense_item")), _most_specific_dashboard_account(row)}:
            if account:
                lookup.setdefault((parent, voucher, account), row)
    return lookup


def _with_snapshot_accounts(line, snapshots, period_by_parent):
    parent = _clean(_value(line, "parent"))
    voucher = _clean(_value(line, "voucher_no"))
    item = _clean(_value(line, "expense_item_name"))
    snapshot = snapshots.get((parent, voucher, item))
    year, month = period_by_parent.get(parent, (None, None))
    level_3 = _clean(_value(line, "account_level_3")) or _clean(_value(snapshot, "account_level_3"))
    level_4 = _clean(_value(line, "account_level_4")) or _clean(_value(snapshot, "account_level_4"))
    level_2 = _clean(_value(snapshot, "account_level_2"))
    # 工资单人工费和人事的单位社保、公积金都归"人员人工费用"（修复 2026-09-29）。
    if not level_2 and level_3 in ("\u4eba\u5de5\u8d39", "\u793e\u4f1a\u4fdd\u9669\u8d39\u7528\uff08\u5355\u4f4d\uff09", "\u4f4f\u623f\u516c\u79ef\u91d1\uff08\u5355\u4f4d\uff09"):
        level_2 = "\u4eba\u5458\u4eba\u5de5\u8d39\u7528"
    level_1 = _clean(_value(snapshot, "account_level_1")) or ("\u7814\u53d1\u8d39\u7528" if level_2 or level_3 else "")
    return {
        "parent": parent,
        "period": "%04d-%02d" % (int(year), int(month)) if year and month else "",
        "year": year,
        "month": month,
        "voucher_no": voucher,
        "expense_item_name": item or level_4 or level_3,
        "account_level_1": level_1,
        "account_level_2": level_2,
        "account_level_3": level_3 or item,
        "account_level_4": level_4,
        "source_amount": _money(_value(snapshot, "amount")) if snapshot else None,
        "project": _clean(_value(line, "project")),
        "project_stage": _normalize_stage(_value(line, "project_stage")),
        "allocated_amount": _money(_value(line, "allocated_amount")),
    }


def _domestic_dashboard_lines(allocation_names, period_by_parent):
    if not allocation_names:
        return []
    parent_filter = _parent_filter(allocation_names)
    fields = [
        "parent",
        "voucher_no",
        "expense_item_name",
        "account_level_3",
        "account_level_4",
        "project",
        "project_stage",
        "allocated_amount",
    ]
    source_fields = [
        "parent",
        "voucher_no",
        "expense_item",
        "account_level_1",
        "account_level_2",
        "account_level_3",
        "account_level_4",
        "amount",
        "direct_project",
    ]
    lines = frappe.get_all(
        "RD Cost Allocation Line",
        filters={"parent": parent_filter},
        fields=fields,
        order_by="voucher_no, account_level_3, account_level_4, project",
        limit_page_length=50000,
    )
    snapshots = frappe.get_all(
        "RD Allocation Source Expense",
        filters={"parent": parent_filter},
        fields=source_fields,
        limit_page_length=50000,
    )
    return _shape_dashboard_lines(lines, snapshots, period_by_parent)


def _shape_dashboard_lines(lines, snapshots, period_by_parent):
    """分摊明细 + 费用快照 -> 看板行（已定版的数据库行和预览的内存行共用）。"""
    lookup = _snapshot_lookup(snapshots)
    return [_with_snapshot_accounts(line, lookup, period_by_parent) for line in lines]


def _preview_parent(year, month):
    return "PREVIEW-%04d-%02d" % (int(year), int(month))


def _preview_dashboard_lines(doc, year, month):
    """预览（内存里算出、没入库的分摊单）的明细 -> 看板行，和 _domestic_dashboard_lines 同样的形状。"""
    parent = _preview_parent(year, month)
    lines = [
        {
            "parent": parent,
            "voucher_no": _value(line, "voucher_no"),
            "expense_item_name": _value(line, "expense_item_name"),
            "account_level_3": _value(line, "account_level_3"),
            "account_level_4": _value(line, "account_level_4"),
            "project": _value(line, "project"),
            "project_stage": _value(line, "project_stage"),
            "allocated_amount": _value(line, "allocated_amount"),
        }
        for line in (_value(doc, "lines", []) or [])
    ]
    snapshots = [
        {
            "parent": parent,
            "voucher_no": _value(row, "voucher_no"),
            "expense_item": _value(row, "expense_item"),
            "account_level_1": _value(row, "account_level_1"),
            "account_level_2": _value(row, "account_level_2"),
            "account_level_3": _value(row, "account_level_3"),
            "account_level_4": _value(row, "account_level_4"),
            "amount": _value(row, "amount"),
            "direct_project": _value(row, "direct_project"),
        }
        for row in (_value(doc, "expense_snapshots", []) or [])
    ]
    return _shape_dashboard_lines(lines, snapshots, {parent: (int(year), int(month))})


def _imported_months(year):
    """这一年有（未取消）费用导入单的月份。"""
    rows = frappe.get_all(
        "RD Expense Import",
        filters={"year": year, "docstatus": ["<", 2]},
        fields=["year", "month"],
        limit_page_length=0,
    )
    return {int(_value(row, "month")) for row in rows if _value(row, "month")}


def _dashboard_previews(context):
    """没有定版（已提交）分摊单、但有费用导入的月份：按当前数据现算预览（只读，不写库）。

    返回 {lines, months, errors}：lines 是预览的看板行，months 是预览成功的月份（YYYY-MM），
    errors 是有导入但算不出来的月份 [{"period", "error"}]。年度范围只算「有导入且没定版」的月份，
    最多 12 个（一年的月份数）。"""
    year = context["year"]
    if context["scope"] == "year":
        finalized = {m for (_y, m) in context["period_by_parent"].values()}
        candidates = sorted(_imported_months(year) - finalized)[:12]
    elif context["allocation_names"]:
        return {"lines": [], "months": [], "errors": []}
    else:
        candidates = [context["month"]]
    lines, months, errors = [], [], []
    for month in candidates:
        period = "%04d-%02d" % (year, month)
        preview = _build_preview(period, year, month)
        if preview is None:
            continue
        if preview.error is not None or preview.doc is None:
            errors.append({"period": period, "error": preview.error})
            continue
        lines.extend(_preview_dashboard_lines(preview.doc, year, month))
        months.append(period)
    return {"lines": lines, "months": months, "errors": errors}


def _foreign_dashboard_lines(periods):
    if not periods:
        return []
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix.rd_allocation_matrix import (
        _foreign_matrix_lines_for_month,
    )

    rows = []
    for year, month in periods:
        foreign_lines = _foreign_matrix_lines_for_month(year, month)
        for line in foreign_lines:
            level_3 = _clean(_value(line, "account_level_3")) or "\u5883\u5916"
            level_4 = _clean(_value(line, "account_level_4"))
            rows.append({
                "parent": "FOREIGN-%04d-%02d" % (int(year), int(month)),
                "period": "%04d-%02d" % (int(year), int(month)),
                "year": int(year),
                "month": int(month),
                "voucher_no": _clean(_value(line, "voucher_no")),
                "expense_item_name": _clean(_value(line, "expense_item_name")) or level_4 or level_3,
                "account_level_1": "\u7814\u53d1\u8d39\u7528",
                "account_level_2": "\u59d4\u6258\u7814\u53d1",
                "account_level_3": level_3,
                "account_level_4": level_4,
                "source_amount": None,
                "project": _clean(_value(line, "project")),
                "project_stage": _normalize_stage(_value(line, "project_stage")),
                "allocated_amount": _money(_value(line, "allocated_amount")),
            })
    return rows


def _append_project_amount(row, project, amount):
    if not project:
        return
    projects = row.setdefault("projects", {})
    projects[project] = _money(projects.get(project, 0) + amount)
    row["total"] = _money(row.get("total", 0) + amount)


def _dashboard_project_columns(lines):
    projects = sorted({_clean(_value(row, "project")) for row in lines if _clean(_value(row, "project"))})
    info = _project_info(projects)
    stage_by_project = {}
    for row in lines:
        project = _clean(_value(row, "project"))
        if project:
            stage_by_project.setdefault(project, _normalize_stage(_value(row, "project_stage")))
    columns = []
    for project in projects:
        project_info = info.get(project, {})
        code = _value(project_info, "rd_project_code") or project
        name = _value(project_info, "project_name") or project
        label = code if name == code else ("%s %s" % (code, name))
        stage = stage_by_project.get(project, "unknown")
        columns.append({
            "project": project,
            "project_code": code,
            "project_name": name,
            "label": label,
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, STAGE_LABELS["unknown"]),
        })
    return columns


def _dashboard_group_rows(lines, fields):
    grouped = {}
    for line in lines:
        key = tuple(_clean(_value(line, fieldname)) for fieldname in fields)
        row = grouped.setdefault(key, {fieldname: key[index] for index, fieldname in enumerate(fields)})
        for fieldname in ("period", "year", "month", "voucher_no", "expense_item_name", "account_level_1", "account_level_2", "account_level_3", "account_level_4"):
            if fieldname not in row:
                row[fieldname] = _value(line, fieldname)
        source_amount = _value(line, "source_amount")
        if source_amount is not None and row.get("source_amount") is None:
            row["source_amount"] = _money(source_amount)
        _append_project_amount(row, _clean(_value(line, "project")), _money(_value(line, "allocated_amount")))
    result = list(grouped.values())
    for row in result:
        row.setdefault("projects", {})
        row.setdefault("total", 0)
        if row.get("source_amount") is None:
            row["source_amount"] = row["total"]
    return sorted(result, key=lambda row: tuple(_clean(row.get(fieldname)) for fieldname in fields))


def _dashboard_total_row(rows, label, row_type):
    total = {
        "row_type": row_type,
        "account_level_1": "",
        "account_level_2": label,
        "account_level_3": "",
        "projects": {},
        "total": 0,
    }
    for row in rows:
        for project, amount in (row.get("projects") or {}).items():
            _append_project_amount(total, project, _money(amount))
    return total


def _dashboard_second_level_summary_rows(lines):
    grouped = {}
    for line in lines:
        level_1 = _clean(_value(line, "account_level_1")) or "\u7814\u53d1\u652f\u51fa"
        level_2 = _clean(_value(line, "account_level_2")) or "\u672a\u5206\u7c7b"
        level_3 = _clean(_value(line, "account_level_3")) or _clean(_value(line, "expense_item_name")) or "\u672a\u5206\u7c7b"
        key = (level_1, level_2, level_3)
        row = grouped.setdefault(key, {
            "row_type": "detail",
            "account_level_1": level_1,
            "account_level_2": level_2,
            "account_level_3": level_3,
            "projects": {},
            "total": 0,
        })
        _append_project_amount(row, _clean(_value(line, "project")), _money(_value(line, "allocated_amount")))

    detail_rows = sorted(grouped.values(), key=lambda row: (
        _clean(row.get("account_level_1")),
        _clean(row.get("account_level_2")),
        _clean(row.get("account_level_3")),
    ))
    rows = []
    current_key = None
    bucket = []
    for row in detail_rows:
        key = (row["account_level_1"], row["account_level_2"])
        if current_key is not None and key != current_key:
            rows.extend(bucket)
            rows.append(_dashboard_total_row(bucket, "%s \u6c47\u603b" % current_key[1], "subtotal"))
            bucket = []
        current_key = key
        bucket.append(row)
    if bucket:
        rows.extend(bucket)
        rows.append(_dashboard_total_row(bucket, "%s \u6c47\u603b" % current_key[1], "subtotal"))
    if detail_rows:
        grand_total = _dashboard_total_row(detail_rows, "", "grand_total")
        grand_total["account_level_1"] = "\u603b\u8ba1"
        rows.append(grand_total)
    return rows, detail_rows


def _dashboard_stage_totals(lines):
    totals = _zero_stage_totals()
    for line in lines:
        stage = _normalize_stage(_value(line, "project_stage"))
        totals[stage] = _money(totals.get(stage, 0) + _money(_value(line, "allocated_amount")))
    return _stage_summary_values(totals["capitalized"], totals["expensed"], totals["unknown"])


@frappe.whitelist()
def get_allocation_dashboard(period, scope="month", mode="all"):
    _require_read_access()
    mode = _dashboard_mode(mode)
    context = _allocation_dashboard_context(period, scope)
    lines = _domestic_dashboard_lines(context["allocation_names"], context["period_by_parent"])
    # 没有定版的月份用预览顶上（只读）；已定版的月份和原来完全一样。
    previews = _dashboard_previews(context)
    lines.extend(previews["lines"])
    lines.extend(_foreign_dashboard_lines(context["foreign_periods"]))
    finalized_months = sorted({
        "%04d-%02d" % (int(y), int(m)) for (y, m) in context["period_by_parent"].values() if y and m
    })

    stage_filter = None if mode == "all" else mode
    filtered_lines = [
        line for line in lines
        if not stage_filter or _normalize_stage(_value(line, "project_stage")) == stage_filter
    ]
    project_columns = _dashboard_project_columns(filtered_lines)
    summary_rows, detail_rows = _dashboard_second_level_summary_rows(filtered_lines)
    second_levels = {
        _clean(row.get("account_level_2"))
        for row in detail_rows
        if _clean(row.get("account_level_2"))
    }
    result = {
        "period": context["period"],
        "scope": context["scope"],
        "mode": mode,
        "mode_label": DASHBOARD_MODE_LABELS[mode],
        "allocation_names": context["allocation_names"],
        "total_amount": _money(sum(_money(_value(line, "allocated_amount")) for line in filtered_lines)),
        "project_count": len(project_columns),
        "second_level_count": len(second_levels),
        "third_level_count": len(detail_rows),
        "expense_item_count": len(detail_rows),
        "stage_summaries": _dashboard_stage_totals(filtered_lines),
        "project_columns": project_columns,
        "summary_rows": summary_rows,
    }
    if context["scope"] == "year":
        result["finalized_months"] = finalized_months
        result["preview_months"] = previews["months"]
        result["has_preview"] = bool(previews["months"])
        if previews["errors"]:
            result["preview_errors"] = previews["errors"]
    else:
        result["finalized"] = bool(context["allocation_names"])
        result["preview"] = bool(previews["months"])
        if previews["errors"]:
            result["preview_error"] = previews["errors"][0]["error"]
    return result


def _finance_manager_users():
    from rayher_hr_payroll.position_access import position_users

    return position_users(FINALIZE_POSITION_KEY)


def _can_finalize():
    """财务主管（岗位持有人）、System Manager、Administrator 可以定版 / 撤销定版。"""
    user = str(getattr(getattr(frappe, "session", None), "user", "") or "").strip()
    if user == "Administrator" or "System Manager" in set(frappe.get_roles() or []):
        return True
    return bool(user) and user.lower() in _finance_manager_users()


def _require_can_finalize(message):
    if not _can_finalize():
        frappe.throw(frappe._(message))


def _build_preview(period, year, month):
    from rayher_hr_payroll.rd_cost import allocation_preview

    return allocation_preview.build_preview(period, year, month)


def _new_allocation_doc(period, year, month, expense_import):
    from rayher_hr_payroll.rd_cost import allocation_preview

    return allocation_preview.new_allocation_doc(period, year, month, expense_import)


def _submitted_allocation_name(year, month):
    return frappe.db.get_value(
        "RD Cost Allocation", {"year": year, "month": month, "docstatus": 1},
        "name", order_by="creation desc",
    )


def _datetime_text(value):
    """datetime / 字符串 -> "YYYY-MM-DD HH:MM:SS"（去掉小数秒）；空值返回 None。"""
    if not value:
        return None
    strftime = getattr(value, "strftime", None)
    if callable(strftime):
        return strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip()[:19] or None


def _user_display_name(user):
    """账号 -> 姓名（没有姓名就用账号本身）。"""
    user = _clean(user)
    if not user:
        return ""
    try:
        return _clean(frappe.utils.get_fullname(user)) or user
    except Exception:
        return user


def _finalized_info(doc):
    """谁、什么时候定版：定版是同一个请求里创建并提交分摊单，所以已提交单据的 modified_by / modified 就是提交那一刻。"""
    user = _clean(_value(doc, "modified_by")) or _clean(_value(doc, "owner"))
    return {
        "finalized_by": user or None,
        "finalized_by_name": _user_display_name(user) or None,
        "finalized_on": _datetime_text(_value(doc, "modified")) or _datetime_text(_value(doc, "creation")),
    }


# 备注格式：撤销定版：{原因}（{姓名或账号}，YYYY-MM-DD HH:MM:SS）。原因里可以有括号和逗号，所以原因取最后一组括号之前的全部内容。
_REVOKE_PREFIXES = ("撤销定版：", "撤销定版:")
_REVOKE_COMMENT_RE = re.compile(
    r"^撤销定版[：:]\s*(?P<reason>.*)[（(](?P<by>[^（）()]*?)[，,]\s*(?P<on>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\s*[）)]\s*$",
    re.S,
)


def _parse_revoke_comment(content):
    """撤销备注 -> {"reason", "by_name", "on"}；格式不对时整段当作原因，姓名和时间为空。"""
    text = _clean(content)
    match = _REVOKE_COMMENT_RE.match(text)
    if match:
        return {
            "reason": match.group("reason").strip(),
            "by_name": match.group("by").strip(),
            "on": match.group("on").replace("T", " "),
        }
    for prefix in _REVOKE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return {"reason": text.strip(), "by_name": "", "on": ""}


def _last_revoke(year, month):
    """这个月最近一次撤销定版：{by, by_name, on, reason}，没有（或查不到）返回 None。

    撤销时每张被撤销的分摊单都写了一条「撤销定版：…」Info 备注；取已取消分摊单上最新的一条，
    操作人、时间优先用备注自己的 owner / creation，缺了再用备注文字里的姓名和时间。
    这只是页面上的辅助信息，查询失败不影响主流程。"""
    try:
        names = frappe.get_all(
            "RD Cost Allocation",
            filters={"year": year, "month": month, "docstatus": 2},
            pluck="name",
            limit_page_length=0,
        )
        if not names:
            return None
        rows = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "RD Cost Allocation",
                "reference_name": ["in", list(names)],
                "comment_type": "Info",
                "content": ["like", "撤销定版%"],
            },
            fields=["content", "owner", "creation"],
            order_by="creation desc",
            limit_page_length=1,
        )
    except Exception:
        return None
    if not rows:
        return None
    row = rows[0]
    parsed = _parse_revoke_comment(_value(row, "content"))
    by = _clean(_value(row, "owner"))
    return {
        "by": by or None,
        "by_name": parsed["by_name"] or _user_display_name(by) or None,
        "on": _datetime_text(_value(row, "creation")) or parsed["on"] or None,
        "reason": parsed["reason"],
    }


def _month_view(period, year, month):
    """月份的分摊页数据：(响应, 分摊单文档)。

    - 有已提交的分摊单：定版数据（preview False, finalized True）。
    - 没有，但有费用导入且 calculate() 成功：只读预览（name None, status "预览"）。
    - 其余：只有境外数据（预览不可用；导入存在但算不出来时带 preview_error）。
    文档是已提交的分摊单或内存里算出的预览（没有则 None），定版检查用它核对明细和合计。"""
    name = _submitted_allocation_name(year, month)
    foreign_totals, has_foreign_data = _foreign_period_state(year, month)
    base = {
        "period": period, "scope": "month",
        "has_foreign_data": has_foreign_data,
        "can_finalize": _can_finalize(),
        "preview_warnings": [],
        "finalized_by": None, "finalized_by_name": None, "finalized_on": None,
    }
    if name:
        d = frappe.get_doc("RD Cost Allocation", name)
        capitalized, expensed, unknown = _add_foreign_totals(
            d.capitalized_total, d.expensed_total, d.unknown_total, foreign_totals,
        )
        return {
            **base,
            "name": d.name, "status": d.status,
            "has_data": True,
            "has_domestic_data": True,
            "capitalized": capitalized, "expensed": expensed,
            "unknown": unknown, "lines": len(d.lines),
            "stage_summaries": _stage_summary_values(capitalized, expensed, unknown),
            "project_summaries": _project_summaries(d.name),
            "preview": False, "finalized": True,
            **_finalized_info(d),
        }, d

    preview = _build_preview(period, year, month)
    if preview is not None and preview.error is None:
        d = preview.doc
        lines = list(_value(d, "lines", []) or [])
        capitalized, expensed, unknown = _add_foreign_totals(
            d.capitalized_total, d.expensed_total, d.unknown_total, foreign_totals,
        )
        return {
            **base,
            "name": None, "status": PREVIEW_STATUS,
            "has_data": True,
            "has_domestic_data": True,
            "capitalized": capitalized, "expensed": expensed,
            "unknown": unknown, "lines": len(lines),
            "stage_summaries": _stage_summary_values(capitalized, expensed, unknown),
            "project_summaries": _project_summaries_from_lines(lines),
            "preview": True, "finalized": False,
            "preview_warnings": list(preview.warnings or []),
        }, d

    capitalized, expensed, unknown = _add_foreign_totals(0, 0, 0, foreign_totals)
    payload = {
        **base,
        "name": None, "status": None,
        "has_data": has_foreign_data,
        "has_domestic_data": False,
        "capitalized": capitalized, "expensed": expensed,
        "unknown": unknown, "lines": 0,
        "stage_summaries": _stage_summary_values(capitalized, expensed, unknown),
        "project_summaries": [],
        "preview": False, "finalized": False,
    }
    if preview is not None:
        payload["preview_error"] = preview.error
        payload["preview_warnings"] = list(preview.warnings or [])
    return payload, None


@frappe.whitelist()
def get_allocation(period, scope="month"):
    _require_read_access()
    if str(scope or "month") == "year":
        result = _year_allocation(period)
        result["can_finalize"] = _can_finalize()
        return result
    year, month = parse_period(period)
    payload, _doc = _month_view(period, year, month)
    # 本月最近一次撤销定版（谁、什么时候、为什么）；预览状态下页面用它说明本月为什么回到预览。
    payload["last_revoke"] = _last_revoke(year, month)
    return payload


def _reconcile_diff(doc):
    """明细合计 - 三个阶段合计（应为 0）。"""
    if doc is None:
        return 0.0
    line_total = sum(_number(_value(line, "allocated_amount")) for line in (_value(doc, "lines", []) or []))
    stage_total = sum(_number(_value(doc, field)) for field in ("capitalized_total", "expensed_total", "unknown_total"))
    return round(line_total - stage_total, 2)


@frappe.whitelist()
def get_finalize_check(period):
    """定版前的检查清单：工时填报情况、未判定金额、境外公共费用、明细和合计的差额、预览警告。"""
    require_rd_access(RD_FINANCE_ROLES)
    year, month = parse_period(period)
    payload, doc = _month_view(period, year, month)
    from rayher_hr_payroll.api import foreign_rd_entry, monthly_timesheet_entry

    # 和「工时填报进度」页同一份数据；scope=None 即全部研发人员，财务看全部，不受当前账号的部门范围限制。
    fill_rows = monthly_timesheet_entry._fill_rows(year, month, None)

    def count(status):
        return sum(1 for row in fill_rows if _value(row, "status") == status)

    foreign = foreign_rd_entry._get_foreign_rd_month(year, month)
    warnings = list(payload.get("preview_warnings") or [])
    preview_error = payload.get("preview_error")
    if preview_error:
        warnings.append(preview_error)
    elif not payload["preview"] and not payload["finalized"]:
        warnings.append("本月还没有费用导入单，无法定版。")
    elif payload["preview"] and not payload["lines"]:
        warnings.append("没有可分摊的数据，不能定版。")
    result = {
        "period": period,
        "can_finalize": payload["can_finalize"],
        "preview": payload["preview"],
        "finalized": payload["finalized"],
        "unfilled_people": count("none"),
        "underfilled_people": count("part"),
        "over_limit_people": count("over"),
        "unknown_amount": _money(payload["unknown"]),
        "unallocated_foreign_common_amount": _money(_value(foreign, "unallocated_common_amount")),
        "reconcile_diff": _reconcile_diff(doc),
        "warnings": warnings,
    }
    if preview_error:
        result["preview_error"] = preview_error
    return result


def _allow_ignore_permissions(doc):
    flags = getattr(doc, "flags", None)
    if flags is not None:
        flags.ignore_permissions = True


CANCEL_REASON_REQUIRED = "请填写撤销原因（200 字以内）。"
CANCEL_REASON_MAX = 200


def _clean_cancel_reason(reason):
    text = str(reason if reason is not None else "").strip()
    if not text or len(text) > CANCEL_REASON_MAX:
        frappe.throw(frappe._(CANCEL_REASON_REQUIRED))
    return text


def _cancel_comment_text(reason):
    """「撤销定版：原因（姓名，时间）」，写进被撤销的分摊单的备注，留痕。"""
    from datetime import datetime

    user = str(getattr(getattr(frappe, "session", None), "user", "") or "").strip()
    name = user
    try:
        name = frappe.utils.get_fullname(user) or user
    except Exception:
        name = user
    try:
        now = frappe.utils.now_datetime()
    except Exception:
        now = datetime.now()
    return "撤销定版：%s（%s，%s）" % (reason, name, now.strftime("%Y-%m-%d %H:%M:%S"))


def _add_cancel_comment(allocation_name, reason):
    frappe.get_doc(dict(
        doctype="Comment", comment_type="Info",
        reference_doctype="RD Cost Allocation", reference_name=allocation_name,
        content=_cancel_comment_text(reason),
    )).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def cancel_allocation(period, reason=None):
    """撤销定版。只有财务主管 / System Manager / Administrator；必须填撤销原因（1–200 字）。

    原因会作为一条备注写在每张被撤销的分摊单上（谁、什么时候、为什么）。"""
    require_rd_access(RD_FINANCE_ROLES)
    _require_can_finalize(CANCEL_DENIED)
    reason = _clean_cancel_reason(reason)
    year, month = parse_period(period)
    ensure_not_locked(period, "lock_allocations", "分摊")
    lock_period_import(year, month)
    submitted = frappe.get_all(
        "RD Cost Allocation",
        filters={"year": year, "month": month, "docstatus": 1},
        pluck="name",
    )
    if not submitted:
        return {"ok": True, "period": period, "canceled": [], "reason": reason}
    frappe.db.savepoint("rd_cancel_allocation")
    try:
        for name in submitted:
            allocation = frappe.get_doc("RD Cost Allocation", name)
            _allow_ignore_permissions(allocation)
            allocation.cancel()
            _add_cancel_comment(name, reason)
    except Exception:
        frappe.db.rollback(save_point="rd_cancel_allocation")
        raise
    frappe.db.commit()
    return {"ok": True, "period": period, "canceled": submitted, "reason": reason}


@frappe.whitelist(methods=["POST"])
def finalize_allocation(period):
    """定版：创建并提交本月分摊单（原来的「重算分摊」）。只有财务主管 / System Manager / Administrator。

    定版后工时（国内、境外）、费用导入、工资单等所有分摊输入都被冻结；要改先撤销定版。
    已经定版的月份不能再定版（原来 System Manager 可以顶替旧分摊单，现在必须先撤销）。"""
    require_rd_access(RD_FINANCE_ROLES)
    _require_can_finalize(FINALIZE_DENIED)
    year, month = parse_period(period)
    ensure_not_locked(period, "lock_allocations", "分摊")
    # Lock the period import row up front (same row every other path locks) so a
    # concurrent hour add/edit/delete serializes against this allocation: hours are then
    # read and snapshotted under the lock, closing the edit-vs-allocate race.
    imp = lock_period_import(year, month)
    if not imp:
        frappe.throw(frappe._("本期没有费用导入单，无法分摊。请先在「研发费用导入」录入费用。"))
    # 加锁后当前读，和别的请求同时定版时第二个会看到第一个提交的分摊单。
    if period_has_submitted_allocation(year, month):
        frappe.throw(frappe._(ALREADY_FINALIZED))
    frappe.db.savepoint("rd_recalc")
    try:
        # Submit the draft import first: the hardened allocation before_submit
        # requires a submitted (docstatus=1) import. Finance holds submit on
        # RD Expense Import; its before_submit re-checks non-zero lines and duplicates.
        impdoc = frappe.get_doc("RD Expense Import", imp)
        if impdoc.docstatus == 0:
            impdoc.submit()
        a = _new_allocation_doc(period, year, month, impdoc.name)
        a.calculate()
        a.insert(ignore_permissions=True)
        a.submit()  # on_submit marks the source import as Allocated (path-independent)
    except Exception:
        frappe.db.rollback(save_point="rd_recalc")
        raise
    frappe.db.commit()
    return get_allocation(period)


@frappe.whitelist(methods=["POST"])
def recalc_allocation(period):
    """已弃用：等同于 finalize_allocation（权限同为财务主管；已定版的月份要先撤销，不再顶替）。"""
    return finalize_allocation(period)
