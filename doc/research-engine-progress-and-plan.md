# ResearchEngine P0 进度与当前状态

版本：v0.2
日期：2026-07-07
来源设计：`doc/research-engine-and-auto-research-design.md`  
实施计划：`doc/research-engine-plan-00-roadmap.md`

---

## P0 总体完成状态

| 计划 | 文件 | 状态 | 完成日期 |
| --- | --- | --- | --- |
| Plan 01 | `research-engine-plan-01-domain-foundation.md` | ✅ 已完成 | 2026-07-06 |
| Plan 02 | `research-engine-plan-02-problem-spec-and-registry-api.md` | ✅ 已完成 | 2026-07-06 |
| Plan 03 | `research-engine-plan-03-manual-algorithm-channel.md` | ✅ 已完成 | 2026-07-06 |
| Plan 04 | `research-engine-plan-04-autoresearch-orchestrator.md` | ✅ 已完成 | 2026-07-06 |
| Plan 05 | `research-engine-plan-05-frontend-mvp.md` | ✅ 已完成 | 2026-07-06 |
| Plan 06 | `research-engine-plan-06-traceability-and-qa.md` | ✅ 已完成 | 2026-07-06 |

---

## 当前代码状态摘要

截至 2026-07-07，ResearchEngine 已从“规划阶段”进入 P0 可用状态。当前代码提供以下主路径：

| 主路径 | 当前能力 | 主要入口 |
| --- | --- | --- |
| 研发任务定义 | 创建、查询、更新、冻结、归档 ProblemSpec；支持材料体系、问题类型、变量、目标、约束和测量条件 | `POST/GET/PATCH /api/v1/research-engine/problem-specs` |
| 执行路径选择 | 在 ProblemSpec 下创建并查询 `manual_workbench` / `autoresearch` ExecutionDecision | `/api/v1/research-engine/problem-specs/{id}/execution-decisions` |
| 人工算法 Workflow | 创建、归档 ManualAlgorithmWorkflow，启动 WorkflowRun，按步骤生成 AlgorithmRun | `/api/v1/research-engine/manual-workflows` |
| 算法清单 | 自动 seed 计算适配器、生产候选适配器、演示 mock 算法和 computation bridge；支持多条件过滤 | `/api/v1/research-engine/algorithms` |
| AutoResearch | 创建、启动、推进、暂停、恢复、失败标记和归档 ResearchRun；P0 gate 阶段支持批准/拒绝 | `/api/v1/research-engine/research-runs` |
| 示例流程 | 一键创建人工计算 Workflow 示例和 AutoResearch 审批示例 | `/api/v1/research-engine/examples` |
| 追溯审计 | 聚合 AlgorithmRun、ResearchRun、StageRun 的输入、输出、artifact、关联计算任务和 audit | `/api/v1/research-engine/*/traceability` |
| 产品内助手 | 基于项目事实回答 ResearchEngine、计算任务、审批和算法清单问题，返回结构化跳转动作 | `POST /api/v1/assistant/chat` |

前端当前提供 `/research-engine` 双通道工作台、任务中心 ResearchRun/AlgorithmRun 映射、Dashboard 产品内助手、AutoResearch Gate 审批对话框和示例流程入口。

### 算法能力边界

| 类别 | algorithm_id | 当前含义 |
| --- | --- | --- |
| 计算 workflow 适配器 | `local_structure_adapter`、`local_xtb_adapter`、`orca_compute_engine_laser_adapter` | 代表已有 Computation workflow 能力；直接提交统一走 `computation_submit_adapter` |
| 计算提交 bridge | `computation_submit_adapter` | 委托 ComputationService 创建 `LOCAL_STRUCTURE`、`LOCAL_XTB`、`ORCA_COMPUTE_ENGINE_LASER` 计算任务 |
| 生产候选适配器 | `literature_rag_adapter`、`vertical_predictor_adapter`、`mobo_alchemist_adapter` | `literature_rag_adapter` 已接 KnowledgeService，未配置 LightRAG 时返回 AI4S demo fallback；其余适配器依赖外部模型或优化服务 |
| 演示 mock 算法 | `literature_mock`、`polymer_descriptor_mock`、`property_predictor_mock`、`mobo_mock` | 用于 P0 演示、测试和闭环验收，不代表真实生产算法 |

---

## Plan 06 验收结果

### Task 1: Artifact/Audit 聚合查询 ✅

**实现内容：**
- 新增 6 个 traceability schema：`AuditEventItem`、`EntityAuditListData`、`LinkedComputationRef`、`AlgorithmRunTraceability`、`ResearchRunTraceability`、`StageRunTraceability`
- 新增 4 个 API 端点：
  - `GET /api/v1/research-engine/audit` — 审计事件聚合查询（按 entity_type/entity_id/event_type 过滤）
  - `GET /api/v1/research-engine/algorithm-runs/{run_id}/traceability` — AlgorithmRun 完整追溯链
  - `GET /api/v1/research-engine/research-runs/{run_id}/traceability` — ResearchRun 完整追溯链
  - `GET /api/v1/research-engine/research-runs/{run_id}/stages/{stage_run_id}/traceability` — StageRun 追溯链
- 服务层聚合方法：`query_audit_events()`、`get_algorithm_run_traceability()`、`get_research_run_traceability()`、`get_stage_run_traceability()`
- 脱敏处理：不暴露本地敏感路径、secret、storage_uri

**测试结果：** 8/8 traceability 测试通过

### Task 2: P0 端到端后端测试 ✅

**实现内容：**
- 新增 `test_research_engine_e2e.py`，覆盖 11 个 E2E 场景：
  1. 人工运行 mock predictor
  2. 多次人工运行不同算法
  3. 创建并启动 ResearchRun
  4. 推进到 gate 并审批
  4b.拒绝 gate 导致失败
  5. 通过 AlgorithmRun 提交 computation
  7. 完整追溯链验证
  8. 暂停-恢复路径
  9. 手动标记失败
  10. ProblemSpec 全生命周期
  11. 任务中心映射查询

**测试结果：** 11/11 E2E 测试通过

### Task 3: 现有模块回归测试 ✅

**验证命令：**
```bash
pytest tests/test_computation_service.py \
      tests/test_optimization_service.py \
      tests/test_integration_config_service.py \
      tests/test_computation_mvp.py \
      tests/test_local_structure_adapter.py \
      tests/test_local_xtb_adapter.py \
      tests/test_orca_compute_engine_laser_workflow.py
```

**测试结果：** 61/61 全部通过，零回归

### Task 4: 前端构建验证 ✅

**验证命令：** `cd frontend && npm run build`

**构建结果：**
```
dist/index.html         0.77 kB
dist/assets/index.css 396.54 kB
dist/assets/index.js  5936.54 kB
✓ built in 2.10s
```

前端构建成功，无错误。

### Task 5: P0 验收记录 ✅

本文档即为验收记录。

---

## 测试资产统计与当前验证

以下统计按当前测试文件中的 `def test_` 数量整理。本轮文档更新时已运行 ResearchEngine / assistant 相关后端测试；历史回归与前端构建记录来自 P0 验收记录，本轮未重复执行。

| 测试类别 | 文件 | 测试数 | 当前状态 |
| --- | --- | --- | --- |
| ResearchEngine Schema 测试 | `test_research_engine_schemas.py` | 51 | ✅ 本次通过 |
| ResearchEngine 仓储测试 | `test_research_engine_repository.py` | 39 | ⚠️ 本次 38/39，通过失败见下方已知问题 |
| ResearchEngine 服务测试 | `test_research_engine_service.py` | 88 | ✅ 本次通过 |
| ResearchEngine API 测试 | `test_research_engine_api.py` | 82 | ✅ 本次通过 |
| ResearchEngine E2E 测试 | `test_research_engine_e2e.py` | 11 | ✅ 本次通过 |
| ResearchEngine 示例与适配器测试 | `test_research_engine_examples_and_adapters.py` | 6 | ✅ 本次通过 |
| 产品内助手 API 测试 | `test_assistant_api.py` | 3 | ✅ 本次通过 |
| AutoResearch 示例脚本测试 | `test_autoresearch_example.py` | 3 | ✅ 本次通过 |
| 人工 Workflow 示例脚本测试 | `test_manual_workflow_example.py` | 3 | ✅ 本次通过 |
| 已有回归测试 (7文件) | 7 files | 61 | ✅ P0 验收通过，本次未重跑 |
| 前端构建 | — | 1 | ✅ P0 验收通过，本次未重跑 |
| **本次已运行后端测试合计** | 9 files | **286** | **历史记录：284 passed / 2 failed；知识检索相关失败已在知识库接入后修复** |

---

## P0 总体验收对照

| # | 验收标准 | 状态 |
| --- | --- | --- |
| 1 | 用户可创建氟基高分子 ProblemSpec，并关联或创建现有 campaign | ✅ |
| 2 | 用户可从算法清单人工触发 mock/preset 算法，形成 AlgorithmRun、输入快照、输出摘要、artifact/audit | ✅ |
| 3 | 用户可基于同一个 ProblemSpec 创建 ResearchRun，并启动固定阶段推进 | ✅ |
| 4 | ResearchRun 至少能推进到 `RECOMMENDATION_ASK` 或 `HUMAN_REVIEW` gate | ✅ `KNOWLEDGE_RETRIEVAL` 可通过 `literature_rag_adapter` 调用 KnowledgeService；未配置 LightRAG 时返回 AI4S demo fallback |
| 5 | 用户可批准或拒绝候选；批准路径复用现有 suggestion/computation/observation 能力 | ⚠️ 拒绝路径可用；批准后继续推进依赖后续适配器配置 |
| 6 | ResearchRun / AlgorithmRun / StageRun 详情可查看关键输入、输出、artifact 和 audit | ✅ |
| 7 | 现有 computation、optimization、integration config 测试不回退 | ✅ |
| 8 | 前端构建通过，任务提交、湿实验优化、Campaign 详情、任务中心、Dashboard 助手和 ResearchEngine 入口可用 | ✅ |

---

## Checkpoint C 验收

- [x] 后端 ResearchEngine e2e 测试通过（11/11）
- [x] 现有 computation / optimization / integration 回归测试通过（61/61）
- [x] 前端构建通过
- [x] 手工验收脚本完成并记录

---

## 新增/修改文件清单（Plan 06）

### 修改的文件
| 文件 | 变更内容 |
| --- | --- |
| `backend/app/schemas/research_engine.py` | 新增 6 个 traceability schema（AuditEventItem、EntityAuditListData、LinkedComputationRef、AlgorithmRunTraceability、ResearchRunTraceability、StageRunTraceability） |
| `backend/app/services/research_engine_service.py` | 新增 `query_audit_events()`、`get_algorithm_run_traceability()`、`get_research_run_traceability()`、`get_stage_run_traceability()` 方法及辅助方法 `_resolve_computation_ref()`、`_resolve_observations()` |
| `backend/app/api/v1/endpoints/research_engine.py` | 新增 4 个 traceability API 端点（GET /audit、GET /algorithm-runs/{id}/traceability、GET /research-runs/{id}/traceability、GET /research-runs/{id}/stages/{stage_id}/traceability） |

### 新增的文件
| 文件 | 内容 |
| --- | --- |
| `backend/tests/test_research_engine_e2e.py` | P0 端到端测试，覆盖 11 个闭环场景 |

### P0 后续增量文件
| 文件 | 内容 |
| --- | --- |
| `backend/app/api/v1/endpoints/assistant.py` | 产品内助手结构化 API，基于算法清单、集成状态和 AutoResearch 阶段事实回答问题 |
| `backend/tests/test_assistant_api.py` | 产品内助手 API 测试 |
| `backend/tests/test_research_engine_examples_and_adapters.py` | 示例流程和适配器边界测试 |
| `backend/tests/test_autoresearch_example.py` | AutoResearch 审批、拒绝、暂停恢复示例测试 |
| `backend/tests/test_manual_workflow_example.py` | 人工单算法、串行 Pipeline、计算提交 Workflow 示例测试 |
| `frontend/src/views/research-engine/PipelineRunPanel.vue` | 人工多步骤 Workflow / Pipeline 配置与运行面板 |
| `doc/autoresearch-user-guide.md` | AutoResearch 用户操作指南 |

---

## P0 边界与遗留事项

### P0 不包含的内容（按计划）
- 不 vendor `refer/AutoResearchClaw-main` 整仓代码
- 不实现真实 LabOS / SpecLabOS 设备提交
- 不做复杂 RBAC（但已预留字段）
- 不新增大型状态管理或 UI 框架
- 不实现完整模型训练平台

### 已知限制
1. **Computation adapter 映射**：`local_structure_adapter`、`local_xtb_adapter`、`orca_compute_engine_laser_adapter` 三个 algorithm_id 在 AlgorithmRegistry 中存在，但用户直接调用时需使用 `computation_submit_adapter`（P1 建议统一映射）
2. **Mock stage 输出**：非 gate 阶段的 mock runner 输出为预设数据，P1 可接入真实算法
3. **真实观测回填**：当前 observation 主要通过 campaign_id 和 computation 结果关联，P1 可增强 ResearchRun 级别 observation、失败原因和实验原始文件回填
4. **生产候选适配器配置**：`literature_rag_adapter` 已接入 KnowledgeService，未配置 LightRAG 时使用 AI4S demo fallback；`vertical_predictor_adapter`、`mobo_alchemist_adapter` 仍需要配置模型服务或 Alchemist 服务后才可作为生产能力使用
5. **产品内助手边界**：assistant 已做事实约束和确定性回答分支，但复杂问题仍可能走 LLM fallback，回答必须继续以 live facts 为准

### 历史已知测试失败与当前状态

本次运行命令：

```bash
python -m pytest backend/tests/test_research_engine_schemas.py \
  backend/tests/test_research_engine_repository.py \
  backend/tests/test_research_engine_service.py \
  backend/tests/test_research_engine_api.py \
  backend/tests/test_research_engine_e2e.py \
  backend/tests/test_research_engine_examples_and_adapters.py \
  backend/tests/test_assistant_api.py \
  backend/tests/test_autoresearch_example.py \
  backend/tests/test_manual_workflow_example.py -q
```

历史结果：`284 passed, 2 failed`。本次知识库接入后已单独验证 `test_autoresearch_example.py` 通过。

| 失败用例 | 当前表现 | 初步定位 |
| --- | --- | --- |
| `ProblemSpecRepositoryTest.test_list_by_status` | 查询 `status="frozen"` 返回 2 条而非 1 条 | demo store 路径下 `list_problem_specs()` 对显式 status 过滤处理不完整 |
| `AutoResearchExampleTest.test_autoresearch_with_gate_approval` | 历史失败：批准 `PROBLEM_SPEC` 后 ResearchRun 进入 `failed`，随后 `/advance` 返回 409 | ✅ 本次已通过；未配置 LightRAG 时 `literature_rag_adapter` 返回 demo evidence，不再因 `configured=false` 触发失败路径 |

### P1/P2 候选计划（不在 P0 范围）
- P1：Schema 驱动算法表单增强和 AlgorithmRegistry 管理
- P1：ResearchRun checkpoint/rerun 完整恢复语义和阶段级重跑
- P1：ModelUpdate、lesson、archive 和策略收益记录
- P1：computation adapter algorithm_id 统一映射
- P1：生产候选适配器接入真实文献索引、垂类预测服务和 MOBO 服务
- P2：多材料 profile 模板和默认 stage algorithm 配置
- P2：真实 SpecLabOS / AiiDA / ORCA / HPC 外部执行器

---

## 验证命令速查

```bash
# 全部 ResearchEngine 测试（含 E2E）
cd backend && python -m pytest tests/test_research_engine_*.py -v

# ResearchEngine 示例与产品内助手测试
cd backend && python -m pytest tests/test_research_engine_examples_and_adapters.py tests/test_autoresearch_example.py tests/test_manual_workflow_example.py tests/test_assistant_api.py -v

# 只运行 traceability 测试
cd backend && python -m pytest tests/test_research_engine_api.py -k traceability -v

# 只运行 E2E 测试
cd backend && python -m pytest tests/test_research_engine_e2e.py -v

# 已有模块回归测试
cd backend && python -m pytest tests/test_computation_service.py tests/test_optimization_service.py tests/test_integration_config_service.py tests/test_computation_mvp.py tests/test_local_structure_adapter.py tests/test_local_xtb_adapter.py tests/test_orca_compute_engine_laser_workflow.py -v

# 前端构建
cd frontend && npm run build
```
