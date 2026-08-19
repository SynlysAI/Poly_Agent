# Plan 08：LUI Runtime、上下文注入与工具调用增强工作计划

> **状态：已完成（PR-01、PR-02、PR-03、PR-04 阶段一、PR-05、PR-06、PR-07、PR-08 已完成；P08-F1–F10 收尾项均已关闭）**
>
> 日期：2026-08-15
>
> 基线：`develop` 分支提交 `f40d819`（`feat: enhance assistant service and tool service with improved argument handling and error reporting`）
>
> 前置计划：[research-engine-plan-07-lui-algorithm-tooling.md](research-engine-plan-07-lui-algorithm-tooling.md)
>
> 评审结论：当前实现覆盖 Plan 08 的核心链路，但文档中的“已完成”与 Phase 3、Phase 4、测试计划、E2E 的未勾选项不一致。已按 2026-08-15 评审修正，详见第 13 节。

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

- [x] 已选择算法工具时，若当前模型缺少 `tool_calling`，路由自动改选可用工具模型，并记录 `tool_capability_override`。
- [x] 新增 `backend/app/services/assistant_tool_contract.py`，提供：
  - `safe_function_name(tool_id)`
  - `build_json_schema(tool)`
  - `build_function_tool(tool)`
  - `validate_arguments(tool, arguments)`
  - `missing_inputs(tool, arguments, asset_refs)`
  - `schema_digest(tool)`
  - `normalize_provider_arguments(raw_arguments)`
- [x] `AgentTool` 响应增加派生字段：
  - `function_name`
  - `input_json_schema`
  - `schema_digest`
  - `presentation`
- [x] JSON Schema 支持：
  - string / integer / number / boolean / array / object
  - enum
  - minimum / maximum
  - min_length / max_length / pattern
  - default
  - required
  - additionalProperties
- [x] function name 使用稳定 hash 后缀，避免同名冲突和超长名称。
- [x] `AssistantService._propose_tool_calls()` 改用统一 adapter。
- [x] `AssistantToolCallService` 参数校验改用统一 adapter，保留现有兼容 coercion。
- [x] 前端优先使用后端 `input_json_schema` / `presentation`，旧 `field_schema` 仅作 fallback。
- [x] `AssistantToolCall` 增加提案元数据：
  - `function_name`
  - `provider_tool_call_index`
  - `raw_arguments`
  - `arguments_parse_error`
  - `finish_reason`
  - `proposal_route`
  - `proposal_usage`
  - `schema_digest`
- [x] malformed arguments 不再置空；创建 `awaiting_input` 时同时保存 raw output 和 parse error。
- [x] 定义错误码：
  - `MODEL_TOOL_CAPABILITY_UNAVAILABLE`
  - `PROVIDER_AUTH_FAILED`
  - `PROVIDER_TIMEOUT`
  - `MODEL_NOT_FOUND`
  - `TOOL_PROTOCOL_ERROR`
  - `TOOL_ARGUMENTS_INVALID`
  - `UNKNOWN_TOOL_NAME`
  - `PROVIDER_REQUEST_FAILED`
- [x] 多工具调用策略（第一版仅统一为单工具提示词，不开放并行执行）：
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

- [x] 新增 `backend/app/services/assistant_context_assembler.py`。
- [x] 定义 `ContextSection`：

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

- [x] 内置 provider：
  - `project_facts`
  - `llm_route`
  - `selected_tools`
  - `knowledge_evidence`
  - `web_evidence`
  - `prior_tool_results`
  - `conversation_policy`
- [x] 第一版 token 估算使用保守字符估算：`ceil(len(text) / 4)`，不引入 tokenizer 依赖。
- [x] 设置 section 级预算和总预算，超预算时记录 `omitted_reason`。
- [x] `selected_tools` 只注入简短目录，不重复塞完整 JSON schema；完整 schema 仍走 native tools。
- [x] `AssistantService` 的 tool proposal 与 final answer 使用同一 assembler。
- [x] 生成 request manifest：

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

- [x] 先保存 manifest、section digest 和工具 schema digest；完整 sanitized prompt snapshot 可作为后续可选项。
- [x] assistant message metadata 写入 route 与 context digest。

**验收标准**

- 每次模型请求都有 request manifest。
- 能查看每个 section 的 token estimate 和 omitted reason。
- 恢复历史时能知道当时模型看到的工具集合。
- 算法 active version 变化后，历史调用仍可关联当时 schema digest。

### Phase 3：统一 Assistant Event Log

**目标**：将 run、route、context、tool、usage、continuation 统一为 append-only 事实流。

**预计工作量**：4–6 天

**建议 PR**：PR-04

- [x] 新增 Mongo collection：`assistant_events`。
- [x] 文档结构：

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

- [x] 建立索引：
  - `(chat_id, created_by, seq)`
  - `(run_id, seq)`
  - `(call_id, seq)`
  - `(type, at)`
- [x] 第一批事件类型（含本次补全的三条 LLM 生命周期事件）：
  - [x] `run.created`
  - [x] `run.started`
  - [x] `run.canceled`
  - [x] `run.completed`
  - [x] `run.failed`
  - [x] `route.requested`
  - [x] `route.resolved`
  - [x] `route.fallback`
  - [x] `context.assembled`
  - [x] `request.header`
  - [x] `tool.catalog.resolved`
  - [x] `tool.schema.rendered`
  - [x] `tool.proposed`
  - [x] `tool.arguments.invalid`
  - [x] `tool.awaiting_input`
  - [x] `tool.awaiting_confirmation`
  - [x] `tool.confirmed`
  - [x] `tool.queued`
  - [x] `tool.started`
  - [x] `tool.result`
  - [x] `tool.failed`
  - [x] `tool.canceled`
  - [x] `tool.continuation.scheduled`
  - [x] `llm.request.started`
  - [x] `llm.request.failed`
  - [x] `llm.usage.recorded`
  - [x] `assistant.finalized`
- [x] 新旧双写：
  - 新事件写 `assistant_events`
  - 旧 `assistant_runs.events` 和 `assistant_tool_calls.events` 暂保留
  - 读取时优先新事件，无新事件 fallback 旧字段
- [x] 编写 backfill 脚本，将旧 embedded events 迁移到新集合，不修改旧文档语义。
- [x] 事件只追加不更新；run/call 内 seq 连续。
- [x] 前端新增 `assistantEvents.mjs`，统一按 seq 合并事件，保留现有 stale phase 防降级逻辑。

**验收标准**

- 刷新页面后 LUI 状态可由事件重放得到。
- tool call 事件不会因乱序或重放降级。
- route、context、tool、run 可通过 event stream 串联。
- 旧数据不迁移也能打开，新数据可进入 admin trace。

### Phase 4：服务端工具续答与执行可靠性

**目标**：工具执行完成后，最终模型综合回答不依赖浏览器在线。

**预计工作量**：3–5 天

**建议 PR**：PR-06

- [x] `AssistantToolCall` 增加：
  - `continuation_state`
  - `continuation_run_id`
  - `continuation_error`
  - `source_context`
- [x] 工具提案时保存安全 `source_context`：
  - original user message id
  - selected tools
  - mode
  - model request
  - context manifest digest
  - route snapshot
- [x] 工具进入 terminal 状态后写入 continuation outbox 事件。
- [x] assistant worker 扫描 `completed/failed` 且 `continuation_state=pending` 的调用。
- [x] 以 tool call id 作为幂等键创建 continuation run。
- [x] continuation context 复用原 user message 和 `source_context`，并携带 `tool_call_ids`。
- [x] `_continuation_messages()` 支持多工具结果和结构化失败信息。
- [x] 对 result summary 和 artifact 引用做 token 截断，避免工具输出挤爆上下文。
- [x] 保留现有 daemon thread 兼容路径，但增加孤儿 queued/running 调用扫描。
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

- [x] 消息 meta 显示：
  - provider / model
  - route reason
  - capabilities
  - usage
  - context digest
- [x] 点击模型 meta 展示详情：
  - capability source
  - context window
  - tool protocol
  - fallback reason
- [x] 所选模型无 `tool_calling` 且已选工具时显示 warning：
  - 可继续普通问答
  - 可一键切换 tool-capable 模型
  - 后端仍保留硬拦截
- [x] 工具卡片展示：
  - 提议模型
  - provider tool call id
  - function name
  - schema digest
  - raw arguments
  - parse/validation error
  - 模型提议值与用户确认值 diff
  - 事件 timeline
- [x] 增加 “本轮上下文” 折叠面板：
  - route
  - context sections
  - token estimate
  - omitted reason
  - tool schema digest
  - evidence references
- [x] `ToolMenuPicker` 增加：
  - 健康状态
  - 是否需要确认
  - 是否需要文件
  - 版本
  - 最近成功率
- [x] 增加保守的“自动选择相关工具”模式：
  - 最多 5 个
  - 基于名称、描述、material scope、输入 schema 做轻量匹配
  - 记录选中原因
  - 显式用户选择优先
- [x] 保持 320 / 768 / 1440 响应式验收。

**验收标准**

- 用户能直观看到回答使用的模型、证据、工具和失败原因。
- 参数确认前能看到模型原始提案。
- 模型不支持工具时不会误以为已经调用。
- 刷新后 UI 状态与事件流一致。

### Phase 6：配置目录、观测与验收

**目标**：让配置、文档、观测和回归测试形成闭环。

**预计工作量**：2–4 天

**建议 PR**：PR-08

- [x] 从 Pydantic schema 生成：
  - `docs/llm-provider-config-schema.md`
  - `docs/llm-provider-config-schema.json`
- [x] Admin LLM 配置页展示字段说明、类型、默认值和错误路径。
- [x] 新增 LUI 调用质量指标：
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
- [x] 增加回归测试矩阵（见 [research-engine-plan-08-regression-test-matrix.md](research-engine-plan-08-regression-test-matrix.md)）。
- [x] 更新 README、Plan 07 状态和本计划状态。

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

- [x] 字符串 model 配置兼容。
- [x] object model 配置解析。
- [x] per-model capabilities 独立生效。
- [x] 未配置能力的远端模型标记 `inferred`，不继承第一个模型能力。
- [ ] requested provider/model 只有一方时返回明确错误（代码已实现，缺专项测试）。
- [x] purpose route 与用户选择并存时 route reason 正确。
- [x] run 保存 requested 与 resolved route。
- [x] schema 转换覆盖 enum、min、max、pattern、default、required。
- [x] stable function name 不冲突。
- [x] malformed raw arguments 保留并可展示 parse error。
- [x] 模型无 tool calling 时不发起 provider 请求。
- [x] provider 鉴权、超时、模型不存在错误分类正确。
- [x] 多工具提案在未开启并行时被明确限制。
- [x] request manifest 记录所有 section 和 omitted reason。
- [x] assistant event seq 连续且不更新。
- [x] 事件重放不会降级 tool phase。
- [x] continuation 幂等。

### 7.2 前端测试

- [x] 默认模型选择优先级。
- [x] 用户手动选择不被模式切换覆盖（`llmModels.test.mjs` 覆盖手动选择保留纯函数，Playwright 覆盖模式切换后不覆盖）。
- [x] 历史会话恢复模型。
- [x] `tool_calling` 标签展示。
- [x] 模型无工具能力时 warning（`llmModels.test.mjs` 覆盖 `modelLacksToolCalling` 判定）。
- [x] event reducer 合并 route / context / tool / answer / final。
- [x] stale phase 防降级。
- [x] raw arguments 与 parse error 展示。
- [x] 320 / 768 / 1440 布局不溢出（Playwright 覆盖页面/body/模型选择器与工具 warning 边界）。
- [x] ToolMenuPicker 展示健康状态、确认、文件、版本和最近成功率。
- [x] 自动选择相关工具最多 5 个，显式用户选择优先，并记录/展示选中原因。

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

> 当前回归矩阵将部分纯函数单测计入 E2E，真实浏览器场景仍需在 PI Mock / 真实模型环境中跑通。场景 3、5、6、7、9 应作为后续必验项。

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

## 13. 评审结论与后续优化清单

### 13.1 结论

Plan 08 的核心链路已落地，2026-08-15 本地复核通过 64 个相关后端测试与前端 LLM/事件/工具菜单单测。但当前实现仍不应标记为完全完成，主要因为：

1. LLM request 生命周期事件已由 P08-F1 补全，`llm.request.started`、`llm.request.failed`、`llm.usage.recorded` 现已在 LLM client 边界统一落事件。
2. Phase 4 中的“上传附件转为受管 runtime asset”仍未实现。
3. 测试矩阵存在误勾选与错误归因，部分 E2E 实际只是纯函数单测。
4. Context Assembler 仍是 v1 预算方案，存在整体省略、粗 token 估算、native tool schema 未计入预算等限制。
5. 工具契约的类型推断、并行工具、续答重试/死信、质量指标口径和 Admin trace 仍需后续增强。

### 13.2 文档一致性修正

- 计划状态由“已完成”改为“主体已完成，待收尾”。
- Phase 3 事件类型按代码实际映射更新，原 3 个未落地项已由 P08-F1 补齐。
- 后端测试勾选按回归矩阵与本地测试结果更新，`requested provider/model 只有一方`保留为缺专项测试。
- 前端测试勾选按实际测试文件更新，`用户手动选择不覆盖`、`模型 warning`、`320/768/1440` 已由 P08-F9 补充纯函数与 Playwright 断言。
- 明确“malformed arguments 不再置空”应理解为：解析失败时保留 `raw_arguments` 与 `arguments_parse_error`，但当前 `normalize_provider_arguments` 仍以 `{}` 作为可解析参数，需在文案和后续契约中避免歧义。

### 13.3 后续优化清单

| ID | 类型 | 问题 | 建议 | 状态 |
|---|---|---|---|---|
| P08-F1 | 事件观测 | LLM 请求开始、失败与 usage 未统一落事件 | 在 ProviderGateway / LLM client 边界发出 `llm.request.started`、`llm.request.failed`、`llm.usage.recorded`，并关联 run/call | 已完成 |
| P08-F2 | 上下文预算 | section 只整体省略，native tools schema 未计入预算，token 估算粗糙 | 增加 section 内截断与优先级；manifest 记录 native tool schema token；token 估算按 provider/model 校准 | 已完成 |
| P08-F3 | 工具契约 | 类型仍由描述字符串推断，数组/对象约束不完整 | 增加显式字段类型或规范化输入 schema；支持 `minItems` / `maxItems`、嵌套对象等 | 已完成 |
| P08-F4 | 并行工具 | 已记录并行能力但执行层仍单工具 | 提供显式开关与最大并发，补多工具卡片、续答与失败回滚策略 | 已完成 |
| P08-F5 | 续答可靠性 | pending continuation 遇到活动 run 冲突时无退避、尝试计数或死信 | 增加 `continuation_attempts`、`next_retry_at` 与终态死信；修复旧数据 `context_manifest_digest` 回退语义 | 已完成 |
| P08-F6 | 质量指标 | 指标全量扫描、无时间窗口，部分口径不准 | 增加时间范围、聚合/缓存；细分 fallback 与 proposal validation 分母 | 已完成 |
| P08-F7 | 受管资产 | 上传附件仍走内存/临时文件 | 迁移到受管 runtime asset，限制大小、生命周期与清理策略 | 已完成 |
| P08-F8 | 回放深度 | 只有 manifest digest，无 sanitized prompt snapshot | 后续按需增加 TTL 快照或可恢复 prompt log，先明确脱敏边界 | 已完成 |
| P08-F9 | UI/测试 | 手动模型选择、响应式、真实 E2E 自动化不足 | 抽取纯函数/组件测试；用 Playwright 跑 320/768/1440 与关键 E2E | 已完成 |
| P08-F10 | 文档一致性 | 计划状态、测试矩阵、勾选项互相矛盾 | 按本评审修正；后续每个 PR 同步矩阵和状态 | 已完成（本次同步） |

> P08-F2–F8 已拆入独立收尾计划：[research-engine-plan-08-wrapup.md](research-engine-plan-08-wrapup.md)。

### 13.4 建议状态口径

- 代码：主体已完成。
- 计划：标记为“主体完成，待收尾”，收尾项以 P08-F1–F10 跟踪。
- 完成定义第 6 条在真实 E2E 未通过前不应完全勾选。

## 14. 状态记录

- 2026-08-15：创建工作计划，状态为待评审 / 未开始。计划基于当前 `develop` 基线和本地 DeepSeek Harness 参考源码整理。
- 2026-08-15：PR-01 已完成：per-model 能力配置、resolved route、`route.resolved` 事件、run requested/resolved 模型持久化、LUI 模型选择优先级与 `tool_calling` 可见性均已落地；相关后端测试、前端单测与前端构建通过。`tool_capability_override` 留待 PR-02 引入。
- 2026-08-15：PR-02 已完成：统一 Tool Contract Adapter、稳定 function name、完整 JSON Schema 约束、AgentTool 派生契约、raw arguments / parse error 持久化与展示、提案元数据、provider 错误分类、单工具提示词策略和 `tool_capability_override` 均已落地；相关后端测试、前端单测与前端构建通过。并行工具执行仍保持关闭，留待后续配置化开启。
- 2026-08-15：PR-03 已完成：Context Assembler v1、7 类内置上下文 section、保守 token 估算、section/总预算与 omitted reason、工具简短目录、tool proposal 与 final answer 统一上下文、request manifest v1、run manifest 持久化、assistant message route/context digest metadata 和 LUI 上下文存证标签均已落地；相关后端测试与前端单测通过。
- 2026-08-15：PR-04 阶段一已完成：`assistant_events` append-only 集合、run/call 双写与连续 seq、统一事件回放 fallback、旧数据幂等 backfill 脚本、route/request/tool catalog/schema/confirmed 等事件、run 与 call 关联以及前端 `assistantEvents` reducer 均已落地；相关后端 77 个 assistant 测试、前端 assistant 单测与构建通过。完整 LLM request 生命周期事件、admin trace 展示和 continuation scheduled 事件仍留在 PR-04 后续切片。
- 2026-08-15：PR-05 已完成：assistant 消息 meta 展示 provider/model、路由原因、能力、usage 与 context digest；模型 meta 支持点击查看 capability source、context window、tool protocol 与 fallback reason；所选模型无 `tool_calling` 且已选工具时提供 warning 与一键切换工具模型入口；工具卡片补齐提议模型、provider call id、function name、schema digest、raw arguments、parse error、模型/用户参数 diff 和事件 timeline；新增“本轮上下文”折叠面板，展示 route、context sections、token estimate、omitted reason、工具 schema digest 与证据引用；相关前端 `assistantUi`、assistant 事件/工具调用单测和 `npm run build` 通过。ToolMenuPicker 健康/版本/确认/文件/成功率增强及自动选择相关工具仍留给 PR-07。
- 2026-08-15：PR-06 已完成：`AssistantToolCall` 增加 `continuation_state`、`continuation_run_id`、`continuation_error` 与安全 `source_context`；工具提案持久化原用户消息、selected tools、mode、model request、context manifest digest 与 route snapshot；工具 completed/failed 后写入 `tool.continuation.scheduled` outbox 事件；assistant worker 扫描 pending continuation 调用并以 call id 幂等创建 continuation run；continuation 复用原用户消息和 source_context，最终 assistant 消息可追溯到 tool call；多工具结果与结构化失败信息已进入 `_continuation_messages()`，result summary/artifact refs 做字符预算截断；保留 daemon thread 兼容路径并新增 queued/running 孤儿对账。后端 assistant 相关 79 个测试、前端 assistant 单测及 `npm run build` 通过。
- 2026-08-15：PR-07 已完成：`AgentTool` 目录新增 `recent_success_rate` 与 `recent_run_count`，由最近 20 条 terminal AlgorithmRun 动态计算；`ToolMenuPicker` 展示健康状态、是否需要确认、是否需要文件、版本与最近成功率；新增保守“自动选择相关工具”模式，最多 5 个，基于名称、描述、material scope 与输入 schema 做轻量匹配，显式用户选择优先，自动选择原因进入 `selected_tool_reasons` 并在选中 chips 可见；新增 `assistantToolMenu` 与 `assistantToolAutoSelect` 纯函数及单测。后端 agent-tools/assistant 相关 24 个测试、前端新增工具菜单单测与 `npm run build` 通过。
- 2026-08-15：PR-08 已完成：新增 `LLMConfigSchemaData` 与 `llm_config_schema_service.py`，从 Pydantic schema 生成 `docs/llm-provider-config-schema.md/json`；新增 `GET /llm/config-schema` 供 Admin LLM 配置页展示字段说明、类型、默认值、约束与错误路径；`ToolServicesView` LLM 标签接入来源标注、配置字段目录与 LUI 调用质量面板；新增 `assistant_quality_service.py` 与 `GET /assistant/quality-metrics/summary`，聚合 route resolved rate、requested/resolved mismatch、tool-capable model usage、proposal/validation/failure、confirmation conversion、continuation success、context token distribution 与 event replay errors；新增 `scripts/generate_llm_config_schema.py`、后端配置/质量指标测试与 `doc/research-engine-plan-08-regression-test-matrix.md`。后端相关 53 个测试、前端 `test:llm-models` / `assistant-events` / `assistant-ui` 单测与 `npm run build` 通过。
- 2026-08-15：执行计划评审，修正文档状态、事件类型与测试勾选，新增第 13 节后续优化清单。结论：主体能力已完成，但 P08-F1–F10 仍需跟踪；本地复核 64 个相关后端测试与前端 LLM/事件/工具菜单单测通过，真实 E2E 待补。
- 2026-08-15：优先收尾 P08-F1 与 P08-F9。P08-F1：新增 `llm.request.started`、`llm.request.failed`、`llm.usage.recorded` 统一事件，在 `LLMModelService` 调用边界落库，并随 assistant run 观测作用域关联 `run_id` / `call_id`；新增 `backend/tests/test_assistant_llm_events.py`。P08-F9：抽取 `shouldKeepManualModelSelection`、`modelLacksToolCalling` 纯函数并接入 `DialogueView`，补充 `llmModels.test.mjs`；扩展 `e2e/dialogue_e2e.py` 覆盖手动模型选择后切换模式不覆盖、320/768/1440 模型选择器与 warning 边界。后端相关回归与前端相关单测、`npm run build` 通过。
- 2026-08-15：完成 P08-F2–F8 收尾。上下文装配器增加 section 内截断与 native tool schema token 预算；工具契约支持显式字段类型和数组/对象约束；并行工具调用通过环境变量配置并发上限并支持失败回滚；服务端续答增加退避、尝试计数和死信状态；质量指标增加时间窗口、缓存与细分分母；对话附件迁移到受管 runtime asset，具备 TTL 与清理策略；LLM client 边界增加脱敏 prompt snapshot。相关后端测试、前端单测、`npm run build` 与 `py_compile` 均通过，计划状态更新为已完成。
- 2026-08-18：补充 LUI 性能优化。SQLite 文档存储新增集合级读取与集合级事务改写，LUI 高频 run/event/tool/chat 查询与写入改为只触碰目标集合；历史会话摘要改为批量统计消息数，避免逐会话 count。前端进入历史/当前会话时先停止旧会话残留 SSE/轮询，再先渲染消息并滚动到底部，随后并行恢复控制状态、命令目录、run、trace 与统一回放；普通消息创建 run 后立即滚动并用后台请求刷新历史列表。重启脚本已覆盖 assistant worker，本地验证 5200/5201 与 worker 运行正常。相关后端 Assistant/AgentTool 回归 157 项、前端全部轻量测试与 `npm run build` 通过。
- 2026-08-18：继续 LUI 后续性能优化。补齐 command/runtime_asset/tool 删除等残余 SQLite 全库读写；新增 LUI 热路径 MongoDB 索引、轻量 run 状态/events 投影、按 chat 批量 usage 事件与 run/tool/事件批量读取；消除 list_messages 与 usage/trace 聚合的 N+1，优化 run/trace SSE 轮询不再每轮完整加载或投影；新增 `GET /assistant/traces/batch` 批量 Trace 恢复接口；修复 `stopStaleStreams` 的 run 键不匹配问题，为 `loadChat`/`loadChatRun`/`hydrateAssistantTraces` 增加会话切换过期请求丢弃，并对发送后的历史刷新做去抖。相关 Assistant 回归 156 项、前端全部轻量测试与 `npm run build` 通过。
