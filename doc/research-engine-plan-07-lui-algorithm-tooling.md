# Plan 07：PolyAgent 垂类算法工具化与 LUI 升级方案

> **状态：已完成（验收与协议加固）** — 五个交付单元、真实模型/浏览器验收和一次 OpenAI 兼容工具调用协议复核均已完成。
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
- 测试：`test_agent_tools_api.py`、`test_assistant_tool_calls_api.py`、`test_assistant_chats_api.py`、`test_assistant_tool_orchestration_api.py` 共 18 项，覆盖目录派生、策略、状态机幂等、越权隔离、SSE 重放、会话恢复和工具调用协议续答。

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

输入区增加紧凑“工具”选择器（扳手图标，两级菜单：计算工具 / 垂类算法工具 / 其他；当前只有垂类算法工具可勾选，其余为占位）：

- 只显示当前用户有权限的已部署算法。
- 支持在分类内按名称、材料范围和算法类型搜索。
- 默认不自动选中全部算法，用户显式启用当前会话需要的工具，避免向模型发送过多 schema。
- 勾选仅作为当前会话草稿：不触发回答、不创建或修改历史会话；用户发送消息时才把 `selected_tool_ids` 写入会话，并在恢复会话时还原为草稿。

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

## 实现效果（产品用户视角）

本计划将原先偏单次问答的 `/dialogue` 升级为可持续使用的对话工作台。用户侧最明显的变化不是增加了一个算法入口，而是把“选择算法、补充参数、确认执行、查看结果、基于结果继续问答”纳入同一条可保存、可恢复的消息流。

### 1. 历史对话

原页面以当前一次问答为主，没有完整的会话列表和会话管理入口。升级后，桌面端在对话区左侧增加历史会话栏，提供：

- 新建会话、搜索会话，以及“最近 / 归档”切换。
- 点击会话恢复完整上下文；每条记录显示标题和消息数量。
- 通过会话操作菜单执行重命名、归档、取消归档和删除。
- 首条用户消息发送后才创建并保存会话；只调整模型、知识库、联网开关或勾选工具，不会产生空会话。
- 标题由首条用户消息确定性截取生成，不额外消耗一次模型调用。
- 恢复会话时同时还原模型、模式、知识库、联网搜索、已选择工具，以及工具调用的参数、状态、实际版本、run ID、结果摘要和 artifact 引用。
- 所有会话按用户隔离；管理员也不默认读取其他用户的会话。

这里的“恢复”指重新打开历史会话并恢复当时的对话和工具调用现场，也包括对归档会话取消归档；当前删除操作为不可恢复删除，界面会在删除前二次确认。

### 2. 对话渲染

普通用户/助手气泡、Markdown、引用、推理摘要和推荐问题继续保留。新增的主要渲染对象是消息内算法调用卡片：算法运行不再仅以模型文字描述呈现，而成为带状态和操作的结构化交互。

典型用户路径为：

```text
选择工具 → 描述需求 → 模型提出调用 → 补充参数/附件 → 用户确认 → 算法执行 → 展示结果 → 模型基于真实结果继续回答
```

调用卡片当前提供：

- 算法名称、实际版本和 `等待补充参数 / 等待确认 / 运行中 / 已完成 / 失败 / 已取消` 状态。
- JSON 参数编辑、参数更新和算法声明的附件上传槽位。
- 确认执行、取消，以及失败后的重新发起操作。
- 完成后的结果摘要和 artifact 下载入口。
- 确认执行完成后，自动携带真实工具结果继续生成助手回答，用户不需要手工复制算法结果重新提问。

这使执行权和生成权保持分离：模型负责根据用户问题提出工具调用，服务端负责校验权限和输入，用户负责最终确认，算法负责产生真实结果，模型只基于该结果继续解释。默认确认策略下，模型不能仅凭文本直接执行算法。

### 3. 角色、工具管理与工具调用

本计划没有用工具管理替换系统中的用户角色管理，而是在算法之上增加按角色控制的工具策略。角色在这里是工具可见性和调用权限的一项约束，不是新的用户分组体系。

管理员在“工具服务 → 算法工具”中完成管理：

- 查看所有已部署垂类算法的工具名称、稳定工具 ID、active 版本、健康状态、可用状态、输入输出摘要和归因信息。
- 配置工具是否启用、允许 `admin / user` 中的哪些角色调用，以及执行前是否要求确认。
- 查看未部署、未激活、冻结、下线或运行时异常的原因；处于不可用状态的算法不能强制启用为工具。
- 执行一致性检查，核对 ResearchEngine 注册状态与动态派生的工具目录。

普通用户看到的是调用入口而不是策略入口：

- 非管理员只看到自己当前可调用的算法，不显示启用、角色和确认策略编辑控件。
- 输入区工具按钮采用“计算工具 / 垂类算法工具 / 其他”两级菜单；当前仅垂类算法工具可选，其他分类为后续扩展占位。
- 工具默认不全选。用户需要显式勾选本会话希望模型使用的算法；已选工具以标签和数量角标反馈，可单独移除或全部清除。
- 勾选工具只是在当前草稿中向模型开放相应 schema，不会立即调用算法；发送消息后才保存到会话，并在下次打开时恢复。
- 真正的调用发生在对话消息中，而不是在“工具服务”管理页直接运行。模型不支持原生 function calling 时仍可普通问答，但不能发起算法调用。

工具最终是否可见、可调用，由算法原有 visibility/owner 权限、部署和 active 版本状态、运行时健康状态、工具启用状态及角色白名单共同决定。管理员配置角色白名单不能放宽私有算法或所有者权限；服务端也会在创建调用和确认执行时重新校验，历史会话中的旧权限不能用于绕过当前策略。

### 当前实现与原方案界面差异

以下能力在方案中有描述，但当前前端呈现与原设计存在差异，后续界面迭代应以此为基线，不将其误记为已经完整落地：

- 原方案将工作台描述为“左侧历史栏 + 中央消息区 + 可折叠工具活动区”三部分；当前模板实际为历史栏和中央消息区，工具状态集中在消息内调用卡片，没有独立的右侧工具活动区。
- 原方案要求移动端将历史栏和工具活动区改为抽屉；当前 `900px` 以下布局将历史栏放到主内容上方并限制为 `180px` 高，不是抽屉交互。
- 原方案描述按 schema 生成紧凑参数表单；当前调用卡使用 JSON 文本编辑器和附件上传槽位，尚未按字段类型渲染独立表单控件。
- 原方案描述调用卡展示开发者来源及结构/谱图预览；当前消息卡主要显示名称、版本、状态、JSON 结果和 artifact 下载。归因徽章已在“工具服务 → 算法工具”中展示，结构/谱图仍通过 artifact 入口处理，没有消息内专用预览组件。
- 原方案描述详细 JSON 默认折叠；当前待输入或待确认阶段的参数编辑区默认展开，完成后的运行结果默认折叠。

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

5. **界面实现与收敛（已完成）**
   - 历史栏、算法选择器、消息内调用卡片（参数编辑、附件上传、确认/取消/重试、结果与 artifact 入口）和“工具服务”页“算法工具”标签均已完成。
   - 已补充 Playwright 端到端脚本（`e2e/dialogue_e2e.py`）和 320px / 768px / 1440px 响应式验收，`make test-e2e` 可重复执行。
   - 320px 下算法工具选择器固定 340px 导致横向溢出，已通过全局 `max-width: min(340px, calc(100vw - 20px))` 收敛。

### 已实施内容（本轮迭代）

第四、五交付单元已按以下顺序落地：

1. AssistantService 增加工具编排路径：`selected_tool_ids` 非空时构造 function schema 并调用模型；返回 `tool_calls` 时创建持久化调用并输出 SSE 事件。
2. 前端 API 封装 `GET /agent-tools`、`POST/PATCH/GET /assistant/tool-calls`、multipart 上传、确认、取消与事件重放。
3. 对话工作台增加算法工具选择器（保存到会话 `selected_tool_ids`）、消息内调用卡片（参数编辑、附件上传、确认/取消/重试、结果摘要与 artifact 入口）以及 `tool_call` / `tool_input_required` 事件 reducer。
4. “工具服务”页新增“算法工具”标签：管理员查看策略并编辑启用/角色/确认策略，非管理员只读查看可调用工具。
5. 覆盖工具提议、确认后继续生成、不支持工具模型的兼容路径、前端 reducer 与构建验证测试（`test_assistant_tool_orchestration_api.py`、`assistantToolCalls.test.mjs`）。
6. 协议复核补充持久化模型原始 `provider_tool_call_id`，续答时按 OpenAI 兼容格式复用该 ID；多工具结果合并到同一 assistant tool-call 消息，旧调用无该字段时兼容回退本地 `call_id`。
7. E2E 脚本支持 `POLY_AGENT_BACKEND_URL`、`POLY_AGENT_FRONTEND_URL`、`POLY_AGENT_PI_MOCK_URL`，文档与脚本行为一致。

### 最终验收（本轮完成）

1. 用支持 function calling 的真实模型（`deepseek-v4-flash`，OpenAI 兼容网关）完成端到端验收：
   - 选择 `algorithm:pi_synthesis_mock_v2` 后，模型自动提议 `{"diamine":"ODA","dianhydride":"PMDA","solvent":"NMP","water_content_status":"dry"}`。
   - 服务端持久化 pending 调用并输出 `tool_call`（`requested` → `awaiting_confirmation`）。
   - 用户确认后 `AlgorithmRun` 真实执行完成，返回 `difficulty_score=76` 与完整评分明细。
   - 携带 `tool_call_ids` 续问时，模型基于真实结果生成含 76 分、风险标签和推荐工艺参数的回答。
2. Playwright 浏览器验收通过：
   - 1440px 完整交互流：选工具 → 模型提议 → 卡片确认 → 结果续答。
   - 320px / 768px / 1440px 均无整页横向溢出；窄屏下历史栏置于主内容上方并限制高度，算法工具选择器不超出视口。
   - 截图输出至 `e2e/screenshots/`，脚本已接入 `make test-e2e`。
3. 回归结果：后端目标测试 18 passed，前端 `test:assistant-tool-calls`、`test:tool-menu-categories` 与 `npm run build` 全部通过。
4. 已知环境问题（不影响本计划验收）：`PI_Tg_predictor` 本地算法包的 `storage_uri` 仍指向旧工作区路径，直接确认执行会因包目录缺失失败；本轮验收改用已验证的 PI 合成难度评分 Mock 接口（`services/pi_algo_test`，8300 端口）。

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
- 续答构造的 assistant/tool 消息复用模型原始 `provider_tool_call_id`；历史调用缺失该字段时回退本地 `call_id`，并支持同一轮多个工具结果。
- Playwright 验证算法选择、参数补充、确认、运行结果及 320px、768px、1440px 响应式布局（已通过，`make test-e2e`）。
- 后端目标测试、前端单元测试和 `npm run build` 全部通过（18 passed + 前端单测 + 构建通过）。

## Assumptions

- “已部署垂类算法”以 active registry、active version 和可用 runtime 的组合状态为准。
- 本地算法包与已激活的远程接口算法都属于垂类算法工具来源。
- 第一版不支持手工录入独立工具、知识检索工具、任务查询工具、OpenAPI 或 MCP。
- 每次算法执行默认要求确认，管理员可在策略中调整，但服务端始终保留权限与 schema 校验。
- 原有垂类预测页面、算法部署流程和 AlgorithmRun API 保持兼容。

## 状态记录

- 2026-08-11：完成收尾验收与协议加固。真实模型端到端走通“选择工具 → 模型提议 → 用户确认 → AlgorithmRun 执行 → 结果注入续答”；补充 `provider_tool_call_id` 持久化与严格 OpenAI 兼容续答格式，新增回归测试；`e2e/dialogue_e2e.py` 支持三项 URL 环境变量覆盖。`make test-e2e` 可执行 1440px 完整流程和 320/768/1440px 响应式断言；后端相关测试 18 passed，前端单测与 `npm run build` 通过，计划整体完成。
- 2026-08-11：本次复核在 `poly_agent` 环境中重新通过目标后端 18 项、前端工具单测和构建；当前环境的 PI Mock `/healthz` 返回 502，因此 `make test-e2e` 未进入浏览器断言；完整 `backend/tests` 因既有外部服务测试长时间等待后手动中断，不能作为本轮通过项。
- 2026-08-11：完成第二交付单元“工具调用状态机”。新增 `assistant_tool_calls` Mongo/demo-store 双模仓储和索引，提供 pending 调用创建、详情、参数/附件补充、确认、取消及 SSE 事件重放接口；状态覆盖 `requested`、`awaiting_input`、`awaiting_confirmation`、`running`、`completed`、`failed`、`canceled`。确认时重新校验当前用户权限、工具策略、算法状态和 active 版本，通过原子状态认领保证重复确认只执行一次，并委托现有 `ResearchEngineService.create_algorithm_run` 执行 JSON、artifact 引用或 multipart 输入。调用保存实际版本、run ID、结果摘要和公开 artifact 引用，事件与历史参数执行敏感字段脱敏，临时附件不暴露内部路径。新增后端状态机测试，覆盖参数补充、幂等确认、取消终态、策略变更、active 版本切换、multipart 透传和 SSE 状态事件。
- 2026-08-11：完成第一交付单元“算法工具派生与策略”。新增 `GET /agent-tools`、`GET /agent-tools/registry`、`PATCH /agent-tools/{algorithm_id}/policy` 和 `POST /agent-tools/sync`；工具目录从 active 垂类算法和 active 版本动态派生，策略保存于独立轻量集合，服务端执行角色、visibility、owner、部署状态、版本状态和运行时健康状态的交集校验。补充后端 API 测试，覆盖公开/私有算法、冻结版本、管理员策略更新和不可用算法启用保护。
- 2026-08-10：创建本计划文档，状态为**未开始**。上述接口、界面和验收项均未实施；待实施时按 Ordered Delivery 顺序推进，并同步更新归因源矩阵与文档地图。
