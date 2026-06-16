from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from rayher_hr_payroll.rd_cost.types import (
    AllocationLine,
    AllocationResult,
    ExpenseItem,
    ProjectHour,
    ProjectStage,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _stage_by_project(project_hours: list[ProjectHour]) -> dict[str, ProjectStage]:
    return {row.project: row.stage for row in project_hours}


def _sum_hours(project_hours: list[ProjectHour]) -> Decimal:
    total = sum((row.hours for row in project_hours), Decimal("0"))
    if total <= 0:
        raise ValueError("project_hours total must be greater than zero")
    return total


def _weighted_amounts(
    amount: Decimal, project_hours: list[ProjectHour]
) -> dict[str, Decimal]:
    total_hours = _sum_hours(project_hours)
    raw_rows = []
    rounded = {}
    for row in project_hours:
        raw = amount * row.hours / total_hours
        rounded_amount = _money(raw)
        raw_rows.append((row.project, raw, rounded_amount))
        rounded[row.project] = rounded_amount

    remainder = _money(amount - sum(rounded.values(), Decimal("0")))
    if remainder:
        project, _raw, _rounded = max(
            raw_rows, key=lambda item: (abs(item[1] - item[2]), item[0])
        )
        rounded[project] = _money(rounded[project] + remainder)
    return rounded


def allocate_expenses(
    *, expenses: list[ExpenseItem], project_hours: list[ProjectHour]
) -> AllocationResult:
    stages = _stage_by_project(project_hours)
    lines = []
    project_amounts = defaultdict(lambda: ZERO)
    stage_totals: dict[ProjectStage, Decimal] = {
        "capitalized": ZERO,
        "expensed": ZERO,
        "unknown": ZERO,
    }

    for expense in expenses:
        amount = _money(expense.amount)
        if expense.direct_project:
            allocations = {project: ZERO for project in stages}
            allocations[expense.direct_project] = amount
        else:
            allocations = _weighted_amounts(amount, project_hours)

        total_hours = sum((row.hours for row in project_hours), Decimal("0")) or Decimal("1")
        hours_by_project = {row.project: row.hours for row in project_hours}
        for project in sorted(allocations):
            allocated_amount = _money(allocations[project])
            stage = stages.get(project, "unknown")
            basis_hours = hours_by_project.get(project, Decimal("0"))
            ratio = (basis_hours / total_hours) if not expense.direct_project else Decimal("0")
            lines.append(
                AllocationLine(
                    expense_item=expense.name,
                    project=project,
                    stage=stage,
                    amount=allocated_amount,
                    basis_hours=basis_hours,
                    ratio=ratio,
                )
            )
            project_amounts[project] = _money(project_amounts[project] + allocated_amount)
            stage_totals[stage] = _money(stage_totals[stage] + allocated_amount)

    return AllocationResult(
        lines=lines,
        project_amounts=dict(project_amounts),
        stage_totals=stage_totals,
    )