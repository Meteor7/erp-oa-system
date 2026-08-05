# 员工信息分页与社保独立复算实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地 Docker 中完成员工信息固定表头/首列和20人分页，并将社保导入改为使用员工档案基数、户籍和期间政策独立复算的可审计批次流程。

**Architecture:** 将社保政策、户籍映射和金额比较保持为纯函数；API层负责按期间解析员工基数、保存导入快照和批次状态；Vue页面只负责筛选分页与显式操作。既有 `Employee Social Insurance` 作为月度基数优先来源，员工默认基数作为兼容回退，导入行保存不可变快照。

**Tech Stack:** Frappe/Python、MariaDB、Vue 3、frappe-ui、pytest、Node source tests、Vite/Yarn、Docker Compose。

## Global Constraints

- 仅修改本地 Docker 环境，不接触 staging 或 production。
- 不编造业务记录，不自动删除现有两个2026年7月待确认批次。
- 户口下拉只允许：深圳、广东省内城镇、广东省内农村、广东省外城镇、广东省外农村。
- 深圳判定为深户，其余四项判定为非深户；空值或异常值进入待确认。
- 员工表固定表头和第一列，固定每页20人，不提供页大小切换。
- 社保匹配率分母为Excel有效明细总人数；人工确认与忽略不提升自动匹配人数。
- 示例研发中心未配置政策时不得套用深圳规则。
- 所有金额按单项四舍五入到分后汇总。

---

### Task 1: 社保政策、户籍映射和严格匹配纯函数

**Files:**
- Modify: `rayher_hr_payroll/hr_contributions.py`
- Modify: `rayher_hr_payroll/social_insurance_import.py`
- Test: `rayher_hr_payroll/tests/test_hr_contributions.py`
- Test: `rayher_hr_payroll/tests/test_social_insurance_import.py`

**Interfaces:**
- Produces: `household_classification(value) -> bool | None`
- Produces: `social_policy(company: str, period: str) -> dict | None`
- Produces: `reconcile_row(row, employee, company=None, association_reason="") -> dict`
- `employee` must provide `social_insurance_base`, `social_base_source`, `household_registration`, `company`, `name`, `employee_name`.

- [ ] **Step 1: Write failing policy and household tests**

```python
def test_household_categories_are_mapped_without_excel_inference():
    assert household_classification("深圳") is True
    assert household_classification("广东省内城镇") is False
    assert household_classification("广东省内农村") is False
    assert household_classification("广东省外城镇") is False
    assert household_classification("广东省外农村") is False
    assert household_classification("") is None


def test_shanghai_policy_is_not_faked_with_shenzhen_rates():
    assert social_policy("示例研发中心", "2026-07") is None
```

- [ ] **Step 2: Run tests and verify failure**

Run: `docker exec rayher-bench bash -lc 'cd /workspace/development/frappe-bench/apps/rayher_hr_payroll && pytest -q rayher_hr_payroll/tests/test_hr_contributions.py rayher_hr_payroll/tests/test_social_insurance_import.py'`

Expected: FAIL because the new mapping and policy functions do not exist.

- [ ] **Step 3: Implement explicit policy selection and household mapping**

```python
HOUSEHOLD_OPTIONS = (
    "深圳", "广东省内城镇", "广东省内农村", "广东省外城镇", "广东省外农村",
)

def household_classification(value):
    value = str(value or "").strip()
    if value == "深圳":
        return True
    if value in HOUSEHOLD_OPTIONS[1:]:
        return False
    return None


def social_policy(company, period):
    if company == "Rayher" and str(period)[:4] == "2026":
        return {"version": "示例总部-2026", "medical_floor": Decimal("6727"), ...}
    return None
```

Update `reconcile_row` so calculations use `employee["social_insurance_base"]`, compare that value with `row["contribution_base"]`, reject missing household or missing policy, and never try both household formulas.

- [ ] **Step 4: Add strict reconciliation tests**

```python
def test_reconcile_uses_employee_base_not_excel_base():
    row = july_row(contribution_base="10000")
    employee = employee_row(social_insurance_base="5000", household_registration="广东省外城镇")
    result = reconcile_row(row, employee)
    assert result["status"] == "Pending"
    assert "缴费工资与员工档案社保基数不一致" in result["difference_reasons"]
    assert result["calculated"]["employee_pension"] == Decimal("400.00")


def test_missing_household_and_missing_policy_are_pending():
    assert "户口信息未维护" in reconcile_row(july_row(), employee_row(household_registration=""))["difference_reasons"]
    assert "社保政策未配置" in reconcile_row(july_row(), employee_row(company="示例研发中心"))["difference_reasons"]
```

- [ ] **Step 5: Run pure-function tests**

Expected: all calculation and import tests pass, including base 5000 medical floor and deep/non-deep local pension cases.

- [ ] **Step 6: Commit Task 1**

```bash
git add rayher_hr_payroll/hr_contributions.py rayher_hr_payroll/social_insurance_import.py rayher_hr_payroll/tests/test_hr_contributions.py rayher_hr_payroll/tests/test_social_insurance_import.py
git commit -m "fix: reconcile social insurance from employee records"
```

### Task 2: 月度基数解析与导入行不可变快照

**Files:**
- Modify: `rayher_hr_payroll/api/social_insurance_import_entry.py`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/social_insurance_import_row/social_insurance_import_row.json`
- Test: `rayher_hr_payroll/tests/test_social_insurance_import.py`
- Create: `rayher_hr_payroll/tests/test_social_insurance_import_entry.py`

**Interfaces:**
- Produces: `_employees(period) -> list[dict]` with `social_insurance_base`, `social_base_source`.
- Import row fields: `reference_base`, `base_source`, `household_source`, `household_classification`, `policy_version`.

- [ ] **Step 1: Write failing base precedence tests**

```python
def test_period_record_wins_over_employee_default_base(fake_frappe):
    employees = _employees("2026-07")
    assert employees[0]["social_insurance_base"] == Decimal("6000")
    assert employees[0]["social_base_source"] == "2026-07月度社保记录"


def test_default_base_is_snapshotted_when_period_record_is_absent(fake_frappe):
    employees = _employees("2026-07")
    assert employees[0]["social_insurance_base"] == Decimal("5000")
    assert employees[0]["social_base_source"] == "员工默认基数"
```

- [ ] **Step 2: Run the new API tests and verify failure**

Expected: FAIL because `_employees` currently has no period argument or resolved base fields.

- [ ] **Step 3: Add snapshot fields and base resolver**

Query active employees and exact-period `Employee Social Insurance` records once, merge by employee id, and store the resolved values in `_row_values`. Do not create or mutate employee/monthly base records during upload.

- [ ] **Step 4: Test that later employee changes do not change stored batch rows**

```python
def test_import_row_keeps_reference_snapshot_after_employee_change():
    stored = _row_values(batch, excel_row, reconciliation)
    assert stored["reference_base"] == Decimal("5000")
    assert stored["base_source"] == "员工默认基数"
    assert stored["household_source"] == "深圳"
    assert stored["policy_version"] == "示例总部-2026"
```

- [ ] **Step 5: Run backend unit tests**

Expected: new snapshot tests and existing parser tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add rayher_hr_payroll/api/social_insurance_import_entry.py rayher_hr_payroll/rayher_hr_payroll/doctype/social_insurance_import_row/social_insurance_import_row.json rayher_hr_payroll/tests/test_social_insurance_import.py rayher_hr_payroll/tests/test_social_insurance_import_entry.py
git commit -m "feat: snapshot employee social insurance inputs"
```

### Task 3: 待确认行、忽略和批次取消/确认流程

**Files:**
- Modify: `rayher_hr_payroll/api/social_insurance_import_entry.py`
- Modify: `rayher_hr_payroll/social_insurance_import.py`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/social_insurance_import_batch/social_insurance_import_batch.json`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/social_insurance_import_row/social_insurance_import_row.json`
- Test: `rayher_hr_payroll/tests/test_social_insurance_import.py`
- Test: `rayher_hr_payroll/tests/test_social_insurance_import_entry.py`

**Interfaces:**
- Produces API: `ignore_social_row(row: str, remark: str)`.
- Produces API: `cancel_social_batch(batch: str, remark: str)`.
- Keeps API: `confirm_social_row(...)`, `activate_social_batch(...)`.

- [ ] **Step 1: Write failing status and summary tests**

```python
def test_ignored_rows_remain_in_match_rate_denominator():
    summary = summarize_rows([matched_row(), ignored_row(), pending_row()])
    assert summary["total_rows"] == 3
    assert summary["matched_rows"] == 1
    assert summary["match_rate"] == 33.33


def test_batch_requires_no_pending_and_at_least_one_accepted_row():
    assert can_activate_rows([matched_row(), ignored_row()]) is True
    assert can_activate_rows([ignored_row()]) is False
    assert can_activate_rows([matched_row(), pending_row()]) is False
```

- [ ] **Step 2: Run tests and verify failure**

Expected: FAIL because Ignored/Canceled are unsupported and current match denominator is linked rows.

- [ ] **Step 3: Implement audited row and batch transitions**

- `ignore_social_row` requires non-empty remark, pending row, and pending-activation batch.
- `cancel_social_batch` requires non-empty remark and pending-activation batch.
- Store `ignored_by`, `ignored_at`, `canceled_by`, `canceled_at`, and cancellation remark.
- Formal details include only Matched and Confirmed Difference rows.
- Batch activation treats Ignored as resolved but requires at least one accepted row.

- [ ] **Step 4: Add transition guard tests**

Test empty remarks, repeated transitions, canceled batch activation, pending rows blocking activation, and historical/current data remaining unchanged after cancel.

- [ ] **Step 5: Run import and API tests**

Expected: all transition tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add rayher_hr_payroll/api/social_insurance_import_entry.py rayher_hr_payroll/social_insurance_import.py rayher_hr_payroll/rayher_hr_payroll/doctype/social_insurance_import_batch/social_insurance_import_batch.json rayher_hr_payroll/rayher_hr_payroll/doctype/social_insurance_import_row/social_insurance_import_row.json rayher_hr_payroll/tests/test_social_insurance_import.py rayher_hr_payroll/tests/test_social_insurance_import_entry.py
git commit -m "feat: add audited social import resolution flow"
```

### Task 4: 员工户口校验与派生判断

**Files:**
- Modify: `rayher_hr_payroll/api/personnel_entry.py`
- Test: `rayher_hr_payroll/tests/test_personnel_entry.py`

**Interfaces:**
- Produces API: `get_household_options() -> list[str]`.
- `list_employees()` adds `household_classification` display value.
- `save_employee()` rejects non-empty values outside the five confirmed options.

- [ ] **Step 1: Write failing personnel validation tests**

```python
def test_household_options_and_classification_are_explicit():
    assert mod.get_household_options() == ["深圳", "广东省内城镇", "广东省内农村", "广东省外城镇", "广东省外农村"]


def test_save_employee_rejects_unknown_household_value():
    with pytest.raises(RuleError, match="户口信息"):
        mod.save_employee(name="EMP-1", household_registration="深户")
```

- [ ] **Step 2: Run personnel tests and verify failure**

- [ ] **Step 3: Implement validation and derived label**

Return `深户`, `非深户`, or `待完善` without overwriting the stored original category.

- [ ] **Step 4: Run personnel tests**

Expected: all existing and new personnel tests pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add rayher_hr_payroll/api/personnel_entry.py rayher_hr_payroll/tests/test_personnel_entry.py
git commit -m "feat: validate employee household categories"
```

### Task 5: 员工表固定表头/首列与20人分页

**Files:**
- Modify: `frontend/src/pages/Personnel.vue`
- Create: `frontend/tests/personnel-source.test.js`

**Interfaces:**
- Consumes `rows.data`, company/department resources, and derived `household_classification`.
- Produces client state: `companyFilter`, `departmentFilter`, `keyword`, `currentPage`, `PAGE_SIZE = 20`, `pagedRows`.

- [ ] **Step 1: Write failing source behavior tests**

Verify source contains fixed `PAGE_SIZE=20`, computed page slicing, filters resetting the page, sticky header classes, sticky first-column classes, household select options, and visible household/base columns.

- [ ] **Step 2: Run Node source test and verify failure**

Run: `docker exec rayher-bench bash -lc 'cd /workspace/development/frappe-bench/apps/rayher_hr_payroll/frontend && node --test tests/personnel-source.test.js'`

- [ ] **Step 3: Implement filtering and pagination**

```js
const PAGE_SIZE = 20;
const currentPage = ref(1);
const filteredRows = computed(() => ...);
const pageCount = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / PAGE_SIZE)));
const pagedRows = computed(() => filteredRows.value.slice((currentPage.value - 1) * PAGE_SIZE, currentPage.value * PAGE_SIZE));
```

Add previous/next and page number controls; no page-size selector. Reset to page 1 on company, department, or keyword changes.

- [ ] **Step 4: Implement visibility and sticky layout**

- Replace free-text household input with five-option select.
- Place 户口信息、系统判断、社保基数、公积金基数 near department/position columns.
- Render `未维护` badges for missing values.
- Use a bounded scroll container with sticky `thead th { top: 0 }` and sticky first cell `{ left: 0 }`, with opaque backgrounds and z-index layering.
- Global sequence is `(currentPage - 1) * 20 + index + 1`.

- [ ] **Step 5: Run source test and frontend build**

Run Node test, then `yarn build`. Expected: both pass without Vue compile errors.

- [ ] **Step 6: Commit Task 5**

```bash
git add frontend/src/pages/Personnel.vue frontend/tests/personnel-source.test.js
git commit -m "feat: paginate and clarify employee information"
```

### Task 6: 社保页面显式批次与差异处理界面

**Files:**
- Modify: `frontend/src/pages/SocialInsurance.vue`
- Create: `frontend/tests/social-insurance-source.test.js`

**Interfaces:**
- Consumes APIs: `get_social_workbench`, `confirm_social_row`, `ignore_social_row`, `activate_social_batch`, `cancel_social_batch`.
- Displays snapshot fields and both calculated/Excel values.

- [ ] **Step 1: Write failing social page source tests**

Verify every pending row has remark input plus “确认并纳入本批次”和“忽略此行”; every pending-activation batch row has “确认导入”和“取消批次”; batch buttons are not conditionally hidden in the upload toolbar; pending table displays档案基数、Excel基数、户籍判断、政策版本 and difference reasons.

- [ ] **Step 2: Run source test and verify failure**

- [ ] **Step 3: Implement resources and actions**

Add explicit row/batch action resources, require remarks client-side, reload the selected batch after every action, and show backend validation errors through `extractFrappeError`.

- [ ] **Step 4: Recompose tables for audit readability**

Keep the four confirmed page sections. Add side-by-side archive/calculated/Excel/difference columns without removing company and period filters. Batch actions live in each batch row so users can always find them.

- [ ] **Step 5: Run source tests and frontend build**

Expected: personnel and social source tests pass; Vite build succeeds.

- [ ] **Step 6: Commit Task 6**

```bash
git add frontend/src/pages/SocialInsurance.vue frontend/tests/social-insurance-source.test.js
git commit -m "feat: expose social import confirmation workflow"
```

### Task 7: Schema migration、严格回归和本地浏览器验证

**Files:**
- Generated by build: `rayher_hr_payroll/public/frontend/**`
- No manual business-data fixture writes.

**Interfaces:**
- Deploys the preceding backend schema and frontend bundle to `rayher.localhost` only.

- [ ] **Step 1: Run focused backend test suite**

```bash
pytest -q rayher_hr_payroll/tests/test_hr_contributions.py rayher_hr_payroll/tests/test_social_insurance_import.py rayher_hr_payroll/tests/test_social_insurance_import_entry.py rayher_hr_payroll/tests/test_personnel_entry.py
```

Expected: all pass.

- [ ] **Step 2: Run frontend tests and build**

```bash
node --test frontend/tests/personnel-source.test.js frontend/tests/social-insurance-source.test.js
yarn --cwd frontend build
```

Expected: all pass and assets regenerate.

- [ ] **Step 3: Apply schema only to local site**

```bash
bench --site rayher.localhost migrate
bench --site rayher.localhost clear-cache
```

Do not insert, cancel, confirm, or delete any existing business batches during migration.

- [ ] **Step 4: Run a read-only July regression audit**

Use the original July Excel and current employee records without saving a new batch. Expected strict result: 68 linked, 68 base matches, 47 automatic matches, 18 missing-household pending, 3 local-pension conflicts, match rate 69.12%.

- [ ] **Step 5: Browser-test employee page**

Verify first row and first column remain visible during vertical/horizontal scrolling, exactly 20 employees appear on the first full page, filters reset page,户口下拉 saves, and missing data is marked.

- [ ] **Step 6: Browser-test social page without mutating batches**

Verify July batch rows expose confirm/cancel actions, pending rows expose remark confirm/ignore actions when present, dashboard denominator semantics are visible, and no action is clicked during QA.

- [ ] **Step 7: Run final git diff and encryption/plaintext checks**

Confirm only scoped source/schema/tests/assets changed, existing unrelated dirty files remain preserved, and new text files begin with normal plaintext headers rather than a TipRay marker.

- [ ] **Step 8: Commit generated assets and migration-safe schema**

```bash
git add rayher_hr_payroll/public/frontend
git commit -m "build: publish personnel and social reconciliation frontend"
```