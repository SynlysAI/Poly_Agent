# ChemOS 计算智能模块产品需求文档 PRD

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | Draft for implementation planning |
| 版本 | v0.1 |
| 日期 | 2026-07-01 |
| 来源文档 | `doc/chemos-computation-migration-design.md` |
| 适用范围 | Poly_Agent 计算任务、计算结果可视化、优化 campaign、SpecLabOS 实验验证集成 |
| 不适用范围 | 直接复制 ChemOS Streamlit 前端、直接迁移 ChemOS SiLA 仪器服务、在 FastAPI 请求内执行 DFT 长任务 |

本文将 ChemOS 迁移设计转化为产品开发可执行 PRD。核心产品口径是：

```text
在 Poly_Agent 中建设面向高分子材料研发的计算智能与优化推荐模块，让用户可以提交计算任务、追踪计算过程、查看结构化结果，并把计算或实验 observation 用于下一轮候选推荐。
```

## 2. 背景和问题

### 2.1 当前事实

| 领域 | 当前状态 |
|---|---|
| Poly_Agent 后端 | FastAPI，API 前缀 `/api/v1`，MongoDB + PyMongo，统一响应结构 `ApiResponse` |
| Poly_Agent 前端 | Vue 3 + Element Plus + Vite，任务提交和任务中心仍是性能预测占位 |
| ChemOS 参考能力 | 计算 workflow、AiiDA provenance 思路、Atlas/Olympus 优化闭环、光谱和 gain 后处理 |
| SpecLabOS | 已有设备、workflow、SmartAccess 和实验日志能力，不应被 ChemOS SiLA 层替代 |
| 迁移约束 | ChemOS 是 demo/reference，不是可直接生产部署的完整服务 |

### 2.2 用户问题

研发用户现在缺少一条可审计的闭环链路：

```text
候选分子
  -> 计算或实验评价
  -> 结构化结果
  -> observation
  -> 下一轮推荐
```

具体痛点：

- 任务提交页面不能提交真实计算任务。
- 任务中心展示静态假数据，无法追踪计算状态。
- 计算过程、输出文件、解析结果和错误原因没有统一业务对象。
- ChemOS 的闭环优化思想尚未变成 Poly_Agent 可维护的 campaign/suggestion/observation 模型。
- AiiDA、ORCA、xTB、SpecLabOS 等外部系统缺少统一状态入口和审计线索。

## 3. 产品目标

### 3.1 目标

| ID | 目标 | 成功标准 |
|---|---|---|
| G1 | 建立真实计算任务生命周期 | 用户可创建、查看、取消、重试计算任务，状态从 `queued` 推进到终态 |
| G2 | 建立可审计结果资产体系 | 每个 artifact 有来源 step、checksum、parser metadata、下载审计 |
| G3 | 建立优化 campaign 基础闭环 | candidate、suggestion、observation 可查询、可追踪、可人工确认 |
| G4 | 支持计算驱动推荐 | suggestion 可转为 computation run，计算完成后可生成 observation |
| G5 | 保留外部系统边界 | AiiDA、optimizer、SpecLabOS 均通过适配层接入，不污染主业务库和前端安全边界 |

### 3.2 非目标

| ID | 非目标 | 原因 |
|---|---|---|
| N1 | 第一版上线完整 ORCA/AiiDA laser workflow | 部署复杂，依赖 AiiDA、RabbitMQ、PostgreSQL、ORCA license 和 HPC |
| N2 | 第一版强依赖 Atlas/Olympus | 当前本地优化栈未完整验证，依赖重且老旧 |
| N3 | 迁移 ChemOS Streamlit UI | Poly_Agent 前端架构是 Vue 3 |
| N4 | 迁移 ChemOS SiLA 仪器层 | SpecLabOS 已承担实验设备和 workflow 编排 |
| N5 | 允许前端传 shell command、任意 code path 或本地文件路径 | 安全和审计风险不可接受 |

## 4. 用户和角色

| 角色 | 典型职责 | 关键需求 |
|---|---|---|
| 研发用户 | 提交计算任务，查看结果，确认推荐 | 表单简单、状态清楚、结果可下载和预览 |
| 课题负责人 | 查看 campaign 进展和候选效果 | 可比较 objective、可回溯每轮推荐依据 |
| 计算管理员 | 配置 worker、AiiDA、ORCA/xTB 运行环境 | 外部系统状态可见，失败可定位 |
| 系统管理员 | 管理权限、集成配置和审计日志 | 操作可追责，敏感配置不泄露 |
| 实验平台用户 | 把推荐候选提交 SpecLabOS 验证 | 实验 run 和候选、observation 有明确关联 |

## 5. 产品范围

### 5.1 MVP 范围

MVP 只承诺打通产品闭环，不承诺真实 DFT 全量计算。

| 模块 | MVP 范围 |
|---|---|
| 计算任务 | 创建、列表、详情、取消、重试、mock/local worker 状态推进 |
| Artifact | 元数据登记、checksum、下载、结构化 preview API 占位 |
| 前端 | 改造任务提交、任务中心，新增计算详情页 |
| 优化 | campaign、candidate、suggestion、observation 基础 API，fallback planner |
| 审计 | 记录计算、artifact 下载、campaign、suggestion、observation 和集成配置关键操作 |
| 集成状态 | 展示 ChemOS demo、computation worker、SpecLabOS、AiiDA 可用性 |

### 5.2 MVP 后范围

| 阶段 | 增量能力 |
|---|---|
| Phase 2 | OpenBabel/RDKit/xTB local adapter，真实结构 artifact |
| Phase 3 | AiiDA worker，写回 `aiida_process_uuid` |
| Phase 4 | ORCA laser workflow，spectra/gain parser |
| Phase 5 | Atlas Tanimoto planner，Morgan fingerprint，Pareto/history |
| Phase 6 | 计算完成后自动生成 observation，并触发下一轮 suggestion |
| Phase 7 | SpecLabOS 实验验证，实验 observation 回写 |

## 6. 核心用户流程

### 6.1 提交计算任务

```text
用户进入任务提交
  -> 选择计算任务 tab
  -> 输入 SMILES、名称、workflow、engine、charge、multiplicity、资源上限
  -> 提交
  -> 后端创建 computation_run(status=queued)
  -> 返回 run_id
  -> 前端跳转任务详情
```

验收点：

- 输入不合法时返回明确校验错误。
- 创建成功后 MongoDB 有 `computation_runs` 记录。
- 首屏能看到 run_id、状态、分子、workflow 和创建人。

### 6.2 查看计算过程和结果

```text
用户进入任务中心
  -> 按状态、workflow、engine、关键词筛选
  -> 打开任务详情
  -> 查看 workflow timeline、result summary、artifacts、logs
  -> 下载或预览 artifact
```

验收点：

- 任务中心数据来自 `/api/v1/computations`，不是静态数组。
- timeline 每个 step 至少显示状态、开始时间、结束时间、错误信息。
- artifact 下载前校验权限并记录审计事件。

### 6.3 创建优化 campaign

```text
用户创建 campaign
  -> 定义 objective 和方向
  -> 导入候选分子库
  -> 添加历史 observation 或等待计算结果
  -> 生成 suggestion
```

验收点：

- campaign 可保存为 `draft`。
- 候选分子有 `candidate_key`、SMILES、来源 metadata。
- suggestion 记录包含 planner type、iteration index 和推荐理由。

### 6.4 suggestion 转计算任务

```text
用户在 CampaignDetail 查看 suggestion
  -> 点击 Submit Computation
  -> 后端创建 computation_run
  -> suggestion.status=submitted
  -> 计算完成后用户或系统写入 observation
```

验收点：

- suggestion、candidate、computation_run 三者可互相追踪。
- 重复提交需要幂等保护或明确阻止。
- observation 写入后 campaign history 能显示新点。

### 6.5 suggestion 转实验验证

```text
用户在 CampaignDetail 查看 suggestion
  -> 点击 Submit Experiment
  -> Poly_Agent 调用 SpecLabOS workflow API
  -> 保存 external workflow_run_id
  -> 实验完成后回写 observation(source_type=experiment)
```

验收点：

- SpecLabOS run id 保存在 external refs。
- 上游调用失败时 suggestion 不应进入 evaluated。
- 实验 observation 与计算 observation 可并存。

## 7. 功能需求

优先级定义：

- P0: MVP 必须交付，否则产品不可用。
- P1: MVP 后第一批增强。
- P2: 中长期增强。

### 7.1 计算任务

| ID | 优先级 | 需求 | 验收标准 |
|---|---|---|---|
| COMP-001 | P0 | 创建计算任务 | `POST /api/v1/computations` 接收白名单 workflow/engine，返回 `run_id` |
| COMP-002 | P0 | 查询任务列表 | `GET /api/v1/computations` 支持分页、状态、workflow、engine、关键词筛选 |
| COMP-003 | P0 | 查询任务详情 | 详情返回 run、steps、artifact ids、result summary、external refs |
| COMP-004 | P0 | mock worker 推进状态 | 开发环境中 queued 任务可自动变为 completed 或 failed |
| COMP-005 | P0 | 取消任务 | 非终态任务可取消，终态任务不可取消 |
| COMP-006 | P0 | 重试任务 | failed/cancelled 任务可生成 retry run 或重置为 queued，策略需记录 |
| COMP-007 | P1 | local 结构生成 | OpenBabel/RDKit 生成 XYZ/SDF artifact |
| COMP-008 | P1 | AiiDA 状态同步 | 保存并同步 `aiida_process_uuid`、AiiDA process state |
| COMP-009 | P2 | ORCA laser workflow | 完整 step 和 spectra/gain 输出可追踪 |

### 7.2 Artifact 和结果展示

| ID | 优先级 | 需求 | 验收标准 |
|---|---|---|---|
| ART-001 | P0 | 登记 artifact 元数据 | 每个 artifact 有 `artifact_id`、`run_id`、`step_key`、type、size、checksum |
| ART-002 | P0 | artifact 下载 | 权限通过后下载，记录 `artifact.downloaded` 审计事件 |
| ART-003 | P0 | parser metadata | 解析产物记录 parser name、version、input checksum |
| ART-004 | P1 | 结构预览 | `/structure` 返回前端可渲染的结构 JSON |
| ART-005 | P1 | 图谱预览 | `/spectrum` 返回 ECharts/Plotly 可消费的 series JSON |
| ART-006 | P2 | artifact 生命周期 | 支持归档、过期、压缩和对象存储迁移 |

### 7.3 优化 campaign

| ID | 优先级 | 需求 | 验收标准 |
|---|---|---|---|
| OPT-001 | P0 | 创建 campaign | 保存 name、objectives、planner type、planner config |
| OPT-002 | P0 | 导入候选 | 支持 JSON/CSV 导入 candidate，失败行有错误报告 |
| OPT-003 | P0 | 写入 observation | 支持 computation、experiment、manual、imported 来源 |
| OPT-004 | P0 | fallback suggestion | 能基于未评估候选生成 suggestion |
| OPT-005 | P0 | suggestion 状态流转 | suggested、submitted、evaluated、rejected、failed 可审计 |
| OPT-006 | P1 | campaign history | 返回 iteration、candidate、objective values、source refs |
| OPT-007 | P1 | suggestion 转 computation | 一键创建 computation_run 并绑定 suggestion |
| OPT-008 | P1 | Morgan fingerprint | 对 candidate 生成 descriptor，供 Tanimoto planner 使用 |
| OPT-009 | P2 | Atlas Tanimoto adapter | 离散分子库上使用 Atlas/Olympus 推荐 |
| OPT-010 | P2 | Pareto front | 多目标优化返回 Pareto 数据 |

### 7.4 SpecLabOS 集成

| ID | 优先级 | 需求 | 验收标准 |
|---|---|---|---|
| INT-001 | P0 | 集成状态展示 | `/integrations/status` 返回 worker、ChemOS demo、SpecLabOS、AiiDA 状态 |
| INT-002 | P1 | 提交实验 workflow | suggestion 可转 SpecLabOS workflow run |
| INT-003 | P1 | 实验结果回写 | 根据 run id 拉取或接收结果并写 observation |
| INT-004 | P2 | SmartAccess 事件 | 支持向 SmartAccess 事件流写入候选和实验状态 |

### 7.5 权限和审计

| ID | 优先级 | 需求 | 验收标准 |
|---|---|---|---|
| AUD-001 | P0 | 关键操作审计 | 创建、取消、重试、下载、生成推荐、写 observation 都有审计记录 |
| AUD-002 | P0 | 请求追踪 | 审计事件记录 `request_id`，与现有 `X-Request-Id` 对齐 |
| AUD-003 | P0 | 操作人记录 | 审计事件记录 `actor_user_id`、role、client ip 或来源 |
| AUD-004 | P0 | 外部引用记录 | 审计事件记录 run/campaign/suggestion/artifact/external ids |
| AUD-005 | P1 | 审计查询页面 | 管理员可按时间、用户、实体、事件类型筛选 |

## 8. 前端信息架构

### 8.1 MVP 页面

| 页面 | 路由建议 | 主要内容 |
|---|---|---|
| 任务提交 | `/tasks/submit` | 保留性能预测入口，新增计算任务 tab |
| 任务中心 | `/tasks/center` | 真实 computation list、过滤、分页、状态标签 |
| 计算详情 | `/computations/:runId` | header、timeline、summary、artifacts、logs |
| 工具服务 | `/tools` | ChemOS demo、worker、AiiDA、SpecLabOS 状态 |
| Campaign 列表 | `/optimization/campaigns` | campaign cards/table、状态和进度 |
| Campaign 详情 | `/optimization/campaigns/:campaignId` | objectives、candidate、suggestion、observation、history |

### 8.2 交互原则

- 所有状态必须有文字，不只依赖颜色。
- 长任务页面默认轮询，后续可换 SSE。
- destructive 操作如 cancel、retry、reject suggestion 需要二次确认。
- artifact 下载按钮展示文件类型、大小、checksum 短码。
- computation 和 campaign 详情页必须展示可复制的 ID。

## 9. 数据对象产品定义

| 对象 | 产品含义 | 关键字段 |
|---|---|---|
| computation_run | 一次计算任务 | run_id、workflow_type、engine、status、molecule、parameters、steps、result_summary |
| computation_step | 计算任务中的阶段 | step_key、status、started_at、finished_at、artifact_ids、error |
| artifact | 计算或解析产生的文件或结构化数据 | artifact_id、type、storage_uri、checksum、parser metadata |
| campaign | 一组候选和目标的优化任务 | campaign_id、objectives、planner_type、status |
| candidate | 可被评估的分子或参数组合 | candidate_id、candidate_key、smiles、descriptors |
| suggestion | planner 推荐的下一步候选 | suggestion_id、iteration_index、planner_payload、status |
| observation | 对 candidate 的一次评价结果 | source_type、source_run_id、values、uncertainty |
| audit_event | 用户或系统关键操作记录 | event_id、event_type、actor、entity、request_id、created_at |

## 10. 状态定义

### 10.1 computation_run 状态

| 状态 | 含义 | 允许下一状态 |
|---|---|---|
| draft | 草稿，未入队 | queued、cancelled |
| queued | 已创建等待 worker | submitted、running、cancelled、failed |
| submitted | 已提交外部系统 | running、failed、cancelled |
| running | 正在执行 | parsing、completed、failed、cancelled |
| parsing | 计算完成，正在解析结果 | completed、failed |
| completed | 成功终态 | retry 生成新 run |
| failed | 失败终态 | retry 生成新 run 或重置 queued |
| cancelled | 取消终态 | retry 生成新 run |

### 10.2 campaign 状态

| 状态 | 含义 |
|---|---|
| draft | 可编辑，未开始推荐 |
| running | 正在进行推荐和评价 |
| paused | 人工暂停 |
| completed | 已完成 |
| failed | planner 或流程失败 |
| archived | 归档只读 |

### 10.3 suggestion 状态

| 状态 | 含义 |
|---|---|
| suggested | 已推荐，等待处理 |
| submitted | 已提交计算或实验 |
| evaluated | 已产生 observation |
| rejected | 人工拒绝 |
| failed | 提交或评价失败 |

## 11. 权限矩阵

| 操作 | 研发用户 | 课题负责人 | 计算管理员 | 系统管理员 |
|---|---:|---:|---:|---:|
| 创建 computation | 是 | 是 | 是 | 是 |
| 查看本人 computation | 是 | 是 | 是 | 是 |
| 查看全部 computation | 否 | 视项目权限 | 是 | 是 |
| 取消本人 computation | 是 | 是 | 是 | 是 |
| 取消任意 computation | 否 | 视项目权限 | 是 | 是 |
| 下载 artifact | 视任务权限 | 视项目权限 | 是 | 是 |
| 创建 campaign | 是 | 是 | 是 | 是 |
| 修改 campaign | 创建人 | 是 | 是 | 是 |
| 生成 suggestion | 是 | 是 | 是 | 是 |
| 确认 observation | 创建人 | 是 | 是 | 是 |
| 提交 SpecLabOS 实验 | 否 | 是 | 是 | 是 |
| 管理集成配置 | 否 | 否 | 否 | 是 |
| 查询审计日志 | 否 | 项目范围 | 是 | 是 |

## 12. 审计要求

### 12.1 审计事件类型

| 事件类型 | 触发场景 | 必填实体 |
|---|---|---|
| `computation.created` | 创建计算任务 | run_id |
| `computation.cancelled` | 取消任务 | run_id |
| `computation.retried` | 重试任务 | old_run_id、new_run_id 或 run_id |
| `computation.status_changed` | worker 或同步器更新状态 | run_id、from_status、to_status |
| `artifact.registered` | worker 登记 artifact | artifact_id、run_id |
| `artifact.downloaded` | 用户下载 artifact | artifact_id、run_id |
| `campaign.created` | 创建 campaign | campaign_id |
| `campaign.updated` | 修改 campaign 配置或状态 | campaign_id |
| `candidate.imported` | 导入候选 | campaign_id、import_batch_id |
| `suggestion.generated` | 生成 suggestion | suggestion_id、campaign_id |
| `suggestion.rejected` | 拒绝 suggestion | suggestion_id、reason |
| `observation.created` | 写入 observation | observation_id、campaign_id |
| `experiment.submitted` | 提交 SpecLabOS workflow | suggestion_id、workflow_run_id |
| `integration.updated` | 修改集成配置 | integration_id |

### 12.2 审计字段

每条审计记录至少包含：

```json
{
  "event_id": "audit_...",
  "event_type": "computation.created",
  "actor_user_id": "user_id",
  "actor_role": "user",
  "request_id": "x-request-id",
  "entity_type": "computation_run",
  "entity_id": "comp_...",
  "related_ids": {
    "campaign_id": null,
    "suggestion_id": null,
    "artifact_id": null,
    "external_run_id": null
  },
  "before": {},
  "after": {},
  "metadata": {
    "client_ip": "127.0.0.1",
    "user_agent": "...",
    "source": "web"
  },
  "created_at": "2026-07-01T00:00:00Z"
}
```

审计保留要求：

- MVP 阶段至少保留 180 天。
- 不记录 secret 原文。
- 对大字段只记录摘要、hash 或变更字段名。
- worker 自动事件也要记录 `actor_user_id=system` 和 worker id。

## 13. 指标和验收

### 13.1 产品指标

| 指标 | MVP 目标 |
|---|---|
| 任务创建成功率 | 开发环境 mock adapter 下不低于 99% |
| 任务状态可见性 | 100% 非草稿任务有状态和更新时间 |
| artifact 可追踪性 | 100% artifact 有 checksum 和 source step |
| 审计覆盖率 | P0 操作 100% 产生审计事件 |
| recommendation 可追踪性 | 100% suggestion 可追溯 planner、candidate 和 campaign |

### 13.2 MVP 发布门禁

MVP 发布前必须满足：

- `POST /api/v1/computations`、列表、详情、取消、重试可用。
- TaskSubmitView 和 TaskCenterView 不再依赖静态假数据。
- mock worker 可完成至少一个成功任务和一个失败任务。
- computation detail 可展示 timeline、summary、artifact 列表。
- campaign/candidate/observation/suggestion P0 API 可用。
- P0 审计事件可查询。
- `.env.example` 包含新增非 secret 配置示例，secret 只写变量名不写真实值。
- 所有 API 输入有 Pydantic schema 校验。

## 14. 需求追踪矩阵

| 来源章节 | PRD 需求 | 设计文档章节 |
|---|---|---|
| 迁移设计 6 数据模型 | COMP、ART、OPT、AUD | `chemos-computation-product-design.md` 4 |
| 迁移设计 7 API 设计 | COMP、ART、OPT、INT | `chemos-computation-product-design.md` 5 |
| 迁移设计 8 Computation Service | COMP | `chemos-computation-product-design.md` 6 |
| 迁移设计 9 Optimizer Service | OPT | `chemos-computation-product-design.md` 7 |
| 迁移设计 10 前端可视化 | 前端信息架构 | `chemos-computation-product-design.md` 8 |
| 迁移设计 11 SpecLabOS | INT | `chemos-computation-product-design.md` 9 |
| 迁移设计 12 安全、权限和审计 | AUD、权限矩阵 | `chemos-computation-product-design.md` 10 |
| 迁移设计 14 实施路线 | MVP 和阶段计划 | `chemos-computation-product-design.md` 12 |

## 15. 开放问题

| ID | 问题 | 默认假设 | 决策人 |
|---|---|---|---|
| Q1 | MVP 重试策略是重置原 run 还是创建新 run | 创建新 run，并通过 `retry_of_run_id` 关联 | 技术负责人 |
| Q2 | campaign 是否需要项目空间隔离 | MVP 先按创建人和管理员权限，后续加 project/team | 产品负责人 |
| Q3 | artifact 存储是否直接上对象存储 | MVP 用 `.runtime/outputs`，后续迁移 S3/MinIO | 运维负责人 |
| Q4 | AiiDA worker 是否独立 repo | 先放在 `backend/app/workers`，部署时独立进程 | 技术负责人 |
| Q5 | SpecLabOS 结果回写用 webhook 还是 polling | MVP 先 polling，后续支持 webhook | 平台负责人 |
