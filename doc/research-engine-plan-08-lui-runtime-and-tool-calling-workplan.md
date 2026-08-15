# Plan 08：LUI Runtime、上下文注入与工具调用增强工作计划

> **状态：待评审 / 未开始**
>
> 日期：2026-08-15
>
> 基线：`develop` 分支提交 `f40d819`（`feat: enhance assistant service and tool service with improved argument handling and error reporting`）
>
> 前置计划：[research-engine-plan-07-lui-algorithm-tooling.md](research-engine-plan-07-lui-algorithm-tooling.md)

## 1. 背景与目标

Plan 07 已完成 `/dialogue` LUI 的基础能力：垂类算法工具派生、权限策略、参数确认状态机、AlgorithmRun 执行、历史会话恢复、真实模型工具调用和响应式验收。当前主要问题从“功能是否存在”转为“运行链路是否可识别、可解释、可预算、可回放”。

本计划参考 DeepSeek Harness 的 Cordis、Tool Runtime、System Prompt、Session Log 和配置目录设计，在不推翻现有 FastAPI + MongoDB + Vue 架构、不引入 Cordis 运行时的前提下，对 Poly_Agent LUI 做渐进增强。

### 1.1 产品目标

每一轮 LUI 回答都应能明确回答：

1. 实际使用了哪个 provider / model。
2. 模型能力是配置确认的、探测到的，还是推断出来的。
3. 本轮注入了哪些上下文，各来自哪里，占了多少预算，哪些被省略。
4. 模型看到了哪些工具 schema，schema 对应哪个算法版本。
5. 模型为什么提议某个工具调用，原始参数是什么。
6. 用户确认时修改了哪些参数。
7. 工具执行结果如何回到模型，最终回答基于哪个 continuation run。
8. 失败发生在模型、路由、schema、权限、执行还是续答阶段。

### 1.2 非目标

本计划明确不做以下事项：

- 不引入 Cordis / TypeScript 插件运行时。
- 不重写 MongoDB 数据模型或废弃现有 API 路径。
- 不把前端迁移为 agent harness UI。
- 不在第一阶段实现完整 token 级回放、fork、compaction。
- 不一次性开放任意 MCP / OpenAPI / 系统级工具。
- 不把现有垂类算法执行链路替换为新的执行器。

### 1.3 核心决策

**借 DeepSeek Harness 的不变量，不移植它的运行时。**

| DeepSeek Harness 设计 | Poly_Agent 借鉴方式 |
|---|---|
| Cordis 服务 seam 与依赖注入 | 用清晰的 Python 服务边界命名现有能力，不引入 IoC 框架 |
| 每轮动态组装 system prompt 与 tool schema | 新增 `AssistantContextAssembler` 与 request manifest |
| `tools/pre-execute → execute → post-execute → result` 流水线 | 梳理现有权限、确认、AlgorithmRun、结果归一化为显式阶段并落事件 |
| `request/header` 记录模型配置、系统提示词与工具 schema | LUI run 保存 route、context manifest、tool schema digest / 快照 |
| append-only Session Event 与连续 seq | 新增统一 `assistant_events`，旧 embedded events 双写并回填 |
| 配置目录由源码类型生成并校验 | 用 Pydantic schema 作为 LLM provider 配置和文档的唯一来源 |

## 2. 参考材料

### 2.1 DeepSeek Harness 文档

- [Cordis Primer](https://deepseek-harness.github.io/deepseek-harness/reference/cordis-primer)
- [插件配置目录](https://deepseek-harness.github.io/deepseek-harness/reference/config-catalog)
- [Tool Schema 目录](https://deepseek-harness.github.io/deepseek-harness/reference/tool-catalog)
- [持久化事件目录](https://deepseek-harness.github.io/deepseek-harness/reference/persistence-catalog)
- [Cordis Context API](https://deepseek-harness.github.io/deepseek-harness/reference/cordis-api/context)

### 2.2 本地参考源码

以下文件位于 `refer/deepseek-harness-master/`：

- `docs/cordis-primer.zh.md`
- `docs/config-catalog.zh.md`
- `docs/tool-catalog.zh.md`
- `docs/persistence-catalog.zh.md`
- `docs/cordis-api/context.zh.md`
- `docs/architecture.zh.md`
- `docs/agent-lifecycle.zh.md`
- `packages/core/system-prompt/src/index.ts`
- `packages/core/tools/src/index.ts`
- `packages/core/agent-loop/src/agent.ts`
- `packages/core/session/src/types.ts`
- `packages/session/session-persistence/src/*`

### 2.3 Poly_Agent 当前基线

- `backend/app/services/assistant_service.py`
- `backend/app/services/assistant_run_service.py`
- `backend/app/services/assistant_tool_service.py`
- `backend/app/services/agent_tool_service.py`
- `backend/app/services/llm_model_service.py`
- `backend/app/schemas/agent_tools.py`
- `backend/app/schemas/llm_models.py`
- `backend/app/infra/research_engine_repositories.py`
- `frontend/src/views/DialogueView.vue`
- `frontend/src/components/LlmModelSelect.vue`
- `frontend/src/components/ToolMenuPicker.vue`
- `frontend/src/utils/assistantToolCalls.mjs`
- `frontend/src/utils/llmModels.js`

## 3. 当前问题盘点

### 3.1 模型信息与能力识别

| 问题 | 现状 | 影响 |
|---|---|---|
| `tool_calling` 未在 LUI 展示 | 后端 capability 枚举已有该值，`LlmModelSelect.vue` 未渲染 | 用户选择工具时无法判断模型能否发起调用 |
| 模型配置粒度过粗 | provider 级 capabilities + 字符串 models | 无法描述 per-model 工具协议、上下文窗口、并行调用能力 |
| 远端探测模型能力继承不准确 | 新发现模型继承第一个已知模型能力 | 可能误判工具调用或推理能力 |
| 默认模型选择有硬编码 | 优先 `default_openai`，再看 preferred/route | 深度模式和历史会话模型可能被覆盖 |
| run 只记录请求模型 | `AssistantRunService.create()` 只读 context.model | 历史消息无法回答实际 resolved route |
| 错误归因粗糙 | provider 异常统一提示“不支持工具调用” | 鉴权、超时、模型不存在与能力缺失混淆 |

### 3.2 工具调用协议

| 问题 | 现状 | 影响 |
|---|---|---|
| schema 转换重复 | 后端、工具状态机、前端各自解析描述字符串 | 模型 schema、校验和表单可能漂移 |
| 约束转换不完整 | enum / min / max / pattern / default 未完整进入 JSON Schema | 模型提案质量和校验一致性不足 |
| tool call 元数据丢失 | 只保留 id、name、parsed arguments | 无法审计 finish reason、raw arguments、usage、tool index |
| 参数解析失败置空 | JSON 异常后使用 `{}` | 模型 malformed 输出被伪装成参数缺失 |
| 多工具行为不一致 | 系统提示词允许多个调用，实现只取 `tool_calls[:1]` | 模型预期与产品行为不一致 |
| 提议原因固定 | `selection_confidence=0.5`，reason 为固定文案 | 无法解释工具选择和模型输出质量 |

### 3.3 上下文注入

| 问题 | 现状 | 影响 |
|---|---|---|
| 全量注入事实 | `_build_context_block()` 直接拼完整 FACTS / LLM catalog | 长上下文浪费与重点稀释 |
| 无 section 预算 | 未按来源或 token 估算裁剪 | 算法和模型数量增长后不可控 |
| 无上下文 manifest | 未记录注入、截断、省略原因 | 无法审计模型看到什么 |
| 工具 schema 无请求快照 | 历史调用只保存算法版本 | active version 或 schema 变化后无法精确重放 |

### 3.4 持久化与状态恢复

| 问题 | 现状 | 影响 |
|---|---|---|
| 事件格式不统一 | run events 有 seq，tool events 无 seq | 前端需要两套恢复逻辑 |
| route / context 无事件 | run 只保存 stage 与 partial content | 回放缺少关键决策点 |
| 续答依赖前端 | 工具完成后浏览器轮询并触发 continuation | 浏览器关闭可能丢失最终回答 |
| 工具执行有线程路径 | 确认后存在 daemon thread 执行路径 | 进程退出时可靠性不足 |

## 4. 目标架构

```text
Frontend LUI
  │ AssistantRun API / SSE
  ▼
AssistantRunService
  │
  ├─ ModelRouteResolver
  │    ├─ requested model
  │    ├─ purpose route
  │    ├─ capability filter
  │    └─ fallback reason
  │
  ├─ AssistantContextAssembler
  │    ├─ project facts provider
  │    ├─ selected tools provider
  │    ├─ knowledge evidence provider
  │    ├─ web evidence provider
  │    ├─ prior tool result provider
  │    └─ budget + manifest
  │
  ├─ AssistantToolContractAdapter
  │    ├─ AlgorithmIOSchema → JSON Schema
  │    ├─ stable function name
  │    ├─ constraints / defaults / enums
  │    └─ provider compatibility
  │
  ├─ ProviderGateway
  │    ├─ chat.completions tools
  │    ├─ response model / usage / finish reason
  │    └─ structured error
  │
  ├─ ToolProposalParser
  │    ├─ raw arguments
  │    ├─ validation result
  │    ├─ tool id mapping
  │    └─ proposal metadata
  │
  ├─ ToolExecutionPipeline
  │    ├─ auth / policy
  │    ├─ schema validation
  │    ├─ confirmation
  │    ├─ AlgorithmRun
  │    └─ result normalization
  │
  └─ AssistantEventWriter
       ├─ route.resolved
       ├─ request.header
       ├─ context.assembled
       ├─ tool.proposed
       ├─ tool.state
       ├─ tool.result
       ├─ llm.usage
       └─ run.status
```

上述边界通过普通 Python module / class 落地，现有服务单例和 API 契约保持不变。

## 5. 分阶段任务

### Phase 0：模型识别与 LUI 可见性修复

**目标**：先让用户和后端都能准确知道“本轮实际使用什么模型、该模型能否调用工具”。

**预计工作量**：1–2 天

**建议 PR**：PR-01

- [x] 扩展 `LLMProviderConfigInput`，允许 `models` 同时兼容字符串和对象：

  ```json
  {
    "provider_id": "deepseek_primary",
    "provider_type": "openai_compatible",
    "base_url": "https://example.internal/v1",
    "api_key_env": "DEEPSEEK_API_KEY",
    "models": [
      {
        "model_id": "deepseek-v4-flash",
        "display_name": "DeepSeek V4 Flash",
        "capabilities": ["chat", "structured_json", "tool_calling"],
        "recommended_for": ["qa", "deep"],
        "context_window": 131072,
        "max_output_tokens": 8192,
        "tool_protocol": "openai_chat_tools",
        "supports_parallel_tool_calls": true
      }
    ]
  }
  ```

- [x] 为 `LLMModelInfo` 增加可空字段：
  - `context_window`
  - `max_output_tokens`
  - `tool_protocol`
  - `supports_parallel_tool_calls`
  - `capability_source`
- [x] 内部统一将字符串 model 配置 normalize 为 object，旧配置不报错。
- [x] `_provider_with_models()` 不再把第一个已知模型能力直接赋给所有新发现模型；未配置模型能力标记为 `inferred`。
- [x] `resolve_route()` 返回：
  - requested provider/model
  - resolved provider/model
  - route reason：`user_selected` / `purpose_default` / `tool_capability_override` / `fallback`
  - capabilities 与 tool protocol
  - context window
- [x] `AssistantRunService.create()` 保存 requested model；worker 解析后保存 resolved route。
- [x] 新增 `route.resolved` 事件并写入 run event stream。
- [x] `LlmModelSelect.vue` 展示 `tool_calling` 标签和 provider/model 双重信息。
- [x] `DialogueView.vue` 修正默认选择顺序：
    1. URL 显式指定
    2. 历史会话保存的模型
    3. 当前 purpose 默认 route
    4. recommended model
    5. 第一个可用模型
- [x] 引入 `modelSelectionOrigin`，区分 `url` / `chat` / `route` / `user` / `fallback`；用户手动选择后不被模式切换覆盖。
- [x] assistant message meta 展示实际模型与能力。

**验收标准**

- 历史会话恢复后能显示原模型。
- qa/deep 切换使用正确默认路由，用户手动选择不被覆盖。
- run API 能区分 requested model 与 resolved model。
- 无 `tool_calling` 能力的模型在 LUI 中可见且后端可硬拦截。
- 相关后端测试与 `frontend/src/utils/llmModels.test.mjs` 通过。

### Phase 1：统一 Tool Contract Adapter

**目标**：让模型 schema、服务端校验、前端表单共享同一契约，并保留模型原始提议。

**预计工作量**：2–4 天

**建议 PR**：PR-02

- [ ] 新增 `backend/app/services/assistant_tool_contract.py`，提供：
  - `safe_function_name(tool_id)`
  - `build_json_schema(tool)`
  - `build_function_tool(tool)`
  - `validate_arguments(tool, arguments)`
  - `missing_inputs(tool, arguments, asset_refs)`
  - `schema_digest(tool)`
  - `normalize_provider_arguments(raw_arguments)`
- [ ] `AgentTool` 响应增加派生字段：
  - `function_name`
  - `input_json_schema`
  - `schema_digest`
  - `presentation`
- [ ] JSON Schema 支持：
  - string / integer / number / boolean / array / object
  - enum
  - minimum / maximum
  - min_length / max_length / pattern
  - default
  - required
  - additionalProperties
- [ ] function name 使用稳定 hash 后缀，避免同名冲突和超长名称。
- [ ] `AssistantService._propose_tool_calls()` 改用统一 adapter。
- [ ] `AssistantToolCallService` 参数校验改用统一 adapter，保留现有兼容 coercion。
- [ ] 前端优先使用后端 `input_json_schema` / `presentation`，旧 `field_schema` 仅作 fallback。
- [ ] `AssistantToolCall` 增加提案元数据：
  - `function_name`
  - `provider_tool_call_index`
  - `raw_arguments`
  - `arguments_parse_error`
  - `finish_reason`
  - `proposal_route`
  - `proposal_usage`
  - `schema_digest`
- [ ] malformed arguments 不再置空；创建 `awaiting_input` 时同时保存 raw output 和 parse error。
- [ ] 定义错误码：
  - `MODEL_TOOL_CAPABILITY_UNAVAILABLE`
  - `PROVIDER_AUTH_FAILED`
  - `PROVIDER_TIMEOUT`
  - `MODEL_NOT_FOUND`
  - `TOOL_PROTOCOL_ERROR`
  - `TOOL_ARGUMENTS_INVALID`
  - `UNKNOWN_TOOL_NAME`
  - `PROVIDER_REQUEST_FAILED`
- [ ] 多工具调用策略：
  - 默认保持单工具卡片，系统提示词与实现一致；
  - 当模型和工具都声明支持并行调用时，通过配置开启最多 3 个；
  - 保守起见第一版可先只改提示词，不开放多工具执行。

**验收标准**

- 同一算法版本生成的 function schema 稳定。
- 不同 `tool_id` 不生成重复 function name。
- enum / min / max / default 均进入模型 schema，并能被服务端复用校验。
- 模型原始 arguments 和 parse error 可追溯。
- provider 网络错误不再被误报为模型不支持工具调用。

### Phase 2：Context Assembler 与 Request Manifest

**目标**：上下文注入可预算、可解释、可回放。

**预计工作量**：3–5 天

**建议 PR**：PR-03

- [ ] 新增 `backend/app/services/assistant_context_assembler.py`。
- [ ] 定义 `ContextSection`：

  ```python
  @dataclass(frozen=True)
  class ContextSection:
      name: str
      source: str
      content: str
      token_estimate: int
      included: bool
      omitted_reason: str | None
      digest: str
  ```

- [ ] 内置 provider：
  - `project_facts`
  - `llm_route`
  - `selected_tools`
  - `knowledge_evidence`
  - `web_evidence`
  - `prior_tool_results`
  - `conversation_policy`
- [ ] 第一版 token 估算使用保守字符估算：`ceil(len(text) / 4)`，不引入 tokenizer 依赖。
- [ ] 设置 section 级预算和总预算，超预算时记录 `omitted_reason`。
- [ ] `selected_tools` 只注入简短目录，不重复塞完整 JSON schema；完整 schema 仍走 native tools。
- [ ] `AssistantService` 的 tool proposal 与 final answer 使用同一 assembler。
- [ ] 生成 request manifest：

  ```json
  {
    "schema_version": 1,
    "run_id": "asrun_xxx",
    "request_kind": "tool_proposal",
    "route": {
      "provider_id": "deepseek_primary",
      "model_id": "deepseek-v4-flash",
      "purpose": "qa",
      "route_reason": "user_selected",
      "tool_protocol": "openai_chat_tools"
    },
    "context": {
      "digest": "sha256:...",
      "sections": [
        {
          "name": "project_facts",
          "source": "ProjectGroundingService",
          "token_estimate": 830,
          "included": true,
          "omitted_reason": null
        }
      ]
    },
    "tools": [
      {
        "tool_id": "algorithm:pi_score",
        "function_name": "algorithm_ab12cd34ef",
        "version": "1.0.0",
        "schema_digest": "sha256:..."
      }
    ]
  }
  ```

- [ ] 先保存 manifest、section digest 和工具 schema digest；完整 sanitized prompt snapshot 可作为后续可选项。
- [ ] assistant message metadata 写入 route 与 context digest。

**验收标准**

- 每次模型请求都有 request manifest。
- 能查看每个 section 的 token estimate 和 omitted reason。
- 恢复历史时能知道当时模型看到的工具集合。
- 算法 active version 变化后，历史调用仍可关联当时 schema digest。

### Phase 3：统一 Assistant Event Log

**目标**：将 run、route、context、tool、usage、continuation 统一为 append-only 事实流。

**预计工作量**：4–6 天

**建议 PR**：PR-04

- [ ] 新增 Mongo collection：`assistant_events`。
- [ ] 文档结构：

  ```json
  {
    "event_id": "asevt_xxx",
    "chat_id": "chat_xxx",
    "run_id": "asrun_xxx",
    "call_id": "atc_xxx",
    "seq": 12,
    "type": "tool.proposed",
    "schema_version": 1,
    "created_by": "user_xxx",
    "at": "2026-08-15T10:00:00Z",
    "data": {}
  }
  ```

- [ ] 建立索引：
  - `(chat_id, created_by, seq)`
  - `(run_id, seq)`
  - `(call_id, seq)`
  - `(type, created_at)`
- [ ] 第一批事件类型：
  - `run.created`
  - `run.started`
  - `run.canceled`
  - `run.completed`
  - `run.failed`
  - `route.requested`
  - `route.resolved`
  - `route.fallback`
  - `context.assembled`
  - `request.header`
  - `tool.catalog.resolved`
  - `tool.schema.rendered`
  - `tool.proposed`
  - `tool.arguments.invalid`
  - `tool.awaiting_input`
  - `tool.awaiting_confirmation`
  - `tool.confirmed`
  - `tool.queued`
  - `tool.started`
  - `tool.result`
  - `tool.failed`
  - `tool.canceled`
  - `tool.continuation.scheduled`
  - `llm.request.started`
  - `llm.request.failed`
  - `llm.usage.recorded`
  - `assistant.finalized`
- [ ] 新旧双写：
  - 新事件写 `assistant_events`
  - 旧 `assistant_runs.events` 和 `assistant_tool_calls.events` 暂保留
  - 读取时优先新事件，无新事件 fallback 旧字段
- [ ] 编写 backfill 脚本，将旧 embedded events 迁移到新集合，不修改旧文档语义。
- [ ] 事件只追加不更新；run 内 seq 连续。
- [ ] 前端新增 `assistantEvents.mjs`，统一按 seq 合并事件，保留现有 stale phase 防降级逻辑。

**验收标准**

- 刷新页面后 LUI 状态可由事件重放得到。
- tool call 事件不会因乱序或重放降级。
- route、context、tool、run 可通过 event stream 串联。
- 旧数据不迁移也能打开，新数据可进入 admin trace。

### Phase 4：服务端工具续答与执行可靠性

**目标**：工具执行完成后，最终模型综合回答不依赖浏览器在线。

**预计工作量**：3–5 天

**建议 PR**：PR-06

- [ ] `AssistantToolCall` 增加：
  - `continuation_state`
  - `continuation_run_id`
  - `continuation_error`
  - `source_context`
- [ ] 工具提案时保存安全 `source_context`：
  - original user message id
  - selected tools
  - mode
  - model request
  - context manifest digest
  - route snapshot
- [ ] 工具进入 terminal 状态后写入 continuation outbox 事件。
- [ ] assistant worker 扫描 `completed/failed` 且 `continuation_state=pending` 的调用。
- [ ] 以 tool call id 作为幂等键创建 continuation run。
- [ ] continuation context 复用原 user message 和 `source_context`，并携带 `tool_call_ids`。
- [ ] `_continuation_messages()` 支持多工具结果和结构化失败信息。
- [ ] 对 result summary 和 artifact 引用做 token 截断，避免工具输出挤爆上下文。
- [ ] 保留现有 daemon thread 兼容路径，但增加孤儿 queued/running 调用扫描。
- [ ] 后续将上传附件转为受管 runtime asset，减少进程内存和临时文件依赖。

**验收标准**

- 用户确认工具后关闭浏览器，算法完成后仍自动生成最终回答。
- 同一 tool call 只触发一次 continuation。
- continuation run 可追溯到原用户消息、模型提议和工具执行。
- 工具失败时模型收到结构化失败信息并给出下一步建议。

### Phase 5：LUI 产品体验升级

**目标**：让模型路由、上下文来源、工具提案和执行状态成为一等可见信息。

**预计工作量**：3–5 天

**建议 PR**：PR-05、PR-07

- [ ] 消息 meta 显示：
  - provider / model
  - route reason
  - capabilities
  - usage
  - context digest
- [ ] 点击模型 meta 展示详情：
  - capability source
  - context window
  - tool protocol
  - fallback reason
- [ ] 所选模型无 `tool_calling` 且已选工具时显示 warning：
  - 可继续普通问答
  - 可一键切换 tool-capable 模型
  - 后端仍保留硬拦截
- [ ] 工具卡片展示：
  - 提议模型
  - provider tool call id
  - function name
  - schema digest
  - raw arguments
  - parse/validation error
  - 模型提议值与用户确认值 diff
  - 事件 timeline
- [ ] 增加 “本轮上下文” 折叠面板：
  - route
  - context sections
  - token estimate
  - omitted reason
  - tool schema digest
  - evidence references
- [ ] `ToolMenuPicker` 增加：
  - 健康状态
  - 是否需要确认
  - 是否需要文件
  - 版本
  - 最近成功率
- [ ] 增加保守的“自动选择相关工具”模式：
  - 最多 5 个
  - 基于名称、描述、material scope、输入 schema 做轻量匹配
  - 记录选中原因
  - 显式用户选择优先
- [ ] 保持 320 / 768 / 1440 响应式验收。

**验收标准**

- 用户能直观看到回答使用的模型、证据、工具和失败原因。
- 参数确认前能看到模型原始提案。
- 模型不支持工具时不会误以为已经调用。
- 刷新后 UI 状态与事件流一致。

### Phase 6：配置目录、观测与验收

**目标**：让配置、文档、观测和回归测试形成闭环。

**预计工作量**：2–4 天

**建议 PR**：PR-08

- [ ] 从 Pydantic schema 生成：
  - `docs/llm-provider-config-schema.md`
  - `docs/llm-provider-config-schema.json`
- [ ] Admin LLM 配置页展示字段说明、类型、默认值和错误路径。
- [ ] 新增 LUI 调用质量指标：
  - route resolved rate
  - requested vs resolved mismatch
  - tool-capable model usage
  - tool proposal rate
  - tool proposal validation failure
  - unsupported model fallback
  - confirmation conversion
  - tool run failure
  - continuation success
  - context token distribution
  - event replay errors
- [ ] 增加回归测试矩阵（见第 7 节）。
- [ ] 更新 README、Plan 07 状态和本计划状态。

**验收标准**

- 配置字段在代码、文档和 Admin UI 中一致。
- 管理员可以定位 LUI 工具调用质量下降的具体阶段。
- 目标测试、前端单测、构建和 e2e 通过。

## 6. PR 拆分与依赖

| PR | 主题 | 主要范围 | 依赖 |
|---|---|---|---|
| PR-01 | 模型能力与路由可见性 | per-model config、tool_calling 标签、resolved route、默认选择修复 | 无 |
| PR-02 | Tool Contract Adapter | JSON Schema、stable name、raw arguments、错误分类 | PR-01 |
| PR-03 | Context Assembler | context sections、预算、manifest、request header | PR-01 |
| PR-04 | Assistant Event Log | 新 collection、双写、backfill、事件重放 | PR-01 |
| PR-05 | LUI UI 升级 | 模型 meta、上下文面板、工具卡片增强 | PR-01、PR-02 |
| PR-06 | 服务端 continuation | outbox、幂等续答、结果回注 | PR-04 |
| PR-07 | 工具菜单增强 | 健康状态、自动选择工具 | PR-02、PR-05 |
| PR-08 | 配置目录与观测 | schema 文档、指标、测试矩阵 | PR-01–PR-06 |

## 7. 测试计划

### 7.1 后端单元与 API 测试

- [ ] 字符串 model 配置兼容。
- [ ] object model 配置解析。
- [ ] per-model capabilities 独立生效。
- [ ] 未配置能力的远端模型标记 `inferred`，不继承第一个模型能力。
- [ ] requested provider/model 只有一方时返回明确错误。
- [ ] purpose route 与用户选择并存时 route reason 正确。
- [ ] run 保存 requested 与 resolved route。
- [ ] schema 转换覆盖 enum、min、max、pattern、default、required。
- [ ] stable function name 不冲突。
- [ ] malformed raw arguments 保留并可展示 parse error。
- [ ] 模型无 tool calling 时不发起 provider 请求。
- [ ] provider 鉴权、超时、模型不存在错误分类正确。
- [ ] 多工具提案在未开启并行时被明确限制。
- [ ] request manifest 记录所有 section 和 omitted reason。
- [ ] assistant event seq 连续且不更新。
- [ ] 事件重放不会降级 tool phase。
- [ ] continuation 幂等。

### 7.2 前端测试

- [ ] 默认模型选择优先级。
- [ ] 用户手动选择不被模式切换覆盖。
- [ ] 历史会话恢复模型。
- [ ] `tool_calling` 标签展示。
- [ ] 模型无工具能力时 warning。
- [ ] event reducer 合并 route / context / tool / answer / final。
- [ ] stale phase 防降级。
- [ ] raw arguments 与 parse error 展示。
- [ ] 320 / 768 / 1440 布局不溢出。

### 7.3 E2E 场景

1. 普通问答显示实际模型。
2. qa/deep 模式切换默认模型。
3. 用户手动选择模型后切换模式不覆盖。
4. 选择 tool-capable 模型完成工具调用。
5. 选择非 tool-capable 模型时显示 warning 且不误调用。
6. 模型返回 malformed tool arguments。
7. 工具运行中刷新页面并恢复状态。
8. 浏览器关闭后服务端 continuation 自动完成。
9. 管理员查看 run trace。

## 8. 兼容与迁移策略

| 项 | 策略 |
|---|---|
| API 路径 | `/assistant/*`、`/agent-tools/*` 不变 |
| 旧 provider 配置 | `models: ["id"]` 继续合法，内部 normalize |
| 旧消息 | 无模型 metadata 时显示“模型未记录”，不拒绝加载 |
| 旧 run / tool events | 保留，读取时 fallback；新事件双写 |
| Mongo 文档 | 新字段全部可空，不强制一次性迁移 |
| 工具权限 | 继续使用 ResearchEngine visibility / owner / role / policy |
| 前端状态 | 先兼容旧事件，再逐步切到统一 event reducer |

## 9. 风险与规避

| 风险 | 规避 |
|---|---|
| provider 工具能力配置错误 | 增加 `capability_source`，区分 configured / probed / inferred |
| context manifest 太大 | 第一版只保存 digest 和摘要；完整 sanitized snapshot 后续加 TTL |
| 事件迁移复杂 | 双写 + fallback + backfill，不一次性切换 |
| 多工具确认复杂 | 默认单工具；并行能力通过配置逐步开启 |
| continuation 重复触发 | tool call id 幂等键 |
| provider 错误分类不准 | ProviderGateway 返回统一结构化错误 |
| 前端状态合并复杂 | 纯函数 event reducer + 单元测试 |
| token 估算不精确 | 第一版只用于预算控制，标注估算方式 |
| 工具执行线程可靠性 | 保留兼容路径，同时增加 worker 扫描和孤儿恢复 |

## 10. 观测指标

| 指标 | 含义 | 目标 |
|---|---|---|
| route resolved rate | 成功解析实际模型的请求占比 | 接近 100% |
| requested vs resolved mismatch | 用户请求模型被替换的请求占比 | 可解释、可审计 |
| tool-capable model usage | 选中工具且使用支持工具模型的占比 | 提升 |
| tool proposal rate | 已选择工具后模型实际提议调用的占比 | 提升 |
| proposal validation failure | 模型提案参数校验失败率 | 下降 |
| unsupported fallback | 因能力缺失进入普通问答的占比 | 下降且明确展示 |
| confirmation conversion | 工具卡片确认执行率 | 提升 |
| tool run failure | AlgorithmRun 失败率 | 下降 |
| continuation success | 工具结果回注后成功生成最终回答占比 | 接近 100% |
| context token distribution | section token 分布 | 可观测、可调预算 |
| event replay errors | 前端事件重放错误数 | 0 |

## 11. 第一周执行建议

### Day 1–2

- PR-01：
  - per-model capability
  - resolved route
  - `tool_calling` 展示
  - 默认模型选择修复

### Day 3–4

- PR-02：
  - `assistant_tool_contract.py`
  - JSON Schema 统一
  - raw arguments
  - provider error 分类

### Day 5

- PR-03 起步：
  - `assistant_context_assembler.py`
  - context manifest v1
  - request header event
  - 前端模型 meta 初版

## 12. 完成定义

满足以下条件时，本计划可标记为完成：

1. 每条 assistant 消息都知道实际 provider / model、route reason、capabilities、usage 和 context digest。
2. 每个工具调用都知道提议模型、provider tool call id、function name、schema digest、raw arguments、用户确认参数、AlgorithmRun 和 continuation run。
3. 每轮请求可回放 route resolved、context assembled、tools rendered、model proposed、user confirmed、algorithm executed、result returned、final answer generated。
4. 模型能力不再靠猜；无 `tool_calling` 能力时明确阻止或警告。
5. 上下文有预算、有来源、有截断原因、有 token estimate。
6. 后端目标测试、前端单测、构建和 e2e 全部通过。

## 13. 状态记录

- 2026-08-15：创建工作计划，状态为待评审 / 未开始。计划基于当前 `develop` 基线和本地 DeepSeek Harness 参考源码整理。
- 2026-08-15：PR-01 已完成：per-model 能力配置、resolved route、`route.resolved` 事件、run requested/resolved 模型持久化、LUI 模型选择优先级与 `tool_calling` 可见性均已落地；相关后端测试、前端单测与前端构建通过。`tool_capability_override` 留待 PR-02 引入。
