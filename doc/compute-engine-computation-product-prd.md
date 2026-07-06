# ComputeEngine 计算智能模块产品需求文档 PRD

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | Current product requirements aligned to implemented code |
| 日期 | 2026-07-02 |
| 关联文档 | `doc/compute-engine-computation-product-design.md`、`doc/compute-engine-computation-migration-design.md`、`doc/compute-engine-computation-progress-and-plan.md` |
| 代码范围 | `backend/app`、`backend/tests`、`frontend/src`、`scripts/run_compute_engine.sh` |

本文定义 Poly_Agent 中 ComputeEngine 计算智能模块的当前产品需求、已交付范围和剩余缺口。它以当前代码为基线，而不是早期设计假设。

## 2. 背景和当前事实

### 2.1 当前代码事实

| 领域 | 当前状态 |
|---|---|
| 计算任务 | 已有 computation API、worker、artifact、audit、mock/local/ORCA fixture adapter |
| 本地计算 | 已支持 RDKit/OpenBabel 结构生成和 xTB subprocess adapter |
| ORCA/ComputeEngine | 已支持受控 `ORCA_COMPUTE_ENGINE_LASER` fixture/parser 模式；真实 external executor 未接入 |
| 优化闭环 | 已有 campaign/candidate/suggestion/observation，fallback 和 tanimoto planner，自动 observation/下一轮 suggestion |
| 集成状态 | 已有 integration status 探测和 service integration 后端配置管理 |
| 前端 | 已有 computation submit/runs、campaign list/detail、Tool Services 状态页 |
| 测试 | 已覆盖 computation service、local adapters、ORCA fixture、optimization、integration config |

### 2.2 仍需解决的问题

- AUTH 开启后，computation、campaign、artifact、audit 仍缺完整 owner 权限隔离。
- candidate 导入只支持 JSON/ComputeEngine demo，缺 CSV 和失败行/重复行报告。
- suggestion schema 有 `rejected/failed`，但还没有 reject/failed API 和原因记录。
- 手工 observation 还未按 campaign objectives 严格校验字段。
- worker 还缺 heartbeat、stale running reclaim 和运行中 cancel 的资源终止语义。
- ORCA/ComputeEngine 目前是 fixture/parser 验证，真实 HPC/AiiDA/external executor 尚未实现。
- Tool Services 前端还不能管理后端已实现的 integration config。

## 3. 产品目标

| ID | 目标 | 当前达成情况 |
|---|---|---|
| G1 | 建立可追踪的计算任务中心 | 已达成 MVP |
| G2 | 建立 artifact 资产体系 | 已达成 MVP，含 checksum/parser/download audit |
| G3 | 打通优化 campaign 闭环 | 已达成 MVP，含自动 observation |
| G4 | 支持轻量真实本地计算 | 已达成 MVP，local structure/local xTB 已实现 |
| G5 | 保留外部系统边界 | 部分达成，ORCA/SpecLabOS/AiiDA 仍需真实 adapter |
| G6 | 权限和审计可追责 | 部分达成，事件已记录，权限和 actor metadata 待补 |

## 4. 非目标

| ID | 非目标 | 原因 |
|---|---|---|
| N1 | 让前端传 shell command、本地路径或任意 job script | 安全和审计风险不可接受 |
| N2 | 把 AiiDA PostgreSQL 当成 Poly_Agent 主业务库 | AiiDA 是外部 provenance 系统，业务只保存引用和摘要 |
| N3 | 把 ORCA license/HPC key/SpecLabOS token 写入业务库 | 敏感配置只能通过环境变量或 secret reference |
| N4 | 迁移 ComputeEngine Streamlit/SiLA 仪器层作为主界面 | Poly_Agent 已有 Vue/FastAPI 架构，实验设备由 SpecLabOS 承担 |
| N5 | 第一版强依赖 Atlas/Olympus | 依赖重且未在当前环境完整验证，当前用轻量 tanimoto 替代 |

## 5. 用户和角色

| 角色 | 需求 |
|---|---|
| 研发用户 | 提交 mock/local/ORCA fixture 计算，查看状态、结果、artifact 和失败原因 |
| 优化用户 | 创建 campaign、导入候选、生成 suggestion、提交计算、生成 observation |
| 计算管理员 | 查看 worker、依赖、外部服务状态，配置集成摘要 |
| 系统管理员 | 管理用户、权限、集成配置和审计日志 |
| 实验平台用户 | 后续将 suggestion 提交 SpecLabOS 并回写 experiment observation |

## 6. 当前产品范围

### 6.1 已交付 MVP 范围

| 模块 | 已交付能力 |
|---|---|
| Computation | 创建、列表、详情、取消、重试、worker 执行、timeline |
| Workflow | `MOCK_XTB_ONLY`、`MOCK_LASER`、`LOCAL_STRUCTURE`、`LOCAL_XTB`、`ORCA_COMPUTE_ENGINE_LASER` fixture |
| Artifact | metadata、preview、structure、spectrum、download、checksum、parser metadata |
| Local adapter | RDKit/OpenBabel 结构生成，xTB fake/real subprocess 执行边界 |
| Optimization | campaign/candidate/suggestion/observation/history |
| Planner | fallback planner、轻量 tanimoto planner、planner request/response 快照 |
| Automation | completed computation 可自动生成 observation 和下一轮 suggestion |
| Integrations | `/integrations/status`、integration config list/upsert/check 后端 API |
| Frontend | computation submit/runs、campaign list/detail、Tool Services status |

### 6.2 未完成但仍属 P0/P1 的范围

| 模块 | 缺口 |
|---|---|
| 权限 | owner 过滤、详情/下载权限、audit 查询权限 |
| 导入 | CSV 支持、失败行报告、重复行报告 |
| 状态机 | suggestion reject/failed API，campaign lifecycle API |
| Observation | 按 objectives 校验 required/allowed values |
| Worker | heartbeat、stale reclaim、running cancel |
| 前端 | integration config 管理、结构 viewer、前端 e2e |
| ORCA/ComputeEngine | external executor、真实 raw output parser 样本验证 |

## 7. 核心用户流程

### 7.1 提交并查看计算任务

```text
用户选择 workflow/engine
  -> 填写 molecule/parameters/resources
  -> POST /api/v1/computations
  -> worker 领取 queued run
  -> adapter 生成 result/artifacts/error
  -> 用户在 /computations/runs 查看 timeline、summary、artifact、spectrum
```

关键要求：
- workflow/engine/method/solvent/resource 必须由后端白名单校验。
- artifact 下载必须走 API blob 请求，以便携带 Authorization 并写下载审计。
- 失败任务要展示 `error_code/message/retryable`。

### 7.2 创建优化闭环

```text
创建 campaign
  -> 导入 candidate
  -> 生成 suggestion
  -> suggestion 提交 computation
  -> worker 完成 laser workflow
  -> 生成 observation
  -> history 记录本轮闭环
```

关键要求：
- suggestion 必须保存 planner request/response 快照。
- observation 必须能追溯到 candidate、suggestion、source run。
- 自动闭环必须默认关闭，由 `planner_config.automation` 启用。

### 7.3 后续实验验证流程

```text
用户选择 suggestion
  -> 提交 SpecLabOS workflow preset
  -> 保存 workflow_run_id
  -> polling 或 webhook 同步结果
  -> 写入 experiment observation
```

当前代码状态：字段和集成配置已有基础，真实 SpecLabOS client/API 尚未实现。

## 8. 功能需求

优先级定义：
- P0: 演示转内测前必须补齐。
- P1: 第一批增强，影响真实使用质量。
- P2: 外部系统或生产化增强。

### 8.1 计算任务

| ID | 优先级 | 需求 | 当前状态 |
|---|---|---|---|
| COMP-001 | P0 | 创建计算任务 | 已完成 |
| COMP-002 | P0 | 查询任务列表 | 部分完成，缺 owner 过滤 |
| COMP-003 | P0 | 查询任务详情 | 部分完成，缺详情权限校验 |
| COMP-004 | P0 | worker 推进状态 | 已完成 MVP，缺 heartbeat |
| COMP-005 | P0 | 取消任务 | 部分完成，缺运行中资源终止 |
| COMP-006 | P0 | 重试任务 | 已完成 MVP，缺 retry policy |
| COMP-007 | P1 | local 结构生成 | 已完成 MVP |
| COMP-008 | P1 | local xTB | 已完成 MVP |
| COMP-009 | P1/P2 | ORCA/ComputeEngine external executor | 未完成，已有 fixture/parser |
| COMP-010 | P2 | AiiDA 状态同步 | 未完成 |

### 8.2 Artifact 和结果展示

| ID | 优先级 | 需求 | 当前状态 |
|---|---|---|---|
| ART-001 | P0 | 登记 artifact 元数据 | 已完成 |
| ART-002 | P0 | artifact 下载和审计 | 已完成短期方案 |
| ART-003 | P0 | parser metadata | 已完成 MVP |
| ART-004 | P1 | structure/spectrum 结构化展示 | 部分完成 |
| ART-005 | P1 | 大文件下载 token/stream | 未完成 |
| ART-006 | P2 | 对象存储和归档 | 未完成 |

### 8.3 优化 campaign

| ID | 优先级 | 需求 | 当前状态 |
|---|---|---|---|
| OPT-001 | P0 | 创建 campaign | 已完成 MVP |
| OPT-002 | P0 | JSON/CSV candidate 导入和报告 | 部分完成，缺 CSV/report |
| OPT-003 | P0 | 写入 observation | 部分完成，缺 objective 校验 |
| OPT-004 | P0 | fallback suggestion | 已完成 |
| OPT-005 | P0 | suggestion 状态流转 | 部分完成，缺 reject/failed API |
| OPT-006 | P1 | tanimoto planner | 已完成轻量版 |
| OPT-007 | P1 | 自动 observation 和下一轮 suggestion | 已完成 MVP |
| OPT-008 | P1 | configurable computation preset | 未完成，当前 submit 硬编码 `MOCK_LASER` |
| OPT-009 | P2 | Atlas/Olympus adapter | 未完成 |

### 8.4 集成和实验

| ID | 优先级 | 需求 | 当前状态 |
|---|---|---|---|
| INT-001 | P0 | 集成状态展示 | 已完成 MVP |
| INT-002 | P1 | integration config 后端管理 | 已完成后端 MVP |
| INT-003 | P1 | integration config 前端管理 | 未完成 |
| INT-004 | P2 | SpecLabOS workflow 提交 | 未完成 |
| INT-005 | P2 | AiiDA worker | 未完成 |

### 8.5 权限和审计

| ID | 优先级 | 需求 | 当前状态 |
|---|---|---|---|
| AUD-001 | P0 | 关键操作审计 | 部分完成 |
| AUD-002 | P0 | request_id 追踪 | 已完成 MVP |
| AUD-003 | P0 | actor role/ip/source | 部分完成 |
| AUD-004 | P0 | owner 权限隔离 | 未完成 |
| AUD-005 | P1 | 审计查询页面 | 后端列表已有，前端未做专门页面 |

## 9. 前端信息架构

| 页面 | 路由 | 当前能力 |
|---|---|---|
| 提交计算 | `/computations/submit` | 提交 mock/local/ORCA fixture workflow |
| 计算任务中心 | `/computations/runs` | 列表、筛选、详情 drawer、timeline、artifact、spectrum、下载 |
| Campaign 列表 | `/optimization/campaigns` | 创建 campaign、导入 demo、生成 suggestion |
| Campaign 详情 | `/optimization/campaigns/:campaignId` | candidates/suggestions/observations/history、submit computation、create observation |
| Tool Services | `/tools` | 集成状态展示 |
| 系统管理 | `/database` | admin 路由 |

## 10. 数据对象产品定义

| 对象 | 说明 | 关键字段 |
|---|---|---|
| `computation_run` | 计算任务运行记录 | `run_id`、`workflow_type`、`engine`、`status`、`steps`、`artifact_ids`、`result_summary`、`error`、`external_refs` |
| `computation_artifact` | 计算产物元数据 | `artifact_id`、`run_id`、`step_key`、`artifact_type`、`storage_uri`、`checksum_sha256`、`parser_name/version` |
| `optimization_campaign` | 优化任务 | `campaign_id`、`status`、`planner_type`、`objectives`、`planner_config` |
| `optimization_candidate` | 候选分子 | `candidate_id`、`candidate_key`、`smiles`、`descriptors` |
| `optimization_suggestion` | planner 推荐 | `suggestion_id`、`candidate_id`、`iteration_index`、`status`、`planner_payload`、`submitted_run_id` |
| `optimization_observation` | 观测值 | `observation_id`、`candidate_id`、`suggestion_id`、`source_type`、`source_run_id`、`values` |
| `service_integration` | 外部服务配置摘要 | `service_key`、`enabled`、`endpoint`、`config_summary`、`secret_refs`、`last_status` |
| `audit_event` | 审计事件 | `event_id`、`event_type`、`actor_user_id`、`actor_role`、`request_id`、`entity_type/id` |

## 11. 状态定义

### 11.1 computation 状态

| 状态 | 含义 | 当前支持 |
|---|---|---|
| queued | 已创建，等待 worker | 是 |
| running | worker 已领取执行 | 是 |
| completed | 成功完成 | 是 |
| failed | 执行或解析失败 | 是 |
| cancelled | 用户取消 | 是 |

### 11.2 campaign 状态

| 状态 | 含义 | 当前支持 |
|---|---|---|
| draft | 新建未导入候选 | schema 支持 |
| running | 已导入候选或运行中 | 是 |
| paused | 暂停 | schema 支持，缺 API |
| completed | 完成 | schema 支持，缺 API |
| failed | 失败 | schema 支持，缺 API |
| archived | 归档 | schema 支持，缺 API |

### 11.3 suggestion 状态

| 状态 | 含义 | 当前支持 |
|---|---|---|
| suggested | 已推荐 | 是 |
| submitted | 已提交 computation | 是 |
| evaluated | 已产生 observation | 是 |
| rejected | 人工拒绝 | schema 支持，缺 API |
| failed | 提交或执行失败 | schema 支持，缺 API |

## 12. 审计要求

### 12.1 当前事件类型

| 事件 | 说明 |
|---|---|
| `computation.created` | 创建计算任务 |
| `computation.status_changed` | worker 状态变更 |
| `computation.cancelled` | 取消任务 |
| `computation.retried` | 重试任务 |
| `artifact.registered` | worker 登记 artifact |
| `artifact.downloaded` | 下载 artifact |
| `campaign.created` | 创建 campaign |
| `candidate.imported` | 导入候选 |
| `suggestion.generated` | 生成 suggestion |
| `suggestion.submitted_computation` | suggestion 提交计算 |
| `observation.created` | 创建 observation |
| `automation.observation_created` | 自动创建 observation |
| `automation.suggestion_triggered` | 自动触发下一轮 suggestion |
| `integration_config.updated` | 更新集成配置 |
| `integration_config.checked` | 检查集成配置 |

### 12.2 待补审计要求

- 权限拒绝、reject/failed suggestion、campaign lifecycle、external job submit/poll/cancel 需要补事件。
- audit event 应记录 client ip、user agent/source。
- optimization worker/automation 的 actor role 不应固定为 `user`。

## 13. MVP 发布门禁

当前已满足：
- computation create/list/detail/cancel/retry 可用。
- worker 可执行 mock/local/ORCA fixture adapter。
- artifact metadata、preview、download、checksum、parser metadata 可用。
- campaign/candidate/suggestion/observation 主流程可用。
- P0 主路径审计事件已有。

内测前仍必须补齐：
- owner 权限过滤和 artifact 下载权限。
- CSV 导入报告。
- suggestion reject/failed API。
- observation objective 校验。
- worker heartbeat 或至少 stale running 管理策略。

## 14. 开放问题

| ID | 问题 | 当前建议 |
|---|---|---|
| Q1 | campaign 是否需要 project/team 维度 | 当前先做 created_by/admin，后续扩 project/team |
| Q2 | ORCA external 先接 HPC 脚本还是 AiiDA | 先做受控 fake/external executor 边界，再决定 HPC/AiiDA |
| Q3 | artifact 是否迁移对象存储 | 当前本地 `.runtime/outputs`，生产化再引入 S3/MinIO |
| Q4 | SpecLabOS 结果用 webhook 还是 polling | 第一版 polling，后续支持 webhook |
| Q5 | Atlas/Olympus 是否作为主依赖 | 不进入主后端，作为独立可选 optimizer adapter |
