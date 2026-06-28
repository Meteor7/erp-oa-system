from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from rayher_hr_payroll.rd_cost.allocation import (
    allocate_expenses,
    allocate_labor,
    combine_results,
)
from rayher_hr_payroll.rd_cost.types import ExpenseItem, ProjectHour

LABOR_PREFIX = "labor:"


def _value(row: Any, fieldname: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def _source_expense_by_name(source_expense_rows: list[Any]) -> dict[str, Any]:
    return {str(_value(row, "expense_item")): row for row in source_expense_rows}


def _employee_project_hours(
    source_hour_rows: list[Any], project_hours: list[ProjectHour]
) -> dict[str, list[ProjectHour]]:
    """Per-employee project hours keyed by the labor item name ('labor:<emp>').
    Each project's capitalization stage is taken from the aggregated project_hours
    so labor inherits the same stage classification as expenses."""
    stage_by_project = {row.project: row.stage for row in project_hours}
    agg: dict[tuple[str, str], Decimal] = {}
    for row in source_hour_rows:
        emp = _value(row, "employee")
        project = _value(row, "project")
        if not emp or not project:
            continue
        hours = Decimal(str(_value(row, "hours", 0) or 0))
        agg[(str(emp), str(project))] = agg.get((str(emp), str(project)), Decimal("0")) + hours
    employee_hours: dict[str, list[ProjectHour]] = {}
    for (emp, project), hours in agg.items():
        employee_hours.setdefault(LABOR_PREFIX + emp, []).append(
            ProjectHour(project=project, hours=hours, stage=stage_by_project.get(project, "unknown"))
        )
    return employee_hours


def _labor_result(salaries, source_hour_rows, project_hours, total_hours=None):
    employee_hours = _employee_project_hours(source_hour_rows, project_hours)
    total_hours = total_hours or {}
    items = []
    for emp, gross in salaries.items():
        if not gross:
            continue
        key = LABOR_PREFIX + str(emp)
        hours = employee_hours.get(key)
        if not hours:
            continue
        rd_hours = sum((h.hours for h in hours), Decimal("0"))
        total = Decimal(str(total_hours.get(emp) or 0))
        # ratio = R&D hours / total worked hours (<= 1). If total is missing or not
        # greater than R&D hours, the employee's whole logged time is R&D, so the
        # full salary is capitalisable (ratio 1). This implements the spec's
        # "工资 × 研发工时占比" so a part-time researcher is only partially capitalised.
        ratio = (rd_hours / total) if (total > rd_hours and total > 0) else Decimal("1")
        amount = Decimal(str(gross)) * ratio
        if amount <= 0:
            continue
        items.append(ExpenseItem(name=key, amount=amount, account_level_3="人工费", category="人工费"))
    return allocate_labor(salaries=items, employee_hours=employee_hours)


def populate_allocation_document(
    doc: Any,
    *,
    expenses: list[ExpenseItem],
    source_hour_rows: list[Any],
    source_expense_rows: list[Any],
    project_hours: list[ProjectHour],
    salaries: Mapping[str, float] | None = None,
    total_hours: Mapping[str, float] | None = None,
) -> None:
    if salaries:
        # Labor now comes from Salary Slips; drop any personnel-category imported
        # expenses (legacy GL payroll rows) for this period so labor is not counted
        # twice with the Salary-Slip labor added below.
        expenses = [e for e in expenses if (e.category or "") != "personnel"]
    result = allocate_expenses(expenses=expenses, project_hours=project_hours)
    if salaries:
        result = combine_results(
            result, _labor_result(salaries, source_hour_rows, project_hours, total_hours)
        )
    expense_sources = _source_expense_by_name(source_expense_rows)

    doc.set("hour_snapshots", [])
    doc.set("expense_snapshots", [])
    doc.set("lines", [])

    for row in source_hour_rows:
        doc.append("hour_snapshots", row)

    for row in source_expense_rows:
        doc.append("expense_snapshots", row)

    for line in result.lines:
        if str(line.expense_item).startswith(LABOR_PREFIX):
            emp = str(line.expense_item)[len(LABOR_PREFIX):]
            item_name = "人工费-" + emp
            voucher = "工资单:" + emp  # voucher_no is reqd; mark the Salary Slip source
        else:
            source = expense_sources.get(line.expense_item, {})
            item_name = _value(source, "account_level_3", "") or line.expense_item
            voucher = _value(source, "voucher_no", "")
        doc.append(
            "lines",
            {
                "expense_item_name": item_name,
                "voucher_no": voucher,
                "project": line.project,
                "project_stage": line.stage,
                "basis_hours": float(line.basis_hours),
                "ratio": float(line.ratio * 100),
                "allocated_amount": line.amount,
            },
        )

    doc.capitalized_total = result.stage_totals["capitalized"]
    doc.expensed_total = result.stage_totals["expensed"]
    doc.unknown_total = result.stage_totals["unknown"]
    doc.status = "Calculated"
