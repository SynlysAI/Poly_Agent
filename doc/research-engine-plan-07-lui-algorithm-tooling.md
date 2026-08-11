# Plan 07：PolyAgent 垂类算法工具化与 LUI 升级方案

> **状态：进行中** — 已完成“算法工具派生与策略”“工具调用状态机”“历史对话”“流式协议与模型编排”和“界面实现”主体；剩余响应式浏览器验证与收敛。
>
> 日期：2026-08-11
>
> 来源：方案草稿（参考 Open WebUI 的对话工作台与工具调用交互，仅作为产品交互与实现参考，不暗示代码归属）。

## Summary

参考 Open WebUI 的对话工作台与工具调用交互，将 `/dialogue` 升级为 PolyAgent 的主要 LUI 入口，提供：

- 将每个“已部署且已激活”的垂类算法自动注册为独立对话工具。
- 管理员按 `admin / user` 角色配置算法工具的启用和调用权限。
- 在对话中选择、调用算法，并可视化参数补全、确认、运行和结果。
- 按用户持久化历史对话，支持搜索、重命名、归档、删除和恢复。
- 保持现有 Element Plus 设计体系，采用历史侧栏、中央消息区和可折叠工具详情，不增加冗余页面装饰。

不预置知识库检索、任务查询、通用计算提交等对话工具。第一版工具来源仅为已经部署的垂类算法。

## Algorithm Tool Model

### 自动注册规则

不建立与算法注册表重复的工具定义。工具目录从 ResearchEngine 当前数据动态派生：

- 算法属于 `algorithm_family=vertical_prediction` 或 `capability_group=vertical_algorithm`。
- 算法注册状态为 `active`。
- 存在 `active_version_id`。
- 对应版本状态为 `active`，且运行时健康检查未标记为不可用。
- 本地算法包和远程接口算法统一生成工具，但继续使用各自现有运行适配器。

每个算法生成一个稳定工具标识：

```text
algorithm:{algorithm_id}
```

工具名称、描述、输入输出契约、文件要求和来源信息直接读取：

- `AlgorithmRegistryEntry.name`
- `description`
- `input_schema` / `output_schema`
- `input_assets` / `output_assets`
- `active_version_id` / `version`
- `developer_attribution`
- `framework_attributions`
- `method_attributions`

版本切换时工具 ID 不变，工具契约自动跟随新的 active 版本；冻结、下线或失去 active 版本后，工具立即从可调用目录移除，历史消息仍保留原始版本信息。

### 工具策略覆盖层

新增轻量策略集合，只保存算法工具管理信息，不复制算法 schema：

- `algorithm_id`
- `enabled`
- `allowed_roles`
- `requires_confirmation`
- `updated_by`
- `updated_at`

默认策略：

- 所有算法运行都会创建 `AlgorithmRun`，因此默认 `requires_confirmation=true`。
- 公开算法默认允许 `admin` 和 `user`。
- 私有算法只允许管理员和算法所有者；角色策略不能放宽现有 visibility/owner 权限。
- 最终可见性为：算法原有访问权限、部署状态、工具启用状态和角色白名单的交集。

## Backend Changes

### 当前代码实现（2026-08-11 基线）

以下后端能力已按本计划落地，配套测试位于 `backend/tests/`：

- `backend/app/services/agent_tool_service.py`：从 ResearchEngine 注册表动态派生算法工具目录，组合算法 visibility/owner、部署与 active 版本状态、工具策略进行授权；支持管理员注册表视图、策略更新与一致性检查。
- `backend/app/services/assistant_tool_service.py`：实现 `requested → awaiting_input → awaiting_confirmation → running → completed / failed / canceled` 状态机；确认后固定 active 版本并复用 `ResearchEngineService.create_algorithm_run` 执行；SSE 事件持久化到 `assistant_tool_calls`。
- `backend/app/services/assistant_chat_service.py` 与 `backend/app/api/v1/endpoints/assistant.py`：用户级会话/消息 CRUD、搜索、归档、所有权校验，工具调用按 `chat_id + created_by` 关联并在会话恢复时还原参数、实际版本、run ID、结果摘要与事件。
- 测试：`test_agent_tools_api.py`、`test_assistant_tool_calls_api.py`、`test_assistant_chats_api.py` 共 13 项，覆盖目录派生、策略、状态机幂等、越权隔离、SSE 重放与会话恢复。

### 工具目录与权限接口

新增接口：

- `GET /agent-tools`：返回当前用户可以在对话中调用的已部署算法工具。
- `GET /agent-tools/registry`：管理员查看所有已部署算法及工具策略。
- `PATCH /agent-tools/{algorithm_id}/policy`：管理员更新启用状态、允许角色和确认策略。
- `POST /agent-tools/sync`：管理员执行一致性检查；正常情况下查询时自动派生，无需手动同步。
- `POST /assistant/tool-calls`：创建 pending 算法调用并计算参数/附件缺口。
- `GET /assistant/tool-calls/{call_id}`：读取当前用户自己的调用状态。
- `PATCH /assistant/tool-calls/{call_id}/input`：补充或修正 JSON 参数和 artifact 引用。
- `POST /assistant/tool-calls/{call_id}/input:multipart`：补充算法声明的文件输入。
- `POST /assistant/tool-calls/{call_id}/confirm`：确认并执行待处理的算法调用。
- `POST /assistant/tool-calls/{call_id}/cancel`：取消待处理调用。
- `GET /assistant/tool-calls/{call_id}/events`：以 SSE 重放调用状态事件，用于断线恢复。

服务端必须在每次调用时重新检查：

- 当前用户角色、算法 visibility 和 owner。
- 算法及 active 版本状态。
- 当前工具策略。
- 输入参数和附件是否满足 active 版本契约。
- 确认记录是否属于当前用户及当前会话。

不能通过历史消息中保存的旧 schema 或旧权限绕过当前校验。

### 算法调用编排

扩展 AssistantService，允许模型根据已选择工具的 schema 生成算法调用：

1. 将当前用户授权且当前会话启用的算法 schema 转为模型 tool/function schema（暂存于 AssistantService，不写入持久化工具目录）。
2. 模型提出工具调用后，服务端创建 `pending` 调用记录并持久化。
3. SSE 发送 `tool_call` / `tool_input_required` 事件和参数摘要。
4. 用户在消息内确认或修改参数（复用 `PATCH /assistant/tool-calls/{call_id}/input` 与 `confirm` 接口）。
5. 后端通过现有 `ResearchEngineService.create_algorithm_run` 执行，并固定使用确认时的 active version。
6. 前端在调用完成后携带 `tool_call_ids` 重新发起流式对话；服务端把真实结果注入消息上下文。
7. 模型基于真实结果继续生成最终回答。

对于不支持原生 tool calling 的模型，保持普通问答能力，同时明确提示当前模型不能发起算法调用，不使用文本解析猜测工具参数。

模型编排的上下文约定（`AssistantChatRequest.context`）：

- `selected_tool_ids`：当前会话显式启用的算法工具，仅在非空时向模型暴露 function schema。
- `chat_id` / `message_id`：新建的算法调用需要关联的会话与用户消息。
- `tool_call_ids`：确认执行完成后携带的调用 ID 列表，服务端据此注入结果消息并继续生成。

### Schema 与附件处理

- JSON/标量输入从算法 `input_schema` 生成紧凑参数表单。
- 模型未能提供的必填字段通过 `tool_input_required` 事件交给用户补充。
- `input_assets` 生成对应附件槽位，复用现有 multipart AlgorithmRun 接口和上传大小限制。
- 提交前统一展示算法名称、版本、参数摘要和附件清单。
- 输出优先展示 `output_summary`；结构、谱图和文件通过现有 artifact 预览/下载接口打开。
- 参数、输出和错误日志按现有安全规则脱敏，禁止在对话历史保存密钥和内部路径。

### SSE 事件扩展

保留现有事件，并增加：

- `tool_call`：
  `call_id`、`tool_id`、`algorithm_id`、`algorithm_version_id`、`tool_name`、`phase`、`arguments`、`result_summary`、`artifact_refs`、`error`。
- `tool_input_required`：
  缺少字段、字段 schema、所需附件。
- `tool_call.phase`：
  `requested`、`awaiting_input`、`awaiting_confirmation`、`running`、`completed`、`failed`、`canceled`。

所有调用、确认、取消、成功和失败写入现有审计事件体系。

## Chat History

新增按用户隔离的会话仓储：

- `GET /assistant/chats?query=&archived=&page=&page_size=`
- `POST /assistant/chats`
- `GET /assistant/chats/{chat_id}`
- `PATCH /assistant/chats/{chat_id}`
- `DELETE /assistant/chats/{chat_id}`

会话保存：

- 标题、创建/更新时间、归档状态和所有者。
- 模型、模式、知识库、联网搜索和已选择算法工具。
- 用户消息、助手消息、引用、推理摘要。
- 算法工具调用状态、确认参数、实际运行版本、run ID、结果摘要和 artifact 引用。

标题默认取首条用户消息的确定性摘要，不额外调用模型。所有读取、修改和删除操作校验所有权，管理员不默认读取其他用户会话。

## LUI Changes

### 对话工作台

将 `/dialogue/:chatId?` 调整为三部分：

- 左侧历史栏：新建、搜索、最近对话、归档、重命名和删除。
- 中央消息区：消息、引用、算法调用过程和结果。
- 可折叠工具活动区：汇总当前会话调用过的算法、版本、运行状态和结果入口。

移动端历史栏和工具活动区改为抽屉，中央消息区始终保持主视图。

### 算法工具交互

输入区增加紧凑“算法工具”选择器：

- 只显示当前用户有权限的已部署算法。
- 支持按名称、材料范围和算法类型搜索。
- 默认不自动选中全部算法，用户显式启用当前会话需要的工具，避免向模型发送过多 schema。
- 当前选择随会话保存和恢复。

消息内算法调用卡片显示：

- 算法名称、active 版本和开发者来源。
- `等待补充参数 / 等待确认 / 运行中 / 已完成 / 失败 / 已取消`。
- 按 schema 生成的参数编辑与附件槽位。
- 确认执行、取消、失败后重试。
- 完成后的结果摘要、结构/谱图预览和 artifact 下载入口。

卡片默认折叠详细 JSON，只突出当前状态与可执行操作。

### 工具管理入口

在现有“工具服务”页增加“算法工具”标签：

- 管理员查看所有已部署垂类算法及工具状态。
- 配置允许角色、启用状态和是否要求确认。
- 查看 active 版本、运行时健康状态和输入输出摘要。
- 未部署、未激活、冻结或下线算法显示原因，但不能启用为工具。
- 非管理员只看到自己可调用的算法工具，不显示策略编辑控件。

工具来源展示复用算法现有 `AttributionBanner` / `AttributionBadges`。在归因源矩阵记录 Open WebUI 作为 LUI 产品交互与实现参考，不暗示代码归属。

## Ordered Delivery

1. **算法工具派生与策略（已完成）**
   - 建立工具策略集合和 active 垂类算法派生服务。
   - 实现角色、visibility、owner、部署状态的组合授权。
   - 覆盖激活、回滚、冻结和下线后的工具可用性。
   - 代码位置：`agent_tool_service.py`、`endpoints/agent_tools.py`、`test_agent_tools_api.py`。

2. **工具调用状态机（已完成）**
   - 实现 pending 调用、参数补充、确认、取消和执行。
   - 接入现有 JSON 与 multipart AlgorithmRun 运行链路。
   - 保存实际运行版本、run ID、结果摘要和 artifact 引用。
   - 代码位置：`assistant_tool_service.py`、`test_assistant_tool_calls_api.py`。

3. **历史对话（已完成）**
   - 实现用户级会话 CRUD、搜索、归档和自动保存。
   - 将工具调用状态完整纳入会话恢复。
   - 代码位置：`assistant_chat_service.py`、`endpoints/assistant.py`、`DialogueView.vue` 历史侧栏、`test_assistant_chats_api.py`。

4. **流式协议与模型编排（已完成）**
   - AssistantService 把已启用算法转为 function schema，支持原生 function calling、确认后继续生成以及不支持工具模型的兼容路径。
   - 对话流 SSE 输出 `tool_call` / `tool_input_required` 事件；前端 API 封装 `agent-tools` 与 `assistant/tool-calls` 接口并在 reducer 中处理。
   - 代码位置：`assistant_service.py` 工具编排、`llm_client.chat_message`、`test_assistant_tool_orchestration_api.py`。

5. **界面实现与收敛（主体完成，剩余浏览器验证）**
   - 历史栏、算法选择器、消息内调用卡片（参数编辑、附件上传、确认/取消/重试、结果与 artifact 入口）和“工具服务”页“算法工具”标签均已完成。
   - 待办：桌面与移动端浏览器验证，压缩无关装饰和常驻信息。

### 已实施内容（本轮迭代）

第四、五交付单元已按以下顺序落地：

1. AssistantService 增加工具编排路径：`selected_tool_ids` 非空时构造 function schema 并调用模型；返回 `tool_calls` 时创建持久化调用并输出 SSE 事件。
2. 前端 API 封装 `GET /agent-tools`、`POST/PATCH/GET /assistant/tool-calls`、multipart 上传、确认、取消与事件重放。
3. 对话工作台增加算法工具选择器（保存到会话 `selected_tool_ids`）、消息内调用卡片（参数编辑、附件上传、确认/取消/重试、结果摘要与 artifact 入口）以及 `tool_call` / `tool_input_required` 事件 reducer。
4. “工具服务”页新增“算法工具”标签：管理员查看策略并编辑启用/角色/确认策略，非管理员只读查看可调用工具。
5. 覆盖工具提议、确认后继续生成、不支持工具模型的兼容路径、前端 reducer 与构建验证测试（`test_assistant_tool_orchestration_api.py`、`assistantToolCalls.test.mjs`）。

### 下一步（收尾）

1. Playwright 验证算法选择、参数补充、确认、结果展示及 320px、768px、1440px 响应式布局。
2. 用支持 function calling 的真实模型做一次端到端人工验收：启用工具 → 模型提议 → 确认执行 → 结果注入续答。
3. 按验收结果压缩卡片/选择器中的常驻信息与无关装饰。

## Test Plan

- 已部署且 active 的垂类算法一一生成工具；未激活、冻结和下线算法不可调用。
- 激活新版本后工具 ID 不变，schema 和运行版本更新；历史调用仍显示原版本。
- 公开、私有、owner、admin/user 和策略白名单组合权限正确。
- 用户无法伪造 `algorithm_id`、`version_id` 或确认记录绕过授权。
- 必填参数、类型约束、附件缺失和文件大小限制均能在执行前阻止调用。
- 确认前不创建 AlgorithmRun；确认后只创建一次，重复确认保持幂等。
- SSE 能正确恢复 `awaiting_input`、`awaiting_confirmation`、`running`、`completed` 和 `failed` 状态。
- 历史搜索、恢复、重命名、归档和删除按用户隔离。
- `selected_tool_ids` 为空时模型不接收任何 function schema；非空时仅接收当前用户可调用的工具。
- 模型提出调用后服务端立即创建 `pending` 记录并持久化，SSE 输出 `tool_call` / `tool_input_required` 事件。
- 确认完成后携带 `tool_call_ids` 的续问请求能把真实 `AlgorithmRun` 结果注入模型上下文，模型基于结果生成最终回答。
- 不支持 function calling 的模型不产生调用，且流式回答明确提示当前模型不能发起算法调用。
- Playwright 验证算法选择、参数补充、确认、运行结果及 320px、768px、1440px 响应式布局。
- 后端目标测试、前端单元测试和 `npm run build` 全部通过。

## Assumptions

- “已部署垂类算法”以 active registry、active version 和可用 runtime 的组合状态为准。
- 本地算法包与已激活的远程接口算法都属于垂类算法工具来源。
- 第一版不支持手工录入独立工具、知识检索工具、任务查询工具、OpenAPI 或 MCP。
- 每次算法执行默认要求确认，管理员可在策略中调整，但服务端始终保留权限与 schema 校验。
- 原有垂类预测页面、算法部署流程和 AlgorithmRun API 保持兼容。

## 状态记录

- 2026-08-11：完成第二交付单元“工具调用状态机”。新增 `assistant_tool_calls` Mongo/demo-store 双模仓储和索引，提供 pending 调用创建、详情、参数/附件补充、确认、取消及 SSE 事件重放接口；状态覆盖 `requested`、`awaiting_input`、`awaiting_confirmation`、`running`、`completed`、`failed`、`canceled`。确认时重新校验当前用户权限、工具策略、算法状态和 active 版本，通过原子状态认领保证重复确认只执行一次，并委托现有 `ResearchEngineService.create_algorithm_run` 执行 JSON、artifact 引用或 multipart 输入。调用保存实际版本、run ID、结果摘要和公开 artifact 引用，事件与历史参数执行敏感字段脱敏，临时附件不暴露内部路径。新增后端状态机测试，覆盖参数补充、幂等确认、取消终态、策略变更、active 版本切换、multipart 透传和 SSE 状态事件。
- 2026-08-11：完成第一交付单元“算法工具派生与策略”。新增 `GET /agent-tools`、`GET /agent-tools/registry`、`PATCH /agent-tools/{algorithm_id}/policy` 和 `POST /agent-tools/sync`；工具目录从 active 垂类算法和 active 版本动态派生，策略保存于独立轻量集合，服务端执行角色、visibility、owner、部署状态、版本状态和运行时健康状态的交集校验。补充后端 API 测试，覆盖公开/私有算法、冻结版本、管理员策略更新和不可用算法启用保护。
- 2026-08-10：创建本计划文档，状态为**未开始**。上述接口、界面和验收项均未实施；待实施时按 Ordered Delivery 顺序推进，并同步更新归因源矩阵与文档地图。
