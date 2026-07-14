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


def _most_specific_expense_item_name(source: Any, fallback: Any) -> str:
    for fieldname in ("account_level_4", "account_level_3", "account_level_2", "account_level_1"):
        value = str(_value(source, fieldname, "") or "").strip()
        if value:
            return value
    return str(fallback)


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


def _labor_result(salaries, source_hour_rows, project_hours, total_hours=None, personnel_types=None, skipped=None):
    employee_hours = _employee_project_hours(source_hour_rows, project_hours)
    total_hours = total_hours or {}
    personnel_types = personnel_types or {}
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
        # ratio = R&D hours / total worked hours (<= 1), per the spec "工资 × 研发工时占比".
        if total > rd_hours and total > 0:
            ratio = rd_hours / total
        elif str(personnel_types.get(emp) or "") == "全时研发":
            # Full-time R&D: by definition all worked time is R&D, so the full salary
            # is capitalisable even when only R&D hours are logged.
            ratio = Decimal("1")
        else:
            # 非全时研发/研发辅助 with no usable total denominator: their non-R&D time was
            # not captured (the Timesheet validator only accepts R&D project rows), so
            # 研发工时占比 cannot be computed. Capitalising the full salary would over-state
            # R&D cost AND aborting the whole period is too blunt -- skip this employee and
            # surface them so finance completes the timesheet or reclassifies, then re-runs.
            if skipped is not None:
                skipped.append(str(emp))
            continue
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
    personnel_types: Mapping[str, str] | None = None,
) -> None:
    skipped: list = []
    labor = None
    if salaries:
        labor = _labor_result(
            salaries, source_hour_rows, project_hours, total_hours, personnel_types, skipped
        )
    if labor and labor.lines and any((e.category or "") == "personnel" for e in expenses):
        # Personnel-category GL rows ARE R&D labour booked via GL; combined with the
        # Salary-Slip labour they double-count R&D personnel cost. Only a real conflict
        # (slips that actually produced labour) raises -- a period whose salaried R&D
        # employees logged no R&D hours produces no labour, so the GL rows are the sole
        # source and there is nothing to double-count.
        raise ValueError(
            "本期同时存在「人工费」类导入费用与工资单(研发人工费),会重复计算研发人工成本。"
            "请移除人工费类导入费用,或本期不纳入工资单人工费,只保留一种来源。"
        )
    result = allocate_expenses(expenses=expenses, project_hours=project_hours)
    if labor:
        result = combine_results(result, labor)
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
            item_name = "\u4eba\u5de5\u8d39-" + emp
            voucher = "\u5de5\u8d44\u5355:" + emp  # voucher_no is reqd; mark the Salary Slip source
            account_level_3 = "\u4eba\u5de5\u8d39"
            account_level_4 = emp
        else:
            source = expense_sources.get(line.expense_item, {})
            item_name = _most_specific_expense_item_name(source, line.expense_item)
            voucher = _value(source, "voucher_no", "")
            account_level_3 = str(_value(source, "account_level_3", "") or "").strip() or item_name
            account_level_4 = str(_value(source, "account_level_4", "") or "").strip()
        doc.append(
            "lines",
            {
                "expense_item_name": item_name,
                "voucher_no": voucher,
                "account_level_3": account_level_3,
                "account_level_4": account_level_4,
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
    return skipped
