# 2026-07-06 至 2026-07-09 Rayher 研发成本管理修改记录

## Git 环境

- 仓库目录：`D:\rayher\rayher-logistics-main`
- 工作分支：`feat/rayher-rd-cost-portal-qa`
- 远端仓库：`origin https://github.com/jacquesly249-byte/rayher-logistics.git`
- Git 作者：`d2vs8pz7rj-create <d2vs8pz7rj-create@users.noreply.github.com>`
- 记录期间：2026-07-06 00:00 至 2026-07-09 23:59（Asia/Shanghai）

## 记录口径

- 2026-07-06 有一条正式提交：`90f33c6351c3ddb93a743982152cca056cbe8ec3`，提交说明为 `feat: refine Rayher R&D cost portal`。
- 2026-07-07 至 2026-07-09 的修改没有形成按日独立 commit，主要依据未提交 Git diff、文件创建/修改时间、7 月 7 日项目状态说明和 7 月 8 日原始修改记录整理。
- Git 无法严格还原未提交修改发生的每一分钟，因此 7 月 7–8 日跨日持续开发的内容按主要完成阶段归档。
- 当前工作区还包含 2026-07-13 的后续开发；审批详情、分摊看板、通用表格导出和 7 月 13 日重新构建的前端产物不计入本记录。

## 一、2026-07-06：研发成本门户基础能力完善

### 1. 导航、账号与权限

- 研发台账导航由旧的“研发人员台账”调整为“项目管理”。
- 顶部增加当前用户、角色标签和退出登录入口。
- 完善员工、部门主管、HR、财务和系统管理员的页面访问规则。
- 员工和部门主管可进入研发工时填报；财务可以查看工时数据，但写入仍受后端角色限制。
- 增加登录后首个可见页面的选择逻辑，避免用户进入无权限页面。

### 2. 项目管理

- 新增项目管理前端页面 `Projects.vue`。
- 新增项目查询、保存和停用接口 `project_entry.py`。
- 项目数据支持项目编号、项目名称、开始/结束日期、状态和研发阶段。
- 项目停用后不直接删除，而是关闭工时填报可选状态，保留历史数据。
- 增加默认项目和研发阶段初始化逻辑，为工时填报与费用分摊提供基础数据。

### 3. 研发工时填报

- 工时填报改为按日期、项目编号、项目名称、活动类型和工作内容录入。
- 前后端共同校验项目编号与项目名称，防止选择不存在或未启用的项目。
- 支持员工查看自己的数据、部门主管查看本人和直属下属，财务保持只读。
- 增加单个员工每日工时不超过 8 小时的后端校验。
- 增加所选员工的研发工时汇总和 PLM 指标展示。
- 补充 Timesheet Detail 的项目编号自定义字段及迁移回填逻辑。

### 4. 财务费用导入

- 费用增加“公共费用”和“项目费用”两种归属方式。
- 项目费用必须选择所属项目，直接进入指定项目；公共费用继续按研发工时比例分配。
- 保存费用时保留 `direct_project` 和 `allocation_type`。
- 已分摊月份需要修改费用时，支持撤销原分摊并生成替代费用导入单，避免直接篡改已提交单据。

### 5. 测试与构建产物

- 本次提交涉及 57 个文件，Git 统计为 `2767 insertions / 274 deletions`。
- 增加项目、工时、费用、权限、默认入口和自定义字段相关的前后端测试。
- 同步更新 Vue 构建产物和 `/rayher` 入口文件。

## 二、2026-07-07：审批雏形与批量导入准备

### 1. OA 审批基础结构

- 开始新增 `OA Approval Request` 和 `OA Approval Step` DocType。
- 增加 OA 审批后端入口、审批路由服务和前端 `OAApprovals.vue` 页面雏形。
- 将审批作为独立业务入口，为请假审批、费用付款/报销审批预留统一页面。
- 审批链当时仍是基础版本，正式人员、部门、部门主管和审批人关系尚未接入。

### 2. 批量导入基础

- 前端加入 `xlsx` 依赖，为 Excel 导入和导出提供基础能力。
- 新增费用批量粘贴解析工具 `expensePaste.js`，并在 7 月 8 日继续补充科目校验与页面交互。

### 3. 项目说明文档

- 生成 `rayher-project-status.html`，梳理 Frappe/ERPNext/HRMS、Vue SPA、后端 API、DocType 和研发分摊服务之间的关系。
- 记录当时的主要卡点：本机验证环境、审批路线收敛、出差/调休审批、纯人工费月份路径及非全时研发工时分母。

## 三、2026-07-08：业务模块集中完善

### 1. 审批与组织文案

- 审批入口拆分为请假审批、费用付款/报销。
- 审批相关文案由“经理”统一调整为“部门主管”。
- 继续完善 OA 审批页面、接口、审批请求和审批步骤数据结构。

### 2. 人事信息

- 人事信息增加“费用科目”，用于住宿等公共费用归集。
- 人员导入支持费用科目写入后台。
- 增加入职日期和离职日期展示。
- 取消“离职人员不导入”的规则：离职人员继续保留，离职日期为空时保持空值。
- 调整人事列表字段，配合费用科目、归档状态和应发信息展示。

### 3. 住宿费用

- 住宿页面和后端增加房间号、房租、水费、电费、合计、个人承担费用和公司承担费用。
- 明细加入房间号，支持空房仍产生费用的场景。
- 增加按人员费用科目汇总的看板，归集研发费用、管理费用、销售费用和生产成本。
- 同步扩展住宿扣款 DocType、接口和测试。

### 4. 项目与工时页面

- 项目管理页去掉“英文名”独立列，只保留项目名称。
- 按业务要求调整前两个项目名称，仅保留英文部分。
- 工时填报增加批量粘贴和 Excel 导入。
- 导入校验覆盖日期、员工、项目、单日 8 小时上限、重复行和系统已有行。
- 工时顶部看板统一按每人每天 8 小时的人天口径计算。
- 员工筛选改为输入搜索加下拉，选择后明细同步过滤。
- 工时明细和透视表加宽，数字统一保留两位小数，项目列显示更紧凑。

### 5. 财务费用导入

- 费用结构由简单费用项扩展为 1–4 级费用科目。
- 增加费用科目候选下拉、Excel 批量导入和批量粘贴解析。
- 按研发分类明细表校验科目层级，防止 2、3、4 级科目错配。
- 保留公共费用按工时比例分配、项目费用直接归属项目的处理方式。
- 委托研发/境外的 4 级费用科目加入 `Sabri费用`。
- 费用导入表格加宽，尽量完整展示各级科目和所属项目。

### 6. 研发费用分摊

- 财务和管理员可撤销本期分摊，调整工时或费用后重新计算。
- 保留期间锁逻辑，避免已分摊后继续修改源数据造成结果不一致。
- 分摊页增加资本化、费用化和未判定阶段合计。
- 增加按项目汇总的研发阶段、工时、分摊率、分摊金额和明细行数。
- 加宽分摊明细表，便于查看项目和金额。

### 7. 2026-06 分摊差异排查

- 当时生效分摊基于 `EXP-202606-0002 / ALLOC-202606-0007`。
- 生效结果为资本化 69,756.84、费用化 1,671,500.08、未判定 0.00。
- 资本化仅包含 MUSHI，是因为进入当期结果的项目中只有 `RD06 / MUSHI 7546` 属于资本化阶段。
- 旧值 85,338.21 来自已撤销分摊 `ALLOC-202606-0001/0002`，其费用来源为 `EXP-202606-0001`。
- 新旧费用导入单相差 402,119.60，共 9 行，主要是 PLANCK 和 Sabri 的委托研发/境外费用。
- 缺少的公共费用约 385,890.85，按 MUSHI 分摊率 4.037768667% 计算影响约 15,581.37，可解释 85,338.21 到 69,756.84 的差额。

### 8. 当日验证记录

- 后端测试：`260 passed`。
- 前端测试：`53 passed`。
- 前端构建：`yarn build` 通过。
- `git diff --check` 通过，仅有已有 CRLF 提示。
- 当时对关键写入文件执行 TipRay/TSD 明文头检查，未发现加密头。

## 四、2026-07-09：境外研发、分摊矩阵与 Excel 导出

### 1. 境外委托研发费用

- 新增境外研发前端页面、路由和导航入口，支持按月录入、按年只读汇总。
- 新增 `Foreign RD Expense` 和 `Foreign RD Expense Line` DocType。
- 明细记录工作日期、项目、项目编号、项目名称、活动类型、研发阶段、工时、分摊比例、公共费用分摊额、项目直接费用和合计金额。
- 新增 `foreign_rd_entry.py` 查询和保存接口，并限制为境外研发相关财务角色使用。
- 境外公共费用按工时占比分配；项目费用直接归属指定项目。
- 增加日期必须属于当前会计期间、项目必须存在且启用、活动类型和工作内容必填、单日不超过 8 小时等校验。
- 增加境外工时批量粘贴和 Excel 导入；导入格式不要求员工列，并校验项目、日期、重复项和每日工时。
- 境内与境外结果可以合并生成项目汇总和阶段汇总。

### 2. 研发费用分摊矩阵

- 分摊明细由单一费用项目扩展为凭证号、3 级费用科目、4 级费用科目和各项目金额矩阵。
- 分摊单行增加 `account_level_3` 和 `account_level_4`，优先保留最具体的费用科目。
- 对旧的已提交分摊行，可从费用快照恢复 3、4 级科目，兼容历史数据。
- 项目列增加研发阶段元数据，并在矩阵底部增加各项目合计行。
- 报表支持指定分摊单、年度汇总和最新分摊三种读取方式。
- 境外公共费用和项目直接费用纳入同一分摊矩阵。

### 3. 研发费用分摊表导出 Excel

- 新增 `allocationExport.js`，导出文件名格式为 `研发费用分摊表-<期间>.xlsx`。
- 工作簿包含 4 个工作表：阶段合计、分摊明细、资本化分摊、费用化分摊。
- 阶段合计包含资本化、费用化、资本和费用合计、未判定金额。
- 月度和年度视图均可导出当前矩阵，资本化和费用化工作表只保留对应阶段的项目列。

### 4. 测试与本地化

- 增加境外费用拆分、按工时分配、项目直接归属、日期/8 小时校验、境内外汇总和重新计算测试。
- 增加分摊矩阵 3/4 级科目、项目合计、阶段元数据、历史快照回填和境外费用并表测试。
- 增加 Excel 工作表内容和文件名测试，以及境外研发页面、批量导入、月/年视图测试。
- 更新中英文翻译模板及前端构建产物。
- 7 月 8 日原始记录中的阶段性结果显示：完成分摊表导出后，前端测试由 `53 passed` 增加到 `56 passed`；境外研发后续测试已加入仓库，但未保留 7 月 9 日结束时的完整测试总数，因此不补写未经证实的数字。

## 五、主要改动文件范围

### 2026-07-06 正式提交

- `frontend/src/App.vue`
- `frontend/src/lib/access.js`
- `frontend/src/pages/ExpenseImport.vue`
- `frontend/src/pages/Projects.vue`
- `frontend/src/pages/Timesheet.vue`
- `frontend/src/pages/TimesheetEntry.vue`
- `frontend/src/router.js`
- `rayher_hr_payroll/api/expense_entry.py`
- `rayher_hr_payroll/api/project_entry.py`
- `rayher_hr_payroll/api/timesheet_entry.py`
- `rayher_hr_payroll/custom_fields.py`
- `rayher_hr_payroll/install.py`
- `rayher_hr_payroll/project_controls.py`
- `rayher_hr_payroll/timesheet_controls.py`
- 对应的 `frontend/tests/*`、`rayher_hr_payroll/tests/*` 和前端构建产物。

### 2026-07-07 至 2026-07-08 未提交修改

- `frontend/src/lib/expenseAccounts.js`
- `frontend/src/lib/expensePaste.js`
- `frontend/src/lib/timesheetImport.js`
- `frontend/src/pages/Accommodation.vue`
- `frontend/src/pages/Allocation.vue`
- `frontend/src/pages/OAApprovals.vue`
- `frontend/src/pages/Personnel.vue`
- `rayher_hr_payroll/api/accommodation_entry.py`
- `rayher_hr_payroll/api/allocation_entry.py`
- `rayher_hr_payroll/api/oa_entry.py`
- `rayher_hr_payroll/api/personnel_entry.py`
- `rayher_hr_payroll/oa_approval.py`
- `rayher_hr_payroll/rayher_hr_payroll/doctype/accommodation_deduction/`
- `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/`
- `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_step/`
- `rayher-project-status.html`

### 2026-07-09 未提交修改

- `frontend/src/lib/allocationExport.js`
- `frontend/src/lib/foreignRdImport.js`
- `frontend/src/pages/ForeignRD.vue`
- `frontend/tests/allocation-export.test.js`
- `frontend/tests/foreign-rd-*.test.js`
- `rayher_hr_payroll/api/foreign_rd_entry.py`
- `rayher_hr_payroll/rd_cost/document_builder.py`
- `rayher_hr_payroll/rayher_hr_payroll/doctype/foreign_rd_expense/`
- `rayher_hr_payroll/rayher_hr_payroll/doctype/foreign_rd_expense_line/`
- `rayher_hr_payroll/rayher_hr_payroll/doctype/rd_cost_allocation_line/rd_cost_allocation_line.json`
- `rayher_hr_payroll/rayher_hr_payroll/report/rd_allocation_matrix/rd_allocation_matrix.py`
- `rayher_hr_payroll/tests/test_allocation_document.py`
- `rayher_hr_payroll/tests/test_foreign_rd_entry.py`
- `rayher_hr_payroll/tests/test_reports.py`
- `rayher_hr_payroll/locale/main.pot`
- `rayher_hr_payroll/locale/zh.po`
- `rayher_hr_payroll/translatable_labels.py`
- `rayher_hr_payroll/translations/zh.csv`

## 六、提交状态与后续注意事项

- 7 月 6 日修改已有正式提交；7 月 7–9 日修改截至记录结束时仍未形成独立 commit。
- 后续提交时建议按审批、人事住宿、工时导入、费用导入、境外研发、分摊报表和构建产物拆分，便于审查和回滚。
- 前端 `public/frontend/assets` 下的哈希文件属于构建产物，提交前应确认新增和删除成对对应，避免误删仍被入口引用的文件。
- 当前工作区中部分源码在 7 月 13 日又被继续编辑，不能用当前完整 diff 直接代表 7 月 6–9 日的历史状态。
- 正式部署前仍需在可用的 Frappe/bench 环境执行数据库迁移、完整后端测试、完整前端测试和生产构建。
