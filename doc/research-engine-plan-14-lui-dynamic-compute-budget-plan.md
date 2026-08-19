# Plan 14：LUI 动态计算预算与分级路由工作计划

> 状态：待评审 / 未开始
>
> 日期：2026-08-19
>
> 前置文档：
> - [research-engine-plan-10-slash-command-and-agent-control-workplan.md](research-engine-plan-10-slash-command-and-agent-control-workplan.md)
> - [research-engine-plan-11-lui-qa-deep-preset-positioning.md](research-engine-plan-11-lui-qa-deep-preset-positioning.md)
> - [research-engine-plan-13-lui-agent-evaluation-plan.md](research-engine-plan-13-lui-agent-evaluation-plan.md)
>
> 迁移说明：本计划承接原 Plan 11 第 12 节“动态计算预算”与第 13 节 P11-A–P11-E 行动框架；Plan 11 保留 `research_qa` / `research_deep` 的 Preset 定位、契约与 `preset_id` 兼容基础。

## 1. 摘要

PolyAgent LUI 的 `research_qa` / `research_deep` Preset 已在 Plan 11 完成定位与 `preset_id` 兼容基础，但两个模式仍是静态的“模型路由用途 + 检索强度 + 输出策略”开关，不能按问题难度、风险等级和证据需求调节效果、延迟与成本。

本计划在两个 Preset 之上落地“动态计算预算”：

```text
请求与约束 → 难度 / 风险 / 证据需求分类 → 选择模型、检索与执行档位
           → 用户显式选择覆盖默认值 → 安全策略兜底 → Execution Trace 记录
```

核心拆解为四层演进：

| 层 | 演进方向 |
| --- | --- |
| Model Router | 静态 `route_purpose` → 先分类、再路由的 Simple / Complex / High-risk 档位 |
| RAG 检索 | 统一向量检索 → Easy Query Vector、Hard Query Hybrid + Reranker |
| Agent 执行 | 一律同构执行 → Low-risk One-shot、Medium Planning、High-risk Verification + Human |
| 发布与调优 | 直接生效 → 影子观测、灰度启用、指标门槛与回滚 |

## 2. 目标与非目标

### 2.1 目标

- 定义 `AssistantPreset` 的 `classification_policy`、`budget_policy` 与 `execution_policy` 存储契约，并保持 `mode` / `preset_id` 兼容迁移。
- 实现确定性 Query Classifier 与保守 Model Router MVP，用户显式选择与系统安全策略始终优先。
- 实现 RAG 检索分层：Easy Query 默认 Vector Search，Hard Query 按触发条件升级 Hybrid Search + Reranker。
- 实现 Agent 执行分级与安全兜底：Low-risk One-shot、Medium Planning、High-risk Planning + Verification + Human。
- 建立“影子观测 → 灰度启用 → 默认档位调优”的发布闭环，并依赖 Plan 13 的八项指标作为门槛。
- 所有预算决策进入 Execution Trace，保证效果、延迟与成本可回放、可审计。

### 2.2 非目标

- 不重写 `research_qa` / `research_deep` 为独立 Agent，仍共享 Base Agent / AssistantService。
- 不引入 Cordis、DSH 插件系统或 TypeScript runtime。
- 不实现完整 Preset Registry、Preset 编辑器或 Preset 市场。
- 不默认引入昂贵的分类模型调用；Query Classifier 初期只用确定性规则和既有会话状态。
- 不以“成本优化”为由降低安全底线；高风险任务必须保留验证、审批与 Human 节点。
- 不把预算策略做成可覆盖用户显式模型、工具或权限选择的强制策略。

## 3. 当前基线

截至 2026-08-19：

| 维度 | 当前实现 | 差距 |
| --- | --- | --- |
| Preset 基础 | `assistant_presets.py` 提供 `research_qa` / `research_deep` 标识、`mode` 双向映射与静态 `route_purpose`；会话与 run 已记录 `preset_id` | 无结构化 Preset Registry、策略对象与预算契约 |
| 查询分类 | `AssistantIntent` 基于项目 / 模型 / 联网关键词给出 scope 与 deep 信号 | 无 Simple / Complex / High-risk 分类、置信度与风险分级 |
| 模型路由 | `route_purpose` 按 `qa` / `deep` 静态路由，前端按 Preset 排序默认模型 | 无按分类结果的档位选择、升级提示与降档保护 |
| 知识库检索 | WeKnora 向量检索 + score 排序，`qa` / `deep` 共用同一套证据注入 | 无 Hybrid Search（关键字 + 向量）、Reranker 与升级触发条件 |
| 执行分级 | 所有请求走同一 Assistant 执行链路；Plan 10 已有 Plan Mode、Permission Mode、Goal / Todo 与审批状态 | 未按风险接入 One-shot / Planning / Verification + Human 分级 |
| 观测与灰度 | Plan 09 Trace 与 Plan 10 质量指标已覆盖 run / command / tool / trace | 无预算决策事件、影子模式、灰度开关与回滚机制 |
| 评估依赖 | Plan 13 八项指标体系待评审 / 未开始 | Golden Set、Recall@K、幻觉率、成本对比是本计划验收硬依赖 |

## 4. 目标架构：动态计算预算

Preset 定位不能只追求“效果优先”。面向科研用户的商业系统需要同时管理三个互相制约的目标：

```text
Accuracy   效果与证据质量
Latency    交互延迟
Cost       模型、检索与执行成本
```

统一原则是“动态计算预算”：对每次请求按问题难度、风险等级和当前约束，动态决定模型、检索与 Agent 执行预算，而不是把所有请求固定到最强模型或固定开启最高强度检索。

其中“分类”不是新增一个 opaque 黑盒。初期应使用可解释的规则信号，例如是否只要入口事实、是否需要多来源比较、是否涉及算法执行或审批、是否要求进入正式报告、用户是否要求可解释结论，以及上一轮证据是否冲突。分类结果、置信度、回退原因和最终档位都必须可审计。

### 4.1 Model Router

模型选择从静态 `route_purpose` 进一步演进为“先分类、再路由”：

```text
Simple Query      → Small Model
Complex Reasoning → Large Model
High-risk Task    → Large Model + Verification
```

映射到两个 Preset：

- `research_qa` 的 `model_preference` 对应 Simple Query，优先 `fast` / 小模型，换取低延迟和低成本。
- `research_deep` 的 `model_preference` 对应 Complex Reasoning，优先 `reasoning` / `long_context` 大模型，换取更高证据质量。
- `research_qa` 遇到 Complex Reasoning 信号时不应强行用小模型回答，应提示切换 `research_deep` 或直接使用更高档默认模型；`research_deep` 中的简单子查询可以在不影响证据质量和风险控制时使用更轻模型。
- 高风险任务不单靠模型输出，而是“大模型 + 验证 / 审批 / 来源标注”，避免把高风险决策压缩成一次低成本回答。

### 4.2 RAG 检索分层

检索也按查询难度分级：

```text
Easy Query → Vector Search
Hard Query → Hybrid Search + Reranker
```

- `research_qa` 优先项目事实与知识库向量检索，快速回答入口、能力和简单事实。
- `research_deep` 在需要证据综合或多来源比对时，升级为混合检索（关键字 + 向量）+ Reranker，并按现有策略增加联网结果和证据数量。
- 是否升级由问题复杂度、证据一致性、来源数量、用户是否要求可解释结论和当前延迟 / 成本约束决定，避免所有请求都付出最高检索成本。
- 检索升级必须保留来源、排序、得分和使用位置；不能因为引入 Reranker 而丢失项目事实优先、知识库证据优先与来源标注规则。

### 4.3 Agent 执行分级

按任务风险和自主程度分级，而不是一律多步规划：

```text
Low-risk  → One-shot
Medium    → Planning
High-risk → Planning + Verification + Human
```

- `research_qa` 的导航与事实查询多数走 One-shot，减少等待与来回。
- `research_deep` 对需要多步判断的问题走 Planning，并以高层 `reasoning_summary` 呈现步骤与依据。
- 涉及算法执行、审批、不可逆操作或结果进入正式报告的高风险任务，必须保留 Human / 审批 / 验证节点；Preset 不能绕过 RBAC、AgentTool policy 和来源标注。
- Medium 任务可以规划但不自动扩大权限；Planning 的价值是拆解证据和检查步骤，不是默认多调用工具。

### 4.4 落地边界

实现 Preset Registry 或路由增强时，可在 `AssistantPreset` / 路由层引入预算策略，但受以下约束：

- 预算策略只提供“默认选择”，用户显式选择模型、工具或权限时优先。
- 预算分级不改变系统安全策略，高风险必须保留验证 / 审批 / Human。
- 模型路由、检索升级与 Agent 分级都要记录进 Execution Trace，保证成本、延迟和效果可回放、可审计。
- 分类不确定、指标冲突或预算系统异常时，回退到当前 `qa` / `deep` 静态路由和既有安全策略，不得让请求失败或绕过审批。
- 预算优化不得只以成本或延迟为单一目标；每次默认档位调整都需要用 Plan 13 的任务成功、准确率、幻觉、延迟和成本指标对比。
- 必须先观测、再保守启用、最后灰度扩展；没有指标对比和回滚能力时，不得把预算策略作为默认行为。

## 5. 假设与默认选择

- Query Classifier 初期优先使用确定性规则和既有上下文信号，不默认引入一个昂贵的分类模型；分类不确定时向更高证据质量或更高安全档位回退。
- 预算策略只决定默认值；用户显式选择、系统安全策略、RBAC、AgentTool policy 和审批状态始终优先。
- `deep` 的高层 `reasoning_summary` 仍只展示可审计的高层推理，不展示 hidden CoT 或私有 scratchpad。
- 算法工具调用不因预算档位自动打开，仍需用户选择工具且模型支持 `tool_calling`。
- 预算策略不能覆盖平台 RBAC、AgentTool policy、审批和系统安全规则。
- Plan 13 的 Golden Set 与八项指标是默认档位调优和发布门槛的评估基础；Plan 13 未完成 Phase 0–3 前，不启用任何改变线上默认行为的预算档位。

## 6. 分阶段行动计划

> 本节是后续独立代码计划的行动框架，当前全部未开始。每完成一项，必须同步更新复选框与状态记录；实施前应先回填当时的代码基线和依赖提交。

### P14-A. 预算契约与观测设计

- [ ] 定义 `AssistantPreset.classification_policy`、`budget_policy` 与 `execution_policy` 的 Pydantic / 存储契约，并保持 `mode` / `preset_id` 兼容迁移。
- [ ] 定义最小分类输入：`query_complexity`、`risk_level`、`evidence_need`、`explainability_required`、`user_constraint` 和 `prior_evidence_conflict`，明确每项的取值、来源与缺省回退。
- [ ] 设计预算档位矩阵：
  - [ ] Model：Simple / Complex / High-risk。
  - [ ] Retrieval：Vector / Hybrid + Reranker / Hybrid + Reranker + Web Evidence。
  - [ ] Execution：One-shot / Planning / Planning + Verification + Human。
- [ ] 定义预算 Trace 契约，至少记录分类输入摘要、分类结果与置信度、最终档位、用户覆盖、回退原因、实际模型 route、检索方式与升级原因、执行档位、验证 / 审批节点、耗时和 token / 检索成本。
- [ ] 与 Plan 13 对齐 Golden Set 与指标口径，覆盖简单问答、复杂推理、高风险工具执行、证据冲突和用户显式覆盖五类样本。
- [ ] 明确隐私与冗余控制：Trace 记录预算决策所需摘要，不因预算事件重复保存大段用户输入或私有 scratchpad。

### P14-B. 保守 Model Router MVP

- [ ] 实现确定性 Query Classifier，先只使用规则和既有会话状态，不默认新增分类模型调用。
- [ ] 将 `route_purpose` 保留为兜底，按分类结果在 Preset 允许的模型候选池内选择 Simple / Complex / High-risk 默认档位。
- [ ] 接入 Plan 10 `/model` 控制状态：用户显式选择模型时记录 `user_override=model` 并直接使用该模型。
- [ ] 实现 `research_qa → research_deep` 或高档模型的升级提示，避免复杂问题被小模型压缩成低质量回答。
- [ ] 允许 `research_deep` 的简单子查询降档，但必须设置证据质量、风险和可解释性保护条件；高风险任务禁止降档绕过验证。
- [ ] 补充测试：默认路由、显式模型覆盖、复杂问题升级、分类不确定回退、高风险不降档、Trace 字段完整。

### P14-C. RAG 分层与证据质量

- [ ] 保持项目事实与用户选择的知识库为第一证据来源，Easy Query 默认 Vector Search。
- [ ] 实现 Hybrid Search + Reranker 的升级触发条件：多来源比较、证据冲突、复杂综合、用户要求可解释结论或首次检索不足以支撑结论。
- [ ] 联网检索继续作为项目外与补充证据来源，按 Preset 策略控制结果数、抓取页数和引用数量。
- [ ] Trace 中记录候选来源、排序 / rerank 得分、被答案使用的证据、升级原因和未升级原因。
- [ ] 用 Plan 13 的 Recall@K、准确率、幻觉率、P50 / P95 延迟和检索成本对比 Vector 与 Hybrid 档位，确定默认阈值。
- [ ] 补充回归：无知识库、空检索、证据冲突、Reranker 不可用、来源缺失和项目事实优先。

### P14-D. Agent 执行分级与安全兜底

- [ ] 将低风险事实 / 导航请求接入 One-shot 路径，减少不必要的规划轮次和模型调用。
- [ ] 将 Medium 任务接入 Plan 10 Plan Mode 与 Todo / Goal 状态，执行前明确步骤、证据需求和停止条件。
- [ ] 将 High-risk 任务映射到 Planning + Verification + Human，覆盖算法执行、审批、不可逆操作和进入正式报告的结果。
- [ ] 保持 RBAC、AgentTool policy、Permission Mode、确认状态机、审批和来源标注优先于预算策略。
- [ ] 高风险输出必须展示验证结果、审批状态、来源和不确定性；不得以“成本优化”为由省略。
- [ ] 补充安全测试：Plan Mode 阻断、read-only 阻断、审批缺失阻断、full access 不越权、预算异常时回退静态安全路径。

### P14-E. 灰度发布、评估与调优

- [ ] 建立预算决策质量看板：分类分布、档位分布、用户覆盖率、回退率、任务成功率、准确率、幻觉率、P50 / P95 延迟和成本。
- [ ] 先在影子模式记录“预算建议 vs 当前实际行为”，不改变线上默认行为。
- [ ] 通过离线评估后，按用户组 / Preset / 查询类型灰度启用保守默认档位。
- [ ] 设定发布门槛与回滚条件：效果和安全事故一票否决，延迟或成本收益不得以明显准确率下降为代价。
- [ ] 根据评估结果调优分类阈值和档位映射，所有默认档位变更保留实验记录和回放样本。
- [ ] 更新 `/dialogue` 用户指南，解释自动预算、用户覆盖、延迟 / 成本预期与高风险审批，不夸大为无限制自主 Agent。

## 7. 验收标准

- [ ] 文档定义动态计算预算原则，并能把 Simple / Complex / High-risk 查询映射到两个 Preset 的模型、检索与执行策略。
- [ ] 文档说明预算默认值、用户显式选择与系统安全策略的优先级，特别是高风险任务不可因降本绕过验证 / 审批 / Human。
- [ ] 预算决策（分类输入、分类结果、最终档位、用户覆盖、回退原因、成本）完整进入 Execution Trace，且不泄露 hidden CoT 与私有 scratchpad。
- [ ] Query Classifier 不引入额外模型调用；分类不确定时向更安全、更可验证档位回退；预算系统异常时回退静态 `qa` / `deep` 路由且请求不失败。
- [ ] Hybrid + Reranker 升级保留项目事实优先、知识库证据优先与来源标注；Reranker 不可用时回退 Vector Search。
- [ ] 安全测试覆盖 Plan Mode 阻断、read-only 阻断、审批缺失阻断、full access 不越权与预算异常回退。
- [ ] 影子模式、灰度开关、发布门槛与回滚条件落地；默认档位变更有 Plan 13 指标对比、实验记录和回放样本。
- [ ] `/dialogue` 用户指南解释自动预算、用户覆盖、延迟 / 成本预期与高风险审批。
- [ ] 相关相对链接和 `doc/README.md` 索引保持一致。

## 8. 风险与规避

| 风险 | 影响 | 规避 |
| --- | --- | --- |
| Plan 13 未开始 | P14-C 指标对比与 P14-E 发布门槛无法验收 | P14-A 契约冻结后，并行推进 Plan 13 Phase 0–3；未完成前不启用改变默认行为的档位 |
| WeKnora 无 Hybrid / Rerank 能力 | P14-C 需自建混合检索与轻量 rerank | P14-C 开工前先做技术预研；不支持时评估本地关键字召回 + LLM / 规则打分的降级方案 |
| 无灰度 / Feature Flag 机制 | 影子与灰度发布无处落脚 | P14-A 冻结开关与用户组契约，P14-E 落地最小实现 |
| `assistant_service.py` 与 `DialogueView.vue` 体量大 | 改动集中、回归面大 | 每个 PR 只跑 Assistant 指定回归与前端构建，最后阶段全量 E2E |
| 预算策略绕过安全策略 | 高风险任务被降档执行 | 安全测试作为 P14-D 一票否决退出条件；高风险档位禁止降档 |

## 9. 状态记录

- 2026-08-19：从 Plan 11 迁入动态计算预算目标架构、Model Router、RAG 检索分层、Agent 执行分级、落地边界与 P11-A–P11-E 行动框架（重编号为 P14-A–P14-E），并补充当前基线、依赖风险与验收标准；未修改业务代码。
