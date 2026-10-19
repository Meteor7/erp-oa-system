# QIHENG Demo 人事、研发工时、研发费用分摊系统设计

日期：2026-06-15
版本：v2

> v2 范围调整：经确认，**工资核算不在本系统内做**。工资目前由财务在现有财务系统中手工核算并记账；本系统负责人事、研发工时与研发费用分摊，并导入财务导出的研发支出总账按工时占比分摊到项目。原 v1 的“半自动薪酬核算”整章移出本版（见第 9 节与第 10 节）。

## 1. 背景与目标

QIHENG Demo 需要建设一套内部自用的信息化系统，统一管理人事主数据、研发工时、研发费用分摊和日常审批，减少人工重复录入、Excel 汇总和跨部门传递错误。

重要范围界定：

- **本系统不计算工资。** 工资由财务在现有财务系统中手工核算并记账。
- 本系统把人事、请假/出差/加班/调休/报销/审批、研发工时管理起来，**作为财务手工算工资的数据来源**（可导出）。
- 财务算完工资、记账后，把**研发支出总账（按会计科目）导出，回灌本系统**，由系统按项目工时占比生成研发费用分摊表。

第一版定位为 QIHENG Demo 内部自用，覆盖约 50-200 人、多部门、多项目场景。暂不做 SaaS 多租户、银行自动发薪、税务自动申报、社保公积金自动申报、工资核算和完整研发管理平台。

第一版覆盖两组需求：

1. 原始 6 条管理需求：请假、出差、加班、调休、报销、日常审批；员工和管理账号；审批提醒；入职演示员工166；员工信息表；职位变动。
2. 研发链路：研发人员台账、研发工时填报、研发工时汇总表、财务研发支出导入、研发费用按工时分摊、数据看板。

HTML 原型中的**工资核算表、薪资条、工资表导出不在本版**（属财务系统职责，见第 5 节）。

## 2. 技术路线

采用方案 2：

```text
Frappe Framework
  + ERPNext
  + Frappe HR
  + rayher_hr_payroll 自定义 App
```

各层职责如下：

| 层 | 职责 |
|---|---|
| Frappe Framework | 用户、角色、权限、DocType、Workflow、Notification、Assignment、API、后台任务 |
| ERPNext | 项目、任务、Timesheet、成本中心、项目成本、基础财务对象 |
| Frappe HR | 员工、请假、出差、加班、调休、报销、入职、演示员工166、调岗、晋升 |
| rayher_hr_payroll | 中国化员工字段、QIHENG Demo 归档规则、宿舍费用登记、研发支出导入与按工时分摊、研发人员台账、员工简化入口 |

不直接修改 Frappe、ERPNext、Frappe HR 核心代码。

关于 `erpnext_china`：核实其实际功能仅为**身份证解析、性别/年龄/籍贯自动带出、企业微信登录、中国行政区划、命名规范与翻译**，**不包含社保、公积金、个税、加班、调休、考勤、薪酬组件**。因此本系统只参考其身份证解析与企业微信思路；社保/公积金/个税等若将来需要，均须自建（见第 10 节）。

Frappe/ERPNext 原生的薪酬引擎（Salary Slip、Salary Structure、Payroll Entry 等）本版**不启用，但保留待将来扩展**（见第 9、10 节的预留接口）。

## 3. 第一版范围

第一版必须做：

1. 员工主档与中国化字段。
2. 员工入职、演示员工166、职位变动。
3. 请假、出差、加班、调休、报销、日常审批。
4. 员工账号、主管账号、HR、财务、项目负责人、系统演示员工170权限。
5. 审批待办和提醒。
6. ERPNext 项目、任务、工时。
7. 研发人员台账自动归集。
8. 研发工时填报与工时汇总表。
9. 财务研发支出导入（按会计科目，六大归集类）。
10. 研发支出按工时占比分摊（支持资本化/费用化/全部筛选）。
11. 宿舍房租、水费、电费**登记并导出给财务**（本系统不进工资，仅集中数据）。
12. 数据看板和关键报表。

第一版暂不做：

1. **工资核算、工资复核、薪资条、工资表导出**（留财务系统手工完成）。
2. **考勤 Excel 导入**（占比走口径 A 不需要；本版无工资亦用不上。如将来要做“填报工时不超过实际出勤”的强校验或工资，再启用，落标准 Attendance）。
3. 社保、公积金、个税计算。
4. 银行自动发薪、税务自动申报、社保公积金自动申报。
5. SaaS 多租户、对外客户开通/授权/计费。
6. 完整研发需求池、Sprint、Release、GitHub/GitLab 自动同步。
7. IT、行政、资产、邮箱、代码仓库权限自动联动。
8. 完整移动 App 自研、金税/电子发票接口、可视化拖拽流程引擎。

## 4. 标准模块与自定义模块

优先使用 Frappe/ERPNext/Frappe HR 标准对象：

| 领域 | 标准对象 |
|---|---|
| 员工主档 | Employee |
| 入职 | Employee Onboarding |
| 演示员工166 | Employee Separation |
| 职位变动 | Employee Transfer / Employee Promotion |
| 请假 | Leave Application |
| 出差 | Travel Request（+ Travel Itinerary） |
| 加班 | Overtime Slip / Overtime Type（+ Shift Type） |
| 调休 | Compensatory Leave Request |
| 报销 | Expense Claim（+ Employee Advance 预支） |
| 项目 | Project |
| 任务 | Task |
| 工时 | Timesheet / Timesheet Detail |
| 审批 | Workflow |
| 提醒 | Notification / Assignment Rule |
| 导入导出 | Data Import / Data Export |

> 注：加班的真实对象是 Overtime Slip / Overtime Type + Shift Type（提交后生成 Additional Salary），不是单一 “Overtime” DocType。本版加班只做**审批与工时记录**，加班费金额由财务核算。

QIHENG Demo 自定义 App 补充对象：

| 自定义对象 | 作用 |
|---|---|
| Employee 中国化字段 | 身份证号、学历、毕业院校、专业、民族、政治面貌、户籍/籍贯、演示员工116信息；**预留薪资基数、银行卡字段（本版空置，为将来工资模块预留）** |
| Employee Archive Status | 员工信息完整性、待确认、已归档状态 |
| Project 研发字段 | 研发项目编号、项目负责人、分管领导、是否允许填工时、资本化开始日期、资本化结束日期 |
| Accommodation Deduction | 宿舍房租、水费、电费**登记**，导出给财务；**按可转 Additional Salary 的形态存储，为将来工资模块预留** |
| R&D Expense Import | 财务研发支出 GL 导入批次（凭证号、1-4 级会计科目、期间、金额、来源文件哈希）；同一期间重复导入必须被拦截或生成更正批次。 |
| R&D Expense Item | 研发支出费用行，覆盖加计扣除六大归集类；每行保存 `source_row_key`（期间 + 凭证号 + 科目 + 金额 + 行号/来源哈希），防止同期间重复导入。 |
| R&D Cost Allocation | 按项目工时占比生成分摊结果（会计科目 × 项目）；提交后作为一个不可覆盖的计算版本。 |
| R&D Cost Allocation Line | 每条费用 × 每个项目的分摊额。 |
| R&D Allocation Source Hour Snapshot | 分摊时使用的 Timesheet 明细快照，保存员工、项目、日期、小时、部门/岗位历史口径、来源 Timesheet 行。 |
| R&D Allocation Source Expense Snapshot | 分摊时使用的 GL 费用行快照，保存凭证号、科目、金额、直接归集项目、来源行键。 |
| RD Period Lock | 研发月结锁定对象，锁 Timesheet、GL 导入、项目阶段和分摊版本；不依赖 ERPNext Accounting Period。 |
| General Approval Request | 非标准日常审批。 |
| RD Work Ratio Snapshot | 月度个人研发工时占比快照：研发人员认定留痕（详见 §4.1）。 |
| Project 证据子表 | 立项书、预算、测试报告、结项报告、IP/专利/软著等研发证据附件（详见 §4.1）。 |

> R&D Cost Allocation 另含分摊依据 `allocation_basis` 与计算版本号字段，Project 另含资本化阶段 `rd_stage`，均详见 §4.1。

不再设置 Payroll Calculation Sheet / Line、Salary Slip / Payroll Entry / Salary Component / Salary Structure Assignment / Additional Salary 等工资核算对象（本版工资不在系统内）。考勤导入对象（Attendance Import Batch/Row）移至后续增强。

### 4.1 页面落点与后端存储设计

以下 8 项不集中塞进一个页面，而是按业务归属放在 Employee、Project、Timesheet、研发费用分摊单和报表中；最终通过报表串成审计/上市/加计扣除需要的口径。

| 信息项 | 放在哪个页面 / DocType | 实现方式 | 后端存储 |
|---|---|---|---|
| 研发人员类型：全时 / 非全时 / 非研发 | Employee 员工主档 | 在 Employee 增加自定义字段 `rd_personnel_type`。建议选项：全时研发、非全时研发、非研发、研发辅助。 | 存在 `tabEmployee` 的自定义字段列中。 |
| 个人研发工时占比（研发人员认定） | 月度研发人员认定报表 | 这是个人口径，用于判断全时/非全时研发人员，不用于切费用。第一版不导入考勤，因此公式改为：个人当期研发项目 Timesheet 工时 / 个人当期全部已提交 Timesheet 工时。它是填报口径，不等同于考勤口径；待后续接入 Attendance / Employee Checkin 后，再扩展为考勤口径。 | 原始工时存在 `tabTimesheet` / `tabTimesheet Detail`；月度快照存在 `tabRD Work Ratio Snapshot`，字段使用 `total_submitted_timesheet_hours`、`rd_project_hours`、`rd_ratio`。 |
| 项目资本化/费用化阶段 | Project 项目页面 | Project 增加 `rd_stage` 字段；显式填写的 `rd_stage`（资本化/费用化）优先，只有为空或"未判定"时才按期间是否落入起止日期判断（2026-09-29 更正：起止日期在页面上是立项/结项时间，不能盖过显式阶段）。国内分摊和境外研发用同一规则。该状态只用于项目分摊额的事后分组/小计，不改变统一分摊分母。 | 存在 `tabProject` 自定义字段。 |
| 资本化起止日期 | Project 项目页面 | Project 增加 `capitalization_start_date`、`capitalization_end_date`。 | 存在 `tabProject` 自定义字段。 |
| 费用分摊依据 | 研发费用分摊单 | 自定义 DocType `R&D Cost Allocation` 增加 `allocation_basis`。第一版默认按研发项目工时占比，后续可扩展面积、设备使用时长、直接指定项目。 | 主表存在 `tabR&D Cost Allocation`；明细存在 `tabR&D Cost Allocation Line`。 |
| 分摊计算版本 | 研发费用分摊单 | 每个期间、筛选口径、计算时间生成一个版本号；提交后锁定。如需重算，取消旧版本或生成新版本，保留差异。 | 版本号存在 `tabR&D Cost Allocation`；Frappe Document Version 记录修改历史。 |
| 研发支出辅助账 | 报表页面 | 不作为手填单据，而是由项目、工时快照、财务 GL 导入快照、分摊结果汇总生成 Script Report / Query Report，可导出 Excel。 | 已提交分摊版本从 `tabR&D Allocation Source Hour Snapshot`、`tabR&D Allocation Source Expense Snapshot`、`tabR&D Cost Allocation Line` 读取；草稿预览才允许实时读源表。 |
| 项目证据附件 | Project 项目页面 + 项目证据子表 | Project 增加证据清单子表，挂立项书、预算、测试报告、结项报告、IP/专利/软著、资本化依据等附件。 | 文件元数据存在 `tabFile`；实际文件存在站点目录下的 `private/files` 或 `public/files`。研发证据默认用私密附件。 |

附件存储规则：

- Frappe 的每个业务页面本质是一个 DocType，数据存数据库表，例如 Employee -> `tabEmployee`，Project -> `tabProject`，Timesheet -> `tabTimesheet`。
- 附件不会直接塞进业务表。上传后会生成一条 `File` 记录，里面保存文件名、URL、是否私密、挂在哪个 DocType/哪条单据上。
- 实际文件落服务器磁盘：公开文件在 `sites/<site>/public/files`，私密文件在 `sites/<site>/private/files`。
- 研发项目证据、演示员工116、身份证、员工敏感附件默认必须使用 Private File；访问时依赖登录用户权限，不给普通员工开放。
- 第一版不要求对象存储，使用 Frappe 默认本地文件目录。后续如附件量很大，S3/MinIO 不是核心开关，需要评估第三方 App（如外部存储插件）或自研存储适配；业务表结构通常不需要重做。

## 5. HTML 原型映射

| HTML 功能 | 本版实现方式 |
|---|---|
| 会计期间切换 | 自定义 RD Period Lock / 研发月结期间 |
| 数据看板 | Workspace、Number Card、Dashboard、Script Report |
| 人事信息管理 | Employee + 中国化字段 |
| 信息完整后确认归档 | Employee 归档状态或 Workflow |
| 研发部员工自动进入研发台账 | 自定义研发人员台账报表，按部门、状态、归档过滤 |
| 研发工时填报 | ERPNext Timesheet，关联 Project / Task |
| 研发工时表 | 基于 Timesheet 的人员 x 项目 Script Report |
| 财务研发支出导入 | Data Import + R&D Expense Import / Item（六大类，含人员人工费用） |
| 按工时分配率分摊研发费用 | R&D Cost Allocation 自定义计算 |
| 宿舍房租/水费/电费代扣 | Accommodation Deduction 登记 + 导出给财务（本版不进工资） |
| **月末工资计算表** | **不在本版**，由财务在财务系统手工核算 |
| **工资表导出 / 薪资条** | **不在本版**，由财务系统输出 |

诚实说明：本版**不覆盖 HTML 原型的工资核算表与薪资条**部分，这部分留在财务系统。其余 HTML 功能进入第一版。

正式系统不采用 HTML 中“删除员工并级联删除相关记录”的行为。员工演示员工166后保留历史，只更新状态并归档。

## 6. 原始 6 条需求映射

| 需求 | 第一版处理 |
|---|---|
| 请假、出差、加班、调休、报销、日常审批整合 | Frappe HR 标准单据 + General Approval Request + Workflow |
| 员工个人账号、管理人员账号 | User + Role + User Permission；员工端 ESS 自助门户 |
| 审批提醒 | Assignment Rule + Notification，第一版站内和邮件，后续接企微/钉钉/飞书 |
| 入职、演示员工166信息维护 | Employee Onboarding / Employee Separation |
| 员工信息表 | Employee + 中国化字段；所有入职过员工保留历史 |
| 职位变动 | Employee Transfer / Employee Promotion |

补充说明：

- **出差 ↔ 报销串接**：Travel Request 只是出差申请 + 行程 + 预估费用，不出报销款。需预支时勾 Travel Advance Required 生成 Employee Advance；出差结束开 Expense Claim 实报实销，并关联 Employee Advance 自动冲抵预支。在 Expense Claim 上加自定义 Link 字段“关联出差申请”，保证可追溯。
- **调休（加班三分类规则）**：按《劳动法》第 44 条区分加班类型——工作日延时加班付 150%、不可调休替代；休息日加班优先补休、不补休付 200%；法定节假日加班付 300%、不可调休替代。补休用 Compensatory Leave Request，但 Frappe HR 原生只看 Holiday List + Present，可能放行法定节假日补休；因此必须加自定义校验，明确拦截“法定节假日加班换调休”。Overtime Type 按三类配置倍率，本版只做审批与记录，金额由财务核算。由于本版不导入考勤，补休依赖的“当天考勤 Present”由 HR 在批准补休时手工确认或按加班单核对。
- **职位变动运营点**：采用 Frappe 默认行为（同一工号 + 生效日更新 + 留 Internal Work History / Employee Internal Work History）。**禁用/隐藏 "Create New Employee" 勾选**，保证一人一档贯穿历史（需求 5）。注意变动是提交时应用而非到生效日自动应用，需在生效日当天提交或加定时任务。历史月份研发台账必须按 `Employee Internal Work History` 的日期区间取部门/岗位，不能读实时 `Employee.department`。

## 7. 角色与权限

| 角色 | 权限 |
|---|---|
| 员工 | 查看个人信息，提交申请，填报本人工时 |
| 直属主管 | 审批下属申请，查看下属工时和团队待办 |
| 项目负责人 | 审核项目/任务工时，查看项目工时和项目成本 |
| HR | 维护员工主档、入职、演示员工166、职位变动、假勤规则 |
| 财务 | 导入研发支出 GL，维护报销，登记宿舍费用，生成/查看研发费用分摊 |
| 系统演示员工170 | 用户、角色、权限、流程、基础配置 |

不再设“薪酬演示员工170”角色（工资不在本系统）。

员工端使用 Employee Portal / Web Form / Frappe HR Mobile/PWA。管理端使用 Frappe Desk / Workspace。

敏感字段需要限制权限和保留审计：

```text
身份证号
家庭住址/户籍信息
劳动演示员工116附件
```

> 注：Frappe 字段级权限（permlevel）可限制读写，document version 可审计“修改”，但**不原生审计“查看”**。如需访问审计需自建。

## 8. 核心流程

### 8.1 入职流程

```text
HR 新建 Employee
-> 补充身份证、学历、院校、专业、部门、岗位、上级
-> 创建员工账号 User
-> 触发 Employee Onboarding
-> 员工信息确认
-> HR 确认归档
-> 进入对应部门台账
```

如果员工属于研发部，且信息完整、状态有效、HR 已确认归档，则自动进入研发人员台账，可填报项目/任务工时。

### 8.2 统一审批流程

```text
员工提交
-> 直属主管审批
-> HR / 财务 / 项目负责人复核，按申请类型决定
-> 通过 / 驳回 / 退回修改
```

覆盖请假、出差、加班、调休、报销和日常审批。出差结束后由出差申请引出报销（Expense Claim，关联出差单与预支）。待办由 Assignment Rule 生成，提醒由 Notification 发送。

### 8.3 研发工时流程

```text
研发人员进入“我的工时”
-> 选择项目 Project（仅“允许填工时”的研发项目）
-> 选择任务 Task（可选）
-> 按天填写日期、工时、说明（一人可填多个项目）
-> 项目负责人审核（通过自定义派单逻辑按项目负责人路由）
-> 提交 Timesheet
-> 汇总研发工时表
-> 计算各项目工时占比
```

项目工时占比口径（口径 A，用于研发费用分摊）：

```text
项目工时占比 = 该研发项目当期已提交研发 Timesheet 工时 / 当期全部参与分摊研发项目的已提交研发 Timesheet 工时之和
```

- **加班、请假通过 Timesheet 实填工时自然反映**：加班那天在项目上多填即计入，请假当天不填即减少。第一版不把 Overtime Slip 自动折算进分母，因为 Frappe HR 的加班计算依赖考勤打卡和 Attendance；本版以已提交 Timesheet 作为唯一计算源。
- **占比只在研发台账这个圈内算**：分子分母都只取研发台账中的研发人员、在研发项目上填报的工时。非研发人员、非研发项目的工时系统里也有，但一律排除在分母外。默认按研发台账的人划圈——借调帮忙的非研发人员工时不计入研发分摊；如需改为按研发项目划圈（谁在研发项目上干都算），再调整。
- **标准日工时需要自定义配置**：Frappe HR 的 Shift Type 不是一个可直接读取的标准日工时标量。第一版新增公司级配置 `standard_daily_hours`，用于缺填/超填告警；如需做标准工时 - 请假 + 加班的硬上限，加班部分必须来自已审批加班单或主管例外确认，不能假设系统已从考勤自动算出。

项目负责人审核是本项目的自定义工作量：Frappe Workflow 可以做状态流转和角色审批，但不原生支持“按 Timesheet 行上的 Project 自动找到项目负责人并路由审批”。第一版需要在 `rayher_hr_payroll` 中补自定义派单、提醒和提交前校验。

注意：本节“项目工时占比”只用于研发费用分摊；第 4.1 节“个人研发工时占比”用于研发人员认定（全时/非全时），两者公式和用途不同。

第一版先使用 ERPNext 原生 Project、Task、Timesheet、看板、甘特、日历、里程碑、任务依赖和项目成本能力。暂不做完整需求池、Sprint、Release、Git 提交联动。

### 8.4 研发费用分摊流程

```text
财务在财务系统记账 -> 导出研发支出总账（按会计科目）
-> R&D Expense Import 导入（凭证号 + 1-4级科目 + 期间 + 金额）
-> 系统读取本期项目工时占比，并保存 Timesheet 明细快照、GL 行快照、项目阶段快照
-> 每条费用金额 × 项目工时占比 = 各项目分摊额
-> 生成研发费用分摊表（科目 × 项目）和不可覆盖的计算版本
-> 按项目当期资本化/费用化状态汇总小计
-> 可按 资本化 / 费用化 / 全部 + 期间 查看（默认不重算占比分母）
```

要点：

- **费用来源是财务 GL 导入**（已记账、带凭证号），不是本系统计算。涵盖加计扣除六大归集类，**人员人工费用（工资/社保/公积金）也作为 GL 行导入**，与水电、折旧等同样按占比分摊。
- **GL 导入必须有业务唯一键**：Data Import 的 Insert/Upsert 不能替代 QIHENG Demo 的业务去重。`R&D Expense Import` 保存来源文件哈希；`R&D Expense Item` 保存 `source_row_key`，建议由期间、凭证号、1-4 级科目、金额、直接指定项目、来源行号/文件哈希组成。同一期间重复导入同一来源行必须报错，重导只能走更正批次或明确覆盖流程。
- **统一工时占比分摊**：经确认，QIHENG Demo 现行做法是同一组工时占比套到全部研发支出科目（含工资、专用设备折旧）。系统照此实现：分摊表 = 每行 GL 金额 × 当期占比向量，纯计算报表。
- **资本化/费用化按期间判定，但不默认重算分母**：不是 Project 上的静态属性。按《企业会计准则第 6 号—无形资产》，同一项目研究阶段费用化、开发阶段资本化，随时间切换。默认口径是：先用全部参与分摊的研发项目统一计算项目工时占比，再把每笔 GL 费用分摊到项目，最后按项目当期资本化/费用化状态求小计。筛选“资本化/费用化”只是事后分组查看，不把整笔合并 GL 重新分给资本化项目或费用化项目。只有当财务 GL 本身已经拆成“资本化-电费 / 费用化-电费”等独立费用池时，才允许各池单独计算分母。
- **可选直接归集**：对专用于单一项目的费用，允许在导入行上选“直接指定项目”而非按占比分摊（加计扣除更稳）。默认走占比。
- **其他相关费用 10% 校验（可选增值）**：加计扣除中“其他相关费用”（职工福利费、装修费等）有 10% 上限，系统可在分摊后校验并告警。
- 分摊结果第一版作为管理报表、项目成本依据与加计扣除/高新归集辅助；是否自动生成财务凭证作为后续增强。
- **可追溯且可复现**：分摊明细不仅保留凭证号 → 项目分摊额，还要保存当次计算用到的 Timesheet 明细快照、GL 行快照、项目资本化/费用化阶段快照。提交后的分摊报表从快照读取，不能再实时重算源 Timesheet；如源数据更正，生成新版本并保留差异。

### 8.5 宿舍费用流程

```text
HR / 财务登记员工本期房租、水费、电费
-> 形成 Accommodation Deduction（按可转 Additional Salary 的形态存）
-> 导出清单给财务，财务在手工算工资时扣除
```

本版宿舍费用**不进入本系统工资**（无工资模块），仅集中登记并导出。数据结构为将来工资模块预留，届时可直接转为 Additional Salary 扣款项。

### 8.6 职位变动流程

第一版采用 B 级：记录历史 + 生效更新。

```text
HR 创建 Employee Transfer / Promotion
-> 主管 / HR 审批
-> 设置生效日期（Transfer Date）
-> 在生效日当天提交，应用部门、岗位、上级、职级、成本中心变更
-> 保留变动历史（Internal Work History / Employee Internal Work History）
```

- **禁用/隐藏 "Create New Employee"**，保证一人一档贯穿历史。
- 变更是“提交时应用”，不是到生效日自动应用：需当天提交或加定时任务到日子自动提交。
- **历史月份必须查历史表**：Employee 主档上的 `department`、`designation`、`branch` 是实时字段，转岗后会覆盖当前值。研发台账、个人研发占比和分摊快照在计算过去期间时，必须按日期区间查询 `Employee Internal Work History`，并把当期部门/岗位写入快照。
- 不在第一版做 IT、行政、资产、代码仓库权限的自动联动。

### 8.7 研发工时数据质量与月结锁定

研发费用分摊的可信度取决于研发工时是否及时、完整、可复核。第一版必须把工时内控作为核心功能，而不是只做填报表单。

```text
研发人员每日/每周填报
-> 系统检查缺填、超填、非研发项目误填
-> 项目负责人复核并留痕
-> 月末 HR / 财务发起工时关账
-> 生成并提交本期工时/GL/项目阶段快照
-> 锁定当月 Timesheet、GL 导入、项目阶段和分摊版本
-> 如需补填/改填，走更正申请并生成新版本，保留原快照
```

第一版内控要求：

- **填报截止**：建议按周截止，月末关账前必须完成；超过截止日期的补填需要说明原因。
- **缺填告警**：研发台账内人员在工作日无研发工时、无请假/出差/调休记录时，生成缺填清单并提醒本人和主管。
- **超填校验**：单日项目工时合计不得超过公司配置的 `standard_daily_hours` 加已批准/已确认的加班例外；本版不依赖考勤自动加班计算，异常需主管确认。
- **项目负责人复核**：项目负责人确认“这个人确实在这个项目上做了这些工时”，复核动作要留时间、人员、意见。
- **月末锁定**：研发费用分摊生成后，锁定对应期间的 Timesheet、项目阶段和 GL 导入批次；修改需生成新版本，不覆盖旧结果。锁定必须在服务端实现，至少覆盖 Timesheet 的保存/提交/取消/删除/Amend 场景，不能只靠 Client Script 的 `validate`。
- **快照优先**：提交后的分摊单和研发辅助账从本次计算快照读取，不再实时读 `tabTimesheet Detail` 或当前 Employee 部门字段，避免后续取消/补填/转岗导致历史报表漂移。
- **改填留痕**：补填、改填、驳回、重提都要保留原因和前后差异，便于税务、审计、上市核查倒推。
- **异常报表**：至少包含缺填人员、月底集中补填、单日超 8/10/12 小时、项目负责人未复核、项目阶段缺失、资本化日期缺失。

## 9. 工资边界与数据交接

第一版**不在系统内核算工资**。工资由财务在现有财务系统中手工核算并记账。本系统与工资的关系是“供数据、收 GL”：

```text
本系统 -> 提供给财务（导出）：
  请假 / 加班 / 调休 审批结果
  宿舍费用登记
  研发工时
  （考勤——本版暂不做，将来如启用落标准 Attendance）
       |
       v
财务在财务系统手工核算工资、记账
       |
       v
财务 -> 回灌本系统（导入）：
  研发支出总账（六大类，含工资/社保/公积金），用于按工时占比分摊
```

为将来“工资模块”扩展预留的接口（本版即埋好，避免将来返工）：

- 宿舍代扣按**可转 Additional Salary** 的形态存储。
- 考勤若将来启用，落**标准 Attendance**，不建平行表。
- Employee 预留**薪资基数、银行卡**字段（本版空置）。
- 请假、加班、调休用**原生单据**，工资引擎可直接读取。
- Frappe 原生 **Salary Slip / Salary Structure / Payroll Entry 引擎保留待启用**（本版不配置）。

## 10. 后续增强

第二阶段以后再考虑（均为在现有标准件上叠加，接口已在第 9 节预留）：

1. **启用工资模块**：用 Frappe 原生 Salary Slip / Salary Structure / Payroll Entry 计算工资（含按天折算、工时进薪、加班、宿舍代扣并入）。
2. 中国个税（累计预扣法）、社保、公积金计算（ERPNext 不原生，须自建 Salary Component 公式）。
3. 考勤接口自动同步 / 考勤 Excel 导入（落标准 Attendance）。
4. 银行发薪文件或银行接口。
5. 企业微信、钉钉、飞书提醒和审批入口。
6. 完整研发需求池、Sprint、版本管理、GitHub/GitLab webhook 自动同步。
7. 研发费用分摊自动生成财务凭证、更深 ERP 财务闭环。
8. IT、行政、资产、邮箱、代码仓库权限联动。

将来“把工资搬进本系统”的主要阻力不是 Frappe 技术（引擎现成、加字段不碰核心），而是组织上**把工资从财务系统移交、并做 GL 对账**的决定。本版选择不碰工资是安全且可逆的。

## 11. 决策结论

第一版采用 Frappe/ERPNext/Frappe HR 标准能力为主体，用 `rayher_hr_payroll` 补齐 QIHENG Demo 内部管理规则、研发人员台账、研发支出导入与按工时分摊、宿舍费用登记。

范围界定：

- **HR 主线（6 条管理需求）**：基本落在 Frappe HR 标准对象上，自定义量极小（仅 General Approval Request）。
- **研发工时 + 研发费用分摊**：标准 Timesheet/Project + 自定义 R&D Expense Import / Cost Allocation；费用金额来自财务 GL 导入，按统一工时占比分摊，支持资本化/费用化按期间筛选。
- **工资核算不在本版**：留财务系统手工完成，本系统供数据、收 GL，并已预留将来扩展接口。

本版**不再声称“覆盖 HTML 原型全部内容”**：HTML 的月末工资计算表、薪资条、工资表导出移出本版。原生覆盖以 HR + 研发工时为主，自定义集中在研发费用分摊与中国化字段。

PoC 执行与验收记录见 `docs/frappe-poc-runbook.md` 和 `docs/superpowers/plans/2026-06-16-rayher-frappe-rd-cost-poc.md`。当前 PoC 的核心验收样例是 2026-01 演示分摊：GL 总额 1200.00，RD-CAP 60% / RD-EXP 40%，资本化小计 720.00，费用化小计 480.00。
