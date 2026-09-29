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


def test_part_time_rd_without_denominator_skips_and_surfaces():
    # 非全时研发 with only R&D hours logged (total == rd_hours): the ratio is unknowable,
    # so the employee is skipped (NOT capitalized 100%, NOT aborting the period) and
    # reported back to the caller so finance can complete the timesheet.
    doc = FakeDoc()
    skipped = populate_allocation_document(
        doc, expenses=[],
        source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("4")}],
        source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("4"), "capitalized")],
        salaries={"E1": 10000}, total_hours={"E1": 4}, personnel_types={"E1": "非全时研发"},
    )
    assert skipped == ["E1"]
    assert not [l for l in doc.tables["lines"] if str(l["expense_item_name"]).startswith("人工费")]


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


def test_part_time_rd_uses_the_month_standard_hours_as_denominator():
    # 审查 X2-4（决定 D2）：页面只填研发工时时，按当月标准工时算比例，不再整月跳过。
    doc = FakeDoc()
    skipped = populate_allocation_document(
        doc, expenses=[],
        source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("88")}],
        source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("88"), "capitalized")],
        salaries={"E1": 17600}, total_hours={"E1": 88}, personnel_types={"E1": "研发辅助"},
        standard_hours={"E1": 176},
    )
    labor = [l for l in doc.tables["lines"] if str(l["expense_item_name"]).startswith("人工费")]
    assert skipped == []
    assert sum(float(l["allocated_amount"]) for l in labor) == 8800.0  # 17600 * 88/176


def test_part_time_denominator_takes_the_larger_of_logged_and_standard_hours():
    doc = FakeDoc()
    populate_allocation_document(
        doc, expenses=[],
        source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("80")}],
        source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("80"), "capitalized")],
        salaries={"E1": 20000}, total_hours={"E1": 200}, personnel_types={"E1": "非全时研发"},
        standard_hours={"E1": 160},
    )
    labor = [l for l in doc.tables["lines"] if str(l["expense_item_name"]).startswith("人工费")]
    assert sum(float(l["allocated_amount"]) for l in labor) == 8000.0  # 20000 * 80/200


def test_full_time_rd_ignores_standard_hours():
    doc = FakeDoc()
    populate_allocation_document(
        doc, expenses=[],
        source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("80")}],
        source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("80"), "capitalized")],
        salaries={"E1": 10000}, total_hours={"E1": 80}, personnel_types={"E1": "全时研发"},
        standard_hours={"E1": 160},
    )
    assert doc.capitalized_total == Decimal("10000.00")


def test_rd_staff_without_a_salary_slip_are_reported():
    # 审查 X2-11-B（决定 D14）：有工时没工资单的员工原来悄悄不算，现在列出来。
    doc = FakeDoc()
    skipped = populate_allocation_document(
        doc, expenses=[],
        source_hour_rows=[
            {"employee": "E1", "project": "P1", "hours": Decimal("8")},
            {"employee": "E2", "project": "P1", "hours": Decimal("8")},
            {"employee": "E3", "project": "P1", "hours": Decimal("8")},
        ],
        source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("24"), "capitalized")],
        salaries={"E1": 10000, "E3": 0}, total_hours={"E1": 8}, personnel_types={"E1": "全时研发"},
    )
    assert skipped == ["E2（无工资单）", "E3（无工资单）"]
    assert doc.capitalized_total == Decimal("10000.00")


def test_confirmed_company_contributions_follow_the_salary_ratio_as_their_own_accounts():
    # 审查 X2-2（决定 D1）：单位社保、公积金按工资同样的研发占比进研发人工，单列科目。
    doc = FakeDoc()
    populate_allocation_document(
        doc, expenses=[],
        source_hour_rows=[
            {"employee": "E1", "project": "P1", "hours": Decimal("60")},
            {"employee": "E1", "project": "P2", "hours": Decimal("20")},
        ],
        source_expense_rows=[],
        project_hours=[ProjectHour("P1", Decimal("60"), "capitalized"), ProjectHour("P2", Decimal("20"), "expensed")],
        salaries={"E1": 10000}, total_hours={"E1": 80}, personnel_types={"E1": "非全时研发"},
        standard_hours={"E1": 160}, contributions={"E1": {"si": 3000, "hf": 1000}},
    )
    by_account = {}
    for line in doc.tables["lines"]:
        by_account[line["account_level_3"]] = by_account.get(line["account_level_3"], 0) + float(line["allocated_amount"])
    assert by_account == {"人工费": 5000.0, "社会保险费用（单位）": 1500.0, "住房公积金（单位）": 500.0}
    si = [line for line in doc.tables["lines"] if line["account_level_3"] == "社会保险费用（单位）"]
    assert {line["voucher_no"] for line in si} == {"社保:E1"} and {line["project"] for line in si} == {"P1", "P2"}


def test_gl_social_insurance_rows_are_allowed_when_hr_has_no_confirmed_records():
    # 原来有工资单时，任何人员人工类总账行都报冲突；现在单位社保行只和人事的单位社保冲突。
    doc = FakeDoc()
    expenses = [ExpenseItem(name="GL-SI", amount=Decimal("600"), account_level_3="社会保险费用（单位）", category="personnel")]
    populate_allocation_document(
        doc, expenses=expenses, source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("4")}],
        source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("4"), "capitalized")],
        salaries={"E1": 10000}, total_hours={"E1": 4}, personnel_types={"E1": "全时研发"},
    )
    names = [str(l["expense_item_name"]) for l in doc.tables["lines"]]
    assert "GL-SI" in names and any(n.startswith("人工费") for n in names)


def test_gl_social_insurance_rows_conflict_with_confirmed_hr_records():
    import pytest

    doc = FakeDoc()
    expenses = [ExpenseItem(name="GL-SI", amount=Decimal("600"), account_level_3="社会保险费用（单位）", category="personnel")]
    with pytest.raises(ValueError, match="社会保险费用"):
        populate_allocation_document(
            doc, expenses=expenses, source_hour_rows=[{"employee": "E1", "project": "P1", "hours": Decimal("4")}],
            source_expense_rows=[], project_hours=[ProjectHour("P1", Decimal("4"), "capitalized")],
            salaries={"E1": 10000}, total_hours={"E1": 4}, personnel_types={"E1": "全时研发"},
            contributions={"E1": {"si": 300, "hf": 0}},
        )
