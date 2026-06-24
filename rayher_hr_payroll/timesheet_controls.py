from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Callable


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def _identity(text: str) -> str:
    return text


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).split(' ')[0]
    year, month, day = text.split('-')
    return date(int(year), int(month), int(day))


def _period(d: date) -> str:
    return f'{d.year}{d.month:02d}'


def period_from_timesheet(doc: Any) -> str | None:
    start_date = _as_date(getattr(doc, 'start_date', None))
    if not start_date:
        return None
    return _period(start_date)


def periods_from_timesheet(doc: Any) -> set[str]:
    periods: set[str] = set()
    start_date = _as_date(getattr(doc, 'start_date', None))
    if start_date:
        periods.add(_period(start_date))
    for row in getattr(doc, 'time_logs', []) or []:
        for attr in ('from_time', 'to_time'):
            row_date = _as_date(getattr(row, attr, None))
            if row_date:
                periods.add(_period(row_date))
    return periods


def ensure_period_unlocked(
    doc: Any,
    *,
    is_period_locked: Callable[[str | None], bool],
    throw: Callable[[str], None],
    translate: Callable[[str], str] = _identity,
) -> None:
    template = 'R&D period {0} is locked; timesheet changes require a correction workflow.'
    for period in sorted(periods_from_timesheet(doc)):
        if is_period_locked(period):
            throw(translate(template).format(period))


def _row_value(row: Any, fieldname: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def _entry_date(doc: Any, row: Any) -> date | None:
    return _as_date(_row_value(row, 'from_time')) or _as_date(getattr(doc, 'start_date', None))


def ensure_rd_projects_enabled(
    doc: Any,
    *,
    is_project_enabled: Callable[[str], bool],
    throw: Callable[[str], None],
    translate: Callable[[str], str] = _identity,
    project_stage_for_entry: Callable[[str, date | None], str | None] | None = None,
    block_unknown_project_stage: bool = False,
) -> None:
    enabled_template = 'Project {0} is not enabled for R&D timesheet entry.'
    stage_template = 'Project {0} needs capitalization start and end dates before R&D timesheet entry.'
    for row in getattr(doc, 'time_logs', []) or []:
        project = _row_value(row, 'project')
        if not project:
            continue
        if not is_project_enabled(project):
            throw(translate(enabled_template).format(project))
        if project_stage_for_entry:
            stage = project_stage_for_entry(project, _entry_date(doc, row))
            if block_unknown_project_stage and stage == 'unknown':
                throw(translate(stage_template).format(project))


def distinct_project_owners(time_logs: Any, owner_of: Callable[[str], Any]) -> list[str]:
    owners: set[str] = set()
    for row in time_logs or []:
        if isinstance(row, Mapping):
            project = row.get('project')
        else:
            project = getattr(row, 'project', None)
        if project:
            owner = owner_of(project)
            if owner:
                owners.add(owner)
    return sorted(owners)


def _is_period_locked(period: str | None) -> bool:
    if not period:
        return False
    frappe = _get_frappe()
    return bool(
        frappe.db.exists(
            'RD Period Lock',
            {'period': period, 'docstatus': 1, 'lock_timesheets': 1},
        )
    )


def _is_project_enabled(project: str) -> bool:
    frappe = _get_frappe()
    return bool(frappe.db.get_value('Project', project, 'allow_rd_timesheet'))


def _project_stage_for_entry(project: str, posting_date: date | None) -> str:
    if posting_date is None:
        return 'unknown'
    frappe = _get_frappe()
    from rayher_hr_payroll.rd_cost.frappe_adapter import stage_for_period

    fields = frappe.db.get_value(
        'Project',
        project,
        ['capitalization_start_date', 'capitalization_end_date'],
        as_dict=True,
    ) or {}
    return stage_for_period(fields, year=posting_date.year, month=posting_date.month)


def _ensure_periods_unlocked_incl_history(doc: Any, frappe: Any) -> None:
    # Check the current doc AND its pre-save version, so a timesheet cannot be
    # edited OUT of a locked period (consistent with import/allocation guards).
    ensure_period_unlocked(
        doc, is_period_locked=_is_period_locked, throw=frappe.throw, translate=frappe._,
    )
    before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
    if before is not None:
        ensure_period_unlocked(
            before, is_period_locked=_is_period_locked, throw=frappe.throw, translate=frappe._,
        )


def block_locked_timesheet_change(doc: Any, method: str | None = None) -> None:
    frappe = _get_frappe()
    _ensure_periods_unlocked_incl_history(doc, frappe)


def validate_timesheet(doc: Any, method: str | None = None) -> None:
    frappe = _get_frappe()
    _ensure_periods_unlocked_incl_history(doc, frappe)
    ensure_rd_projects_enabled(
        doc,
        is_project_enabled=_is_project_enabled,
        throw=frappe.throw,
        translate=frappe._,
    )


def on_submit_timesheet(doc: Any, method: str | None = None) -> None:
    frappe = _get_frappe()
    owners = distinct_project_owners(
        getattr(doc, 'time_logs', []) or [],
        lambda project: frappe.db.get_value('Project', project, 'project_owner'),
    )
    if not owners:
        return

    if len(owners) == 1 and not getattr(doc, 'rd_reviewer', None):
        doc.db_set('rd_reviewer', owners[0], update_modified=False)

    try:
        from frappe.desk.form.assign_to import add as assign_to_add

        current = set(frappe.parse_json(getattr(doc, '_assign', None) or '[]'))
        for owner in owners:
            if owner not in current:
                assign_to_add(
                    {
                        'assign_to': [owner],
                        'doctype': doc.doctype,
                        'name': doc.name,
                        'description': frappe._('Review R&D timesheet'),
                    }
                )
    except Exception:
        frappe.log_error(title='RD timesheet reviewer assignment failed')
