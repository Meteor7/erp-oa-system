"""境外委托研发计入首页费用的口径（2026-10-13）：按月份直接计入，和研发费用汇总页、分摊页一致。"""
import sys
import types

from rayher_hr_payroll.api import overview_entry

MATRIX = "rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix.rd_allocation_matrix"


def test_foreign_rd_counts_for_every_month_even_without_a_submitted_import(monkeypatch):
    stub = types.ModuleType(MATRIX)
    stub._foreign_matrix_lines_for_month = lambda year, month: [{"project": "RD02", "allocated_amount": 1200.0}] if month == 10 else []
    monkeypatch.setitem(sys.modules, MATRIX, stub)
    # 不再去查国内费用导入有没有提交
    monkeypatch.setattr(overview_entry.frappe, "get_all", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不该查费用导入")))
    rows = overview_entry._foreign_rd_rows([(2026, 9), (2026, 10)])
    assert rows == [{"project": "RD02", "kind": "rd", "amount": 1200.0, "label": overview_entry.FOREIGN_RD_LABEL, "period": (2026, 10)}]
    assert overview_entry._foreign_rd_rows([]) == []
