# ChemOS 计算智能模块产品设计文档

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | Draft for implementation planning |
| 版本 | v0.1 |
| 日期 | 2026-07-01 |
| 输入文档 | `doc/chemos-computation-migration-design.md`、`doc/chemos-computation-product-prd.md` |
| 目标 | 将 PRD 转为可开发、可测试、可审计的工程设计 |

## 2. 设计原则

| 原则 | 说明 |
|---|---|
| 业务库保持 MongoDB | 贴合现有 Poly_Agent 架构，不把 AiiDA PostgreSQL 当业务库 |
| 长任务出 Web 进程 | FastAPI 只创建和查询任务，worker 执行计算和同步状态 |
| 外部系统引用不复制 | Poly_Agent 保存 AiiDA UUID、SpecLabOS run id、artifact 摘要，不复制完整 provenance |
| 输入白名单 | workflow、engine、resource、parser、artifact type 均使用白名单 |
| 每个状态变化可审计 | 用户操作和 worker 自动操作都要有审计事件 |
| adapter 可替换 | mock、local、AiiDA、Atlas、SpecLabOS 都通过边界接入 |

## 3. 系统上下文

```text
Vue Frontend
  -> FastAPI /api/v1
     -> MongoDB business collections
     -> Artifact store .runtime/outputs first
     -> Audit events
     -> Computation worker process
        -> mock/local adapter
        -> optional AiiDA profile
           -> AiiDA PostgreSQL/RabbitMQ/HPC/ORCA/xTB
     -> Optimizer worker/service
        -> fallback planner
        -> optional Atlas/Olympus adapter
     -> SpecLabOS client
        -> workflow runs and experiment observations
```

### 3.1 组件职责

| 组件 | 负责 | 不负责 |
|---|---|---|
| FastAPI backend | 权限、API、业务对象、审计、状态聚合 | 直接执行 DFT 或解析大文件 |
| MongoDB | computation、campaign、artifact、audit 索引 | AiiDA provenance 全量存储 |
| Artifact store | 原始文件、日志、结构和图谱产物 | 权限判断和主元数据查询 |
| Computation worker | 状态锁定、执行 adapter、登记 artifact、解析结果 | 用户认证和页面交互 |
| Optimizer service | suggestion 生成和 planner adapter | 计算或实验执行 |
| SpecLabOS client | workflow 提交、结果拉取 | 仪器调度实现 |

## 4. 数据设计

### 4.1 Collection 列表

| Collection | 用途 | MVP 必需 |
|---|---|---|
| `computation_runs` | 计算任务主记录 | 是 |
| `computation_artifacts` | artifact 元数据 | 是 |
| `optimization_campaigns` | 优化 campaign | 是 |
| `optimization_candidates` | 候选分子或参数 | 是 |
| `optimization_suggestions` | 推荐记录 | 是 |
| `optimization_observations` | 评价结果 | 是 |
| `service_integrations` | 外部集成配置摘要 | 是 |
| `audit_events` | 审计事件 | 是 |
| `worker_heartbeats` | worker 心跳和能力 | P1 |

### 4.2 `computation_runs`

关键字段：

```json
{
  "run_id": "comp_20260701_0001",
  "retry_of_run_id": null,
  "workflow_type": "MOCK_XTB_ONLY",
  "engine": "MOCK",
  "status": "queued",
  "molecule": {
    "smiles": "CCOC1=CC=CC=C1",
    "name": "candidate_001",
    "formula": null
  },
  "parameters": {
    "charge": 0,
    "multiplicity": 1,
    "method": "GFN2-xTB",
    "solvent": null
  },
  "resources": {
    "num_cores": 4,
    "memory_mb": 8192,
    "max_wallclock_seconds": 3600
  },
  "external_refs": {
    "aiida_process_uuid": null,
    "aiida_node_pk": null,
    "scheduler_job_id": null,
    "speclabos_run_id": null,
    "worker_id": null
  },
  "steps": [],
  "artifact_ids": [],
  "result_summary": {},
  "error": null,
  "created_by": "user_id",
  "created_at": "2026-07-01T00:00:00Z",
  "updated_at": "2026-07-01T00:00:00Z",
  "started_at": null,
  "finished_at": null
}
```

索引建议：

```text
unique(run_id)
created_by + created_at desc
status + updated_at asc
workflow_type + status
external_refs.aiida_process_uuid sparse unique
retry_of_run_id
```

### 4.3 `computation_artifacts`

关键字段：

```json
{
  "artifact_id": "art_001",
  "run_id": "comp_20260701_0001",
  "step_key": "MOCK_RESULT",
  "artifact_type": "spectrum_json",
  "name": "result.json",
  "storage_uri": ".runtime/outputs/computations/comp_20260701_0001/result.json",
  "mime_type": "application/json",
  "size_bytes": 1234,
  "checksum_sha256": "sha256...",
  "parser_name": "mock_parser",
  "parser_version": "0.1.0",
  "metadata": {
    "source": "mock",
    "source_step": "MOCK_RESULT"
  },
  "created_at": "2026-07-01T00:00:00Z"
}
```

索引建议：

```text
unique(artifact_id)
run_id + step_key
artifact_type
checksum_sha256
```

### 4.4 优化集合

`optimization_campaigns`：

```json
{
  "campaign_id": "camp_001",
  "name": "laser molecule screening",
  "status": "draft",
  "planner_type": "fallback",
  "search_space": {
    "kind": "discrete_molecule_library",
    "candidate_count": 40
  },
  "objectives": [
    {
      "name": "gain_factor",
      "direction": "max",
      "unit": "cm2_s",
      "required": true
    }
  ],
  "planner_config": {
    "batch_size": 1,
    "descriptor": {
      "kind": "morgan_fingerprint",
      "radius": 3,
      "n_bits": 2048
    }
  },
  "created_by": "user_id",
  "created_at": "2026-07-01T00:00:00Z",
  "updated_at": "2026-07-01T00:00:00Z"
}
```

`optimization_candidates`：

```json
{
  "candidate_id": "cand_C039",
  "campaign_id": "camp_001",
  "candidate_key": "C039",
  "smiles": "C(=C/c1cccc...)",
  "parameters": {},
  "descriptors": {
    "morgan_fingerprint": null
  },
  "metadata": {
    "source": "ChemOS molecules.json"
  },
  "is_active": true,
  "created_at": "2026-07-01T00:00:00Z"
}
```

`optimization_suggestions`：

```json
{
  "suggestion_id": "sug_001",
  "campaign_id": "camp_001",
  "candidate_id": "cand_C039",
  "iteration_index": 1,
  "status": "suggested",
  "planner_type": "fallback",
  "planner_payload": {
    "reason": "first unevaluated active candidate"
  },
  "submitted_run_id": null,
  "submitted_experiment_run_id": null,
  "created_at": "2026-07-01T00:00:00Z",
  "updated_at": "2026-07-01T00:00:00Z"
}
```

`optimization_observations`：

```json
{
  "observation_id": "obs_001",
  "campaign_id": "camp_001",
  "candidate_id": "cand_C039",
  "suggestion_id": "sug_001",
  "source_type": "computation",
  "source_run_id": "comp_20260701_0001",
  "values": {
    "gain_factor": 1.2e-16,
    "s1_energy_ev": 2.35
  },
  "uncertainty": {},
  "raw_result_ref": "art_001",
  "confirmed_by": "user_id",
  "created_at": "2026-07-01T00:00:00Z"
}
```

索引建议：

```text
optimization_campaigns: unique(campaign_id), created_by + updated_at desc, status
optimization_candidates: unique(campaign_id + candidate_key), campaign_id + is_active
optimization_suggestions: unique(suggestion_id), campaign_id + iteration_index, campaign_id + status
optimization_observations: unique(observation_id), campaign_id + candidate_id, source_type + source_run_id
```

### 4.5 `audit_events`

```json
{
  "event_id": "audit_001",
  "event_type": "computation.created",
  "actor_user_id": "user_id",
  "actor_role": "user",
  "request_id": "req_001",
  "entity_type": "computation_run",
  "entity_id": "comp_001",
  "related_ids": {
    "campaign_id": null,
    "suggestion_id": null,
    "artifact_id": null,
    "external_run_id": null
  },
  "before": {},
  "after": {
    "status": "queued"
  },
  "metadata": {
    "client_ip": "127.0.0.1",
    "source": "web"
  },
  "created_at": "2026-07-01T00:00:00Z"
}
```

索引建议：

```text
created_at desc
actor_user_id + created_at desc
event_type + created_at desc
entity_type + entity_id + created_at desc
request_id
```

## 5. API 设计

所有 API 使用现有统一响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "request_id": "..."
}
```

### 5.1 Computations

创建任务：

```http
POST /api/v1/computations
```

请求：

```json
{
  "workflow_type": "MOCK_XTB_ONLY",
  "engine": "MOCK",
  "molecule": {
    "smiles": "CCOC1=CC=CC=C1",
    "name": "candidate_001"
  },
  "parameters": {
    "charge": 0,
    "multiplicity": 1
  },
  "resources": {
    "num_cores": 4,
    "memory_mb": 8192,
    "max_wallclock_seconds": 3600
  }
}
```

响应：

```json
{
  "run_id": "comp_20260701_0001",
  "status": "queued"
}
```

列表：

```http
GET /api/v1/computations?status=queued&page=1&page_size=20
```

响应数据：

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
```

详情和操作：

```http
GET /api/v1/computations/{run_id}
GET /api/v1/computations/{run_id}/artifacts
POST /api/v1/computations/{run_id}/cancel
POST /api/v1/computations/{run_id}/retry
```

取消规则：

- `completed`、`failed`、`cancelled` 不允许取消。
- 如果已提交外部 AiiDA，应先标记 cancel requested，再由 sync worker 确认。

重试规则：

- 默认创建新 run，字段 `retry_of_run_id` 指向原 run。
- 新 run 复制 molecule、workflow、parameters、resources，不复制 artifact 和 result。

### 5.2 Artifacts

```http
GET /api/v1/artifacts/{artifact_id}
GET /api/v1/artifacts/{artifact_id}/download
GET /api/v1/artifacts/{artifact_id}/preview
GET /api/v1/artifacts/{artifact_id}/structure
GET /api/v1/artifacts/{artifact_id}/spectrum
```

安全规则：

- `storage_uri` 必须解析到配置的 artifact root 内。
- 下载前按 run 权限校验。
- `preview` 只返回白名单类型。
- 原始 ORCA out、npz、pickle 不由前端直接解析。

### 5.3 Optimization

```http
POST /api/v1/optimization/campaigns
GET /api/v1/optimization/campaigns
GET /api/v1/optimization/campaigns/{campaign_id}
PATCH /api/v1/optimization/campaigns/{campaign_id}
POST /api/v1/optimization/campaigns/{campaign_id}/candidates:import
POST /api/v1/optimization/campaigns/{campaign_id}/suggestions
POST /api/v1/optimization/campaigns/{campaign_id}/observations
POST /api/v1/optimization/suggestions/{suggestion_id}/submit-computation
POST /api/v1/optimization/suggestions/{suggestion_id}/submit-experiment
GET /api/v1/optimization/campaigns/{campaign_id}/history
GET /api/v1/optimization/campaigns/{campaign_id}/pareto
```

`submit-computation` 响应：

```json
{
  "suggestion_id": "sug_001",
  "run_id": "comp_20260701_0002",
  "suggestion_status": "submitted"
}
```

幂等规则：

- suggestion 已有 `submitted_run_id` 时，重复请求返回已有 run，不创建第二个 run。
- suggestion 为 `rejected` 或 `evaluated` 时拒绝提交。

### 5.4 Integrations

```http
GET /api/v1/integrations/status
GET /api/v1/integrations/chemos-demo/status
GET /api/v1/integrations/computation-worker/status
GET /api/v1/integrations/speclabos/status
GET /api/v1/integrations/aiida/status
```

统一状态：

```json
{
  "service": "computation-worker",
  "status": "up",
  "checked_at": "2026-07-01T00:00:00Z",
  "details": {
    "worker_id": "worker-local-1",
    "capabilities": ["MOCK_XTB_ONLY"]
  }
}
```

## 6. Computation Worker 设计

### 6.1 Worker 循环

```text
loop:
  find one queued run with atomic lock
  set status=running, external_refs.worker_id=worker_id
  emit audit computation.status_changed
  create or update steps
  execute adapter
  register artifacts
  parse result summary
  set status=completed or failed
  emit audit status and artifact events
  sleep polling interval
```

### 6.2 原子锁定

worker 获取任务必须使用 MongoDB 原子更新：

```text
find_one_and_update(
  {status: "queued", worker_lock: null or expired},
  {$set: {worker_lock: {worker_id, locked_at, expires_at}, status: "running"}}
)
```

要求：

- 同一个 run 不能被两个 worker 执行。
- worker crash 后锁过期可被重新获取。
- 已产生外部 job 的 run 不应重复提交，需要先检查 external refs。

### 6.3 Adapter 分层

| Adapter | workflow_type | 作用 |
|---|---|---|
| mock | `MOCK_XTB_ONLY`、`MOCK_LASER` | 打通生命周期和前端 |
| local | `LOCAL_RDKIT_3D`、`LOCAL_XTB_ONLY` | 轻量结构和 xTB |
| aiida | `AIIDA_XTB_ONLY`、`AIIDA_LASER_DFT` | 外部 AiiDA provenance |

adapter 接口：

```python
class ComputationAdapter:
    workflow_type: str

    def prepare_steps(self, run: ComputationRun) -> list[ComputationStep]:
        ...

    def execute(self, run: ComputationRun, workdir: Path) -> AdapterResult:
        ...
```

`AdapterResult` 至少包含：

```text
status
steps
artifact_paths
result_summary
external_refs
error
```

### 6.4 Step key 白名单

MVP：

```text
MOCK_VALIDATE_INPUT
MOCK_GENERATE_STRUCTURE
MOCK_RESULT
```

后续：

```text
OPENBABEL_3D
RDKIT_3D
XTB_CREST
ORCA_FREQ
ORCA_SP_NACSOC
ORCA_OPT
ORCA_COMB
SPECTRA_POSTPROCESS
```

### 6.5 错误处理

错误对象：

```json
{
  "error_code": "ADAPTER_EXECUTION_FAILED",
  "message": "mock adapter failed",
  "step_key": "MOCK_RESULT",
  "retryable": true,
  "details": {}
}
```

错误原则：

- 用户可见 message 不包含 secret、本地敏感路径或完整命令。
- 详细日志进入 artifact 或 worker log，但下载仍需权限。
- parser failure 不覆盖原始计算完成状态，run 可进入 `failed` 或 `completed_with_parse_warning`。MVP 为简化不新增该状态，统一按 `failed` 处理并保留 artifact。

## 7. Optimizer 设计

### 7.1 Fallback planner

MVP planner 规则：

```text
1. 读取 campaign active candidates
2. 排除已有 evaluated observation 的 candidate
3. 排除已有 suggested/submitted 且未终结的 candidate
4. 按 candidate_key 排序或随机策略选择 batch_size 个
5. 写入 optimization_suggestions
```

推荐 payload：

```json
{
  "strategy": "first_unevaluated",
  "excluded_counts": {
    "evaluated": 2,
    "pending": 1
  },
  "reason": "first unevaluated active candidate"
}
```

### 7.2 Atlas Tanimoto adapter

P2 接入，不进入 MVP 主依赖。

边界：

- Poly_Agent 从 MongoDB 构造临时 optimizer 输入。
- 不读取外部 pickle。
- 不使用 `eval(Config)`。
- Atlas/Olympus 安装在独立 optimizer 环境。

输入：

```text
campaign objectives
active candidates with SMILES
Morgan fingerprints
observations
planner_config
```

输出：

```text
candidate_id
score or acquisition value
planner_payload
```

### 7.3 Observation 写回

计算结果转 observation 的映射配置应是白名单：

```json
{
  "workflow_type": "MOCK_LASER",
  "mappings": [
    {
      "objective_name": "gain_factor",
      "result_path": "laser_metrics.gain_factor",
      "required": true
    }
  ]
}
```

规则：

- required objective 缺失时不自动生成 observation。
- 自动生成 observation 需要记录 `source_type=computation` 和 `source_run_id`。
- 人工确认后写 `confirmed_by`。

## 8. 前端设计

### 8.1 API 客户端

在 `frontend/src/api/polyAgentApi.js` 增加：

```text
createComputation
listComputations
getComputation
cancelComputation
retryComputation
listComputationArtifacts
downloadArtifact
listCampaigns
createCampaign
getCampaign
importCampaignCandidates
generateSuggestion
createObservation
submitSuggestionComputation
getIntegrationStatus
```

继续复用：

- `X-Request-Id` request interceptor。
- `Authorization` header。
- `unwrapResponse` 统一处理。

### 8.2 页面和组件

| 页面 | 组件 |
|---|---|
| TaskSubmitView | `ComputationSubmitForm` |
| TaskCenterView | `ComputationFilterBar`、`ComputationTable` |
| ComputationDetailView | `ComputationHeader`、`WorkflowTimeline`、`ArtifactTable`、`ResultSummaryPanel`、`LogPanel` |
| CampaignDetailView | `ObjectiveTable`、`CandidateTable`、`SuggestionQueue`、`ObservationTable`、`CampaignHistoryChart` |
| ToolServicesView | `IntegrationStatusList` |

### 8.3 轮询策略

详情页：

```text
if status in queued/submitted/running/parsing:
  poll every 3s
else:
  stop polling
```

列表页：

```text
manual refresh button
optional 10s refresh when active filters include non-terminal status
```

## 9. SpecLabOS 集成设计

### 9.1 配置

后端配置项：

```text
POLY_AGENT_SPECLABOS_ENABLED
POLY_AGENT_SPECLABOS_BASE_URL
POLY_AGENT_SPECLABOS_TOKEN
POLY_AGENT_SPECLABOS_TIMEOUT_SECONDS
```

### 9.2 提交流程

```text
POST /optimization/suggestions/{id}/submit-experiment
  -> load suggestion, campaign, candidate
  -> validate status=suggested
  -> call SpecLabOS workflow run API
  -> save workflow_run_id
  -> status=submitted
  -> audit experiment.submitted
```

### 9.3 结果同步

MVP 后采用 polling：

```text
find submitted suggestions with submitted_experiment_run_id
  -> GET /api/workflow-runs/{run_id}
  -> if completed, parse outputs
  -> create observation(source_type=experiment)
  -> set suggestion.status=evaluated
```

## 10. 安全和审计设计

### 10.1 输入白名单

| 输入 | 白名单来源 |
|---|---|
| workflow_type | 后端枚举 |
| engine | 后端枚举 |
| step_key | 后端枚举 |
| artifact_type | 后端枚举 |
| parser_name | parser registry |
| resource 上限 | settings |
| SpecLabOS protocol | integration config |

禁止：

- 前端传任意 shell command。
- 前端传任意本地路径。
- 反序列化外部 pickle。
- 使用 `eval` 解析 planner config。
- 把 ORCA license、HPC key、SpecLabOS token 写入业务日志。

### 10.2 权限检查点

| API | 权限检查 |
|---|---|
| create computation | 登录用户，feature enabled |
| list computations | 本人或管理员，后续按 project |
| get computation | run owner、project member 或管理员 |
| download artifact | 对应 run 可见 |
| cancel/retry | owner、计算管理员或管理员 |
| create campaign | 登录用户 |
| modify campaign | owner、负责人或管理员 |
| submit experiment | 负责人、计算管理员或管理员 |
| manage integration | 管理员 |

### 10.3 审计写入位置

建议在 service 层写审计：

```text
endpoint
  -> auth dependency resolves actor
  -> service performs validation and mutation
  -> audit service records event in same logical operation
```

对 MongoDB 无事务的 MVP：

- 主操作成功后写审计。
- 审计失败要写应用 error log。
- 对高风险操作如 artifact download，如果审计失败，应拒绝下载或降级由配置控制。默认拒绝。

## 11. 配置设计

`backend/app/core/config.py` 增加：

```text
POLY_AGENT_COMPUTATION_ENABLED=true
POLY_AGENT_COMPUTATION_WORKER_MODE=mock
POLY_AGENT_COMPUTATION_POLL_INTERVAL_SECONDS=3
POLY_AGENT_ARTIFACT_ROOT=.runtime/outputs
POLY_AGENT_MAX_COMPUTATION_CORES=16
POLY_AGENT_MAX_COMPUTATION_MEMORY_MB=65536
POLY_AGENT_MAX_COMPUTATION_WALLCLOCK_SECONDS=86400
POLY_AGENT_OPTIMIZER_ENABLED=true
POLY_AGENT_SPECLABOS_ENABLED=false
POLY_AGENT_SPECLABOS_BASE_URL=
POLY_AGENT_SPECLABOS_TOKEN=
POLY_AGENT_AIIDA_ENABLED=false
POLY_AGENT_AIIDA_PROFILE=
POLY_AGENT_AIIDA_COMPUTER=
```

注意：

- secret 只放 `.env`，不进入前端构建。
- AiiDA profile/computer 由 worker 环境配置，不允许前端覆盖。
- ORCA/xTB/CREST 路径不进入业务 API。

## 12. 实施计划

### 12.1 MVP 任务拆分

| 顺序 | 任务 | 主要文件 | 验证 |
|---|---|---|---|
| 1 | 新增 computation schemas 和 repository | `backend/app/schemas/computation.py`、`backend/app/infra/computation_repositories.py` | 单元测试 repository CRUD |
| 2 | 新增 computation service/API | `backend/app/services/computation_service.py`、`backend/app/api/v1/endpoints/computations.py` | API 创建、列表、详情 |
| 3 | 新增 audit collection/service | `backend/app/schemas/audit.py`、`backend/app/services/audit_service.py` | P0 事件写入 |
| 4 | 新增 artifact schema/API | `artifact.py`、`artifacts.py` | checksum、路径归一化、下载 |
| 5 | mock worker | `backend/app/workers/computation_worker.py` | queued 到 completed |
| 6 | 前端任务提交和任务中心改造 | `TaskSubmitView.vue`、`TaskCenterView.vue`、`polyAgentApi.js` | 手工端到端 |
| 7 | 计算详情页 | `ComputationDetailView.vue`、router | timeline 和 artifacts 展示 |
| 8 | optimization P0 backend | optimization schemas/repositories/services/endpoints | campaign、candidate、suggestion、observation |
| 9 | Campaign 基础页面 | campaign views/components | 创建和查看 |
| 10 | integration status | integrations endpoint、ToolServicesView | 状态展示 |

### 12.2 验证命令

以后端当前结构为准：

```bash
cd backend
python -m pytest
uvicorn app.main:app --host 127.0.0.1 --port 8003
```

前端：

```bash
cd frontend
npm run build
npm run dev -- --host 127.0.0.1
```

如果测试框架尚未建立，MVP 开发任务应同时补齐 pytest 基础设施。

## 13. 可审计验收清单

每个开发 PR 或阶段验收需要回答：

| 检查项 | 证据 |
|---|---|
| 需求 ID 是否覆盖 | PR 描述列出 COMP/ART/OPT/AUD 编号 |
| API 是否有 schema 校验 | Pydantic schema 和 422 测试 |
| 状态变更是否受控 | 状态迁移测试 |
| 审计事件是否写入 | audit_events 查询截图或测试断言 |
| artifact 是否有 checksum | artifact record 和文件 hash 对比 |
| 是否避免 secret 泄露 | 日志样例和 `.env.example` 审查 |
| 是否能端到端复现 | 创建任务到 completed 的 run_id |
| 是否保留外部引用 | AiiDA/SpecLabOS/mock external refs |

## 14. 风险和缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| MongoDB 无事务导致主记录和审计不一致 | 审计缺口 | service 层顺序写入，关键操作审计失败则拒绝 |
| worker 重复执行 | 外部计算浪费 | 原子锁、external refs 幂等检查 |
| artifact 路径穿越 | 文件泄露 | root 内归一化校验 |
| parser 结果不稳定 | observation 错误 | parser version、checksum、required mapping |
| Atlas/Olympus 依赖失败 | 推荐不可用 | fallback planner 可独立工作 |
| AiiDA/ORCA 部署复杂 | DFT 延期 | MVP 不依赖，使用 adapter 分阶段接入 |
| SpecLabOS 上游不可用 | 实验提交失败 | 状态页、超时、重试和失败审计 |

## 15. ADR 记录建议

建议后续在 `doc/` 或 `doc/decisions/` 追加 ADR：

| ADR | 决策 |
|---|---|
| ADR-001 | Poly_Agent 业务库继续使用 MongoDB |
| ADR-002 | AiiDA 作为外部计算环境独立部署 |
| ADR-003 | Computation worker 使用 MongoDB polling 作为 MVP 队列 |
| ADR-004 | Atlas/Olympus 不进入主后端依赖 |
| ADR-005 | Artifact store 从本地 `.runtime/outputs` 起步，后续迁移对象存储 |

## 16. 与 PRD 的验收映射

| PRD 需求 | 设计实现 |
|---|---|
| COMP-001 至 COMP-006 | API 5.1、Worker 6、数据 4.2 |
| ART-001 至 ART-003 | API 5.2、数据 4.3、安全 10 |
| OPT-001 至 OPT-005 | API 5.3、数据 4.4、Optimizer 7 |
| INT-001 | API 5.4、配置 11 |
| AUD-001 至 AUD-004 | 数据 4.5、安全审计 10、验收清单 13 |
