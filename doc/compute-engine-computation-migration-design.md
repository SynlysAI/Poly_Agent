# ComputeEngine 计算、优化与可视化能力迁移设计

## 1. 文档定位

| 字段 | 内容 |
|---|---|
| 文档状态 | Current migration status and remaining roadmap |
| 日期 | 2026-07-02 |
| 目标 | 记录 ComputeEngine 可迁移能力在 Poly_Agent 中的实际落地状态和后续迁移边界 |
| 关联文档 | `doc/compute-engine-computation-product-prd.md`、`doc/compute-engine-computation-product-design.md`、`doc/compute-engine-computation-progress-and-plan.md` |

本文不再作为从零开始的开发计划，而是作为 ComputeEngine 参考项目能力向当前 Poly_Agent 代码迁移的状态说明。

## 2. 当前结论

ComputeEngine 中最有价值的能力不是原样迁移 UI 或 SiLA 服务，而是迁移以下思想：
- computation workflow 分步骤执行。
- provenance 外部化，业务库只保存引用和摘要。
- artifact/result/parser 元数据化。
- campaign/suggestion/observation 闭环。
- planner 可替换。
- 光谱和 gain 等结果进入统一结果资产。

当前 Poly_Agent 已经落地了其中的 MVP 主干：
- computation run + worker + adapter registry。
- mock/local structure/local xTB/ORCA fixture adapter。
- artifact metadata、preview、download、structure、spectrum。
- campaign/candidate/suggestion/observation/history。
- fallback/tanimoto planner。
- completed computation 自动 observation 和下一轮 suggestion。
- integration status 和 service integration 后端配置。

仍未落地的 ComputeEngine 高复杂度部分：
- AiiDA WorkChain 真实提交和状态同步。
- ORCA/HPC external executor。
- CREST/ORCA 多步骤真实 raw output 解析。
- SpecLabOS 实验 workflow 提交和结果回写。

## 3. ComputeEngine 能力迁移映射

| ComputeEngine 能力 | 参考来源 | Poly_Agent 当前落点 | 状态 |
|---|---|---|---|
| 计算任务生命周期 | ComputeEngine workflow 思路 | `computation_runs`、`ComputationWorker` | 已落地 MVP |
| step timeline | AiiDA WorkChain outline | adapter `step_labels` + run `steps` | 已落地 MVP |
| artifact/result asset | AiiDA retrieved/output 思路 | `computation_artifacts` + `.runtime/outputs` | 已落地 MVP |
| 本地结构生成 | OpenBabel/RDKit | `LocalStructureAdapter` | 已落地 MVP |
| xTB 轻量计算 | xTB/CREST 前处理思路 | `LocalXtbAdapter` | 已落地 MVP |
| ORCA laser workflow | `laser_workchain.py` | `OrcaComputeEngineLaserAdapter` fixture/parser | 部分落地 |
| spectra/gain parser | ComputeEngine spectra 后处理 | `compute_engine_laser_parser.py` | 部分落地，需真实样本 |
| optimizer campaign | 内置优化闭环 | OptimizationService | 已落地 MVP |
| fallback planner | 本地规则策略 | `planner_adapters.py` | 已落地 |
| Tanimoto planner | 相似度规划思路 | 轻量 `tanimoto` planner | 已落地轻量版 |
| AiiDA provenance | AiiDA process UUID | `external_refs.aiida_process_uuid` 占位 | 未接真实同步 |
| SpecLabOS 实验验证 | 用户现有平台 | integration config + suggestion 字段占位 | 未接真实提交 |
| ComputeEngine SiLA 仪器层 | SiLA servers | 不迁移，由 SpecLabOS 承担 | 明确不迁移 |
| Streamlit UI | ComputeEngine demo UI | 不迁移，使用 Vue 页面 | 明确不迁移 |

## 4. 当前 Poly_Agent 落地结构

### 4.1 后端模块

```text
backend/app
  api/v1/endpoints/
    computations.py
    optimization.py
    integrations.py
  schemas/
    computation.py
    optimization.py
    integrations.py
  services/
    computation_service.py
    optimization_service.py
    planner_adapters.py
    integration_status_service.py
    integration_config_service.py
  computation_adapters/
    base.py
    registry.py
    mock.py
    local_structure.py
    local_xtb.py
    orca_compute_engine_laser.py
    compute_engine_laser_parser.py
  workers/
    computation_worker.py
  infra/
    computation_repositories.py
    demo_store.py
    mongo.py
```

### 4.2 前端模块

```text
frontend/src
  api/polyAgentApi.js
  views/
    ComputationSubmitView.vue
    ComputationRunsView.vue
    CampaignsView.vue
    CampaignDetailView.vue
    ToolServicesView.vue
```

### 4.3 测试覆盖

```text
backend/tests/
  test_computation_mvp.py
  test_computation_service.py
  test_local_structure_adapter.py
  test_local_xtb_adapter.py
  test_orca_compute_engine_laser_workflow.py
  test_optimization_service.py
  test_integration_config_service.py
```

## 5. 迁移后的目标架构

```text
Poly_Agent Vue
  -> FastAPI API
      -> ComputationService
          -> Mongo/demo store run state
          -> artifact metadata
      -> ComputationWorker
          -> adapter registry
          -> local adapters
          -> ORCA/ComputeEngine external adapter later
          -> AiiDA adapter later
      -> OptimizationService
          -> fallback/tanimoto planner
          -> custom planner adapter later
      -> IntegrationConfigService
          -> endpoint/config summary
          -> secret refs only
      -> Artifact store
          -> local .runtime/outputs now
          -> object storage later

External systems
  -> RDKit/OpenBabel/xTB optional local dependencies
  -> ORCA/HPC/AiiDA external computation environment later
  -> SpecLabOS experiment workflow later
  -> custom optional optimizer service later
```

设计边界：
- Poly_Agent 业务库保存可查询业务状态、摘要、checksum 和外部引用。
- AiiDA 保留完整 provenance，不复制到 MongoDB。
- SpecLabOS 保留设备和实验 workflow 细节，Poly_Agent 保存 workflow_run_id 和 observation 摘要。
- 外部优化器如果接入，应在独立 optimizer 环境，不进入主 FastAPI 依赖。

## 6. 迁移后的数据模型

### 6.1 Computation

已落地：
- `computation_runs`
- `computation_artifacts`
- `audit_events`

关键迁移结果：
- ComputeEngine/AiiDA 的步骤式 workflow 映射为 run `steps`。
- AiiDA retrieved/output 文件思想映射为 `ArtifactSpec` + artifact metadata。
- 外部 process/job id 映射到 `external_refs`，当前字段已有占位。

仍需补：
- AiiDA UUID/status/profile 摘要真实写入。
- ORCA/HPC job id/queue/submitted_at/polled_at。
- storage_uri 从绝对本地路径演进到 backend-owned scheme。

### 6.2 Optimization

已落地：
- `optimization_campaigns`
- `optimization_candidates`
- `optimization_suggestions`
- `optimization_observations`

关键迁移结果：
- ComputeEngine optimizer 状态从 pickle/进程内对象迁移为可查询集合。
- planner 输入输出保存为 request/response snapshot。
- suggestion、computation run、observation 已可通过 id 追踪。

仍需补：
- CSV import report。
- suggestion reject/failed 状态操作。
- campaign lifecycle 操作。
- SpecLabOS experiment observation 回写。

### 6.3 Integration

已落地：
- `service_integrations`
- `/integrations/status`
- `/integrations/configs`
- `/integrations/configs/{service_key}/check`

关键迁移结果：
- 外部系统可用性从临时说明迁移为 API 状态摘要。
- endpoint/config summary/secret refs 持久化。
- 明文密钥字段被拒绝。

仍需补：
- 前端 config 管理。
- 真实 SpecLabOS/AiiDA/ORCA 客户端使用这些配置。

## 7. API 迁移状态

| API 组 | 当前状态 | 缺口 |
|---|---|---|
| Computations | 已实现 create/list/detail/cancel/retry/artifacts | owner 权限、heartbeat/cancel 语义 |
| Artifacts | 已实现 metadata/preview/structure/spectrum/download | 大文件 token/stream、对象存储 |
| Optimization | 已实现 campaign/candidate/suggestion/observation/history | CSV、reject/failed、campaign lifecycle、preset |
| Integrations | 后端 status/config 已实现 | 前端 CRUD、真实客户端 |
| Auth/Admin | 已有登录、注册、用户管理基础 | computation/optimization owner 过滤需接入 |

## 8. Computation adapter 迁移状态

### 8.1 已完成 adapter

Mock:
- 用于 smoke/demo。
- 生成 structure/result/log/error artifact。

Local structure:
- RDKit 优先，OpenBabel 兜底。
- 输出 `input_json`、`structure_json`、`xyz`、`sdf`、`log_text`、`error_json`。
- 缺依赖时任务 failed 且 retryable。

Local xTB:
- 复用 structure builder 生成 input。
- 使用 `subprocess.run`，不拼 shell。
- 白名单参数：method、charge、multiplicity、solvent、cores。
- 捕获 stdout/stderr/output/result/error artifact。
- 覆盖缺依赖、成功、非零退出、timeout。

ORCA/ComputeEngine fixture:
- 受控 workflow preset。
- `disabled/fixture/external` execution mode。
- fixture 模式生成 raw spectra/gain 并解析为 `compute_engine_spectrum.v1`、`compute_engine_gain.v1`、`compute_engine_laser_result.v1`。
- external 模式目前明确返回 `ORCA_EXTERNAL_EXECUTOR_NOT_IMPLEMENTED`。

### 8.2 下一步 adapter

ORCA external executor:
- 后端配置 job template，不从前端接命令。
- fake executor 测试 submit/poll/cancel/success/fail。
- 保存 external refs。
- 复用现有 parser。

AiiDA adapter:
- 提交 AiiDA WorkChain。
- 保存 process UUID 和 state。
- 周期同步状态。
- 从 retrieved/output nodes 生成 artifact 摘要。

SpecLabOS adapter/client:
- suggestion 提交 experiment preset。
- 保存 workflow_run_id。
- polling 或 webhook 同步实验结果。
- 创建 experiment observation。

## 9. Optimizer 迁移状态

### 9.1 已完成

Fallback planner：
- 稳定选择未评价、未 pending 的候选。

Tanimoto planner：
- 使用 descriptor bits 计算相似度。
- 参考最佳 observation candidate。
- 无 descriptor/observation 时给出 reason。

Descriptor：
- RDKit Morgan fingerprint。
- RDKit 不可用时 SMILES hash fallback。

Automation：
- `auto_create_observation`。
- `auto_generate_suggestion`。
- `suggestion_batch_size`。
- `observation_mapping`。

### 9.2 未完成

外部优化器：
- 不进入主依赖。
- 后续可作为独立 optimizer adapter。
- 输入仍应使用 `PlannerRequest`，输出仍应使用 `PlannerResponse`。

BoTorch/native optimization：
- 中长期可扩展为独立 planner 封装。
- 当前不属于 MVP/P1。

## 10. 前端迁移状态

已落地：
- ComputeEngine Streamlit UI 不迁移。
- Vue 页面已经覆盖计算提交、计算任务中心、campaign 列表和详情、服务状态。
- 光谱已经有基础 SVG 预览。
- artifact 下载使用 API blob。

仍需补：
- 结构 viewer 或更好的结构表。
- integration config 管理。
- CSV import UI 和报告展示。
- suggestion reject/failed 操作。
- Playwright 端到端测试。

## 11. SpecLabOS 集成边界

SpecLabOS 继续负责：
- 设备连接。
- 实验 workflow 编排。
- SmartAccess。
- 原始实验日志。

Poly_Agent 只负责：
- 从 suggestion 提交受控 experiment preset。
- 保存 `submitted_experiment_run_id` 或 external refs。
- 同步实验结果摘要。
- 写入 `source_type="experiment"` observation。
- 在 campaign history 中展示计算和实验来源。

当前状态：
- 字段和 service integration 配置基础已存在。
- 真实 submit/sync client 未实现。

## 12. 安全迁移规则

已实现规则：
- workflow/engine/method/solvent 白名单。
- Pydantic request body 禁止未知字段。
- integration config 拒绝敏感字段。
- artifact path 必须在 `outputs_root`。
- xTB/ORCA fixture 不接受用户 shell command。

待补规则：
- owner/admin 权限过滤。
- audit client ip/user agent。
- running cancel 对 local subprocess/external job 生效。
- external executor 的 job spec 只能由后端配置生成。

## 13. 实施路线现状

### 已完成的原 Phase

| 原路线 | 当前状态 |
|---|---|
| Phase 1: 计算任务基础闭环 | 已完成 MVP |
| Phase 2: 本地轻量计算 adapter | 已完成 MVP |
| Phase 5: Optimization Campaign fallback | 已完成 |
| Phase 5: Tanimoto planner | 已完成轻量版 |
| Phase 6: 计算驱动优化闭环 | 已完成 MVP |
| service_integrations 后端配置 | 已完成后端 MVP |
| ORCA/ComputeEngine parser fixture | 已完成 fixture MVP |

### 需要继续推进的路线

| 新阶段 | 内容 | 优先级 |
|---|---|---|
| Phase A | 权限、CSV、suggestion 状态、observation 校验、worker heartbeat | P0 |
| Phase B | local adapter 硬化、ORCA external executor、workflow preset、前端可视化 | P1 |
| Phase C | campaign lifecycle、planner 约束、SpecLabOS 实验提交 | P1/P2 |
| Phase D | integration config 前端、审计增强、对象存储 | P1/P2 |

详细任务见 `doc/compute-engine-computation-progress-and-plan.md`。

## 14. 验证计划

当前可运行后端验证：

```bash
PYTHONPATH=backend python -m unittest \
  backend.tests.test_computation_mvp \
  backend.tests.test_computation_service \
  backend.tests.test_local_structure_adapter \
  backend.tests.test_local_xtb_adapter \
  backend.tests.test_orca_compute_engine_laser_workflow \
  backend.tests.test_optimization_service \
  backend.tests.test_integration_config_service
```

后续新增验证：
- AUTH 开启后的跨用户访问拒绝。
- CSV 导入失败行报告。
- reject/failed suggestion 状态流转。
- fake ORCA external executor。
- fake SpecLabOS client。
- 前端 Playwright 截图和下载验证。

## 15. 关键设计决策

### Decision 1: 不迁移 ComputeEngine Streamlit 前端

Poly_Agent 已有 Vue/FastAPI 架构，ComputeEngine UI 只作为参考。当前已通过 Vue 页面承载计算和优化流程。

### Decision 2: 不迁移 ComputeEngine SiLA 仪器层

用户已有 SpecLabOS。ComputeEngine SiLA 仪器服务不作为 Poly_Agent 的设备控制层。

### Decision 3: AiiDA 独立部署

AiiDA 依赖 PostgreSQL、RabbitMQ、daemon、HPC/code 配置。Poly_Agent 只保存 process UUID、状态摘要和 artifact 索引。

### Decision 4: Adapter 不写业务库

Adapter 返回 `AdapterRunResult` 和 `ArtifactSpec`。ComputationService 统一登记 artifact、更新 run 和写审计。

### Decision 5: 外部优化器不进入主后端依赖

当前以 fallback/tanimoto 保底。未来自研 planner 可作为可选 optimizer adapter 或独立服务。

## 16. 风险和缓解

| 风险 | 当前证据 | 影响 | 缓解 |
|---|---|---|---|
| 权限过滤未完成 | service list/detail 未传 actor scope | AUTH 内测风险 | Phase A 优先补齐 |
| ORCA external 未实现 | adapter external mode 明确返回未实现 | 真实 DFT 不能跑 | 先做 fake executor 边界 |
| AiiDA 部署复杂 | 需要外部 DB/queue/daemon | 迁移周期长 | 业务先保存 external refs，AiiDA 后接 |
| SpecLabOS API 未接 | 仅有配置摘要 | 实验闭环未完成 | fake client + polling 第一版 |
| artifact 本地绝对路径 | `storage_uri` 当前是路径 | 部署信息泄露/迁移困难 | 后续 storage scheme |
| 前端缺 e2e | 复杂 drawer/download/chart 无自动验证 | 回归风险 | 引入 Playwright |

## 17. 最终口径

当前 Poly_Agent 已经吸收 ComputeEngine 的核心产品思想，并形成可运行的计算智能 MVP：计算任务、adapter、artifact、优化闭环和基础可视化已经贯通。后续迁移重点不再是“把 ComputeEngine 代码搬进来”，而是围绕安全、权限、真实外部执行器、实验系统和生产化运维，把已建立的 Poly_Agent 边界继续补完整。
