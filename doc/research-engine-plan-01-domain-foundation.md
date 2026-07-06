# Plan 01：ResearchEngine 后端领域底座

## 目标

建立 ResearchEngine P0 所需的后端领域模型、枚举、Pydantic schema 和 demo/mongo repository 边界。这个阶段只做“可被后续 API 和服务复用的底座”，不实现前端、不跑 AutoResearch 编排。

## 范围

- `ProblemSpec`：材料研发问题规格，首版可映射到 `OptimizationCampaign`。
- `AlgorithmRegistry`：算法能力登记，只读清单和 schema 描述。
- `AlgorithmRun`：人工或自动算法运行记录。
- `ResearchRun` / `ResearchStageRun`：AutoResearch 主运行和阶段运行记录。
- `StageGate` / `StageContract`：阶段门禁、审批策略和 DoD。
- 统一状态枚举、触发来源、执行模式、材料阶段枚举。

## 不做

- 不写 UI。
- 不实现真实算法 adapter 调用。
- 不实现 ResearchRun 自动推进。
- 不改现有 campaign / computation 行为，只预留关联字段和映射。

## 任务列表

### Task 1a：定义 ResearchEngine 核心 schema

**说明：** 在 `backend/app/schemas` 中新增 `research_engine.py`，先覆盖 P0 数据结构、枚举和基础校验。遵循现有 `computation.py`/`optimization.py` 的 Pydantic 模式：`ConfigDict(extra="forbid")`、`field_validator` 装饰器、`Literal` 类型、中文错误消息。

**新建文件：**
- `backend/app/schemas/research_engine.py`

**验收标准：**
- [ ] 定义 `ExecutionMode = Literal["manual", "autoresearch", "hybrid"]`
- [ ] 定义 `TriggerSource = Literal["human", "autoresearch", "system"]`
- [ ] 定义 `ResearchRunStatus = Literal["draft", "running", "paused", "blocked_approval", "completed", "failed", "archived"]`
- [ ] 定义 `ResearchStageStatus = Literal["pending", "running", "blocked_approval", "completed", "failed"]`
- [ ] `ProblemSpecCreate` 支持 `execution_mode`、variables（类型/单位/边界/必填校验）、objectives、constraints
- [ ] `AlgorithmRegistryEntry` 包含 `algorithm_id`、`type`、`material_scope`、`input_schema`、`output_schema`、`trigger_modes`、`status`、`validation_metric`、`runtime_dependency`
- [ ] `AlgorithmRun` 区分 `trigger_source`，保存 `input_snapshot: dict`、`output_summary: dict`、`linked_computation_run_id: str | None`
- [ ] `ResearchRun` 和 `ResearchStageRun` 支持完整状态枚举
- [ ] `StageGate` 包含 `stage_key`、`required_inputs`、`expected_outputs`、`definition_of_done`、`gate_policy`、`retry_policy`、`rollback_target`、`artifact_policy`
- [ ] 所有 `field_validator` 使用中文错误消息（与 `computation.py` 中 `"SMILES 不能为空"` 等保持一致）

**验证：**
- [ ] `pytest backend/tests/test_research_engine_schemas.py`

**依赖：** 无

**规模：** L（5+ Pydantic models + 枚举定义）

### Task 1b：建立领域默认值和阶段常量

**说明：** 固化材料版 AutoResearch 阶段序列和默认 stage contract，供后续 orchestrator 复用。参考现有 `ComputationStep` 模式（step_key、label、status、started_at、finished_at、error）设计 ResearchStageRun。

**新建文件：**
- `backend/app/services/research_engine_defaults.py`

**验收标准：**
- [ ] 默认阶段序列包含 `PROBLEM_SPEC`、`KNOWLEDGE_RETRIEVAL`、`STRUCTURE_FEATURE`、`COMPUTE_PREDICT`、`RECOMMENDATION_ASK`、`HUMAN_REVIEW`、`EXPERIMENT_EXECUTION`、`RESULT_TELL`、`MODEL_UPDATE`、`ARCHIVE_LEARNING`
- [ ] P0 默认 gate 至少覆盖 `PROBLEM_SPEC`、`RECOMMENDATION_ASK`、`EXPERIMENT_EXECUTION` 三个阶段
- [ ] 每个 stage contract 有 required_inputs、expected_outputs、definition_of_done、artifact_policy
- [ ] ResearchRun 状态转移规则明确（见下方状态转移表）

**ResearchRun 状态转移表：**
```
draft → running（启动时）
running → blocked_approval（到达 gate 阶段）
running → paused（用户暂停）
running → completed（所有阶段完成）
running → failed（不可恢复错误）
blocked_approval → running（审批通过）
blocked_approval → failed（审批拒绝且无回滚目标）
blocked_approval → paused（用户暂停）
paused → running（恢复，回到暂停前阶段）
completed → archived（用户操作，可选）
```

**ResearchStageRun 状态转移表：**
```
pending → running（ResearchRun 到达该阶段）
running → completed（阶段逻辑完成）
running → failed（阶段错误）
running → blocked_approval（gate 需要人工审核）
blocked_approval → completed（批准）
blocked_approval → failed（拒绝）
```

**验证：**
- [ ] `pytest backend/tests/test_research_engine_schemas.py -k defaults`

**依赖：** Task 1a

**规模：** S

### Task 2：扩展 repository 持久化层

**说明：** 按现有 `BaseRepository` 模式（`backend/app/infra/computation_repositories.py`）扩展持久化层。该模式实现 Mongo-first + demo JSON 双模存储（通过 `_mongo_unavailable` 标志自动切换）。新增 repository 类可放在 `computation_repositories.py` 中，或新建 `research_engine_repositories.py` 但继承同一个 `BaseRepository`。

**涉及修改的现有文件：**
- `backend/app/infra/demo_store.py`：在 `COLLECTION_NAMES` 列表（第 18-27 行）中追加 4 个集合名
- `backend/app/infra/mongo.py`：新增 4 个 collection accessor 函数
- `backend/app/infra/computation_repositories.py`（或新建 `research_engine_repositories.py`）：新增 4 个 Repository 类

**验收标准：**
- [ ] `demo_store.py` 的 `COLLECTION_NAMES` 扩展为 12 个（新增：`research_problem_specs`、`algorithm_registry_entries`、`algorithm_runs`、`research_runs`）
- [ ] `mongo.py` 新增对应的 `get_*_collection()` 函数
- [ ] 新增 `ResearchProblemSpecRepository`：支持 create/get/list/update/freeze，至少按 `project_id`、`campaign_id`、`created_by` 过滤
- [ ] 新增 `AlgorithmRegistryRepository`：支持只读清单查询，按 `type`、`material_scope`、`trigger_mode`、`status` 过滤
- [ ] 新增 `AlgorithmRunRepository`：支持 create/get/list，按 `problem_spec_id`、`campaign_id`、`algorithm_id`、`status`、`trigger_source` 过滤
- [ ] 新增 `ResearchRunRepository`：支持 create/get/list/update，按 `problem_spec_id`、`campaign_id`、`status` 过滤
- [ ] 每个 Repository 类继承 `BaseRepository`，设置 `collection_name` 类属性
- [ ] 所有返回值不泄露内部可变对象引用（沿用 `clone_document` 防护）

**验证：**
- [ ] `pytest backend/tests/test_research_engine_repository.py`

**依赖：** Task 1a

**规模：** M

### Task 3：建立领域默认值和阶段常量

**说明：** 固化材料版 AutoResearch 阶段序列和默认 stage contract，供后续 orchestrator 复用。

**验收标准：**
- [ ] 默认阶段包含 `PROBLEM_SPEC`、`KNOWLEDGE_RETRIEVAL`、`STRUCTURE_FEATURE`、`COMPUTE_PREDICT`、`RECOMMENDATION_ASK`、`HUMAN_REVIEW`、`EXPERIMENT_EXECUTION`、`RESULT_TELL`、`MODEL_UPDATE`、`ARCHIVE_LEARNING`。
- [ ] P0 默认 gate 至少覆盖 `PROBLEM_SPEC`、`RECOMMENDATION_ASK`、`EXPERIMENT_EXECUTION`。
- [ ] 每个 stage contract 有 required inputs、expected outputs、DoD、artifact policy。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_schemas.py`

**依赖：** Task 1

**可能触达文件：**
- `backend/app/services/research_engine_defaults.py`
- `backend/tests/test_research_engine_schemas.py`

**规模：** S

### Task 4：兼容现有 campaign 映射

**说明：** 在 schema 和 repository 层预留 `campaign_id`、`candidate_id`、`suggestion_id`、`observation_id`、`computation_run_id` 关联字段，避免后续重复造闭环。

**审计模式：** 所有 ResearchEngine 对象的状态变更必须复用现有 `AuditEventRepository`（位于 `computation_repositories.py`），通过 `append()` 方法写入 AuditEvent。审计字段：`actor_user_id`、`entity_type`（如 `"research_run"`、`"algorithm_run"`、`"stage_run"`）、`entity_id`、`event_type`（如 `"created"`、`"started"`、`"approved"`、`"rejected"`、`"failed"`）、`before`、`after`、`metadata`（含 `reason`）。此模式已由 computation 和 optimization 模块验证，后续 Plans 03-06 不再重复描述审计机制，统一引用此说明。

**验收标准：**
- [ ] ProblemSpec 可以关联 `campaign_id`（可选字段）。
- [ ] AlgorithmRun / ResearchStageRun 可以引用 `computation_run_id`、`suggestion_id`、`observation_id`（均为可选）。
- [ ] 字段是可选关联，不破坏现有 optimization 测试。

**验证：**
- [ ] `pytest backend/tests/test_optimization_service.py backend/tests/test_computation_service.py`

**依赖：** Task 1a, Task 2

**规模：** S

## Checkpoint

- [ ] ResearchEngine 新 schema 和 repository 测试通过。
- [ ] 现有 optimization / computation 测试通过。
- [ ] 尚未引入任何前端入口或自动编排逻辑。

## 风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 领域对象和现有 campaign 重叠 | 后续出现两套候选/observation | P0 只把 campaign 作为容器和关联对象，不迁移现有数据 |
| schema 一次设计过大 | 实现成本失控 | P0 只覆盖创建、查询、运行记录、gate 审批必需字段 |
| repository 模式不一致 | 后续 API 难维护 | 参考现有 computation/optimization repository 风格 |
