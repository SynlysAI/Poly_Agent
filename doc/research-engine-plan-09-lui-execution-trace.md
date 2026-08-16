# Plan 09：LUI Execution Trace 与可追溯执行增强

> 状态：已完成
>
> 日期：2026-08-16
>
> 基线：`develop` 分支提交 `476fb99`
>
> 前置文档：[Plan 08：LUI Runtime、上下文注入与工具调用增强](research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md)
>
> 参考实现：`refer/deepseek-harness-master/`

## 1. 背景与目标

Plan 08 已完成 LUI 的模型路由、上下文 manifest、统一事件日志、算法工具提案、参数确认、AlgorithmRun 执行、服务端续答和调用质量指标。当前主要缺口是：这些真实执行事实分散在 AssistantRun SSE、AssistantToolCall 状态、AlgorithmRun 和 continuation run 中，用户仍难以在一轮请求内连续看到“准备了什么上下文、调用了什么模型、为什么暂停、执行了什么工具、结果如何进入最终回答”。

### 1.1 产品目标

每轮用户请求在 `/dialogue` 中应能清楚回答：

1. 注入了哪些上下文，各自来源、用途、token 预算和省略原因。
2. 实际选择了哪个 provider / model，请求何时开始和结束。
3. 模型提出了哪些算法工具，参数摘要和 schema 版本是什么。
4. 哪些动作等待用户补充参数或确认，用户确认时改了什么。
5. AlgorithmRun 何时排队、运行、完成或失败。
6. 工具结果和 artifact 如何回到服务端续答。
7. 失败发生在模型、检索、参数、审批、算法执行还是续答阶段。
8. 整个请求共执行多少关键步骤、耗时多少、是否发生异常和恢复。

### 1.2 已锁定决策

- 第一版只覆盖现有 LUI 真实链路，不新增通用 Bash / Read / Edit 工具。
- 一条 Trace 以初始 `AssistantRun.run_id` 为 `trace_id`，串起工具确认、算法执行和服务端续答。
- Trace 展示在每轮助手消息内，运行中实时展开，完成后保留时间线和执行摘要。
- Trace 必须来自真实持久化事件；每个展示步骤都要能回溯到原始事件 ID。

### 1.3 DeepSeek Harness 参考结论

| DeepSeek Harness 设计 | Poly_Agent 借鉴方式 | 不移植内容 |
|---|---|---|
| append-only `SessionEvent` 是回放事实，UI 状态由投影生成 | 继续以 `assistant_events` 为事实源，Execution Trace 是确定性投影，不复制第二套事实日志 | 不替换为 Cordis Session，不重写 MongoDB 模型 |
| `turn/start → step/start → tool/call → tool/result → step/end → turn/end` 边界 | 以用户请求为 Trace root，以 `tool_proposal`、`approval/execution`、`final_answer` continuation 为逻辑 segment | 不引入新的 Agent loop 或插件运行时 |
| `tool/call` 在执行前落事件，并与 `tool/result` 通过 `callId` 配对 | 保持工具提案先落事件、确认后执行、结果再落事件的顺序，并验证配对完整性 | 不引入通用工具注册表 |
| `approval/asked` 与 `approval/decided` 审计配对、一次性授权 | 将 awaiting input/confirmation 与确认/取消映射为标准 Approval 步骤，并校验 pending 配对 | 不新增独立审批服务 |
| `sourceEventSeqs` 记录派生关系 | 每个 Trace step 携带 `source_event_refs`，可追溯到原始 event ID、run ID、call ID 和流内 seq | 不做 token 级完整会话 fork |
| Trajectory UI 使用稳定 key、分组折叠、有限摘要、未知耗时显示为未记录 | Trace 行使用稳定 `step_id`、分组展示、摘要限长、未知耗时不得伪造 | 第一版不做完整虚拟表格和复杂时间轴拖选 |
| Tool UI 区分调用参数、结果、错误和文件 diff | Trace 行区分参数摘要、结果摘要、错误首行和 artifact 详情 | 第一版没有通用文件编辑 diff |

### 1.4 非目标

- 不暴露模型完整 Chain of Thought。
- 不新增任意 shell、文件编辑或系统级工具。
- 不保存完整敏感 prompt 或凭据。
- 不迁移 Plan 08 已完成的 AlgorithmRun 执行器。
- 不新增管理端 Trace 列表页。
- 不做 token 级重放、fork、compaction。

## 2. 目标架构

```text
/dialogue 用户请求
  ↓
AssistantRunService 创建初始 run
  trace_id = 初始 run_id
  ↓
assistant_events append-only 原始事实
  ├─ run 状态与阶段
  ├─ 上下文 manifest
  ├─ LLM request / usage / failure
  ├─ 知识库与网页检索
  ├─ 算法工具提案与参数状态
  ├─ 审批确认与 AlgorithmRun 状态
  ├─ 受管资产与 artifact
  └─ continuation run 与最终回答
  ↓
AssistantTraceProjectionService
  ├─ 只读聚合原始事件
  ├─ 生成标准 Trace Step
  ├─ 计算状态、耗时、父子关系
  └─ 校验开始/结束配对
  ↓
Trace Snapshot API + Trace SSE
  ↓
/dialogue 消息内 Execution Trace Timeline
```

核心不变量：

1. 原始执行事实只写入 append-only 事件，Trace 不反向修改事实。
2. 每个 Trace step 至少引用一个真实 `source_event_refs`。
3. 后端历史快照与实时 SSE 使用同一个投影服务。
4. 前端只归并标准 Trace step，不再自行猜测后端执行细节。
5. 未知耗时显示“未记录”，不得用 0 冒充真实耗时。
6. `Think` 只来自对外安全的阶段行动摘要，不来自模型内部推理。

## 3. 数据契约

### 3.1 Trace 根对象

新增 Pydantic schema：

```text
AssistantTraceData
├─ trace_id: str
├─ chat_id: str
├─ user_message_id: str
├─ root_run_id: str
├─ status: planning | running | waiting_approval | recovering | completed | failed | canceled
├─ created_at / updated_at
├─ runs: [{run_id, request_kind, status, started_at, finished_at}]
├─ tool_calls: [{call_id, algorithm_id, tool_name, phase, run_id}]
├─ steps: list[AssistantTraceStep]
├─ summary: AssistantTraceSummary
├─ cursor: str
└─ replay_warnings: list[str]
```

### 3.2 标准 Trace Step

```json
{
  "trace_id": "初始 AssistantRun ID",
  "step_id": "稳定步骤ID",
  "timestamp": "ISO 8601 UTC 时间",
  "type": "context | think | tool_call | tool_result | read | write | edit | approval | error | final",
  "title": "步骤名称",
  "summary": "面向用户的简短自然语言说明",
  "tool_name": "",
  "tool_type": "llm | retrieval | algorithm | asset | file | other",
  "status": "running | success | failed | waiting",
  "duration_ms": 0,
  "details": {
    "duration_known": false,
    "source_event_refs": [
      {
        "stream": "assistant_event",
        "event_id": "asevt_xxx",
        "run_id": "asrun_xxx",
        "call_id": "",
        "seq": 12
      }
    ],
    "next_action": "等待用户确认后执行"
  },
  "parent_step_id": null
}
```

规则：

- `step_id` 确定生成：`context:{request_kind}`、`llm:{request_id}`、`retrieval:{source}:{query_digest}`、`tool:{call_id}`、`approval:{call_id}`、`result:{call_id}`、`asset:{asset_id}`、`continuation:{continuation_run_id}`、`error:{source_event_id}`、`final:{trace_id}`。
- 同一 `step_id` 的后续 Trace SSE 消息表示状态更新，前端按时间合并并保留最新状态。
- `duration_ms` 默认 0，但必须配合 `details.duration_known`；UI 对未知耗时显示“未记录”。
- `source_event_refs` 是展示步骤的合法性证明；没有原始事件引用的步骤不允许生成。

### 3.3 原始事件到 Trace 步骤映射

| 原始事件 / 状态 | 标准 Trace 步骤 |
|---|---|
| `run.created`、intent/facts 阶段状态 | `think`：识别请求范围、准备项目事实 |
| `context.assembly.started` → `context.assembled` / `request.header` | `context`：展示 section 来源、token 估算、digest、是否省略 |
| `route.resolved` | 更新对应 context/LLM step 的模型路由详情，并生成安全行动摘要 |
| `retrieval.started` → `evidence` | 知识库/网页检索的 `tool_call` 与 `tool_result` |
| `llm.request.started` → `llm.usage.recorded` | `tool_call`，`tool_type=llm` |
| `llm.request.failed` | `error`，并关闭对应 LLM step |
| `tool.catalog.resolved`、`tool.schema.rendered` | 工具目录和 schema 信息进入 context step 详情 |
| `tool.proposed` | `tool_call`，展示工具名、版本、参数摘要、schema digest |
| `tool.awaiting_input` / `tool.awaiting_confirmation` / 参数更新 | `approval`，状态 `waiting` |
| `tool.confirmed` | `approval`，状态 `success`，记录确认后的参数差异 |
| `tool.queued` / `tool.started` | 同一 `tool:{call_id}` 状态更新为 `running` |
| `tool.result` / `tool.failed` / `tool.canceled` | `tool_result`，失败或取消同时生成 `error` |
| `asset.uploaded`、artifact refs | `write`，仅当受管资产或 artifact 真实存在 |
| `tool.continuation.retry_scheduled` / `dead_letter` | `error`，状态 `running` 或 `failed`，摘要说明自动恢复 |
| `tool.continuation.run_created` | `think`：基于工具结果准备服务端续答 |
| 无工具 `assistant.finalized` 或 continuation `assistant.finalized` | `final` |
| 工具提案阶段的 `assistant.finalized` | 不映射为整个 Trace 的 Final，只表示提案完成并进入等待确认 |

### 3.4 状态机

```text
idle
↓
planning
↓
running
↔ waiting_approval
↓
running
↓
recovering（发生可重试异常时）
↓
running
↓
completed | failed | canceled
```

状态由真实对象推导：

- 存在 `awaiting_input` / `awaiting_confirmation` 且无活动 continuation：`waiting_approval`。
- 存在 queued/running AssistantRun 或 AlgorithmRun：`running`。
- 仅存在 continuation retry/dead letter 处理：`recovering`。
- 无工具链路：初始 AssistantRun 终态即 Trace 终态。
- 有工具链路：以服务端 continuation run 终态为准；工具失败后仍生成最终回答时，Trace 可为 `completed`，但摘要保留异常数。
- 用户取消工具且无续答：`canceled`。

### 3.5 执行摘要

```text
AssistantTraceSummary
├─ total_steps
├─ tool_calls
├─ llm_calls
├─ retrievals
├─ approvals
├─ file_reads / file_writes / file_edits
├─ artifacts
├─ errors
├─ recoveries
├─ replay_warnings
├─ duration_ms
└─ duration_known
```

- `duration_ms` 使用 Trace 首个原始事件到最后原始事件的 wall-clock 时间。
- 运行中不生成最终摘要；可显示已用时间。
- 不把并发步骤耗时相加冒充总耗时。

## 4. 后端实施计划

### Phase 1：Trace 身份与原始事件补齐

- [x] 新建 Plan 09 文档并登记任务清单
- [x] 增加 `trace_id` 贯穿链路
- [x] 统一事件携带 Trace 身份
- [x] 补齐真实边界事件
- [x] 事件写入校验

### Phase 2：Trace 投影服务

- [x] 新增 `AssistantTraceProjectionService`
- [x] 实现确定性排序
- [x] 实现步骤映射和父子关系
- [x] 实现配对校验
- [x] 历史兼容
- [x] 安全投影

### Phase 3：Trace API 与实时 SSE

- [x] 新增 Snapshot API
- [x] 新增 Trace SSE
- [x] SSE cursor
- [x] 保持既有接口兼容

## 5. 前端实施计划

### Phase 4：Trace 状态归并与 UI

- [x] 新增前端 API client
- [x] 新增纯函数 reducer
- [x] 新增 `ExecutionTraceTimeline` 组件
- [x] 参照 Trajectory UI 的安全显示规则
- [x] 分组展示
- [x] 接入现有 LUI 状态
- [x] 可访问性与响应式
- [x] 来源标注

## 6. 测试与验收

### 6.1 后端测试

新增：

- `backend/tests/test_assistant_trace_projection.py`
- `backend/tests/test_assistant_trace_api.py`

覆盖 Trace 身份继承、历史兼容、事件配对、状态机、摘要统计、owner 权限、SSE cursor、跨流排序、脱敏与未知耗时。

更新既有回归：

- `test_assistant_event_log.py`
- `test_assistant_runs_api.py`
- `test_assistant_tool_calls_api.py`
- `test_assistant_llm_events.py`
- `test_assistant_quality_metrics.py`

### 6.2 前端测试

新增：

- `frontend/src/utils/assistantTrace.test.mjs`

覆盖 snapshot + SSE 归并、状态更新、断线去重、父子层级、摘要统计、未知耗时、摘要截断、未知事件降级和安全显示。

更新：

- `assistantEvents.test.mjs`
- `assistantToolCalls.test.mjs`
- `assistantUi.test.mjs`

### 6.3 E2E 验收

扩展 `e2e/dialogue_e2e.py`，覆盖 mock 工具提案、参数确认、算法执行、服务端续答、实时 Trace、刷新恢复、断线重连、320/768/1440px 响应式和不暴露完整 Chain of Thought。

### 6.4 验证命令

```bash
python -m pytest backend/tests/test_assistant_trace_projection.py backend/tests/test_assistant_trace_api.py backend/tests/test_assistant_event_log.py backend/tests/test_assistant_runs_api.py backend/tests/test_assistant_tool_calls_api.py backend/tests/test_assistant_llm_events.py

npm --prefix frontend run test:assistant-trace
npm --prefix frontend run test:assistant-events
npm --prefix frontend run test:assistant-tool-calls
npm --prefix frontend run test:assistant-ui
npm --prefix frontend run build

make test-e2e
```

## 7. 兼容、风险与完成定义

### 7.1 兼容策略

- 所有 API 字段均为 additive。
- 旧客户端忽略 Trace 字段和新增接口。
- 旧会话通过 run/call 关系推导 Trace。
- 不修改既有 AssistantRun SSE 和工具调用 API 路径。
- 不做破坏性数据库迁移，仅新增索引和可空字段。

### 7.2 风险与规避

| 风险 | 影响 | 规避 |
|---|---|---|
| run、tool、continuation 事件序列不一致 | Trace 顺序漂移 | 跨流按时间排序，同流 seq 仅用于校验 |
| 事件重复写入 | UI 步骤重复 | 以 `step_id + source_event_refs` 去重 |
| 展示层诱导虚构步骤 | 违反真实执行原则 | 无 `source_event_refs` 的 step 不允许生成 |
| Trace SSE 长时间等待审批 | 连接被代理断开 | heartbeat + cursor 重连，任务执行不依赖 SSE |
| 敏感信息进入详情 | 安全风险 | 白名单投影、继承脱敏、详情限长 |
| 旧数据缺少开始事件 | 耗时不完整 | 显示“未记录”，记录 replay warning |
| 前端状态膨胀 | 长会话卡顿 | 每条消息只保存一个 Trace，详情懒展开，摘要限长 |

### 7.3 完成定义

- 现有 LUI 问答、算法工具、确认执行、服务端续答回归全部通过。
- 新增后端和前端测试通过。
- Playwright 完整链路和响应式验收通过。
- 每个展示步骤均可回溯到真实事件。
- 不暴露完整 Chain of Thought、完整 prompt、凭据或本地路径。
- Plan 09 文档复选框、状态记录和验证命令全部同步更新。

## 8. 状态记录

- 2026-08-16：创建计划并开始实施；已创建功能分支 `feature/plan09-execution-trace`。
- 2026-08-16：Phase 1–3 完成：Trace 身份贯穿、统一事件 trace_id、上下文/检索边界事件、投影服务、Snapshot API 与 Trace SSE 已落地；新增 7 个后端 Trace 测试，既有 assistant 相关 37 项回归通过。
- 2026-08-16：Phase 4 主体完成：前端 Trace API client、纯函数 reducer、消息内 Execution Trace Timeline、历史恢复与 SSE 重连状态归并已接入；assistant trace/events/tool-calls/ui 单测与前端构建通过。
- 2026-08-16：Phase 4 完成收尾：补齐 Execution Trace Timeline 的可访问性（`role=region`、`aria-busy`、`aria-live` 状态提示、焦点可见样式）与 320/768/1440px 响应式布局；修复快照投影 UTC 时间比较、工具续答 trace_id 继承、单 Trace 单消息承载，避免续答竞态和刷新后步骤重复。后端 38 项回归、前端 trace/events/tool-calls/ui 单测、前端构建与 `e2e/dialogue_e2e.py` 完整链路均通过。
- 2026-08-16：复核与补漏：修复 AssistantRun 统一事件 Mongo 投影未携带 `trace_id` 导致续答增量事件无法按根 Trace 查询的问题；修复 Trace SSE 对同一 `step_id` 只发首帧、后续状态更新被吞的问题；修复客户端创建续答且未传 `trace_id` 时无法从首个工具调用推导根 Trace 的问题；为续答上下文补齐 `context.assembly.started` 边界事件。同步新增 SSE 增量更新与续答 trace_id 继承回归测试，Plan 09 相关后端测试、前端单测、前端构建与 `e2e/dialogue_e2e.py` 完整链路均通过。
