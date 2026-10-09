from rayher_hr_payroll.department_structure import (
    CANONICAL_DEPARTMENTS,
    department_base_name,
    department_expense_category,
)


def test_base_name_drops_the_company_suffix():
    assert department_base_name("研发软件部 - RAY") == "研发软件部"
    assert department_base_name("客服部 - SHGL") == "客服部"
    assert department_base_name("财务部") == "财务部"
    assert department_base_name("") == ""


def test_every_formal_department_has_the_category_the_staff_costs_already_use():
    expected = {
        "研发": "研发费用", "销售": "销售费用", "客服": "销售费用", "制造": "生产成本",
    }
    for department in CANONICAL_DEPARTMENTS:
        category = department_expense_category(department)
        assert category in {"研发费用", "管理费用", "销售费用", "生产成本"}, department
    for name in ("研发软件部", "研发算法部", "研发光学部", "研发机械部", "研发电气部", "研发系统部", "研发AI部", "研发部", "知识产权部"):
        assert department_expense_category(name + " - RAY") == "研发费用", name
    assert department_expense_category("销售部 - SHGL") == expected["销售"]
    assert department_expense_category("客服部 - RAY") == expected["客服"]
    assert department_expense_category("制造部 - RAY") == expected["制造"]
    for name in ("财务部", "人事行政部", "总经办", "IT部", "项目申报部", "仓库部", "采购部", "物控部"):
        assert department_expense_category(name + " - RAY") == "管理费用", name


def test_unknown_or_legacy_departments_have_no_category():
    assert department_expense_category("Accounts - RAY") == ""
    assert department_expense_category("") == ""
    assert department_expense_category(None) == ""
