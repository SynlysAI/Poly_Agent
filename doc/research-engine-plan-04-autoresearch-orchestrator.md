# Plan 04：AutoResearch 材料版编排器

## 目标

实现材料研发专用 ResearchRun 和 Stage/Gate 状态机。P0 只做固定阶段序列、mock 阶段推进、候选 gate 审批和现有 computation/optimization 复用，不迁移 AutoResearchClaw 原代码。

## 范围

- ResearchRun 创建、启动、暂停、恢复的最小语义。
- ResearchStageRun 创建和推进。
- `RECOMMENDATION_ASK` / `HUMAN_REVIEW` gate。
- 审批、拒绝、原因记录和 audit。
- 批准候选后复用现有 suggestion/computation/observation 路径。

## 不做

- 不做复杂 branch exploration。
- 不做真实模型更新。
- 不做完整 checkpoint replay，只保存最近 checkpoint snapshot，恢复语义可先有限支持。

## 任务列表

### Task 1：ResearchRun service

**说明：** 创建 ResearchRun，并基于 ProblemSpec 生成默认 stage_runs。

**验收标准：**
- [ ] `create_research_run(problem_spec_id)` 生成 draft run。
- [ ] ResearchRun 关联 `problem_spec_id`、`campaign_id`、`profile_id`。
- [ ] 默认 stage_runs 按材料版阶段序列生成。
- [ ] 创建和状态变更写 AuditEvent。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_service.py -k research_run_create`

**依赖：** Plan 01-03

**可能触达文件：**
- `backend/app/services/research_engine_orchestrator.py`
- `backend/app/services/research_engine_service.py`
- `backend/tests/test_research_engine_service.py`

**规模：** M

### Task 2：固定阶段推进

**说明：** 实现 start/advance 逻辑，自动完成低风险 mock stage，在 gate 阶段阻塞。

**验收标准：**
- [ ] 启动 ResearchRun 后从 `PROBLEM_SPEC` 开始推进。
- [ ] `KNOWLEDGE_RETRIEVAL`、`STRUCTURE_FEATURE`、`COMPUTE_PREDICT` 可用 mock runner 生成阶段输出。
- [ ] 到达 `RECOMMENDATION_ASK` 或 `HUMAN_REVIEW` 时进入 `blocked_approval`。
- [ ] 每个阶段保存 input snapshot、output summary、artifact refs、status、error。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_service.py -k orchestrator_advance`

**依赖：** Task 1、Plan 03 mock runner

**可能触达文件：**
- `backend/app/services/research_engine_orchestrator.py`
- `backend/tests/test_research_engine_service.py`

**规模：** M

### Task 3：Stage/Gate 审批 API

**说明：** 用户可批准、拒绝、修改候选，所有决策必须记录原因。

**验收标准：**
- [ ] `POST /api/v1/research-engine/research-runs/{run_id}/start`
- [ ] `POST /api/v1/research-engine/research-runs/{run_id}/stages/{stage_run_id}/approve`
- [ ] `POST /api/v1/research-engine/research-runs/{run_id}/stages/{stage_run_id}/reject`
- [ ] 审批请求要求 `reason` 或 decision note。
- [ ] 审批后 ResearchRun 可继续推进或标记失败/回滚目标。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_api.py -k gate`

**依赖：** Task 2

**可能触达文件：**
- `backend/app/api/v1/endpoints/research_engine.py`
- `backend/tests/test_research_engine_api.py`

**规模：** M

### Task 4：候选批准后复用 optimization/computation

**说明：** Gate 批准候选后，不新建独立实验系统，复用现有 suggestion submit computation 和 observation 回填能力。

**验收标准：**
- [ ] `RECOMMENDATION_ASK` 输出候选可映射为 existing campaign suggestion 或 candidate refs。
- [ ] 批准候选后可提交受控 computation workflow。
- [ ] computation 完成后仍由现有 observation 路径回填。
- [ ] ResearchStageRun 保存 linked suggestion/computation/observation refs。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_service.py -k optimization_reuse`
- [ ] `pytest backend/tests/test_optimization_service.py`

**依赖：** Task 3、现有 optimization/computation service

**可能触达文件：**
- `backend/app/services/research_engine_orchestrator.py`
- `backend/app/services/optimization_service.py`
- `backend/tests/test_research_engine_service.py`

**规模：** M

### Task 5：暂停、恢复和失败最小语义

**说明：** P0 支持用户暂停和恢复 ResearchRun；失败阶段可记录失败原因。

**验收标准：**
- [ ] running / blocked_approval run 可暂停。
- [ ] paused run 可恢复到暂停前 stage。
- [ ] stage 可标记 failed，必须记录 error 和 reason。
- [ ] checkpoint snapshot 保存最近可恢复状态。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_service.py -k pause_resume`

**依赖：** Task 2-3

**可能触达文件：**
- `backend/app/services/research_engine_orchestrator.py`
- `backend/tests/test_research_engine_service.py`

**规模：** S

## Checkpoint

- [ ] 一个 mock ResearchRun 可从创建、启动、推进到 gate、审批、继续推进。
- [ ] 所有 gate 决策写 audit。
- [ ] 已批准候选不绕开现有 computation/optimization 闭环。

## 风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 编排器一次做太完整 | P0 失控 | 固定 stage + mock output + gate 阻塞优先 |
| AutoResearch 绕开人工 | 产品风险 | 高影响阶段默认 blocked_approval |
| 和现有 suggestion 重复 | 数据割裂 | 候选批准后必须挂到 campaign/suggestion/computation refs |
