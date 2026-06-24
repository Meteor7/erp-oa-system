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


def build_allocation_matrix(
    lines: Iterable[Any],
    *,
    translate: Callable[[str], str] = _identity,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    line_rows = list(lines)
    projects = sorted({str(_value(row, 'project')) for row in line_rows if _value(row, 'project')})
    project_fieldnames = {project: f'project_{index + 1}' for index, project in enumerate(projects)}
    columns: list[dict[str, Any]] = [
        {'label': translate('Voucher No'), 'fieldname': 'voucher_no', 'fieldtype': 'Data', 'width': 140},
        {'label': translate('Expense Item'), 'fieldname': 'expense_item_name', 'fieldtype': 'Data', 'width': 180},
    ]
    columns.extend(
        {'label': project, 'fieldname': project_fieldnames[project], 'fieldtype': 'Currency', 'width': 130}
        for project in projects
    )

    rows_by_key: dict[tuple[Any, Any], dict[str, Any]] = {}
    for line in line_rows:
        project_value = _value(line, 'project')
        if not project_value:
            continue
        key = (_value(line, 'voucher_no'), _value(line, 'expense_item_name'))
        row = rows_by_key.setdefault(
            key,
            {
                'voucher_no': _value(line, 'voucher_no'),
                'expense_item_name': _value(line, 'expense_item_name'),
            },
        )
        project = str(project_value)
        fieldname = project_fieldnames[project]
        row[fieldname] = row.get(fieldname, 0) + (_value(line, 'allocated_amount') or 0)

    return columns, list(rows_by_key.values())


def execute(filters=None):
    filters = filters or {}
    frappe = _get_frappe()
    allocation = filters.get('allocation')
    if not allocation:
        # get_list (not get_all) so record-level permissions apply: a restricted
        # user gets the newest allocation THEY may read, instead of get_all
        # picking an unreadable one that then fails check_permission.
        latest = frappe.get_list(
            'RD Cost Allocation', filters={'docstatus': 1},
            fields=['name'], order_by='creation desc', limit=1,
        )
        if not latest:
            return [], []
        allocation = latest[0]['name']

    frappe.get_doc("RD Cost Allocation", allocation).check_permission("read")
    lines = frappe.get_all(
        'RD Cost Allocation Line',
        filters={'parent': allocation},
        fields=['voucher_no', 'expense_item_name', 'project', 'project_stage', 'allocated_amount'],
        order_by='voucher_no, expense_item_name, project',
    )
    return build_allocation_matrix(lines, translate=frappe._)
