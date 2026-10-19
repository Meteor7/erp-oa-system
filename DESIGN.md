---
name: "栖衡 QIHENG ERP / OA"
description: "深青索引导航与轻量业务面板组成的运营协作工作台。"
colors:
  primary: "#147b73"
  primary-hover: "#0e615b"
  primary-soft: "#e7f4f0"
  page: "#f2f6f5"
  surface: "#fff"
  soft: "#f4f8f6"
  heading: "#223e39"
  text: "#243a35"
  text-secondary: "#526a62"
  text-muted: "#637970"
  line: "#dce6e1"
  line-strong: "#c8d8d0"
  nav-bg: "#173e3a"
  nav-text: "#d5e8e2"
  nav-hover: "#28534b"
  nav-active-bg: "#d9efe7"
  nav-active-text: "#184b40"
  positive: "#2F7A55"
  warning: "#8A5A1C"
  danger: "#B42318"
  annual-ink: "#1f6a4d"
  annual-fill: "#e3f5ec"
  personal-chart: "#8db4ee"
  comp-chart: "#b8a6ee"
  overtime-chart: "#f4c47a"
  trip-chart: "#84cdd6"
typography:
  headline:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", sans-serif"
    fontSize: "24px"
    fontWeight: 650
    letterSpacing: "-.02em"
  headline-mobile:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", sans-serif"
    fontSize: "21px"
    fontWeight: 650
    letterSpacing: "-.02em"
  body:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", sans-serif"
    fontSize: "14px"
    lineHeight: 1.6
  table:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", sans-serif"
    fontSize: "13px"
  label:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", sans-serif"
    fontSize: "12px"
  button:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", sans-serif"
    fontSize: "13px"
  panel-title:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", sans-serif"
    fontSize: "14px"
    fontWeight: 650
  navigation:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", sans-serif"
    fontSize: "14px"
    fontWeight: 500
  record-id:
    fontFamily: "ui-monospace, \"SFMono-Regular\", Consolas, monospace"
  attendance-tag:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", sans-serif"
    fontSize: "11px"
    lineHeight: "18px"
rounded:
  field: "6px"
  button: "7px"
  navigation: "8px"
  panel: "12px"
  login-panel: "14px"
spacing:
  xs: "4px"
  sm: "8px"
  row: "10px"
  md: "12px"
  section: "14px"
  panel: "16px"
  heading: "22px"
  page: "28px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.button}"
    padding: "6px 12px"
    typography: "{typography.button}"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.surface}"
    rounded: "{rounded.button}"
    padding: "6px 12px"
    typography: "{typography.button}"
  input-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.field}"
    padding: "7px 10px"
    typography: "{typography.table}"
  nav-active:
    backgroundColor: "{colors.nav-active-bg}"
    textColor: "{colors.nav-active-text}"
    rounded: "{rounded.navigation}"
    padding: "8px"
    typography: "{typography.navigation}"
  attendance-tag-annual:
    backgroundColor: "{colors.annual-fill}"
    textColor: "{colors.annual-ink}"
    rounded: "{rounded.field}"
    padding: "0 8px"
    typography: "{typography.attendance-tag}"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "16px"
    typography: "{typography.body}"
---

# Design System: 栖衡 QIHENG ERP / OA

## Overview

**Creative North Star: "研发记录册 / The R&D Notebook"**

栖衡 QIHENG 以研发记录册的索引和对齐组织员工、审批、采购与研发记录。深青侧栏承担稳定定位，浅色主区承托列表、统计与表单；不以具象笔记本或装饰物表达隐喻。

本规范固定已实现的品牌层，并保留业务页面各自的密度与状态语义。依据当前源码以及桌面、移动和原生登录截图记录；方向种子为 41963e97，既有业务流程、权限和路由继续有效。

**Key Characteristics:**

- 深青导航、浅色工作区与青绿主要操作。
- 面板细线分区，桌面并列、窄屏堆叠。
- 考勤类别保留独立颜色，数字、日期与记录标识可扫描。

## Colors

### Primary

青绿 primary 用于主要操作、焦点和链接；primary-hover 提供通用业务按钮的悬停反馈。primary-soft 用于轻量选中与强调。

### Secondary

通用业务区保留 positive、warning、danger。考勤还区分年假、事假、病假、调休、加班、出差和其他假；frontmatter 收录代表性的复用值，完整配对以 `attendanceBoardUi.css` 的 `--ac-t-* / --ac-b-* / --ac-x-*` 为准。

### Neutral

nav-bg 承托浅字标与 nav-text，活动导航采用 nav-active-bg / nav-active-text。page 与 surface 区分工作区和面板；正文、次要文字、辅助说明与边界使用对应中性色。

**The Status Rule.** 品牌青绿表达操作与位置；考勤类型和业务状态保留各自的文字及色彩映射。

## Typography

工作区使用系统无衬线栈并启用 tabular-nums。通用业务区 body 为基础层级，表格与操作采用 table / button，说明采用 label。页面标题在桌面与窄屏分别使用 headline 与 headline-mobile；考勤面板标题对应 panel-title。单号等记录标识采用 record-id 的等宽字体，统计金额仍用正文栈。

**The Scope Rule.** 工作区、通用业务面板、考勤首页与原生登录各有作用域，局部规则优先时按局部实现记录。

品牌层主要覆盖 `.qh-workspace .xp` 与考勤 `.xp.at .acx`。本文件记录浅色评审状态；考勤源码仍存在系统偏好与显式 data-theme 的局部暗色分支，`html { color-scheme: light; }` 本身不会移除这些分支，不能据此宣称全站统一暗色或统一覆盖。

## Layout

侧栏宽（240px），桌面在（768px）起固定于滚动视口，顶栏最小高（64px）。移动端侧栏作为带遮罩的抽屉，顶栏最小高（60px）。主区内边距按宽度为（12px / 16px / 28px）；常规主区最大宽（72rem），宽页面为（1900px）。

考勤首页最大宽（1280px）；不大于（1100px）时主分栏折为单列，不大于（640px）时四格统计变为两列且搜索框占满宽度。通用表格可横向滚动，部分表格最小宽（620px），考勤申请表为（880px）。表格密度和布局随实际模块保留。

## Elevation & Depth

常规业务面板和考勤面板采用细边框与浅色分层，无默认投影。聚焦面板可用品牌浅底形成（0 0 0 3px var(--xp-brand-bg)）光圈；它表示当前操作区域。通知和密码弹窗保留应用壳的浮层投影。

导航颜色过渡为（180ms ease），移动抽屉过渡为（200ms）。减少动态效果时动画和过渡缩短至（0.01ms）。原生登录卡片无投影。

## Shapes

通用业务按钮使用 button 圆角，业务字段使用 field，导航使用 navigation，业务与考勤面板使用 panel。考勤首页自己的操作按钮为（8px），小按钮为（7px）；考勤统计块为（11px），并非全部采用面板圆角。登录面板使用 login-panel，字段与主按钮为（7px）。

## Components

### Buttons

通用业务按钮最小高（34px）、小按钮（28px）；主要操作青绿底白字，悬停加深。次要按钮白底灰字，悬停强调边框与文字；危险变体在悬停强调风险色。禁用透明度为（0.45）。考勤首页 ac-btn、复用 btn 与页面局部按钮各有明确样式，不能据通用按钮推断全部行为。

### Inputs / Fields

通用业务字段采用细线白底和 field 圆角；只读和禁用字段使用 soft。普通工作区焦点为（2px）青绿外框、偏移（3px）；通用业务字段局部规则偏移（2px），考勤筛选局部规则为（1px）。

### Navigation

深青侧栏中的模块按组排列，浅绿色选中块与加粗文字表达当前位置。子级缩进（30px），模块图标（17px）。移动菜单由应用壳控制。

### Chips

考勤标签使用浅底深字和文字类别，annual 配对见 frontmatter。业务 pill 为另一套（12px）标签；不要用考勤标签尺寸覆盖全部状态标签。

### Cards / Containers

通用面板内边距（16px），flush 面板无内边距；考勤面板标题区（10px 16px），主体通常（12px 16px 14px），标题区最小高（42px）。图表依靠坐标、图例、数值与状态文字表达业务含义。

### Brand and Login

`rayher_hr_payroll/public/images/qiheng-logo.svg` 用于深色侧栏，`qiheng-logo-light.svg` 用于浅色登录，`qiheng-icon.svg` 用于图标入口。原生登录由 `public/css/qiheng-login.css` 独立控制：面板内边距（32px），输入最小高（42px），主要按钮最小高（40px）；Frappe 字段内部仍可能使用其自身表面。

依据：`frontend/src/styles/qiheng.css`、`expenseUi.css`、`attendanceUi.css`、`attendanceBoardUi.css` 和 `frontend/src/App.vue`。侧车示例解析 Tailwind 工具类，CSS 变量带实际回退，不依赖 Vue 运行时。

侧车色带是用于预览的合成 OKLCH 明度梯度，不新增源码颜色令牌。

## Do's and Don'ts

### Do:

- Do 深色侧栏使用亮字标，浅色登录使用深字标，保持 SVG 原始比例。
- Do 沿用业务页面的表格、审批、状态标签与图表映射，并保留文字说明。
- Do 让窄屏操作换行、面板堆叠、表格独立滚动；保留键盘焦点和减少动态效果支持。

### Don't:

- Don't 将深青侧栏解释为整站暗色主题，或将考勤局部暗色样式推广到全站。
- Don't 把所有局部按钮与字段强制换成同一种圆角、颜色或尺寸。
- Don't 为视觉一致性删除业务状态、审批入口或权限差异，也不要添加具象记录册装饰。
