# Plan 05：ResearchEngine 前端 MVP

## 目标

在现有 Vue 3 + Element Plus 工作台中加入 ResearchEngine P0 入口和操作面板。UI 应复用现有导航、panel、表格、drawer、dialog、tag 风格，不新建复杂独立壳。

## 范围

- 任务提交页 ResearchEngine 入口。
- 湿实验优化页 ResearchEngine / AutoResearch 入口卡。
- Campaign 详情中的 ProblemSpec、人工算法、AutoResearch、Audit 区块。
- Tool Services 中 AlgorithmRegistry 清单。
- ResearchRun stage timeline 和 gate 审批。

## 共享组件规范

所有 ResearchEngine 前端组件应遵循以下约定，确保与现有 Vue 工作台视觉和交互一致。

### 组件目录结构

```
frontend/src/views/research-engine/
  ├── ProblemSpecPanel.vue       # ProblemSpec 编辑与预览
  ├── AlgorithmRegistryPanel.vue # 算法能力清单（可筛选）
  ├── AlgorithmRunPanel.vue      # 人工算法运行表单
  ├── AlgorithmRunDetail.vue     # AlgorithmRun 详情
  ├── ResearchRunPanel.vue       # ResearchRun Stage/Gate 看板
  └── GateReviewDialog.vue       # Gate 审批 dialog
```

### 共享 UI 模式

所有组件复用 Element Plus 的以下组件（与现有 Dashboard/CampaignDetail 等页面一致）：

| 场景 | Element Plus 组件 | 参考页面 |
| --- | --- | --- |
| 页面区块容器 | `div.panel > div.panel-header + div.panel-body` | DashboardView.vue |
| 统计卡片 | `div.stat-grid > div.stat-card` | DashboardView.vue |
| 数据表格 | `el-table` + `el-tag`（状态）+ `el-button`（操作） | CampaignDetailView.vue |
| 筛选条件 | `el-select` + `el-input` + `el-button` 行内排列 | ComputationRunsView.vue |
| 表单 | `el-form` + `el-form-item` + `el-input`/`el-select`/`el-input-number` | ComputationSubmitView.vue |
| 阶段时间线 | `el-steps` | —（新增，无现有参考） |
| 详情抽屉 | `el-drawer` | CampaignDetailView.vue |
| 确认弹窗 | `el-dialog` + `el-button`（确认/取消） | CampaignDetailView.vue |
| JSON 预览 | `<pre>` 标签在 drawer 内展示 | — |
| 入口卡片 | `div.page-grid > div.page-card` | OptimizationHomeView.vue |

### 文案规范

- **主文案**：使用中文化术语（"研发任务"、"候选"、"推荐"、"实验"、"回填"、"模型更新"）
- **技术对象名**：仅在详情、审计和调试区展示英文名（`ProblemSpec`、`ResearchRun`、`AlgorithmRun`）
- **按钮文案**：动作性动词（"启动"、"审批"、"拒绝"、"重跑"），避免"确认"、"提交"等模糊文案
- **状态标签**：使用 `el-tag` 中文状态文案，颜色与现有 computation/campaign 状态一致

### 响应式要求

- 768px、1024px、1440px 视口下不出现文字重叠或按钮溢出
- 复杂表格在窄屏下允许横向滚动（`el-table` 默认行为）
- `el-dialog` 在 768px 以下使用 `fullscreen` 模式

## 不做

- 不新增大型状态管理框架（页面局部状态优先使用 Vue `ref`/`computed`）。
- 不做完整低代码 schema form，只覆盖 P0 常用字段（text、number、select、file upload）。
- 不做新一级导航，除非现有入口无法承载。

## 任务列表

### Task 1：API client 封装

**说明：** 在前端 API client 中封装 ResearchEngine API。

**验收标准：**
- [ ] 支持 ProblemSpec CRUD/freeze。
- [ ] 支持 AlgorithmRegistry list/detail。
- [ ] 支持 AlgorithmRun create/list/detail。
- [ ] 支持 ResearchRun create/start/detail/gate approve/reject。

**验证：**
- [ ] `cd frontend && npm run build`

**依赖：** Plan 02-04 API

**可能触达文件：**
- `frontend/src/api/polyAgentApi.js`

**规模：** S

### Task 2：任务提交和湿实验优化入口

**说明：** 增加用户可发现的 ResearchEngine 入口，不新增重壳。

**验收标准：**
- [ ] `frontend/src/tasks/taskModules.js` 增加“ResearchEngine 研发任务”模块卡。
- [ ] `/tasks/submit` 可看到入口，点击跳转到 `/optimization` 或 ResearchEngine 区块。
- [ ] `/optimization` 增加 ResearchEngine / AutoResearch 入口卡，与现有卡片视觉一致。

**验证：**
- [ ] `cd frontend && npm run build`
- [ ] 手工检查任务提交页和湿实验优化页入口可点击。

**依赖：** Task 1

**可能触达文件：**
- `frontend/src/tasks/taskModules.js`
- `frontend/src/views/TaskSubmitView.vue`
- `frontend/src/views/OptimizationHomeView.vue`

**规模：** S

### Task 3：ProblemSpec 编辑与预览

**说明：** 提供 P0 表单，让用户能定义材料体系、变量、目标、约束和执行模式。

**验收标准：**
- [ ] 支持创建和编辑 draft ProblemSpec。
- [ ] 支持变量、目标、约束的增删改。
- [ ] 支持 execution_mode 选择。
- [ ] 显示 JSON 预览 drawer。
- [ ] 冻结操作有确认和失败提示。

**验证：**
- [ ] `cd frontend && npm run build`
- [ ] 手工创建氟基高分子 ProblemSpec。

**依赖：** Plan 02

**可能触达文件：**
- `frontend/src/views/CampaignDetailView.vue`
- `frontend/src/views/research-engine/ProblemSpecPanel.vue`

**规模：** M

### Task 4：AlgorithmRegistry 和人工运行界面

**说明：** 在 Tool Services 或 Campaign 详情中展示算法能力，并允许人工触发 mock 算法。

**验收标准：**
- [ ] AlgorithmRegistry 可按类型、材料体系、触发方式筛选。
- [ ] 算法详情 drawer 展示 input_schema / output_schema。
- [ ] 用户可填写 P0 输入并创建 AlgorithmRun。
- [ ] AlgorithmRun 详情展示状态、输入快照、输出摘要、错误和 artifact refs。

**验证：**
- [ ] `cd frontend && npm run build`
- [ ] 手工运行一个 mock predictor 并查看结果。

**依赖：** Plan 03

**可能触达文件：**
- `frontend/src/views/ToolServicesView.vue`
- `frontend/src/views/CampaignDetailView.vue`
- `frontend/src/views/research-engine/AlgorithmRegistryPanel.vue`
- `frontend/src/views/research-engine/AlgorithmRunPanel.vue`

**规模：** M

### Task 5：ResearchRun Stage/Gate 看板

**说明：** 在 Campaign 详情或 ResearchEngine 区块展示 AutoResearch 当前进度和待审批 gate。

**验收标准：**
- [ ] 可创建并启动 ResearchRun。
- [ ] 使用 `el-steps` 或 timeline 展示 stage 状态。
- [ ] blocked_approval 状态下显示审批按钮。
- [ ] 批准/拒绝 dialog 必须填写原因。
- [ ] 操作后刷新 stage timeline 和 audit。

**验证：**
- [ ] `cd frontend && npm run build`
- [ ] 手工创建 ResearchRun、启动、审批一个 gate。

**依赖：** Plan 04

**可能触达文件：**
- `frontend/src/views/CampaignDetailView.vue`
- `frontend/src/views/research-engine/ResearchRunPanel.vue`
- `frontend/src/views/research-engine/GateReviewDialog.vue`

**规模：** M

### Task 6：任务中心和 Dashboard 最小映射

**说明：** 让 ResearchRun / AlgorithmRun 不只藏在 campaign detail 中。

**验收标准：**
- [ ] Dashboard 显示最近 ResearchRun 或待审批 gate 的简要入口。
- [ ] 任务中心可展示 ResearchRun / AlgorithmRun 的基本状态或跳转链接。
- [ ] 不破坏现有 computation 任务列表。

**验证：**
- [ ] `cd frontend && npm run build`
- [ ] 手工检查 Dashboard、任务中心、计算任务中心仍可用。

**依赖：** Task 4-5

**可能触达文件：**
- `frontend/src/views/DashboardView.vue`
- `frontend/src/views/TaskCenterView.vue`

**规模：** S

## Checkpoint

- [ ] 用户能从任务提交或湿实验优化进入 ResearchEngine。
- [ ] 用户能创建 ProblemSpec、人工运行算法、启动 ResearchRun、审批 gate。
- [ ] 前端构建通过，页面没有明显文字重叠和按钮溢出。

## 风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| UI 入口过多 | 用户迷失 | P0 入口挂在任务提交、湿实验优化、Campaign 详情、Tool Services |
| 技术对象名过多 | 非算法用户难理解 | 主文案使用研发任务、候选、推荐、实验、回填 |
| 表格和 JSON 挤压布局 | 可用性差 | 长字段放 drawer/pre，窄屏允许横向滚动 |
