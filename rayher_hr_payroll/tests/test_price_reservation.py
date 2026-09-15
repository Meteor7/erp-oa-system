"""Quantity lifecycle regression tests using the actual API function bodies."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict
from decimal import Decimal
from unittest.mock import Mock


class Row(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


class ReservationTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).parents[1] / "api" / "procurement_chain.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        names = {"_locked_pr_documents", "_change_reserved_pr_lines",
                 "_release_reserved_pr_lines", "_reserve_released_pr_lines"}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.line = Row(name="line", quantity=1, remaining_quantity=0, po_quantity=0, save=Mock())
        self.pr = Row(status="待采购", lines=[self.line])
        def get_doc(doctype, name, **kwargs):
            self.assertTrue(kwargs.get("for_update"))
            return self.pr
        def fail(message):
            raise ValueError(message)
        self.ns = dict(frappe=Row(get_doc=get_doc, throw=fail), defaultdict=defaultdict,
                       Decimal=Decimal, _decimal=lambda v: Decimal(str(v or 0)),
                       _text=lambda v: str(v or "").strip())
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), self.ns)
        self.approval = Row(pr_quantities_released=0,
                            lines=[Row(source_pr="PR", source_pr_line="line", quantity=1)])
        self.release = self.ns["_release_reserved_pr_lines"]
        self.reserve = self.ns["_reserve_released_pr_lines"]

    def test_repeated_withdraw_submit_cycle_conserves_quantity(self):
        for _ in range(5):
            self.release(self.approval)
            self.assertEqual(self.line.remaining_quantity, 1)
            self.reserve(self.approval)
            self.assertEqual(self.line.remaining_quantity, 0)

    def test_withdraw_then_cancel_releases_once(self):
        self.release(self.approval)
        self.release(self.approval)
        self.assertEqual(self.line.remaining_quantity, 1)
        self.assertEqual(self.line.save.call_count, 1)

    def test_initial_submit_does_not_reserve_twice(self):
        self.reserve(self.approval)
        self.assertEqual(self.line.remaining_quantity, 0)
        self.line.save.assert_not_called()

    def test_resubmit_fails_if_another_approval_took_quantity(self):
        self.approval.pr_quantities_released = 1
        with self.assertRaises(ValueError):
            self.reserve(self.approval)
        self.assertEqual(self.approval.pr_quantities_released, 1)
        self.line.save.assert_not_called()

    def test_partial_quantity_retains_other_reservations(self):
        self.line.quantity = 10
        self.line.remaining_quantity = 3
        self.line.po_quantity = 2
        self.approval.lines[0].quantity = 2
        self.release(self.approval)
        self.assertEqual(self.line.remaining_quantity, 5)
        self.reserve(self.approval)
        self.assertEqual(self.line.remaining_quantity, 3)

    def test_invalid_old_balance_is_blocked(self):
        self.line.remaining_quantity = 2
        with self.assertRaises(ValueError):
            self.release(self.approval)
        self.line.save.assert_not_called()

    def test_release_cannot_exceed_unordered_quantity(self):
        self.line.po_quantity = 1
        with self.assertRaises(ValueError):
            self.release(self.approval)

    def test_missing_source_is_error_not_silent_skip(self):
        self.approval.lines[0].source_pr_line = "missing"
        with self.assertRaises(ValueError):
            self.release(self.approval)

    def test_all_lines_validated_before_any_write(self):
        self.approval.lines.append(Row(source_pr="PR", source_pr_line="missing", quantity=1))
        with self.assertRaises(ValueError):
            self.release(self.approval)
        self.line.save.assert_not_called()

    def test_unselected_lines_only_are_released(self):
        other = Row(name="other", quantity=2, remaining_quantity=0, po_quantity=0, save=Mock())
        self.pr.lines.append(other)
        row = Row(source_pr="PR", source_pr_line="other", quantity=2)
        self.ns["_change_reserved_pr_lines"](self.approval, release=True, lines=[row])
        self.assertEqual(other.remaining_quantity, 2)
        self.assertEqual(self.line.remaining_quantity, 0)


if __name__ == "__main__":
    unittest.main()
