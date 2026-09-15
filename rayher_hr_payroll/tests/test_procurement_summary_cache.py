import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class SummaryCacheTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).parents[1] / "procurement_summary_cache.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        tree.body = [node for node in tree.body if not (
            isinstance(node, ast.Import) and any(a.name in {"frappe", "redis"} for a in node.names))]
        self.frappe = SimpleNamespace(
            cache=lambda: SimpleNamespace(make_key=lambda key: ("site|" + key).encode()))
        self.ns = {"frappe": self.frappe, "redis": SimpleNamespace(), "__name__": "cache_test"}
        exec(compile(tree, str(source), "exec"), self.ns)
        self.docs = [SimpleNamespace(name=name, request_type="采购申请",
                     workflow_status="已完成", business_status="", business_lines=[])
                     for name in ("A", "B", "C")]
        self.data = {doc.name: ([], [], [], {}, {}) for doc in self.docs}
        self.ns["_read_inputs"] = lambda docs: {d.name: self.data[d.name] for d in docs}
        self.storage = {}
        client = Mock()
        client.mget.side_effect = lambda keys: [self.storage.get(key) for key in keys]
        client.pipeline.return_value = client
        client.set.side_effect = lambda key, value, **kw: self.storage.update({key: value})
        self.client = client
        self.ns["_client"] = lambda: client
        self.calculate = Mock(side_effect=lambda doc, **kw: {
            "stage": "po", "label": "PO", "summary": doc.name,
            "pr_numbers": [], "price_approval_numbers": [], "po_numbers": [],
            "pending_pr_lines": 0, "pending_price_lines": 0, "draft_price_lines": 0,
            "approval_lines": 0, "po_lines": 0})
        self.prepare = self.ns["prepare_summaries"]

    def read(self):
        with self.prepare(self.docs, self.calculate):
            return [self.ns["prepared_summary"](doc.name) for doc in self.docs]

    def test_warm_cache_skips_all_calculations(self):
        self.read()
        self.calculate.reset_mock()
        self.read()
        self.calculate.assert_not_called()

    def test_single_change_recalculates_only_affected_request(self):
        self.read()
        self.calculate.reset_mock()
        self.data["B"] = ([], [], [], {}, {"PO": "已关闭"})
        self.read()
        self.assertEqual([call.args[0].name for call in self.calculate.call_args_list], ["B"])

    def test_merged_po_change_recalculates_all_its_requests(self):
        self.read()
        self.calculate.reset_mock()
        for name in ("A", "C"):
            self.data[name] = ([], [], [], {}, {"merged": "已关闭"})
        self.read()
        self.assertEqual([call.args[0].name for call in self.calculate.call_args_list], ["A", "C"])

    def test_redis_outage_uses_live_inputs(self):
        self.client.mget.side_effect = ConnectionError("offline")
        self.read()
        self.assertEqual(self.calculate.call_count, 3)

    def test_bad_cache_recomputed(self):
        self.read()
        for key in self.storage:
            self.storage[key] = "invalid"
        self.calculate.reset_mock()
        self.read()
        self.assertEqual(self.calculate.call_count, 3)

    def test_expired_cache_recomputed(self):
        self.read()
        self.storage.clear()
        self.calculate.reset_mock()
        self.read()
        self.assertEqual(self.calculate.call_count, 3)

    def test_context_and_results_are_isolated(self):
        with self.prepare(self.docs, self.calculate):
            result = self.ns["prepared_summary"]("A")
            result["stage"] = "wrong"
            self.assertEqual(self.ns["prepared_summary"]("A")["stage"], "po")
        self.assertIsNone(self.ns["prepared_summary"]("A"))

    def test_old_transaction_result_cannot_overwrite_new_version(self):
        self.read()
        old = self.data["A"]
        self.data["A"] = ([], [], [], {}, {"PO": "已关闭"})
        self.read()
        self.data["A"] = old
        self.read()  # a late old snapshot writes/reads its own key only
        self.data["A"] = ([], [], [], {}, {"PO": "已关闭"})
        self.calculate.reset_mock()
        self.read()
        self.calculate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
