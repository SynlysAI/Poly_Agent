---
version: alpha
name: PolyAgent-design
description: 基于 SpecAgent 蓝白科研实验室风格优化 — 深蓝侧边栏 + 浅蓝灰背景 + 白色面板，Inter 字体族替换系统默认字体，精细化排版层级与组件细节，保留同一产品线的视觉一致性。
---

colors:
  primary: "#3b82f6"
  primary-hover: "#2563eb"
  primary-active: "#1d4ed8"
  primary-light: "#dbeafe"
  on-primary: "#ffffff"
  sidebar-from: "#0b2d63"
  sidebar-to: "#091f44"
  sidebar-mid: "#0f3268"
  sidebar-text: "#c5d4f0"
  sidebar-text-muted: "#93b4e8"
  sidebar-active-bg: "rgba(59,130,246,0.3)"
  canvas: "#eef3fb"
  canvas-soft: "#f3f7fd"
  canvas-gradient: "linear-gradient(180deg, #f3f7fd 0%, #ecf2fa 100%)"
  card: "#ffffff"
  card-border: "#dce5f5"
  card-shadow: "0 4px 16px rgba(11,45,99,0.05)"
  ink: "#0f172a"
  body: "#334155"
  muted: "#64748b"
  subtle: "#94a3b8"
  hairline: "#d7e0ec"
  hairline-soft: "#e2e8f0"
  stat-bg: "linear-gradient(180deg, #f8fbff 0%, #eef4fd 100%)"
  stat-border: "#d9e6fa"
  header-bg: "rgba(255,255,255,0.94)"
  header-border: "#e2e8f0"
  success: "#16a34a"
  success-soft: "#f0fdf4"
  success-border: "#bbf7d0"
  warning: "#d97706"
  warning-soft: "#fffbeb"
  error: "#dc2626"
  error-soft: "#fef2f2"

typography:
  display-lg:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: -0.5px
  display-md:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 20px
    fontWeight: 700
    lineHeight: 1.35
    letterSpacing: -0.3px
  heading:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: -0.2px
  subheading:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 14px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: -0.1px
  body:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0
  body-sm:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  caption:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 11px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: 0.5px
    textTransform: uppercase
  button:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 13px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: 0
  mono:
    fontFamily: "'JetBrains Mono', 'SF Mono', 'Cascadia Code', monospace"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: 0
  stat-value:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 22px
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: -0.3px
  sidebar-brand:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 16px
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: -0.3px
  sidebar-subtitle:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 11px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: 0
  sidebar-item:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: 0

rounded:
  sm: 6px
  md: 10px
  lg: 14px
  pill: 9999px
  full: 9999px

spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px

components:
  sidebar:
    background: "linear-gradient(180deg, {colors.sidebar-from} 0%, {colors.sidebar-mid} 50%, {colors.sidebar-to} 100%)"
    textColor: "{colors.sidebar-text}"
    width: 220px
    collapsedWidth: 66px
  sidebar-brand:
    padding: "14px 16px"
    borderBottom: "1px solid rgba(255,255,255,0.1)"
  sidebar-brand-logo:
    size: 32px
    rounded: "{rounded.md}"
    background: "rgba(255,255,255,0.95)"
  sidebar-item:
    padding: "8px 12px"
    rounded: "{rounded.md}"
    marginBottom: 2px
    textColor: "{colors.sidebar-text}"
  sidebar-item-active:
    background: "{colors.sidebar-active-bg}"
    textColor: "#ffffff"
    fontWeight: 600
  header:
    height: 48px
    background: "{colors.header-bg}"
    borderBottom: "1px solid {colors.header-border}"
    backdropFilter: "blur(12px)"
  panel:
    background: "{colors.card}"
    borderColor: "{colors.card-border}"
    shadow: "{colors.card-shadow}"
    rounded: "{rounded.lg}"
    padding: 14px
  stat-card:
    background: "{colors.stat-bg}"
    borderColor: "{colors.stat-border}"
    rounded: "{rounded.md}"
    padding: 12px
  button-primary:
    background: "linear-gradient(135deg, {colors.primary}, {colors.primary-hover})"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
    padding: "8px 18px"
    shadow: "0 2px 8px rgba(37,99,235,0.25)"
  button-primary-hover:
    background: "linear-gradient(135deg, {colors.primary-hover}, {colors.primary-active})"
    shadow: "0 4px 12px rgba(37,99,235,0.35)"
  button-secondary:
    background: "transparent"
    textColor: "{colors.body}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
    padding: "8px 18px"
    border: "1px solid {colors.hairline}"
  text-input:
    background: "{colors.card}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
    border: "1px solid {colors.hairline}"
    height: 36px
  text-input-focused:
    border: "2px solid {colors.primary}"
    shadow: "0 0 0 3px {colors.primary-light}"
  badge-default:
    background: "{colors.primary-light}"
    textColor: "{colors.primary}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
    typography: "{typography.caption}"
    border: "1px solid #bfdbfe"
  badge-success:
    background: "{colors.success-soft}"
    textColor: "{colors.success}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
    typography: "{typography.caption}"
    border: "1px solid {colors.success-border}"
  table:
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
  table-header:
    textColor: "{colors.body}"
    typography:
      fontSize: 11px
      fontWeight: 600
      letterSpacing: 0.5px
      textTransform: uppercase
    borderBottom: "2px solid {colors.hairline-soft}"
  table-cell:
    padding: "7px 10px"
    borderBottom: "1px solid {colors.hairline-soft}"
  icon:
    size: 18px
    strokeWidth: 2
    strokeLinecap: round
    strokeLinejoin: round
---

## Overview

基于 SpecAgent 蓝白科研实验室风格优化版。保留深蓝侧边栏 + 浅蓝灰背景 + 白色面板的核心视觉特征，引入 Inter 字体族替代系统默认字体，精细调整排版层级与组件细节。

**关键特征：**
- 深蓝渐变色侧边栏 (`#0b2d63` → `#0f3268` → `#091f44`)
- 浅蓝灰页面背景 (`#eef3fb` → `#ecf2fa` 渐变)
- 白色内容面板 + 细腻阴影
- Inter 字体族 (400/500/600/700) + JetBrains Mono 等宽
- 蓝色主 CTA 按钮 (`#3b82f6` → `#2563eb` 渐变 + 柔和阴影)
- 统一 6/10/14px 圆角体系
- SVG 线性图标 (Element Plus 风格)

## Colors

### Brand & Surface
- **Primary Blue** (`{colors.primary}` — `#3b82f6`): 主 CTA 按钮、选中态、链接强调色。
- **Primary Hover** (`{colors.primary-hover}` — `#2563eb`): hover 态。
- **Primary Light** (`{colors.primary-light}` — `#dbeafe`): 淡蓝背景，用于标签和选中态背景。

### Sidebar
- **Sidebar From** (`{colors.sidebar-from}` — `#0b2d63`): 侧边栏顶部渐变起始色。
- **Sidebar Mid** (`{colors.sidebar-mid}` — `#0f3268`): 侧边栏中部过渡色。
- **Sidebar To** (`{colors.sidebar-to}` — `#091f44`): 侧边栏底部渐变结束色。

### Page Canvas
- **Canvas** (`{colors.canvas}` — `#eef3fb`): 页面默认背景。
- **Canvas Soft** (`{colors.canvas-soft}` — `#f3f7fd`): 浅色区域背景。
- **Card** (`{colors.card}` — `#ffffff`): 面板和卡片背景。

### Text
- **Ink** (`{colors.ink}` — `#0f172a`): 标题和主要文字。
- **Body** (`{colors.body}` — `#334155`): 正文。
- **Muted** (`{colors.muted}` — `#64748b`): 次要标注。
- **Subtle** (`{colors.subtle}` — `#94a3b8`): 最弱文字。

### Semantic
- **Success** (`{colors.success}` — `#16a34a`): 成功/完成状态。
- **Warning** (`{colors.warning}` — `#d97706`): 警告/进行中状态。
- **Error** (`{colors.error}` — `#dc2626`): 错误/失败状态。

## Typography

### Font Family
- **Primary**: Inter (400/500/600/700) — 所有 UI 文本
  - 中文回退: PingFang SC → Microsoft YaHei → sans-serif
- **Mono**: JetBrains Mono (400) — 代码块和数据标注

### Hierarchy
| Token | Size | Weight | Line Height | Letter Spacing | Use |
|---|---|---|---|---|---|
| `display-lg` | 24px | 700 | 1.3 | -0.5px | 页面标题 |
| `display-md` | 20px | 700 | 1.35 | -0.3px | 区块标题 |
| `heading` | 16px | 600 | 1.4 | -0.2px | 面板标题、卡片标题 |
| `subheading` | 14px | 600 | 1.4 | -0.1px | 子标题 |
| `body` | 14px | 400 | 1.55 | 0 | 正文 |
| `body-sm` | 13px | 400 | 1.5 | 0 | 表格内容、列表 |
| `caption` | 11px | 600 | 1.4 | +0.5px | uppercase 标注 |
| `button` | 13px | 600 | 1.2 | 0 | 按钮标签 |
| `stat-value` | 22px | 700 | 1.2 | -0.3px | 统计数字 |
| `mono` | 13px | 400 | 1.6 | 0 | 代码 |

### Principles
- 标题使用负字间距 (-0.5px ~ -0.1px) 增加精致感
- 正文保持 0 字间距保证可读性
- 标注使用大写 + 正字间距 (+0.5px)
- 统计数字使用 700 字重突出

## Components

### Sidebar
深蓝三阶渐变背景，白色/浅蓝文字。菜单项 `{rounded.md}` (10px) 圆角。选中态使用 `{colors.sidebar-active-bg}` (半透明蓝)。品牌区域底部 1px 半透明白色分割线。

### Header
白色半透明背景 + backdrop-filter 模糊，48px 高度，底部细边框分割。

### Panel / Card
白色背景 + 浅蓝灰边框 + 细腻阴影。`{rounded.lg}` (14px) 圆角。

### Button
- **Primary**: 蓝渐变 (`#3b82f6` → `#2563eb`) + 柔和投影
- **Secondary**: 透明背景 + 灰色边框

### Input
白色背景 + 灰色边框，`{rounded.sm}` (6px) 圆角。聚焦态蓝色双线边框 + 淡蓝外发光。

### Badge
- **Default**: 淡蓝背景 + 蓝色文字 + 蓝色细边框
- **Success**: 淡绿背景 + 绿色文字 + 绿色细边框

### Table
表头 uppercase + 600 字重 + 底部双线。行底部细线分割。

## Do's and Don'ts

### Do
- 严格使用 Inter 字体族，中文回退 PingFang SC
- 侧边栏使用三阶深蓝渐变
- 主按钮使用蓝渐变 + 投影
- SVG 图标使用 2px 描边 + round cap/join
- 统一使用 {rounded.sm/md/lg} 圆角体系

### Don't
- 不要使用系统默认字体栈
- 不要使用 Emoji 作为功能图标
- 不要引入深蓝/蓝灰以外的主色调
- 不要让卡片阴影过重 (> 8% 透明度)
