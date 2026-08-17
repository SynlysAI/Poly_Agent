# Plan 10：Slash Command、会话控制面与 Agent 控制体系工作计划

> **状态：PR-02 已完成，PR-03 待启动**
>
> 日期：2026-08-16
>
> 基线：Plan 09 完成后的 `develop` 提交 `21d407`
>
> 前置计划：[research-engine-plan-09-lui-execution-trace.md](research-engine-plan-09-lui-execution-trace.md)
>
> 启动条件：Plan 09 必须先完成实现、测试、E2E、文档复选框与状态记录更新；本计划不得与 Plan 09 并行实施。
>
> 评审结论：2026-08-17 确认 Plan 09 已完成并启动 PR-01。

## 1. 背景与目标

Plan 08 已完成 LUI 的模型路由可见性、上下文 manifest、统一事件流、工具提案与执行、服务端续答、工具健康度和质量指标。当前问题从“模型和工具调用是否可解释”进一步前移为“用户是否能显式发现和控制 Agent 的模式、目标、权限与能力”。

Plan 09 正在补齐 LUI Execution Trace 的原始事件、投影、API 与前端时间线。Slash Command 会引入 run 外的控制动作、权限决策、压缩、导出与反馈事件，必须等 Plan 09 的 Trace 事实源和投影验收稳定后再扩展，避免同时修改两套 Trace 语义。

本计划参考 DeepSeek Harness（以下简称 DSH）的用户命令注册表、输入触发流水线、Plan Mode、权限预设、压缩、导出与反馈设计，在 PolyAgent 现有 FastAPI + Mongo/SQLite + Vue 架构上实现 Slash Command 控制面。方案借 DSH 的架构不变量，不引入 Cordis / TypeScript runtime，不复制 DSH 代码；Trace 层复用 Plan 09 的 append-only 事件与投影服务，只做命令事件扩展。

### 1.1 产品目标

1. 用户在 `/dialogue` 输入 `/` 时立即看到命令面板。
2. 继续输入时实时过滤命令，支持鼠标点击、`↑` / `↓` 和 `Enter` 选择，`Esc` 关闭。
3. 每条命令展示名称、参数提示、描述、来源、可用状态与不可用原因。
4. 内置命令覆盖会话模式、长期目标、权限、模型、压缩、导出、反馈和状态查看。
5. 当前用户可用的算法工具自动派生为动态命令，选择后进入既有参数补充、确认、执行和结果展示链路。
6. Goal、Todo、Plan Mode、Permission Mode、Compaction 和模型选择随会话持久化，模型切换不丢失状态。
7. Slash Command 本身进入统一 Execution Trace，并与 run、tool call、permission decision、导出和反馈事件可回放关联。
8. 命令默认在用户命令平面直接执行，不进入模型历史；显式需要模型工作的命令（如 `/plan <message>`）必须单独声明模型可见输入。

### 1.2 非目标

本计划明确不做以下事项：

- 不与 Plan 09 并行实施；Plan 09 未完成前不启动本计划任何 PR。
- 不引入 Cordis、DSH 插件系统或 TypeScript runtime。
- 不重写 MongoDB 数据模型、现有 Assistant Run 或 AlgorithmRun 执行器。
- 不把 `/dialogue` 前端迁移为 agent harness UI。
- 不实现用户自定义命令编辑器或命令市场；仅预留 `custom` 分类和 provider seam。
- 不在本期实现 OS 级文件、Shell、网络、设备沙箱；权限命令只强制约束当前 LUI 控制面和算法工具执行边界。
- 不允许 slash 命令输出默认混入模型 prompt 或 KV cache。
- 不重建 Plan 09 的 AssistantTraceProjectionService，不创建第二套 Trace 事实日志。
- 不做 token 级完整回放和会话 fork。
- 不把 Plan Mode 声称为安全沙箱；它有后端工具执行门禁，但模型输出仍需遵循审计与验收。

### 1.3 核心决策

**命令是控制面，不是模型提示词。**

| 决策 | 含义 |
|---|---|
| Registry 后置 | 前端不硬编码命令逻辑，只消费 handler-free descriptor |
| 直接执行 | 已注册命令在后端命令平面执行，未知命令返回直接错误 |
| 原样参数 | 解析器只切分命令名与 raw input，各 handler 自行解析参数 |
| 生命周期成对 | 每次执行写 `command.run` 与 `command.done`，以 `command_id` 配对 |
| 状态持久 | Plan / Permission / Goal / Todo / Compaction 保存在会话控制状态 |
| 工具复用 | 动态命令复用现有 AssistantToolCall 参数、附件、确认和执行状态机 |
| 权限分层 | 会话 permission mode 是额外门禁，不覆盖平台 RBAC 与工具策略 |
| Trace 复用 | 命令事件镜像到 Plan 09 已验收的 `assistant_events`，通过 Trace 投影扩展回放 |

## 2. 参考材料

### 2.1 DSH 文档与源码

| 材料 | 借鉴点 |
|---|---|
| [用户命令子系统](../refer/deepseek-harness-master/docs/subsystems/commands.zh.md) | command definition、descriptor、invocation、result、`command/run` / `command.done` 生命周期 |
| [dsh-commands 源码](../refer/deepseek-harness-master/packages/interaction/commands/src/index.ts) | 名称规范、解析规则、注册表遮蔽、变更通知与未知命令处理 |
| [ui-input-trigger](../refer/deepseek-harness-master/packages/client/ui-input-trigger/README.zh.md) | `/` 触发检测、词边界、URL carve-out、候选菜单状态机 |
| [ui-commands](../refer/deepseek-harness-master/packages/client/ui-commands/README.zh.md) | handler-free 目录缓存、fuzzy discovery、命令弹窗与风险确认 |
| [Plan Mode](../refer/deepseek-harness-master/packages/plan/plan-mode/README.zh.md) | plan 状态事件、模型指引、`/plan` 与 `/plan off` 语义 |
| [权限预设](../refer/deepseek-harness-master/docs/subsystems/permission-presets.zh.md) | 预设只记录用户意图，实际执行由各强制点读取 |
| [User Approval](../refer/deepseek-harness-master/docs/subsystems/approval.zh.md) | 审批请求 / 结果事件配对与 fail closed 原则 |
| [command-compact](../refer/deepseek-harness-master/packages/compaction/command-compact/README.zh.md) | 手动压缩事务、busy / changed / summary / commit 错误边界 |
| [session-log-export](../refer/deepseek-harness-master/packages/session-query/session-log-export/README.zh.md) | 斜杠命令与 Header 操作共用下载控制器、流式 ZIP 边界 |
| [command-feedback](../refer/deepseek-harness-master/packages/feedback/command-feedback/README.zh.md) | 反馈权威事件与命令生命周期分离，避免重复记录正文 |

### 2.2 PolyAgent 当前基线

| 现有能力 | 相关位置 | Plan 09 复用方式 |
|---|---|---|
| 会话、消息、run 与工具调用 API | `backend/app/api/v1/endpoints/assistant.py` | 新增命令目录 / 执行 / Trace / 导出端点，不破坏旧路径 |
| 会话持久化与恢复 | `backend/app/services/assistant_chat_service.py` | 扩展控制状态字段并保持旧会话默认值兼容 |
| 模型路由与请求快照 | `backend/app/services/llm_model_service.py`、`assistant_run_service.py` | `/model` 只更新会话模型，不重置 run 与 trace |
| 上下文装配与 manifest | `backend/app/services/assistant_context_assembler.py` | 新增 session state 与 plan policy section |
| 工具目录与策略 | `backend/app/services/agent_tool_service.py` | 动态命令从当前用户可用 AgentTool 派生 |
| 工具参数 / 附件 / 确认 / 执行 | `backend/app/services/assistant_tool_service.py` | 动态命令直接创建 AssistantToolCall 并复用状态机 |
| 统一事件流 | `backend/app/infra/research_engine_repositories.py` | 命令事件镜像到 `assistant_events` chat scope |
| Execution Trace | Plan 09 的 AssistantTraceProjectionService、Trace API 与前端时间线 | 复用既有投影与 UI，仅扩展 command / permission / compact / export / feedback 事件 |
| 对话输入与工具 UI | `frontend/src/views/DialogueView.vue` | 在 composer 上方接入命令面板与状态标签 |

## 3. 当前问题盘点

### 3.1 输入入口与命令发现

| 问题 | 现状 | 影响 |
|---|---|---|
| 无 `/` 命令入口 | `DialogueView` 输入框只有普通 Enter 发送 | 用户无法发现系统能力与控制模式 |
| 无统一命令目录 | 前端没有 command catalog 缓存与过滤模型 | 新能力只能继续增加按钮或菜单 |
| 无键盘 / 指针混合交互 | 没有 command palette 状态机 | 无法满足快速选择和可访问性要求 |
| 无 IME 边界 | 当前 keydown 只区分 Enter + Shift | 中文输入法候选确认可能误发送 |
| 无未知命令策略 | 以 `/` 开头的文本会作为普通 prompt | 控制语义与模型语义混杂 |

### 3.2 会话控制状态

| 问题 | 现状 | 影响 |
|---|---|---|
| 无 Plan Mode | 模型没有稳定的只调查 / 只规划政策 | 用户无法显式禁止执行阶段动作 |
| 无 Session Goal | 会话只保存模型、模式、知识库和工具 | 复杂任务缺少长期方向锚点 |
| 无 Session Todo | Goal 与短期任务没有持久分离 | 后续任务容易偏离目标或重复判断 |
| 无 Permission Mode | 只有工具级 enabled / role / confirmation | 用户无法按会话切换只读或执行边界 |
| 无 Compaction Snapshot | 历史消息逐轮传入请求 | 长会话上下文膨胀且无法安全压缩 |
| 状态随前端散落 | 模型选择、工具选择、模式由页面状态维护 | 模型切换或恢复时容易缺少统一审计 |

### 3.3 能力注册与动态扩展

| 问题 | 现状 | 影响 |
|---|---|---|
| 算法工具已动态化 | AgentTool 根据注册表、版本、健康度和策略派生 | 具备动态命令基础 |
| 工具没有命令入口 | 用户只能通过工具菜单或模型提议调用 | 可发现性和确定性不足 |
| 无统一 provider seam | 内置命令、算法工具和未来 custom 命令缺少同一目录模型 | 新能力需要前端定制 |
| 无名称冲突策略 | 算法 ID 未映射为稳定命令 slug | 动态命令可能覆盖内置命令 |

### 3.4 权限、审批与 Trace

| 问题 | 现状 | 影响 |
|---|---|---|
| 工具策略已存在 | policy 控制 enabled、角色、owner、visibility、confirmation | 可作为权限基础 |
| 无会话级门禁 | read-only 需求无法作用于已有 tool call 确认 | 用户意图与执行边界不一致 |
| Permission decision 无独立事件 | 工具阶段事件不能区分策略拒绝、会话拒绝、计划模式拒绝 | 审计粒度不足 |
| Trace 以 run / call 为主 | 命令本身不在时间线 | 控制动作与后续执行无法串联 |

### 3.5 导出与反馈

| 问题 | 现状 | 影响 |
|---|---|---|
| 会话可通过 API 读取 | 消息、run、tool call 分散在多个资源 | 无法一键获得可审计包 |
| artifact 已有引用 | 工具调用保存 `artifact_refs` | 具备 ZIP 导出基础 |
| 无统一反馈模型 | 缺少与 route、版本、trace 关联的反馈记录 | 无法度量特定会话体验 |

## 4. 目标架构

```text
Frontend Dialogue composer
  │ slash detect + command palette
  ▼
Command Catalog API
  │ handler-free descriptors + session state
  ▼
AssistantCommandService
  │
  ├─ Command Parser
  │    ├─ command name normalize
  │    ├─ verbatim raw input
  │    └─ unknown command error
  │
  ├─ AssistantCommandRegistry
  │    ├─ builtin system commands
  │    ├─ agent / session commands
  │    ├─ AgentTool derived commands
  │    └─ custom provider seam
  │
  ├─ Command Permission Gate
  │    ├─ platform RBAC / ownership
  │    ├─ AgentTool policy
  │    ├─ session permission mode
  │    └─ plan mode hard gate
  │
  ├─ Command Handlers
  │    ├─ plan / goal / permission / model / status
  │    ├─ compact
  │    ├─ export / feedback
  │    ├─ reset / clear
  │    └─ dynamic tool invocation
  │
  ├─ Session Control State
  │    ├─ plan_mode
  │    ├─ permission_mode
  │    ├─ goal / todos
  │    └─ compaction snapshot
  │
  └─ AssistantCommandEventWriter
       ├─ assistant_command_runs
       ├─ assistant_events mirror
       ├─ permission.decision
       └─ Plan 09 Trace projection extension
```

### 4.1 Command Registry 契约

前端只消费以下 handler-free descriptor：

```text
name
title
description
usage
category: system | agent | skill | tool | custom
source
source_kind
enabled
available
unavailable_reason
input_mode: none | text | single_choice | tool_schema
argument_hint
variants
choices
tool_id
requires_confirmation
risk_level
```

约束：

- `name` 为小写 ASCII 字母、数字、`_`、`-`，以字母开头。
- `variants` 用于展示 `/plan` 与 `/plan off` 等参数形态，不重复注册处理器。
- `handler`、内部服务引用和 callable 不出现在 API 响应中。
- 内置命令拥有最高保留名；动态命令冲突时追加稳定短 hash，不得遮蔽内置命令。
- 动态命令来源必须能追溯到 `tool_id` / `algorithm_id` 和算法 attribution。

### 4.2 命令解析与执行生命周期

解析规则：

1. 仅当行首非空白字符为 `/` 时进入命令解析。
2. 命令 token 规范化为小写。
3. 名称后的所有内容作为 raw input 原样保留，包含分隔空白。
4. URL、路径和文本中间的 `/` 不触发命令面板或命令执行。
5. 未知命令写入命令失败闭环，但不创建模型 run，不作为 prompt 发送。

执行链：

```text
用户提交 slash line
  ↓
parse_command()
  ↓
registry.resolve()
  ↓
platform ownership / RBAC
  ↓
session permission gate
  ↓
handler
  ↓
command.done
  ↓
UI result / tool call / run / download
```

事件契约：

| 事件 | 时机 | 关键字段 |
|---|---|---|
| `command.run` | handler 执行前 | `command_id`、`name`、`raw_args`、`source`、`chat_id` |
| `command.done` | handler 结算后 | `command_id`、`status`、`message`、`source_event` |
| `permission.decision` | 会话 / 计划门禁判断后 | `command_id`、`decision`、`reason`、`mode` |
| `plan.mode.changed` | Plan Mode 写入后 | `active`、`actor` |
| `goal.changed` | Goal 写入后 | `goal_id`、`action`、objective digest |
| `permission.mode.changed` | Permission Mode 写入后 | `before`、`after` |
| `context.compacted` | 压缩提交后 | `snapshot_id`、cutoff、token estimate |
| `session.exported` | 导出开始 / 结束 | `format`、`status`、manifest digest |
| `feedback.recorded` | 反馈写入后 | `feedback_id`、rating、关联上下文 |

存储策略：

- 新增 `assistant_command_runs` 作为命令执行与 lifecycle 权威集合。
- 每个会话维护 `command_event_seq`，Mongo 使用原子 `$inc`，SQLite 使用现有事务。
- 每条命令事件同步镜像到 `assistant_events`，`run_id` 可为空、`chat_id` 必填。
- Trace 层不得新写第二套事实日志；命令事件进入 Plan 09 Trace 投影的标准映射。
- `command.run` 与 `command.done` 必须同 `command_id` 配对；失败、取消和交互等待也要闭环。
- `assistant_events` 旧 reducer 忽略未知事件，避免旧前端硬失败。

### 4.3 会话控制状态

`AssistantChat` 语义新增：

```text
plan_mode: boolean
permission_mode: read_only | workspace_write | full_access
goal: SessionGoal | null
todos: SessionTodo[]
compaction: CompactionSnapshot | null
command_event_seq: integer
```

默认值：

```text
plan_mode=false
permission_mode=workspace_write
goal=null
todos=[]
compaction=null
command_event_seq=0
```

旧会话不做数据迁移，读取时补默认值。写路径必须通过命令服务或专门的 control-state API，避免普通 chat PATCH 造成无事件状态变更。

### 4.4 权限矩阵

| 行为 | read_only | workspace_write | full_access | plan_mode |
|---|---|---|---|---|
| 查看命令目录与状态 | 允许 | 允许 | 允许 | 允许 |
| `/plan`、`/goal`、`/status` | 允许 | 允许 | 允许 | 允许 |
| `/model` | 允许 | 允许 | 允许 | 允许 |
| `/compact` | 允许 | 允许 | 允许 | 允许 |
| `/export`、`/feedback` | 允许 | 允许 | 允许 | 允许 |
| 动态工具命令创建 call | 阻止 | 受工具策略控制 | 受工具策略控制 | 阻止 |
| 已有工具 call 确认执行 | 阻止 | 受工具策略控制 | 受工具策略控制 | 阻止 |
| `/reset` | 允许 | 允许 | 允许 | 允许 |
| `/clear` | 允许 | 允许 | 允许 | 允许 |

说明：

- `read_only` 只描述 LUI 会话执行边界，内部会话状态写入仍允许。
- `full_access` 不 bypass 登录、RBAC、owner、visibility、工具策略或 `requires_confirmation`。
- `plan_mode` 下模型仍可提议工具，但确认阶段必须返回稳定错误 `plan_mode_blocked`。
- 所有阻断写 `permission.decision`，并与命令或 tool call 关联。
- 未来细粒度矩阵预留：文件读取、文件修改、Shell、网络、设备控制、实验执行；本期不声称这些 OS 级能力已强制。

### 4.5 模型上下文集成

- `AssistantContextAssembler` 新增 `session_state` section：
  - active goal
  - todo status
  - plan mode
  - permission mode
  - compaction summary digest
- Plan Mode 激活时新增 `plan_policy` section，明确：
  - 只调查、读取、分析和制定方案
  - 不修改文件、不删除数据、不改配置、不执行副作用操作
  - 输出计划并等待用户确认
- 命令目录、命令结果和直接 UI 输出不进入模型请求。
- `/plan <message>` 是唯一默认内置例外：启用 Plan Mode 后，将 `<message>` 作为显式模型输入创建 run。
- 动态工具命令 owned message 标记 `metadata.model_visible=false`，构建模型历史时过滤。

### 4.6 API 契约

#### 命令目录

```http
GET /assistant/commands?chat_id={chatId}
```

响应核心：

```json
{
  "items": [],
  "total": 0,
  "session_state": {},
  "catalog_version": ""
}
```

#### 命令执行

```http
POST /assistant/commands/execute
```

请求核心：

```json
{
  "chat_id": "chat_xxx",
  "line": "/plan",
  "payload": {}
}
```

响应核心：

```json
{
  "command_id": "cmd_xxx",
  "name": "plan",
  "status": "success",
  "message": "",
  "state_after": {},
  "interaction": null,
  "run": null,
  "tool_call": null,
  "download_url": null
}
```

#### Trace

```http
GET /assistant/chats/{chat_id}/trace?after_seq=0
```

该接口是 Plan 09 Trace API 的 chat-scope 扩展，返回统一排序的 command、run、tool call、permission、compaction、export、feedback 事件；不得绕过 Plan 09 投影直接拼接 UI 时间线。

#### Export

```http
GET /assistant/chats/{chat_id}/export?format=json|markdown|zip
```

导出必须校验会话 owner，并在 metadata 中记录 schema version、生成时间和数据清单。

## 5. 分阶段任务

### Phase 0 / PR-01：命令内核、会话状态与事件契约

**目标**：先建立可靠的后端命令平面，避免前端先行造成第二套控制语义。

**预计工作量**：2–3 天

- [x] 新增 `assistant_commands` schema：
  - `CommandDescriptor`
  - `CommandCatalogData`
  - `CommandExecuteRequest`
  - `CommandExecution`
  - `SessionGoal`
  - `SessionTodo`
  - `CompactionSnapshot`
- [x] 实现命令名解析、大小写规范化、raw input 保留和未知命令错误。
- [x] 新增 `AssistantCommandRegistry`，注册内置命令并保留动态 provider seam。
- [x] 新增 `AssistantCommandService`，统一执行解析、目录、权限、handler 和事件。
- [x] 新增 `AssistantCommandRunRepository`，支持 Mongo 与 SQLite 双模。
- [x] 为 `AssistantChat` 增加控制状态字段，读取旧数据时补默认值。
- [x] 实现会话级 `command_event_seq` 原子递增。
- [x] 实现 `command.run` / `command.done` 生命周期事件与 `assistant_events` 镜像。
- [x] 实现 `/plan`：
  - 裸 `/plan` 启用 Plan Mode
  - `/plan off` 退出
  - `/plan <message>` 启用后创建受计划政策约束的 run
- [x] 实现 `/goal`：
  - 裸命令查看当前目标
  - `/goal <objective>` 设置目标
  - `/goal clear` 清除 active goal
- [x] 实现 `/permission`：
  - 裸命令返回选项交互
  - `/permission read-only|workspace-write|full-access` 切换
- [x] 实现 `/model`：
  - 裸命令返回当前模型与可用选项
  - `/model <provider_id>::<model_id>` 切换并保留控制状态
- [x] 实现 `/status`，汇总模型、模式、目标、Todo、权限、active run、active tool call 和 trace 摘要。
- [x] 在 `AssistantContextAssembler` 中加入 session state 与 plan policy。
- [x] 在 `AssistantToolCallService.confirm()` 中接入 permission / plan gate。
- [x] 补充后端单元与 API 测试。

**验收标准**

- 命令目录、执行、解析、事件和状态 API 可用。
- 任意执行失败均能找到配对 `command.done`。
- 未知命令不创建 model run。
- 旧会话恢复后控制状态全部有默认值。
- `/model` 切换后 Goal、Todo、Trace、权限和已注册工具不丢失。
- read-only 与 plan mode 均能阻断工具确认执行。

### Phase 1 / PR-02：命令面板与前端控制面

**目标**：让命令系统成为用户可发现、可键盘操作、可恢复的 LUI 控制入口。

**预计工作量**：2–3 天

- [x] 新增 `frontend/src/utils/slashCommands.mjs` 纯函数模块：
  - 行首 slash 检测
  - 当前 token 提取
  - URL / 路径 carve-out
  - prefix 与 fuzzy 过滤
  - category 排序
  - variant 展开与合并
  - keyboard highlight 状态计算
- [x] 新增 `slashCommands.test.mjs` 覆盖纯函数。
- [x] 新增 `CommandPalette.vue`，挂载在 composer 输入框上方。
- [x] 支持 `/` 打开、输入实时过滤、空结果自动关闭。
- [x] 支持鼠标点击、`↑` / `↓` 循环高亮、`Enter` 选择、`Esc` 关闭。
- [x] 支持 IME composition 期间不触发 Enter 选择。
- [x] 支持展示：
  - 命令名
  - 参数提示
  - 描述
  - 分类
  - 来源
  - 可用状态
  - 不可用原因
  - 风险标识
- [x] 支持 `/plan` 与 `/plan off` variant 提示。
- [x] 命令目录加载、缓存、失败重试和 catalog version 失效刷新。
- [x] `DialogueView` 接入 `GET /assistant/commands` 与 `POST /assistant/commands/execute`。
- [x] 普通文本提交前先识别 slash；未知命令显示直接错误，不调用 run API。
- [x] 渲染命令结果行，支持成功、失败、交互、run 创建和 tool call 创建状态。
- [x] composer 顶部增加 Plan / Permission / Goal / Model 状态标签。
- [x] 会话加载时恢复控制状态并同步命令目录。
- [x] 补充前端单测与构建验证。

**验收标准**

- `/`、`/pl`、`/plan off` 的过滤结果符合预期。
- 鼠标与键盘路径都能选择同一命令。
- URL 和普通文本中的 `/` 不打开面板。
- 中文输入法候选确认不会误选择命令。
- 未知 slash 命令不会进入模型历史。
- 命令面板打开时不改变普通 textarea 焦点和已有发送行为。

### Phase 2 / PR-03：动态 Tool 命令与直接执行

**目标**：让当前用户可用的算法能力自动进入命令目录，并复用既有安全执行链路。

**预计工作量**：2–3 天

- [ ] 从 `AgentToolService.list_tools()` 派生动态 command descriptor。
- [ ] 按 `algorithm_family` / `tool_type` / `capability_group` 映射 `tool` 或 `skill` 分类。
- [ ] 实现 `algorithm_id → command slug` 稳定规范化：
  - 小写
  - 非法字符转 `-`
  - 收缩连续分隔符
  - 内置名冲突追加短 hash
- [ ] descriptor 携带 `tool_id`、`input_mode=tool_schema`、确认要求和算法 attribution 摘要。
- [ ] 选择动态命令后，前端打开基于 `input_json_schema` 的参数表单。
- [ ] 表单支持字符串、数字、布尔、枚举、数组、对象和必填标识。
- [ ] 文件输入复用 AssistantToolCall 附件上传。
- [ ] 后端命令 handler 创建 `AssistantToolCall`，并写入 `command_id` 关联。
- [ ] `AssistantToolCall` schema 与集合新增 `command_id`。
- [ ] 命令 owned message 增加：
  - `metadata.origin=slash_command`
  - `metadata.model_visible=false`
  - `metadata.command_id`
  - 可选 `metadata.task_content`
- [ ] 模型历史构建过滤 `metadata.model_visible=false`。
- [ ] 工具完成后的续答优先使用 `metadata.task_content`，没有任务说明则只展示结果，不自动编造续答目标。
- [ ] 动态命令执行前后保留算法 developer / framework / method attribution。
- [ ] 工具不可用、权限不足、schema 缺失、参数缺失和执行失败均返回可展示状态。
- [ ] 补充动态命令目录与执行测试。

**验收标准**

- 新增或启用算法工具后，刷新命令目录即可见，不需要修改前端代码。
- 动态命令创建的 call 与普通模型提议 call 走同一确认和执行状态机。
- `command_id` 能串联命令、tool call、run 和 trace。
- read-only / plan mode 阻断动态命令创建。
- 命令 owned message 不进入后续模型请求。
- 命令结果卡片继续展示算法来源标注。

### Phase 3 / PR-04：上下文压缩 `/compact`

**目标**：在不破坏任务状态和审计数据的前提下降低长会话上下文压力。

**预计工作量**：2 天

- [ ] 定义 `CompactionSnapshot`：
  - snapshot id
  - summary
  - cutoff message id
  - retained message ids
  - token estimate before / after
  - route
  - usage
  - created at / created by
  - digest
- [ ] `/compact` 仅在无 active run 时允许执行；有 active run 返回 busy。
- [ ] 使用辅助 LLM 请求生成摘要，purpose 使用独立 compact route。
- [ ] LLM 不可用或返回无效摘要时，使用确定性摘要兜底。
- [ ] 摘要必须保留：
  - 用户目标
  - active Goal
  - Todo 状态
  - 当前权限与模式
  - 已完成任务
  - 当前状态
  - 关键结论
  - 重要文件
  - 关键配置
  - 未完成任务
  - 活跃工具结果
- [ ] 摘要必须压缩：
  - 重复对话
  - 已解决的问题
  - 无关过程信息
  - 冗长工具返回
- [ ] 原始消息不删除、不改写。
- [ ] 后续 assistant run 由服务端按 snapshot 构建有效历史：
  - compaction summary
  - retained messages
  - cutoff 后消息
  - 活跃 tool result
- [ ] 前端请求消息只作为兼容输入，服务端以持久化消息和 snapshot 为准。
- [ ] 写入 `context.compacted` 事件并记录 token 收益。
- [ ] 压缩失败时不改变有效历史，并返回稳定错误。
- [ ] 补充压缩服务、run 请求构建和事件测试。

**验收标准**

- 压缩后刷新会话，Goal / Todo / 权限 / Plan / Trace 全部保留。
- 后续请求包含摘要和 cutoff 后消息，不包含被压缩的完整重复历史。
- 原始消息仍可通过导出和 Trace API 审计。
- active run 期间请求压缩返回 busy，不产生半提交 snapshot。

### Phase 4 / PR-05：导出 `/export` 与反馈 `/feedback`

**目标**：提供可审计的会话交付物，并让用户反馈能关联实际执行上下文。

**预计工作量**：2–3 天

- [ ] 新增会话导出服务，支持 `json`、`markdown`、`zip`。
- [ ] 导出数据包含：
  - session 与控制状态
  - messages
  - commands
  - assistant runs
  - assistant events / execution trace
  - tool calls
  - tool results
  - algorithm run 关联
  - artifact 引用
  - metadata
- [ ] ZIP 结构固定为：

```text
session.json
messages.json
commands.jsonl
execution_trace.jsonl
tool_calls.json
artifacts/
metadata.json
```

- [ ] JSON 导出为单个对象，Markdown 导出为人类可读报告。
- [ ] 本地受管 artifact 进入 ZIP，保留原文件名并处理重名。
- [ ] 无法读取或已过期的 artifact 不导致整个导出失败，写入 manifest 错误。
- [ ] `/export` 裸命令返回格式选择交互；带参数命令返回下载 URL。
- [ ] 前端通过浏览器下载，不在 JavaScript 中完整缓存 ZIP。
- [ ] 写入 `session.exported` 开始与结束事件。
- [ ] 新增反馈 schema 与集合：
  - rating: `helpful | not_helpful`
  - comment
  - chat id
  - command id / trace id
  - model route
  - agent version
  - created by / at
- [ ] `/feedback` 裸命令打开反馈对话框，提交后写权威 `feedback.recorded` 事件。
- [ ] 反馈正文只保存在权威反馈记录，`command.run` 不重复记录正文。
- [ ] 补充导出内容一致性、owner 校验、artifact 错误和反馈关联测试。

**验收标准**

- 三种格式的会话、消息、命令、Trace 和工具结果语义一致。
- ZIP 内核心文件齐全，artifact manifest 可解释。
- 非 owner 无法导出或反馈他人会话。
- 反馈能关联实际模型 route、Agent 版本和 trace。
- 反馈正文不会在命令事件中重复出现。

### Phase 5 / PR-06：基于 Plan 09 Trace 的统一回放、观测与收尾命令

**目标**：复用 Plan 09 已验收的 Trace 投影，把命令、模型、工具、权限、压缩、导出和反馈串成完整可回放控制链路。

**预计工作量**：2–3 天

- [ ] 回填 Plan 09 完成后的实际基线提交，并确认 Trace API / SSE 契约。
- [ ] 复用 Plan 09 AssistantTraceProjectionService，不新增第二套 Trace 聚合服务。
- [ ] 扩展 Plan 09 Trace API 支持 chat scope 与命令事件。
- [ ] 合并事件类型：
  - command lifecycle
  - run lifecycle
  - tool call lifecycle
  - permission decision
  - plan mode
  - goal / todo
  - compaction
  - export
  - feedback
- [ ] 提供连续 chat seq、稳定排序和 `after_seq` 游标。
- [ ] 前端新增 Trace 时间线，支持按类型过滤。
- [ ] `/plan → 调查 → 工具提议 → 权限阻断/确认 → 结果 → 导出` 可在同一时间线回放。
- [ ] 实现 `/reset`：
  - 退出 plan mode
  - permission mode 恢复 `workspace_write`
  - 清除 active goal
  - 清空 todo
  - 保留消息、run、tool call 和事件
  - 弹出确认，避免误操作
- [ ] 实现 `/clear`：
  - 创建或切换到新会话
  - 不删除旧会话数据
  - 旧会话仍可从历史恢复
- [ ] 增加质量指标：
  - command catalog latency
  - command execute success rate
  - unknown command rate
  - permission blocked rate
  - plan mode block rate
  - dynamic tool command conversion
  - compact token reduction
  - export success rate
  - feedback submission rate
- [ ] 指标接入现有 assistant quality summary，并支持时间窗口。
- [ ] 增加命令目录与 Trace 管理视图或折叠面板。
- [ ] 更新用户文档与来源标注说明。
- [ ] 补充端到端回放测试。

**验收标准**

- 每条命令都能从触发、权限判断、执行结果到后续 run / tool call 追踪。
- Trace 游标断线后可恢复且不丢事件。
- `/reset` 只重置控制状态，不破坏审计数据。
- `/clear` 不删除旧会话。
- 核心指标可在质量 API 中查询。

## 6. PR 拆分与依赖

| PR | 主题 | 依赖 | 可并行点 | 退出条件 |
|---|---|---|---|---|
| PR-01 | 命令内核、状态、事件、基础命令 | Plan 09 已完成 | 前端可先写 slash 纯函数测试 | 后端命令 API 与生命周期测试通过 |
| PR-02 | 命令面板与前端控制面 | PR-01 | 与 PR-03 schema 设计并行 | 面板交互和未知命令策略验收通过 |
| PR-03 | 动态 Tool 命令直接执行 | PR-01、PR-02 | 导出 / 反馈 schema 可并行设计 | 动态命令完整走工具状态机 |
| PR-04 | `/compact` | PR-01 | 可与 PR-05 并行 | 压缩后请求历史与状态恢复正确 |
| PR-05 | `/export`、`/feedback` | PR-01 | 可与 PR-04 并行 | 三种导出与反馈关联验收通过 |
| PR-06 | Trace、指标、`/reset`、`/clear` | PR-01–PR-05 | 指标口径可提前定义 | 全链路 Trace 与 E2E 通过 |

PR 拆分原则：

- Plan 09 状态仍为“进行中”时，本计划所有 PR 均不得开工。
- Plan 09 完成后，先回填本计划基线提交，再启动 PR-01。
- 每个 PR 保持现有 API 兼容，不要求一次性上线全部命令。
- PR-01 完成前不合并前端执行逻辑，避免绕过后端权限与事件。
- PR-03 完成前不把动态工具命令暴露为可用状态。
- PR-04 与 PR-05 可分支并行，但都必须基于 PR-01 事件契约。
- PR-06 统一收口指标与 Trace，不引入新的业务执行器。

## 7. 测试计划

### 7.1 后端单元与 API 测试

新增或扩展以下测试方向：

- 命令解析：
  - `/plan`
  - `/PLAN off`
  - `/plan 保留原样参数`
  - `/unknown`
  - `/`
  - 非 `/` 开头文本
- Registry：
  - 内置命令排序
  - 动态工具派生
  - 名称冲突
  - 工具不可用原因
  - 用户角色过滤
  - custom provider 不暴露 handler
- 生命周期：
  - `command.run` 先于 handler
  - `command.done` 必定落库
  - handler 抛错时 error 闭环
  - 交互等待时状态明确
  - chat seq 连续且并发不重复
  - `assistant_events` 镜像字段完整
- 会话状态：
  - 旧 chat 默认值
  - `/model` 后状态保留
  - 服务重启后状态恢复
  - control-state 不能通过普通 PATCH 无事件修改
- 权限：
  - read-only 阻断动态工具命令创建
  - read-only 阻断已有 call confirm
  - plan mode 阻断工具执行
  - full access 不 bypass RBAC / owner / policy
  - permission decision 事件可追溯
- 动态工具：
  - schema 字段校验
  - required 字段
  - enum / number / boolean / array / object
  - 文件输入
  - command_id 关联
  - `model_visible=false` 过滤
  - continuation 使用 task content
- 压缩：
  - active run busy
  - LLM 成功
  - LLM 失败 fallback
  - 原始消息不变
  - 后续请求使用 snapshot
  - 状态与工具结果保留
- 导出与反馈：
  - owner 校验
  - JSON / Markdown / ZIP 内容一致
  - artifact 缺失 manifest
  - 反馈关联 route / version / trace
  - 反馈正文不重复进入 command event

建议测试文件：

```text
backend/tests/test_assistant_commands_api.py
backend/tests/test_assistant_command_events.py
backend/tests/test_assistant_session_control.py
backend/tests/test_assistant_compaction.py
backend/tests/test_assistant_export.py
backend/tests/test_assistant_feedback.py
```

### 7.2 前端测试

新增纯函数测试：

```text
frontend/src/utils/slashCommands.test.mjs
frontend/src/utils/commandCatalog.test.mjs
```

覆盖：

- 行首 `/` 打开。
- `/pl` 过滤 plan。
- `/plan off` variant。
- fuzzy 命中与排序。
- 分组顺序 System → Agent → Skills → Tools → Custom。
- URL 和路径中的 `/` 不触发。
- keyboard highlight 循环。
- Enter / Esc 状态转换。
- IME composition 状态。
- unknown command 判定。
- 目录缓存失效与失败重试。

组件与页面验收：

- 面板定位不遮挡输入焦点。
- 鼠标与键盘选择一致。
- 状态标签随命令结果更新。
- 动态工具参数表单与既有工具卡片一致。
- 权限阻断后 UI 显示不可用或确认错误。

### 7.3 E2E 场景

1. 输入 `/`，键盘选择 `/plan`，确认状态标签变化，再执行 `/plan off`。
2. 执行 `/goal 构建材料实验智能体`，刷新页面后目标仍显示。
3. 执行 `/permission read-only`，选择动态工具命令，确认被阻断并写入 Trace。
4. 执行 `/model`，切换模型后继续提问，确认 Goal、Todo、Trace、工具和权限保留。
5. 选择动态工具命令，填写参数、上传文件、确认执行并查看结果与来源标注。
6. 执行 `/compact`，继续提问，确认任务状态未丢失且上下文 manifest 显示压缩摘要。
7. 执行 `/export zip`，检查 ZIP 核心文件与 artifact manifest。
8. 执行 `/feedback`，提交 helpful 与补充意见，确认反馈关联当前模型和 trace。
9. 执行 `/reset`，确认控制状态重置但历史会话仍可回放。
10. 执行 `/clear`，确认只进入新会话，旧会话仍在历史列表。

### 7.4 回归命令

后续实现每个 PR 至少运行：

```bash
cd backend
pytest tests/test_assistant_commands_api.py \
  tests/test_assistant_command_events.py \
  tests/test_assistant_chats_api.py \
  tests/test_assistant_runs_api.py \
  tests/test_assistant_tool_calls_api.py

python -m py_compile app/services/assistant_command_service.py \
  app/services/assistant_chat_service.py \
  app/services/assistant_tool_service.py
```

```bash
cd frontend
npm run test:assistant-events
npm run test:assistant-tool-calls
npm run build
```

PR-02 起：

```bash
cd frontend
node src/utils/slashCommands.test.mjs
node src/utils/commandCatalog.test.mjs
```

PR-06 完成后：

```bash
python e2e/dialogue_e2e.py
```

## 8. 兼容与迁移策略

| 范围 | 策略 |
|---|---|
| 旧会话 | 不迁移，读取时补默认控制状态 |
| 旧 API | 现有 chats / messages / runs / tool-calls 路径不变 |
| 旧前端 | 未知 command 事件被忽略，不阻塞既有 run 回放 |
| 工具调用 | 保留现有 policy、schema、确认、AlgorithmRun 与 continuation |
| 模型路由 | `/model` 只更新会话模型，不改变全局 routing 配置 |
| 命令事件 | 只新增集合、索引和事件类型，不改写旧事件 |
| 压缩 | 原始消息保留，snapshot 只影响后续有效请求历史 |
| 导出 | 只读导出，不修改会话和 artifact 状态 |
| 回滚 | 关闭命令目录开关或回滚 API，不影响普通对话与工具调用 |

迁移与索引要求：

- `assistant_command_runs.command_id` unique index。
- `assistant_command_runs(chat_id, created_by, created_at)` 查询索引。
- `assistant_events(chat_id, created_by, seq)` 继续复用。
- SQLite `COLLECTION_NAMES` 增加 `assistant_command_runs`。
- 所有新增字段均允许缺省，避免历史文档 Pydantic 校验失败。

## 9. 风险与规避

| 风险 | 影响 | 规避 |
|---|---|---|
| 命令服务与 run / tool 服务循环依赖 | 启动失败或测试难以隔离 | registry 只保存 descriptor，handler 通过延迟解析或显式依赖注入 |
| chat seq 并发冲突 | Trace 顺序不稳定 | Mongo 原子 `$inc`，SQLite `BEGIN IMMEDIATE`，失败重试 |
| 命令输出泄漏进模型历史 | token 浪费与语义污染 | command plane 独立；owned message 标记 `model_visible=false` 并在服务端过滤 |
| 权限被误解为 OS 沙箱 | 安全夸大 | UI 与文档明确只约束 LUI 控制面和算法工具执行 |
| plan mode 影响只靠 prompt | 用户预期落空 | prompt 指引 + tool confirm 后端硬门禁双保险 |
| 动态工具 schema 复杂 | 参数表单不可用 | 复用现有 input schema 归一化，未知类型降级为 JSON 编辑器 |
| 压缩丢失关键状态 | 后续任务失败 | snapshot 保留 Goal / Todo / active tool result，并有回归测试 |
| 导出过大或包含敏感内容 | 浏览器或存储压力 | ZIP 流式输出、artifact manifest、字段脱敏与 owner 校验 |
| IME Enter 误触发 | 中文输入体验差 | compositionstart / compositionend 状态进入纯函数测试 |
| 命令目录频繁刷新 | 前端抖动 | catalog version 缓存，工具 / 模型 / 权限变化时才失效 |
| 名称冲突遮蔽内置命令 | 控制面不可用 | 内置保留名最高优先，动态命令冲突追加 hash |
| 事件双写不一致 | Trace 缺口 | command run 权威集合 + 镜像对账脚本 / 测试 |

## 10. 观测指标

| 指标 | 口径 | 目标 |
|---|---|---|
| catalog latency | `GET /assistant/commands` P95 | 热缓存 < 100ms |
| command execute success | `command.done success / command.run` | ≥ 99% |
| unknown command rate | 未知命令 / 全部命令提交 | 持续下降 |
| palette conversion | 面板选择执行 / 面板打开 | 反映可发现性 |
| dynamic tool conversion | 动态命令创建 call / 目录选择 | 反映表单可用性 |
| permission blocked clarity | 阻断事件带 reason 的比例 | 100% |
| plan block accuracy | plan mode 阻断 / 应阻断确认 | 100% |
| compact token reduction | 压缩前后有效请求 token 差 | 长会话可观测下降 |
| compact state integrity | 压缩后状态恢复测试通过率 | 100% |
| export success | 成功下载 / 导出请求 | ≥ 99% |
| feedback linkage | 反馈带 chat / route / trace 比例 | 100% |
| event pairing | `command.done / command.run` | 100% |

日志与事件不得记录 API key、凭据、完整敏感反馈正文或未脱敏文件内容。

## 11. 第一周执行建议

**启动门槛**：仅在本节执行时 Plan 09 已完成、其复选框与状态记录已同步、验证命令全部通过。

### Day 1–2：PR-01 后端命令平面

- 回填 Plan 09 完成后的实际基线提交。
- 确认 Plan 09 Trace API、SSE 与事件映射契约。
- 确定最终 schema 和事件字段。
- 实现解析、registry、命令执行、命令事件和会话状态。
- 先交付 `/plan`、`/goal`、`/permission`、`/model`、`/status`。
- 补齐生命周期与旧会话兼容测试。

### Day 3：PR-02 前端面板

- 先完成 slash 纯函数和测试。
- 再接入 API 与 `CommandPalette`。
- 重点验收键盘、IME、URL carve-out 和未知命令策略。

### Day 4：PR-03 动态工具命令

- 完成动态 descriptor 派生和 slug 策略。
- 打通参数表单到 AssistantToolCall。
- 验证 command owned message 不进入模型历史。

### Day 5：集成与风险收口

- 跑完整后端 / 前端回归。
- 人工检查权限阻断和 Trace 事件。
- 冻结 PR-04–PR-06 接口口径，避免后续返工。

## 12. 完成定义

### 12.1 产品完成

- `/` 命令面板、实时过滤、键盘与鼠标选择可用。
- System / Agent / Skills / Tools 分类清晰，动态工具自动出现。
- Plan、Goal、Permission、Model、Compact、Export、Feedback、Status、Reset、Clear 语义稳定。
- 会话刷新和模型切换后控制状态不丢失。
- 命令结果与工具结果可视化，用户能知道当前模式、可用能力、阻断原因和执行结果。

### 12.2 工程完成

- Plan 09 已完成且其 Trace 投影、API、前端时间线和 E2E 验收全部通过。
- 本计划未引入第二套 Trace 事实源或投影服务。
- 后端命令、状态、事件、压缩、导出、反馈测试通过。
- 前端 slash 纯函数、目录、面板和工具命令测试通过。
- `npm run build` 与后端 `py_compile` 通过。
- E2E 覆盖核心命令链路。
- Mongo 与 SQLite 双模行为一致。
- Trace API 能完整回放命令到工具与 run 的链路。

### 12.3 安全与审计完成

- read-only 与 plan mode 的工具阻断有后端测试。
- full access 不 bypass 平台 RBAC 和工具策略。
- 所有 permission decision 有 reason 和关联对象。
- `command.run` / `command.done` 配对率 100%。
- 导出与反馈均校验 owner。
- 文档与 UI 不夸大 OS 级沙箱能力。

### 12.4 文档与来源完成

- 更新 `/dialogue` 用户指南和命令说明。
- 保持既有来源矩阵中 Open WebUI / DeepSeek Harness “参考架构、不复制代码”的口径。
- 动态工具命令继续展示算法 developer / framework / method attribution。
- 不新增无授权机构 Logo。
- 本工作计划中的后续实现每完成一项，必须同步更新对应复选框与状态记录。

## 13. 状态记录

- 2026-08-16：文档创建，并按项目排期调整为 Plan 10；待 Plan 09 完成后启动评审与实施。
- 2026-08-17：确认 Plan 09 已完成，回填基线提交 `21d407`，启动 PR-01 后端命令平面实施。
- 2026-08-17：PR-01 完成：新增命令 schema、解析器、注册表、执行服务、Mongo/SQLite 双模命令仓储、会话控制状态、命令生命周期事件镜像与命令 API；落地 `/plan`、`/goal`、`/permission`、`/model`、`/status`，接入上下文 session state / plan policy，并在工具确认阶段阻断 read-only 与 Plan Mode。PR-01 相关回归 59 项通过，assistant 后端全量回归 122 项通过。

- 2026-08-17：PR-02 完成：新增 slash 纯函数、命令目录缓存与 `CommandPalette`，接入命令目录 / 执行 API、IME 与键盘交互、URL / 路径 carve-out、未知命令直接失败闭环、命令结果行、Plan / Permission / Goal / Model 控制状态标签和会话恢复；命令结果不进入模型请求历史。后端指定回归 36 项通过，前端 assistant events / tool calls / slash commands / command catalog 测试与 `npm run build` 通过；真实浏览器冒烟覆盖 `/` 面板、`/pl` 过滤、URL 不触发、键盘选择、`/plan off`、未知命令且 0 次 run 请求。
