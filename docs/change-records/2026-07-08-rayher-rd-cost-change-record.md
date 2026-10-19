# 2026-07-08 QIHENG Demo 研发成本管理修改记录

## Git 环境

- 仓库目录：`D:\rayher\rayher-logistics-main`
- 当前分支：`feat/rayher-rd-cost-portal-qa`
- 远端仓库：`origin https://github.com/jacquesly249-byte/rayher-logistics.git`
- 说明：`D:\rayher` 根目录不是 Git 仓库，真正的 Git 仓库在 `rayher-logistics-main`。
- 状态：昨天修改目前仍是未提交状态，尚未形成单独 commit。

## 记录口径

本记录按当前未提交 Git diff、文件时间和 2026-07-08 的开发过程整理。因为昨天没有单独提交 commit，Git 无法自动严格区分每一项修改发生在哪一分钟；本文按业务模块归档。

今天 2026-07-09 新增的“研发费用分摊表导出 Excel”不计入本记录，只在备注里说明。

## 一、审批模块

- 将审批作为独立大类拆出，前端入口分为：请假审批、费用付款/报销。
- 新增 OA 审批相关前端页面与后端接口雏形：`OAApprovals.vue`、`oa_entry.py`、`oa_approval.py`、`oa_approval_request`、`oa_approval_step`。
- 文案统一：不再使用“经理”，改为“部门主管”。
- 当前审批链仍是基础版本，后续需要接入正式人员组织架构：不同员工、不同部门、不同部门主管、不同审批人。

## 二、人事信息

- 人事信息管理加入“费用科目”字段，用于后续住宿等公共费用归集。
- 导入人员信息时支持费用科目写入后台。
- 增加入职日期旁边的离职日期。
- 取消“离职人员不导入”的规则：表中离职人员也保留导入，离职日期为空则保持空。
- 人事列表展示字段调整，配合费用科目、归档状态、应发等信息。

## 三、住宿费用

- 住宿页面和后端增加住宿基础资料与费用结构：房间号、房租、水费、电费、合计、个人承担费用、公司承担费用。
- 明细表也加入房间号，支持“空房也产生费用”的场景。
- 新增按人员费用科目汇总的看板，用于汇总公司承担部分对应的费用科目：研发费用、管理费用、销售费用、生产成本。
- 后端住宿扣款 DocType 与接口同步扩展。

## 四、项目管理

- 项目管理页去掉“英文名”列，只保留项目名称。
- 前两个项目名称按要求只保留英文部分，去掉中文前缀。
- 项目名称与研发阶段继续作为工时、分摊、费用归属的基础数据。

## 五、研发工时填报与工时表

- 工时填报增加批量粘贴/Excel 导入能力。
- 导入时校验日期、员工、项目、每日 8 小时上限、重复行和已存在行。
- 工时页面顶部看板按“人天”口径修正：标准为每人每天 8 小时。
- 查看员工支持输入搜索加下拉，选择员工后明细表跟随过滤。
- 工时明细与研发工时表可视化优化：表格加宽、数字保留两位小数、透视表项目列更紧凑。

## 六、财务费用导入

- 费用导入从原来的简单费用项改为 1-4 级费用科目。
- 费用科目支持输入栏加候选下拉，后续可继续优化为输入一两个字智能匹配。
- 新增/完善 Excel 批量导入与批量粘贴解析。
- 导入校验按研发分类明细表的科目层级执行，防止 2/3/4 级科目错配。
- 保留“公共费用”和“项目费用”的归属方式：公共费用按研发工时比例分配，项目费用直接归属到所选项目。
- 委托研发/境外的 4 级费用科目中加入 `Sabri费用`。
- 费用导入宽表优化：表格加宽，1-4 级费用科目和所属项目尽量完整展示。

## 七、研发费用分摊

- 分摊逻辑支持撤销本期分摊：财务和管理员可先撤销，再调整工时或费用后重算。
- 重算分摊时保留期间锁逻辑，避免已经分摊后继续改工时导致数据不一致。
- 分摊页新增阶段合计：资本化合计、费用化合计、未判定合计。
- 分摊页新增项目汇总：按项目列出阶段、分摊工时、分摊率、分摊金额、明细行数。
- 分摊明细表加宽，方便查看项目与金额。
- 已核对 2026-06 数据：当前生效分摊基于 `EXP-202606-0002 / ALLOC-202606-0007`。

## 八、2026-06 分摊差异排查结论

- 当前 2026-06 生效分摊：资本化 69,756.84，费用化 1,671,500.08，未判定 0.00。
- 为什么资本化只有 MUSHI：当前六月进入分摊结果的项目里，只有 `RD06 / MUSHI 7546` 的研发阶段是资本化；其他资本化项目本期没有进入当前分摊结果。
- 之前看到的 85,338.21 来自已撤销旧分摊 `ALLOC-202606-0001/0002`，旧分摊基于 `EXP-202606-0001`。
- 当前导入单 `EXP-202606-0002` 比旧导入单 `EXP-202606-0001` 少 402,119.60，共 9 行，主要是委托研发/境外的 PLANCK 与 Sabri 费用。
- 缺少的公共费用部分约 385,890.85，按 MUSHI 分摊率 4.037768667% 计算，影响约 15,581.37，正好解释 85,338.21 到 69,756.84 的差额。

## 九、权限、导航和页面结构

- 左侧菜单调整：审批、人事中心、研发台账分组更清晰。
- 财务、管理员、部门主管等角色的页面可见性继续按业务权限控制。
- 高密度页面加宽：工时表、费用导入、分摊表等页面使用更宽的工作区。
- 旧的人事/研发人员台账入口隐藏，避免与当前页面重复。

## 十、测试和验证

昨天主要验证：

- 后端测试：`260 passed`
- 前端测试：当时为 `53 passed`
- 前端构建：`yarn build` 通过
- `git diff --check`：通过，仅存在已有 CRLF 提示
- 关键写入文件做过 TipRay/TSD 明文头检查，未发现加密头。

今天 2026-07-09 新增“研发费用分摊表导出 Excel”后，前端测试增加到 `56 passed`，该功能不计入本记录主体。

## 十一、主要改动文件范围

前端主要文件：

- `frontend/src/App.vue`
- `frontend/src/lib/access.js`
- `frontend/src/lib/expenseAccounts.js`
- `frontend/src/lib/expensePaste.js`
- `frontend/src/lib/timesheetImport.js`
- `frontend/src/pages/Accommodation.vue`
- `frontend/src/pages/Allocation.vue`
- `frontend/src/pages/ExpenseImport.vue`
- `frontend/src/pages/OAApprovals.vue`
- `frontend/src/pages/Personnel.vue`
- `frontend/src/pages/Projects.vue`
- `frontend/src/pages/Timesheet.vue`
- `frontend/src/pages/TimesheetEntry.vue`
- `frontend/src/router.js`

后端主要文件：

- `rayher_hr_payroll/api/accommodation_entry.py`
- `rayher_hr_payroll/api/allocation_entry.py`
- `rayher_hr_payroll/api/expense_entry.py`
- `rayher_hr_payroll/api/oa_entry.py`
- `rayher_hr_payroll/api/personnel_entry.py`
- `rayher_hr_payroll/api/project_entry.py`
- `rayher_hr_payroll/api/timesheet_entry.py`
- `rayher_hr_payroll/custom_fields.py`
- `rayher_hr_payroll/oa_approval.py`
- `rayher_hr_payroll/rayher_hr_payroll/doctype/accommodation_deduction/`
- `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/`
- `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_step/`

测试主要文件：`frontend/tests/*`、`rayher_hr_payroll/tests/*`。

## 十二、提交前注意事项

- 当前工作区还有大量未提交变更，建议在正式提交前按模块拆 commit，避免一个大提交难以回滚。
- `rayher_hr_payroll/public/frontend/assets/Inter-Italic.var-BGHziHgI.woff2` 当前在 Git 状态中显示为删除，需要在提交前确认是否为构建产物差异，避免误删字体文件。
- `rayher_hr_payroll/translations/zh.csv` 显示为二进制变更，需要确认是否符合预期。
- 组织架构与真实审批链还需要后续提供人员/部门/部门主管关系后继续完善。