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
# 单位社保、公积金按员工单列（修复 2026-09-29，审查 X2-2，决定 D1）：(前缀, 键, 3 级科目, 凭证前缀)。
SI_ACCOUNT = "社会保险费用（单位）"
HF_ACCOUNT = "住房公积金（单位）"
CONTRIBUTION_ITEMS = (
    ("labor_si:", "si", SI_ACCOUNT, "社保"),
    ("labor_hf:", "hf", HF_ACCOUNT, "公积金"),
)
# labor_skipped 里"没有工资单"的员工带这个后缀，和"工时不完整"的区分开（修复 2026-09-29，审查 X2-11-B）。
NO_SALARY_SUFFIX = "（无工资单）"


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


def _labor_result(salaries, source_hour_rows, project_hours, total_hours=None, personnel_types=None, skipped=None,
                  standard_hours=None, contributions=None):
    employee_hours = _employee_project_hours(source_hour_rows, project_hours)
    total_hours = total_hours or {}
    personnel_types = personnel_types or {}
    standard_hours = standard_hours or {}
    contributions = contributions or {}
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
        standard = Decimal(str(standard_hours.get(emp) or 0))
        full_time = str(personnel_types.get(emp) or "") == "全时研发"
        # ratio = R&D hours / total worked hours (<= 1), per the spec "工资 × 研发工时占比".
        if not full_time and standard > 0:
            # 修复（2026-09-29，审查 X2-4，决定 D2）：页面只能填研发工时，非全时研发和研发辅助的
            # 总工时就等于研发工时，原来整月工资都被跳过。现在分母取当月标准工时（工作日×8 扣事假），
            # Desk 里另补了非研发工时的，取两者较大的。
            ratio = rd_hours / max(total, rd_hours, standard)
        elif total > rd_hours and total > 0:
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
        if amount > 0:
            items.append(ExpenseItem(name=key, amount=amount, account_level_3="人工费", category="人工费"))
        # 单位社保、公积金用和工资相同的研发工时占比，分到同样的项目。
        employee_contributions = contributions.get(emp) or contributions.get(str(emp)) or {}
        for prefix, field, account, _voucher in CONTRIBUTION_ITEMS:
            value = Decimal(str(employee_contributions.get(field) or 0)) * ratio
            if value > 0:
                name = prefix + str(emp)
                employee_hours[name] = hours
                items.append(ExpenseItem(name=name, amount=value, account_level_3=account, category="人工费"))
    return allocate_labor(salaries=items, employee_hours=employee_hours)


def _labor_conflicts(labor, expenses):
    """总账的人员人工行和工资单、单位社保公积金重复的科目。

    修复（2026-09-29，审查 X2-2）：原来只要有工资单人工，任何人员人工类总账行都算冲突，
    单位社保和公积金两条路都进不来。现在按科目判断：社保行只和系统算出的单位社保冲突，
    公积金行只和单位公积金冲突，其余人员人工行（工资等）和工资单冲突，和原来一样。
    """
    booked = {str(line.expense_item).split(":", 1)[0] + ":" for line in labor.lines}
    conflicts = set()
    for expense in expenses:
        if (expense.category or "") != "personnel":
            continue
        level_3 = str(expense.account_level_3 or "").strip()
        prefix = next((item[0] for item in CONTRIBUTION_ITEMS if item[2] == level_3), LABOR_PREFIX)
        if prefix in booked:
            conflicts.add(level_3 or "人员人工费用")
    return sorted(conflicts)


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
    standard_hours: Mapping[str, float] | None = None,
    contributions: Mapping[str, Mapping[str, float]] | None = None,
) -> list:
    skipped: list = []
    labor = None
    if salaries:
        labor = _labor_result(
            salaries, source_hour_rows, project_hours, total_hours, personnel_types, skipped, standard_hours,
            contributions,
        )
    # 修复（2026-09-29，审查 X2-11-B，决定 D14）：有研发工时却没有工资单（或应发为 0）的员工，
    # 原来直接不算人工费、也不提示。现在记进 labor_skipped 并提示，先不阻止提交。
    paid = {str(emp) for emp, gross in (salaries or {}).items() if gross}
    hour_employees = sorted({str(_value(row, "employee")) for row in source_hour_rows if _value(row, "employee")})
    skipped.extend(emp + NO_SALARY_SUFFIX for emp in hour_employees if emp not in paid)
    conflicts = _labor_conflicts(labor, expenses) if labor and labor.lines else []
    if conflicts:
        # Personnel-category GL rows ARE R&D labour booked via GL; combined with the
        # Salary-Slip labour (or the confirmed company contributions) they double-count
        # R&D personnel cost. Only a real conflict (labour actually produced for the same
        # account) raises -- a period whose salaried R&D employees logged no R&D hours
        # produces no labour, so the GL rows are the sole source.
        raise ValueError(
            "本期同时存在「人工费」类导入费用与工资单或人事的单位社保、公积金(研发人工费),会重复计算研发人工成本"
            "(重复科目:" + "、".join(conflicts) + ")。"
            "请移除这些导入费用,或本期不纳入工资单人工费,只保留一种来源。"
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
        item_key = str(line.expense_item)
        contribution = next((item for item in CONTRIBUTION_ITEMS if item_key.startswith(item[0])), None)
        if item_key.startswith(LABOR_PREFIX):
            emp = item_key[len(LABOR_PREFIX):]
            item_name = "\u4eba\u5de5\u8d39-" + emp
            voucher = "\u5de5\u8d44\u5355:" + emp  # voucher_no is reqd; mark the Salary Slip source
            account_level_3 = "\u4eba\u5de5\u8d39"
            account_level_4 = emp
        elif contribution:
            prefix, _field, account, voucher_prefix = contribution
            emp = item_key[len(prefix):]
            item_name = account + "-" + emp
            voucher = voucher_prefix + ":" + emp
            account_level_3 = account
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
