# Plan 16：Agent 能力中心与权限治理工作计划

> 状态：待评审 / 未开始
>
> 日期：2026-08-27
>
> 前置文档：
> - [research-engine-plan-15-agent-exec-provider-seam-workplan.md](research-engine-plan-15-agent-exec-provider-seam-workplan.md)
> - [research-engine-plan-10-slash-command-and-agent-control-workplan.md](research-engine-plan-10-slash-command-and-agent-control-workplan.md)
> - [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md)
>
> 拆分说明：本计划从 Plan 15 修订拆分而来。Plan 15 只交付受控外部 Agent 的执行安全内核与连接器管理 API；全局“连接器 + Skill + Agent + 权限管理”大入口的范围横跨外部服务集成、算法工具、报告 Skill、LLM Provider 与用户管理，归入本计划，避免演变为插件市场，也避免与 Plan 15 的安全内核耦合。
>
> 修订说明（2026-08-27 第二版）：明确能力中心与工具服务是两个业务逻辑不同的独立入口，不复用页面。工具服务 `/tools` 收窄为“配置中心”，负责工具与服务的配置运维（写操作）；能力中心 `/capabilities` 新建独立入口，负责 Agent 可调用能力的发现与准入（读 + 调用）。两者数据单向流动：配置流向能力，能力不反向改配置。

## 1. 摘要

PolyAgent 已有分散的能力入口：外部服务集成（`integrations`）、算法工具（`agent_tools`）、报告 Skill pipeline（`report_skills`）、LLM Provider 配置与 Plan 15 新增的 Agent 连接器。这些入口目前集中在 `/tools` 页面，混在一个“配置 + 展示”的大页面里，业务逻辑不清：管理员既在里面配工具，也试图用它看能力可用性，但普通用户无法用它判断“agent 现在能调哪些能力”。

本计划把这两件事拆开，做两个独立入口：

- **工具服务 `/tools`**（保持现状，定位收窄为“配置中心”）：工具与服务的配置运维，面向管理员，核心动作是配置 / 启停 / 改策略（写）。
- **能力中心 `/capabilities`**（新建独立入口）：Agent 可调用能力的发现与准入目录，面向管理员（看全部 + 准入）和用户（看自己可调用），核心动作是浏览能力 / 查可用性 / 触发调用 / 确认执行（读 + 调用）。

核心原则：**配置面与调用面分离，数据单向流动**。`/tools` 配置产出能力，`/capabilities` 只读消费能力 readiness + 准入策略展示；`/capabilities` 不存配置、不重建状态源、不反向改配置，但可发起“调用”动作（走原模块 API）。

```text
/tools（配置中心）            /capabilities（能力中心）
  配置 LLM provider     →     展示 LLM 可用能力（只读）
  配置外部集成          →     展示连接器可用性（只读）
  配置算法工具注册      →     展示对话工具可调用（只读 + 调用）
  配置连接器凭据/sandbox →     展示外部 Agent 连接器可用性（只读 + 调用）
  配置 report skill     →     展示报告 Skill pipeline（只读）
                 ↓
        GET /capabilities/catalog 只读聚合
```

权限管理 `/admin` 保持独立，与两个入口都不合并。

## 2. 目标与非目标

### 2.1 目标

- 新建 `/capabilities` 独立路由与 `CapabilityCenterView.vue`，定位为 Agent 可调用能力的发现与准入目录，不复用 `/tools` 页面。
- 工具服务 `/tools` 收窄为“配置中心”，保持现有配置面（状态 / 算法清单 / 算法工具 / 配置 / LLM 模型），不在能力中心重复配置操作。
- 新增 `GET /capabilities/catalog` 只读聚合契约，按 **agent 调用语义**分组（对话工具 / 外部 Agent 连接器 / 报告 Skill / LLM 能力），复用各模块既有 readiness / policy 状态，不重建事实源。
- 能力卡片展示：名称、可用性 readiness、准入策略摘要（谁能用 / 要不要确认）、调用方式、来源牌。
- 能力中心可发起“调用”动作（走原模块 API），但不代理配置写操作。
- 管理员看全部能力 + 调用准入配置；用户只看 policy 允许且可调用的能力。
- MVP Skill 目录只展示服务端注册的 report skill pipeline 和 allowlist，不做本地 `.codex/skills` 扫描或插件市场。
- 在 `/admin` 增加“用户与邀请码”页签，补齐前端 UI，复用既有 `/admin/users`、`/admin/invite-codes`、`PATCH /admin/users/{user_id}/status` 接口。
- 来源标注覆盖外部服务、Codex、报告 Skill、算法工具和 LLM Provider。

### 2.2 非目标

- 不复用 `/tools` 页面做能力中心；两个入口业务逻辑不同，页面不合并。
- 不把 `/tools` 的配置操作搬到能力中心；配置仍在 `/tools`，能力中心只读 + 调用。
- 不新建第二套 provider、tool、skill、policy 或 trace 事实源。
- 不提供统一写代理，避免权限语义被二次实现；能力中心可发起调用，但不代理配置写。
- 不扫描本地 `.codex/skills`、不上传任意 SKILL.md、不做插件市场。
- 不做项目级 RBAC、用户级自定义授权矩阵或角色随意变更；MVP 继续使用 `admin / user` 两角色。
- 不实现 Manus 式插件市场、浏览器连接器、任意 OAuth 连接器安装或本地 Skill 动态加载。
- 如需要更细粒度用户授权，另立 Plan 17，不并入本计划。
- 不替代 Plan 15 的连接器策略治理；能力中心只读消费 Plan 15 `GET /agent-exec/providers`。
- 不把权限管理并入能力中心或工具服务；`/admin` 保持独立。

## 3. 当前基线

| 能力 | 当前状态 | 差距 |
| --- | --- | --- |
| 工具服务 `/tools` | `ToolServicesView.vue` 已有 5 个 tab：状态 / 算法清单 / 算法工具 / 配置 / LLM 模型，混配置与展示 | 定位不清，配置与能力展示混杂；普通用户无法据此判断 agent 可调能力 |
| 外部服务集成 | `integrations.py`、`integration_status_service.py`、`integration_config_service.py` 已有配置与 readiness | 无独立能力展示入口 |
| 算法工具 | `agent_tools.py`、`agent_tool_service.py`、AgentToolRegistry 已注册工具，`算法工具` tab 已有“允许角色 / 确认执行”policy 列 | policy 只在配置面展示，无面向 agent 调用的能力目录 |
| 报告 Skill | `report_skills/`、`report_skill_orchestrator.py` 已有 pipeline | 无服务端 allowlist 的 Skill 目录展示 |
| LLM Provider | `/tools?tab=llm-models` 已有 provider 配置与 readiness | 配置面，无面向 agent 调用的 LLM 能力展示 |
| Agent 连接器 | Plan 15 规划 `GET /agent-exec/providers` 与 policy API | 依赖 Plan 15 稳定后接入能力中心 |
| 能力契约 | `capabilities.py` 已有 `CapabilityStatus` / `CapabilityStatusData` | 尚无面向能力中心的 catalog 分组契约 |
| 用户与邀请码 | `admin.py` 已有 `GET /users`、`GET /invite-codes`、`POST /invite-codes`、`PATCH /users/{user_id}/status` | 缺前端 UI |
| 前端路由 | `/tools` → `ToolServicesView`，`/admin` → `DatabaseManagementView` | 无 `/capabilities` 路由与视图 |
| 来源标注 | `AttributionService` 与来源矩阵已覆盖主要模块 | 尚未登记能力中心聚合视图的来源 |

## 4. 入口设计与分工

### 4.1 两个独立入口的职责划分

| 维度 | 工具服务 `/tools`（配置中心） | 能力中心 `/capabilities`（新建） |
| --- | --- | --- |
| 业务逻辑 | 工具与服务的**配置运维** | Agent **可调用能力的发现与准入** |
| 回答的问题 | “这个工具配好没、怎么配” | “agent 现在能调哪些能力、能不能用、怎么用” |
| 面向角色 | 管理员（运维） | 管理员（看全部 + 准入）+ 用户（看自己可调用） |
| 核心动作 | 配置 / 启停 / 改策略（**写**） | 浏览能力 / 查可用性 / 触发调用 / 确认执行（**读 + 调用**） |
| 数据来源 | provider 配置、集成配置、工具注册表（权威源） | 各能力 readiness、准入策略摘要、调用方式、来源牌（只读聚合） |
| 与 agent 关系 | 间接（配好了 agent 才能用） | 直接（agent 调用前的能力目录） |
| 写操作 | 直接配置原模块 | 不代理配置写；可发起调用走原模块 API |

### 4.2 工具服务 `/tools` 收窄为配置中心

- 保留现有 5 个 tab：状态 / 算法清单 / 算法工具 / 配置 / LLM 模型。
- 职责收窄为：配 LLM provider、配外部集成、配算法工具注册与策略、（Plan 15 稳定后）配连接器凭据与 sandbox 参数。
- 面向 admin，是“后台配置”，普通用户不进。
- 在页面顶部增加引导：“能力可用性请前往能力中心 `/capabilities` 查看”，避免管理员在配置面误判能力状态。

### 4.3 能力中心 `/capabilities` 入口设计

新建独立路由 `/capabilities` 与 `CapabilityCenterView.vue`，按 **agent 调用语义**分组（不是按工具配置类型）：

1. **总览**：各能力组 readiness 与安全状态卡片，一眼看到“哪些能用、哪些不可用”。
2. **对话工具**：slash command / 工具调用派生的算法工具（来自 AgentToolRegistry，按准入策略展示）。
3. **外部 Agent 连接器**：Plan 15 `agent_exec` 受控外部执行（依赖 Plan 15 稳定，未稳定时占位）。
4. **报告 Skill**：服务端 report skill pipeline allowlist。
5. **LLM 能力**：当前路由可用的模型能力（只读展示当前配置能力，不是配置入口）。
6. **权限摘要**：展示 admin / user 可用性，并跳转 `/admin`。

每张能力卡片包含：

- 名称与来源牌（复用 `AttributionBanner`）
- 可用性 readiness（可用 / 不可用 + 原因）
- 准入策略摘要（谁能用、要不要确认）——只读展示，修改跳转 `/tools` 对应 tab
- 调用方式（如何被 agent 调用）
- 可执行操作：admin 可发起受控测试 / 调用；user 只看 policy 允许且可调用的能力

### 4.4 数据单向流动

- `/tools` 配置 → 产出能力 → `/capabilities` 只读消费 readiness + policy 展示。
- `/capabilities` 不存配置、不重建状态源，只读聚合 + 触发调用。
- 单向：配置流向能力，能力不反向改配置。
- 修改准入策略 / 配置 → 跳转 `/tools` 对应 tab；能力中心不内嵌配置表单。

### 4.5 与 Plan 15 的边界

- Plan 15 交付受控外部 Agent 的执行安全内核与连接器管理 API。
- 能力中心只读消费 Plan 15 `GET /agent-exec/providers`，展示连接器可用性与准入策略摘要。
- 能力中心可发起受控调用（走 `POST /agent-exec/runs`），但连接器策略配置仍在 `/tools`（Plan 15 P15-G 连接器区域）或 Plan 15 管理 API。
- 能力中心不重建第二套 provider、policy 或 trace 事实源。
- Plan 15 未稳定时，`外部 Agent 连接器` 分组占位或标记待接入，不阻断能力中心其他分组。

## 5. 后端聚合契约

新增或扩展 capability read model：

- `GET /capabilities/catalog`
  - 返回 `dialogue_tools`、`agent_connectors`、`report_skills`、`llm_capabilities` 分组（按 agent 调用语义，区别于 `/tools` 的配置分组）。
  - 每项包含 id、名称、状态、来源、policy 摘要、可执行操作类型、归属模块。
- 写操作仍调用原模块 API：
  - `agent_exec`（Plan 15 连接器策略与 run）
  - `integrations`（外部服务集成配置）
  - `agent-tools`（算法工具）
  - reports / skills（报告 Skill pipeline）
  - LLM 配置接口
- 能力中心可发起调用（如 `POST /agent-exec/runs`），但不代理配置写操作。

### 5.1 catalog 数据来源映射

| 分组 | 数据来源 | 调用接口 | 调用 / 配置目标 |
| --- | --- | --- | --- |
| `dialogue_tools` | `agent_tool_service` / AgentToolRegistry | `GET /agent-tools` | 调用走 `agent-tools` API；配置跳转 `/tools` |
| `agent_connectors` | Plan 15 `agent_exec` providers | `GET /agent-exec/providers` | 调用走 `POST /agent-exec/runs`；配置跳转 `/tools` |
| `report_skills` | `report_skill_orchestrator` 已注册 pipeline | 服务端 allowlist 接口 | 调用走 reports / skills API |
| `llm_capabilities` | LLM 模型配置与 readiness | 现有 LLM 配置接口 | 只读展示当前可用能力；配置跳转 `/tools` |

## 6. Skill 治理边界

- MVP Skill 目录只展示服务端注册的 report skill pipeline 和 allowlist。
- Skill 卡片包含：
  - skill / pipeline id
  - 描述
  - 适用报告场景
  - readiness
  - 来源与引用
- 不扫描本地 `.codex/skills`、不上传任意 SKILL.md、不做插件市场。
- 若未来要动态安装或版本管理 Skill，另立后续计划。

## 7. 用户与权限管理

- 后端已有 `/admin/users`、`/admin/invite-codes`、用户状态更新和邀请码接口；Plan 16 补齐前端 UI。
- 在 `/admin` 增加“用户与邀请码”页签：
  - 用户列表：username、real_name、organization、role、status
  - 禁用 / 启用非 admin 用户
  - 邀请码列表、创建、禁用
  - 显示最近登录与创建时间
- MVP 权限模型继续使用 `admin / user` 两角色：
  - admin 可配置和测试能力（`/tools`），可看全部能力与准入（`/capabilities`）
  - user 只能使用 policy 明确允许且 `requires_confirmation` 为 true 的能力（`/capabilities` 只看可调用项）
- 不做项目级 RBAC、用户级自定义授权矩阵或角色随意变更。
- 如需要更细粒度用户授权，另立 Plan 17，不并入 Plan 16。
- `/admin` 保持独立入口，不并入能力中心或工具服务。

## 8. 分阶段任务

### P16-A. 能力中心聚合契约

- [ ] 扩展 `backend/app/schemas/capabilities.py`，新增能力中心 catalog 分组契约：`CapabilityCatalogGroup`、`CapabilityCatalogItem`、`CapabilityCatalogData`（含 `dialogue_tools`、`agent_connectors`、`report_skills`、`llm_capabilities` 分组）。
- [ ] 新增 `backend/app/services/capability_catalog_service.py`，只读聚合各模块 readiness / policy / 来源，不写、不缓存权威状态。
- [ ] 新增 `GET /capabilities/catalog` 端点（或扩展现有 `capabilities.py` 端点），返回分组与卡片摘要。
- [ ] catalog 按 agent 调用语义分组，区别于 `/tools` 的配置分组。
- [ ] catalog 不返回 secret、workdir 绝对路径、完整 prompt 或未脱敏配置。
- [ ] 补充测试：catalog 聚合结果与各模块 readiness 一致；某模块不可用时不阻断 catalog 返回，标记 unavailable。

### P16-B. 能力中心前端独立入口

- [ ] 新增前端路由 `/capabilities`，`meta: { section: '能力中心', title: 'Agent 能力目录' }`。
- [ ] 新增 `frontend/src/views/CapabilityCenterView.vue`，按 agent 调用语义分组：总览 / 对话工具 / 外部 Agent 连接器 / 报告 Skill / LLM 能力 / 权限摘要。
- [ ] 总览展示各能力组 readiness 与安全状态卡片，一眼看到可用 / 不可用。
- [ ] 能力卡片展示名称、来源牌（`AttributionBanner`）、可用性 readiness、准入策略摘要、调用方式。
- [ ] 修改准入策略 / 配置 → 跳转 `/tools` 对应 tab，不在能力中心内嵌配置表单。
- [ ] admin 可发起受控调用（如 `POST /agent-exec/runs`）；user 只看 policy 允许且可调用的能力。
- [ ] 在 `/tools` 页面顶部增加引导：“能力可用性请前往能力中心 `/capabilities` 查看”。
- [ ] 补充前端测试：分组展示、状态与后端一致、来源牌可见、调用跳转正确模块、配置跳转 `/tools`、admin/user 权限差异。

### P16-C. 连接器与 Skill 卡片聚合

- [ ] `agent_connectors` 分组聚合 Plan 15 `agent_exec` providers；Plan 15 未稳定时该分组只占位或标记待接入，不阻断其他分组。
- [ ] `report_skills` 分组只展示服务端 report skill pipeline allowlist，不扫描本地 `.codex/skills`。
- [ ] Skill 卡片包含 skill / pipeline id、描述、适用报告场景、readiness、来源与引用。
- [ ] 连接器卡片展示 Plan 15 readiness、准入策略摘要、来源牌；调用走 `POST /agent-exec/runs`，配置跳转 `/tools`。
- [ ] 补充测试：Skill 页面只显示服务端 allowlist，不出现本地任意 Skill 扫描结果；连接器卡片来源标注覆盖外部服务与 Codex；Plan 15 未稳定时占位正常。

### P16-D. 用户与邀请码管理 UI

- [ ] 在 `/admin` 增加“用户与邀请码”页签，复用既有 `/admin/users`、`/admin/invite-codes`、`PATCH /admin/users/{user_id}/status` 接口。
- [ ] 用户列表展示 username、real_name、organization、role、status；支持禁用 / 启用非 admin 用户。
- [ ] 邀请码列表展示、创建、禁用；显示最近登录与创建时间（字段存在时）。
- [ ] MVP 权限模型保持 `admin / user` 两角色，不做角色随意变更。
- [ ] 补充前端测试：admin 可管理，普通用户不可进入管理操作；操作复用既有 API 权限测试。

### P16-E. 来源标注与文档同步

- [ ] 更新来源矩阵：新增能力中心聚合视图条目，明确各能力来源仍归属原模块，能力中心只做展示。
- [ ] 来源标注覆盖外部服务、Codex、报告 Skill、算法工具和 LLM Provider。
- [ ] 更新 `doc/README.md` 索引与用户指南。
- [ ] 明确非目标：不实现插件市场、浏览器连接器、任意 OAuth 安装或本地 Skill 动态加载。
- [ ] 在文档中明确 `/tools`（配置中心）与 `/capabilities`（能力中心）的职责分工与数据单向流动。

## 9. 测试计划

### 9.1 后端测试

```bash
conda run -n poly_agent python -m pytest \
  backend/tests/test_capability_catalog_service.py \
  backend/tests/test_capabilities_api.py -q
```

覆盖：

- capability catalog 聚合结果与各模块 readiness 一致。
- catalog 按 agent 调用语义分组，不混入配置分组。
- 某模块不可用时 catalog 不阻断，标记 unavailable。
- catalog 不返回 secret、workdir、完整 prompt 或未脱敏配置。
- `/admin` 用户与邀请码操作复用既有 API 权限测试。
- admin 可管理，普通用户不可进入管理操作。

### 9.2 前端与 E2E

- 执行 `cd frontend && npm run build` 与相关 `assistant` / `tools` / `capabilities` 前端测试。
- `/capabilities` 与 `/tools` 为两个独立页面，不共享视图组件配置面。
- 能力卡片调用跳转到正确模块 API，配置跳转 `/tools`，不出现第二套状态源。
- Skill 页面只显示服务端 allowlist，不出现本地任意 Skill 扫描结果。
- 来源标注覆盖外部服务、Codex、报告 Skill、算法工具和 LLM Provider。
- admin 可见全部能力 + 发起调用 + 管理用户与邀请码；user 只看可调用能力，被拒绝管理操作。
- Plan 15 未稳定时 `agent_connectors` 分组占位正常，不阻断其他分组。

## 10. 兼容与迁移策略

- `/tools` 保持现有路由与 tab 不变，只收窄定位为配置中心，旧链接全部可用。
- 新增 `/capabilities` 路由与视图，不影响现有 `/tools` 行为。
- catalog 只读消费各模块既有接口，模块升级时 catalog 自动反映新状态，无需数据迁移。
- Plan 15 未稳定时，`agent_connectors` 分组占位，待 Plan 15 `GET /agent-exec/providers` 稳定后接入。
- 用户与邀请码 UI 复用既有接口与数据模型，无后端迁移。
- `/tools` 页面顶部引导链接为增量改动，不影响现有功能。

## 11. 风险与规避

| 风险 | 影响 | 规避 |
| --- | --- | --- |
| 两个入口职责混淆 | 用户不知道去哪配 / 去哪看能力 | 明确分工表写入文档与页面引导；配置跳 `/tools`，看能力跳 `/capabilities` |
| 能力中心被当成配置面 | 用户尝试在能力中心改配置 | 能力中心不内嵌配置表单，修改一律跳转 `/tools`；卡片只展示准入摘要 |
| 聚合视图与各模块状态不一致 | 用户看到过期或矛盾的状态 | catalog 只读实时聚合，不缓存权威状态；卡片操作走原模块 API |
| 统一写代理导致权限语义被二次实现 | 越权或绕过模块策略 | 不提供配置写代理；能力中心只可发起调用走原模块 API |
| Skill 目录被误解为插件市场 | 用户期望上传任意 Skill 或扫描本地 | 只展示服务端 allowlist；非目标写入文档与来源矩阵 |
| Plan 15 未稳定即接入连接器分组 | 聚合到不存在的接口 | 连接器分组先占位，Plan 15 API 稳定后接入 |
| 用户管理 UI 引入角色随意变更 | 破坏两角色权限模型 | MVP 只允许禁用 / 启用非 admin 用户，不做角色变更；细粒度授权另立 Plan 17 |

## 12. 完成定义

- [ ] `GET /capabilities/catalog` 返回 `dialogue_tools`、`agent_connectors`、`report_skills`、`llm_capabilities` 分组，且聚合结果与各模块 readiness 一致。
- [ ] `/capabilities` 独立路由与 `CapabilityCenterView.vue` 可用，按 agent 调用语义分组，与 `/tools` 配置中心职责分离、不复用页面。
- [ ] 能力卡片展示 readiness、准入策略摘要、来源牌；调用走原模块 API，配置跳转 `/tools`，无第二套状态源。
- [ ] `/tools` 收窄为配置中心，页面顶部引导至 `/capabilities`，现有配置功能不回退。
- [ ] Skill 页面只显示服务端 allowlist，不出现本地任意 Skill 扫描结果。
- [ ] `/admin` 用户与邀请码页签可用，admin 可管理，普通用户不可进入管理操作。
- [ ] MVP 权限模型保持 `admin / user` 两角色，未引入角色随意变更或细粒度授权矩阵。
- [ ] 来源标注覆盖外部服务、Codex、报告 Skill、算法工具和 LLM Provider。
- [ ] catalog 不返回 secret、workdir、完整 prompt 或未脱敏配置。
- [ ] 文档、用户指南、来源矩阵和 `doc/README.md` 索引同步更新，明确两入口分工。

## 13. 状态记录

- 2026-08-27：从 Plan 15 修订拆分新建统一能力中心与权限治理计划；本次仅编写文档，未修改业务代码。
- 2026-08-27（第二版修订）：明确能力中心 `/capabilities` 与工具服务 `/tools` 为两个独立入口，不复用页面；`/tools` 收窄为配置中心，`/capabilities` 新建为 Agent 能力调用目录；数据单向流动，配置面与调用面分离。本次仅修改文档。
