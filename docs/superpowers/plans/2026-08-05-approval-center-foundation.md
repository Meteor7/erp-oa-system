# 审批中心事前申请与付款关联底座 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有请假、报销和对公付款审批路线的前提下，为本地 Docker 建立“事前申请—付款—看板”的可追溯数据底座，并在新审批路线正式提供前保持新流程不可提交。

**Architecture:** 继续复用 `OA Approval Request` 和现有审批步骤引擎，新增事前申请类型、采购付款类型、事前申请明细及来源关联字段；现有 `费用付款申请` 仍作为报销和对公付款的存储类型，以 `payment_type` 区分“支付个人”和“对公支付”，避免危险的历史数据重分类。关联额度由后端在同一数据库事务中锁定来源申请并计算，前端只展示后端返回的余额和能力标志。

**Tech Stack:** Frappe/ERPNext Python API、MariaDB、Vue 3、frappe-ui、Vue Router、Node test runner、pytest、Yarn 1.22.22、Vite 5。

## Global Constraints

- 本计划只允许修改隔离 Git worktree 和本地 Docker；不得访问或写入 staging `203.0.113.58`、product `203.0.113.32`。
- 执行前必须审计本地 Docker 脏工作树并确定包含所有已验收本地改动的基线提交，再从该提交创建隔离 worktree；不得丢弃、覆盖或顺手提交无关的用户改动。
- 不改变现有“请假申请”和“费用付款申请”的审批步骤、审批人、驳回、加签、确认付款及撤回逻辑。
- 新增的“采购申请”“购买申请”“采购付款”默认关闭提交能力；收到并评审三条正式审批路线后，使用另一份审批路线计划启用。
- 申请人自行判断并选择“采购申请/购买申请”和“固定资产/非固定资产”；系统不根据品名自动改类，审批人发现错误后驳回，申请人修改并重新提交。
- 审批人不得直接修改申请人的业务分类，只能通过、驳回或按现有规则加签。
- “采购付款”必须关联已审批通过的“采购申请”；因购买产生的报销或对公付款必须关联已审批通过的“购买申请”；打车、餐费、差旅、房租、水电、税费等非购买事项允许选择“无事前申请”。
- 一张事前申请可以关联多张付款/报销单；“已付款金额 + 审批中保留金额 + 本次申请金额”不得超过事前申请批准金额。
- 第一阶段不允许同一张事前申请混合固定资产和非固定资产；申请人需要拆成两张申请，每张申请内部可以包含多条同一资产属性的明细。
- 固定资产类别只允许：`办公家具、工具及器具`、`电子设备、研发专用设备、仪器仪表`、`生产设备、生产工具及器具`。
- 固定资产责任人信息作为分类元数据展示：行政部演示员工30、IT部演示员工18、生产部演示员工241；本计划不把三人写入新审批路线。
- 现有记录不得因字段为空或旧分类模糊而被自动改成报销、对公付款、固定资产或非固定资产；无法可靠判断的历史记录显示“历史未分类”。
- 看板是查询视图，不是新的申请类型；所有金额从权限过滤后的服务端数据计算。
- 所有写接口必须在后端重复执行权限、状态、来源类型、余额和版本检查；前端隐藏按钮不构成权限控制。
- 迁移和补丁必须幂等，只补缺失字段或可靠可推导的数据，不覆盖管理员已经维护的值。
- 生成或修改的源码、测试、文档和 Vite 构建产物都必须检查文件开头不是 `%TSD-Header-###%`，且以各自预期的明文头开始。

## 本计划明确不包含

- 采购申请审批路线、购买申请审批路线、采购付款审批路线的审批人和顺序。
- 采购询价、比价、采购订单、合同、供应商门户、收货入库和退货。
- 固定资产验收是否作为付款前置条件、固定资产卡片、标签、折旧和盘点。
- 银企直连或真实银行付款。
- 自动判断申请应归“采购申请”还是“购买申请”。

上述事项必须在取得业务规则后形成独立设计和实施计划，不能由实施人员自行补全。

---

### Task 1: 固化单据类型、来源类型和资产分类契约

**Files:**
- Create: `rayher_hr_payroll/oa_document_types.py`
- Create: `rayher_hr_payroll/tests/test_oa_document_types.py`
- Modify: `rayher_hr_payroll/oa_approval.py`

**Interfaces:**
- Produces: `REQUEST_PROCUREMENT = "采购申请"`、`REQUEST_DIRECT_PURCHASE = "购买申请"`、`REQUEST_PROCUREMENT_PAYMENT = "采购付款"`。
- Produces: `PAYMENT_SOURCE_PROCUREMENT`、`PAYMENT_SOURCE_DIRECT_PURCHASE`、`PAYMENT_SOURCE_NONE`。
- Produces: `ASSET_NATURE_FIXED`、`ASSET_NATURE_NON_FIXED`、`FIXED_ASSET_CATEGORIES`、`asset_responsible_party(category)`。
- Preserves: `REQUEST_LEAVE`、`REQUEST_EXPENSE_PAYMENT` and all existing route constants.

- [ ] **Step 1: Write the failing contract tests**

```python
from rayher_hr_payroll.oa_document_types import (
    ASSET_NATURE_FIXED,
    ASSET_NATURE_NON_FIXED,
    FIXED_ASSET_CATEGORIES,
    REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
    asset_responsible_party,
)


def test_approval_center_document_types_are_stable():
    assert REQUEST_PROCUREMENT == "采购申请"
    assert REQUEST_DIRECT_PURCHASE == "购买申请"
    assert REQUEST_PROCUREMENT_PAYMENT == "采购付款"
    assert {ASSET_NATURE_FIXED, ASSET_NATURE_NON_FIXED} == {"固定资产", "非固定资产"}


def test_fixed_asset_categories_map_to_display_responsible_parties():
    assert FIXED_ASSET_CATEGORIES == (
        "办公家具、工具及器具",
        "电子设备、研发专用设备、仪器仪表",
        "生产设备、生产工具及器具",
    )
    assert asset_responsible_party(FIXED_ASSET_CATEGORIES[0]) == {"department": "行政部", "name": "演示员工30"}
    assert asset_responsible_party(FIXED_ASSET_CATEGORIES[1]) == {"department": "IT部", "name": "演示员工18"}
    assert asset_responsible_party(FIXED_ASSET_CATEGORIES[2]) == {"department": "生产部", "name": "演示员工241"}
```

- [ ] **Step 2: Run the new tests and confirm RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_oa_document_types.py -q`

Expected: FAIL because `rayher_hr_payroll.oa_document_types` does not exist.

- [ ] **Step 3: Implement the immutable contract module**

```python
REQUEST_PROCUREMENT = "采购申请"
REQUEST_DIRECT_PURCHASE = "购买申请"
REQUEST_PROCUREMENT_PAYMENT = "采购付款"

PAYMENT_SOURCE_PROCUREMENT = "关联采购申请"
PAYMENT_SOURCE_DIRECT_PURCHASE = "关联购买申请"
PAYMENT_SOURCE_NONE = "无事前申请"

ASSET_NATURE_FIXED = "固定资产"
ASSET_NATURE_NON_FIXED = "非固定资产"

FIXED_ASSET_RESPONSIBLE_PARTIES = {
    "办公家具、工具及器具": {"department": "行政部", "name": "演示员工30"},
    "电子设备、研发专用设备、仪器仪表": {"department": "IT部", "name": "演示员工18"},
    "生产设备、生产工具及器具": {"department": "生产部", "name": "演示员工241"},
}
FIXED_ASSET_CATEGORIES = tuple(FIXED_ASSET_RESPONSIBLE_PARTIES)


def asset_responsible_party(category):
    try:
        return dict(FIXED_ASSET_RESPONSIBLE_PARTIES[str(category or "").strip()])
    except KeyError as exc:
        raise ValueError(f"不支持的固定资产类别：{category}") from exc
```

Move only the new neutral constants to this module. Keep existing reimbursement asset constants in `oa_approval.py` until the separately reviewed route migration is approved.

- [ ] **Step 4: Run focused and existing route tests**

Run: `python -m pytest rayher_hr_payroll/tests/test_oa_document_types.py rayher_hr_payroll/tests/test_oa_approval_routes.py -q`

Expected: PASS; existing reimbursement route snapshots are unchanged.

- [ ] **Step 5: Commit the contract**

```bash
git add rayher_hr_payroll/oa_document_types.py rayher_hr_payroll/oa_approval.py rayher_hr_payroll/tests/test_oa_document_types.py
git commit -m "feat: define approval center document contracts"
```

### Task 2: Add forward-compatible request schema without rewriting history

**Files:**
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_purchase_request_line/__init__.py`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_purchase_request_line/oa_purchase_request_line.py`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_purchase_request_line/oa_purchase_request_line.json`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.json`
- Create: `rayher_hr_payroll/patches/v1_0/add_approval_center_foundation.py`
- Modify: `rayher_hr_payroll/patches.txt`
- Create: `rayher_hr_payroll/tests/test_approval_center_schema.py`
- Create: `rayher_hr_payroll/tests/test_approval_center_migration.py`

**Interfaces:**
- Produces parent fields: `asset_nature`, `fixed_asset_category`, `payment_source_kind`, `source_request`, `approved_amount_snapshot`, `source_modified`, `business_lines`.
- Produces child row fields: `item_name`, `specification`, `quantity`, `unit`, `unit_price`, `amount`, `remarks`.
- Preserves all current `OA Approval Request` fields and existing rows.

- [ ] **Step 1: Write schema tests before editing JSON**

```python
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _doctype(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_request_schema_has_source_and_asset_dimensions():
    doc = _doctype("rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.json")
    fields = {row["fieldname"]: row for row in doc["fields"]}
    assert fields["request_type"]["options"].splitlines() == [
        "请假申请", "费用付款申请", "采购申请", "购买申请", "采购付款",
    ]
    assert fields["asset_nature"]["options"] == "非固定资产\n固定资产"
    assert fields["fixed_asset_category"]["fieldtype"] == "Select"
    assert fields["source_request"] == {
        **fields["source_request"],
        "fieldtype": "Link",
        "options": "OA Approval Request",
    }
    assert fields["business_lines"]["options"] == "OA Purchase Request Line"


def test_purchase_line_amount_is_server_calculated():
    doc = _doctype("rayher_hr_payroll/rayher_hr_payroll/doctype/oa_purchase_request_line/oa_purchase_request_line.json")
    fields = {row["fieldname"]: row for row in doc["fields"]}
    assert fields["amount"]["fieldtype"] == "Currency"
    assert fields["amount"]["read_only"] == 1
```

- [ ] **Step 2: Run schema tests and confirm RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_approval_center_schema.py -q`

Expected: FAIL on missing fields and child DocType.

- [ ] **Step 3: Add the exact schema**

Add these parent fields without renaming or deleting existing fields:

```json
{"fieldname":"asset_nature","fieldtype":"Select","label":"资产属性","options":"非固定资产\n固定资产"},
{"fieldname":"fixed_asset_category","fieldtype":"Select","label":"固定资产类别","options":"办公家具、工具及器具\n电子设备、研发专用设备、仪器仪表\n生产设备、生产工具及器具"},
{"fieldname":"payment_source_kind","fieldtype":"Select","label":"付款来源","options":"关联采购申请\n关联购买申请\n无事前申请"},
{"fieldname":"source_request","fieldtype":"Link","label":"来源申请","options":"OA Approval Request"},
{"fieldname":"approved_amount_snapshot","fieldtype":"Currency","label":"来源批准金额快照","read_only":1},
{"fieldname":"source_modified","fieldtype":"Datetime","label":"来源版本时间","read_only":1},
{"fieldname":"business_lines","fieldtype":"Table","label":"采购/购买明细","options":"OA Purchase Request Line"}
```

The child DocType must contain exactly the seven interfaces listed above. Calculate `amount = quantity * unit_price` in server validation and reject negative quantity, unit price, or amount.

Append `采购申请`、`购买申请`、`采购付款` to the existing `request_type` Select options; do not rename or remove `请假申请` and `费用付款申请`.

- [ ] **Step 4: Write migration tests that protect ambiguous history**

```python
def test_patch_does_not_guess_ambiguous_legacy_asset_classification(fake_rows, run_patch):
    old = fake_rows.request(asset_category="其他", doc_type="", asset_nature="")
    run_patch()
    assert old.asset_nature == ""
    assert old.fixed_asset_category == ""


def test_patch_only_maps_unambiguous_legacy_fixed_asset(fake_rows, run_patch):
    old = fake_rows.request(asset_category="电子类固定资产（IT）", asset_nature="")
    run_patch()
    assert old.asset_nature == "固定资产"
    assert old.fixed_asset_category == "电子设备、研发专用设备、仪器仪表"
```

- [ ] **Step 5: Implement an idempotent patch**

The patch may map only these exact legacy values when the new fields are empty:

```python
LEGACY_FIXED_MAP = {
    "非电子类固定资产（人事/行政）": "办公家具、工具及器具",
    "电子类固定资产（IT）": "电子设备、研发专用设备、仪器仪表",
}
```

It must not infer `asset_nature` from `asset_category="其他"`. It must not update rows whose new fields are already populated.

- [ ] **Step 6: Run schema and migration tests twice**

Run: `python -m pytest rayher_hr_payroll/tests/test_approval_center_schema.py rayher_hr_payroll/tests/test_approval_center_migration.py -q`

Expected: PASS on the first and second patch execution.

- [ ] **Step 7: Commit schema and migration**

```bash
git add rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request rayher_hr_payroll/rayher_hr_payroll/doctype/oa_purchase_request_line rayher_hr_payroll/patches.txt rayher_hr_payroll/patches/v1_0/add_approval_center_foundation.py rayher_hr_payroll/tests/test_approval_center_schema.py rayher_hr_payroll/tests/test_approval_center_migration.py
git commit -m "feat: add approval request linkage schema"
```

### Task 3: Implement server-owned classification and line validation

**Files:**
- Create: `rayher_hr_payroll/approval_center_validation.py`
- Create: `rayher_hr_payroll/tests/test_approval_center_validation.py`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.py`

**Interfaces:**
- Produces: `validate_asset_selection(asset_nature, fixed_asset_category)`.
- Produces: `normalize_purchase_lines(rows) -> tuple[list[dict], Decimal]`.
- Produces: `validate_payment_source_shape(request_type, payment_source_kind, source_request)`.

- [ ] **Step 1: Write behavior tests**

```python
import pytest

from rayher_hr_payroll.approval_center_validation import (
    normalize_purchase_lines,
    validate_asset_selection,
    validate_payment_source_shape,
)


def test_non_fixed_request_rejects_fixed_asset_category():
    with pytest.raises(ValueError, match="非固定资产申请不能选择固定资产类别"):
        validate_asset_selection("非固定资产", "办公家具、工具及器具")


def test_fixed_request_requires_canonical_category():
    with pytest.raises(ValueError, match="固定资产申请必须选择固定资产类别"):
        validate_asset_selection("固定资产", "")


def test_lines_are_positive_and_total_is_recalculated():
    lines, total = normalize_purchase_lines([
        {"item_name": "设备A", "quantity": "2", "unit_price": "10.01", "amount": "1"},
    ])
    assert lines[0]["amount"] == "20.02"
    assert str(total) == "20.02"


def test_procurement_payment_requires_procurement_source():
    with pytest.raises(ValueError, match="采购付款必须关联采购申请"):
        validate_payment_source_shape("采购付款", "无事前申请", "")
```

- [ ] **Step 2: Run and confirm RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_approval_center_validation.py -q`

Expected: FAIL because the validation module does not exist.

- [ ] **Step 3: Implement Decimal-based normalization**

Use `Decimal(str(value or 0)).quantize(Decimal("0.01"))`; reject non-finite values, booleans, zero/negative quantity, negative unit price, blank item name, and more than 200 lines. Ignore client-supplied line `amount` and recalculate it server-side.

For `资产属性` enforce only internal consistency, not business correctness:

```python
if asset_nature == "固定资产" and fixed_asset_category not in FIXED_ASSET_CATEGORIES:
    raise ValueError("固定资产申请必须选择固定资产类别")
if asset_nature == "非固定资产" and fixed_asset_category:
    raise ValueError("非固定资产申请不能选择固定资产类别")
```

- [ ] **Step 4: Wire validation into DocType `validate()`**

Only apply purchase-line validation to `采购申请` and `购买申请`. Existing leave and expense/payment documents must follow their current validation path unchanged.

For a procurement/direct-purchase draft, overwrite parent `amount` with the normalized child-line total on every save. After approval, treat `amount`, `asset_nature`, `fixed_asset_category` and `business_lines` as immutable. A rejected request may be returned to draft and edited only while it has no reserving or paid linked document.

- [ ] **Step 5: Run focused and legacy API tests**

Run: `python -m pytest rayher_hr_payroll/tests/test_approval_center_validation.py rayher_hr_payroll/tests/test_oa_approval_routes.py -q`

Expected: PASS.

- [ ] **Step 6: Commit validation**

```bash
git add rayher_hr_payroll/approval_center_validation.py rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.py rayher_hr_payroll/tests/test_approval_center_validation.py
git commit -m "feat: validate approval center business documents"
```

### Task 4: Enforce source linkage and concurrent amount reservation

**Files:**
- Create: `rayher_hr_payroll/approval_linkage.py`
- Create: `rayher_hr_payroll/tests/test_approval_linkage.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`

**Interfaces:**
- Produces: `source_balance(source_name, *, exclude_name=None) -> dict` with `approved_amount`, `paid_amount`, `reserved_amount`, `available_amount`.
- Produces: `validate_and_reserve_source(doc)`; caller must already be inside the request transaction.
- Consumes: source status `已完成`; linked payment statuses `待审批`、`待办理`、`已完成`、`已付款` reserve capacity; `草稿`、`已拒绝` do not reserve.

- [ ] **Step 1: Write source-type and amount tests**

```python
def test_procurement_payment_only_accepts_completed_procurement_request(store):
    source = store.request(request_type="采购申请", workflow_status="已完成", amount=100)
    payment = store.request(
        request_type="采购付款",
        source_request=source.name,
        payment_source_kind="关联采购申请",
        amount=20,
    )
    validate_and_reserve_source(payment)


def test_purchase_related_reimbursement_only_accepts_completed_purchase_request(store):
    source = store.request(request_type="购买申请", workflow_status="已完成", amount=100)
    reimbursement = store.request(
        request_type="费用付款申请",
        payment_type="支付个人",
        source_request=source.name,
        payment_source_kind="关联购买申请",
        amount=20,
    )
    validate_and_reserve_source(reimbursement)


def test_non_purchase_expense_can_have_no_source(store):
    taxi = store.request(
        request_type="费用付款申请",
        payment_type="支付个人",
        payment_source_kind="无事前申请",
        source_request="",
        reason="客户现场返回公司的打车费",
        amount=80,
    )
    validate_and_reserve_source(taxi)


def test_no_source_expense_requires_reason(store):
    taxi = store.request(
        request_type="费用付款申请",
        payment_type="支付个人",
        payment_source_kind="无事前申请",
        source_request="",
        reason="",
        amount=80,
    )
    with pytest.raises(ValueError, match="无事前申请必须填写费用事由"):
        validate_and_reserve_source(taxi)


def test_pending_and_paid_links_both_consume_available_amount(store):
    source = store.request(request_type="采购申请", workflow_status="已完成", amount=100)
    store.link(source, amount=30, status="已付款")
    store.link(source, amount=50, status="待审批")
    assert source_balance(source.name)["available_amount"] == 20


def test_reimbursement_and_corporate_payment_share_the_same_purchase_balance(store):
    source = store.request(request_type="购买申请", workflow_status="已完成", amount=100)
    store.link(source, amount=40, status="已付款", payment_type="支付个人")
    store.link(source, amount=50, status="待审批", payment_type="对公支付")
    with pytest.raises(ValueError, match="超过剩余可申请金额 10.00"):
        validate_and_reserve_source(store.link(source, amount=20, status="草稿"))
```

- [ ] **Step 2: Write a real concurrency regression test**

Use two independent MariaDB connections. Both attempt to submit a 60.00 payment against the same approved 100.00 source. Synchronize the workers before `SELECT ... FOR UPDATE` using a barrier. Assert exactly one succeeds and the other receives the business validation error; the sum of reserving documents remains 60.00.

- [ ] **Step 3: Run and confirm RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_approval_linkage.py -q`

Expected: FAIL because linkage enforcement is absent.

- [ ] **Step 4: Implement row locking and server-side sums**

The lock must be acquired before reading linked totals:

```python
source = frappe.db.sql(
    """select name, request_type, workflow_status, amount, modified
       from `tabOA Approval Request`
       where name=%s for update""",
    (source_name,),
    as_dict=True,
)
```

Then sum authoritative `amount` values for links in reserving statuses, excluding the current document when editing. Reject missing, unauthorized, wrong-type, non-completed, withdrawn, or over-capacity sources. Store `approved_amount_snapshot` and the locked source row's exact `modified` timestamp in `source_modified` only after validation succeeds.

When `payment_source_kind="无事前申请"`, require a non-empty bounded reason and an existing expense line/category, but do not require a source link. This exception applies only to existing reimbursement and corporate-payment documents, never to `采购付款`.

- [ ] **Step 5: Call linkage validation at submission and amount-changing operations**

Integrate with `_submit_draft()` and every existing API path that can change `amount`, `source_request`, `payment_source_kind`, or linked expense lines. Never rely only on `create_request()` because direct draft submit and invoice pushdown are separate entry points.

Extend `create_request(...)`, `_build_request_doc(...)`, `push_invoices_to_request(..., payment_info)` and consumption pushdown to accept and persist the three source fields. Reject client attempts to set `approved_amount_snapshot` or `source_modified`.

Before withdrawing or deleting an approved `采购申请` or `购买申请`, acquire the same source lock and reject the operation when any linked document is in `待审批`、`待办理`、`已完成` or `已付款`. This prevents an approved source from being withdrawn underneath an active or completed payment.

- [ ] **Step 6: Run linkage, legacy OA, and transaction tests**

Run: `python -m pytest rayher_hr_payroll/tests/test_approval_linkage.py rayher_hr_payroll/tests/test_oa_approval_routes.py -q`

Expected: PASS including the two-connection race.

- [ ] **Step 7: Commit linkage enforcement**

```bash
git add rayher_hr_payroll/approval_linkage.py rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests/test_approval_linkage.py
git commit -m "feat: enforce approval source balances"
```

### Task 5: Add permission-scoped query APIs and safe activation gates

**Files:**
- Modify: `rayher_hr_payroll/oa_feature_gate.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `rayher_hr_payroll/hooks.py`
- Create: `rayher_hr_payroll/tests/test_approval_center_access.py`
- Modify: `rayher_hr_payroll/tests/test_oa_feature_gate.py`

**Interfaces:**
- Produces: `list_source_requests(source_type, query="", limit=20)` returning completed, accessible sources plus balance.
- Produces: `get_approval_center_dashboard(center, asset_nature=None, status=None, limit=100)`.
- Produces boot flags: `pre_request_center` and `procurement_payment`, both false unless the matching explicit site configuration is enabled and a route provider is registered.

- [ ] **Step 1: Write direct-API permission tests**

```python
def test_employee_source_search_cannot_read_other_employee_private_request(session, api):
    session.login("employee-a@example.com")
    rows = api.list_source_requests(source_type="购买申请", query="employee-b-secret")
    assert rows == []


def test_dashboard_never_trusts_client_department_filter_for_scope(session, api):
    session.login("department-manager-a@example.com")
    rows = api.get_approval_center_dashboard(center="事前申请", department="其他部门")
    assert all(row["department"] == "部门A" for row in rows)


def test_new_submission_is_blocked_until_route_is_registered(session, api):
    session.login("employee-a@example.com")
    with pytest.raises(PermissionError, match="审批流程尚未启用"):
        api.submit_request(name=session.procurement_draft)
```

- [ ] **Step 2: Run and confirm RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_approval_center_access.py rayher_hr_payroll/tests/test_oa_feature_gate.py -q`

Expected: FAIL on missing APIs and flags.

- [ ] **Step 3: Implement server-side visibility**

Apply the same applicant/approver/finance/administrator visibility rules used by `list_requests`; source search must return only documents the current user may read. Finance/System Manager may use organization-wide dashboards; ordinary employees see their own requests; approvers see requests assigned to them. `limit` must be bounded to `1..200`, search text to 100 characters, and filters must be allow-listed.

- [ ] **Step 4: Add an activation invariant**

```python
def can_submit_request_type(request_type):
    return request_type in {REQUEST_LEAVE, REQUEST_EXPENSE_PAYMENT} or (
        request_type in REGISTERED_NEW_ROUTES
        and not is_admin_only(request_type)
    )
```

Until the separate route plan registers each new route, save-draft may be allowed for Administrator in local development, but submit must fail closed for every user, including Administrator and direct API calls.

For inactive new types, `preview_route()` must return `{"enabled": False, "steps": []}` without calling the existing `build_route()`. Add the three new types to the API allow-list only for Administrator draft creation; ordinary users must not receive them from `get_options()` until their route and feature flag are both active.

- [ ] **Step 5: Run access and existing OA tests**

Run: `python -m pytest rayher_hr_payroll/tests/test_approval_center_access.py rayher_hr_payroll/tests/test_oa_feature_gate.py rayher_hr_payroll/tests/test_oa_approval_routes.py -q`

Expected: PASS.

- [ ] **Step 6: Commit access and gates**

```bash
git add rayher_hr_payroll/oa_feature_gate.py rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/hooks.py rayher_hr_payroll/tests/test_approval_center_access.py rayher_hr_payroll/tests/test_oa_feature_gate.py
git commit -m "feat: gate approval center foundation APIs"
```

### Task 6: Build the approval-center navigation without duplicating existing workflow code

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/lib/access.js`
- Modify: `frontend/src/pages/OAApprovals.vue`
- Modify: `frontend/src/components/ExpenseWorkbench.vue`
- Create: `frontend/src/pages/PreRequestCenter.vue`
- Create: `frontend/src/pages/PaymentCenter.vue`
- Create: `frontend/src/pages/ApprovalDashboard.vue`
- Create: `frontend/src/lib/approvalCenter.js`
- Modify: `frontend/tests/oa-source.test.js`
- Create: `frontend/tests/approval-center.test.js`

**Interfaces:**
- Produces routes:
  - `/approval/leave`
  - `/approval/pre-request/procurement`
  - `/approval/pre-request/direct-purchase`
  - `/approval/pre-request/dashboard`
  - `/approval/payment/procurement`
  - `/approval/payment/reimbursement`
  - `/approval/payment/corporate`
  - `/approval/payment/dashboard`
- Preserves `/approval/purchase` as a compatibility redirect to `/approval/payment/reimbursement`.
- `ExpenseWorkbench` consumes prop `mode: "reimbursement" | "corporate"` and continues using the existing `费用付款申请` backend request type.

- [ ] **Step 1: Write route and label tests**

```javascript
test('approval center exposes agreed information architecture', () => {
  for (const path of [
    '/approval/leave',
    '/approval/pre-request/procurement',
    '/approval/pre-request/direct-purchase',
    '/approval/pre-request/dashboard',
    '/approval/payment/procurement',
    '/approval/payment/reimbursement',
    '/approval/payment/corporate',
    '/approval/payment/dashboard',
  ]) assert.ok(routerSource.includes(path), path);

  for (const label of ['审批中心', '事前申请', '采购申请', '购买申请', '申请看板', '付款申请', '采购付款', '报销申请', '对公付款', '付款看板']) {
    assert.ok(appSource.includes(label), label);
  }
  assert.doesNotMatch(appSource, /付款申请[\s\S]*付款申请/);
});
```

- [ ] **Step 2: Write mode-isolation tests**

```javascript
test('reimbursement and corporate payment reuse logic but cannot cross-list data', () => {
  assert.match(workbenchSource, /defineProps/);
  assert.match(workbenchSource, /mode:\s*\{[^}]*required:\s*true/);
  assert.match(workbenchSource, /payment_type:\s*expectedPaymentType/);
  assert.match(workbenchSource, /支付个人/);
  assert.match(workbenchSource, /对公支付/);
});
```

- [ ] **Step 3: Run frontend tests and confirm RED**

Run: `D:\\Tools\\Pi\\node\\node.exe --test frontend/tests/oa-source.test.js frontend/tests/approval-center.test.js`

Expected: FAIL on missing routes/components.

- [ ] **Step 4: Implement navigation and route metadata**

Use route `meta` for center, page kind and title. Do not infer business behavior from URL substrings. The sidebar group label becomes `审批中心`; render nested headings `事前申请` and `付款申请` with the exact child labels above.

- [ ] **Step 5: Parameterize the existing expense workbench**

```javascript
const props = defineProps({
  mode: { type: String, required: true, validator: (v) => ['reimbursement', 'corporate'].includes(v) },
});
const expectedPaymentType = computed(() => props.mode === 'reimbursement' ? '支付个人' : '对公支付');
```

Pass `payment_type: expectedPaymentType.value` in every list and exact-detail query, set it server-side on create/pushdown, and reject mismatched responses. Do not duplicate the 900-line component.

- [ ] **Step 6: Implement pre-request and payment shells behind boot flags**

When the new route flag is false, show the exact non-actionable message `审批流程尚未配置，当前页面仅供管理员本地验收。` and do not render a submit button. Existing reimbursement and corporate payment pages remain active according to the current expense feature flag.

- [ ] **Step 7: Run frontend tests**

Run: `D:\\Tools\\Pi\\node\\node.exe --test frontend/tests/*.test.js`

Expected: PASS.

- [ ] **Step 8: Commit navigation and pages**

```bash
git add frontend/src/App.vue frontend/src/router.js frontend/src/lib/access.js frontend/src/lib/approvalCenter.js frontend/src/pages/OAApprovals.vue frontend/src/pages/PreRequestCenter.vue frontend/src/pages/PaymentCenter.vue frontend/src/pages/ApprovalDashboard.vue frontend/src/components/ExpenseWorkbench.vue frontend/tests/oa-source.test.js frontend/tests/approval-center.test.js
git commit -m "feat: add approval center navigation"
```

### Task 7: Implement application and payment dashboards from authoritative dimensions

**Files:**
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `frontend/src/pages/ApprovalDashboard.vue`
- Create: `rayher_hr_payroll/tests/test_approval_center_dashboard.py`
- Modify: `frontend/tests/approval-center.test.js`

**Interfaces:**
- `center="事前申请"` aggregates `采购申请` and `购买申请`.
- `center="付款申请"` aggregates `采购付款` plus existing `费用付款申请`, classifying the latter by `payment_type`.
- Produces per row: `document_kind`, `asset_nature`, `fixed_asset_category`, `requested_amount`, `reserved_amount`, `paid_amount`, `available_amount`, `workflow_status`, `source_request`.

- [ ] **Step 1: Write behavior tests for dimensions and history**

```python
def test_application_dashboard_splits_fixed_and_non_fixed_by_authoritative_field(api, records):
    records.pre_request(asset_nature="固定资产", amount=100)
    records.pre_request(asset_nature="非固定资产", amount=20)
    result = api.get_approval_center_dashboard(center="事前申请")
    assert result["totals"]["固定资产"] == 100
    assert result["totals"]["非固定资产"] == 20


def test_ambiguous_legacy_row_is_not_silently_counted_as_non_fixed(api, records):
    records.legacy_expense(asset_category="其他", asset_nature="", amount=30)
    result = api.get_approval_center_dashboard(center="付款申请")
    assert result["totals"]["历史未分类"] == 30


def test_payment_dashboard_distinguishes_personal_and_corporate(api, records):
    records.expense(payment_type="支付个人", amount=80)
    records.expense(payment_type="对公支付", amount=120)
    result = api.get_approval_center_dashboard(center="付款申请")
    assert result["totals_by_kind"]["报销申请"] == 80
    assert result["totals_by_kind"]["对公付款"] == 120
```

- [ ] **Step 2: Run and confirm RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_approval_center_dashboard.py -q`

Expected: FAIL on missing dashboard response.

- [ ] **Step 3: Implement server aggregation**

All dashboard filters and totals must be computed after permission filtering. Use database aggregation for totals and a bounded detail query; do not fetch unrestricted rows and hide them in Vue. Empty new fields map to `历史未分类`, never to `非固定资产`.

- [ ] **Step 4: Implement the shared dashboard UI**

Provide filters for period, document kind, fixed/non-fixed, fixed-asset category, department and workflow status. Show separate cards for requested, approval-reserved, paid and remaining amounts. Selecting a card applies a filter; it must not change the underlying API scope.

- [ ] **Step 5: Run backend and frontend tests**

Run: `python -m pytest rayher_hr_payroll/tests/test_approval_center_dashboard.py -q`

Run: `D:\\Tools\\Pi\\node\\node.exe --test frontend/tests/approval-center.test.js`

Expected: PASS.

- [ ] **Step 6: Commit dashboards**

```bash
git add rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests/test_approval_center_dashboard.py frontend/src/pages/ApprovalDashboard.vue frontend/tests/approval-center.test.js
git commit -m "feat: add approval center dashboards"
```

### Task 8: Verify compatibility, migrations, build output and local-only deployment

**Files:**
- Modify generated files only: `rayher_hr_payroll/public/frontend/index.html`, `rayher_hr_payroll/public/frontend/assets/*.js`, `rayher_hr_payroll/public/frontend/assets/*.css`
- Create: `docs/superpowers/reports/2026-08-05-approval-center-foundation-verification.md`

**Interfaces:**
- Produces a repeatable verification record with commit SHA, test commands, migration results, asset hashes, feature-flag state and manual scenarios.

- [ ] **Step 1: Run the complete Python suite**

Run: `python -m pytest rayher_hr_payroll/tests -q`

Expected: all tests pass; no existing OA approval snapshot changes unless explicitly listed in this plan.

- [ ] **Step 2: Run the complete frontend test suite**

Run: `D:\\Tools\\Pi\\node\\node.exe --test frontend/tests/*.test.js`

Expected: all tests pass.

- [ ] **Step 3: Build using the project-pinned package manager**

Run from `frontend`: `yarn build`

Expected: Vite build exits 0 and updates only `rayher_hr_payroll/public/frontend` assets referenced by `index.html`.

- [ ] **Step 4: Scan every changed file for TipRay encryption**

Run:

```powershell
$changed = git diff --name-only --diff-filter=ACMR
$marker = [Text.Encoding]::ASCII.GetBytes('%TSD-Header-###%')
foreach ($file in $changed) {
  $bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $file))
  if ($bytes.Length -ge $marker.Length) {
    $prefix = $bytes[0..($marker.Length - 1)]
    if ([Linq.Enumerable]::SequenceEqual[byte]($prefix, $marker)) {
      throw "TipRay header found: $file"
    }
  }
}
```

Expected: no marker found. Confirm the plan begins with `# 审批中心` and generated `index.html` begins with normal HTML.

- [ ] **Step 5: Back up the local Docker site before migration**

Run inside `rayher-bench`: `bench --site rayher.localhost backup --with-files`

Expected: database and file backup paths are printed and recorded in the verification report.

- [ ] **Step 6: Deploy only to local Docker and migrate twice**

Run inside `rayher-bench`:

```bash
bench --site rayher.localhost migrate
bench --site rayher.localhost migrate
bench --site rayher.localhost clear-cache
```

Expected: both migrations exit 0; the second run makes no additional business-data changes.

- [ ] **Step 7: Execute manual behavior checks**

Verify all of the following on `http://rayher.localhost:8000/planck-semicon`:

1. Existing leave submission, approval and rejection behave exactly as before.
2. Existing employee reimbursement (`支付个人`) appears only under“报销申请”.
3. Existing corporate payment (`对公支付`) appears only under“对公付款”.
4. A taxi reimbursement can select“无事前申请”and does not require a purchase source.
5. Procurement request, direct purchase request and procurement payment show the disabled local-review message and cannot be submitted through UI or direct API.
6. Ambiguous historical records appear under“历史未分类”.
7. Ordinary employees cannot view another employee's private source requests or dashboard rows.
8. No request is written to staging or product.

- [ ] **Step 8: Record evidence and commit build output**

The verification report must contain the exact commands, exit codes, test counts, local backup path, changed database row counts from the idempotent patch, and screenshots of the four existing-flow checks. Then commit:

```bash
git add rayher_hr_payroll/public/frontend docs/superpowers/reports/2026-08-05-approval-center-foundation-verification.md
git commit -m "test: verify approval center foundation"
```

## Follow-on plan activation criteria

A separate approval-route plan may be written only after all three route definitions are supplied in this exact form for every amount/department/asset branch:

1. 采购申请：节点顺序、每个节点的审批人来源、会签/或签、跳过条件、驳回目标、固定资产责任人是否参与。
2. 购买申请：同上。
3. 采购付款：同上，并明确预付款、到货款、验收款和尾款对验收资料的要求。

That follow-on plan must add route snapshots, missing-approver fail-closed tests, self-approval prevention, direct-API authorization tests and activation configuration. It must not change the existing reimbursement/payment route unless the user separately approves that change.

## Self-review record

- Spec coverage: menu hierarchy, manual classification, conditional source linkage, no-source daily expenses, split payments, shared balance, fixed/non-fixed dashboards, historical safety, permissions, concurrency and local-only deployment each have an implementation task and acceptance test.
- Scope correction: removed the earlier assumption that the system decides“采购”versus“购买”; approval owns that judgment.
- Naming correction: uses“对公付款”for the child page so the parent and child are not both called“付款申请”.
- Safety correction: new flows fail closed until explicit routes exist; Administrator cannot bypass the submission gate.
- Data correction: pending payments reserve capacity; otherwise two simultaneous 60.00 requests could both pass against a 100.00 source.
- Migration correction: `其他` is not treated as non-fixed because old data cannot prove that meaning.
- Dashboard correction: fixed/non-fixed classification is a dimension, not a separate request type.
- Placeholder scan: no implementation step delegates unspecified behavior to the engineer; the three unknown approval routes are explicitly excluded and gated.
- Type consistency: request type, source kind, asset nature, fixed category, link, `source_modified` and balance names are identical across schema, service, API, UI and tests.
