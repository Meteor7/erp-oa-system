from decimal import Decimal

from rayher_hr_payroll.rd_cost.document_builder import populate_allocation_document
from rayher_hr_payroll.rd_cost.types import ExpenseItem, ProjectHour


class FakeDoc:
    def __init__(self):
        self.tables = {}
        self.status = None
        self.capitalized_total = None
        self.expensed_total = None
        self.unknown_total = None

    def set(self, field, value):
        self.tables[field] = []

    def append(self, field, value):
        self.tables.setdefault(field, []).append(value)


def test_labor_cost_allocated_by_employee_hours_and_merged():
    doc = FakeDoc()
    # E1 logged 3h on capitalized P1 and 1h on expensed P2; salary 10000.
    source_hour_rows = [
        {"employee": "E1", "project": "P1", "hours": Decimal("3")},
        {"employee": "E1", "project": "P2", "hours": Decimal("1")},
    ]
    project_hours = [
        ProjectHour(project="P1", hours=Decimal("3"), stage="capitalized"),
        ProjectHour(project="P2", hours=Decimal("1"), stage="expensed"),
    ]
    populate_allocation_document(
        doc, expenses=[], source_hour_rows=source_hour_rows,
        source_expense_rows=[], project_hours=project_hours,
        salaries={"E1": 10000}, personnel_types={"E1": "全时研发"},
    )
    # 10000 split 3:1 -> 7500 capitalized (P1), 2500 expensed (P2)
    assert doc.capitalized_total == Decimal("7500.00")
    assert doc.expensed_total == Decimal("2500.00")
    labor_lines = [l for l in doc.tables["lines"] if str(l["expense_item_name"]).startswith("人工费")]
    assert len(labor_lines) == 2
    assert {l["project"] for l in labor_lines} == {"P1", "P2"}


def test_no_salaries_means_no_labor_lines_backward_compatible():
    doc = FakeDoc()
    source_hour_rows = [{"employee": "E1", "project": "P1", "hours": Decimal("4")}]
    project_hours = [ProjectHour(project="P1", hours=Decimal("4"), stage="capitalized")]
    populate_allocation_document(
        doc, expenses=[], source_hour_rows=source_hour_rows,
        source_expense_rows=[], project_hours=project_hours,
    )
    assert doc.tables["lines"] == []
    assert doc.capitalized_total == Decimal("0.00")


def test_labor_scaled_by_rd_hour_ratio():
    # E1 logged 4 R&D hours on capitalized P1, but 8 total worked hours that month
    # (4 non-R&D). gross 10000 -> only 4/8 = 50% is R&D-capitalisable -> 5000.
    doc = FakeDoc()
    source_hour_rows = [{"employee": "E1", "project": "P1", "hours": Decimal("4")}]
    project_hours = [ProjectHour(project="P1", hours=Decimal("4"), stage="capitalized")]
    populate_allocation_document(
        doc, expenses=[], source_hour_rows=source_hour_rows,
        source_expense_rows=[], project_hours=project_hours,
        salaries={"E1": 10000}, total_hours={"E1": 8}, personnel_types={"E1": "全时研发"},
    )
    assert doc.capitalized_total == Decimal("5000.00")


def test_labor_full_salary_when_all_time_is_rd():
    # total == R&D hours -> ratio 1 -> full salary capitalised (full-time researcher).
    doc = FakeDoc()
    source_hour_rows = [{"employee": "E1", "project": "P1", "hours": Decimal("8")}]
    project_hours = [ProjectHour(project="P1", hours=Decimal("8"), stage="capitalized")]
    populate_allocation_document(
        doc, expenses=[], source_hour_rows=source_hour_rows,
        source_expense_rows=[], project_hours=project_hours,
        salaries={"E1": 10000}, total_hours={"E1": 8}, personnel_types={"E1": "全时研发"},
    )
    assert doc.capitalized_total == Decimal("10000.00")


def test_labor_lines_have_nonempty_voucher_no():
    # voucher_no is reqd on the allocation line; a labor line writing "" would fail insert.
    doc = FakeDoc()
    populate_allocation_document(
        doc, expenses=[], source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("4")}],
        source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("4"), "capitalized")],
        salaries={"E1": 10000}, total_hours={"E1": 4}, personnel_types={"E1": "全时研发"},
    )
    labor = [l for l in doc.tables["lines"] if str(l["expense_item_name"]).startswith("人工费")]
    assert labor and all(l["voucher_no"] for l in labor)


def test_personnel_import_with_salaries_raises_conflict():
    # Personnel-category import + Salary-Slip labour = double-count of R&D labour.
    # Must raise (force one source), NOT silently drop (which could under-count).
    import pytest
    doc = FakeDoc()
    expenses = [ExpenseItem(name="GL-PERSONNEL", amount=Decimal("5000"), account_level_3="工资", category="personnel")]
    with pytest.raises(ValueError):
        populate_allocation_document(
            doc, expenses=expenses, source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("4")}],
            source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("4"), "capitalized")],
            salaries={"E1": 10000}, total_hours={"E1": 4}, personnel_types={"E1": "全时研发"},
        )


def test_non_personnel_imports_coexist_with_labor():
    # Non-personnel imports + Salary-Slip labour are fine (no double-count).
    doc = FakeDoc()
    expenses = [ExpenseItem(name="GL-MATERIAL", amount=Decimal("3000"), account_level_3="材料", category="other")]
    populate_allocation_document(
        doc, expenses=expenses, source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("4")}],
        source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("4"), "capitalized")],
        salaries={"E1": 10000}, total_hours={"E1": 4}, personnel_types={"E1": "全时研发"},
    )
    names = [str(l["expense_item_name"]) for l in doc.tables["lines"]]
    assert "GL-MATERIAL" in names and any(n.startswith("人工费") for n in names)


def test_part_time_rd_without_denominator_raises():
    # 非全时研发 with only R&D hours logged (total == rd_hours) must NOT capitalize 100%:
    # their non-R&D time was not captured, so the ratio is unknowable -> refuse.
    import pytest
    doc = FakeDoc()
    with pytest.raises(ValueError):
        populate_allocation_document(
            doc, expenses=[],
            source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("4")}],
            source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("4"), "capitalized")],
            salaries={"E1": 10000}, total_hours={"E1": 4}, personnel_types={"E1": "非全时研发"},
        )


def test_part_time_rd_with_real_denominator_prorates():
    # With a real total > R&D hours, 非全时研发 prorates correctly (no raise).
    doc = FakeDoc()
    populate_allocation_document(
        doc, expenses=[],
        source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("4")}],
        source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("4"), "capitalized")],
        salaries={"E1": 10000}, total_hours={"E1": 8}, personnel_types={"E1": "非全时研发"},
    )
    labor = [l for l in doc.tables["lines"] if str(l["expense_item_name"]).startswith("人工费")]
    assert labor and sum(float(l["allocated_amount"]) for l in labor) == 5000.0  # 10000 * 4/8
