# ComputeEngine 计算智能模块产品设计文档

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | Current architecture design aligned to implemented code |
| 日期 | 2026-07-02 |
| 关联文档 | `doc/compute-engine-computation-product-prd.md`、`doc/compute-engine-computation-migration-design.md`、`doc/compute-engine-computation-progress-and-plan.md` |
| 代码范围 | `backend/app`、`backend/tests`、`frontend/src` |

本文描述当前 ComputeEngine 计算智能模块在 Poly_Agent 中的实际设计。历史设计中的“新增模块”若已落地，本文按当前实现记录；未落地内容单独列为后续扩展。

## 2. 设计原则

| 原则 | 当前实现 |
|---|---|
| 业务库保持 MongoDB | repository 优先写 MongoDB，不可用时回退 demo JSON store |
| 外部系统只保存引用 | `external_refs`、`service_integrations.secret_refs` 保存摘要或引用，不保存密钥 |
| 输入白名单 | workflow/engine/method/solvent/resource/artifact type 均由 schema 或 registry 限定 |
| adapter 可替换 | `computation_adapters` 定义协议，worker 只负责领取、调用、落库 |
| artifact 由 service 统一登记 | adapter 只产出 `ArtifactSpec`，service 做路径边界、checksum、审计 |
| planner 与 service 分层 | optimization service 构造 request，`planner_adapters.py` 派发策略 |
| 自动化默认可控 | 自动 observation/下一轮 suggestion 由 `planner_config.automation` 显式开启 |

## 3. 系统上下文

```text
Vue frontend
  -> FastAPI /api/v1
      -> auth/admin/health
      -> computations API
          -> ComputationService
          -> ComputationWorker
              -> adapter registry
              -> mock/local_structure/local_xtb/orca_compute_engine_fixture
          -> artifact preview/download/spectrum/structure
      -> optimization API
          -> OptimizationService
          -> fallback/tanimoto planner adapters
      -> integrations API
          -> status probes
          -> service integration config
  -> MongoDB or demo JSON store
  -> .runtime/outputs artifact files
```

外部系统边界：
- RDKit/OpenBabel/xTB 是可选本地依赖，不阻塞应用启动。
- ORCA/ComputeEngine 目前支持 fixture/parser；external executor 未实现。
- AiiDA、SpecLabOS、Atlas/Olympus 仍为后续 adapter，不进入主后端必需依赖。

## 4. 组件职责

| 组件 | 负责 | 不负责 |
|---|---|---|
| FastAPI backend | API、权限入口、业务服务、审计、状态聚合 | 直接接受用户 shell/script |
| ComputationService | run/artifact/audit 持久化、路径边界、retry/cancel | workflow 内部计算细节 |
| ComputationWorker | 原子领取 queued run、调用 adapter、状态落库、触发自动闭环 | 用户认证和 UI |
| ComputationAdapter | workflow 输入校验、执行、产物描述、结果摘要 | 直接写数据库 |
| OptimizationService | campaign/candidate/suggestion/observation、planner request、automation | 执行计算或实验 |
| Planner adapters | fallback/tanimoto 推荐策略 | 修改业务状态 |
| Integration services | 状态探测、配置摘要、安全校验 | 保存明文密钥 |
| Frontend | 提交、查询、展示、下载、用户操作 | 绕过后端读取本地文件 |

## 5. 数据设计

### 5.1 Collections

| Collection | 用途 | 当前状态 |
|---|---|---|
| `computation_runs` | 计算任务状态 | 已实现 |
| `computation_artifacts` | artifact 元数据 | 已实现 |
| `optimization_campaigns` | 优化 campaign | 已实现 |
| `optimization_candidates` | 候选分子 | 已实现 |
| `optimization_suggestions` | 推荐记录 | 已实现 |
| `optimization_observations` | observation | 已实现 |
| `service_integrations` | 外部服务配置摘要 | 已实现 |
| `audit_events` | 审计事件 | 已实现 |

### 5.2 `computation_runs`

核心字段：

```json
{
  "run_id": "comp_20260702_xxx",
  "retry_of_run_id": null,
  "workflow_type": "LOCAL_XTB",
  "engine": "XTB",
  "status": "queued",
  "molecule": {"smiles": "CCO", "name": "ethanol"},
  "parameters": {"charge": 0, "multiplicity": 1, "method": "GFN2-xTB", "solvent": null},
  "resources": {"num_cores": 2, "memory_mb": 4096, "max_wallclock_seconds": 1800},
  "external_refs": {"worker_id": null, "aiida_process_uuid": null, "speclabos_run_id": null},
  "steps": [],
  "artifact_ids": [],
  "result_summary": {},
  "error": null,
  "created_by": "user_id",
  "campaign_id": null,
  "suggestion_id": null
}
```

当前状态枚举：`queued`、`running`、`completed`、`failed`、`cancelled`。

### 5.3 Workflow 和 Engine

当前支持组合：

| workflow_type | engine | adapter |
|---|---|---|
| `MOCK_XTB_ONLY` | `MOCK` | `MockComputationAdapter` |
| `MOCK_LASER` | `MOCK` | `MockComputationAdapter` |
| `LOCAL_STRUCTURE` | `LOCAL`、`RDKit`、`OPENBABEL` | `LocalStructureAdapter` |
| `LOCAL_XTB` | `XTB` | `LocalXtbAdapter` |
| `ORCA_COMPUTE_ENGINE_LASER` | `ORCA` | `OrcaComputeEngineLaserAdapter` fixture/parser |

不支持的组合在 create run 时返回 400。

### 5.4 `computation_artifacts`

核心字段：

```json
{
  "artifact_id": "art_20260702_xxx",
  "run_id": "comp_20260702_xxx",
  "step_key": "XTB_RUN",
  "artifact_type": "log_text",
  "name": "xtb.stdout.log",
  "storage_uri": "/abs/path/.runtime/outputs/computations/.../work/xtb.stdout.log",
  "mime_type": "text/plain",
  "size_bytes": 1234,
  "checksum_sha256": "...",
  "parser_name": "local_xtb_adapter",
  "parser_version": "0.1.0",
  "metadata": {"source": "local_xtb", "source_step": "XTB_RUN"}
}
```

当前 artifact type：
- `result_json`
- `log_text`
- `structure_json`
- `input_json`
- `error_json`
- `sdf`
- `xyz`
- `spectrum_json`
- `metrics_json`

路径安全：登记和读取时都要求文件位于 `settings.outputs_root` 下。

### 5.5 Optimization 对象

`optimization_campaigns`：
- `campaign_id`
- `name`
- `status`
- `planner_type`: `fallback` 或 `tanimoto`
- `objectives`
- `planner_config`
- `created_by`

`optimization_candidates`：
- `candidate_id`
- `candidate_key`
- `smiles`
- `parameters`
- `descriptors`
- `metadata`

Descriptor schema 当前为 `candidate_descriptor.v1`：
- RDKit 可用时生成 Morgan fingerprint。
- RDKit 不可用时使用稳定 SMILES hash fingerprint 兜底。

`optimization_suggestions`：
- `suggestion_id`
- `candidate_id`
- `iteration_index`
- `status`
- `planner_type`
- `planner_payload.request`
- `planner_payload.response`
- `submitted_run_id`

`optimization_observations`：
- `candidate_id`
- `suggestion_id`
- `source_type`: `computation`、`experiment`、`manual`、`imported`
- `source_run_id`
- `values`
- `raw_result_ref`

### 5.6 `service_integrations`

服务配置摘要，不保存明文密钥：

```json
{
  "service_key": "speclabos",
  "display_name": "SpecLabOS",
  "service_type": "experiment",
  "enabled": false,
  "endpoint": "https://example.internal",
  "config_summary": {"timeout_seconds": 10},
  "secret_refs": {"token": "SPECLABOS_TOKEN"},
  "last_checked_at": null,
  "last_status": "unknown",
  "last_error_summary": null
}
```

敏感字段名如 `token/password/api_key/secret/private_key/credential` 会被拒绝进入 `config_summary` 或 endpoint query。

## 6. API 设计

### 6.1 Computations

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/v1/computations` | 创建 run |
| GET | `/api/v1/computations` | 列表，支持 status/workflow_type/engine/keyword/page/page_size |
| GET | `/api/v1/computations/{run_id}` | 详情 |
| POST | `/api/v1/computations/{run_id}/cancel` | 取消非终态 run |
| POST | `/api/v1/computations/{run_id}/retry` | 从 failed/cancelled 创建 retry run |
| GET | `/api/v1/computations/{run_id}/artifacts` | artifact 列表 |

当前缺口：列表和详情还需按当前用户 owner/admin 做权限过滤。

### 6.2 Artifacts

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/v1/artifacts/{artifact_id}` | 元数据 |
| GET | `/api/v1/artifacts/{artifact_id}/preview` | JSON/text 预览 |
| GET | `/api/v1/artifacts/{artifact_id}/structure` | 结构 JSON |
| GET | `/api/v1/artifacts/{artifact_id}/spectrum` | 光谱/指标数据 |
| GET | `/api/v1/artifacts/{artifact_id}/download` | 下载文件并写审计 |

前端使用 axios blob 下载，不再使用裸 `<a>` 访问。

### 6.3 Optimization

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/v1/optimization/campaigns` | 创建 campaign |
| GET | `/api/v1/optimization/campaigns` | campaign 列表 |
| GET | `/api/v1/optimization/campaigns/{campaign_id}` | campaign 详情 |
| GET | `/api/v1/optimization/campaigns/{campaign_id}/history` | history |
| POST | `/api/v1/optimization/campaigns/{campaign_id}/candidates:import` | JSON 导入候选 |
| POST | `/api/v1/optimization/campaigns/{campaign_id}/candidates:import-compute-engine-demo` | 导入 ComputeEngine demo 候选 |
| POST | `/api/v1/optimization/campaigns/{campaign_id}/suggestions` | 生成 suggestion |
| POST | `/api/v1/optimization/suggestions/{suggestion_id}/submit-computation` | suggestion 转 computation |
| POST | `/api/v1/optimization/campaigns/{campaign_id}/observations` | 手工写 observation |
| POST | `/api/v1/optimization/computations/{run_id}/create-observation` | completed run 转 observation |

当前缺口：
- CSV 导入 endpoint。
- suggestion reject/failed endpoint。
- campaign lifecycle endpoint。
- submit computation preset 配置。

### 6.4 Integrations

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/v1/integrations/status` | 状态探测摘要 |
| GET | `/api/v1/integrations/configs` | 管理员查看配置摘要 |
| PUT | `/api/v1/integrations/configs/{service_key}` | 管理员 upsert 配置摘要 |
| POST | `/api/v1/integrations/configs/{service_key}/check` | 管理员触发健康检查 |

当前缺口：前端 Tool Services 页面尚未接入 config CRUD。

## 7. Computation Worker 设计

### 7.1 当前执行流程

```text
acquire queued run atomically
  -> get adapter by workflow/engine
  -> initialize timeline
  -> build AdapterContext
  -> adapter.validate_input()
  -> adapter.run()
  -> adapter.collect_artifacts()
  -> adapter.parse_result()
  -> service.register_artifacts()
  -> service.finish_acquired_run()
  -> if campaign/suggestion and automation enabled: process_completed_computation()
```

Mongo 可用时使用 `find_one_and_update` 原子领取；不可用时 demo store 使用进程内锁。

### 7.2 Adapter 接口

`backend/app/computation_adapters/base.py` 定义：
- `ArtifactSpec`
- `AdapterContext`
- `AdapterRunResult`
- `ComputationAdapter` protocol
- `build_steps`

Adapter 不写 repository，只返回产物规格和结果摘要。

### 7.3 当前 step keys

Mock:
- `MOCK_VALIDATE`
- `MOCK_EXECUTE`
- `MOCK_RESULT`

Local structure:
- `LOCAL_VALIDATE_INPUT`
- `LOCAL_GENERATE_STRUCTURE`
- `LOCAL_COLLECT_ARTIFACTS`

Local xTB:
- `XTB_VALIDATE_INPUT`
- `XTB_PREPARE_STRUCTURE`
- `XTB_RUN`
- `XTB_PARSE_RESULT`

ORCA/ComputeEngine fixture:
- `COMPUTE_ENGINE_PREPARE_STRUCTURE`
- `COMPUTE_ENGINE_XTB_CREST`
- `COMPUTE_ENGINE_ORCA`
- `COMPUTE_ENGINE_SPECTRA_PARSE`
- `COMPUTE_ENGINE_GAIN_PARSE`

### 7.4 错误处理

错误统一写入 run `error`：

```json
{
  "error_code": "XTB_NOT_AVAILABLE",
  "message": "未检测到 xtb 可执行文件",
  "retryable": true
}
```

失败 run 应生成 `error_json` 和 `log_text` artifact。未捕获 adapter 异常由 worker 转成 `ADAPTER_UNHANDLED_EXCEPTION`。

当前缺口：
- running cancel 不会终止已经启动的 subprocess。
- worker 崩溃后 running run 缺 stale reclaim。
- heartbeat 未实现。

## 8. Optimizer 设计

### 8.1 Planner request/response

OptimizationService 在生成 recommendation 前构造 `PlannerRequest`：
- `schema_version`
- `campaign_id`
- `planner_type`
- `batch_size`
- `candidates`
- `observations`
- `objectives`
- `constraints`

Planner 返回 `PlannerResponse`：
- `schema_version`
- `planner_type`
- `suggestions`
- `iteration_metadata`

每条 suggestion 保存 request/response 快照，保证推荐可复现。

### 8.2 Fallback planner

规则：
1. 排除已有 observation 的 candidate。
2. 排除已有 `suggested/submitted` 且未终结的 candidate。
3. 按 `candidate_key` 稳定排序。
4. 取前 `batch_size` 个。

### 8.3 Tanimoto planner

规则：
1. 找到主 objective 上表现最佳的 observation。
2. 取对应 candidate descriptor 作为 reference。
3. 对未评价 candidate 计算 Tanimoto similarity。
4. 按 score 降序和 candidate_key 升序排序。

无 observation 或 descriptor 时返回低置信 reason，不伪装为高置信推荐。

### 8.4 Observation 写回

当前支持：
- 手工 observation。
- `MOCK_LASER` 或 `ORCA_COMPUTE_ENGINE_LASER` completed run 转 computation observation。
- automation 配置下，worker 完成后自动生成 observation 和下一轮 suggestion。

当前缺口：
- 手工 observation 需要按 objectives 校验 required/allowed fields。
- submit suggestion 当前固定提交 `MOCK_LASER`，需要支持 computation preset。

## 9. 前端设计

### 9.1 API client

`frontend/src/api/polyAgentApi.js` 已封装：
- auth/admin
- computation create/list/detail/cancel/retry/artifact/preview/structure/spectrum/download
- optimization campaign/candidate/suggestion/observation/history
- integration status

待补：
- integration config API。
- CSV import API。
- suggestion reject/failed API。

### 9.2 页面

| 页面 | 文件 | 当前能力 |
|---|---|---|
| Computation submit | `ComputationSubmitView.vue` | workflow/engine/method 表单 |
| Computation runs | `ComputationRunsView.vue` | 列表、筛选、轮询、drawer、timeline、artifact、spectrum SVG、blob 下载 |
| Campaigns | `CampaignsView.vue` | 创建、导入 demo、生成建议 |
| Campaign detail | `CampaignDetailView.vue` | candidates/suggestions/observations/history、submit/create observation |
| Tool services | `ToolServicesView.vue` | integration status 展示 |

当前缺口：
- 结构 viewer 仍轻量。
- integration config 管理未接。
- Playwright/e2e 未建立。

## 10. 安全和审计设计

### 10.1 输入白名单

| 输入 | 控制点 |
|---|---|
| workflow/engine | `supported_workflow_engine_pairs()` |
| method/solvent | `ComputationParameters` 白名单 |
| molecule | Pydantic 长度和控制字符校验 |
| resources | Pydantic 上下限 |
| artifact path | `settings.outputs_root` 边界校验 |
| integration config | 敏感字段拒绝，endpoint 禁止凭据 |

禁止：
- 前端传 shell command。
- 前端传本地 file path。
- `config_summary` 保存 token/password/api_key/secret/private_key。
- xTB adapter 拼接 shell 字符串。

### 10.2 权限检查点

当前仍需补齐 owner/admin 权限过滤：
- computation list/detail/cancel/retry。
- artifact metadata/preview/download。
- campaign list/detail/mutation。
- audit event list。

### 10.3 审计写入

当前主要在 service 层写审计：
- ComputationService
- OptimizationService
- IntegrationConfigService

待改进：
- 审计 actor role 统一从 current user/worker/system 解析。
- 记录 client ip、user agent/source。
- integration endpoints 统一使用 `request.state.request_id`。

## 11. 配置设计

当前配置来源：`backend/app/core/config.py`。

| 配置 | 默认 | 用途 |
|---|---|---|
| `POLY_AGENT_RUNTIME_ROOT` | `.runtime` | runtime 根目录 |
| `POLY_AGENT_OUTPUT_ROOT` | `.runtime/outputs` | artifact 输出 |
| `AUTH_ENABLED` | `false` | 是否启用登录鉴权 |
| `MONGODB_HOST/PORT/...` | localhost | 主业务 Mongo |
| `ORCA_COMPUTE_ENGINE_EXECUTION_MODE` | `disabled` | `disabled/fixture/external` |
| `ORCA_LICENSE_AVAILABLE` | `false` | ORCA external 前置检查 |
| `HPC_QUEUE_AVAILABLE` | `false` | HPC external 前置检查 |
| `HPC_QUEUE_NAME` | `default` | 队列名摘要 |

## 12. 验证设计

当前后端测试：

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

建议新增：
- 权限隔离测试。
- CSV import/report 测试。
- suggestion reject/failed 状态机测试。
- worker heartbeat/cancel/stale reclaim 测试。
- 前端 Playwright 冒烟测试。

## 13. 风险和缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| AUTH 开启后缺 owner 过滤 | 数据泄露 | Phase A 优先补齐权限 |
| worker 崩溃后 run 卡 running | 用户无法恢复任务 | heartbeat/stale reclaim |
| running cancel 不杀子进程 | 资源泄露 | local adapter cancel hook |
| ORCA external 执行器未实现 | 真实 ComputeEngine laser 不能跑 | 先实现 fake executor 边界 |
| artifact 绝对路径暴露 | 部署信息泄露 | 后续改 storage scheme |
| Atlas/Olympus 依赖复杂 | 优化能力受限 | 轻量 tanimoto 保底，Atlas 独立 adapter |

## 14. ADR 建议

当前代码已经体现但尚未正式写 ADR 的决策：
- ADR-001: computation adapter 不直接写 repository。
- ADR-002: AiiDA 作为外部计算/provenance 系统，不进入业务库。
- ADR-003: Mongo polling + demo JSON store 作为 MVP 队列和本地兜底。
- ADR-004: Atlas/Olympus 不进入主后端依赖。
- ADR-005: artifact 文件本地存储，metadata/checksum 进入业务库。
