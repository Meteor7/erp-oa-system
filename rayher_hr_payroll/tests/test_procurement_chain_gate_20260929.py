"""采购链路跟随功能开关（模块 6，2026-09-29，审查 #8，决定 D7）。"""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "api" / "procurement_chain.py"
PAYMENT = {"list_payment_work_items", "start_po_payment_approval", "push_po_payment_request",
           "approve_po_payment_step", "record_po_payment"}


def _whitelisted_functions():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and any(
            "whitelist" in ast.unparse(decorator) for decorator in node.decorator_list
        ):
            yield node


def test_every_procurement_chain_endpoint_checks_its_feature_gate():
    functions = list(_whitelisted_functions())
    assert len(functions) == 34
    for node in functions:
        body = node.body[1:] if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) else node.body
        first = ast.unparse(body[0])
        expected = "REQUEST_PROCUREMENT_PAYMENT" if node.name in PAYMENT else "REQUEST_PROCUREMENT"
        assert first == f"_require_gate({expected})", node.name
