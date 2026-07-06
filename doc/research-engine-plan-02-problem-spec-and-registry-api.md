# Plan 02：ProblemSpec 与 AlgorithmRegistry API

## 目标

在后端暴露 P0 API，使前端和后续服务能创建材料研发任务、查看 ProblemSpec、读取算法能力清单。该阶段仍不实现人工算法运行和 AutoResearch 推进。

## 范围

- ProblemSpec 创建、更新草稿、校验、冻结、详情和列表。
- AlgorithmRegistry 只读清单、详情和健康摘要。
- 默认算法能力清单 seed，包含 mock/preset 算法，覆盖文献、结构、预测、推荐、计算几类。
- API 路由接入 `/api/v1`。

## 不做

- 不实现 AlgorithmRegistry 管理后台。
- 不实现 schema 驱动前端表单。
- 不执行真实算法。

## 任务列表

### Task 1：ProblemSpec service

**说明：** 实现 ProblemSpec 的业务服务，包括草稿、冻结和校验逻辑。

**验收标准：**
- [ ] 用户可以创建 ProblemSpec 草稿。
- [ ] 草稿可以更新；冻结后默认不可直接修改，只能复制新版本。
- [ ] 非法变量边界、目标方向、execution_mode 返回结构化错误。
- [ ] 创建时可选择关联已有 campaign 或创建一个首版 campaign 容器。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_service.py -k problem_spec`

**依赖：** Plan 01

**可能触达文件：**
- `backend/app/services/research_engine_service.py`
- `backend/tests/test_research_engine_service.py`

**规模：** M

### Task 2：ProblemSpec API

**说明：** 暴露 ProblemSpec 的 REST API。

**验收标准：**
- [ ] `POST /api/v1/research-engine/problem-specs`
- [ ] `GET /api/v1/research-engine/problem-specs`
- [ ] `GET /api/v1/research-engine/problem-specs/{id}`
- [ ] `PATCH /api/v1/research-engine/problem-specs/{id}`
- [ ] `POST /api/v1/research-engine/problem-specs/{id}/freeze`
- [ ] API 使用现有认证和错误格式。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_api.py -k problem_spec`

**依赖：** Task 1

**可能触达文件：**
- `backend/app/api/v1/endpoints/research_engine.py`
- `backend/app/api/v1/router.py`
- `backend/tests/test_research_engine_api.py`

**规模：** M

### Task 3：AlgorithmRegistry 默认清单

**说明：** 提供 P0 只读算法能力清单，先用本地默认数据驱动 UI 和后续 manual run。默认清单包含 8 个算法条目：5 个 mock/preset 算法（用于演示人工通道闭环）+ 3 个已有计算 workflow 适配器（复用现有 computation 模块）。

**验收标准：**

**Mock 算法（5 个）：**
- [ ] `literature_mock`：文献检索 mock，返回 knowledge_cards
- [ ] `polymer_descriptor_mock`：聚合物描述符生成 mock，返回 descriptors（MW、logP、TPSA、rotatable_bonds 等）
- [ ] `property_predictor_mock`：性质预测 mock，返回预测值和 uncertainty
- [ ] `mobo_mock`：BO/MOBO 推荐 mock，返回 Top-K candidate suggestions
- [ ] `computation_submit_adapter`：计算任务提交适配器，委托给现有 `ComputationService.create_run()`

**计算 Workflow 适配器（3 个）：**
- [ ] `local_structure_adapter`：映射 `LOCAL_STRUCTURE` workflow，type=simulator，material_scope=universal
- [ ] `local_xtb_adapter`：映射 `LOCAL_XTB` workflow，type=simulator，input_schema 包含 smiles/charge/multiplicity/method/solvent
- [ ] `orca_compute_engine_laser_adapter`：映射 `ORCA_COMPUTE_ENGINE_LASER` workflow，type=simulator，仅 ORCA 可用时 status=已接入，否则 status=待封装

**通用要求：**
- [ ] 每个算法包含用户可读名称、类型、材料范围、适用阶段、trigger_modes、status、schema 摘要
- [ ] 算法 ID 稳定，后续 audit 和 AlgorithmRun 可引用
- [ ] 计算 adapter 的 input_schema 和 output_schema 与 `doc/research-engine-and-auto-research-design.md` §17.2 保持一致

**验证：**
- [ ] `pytest backend/tests/test_research_engine_service.py -k registry`

**依赖：** Plan 01

**可能触达文件：**
- `backend/app/services/research_engine_defaults.py`
- `backend/app/services/research_engine_service.py`
- `backend/tests/test_research_engine_service.py`

**规模：** M（8 个算法条目，其中 5 个 mock 需定义输出结构，3 个 adapter 需映射现有 schema）

### Task 4：AlgorithmRegistry API

**说明：** 暴露只读 API，供 Tool Services 或 ResearchEngine 页面展示算法能力。

**验收标准：**
- [ ] `GET /api/v1/research-engine/algorithms`
- [ ] `GET /api/v1/research-engine/algorithms/{algorithm_id}`
- [ ] 支持按 `type`、`material_scope`、`trigger_mode`、`status` 过滤。
- [ ] 响应字段足够前端渲染算法卡和 schema drawer。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_api.py -k algorithm_registry`

**依赖：** Task 3

**可能触达文件：**
- `backend/app/api/v1/endpoints/research_engine.py`
- `backend/tests/test_research_engine_api.py`

**规模：** S

## Checkpoint

- [ ] ProblemSpec API 和 AlgorithmRegistry API 均可被测试客户端调用。
- [ ] 默认算法清单可稳定返回。
- [ ] 现有 `/api/v1` 路由不受影响。

## 风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 过早做 Registry 管理 | 分散 P0 重点 | P0 只读，管理能力放 P1 |
| ProblemSpec 和 campaign 创建边界不清 | 数据重复 | API 明确 `campaign_id` 可选，自动创建只做容器 |
| schema 错误信息不可读 | 前端难展示 | 返回字段路径和原因，不只返回字符串 |
