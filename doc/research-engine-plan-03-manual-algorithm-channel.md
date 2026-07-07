# Plan 03：人工算法 Workflow 通道

## 目标

实现用户从 AlgorithmRegistry 选择算法节点并编排 ManualAlgorithmWorkflow 的 P0 通道。人工模式不能直接点击算法生成孤立 AlgorithmRun；即使只运行一个算法，也必须先形成单节点 WorkflowRun，再由节点产生 AlgorithmRun、输入快照、输出摘要、artifact/audit，并能关联 ProblemSpec / campaign / candidate。

## 范围

- ManualAlgorithmWorkflow 创建、校验、列表、详情。
- WorkflowRun 创建、启动、列表、详情。
- WorkflowStepRun 与 AlgorithmRun 创建、列表、详情。
- mock/preset 算法执行器。
- 与现有 computation/artifact 的最小复用。
- 人工 Workflow 产物可被后续 ResearchRun 引用。

## 不做

- 不允许前端传任意 shell、本地路径或 job script。
- 不接真实外部算法平台。
- 不做复杂异步队列；P0 可同步完成 mock 算法，计算任务仍复用现有 computation worker。

## 任务列表

### Task 1：ManualAlgorithmWorkflow service

**说明：** 实现人工 Workflow 定义创建、节点输入绑定和启动前校验。P0 可只支持线性 steps，但 schema 要保留 `depends_on` 便于后续扩展 DAG。

**验收标准：**
- [ ] 创建 ManualAlgorithmWorkflow 时必须关联 `problem_spec_id` 和 `execution_decision_id`，且 decision mode 必须为 `manual_workbench`。
- [ ] 每个 step 必须引用存在且支持 `human_workflow` trigger 的 algorithm_id。
- [ ] 每个 step 的 input_bindings 必须能解析到 ProblemSpec、手工输入、Candidate、Observation、上游 step output 或上传文件。
- [ ] P0 支持单节点 Workflow 和线性多节点 Workflow。
- [ ] 校验失败返回结构化错误，指出 step_id、字段路径和原因。
- [ ] Workflow 创建、修改、校验通过/失败都写 AuditEvent。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_service.py -k manual_workflow`

**依赖：** Plan 01-02

**可能触达文件：**
- `backend/app/services/research_engine_service.py`
- `backend/app/services/research_engine_algorithm_runner.py`
- `backend/tests/test_research_engine_service.py`

**规模：** M

### Task 2：WorkflowRun / AlgorithmRun service

**说明：** 启动 ManualAlgorithmWorkflow 时创建 WorkflowRun。WorkflowRun 按 step 顺序执行，每个 step 创建 WorkflowStepRun 和 AlgorithmRun。AlgorithmRun 是节点的原子算法调用记录，不能替代 WorkflowRun。

**验收标准：**
- [ ] 启动 Workflow 前冻结 `input_snapshot`、algorithm version、runtime_dependency 和 seed。
- [ ] WorkflowRun 保存 `workflow_id`、`problem_spec_id`、`execution_decision_id`、`status`、`step_runs`、`artifact_refs`。
- [ ] 每个 step 运行时创建 WorkflowStepRun，并创建 `trigger_source=human_workflow` 的 AlgorithmRun。
- [ ] AlgorithmRun 保存 `workflow_run_id`、`workflow_step_run_id`、`problem_spec_id`、`campaign_id`、`input_snapshot`。
- [ ] 运行成功写 `completed` 和输出摘要；失败写 `failed`、error、可重试标记，并让 WorkflowRun 进入 failed 或 partial failed。
- [ ] 每次 WorkflowRun / WorkflowStepRun / AlgorithmRun 创建、完成、失败都写 AuditEvent。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_service.py -k workflow_run`
- [ ] `pytest backend/tests/test_research_engine_service.py -k algorithm_run`

**依赖：** Task 1

**可能触达文件：**
- `backend/app/services/research_engine_service.py`
- `backend/app/services/research_engine_algorithm_runner.py`
- `backend/tests/test_research_engine_service.py`

**规模：** M

### Task 3：实现 P0 mock 算法执行器

**说明：** 为默认算法清单提供可演示的 mock 执行结果，保证人工 Workflow 能闭环。所有 mock runner 共享 `BaseMockRunner` 基类，通过 `algorithm_id` 路由到对应实现。每个 mock 返回确定性输出（可用于测试断言），但输出内容应足够真实以支持演示。

**共享模式：`BaseMockRunner`**

```python
# backend/app/services/research_engine_algorithm_runner.py

class BaseMockRunner:
    """Mock 算法执行器基类。"""
    algorithm_id: str  # 子类设置

    def validate_input(self, input_snapshot: dict) -> None:
        """按 AlgorithmRegistryEntry.input_schema 校验输入。"""
        ...

    def run(self, input_snapshot: dict) -> dict:
        """执行 mock 逻辑，返回 output_summary。"""
        raise NotImplementedError

    def get_artifact_specs(self, output_summary: dict) -> list[dict]:
        """从 output_summary 生成 artifact 规格。"""
        return []
```

**各 mock runner 的输出 schema：**

| algorithm_id | 输出类型 | 核心字段 |
| --- | --- | --- |
| `literature_mock` | knowledge_cards | `papers: list[{title, authors, year, abstract, relevance_score}]` |
| `polymer_descriptor_mock` | descriptors | `mw: float, logp: float, tpsa: float, num_rotatable_bonds: int, num_h_acceptors: int, num_h_donors: int, fingerprint_bits: list[int]` |
| `property_predictor_mock` | prediction | `predictions: dict[str, float]`（property_name → value）、`uncertainty: dict[str, float]` |
| `mobo_mock` | suggestions | `candidates: list[{rank, smiles, predicted_values: dict, reason: str}]`（Top-K） |
| `computation_submit_adapter` | computation_ref | 不直接产出，委托给 ComputationService；返回 `linked_computation_run_id` |

**验收标准：**
- [ ] 所有 5 个 mock runner 继承 `BaseMockRunner`，设置 `algorithm_id`。
- [ ] 输入校验与 `AlgorithmRegistryEntry.input_schema` 一致（必填字段、类型、边界）。
- [ ] `literature_mock` 返回 ≥ 3 条 knowledge cards。
- [ ] `polymer_descriptor_mock` 返回 ≥ 6 个描述符字段。
- [ ] `property_predictor_mock` 返回预测值 + uncertainty。
- [ ] `mobo_mock` 返回 Top-5 candidate suggestions，含推荐理由。
- [ ] `computation_submit_adapter` 委托给现有 ComputationService，不重新实现计算系统。
- [ ] 每个 runner 输出统一保存为 output_summary，并可生成 JSON artifact。
- [ ] 所有 mock runner 的输入/输出是确定性的（相同输入 → 相同输出），可被测试断言。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_service.py -k mock_algorithm`

**依赖：** Task 2

**新建文件：**
- `backend/app/services/research_engine_algorithm_runner.py`

**规模：** M

### Task 4：ManualWorkflow / WorkflowRun / AlgorithmRun API

**说明：** 暴露人工 Workflow 编排、启动和查看运行记录的 API。P0 不提供绕过 Workflow 的“直接运行算法”API。

**验收标准：**
- [ ] `POST /api/v1/research-engine/manual-workflows`
- [ ] `GET /api/v1/research-engine/manual-workflows`
- [ ] `GET /api/v1/research-engine/manual-workflows/{workflow_id}`
- [ ] `POST /api/v1/research-engine/manual-workflows/{workflow_id}/runs`
- [ ] `GET /api/v1/research-engine/workflow-runs`
- [ ] `GET /api/v1/research-engine/workflow-runs/{workflow_run_id}`
- [ ] `GET /api/v1/research-engine/algorithm-runs`
- [ ] `GET /api/v1/research-engine/algorithm-runs/{run_id}`
- [ ] 列表支持按 problem_spec、campaign、workflow、algorithm、status 过滤。
- [ ] 详情返回 input snapshot、output summary、artifact refs、audit refs。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_api.py -k manual_workflow`
- [ ] `pytest backend/tests/test_research_engine_api.py -k workflow_run`
- [ ] `pytest backend/tests/test_research_engine_api.py -k algorithm_run`

**依赖：** Task 1-3

**可能触达文件：**
- `backend/app/api/v1/endpoints/research_engine.py`
- `backend/tests/test_research_engine_api.py`

**规模：** M

### Task 5：复用 computation 提交路径

**说明：** 对 `computation_submit_adapter` 这类算法能力，不重新实现计算系统，而是创建现有 computation run 并把 ref 写回 AlgorithmRun。

**验收标准：**
- [ ] 人工 Workflow 节点可基于输入创建 `MOCK_XTB_ONLY` 或已有受控 workflow 的 computation run。
- [ ] AlgorithmRun 保存 `linked_computation_run_id`。
- [ ] artifact 详情可通过现有 computation artifact API 追溯。
- [ ] 不破坏现有 computation submit 和 worker 测试。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_service.py -k computation_adapter`
- [ ] `pytest backend/tests/test_computation_service.py`

**依赖：** Task 2、现有 computation service

**可能触达文件：**
- `backend/app/services/research_engine_algorithm_runner.py`
- `backend/app/services/computation_service.py`
- `backend/tests/test_research_engine_service.py`

**规模：** M

## Checkpoint

- [ ] 用户可通过 API 创建单节点或多节点 ManualAlgorithmWorkflow 并启动 WorkflowRun。
- [ ] WorkflowRun 和 AlgorithmRun 有完整状态、输入、输出、artifact/audit 引用。
- [ ] 运行产物可以通过 problem_spec_id 或 campaign_id 查询。

## 风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 人工工作台退化成算法按钮集合 | 产物不可复用、不可回放 | 所有人工运行必须从 ManualAlgorithmWorkflow 启动，单算法也生成单节点 WorkflowRun |
| mock runner 后续难替换 | 形成临时耦合 | runner 只消费 Registry schema 和白名单 algorithm_id |
| 计算任务路径重复实现 | 维护成本高 | computation 类能力必须调用现有 computation service |
| artifact 归属不清 | 详情页无法追溯 | AlgorithmRun 保存自有 artifact refs 和 linked computation refs |
