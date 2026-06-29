# 研发人事·工时·薪酬 一体化平台(Serena 需求)— 设计文档

- 日期:2026-06-27
- 基线分支:`frappe-rd-cost-poc @ a1c78a2`(含全部已建科研成本系统;`main` 是其直系祖先,可纯 ff)
- 平台栈:Frappe 15.111 / ERPNext 15.111 / HRMS 15.61 / 自建 app `rayher_hr_payroll`
- 实施顺序:A — 后端先贯通,外壳最后

## 1. 背景与目标

Serena(财务,系统负责人)提出:把**人事、研发工时、薪酬核算**整合为一体化系统,
数据从人力流出后分别同步到研发与薪酬模块。六条需求:

1. 请假/出差/加班/调休/报销/日常审批,整合在一个平台
2. 分员工个人账号、管理人员账号
3. 审批流程要有提醒功能
4. 员工入职、离职信息维护
5. 员工信息表(姓名、身份证号、性别、学历、毕业院校、专业、入职部门、岗位名称;含所有入职过的员工)
6. 职位变动功能

核心策略:**不重建平台**。HRMS 已自带需求 1/4/6 的全部单据;我们只做"配置 + 与已建科研系统打通 + 最后一层好看外壳"。

## 2. 关键决策(已与用户逐条确认)

| # | 决策 | 选择 |
|---|---|---|
| Q1 | 代码基线 | 新 worktree 从 `frappe-rd-cost-poc @ a1c78a2` 拉分支 |
| Q2 | 门户形态 | **C** — 自建好看外壳 + 复用 HRMS 表单(不重写表单) |
| Q3 | 角色粒度 | **四档**:员工 / HR / 财务 / 部门经理(与科研系统同一套) |
| Q4 | 员工信息落地 | **HRMS 原生** Department / Designation / Employee Education;职位变动用 Promotion/Transfer |
| Q5 | 加班 | → 调休(Compensatory Leave),不发加班费(起步) |
| Q6 | 薪酬 | **HRMS 正式算薪**,并把真工资喂给科研系统(见 §5) |
| + | 总控账号(Serena) | Role Profile = System Manager + HR Manager + Accounts User,用官方 Desk 工作区 |
| + | 报销审批第二段 | 财务**复核确认**(不做实际付款/记账) |
| + | 入职建号 | 自动建 User 默认只挂"员工"角色;管理角色由 HR 事后手动加 |

## 3. 架构(三层,不重复造轮子)

```
① 自建外壳(P5,最后做,可砍)
   员工工作台/待办提醒 · 经理审批中心 · 快捷入口 · 我的申请
   技术:先 Frappe Workspace/Web 零编译 → 后 frappe-ui SPA(复用 /rayher 基建)
─────────────────────────────────────────────
② HRMS 原生(平台主体,现成)
   请假 出差 报销 调休 · 入职离职 · 职位变动 · Workflow 审批 · Notification 提醒
   · 正式薪酬 Salary Structure / Salary Slip / Payroll Entry
─────────────────────────────────────────────
③ 已建科研系统(a1c78a2)
   研发工时 · 费用导入 · 费用分摊 · 期间锁定 · 数据看板
   ← P4 接入真薪酬:真工资替换模拟字段 + 研发人工费进分摊
─────────────────────────────────────────────
   全部共用同一套四档角色 + 同一套员工主数据
```

HRMS(②)的员工/部门/薪酬为源头,数据同步流向科研系统(③)与外壳(①)——即 Serena 说的"数据从人力流出后分别同步"。

## 4. 角色与权限

### 4.1 四档角色映射(复用现成角色,不新造)

| 四档 | 落到的角色 | 可见范围 |
|---|---|---|
| 员工 | HRMS 内置 `Employee` | 只看自己(User↔Employee 绑定) |
| HR | `HR User` / `HR Manager` | 全员 + 身份证 PII |
| 财务 | `Accounts User` | 全员工资/费用,**不看 PII** |
| 部门经理 | Department 审批人 + 自定义 `Department Manager` 角色 | 只看本部门(审批/工时/看板) |

### 4.2 总控账号(Serena)— Frappe 官方正路

- **做法**:普通账号 + Role Profile「总控/Owner」打包 `System Manager + HR Manager + Accounts User`。
  **不使用 Administrator**(官方反模式:仅用于初装/应急)。
- **UI**:官方 Desk「工作区(Workspace)」。叠角色后左侧所有工作区自动全开;可零代码拖拽配一个"总控"工作区聚合快捷入口/指标卡/链接。
- **效果(已逐层核实)**:对 RD 费用分摊等所有页面**可看、可改、可作废**。

### 4.3 证据:总控对 RD allocation 的权限(核实自运行源码 `feat/rd-spa-period-aware`)

| 层 | 规则 | 总控是否通过 |
|---|---|---|
| 前端可见 | `access.js` `/allocation → FINANCE=[System Manager, Accounts User]` | ✅ |
| 后端接口 | `allocation_entry.py` `require_rd_access(RD_FINANCE_ROLES=("System Manager","Accounts User"))` | ✅ |
| doctype 写权限 | `RD Cost Allocation`:System Manager read/write/create/cancel/submit 全=1 | ✅(含作废) |

**有意限制**:`recalc_allocation` 受 `ensure_not_locked(period,"lock_allocations")` 约束 —— 期间锁定后任何人不可改;但总控(System Manager)可管 RD Period Lock 自行解锁。
**用法**:SPA allocation 唯一写操作是"重算";逐行手改在 Desk 的 RD Cost Allocation 表单(总控凭 System Manager 同样有完整写权)。

## 5. 科研费用来源(已核实)与 P4 薪酬打通

### 5.1 当前科研费用怎么来的(核实 `rd_cost/allocation.py`)

```
①财务费用导入(06)每条 amount + 可选 direct_project
②研发工时(04/05)每人每项目 hours + 项目资本化阶段
        └──► 研发费用分摊(07)allocate_expenses():
             · 有 direct_project → 100% 记该项目(直接费用)
             · 无 → 按工时占比分摊 amount × hours/总hours(间接费用)
             · 每笔按项目阶段归类:资本化/费用化/unknown
```

**关键事实**:`allocate_expenses` 输入只有 `expenses`(导入费用)与 `project_hours`(工时),**工资/人工费完全不参与分摊**。
消费 `rd_mock_*`(模拟工资)的只有:`dashboard_entry.py`(看板聚合)、`personnel_entry.py`(员工 CRUD)、`employee_controls.py`(校验)、`demo.py`(种子)。

### 5.2 P4 决策 = (ii) 完整版

**5.2.1 上 HRMS 正式算薪**:Salary Component → Salary Structure → Salary Structure Assignment(入职/调薪时设基本工资)→ Payroll Entry(每月批量算薪出 Salary Slip)。

**5.2.2 真工资替换模拟字段**(改科研系统代码):
| 现在 | 改成 |
|---|---|
| 看板读 `rd_mock_base/social/fund/tax`(静态) | 读该期 Salary Slip 真数 |
| 08 月末工资计算表显示模拟数 | 显示 Payroll Entry 真工资单 |
| 员工卡片手填模拟工资 + 校验 base>0 | 不再手填,薪资结构自动算 |

**5.2.3 研发人工费进分摊(新功能)**:新增一类分摊来源 = 研发人员 Salary Slip 工资 × 当期研发工时占比 → 作为"人工费"与导入费用一起进入 `allocate_expenses` 的资本化/费用化分摊。这是研发加计里最大的一块。

## 6. 实施阶段与验证标准

每阶段独立可用、独立验证;工作量重心在 P4(改科研代码)与 P5(外壳),P1-P3 以配置为主。

### P0 — worktree + 基线对齐
1. 本地 `main` ff 到 `frappe-rd-cost-poc @ a1c78a2`(纯快进,无冲突、无合并提交)。
2. 从 `frappe-rd-cost-poc` 拉新分支 `feat/serena-hr-oa`,建新 worktree(如 `E:/Rayher/Logistics-hroa`)。
3. **对齐 WSL bench**:qatest 现跑旧的 `feat/rd-spa-period-aware`(PR#7,已被 #8/#9/#10 取代);切到新基线 `a1c78a2`,确保在真 main 基线上开发/测试。
- **验证**:站点能起;现有 97 测试全绿。

### P1 — 主数据 + 四档角色 + 总控
- 配 Department / Designation / Employee Education;补全员工信息(身份证现有字段保留、仅 HR 可见)。
- 「员工信息总表」报表:姓名/身份证/性别/学历/院校/专业/部门/岗位/状态;不过滤 status → 含离职。
- 四档角色映射 + 总控 Role Profile。
- **验证**:任一员工有部门/岗位/学历;总表含在职+离职;四账号 + 总控可见范围正确(员工只见自己、HR 见 PII、财务见钱不见 PII、经理只见本部门、总控全见)。

### P2 — 申请审批 + 提醒
- 请假/出差/调休:HRMS 自带审批人(单段,转本部门经理)。
- 报销:Frappe Workflow 两段 `草稿→经理已批→财务已审→完成`(财务仅复核确认)。
- 提醒:Frappe Notification(提交→通知审批人;批/驳→通知申请人;超时催办),渠道 = 系统铃铛 + 邮件;同一份数据供 P5 外壳"待办"展示。
- **验证**:员工提交请假 → 经理收提醒 → 批准 → 员工收"已批准";报销经理批完才进入财务可见;锁定期间/越权操作被拦。

### P3 — 入职/离职/职位变动
- 入职 Employee Onboarding:完成 → 自动建 Employee + User(默认"员工"角色)+ 绑定 User↔Employee。
- 离职 Employee Separation:status=离职、停用账号、工资停发;仍保留在员工信息总表。
- 晋升 Promotion / 调岗 Transfer:更新 Designation/Department;调岗后审批路由自动改走新部门经理。
- **验证**:入职后新人能登录提申请;调岗后下一张申请走新经理;离职后账号停用但总表仍可查。

### P4 — 正式薪酬 + 科研打通(决策 ii)
- 配薪资项/结构/分配;Payroll Entry 批量算薪。
- 改科研代码:看板/08 表读 Salary Slip 真数;新增"研发人工费"分摊来源(工资×研发工时占比)。
- **验证**:跑 Payroll Entry 出真工资单;看板/08 显示真数;某研发人员人工费按其研发工时占比正确进入资本化/费用化;现有分摊测试不回归。

### P5 — 自建外壳(可砍)
- 员工工作台 + 经理审批中心(自建);HR/财务/总控用官方 Desk 工作区。
- 技术:先 Frappe Workspace/Web 零编译 → 后 frappe-ui SPA。
- **验证**:各角色看到对应界面;快捷入口能开 HRMS 表单;待办来自 P2 Notification 数据。

## 7. 范围之外(YAGNI)

- 加班费计算与发放(决策 Q5:只调休)。
- 报销实际付款/记账资金流(报销第二段仅复核)。
- 移动 App 原生开发(HRMS 自带 PWA 已移动友好)。
- 员工自助 SPA 的像素级定制(P5 先零编译,SPA 化按需后置)。

## 8. 风险 / 待办

- **基线漂移**:WSL bench 与 Windows 提交库分属不同分支(见 memory「两套分叉仓库」);P0 必须对齐到 `a1c78a2`,否则测试结果不可信。
- **P4 回归面**:改 `dashboard_entry.py` / 08 页面 / 新增人工费来源会触及科研系统核心;需补针对"真工资来源 + 人工费分摊"的测试,并跑全量 97 测试防回归。
- **Frappe 语义**:Workflow/Notification/Role Profile/Salary 的具体行为以装好的 bench 核实为准(CLAUDE.md #7),不臆断写入。
- **总控 PII**:总控账号有意越过财务 PII 隔离(经 Serena 授权),单独标记、操作可审计。

## 9. 成功标准(整体)

Serena 六条需求逐条可演示:① 四类申请一处提交+审批;② 员工/管理/总控账号分级;③ 提醒到铃铛+邮件;④ 入职离职走通且账号联动;⑤ 员工信息总表含离职全员;⑥ 职位变动改岗并自动改审批路由。叠加:真薪酬算薪 + 研发人工费进归集。
