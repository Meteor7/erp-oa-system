# 组织架构部门收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按组织架构重建员工正式部门分类，并提供清晰可筛选的部门人数视图。

**Architecture:** 用一个纯 Python 组织映射模块维护正式部门、板块和人员归属；导入和本地同步共用该模块。员工 API 只返回实际使用部门与人数，Vue 页面用分组卡片呈现并复用现有筛选。

**Tech Stack:** Frappe/ERPNext、Python、Vue 3、Vitest、MariaDB、Docker。

## Global Constraints

- 只修改 `rayher.localhost` 本地 Docker。
- 不删除历史 Department 主数据，不编造员工。
- 页面不显示 RAY/QIHENG Demo 后缀。
- 默认每页固定 20 人，表头和首列保持冻结。

---

### Task 1: 建立唯一正式部门映射

**Files:**
- Create: `rayher_hr_payroll/department_structure.py`
- Modify: `rayher_hr_payroll/importers/personnel_master.py`
- Test: `rayher_hr_payroll/tests/test_personnel_department_mapping.py`

**Interfaces:**
- Produces: `CANONICAL_DEPARTMENTS`, `DEPARTMENT_GROUPS`, `department_for_employee(name, designation, current_department)`。
- Consumes: 组织架构已确认的姓名映射。

- [ ] 扩展失败测试，覆盖光学、机械、电气、工艺、测试、系统工程、客户运营和职能团队。
- [ ] 运行 `pytest -q rayher_hr_payroll/tests/test_personnel_department_mapping.py`，确认新增断言失败。
- [ ] 实现纯映射模块并让导入器调用共同函数。
- [ ] 重跑测试，确认通过。
- [ ] 提交映射与测试。

### Task 2: 收敛部门 API 并实现安全同步

**Files:**
- Modify: `rayher_hr_payroll/api/personnel_entry.py`
- Create: `rayher_hr_payroll/department_sync.py`
- Create: `rayher_hr_payroll/tests/test_department_structure.py`

**Interfaces:**
- Consumes: `department_for_employee` 和正式部门元数据。
- Produces: `get_dept_options()` 的 `name/department_name/group_name/employee_count` 列表；`sync_active_employee_departments(dry_run=True)`。

- [ ] 写失败测试，证明 API 结果只包含正式且有人部门，且同步计划不删除 Department。
- [ ] 运行针对性测试并确认失败。
- [ ] 实现聚合 API 与 dry-run/事务同步。
- [ ] 重跑测试并提交。

### Task 3: 重做员工页部门分类

**Files:**
- Modify: `frontend/src/pages/Personnel.vue`
- Modify: `frontend/tests/personnel-source.test.js`

**Interfaces:**
- Consumes: `get_dept_options()` 的分组与人数字段。
- Produces: 四板块部门卡片、点击筛选、无空部门的下拉列表。

- [ ] 写源代码测试，检查四板块、人数、点击筛选以及现有 20 人分页/冻结行为。
- [ ] 运行 `yarn vitest run frontend/tests/personnel-source.test.js` 并确认新增断言失败。
- [ ] 实现紧凑部门卡片并保持表格布局。
- [ ] 重跑前端测试并提交。

### Task 4: 本地同步与回归验收

**Files:**
- Modify: `rayher_hr_payroll/public/frontend/**`
- Modify: `rayher_hr_payroll/www/rayher.html`

**Interfaces:**
- Consumes: 前三项已通过测试的代码。
- Produces: 本地站点已同步部门数据和构建资源。

- [ ] dry-run 输出 79 名在职员工的变更计划与未识别列表，未识别必须为 0。
- [ ] 导出姓名-原部门快照后执行本地同步；查询验证 84 人均在正式部门。
- [ ] 运行后端测试、前端测试和 `yarn build`。
- [ ] 清缓存并用浏览器验证部门卡片、人数、分页、冻结列和社保七月流程。
- [ ] 检查控制台错误、可见 QIHENG Demo 文案和 Git 差异后提交生成资源。