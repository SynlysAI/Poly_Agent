# ResearchEngine P0 进度与验收记录

版本：v0.1  
日期：2026-07-06  
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

## 总体测试统计

| 测试类别 | 文件数 | 测试数 | 通过 |
| --- | --- | --- | --- |
| ResearchEngine 单元测试 | `test_research_engine_schemas.py` | 25 | ✅ |
| ResearchEngine 仓储测试 | `test_research_engine_repository.py` | 22 | ✅ |
| ResearchEngine 服务测试 | `test_research_engine_service.py` | 86 | ✅ |
| ResearchEngine API 测试 | `test_research_engine_api.py` | 76 | ✅ |
| ResearchEngine E2E 测试 | `test_research_engine_e2e.py` | 11 | ✅ |
| Traceability API 测试 | `test_research_engine_api.py` (traceability) | 8 | ✅ |
| 已有回归测试 (7文件) | 7 files | 61 | ✅ |
| 前端构建 | — | 1 | ✅ |
| **总计** | | **290** | **全部通过** |

---

## P0 总体验收对照

| # | 验收标准 | 状态 |
| --- | --- | --- |
| 1 | 用户可创建氟基高分子 ProblemSpec，并关联或创建现有 campaign | ✅ |
| 2 | 用户可从算法清单人工触发 mock/preset 算法，形成 AlgorithmRun、输入快照、输出摘要、artifact/audit | ✅ |
| 3 | 用户可基于同一个 ProblemSpec 创建 ResearchRun，并启动固定阶段推进 | ✅ |
| 4 | ResearchRun 至少能推进到 `RECOMMENDATION_ASK` 或 `HUMAN_REVIEW` gate | ✅ |
| 5 | 用户可批准或拒绝候选；批准路径复用现有 suggestion/computation/observation 能力 | ✅ |
| 6 | ResearchRun / AlgorithmRun / StageRun 详情可查看关键输入、输出、artifact 和 audit | ✅ |
| 7 | 现有 computation、optimization、integration config 测试不回退 | ✅ |
| 8 | 前端构建通过，任务提交、湿实验优化、Campaign 详情、Tool Services 中的 ResearchEngine 入口可用 | ✅ |

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
3. **真实观测回填**：当前 observation 关联通过 campaign_id，P1 可增强 ResearchRun 级别的 observation 来��

### P1/P2 候选计划（不在 P0 范围）
- P1：Schema 驱动算法表单增强和 AlgorithmRegistry 管理
- P1：ResearchRun pause/resume/checkpoint/rerun 完整恢复语义
- P1：ModelUpdate、lesson、archive 和策略收益记录
- P1：computation adapter algorithm_id 统一映射
- P2：多材料 profile 模板和默认 stage algorithm 配置
- P2：真实 SpecLabOS / AiiDA / ORCA / HPC 外部执行器

---

## 验证命令速查

```bash
# 全部 ResearchEngine 测试（含 E2E）
cd backend && python -m pytest tests/test_research_engine_*.py -v

# 只运行 traceability 测试
cd backend && python -m pytest tests/test_research_engine_api.py -k traceability -v

# 只运行 E2E 测试
cd backend && python -m pytest tests/test_research_engine_e2e.py -v

# 已有模块回归测试
cd backend && python -m pytest tests/test_computation_service.py tests/test_optimization_service.py tests/test_integration_config_service.py tests/test_computation_mvp.py tests/test_local_structure_adapter.py tests/test_local_xtb_adapter.py tests/test_orca_compute_engine_laser_workflow.py -v

# 前端构建
cd frontend && npm run build
```
