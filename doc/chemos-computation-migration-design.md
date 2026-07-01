# ChemOS 计算、优化与可视化能力迁移设计

## 1. 文档定位

本文是 ChemOS 迁移到 Poly_Agent 的融合最终版设计文档，合并了原 v1 的完整架构设计和 v2 的本地事实校正。

本文不把目标定义为“复制 ChemOS 到 Poly_Agent”，而是定义为：

```text
将 ChemOS 中可复用的计算工作流、AiiDA provenance 思路、Atlas/Olympus 优化闭环和计算结果可视化模型，重构为 Poly_Agent 的计算智能模块。
```

本文同时记录：

- 本地 ChemOS demo 的实际可运行状态。
- Poly_Agent 当前代码中的真实落点。
- 哪些 ChemOS 能力应迁移、重写、保留参考或明确不迁移。
- 计算服务、优化服务、前端页面、SpecLabOS 集成、安全审计和实施路线。

## 2. 已验证事实

本节基于 2026-07-01 对当前工作区的代码检查和运行验证。

### 2.1 Poly_Agent 当前事实

| 对象 | 事实 |
|---|---|
| 后端框架 | FastAPI，入口为 `backend/app/main.py` |
| API 前缀 | `/api/v1` |
| 当前 API | `health`、`auth`、`admin`，由 `backend/app/api/v1/router.py` 聚合 |
| 数据库 | MongoDB + PyMongo |
| 数据访问 | `backend/app/infra/mongo.py` 和 `backend/app/infra/repositories.py` |
| 认证 | HMAC token，与 AI4MS 统一认证数据库对接 |
| 前端 | Vue 3 + Element Plus + Vite |
| 前端路由 | `frontend/src/router/index.js` |
| 当前任务页面 | `TaskSubmitView.vue` 和 `TaskCenterView.vue` 仍是性能预测占位，没有真实任务 API |
| 当前工具页面 | 可作为外部服务状态入口扩展 |
| 业务库现状 | 没有已有 computation、campaign、molecule、sample、experiment 核心模型 |

关键修正：

- Poly_Agent 业务库是 MongoDB，迁移设计不应默认引入 PostgreSQL 作为主业务库。
- AiiDA 仍需要 PostgreSQL/RabbitMQ，但它属于外部计算环境，不属于 Poly_Agent 主业务数据库。
- 第一阶段应先补齐计算任务和优化 campaign 的业务模型，而不是直接接完整 ORCA/AiiDA/Atlas。

### 2.2 ChemOS 当前事实

| 对象 | 事实 |
|---|---|
| 参考项目 | `refer/ChemOS2.0-master` |
| simulation demo | `refer/ChemOS2.0-master/ChemOS2.0-simulation` |
| deploy 计算工作流 | `refer/ChemOS2.0-master/ChemOS2.0-deploy/aiida-workchain` |
| GUI | Streamlit，入口 `ChemOS2.0-simulation/streamlit/Hello.py` |
| SiLA 模拟器 | HPLC、Chemspeed、Optics、Atlas |
| 闭环脚本 | `ChemOS2.0-simulation/laserworkflow.py` |
| AiiDA WorkChain | `ChemOS2.0-deploy/aiida-workchain/laser_workchain.py` |
| ChemOS README 定位 | demonstration code，不是可直接生产部署的完整包 |
| 数据库 | ChemOS demo 使用 PostgreSQL `localhost:5432/chemos` |
| 原始凭据问题 | simulation 的 `dblogin.py` 原本硬编码个人或占位凭据，已本地改为环境变量优先、默认 `chemos/chemos` |
| Atlas 状态 | 依赖 `olympus` 和 `atlas`，当前 `chemos` 环境未安装完整优化栈 |

### 2.3 本地运行验证

已创建 Conda 环境：

```bash
conda create -n chemos python=3.10 -y
```

已安装并验证的基础依赖：

```text
sila2==0.10.1
streamlit==1.22.0
sqlalchemy
sqlalchemy-utils
psycopg2-binary
numpy
pandas
scipy
matplotlib
pyvisa
pyunpack
py7zr
python-telegram-bot==13.15
singleton-decorator
```

已安装为 editable 的本地包：

```text
refer/ChemOS2.0-master/ChemOS2.0-simulation/sila-atlas
refer/ChemOS2.0-master/ChemOS2.0-simulation/sila-hplc
refer/ChemOS2.0-master/ChemOS2.0-simulation/sila-chemspeed
refer/ChemOS2.0-master/ChemOS2.0-simulation/sila-optics
```

新增一键脚本：

```bash
scripts/run_chemos.sh
```

脚本命令：

| 命令 | 作用 | 当前状态 |
|---|---|---|
| `check` | 检查 Conda 环境和基础包导入 | 已通过 |
| `gui` | 启动 Streamlit GUI | 已验证 HTTP 200 |
| `base` | 启动 HPLC/Chemspeed/Optics + GUI | 已短时启动验证 |
| `postgres` | 用 Docker 启动 PostgreSQL | 当前用户无 Docker socket 权限，未运行 |
| `with-atlas` | 连 Atlas 一起启动 | 依赖未安装完整，未验证 |
| `workflow` | 运行 `laserworkflow.py` 闭环 | 依赖未齐，未验证 |

默认启动：

```bash
scripts/run_chemos.sh base
```

GUI 地址：

```text
http://127.0.0.1:8501
```

日志目录：

```text
.runtime/chemos/logs/
```

本地限制：

- 本机未发现 `psql`、`postgres`、`pg_isready`。
- Docker CLI 存在，但当前用户无 Docker socket 权限。
- Atlas/Olympus 优化栈尚未安装完整。
- `laserworkflow.py` 还依赖 PostgreSQL、RDKit、Olympus、Atlas 和 live SiLA services。
- AiiDA/ORCA 工作流位于 deploy 目录，不属于 simulation GUI 的已验证路径。

### 2.4 SpecLabOS 当前事实

SpecLabOS 是现有实验设备和 workflow 编排系统，不应被 ChemOS SiLA 层替代。

参考 `refer/SpecLabOS-main/README.md`，其已有能力包括：

```text
GET /api/devices
GET /api/workflows
GET /api/workflow-runs
GET /api/workflow-runs/{run_id}
GET /api/logs
POST /api/smartaccess/templates/publish
POST /api/smartaccess/runs/{run_id}/events
RabbitMQ exchange: smartaccess.commands
```

结论：

- ChemOS 仪器管理层不迁入 Poly_Agent。
- Poly_Agent 只需要在优化推荐或计算结果需要实验验证时，对接 SpecLabOS workflow run。

## 3. 总体结论

### 3.1 应迁移的核心能力

应迁移的是思想、数据模型和服务边界：

```text
candidate
  -> suggestion
  -> computation or experiment evaluator
  -> observation
  -> next suggestion
```

应迁移或重构：

| ChemOS 能力 | 原位置 | Poly_Agent 迁移方式 |
|---|---|---|
| 闭环推荐流程 | `laserworkflow.py` | 抽象为 campaign/suggestion/evaluation/observation |
| 候选分子库 | `job_files/molecules.json` | 导入为 `optimization_candidates` |
| RDKit Morgan fingerprint | `laserworkflow.py` | descriptor 生成器 |
| Olympus Campaign 思路 | `laserworkflow.py` | 映射为 MongoDB campaign/observation |
| Atlas TanimotoPlanner | `sila-atlas/.../atlas_impl.py` | 独立 Optimizer Service adapter |
| BoTorchPlanner 思路 | `atlas_impl.py` | 作为连续参数优化 adapter |
| AiiDA WorkChain outline | `aiida-workchain/laser_workchain.py` | 重构为外部 computation worker |
| xTB/CREST/ORCA 步骤 | `laser_workchain.py` | 配置化计算 step |
| spectra/gain 后处理 | `aiida-workchain/spectra/` | parser + artifact generator |
| provenance 思路 | AiiDA | 保留 AiiDA UUID，业务库只存索引和摘要 |

### 3.2 不应迁移的内容

| 内容 | 原因 |
|---|---|
| ChemOS Streamlit 前端 | 与 Vue 架构不匹配，且只是 demo 控制台 |
| ChemOS SiLA 仪器服务 | 用户已有 SpecLabOS |
| Chemspeed/HPLC/Optics demo 编排 | 属于 ChemOS 实验仪器闭环，不是 Poly_Agent 核心 |
| ChemOS PostgreSQL demo schema | Poly_Agent 业务库是 MongoDB |
| pickle 作为主业务状态 | 不可查询、不可审计、不可权限控制 |
| `eval(Config)` | 安全风险 |
| 硬编码 HPC 路径和 `niagara` | 不可移植 |
| FastAPI 请求内直接跑 DFT | 长任务阻塞且难以恢复 |

### 3.3 可选迁移内容

| 内容 | 建议 |
|---|---|
| Atlas/Olympus 原始依赖 | 可在独立 optimizer 环境中使用，不进入主后端依赖 |
| BoTorch 直接实现 | 中长期可替代 Atlas 封装 |
| 多目标 Hypervolume scalarizer | 对多目标分子筛选有价值，保留接口 |
| ChemOS spectra 后处理代码 | 先封装 parser，后续用测试逐步替换 |
| ChemOS simulation GUI | 作为参考 demo 保留，通过 `scripts/run_chemos.sh` 启动 |

## 4. 目标架构

### 4.1 总体架构

```text
+-------------------------------------------------------------+
| Poly_Agent Vue Frontend                                      |
| - Task submit / computation submit                           |
| - Computation list/detail                                    |
| - Workflow timeline                                          |
| - Artifact browser                                           |
| - Campaign dashboard                                         |
| - Optimization history / Pareto / molecule map               |
+------------------------------+------------------------------+
                               |
                               | REST API / optional SSE
                               |
+------------------------------v------------------------------+
| Poly_Agent FastAPI Backend                                   |
| - auth and authorization                                     |
| - computation APIs                                           |
| - optimization APIs                                          |
| - artifact APIs                                              |
| - SpecLabOS integration adapter                              |
| - service status APIs                                        |
+--------------+----------------+-----------------------------+
               |                |
               |                |
+--------------v---+     +------v-----------------------------+
| MongoDB           |     | Runtime / Artifact Store            |
| - computation     |     | - .runtime/outputs first            |
| - optimization    |     | - S3/MinIO later                    |
| - integration     |     | - checksum and parser metadata      |
+--------------+---+     +------^-----------------------------+
               |                |
               |                |
+--------------v----------------v-----------------------------+
| Computation Worker                                           |
| - poll queued computation_runs                               |
| - submit local adapter or AiiDA WorkChain                    |
| - sync status                                                |
| - parse outputs                                              |
| - register artifacts                                         |
+------------------------------+------------------------------+
                               |
                               |
+------------------------------v------------------------------+
| External AiiDA / HPC Environment                             |
| - AiiDA profile                                              |
| - AiiDA PostgreSQL + RabbitMQ                                |
| - OpenBabel / xTB / CREST / ORCA                             |
| - scheduler integration                                      |
+-------------------------------------------------------------+

+-------------------------------------------------------------+
| Optimizer Service                                             |
| - fallback planner first                                     |
| - Atlas/Olympus adapter later                                |
| - TanimotoPlanner / BoTorchPlanner                           |
| - replaceable optimizer boundary                             |
+-------------------------------------------------------------+

+-------------------------------------------------------------+
| SpecLabOS                                                     |
| - existing instrument management                              |
| - existing workflow and SmartAccess execution                 |
| - experiment observation source                               |
+-------------------------------------------------------------+
```

### 4.2 服务职责

| 服务 | 负责 | 不负责 |
|---|---|---|
| Poly_Agent Backend | 权限、业务对象、API、审计、状态聚合 | 直接执行 ORCA/DFT |
| MongoDB | 业务状态、任务状态、campaign、artifact 索引 | AiiDA provenance 全量复制 |
| Artifact Store | 原始文件、结构、图谱、日志、checksum | 元数据主索引 |
| Computation Worker | 长任务执行、AiiDA 提交、状态同步、结果解析 | 用户认证、前端交互 |
| AiiDA Environment | provenance、计算过程、HPC 作业 | Poly_Agent 业务权限 |
| Optimizer Service | suggestion、planner adapter、推荐记录 | 执行计算或实验 |
| SpecLabOS | 仪器 workflow、SmartAccess、实验执行 | 计算任务调度 |

### 4.3 部署建议

开发阶段：

```text
Poly_Agent backend
Poly_Agent frontend
MongoDB
.runtime artifact directory
optional local computation worker
ChemOS demo via scripts/run_chemos.sh
```

计算阶段：

```text
Web node
  FastAPI
  Vue build
  MongoDB or managed MongoDB
  artifact store

Computation node
  AiiDA profile
  AiiDA PostgreSQL
  RabbitMQ
  OpenBabel/xTB/CREST/ORCA
  computation worker

Optional HPC
  Slurm/PBS
  AiiDA Computer
```

优化阶段：

```text
Optimizer environment
  Atlas/Olympus dependencies
  RDKit
  BoTorch stack
  independent process or service
```

## 5. Poly_Agent 落地结构

### 5.1 后端目录

当前结构保留，新增以下模块：

```text
backend/app/api/v1/endpoints/
  computations.py
  optimization.py
  artifacts.py
  integrations.py

backend/app/schemas/
  computation.py
  optimization.py
  artifact.py
  integration.py

backend/app/services/
  computation_service.py
  optimizer_service.py
  artifact_service.py
  speclabos_client.py
  service_status_service.py

backend/app/infra/
  computation_repositories.py
  optimization_repositories.py
  artifact_repositories.py

backend/app/workers/
  computation_worker.py
  sync_aiida.py
  parse_results.py
  optimizer_worker.py

backend/app/parsers/
  xyz_parser.py
  orca_parser.py
  xtb_parser.py
  spectra_parser.py

backend/app/optimizers/
  fallback_planner.py
  atlas_tanimoto.py
  atlas_botorch.py
```

### 5.2 前端目录

第一阶段可少量扩展现有 `views/`：

```text
frontend/src/views/
  TaskSubmitView.vue
  TaskCenterView.vue
  ComputationDetailView.vue
  CampaignListView.vue
  CampaignDetailView.vue
```

后续模块化：

```text
frontend/src/modules/
  computations/
    api.js
    types.js
    pages/
    components/
  optimization/
    api.js
    types.js
    pages/
    components/
```

### 5.3 配置扩展

`backend/app/core/config.py` 建议增加：

```text
POLY_AGENT_COMPUTATION_ENABLED
POLY_AGENT_COMPUTATION_WORKER_MODE
POLY_AGENT_ARTIFACT_ROOT
POLY_AGENT_OPTIMIZER_ENABLED
POLY_AGENT_SPECLABOS_BASE_URL
POLY_AGENT_SPECLABOS_TOKEN
POLY_AGENT_AIIDA_PROFILE
POLY_AGENT_AIIDA_COMPUTER
```

注意：

- AiiDA profile/computer 是 worker 配置，不应由前端传任意值。
- ORCA/xTB/CREST 路径不应暴露到前端。
- Secret 不写入 Git，不进入前端构建产物。

## 6. 数据模型

Poly_Agent 使用 MongoDB，以下模型以 collection 文档为准。早期可将 step 摘要嵌入 `computation_runs`，后续按查询压力拆分。

### 6.1 `computation_runs`

```json
{
  "run_id": "comp_20260701_0001",
  "task_type": "computation",
  "workflow_type": "XTB_ONLY",
  "engine": "XTB",
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
    "basis": null,
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
    "worker_id": null
  },
  "steps": [
    {
      "step_key": "OPENBABEL_3D",
      "step_name": "SMILES to 3D structure",
      "status": "pending",
      "order_index": 1,
      "artifact_ids": [],
      "input_summary": {},
      "output_summary": {},
      "log_tail": null,
      "error_message": null,
      "started_at": null,
      "finished_at": null
    }
  ],
  "artifact_ids": [],
  "result_summary": {},
  "error": null,
  "created_by": "user_id",
  "created_at": "2026-07-01T00:00:00Z",
  "updated_at": "2026-07-01T00:00:00Z",
  "submitted_at": null,
  "started_at": null,
  "finished_at": null
}
```

计算任务状态：

```text
draft
queued
submitted
running
parsing
completed
failed
cancelled
```

计算步骤状态：

```text
pending
running
completed
failed
skipped
```

### 6.2 `computation_artifacts`

```json
{
  "artifact_id": "art_001",
  "run_id": "comp_20260701_0001",
  "step_key": "XTB_CREST",
  "artifact_type": "xyz",
  "name": "xtbopt.xyz",
  "storage_uri": ".runtime/outputs/computations/comp_20260701_0001/xtbopt.xyz",
  "mime_type": "chemical/x-xyz",
  "size_bytes": 1234,
  "checksum_sha256": "...",
  "parser_name": "xtb_parser",
  "parser_version": "0.1.0",
  "metadata": {
    "source": "xtb",
    "unit": "angstrom",
    "source_step": "XTB_CREST"
  },
  "created_at": "2026-07-01T00:00:00Z"
}
```

artifact 类型：

```text
xyz
sdf
orca_out
orca_inp
molden
hessian
npz
spectrum_json
gain_json
log
archive
```

### 6.3 `optimization_campaigns`

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
      "transform": null,
      "weight": null
    }
  ],
  "planner_config": {
    "batch_size": 1,
    "descriptor": {
      "kind": "morgan_fingerprint",
      "radius": 3,
      "n_bits": 2048
    },
    "atlas": {
      "planner": "tanimoto",
      "is_moo": false,
      "scalarizer_kind": null,
      "acquisition_optimizer_kind": "genetic"
    }
  },
  "created_by": "user_id",
  "created_at": "2026-07-01T00:00:00Z",
  "updated_at": "2026-07-01T00:00:00Z"
}
```

campaign 状态：

```text
draft
running
paused
completed
failed
archived
```

### 6.4 `optimization_candidates`

```json
{
  "candidate_id": "cand_C039",
  "campaign_id": "camp_001",
  "candidate_key": "C039",
  "smiles": "C(=C/c1cccc...",
  "parameters": {
    "building_block": "C039"
  },
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

### 6.5 `optimization_suggestions`

```json
{
  "suggestion_id": "sug_001",
  "campaign_id": "camp_001",
  "candidate_id": "cand_C039",
  "iteration_index": 1,
  "status": "suggested",
  "planner_type": "fallback",
  "planner_payload": {
    "reason": "first unevaluated candidate"
  },
  "submitted_run_id": null,
  "created_at": "2026-07-01T00:00:00Z"
}
```

suggestion 状态：

```text
suggested
submitted
evaluated
rejected
failed
```

### 6.6 `optimization_observations`

```json
{
  "observation_id": "obs_001",
  "campaign_id": "camp_001",
  "candidate_id": "cand_C039",
  "suggestion_id": "sug_001",
  "source_type": "computation",
  "source_run_id": "comp_20260701_0001",
  "values": {
    "gain_factor": 6.89e-17,
    "s1_energy_ev": 2.35
  },
  "uncertainty": {},
  "raw_result_ref": "art_001",
  "created_at": "2026-07-01T00:00:00Z"
}
```

observation 来源：

```text
computation
experiment
manual
imported
```

### 6.7 `service_integrations`

```json
{
  "integration_id": "int_speclabos",
  "integration_type": "speclabos",
  "base_url": "http://127.0.0.1:8010",
  "auth_mode": "bearer_token",
  "enabled": true,
  "metadata": {
    "smartaccess_exchange": "smartaccess.commands"
  },
  "created_at": "2026-07-01T00:00:00Z",
  "updated_at": "2026-07-01T00:00:00Z"
}
```

## 7. API 设计

API 统一放在 `/api/v1` 下，响应结构沿用现有 Poly_Agent 统一响应风格。

### 7.1 计算任务 API

创建计算任务：

```http
POST /api/v1/computations
```

```json
{
  "workflow_type": "XTB_ONLY",
  "engine": "XTB",
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
    "max_wallclock_seconds": 3600
  }
}
```

列表和详情：

```http
GET /api/v1/computations
GET /api/v1/computations/{run_id}
GET /api/v1/computations/{run_id}/artifacts
POST /api/v1/computations/{run_id}/cancel
POST /api/v1/computations/{run_id}/retry
```

查询参数：

```text
status
workflow_type
engine
created_by
keyword
page
page_size
```

### 7.2 Artifact API

```http
GET /api/v1/artifacts/{artifact_id}
GET /api/v1/artifacts/{artifact_id}/download
GET /api/v1/artifacts/{artifact_id}/preview
GET /api/v1/artifacts/{artifact_id}/structure
GET /api/v1/artifacts/{artifact_id}/spectrum
```

规则：

- 下载原始文件前检查用户权限。
- 前端不直接解析 ORCA `.out`、`.npz`、pickle。
- 结构和图谱预览由后端解析为 JSON。

### 7.3 优化 API

```http
POST /api/v1/optimization/campaigns
GET /api/v1/optimization/campaigns
GET /api/v1/optimization/campaigns/{campaign_id}
POST /api/v1/optimization/campaigns/{campaign_id}/candidates:import
POST /api/v1/optimization/campaigns/{campaign_id}/suggestions
POST /api/v1/optimization/campaigns/{campaign_id}/observations
POST /api/v1/optimization/suggestions/{suggestion_id}/submit-computation
POST /api/v1/optimization/suggestions/{suggestion_id}/submit-experiment
GET /api/v1/optimization/campaigns/{campaign_id}/history
GET /api/v1/optimization/campaigns/{campaign_id}/pareto
```

创建 campaign：

```json
{
  "name": "DFT molecular screening",
  "planner_type": "fallback",
  "objectives": [
    {
      "name": "gain_factor",
      "direction": "max",
      "unit": "cm2_s"
    }
  ],
  "planner_config": {
    "batch_size": 1,
    "descriptor": {
      "kind": "morgan_fingerprint",
      "radius": 3,
      "n_bits": 2048
    }
  }
}
```

写入 observation：

```json
{
  "candidate_id": "cand_C039",
  "suggestion_id": "sug_001",
  "source_type": "computation",
  "source_run_id": "comp_20260701_0001",
  "values": {
    "gain_factor": 1.2e-16,
    "s1_energy_ev": 2.35
  }
}
```

### 7.4 集成状态 API

```http
GET /api/v1/integrations/status
GET /api/v1/integrations/chemos-demo/status
GET /api/v1/integrations/computation-worker/status
GET /api/v1/integrations/speclabos/status
```

这些接口用于 `ToolServicesView.vue` 展示外部服务健康状态。

## 8. Computation Service 设计

### 8.1 阶段化执行策略

不要第一阶段直接接完整 ORCA/AiiDA。建议三层 adapter：

| 层 | 能力 | 目的 |
|---|---|---|
| mock adapter | 生成假 step/result/artifact | 打通前后端生命周期 |
| local adapter | OpenBabel/RDKit/xTB local job | 打通轻量计算 |
| aiida adapter | 提交 AiiDA WorkChain | 接真实计算和 provenance |

### 8.2 Worker 模式

FastAPI 只创建任务，不直接跑长任务。

```text
POST /api/v1/computations
  -> validate request
  -> insert computation_run(status=queued)
  -> return run_id

computation_worker
  -> poll queued runs
  -> mark running
  -> execute local adapter or submit AiiDA
  -> update step statuses
  -> register artifacts
  -> parse result_summary
  -> mark completed or failed
```

初期可用 MongoDB polling。后续如果任务量上升，再引入 Redis/RQ/Celery/Arq。

### 8.3 AiiDA WorkChain 重构

ChemOS 原始 `SilaLaserWorkChain` outline：

```text
make_3d_struct
laser_xtb_crest
laser_orca_freq
laser_orca_sp_nacsoc
laser_orca_opt
laser_orca_comb
final_step
```

重构后的 step：

| 原步骤 | 新 step_key | 输出 |
|---|---|---|
| `make_3d_struct` | `OPENBABEL_3D` | initial XYZ |
| `laser_xtb_crest` | `XTB_CREST` | conformers、S0/T1 xyz、hessian |
| `laser_orca_freq` | `ORCA_FREQ` | optimized xyz、freq out |
| `laser_orca_sp_nacsoc` | `ORCA_SP_NACSOC` | out、inp、molden |
| `laser_orca_opt` | `ORCA_OPT` | S1/T1/T2/T3/T4 xyz |
| `laser_orca_comb` | `ORCA_COMB` | combined property outputs |
| `final_step` | `SPECTRA_POSTPROCESS` | spectra JSON、gain JSON |

必须修改：

- 所有 shell script 路径改为配置。
- `load_computer('niagara')` 改为配置。
- 中间文件不写固定相对目录。
- AiiDA retrieved folder 和 artifact store 负责文件归档。
- parser 独立测试。
- 结果写入 `result_summary`。

### 8.4 AiiDA 配置

示例 worker 配置：

```yaml
aiida:
  profile: poly-agent-compute
  computer: ubuntu-local
  codes:
    openbabel: openbabel@ubuntu-local
    xtb: xtb@ubuntu-local
    crest: crest@ubuntu-local
    orca: orca@ubuntu-local
  resources:
    default_num_cores: 16
    default_wallclock_seconds: 10800
```

注意：

- 业务 API 不接受任意 code path。
- ORCA license、HPC key、AiiDA private key 不进入业务库。
- 前端只选择 workflow type 和白名单参数。

### 8.5 状态同步

AiiDA 状态映射：

| AiiDA 状态 | 业务状态 |
|---|---|
| Created | submitted |
| Running | running |
| Waiting | running |
| Finished ok | parsing 或 completed |
| Excepted | failed |
| Killed | cancelled |

同步 worker：

```text
for run in computation_runs where status in submitted/running/parsing:
  load aiida process by uuid
  map process state
  update run and steps
  collect retrieved files
  parse completed outputs
  register artifacts
```

### 8.6 结果摘要

`result_summary` 示例：

```json
{
  "molecule": {
    "smiles": "CCOC1=CC=CC=C1",
    "formula": "C8H10O"
  },
  "energetics": {
    "s0_energy_hartree": -144.079735,
    "t1_energy_hartree": -144.012421
  },
  "excited_states": [
    {
      "state": "S1",
      "energy_ev": 2.35,
      "oscillator_strength": 0.42
    }
  ],
  "spectra": {
    "absorption_peak_nm": 420.5,
    "emission_peak_nm": 510.2
  },
  "laser_metrics": {
    "gain_factor": 1.2e-16
  }
}
```

## 9. Optimizer Service 设计

### 9.1 ChemOS 优化层事实

ChemOS simulation 的 Atlas 实现：

```text
refer/ChemOS2.0-master/ChemOS2.0-simulation/sila-atlas/SilaAtlas/feature_implementations/atlas_impl.py
```

核心逻辑：

```text
if config["planner"] == "tanimoto":
  TanimotoPlanner(
    goal=config["goal"],
    use_descriptors=True,
    acquisition_optimizer_kind="genetic",
    is_moo=True,
    scalarizer_kind="Hypervolume",
    goals=config["moos"]
  )
else:
  BoTorchPlanner(
    goal=config["goal"],
    acquisition_type=config["acquisition_type"],
    acquisition_optimizer_kind=config["acquisition_optimizer_kind"]
  )
```

问题：

- `eval(Config)` 不安全。
- Campaign 用 pickle 传输和保存。
- Atlas/Olympus 依赖重且老旧。
- 当前本地 `chemos` 环境未验证 Atlas 服务完整运行。

### 9.2 迁移策略

第一版不要强依赖 Atlas 常驻服务。按以下顺序：

| 阶段 | planner | 说明 |
|---|---|---|
| MVP | fallback planner | 未评估优先、随机、规则筛选 |
| Phase 5 | atlas_tanimoto adapter | 离散分子库 + fingerprint |
| Phase 5+ | atlas_botorch adapter | 连续工艺参数 |
| 中长期 | native BoTorch | 替代 Atlas 封装 |

Adapter 输入来自 MongoDB，不直接读取 pickle。

```text
optimization_campaign
optimization_candidates
optimization_observations
  -> build temporary optimizer object
  -> planner.recommend(...)
  -> save optimization_suggestion
```

### 9.3 TanimotoPlanner 适用场景

适合：

- 候选空间是离散分子库。
- 每个候选有 SMILES。
- 可用 RDKit Morgan fingerprint 构造 descriptor。
- objective 来自计算、实验或人工 observation。

迁移流程：

```text
读取 campaign
读取 active candidates
生成 Morgan fingerprint
读取 observations
构造临时 Campaign
调用 TanimotoPlanner
保存 suggestion
```

配置：

```json
{
  "planner_type": "atlas_tanimoto",
  "descriptor": {
    "kind": "morgan_fingerprint",
    "radius": 3,
    "n_bits": 2048
  },
  "planner": {
    "goal": "maximize",
    "batch_size": 1,
    "use_descriptors": true,
    "acquisition_optimizer_kind": "genetic",
    "is_moo": true,
    "scalarizer_kind": "Hypervolume",
    "goals": ["max", "min"]
  }
}
```

### 9.4 计算驱动闭环

```text
1. 用户创建 campaign
2. 用户导入候选分子库
3. Optimizer Service 生成 suggestion
4. 用户确认 suggestion
5. Backend 创建 computation_run
6. Worker 执行计算
7. Parser 提取 objective values
8. Backend 写入 observation
9. Optimizer Service 进入下一轮
```

建议第一版采用半自动确认，避免错误配置浪费计算资源。

### 9.5 计算和实验混合优化

同一个 candidate 可以有多种 observation：

```text
COMPUTATION: AiiDA/xTB/ORCA 结果
EXPERIMENT: SpecLabOS 实验结果
MANUAL: 人工录入结果
IMPORTED: 历史数据导入
```

这样可以比较：

- 计算预测值。
- 实验测量值。
- 计算和实验偏差。
- 多轮推荐效果。

## 10. 前端可视化设计

### 10.1 MVP 页面

优先改造现有页面：

| 页面 | 改造 |
|---|---|
| `TaskSubmitView.vue` | 增加计算任务 tab，支持 SMILES/workflow/engine/resources |
| `TaskCenterView.vue` | 接真实 computation list API |
| `ToolServicesView.vue` | 展示 ChemOS demo、worker、SpecLabOS 状态 |

新增页面：

```text
ComputationDetailView.vue
```

详情页：

```text
Header
  run_id / status / molecule / workflow / created_by / duration

Workflow Timeline
  step_key / status / duration / log_tail / artifacts

Summary
  structure summary / energetics / spectra / laser metrics

Artifacts
  files / type / size / checksum / download / preview

Logs
  error / worker log tail / parser messages
```

### 10.2 后续页面

```text
CampaignListView.vue
CampaignDetailView.vue
SuggestionQueue.vue
OptimizationHistory.vue
ParetoFront.vue
MoleculeMap.vue
StructureViewer.vue
SpectrumViewer.vue
ProvenancePanel.vue
```

### 10.3 Workflow Timeline

展示字段：

```text
step_name
status
start time
duration
resource
linked artifacts
error message
```

状态必须有文字，不只靠颜色。

### 10.4 Structure Viewer

推荐：

```text
3Dmol.js
NGL Viewer
```

输入 JSON：

```json
{
  "format": "xyz",
  "content": "...",
  "metadata": {
    "charge": 0,
    "multiplicity": 1,
    "source_step": "XTB_CREST"
  }
}
```

### 10.5 Spectrum Viewer

后端输出：

```json
{
  "kind": "absorption",
  "x_unit": "nm",
  "y_unit": "a.u.",
  "series": [
    {
      "name": "absorption",
      "points": [
        [350.0, 0.02],
        [351.0, 0.025]
      ]
    }
  ],
  "peaks": [
    {
      "x": 420.5,
      "y": 1.0,
      "label": "Abs max"
    }
  ]
}
```

前端可用 ECharts 或 Plotly。

### 10.6 Campaign Dashboard

展示：

```text
campaign status
candidate count
evaluated count
current best candidate
objective definitions
suggestion queue
recent observations
computation success rate
```

### 10.7 Molecule Map

流程：

```text
RDKit fingerprint
  -> PCA/UMAP/t-SNE 后端预计算
  -> frontend scatter plot
```

状态：

```text
not evaluated
suggested
submitted
evaluated
failed
rejected
```

## 11. 与 SpecLabOS 的集成

### 11.1 边界

SpecLabOS 继续负责：

```text
device registry
workflow templates
workflow runs
SmartAccess worker
experiment logs
```

Poly_Agent 只负责：

```text
把 suggestion 转为实验验证请求
记录 SpecLabOS run id
接收或拉取实验结果
写入 optimization_observation
```

### 11.2 建议流程

```text
用户在 CampaignDetail 选择 suggestion
点击 Submit Experiment
Poly_Agent 调用 SpecLabOS workflow API
SpecLabOS 返回 workflow_run_id
Poly_Agent 更新 suggestion.status=submitted
SpecLabOS 完成后回传或由 Poly_Agent 拉取结果
Poly_Agent 写 observation(source_type=experiment)
```

### 11.3 Payload 草案

```json
{
  "campaign_id": "camp_001",
  "suggestion_id": "sug_001",
  "candidate": {
    "candidate_key": "C039",
    "smiles": "..."
  },
  "protocol_name": "validate_candidate",
  "parameters": {
    "concentration": 1.0,
    "solvent": "ACN"
  }
}
```

## 12. 安全、权限和审计

### 12.1 权限

需要区分：

```text
create computation
cancel computation
retry computation
view computation
download artifact
create campaign
modify campaign
generate suggestion
confirm observation
submit experiment
manage integrations
```

### 12.2 输入安全

禁止：

```text
前端传任意 shell command
前端传任意本地路径
使用 eval 解析配置
未校验 ORCA/xTB 参数直接进入 shell script
pickle 作为外部输入直接反序列化
```

必须：

```text
Pydantic schema 校验
workflow_type 白名单
engine 白名单
resource 上限
SMILES 校验
artifact 路径归一化
```

### 12.3 Secret 管理

不得进入前端或明文业务日志：

```text
ORCA license path
HPC credentials
AiiDA private keys
SpecLabOS token
database password
object storage secret
```

### 12.4 审计日志

记录：

```text
创建计算任务
取消计算任务
重试计算任务
下载敏感 artifact
创建或修改 campaign
生成 suggestion
拒绝 suggestion
确认 observation
提交 SpecLabOS 实验
修改集成配置
```

## 13. 可观测性和运维

### 13.1 指标

计算服务：

```text
queued computation count
running computation count
success rate
failure rate by step
average runtime by workflow
artifact storage size
parser failure count
```

优化服务：

```text
campaign count by status
suggestion count
observation count
best objective over time
optimizer failure count
```

AiiDA：

```text
daemon status
RabbitMQ status
PostgreSQL status
process state distribution
HPC queue latency
```

### 13.2 日志字段

```text
request_id
run_id
campaign_id
suggestion_id
aiida_process_uuid
step_key
worker_id
artifact_id
error_code
```

### 13.3 告警

```text
AiiDA daemon stopped
RabbitMQ unavailable
computation queue backlog too high
parser failures continuous
artifact store write failed
HPC jobs pending too long
optimizer service unavailable
```

## 14. 实施路线

### Phase 0: 参考项目和运行环境

已完成：

- 创建 `chemos` Conda 环境。
- 安装 ChemOS simulation 基础依赖。
- 添加 `scripts/run_chemos.sh`。
- 验证 `check`、`gui`、`base`。
- 将 `refer/` 加入 `.gitignore`。

待处理：

- PostgreSQL 运行方式：本地安装、Docker 权限或远程 PostgreSQL。
- 可选安装 Atlas/Olympus 完整优化栈。

验收：

```text
scripts/run_chemos.sh check 通过
scripts/run_chemos.sh gui 返回 HTTP 200
scripts/run_chemos.sh base 可短时启动基础模拟器
```

### Phase 1: Poly_Agent 计算任务基础闭环

目标：

- 新增 computation schema/repository/service/API。
- `POST /api/v1/computations` 写入 MongoDB。
- `GET /api/v1/computations` 驱动任务中心真实列表。
- 实现 mock worker。

验收：

```text
前端能提交一个 SMILES 计算任务
任务中心不再使用静态假数据
任务详情能展示步骤和 artifact 占位
状态可从 queued 变为 completed
```

### Phase 2: 本地轻量计算 adapter

目标：

- 接入 OpenBabel 或 RDKit。
- 生成 3D/2D 结构。
- 保存 XYZ/SDF artifact。
- 生成 result summary。

验收：

```text
不依赖 AiiDA 即可完成轻量计算任务
artifact 可下载或预览
失败能定位到 step
```

### Phase 3: 外部 AiiDA/xTB worker

目标：

- 独立 worker 轮询 MongoDB queued runs。
- 提交 AiiDA OpenBabel/xTB job。
- 同步 AiiDA UUID 和状态。

验收：

```text
OPENBABEL_3D 和 XTB_ONLY 有真实外部执行链路
业务库保存 aiida_process_uuid
前端能看到 step 状态变化
```

### Phase 4: ORCA/Laser DFT 工作流

目标：

- 重构 ChemOS `SilaLaserWorkChain`。
- 接入 ORCA freq、SP NAC/SOC、opt、comb。
- 拆出 spectra/gain parser。

验收：

```text
所有 laser workflow step 都有状态
每一步 artifact 可追溯
前端可查看 spectra/gain JSON
```

### Phase 5: Optimization Campaign

目标：

- 新增 campaign/candidate/objective/suggestion/observation API。
- 先实现 fallback planner。
- 再接 Atlas Tanimoto adapter。

验收：

```text
能导入 ChemOS molecules.json
能基于已有 observation 推荐下一个候选
推荐可转为 computation_run
推荐记录可审计
```

### Phase 6: 计算驱动优化闭环

目标：

- suggestion 一键提交 computation。
- computation 完成后自动生成 observation。
- observation 触发下一轮 suggestion。

验收：

```text
完成至少 3 轮推荐和计算闭环
suggestion、computation、observation 关系清晰
可暂停、恢复和人工确认
```

### Phase 7: SpecLabOS 实验验证

目标：

- 增加 SpecLabOS client。
- suggestion 可提交实验验证 workflow。
- 实验结果回写 observation。

验收：

```text
同一 candidate 支持 computation 和 experiment observation
前端能比较计算预测与实验结果
```

## 15. 验证计划

### 15.1 后端验证

```text
创建 computation_run
查询 computation list/detail
worker 更新状态
注册 artifact
取消任务
重试任务
权限校验
```

### 15.2 计算验证

```text
mock adapter 完成
OpenBabel/RDKit adapter 完成
xTB adapter 完成
AiiDA UUID 写回
parser 输出 result_summary
失败任务定位 step
```

### 15.3 优化验证

```text
导入候选分子
生成 fingerprint
添加 observation
fallback planner 推荐
Atlas adapter 推荐
保存 suggestion
Pareto/history 查询
```

### 15.4 前端验证

```text
任务提交表单
任务列表过滤
任务详情时间线
artifact 下载
structure preview
spectrum preview
campaign dashboard
suggestion queue
```

### 15.5 端到端验证

最小闭环：

```text
创建 candidate library
创建 campaign
添加 2 个初始 observation
生成 suggestion
提交 mock/local computation
写回 observation
生成下一轮 suggestion
```

完整闭环：

```text
Tanimoto suggestion
  -> AiiDA LaserDftWorkChain
  -> ORCA/xTB results
  -> parser
  -> observation
  -> Pareto/history update
  -> next suggestion
```

## 16. 关键设计决策

### Decision 1: 不迁移 ChemOS Streamlit 前端

原因：

- Poly_Agent 是 Vue 3。
- ChemOS Streamlit 是 demo 控制台。
- Streamlit 没有完整 DFT 计算可视化。

结果：

- Streamlit 只作为参考 demo。
- Poly_Agent 用 Vue 实现计算和优化页面。

### Decision 2: Poly_Agent 业务库继续使用 MongoDB

原因：

- 当前代码已使用 MongoDB + PyMongo。
- computation/campaign 文档结构适合 MongoDB 快速落地。
- 引入 PostgreSQL 业务库会增加迁移成本。

结果：

- AiiDA PostgreSQL 仅属于 AiiDA 环境。
- Poly_Agent 只保存业务摘要和 AiiDA 引用。

### Decision 3: AiiDA 独立部署

原因：

- AiiDA 依赖 daemon、PostgreSQL、RabbitMQ、外部可执行程序。
- ORCA/xTB/CREST 更适合 Linux/HPC。
- FastAPI 进程不应承担长计算。

结果：

- 外部 computation worker 负责 AiiDA。
- Web API 只处理任务和状态。

### Decision 4: Optimizer Service 独立于 Computation Service

原因：

- optimizer 只负责推荐，不负责评价。
- evaluator 可以是计算、实验或人工。
- Atlas/Olympus 未来可能替换。

结果：

- campaign/suggestion/observation 独立建模。
- 计算和实验都能作为 observation source。

### Decision 5: 结构化状态替代 pickle

原因：

- pickle 不可查询、不可审计、不适合权限控制。
- 业务系统需要可追溯状态。

结果：

- MongoDB 保存 campaign/candidate/objective/observation。
- 调用 Atlas/Olympus 时临时构造对象。

## 17. 风险和缓解

| 风险 | 当前证据 | 影响 | 缓解 |
|---|---|---|---|
| ChemOS demo 非生产包 | README 明确说明需要实验室定制 | 直接迁移会失败 | 只迁移模型和思想 |
| Atlas/Olympus 依赖复杂 | 当前 `SilaAtlas` 缺 `olympus` | 优化栈安装困难 | 独立 optimizer 环境，MVP 用 fallback |
| PostgreSQL 未就绪 | 本机无 PostgreSQL CLI，Docker 无权限 | ChemOS DB 页面不可用 | 不阻塞 Poly_Agent，单独解决 demo DB |
| AiiDA/ORCA 部署复杂 | ChemOS hard-code `niagara` 和个人路径 | 计算不可迁移 | worker + 配置化 computer/code |
| 任务状态不一致 | AiiDA 与 MongoDB 双状态 | UI 误导 | 周期同步，幂等更新 |
| parser 不稳定 | ORCA 输出复杂 | 前端展示错误 | parser version、checksum、测试 |
| artifact 过大 | ORCA/molden/npz 文件多 | 存储压力 | artifact store、压缩、保留策略 |
| 输入安全风险 | ChemOS 使用 shell 和 `eval` | 命令注入 | schema 白名单，禁止任意命令 |

## 18. MVP 范围

第一版不要包含完整 ORCA/AiiDA/Atlas。

MVP：

```text
Backend:
  computation_runs MongoDB collection
  computation API
  mock/local worker
  artifact metadata API

Frontend:
  TaskSubmitView real submit
  TaskCenterView real list
  ComputationDetailView timeline + artifacts

Optimizer:
  campaign/candidates/observations schema
  fallback planner

Reference:
  scripts/run_chemos.sh keeps ChemOS demo runnable
```

MVP 后扩展：

```text
OpenBabel/xTB
AiiDA worker
ORCA laser workflow
Spectra/gain parser
Atlas Tanimoto planner
SpecLabOS experiment validation
```

## 19. 最终口径

本项目迁移不应表述为：

```text
把 ChemOS 搬到 Poly_Agent 里。
```

应表述为：

```text
以 Poly_Agent 的 FastAPI + MongoDB + Vue 架构为主，吸收 ChemOS 的计算工作流、AiiDA provenance、Atlas/Olympus 优化闭环和结果可视化思想，建设面向高分子材料研发的计算智能与优化推荐模块。
```

最终系统边界：

```text
Poly_Agent:
  权限、业务状态、计算任务、优化 campaign、前端可视化。

Computation Worker:
  长计算执行、AiiDA 提交、状态同步、结果解析。

Optimizer Service:
  campaign 推荐、Atlas/Olympus adapter、后续可替换算法。

SpecLabOS:
  实验仪器、workflow、SmartAccess、实验验证。

ChemOS reference:
  保留为参考项目和设计来源，不作为生产代码直接迁入。
```
