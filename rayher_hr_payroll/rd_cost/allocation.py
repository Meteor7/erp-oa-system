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


def merge_direct_project_stages(
    project_hours: list[ProjectHour],
    stage_by_project: dict[str, ProjectStage],
) -> list[ProjectHour]:
    """Ensure every project named in ``stage_by_project`` is represented in
    ``project_hours``. Projects that logged no hours this period are appended with
    zero hours and their real (date-derived) capitalization stage, so a direct
    expense to an idle project is still classified correctly instead of 'unknown'."""
    present = {row.project for row in project_hours}
    result = list(project_hours)
    for project, stage in stage_by_project.items():
        if project not in present:
            result.append(ProjectHour(project=project, hours=Decimal("0"), stage=stage))
            present.add(project)
    return result


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

    # G2 guard: a direct expense must target a project whose stage we know. If the
    # project is absent from project_hours we cannot classify capitalized/expensed,
    # so fail loudly instead of silently bucketing the amount into 'unknown'.
    for expense in expenses:
        if expense.direct_project and expense.direct_project not in stages:
            raise ValueError(
                f"direct_project '{expense.direct_project}' is not present in "
                "project_hours; its capitalization stage cannot be determined"
            )

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
            allocations = {expense.direct_project: amount}
        else:
            allocations = _weighted_amounts(amount, project_hours)

        total_hours = sum((row.hours for row in project_hours), Decimal("0")) or Decimal("1")
        hours_by_project = {row.project: row.hours for row in project_hours}
        for project in sorted(allocations):
            allocated_amount = _money(allocations[project])
            if allocated_amount == ZERO:
                continue
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

    expected_total = _money(sum((_money(expense.amount) for expense in expenses), ZERO))
    allocated_total = _money(
        stage_totals["capitalized"] + stage_totals["expensed"] + stage_totals["unknown"]
    )
    if allocated_total != expected_total:
        raise ValueError(
            f"allocation totals do not reconcile: allocated {allocated_total}, expected {expected_total}"
        )

    return AllocationResult(
        lines=lines,
        project_amounts=dict(project_amounts),
        stage_totals=stage_totals,
    )


def combine_results(a, b):
    project_amounts = dict(a.project_amounts)
    for proj, amt in b.project_amounts.items():
        project_amounts[proj] = _money(project_amounts.get(proj, ZERO) + amt)
    stage_totals = dict(a.stage_totals)
    for stage, amt in b.stage_totals.items():
        stage_totals[stage] = _money(stage_totals.get(stage, ZERO) + amt)
    return AllocationResult(
        lines=list(a.lines) + list(b.lines),
        project_amounts=project_amounts,
        stage_totals=stage_totals,
    )


def allocate_labor(*, salaries, employee_hours):
    """Allocate each employee's salary across THEIR own project hours (reusing
    allocate_expenses), then sum. `salaries` are ExpenseItem(name='labor:<emp>');
    `employee_hours` maps that same name -> list[ProjectHour]."""
    result = AllocationResult(
        lines=[], project_amounts={},
        stage_totals={"capitalized": ZERO, "expensed": ZERO, "unknown": ZERO},
    )
    for item in salaries:
        hours = employee_hours.get(item.name)
        if not hours:
            continue
        result = combine_results(result, allocate_expenses(expenses=[item], project_hours=hours))
    return result
