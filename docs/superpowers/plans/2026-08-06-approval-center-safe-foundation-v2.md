# 审批中心安全底座 V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在采购申请、购买申请和采购付款的最终审批人尚未完全确定时，先在隔离本地环境交付不可绕过权限、不可超额付款、可保存草稿、可归档资料的审批中心安全底座，并保持所有未确认路线关闭。

**Architecture:** 继续复用 `OA Approval Request` 作为审批聚合根，但把行级权限、状态转换、金额口径和原生 Frappe 写入保护下沉到共用服务。新增追加式金额流水和通用业务文档中心；新流程只允许 Administrator 在本地保存草稿，自定义 API、Frappe REST、Desk、导入器和后台任务都不能绕过关闭状态。

**Tech Stack:** Frappe/ERPNext Python、MariaDB/InnoDB、Vue 3、frappe-ui、pytest、Node test runner、Yarn 1.22.22、Vite 5、本地 Docker Bench。

---

## 0. 计划定位与可交付范围

本文件取代 `2026-08-05-approval-center-foundation.md`。旧计划的菜单、来源关联、并发锁、历史保护和本地部署方向保留；权限、状态、金额和付款占用以本计划为准。

本计划现在可以做出：

1. 审批中心菜单保留现有请假审批，并增加新流程草稿页面和关闭提示。
2. 采购申请、购买申请、采购付款的稳定类型及采购/购买明细。
3. 新流程关闭期间普通员工看不到入口且不能创建、读取或保存；仅本地 Administrator 可保存本人创建的草稿。现有请假、报销和对公付款继续沿用既有权限。
4. 自定义 API 和 Frappe 原生接口共用行级权限。
5. 申请金额、批准金额、审批占用、已付和可用余额分离。
6. 并发付款不突破批准金额，撤回、付款、退款和冲销可追溯。
7. 报价、价格审批、PR、PO、合同、付款计划、发票、验收、收料、入库和付款回单统一归档并版本化。
8. 使用本地测试数据验收申请看板和付款看板。

必须等待后续路线计划才能启用：

1. 采购申请、购买申请、采购付款的正式审批人、顺序、会签/或签和驳回目标。
2. 价格审批、合同、付款计划、预付款、到货款和尾款完整状态机。
3. 金蝶、电子章、邮件真实接口。
4. 采购发票 OCR 自动放行付款。

## 1. 全局不变量

- 仅修改新建隔离 worktree 和本地 Docker `rayher.localhost`；禁止访问 staging `203.0.113.58`、product `203.0.113.32`。
- 不改变现有请假、报销和对公付款路线快照；请假继续复用现有提交、审批、驳回和可见范围，只迁移入口与展示归类。
- 新流程默认关闭：仅 Administrator 可保存本地草稿，任何用户包括 Administrator 都不能推进为非草稿状态。
- 前端隐藏、Select选项和`read_only`元数据不是安全边界；所有路径必须执行服务端权限、状态和字段校验。
- `workflow_status`、当前步骤、审批步骤、`approved_amount`、来源快照、付款信息和金额流水由服务端动作拥有。
- 现有`amount`保持为申请金额；`approved_amount`是终审确认的含税人民币付款上限。外币采购在本阶段禁用。
- `available_amount = approved_amount - reserved_amount - paid_amount`，全部使用`Decimal`精确到分。
- 金额流水只追加、不更新、不删除；每个事件有唯一幂等键。
- 新付款只能关联有权使用、类型正确、状态完成、批准金额大于0的来源申请。正式路线权限未确定前，“有权使用”只包括来源申请人本人和System Manager；后续路线只能显式扩大，不能依赖部门参数。
- 每次追加流水后`reserved_amount`和`paid_amount`都不得为负；释放不得超过现有占用，退款/冲销不得超过现有已付。
- `OA Approval Request`、金额流水和业务文档均禁止改名，避免来源链和审计引用漂移。
- 权限复核、来源行锁、余额计算、流水追加和状态变化必须在同一事务完成。
- 迁移不推断历史批准金额、固定资产属性或来源申请。
- 所有修改文件和构建产物开头不得为`%TSD-Header-###%`。

## 2. 文件结构

- Create: `rayher_hr_payroll/oa_document_types.py` — 稳定单据和事件常量。
- Create: `rayher_hr_payroll/oa_access.py` — 统一行级权限。
- Create: `rayher_hr_payroll/oa_mutation_guard.py` — 状态和服务端字段保护。
- Create: `rayher_hr_payroll/approval_amount_ledger.py` — 金额流水、余额和并发控制。
- Create: `rayher_hr_payroll/business_documents.py` — 业务文档、版本和下载权限。
- Modify: `rayher_hr_payroll/oa_feature_gate.py`、`hooks.py`、`api/oa_entry.py`。
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.py`及JSON。
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_purchase_request_line/*`。
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_amount_ledger/*`。
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_business_document/*`。
- Create: `rayher_hr_payroll/patches/v1_0/add_approval_center_safe_foundation.py`。
- Create: `frontend/src/pages/PreRequestCenter.vue`、`PaymentCenter.vue`、`ApprovalDashboard.vue`。
- Create: `frontend/src/lib/approvalCenter.js`。

### Task 1: 固化单据与金额契约

**Files:**
- Create: `rayher_hr_payroll/oa_document_types.py`
- Test: `rayher_hr_payroll/tests/test_oa_document_types.py`

- [ ] **Step 1: 写失败测试**

```python
from rayher_hr_payroll.oa_document_types import (
    REQUEST_PROCUREMENT, REQUEST_DIRECT_PURCHASE,
    REQUEST_PROCUREMENT_PAYMENT, AMOUNT_EVENTS,
)

def test_contracts_are_stable():
    assert REQUEST_PROCUREMENT == "采购申请"
    assert REQUEST_DIRECT_PURCHASE == "购买申请"
    assert REQUEST_PROCUREMENT_PAYMENT == "采购付款"
    assert AMOUNT_EVENTS == ("reserve", "release", "pay", "refund", "reverse")
```

- [ ] **Step 2: 在本地Docker确认RED**

```bash
docker exec rayher-bench bash -lc 'cd /workspace/development/frappe-bench/apps/rayher_hr_payroll && python -m pytest rayher_hr_payroll/tests/test_oa_document_types.py -q'
```

Expected: FAIL，模块不存在。

- [ ] **Step 3: 最小实现**

```python
REQUEST_PROCUREMENT = "采购申请"
REQUEST_DIRECT_PURCHASE = "购买申请"
REQUEST_PROCUREMENT_PAYMENT = "采购付款"
PAYMENT_SOURCE_PROCUREMENT = "关联采购申请"
PAYMENT_SOURCE_DIRECT_PURCHASE = "关联购买申请"
PAYMENT_SOURCE_NONE = "无事前申请"
ASSET_FIXED = "固定资产"
ASSET_NON_FIXED = "非固定资产"
AMOUNT_EVENTS = ("reserve", "release", "pay", "refund", "reverse")
```

- [ ] **Step 4: 重跑确认PASS并提交**

```bash
git add rayher_hr_payroll/oa_document_types.py rayher_hr_payroll/tests/test_oa_document_types.py
git commit -m "feat: define approval center contracts"
```

### Task 2: 增加Schema和幂等迁移

**Files:**
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.json`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_purchase_request_line/*`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_amount_ledger/*`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_business_document/*`
- Create: `rayher_hr_payroll/patches/v1_0/add_approval_center_safe_foundation.py`
- Test: `rayher_hr_payroll/tests/test_approval_center_schema.py`

- [ ] **Step 1: 写Schema测试工具和失败测试**

```python
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def fields(slug):
    path = ROOT / "rayher_hr_payroll" / "rayher_hr_payroll" / "doctype" / slug / f"{slug}.json"
    return {row["fieldname"]: row for row in json.loads(path.read_text(encoding="utf-8"))["fields"]}

def test_request_amount_and_source_fields():
    result = fields("oa_approval_request")
    assert result["amount"]["fieldtype"] == "Currency"
    assert result["approved_amount"]["read_only"] == 1
    assert result["currency"]["default"] == "CNY"
    assert result["source_request"]["options"] == "OA Approval Request"
    assert result["approved_amount_snapshot"]["read_only"] == 1
    assert result["business_lines"]["options"] == "OA Purchase Request Line"

def test_ledger_has_unique_idempotency_key():
    result = fields("oa_approval_amount_ledger")
    assert result["reserved_delta"]["fieldtype"] == "Currency"
    assert result["paid_delta"]["fieldtype"] == "Currency"
    assert result["idempotency_key"]["unique"] == 1
```

- [ ] **Step 2: 运行确认RED**

```bash
docker exec rayher-bench bash -lc 'cd /workspace/development/frappe-bench/apps/rayher_hr_payroll && python -m pytest rayher_hr_payroll/tests/test_approval_center_schema.py -q'
```

- [ ] **Step 3: 增加父单字段**

新增：`currency`（默认且仅允许CNY）、`approved_amount`、`asset_nature`、`fixed_asset_category`、`payment_source_kind`、`source_request`、`approved_amount_snapshot`、`source_modified`、`business_lines`。其中批准金额、来源快照和来源版本只读。`amount`继续是申请金额，不得批量复制到`approved_amount`。同时把`OA Approval Request.allow_rename`改为0。

- [ ] **Step 4: 创建三个DocType**

`OA Purchase Request Line`：`item_name`、`specification`、`quantity`、`unit`、`unit_price`、`amount`、`remarks`。

`OA Approval Amount Ledger`：`source_request`、`linked_request`、`event_type`、`reserved_delta`、`paid_delta`、`idempotency_key`、`actor`、`event_time`、`note`。控制器拒绝更新和删除，且三个新DocType均设置`allow_rename=0`。

`OA Business Document`：`request`、`document_type`、`version_no`、`file`、`file_sha256`、`original_filename`、`uploaded_by`、`uploaded_on`、`supersedes`。

- [ ] **Step 5: 写迁移回归测试**

```python
def test_patch_never_guesses_approved_amount(fake_request, run_patch):
    row = fake_request(amount=100, approved_amount=None)
    run_patch(); run_patch()
    assert row.approved_amount is None
```

- [ ] **Step 6: 实现补丁，运行两次均PASS并提交**

```bash
git add rayher_hr_payroll/rayher_hr_payroll/doctype rayher_hr_payroll/patches.txt rayher_hr_payroll/patches/v1_0/add_approval_center_safe_foundation.py rayher_hr_payroll/tests/test_approval_center_schema.py
git commit -m "feat: add safe approval center schema"
```

### Task 3: 收紧原生Frappe行级权限

**Files:**
- Create: `rayher_hr_payroll/oa_access.py`
- Modify: `rayher_hr_payroll/hooks.py`
- Modify: `rayher_hr_payroll/oa_feature_gate.py`
- Test: `rayher_hr_payroll/tests/test_approval_center_native_access.py`

- [ ] **Step 1: 写直接攻击测试**

```python
def test_employee_cannot_read_or_write_another_request(native_api, login):
    login("employee-a@example.com")
    assert native_api.get_list("OA Approval Request", {"name": "OA-BOB"}) == []
    with pytest.raises(frappe.PermissionError):
        native_api.get_doc("OA Approval Request", "OA-BOB")
    with pytest.raises(frappe.PermissionError):
        native_api.set_value("OA Approval Request", "OA-BOB", "amount", 1)

def test_finance_cannot_change_applicant_amount(native_api, login):
    login("finance@example.com")
    with pytest.raises(frappe.PermissionError):
        native_api.set_value("OA Approval Request", "OA-ALICE", "amount", 1)
```

测试文件必须使用真实Frappe测试用户和`frappe.client.get_list/get/set_value`调用，不得只模拟前端。

- [ ] **Step 2: 运行确认当前至少一个攻击成功**

- [ ] **Step 3: 实现统一规则**

- System Manager：对现有已启用类型沿用组织范围读取；对关闭类型只有 Administrator 账号可在本地创建、读取和保存草稿，业务字段仍走动作服务。
- 普通员工：对现有已启用类型沿用既有本人范围；对采购申请、购买申请、采购付款等关闭类型无入口、无创建权、无读取权和无写权。
- 审批人：读取分配给自己的申请，不直接写业务字段。
- 财务：读取付款类申请，只通过付款动作更新服务端字段。
- HR：不因HR角色自动获得采购付款写权限。

`permission_query_conditions`、`has_permission`、自定义列表、来源搜索、看板和附件下载必须调用同一规则。子表和文档反查父单权限。

- [ ] **Step 4: 重跑攻击测试和现有审批回归并提交**

```bash
git add rayher_hr_payroll/oa_access.py rayher_hr_payroll/hooks.py rayher_hr_payroll/oa_feature_gate.py rayher_hr_payroll/tests/test_approval_center_native_access.py
git commit -m "fix: enforce approval request row permissions"
```

### Task 4: 保护状态和服务端字段

**Files:**
- Create: `rayher_hr_payroll/oa_mutation_guard.py`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Test: `rayher_hr_payroll/tests/test_approval_center_mutation_guard.py`

- [ ] **Step 1: 写绕过测试**

```python
def test_inactive_route_cannot_advance_by_native_save(request_doc):
    request_doc.request_type = "采购申请"
    request_doc.workflow_status = "待审批"
    with pytest.raises(frappe.PermissionError, match="审批流程尚未启用"):
        request_doc.save()

def test_client_cannot_change_server_fields(request_doc):
    request_doc.approved_amount = 1
    with pytest.raises(frappe.PermissionError, match="服务端字段"):
        request_doc.save()
```

- [ ] **Step 2: 确认RED**

- [ ] **Step 3: 实现字段守卫**

```python
SERVER_OWNED_FIELDS = {
    "workflow_status", "current_step_index", "current_step_label", "steps",
    "approved_amount", "approved_amount_snapshot", "source_modified",
    "paid_by", "paid_on",
}
```

控制器`validate()`比较`get_doc_before_save()`。只有`frappe.flags.oa_authorized_action`受控上下文允许变化，且必须在`finally`清除。

- [ ] **Step 4: 实现路径无关关闭规则**

未注册路线时只允许Administrator保存草稿；禁止非草稿状态；禁止普通用户从REST、Desk、导入器或后台任务创建；`preview_route()`返回空步骤；`submit_request()`再次复核。

- [ ] **Step 5: 跑测试并提交**

```bash
git add rayher_hr_payroll/oa_mutation_guard.py rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.py rayher_hr_payroll/tests/test_approval_center_mutation_guard.py
git commit -m "fix: protect approval state transitions"
```

### Task 5: 实现追加式金额流水与并发控制

**Files:**
- Create: `rayher_hr_payroll/approval_amount_ledger.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Test: `rayher_hr_payroll/tests/test_approval_amount_ledger.py`

- [ ] **Step 1: 写金额生命周期测试**

```python
def test_balance_uses_approved_amount(store):
    source = store.source(amount=150, approved_amount=100, status="已完成")
    assert source_balance(source.name)["available_amount"] == Decimal("100.00")

def test_reserve_pay_refund(store):
    source = store.source(approved_amount=100, status="已完成")
    payment = store.payment(amount=60)
    reserve(source, payment, "submit:PAY-1")
    mark_paid(source, payment, "pay:PAY-1")
    refund(source, payment, Decimal("10.00"), "refund:PAY-1:1")
    result = source_balance(source.name)
    assert result["reserved_amount"] == Decimal("0.00")
    assert result["paid_amount"] == Decimal("50.00")
    assert result["available_amount"] == Decimal("50.00")

def test_idempotency_key_applies_once(store):
    source = store.source(approved_amount=100, status="已完成")
    payment = store.payment(amount=30)
    reserve(source, payment, "submit:PAY-1")
    reserve(source, payment, "submit:PAY-1")
    assert source_balance(source.name)["reserved_amount"] == Decimal("30.00")

def test_release_and_refund_cannot_make_balances_negative(store):
    source = store.source(approved_amount=100, status="已完成")
    payment = store.payment(amount=30)
    reserve(source, payment, "submit:PAY-1")
    with pytest.raises(ValueError, match="超过现有占用"):
        release(source, payment, Decimal("40.00"), "release:PAY-1:bad")
    mark_paid(source, payment, "pay:PAY-1")
    with pytest.raises(ValueError, match="超过已付金额"):
        refund(source, payment, Decimal("40.00"), "refund:PAY-1:bad")
```

- [ ] **Step 2: 写双连接并发测试**

两个独立MariaDB连接同时对100元来源提交60元付款，先锁同一来源行。断言一个成功、一个因可用余额40元失败，最终占用60元。

- [ ] **Step 3: 实现事务**

```sql
SELECT name, request_type, workflow_status, approved_amount, modified
FROM `tabOA Approval Request`
WHERE name=%s FOR UPDATE
```

锁后用当前读汇总流水。拒绝无权限、错误类型、未完成、批准金额空/非正数、非人民币和超额付款。

事件定义：提交`(+reserved,0)`；驳回/撤回`(-reserved,0)`；付款`(-reserved,+paid)`；退款/冲销`(0,-paid)`。事件与请求状态同事务提交。已付款请求不得物理删除。

- [ ] **Step 4: 跑单元、并发及旧付款回归并提交**

```bash
git add rayher_hr_payroll/approval_amount_ledger.py rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests/test_approval_amount_ledger.py
git commit -m "feat: add append-only approval amount ledger"
```

### Task 6: 建立通用业务文档中心

**Files:**
- Create: `rayher_hr_payroll/business_documents.py`
- Test: `rayher_hr_payroll/tests/test_business_documents.py`

- [ ] **Step 1: 写权限和版本测试**

```python
def test_document_requires_parent_permission(service, login):
    login("employee-a@example.com")
    with pytest.raises(frappe.PermissionError):
        service.list_documents("OA-OTHER")

def test_private_file_url_cannot_bypass_parent_permission(http, login):
    login("employee-a@example.com")
    response = http.get("/private/files/other-contract.pdf")
    assert response.status_code in {403, 404}

def test_upload_appends_version(service, login):
    login("owner@example.com")
    first = service.attach("OA-1", "合同", "/private/files/a.pdf")
    second = service.attach("OA-1", "合同", "/private/files/b.pdf")
    assert second.version_no == first.version_no + 1
    assert second.supersedes == first.name
```

- [ ] **Step 2: 实现允许类型**

允许类型固定为：需求申请、报价单、价格审批表、PR、PO、合同、付款计划、发票、验收资料、送货单、收料单、入库单、付款回单、采购完成报告。这里仅归档，不表示对应流程已启用。

- [ ] **Step 3: 实现文件安全**

只接受私有Frappe File；限制扩展名、大小和文件头；保存SHA-256；下载和预览复用父单权限；禁止覆盖旧版本和客户端指定上传人。

- [ ] **Step 4: 跑测试并提交**

```bash
git add rayher_hr_payroll/business_documents.py rayher_hr_payroll/rayher_hr_payroll/doctype/oa_business_document rayher_hr_payroll/tests/test_business_documents.py
git commit -m "feat: add approval business document archive"
```

### Task 7: 构建草稿页面和只读看板

**Files:**
- Modify: `frontend/src/App.vue`、`frontend/src/router.js`
- Create: `frontend/src/pages/PreRequestCenter.vue`
- Create: `frontend/src/pages/PaymentCenter.vue`
- Create: `frontend/src/pages/ApprovalDashboard.vue`
- Create: `frontend/src/lib/approvalCenter.js`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Test: `frontend/tests/approval-center.test.js`
- Test: `rayher_hr_payroll/tests/test_approval_center_dashboard.py`

- [ ] **Step 1: 写路由和关闭测试**

要求存在请假审批、采购申请、购买申请、申请看板、采购付款、报销、对公付款和付款看板路由。请假审批继续使用已启用的现有逻辑；新采购/购买路线关闭不得隐藏或阻断请假。新路线关闭时，普通用户的boot flags不返回菜单和路由；Administrator本地验收页不渲染提交按钮，并显示：`审批流程尚未配置，当前仅可保存本地草稿。`

- [ ] **Step 2: 写请假不变回归与看板权限测试**

请假必须覆盖：原申请人可提交、原审批人可处理、无关员工不可查看、驳回/通过状态不变；新流程功能开关关闭时这些行为仍通过。

普通员工只看本人；审批人只看分配记录；财务只看付款范围；System Manager看组织范围。客户端部门参数不得扩大结果。

- [ ] **Step 3: 实现草稿页面**

管理员本地草稿支持基本信息、明细、资产属性、附件归档和来源预览。后端重算明细金额；前端不得提交批准金额、余额或状态字段。

- [ ] **Step 4: 实现看板**

展示申请、批准、占用、已付和可用余额。空资产属性显示“历史未分类”，不得归入非固定资产。

- [ ] **Step 5: 跑前后端测试并提交**

```bash
docker exec rayher-bench bash -lc 'cd /workspace/development/frappe-bench/apps/rayher_hr_payroll && python -m pytest rayher_hr_payroll/tests/test_approval_center_dashboard.py -q'
D:\Tools\Pi\node\node.exe --test frontend/tests/approval-center.test.js
git add frontend rayher_hr_payroll/api/oa_entry.py rayher_hr_payroll/tests/test_approval_center_dashboard.py
git commit -m "feat: add gated approval center drafts"
```

### Task 8: 完整验证和仅本地部署

**Files:**
- Modify generated: `rayher_hr_payroll/public/frontend/*`
- Create: `docs/superpowers/reports/2026-08-06-approval-center-safe-foundation-verification.md`

- [ ] **Step 1: 跑完整测试**

```bash
docker exec rayher-bench bash -lc 'cd /workspace/development/frappe-bench/apps/rayher_hr_payroll && python -m pytest rayher_hr_payroll/tests -q'
D:\Tools\Pi\node\node.exe --test frontend/tests/*.test.js
```

记录准确通过数，不得只写“全部通过”。

- [ ] **Step 2: 构建并扫描产物**

从`frontend`执行`yarn build`。检查全部Git新增/修改文件和构建产物开头不是TSD标记，`index.html`以正常HTML开头。

- [ ] **Step 3: 备份并迁移两次**

```bash
docker exec rayher-bench bash -lc 'cd /workspace/development/frappe-bench && bench --site rayher.localhost backup --with-files && bench --site rayher.localhost migrate && bench --site rayher.localhost migrate && bench --site rayher.localhost clear-cache'
```

两次迁移都退出0，第二次不再改变业务数据。

- [ ] **Step 4: 直接攻击验收**

跨员工原生REST读取、`frappe.client.set_value`改金额、关闭路线直接改状态、重复提交、并发超额付款、重复幂等键和未授权附件下载都必须被拒绝。

- [ ] **Step 5: 旧业务回归**

请假、报销、对公付款、发票OCR、工时及管理员查看保持原行为。新流程只显示本地草稿能力，无法提交。

- [ ] **Step 6: 写验证报告并提交**

报告记录提交SHA、测试命令和数量、备份路径、迁移结果、攻击结果、功能开关和本地截图；不得访问staging/product。

## 3. 后续独立计划

1. `approval-center-purchase-request`：购买申请正式路线、合同模板和关联付款。
2. `approval-center-procurement-request`：需求、PMC、演示员工37、价格审批、PR/PO和采购进度。
3. `approval-center-procurement-payment`：付款计划、预付款、到货、验收、发票核对、尾款和完成报告。
4. `approval-center-procurement-ocr`：采购发票字段、全局发票占用、三方金额核对和人工异常审批。
5. `approval-center-integrations`：金蝶、电子章、邮件的幂等接口和失败任务中心。

每份后续计划必须包含原生接口越权、缺审批人失败关闭、自审禁止、并发、幂等和路线快照测试。审批人未确认的路线只能开发为关闭状态。

## 4. 自审记录

- 范围：本计划只交付安全底座，没有假装覆盖采购完整业务。
- 权限：自定义API、原生列表、原生文档、set_value、导入器和附件均纳入。
- 金额：申请、批准、占用、已付、退款和可用余额分开。
- 关闭：路线未确定时仅Administrator本地保存草稿，全部提交路径失败关闭。
- 历史：不推断旧批准金额、资产类别或来源。
- 环境：仅本地Docker，不访问staging/product。
- 占位符扫描：没有TBD/TODO，未确认业务拆入后续独立计划。