# Plan 11：LUI 科研问答 / 深度思考 Preset 定位与演进

> 状态：已完成（Preset 定位与 `preset_id` 兼容基础已实施；动态计算预算已移交 Plan 14）
>
> 日期：2026-08-16
>
> 最近更新：2026-08-19
>
> 前置文档：
> - [research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md](research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md)
> - [research-engine-plan-09-lui-execution-trace.md](research-engine-plan-09-lui-execution-trace.md)
> - [research-engine-plan-10-slash-command-and-agent-control-workplan.md](research-engine-plan-10-slash-command-and-agent-control-workplan.md)
> - [research-engine-plan-12-product-positioning-evolution.md](research-engine-plan-12-product-positioning-evolution.md)
> - [research-engine-plan-14-lui-dynamic-compute-budget-plan.md](research-engine-plan-14-lui-dynamic-compute-budget-plan.md)
> - [platform-positioning-and-small-iteration-plan.md](platform-positioning-and-small-iteration-plan.md)
> - [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md)

## 1. 摘要

PolyAgent LUI 当前提供的 `科研问答` 与 `深度思考` 仍是 `AssistantService` 中的 `mode` 分支，不是完整 Preset。两个模式的差异集中在模型路由 purpose、联网检索深度和是否输出高层 `reasoning_summary`，没有独立的工具集、Skills、权限、workflow、output policy 或 execution policy。

本计划将 `科研问答` 与 `深度思考` 定义为 PolyAgent LUI 的两个领域 Preset：

```text
research_qa    快速科研问答、平台入口导航与项目事实查询
research_deep  需要证据综合、多步判断或可解释结论的深度科研分析
```

两者共享同一个 Base Agent / AssistantService，不复制 DeepSeek Harness 的 Cordis / TypeScript runtime，也不照搬 `Standard` / `PTC` / `Minimal` / `Cordis`。

本计划只承担 Preset 定位、边界、共同不变量、切换规则与 `preset_id` 兼容基础；动态计算预算（分类 → 路由 → 分级预算）的架构、行动框架与实施已整体移交 [Plan 14](research-engine-plan-14-lui-dynamic-compute-budget-plan.md)。

## 2. 非目标

本计划明确不做以下事项：

- 除 11.1 的最小兼容落地外，不修改其他业务代码、API、Pydantic schema、前端组件或自动化测试。
- 不在本次实现完整 Preset Registry、Preset 编辑器或 Preset 市场。
- 不引入 Cordis、DSH 插件系统或 TypeScript runtime。
- 不照搬通用 `Standard` / `PTC` / `Minimal` / `Cordis` 四类定义。
- 不把 `qa` / `deep` 重写为两个独立 Agent。
- 不扩展本期 Preset 集合，仅保留未来 `algorithm`、`report`、`literature` 等扩展 seam。
- 不将 Preset 声称为安全沙箱；最终执行仍受 RBAC、工具 policy、审批、Execution Trace 和系统级安全规则约束。
- 不实现 Query Classifier、动态 Model Router、Hybrid Retrieval 升级、Reranker 或 Agent 执行分级；上述内容由 Plan 14 承接。
- 预算策略的默认值、用户显式选择与系统安全策略优先级由 Plan 14 定义和实施。

## 3. 当前实现基线

截至 2026-08-16，LUI 的 `qa` / `deep` 行为如下；2026-08-19 仅按 11.1 增加 `preset_id` 兼容记录，动态预算演进项已移交 Plan 14：

| 维度 | 当前实现 | 说明 |
| --- | --- | --- |
| 前端模式值 | `qa`、`deep` | `DialogueView` 提供“科研问答 / 深度思考”切换，默认 `qa` |
| 模式归一化 | 后端 `_normalize_mode` | 仅接受 `qa` / `deep` / `model`，其余回退 `qa` |
| 模型路由 | `route_purpose` | `qa` 走 `catalog.routing.qa`，`deep` 走 `catalog.routing.deep` |
| 模型排序 | 前端 `llmModels.js` | `qa` 优先 `fast` / `recommended_for=qa`；`deep` 优先 `reasoning` / `long_context` / `recommended_for=deep` |
| 联网检索 | `AssistantWebSearchService.search` | `deep` 比 `qa` 多取 4 条结果、多抓 2 页 |
| 知识库检索 | `_retrieve_knowledge` | `qa` / `deep` 当前使用同一套 WeKnora 检索与证据注入 |
| 输出格式 | `AssistantAnswerSynthesizer` | `deep` 非流式要求 `answer_markdown` + `reasoning_summary` JSON；流式路径直接输出 Markdown，并由服务端生成可见推理摘要 |
| 推理摘要 | `_visible_reasoning_summary` | `deep` 展示 2–5 条高层推理/证据检查/决策依据，禁止暴露 hidden chain-of-thought、私有 scratchpad、token 级推理 |
| 算法工具调用 | `_propose_tool_calls` | 当前不由 `qa` / `deep` 决定，而由“用户是否选择算法工具 + 模型是否具备 `tool_calling`”决定 |
| 会话持久化 | `AssistantChatCreate / Update` | 仅保存 `mode` 字符串，没有 Preset 对象、工具集、Skills、权限、workflow、output_policy 或 execution_policy |
| Trace | Plan 09 / `assistant_run_service` | run、message、route、retrieval 和工具调用已进入统一事件与投影，但尚无显式 `preset_id` |
| 动态计算预算 | 暂无独立策略 | 当前 `qa` / `deep` 是粗粒度默认值；问题难度分类、风险分级、检索升级、执行预算档位与预算决策 Trace 由 Plan 14 承接 |

结论：`科研问答` 与 `深度思考` 在本计划完成 `preset_id` 兼容基础后，仍是“模型路由 + 检索强度 + 输出策略”的轻量 Preset；按请求动态调节 Accuracy / Latency / Cost 的预算系统由 Plan 14 实施。

## 4. DSH / Preset 参考结论

### 4.1 参考材料

- `refer/deepseek-harness-master/packages/preset/agent-presets/README.zh.md`
- `refer/deepseek-harness-master/docs/subsystems/permission-presets.zh.md`
- 用户提供的 Preset 系统草案，作为需求背景和概念来源，不作为实现规范。

### 4.2 应借鉴的架构不变量

| DSH 设计 | PolyAgent 借鉴方式 |
| --- | --- |
| Preset 是完整 runtime 配置，不是简单 prompt | 将 `qa` / `deep` 从单一 mode 升级为包含模型、检索、输出、工具和 Trace 策略的配置对象 |
| `Base Agent + Preset Prompt + Session Context + User Prompt` | 保留现有 `SYSTEM_PROMPT` 作为 Base；新增 Preset 策略段；继续复用项目事实、知识库证据和网页证据 |
| Preset 决定模型可见工具、Skills、权限、workflow、输出策略、执行策略 | PolyAgent 先落地模型偏好、检索策略、工具边界、输出策略和 Trace 策略；Skills / 插件能力不在本期实现 |
| 每次 Execution Trace 记录当前 Preset | 在 run、message 和命令事件中记录 `preset_id`，切换后新事件使用新 Preset |
| Preset 默认绑定 Session | 复用 `AssistantChat.mode` 作为当前兼容字段；未来引入 `preset_id`，切换时保留消息、工具调用、Trace 和 Artifact |
| 系统级安全策略高于 Preset | Preset 只提供默认策略，不覆盖平台 RBAC、AgentTool policy、审批和来源标注 |
| Runtime 需要可观测的资源决策 | 未来 Preset 除能力配置外，还应记录模型、检索和执行预算的选择原因，使效果、延迟与成本可回放；由 Plan 14 承接 |

### 4.3 明确不引入

- 不引入 Cordis / TypeScript runtime。
- 不照搬 `Standard` / `PTC` / `Minimal` / `Cordis`。
- 不在本次实现完整 Preset Registry、Preset 编辑器或 Preset 市场。
- 不把 DSH 的“preset 是目录 + agent.cordis.yml”直接映射到 PolyAgent 文件系统。

## 5. PolyAgent LUI Preset 最小契约

未来若落地 Preset Registry，`AssistantPreset` 至少应包含：

```text
id
display_name
description
route_purpose: qa | deep
model_preference
classification_policy
budget_policy
system_prompt_policy
retrieval_policy
tool_policy
execution_policy
output_policy
trace_policy
ui_policy
```

字段语义：

| 字段 | 含义 |
| --- | --- |
| `id` | 稳定 Preset 标识，本期定义为 `research_qa` / `research_deep` |
| `display_name` | 前端展示名，分别为“科研问答” / “深度思考” |
| `description` | 一句话说明该 Preset 的适用任务 |
| `route_purpose` | 初始模型路由用途，当前对应 `qa` / `deep`；未来只作为兜底路由，不等于最终模型选择 |
| `model_preference` | 默认模型候选池与优先级，如 fast、reasoning、long_context、recommended_for；用户显式选择模型时优先 |
| `classification_policy` | 从问题复杂度、风险等级、证据需求和可解释性要求中提取预算输入；初期优先使用确定性规则，避免为分类本身引入过高成本（Plan 14 落地） |
| `budget_policy` | 将分类结果映射为模型档位、检索档位、执行档位和验证要求；只提供默认值，不覆盖用户显式选择和系统安全策略（Plan 14 落地） |
| `system_prompt_policy` | 是否注入深度输出格式、证据综合要求或禁止泄露 CoT 的规则 |
| `retrieval_policy` | 项目事实、知识库、联网检索的启用、默认检索方式与升级条件 |
| `tool_policy` | 是否允许算法工具调用、是否要求确认、是否要求模型具备 `tool_calling` |
| `execution_policy` | 默认执行档位，如 one-shot、planning、planning + verification；高风险任务必须叠加审批 / Human 节点 |
| `output_policy` | 是否要求 `reasoning_summary`、回答长度、依据呈现和可操作性 |
| `trace_policy` | Trace 中必须记录哪些 Preset、预算、路由、检索、执行和成本相关字段 |
| `ui_policy` | 前端切换文案、默认选择、能力、延迟 / 成本预期和风险提示 |

当前会话只保存 `mode`。未来若实现 Preset Registry：

- 以 `preset_id` 作为权威标识。
- `mode` 作为兼容字段或映射字段保留。
- 历史会话没有 `preset_id` 时，按 `mode == "deep" ? "research_deep" : "research_qa"` 回退。
- 恢复历史会话时不得因新增字段导致 500 或能力丢失。
- 用户通过 `/model`、工具选择或权限命令做出的显式选择优先于 Preset 默认值；Preset 切换不得静默重置这些显式选择。

## 6. `research_qa` 科研问答 Preset

定位：快速科研问答、平台入口导航和项目事实查询。

适用场景：

- 询问某个页面、算法、任务、审批或配置在哪里。
- 快速确认 ResearchEngine / ComputeEngine / Knowledge Base 的当前能力。
- 回答材料、算法或平台流程的简单事实问题。
- 作为进入任务提交、算法调用和研发编排的轻量入口。

核心策略：

| 策略 | 定义 |
| --- | --- |
| `route_purpose` | `qa` |
| `model_preference` | 对应 Simple Query 默认档：优先 `fast`、小模型、`recommended_for=qa`，其次使用路由中已配置的 `qa` 模型；用户显式选择模型时优先 |
| `system_prompt_policy` | 复用 Base `SYSTEM_PROMPT`，不强制注入 `DEEP_RESPONSE_FORMAT` |
| `retrieval_policy` | Easy Query 默认走项目事实与知识库 Vector Search；项目外问题按需联网。只有证据冲突、问题复杂或用户要求可解释结论时才建议升级，不得默认付出最高检索成本 |
| `tool_policy` | 允许现有算法工具调用，前提是用户已选工具且当前模型支持 `tool_calling`；算法执行仍必须走确认 / 审批状态机 |
| `execution_policy` | 低风险导航与事实查询默认 One-shot；复杂或高风险问题应提示升级到 `research_deep` 或进入验证流程，而不是伪造深度结论 |
| `output_policy` | 直接输出 Markdown，回答简洁、可操作，必要时用要点列出依据；不强制展示 `reasoning_summary` |
| `trace_policy` | 记录 `preset_id=research_qa`、实际 route、query 分类、预算档位、retrieval status 和 answer_scope |
| `ui_policy` | 默认 Preset；文案为“科研问答”；提示其定位是快速、低延迟、低成本；切换后仅在没有用户显式模型选择时选择正确的 `qa` 默认模型 |

表中 Simple / Complex / High-risk 档位的动态分类、触发与保护机制由 Plan 14 实施；本计划只定义两个 Preset 的静态策略倾向。

## 7. `research_deep` 深度思考 Preset

定位：需要证据综合、多步判断或可解释结论的深度科研分析。

适用场景：

- 比较不同材料、配方、算法或工艺路径。
- 结合项目事实、知识库和外部证据形成带依据的判断。
- 需要明确推理步骤、证据检查或决策条件的问题。
- 面向研究人员、算法/计算工程师的复杂科研分析。

核心策略：

| 策略 | 定义 |
| --- | --- |
| `route_purpose` | `deep` |
| `model_preference` | 对应 Complex Reasoning 默认档：优先 `reasoning`、`long_context` 大模型和 `recommended_for=deep`，其次使用路由中已配置的 `deep` 模型；用户显式选择模型时优先 |
| `system_prompt_policy` | 在 Base 之上注入证据综合、高层推理摘要和禁止暴露 hidden CoT 的规则 |
| `retrieval_policy` | 使用与 `qa` 相同的项目事实、知识库和联网来源；Hard Query 在需要证据综合或多来源比对时升级为 Hybrid Search + Reranker，并按现有策略多取 4 条结果、多抓 2 页 |
| `tool_policy` | 允许现有算法工具调用，前提是用户已选工具且当前模型支持 `tool_calling`；执行结果必须进入最终证据链并保留来源标注 |
| `execution_policy` | 需要多步判断的问题默认 Planning，并以高层 `reasoning_summary` 呈现步骤与依据；算法执行、审批、不可逆操作或进入正式报告的结果必须叠加 Verification / Human |
| `output_policy` | 输出 Markdown 最终答案 + 2–5 条高层推理/证据检查/决策依据摘要；禁止泄露 private scratchpad 或 token 级推理 |
| `trace_policy` | 记录 `preset_id=research_deep`、实际 route、query 分类、预算档位、检索升级原因、retrieval status、证据数量和 `reasoning_summary` |
| `ui_policy` | 文案为“深度思考”；切换后仅在没有用户显式模型选择时选择正确的 `deep` 默认模型，并提示该模式可能更慢、成本更高、更强调依据 |

表中 Hybrid Search + Reranker 升级、Planning 执行档位与预算档位的动态选择机制由 Plan 14 实施；本计划只定义两个 Preset 的静态策略倾向。

## 8. 两者共同不变量与切换规则

### 8.1 共同不变量

- 同一个 Base Agent / AssistantService，不创建两个独立 Agent。
- 都遵守项目事实优先、知识库证据优先、外部证据补充、不编造事实。
- 都遵守 RBAC、AgentTool policy、审批、Execution Trace 和来源标注。
- 算法工具调用都遵循“用户已选工具 + 模型支持 `tool_calling` + 确认/审批状态机”。
- 都以 Accuracy / Latency / Cost 的动态预算为共同优化目标；预算只改变默认模型、检索和执行强度，不降低安全底线（机制由 Plan 14 实施）。
- 用户显式选择的模型、工具和权限优先于预算默认值；分类不确定时向更安全、更可验证的档位回退（机制由 Plan 14 实施）。
- 模型路由、检索升级、执行分级、人工 / 验证节点和用户覆盖都必须进入 Execution Trace，保证效果、延迟与成本可回放、可审计（机制由 Plan 14 实施）。
- 都支持会话持久化、历史恢复、服务端续答、run 取消和 Trace 回放。
- 都使用中文产品口径，不把通用 agent harness 作为 PolyAgent 核心竞争力。

### 8.2 切换规则

切换 Preset 只改变 runtime 配置：

```text
model_preference
classification_policy
budget_policy
system_prompt_policy
retrieval_policy
tool_policy
execution_policy
output_policy
trace_policy
```

切换后必须保留：

```text
chat
messages
tool_calls
run
execution trace
artifacts
goal / todo（未来 Plan 10 落地后）
```

切换必须记录新的 `preset_id`，后续新事件、新 run 和新 Trace 使用新 Preset。

## 9. 演进边界

本计划先把 `research_qa` 与 `research_deep` 定义清楚，未来可以按同一 Preset seam 增加：

```text
research_algorithm  算法调用与实验执行
research_report     报告生成
research_literature 文献阅读与证据整理
research_code       受限科研代码 / 计算脚本
```

这些 Preset 不进入本期定义；新增时只扩展配置，不重写 AssistantService 的领域事实、工具确认和 Trace 体系。

与 Plan 10 的关系：

- Plan 10 落地的 Slash Command、Plan Mode、Permission Mode、Goal/Todo 应作为会话级控制状态。
- 未来若实现 Preset Registry，`preset_id` 应进入会话控制状态和 Trace。
- 权限仍由系统安全策略、AgentTool policy、会话权限模式和审批共同决定，Preset 不能越权。
- 动态预算由 Plan 14 承接：依赖 Plan 10 的 Plan Mode、Permission Mode、Goal / Todo 与审批状态，也依赖 Plan 13 的任务成功率、准确率、延迟、成本和幻觉指标进行调优。
- Plan 14 落地必须先观测、再保守启用、最后灰度扩展；没有指标对比和回滚能力时，不得把预算策略作为默认行为。

## 10. 验收标准

- [x] 文档能明确区分 `科研问答` 与 `深度思考`：前者是快速问答与导航，后者是带证据链和高层推理摘要的深度分析。
- [x] 文档明确写出 `qa` / `deep` 当前只是 mode 开关，不是完整 Preset。
- [x] 文档定义 `research_qa` / `research_deep` 的模型偏好、检索策略、工具策略、输出策略、Trace 策略和 UI 策略。
- [x] 文档说明未来 `preset_id` 与当前 `mode` 的兼容/映射关系。
- [x] 文档说明 Preset 切换保留会话、消息、工具调用、Trace 和 Artifact，只改变 runtime 配置。
- [x] 动态计算预算的原则、档位映射、落地行动、Trace 要求与评估依赖已移交 Plan 14，本计划不再承担其实施与验收。
- [x] 文档不照搬 `Standard` / `PTC` / `Minimal` / `Cordis`，不引入 Cordis / TypeScript runtime。
- [x] 文档不直接修改代码，也不把本期写成完整 Preset Registry 实施任务。
- [x] 相关相对链接和 `doc/README.md` 索引保持一致。

## 11. 假设与默认选择

- 本期只定义 `科研问答` 与 `深度思考` 两个 Preset，不扩展完整 PolyAgent Preset 体系。
- 本计划原为定位、架构与验收文档，不拆成后端/前端/测试的逐文件实施任务；2026-08-19 仅补充 11.1 的最小兼容落地。
- 动态计算预算已整体移交 Plan 14 独立实施。
- 未来若实现 Preset Registry，`preset_id` 成为权威标识，`mode` 作为兼容字段保留。
- `deep` 的高层 `reasoning_summary` 仍只展示可审计的高层推理，不展示 hidden CoT 或私有 scratchpad。
- 算法工具调用不因切换到 `research_qa` 或 `research_deep` 而自动打开，仍需用户选择工具且模型支持。
- Preset 不能覆盖平台 RBAC、AgentTool policy、审批和系统安全规则。

### 11.1 最小代码落地记录（2026-08-19）

- [x] 新增 `research_qa` / `research_deep` 轻量标识与兼容映射，不引入完整 Preset Registry、Preset 编辑器或新 Agent。
- [x] 会话创建、更新与恢复保留 `mode`，同步保存 `preset_id`；历史会话缺少 `preset_id` 时按旧 `mode` 回退。
- [x] run 请求快照、初始 route 与 `route.resolved` 事件记录 `preset_id`，保证后续 Trace 回放可识别本轮 Preset。
- [x] 保持用户显式模型选择优先；Preset 只决定默认路由用途，不改变既有工具确认、RBAC、审批和安全策略。
- [x] 保持算法工具启用条件不变：仍由用户已选工具、模型能力和既有确认状态机决定，不因 Preset 自动开启。
- [x] 补充 Preset 兼容、旧会话回退、run 记录、显式模型优先与工具不自动开启的回归测试。
- [x] 验证 Assistant 相关后端测试、模型排序前端测试与前端构建通过。

本节不实施动态计算预算；Query Classifier、动态 Model Router、Hybrid Retrieval、Reranker 与 Agent 执行分级均已移交 Plan 14。

## 12. 移交 Plan 14 的内容

以下动态计算预算相关内容已于 2026-08-19 整体移交 [Plan 14](research-engine-plan-14-lui-dynamic-compute-budget-plan.md)，本计划不再维护其待办与验收：

- 动态计算预算目标架构：Accuracy / Latency / Cost 平衡原则与“分类 → 路由 → 分级预算”决策顺序。
- Model Router：Simple Query / Complex Reasoning / High-risk Task 的先分类、再路由演进。
- RAG 检索分层：Easy Query Vector Search 与 Hard Query Hybrid Search + Reranker 的升级触发。
- Agent 执行分级：Low-risk One-shot、Medium Planning、High-risk Planning + Verification + Human。
- 预算落地边界：默认值优先级、安全兜底、Trace 记录、异常回退、观测 → 灰度 → 默认的启用顺序。
- 后续行动框架：原 P11-A–P11-E 重编号为 Plan 14 的 P14-A–P14-E，全部保持未开始。
- 相关假设与验收：确定性 Query Classifier、预算默认值优先级、预算 Trace 隐私控制与指标门槛。

## 13. 状态记录

- 2026-08-16：创建 Plan 11 文档，定义 `research_qa` / `research_deep` 的定位、边界、共同不变量与演进方向；未修改业务代码。
- 2026-08-18：补充成本、延迟、效果平衡与动态计算预算说明，明确 Model Router、RAG 检索分层、Agent 执行分级及落地边界；未修改业务代码。
- 2026-08-19：将动态计算预算贯穿 Preset 契约、两个模式策略、切换不变量、验收标准和落地边界，并新增 P11-A–P11-E 后续行动框架；未修改业务代码。
- 2026-08-19：完成本期定位与演进方案评审闭环，勾选第 10 节验收项；P11-A–P11-E 保持待办，待拆分独立实施计划。
- 2026-08-19：完成第 11 节最小代码落地：新增两个 Preset 标识、`mode` 兼容映射、会话与 run 的 `preset_id` 记录；显式模型、工具选择和安全策略优先级保持不变。第 12 节动态计算预算与 P11-A–P11-E 仍未实施。
- 2026-08-19：将第 12 节动态计算预算与 P11-A–P11-E 行动框架整体移交 Plan 14（重编号为 P14-A–P14-E），并同步更新摘要、非目标、基线、契约、策略、不变量、验收与假设中的引用；本计划范围收敛为 Preset 定位与 `preset_id` 兼容基础，未修改业务代码。
