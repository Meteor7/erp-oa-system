from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Any

RD_PERSONNEL_TYPES = ('全时研发', '非全时研发', '研发辅助')


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def _identity(text: str) -> str:
    return text


def _value(row: Any, fieldname: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def build_timesheet_exception_rows(
    employees: Iterable[Any],
    *,
    hours_by_employee: Mapping[str, Decimal],
    year: int,
    month: int,
    translate: Callable[[str], str] = _identity,
) -> list[dict[str, Any]]:
    rows = []
    message_template = '{0}-{1:02d} has no submitted timesheet hours.'
    for employee in employees:
        employee_id = str(_value(employee, 'name'))
        hours = Decimal(str(hours_by_employee.get(employee_id, Decimal('0')) or 0))
        if hours <= 0:
            rows.append(
                {
                    'employee': employee_id,
                    'employee_name': _value(employee, 'employee_name'),
                    'exception_type': translate('Missing Timesheet'),
                    'message': translate(message_template).format(year, month),
                }
            )
    return rows


def build_unclassified_rd_rows(
    rd_hour_logs: Iterable[Any],
    *,
    translate: Callable[[str], str] = _identity,
) -> list[dict[str, Any]]:
    rows = []
    quote = chr(39)
    message_template = (
        'Logged {0} h on R&D projects but rd_personnel_type is '
        + quote
        + '{1}'
        + quote
        + '; excluded from R&D allocation.'
    )
    for log in rd_hour_logs:
        ptype = _value(log, 'rd_personnel_type')
        hours = Decimal(str(_value(log, 'hours', 0) or 0))
        if hours > 0 and ptype not in RD_PERSONNEL_TYPES:
            rows.append(
                {
                    'employee': str(_value(log, 'employee')),
                    'employee_name': _value(log, 'employee_name'),
                    'exception_type': translate('Unclassified R&D Hours'),
                    'message': translate(message_template).format(hours, ptype or '(unset)'),
                }
            )
    return rows


def parse_year_month_filters(
    filters: Mapping[str, Any],
    *,
    throw: Callable[[str], None],
    translate: Callable[[str], str] = _identity,
) -> tuple[int, int]:
    year = filters.get('year')
    month = filters.get('month')
    if year in (None, '') or month in (None, ''):
        throw(translate('Year and month filters are required.'))

    try:
        year_int = int(year)
        month_int = int(month)
    except (TypeError, ValueError):
        throw(translate('Year and month filters must be valid numbers.'))

    if month_int < 1 or month_int > 12:
        throw(translate('Month must be between 1 and 12.'))

    return year_int, month_int


def _columns(translate: Callable[[str], str] = _identity) -> list[dict[str, Any]]:
    return [
        {'label': translate('Employee'), 'fieldname': 'employee', 'fieldtype': 'Link', 'options': 'Employee', 'width': 140},
        {'label': translate('Employee Name'), 'fieldname': 'employee_name', 'fieldtype': 'Data', 'width': 160},
        {'label': translate('Exception Type'), 'fieldname': 'exception_type', 'fieldtype': 'Data', 'width': 180},
        {'label': translate('Message'), 'fieldname': 'message', 'fieldtype': 'Data', 'width': 420},
    ]


def execute(filters=None):
    filters = filters or {}
    frappe = _get_frappe()
    year, month = parse_year_month_filters(filters, throw=frappe.throw, translate=frappe._)

    month_start = '%04d-%02d-01' % (year, month)
    month_end = frappe.utils.get_last_day(month_start)
    # Active-in-period window (matches the other period-scoped reports): employed
    # by month end and not relieved before the month. Use the date window rather
    # than current status so a person relieved before the month is excluded and a
    # person who left DURING the month is still checked for that month.
    employees = frappe.get_all(
        'Employee',
        filters={
            'rd_personnel_type': ['in', RD_PERSONNEL_TYPES],
            'date_of_joining': ['<=', month_end],
        },
        or_filters=[
            {'relieving_date': ['is', 'not set']},
            {'relieving_date': ['>=', month_start]},
        ],
        fields=['name', 'employee_name'],
        order_by='employee_name',
    )
    hour_rows = frappe.db.sql(
        '''
        select ts.employee, coalesce(sum(tsd.hours), 0) as hours
          from `tabTimesheet Detail` tsd
          inner join `tabTimesheet` ts on ts.name = tsd.parent
          inner join `tabProject` p on p.name = tsd.project
         where ts.docstatus = 1
           and coalesce(p.allow_rd_timesheet, 0) = 1
           and year(tsd.from_time) = %(year)s
           and month(tsd.from_time) = %(month)s
         group by ts.employee
        ''',
        {'year': year, 'month': month},
        as_dict=True,
    )
    hours_by_employee = {str(row.employee): Decimal(str(row.hours or 0)) for row in hour_rows}

    rd_hour_logs = frappe.db.sql(
        '''
        select e.name as employee, e.employee_name, e.rd_personnel_type,
               coalesce(sum(tsd.hours), 0) as hours
          from `tabTimesheet Detail` tsd
          inner join `tabTimesheet` ts on ts.name = tsd.parent
          inner join `tabEmployee` e on e.name = ts.employee
          inner join `tabProject` p on p.name = tsd.project
         where ts.docstatus = 1
           and year(tsd.from_time) = %(year)s
           and month(tsd.from_time) = %(month)s
           and coalesce(p.allow_rd_timesheet, 0) = 1
         group by e.name
        ''',
        {'year': year, 'month': month},
        as_dict=True,
    )

    rows = build_timesheet_exception_rows(
        employees,
        hours_by_employee=hours_by_employee,
        year=year,
        month=month,
        translate=frappe._,
    )
    rows += build_unclassified_rd_rows(rd_hour_logs, translate=frappe._)
    return _columns(translate=frappe._), rows
