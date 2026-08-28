# Plan 16：Agent 能力中心与权限治理工作计划

> 状态：已完成 / 全量验证通过
>
> 日期：2026-08-28
>
> 评审基线：`develop` 分支提交 `bac4d3b`。
>
> 前置文档：
> - [research-engine-plan-15-agent-exec-provider-seam-workplan.md](research-engine-plan-15-agent-exec-provider-seam-workplan.md)
> - [research-engine-plan-10-slash-command-and-agent-control-workplan.md](research-engine-plan-10-slash-command-and-agent-control-workplan.md)
> - [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md)
>
> 拆分说明：本计划从 Plan 15 修订拆分而来。Plan 15 只交付受控外部 Agent 的执行安全内核与连接器管理 API；全局“能力目录 + Skill 边界 + 用户与邀请码治理”归入本计划，避免演变为插件市场，也避免与 Plan 15 的安全内核耦合。
>
> 2026-08-28 复核结论：Plan 15 P15-A–P15-G 已落地并通过专项测试，`/tools` 已有 6 个 tab 且已包含 Agent 连接器配置面；本计划不能再把 agent_exec 视为“待接入能力”。Plan 15 P15-H 的生产化缺口继续留在 Plan 15，不并入本计划。
>
> 本轮执行约束：仅修订本文档，不修改后端代码、前端代码、测试代码或配置文件；文档修订单独提交。后续实现必须按第 8 节阶段推进，每完成一个阶段同步更新复选框和状态记录，并创建独立提交。

## 1. 摘要

PolyAgent 的可调用能力目前分散在多个模块：外部服务集成、算法工具、报告 Skill pipeline、LLM Provider，以及 Plan 15 已落地的受控外部 Agent 连接器。它们的事实源已经存在，但入口定位混杂：管理员在 `/tools` 中既配置服务，也查看连接器 readiness；普通用户缺少一个回答“agent 现在能调哪些能力、能否直接调用、调用前需要什么确认”的独立目录。

本计划保持两个入口职责分离：

- **工具服务 `/tools`（配置中心）**：面向管理员，负责配置、启停、策略修改和受控测试；保留现有 6 个 tab：状态、算法清单、算法工具、Agent 连接器、配置、LLM 模型。
- **能力中心 `/capabilities`（新建调用目录）**：面向管理员和普通用户，只读聚合各模块 readiness、准入策略、调用方式与来源；可跳转或发起既有模块调用，不提供配置表单。

核心原则：**配置面与调用面分离，数据单向流动**。`/tools` 和各模块服务端配置产出能力；`/capabilities` 只读消费能力状态，不新建第二套 provider、tool、skill、policy 或 trace 事实源，也不反向修改配置。

权限治理保持 `/admin` 独立。后端用户与邀请码 API 已存在，本计划补齐前端管理界面；外部 Agent 连接器默认仍 admin-only，管理员显式把 `user` 加入策略后，普通用户才可见并可在强制确认后调用。

```text
/tools（配置中心）              /capabilities（能力中心）
  配置 LLM provider       →      展示 LLM 模型能力
  配置外部集成            →      展示服务可用性
  配置算法工具注册与策略  →      展示对话工具可调用性
  配置连接器策略/sandbox  →      展示连接器 readiness 与准入
  服务端报告 Skill 配置   →      展示服务端 pipeline allowlist
                 ↓
        GET /capabilities/catalog 只读聚合
```

## 2. 目标与非目标

### 2.1 目标

- 新建 `/capabilities` 独立路由与 `CapabilityCenterView.vue`，按 agent 调用语义展示总览、对话工具、外部 Agent 连接器、报告 Skill、LLM 能力与权限摘要。
- `/tools` 保持现有 6 个 tab 和旧链接兼容，定位收窄为管理员配置中心；页面顶部引导能力可用性前往 `/capabilities`。
- 新增 `GET /capabilities/catalog` 只读聚合契约，返回 `dialogue_tools`、`agent_connectors`、`report_skills`、`llm_capabilities` 四个分组。
- 能力卡片展示名称、readiness、不可用原因、准入策略摘要、调用方式、配置跳转和来源牌。
- 管理员可见全部能力及不可用原因；普通用户只可见策略允许且可调用的能力。
- 外部 Agent 连接器按用户决策开放策略允许的普通用户调用：
  - 默认策略仍为关闭且 admin-only，升级后普通用户默认看不到连接器。
  - 管理员显式启用 provider 并把 `user` 加入 `allowed_roles` 后，普通用户可见。
  - 普通用户调用必须显式确认，即使策略将 `requires_confirmation` 设为 false。
  - provider、task type、readiness、输入输出边界、审计和 trace 仍由 Plan 15 安全内核执行。
- Skill 目录只展示服务端 report skill pipeline 与 allowlist，不扫描本地 `.codex/skills`。
- 在 `/admin` 增加“用户与邀请码”管理区，复用既有 API；用户列表补充创建、更新和最近登录时间字段。
- 来源标注覆盖算法工具、Codex 连接器、报告 Skill provider、OpenAI-compatible、Ollama 和 Custom HTTP provider。

### 2.2 非目标

- 不把 `/capabilities` 做成 `/tools` 的第二套配置面，不内嵌 provider、工具或连接器配置表单。
- 不提供统一配置写代理；能力中心只跳转原模块或调用原模块 API。
- 不新建第二套 provider、tool、skill、policy、run 或 trace 事实源。
- 不扫描本地 `.codex/skills`、不上传任意 `SKILL.md`、不做插件市场。
- 不实现浏览器连接器、任意 OAuth 连接器安装、本地 Skill 动态加载或 Skill 版本市场。
- 不做项目级 RBAC、用户级授权矩阵或角色随意变更；MVP 继续使用 `admin / user` 两角色。
- 不把权限管理并入能力中心或工具服务；`/admin` 保持独立。
- 不在本计划内解决 Plan 15 P15-H 的生产化收口问题，包括并发配额、多实例部署、TOCTOU 加固、审计失败降级和 Mongo 索引接线。

## 3. 当前基线

| 能力 | 当前状态 | Plan 16 差距 |
| --- | --- | --- |
| 工具服务 `/tools` | `ToolServicesView.vue` 已有 6 个 tab：状态、算法清单、算法工具、Agent 连接器、配置、LLM 模型 | 路由尚未显式 admin-only；缺少能力中心引导；配置与能力发现职责仍易混淆 |
| 外部服务集成 | `integrations` 相关 API、readiness 和配置服务已存在 | 仅作为配置与状态事实源，能力中心需只读消费 |
| 算法工具 | `agent-tools` API、`AgentToolService`、前端策略配置和纯函数测试已存在 | 缺少面向 agent 调用的统一能力卡片目录 |
| 报告 Skill | `ReportSkillOrchestrator`、服务端 pipeline、`SUPPORTED_PIPELINES` 与 allowlist 校验已存在 | 缺少服务端 pipeline 目录卡片；不能引入本地 Skill 扫描 |
| LLM Provider | `/llm/models` 返回脱敏 provider、模型、能力与路由信息 | 缺少面向 agent 调用语义的模型能力卡片 |
| Agent 连接器 | Plan 15 P15-A–P15-G 已落地：provider registry、policy、run、事件、质量摘要、前端配置 tab 均存在 | providers/run API 目前 admin-only；需按本计划开放策略允许的普通用户调用并保持管理 API admin-only |
| Capability API | `GET /capabilities` 已返回产品 readiness 矩阵 | 缺少 `GET /capabilities/catalog` 分组目录契约 |
| 用户与邀请码 | `/admin/users`、`/admin/invite-codes`、状态更新和前端 API 封装已存在 | 缺少 `/admin` 管理界面；用户列表契约缺时间字段 |
| 前端路由 | `/tools` 与 `/admin` 已存在；`/admin` 有角色守卫 | 缺少 `/capabilities` 路由和导航入口；`/tools` 未加角色守卫 |
| 来源标注 | 来源矩阵已有“Agent 能力中心”条目，算法工具和连接器来源牌已有基础 | `AttributionService` 尚未注册 `capability_center`；报告 Skill 与 LLM 卡片来源需统一 |

基线验证结论（2026-08-28）：

- `backend/tests/test_agent_exec_api.py`、`test_agent_exec_policy.py`、`test_agent_tools_api.py` 共 19 个测试通过。
- `frontend npm run test:agent-connectors` 5 个测试通过。
- `frontend npm run build` 通过。

## 4. 入口设计与分工

### 4.1 两个独立入口的职责划分

| 维度 | `/tools` 配置中心 | `/capabilities` 能力中心 |
| --- | --- | --- |
| 业务逻辑 | 工具与服务配置运维 | Agent 可调用能力发现与准入 |
| 回答的问题 | 这个能力怎么配、策略怎么改 | agent 现在能调用什么、是否可用、如何调用 |
| 面向角色 | 管理员 | 管理员 + 策略允许的普通用户 |
| 核心动作 | 配置、启停、修改策略、受控测试 | 浏览、查 readiness、跳转调用、显式确认 |
| 数据来源 | provider 配置、集成配置、工具注册表、agent_exec policy | 各模块 readiness、策略摘要、调用方式和来源 |
| 写操作 | 直接调用原模块配置 API | 不代理配置写；只发起原模块调用 |
| 状态缓存 | 各模块权威状态 | 实时只读聚合，不缓存权威状态 |

### 4.2 工具服务 `/tools`

- 保留现有 6 个 tab 和 URL 参数：`status`、`algorithms`、`agent-tools`、`agent-connectors`、`configs`、`llm-models`。
- Agent 连接器的策略配置、sandbox readiness 和受控测试继续留在 `/tools?tab=agent-connectors`。
- 报告 Skill pipeline 本期不新增运行时配置 tab；其事实源仍是服务端配置、`SUPPORTED_PIPELINES` 和 allowlist。
- 前端路由增加 `requiresRole: 'admin'`；普通用户访问 `/tools` 回到工作台。
- 页面顶部增加提示：“工具配置在这里，能力可用性与调用入口请前往能力中心。”

### 4.3 能力中心 `/capabilities`

新建独立路由与页面，不复用 `ToolServicesView.vue`：

1. **总览**：四个能力组的 available / partial / unavailable 状态。
2. **对话工具**：来自 `AgentToolService`；admin 看治理目录，user 看可调用目录。
3. **外部 Agent 连接器**：来自 Plan 15 provider registry 与 policy；user 仅看到 enabled 且角色允许的条目。
4. **报告 Skill**：仅展示服务端 pipeline allowlist 和 readiness。
5. **LLM 能力**：展示脱敏 provider、模型能力与推荐用途；配置跳转 `/tools?tab=llm-models`。
6. **权限摘要**：展示 admin/user 的可见性与确认要求，管理入口跳转 `/admin`。

卡片固定字段：

- 名称、id、描述、归属模块。
- readiness：available / degraded / disabled / unavailable 与安全原因。
- 准入策略：允许角色、是否需要确认、可见范围。
- 调用方式：对话工具、结构化文件任务、报告 pipeline 或模型路由。
- 配置跳转：对应 `/tools` tab 或服务端配置说明。
- 来源牌：使用结构化 attribution 数据。

### 4.4 数据单向流动

- `/tools` 与服务端配置 → 产出各模块权威状态 → `/capabilities/catalog` 只读聚合。
- 能力中心不保存配置快照，不修改 provider、tool、skill 或 policy。
- 修改配置一律跳转 `/tools`；调用一律走原模块 API。
- 单个模块读取失败只影响该分组状态，不得阻断其他分组返回。

### 4.5 与 Plan 15 的边界

- Plan 15 是受控外部执行的安全内核与连接器治理事实源。
- Plan 16 只消费 provider readiness、policy 和 run API，不重建安全边界。
- `GET /agent-exec/providers` 需要从 admin-only 调整为认证用户可访问，并按角色过滤：
  - admin 返回全部 provider。
  - user 只返回 enabled 且 `allowed_roles` 包含 `user` 的 provider。
- `POST /agent-exec/runs` 需要从 admin-only 调整为认证用户可访问：
  - admin 保持现有策略语义。
  - user 由服务端 policy 校验角色、enabled、task type 和 readiness。
  - user 请求必须 `confirmed=true`。
- `PATCH /providers/{id}/policy`、run 详情、取消和质量汇总继续 admin-only。
- Plan 15 P15-H 生产化缺口不因本计划关闭；上线时管理员应维持默认 admin-only，待容量与审计策略满足要求后再开放 user。

## 5. 后端聚合契约

### 5.1 契约设计

新增或扩展 `backend/app/schemas/capabilities.py`：

- `CapabilityPolicySummary`
  - `allowed_roles: list[admin|user]`
  - `requires_confirmation: bool`
  - `viewer_can_invoke: bool`
  - `scope_note: str`
- `CapabilityInvocation`
  - `kind: dialogue_tool | agent_connector | report_skill | llm_model`
  - `method: navigate | api`
  - `target: str`
- `CapabilityCatalogItem`
  - id、名称、描述、状态、原因、归属模块、策略摘要、调用方式、配置路径、来源列表。
- `CapabilityCatalogGroup`
  - group id、标题、说明、聚合状态、总数、可调用数、不可用原因、items。
- `CapabilityCatalogData`
  - `generated_at`
  - `viewer_role`
  - `is_admin`
  - `dialogue_tools`
  - `agent_connectors`
  - `report_skills`
  - `llm_capabilities`

新增 `GET /capabilities/catalog`：

- 登录启用时必须认证；本地 auth disabled 演示模式按既有约定视为 admin。
- 返回四个固定分组，不按 `/tools` 配置 tab 分组。
- 不返回 secret、API key、base URL、workdir、完整 prompt、环境变量、完整配置对象或工具输入输出 schema。
- 每个来源独立异常捕获，失败分组返回 unavailable 和安全摘要。

### 5.2 数据来源映射

| 分组 | 事实源 | admin 视角 | user 视角 | 调用 / 配置 |
| --- | --- | --- | --- | --- |
| `dialogue_tools` | `AgentToolService.list_registry()` / `list_tools()` | 全部治理条目，包括 disabled / unavailable | 仅 public 或本人 private，且 enabled、角色允许、available | 跳 `/dialogue?toolIds=...`；配置跳 `/tools?tab=agent-tools` |
| `agent_connectors` | Plan 15 provider registry + policy | 全部 provider 与策略 | 仅 enabled 且角色允许的 provider；readiness 可为 unavailable | `POST /agent-exec/runs`；配置跳 `/tools?tab=agent-connectors` |
| `report_skills` | `SUPPORTED_PIPELINES` + orchestrator allowlist | 全部服务端 pipeline 与 readiness | 仅 allowlist 允许且 ready 的 pipeline | 跳研发引擎报告入口；不新增运行时配置 |
| `llm_capabilities` | `LLMModelService.get_catalog(probe=false)` | 全部模型与 provider 状态 | 仅 available / degraded provider 的模型 | 跳 `/dialogue?providerId=...&modelId=...`；配置跳 `/tools?tab=llm-models` |

## 6. Skill 治理边界

- MVP Skill 目录只展示服务端 report skill pipeline 与 allowlist。
- Skill 卡片包含 pipeline id、描述、适用报告场景、步骤中的服务端 skill id、readiness、来源与引用。
- 不读取 `.codex/skills`，不展示用户本地 Skill，不支持上传或动态安装。
- `nature-*` 命名只代表平台内报告工作流命名，不声明 Nature Portfolio 授权或归属。
- 报告 Skill 的外部能力来源按实际 provider 标注：Codex CLI、OpenAI-compatible、Ollama 或 Custom HTTP。

## 7. 用户与权限管理

### 7.1 MVP 权限模型

- 继续使用 `admin / user` 两角色，不提供角色编辑。
- admin：
  - 可进入 `/tools` 配置能力和策略。
  - 可进入 `/capabilities` 查看全部能力与不可用原因。
  - 可进入 `/admin` 管理用户与邀请码。
- user：
  - 不进入 `/tools` 和 `/admin`。
  - 可进入 `/capabilities` 查看策略允许的能力。
  - 可调用允许的算法工具、LLM 模型和显式开放的外部连接器。

### 7.2 外部连接器用户调用规则

- 默认 provider policy：`enabled=false`、`allowed_roles=["admin"]`、`requires_confirmation=true`。
- 管理员开放普通用户必须显式完成两项配置：`enabled=true` 且 `allowed_roles` 包含 `user`。
- 普通用户可见连接器后，readiness 不满足时仍显示 unavailable，不能发起 run。
- 普通用户创建 run 时服务端强制要求 `confirmed=true`；前端必须展示确认说明。
- 请求中的 provider、task type、输入文件、输出 schema、超时与限额仍由 Plan 15 服务端校验。
- 普通 run 的 actor、policy snapshot、事件和 trace 必须可追溯，审计角色不能硬编码。

### 7.3 用户与邀请码管理

- 后端已有接口：
  - `GET /admin/users`
  - `PATCH /admin/users/{user_id}/status`
  - `GET /admin/invite-codes`
  - `POST /admin/invite-codes`
  - `PATCH /admin/invite-codes/{invite_id}/disable`
- 用户列表契约需 additive 补充 `created_at`、`updated_at`、`last_login_at`。
- `/admin` 新增“用户与邀请码”管理区：
  - 用户：username、real_name、organization、role、status、创建时间、最近登录。
  - 操作：仅允许禁用 / 启用非 admin 用户，操作前确认。
  - 邀请码：code、状态、有效期、次数、创建人、创建时间。
  - 操作：创建 user 角色邀请码、禁用邀请码。

## 8. 分阶段任务

### P16-0. 文档基线修订（本轮完成）

- [x] 修正 Plan 15 与 Plan 16 的边界：P15-A–P15-G 已落地，P15-H 留在 Plan 15。
- [x] 修正 `/tools` 当前为 6 个 tab，Agent 连接器配置面已存在。
- [x] 记录外部连接器权限决策：默认 admin-only，策略显式允许后 user 可调用且必须确认。
- [x] 明确 catalog 数据源、脱敏边界、失败隔离和 admin/user 视角差异。
- [x] 重排后续任务、测试计划、兼容策略、风险和完成定义。
- [x] 本轮只修改文档，不修改任何业务代码、前端代码、测试代码或配置文件。

### P16-A. 能力中心聚合契约

- [x] 扩展 `backend/app/schemas/capabilities.py`，新增 catalog item / group / policy / invocation 契约。
- [x] 新增 `backend/app/services/capability_catalog_service.py`，实时只读聚合四个能力组。
- [x] 新增 `GET /capabilities/catalog`，认证与本地演示模式行为符合第 5 节。
- [x] 聚合算法工具、连接器、报告 Skill 与 LLM 的 readiness、策略、调用方式和来源。
- [x] 单个来源异常只标记该分组 unavailable，不阻断其他分组。
- [x] 补充服务与 API 测试，断言 readiness 一致、角色过滤正确且敏感信息不泄漏。

### P16-B. 策略允许的用户连接器调用

- [x] 调整 `GET /agent-exec/providers` 为认证用户可访问，admin 全量、user 按策略过滤。
- [x] 调整 `POST /agent-exec/runs` 为认证用户可访问，继续由 Plan 15 policy 服务端校验。
- [x] 普通用户 run 强制 `confirmed=true`；管理员行为保持兼容。
- [x] 保持 policy 更新、run 详情、取消和质量汇总 admin-only。
- [x] 修正 agent_exec 事件与 policy 审计中的真实 actor role。
- [x] 更新 API、policy 和事件测试，覆盖默认拒绝、显式授权、确认要求、管理接口权限与审计追溯。

### P16-C. 能力中心前端独立入口

- [x] 新增 `/capabilities` 路由、导航入口、面包屑映射与 `CapabilityCenterView.vue`。
- [x] 实现总览、对话工具、外部连接器、报告 Skill、LLM 能力和权限摘要六块视图。
- [x] 卡片展示 readiness、原因、策略摘要、调用方式、来源牌和配置跳转。
- [x] 对话工具跳 `/dialogue?toolIds=...`，LLM 跳 `/dialogue?providerId=...&modelId=...`。
- [x] 连接器调用复用确认与 payload 构建逻辑，直接走 `POST /agent-exec/runs`。
- [x] `/tools` 增加 admin 路由守卫和顶部能力中心引导；现有 6 个 tab 不回退。
- [x] 新增 `capabilityCenter` 纯函数与测试，覆盖分组状态、角色过滤、调用目标、配置跳转和脱敏。

### P16-D. 用户与邀请码管理 UI

- [x] 扩展 admin 用户列表契约，返回创建、更新和最近登录时间。
- [x] 在 `/admin` 增加“用户与邀请码”管理区，复用既有 API。
- [x] 用户列表支持禁用 / 启用非 admin 用户，操作前确认。
- [x] 邀请码支持列表、创建和禁用；固定创建 user 角色。
- [x] 补充 API 权限测试与前端纯函数测试；普通用户不能进入 `/admin`。

### P16-E. 来源标注与文档同步

- [x] 在 `AttributionService` 注册 `capability_center`，使用结构化来源数据。
- [x] 页面来源牌覆盖算法工具、Codex、报告 Skill provider、OpenAI-compatible、Ollama 和 Custom HTTP。
- [x] 更新来源矩阵，明确能力中心只聚合展示，能力归属原模块。
- [x] 新增能力中心用户指南，更新 Agent 连接器指南、`doc/README.md` 和本计划。
- [x] 明确非目标：不做插件市场、浏览器连接器、任意 OAuth 安装或本地 Skill 动态加载。

### P16-F. 全量验证与收尾

- [x] 运行后端专项测试与 `make test-backend`。
- [x] 运行前端全部 `test:*` 脚本和 production build。
- [x] 启动本地服务，用浏览器验证 admin/user 的 `/capabilities`、`/tools`、`/admin` 行为与 console。
- [x] 运行既有 dialogue E2E，并新增能力中心与 admin 治理 E2E。
- [x] 全部通过后更新本计划复选框、状态记录和完成定义。
- [x] 按阶段创建独立提交；推送前同步远端，最后 fast-forward 推送 `develop`。

## 9. 测试计划

### 9.1 后端专项

```bash
conda run -n poly_agent env PYTHONPATH=backend python -m pytest \
  backend/tests/test_capability_catalog_service.py \
  backend/tests/test_capabilities_api.py \
  backend/tests/test_agent_exec_api.py \
  backend/tests/test_agent_exec_policy.py \
  backend/tests/test_agent_exec_events.py \
  backend/tests/test_agent_tools_api.py \
  backend/tests/test_admin_api.py -q
```

覆盖：

- catalog 四分组结构、字段和来源映射。
- admin/user 视角差异；user 只见可调用项。
- 单个来源失败不阻断其他分组。
- catalog 不含 secret、base URL、workdir、完整 prompt、完整配置或工具 schema。
- providers 接口默认 user 返回空；显式授权后返回允许卡片。
- run 接口默认 user 拒绝；显式授权后可调用，未确认拒绝。
- policy 更新、run 详情、取消和质量汇总仍 admin-only。
- 审计 actor role 真实，run policy snapshot 可追溯。
- admin 用户与邀请码接口权限、时间字段、admin 保护和管理操作。

### 9.2 后端回归

```bash
make test-backend
```

重点回归：

- Plan 15 安全边界：默认关闭、readiness、输入输出、取消、终态与事件。
- 对话工具：派生目录、策略、owner/private 可见性。
- 报告 Skill：pipeline 与 allowlist。
- LLM 模型：脱敏、能力推断与路由。
- 既有 `/capabilities` readiness 行为不变。

### 9.3 前端与 E2E

- 运行全部既有 `test:*` 脚本、新增 `test:capability-center` 和 admin 治理测试。
- 运行 `npm --prefix frontend run build`。
- 浏览器验证：
  - admin 可见全部能力、来源牌、配置跳转和调用入口。
  - user 默认看不到连接器；授权后可见且必须确认。
  - user 访问 `/tools`、`/admin` 被重定向。
  - `/capabilities` 与 `/tools` 无 console 错误，核心 API 请求成功。
- 运行 `make test-e2e`，并新增 capability/admin E2E 脚本。

## 10. 兼容与迁移策略

- `GET /capabilities` 旧 readiness 接口保持不变，新增 catalog 为独立端点。
- `/tools` 现有路径、tab key 和配置功能保持不变；仅增加 admin 路由守卫和引导。
- Agent 连接器默认策略不变，升级后普通用户默认仍不可见、不可调用。
- providers/run 权限调整为行为扩展；管理接口权限不变。
- Admin 用户列表新增时间字段为 additive 变更，无数据迁移。
- 不修改报告 Skill pipeline 数据结构，不引入本地 Skill 存储迁移。
- catalog 不缓存权威状态，模块升级后 readiness 自动反映。

## 11. 风险与规避

| 风险 | 影响 | 规避 |
| --- | --- | --- |
| 能力中心被误用为配置面 | 形成第二状态源 | 只读聚合，不内嵌配置表单；修改配置跳 `/tools` |
| catalog 与模块状态不一致 | 用户看到过期能力 | 实时读取事实源，不缓存权威状态 |
| 聚合视图泄漏敏感配置 | 泄漏 secret、路径或 prompt | 契约白名单字段 + 服务端脱敏 + 响应断言 |
| 普通用户开放外部执行后滥用 | 外部任务风险扩大 | 默认 admin-only；显式策略授权；user 强制确认；服务端限额与审计 |
| Plan 15 P15-H 未完成 | 并发、审计和多实例生产风险未收口 | 开放 user 由管理员显式配置；生产化缺口继续在 Plan 15 跟踪 |
| Skill 目录被误解为插件市场 | 安全边界漂移 | 只展示服务端 pipeline allowlist，不做上传、扫描和动态加载 |
| 用户管理引入角色编辑 | 破坏 MVP 权限模型 | 只允许禁用/启用非 admin 用户；邀请码固定 user 角色 |
| `/tools` admin 守卫影响旧链接 | 普通用户旧链接体验变化 | 回退工作台；公共算法入口 `/tools/alchemist` 保持可用 |

## 12. 完成定义

- [x] `GET /capabilities/catalog` 返回四个固定分组，聚合状态与各模块事实源一致。
- [x] admin 可见全部能力与不可用原因；user 只见策略允许且可调用的能力。
- [x] catalog 响应不含 secret、API key、base URL、workdir、完整 prompt 或未脱敏配置。
- [x] `/capabilities` 独立页面可用，与 `/tools` 不共享配置视图，不出现配置表单。
- [x] `/tools` 保留 6 个现有 tab，增加 admin 守卫与能力中心引导，配置功能不回退。
- [x] 默认策略下 user 看不到连接器；显式授权后可见，未确认不能调用。
- [x] provider/run 管理边界清晰：providers/runs 面向认证用户，policy/detail/cancel/quality 仍 admin-only。
- [x] Skill 页面只显示服务端 allowlist，不出现本地 `.codex/skills` 扫描结果。
- [x] `/admin` 用户与邀请码管理可用；admin 可操作，user 被拒绝。
- [x] 来源标注覆盖算法工具、Codex、报告 Skill provider 和 LLM Provider。
- [x] 后端全量、前端全量、构建、既有 E2E 和新增 E2E 全部通过。
- [x] 本计划、来源矩阵、用户指南和 `doc/README.md` 同步更新，所有复选框与状态记录完成。

## 13. 状态记录

- 2026-08-28（P16-F）：完成全量收尾：`make test-backend` 通过（942 passed / 1 skipped）；前端 24 个 `test:*` 脚本与 production build 通过；本地 5200/5201 服务健康；`make test-e2e` 同时通过既有 dialogue E2E 和新增 capability/admin E2E，覆盖 admin/user 目录视角、默认连接器隐藏、`/tools` 与 `/admin` 回退、6 个配置 tab、响应式与 console。修复测试环境认证隔离、WeKnora 图谱失败语义、整页恢复后的角色守卫和算法自动续答恢复，并留存浏览器截图。
- 2026-08-28（P16-E）：注册 `capability_center` 结构化来源，能力中心顶部与卡片覆盖算法来源、Codex CLI、报告 Skill provider、OpenAI-compatible、Ollama 和 Custom HTTP；更新来源矩阵、能力中心用户指南、Agent 连接器指南与 `doc/README.md`，明确不做插件市场、浏览器连接器、任意 OAuth 安装或本地 Skill 动态加载。来源 API 测试、能力中心前端测试和 production build 通过。
- 2026-08-28（P16-D）：admin 用户列表补充创建、更新与最近登录时间；`/admin` 新增用户与邀请码管理区，支持确认后启用/禁用非管理员、创建 user 邀请码和禁用邀请码；新增 API 权限与前端纯函数测试，并修复本地双模存储用户/邀请码列表读取。专项测试与 production build 通过。
- 2026-08-28（P16-C）：新增 `/capabilities` 独立只读页面、全局导航与 API 封装；实现权限摘要和四个能力分组，卡片包含状态、原因、策略、调用方式、来源牌与配置跳转；外部连接器调用复用既有显式确认 payload 构建并直接调用 run API；`/tools` 收窄为管理员配置入口并保留 6 个 tab；新增 capabilityCenter 纯函数测试，production build 通过。
- 2026-08-28（P16-B）：完成策略允许的普通用户连接器访问与调用：providers/runs 面向认证用户，默认策略仍拒绝普通用户；显式授权后可调用且服务端强制逐次确认；管理接口保持 admin-only，run 与 policy 审计记录真实 actor role。专项与 Plan 15 回归测试通过。
- 2026-08-28（P16-A）：完成能力中心聚合契约、只读聚合服务与 `GET /capabilities/catalog`；新增认证、角色过滤、敏感信息脱敏、来源映射与失败隔离专项测试并通过。
- 2026-08-27：从 Plan 15 修订拆分新建统一能力中心与权限治理计划；本次仅编写文档，未修改业务代码。
- 2026-08-27（第二版修订）：明确 `/capabilities` 与 `/tools` 为两个独立入口；配置面与调用面分离，数据单向流动。
- 2026-08-28：基于 `develop@bac4d3b` 复核代码现状，修正 Plan 15 已落地、`/tools` 已有 6 个 tab、连接器配置面已存在等过期基线；记录“策略允许的普通用户可调用连接器且必须确认”的决策；重排任务、测试、兼容、风险与完成定义。本轮仅修改本文档，未修改任何业务代码、前端代码、测试代码或配置文件。
