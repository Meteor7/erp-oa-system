# Foreign-only 月度台账完整修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完整修复“某月只有海外研发费用、没有已提交国内分摊单时，研发费用台账前端显示无数据”的 P1，并保证月视图不会混入同年其他月份数据。

**Architecture:** 保留现有 `get_allocation()` 汇总接口和 `RD Allocation Matrix` 报表，不重构台账架构。后端为月度和年度汇总统一返回明确的数据存在标志；报表新增严格的 `year + month` 月度路径；前端根据 `has_data` 显示汇总，并在没有国内分摊单编号时使用年月加载海外矩阵。

**Tech Stack:** Python、Frappe Script Report、Vue 3、frappe-ui、Node.js `node:test`、pytest。

## Global Constraints

- 本计划只处理 foreign-only 台账显示 P1，不处理 Issue #25–#32 中的其他问题。
- 不处理异步请求乱序风险；该风险单独评估、单独建 Issue，不并入本提交。
- 不重构为新的台账 API，不改数据库结构，不新增 DocType 或迁移。
- 不改变国内费用导入、重算、提交、撤销和期间锁定逻辑。
- “重算分摊”按钮保持现状；“撤销本期分摊”仍只在存在国内分摊单 `name` 时显示。
- 不修改 `status` 的现有语义，因为当前台账页面不依赖该字段判断数据存在。
- `has_data` 表示“存在国内或海外业务数据”，不是“已分摊金额非零”。
- `has_foreign_data` 不得仅由金额或 `expense_import` 判断；普通国内费用导入也可能产生 `expense_import`。
- 空白海外草稿单不单独构成业务数据；`has_foreign_data` 由实际 `expense_sources` 或 `lines` 判断。
- 报表月度路径必须优先识别 `year + month`，不得落入年度查询。
- 前端报表过滤参数三选一：年度 `{year, stage}`、有国内单的月度 `{allocation, stage}`、无国内单的月度 `{year, month, stage}`。
- 报表直接按年月调用时仍必须执行 `RD_FINANCE_ROLES` 财务权限检查。
- 只生成一个独立修复提交：`fix: complete foreign-only allocation ledger`。

## 本次必须修改

| 范围 | 必要原因 |
|---|---|
| 月度与年度汇总数据标志 | 前端不能再把国内分摊单 `name` 当作所有数据存在的唯一条件 |
| 报表 `year + month` 查询 | foreign-only 月份没有国内分摊单编号，只能按年月加载矩阵 |
| 前端汇总与矩阵加载分支 | 让后端已经返回的海外汇总和明细真正显示出来 |
| foreign-only 空状态 | 避免把海外费用误导为需要执行国内“重算分摊” |
| 财务权限检查 | 新增的无国内父文档查询路径不能绕过台账权限 |
| 行为回归测试 | 防止再次出现“后端修了但前端消费路径仍丢数据” |

## 本次明确不修改

| 不修改项 | 原因 |
|---|---|
| 异步请求乱序 | 是相邻的既有风险，不是 foreign-only P1 的根因；混入会扩大审查范围 |
| `status` 字段语义 | 页面不依赖它；修改没有本 P1 的直接收益 |
| OCR、审批、OA 原生接口、每日 8 小时等 Issue | 与本 P1 无关 |
| 国内重算和撤销事务 | 当前问题发生在只读展示链路 |
| 台账整体改用 `get_allocation_dashboard()` | 改动面过大，不符合最小修复原则 |

---

### Task 1: 为月度和年度汇总增加可靠的数据存在标志

**Files:**
- Modify: `rayher_hr_payroll/api/allocation_entry.py`
- Test: `rayher_hr_payroll/tests/test_allocation_entry.py`

**Interfaces:**
- Produces: `_foreign_period_state(year, month) -> tuple[dict[str, float], bool]`
- Produces: `get_allocation()` 和 `_year_allocation()` 响应字段 `has_data`、`has_domestic_data`、`has_foreign_data`
- Preserves: `_foreign_stage_totals(year, month) -> dict[str, float]`

- [ ] **Step 1: 写月度 foreign-only 失败测试**

新增行为测试，构造没有国内分摊单、海外 payload 有 `expense_sources` 但分摊金额为零的月份：

```python
def test_get_allocation_marks_foreign_expense_sources_as_business_data(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.get_value = lambda *args, **kwargs: None
    monkeypatch.setattr(mod, "_foreign_period_state", lambda year, month: (
        mod._zero_stage_totals(),
        True,
    ), raising=False)

    result = mod.get_allocation("2026-06")

    assert result["name"] is None
    assert result["has_domestic_data"] is False
    assert result["has_foreign_data"] is True
    assert result["has_data"] is True
```

- [ ] **Step 2: 写国内、空月份和年度失败测试**

覆盖以下行为：

```python
def test_get_allocation_marks_empty_month_as_no_data(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: (mod._zero_stage_totals(), False),
        raising=False,
    )
    frappe.db.get_value = lambda *args, **kwargs: None

    result = mod.get_allocation("2026-06")

    assert result["has_domestic_data"] is False
    assert result["has_foreign_data"] is False
    assert result["has_data"] is False


def test_get_allocation_marks_domestic_month_as_data(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: (mod._zero_stage_totals(), False),
        raising=False,
    )
    monkeypatch.setattr(mod, "_project_summaries", lambda name: [])
    frappe.db.get_value = lambda *args, **kwargs: "ALLOC-1"
    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        name=name,
        status="Submitted",
        capitalized_total=0,
        expensed_total=0,
        unknown_total=0,
        lines=[],
    )

    result = mod.get_allocation("2026-06")

    assert result["has_domestic_data"] is True
    assert result["has_foreign_data"] is False
    assert result["has_data"] is True


def test_year_allocation_keeps_foreign_only_year_visible(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    frappe.get_all = lambda doctype, **kwargs: []
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: (
            {"capitalized": 12, "expensed": 8, "unknown": 0}
            if month == 6 else mod._zero_stage_totals(),
            month == 6,
        ),
        raising=False,
    )

    result = mod._year_allocation("2026-06")

    assert result["scope"] == "year"
    assert result["has_domestic_data"] is False
    assert result["has_foreign_data"] is True
    assert result["has_data"] is True
```

年度测试必须模拟 12 个月状态，其中仅 6 月 `has_foreign_data=True`，证明年度页面不会因没有国内 allocation 而被隐藏。

- [ ] **Step 3: 运行测试并确认当前实现失败**

Run:

```bash
python -m pytest rayher_hr_payroll/tests/test_allocation_entry.py -k "foreign_expense_sources_as_business_data or empty_month_as_no_data or domestic_month_as_data or foreign_only_year_visible" -q
```

Expected: FAIL，响应中缺少 `has_data`、`has_domestic_data` 或 `has_foreign_data`。

- [ ] **Step 4: 实现单月海外状态读取**

在 `allocation_entry.py` 中增加：

```python
def _foreign_period_state(year, month):
    from rayher_hr_payroll.api import foreign_rd_entry

    payload = foreign_rd_entry._get_foreign_rd_month(int(year), int(month))
    totals = _zero_stage_totals()
    for row in payload.get("foreign_stage_summaries", []) or []:
        stage = _value(row, "stage") or "unknown"
        if stage not in totals:
            stage = "unknown"
        totals[stage] += _number(_value(row, "total"))
    has_foreign_data = bool(
        payload.get("expense_sources")
        or payload.get("lines")
    )
    return totals, has_foreign_data
```

保留现有函数签名：

```python
def _foreign_stage_totals(year, month):
    totals, _has_foreign_data = _foreign_period_state(year, month)
    return totals
```

不得把 `payload.get("expense_import")` 单独加入判断，因为该导入可能只有国内费用。
不得把 `payload.get("name")` 单独加入判断，因为完全空白的海外草稿单不属于实际业务数据。

实现改为直接调用 `_foreign_period_state()` 后，把现有 `test_allocation_entry.py` 中针对
`_foreign_stage_totals` 的月度和年度 mock 同步改为 `_foreign_period_state`，并返回
`(totals, has_foreign_data)`；保留专门验证 `_foreign_stage_totals` 兼容包装和异常传播的测试。

- [ ] **Step 5: 在月度响应中返回三个标志**

`get_allocation()` 只读取一次 `_foreign_period_state()`：

```python
foreign_totals, has_foreign_data = _foreign_period_state(year, month)
has_domestic_data = bool(name)
has_data = has_domestic_data or has_foreign_data
```

无国内单和有国内单的两个返回分支都必须包含：

```python
"has_data": has_data,
"has_domestic_data": has_domestic_data,
"has_foreign_data": has_foreign_data,
```

- [ ] **Step 6: 在年度响应中聚合三个标志**

`_year_allocation()` 中：

```python
has_domestic_data = bool(allocation_names)
has_foreign_data = False
for month in range(1, 13):
    month_totals, month_has_foreign_data = _foreign_period_state(year, month)
    has_foreign_data = has_foreign_data or month_has_foreign_data
    for stage in foreign_totals:
        foreign_totals[stage] += _number(month_totals.get(stage))
```

年度响应加入相同三个字段，并保持现有 `status` 逻辑不变。

- [ ] **Step 7: 运行相关后端测试**

Run:

```bash
python -m pytest rayher_hr_payroll/tests/test_allocation_entry.py -q
```

Expected: PASS。

---

### Task 2: 为矩阵报表增加不会串月的年月路径

**Files:**
- Modify: `rayher_hr_payroll/rayher_hr_payroll/report/rd_allocation_matrix/rd_allocation_matrix.py`
- Test: `rayher_hr_payroll/tests/test_reports.py`

**Interfaces:**
- Consumes: filters `{year, month, stage}`
- Produces: `_allocation_names_for_month(frappe, year, month) -> list[str]`，最多返回一份最新已提交国内分摊单
- Produces: `_foreign_periods_for_report()` 在年月组合下只返回一个月份

- [ ] **Step 1: 写海外矩阵只加载指定月份的失败测试**

测试 `year=2026, month=6`：

```python
def test_matrix_report_year_month_loads_only_requested_foreign_month(monkeypatch):
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    called = []
    class FakeFrappe:
        _ = staticmethod(lambda text: text)

        def get_list(self, doctype, **kwargs):
            assert doctype == "RD Cost Allocation"
            return []

    monkeypatch.setattr(mod, "_get_frappe", lambda: FakeFrappe())
    monkeypatch.setattr(mod, "_require_finance_access", lambda: None, raising=False)
    monkeypatch.setattr(
        mod,
        "_foreign_matrix_lines_for_month",
        lambda year, month: called.append((year, month)) or [],
    )

    mod.execute({"year": 2026, "month": 6, "stage": "all"})

    assert called == [(2026, 6)]
```

测试不得只调用 `_foreign_periods_for_report()`；必须调用完整 `execute()`，覆盖真实报表路径。

- [ ] **Step 2: 写月度国内分摊不会加载同年其他月份的失败测试**

Fake Frappe 记录 `RD Cost Allocation` 查询条件：

```python
def test_matrix_report_year_month_queries_only_same_month_domestic_allocation(monkeypatch):
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    captured = {}
    class FakeFrappe:
        _ = staticmethod(lambda text: text)

        def get_list(self, doctype, filters=None, limit_page_length=None, **kwargs):
            assert doctype == "RD Cost Allocation"
            captured["filters"] = filters
            captured["limit_page_length"] = limit_page_length
            return []

    monkeypatch.setattr(mod, "_get_frappe", lambda: FakeFrappe())
    monkeypatch.setattr(mod, "_require_finance_access", lambda: None, raising=False)
    monkeypatch.setattr(mod, "_foreign_matrix_lines_for_month", lambda year, month: [])
    monkeypatch.setattr(
        mod,
        "_allocation_names_for_year",
        lambda frappe, year: (_ for _ in ()).throw(AssertionError("annual query must not run")),
    )

    mod.execute({"year": 2026, "month": 6, "stage": "all"})

    assert captured["filters"] == {
        "year": 2026,
        "month": 6,
        "docstatus": 1,
    }
    assert captured["limit_page_length"] == 1
```

同时断言未调用 `_allocation_names_for_year()`。

- [ ] **Step 3: 写直接年月调用的财务权限失败测试**

```python
def test_matrix_report_stops_before_business_reads_when_finance_access_is_denied(monkeypatch):
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    class AccessDenied(Exception):
        pass

    class FakeFrappe:
        def get_list(self, *args, **kwargs):
            raise AssertionError("business read must not run")

    monkeypatch.setattr(mod, "_get_frappe", lambda: FakeFrappe())
    monkeypatch.setattr(
        mod,
        "_require_finance_access",
        lambda: (_ for _ in ()).throw(AccessDenied()),
        raising=False,
    )

    with pytest.raises(AccessDenied):
        mod.execute({"year": 2026, "month": 6})


def test_matrix_report_finance_wrapper_uses_finance_roles(monkeypatch):
    from types import SimpleNamespace
    import sys
    from rayher_hr_payroll.rayher_hr_payroll.report.rd_allocation_matrix import rd_allocation_matrix as mod

    checked = []
    fake_guards = SimpleNamespace(
        RD_FINANCE_ROLES=("System Manager", "Accounts User"),
        require_rd_access=lambda roles: checked.append(roles),
    )
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.api._guards", fake_guards)

    mod._require_finance_access()

    assert checked == [fake_guards.RD_FINANCE_ROLES]
```

权限检查必须发生在读取 allocation、海外费用或工时之前。

- [ ] **Step 4: 运行测试并确认当前实现失败**

Run:

```bash
python -m pytest rayher_hr_payroll/tests/test_reports.py -k "matrix_report_year_month" -q
```

Expected: FAIL；当前实现会进入年度分支并调用 12 个月。

- [ ] **Step 5: 实现指定月份的国内单选择函数**

增加：

```python
def _allocation_names_for_month(frappe, year, month):
    rows = frappe.get_list(
        "RD Cost Allocation",
        filters={
            "year": int(year),
            "month": int(month),
            "docstatus": 1,
        },
        fields=["name"],
        order_by="creation desc",
        limit_page_length=1,
    )
    return [row["name"] for row in rows if row.get("name")]
```

选择条件和 `get_allocation()` 保持一致：指定年月、已提交、最新创建、最多一份。

- [ ] **Step 6: 修改海外期间选择优先级**

`_foreign_periods_for_report()` 必须按以下顺序：

```python
if filters.get("year") and filters.get("month"):
    return [(int(filters["year"]), int(filters["month"]))]
if filters.get("year"):
    return [(int(filters["year"]), month) for month in range(1, 13)]
```

- [ ] **Step 7: 修改 `execute()` 的查询分支**

在年度分支之前增加年月分支：

```python
if allocation:
    doc = frappe.get_doc("RD Cost Allocation", allocation)
    doc.check_permission("read")
    allocation_docs = [doc]
    allocation_names = [allocation]
elif filters.get("year") and filters.get("month"):
    allocation_names = _allocation_names_for_month(
        frappe,
        filters.get("year"),
        filters.get("month"),
    )
    for name in allocation_names:
        doc = frappe.get_doc("RD Cost Allocation", name)
        doc.check_permission("read")
        allocation_docs.append(doc)
elif filters.get("year"):
    allocation_names = _allocation_names_for_year(frappe, filters.get("year"))
    for name in allocation_names:
        doc = frappe.get_doc("RD Cost Allocation", name)
        doc.check_permission("read")
        allocation_docs.append(doc)
else:
    latest = _latest_allocation(frappe)
    if not latest:
        return [], []
    doc = frappe.get_doc("RD Cost Allocation", latest)
    doc.check_permission("read")
    allocation_docs = [doc]
    allocation_names = [latest]
```

年月分支不得调用 `_allocation_names_for_year()` 或 `_latest_allocation()`。

- [ ] **Step 8: 在报表入口执行财务权限检查**

增加延迟权限包装，保持报表模块可在无 Frappe 的纯测试环境导入：

```python
def _require_finance_access():
    from rayher_hr_payroll.api._guards import RD_FINANCE_ROLES, require_rd_access

    require_rd_access(RD_FINANCE_ROLES)
```

并在 `execute()` 读取任何业务数据前调用：

```python
_require_finance_access()
```

保留现有父文档 `doc.check_permission("read")`，形成角色与文档权限的双重检查。

- [ ] **Step 9: 运行完整报表测试**

Run:

```bash
python -m pytest rayher_hr_payroll/tests/test_reports.py -q
```

Expected: PASS。

---

### Task 3: 让前端显示 foreign-only 汇总并按年月加载矩阵

**Files:**
- Create: `frontend/src/lib/allocationView.js`
- Modify: `frontend/src/pages/Allocation.vue`
- Test: `frontend/tests/allocation-view.test.js`
- Test: `frontend/tests/allocation-source.test.js`

**Interfaces:**
- Consumes: 后端响应 `has_data`、`has_domestic_data`、`has_foreign_data`
- Produces: `hasAllocationData(payload) -> boolean`
- Produces: `buildAllocationMatrixFilters({scope, period, allocation, stage}) -> object`
- Produces: `allocationEmptyState({hasData, mode}) -> "no-data" | "no-detail" | "no-detail-for-mode"`

- [ ] **Step 1: 写纯行为失败测试**

新增 `frontend/tests/allocation-view.test.js`：

```javascript
import assert from "node:assert/strict";
import test from "node:test";
import {
  allocationEmptyState,
  buildAllocationMatrixFilters,
  hasAllocationData,
} from "../src/lib/allocationView.js";

test("foreign-only payload remains visible without a domestic allocation name", () => {
  assert.equal(hasAllocationData({
    name: null,
    has_data: true,
    has_domestic_data: false,
    has_foreign_data: true,
  }), true);
});

test("foreign-only month matrix uses exact year and month", () => {
  assert.deepEqual(buildAllocationMatrixFilters({
    scope: "month",
    period: "2026-06",
    allocation: null,
    stage: "all",
  }), { year: 2026, month: 6, stage: "all" });
});

test("domestic month matrix uses only allocation name", () => {
  assert.deepEqual(buildAllocationMatrixFilters({
    scope: "month",
    period: "2026-06",
    allocation: "ALLOC-1",
    stage: "capitalized",
  }), { allocation: "ALLOC-1", stage: "capitalized" });
});

test("year matrix does not include a month or allocation", () => {
  assert.deepEqual(buildAllocationMatrixFilters({
    scope: "year",
    period: "2026-06",
    allocation: "ALLOC-1",
    stage: "all",
  }), { year: 2026, stage: "all" });
});

test("empty state distinguishes no business data from no matrix detail", () => {
  assert.equal(allocationEmptyState({ hasData: false, mode: "all" }), "no-data");
  assert.equal(allocationEmptyState({ hasData: true, mode: "all" }), "no-detail");
  assert.equal(allocationEmptyState({ hasData: true, mode: "capitalized" }), "no-detail-for-mode");
});
```

- [ ] **Step 2: 运行测试并确认模块尚不存在**

Run:

```bash
& "D:\Tools\Pi\node\node.exe" --test --test-name-pattern="foreign-only|matrix uses|empty state" tests/allocation-view.test.js
```

Expected: FAIL，`allocationView.js` 尚不存在。

- [ ] **Step 3: 实现最小纯函数模块**

`frontend/src/lib/allocationView.js`：

```javascript
export function hasAllocationData(payload) {
  return Boolean(payload && payload.has_data);
}

export function buildAllocationMatrixFilters({ scope, period, allocation, stage }) {
  if (scope === "year") {
    return { year: Number(String(period).slice(0, 4)), stage };
  }
  if (allocation) {
    return { allocation, stage };
  }
  const [year, month] = String(period).split("-").map(Number);
  return { year, month, stage };
}

export function allocationEmptyState({ hasData, mode }) {
  if (!hasData) return "no-data";
  return mode === "all" ? "no-detail" : "no-detail-for-mode";
}
```

该模块只承载本 P1 所需的判断，不移动其他页面逻辑。

- [ ] **Step 4: 修改前端汇总判断和矩阵参数**

在 `Allocation.vue` 中导入三个纯函数，并将矩阵过滤器改为：

```javascript
const matrixFilters = computed(() => buildAllocationMatrixFilters({
  scope: periodScope.value,
  period: period.value,
  allocation: allocName.value,
  stage: allocationMode.value,
}));
```

`load()` 改为：

```javascript
summary.value = hasAllocationData(a) ? a : null;
allocName.value = a && a.name ? a.name : null;
await loadMatrix();
```

`loadMatrix()` 的提前退出条件改为：

```javascript
if (!summary.value) return;
```

不得改动撤销按钮条件：

```vue
v-if="allocName && !isYearScope"
```

- [ ] **Step 5: 修改矩阵为空时的提示**

增加文案：

```javascript
noBusinessData: "\u672c\u671f\u6682\u65e0\u6570\u636e\u3002",
noAllocationDetail: "\u5df2\u6709\u8d39\u7528\u6216\u4e1a\u52a1\u6570\u636e\uff0c\u4f46\u6682\u65e0\u53ef\u5c55\u793a\u7684\u9879\u76ee\u5206\u644a\u660e\u7ec6\u3002",
noDetailForMode: "\u5f53\u524d\u53e3\u5f84\u6682\u65e0\u53ef\u5c55\u793a\u7684\u5206\u644a\u660e\u7ec6\u3002",
```

模板在 `!result.length` 时根据 `allocationEmptyState()` 选择提示。不得继续在 foreign-only 空矩阵状态提示用户点击国内“重算分摊”。

- [ ] **Step 6: 更新页面连接测试**

`frontend/tests/allocation-source.test.js` 只验证页面正确调用已进行行为测试的纯函数：

```javascript
assert.match(source, /hasAllocationData\(a\)/);
assert.match(source, /buildAllocationMatrixFilters/);
assert.match(source, /allocationEmptyState/);
assert.match(source, /if \(!summary\.value\) return/);
assert.match(source, /v-if="allocName && !isYearScope"/);
```

不得用 source test 替代 `allocation-view.test.js` 的输入输出行为测试。

- [ ] **Step 7: 运行完整前端测试**

Run:

```bash
& "D:\Tools\Pi\node\node.exe" --test
```

Expected: 全部 PASS。

---

### Task 4: 端到端回归验证、构建并形成独立提交

**Files:**
- Modify through build: `rayher_hr_payroll/public/frontend/index.html`
- Modify through build: `rayher_hr_payroll/public/frontend/assets/*`
- Verify: all files changed by Tasks 1–3

**Interfaces:**
- Produces: PR #24 上一个可独立审查、可独立回退的修复提交

- [ ] **Step 1: 运行后端相关测试**

Run:

```bash
python -m pytest \
  rayher_hr_payroll/tests/test_allocation_entry.py \
  rayher_hr_payroll/tests/test_reports.py \
  rayher_hr_payroll/tests/test_foreign_rd_entry.py \
  -q
```

Expected: 全部 PASS。

- [ ] **Step 2: 运行完整前端测试**

Run:

```bash
& "D:\Tools\Pi\node\node.exe" --test
```

Expected: 全部 PASS。

- [ ] **Step 3: 构建生产前端**

Run:

```powershell
$env:PATH = "D:\Tools\Pi\node;$env:PATH"
& "D:\Tools\Pi\node\node.exe" `
  "D:\Tools\Pi\node\node_modules\corepack\dist\yarn.js" build
```

Expected: 构建成功，产物写入 `rayher_hr_payroll/public/frontend/`。

- [ ] **Step 4: 复核改动范围**

Run:

```bash
git status --short
git diff --stat
git diff --check
```

Expected:

- 业务源码只涉及汇总状态、矩阵年月分支和台账前端消费。
- 测试只涉及相同调用链。
- 生产前端只有构建产物变化。
- 不出现 OA、OCR、审批、每日工时限制、数据库迁移或其他 Issue 的源码修改。
- `git diff --check` 无空白错误。

- [ ] **Step 5: 验证 TipRay 明文头**

从 `git diff --name-only` 和未跟踪文件列表取得本次所有新增、修改和构建产物，
逐个按原始字节确认文件开头不含准确标记 `%TSD-Header-###%`。检查范围必须包括源码、
测试、计划以及本次变化的 `public/frontend/index.html`、`assets/*.js`、`assets/*.css`。

```powershell
$changed = @(
  git diff --name-only
  git ls-files --others --exclude-standard
) | Sort-Object -Unique

foreach ($path in $changed) {
  $bytes = [System.IO.File]::ReadAllBytes((Join-Path (Get-Location) $path))
  $prefixLength = [Math]::Min($bytes.Length, 64)
  $prefix = [System.Text.Encoding]::ASCII.GetString($bytes, 0, $prefixLength)
  if ($prefix.Contains("%TSD-Header-###%")) {
    throw "TipRay encrypted output: $path"
  }
}
```

Expected: 所有本次变更文件通过；Markdown/Python/Vue/JS/CSS/HTML 均为可识别明文头，
任何文件出现 `%TSD-Header-###%` 都必须先恢复为明文后才能提交。

- [ ] **Step 6: 创建一个独立提交**

Run:

```bash
git add \
  docs/superpowers/plans/2026-07-30-foreign-only-allocation-ledger-completion.md \
  rayher_hr_payroll/api/allocation_entry.py \
  rayher_hr_payroll/rayher_hr_payroll/report/rd_allocation_matrix/rd_allocation_matrix.py \
  rayher_hr_payroll/tests/test_allocation_entry.py \
  rayher_hr_payroll/tests/test_reports.py \
  frontend/src/lib/allocationView.js \
  frontend/src/pages/Allocation.vue \
  frontend/tests/allocation-view.test.js \
  frontend/tests/allocation-source.test.js \
  rayher_hr_payroll/public/frontend
git commit -m "fix: complete foreign-only allocation ledger"
```

- [ ] **Step 7: 推送前最终核验**

Run:

```bash
git show --stat --oneline HEAD
git status --short
git rev-parse HEAD
```

Expected:

- 提交只包含本任务书列出的范围。
- 工作区干净。
- 记录新提交 SHA，随后推送到 PR #24 的 head 分支。

## 最终验收场景

1. 2026-06 有海外费用、无国内已提交分摊单：顶部汇总显示，矩阵只加载 2026-06。
2. 2026-06 有公共海外费用但没有海外工时：`has_data=true`，矩阵为空，页面提示已有费用但暂无项目分摊明细。
3. 2026-06 国内和海外数据同时存在：汇总金额相加，矩阵不重复，撤销按钮仍仅针对国内分摊单。
4. 2026-06 国内和海外都没有：`has_data=false`，页面显示本期暂无数据。
5. 2026 年只有海外数据：年度汇总不被隐藏，年度矩阵仍按 12 个月聚合。
6. 直接执行报表 `{year: 2026, month: 6}`：只访问 6 月，不访问其他月份，并执行财务角色检查。
7. 选择“资本化”但只有费用化明细：提示当前口径暂无明细，不提示执行国内重算。

## 完成定义

- 上述七个验收场景均有自动化行为测试或对应的后端查询断言。
- 后端相关测试和完整前端测试全部通过。
- 生产前端构建成功。
- 没有本任务范围外的业务源码改动。
- 修复以一个独立提交进入 PR #24。
