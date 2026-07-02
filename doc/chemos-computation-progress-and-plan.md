# ChemOS 计算智能模块当前进展与后续开发计划

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | Current code assessment and refined implementation plan |
| 日期 | 2026-07-02 |
| 对照文档 | `doc/chemos-computation-product-prd.md`、`doc/chemos-computation-product-design.md`、`doc/chemos-computation-migration-design.md` |
| 代码范围 | `backend/app`、`backend/tests`、`frontend/src`、`scripts/run_chemos.sh` |

本文基于当前仓库代码重新评估 ChemOS 计算智能模块：哪些方案已经落地，哪些只是部分完成，以及下一步应如何继续拆分。

## 2. 总体判断

当前代码已经超过上一版文档描述的 MVP 原型阶段。原计划中的 Phase 0 修复、computation adapter 抽象、本地结构生成、本地 xTB、轻量 planner、自动 observation、service integration 持久化配置等能力已经有实现和测试。

当前可跑通的主流程：

```text
创建 computation run
  -> worker 原子领取 queued run
  -> registry 选择 adapter
  -> mock/local structure/local xTB/ORCA fixture 执行
  -> 登记 artifact/result/error/audit
  -> 前端查看 timeline、artifact、spectrum、下载文件
  -> 创建 campaign
  -> 导入 JSON 或 ChemOS demo candidate
  -> fallback/tanimoto planner 生成 suggestion
  -> suggestion 转 MOCK_LASER computation
  -> completed laser run 转 observation
  -> 可按 automation 配置自动 observation 和下一轮 suggestion
```

按当前 PRD 和参考项目目标估算：

| 口径 | 当前完成度 | 判断 |
|---|---:|---|
| MVP/P0 产品闭环 | 约 85%-90% | 主流程、adapter、artifact、审计、planner 均可运行；仍缺权限隔离、CSV 导入报告、suggestion reject/failed API、observation 目标校验和 worker 运维语义 |
| Phase 1 可演示计算智能模块 | 约 75%-80% | mock/local/fixture 演示能力已较完整；真实 ORCA/HPC、SpecLabOS、生产 worker 还未落地 |
| 完整参考项目目标 Phase 1-7 | 约 45%-50% | 本地结构/xTB、ChemOS laser parser fixture、integration config 已开始；AiiDA/ORCA external/SpecLabOS/Atlas/对象存储仍是后续工作 |

核心结论：当前版本已经适合作为“可演示计算智能模块”的基线。下一步不应重复实现 adapter 或 planner 基础设施，而应优先补齐产品闭环缺口、权限审计和真实外部执行器边界。

## 3. 当前已完成内容

### 3.1 后端计算任务

| 能力 | 当前实现 | 主要文件 | 状态 |
|---|---|---|---|
| 创建计算任务 | `POST /api/v1/computations`，校验 workflow/engine 组合 | `backend/app/api/v1/endpoints/computations.py`、`backend/app/services/computation_service.py` | 已完成 MVP |
| workflow/engine 白名单 | 支持 `MOCK_XTB_ONLY/MOCK`、`MOCK_LASER/MOCK`、`LOCAL_STRUCTURE/LOCAL|RDKit|OPENBABEL`、`LOCAL_XTB/XTB`、`ORCA_CHEMOS_LASER/ORCA` | `backend/app/computation_adapters/registry.py`、`backend/app/schemas/computation.py` | 已完成 |
| 任务列表/详情 | 支持分页、status、workflow、engine、keyword 筛选 | `backend/app/services/computation_service.py` | 已完成 MVP；缺 owner 权限过滤 |
| 取消/重试 | 非终态取消，failed/cancelled 生成 retry run | `backend/app/services/computation_service.py` | 已完成 MVP；运行中子进程取消语义待加强 |
| worker 执行模型 | 原子领取 queued run，初始化 timeline，调用 adapter，统一落库 | `backend/app/workers/computation_worker.py` | 已完成 MVP；缺 heartbeat/stale reclaim |
| demo store 兜底 | MongoDB 不可用时回退 JSON store | `backend/app/infra/demo_store.py`、`backend/app/infra/computation_repositories.py` | 已完成 MVP |

### 3.2 Computation adapter 和真实本地能力

| 能力 | 当前实现 | 主要文件 | 状态 |
|---|---|---|---|
| adapter 协议 | `validate_input`、`run`、`collect_artifacts`、`parse_result` | `backend/app/computation_adapters/base.py` | 已完成 |
| registry | 统一派发 mock/local/orca fixture adapter | `backend/app/computation_adapters/registry.py` | 已完成 |
| mock adapter | 原 mock 计算逻辑已迁移到 adapter | `backend/app/computation_adapters/mock.py` | 已完成 |
| local structure | RDKit 或 OpenBabel 生成 `input_json/structure_json/xyz/sdf/log/error` | `backend/app/computation_adapters/local_structure.py` | 已完成 MVP |
| local xTB | 隔离 workdir、白名单参数、subprocess timeout、stdout/stderr/output/result/error artifact | `backend/app/computation_adapters/local_xtb.py` | 已完成 MVP |
| ORCA/ChemOS laser fixture | 受控 workflow preset、fixture raw outputs、spectra/gain parser、result summary | `backend/app/computation_adapters/orca_chemos_laser.py`、`backend/app/computation_adapters/chemos_laser_parser.py` | 部分完成；真实 external executor 未接入 |

### 3.3 Artifact、结果和审计

| 能力 | 当前实现 | 主要文件 | 状态 |
|---|---|---|---|
| artifact 类型扩展 | `result_json/log_text/structure_json/input_json/error_json/sdf/xyz/spectrum_json/metrics_json` | `backend/app/schemas/computation.py` | 已完成 |
| artifact 登记 | adapter 产物统一由 service 校验路径、计算 checksum 并登记 | `backend/app/services/computation_service.py` | 已完成 |
| 预览和结构/光谱 API | `/preview`、`/structure`、`/spectrum`、`/download` | `backend/app/api/v1/endpoints/computations.py` | 已完成 MVP |
| artifact 下载认证 | 前端已改为 axios blob 下载，可携带 Authorization header | `frontend/src/api/polyAgentApi.js`、`frontend/src/views/ComputationRunsView.vue` | 已完成短期方案 |
| 请求追踪 | middleware 生成或继承 `X-Request-Id`，写入 `request.state.request_id` | `backend/app/main.py` | 已完成 |
| 审计事件 | computation、artifact、campaign、suggestion、observation、automation、integration config 有事件 | `backend/app/services/*_service.py` | 部分完成；actor role/ip/source 仍需细化 |

### 3.4 优化闭环

| 能力 | 当前实现 | 主要文件 | 状态 |
|---|---|---|---|
| campaign | 创建、列表、详情，状态支持 draft/running/paused/completed/failed/archived | `backend/app/schemas/optimization.py`、`backend/app/services/optimization_service.py` | 已完成 MVP；缺状态管理 API |
| candidate 导入 | JSON 批量导入、ChemOS demo 导入、descriptor 生成 | `backend/app/services/optimization_service.py` | 部分完成；缺 CSV 上传/失败行/重复行报告 |
| descriptor | `candidate_descriptor.v1`，RDKit Morgan 或 SMILES hash fallback | `backend/app/services/optimization_service.py` | 已完成 MVP |
| planner request/response | `planner_request.v1`、`planner_response.v1`，suggestion 保存 request/response 快照 | `backend/app/schemas/optimization.py`、`backend/app/services/optimization_service.py` | 已完成 MVP |
| fallback planner | 按稳定 key 顺序选择未评价候选 | `backend/app/services/planner_adapters.py` | 已完成 |
| tanimoto planner | 基于最佳 observation 的 Tanimoto 相似度推荐 | `backend/app/services/planner_adapters.py` | 已完成轻量版 |
| suggestion 转 computation | 幂等提交 `MOCK_LASER` computation run | `backend/app/services/optimization_service.py` | 已完成 MVP；缺 workflow 可配置 |
| observation | 手工写入、从 completed `MOCK_LASER/ORCA_CHEMOS_LASER` run 映射目标值 | `backend/app/services/optimization_service.py` | 已完成 MVP；手工 observation 目标字段校验不足 |
| automation | completed computation 可按配置自动创建 observation 和下一轮 suggestion | `backend/app/workers/computation_worker.py`、`backend/app/services/optimization_service.py` | 已完成 MVP |
| history | 返回 candidate/suggestion/observation 时间线 | `backend/app/services/optimization_service.py` | 已完成 MVP |

### 3.5 集成配置和状态

| 能力 | 当前实现 | 主要文件 | 状态 |
|---|---|---|---|
| 集成状态探测 | worker/artifact/ChemOS ports/AiiDA/SpecLabOS/RDKit/OpenBabel/xTB/Docker | `backend/app/services/integration_status_service.py` | 已完成 MVP |
| service_integrations 配置 | 持久化 endpoint/config_summary/secret_refs/last_status | `backend/app/services/integration_config_service.py`、`backend/app/schemas/integrations.py` | 已完成后端 MVP |
| 配置安全 | 拒绝 token/password/api_key/secret/private_key 等明文字段 | `backend/app/schemas/integrations.py`、`backend/app/services/integration_config_service.py` | 已完成 |
| 管理 API | list/upsert/check integration configs，管理员权限保护 | `backend/app/api/v1/endpoints/integrations.py` | 已完成后端 MVP |
| 前端配置管理 | Tool Services 主要展示 status | `frontend/src/views/ToolServicesView.vue` | 部分完成；config CRUD 前端未完整接入 |

### 3.6 前端页面

| 页面 | 当前能力 | 主要文件 | 状态 |
|---|---|---|---|
| 计算提交 | 支持 mock/local structure/local xTB/ORCA ChemOS workflow 选项 | `frontend/src/views/ComputationSubmitView.vue` | 已完成 MVP |
| 计算任务中心 | 列表、筛选、轮询、详情 drawer、timeline、artifact、blob 下载、spectrum SVG 预览 | `frontend/src/views/ComputationRunsView.vue` | 已完成 MVP；结构可视化仍较轻 |
| Campaign 列表 | 创建 campaign、导入 ChemOS、生成推荐 | `frontend/src/views/CampaignsView.vue` | 已完成 MVP |
| Campaign 详情 | candidates/suggestions/observations/history，提交计算和生成 observation | `frontend/src/views/CampaignDetailView.vue` | 已完成 MVP；缺 reject/failed 操作 |
| API client | computation、optimization、integration status API 已封装 | `frontend/src/api/polyAgentApi.js` | 部分完成；integration config API 未封装 |

### 3.7 测试

| 测试 | 覆盖 | 文件 | 状态 |
|---|---|---|---|
| MVP smoke | worker/artifact/audit、failed retry、campaign 到 observation 闭环 | `backend/tests/test_computation_mvp.py` | 已有 |
| computation service | workflow/engine 组合校验、失败 retry、artifact path 越界 | `backend/tests/test_computation_service.py` | 已有 |
| local structure | 缺依赖失败、OpenBabel fake CLI 成功 | `backend/tests/test_local_structure_adapter.py` | 已有 |
| local xTB | 缺依赖、成功、非零退出、timeout/retry | `backend/tests/test_local_xtb_adapter.py` | 已有 |
| ORCA/ChemOS laser | 输入安全、fixture parser artifact、未配置失败、observation 映射 | `backend/tests/test_orca_chemos_laser_workflow.py` | 已有 |
| optimization service | import/generate/submit/observation、descriptor、tanimoto、automation | `backend/tests/test_optimization_service.py` | 已有 |
| integration config | 密钥字段拒绝、upsert/check、API 权限 | `backend/tests/test_integration_config_service.py` | 已有 |
| 前端 e2e | 浏览器路径、可视化和下载行为 | 暂无 | 待补 |

## 4. 和 PRD 的差距

### 4.1 P0 需求覆盖

| PRD ID | 需求 | 当前状态 | 剩余工作 |
|---|---|---|---|
| COMP-001 | 创建计算任务 | 已完成 | 补充 API 文档样例；submit suggestion 的目标 workflow 仍硬编码为 `MOCK_LASER` |
| COMP-002 | 查询任务列表 | 部分完成 | 加 owner/权限过滤，管理员可看全部 |
| COMP-003 | 查询任务详情 | 部分完成 | 详情权限校验；真实 external refs 展示仍有限 |
| COMP-004 | worker 推进状态 | 已完成 MVP | 增加 heartbeat、stale running reclaim、graceful shutdown |
| COMP-005 | 取消任务 | 部分完成 | queued/running 均可置 cancelled，但运行中 subprocess/HPC job 取消语义未闭合 |
| COMP-006 | 重试任务 | 已完成 MVP | 增加 retry policy、retry reason、max retry 约束 |
| ART-001 | artifact 元数据 | 已完成 | 增加索引初始化或启动校验 |
| ART-002 | artifact 下载审计 | 已完成短期方案 | 大文件/跨域场景可后续做短期 download token |
| ART-003 | parser metadata | 已完成 MVP | parser version 后续要跟真实 parser 发布版本绑定 |
| OPT-001 | 创建 campaign | 已完成 MVP | 增加 pause/resume/archive/complete API |
| OPT-002 | 导入候选 | 部分完成 | 缺 CSV 上传/CSV 文本导入、失败行报告、重复行报告、导入任务审计明细 |
| OPT-003 | 写入 observation | 部分完成 | 手工写入缺 objective schema 校验，可能写入非目标字段 |
| OPT-004 | fallback suggestion | 已完成 | 已额外实现 tanimoto planner |
| OPT-005 | suggestion 状态流转 | 部分完成 | schema 有 rejected/failed，但缺 reject/failed API、原因记录和审计路径 |
| INT-001 | 集成状态展示 | 部分完成 | 后端配置已持久化；前端配置 CRUD 未完整接入，真实外部系统仍未连接 |
| AUD-001 | 关键操作审计 | 部分完成 | 主流程覆盖；权限拒绝、reject/failed、running cancel、外部 job 事件待补 |
| AUD-002 | 请求追踪 | 已完成 MVP | integration config endpoints 应统一从 `request.state.request_id` 读取，而不是只读 header |
| AUD-003 | 操作人记录 | 部分完成 | computation worker 记录 system；optimization service 仍固定 user，client ip/source 未记录 |
| AUD-004 | 外部引用记录 | 部分完成 | ORCA/HPC/AiiDA/SpecLabOS 真实 external ids 未接入 |

### 4.2 参考项目目标覆盖

| 目标能力 | 当前状态 | 建议优先级 |
|---|---|---|
| RDKit/OpenBabel local adapter | 已实现 local structure adapter | 已完成 MVP；继续做运行环境验证 |
| xTB local adapter | 已实现 subprocess adapter、fake toolchain 测试 | 已完成 MVP；继续补真实环境验收、版本/runtime 解析 |
| 真实结构 artifact | 已有 `structure_json/sdf/xyz` | 已完成 MVP |
| 光谱/曲线可视化 | 后端有 `spectrum_json`，前端有基础 SVG 曲线 | 部分完成；补更可靠图表和结构视图 |
| AiiDA worker | 仅 external ref 字段和状态占位 | P2 |
| ORCA laser workflow | 有 fixture parser 和受控配置；external executor 未实现 | P1/P2 |
| ChemOS spectra/gain parser | fixture raw outputs 和 parser 已实现 | 部分完成；需真实输出样本适配 |
| Atlas/Olympus planner | 未接入；已有轻量 tanimoto 替代 | P2/P3 |
| SpecLabOS 实验提交 | 集成配置占位，未提交实验 | P2 |
| SmartAccess 事件 | 未接入 | P3 |
| 对象存储/归档 | 当前是本地 `.runtime/outputs` | P2 |

## 5. 已完成的上一版近期修复点

| 原问题 | 当前状态 | 依据 |
|---|---|---|
| `optimization.py` 文件末尾疑似残留文本 | 已修复 | 文件尾部为正常 FastAPI endpoint |
| middleware 未写 `request.state.request_id` | 已修复 | `backend/app/main.py` 中已赋值 |
| artifact 下载裸 `<a>` 无 Authorization | 已修复短期方案 | `downloadArtifact()` 使用 axios blob 请求 |
| 测试集中在 smoke | 已明显改善 | 已新增 service/local adapter/orca/integration/optimization 单测 |
| adapter 仍是计划项 | 已实现 | `backend/app/computation_adapters/*` 已落地 |
| local structure/xTB 仍是计划项 | 已实现 MVP | `test_local_structure_adapter.py`、`test_local_xtb_adapter.py` 覆盖 |
| planner 标准化仍是计划项 | 已实现 MVP | `PlannerRequest/PlannerResponse` 和 `planner_payload` 已落地 |
| service_integrations 仍是计划项 | 已实现后端 MVP | `integration_config_service.py` 和测试已落地 |

## 6. 当前剩余高优先级缺口

| 缺口 | 影响 | 建议 |
|---|---|---|
| computation/campaign/artifact/audit 缺 owner 权限过滤 | AUTH 开启后可能跨用户看到任务或数据 | 优先补；这是演示转内测前的 P0 |
| candidate import 缺 CSV 和失败行报告 | OPT-002 未满足，导入不可审计 | 定义 `CandidateImportReport`，支持 JSON/CSV 共用导入核心 |
| suggestion 缺 reject/failed API | 状态机不闭合，前端只能 submit/evaluate | 增加状态变更 endpoint、reason、审计 |
| 手工 observation 缺 objective schema 校验 | 会污染 planner 输入和目标统计 | 按 campaign objectives 校验 required/allowed fields |
| worker 无 heartbeat/stale reclaim | 长任务或进程崩溃后 running 任务不可恢复 | 增加 claimed_at/heartbeat_at、超时回收策略 |
| running cancel 不终止本地 subprocess/外部 job | 用户看到 cancelled，但计算可能继续占资源 | local adapter 加可取消进程模型；external executor 加 cancel hook |
| ORCA/ChemOS 真实外部执行器未实现 | 目前只能 fixture 演示 | 先做受控 external job boundary，再接 HPC/AiiDA |
| optimization submit workflow 硬编码 mock laser | 无法从推荐直接提交 ORCA/ChemOS workflow | 在 campaign planner_config 或 submit API 中配置 workflow preset |
| integration config 前端未接入 CRUD | 后端能力无法由管理员页面操作 | 封装 API client 并改 Tool Services 页面 |
| 前端缺 e2e | 下载、图表、权限回归靠人工 | 加 Playwright 最小路径 |

## 7. 后续开发计划

### Phase A: 收敛剩余 MVP/P0 产品缺口

#### Task A1: 数据权限和 owner 过滤

**目标：** AUTH 开启后，普通用户只能看到自己的 computation/campaign/artifact/audit，管理员可看全部。

**验收标准：**
- `GET /computations` 默认按 `created_by` 过滤；admin 可通过参数或角色查看全部。
- `GET /computations/{run_id}`、artifact 列表/预览/下载校验 run owner。
- campaign list/detail/import/suggestion/observation 按 `created_by` 校验。
- audit list 对普通用户只返回自己相关实体事件，admin 可查全量。

**验证：**
- 新增 API/service 测试覆盖 user A 不能读取 user B 的 run/campaign/artifact。
- 现有 smoke/local adapter/optimization 测试继续通过。

**预计改动：**
- `backend/app/api/v1/endpoints/computations.py`
- `backend/app/api/v1/endpoints/optimization.py`
- `backend/app/services/computation_service.py`
- `backend/app/services/optimization_service.py`
- `backend/app/infra/computation_repositories.py`
- `backend/tests/`

**Dependencies:** 无。

#### Task A2: CSV 候选导入和导入报告

**目标：** 满足 OPT-002，支持 JSON/CSV 导入、失败行报告、重复行报告。

**验收标准：**
- 新增 CSV 导入 endpoint，支持 multipart file 或 CSV 文本，字段至少包含 `candidate_key,smiles`。
- 响应包含 `imported_count`、`updated_count`、`failed_rows`、`duplicate_rows`、`items`。
- 单行失败不导致整批失败；文件结构完全不可解析时返回 400。
- 导入审计记录报告摘要，不记录过长原始文件。

**验证：**
- 测试覆盖 valid CSV、缺字段、空 SMILES、重复 candidate_key、已有 key 更新。
- 前端 Campaign 详情可显示最近一次导入报告。

**预计改动：**
- `backend/app/schemas/optimization.py`
- `backend/app/api/v1/endpoints/optimization.py`
- `backend/app/services/optimization_service.py`
- `frontend/src/api/polyAgentApi.js`
- `frontend/src/views/CampaignDetailView.vue`
- `backend/tests/test_optimization_service.py`

**Dependencies:** A1 可并行，但 endpoint 权限最终要合并 A1。

#### Task A3: Suggestion reject/failed 状态 API

**目标：** 补齐 suggestion 状态机，使 `suggested/submitted/evaluated/rejected/failed` 都有明确入口。

**验收标准：**
- 新增 `POST /optimization/suggestions/{suggestion_id}/reject`，记录 reason。
- 新增内部或 API 入口把 submitted suggestion 标记 failed，记录关联 run/error。
- `evaluated/rejected/failed` 不允许再次 submit computation。
- 状态变化写审计事件并进入 campaign history。

**验证：**
- service/API 测试覆盖合法状态转换、重复提交拒绝、history 展示。
- 前端 Campaign 详情支持 reject 操作和 failed/reason 展示。

**预计改动：**
- `backend/app/schemas/optimization.py`
- `backend/app/services/optimization_service.py`
- `backend/app/api/v1/endpoints/optimization.py`
- `frontend/src/api/polyAgentApi.js`
- `frontend/src/views/CampaignDetailView.vue`
- `backend/tests/test_optimization_service.py`

**Dependencies:** 无。

#### Task A4: Observation objective schema 校验

**目标：** 防止手工或自动 observation 写入非目标字段或缺 required objective。

**验收标准：**
- `create_observation` 校验 `values` keys 必须来自 campaign objectives。
- required objective 缺失时返回 400。
- 支持可选 objective 缺失；数值必须是 finite number。
- 自动 observation 沿用同一校验，不重复实现。

**验证：**
- 测试覆盖 unknown field、missing required、optional field、NaN/inf。
- tanimoto/fallback planner 测试继续通过。

**预计改动：**
- `backend/app/services/optimization_service.py`
- `backend/app/schemas/optimization.py`
- `backend/tests/test_optimization_service.py`

**Dependencies:** 无。

#### Task A5: Worker heartbeat、stale reclaim 和运行中取消语义

**目标：** 让生产/长任务场景下 running 任务可观测、可恢复、可取消。

**验收标准：**
- run external refs 或 runtime 字段记录 `worker_id/claimed_at/heartbeat_at`。
- worker 周期性 heartbeat；超过阈值的 running run 可标记 failed 或重新 queued。
- local subprocess adapter 支持 cancel 检查或进程终止。
- cancel running run 写明确 error code，并避免 worker 完成后覆盖 cancelled。

**验证：**
- fake long-running adapter 测试 heartbeat 和取消。
- stale running reclaim 测试覆盖进程崩溃场景。

**预计改动：**
- `backend/app/workers/computation_worker.py`
- `backend/app/services/computation_service.py`
- `backend/app/infra/computation_repositories.py`
- `backend/app/computation_adapters/local_xtb.py`
- `backend/tests/`

**Dependencies:** A1 之后更好做审计 actor/owner 校验，但可先后端内部实现。

#### Checkpoint A

- `python -m unittest backend.tests.test_computation_mvp backend.tests.test_computation_service backend.tests.test_optimization_service` 通过。
- 普通用户跨用户访问被拒绝，管理员路径通过。
- Campaign 导入、推荐、拒绝、提交、observation、history 的主流程可演示。

### Phase B: 真实计算链路硬化

#### Task B1: Local structure/xTB 生产硬化

**目标：** 把已实现的 local adapters 从 fake toolchain 测试扩展到真实环境可验收。

**验收标准：**
- xTB result summary 解析 `xtb_version`、`runtime_seconds`、`normal_termination`。
- 输出日志和 artifact 有大小上限或截断策略，preview 不拖垮服务。
- integration status 显示 RDKit/OpenBabel/xTB 版本、路径和能力；失败原因更明确。
- 文档提供本地依赖安装和 smoke 命令。

**验证：**
- fake toolchain 单测保留。
- 有依赖环境下可手动运行 `LOCAL_STRUCTURE` 和 `LOCAL_XTB` 完整任务。

**预计改动：**
- `backend/app/computation_adapters/local_xtb.py`
- `backend/app/computation_adapters/local_structure.py`
- `backend/app/services/integration_status_service.py`
- `backend/tests/test_local_xtb_adapter.py`
- `doc/`

**Dependencies:** Phase A 不阻塞。

#### Task B2: ORCA/ChemOS external executor 边界

**目标：** 从 fixture parser 过渡到受控外部执行器，不允许用户传 shell 命令或本地路径。

**验收标准：**
- `ORCA_CHEMOS_EXECUTION_MODE=external` 时不再直接返回 `ORCA_EXTERNAL_EXECUTOR_NOT_IMPLEMENTED`。
- 后端按部署配置生成 job workdir 和 job spec，提交到受控 executor。
- run external refs 记录 job id、queue、submitted_at、polled_at。
- 支持 poll completed/failed，收集 ORCA/ChemOS raw outputs，复用现有 parser。
- license/queue/config 不可用时保留明确 failed error artifact。

**验证：**
- fake executor 测试覆盖 submit/poll/success/fail/timeout/cancel。
- fixture parser 测试继续通过。

**预计改动：**
- `backend/app/computation_adapters/orca_chemos_laser.py`
- `backend/app/computation_adapters/chemos_laser_parser.py`
- `backend/app/core/config.py`
- `backend/app/workers/computation_worker.py`
- `backend/tests/test_orca_chemos_laser_workflow.py`

**Dependencies:** A5 对 long-running/cancel 语义有帮助；建议先完成 A5。

#### Task B3: Optimization submit workflow preset

**目标：** suggestion 转 computation 不再硬编码 `MOCK_LASER`，支持按 campaign 配置提交 ORCA/ChemOS 或 mock。

**验收标准：**
- campaign `planner_config.computation_preset` 可配置 workflow/engine/method/resources。
- submit suggestion 时只接受后端白名单 preset，不接受任意命令或路径。
- 前端 Campaign 创建或详情可选择 mock/ORCA fixture preset。
- submitted run 保留 campaign/suggestion 关联，observation 映射不变。

**验证：**
- 测试覆盖 mock preset、ORCA fixture preset、非法 preset 拒绝。

**预计改动：**
- `backend/app/schemas/optimization.py`
- `backend/app/services/optimization_service.py`
- `frontend/src/views/CampaignsView.vue`
- `frontend/src/views/CampaignDetailView.vue`
- `backend/tests/test_optimization_service.py`

**Dependencies:** B2 可后置；第一版可只支持 mock 和 ORCA fixture。

#### Task B4: 结果和结构可视化增强

**目标：** 从“能查看 JSON”升级为“能读懂计算结果”。

**验收标准：**
- `result_json/metrics_json` 以指标表展示，保留 raw JSON 折叠区。
- `spectrum_json` 使用稳定图表组件或更完整 SVG 处理坐标轴、tooltip、空数据。
- `structure_json/xyz/sdf` 至少提供原子表和 3D/2D 轻量 viewer 之一。
- 移动端 drawer 内文本和图表不溢出。

**验证：**
- Playwright 截图覆盖 computation detail、spectrum、structure、下载错误。

**预计改动：**
- `frontend/src/views/ComputationRunsView.vue`
- `frontend/src/api/polyAgentApi.js`
- `frontend/package.json`（如引入图表/分子 viewer 库）
- `frontend/tests/` 或 e2e 脚本

**Dependencies:** 无。

#### Checkpoint B

- mock/local/ORCA fixture 三类 workflow 都能从前端提交并查看 artifact。
- local xTB 在 fake 和真实依赖环境都有明确验收路径。
- ORCA external 至少有 fake executor 可跑通 submit/poll/collect/parser。

### Phase C: 优化与实验闭环增强

#### Task C1: Campaign 状态管理

**目标：** 补齐 campaign lifecycle，而不是只在导入候选时自动 running。

**验收标准：**
- 支持 pause/resume/archive/complete/fail API。
- paused/archived/completed campaign 不允许生成新 suggestion 或提交新 computation。
- 状态变化写审计并进入 history。

**预计改动：**
- `backend/app/services/optimization_service.py`
- `backend/app/api/v1/endpoints/optimization.py`
- `frontend/src/views/CampaignsView.vue`
- `frontend/src/views/CampaignDetailView.vue`
- `backend/tests/test_optimization_service.py`

**Dependencies:** A3 建议先完成。

#### Task C2: Planner 约束和 objective 配置增强

**目标：** 让 fallback/tanimoto 之外的 Atlas/Olympus 或自研 planner 可以接入。

**验收标准：**
- `planner_config.constraints` 有明确 schema 和校验。
- planner adapter 返回 skipped/low_confidence reason，不静默伪装推荐。
- suggestion 保存的 request/response 快照有版本兼容策略。
- 可选接入 Atlas/Olympus 作为独立 adapter，不能成为 FastAPI 必需依赖。

**预计改动：**
- `backend/app/schemas/optimization.py`
- `backend/app/services/planner_adapters.py`
- `backend/app/services/optimization_service.py`
- `backend/tests/test_optimization_service.py`

**Dependencies:** A4。

#### Task C3: SpecLabOS 实验提交占位到真实边界

**目标：** 把 `submitted_experiment_run_id` 从字段占位升级为受控实验提交接口。

**验收标准：**
- 后端定义 SpecLabOS submit preset，不接受用户传任意 endpoint payload。
- suggestion 可提交 experiment run，记录 external id。
- poll/import result 后可创建 observation。
- integration config 中的 speclabos endpoint/secret_refs 被使用但不泄露。

**预计改动：**
- `backend/app/services/integration_config_service.py`
- `backend/app/services/optimization_service.py`
- `backend/app/api/v1/endpoints/optimization.py`
- `backend/tests/`

**Dependencies:** A1、A3、D1。

### Phase D: 运维、审计和存储

#### Task D1: Integration config 前端管理

**目标：** 管理员可在 Tool Services 页面管理后端已实现的 integration configs。

**验收标准：**
- 前端封装 `listIntegrationConfigs/upsertIntegrationConfig/checkIntegrationConfig`。
- Tool Services 展示 enabled、endpoint、last_checked_at、last_status、last_error_summary。
- 支持启用/停用、endpoint/config summary 编辑、手动 check。
- 前端不提供明文密钥输入，只填写 secret ref。

**预计改动：**
- `frontend/src/api/polyAgentApi.js`
- `frontend/src/views/ToolServicesView.vue`

**Dependencies:** A1 的管理员权限语义。

#### Task D2: 审计字段增强

**目标：** 审计从“有事件”升级到“可追责”。

**验收标准：**
- audit event 记录 actor role、client ip、user agent/source。
- optimization worker/automation 事件 actor role 不再固定 user。
- 权限拒绝、配置变更、external job submit/poll/cancel 均有事件。
- request_id 来源统一：endpoint 都读 `request.state.request_id`。

**预计改动：**
- `backend/app/services/computation_service.py`
- `backend/app/services/optimization_service.py`
- `backend/app/services/integration_config_service.py`
- `backend/app/api/v1/endpoints/*`
- `backend/tests/`

**Dependencies:** A1。

#### Task D3: Artifact 存储归档和对象存储边界

**目标：** 从本地 `.runtime/outputs` 过渡到可归档、可迁移的 artifact store。

**验收标准：**
- storage_uri 支持 backend-owned scheme，例如 `local://` 或 `s3://` 摘要。
- 下载/预览不直接暴露本地绝对路径。
- 大文件支持 stream 或 signed URL/token。
- artifact retention/archive policy 可配置。

**预计改动：**
- `backend/app/services/computation_service.py`
- `backend/app/infra/`
- `backend/app/schemas/computation.py`
- `frontend/src/api/polyAgentApi.js`
- `backend/tests/`

**Dependencies:** B1 和 D2。

## 8. 建议执行顺序

1. Phase A 先做 A1、A2、A3、A4，补齐产品闭环和权限风险。
2. A5 与 B2 联动，先定义 worker heartbeat/cancel，再接 ORCA external executor。
3. B3 让 optimization 能选择 ORCA fixture/external preset，打通真实 ChemOS laser 演示路径。
4. B4 和 D1 改善前端演示质量和管理员可操作性。
5. C/D 后续按真实实验接入和生产部署节奏推进。

## 9. 下一次计划更新检查清单

- [ ] 文档中的“已完成”项均有代码或测试对应。
- [ ] 每个未完成项都有明确 owner 边界、验收标准和验证方式。
- [ ] 新增功能不绕过 workflow/engine/preset 白名单。
- [ ] AUTH 开启后所有读取和下载路径都有权限校验。
- [ ] worker 崩溃、取消、重试、外部任务失败均有明确状态和审计。
