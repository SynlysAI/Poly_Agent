# ResearchEngine 分阶段实施计划索引

版本：v0.1  
日期：2026-07-06  
来源设计：`doc/research-engine-and-auto-research-design.md`

本文把完整 ResearchEngine 设计拆成多个可独立执行、可验收的计划文件。后续不要一次性做完整平台，而是按下列顺序逐个完成、测试和评审。

## 拆分原则

- 每个计划只解决一个清晰的能力层，不混入下一阶段半成品。
- 优先复用现有 `optimization`、`computation`、`artifact`、`audit`、Vue 工作台，不重复建设孤岛闭环。
- 每个阶段结束时系统都应保持可运行、现有计算智能和湿实验优化流程不被破坏。
- P0 先证明任务先行闭环：ProblemSpec 校验后必须创建 ExecutionDecision，进入人工 ManualAlgorithmWorkflow / WorkflowRun 或 AutoResearch ResearchRun，并共享同一套 AlgorithmRun、Observation、AuditEvent。

## 推荐执行顺序

| 顺序 | 计划文件 | 目标 | 依赖 | 建议状态 | 预估工作量 |
| --- | --- | --- | --- | --- | --- |
| 1 | `doc/research-engine-plan-01-domain-foundation.md` | 建立 ProblemSpec、ExecutionDecision、ManualAlgorithmWorkflow、WorkflowRun、AlgorithmRun、ResearchRun 等后端领域模型和持久化底座 | 无 | P0 必做 | 3-5 天 |
| 2 | `doc/research-engine-plan-02-problem-spec-and-registry-api.md` | 暴露 ProblemSpec 和 AlgorithmRegistry API，并提供默认算法能力清单 | 计划 1 | P0 必做 | 2-3 天 |
| 3 | `doc/research-engine-plan-03-manual-algorithm-channel.md` | 跑通人工算法 Workflow 通道，生成 WorkflowRun、AlgorithmRun、artifact、audit，并可关联 campaign | 计划 1-2 | P0 必做 | 3-4 天 |
| 4 | `doc/research-engine-plan-04-autoresearch-orchestrator.md` | 实现材料版 ResearchRun、Stage/Gate、固定阶段推进和候选审批 | 计划 1-3 | P0 必做 | 4-5 天 |
| 5 | `doc/research-engine-plan-05-frontend-mvp.md` | 在现有 Vue 工作台加入 ResearchEngine 入口、ProblemSpec、算法清单、Stage/Gate 看板 | 计划 2-4 | P0 必做 | 3-5 天 |
| 6 | `doc/research-engine-plan-06-traceability-and-qa.md` | 补齐 artifact/audit 聚合、任务中心映射、测试和浏览器验收 | 计划 3-5 | P0 收尾 | 2-3 天 |

**P0 总预估**：17-25 人天（约 3.5-5 周，单人全职）。

**建议里程碑**：
- Week 1-2：计划 1-2 完成 → Checkpoint A
- Week 3-4：计划 3-4 完成 → Checkpoint B
- Week 5：计划 5-6 完成 → Checkpoint C

## 全局 P0 约束（适用于所有计划 01-06）

以下约束在所有计划中通用，后续计划不再重复声明：

- 所有状态变更必须写 AuditEvent（复用 `AuditEventRepository.append()`），记录 `actor`、`entity_type`、`entity_id`、`event_type`、`reason`、`before`、`after`。
- 所有 Pydantic schema 使用 `ConfigDict(extra="forbid")` 和 `field_validator`，中文错误消息。
- 所有 API 路由沿用 `/api/v1` 前缀、Pydantic schema、service/repository 分层和现有 `ApiResponse` 格式。
- 所有 Repository 类继承 `BaseRepository`（`computation_repositories.py`），支持 MongoDB + demo-store 双模。
- 不 vendor `refer/AutoResearchClaw-main` 或其他同类项目整仓代码，只抽象迁移状态机、契约、HITL、artifact、profile、planner/dataset 和 memory 思想。
- 不引入新 UI 框架、状态管理库或独立视觉体系。
- 所有新增对象预留 `created_by`、`owner_id`、`project_id` 字段，为后续 RBAC 做准备。

## P0 总体验收

- [ ] 用户可创建氟基高分子 ProblemSpec，并关联或创建现有 campaign。
- [ ] 用户可创建 `manual_workbench` ExecutionDecision，从算法清单编排单节点或多节点 ManualAlgorithmWorkflow，形成 WorkflowRun、AlgorithmRun、输入快照、输出摘要、artifact/audit。
- [ ] 用户可创建 `autoresearch` ExecutionDecision，并基于同一个 ProblemSpec 启动 ResearchRun。
- [ ] 用户可基于同一个 ProblemSpec 创建 ResearchRun，并启动固定阶段推进。
- [ ] ResearchRun 至少能推进到 `RECOMMENDATION_ASK` 或 `HUMAN_REVIEW` gate。
- [ ] 用户可批准或拒绝候选；批准路径复用现有 suggestion/computation/observation 能力。
- [ ] ResearchRun / WorkflowRun / AlgorithmRun / StageRun 详情可查看关键输入、输出、artifact 和 audit。
- [ ] 现有 computation、optimization、integration config 测试不回退。
- [ ] 前端构建通过，任务提交、湿实验优化、Campaign 详情、Tool Services 中的 ResearchEngine 入口可用。

## 不进入 P0 的内容

- 不直接 vendor `refer/AutoResearchClaw-main` 整仓代码。
- 不实现真实 LabOS / SpecLabOS 设备提交，只保留 mock/manual/computation 路径。
- 不做复杂 RBAC，但新增对象必须预留 `created_by`、`owner_id`、`project_id`、`actor_role` 和 audit 字段。
- 不新增大型状态管理、UI 框架或独立视觉体系。
- 不实现完整模型训练平台，只记录 ModelUpdate / lesson 的未来扩展边界。

## 阶段检查点

### Checkpoint A：计划 1-2 后

- [ ] 后端 schema、repository、基础 API 可创建和查询 ProblemSpec / AlgorithmRegistry。
- [ ] 默认算法清单能被 API 返回。
- [ ] `pytest backend/tests/test_research_engine_schemas.py backend/tests/test_research_engine_api.py` 通过。

### Checkpoint B：计划 3-4 后

- [ ] 人工 WorkflowRun / AlgorithmRun 和 AutoResearch ResearchRun 都能写入同一套 repository。
- [ ] Stage/Gate 状态机能推进、阻塞审批、记录决策原因。
- [ ] `pytest backend/tests/test_research_engine_service.py backend/tests/test_optimization_service.py backend/tests/test_computation_service.py` 通过。

### Checkpoint C：计划 5-6 后

- [ ] 前端入口、列表、详情和审批操作可完成手工验收脚本。
- [ ] `cd frontend && npm run build` 通过。
- [ ] P0 手工验收流程完整跑通。

## 后续 P1/P2 候选计划

P0 完成后再拆新计划，不混入当前 6 个文件：

- P1：Schema 驱动算法表单增强和 AlgorithmRegistry 管理。
- P1：ResearchRun pause/resume/checkpoint/rerun 完整恢复语义。
- P1：ModelUpdate、lesson、archive 和策略收益记录。
- P2：多材料 profile 模板和默认 stage algorithm 配置。
- P2：真实 SpecLabOS / AiiDA / ORCA / HPC 外部执行器。
