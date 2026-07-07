# Plan 06：追溯闭环与验收

## 目标

收尾 P0：补齐 ResearchRun / WorkflowRun / AlgorithmRun / StageRun 的 artifact/audit 聚合查询、任务中心映射、回归测试和浏览器验收，证明完整闭环可演示且不破坏现有模块。

## 范围

- Artifact / Audit 聚合接口。
- ResearchRun / WorkflowRun / AlgorithmRun 详情追溯链。
- P0 手工验收脚本。
- 后端回归测试和前端构建。
- 浏览器验收或 Playwright 冒烟。

## 不做

- 不接对象存储。
- 不做生产级审计报表。
- 不做真实外部系统压力测试。

## 任务列表

### Task 1：artifact/audit 聚合查询

**说明：** 详情页需要一次性拿到与 ResearchRun、WorkflowRun、AlgorithmRun、StageRun 相关的关键追溯信息。

**验收标准：**
- [ ] WorkflowRun 详情返回 step_runs、linked algorithm_runs、artifact refs 和 audit refs。
- [ ] AlgorithmRun 详情返回自有 artifact 和 linked computation artifact refs。
- [ ] ResearchRun 详情返回 stage_runs、linked algorithm_runs、linked computation_runs、linked observations。
- [ ] Audit 查询可按 entity_type/entity_id 聚合关键事件。
- [ ] 返回内容不暴露本地敏感绝对路径或 secret。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_api.py -k traceability`

**依赖：** Plan 03-04

**可能触达文件：**
- `backend/app/services/research_engine_service.py`
- `backend/app/api/v1/endpoints/research_engine.py`
- `backend/tests/test_research_engine_api.py`

**规模：** M

### Task 2：P0 端到端后端测试

**说明：** 用 API 测试覆盖从 ProblemSpec 到 ResearchRun gate 的主路径。

**验收标准：**
- [ ] 创建 ProblemSpec。
- [ ] 创建 `manual_workbench` ExecutionDecision。
- [ ] 创建单节点 ManualAlgorithmWorkflow 并启动 WorkflowRun，节点运行 mock predictor。
- [ ] 创建 `autoresearch` ExecutionDecision。
- [ ] 创建并启动 ResearchRun。
- [ ] 推进到 gate。
- [ ] 审批候选。
- [ ] 关联 computation 或 observation ref。
- [ ] 查询详情能看到 stage timeline、artifact、audit。

**验证：**
- [ ] `pytest backend/tests/test_research_engine_e2e.py`

**依赖：** Plan 02-04

**可能触达文件：**
- `backend/tests/test_research_engine_e2e.py`

**规模：** M

### Task 3：现有模块回归

**说明：** 确认 ResearchEngine 没有破坏现有计算智能和湿实验优化。

**现有测试文件清单（7 个）：**

| 测试文件 | 覆盖内容 | 测试数 |
| --- | --- | --- |
| `backend/tests/test_computation_service.py` | ComputationRun 生命周期、cancel/retry、worker 心跳、stale reaper | 14 |
| `backend/tests/test_optimization_service.py` | Campaign 生命周期、candidate 导入、suggestion/observation、Tanimoto planner | 18 |
| `backend/tests/test_integration_config_service.py` | 集成配置 CRUD、敏感字段拒绝、健康检查 | 8 |
| `backend/tests/test_computation_mvp.py` | 端到端冒烟、artifact/audit 流、数据隔离、campaign 闭环 | 5 |
| `backend/tests/test_local_structure_adapter.py` | RDKit/OpenBabel 结构生成 | — |
| `backend/tests/test_local_xtb_adapter.py` | xTB/CREST adapter 命令构建和结果解析 | — |
| `backend/tests/test_orca_compute_engine_laser_workflow.py` | ORCA workflow adapter | — |

**验收标准：**
- [ ] 上述全部 7 个测试文件通过。
- [ ] 测试运行命令：`python -m pytest backend/tests/ -v`（或 `python -m unittest discover -s backend/tests -p 'test_*.py'`，取决于项目约定）。

**验证：**
- [ ] `pytest backend/tests/test_computation_service.py backend/tests/test_optimization_service.py backend/tests/test_integration_config_service.py backend/tests/test_computation_mvp.py backend/tests/test_local_structure_adapter.py backend/tests/test_local_xtb_adapter.py backend/tests/test_orca_compute_engine_laser_workflow.py`

**依赖：** Plan 01-05

**规模：** S

### Task 4：前端构建和浏览器冒烟

**说明：** 对 P0 页面做真实浏览器或手工验收，避免只通过静态构建。

**验收标准：**
- [ ] `cd frontend && npm run build` 通过。
- [ ] Dashboard、研发引擎、任务提交、湿实验优化、Campaign 详情、Tool Services 可打开。
- [ ] 任务提交页不出现 ResearchEngine 任务卡。
- [ ] ProblemSpec 创建表单、ExecutionDecision 选择区、ManualWorkflow 编排界面、ResearchRun gate dialog 可正常显示。
- [ ] 768px、1024px、1440px 下没有明显文字重叠或关键按钮溢出。

**验证：**
- [ ] Playwright 冒烟或手工记录验收结果。

**依赖：** Plan 05

**可能触达文件：**
- `frontend/src/views/*`
- `frontend/src/views/research-engine/*`

**规模：** M

### Task 5：P0 验收记录

**说明：** 在文档中记录本轮完成状态、剩余 P1/P2 和已知限制，避免后续忘记边界。

**验收标准：**
- [ ] 更新或新增 ResearchEngine progress 文档。
- [ ] 写明已完成、未完成、验证命令、手工验收结果。
- [ ] P1/P2 不作为 P0 半成品遗留在代码中。

**验证：**
- [ ] 文档评审。

**依赖：** Task 1-4

**可能触达文件：**
- `doc/research-engine-progress-and-plan.md`

**规模：** S

## P0 手工验收脚本

1. 创建 ResearchEngine 研发任务，填写氟基高分子 ProblemSpec。
2. 在人工算法工作台选择一个 mock predictor，运行并生成 AlgorithmRun。
3. 基于同一 ProblemSpec 创建 AutoResearch ResearchRun。
4. 启动 ResearchRun，推进到 `RECOMMENDATION_ASK` 或 `HUMAN_REVIEW`。
5. 审批一个候选并提交 computation。
6. computation 完成后生成 Observation。
7. 在 ResearchRun 详情查看 stage timeline、artifact、audit 和 observation 关联。
8. 在任务中心能看到 ResearchRun / AlgorithmRun。
9. 暂停、恢复、失败重跑至少一条路径可用。
10. 现有 campaign candidate / suggestion / observation 页面仍可正常使用。

## Checkpoint

- [ ] 后端 ResearchEngine e2e 测试通过。
- [ ] 现有 computation / optimization / integration 回归测试通过。
- [ ] 前端构建通过。
- [ ] 手工验收脚本完成并记录。

## 风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 追溯链跨多个对象 | 详情页数据不全 | 后端提供聚合接口，前端避免自己拼复杂关系 |
| 回归测试耗时 | 收尾阶段容易跳过 | 把回归测试列为 P0 验收硬条件 |
| 手工验收无记录 | 后续无法判断基线 | 新增 progress 文档记录命令、截图路径或验收结论 |
