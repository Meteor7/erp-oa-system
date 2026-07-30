import frappe

from rayher_hr_payroll.api._guards import lock_period_import, require_rd_access, parse_period, ensure_not_locked, RD_FINANCE_ROLES


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


def _foreign_stage_totals(year, month):
    from rayher_hr_payroll.api import foreign_rd_entry

    payload = foreign_rd_entry._get_foreign_rd_month(int(year), int(month))
    totals = _zero_stage_totals()
    for row in payload.get("foreign_stage_summaries", []) or []:
        stage = _value(row, "stage") or "unknown"
        if stage not in totals:
            stage = "unknown"
        totals[stage] += _number(_value(row, "total"))
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
    for month in range(1, 13):
        month_totals = _foreign_stage_totals(year, month)
        for stage in foreign_totals:
            foreign_totals[stage] += _number(month_totals.get(stage))
    capitalized, expensed, unknown = _add_foreign_totals(capitalized, expensed, unknown, foreign_totals)
    return {
        "name": None,
        "period": str(year),
        "scope": "year",
        "status": "Yearly" if rows else None,
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
    if not level_2 and level_3 == "\u4eba\u5de5\u8d39":
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
    lookup = _snapshot_lookup(snapshots)
    return [_with_snapshot_accounts(line, lookup, period_by_parent) for line in lines]


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
    require_rd_access(RD_FINANCE_ROLES)
    mode = _dashboard_mode(mode)
    context = _allocation_dashboard_context(period, scope)
    lines = _domestic_dashboard_lines(context["allocation_names"], context["period_by_parent"])
    lines.extend(_foreign_dashboard_lines(context["foreign_periods"]))

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
    return {
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


@frappe.whitelist()
def get_allocation(period, scope="month"):
    require_rd_access(RD_FINANCE_ROLES)
    if str(scope or "month") == "year":
        return _year_allocation(period)
    year, month = parse_period(period)
    name = frappe.db.get_value(
        "RD Cost Allocation", {"year": year, "month": month, "docstatus": 1},
        "name", order_by="creation desc",
    )
    foreign_totals = _foreign_stage_totals(year, month)
    if not name:
        capitalized, expensed, unknown = _add_foreign_totals(0, 0, 0, foreign_totals)
        return {
            "name": None, "status": None, "period": period, "scope": "month",
            "capitalized": capitalized, "expensed": expensed,
            "unknown": unknown, "lines": 0,
            "stage_summaries": _stage_summary_values(capitalized, expensed, unknown),
            "project_summaries": [],
        }
    d = frappe.get_doc("RD Cost Allocation", name)
    capitalized, expensed, unknown = _add_foreign_totals(
        d.capitalized_total,
        d.expensed_total,
        d.unknown_total,
        foreign_totals,
    )
    return {
        "name": d.name, "status": d.status, "period": period, "scope": "month",
        "capitalized": capitalized, "expensed": expensed,
        "unknown": unknown, "lines": len(d.lines),
        "stage_summaries": _stage_summary_values(capitalized, expensed, unknown),
        "project_summaries": _project_summaries(d.name),
    }


def _allow_ignore_permissions(doc):
    flags = getattr(doc, "flags", None)
    if flags is not None:
        flags.ignore_permissions = True


@frappe.whitelist(methods=["POST"])
def cancel_allocation(period):
    require_rd_access(RD_FINANCE_ROLES)
    year, month = parse_period(period)
    ensure_not_locked(period, "lock_allocations", "分摊")
    lock_period_import(year, month)
    submitted = frappe.get_all(
        "RD Cost Allocation",
        filters={"year": year, "month": month, "docstatus": 1},
        pluck="name",
    )
    if not submitted:
        return {"ok": True, "period": period, "canceled": []}
    frappe.db.savepoint("rd_cancel_allocation")
    try:
        for name in submitted:
            allocation = frappe.get_doc("RD Cost Allocation", name)
            _allow_ignore_permissions(allocation)
            allocation.cancel()
    except Exception:
        frappe.db.rollback(save_point="rd_cancel_allocation")
        raise
    frappe.db.commit()
    return {"ok": True, "period": period, "canceled": submitted}


@frappe.whitelist(methods=["POST"])
def recalc_allocation(period):
    require_rd_access(RD_FINANCE_ROLES)
    year, month = parse_period(period)
    ensure_not_locked(period, "lock_allocations", "分摊")
    # Lock the period import row up front (same row every other path locks) so a
    # concurrent hour add/edit/delete serializes against this allocation: hours are then
    # read and snapshotted under the lock, closing the edit-vs-allocate race.
    imp = lock_period_import(year, month)
    if not imp:
        frappe.throw(frappe._("本期没有费用导入单，无法分摊。请先在「研发费用导入」录入费用。"))
    # Existing submitted allocations must be cancelled explicitly first. This keeps
    # the destructive step visible in the Rayher page instead of hiding it behind
    # a regular recompute click.
    submitted = frappe.get_all(
        "RD Cost Allocation", filters={"year": year, "month": month, "docstatus": 1}, pluck="name",
    )
    if submitted and "System Manager" not in frappe.get_roles():
        frappe.throw(frappe._("本期已有已提交的分摊单，请先撤销本期分摊后再重算。"))
    frappe.db.savepoint("rd_recalc")
    try:
        # Submit the draft import first: the hardened allocation before_submit
        # requires a submitted (docstatus=1) import. Finance holds submit on
        # RD Expense Import; its before_submit re-checks non-zero lines and duplicates.
        impdoc = frappe.get_doc("RD Expense Import", imp)
        if impdoc.docstatus == 0:
            impdoc.submit()
        # Supersede prior submitted allocations (only System Manager reaches here).
        for n in submitted:
            frappe.get_doc("RD Cost Allocation", n).cancel()
        a = frappe.get_doc(dict(
            doctype="RD Cost Allocation", period=period, year=year, month=month,
            expense_import=impdoc.name, allocation_basis="rd_project_hours", scope="all",
            calculation_version="v1",
        ))
        a.calculate()
        a.insert(ignore_permissions=True)
        a.submit()  # on_submit marks the source import as Allocated (path-independent)
    except Exception:
        frappe.db.rollback(save_point="rd_recalc")
        raise
    frappe.db.commit()
    return get_allocation(period)
