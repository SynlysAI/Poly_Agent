# Plan 17：工具服务统一入口、AI Ready 能力目录与 Agent 执行生产化整合工作计划

> 状态：已完成并关闭（统一入口、三分组 AI 能力目录、Agent 执行生产化、专项 / 全量回归、生产构建和 E2E 均已验收；真实结构化任务曾受外部模型网关 `/v1/responses` 404 阻塞，已记录为环境依赖而非代码待办）
>
> 日期：2026-09-07（创建、实施与最终收尾）
>
> 评审基线：`develop` 分支提交 `8e20fcd`。
>
> 前置文档：
> - [research-engine-plan-15-agent-exec-provider-seam-workplan.md](research-engine-plan-15-agent-exec-provider-seam-workplan.md)
> - [research-engine-plan-16-capability-center-and-permission-governance-workplan.md](research-engine-plan-16-capability-center-and-permission-governance-workplan.md)
> - [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md)
>
> 整合说明：本计划承接 Plan 15 P15-A–P15-G 之外的全部生产化收口项，并取代 Plan 16 的独立 `/capabilities` 入口目标态。Plan 15 与 Plan 16 的已完成验收事实不回滚；本文收尾后三个计划均关闭，后续新增问题另立变更或运维记录。

## 1. 摘要与决策

PolyAgent 的能力入口收敛到“工具服务”`/tools`。普通用户进入后只看到“AI 能力”页签，用于查看当前账号 AI Ready 的可调用能力并发起受控调用；管理员在同一入口按“状态、AI 能力、LLM 模型、Agent 连接器、算法清单、算法工具、服务配置”顺序使用统一页签。

核心决策：

- UI 导航仅保留“工具服务”，移除“能力中心”独立导航。
- `/capabilities` 保留为兼容重定向，指向 `/tools?tab=ai-ready`。
- AI 能力目录仅保留对话工具、外部 Agent 连接器和报告 Skill 三组。
- LLM 能力目录移除；LLM 配置仍在管理员“LLM 模型”页签，模型选择仍在对话内完成。
- AI 能力不出现配置表单、配置按钮或 `config_path`。
- 外部 Agent 连接器只在管理员“Agent 连接器”页签配置；AI 能力页签只做策略允许的展示、确认和调用。
- `agent_exec` 仍是外部执行安全内核、策略与审计事实源；AI 能力只读消费，不新建第二套事实源。

```text
/tools?tab=ai-ready（AI 能力）          /tools 管理页签
  对话工具目录       ← AgentToolService    LLM 模型 / Agent 连接器
  外部连接器调用     ← agent_exec policy   算法清单 / 算法工具
  报告 Skill 目录    ← 服务端 allowlist    状态 / 服务配置
```

## 2. 目标与非目标

### 2.1 目标

- 建立 `/tools` 统一入口：管理员看到状态、AI 能力、LLM 模型、Agent 连接器、算法清单、算法工具、服务配置七个页签，普通用户只看到 AI 能力。
- 精简 `GET /capabilities/catalog` 契约为三个固定分组，并移除 LLM 与配置跳转字段。
- 保持实时聚合、失败隔离、角色过滤、敏感信息脱敏和结构化来源标注。
- 将 `CapabilityCenterView.vue` 重构为可嵌入的 AI 能力模块。
- 普通 user 不触发管理员配置 API，也没有管理页签或配置入口。
- 承接 Plan 15 P15-H 的数据生命周期、恢复、资源隔离、告警、索引验证、readiness、配置校验、可观测性和真实 CLI 测试缺口。
- 同步计划、用户指南、来源矩阵、官网文档和 E2E 说明。

### 2.2 非目标

- 不做插件市场、浏览器连接器、任意 OAuth 安装或本地 `.codex/skills` 动态加载。
- 不把 AI 能力做成第二套配置面，不代理配置写操作。
- 不把 `/admin` 用户与邀请码治理并入工具服务。
- 不接入 PI / DSH runtime，不改变外部 Agent 默认关闭、默认 admin-only 和强制确认策略。
- 不把 LLM Provider 从“LLM 模型”管理页签迁走，不改变对话模型选择器。

## 3. 当前基线与差距

> 收尾说明：下表为 2026-09-07 创建计划时的基线；P17-A–P17-E 已全部完成，表中差距不再表示当前待办。

| 区域 | 当前状态 | Plan 17 差距 |
| --- | --- | --- |
| 前端入口 | 导航同时有 `/capabilities` 与 admin-only `/tools` | 需收敛为所有认证用户可用的 `/tools` 统一入口 |
| 能力目录 | `/capabilities/catalog` 返回四组，含 LLM 与 `config_path` | 需精简为三组并移除配置跳转 |
| AI 能力页面 | `CapabilityCenterView.vue` 是独立路由页面 | 需重构为 ToolServices 内嵌模块 |
| 工具服务 | 六个管理 tab 与连接器配置已可用 | 需增加 AI 能力 tab，调整为目标页签顺序，并按角色拆分加载 |
| Agent 执行 | P15-A–P15-G 与首轮 P15-H 安全加固已完成 | 数据保留、恢复、资源隔离、告警、版本探测等仍未收口 |
| 文档与 E2E | 用户指南和 E2E 仍验证独立 `/capabilities` | 需按统一入口与三分组目标同步更新 |

## 4. 分阶段任务

### P17-A. 能力目录契约精简

- [x] 修改 `CapabilityCatalogData`、分组 ID 和 invocation kind，仅保留 `dialogue_tools`、`agent_connectors`、`report_skills`。
- [x] 移除 `llm_capabilities`、`llm_model` invocation kind 和能力卡片 `config_path`。
- [x] 移除 catalog 服务对 LLM 目录的依赖，保持 `GET /capabilities` 旧 readiness 行为不变。
- [x] 更新后端服务与 API 测试，覆盖三分组、角色过滤、失败隔离、脱敏和无配置字段。

### P17-B. 工具服务统一入口

- [x] 新增可嵌入的 AI 能力模块，例如 `CapabilityCenterPanel.vue`。
- [x] `ToolServicesView.vue` 增加 `ai-ready` 页签并置于“状态”之后；admin 与 user 均可访问。
- [x] 页签按“状态、AI 能力、LLM 模型、Agent 连接器、算法清单、算法工具、服务配置”排列，管理员无 tab 参数时默认进入“状态”。
- [x] `/tools` 路由移除整体 admin-only；普通 user 访问管理 tab query 时回落到 `ai-ready`。
- [x] `/capabilities` 重定向到 `/tools?tab=ai-ready`；导航移除“能力中心”，所有用户显示“工具服务”。
- [x] 拆分数据加载：AI 能力只调用 catalog 与来源 API；管理 API 只在 admin 页签场景调用。
- [x] 保留六个管理 tab key 与功能，移除跨页“查看能力中心”跳转。
- [x] 更新前端纯函数测试、路由验证和响应式布局。

### P17-C. 重叠功能治理

- [x] 算法清单继续作为注册事实源，算法工具继续作为派生治理面，AI 能力只展示可调用目录并跳转对话。
- [x] 管理员 Agent 连接器页签保留 policy、readiness、质量摘要、受控测试与来源标注。
- [x] AI 能力连接器卡片仅保留状态、策略摘要、显式确认调用与来源牌，不提供配置动作。
- [x] 报告 Skill 仅展示服务端 pipeline allowlist。
- [x] 移除 AI 能力中的 LLM provider / model 卡片，保留管理页签与对话模型选择器。
- [x] 保持 `/admin` 用户与邀请码治理独立，不改变 providers/runs 权限与响应脱敏规则。

### P17-D. Agent 执行生产化收口

- [x] 数据保留与清理：增加保留窗口与数量上限配置，启动和周期任务清理终态 run workdir，清理写审计，并说明加密、备份与销毁要求。
- [x] 重启恢复：启动时把持久化非终态 run 恢复为稳定失败终态，补事件与回放测试。
- [x] 多实例约束：落地跨进程终态 CAS 或分布式锁；若维持单实例，则在部署文档和启动诊断中显式约束。
- [x] 资源隔离深化：落地 CPU / 内存 / IO 或容器级隔离策略，并补并发压力测试。
- [x] 审计恢复：为 `audit_error` 提供外部告警接入、补写与排查 runbook。
- [x] 部署索引验证：执行目标环境 Mongo 索引初始化与核对，补 SQLite / Mongo 行为一致性测试。
- [x] readiness 深化：记录二进制版本 / 摘要，提供管理员显式探测入口，并验证 Codex `read-only` sandbox 出口行为。
- [x] 配置健壮性：数值、路径、布尔配置做类型与范围校验，非法配置返回结构化诊断且不影响默认关闭启动。
- [x] 可观测性深化：run 列表与质量摘要支持时间窗与 provider 维度，并为失败率、超时和 `audit_error` 提供告警。
- [x] 真实 CLI 测试：补显式开启的 Codex CLI 集成测试，不用 mock 伪装真实链路。

### P17-E. 来源、文档与收尾

- [x] 更新能力中心用户指南、Agent 连接器指南、`doc/README.md`、根 README 与官网功能文档。
- [x] 更新来源矩阵中 AI 能力路径，移除 LLM 目录描述，保留 Codex、算法与报告 provider 来源。
- [x] 更新 `AttributionService` 的 `capability_center` 页面路径，继续使用结构化来源数据。
- [x] 更新 E2E 脚本与说明，验证统一入口、角色差异、兼容跳转、响应式与 console。
- [x] 同步 Plan 15、Plan 16 与本文状态记录；每完成一项勾选对应任务。

## 5. 测试计划

### 5.1 后端专项与回归

```bash
conda run -n poly_agent env PYTHONPATH=backend python -m pytest \
  backend/tests/test_capability_catalog_api.py \
  backend/tests/test_agent_exec_production.py \
  backend/tests/test_agent_exec_codex_integration.py \
  backend/tests/test_agent_exec_api.py \
  backend/tests/test_agent_exec_policy.py \
  backend/tests/test_agent_exec_service.py \
  backend/tests/test_agent_exec_events.py -q
make test-backend
```

覆盖：

- catalog 三分组结构、字段与来源映射。
- admin/user 视角差异、失败隔离、敏感信息脱敏、无 `config_path`。
- user 默认不可见连接器；显式授权后可见，未确认不能调用。
- P17-D 新增清理、恢复、配置校验、readiness、索引一致性与可观测性行为。

### 5.2 前端与构建

```bash
npm --prefix frontend run test:capability-center
npm --prefix frontend run test:agent-connectors
npm --prefix frontend run build
```

另需运行前端既有全部 `test:*` 脚本，确认 `/dialogue`、算法工具、模型选择和助手链路不回退。

### 5.3 E2E

- 更新 `capability_admin_e2e.py`：
  - admin 打开 `/tools?tab=ai-ready`，可见三组能力、六个管理页签、连接器配置和来源牌，并断言完整页签顺序为“状态、AI 能力、LLM 模型、Agent 连接器、算法清单、算法工具、服务配置”。
  - user 只见 AI 能力；直接访问管理 tab query 自动回落，无管理 API 请求和 console error。
  - `/capabilities` 跳转到 `/tools?tab=ai-ready`。
  - 320px / 768px / 1440px 无横向溢出。
- 运行 `make test-e2e`。

## 6. 兼容与迁移策略

- `/capabilities` 保留 SPA 内部重定向，不产生 404。
- 原有六个管理 tab key 保持不变，旧深链继续可用。
- `/capabilities/catalog` 移除 LLM 分组与 `config_path` 是明确的产品契约变更，同步更新测试与文档。
- `/tools/alchemist` 公共算法入口保持不变。
- 本地演示模式未启用认证时按管理员视角展示；认证模式下以服务端角色为准。
- Plan 15 已完成安全内核不回滚；本计划只做入口整合、目录精简和生产化补齐。

## 7. 风险与规避

| 风险 | 影响 | 规避 |
| --- | --- | --- |
| AI 能力被误解为配置面 | 形成第二状态源 | 移除 `config_path` 与配置动作，只保留调用入口 |
| 普通 user 进入 `/tools` 后越权 | 泄漏管理数据或触发管理 API | 页签服务端权限不变，前端按角色拆分加载，E2E 断言无管理请求 |
| 移除 LLM 分组影响调用预期 | 用户误以为 LLM 不可用 | 指南明确模型选择在对话内，配置在管理员 LLM 模型页签 |
| 连接器调用入口重复配置语义 | 策略事实源漂移 | AI 能力只读消费 policy，执行仍由 agent_exec 服务端校验 |
| P17-D 引入过重基础设施 | 上线复杂度上升 | 优先显式单实例约束和安全默认值；多实例能力按部署模式增量启用 |
| 真实 CLI 测试依赖外部网关 | 验收被外部凭证阻塞 | 测试显式开启；凭证不可用时记录外部阻塞，不用 mock 伪装通过 |

## 8. 完成定义

- [x] 导航仅有一个“工具服务”入口；admin/user 分别看到正确页签集合。
- [x] `/capabilities` 兼容跳转有效，`/tools/alchemist` 不回退。
- [x] catalog 仅返回三组能力，不含 LLM 分组、`config_path` 或 `llm_model`。
- [x] AI 能力无配置表单与配置按钮；来源标注完整且使用结构化数据。
- [x] 普通 user 默认看不到连接器；显式授权后可见，未确认不能调用。
- [x] 普通 user 打开工具服务不触发管理 API 请求，也无 console error。
- [x] P17-D 全部生产化任务落地或有明确部署约束与验收记录。
- [x] 后端专项、后端回归、前端全量、生产构建和 E2E 全部通过。
- [x] Plan 15、Plan 16、本文、用户指南、来源矩阵和文档索引同步更新。

## 9. 状态记录

- 2026-09-07：基于 `develop@8e20fcd` 新建整合计划。决策为工具服务统一入口、移除 LLM 能力目录、AI 能力无配置入口，并将 Plan 15 P15-H 剩余项全量迁移至本文跟踪。
- 2026-09-07（实施第一阶段）：完成 P17-A/B/C 与 P17-E 文档同步；能力目录契约、统一入口、AI 能力嵌入面板、连接器配置边界、来源标注和 E2E 说明已更新。能力目录 API 5 项、前端能力目录 4 项、Agent 连接器 5 项和生产化专项测试通过。
- 2026-09-07（生产化实施）：完成 workdir 保留清理、重启恢复、单进程约束、CPU / 内存 / 输出文件 RLIMIT、审计补写与外部告警、时间窗 / provider 可观测性、配置健壮性、二进制摘要与显式探测，并新增显式开启的真实 Codex CLI 集成测试。真实 CLI 测试当前未开启，sandbox 出口实测仍保留未勾选；目标 Mongo 索引验证已在后续验证记录中完成。
- 2026-09-07（最终验证记录）：后端全量 1053 项通过 / 2 项跳过（其中真实 Codex CLI 集成测试按显式开关跳过）；前端全部 24 类 `test:*` 脚本通过；Vite 生产构建通过；本地 MongoDB 显式初始化并核对 `agent_exec_runs.run_id_unique`、`agent_exec_artifacts.run_path_unique`、`agent_exec_provider_policies.provider_id_unique` 均存在；重启后能力 / 权限 E2E 通过。`make test-e2e` 中 dialogue E2E 在等待工具确认卡片时超时，重启后旧 run 事件显示 `llm.request.failed`，最终内容为“模型服务鉴权失败”，判定为外部模型凭证阻塞，不用 mock 伪装通过。
- 2026-09-07（页签顺序调整）：`/tools` 页签调整为“状态、AI 能力、LLM 模型、Agent 连接器、算法清单、算法工具、服务配置”，管理员无 tab 参数时默认进入“状态”，“配置”页签更名为“服务配置”；代码、E2E 断言和说明文档已同步。能力中心 4 项、Agent 连接器 5 项、LLM 模型测试、E2E 脚本语法检查和前端生产构建通过。
- 2026-09-07（readiness 收口）：Codex 显式探测新增最低版本门槛（默认 `0.149.1`）与 `version_supported` 结论，管理员卡片显示“最低版本 / 是否满足”；真实 `codex-cli 0.149.1` sandbox 集成测试验证 `read-only` profile 下 workdir 写入与仅监听 `127.0.0.1` 的本地 HTTP 出口均被拒绝。真实结构化任务链路已实际执行并暴露外部网关阻塞：本地模型配置指向 `/v1/responses`，网关返回 404“不支持的端点”，因此该子链路不能判为通过；同时修复 Codex 子进程 stdin 未关闭导致的误读附加输入，并把非零退出诊断合并 stdout / stderr 关键事件。
- 2026-09-07（最终回归收口）：修复 dialogue 工具确认的一个前端状态竞态——模型提议 run 失败后 SSE 可能替换消息对象，确认闭包更新旧引用导致后端已完成而卡片仍停留待确认；现在按 `message_id` 写回当前消息并补纯函数测试。真实 Codex 结构化任务的外部网关仍为 `/v1/responses` 404 阻塞，按要求不伪造通过。后端全量 1067 项通过 / 3 项跳过；前端全部 24 类 `test:*` 脚本与生产构建通过；`make test-e2e` 中 dialogue 真实模型链路、响应式、控制面、工作台与能力 / 权限 E2E 全部通过。
- 2026-09-07（默认入口回归修复）：工具服务初始页签恢复按角色计算：管理员点击导航进入 `/tools` 时直接选中“状态”，普通用户仍默认进入“AI 能力”；显式 `ai-ready` 深链保持可用。E2E 补充默认状态页断言，脚本语法检查、前端生产构建和本地浏览器点击验证通过。
- 2026-09-07（计划关闭）：确认 P17-A–P17-E 全部完成：`/tools` 是唯一工具服务入口，`/capabilities` 仅保留兼容跳转；AI 能力仅含对话工具、Agent 连接器与报告 Skill 三组；LLM 目录和配置跳转移除；普通用户默认无管理 API 请求；Agent 执行具备保留清理、重启恢复、单进程约束、RLIMIT、审计补写、外部告警、时间窗 / provider 观测和显式真实 CLI 集成测试。真实 Codex sandbox 出口实测通过；外部模型网关仍需在其支持 `/v1/responses` 或完成正确端点配置后重跑显式集成测试，该依赖不阻塞本计划关闭。日常体验见 `docs/tips/plan-15-17-tools-capability-agent-governance-experience-guide.md`。
