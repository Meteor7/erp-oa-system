from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ProjectStage = Literal["capitalized", "expensed", "unknown"]


@dataclass(frozen=True)
class ExpenseItem:
    name: str
    amount: Decimal
    account_level_3: str
    category: str
    direct_project: str | None = None


@dataclass(frozen=True)
class ProjectHour:
    project: str
    hours: Decimal
    stage: ProjectStage


@dataclass(frozen=True)
class AllocationLine:
    expense_item: str
    project: str
    stage: ProjectStage
    amount: Decimal
    basis_hours: Decimal
    ratio: Decimal


@dataclass(frozen=True)
class AllocationResult:
    lines: list[AllocationLine]
    project_amounts: dict[str, Decimal]
    stage_totals: dict[ProjectStage, Decimal]