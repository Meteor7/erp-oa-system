"""看板各部分拼在一起以后的对齐检查：布局、提供者、目标表、物料逾期口径。"""
import glob
import os
import re

import pytest

from rayher_hr_payroll.dashboard import core, layout


@pytest.fixture(scope="module", autouse=True)
def providers():
    core.load_providers()


# 「待我处理」类的本人数据：范围由底层接口按本人限定，所以不需要角色（别的块都要有真实权限才返回）。
PERSONAL_BLOCKS = {"claim.todo", "pay.todo", "block.aging", "alert.me_timesheet", "alert.me_leave_unused", "block.me_requests", "block.me_timesheet"}


def test_every_layout_key_has_a_provider_of_the_right_kind():
    missing, wrong = [], []
    for profile, spec in layout.LAYOUTS.items():
        for tab in spec["tabs"]:
            for bucket, kind in (("kpis", "kpi"), ("alerts", "alert"), ("blocks", "block")):
                for key in tab[bucket]:
                    provider = core.REGISTRY.get(key)
                    if provider is None:
                        missing.append((profile, tab["key"], key))
                    elif provider.kind != kind:
                        wrong.append((key, provider.kind, kind))
    assert not missing, f"layout keys without a provider: {sorted(set(missing))}"
    assert not wrong, wrong
    assert "todo.queue" in core.REGISTRY and core.REGISTRY["todo.queue"].kind == "todos"


def test_no_provider_is_left_out_of_every_layout():
    used = layout.all_block_keys()
    orphans = sorted(key for key, provider in core.REGISTRY.items() if provider.kind != "drill" and key not in used)
    assert not orphans, f"providers that no layout uses: {orphans}"


def _drill_items_used_by_providers():
    root = os.path.dirname(os.path.abspath(core.__file__))
    used = set()
    for path in glob.glob(os.path.join(root, "*.py")):
        used.update(re.findall(r"""drill_to\(\s*["']([A-Za-z0-9_.]+)["']""", open(path, encoding="utf-8").read()))
    return used


def test_every_drill_list_is_opened_by_some_card_and_every_card_link_has_its_list():
    """点合计类数字进去的明细清单：卡片指向的清单一定存在，存在的清单一定有卡片指向（不留死代码）。"""
    lists = {key[len(core.DRILL_PREFIX):] for key, provider in core.REGISTRY.items() if provider.kind == "drill"}
    used = _drill_items_used_by_providers()
    assert not used - lists, f"cards point at lists that do not exist: {sorted(used - lists)}"
    assert not lists - used, f"lists no card points at: {sorted(lists - used)}"
    assert all(key.startswith(core.DRILL_PREFIX) for key, provider in core.REGISTRY.items() if provider.kind == "drill")


def test_the_drill_target_is_declared_with_the_item_and_period_parameters():
    spec = core.load_targets()["drill"]
    assert spec["path"] == "/dashboard/detail" and spec["params"] == ["item", "period"]
    assert core.target("drill", item="approval.stuck", period="2026-10") == {"key": "drill", "params": {"item": "approval.stuck", "period": "2026-10"}}


def test_a_drill_list_that_the_user_may_not_see_is_not_returned():
    ctx = core.Ctx(user="nobody@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-09")
    for key in ("cost.total", "approval.stuck", "pay.in_approval", "att.leave", "proc.po_overdue", "proc.urgent", "invoice.review"):
        assert core.get_detail_for(ctx, key) is None, key
    assert core.get_detail_for(ctx, "no.such.list") is None
    assert core.get_detail_for(ctx, "") is None


def test_every_literal_target_used_in_a_provider_exists():
    root = os.path.dirname(os.path.abspath(core.__file__))
    known = set(core.load_targets())
    unknown = {}
    for path in glob.glob(os.path.join(root, "*.py")):
        text = open(path, encoding="utf-8").read()
        for key in re.findall(r"""target\(\s*["']([a-z_]+\.[a-z_]+|payroll|social|housing|allocation)["']""", text):
            if key not in known:
                unknown.setdefault(os.path.basename(path), set()).add(key)
    assert not unknown, unknown


def test_material_overdue_uses_the_same_po_statuses_everywhere():
    from rayher_hr_payroll.api import material_progress
    from rayher_hr_payroll.dashboard import procurement

    assert tuple(procurement.EFFECTIVE_PO) == tuple(material_progress.LIVE_PO_STATUSES)


def test_contract_line_overdue_rules():
    from types import SimpleNamespace as L

    from rayher_hr_payroll.api.material_progress import contract_line_overdue as overdue

    line = lambda due, got, qty: L(contract_delivery_date=due, received_quantity=got, quantity=qty)
    assert overdue(line("2026-10-01", 0, 5), "供应商制作中", "2026-10-09")
    assert overdue(line("2026-10-08", 3, 5), "已生效", "2026-10-09")
    assert not overdue(line("2026-10-09", 0, 5), "已生效", "2026-10-09")        # 今天到期不算逾期
    assert not overdue(line("2026-10-01", 5, 5), "已生效", "2026-10-09")        # 已收齐
    assert not overdue(line("2026-10-01", 0, 5), "草稿", "2026-10-09")          # 演示员工116还没生效
    assert not overdue(line("2026-10-01", 0, 5), "已取消", "2026-10-09")
    assert not overdue(line("2026-10-01", 0, 5), "已关闭", "2026-10-09")
    assert not overdue(line(None, 0, 5), "已生效", "2026-10-09")                # 没填演示员工116交期
    assert not overdue(line("", 0, 5), "已生效", "2026-10-09")


@pytest.mark.parametrize("profile", sorted(core.PROFILE_LABELS))
def test_a_user_with_no_rights_gets_an_empty_but_well_formed_page_for_every_profile(profile):
    """没有任何角色和岗位的人：有 visible 判断的块一个都拿不到，也不会被调用；页面结构照样完整。
    只有「本人数据」的块（visible 为空，范围由底层接口按本人限定）会被尝试，这里没有数据库所以记成块失败，不会漏数据。"""
    ctx = core.Ctx(user="nobody@example.com", roles=frozenset({"Employee"}), positions=frozenset(), period="2026-10", today="2026-10-09")
    ctx.profile = profile
    out = core.assemble(ctx, layout.LAYOUTS[profile], include_todos=False)
    assert out["role"]["key"] == profile and out["tabs"] and out["tabs"][0]["key"] == "overview"
    personal = lambda key: key.startswith("me.") or key in PERSONAL_BLOCKS
    for page in out["pages"].values():
        for bucket in ("kpis", "alerts", "blocks"):
            for item in page[bucket]:
                assert personal(item["key"]), f"{item['key']} was returned to a user with no rights"
        for error in page["errors"]:
            assert personal(error["key"]), f"{error['key']} was called for a user with no rights"


def test_pmc_layout_never_returns_money_even_when_the_user_also_holds_finance_roles():
    from rayher_hr_payroll.dashboard import procurement

    ctx = core.Ctx(user="pmc@example.com", roles=frozenset({"Employee", "Purchase User", "Accounts User"}),
                   positions=frozenset({"pmc"}), period="2026-10", today="2026-10-09")
    for key in ("proc.month_amount", "block.proc_suppliers", "block.proc_projects", "proc.ready_to_pay", "proc.pay_planned_passed", "alert.pay_planned_passed"):
        provider = core.REGISTRY[key]
        assert provider.visible is not None and not provider.visible(ctx), key
    assert procurement._money_blocked(ctx)
