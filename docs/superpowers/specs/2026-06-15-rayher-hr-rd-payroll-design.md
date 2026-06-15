# Rayher 人事、研发工时、薪酬一体化系统设计

日期：2026-06-15

## 1. 背景与目标

Rayher 需要建设一套内部自用的信息化系统，将人事主数据、研发工时、费用分摊、薪酬核算和日常审批放在同一个平台中。目标是让数据从人力侧产生后，自动流向研发工时和薪酬核算模块，减少人工重复录入、Excel 汇总和跨部门传递错误。

第一版必须同时覆盖两组需求：

1. 现有 HTML 原型中的核算链路：人事信息、研发人员台账、研发工时、研发工时表、财务费用导入、研发费用分摊、宿舍费用代扣、月末工资计算表、数据看板。
2. 原始 6 条管理需求：请假、出差、加班、调休、报销、日常审批；员工和管理账号；审批提醒；入职离职；员工信息表；职位变动。

第一版定位为 Rayher 内部自用，覆盖约 50-200 人、多部门、多项目场景。暂不做 SaaS 多租户、银行自动发薪、税务自动申报、社保公积金自动申报和完整研发管理平台。

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
| Frappe HR | 员工、请假、出差、加班、调休、报销、入职、离职、调岗、晋升、薪酬基础 |
| rayher_hr_payroll | 中国化员工字段、Rayher 归档规则、考勤导入、宿舍代扣、研发费用分摊、工资核算表、员工简化入口 |

不直接修改 Frappe、ERPNext、Frappe HR 核心代码。`erpnext_china` 只作为参考，吸收员工中国化字段、劳动合同、岗位层级、身份证解析、社保公积金字段和企业微信思路，重写进 Rayher 自定义 App。

## 3. 第一版范围

第一版必须做：

1. 员工主档与中国化字段。
2. 员工入职、离职、职位变动。
3. 请假、出差、加班、调休、报销、日常审批。
4. 员工账号、主管账号、HR、财务、薪酬管理员、项目负责人、系统管理员权限。
5. 审批待办和提醒。
6. ERPNext 项目、任务、工时。
7. 研发人员台账自动归集。
8. 研发工时填报与工时汇总表。
9. 财务研发费用导入。
10. 研发费用按工时比例分摊。
11. 宿舍房租、水费、电费代扣。
12. 考勤 Excel 导入。
13. 半自动工资核算表。
14. HR/财务复核工资。
15. 薪资条和工资表导出。
16. 数据看板和关键报表。

第一版暂不做：

1. SaaS 多租户。
2. 对外客户开通、授权、计费。
3. 完整研发需求池、Sprint、Release、GitHub/GitLab 自动同步。
4. 银行自动发薪。
5. 税务自动申报。
6. 社保公积金自动申报。
7. IT、行政、资产、邮箱、代码仓库权限自动联动。
8. 完整移动 App 自研。
9. 完整中国财务税控、电子发票、金税接口。
10. 可视化拖拽流程引擎。

## 4. 标准模块与自定义模块

优先使用 Frappe/ERPNext/Frappe HR 标准对象：

| 领域 | 标准对象 |
|---|---|
| 员工主档 | Employee |
| 入职 | Employee Onboarding |
| 离职 | Employee Separation |
| 职位变动 | Employee Transfer / Employee Promotion |
| 请假 | Leave Application |
| 出差 | Travel Request |
| 加班 | Overtime |
| 调休 | Compensatory Leave Request |
| 报销 | Expense Claim |
| 项目 | Project |
| 任务 | Task |
| 工时 | Timesheet |
| 薪酬 | Payroll Entry / Salary Slip / Salary Component / Salary Structure Assignment |
| 临时补扣款 | Additional Salary |
| 审批 | Workflow |
| 提醒 | Notification / Assignment Rule |
| 导入导出 | Data Import / Data Export |

Rayher 自定义 App 补充对象：

| 自定义对象 | 作用 |
|---|---|
| Employee 中国化字段 | 身份证号、学历、毕业院校、专业、民族、政治面貌、户籍/籍贯、合同信息 |
| Employee Archive Status | 员工信息完整性、待确认、已归档状态 |
| Accommodation Deduction | 宿舍房租、水费、电费，进入工资扣款 |
| Attendance Import Batch | 考勤 Excel 导入批次 |
| Attendance Import Row | 员工月度考勤明细 |
| R&D Expense Import | 财务研发费用导入批次 |
| R&D Expense Item | 设备折旧、研发材料、水电、外购服务等费用项 |
| R&D Cost Allocation | 按项目工时比例生成费用分摊结果 |
| Payroll Calculation Sheet | 月度工资核算总表 |
| Payroll Calculation Line | 每个员工一行工资明细 |
| General Approval Request | 非标准日常审批 |

## 5. HTML 原型映射

HTML 原型中的功能全部进入第一版。

| HTML 功能 | 实现方式 |
|---|---|
| 会计期间切换 | Payroll Period / 自定义月度核算期间 |
| 数据看板 | Workspace、Number Card、Dashboard、Script Report |
| 人事信息管理 | Employee + 中国化字段 |
| 信息完整后确认归档 | Employee 归档状态或 Workflow |
| 研发部员工自动进入研发台账 | 自定义研发人员台账报表，按部门、状态、归档过滤 |
| 宿舍房租/水费/电费代扣 | Accommodation Deduction + Additional Salary / Salary Component |
| 研发工时填报 | ERPNext Timesheet，关联 Project / Task |
| 研发工时表 | 基于 Timesheet 的人员 x 项目 Script Report |
| 财务研发费用导入 | Data Import + R&D Expense Import / Item |
| 按工时分配率分摊研发费用 | R&D Cost Allocation 自定义计算 |
| 月末工资计算表 | Payroll Calculation Sheet / Line |
| 工资表导出 | Data Export 或自定义导出模板 |

正式系统不采用 HTML 中“删除员工并级联删除相关记录”的行为。员工离职后应保留历史，只更新状态并归档。

## 6. 原始 6 条需求映射

| 需求 | 第一版处理 |
|---|---|
| 请假、出差、加班、调休、报销、日常审批整合 | Frappe HR 标准单据 + General Approval Request + Workflow |
| 员工个人账号、管理人员账号 | User + Role + User Permission |
| 审批提醒 | Assignment Rule + Notification，第一版站内和邮件，后续接企微/钉钉/飞书 |
| 入职、离职信息维护 | Employee Onboarding / Employee Separation |
| 员工信息表 | Employee + 中国化字段；所有入职过员工保留历史 |
| 职位变动 | Employee Transfer / Employee Promotion + Salary Structure Assignment |

## 7. 角色与权限

| 角色 | 权限 |
|---|---|
| 员工 | 查看个人信息，提交申请，填报本人工时，查看本人薪资条 |
| 直属主管 | 审批下属申请，查看下属工时和团队待办 |
| 项目负责人 | 审核项目/任务工时，查看项目工时和项目成本 |
| HR | 维护员工主档、入职、离职、职位变动、假勤规则、部分薪酬基础数据 |
| 财务 | 导入研发费用，维护报销，查看费用分摊，参与工资复核 |
| 薪酬管理员 | 维护薪资结构，生成工资核算表，复核工资，生成薪资条 |
| 系统管理员 | 用户、角色、权限、流程、基础配置 |

员工端使用 Employee Portal、Web Form 或 Frappe HR Mobile/PWA。管理端使用 Frappe Desk / Workspace。

敏感字段需要限制权限和保留审计：

```text
身份证号
家庭住址/户籍信息
薪资
社保公积金
个税
银行卡
劳动合同附件
薪资条
```

## 8. 核心流程

### 8.1 入职流程

```text
HR 新建 Employee
-> 补充身份证、学历、院校、专业、部门、岗位、上级、薪资结构
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

覆盖请假、出差、加班、调休、报销和日常审批。待办由 Assignment Rule 生成，提醒由 Notification 发送。

### 8.3 研发工时流程

```text
员工进入我的工时
-> 选择项目 Project
-> 选择任务 Task
-> 填写日期、工时、说明
-> 项目负责人审核
-> 生成/提交 Timesheet
-> 汇总研发工时表
-> 计算各项目工时占比
```

第一版先使用 ERPNext 原生 Project、Task、Timesheet、看板、甘特、日历、里程碑、任务依赖和项目成本能力。暂不做完整需求池、Sprint、Release、Git 提交联动。

### 8.4 研发费用分摊流程

```text
财务导入研发费用
-> 系统读取本期项目工时占比
-> 计算项目分摊额 = 费用金额 x 项目工时占比
-> 生成研发费用分摊表
-> 项目成本报表查看
```

费用项包括设备折旧、研发材料、场地水电、第三方测试服务、外购服务等。分摊结果第一版先作为管理报表和项目成本依据；是否自动生成财务凭证作为后续增强。

### 8.5 宿舍费用流程

```text
HR / 财务登记员工本期房租、水费、电费
-> 形成 Accommodation Deduction
-> 月末生成工资核算表时进入扣款项
```

### 8.6 职位变动流程

第一版采用 B 级：记录历史 + 生效更新。

```text
HR 创建 Employee Transfer / Promotion
-> 主管 / HR 审批
-> 设置生效日期
-> 生效时更新员工部门、岗位、上级、职级、成本中心
-> 如影响薪资，创建新的 Salary Structure Assignment
-> 保留变动历史
```

不在第一版做 IT、行政、资产、代码仓库权限的自动联动。

## 9. 半自动薪酬设计

第一版薪酬采用半自动：

```text
系统自动汇总数据
-> 系统自动计算工资核算表
-> HR / 财务人工复核
-> 确认后生成薪资条 / 导出工资表
```

薪酬数据来源：

| 来源 | 作用 |
|---|---|
| Employee | 员工、部门、岗位、状态、成本中心 |
| Salary Structure Assignment | 基本工资、岗位/职级工资、薪资生效日期 |
| Attendance Import | 出勤、迟到、早退、缺勤 |
| Leave Application | 请假扣款、带薪假统计 |
| Overtime | 加班工资或加班补贴 |
| Compensatory Leave Request | 调休抵扣 |
| Expense Claim | 报销金额，单独列示 |
| Accommodation Deduction | 宿舍房租、水费、电费扣款 |
| Timesheet | 项目工时、工时补贴、研发成本归集 |
| Employee Transfer / Promotion | 部门、岗位、职级、成本中心、薪资变动 |

工资核算表每个员工每月一行，字段包括：

```text
员工
部门
岗位
工资期间
基本工资
岗位/职级工资
加班工资
工时补贴/项目补贴
请假扣款
缺勤扣款
社保个人部分
公积金个人部分
个税
宿舍代扣
其他补扣
报销金额
应发工资
应扣合计
实发工资
复核状态
异常提示
```

计算口径：

```text
应发工资 =
基本工资
+ 岗位/职级工资
+ 加班工资
+ 工时补贴/项目补贴
+ 其他补发

应扣合计 =
请假扣款
+ 缺勤扣款
+ 社保个人部分
+ 公积金个人部分
+ 个税
+ 宿舍代扣
+ 其他扣款

实发工资 =
应发工资 - 应扣合计 + 报销金额
```

报销金额第一版可列入工资表但单独标识，是否合并发放按 Rayher 实际制度配置。

工资表状态：

```text
草稿
-> 已生成
-> HR复核中
-> 财务复核中
-> 已确认
-> 已生成薪资条 / 已导出
```

确认后的工资期间应锁定。除管理员授权外，不允许修改影响本期工资的源数据。

第一版异常检查：

```text
身份证号缺失
银行卡/工资发放信息缺失
薪资结构缺失
考勤数据缺失
社保公积金参数缺失
实发工资为负
本月实发相比上月波动过大
员工已离职但仍生成工资
入职/离职当月未按天折算
```

## 10. 后续增强

第二阶段以后再考虑：

1. 企业微信、钉钉、飞书提醒和审批入口。
2. 考勤接口自动同步。
3. 银行发薪文件或银行接口。
4. 更复杂的个税、社保、公积金规则。
5. 完整研发需求池、Sprint、版本管理。
6. GitHub/GitLab webhook 自动同步。
7. IT、行政、资产、邮箱、代码仓库权限联动。
8. 财务凭证自动生成和更深 ERP 财务闭环。

## 11. 决策结论

第一版采用 Frappe/ERPNext/Frappe HR 标准能力为主体，用 `rayher_hr_payroll` 补齐 Rayher 内部管理规则和 HTML 原型中的研发费用分摊、宿舍代扣、工资核算链路。

该方案能覆盖 HTML 原型全部内容，也能覆盖原始 6 条管理需求。Frappe 原生覆盖约 60%-70%，剩余 30%-40% 通过自定义 App 实现。
