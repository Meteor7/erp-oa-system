"""研发费用分摊「预览」：按当前费用导入、工时、工资数据现算一份分摊，只读，不写库。

定版（finalize_allocation）才会真正创建并提交分摊单。预览和定版用同一个 calculate()，
所以预览看到的就是此刻定版会得到的结果。

这里的 frappe 都在函数内部导入：测试里会替换 sys.modules["frappe"]，模块级导入会留住旧的替身。
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

PREVIEW_PARENT = "PREVIEW"


def new_allocation_doc(period, year, month, expense_import):
    """一份还没入库的 RD Cost Allocation（预览和定版共用，保证两边参数一致）。"""
    import frappe

    return frappe.get_doc(dict(
        doctype="RD Cost Allocation", period=period, year=year, month=month,
        expense_import=expense_import, allocation_basis="rd_project_hours", scope="all",
        calculation_version="v1",
    ))


def _message_log():
    import frappe

    log = getattr(getattr(frappe, "local", None), "message_log", None)
    return log if isinstance(log, list) else None


def _message_text(entry):
    data = entry
    if isinstance(entry, str):
        try:
            data = json.loads(entry)
        except ValueError:
            data = entry
    if isinstance(data, dict):
        data = data.get("message") or ""
    return re.sub(r"<[^>]+>", "", str(data or "")).strip()


def _business_errors():
    import frappe

    errors = [ValueError]
    for name in ("ValidationError", "DoesNotExistError", "LinkValidationError"):
        cls = getattr(frappe, name, None)
        if isinstance(cls, type) and issubclass(cls, BaseException):
            errors.append(cls)
    return tuple(errors)


def build_preview(period, year, month):
    """Return None when the month has no (non-cancelled) expense import, otherwise
    SimpleNamespace(import_name, doc, warnings, error).

    - doc: the calculated, UNSAVED allocation document (None when calculate() failed).
    - warnings: calculate() reports "labour skipped" notices through frappe.msgprint; they are
      captured here (removed from the request's message log so the page does not pop them up)
      and returned as plain strings.
    - error: user-facing text when calculate() refused (e.g. duplicated labour sources)."""
    from rayher_hr_payroll.api._guards import find_period_import

    import_name = find_period_import(year, month)
    if not import_name:
        return None
    doc = new_allocation_doc(period, year, month, import_name)
    log = _message_log()
    start = len(log) if log is not None else 0
    error = None
    try:
        doc.calculate()
    except _business_errors() as exc:
        error = str(exc) or exc.__class__.__name__
    except Exception as exc:  # a preview must never take the whole page down
        error = "预览计算失败：%s: %s" % (exc.__class__.__name__, exc)
    finally:
        warnings = []
        if log is not None:
            added = list(log[start:])
            del log[start:]
            warnings = [text for text in (_message_text(item) for item in added) if text]
    return SimpleNamespace(
        import_name=import_name, doc=None if error else doc, warnings=warnings, error=error,
    )


def _value(row, fieldname, default=None):
    if isinstance(row, dict):
        return row.get(fieldname, default)
    return getattr(row, fieldname, default)


def preview_report_lines(doc, period):
    """The preview's domestic lines in the RD Allocation Matrix row shape (same as the DB path)."""
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix.rd_allocation_matrix import (
        enrich_allocation_lines_with_snapshot_accounts,
    )

    lines = [
        {
            "parent": PREVIEW_PARENT,
            "voucher_no": _value(line, "voucher_no"),
            "expense_item_name": _value(line, "expense_item_name"),
            "account_level_3": _value(line, "account_level_3") or "",
            "account_level_4": _value(line, "account_level_4") or "",
            "project": _value(line, "project"),
            "project_stage": _value(line, "project_stage"),
            "allocated_amount": float(_value(line, "allocated_amount") or 0),  # Decimal 和境外行的 float 不能直接相加
        }
        for line in (_value(doc, "lines", None) or [])
    ]
    snapshots = [
        {
            "parent": PREVIEW_PARENT,
            "voucher_no": _value(row, "voucher_no"),
            "expense_item": _value(row, "expense_item"),
            "account_level_1": _value(row, "account_level_1"),
            "account_level_2": _value(row, "account_level_2"),
            "account_level_3": _value(row, "account_level_3"),
            "account_level_4": _value(row, "account_level_4"),
        }
        for row in (_value(doc, "expense_snapshots", None) or [])
    ]
    enriched = enrich_allocation_lines_with_snapshot_accounts(lines, snapshots)
    for line in enriched:
        line["period"] = period
    return enriched
