# ChemOS 计算智能模块当前进展与后续开发计划

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | Current progress snapshot and implementation plan |
| 日期 | 2026-07-01 |
| 对照文档 | `doc/chemos-computation-product-prd.md`、`doc/chemos-computation-product-design.md`、`doc/chemos-computation-migration-design.md` |
| 代码范围 | `backend/app`、`frontend/src`、`backend/tests`、`scripts/run_chemos.sh` |

本文记录当前代码相对 PRD 和 ChemOS 参考项目目标的实际进展、剩余差距和后续逐步开发顺序。

## 2. 总体判断

当前版本已经从“文档设计”推进到“可跑通 MVP 闭环原型”：

```text
创建 computation run
  -> mock worker 领取/推进
  -> 生成 artifact/result summary
  -> 前端查看 timeline、artifact、集成状态
  -> 创建 campaign
  -> 导入候选
  -> 生成 suggestion
  -> suggestion 转 computation
  -> completed run 转 observation
  -> campaign history 追踪
```

按当前 PRD 目标估算：

| 口径 | 当前完成度 | 判断 |
|---|---:|---|
| MVP/P0 产品闭环 | 约 70%-75% | 主流程已通，仍缺权限审计细化、CSV 导入、失败行报告、worker 运维化和若干边界修复 |
| Phase 1 可演示计算智能模块 | 约 60%-65% | 前后端可演示，但真实可视化和生产级 worker 还不足 |
| 完整参考项目目标 Phase 1-7 | 约 30%-35% | AiiDA/ORCA/xTB/Atlas/SpecLabOS 真实适配尚未开始或仅有边界占位 |

核心结论：当前版本适合作为“mock/local MVP 基线”，下一步不应直接跳到 AiiDA/ORCA，而应先把现有 MVP 收敛为稳定、可测试、可审计的第一版。

## 3. 当前已完成内容

### 3.1 后端计算任务

| 能力 | 当前实现 | 主要文件 | 状态 |
|---|---|---|---|
| 创建计算任务 | `POST /api/v1/computations`，白名单 `MOCK_XTB_ONLY`、`MOCK_LASER`、`MOCK` | `backend/app/api/v1/endpoints/computations.py`、`backend/app/schemas/computation.py` | 已完成 MVP |
| 任务列表/详情 | 支持分页、status、workflow、engine、keyword 筛选 | `backend/app/services/computation_service.py` | 已完成 MVP |
| 取消/重试 | 非终态取消，failed/cancelled 生成 retry run | `backend/app/services/computation_service.py` | 已完成 MVP |
| mock worker | 可原子领取 queued run，生成 completed/failed 结果 | `backend/app/workers/computation_worker.py` | 已完成 MVP |
| 本地 demo store | MongoDB 不可用时回退 JSON 存储 | `backend/app/infra/demo_store.py`、`backend/app/infra/computation_repositories.py` | 已完成 MVP |

### 3.2 Artifact、结果和审计

| 能力 | 当前实现 | 主要文件 | 状态 |
|---|---|---|---|
| artifact 元数据 | 登记 `artifact_id/run_id/step_key/type/size/checksum/parser` | `backend/app/schemas/computation.py` | 已完成 MVP |
| artifact 文件 | mock 生成 `structure.json`、`result.json`、`worker.log` | `backend/app/services/computation_service.py` | 已完成 MVP |
| 预览和下载 | `/preview`、`/structure`、`/spectrum`、`/download` | `backend/app/api/v1/endpoints/computations.py` | 已完成 MVP |
| 路径边界 | artifact 路径限制在 `settings.outputs_root` | `backend/app/services/computation_service.py` | 已完成 MVP |
| 审计事件 | computation、artifact、campaign、suggestion、observation 有事件 | `backend/app/services/*_service.py` | 部分完成 |

### 3.3 优化闭环

| 能力 | 当前实现 | 主要文件 | 状态 |
|---|---|---|---|
| campaign | 创建、列表、详情 | `backend/app/api/v1/endpoints/optimization.py` | 已完成 MVP |
| candidate | JSON 批量导入、ChemOS demo 候选导入、可选 RDKit descriptor | `backend/app/services/optimization_service.py` | 部分完成 |
| suggestion | fallback planner 选择未评价候选 | `backend/app/services/optimization_service.py` | 已完成 MVP |
| suggestion 转 computation | 幂等提交 `MOCK_LASER` computation run | `backend/app/services/optimization_service.py` | 已完成 MVP |
| observation | 手工写入、从 completed `MOCK_LASER` run 映射 `gain_factor` | `backend/app/services/optimization_service.py` | 已完成 MVP |
| history | 返回 candidate/suggestion/observation 时间线 | `backend/app/services/optimization_service.py` | 已完成 MVP |

### 3.4 前端页面

| 页面 | 当前能力 | 主要文件 | 状态 |
|---|---|---|---|
| 计算提交 | 表单提交 computation，支持创建优化闭环 demo | `frontend/src/views/ComputationSubmitView.vue` | 已完成 MVP |
| 计算任务中心 | 列表、筛选、轮询、详情 drawer、timeline、artifact、集成状态 | `frontend/src/views/ComputationRunsView.vue` | 已完成 MVP |
| Campaign 列表 | 创建 campaign、导入 ChemOS、生成推荐 | `frontend/src/views/CampaignsView.vue` | 已完成 MVP |
| Campaign 详情 | suggestions/candidates/observations/history，提交计算和生成 observation | `frontend/src/views/CampaignDetailView.vue` | 已完成 MVP |
| API client | computation、optimization、integration API 已封装 | `frontend/src/api/polyAgentApi.js` | 已完成 MVP |

### 3.5 测试

| 测试 | 覆盖 | 文件 | 状态 |
|---|---|---|---|
| smoke test | worker/artifact/audit、failed retry、campaign 到 observation 闭环 | `backend/tests/test_computation_mvp.py` | 已有基础覆盖 |

## 4. 和 PRD 的差距

### 4.1 P0 需求覆盖

| PRD ID | 需求 | 当前状态 | 剩余工作 |
|---|---|---|---|
| COMP-001 | 创建计算任务 | 已完成 | 补充更严格 workflow/engine 错误信息和文档样例 |
| COMP-002 | 查询任务列表 | 已完成 | 加 owner/权限过滤 |
| COMP-003 | 查询任务详情 | 已完成 | 详情增加更明确 external refs 展示 |
| COMP-004 | mock worker 推进状态 | 已完成 | 从 lazy advance 过渡到稳定 worker/heartbeat |
| COMP-005 | 取消任务 | 已完成 | worker 并发取消语义需收敛 |
| COMP-006 | 重试任务 | 已完成 | 重试策略需要在 API 响应和审计中更明确 |
| ART-001 | artifact 元数据 | 已完成 | 增加索引初始化脚本或启动校验 |
| ART-002 | artifact 下载审计 | 部分完成 | 认证开启时浏览器下载链接缺少 Authorization header，需要改成 tokenized download 或 API blob 下载 |
| ART-003 | parser metadata | 已完成 | parser version 后续要跟真实 parser 发布版本绑定 |
| OPT-001 | 创建 campaign | 已完成 | 增加 status 管理和归档策略 |
| OPT-002 | 导入候选 | 部分完成 | 目前支持 JSON/ChemOS demo；缺 CSV 上传、失败行报告和重复行报告 |
| OPT-003 | 写入 observation | 已完成 | 增加 objective schema 校验，防止写入非目标字段 |
| OPT-004 | fallback suggestion | 已完成 | 需要更清楚的 planner 输入/输出契约 |
| OPT-005 | suggestion 状态流转 | 部分完成 | 已有 suggested/submitted/evaluated；缺 rejected/failed API 和审计路径 |
| INT-001 | 集成状态展示 | 已完成 | 目前是探测摘要；缺 service_integrations 持久化配置 |
| AUD-001 | 关键操作审计 | 部分完成 | 覆盖了主流程；集成配置、reject/failed 等路径还缺 |
| AUD-002 | 请求追踪 | 部分完成 | 前端传 `X-Request-Id` 可记录；后端生成的 request_id 尚未写入 `request.state` 给业务审计使用 |
| AUD-003 | 操作人记录 | 部分完成 | actor 有记录；role 固定为 user，client ip/source 未记录 |
| AUD-004 | 外部引用记录 | 部分完成 | 主要实体有关联；AiiDA/SpecLabOS 真实 external ids 尚未接入 |

### 4.2 参考项目目标未完成内容

| 目标能力 | 当前状态 | 建议优先级 |
|---|---|---|
| RDKit/OpenBabel/xTB local adapter | 仅 descriptor 可选使用 RDKit，计算仍是 mock | P1 |
| 真实结构 artifact | 目前是 mock structure JSON | P1 |
| 光谱/曲线可视化 | 后端有 spectrum JSON，前端仍以 JSON/table 为主 | P1 |
| AiiDA worker | 仅 external ref 字段和状态占位 | P2 |
| ORCA laser workflow | 未接入 | P3 |
| ChemOS spectra/gain parser | 仅 mock gain_factor | P3 |
| Atlas/Olympus planner | 未接入，仅 fallback planner | P2/P3 |
| SpecLabOS 实验提交 | 仅集成状态占位 | P2 |
| SmartAccess 事件 | 未接入 | P3 |
| 对象存储/归档 | 当前是本地 `.runtime/outputs` | P2 |

## 5. 已发现的近期修复点

这些问题应在继续扩功能前先处理：

| 问题 | 影响 | 建议 |
|---|---|---|
| `backend/app/api/v1/endpoints/optimization.py` 文件末尾存在疑似残留文本 | 可能导致导入或语法异常 | 立即清理并运行后端测试 |
| request middleware 未把生成的 request_id 写入 `request.state.request_id` | 无请求头时审计事件缺 request_id | 在 middleware 中赋值，并补测试 |
| artifact 下载使用普通 `<a>` 链接 | AUTH 开启时无法携带 Authorization header | 改成前端 blob 下载，或后端发短期 download token |
| audit actor role 固定为 `user` | 管理员/worker/系统操作不可区分 | 从 current_user 取 role，worker 使用 `system`/`worker` |
| candidate import 缺失败行报告 | 无法满足 PRD 的可审计导入 | 设计 import report schema |
| optimization suggestion 缺 reject/failed 操作 | 状态机不闭合 | 增加状态变更 API 和审计 |
| 测试集中在 smoke | 回归定位不够细 | 拆分 service/repository/API/frontend e2e 测试 |

## 6. 后续一步一步开发计划

### Phase 0: 稳定当前 MVP 基线

#### Step 0.1 修复当前可疑代码和审计 request_id

**目标：** 先确保后端导入、测试和审计追踪稳定。

**验收标准：**
- 清理 `optimization.py` 末尾残留文本。
- middleware 生成的 request_id 写入 `request.state.request_id`。
- 无请求头请求创建 computation 时，audit event 仍有 request_id。
- `python -m unittest backend.tests.test_computation_mvp` 通过。

**预计改动：**
- `backend/app/main.py`
- `backend/app/api/v1/endpoints/optimization.py`
- `backend/tests/test_computation_mvp.py`

#### Step 0.2 收敛 artifact 下载认证方案

**目标：** AUTH 开启时 artifact 下载仍可用且可审计。

**验收标准：**
- 前端下载不依赖裸 `<a>` 携带 Authorization。
- 下载失败时前端显示明确错误。
- `artifact.downloaded` 事件包含 actor、request_id、run_id、artifact_id。

**建议设计：**
- 短期方案：前端用 axios `blob` 请求下载，并从响应 header 解析文件名。
- 中期方案：后端提供短期 download token，适合大文件和跨域下载。

**预计改动：**
- `frontend/src/api/polyAgentApi.js`
- `frontend/src/views/ComputationRunsView.vue`
- `backend/app/api/v1/endpoints/computations.py`

#### Step 0.3 拆分并补齐测试基线

**目标：** 让后续扩展真实 adapter 前有可依赖的回归网。

**验收标准：**
- computation service 单元测试覆盖 create/cancel/retry/fail。
- artifact path 越界测试覆盖。
- optimization service 测试覆盖 import/generate/submit/observation。
- smoke test 保留为端到端最小链路。

**预计改动：**
- `backend/tests/`

### Phase 1: 补齐 MVP 产品缺口

#### Step 1.1 候选导入报告和 CSV 支持

**目标：** 满足 OPT-002 的 JSON/CSV 导入、失败行报告和重复行处理。

**验收标准：**
- API 支持 CSV 上传或 CSV 文本导入。
- 响应返回 `imported_count`、`updated_count`、`failed_rows`、`duplicate_rows`。
- 前端 Campaign 详情页可查看导入报告。

**设计约束：**
- CSV 字段先限定为 `candidate_key,smiles`，可选 `metadata.*` 后续扩展。
- 导入不应因单行错误整批失败，除非文件结构完全不可解析。

#### Step 1.2 完整 suggestion 状态机

**目标：** 让 suggestion 的 `suggested/submitted/evaluated/rejected/failed` 都有明确入口。

**验收标准：**
- 增加 reject suggestion API。
- 提交计算失败时可标记 failed，并记录 reason。
- evaluated/rejected/failed 状态不允许重复提交计算。
- 前端 Campaign 详情支持 reject 和失败原因展示。

#### Step 1.3 权限和审计补齐

**目标：** 从“能记录事件”升级到“能追责和隔离数据”。

**验收标准：**
- computation/campaign 列表默认只返回本人数据，管理员可看全部。
- audit event 记录 actor role、client ip/source。
- worker 审计 actor_role 为 `worker`，系统自动事件可区分。

#### Step 1.4 前端结果可视化

**目标：** 把 result summary 和 spectrum 从 JSON 文本升级为可读视图。

**验收标准：**
- `result_json` 中的数值指标以 key-value 或小型图表展示。
- `/spectrum` 返回 points 时，前端渲染曲线/柱状图。
- `structure_json` 至少以原子/键表或轻量 2D/3D 占位展示，不只显示原始 JSON。

### Phase 2: 本地真实计算 adapter

#### Step 2.1 定义 computation adapter 接口

**目标：** 把 mock 执行逻辑从 service 中抽离，形成可替换 adapter。

**验收标准：**
- 定义 `ComputationAdapter` 协议：`validate_input`、`run`、`collect_artifacts`、`parse_result`。
- mock adapter 使用同一接口实现。
- worker 不直接知道具体 workflow 内部细节。

#### Step 2.2 接入 RDKit/OpenBabel 结构生成

**目标：** 先交付低风险真实 artifact。

**验收标准：**
- 新增 `LOCAL_STRUCTURE` 或扩展 `MOCK_XTB_ONLY` 为 local structure workflow。
- SMILES 可生成 SDF/XYZ/structure JSON artifact。
- 无 RDKit/OpenBabel 时返回明确 integration status 和错误 artifact。

#### Step 2.3 接入 xTB local adapter

**目标：** 形成第一条非 mock 计算链路。

**验收标准：**
- worker 在子进程或隔离执行目录运行 xTB。
- stdout/stderr、输入文件、输出文件均登记 artifact。
- 超时、失败码、缺依赖能进入 failed 状态并可重试。

### Phase 3: 优化能力增强

#### Step 3.1 descriptor 和 planner 输入标准化

**目标：** 为 Atlas/Tanimoto 或自研 planner 做接口准备。

**验收标准：**
- candidate descriptors 有版本、参数、生成状态。
- planner request 明确包含 candidates、observations、objectives、constraints。
- planner response 明确包含 suggestion、score/reason、iteration metadata。

#### Step 3.2 Atlas/Tanimoto adapter 或轻量替代实现

**目标：** 在离散分子库上引入真实推荐策略。

**验收标准：**
- fallback planner 保留。
- 新 planner 不进入主 FastAPI 重依赖路径，可独立服务或可选依赖。
- campaign 可选择 planner type，并在 suggestion 记录 planner payload。

#### Step 3.3 自动 observation 和下一轮 recommendation

**目标：** 从手动点击生成 observation 过渡到可配置自动闭环。

**验收标准：**
- completed computation 可根据 campaign config 自动生成 observation。
- observation 创建后可按配置自动触发下一轮 suggestion。
- 自动行为必须有审计事件，并允许关闭。

### Phase 4: 外部系统集成

#### Step 4.1 service_integrations 持久化配置

**目标：** 让集成状态从临时探测升级为可管理配置。

**验收标准：**
- MongoDB 保存 integration config 摘要，不保存明文密钥。
- 管理员可查看启用状态、endpoint、最后检查时间和错误摘要。
- 变更配置写审计。

#### Step 4.2 SpecLabOS workflow 提交

**目标：** suggestion 可转实验验证。

**验收标准：**
- `suggestion -> SpecLabOS workflow_run_id` 关系可追踪。
- 上游失败时 suggestion 不进入 evaluated。
- 实验 observation 可和 computation observation 并存。

#### Step 4.3 AiiDA worker 接入

**目标：** 引入真实 provenance 引用，但不把 AiiDA 数据库混入业务库。

**验收标准：**
- computation run 保存 `aiida_process_uuid` 和同步状态。
- AiiDA 失败/完成映射到 Poly_Agent 状态机。
- artifact parser 只保存摘要、checksum 和可下载产物。

### Phase 5: ORCA/ChemOS laser workflow

#### Step 5.1 ORCA workflow 配置化

**目标：** 将 ChemOS laser workflow 的步骤重构为受控 workflow。

**验收标准：**
- workflow step 明确：结构准备、xTB/CREST、ORCA、spectra parser、gain parser。
- 参数全部白名单，不允许前端传 shell command 或本地路径。
- HPC/license/队列错误能明确展示。

#### Step 5.2 spectra/gain parser 产品化

**目标：** 把 ChemOS 后处理结果变成稳定 artifact 和 result summary。

**验收标准：**
- parser 有版本、输入 checksum、输出 schema。
- 光谱数据可前端图形化展示。
- `gain_factor` 等指标能直接进入 observation。

## 7. 建议的开发顺序

短期不要并行推进太多外部系统。推荐顺序：

1. 先做 Phase 0，保证当前 MVP 可测试、可审计、可演示。
2. 再做 Phase 1，把 PRD P0 缺口补齐，形成真正可交付的 MVP。
3. 然后做 Phase 2，用 local adapter 交付第一条真实计算链路。
4. Phase 3 优化 planner 在 local adapter 稳定后再增强。
5. Phase 4/5 的 SpecLabOS、AiiDA、ORCA 应作为独立集成项目推进，每个系统都先做最小闭环，再扩大能力。

下一次开发建议从 **Step 0.1** 开始，因为它风险最低、收益最高，也能验证当前工作区是否处于健康状态。
