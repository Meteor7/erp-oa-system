from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def _identity(text: str) -> str:
    return text


def _value(row: Any, fieldname: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value: Any) -> float:
    return round(_number(value), 2)


def _add_amount(left: Any, right: Any) -> Any:
    try:
        return (left or 0) + (right or 0)
    except TypeError:
        return _money(_number(left) + _number(right))


def _normalize_stage(stage: Any) -> str:
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
    return aliases.get(_clean(stage), "unknown")


def filter_allocation_lines_by_stage(lines: Iterable[Any], stage: Any) -> list[Any]:
    rows = list(lines)
    selected = _clean(stage or "all")
    if selected not in {"capitalized", "expensed"}:
        return rows
    return [row for row in rows if _normalize_stage(_value(row, "project_stage")) == selected]


def _project_stage_by_project(lines: list[Any]) -> dict[str, str]:
    stages: dict[str, str] = {}
    for row in lines:
        project = _value(row, "project")
        if not project:
            continue
        project_key = str(project)
        stage = _normalize_stage(_value(row, "project_stage", ""))
        stages.setdefault(project_key, stage)
    return stages


def build_allocation_matrix(
    lines: Iterable[Any],
    *,
    translate: Callable[[str], str] = _identity,
    include_total: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    line_rows = list(lines)
    has_period = any(_clean(_value(row, "period")) for row in line_rows)
    projects = sorted({str(_value(row, "project")) for row in line_rows if _value(row, "project")})
    project_fieldnames = {project: f"project_{index + 1}" for index, project in enumerate(projects)}
    project_stages = _project_stage_by_project(line_rows)
    columns: list[dict[str, Any]] = []
    if has_period:
        columns.append({"label": translate("\u65e5\u671f"), "fieldname": "period", "fieldtype": "Data", "width": 110})
    columns.extend([
        {"label": translate("Voucher No"), "fieldname": "voucher_no", "fieldtype": "Data", "width": 140},
        {"label": translate("\u0033\u7ea7\u8d39\u7528\u79d1\u76ee"), "fieldname": "account_level_3", "fieldtype": "Data", "width": 220},
        {"label": translate("\u0034\u7ea7\u8d39\u7528\u79d1\u76ee"), "fieldname": "account_level_4", "fieldtype": "Data", "width": 180},
    ])
    columns.extend(
        {
            "label": project,
            "fieldname": project_fieldnames[project],
            "fieldtype": "Currency",
            "width": 130,
            "project": project,
            "project_stage": project_stages.get(project, "unknown"),
        }
        for project in projects
    )
    columns.append(
        {
            "label": translate("\u6c47\u603b"),
            "fieldname": "row_total",
            "fieldtype": "Currency",
            "width": 140,
        }
    )

    rows_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for line in line_rows:
        project_value = _value(line, "project")
        if not project_value:
            continue
        account_level_3 = _value(line, "account_level_3") or _value(line, "expense_item_name") or ""
        account_level_4 = _value(line, "account_level_4") or ""
        period = _clean(_value(line, "period"))
        key = ((period,) if has_period else ()) + (_value(line, "voucher_no"), account_level_3, account_level_4)
        base_row = {
            "voucher_no": _value(line, "voucher_no"),
            "account_level_3": account_level_3,
            "account_level_4": account_level_4,
        }
        if has_period:
            base_row["period"] = period
        row = rows_by_key.setdefault(
            key,
            base_row,
        )
        project = str(project_value)
        fieldname = project_fieldnames[project]
        amount = _value(line, "allocated_amount") or 0
        row[fieldname] = _add_amount(row.get(fieldname, 0), amount)
        row["row_total"] = _add_amount(row.get("row_total", 0), amount)

    rows = list(rows_by_key.values())
    if has_period:
        rows.sort(key=lambda row: (row.get("period", ""), row.get("voucher_no", ""), row.get("account_level_3", ""), row.get("account_level_4", "")))
    if include_total and rows and projects:
        total_row: dict[str, Any] = {
            "voucher_no": "",
            "account_level_3": translate("Project Total"),
            "account_level_4": "",
            "_is_total": 1,
        }
        if has_period:
            total_row["period"] = ""
        for project in projects:
            fieldname = project_fieldnames[project]
            total = 0
            for row in rows:
                total = _add_amount(total, row.get(fieldname, 0) or 0)
            total_row[fieldname] = total
        total_row["row_total"] = sum((row.get("row_total", 0) or 0) for row in rows)
        rows.append(total_row)

    return columns, rows


def build_foreign_allocation_matrix_lines(
    expense_sources: Iterable[Any],
    time_lines: Iterable[Any],
    project_info: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    project_info = project_info or {}
    prepared_time_lines = [
        row for row in time_lines
        if _clean(_value(row, "project")) and _number(_value(row, "hours")) > 0
    ]
    total_hours = sum(_number(_value(row, "hours")) for row in prepared_time_lines)
    rows: list[dict[str, Any]] = []

    for source in expense_sources or []:
        amount = _money(_value(source, "amount"))
        if not amount:
            continue
        account_level_3 = _clean(_value(source, "account_level_3")) or _clean(_value(source, "account_level_4")) or _clean(_value(source, "expense_item"))
        account_level_4 = _clean(_value(source, "account_level_4"))
        voucher_no = _clean(_value(source, "voucher_no"))
        allocation_type = _clean(_value(source, "allocation_type"))
        direct_project = _clean(_value(source, "direct_project"))

        if allocation_type == "project" or direct_project:
            if not direct_project:
                continue
            info = project_info.get(direct_project, {})
            rows.append({
                "voucher_no": voucher_no,
                "expense_item_name": account_level_4 or account_level_3,
                "account_level_3": account_level_3,
                "account_level_4": account_level_4,
                "project": direct_project,
                "project_stage": _normalize_stage(_value(info, "rd_stage")),
                "allocated_amount": amount,
            })
            continue

        if total_hours <= 0:
            continue
        running = 0.0
        for index, line in enumerate(prepared_time_lines):
            if index == len(prepared_time_lines) - 1:
                allocated = _money(amount - running)
            else:
                allocated = _money(amount * _number(_value(line, "hours")) / total_hours)
                running = _money(running + allocated)
            rows.append({
                "voucher_no": voucher_no,
                "expense_item_name": account_level_4 or account_level_3,
                "account_level_3": account_level_3,
                "account_level_4": account_level_4,
                "project": _clean(_value(line, "project")),
                "project_stage": _normalize_stage(_value(line, "project_stage")),
                "allocated_amount": allocated,
            })
    return rows



def _most_specific_snapshot_account(row: Any) -> str:
    for fieldname in ("account_level_4", "account_level_3", "account_level_2", "account_level_1"):
        value = _clean(_value(row, fieldname))
        if value:
            return value
    return _clean(_value(row, "expense_item"))


def _mutable_line(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    values = getattr(row, "__dict__", None)
    if isinstance(values, dict):
        return dict(values)
    return {
        "parent": _value(row, "parent"),
        "voucher_no": _value(row, "voucher_no"),
        "expense_item_name": _value(row, "expense_item_name"),
        "account_level_3": _value(row, "account_level_3"),
        "account_level_4": _value(row, "account_level_4"),
        "project": _value(row, "project"),
        "project_stage": _value(row, "project_stage"),
        "allocated_amount": _value(row, "allocated_amount"),
    }


def enrich_allocation_lines_with_snapshot_accounts(
    lines: Iterable[Any],
    snapshots: Iterable[Any],
) -> list[dict[str, Any]]:
    lookup: dict[tuple[str, str, str], tuple[str, str]] = {}
    for snapshot in snapshots or []:
        key = (
            _clean(_value(snapshot, "parent")),
            _clean(_value(snapshot, "voucher_no")),
            _most_specific_snapshot_account(snapshot),
        )
        if not all(key):
            continue
        lookup.setdefault(key, (
            _clean(_value(snapshot, "account_level_3")),
            _clean(_value(snapshot, "account_level_4")),
        ))

    enriched: list[dict[str, Any]] = []
    for line in lines or []:
        row = _mutable_line(line)
        key = (
            _clean(row.get("parent")),
            _clean(row.get("voucher_no")),
            _clean(row.get("expense_item_name")),
        )
        levels = lookup.get(key)
        if levels:
            level_3, level_4 = levels
            if not _clean(row.get("account_level_3")):
                row["account_level_3"] = level_3
            if level_4 and not _clean(row.get("account_level_4")):
                row["account_level_4"] = level_4
        enriched.append(row)
    return enriched


def _snapshot_rows_for_allocations(frappe, allocation_names: list[str]) -> list[Any]:
    if not allocation_names:
        return []
    parent_filter = allocation_names[0] if len(allocation_names) == 1 else ["in", allocation_names]
    return frappe.get_all(
        "RD Allocation Source Expense",
        filters={"parent": parent_filter},
        fields=["parent", "voucher_no", "expense_item", "account_level_1", "account_level_2", "account_level_3", "account_level_4"],
        limit_page_length=5000,
    )

def _latest_allocation(frappe):
    latest = frappe.get_list(
        "RD Cost Allocation", filters={"docstatus": 1},
        fields=["name"], order_by="creation desc", limit=1,
    )
    return latest[0]["name"] if latest else None


def _allocation_names_for_year(frappe, year):
    rows = frappe.get_list(
        "RD Cost Allocation",
        filters={"year": int(year), "docstatus": 1},
        fields=["name"],
        order_by="month asc, creation desc",
        limit_page_length=500,
    )
    return [row["name"] for row in rows]


def _has_field(frappe, doctype: str, fieldname: str) -> bool:
    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return False
    has_field = getattr(meta, "has_field", None)
    if callable(has_field):
        return bool(has_field(fieldname))
    return any(_value(field, "fieldname") == fieldname for field in getattr(meta, "fields", []) or [])


def _allocation_line_query_fields(frappe) -> tuple[list[str], str]:
    fields = ["parent", "voucher_no", "expense_item_name", "project", "project_stage", "allocated_amount"]
    order_by = "voucher_no, expense_item_name, project"
    if _has_field(frappe, "RD Cost Allocation Line", "account_level_3") and _has_field(frappe, "RD Cost Allocation Line", "account_level_4"):
        fields = ["parent", "voucher_no", "expense_item_name", "account_level_3", "account_level_4", "project", "project_stage", "allocated_amount"]
        order_by = "voucher_no, account_level_3, account_level_4, project"
    return fields, order_by


def _foreign_matrix_lines_for_month(year: Any, month: Any) -> list[dict[str, Any]]:
    if not year or not month:
        return []
    from rayher_hr_payroll.api import foreign_rd_entry as foreign

    expense_context = foreign._foreign_expense_context(int(year), int(month))
    doc_name = foreign._foreign_doc_name(int(year), int(month))
    time_lines = []
    if doc_name:
        doc = foreign.frappe.get_doc("Foreign RD Expense", doc_name)
        time_lines = [foreign._serialize_line(line) for line in (doc.lines or [])]
    project_names = {_clean(_value(line, "project")) for line in time_lines if _clean(_value(line, "project"))}
    project_names.update(
        _clean(_value(source, "direct_project"))
        for source in expense_context.get("expense_sources", [])
        if _clean(_value(source, "direct_project"))
    )
    project_info = foreign._foreign_project_info(project_names)
    return build_foreign_allocation_matrix_lines(expense_context.get("expense_sources", []), time_lines, project_info)


def _foreign_periods_for_report(filters: Mapping[str, Any], allocation_docs: list[Any]) -> list[tuple[int, int]]:
    if filters.get("year"):
        return [(int(filters.get("year")), month) for month in range(1, 13)]
    periods = []
    seen = set()
    for doc in allocation_docs:
        year = _value(doc, "year")
        month = _value(doc, "month")
        if not year or not month:
            continue
        key = (int(year), int(month))
        if key not in seen:
            seen.add(key)
            periods.append(key)
    return periods


def execute(filters=None):
    filters = filters or {}
    frappe = _get_frappe()
    allocation = filters.get("allocation")
    allocation_names = []
    allocation_docs = []
    if allocation:
        doc = frappe.get_doc("RD Cost Allocation", allocation)
        doc.check_permission("read")
        allocation_docs = [doc]
        allocation_names = [allocation]
    elif filters.get("year"):
        allocation_names = _allocation_names_for_year(frappe, filters.get("year"))
        for name in allocation_names:
            doc = frappe.get_doc("RD Cost Allocation", name)
            doc.check_permission("read")
            allocation_docs.append(doc)
    else:
        latest = _latest_allocation(frappe)
        if not latest:
            return [], []
        doc = frappe.get_doc("RD Cost Allocation", latest)
        doc.check_permission("read")
        allocation_docs = [doc]
        allocation_names = [latest]

    lines: list[Any] = []
    period_by_parent = {
        _clean(_value(doc, "name")): "%04d-%02d" % (int(_value(doc, "year")), int(_value(doc, "month")))
        for doc in allocation_docs
        if _clean(_value(doc, "name")) and _value(doc, "year") and _value(doc, "month")
    }
    if allocation_names:
        parent_filter = allocation_names[0] if len(allocation_names) == 1 else ["in", allocation_names]
        fields, order_by = _allocation_line_query_fields(frappe)
        domestic_lines = frappe.get_all(
            "RD Cost Allocation Line",
            filters={"parent": parent_filter},
            fields=fields,
            order_by=order_by,
        )
        snapshots = _snapshot_rows_for_allocations(frappe, allocation_names)
        enriched_lines = enrich_allocation_lines_with_snapshot_accounts(domestic_lines, snapshots)
        for line in enriched_lines:
            line["period"] = period_by_parent.get(_clean(line.get("parent")), "")
        lines.extend(enriched_lines)

    for year, month in _foreign_periods_for_report(filters, allocation_docs):
        for foreign_line in _foreign_matrix_lines_for_month(year, month):
            row = dict(foreign_line)
            row["period"] = "%04d-%02d" % (int(year), int(month))
            lines.append(row)

    lines = filter_allocation_lines_by_stage(lines, filters.get("stage"))
    return build_allocation_matrix(lines, translate=frappe._)
