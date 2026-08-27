# Plan 15：受控外部 Agent 执行 Provider Seam 与 Agent 连接器治理工作计划

> 状态：MVP 已完成（P15-A–P15-G 已落地并通过专项与回归测试）；2026-08-28 复核新增 P15-H 生产化收口（未开始）
>
> 日期：2026-08-19（初稿）；2026-08-27（修订：新增 Agent 连接器治理，统一能力入口拆分至 Plan 16）；2026-08-28（复核：补齐配置 / API / 数据生命周期契约，新增 P15-H）
>
> 前置文档：
> - [research-engine-plan-09-lui-execution-trace.md](research-engine-plan-09-lui-execution-trace.md)
> - [research-engine-plan-10-slash-command-and-agent-control-workplan.md](research-engine-plan-10-slash-command-and-agent-control-workplan.md)
> - [research-engine-plan-12-product-positioning-evolution.md](research-engine-plan-12-product-positioning-evolution.md)
> - [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md)
>
> 拆分说明：本计划承接 Plan 12 的 `agent_exec` 外部执行 provider seam；Plan 12 只保留“材料研发领域工作台、通用 harness 可替换但不绑定”的产品定位。
>
> 修订说明（2026-08-27）：参考 Manus 的连接器交互模式，把 Codex 这类受控外部 Agent 在产品语义上呈现为“Agent 连接器”，补齐连接器卡片、调用策略、角色限制、确认执行、readiness、run 管理和审计；明确“参考 Manus 的连接器交互模式，但不复制其市场、浏览器连接器或插件生态”。全局“连接器 + Skill + Agent + 权限管理”大入口的范围超过本计划外部执行安全内核，拆分至 [Plan 16：统一能力中心与权限治理](research-engine-plan-16-capability-center-and-permission-governance-workplan.md)。
>
> 复核说明（2026-08-28）：对照后端实现、专项测试、前端纯函数测试、用户指南与来源矩阵复核本计划。P15-A–P15-G 的安全内核、默认关闭行为和回归结论保持有效；同时确认存在 workdir 数据保留、重启恢复、并发配额、取消终态竞态、审计失败降级、Mongo 索引接线、CLI 版本记录等生产化缺口，统一纳入 P15-H 跟踪，不回滚已验收内容。

## 1. 摘要

PolyAgent 不自研或引入通用 agent harness，而是为 Codex / PI / DSH 这类外部执行能力提供统一的受控 provider seam。该 seam 只允许处理显式声明输入、输出和授权范围的文件型任务，不允许暴露通用 Shell、任意文件读写、任意网络访问或插件市场。在产品侧，该 seam 以“Agent 连接器”视图呈现：每个受控外部 Agent 是一张连接器卡片，附带 readiness、调用策略、角色限制、确认要求和来源标注。

目标链路：

```text
显式任务与输入清单 → readiness / policy 校验 → 独立受限 workdir
                   → 外部 provider 执行 → 输出与 artifact 校验
                   → audit / trace / 结果回填 → provider 缺失时走既有兜底
```

MVP 只实现 provider 契约、连接器策略治理、执行服务、Codex 适配器和后端管理接口；PI / DSH 仅保留接口兼容评估，不在本期接入。

## 2. 目标与非目标

### 2.1 目标

- 定义 `AgentExecProvider`、readiness、任务类型、受限 workdir、超时、取消和结果契约。
- 建立 provider registry：平台启动不依赖任何外部 agent，provider 缺失只返回 unavailable，不影响核心链路。
- 实现独立执行服务：输入 allowlist、路径边界、大小限制、输出扫描、超时、取消和失败兜底。
- 将执行请求、readiness、开始、结束、取消、失败和 artifact 清单写入现有 Audit；带会话上下文时进入 Plan 09/10 Trace。
- 以 Codex 作为首个受控适配器，仅支持显式输入文件和结构化输出，不暴露通用工具面。
- 新增“Agent 连接器”产品视图：连接器卡片展示 readiness、支持任务类型、sandbox 摘要、来源标注；管理员可配置调用策略，普通用户受策略限制。
- 提供连接器策略治理：默认关闭、默认 admin-only、默认强制确认，策略持久化并写入审计。
- 提供管理员 readiness / run 查询与策略管理 API，并在现有 `/tools` 增加最小连接器入口（不做全局大入口）。

### 2.2 非目标

- 不把 PolyAgent 做成通用 coding agent、通用 Shell 工具或插件市场。
- 不引入 Cordis、DSH TypeScript runtime 或 PI Agent 运行时依赖。
- 不允许外部 provider 访问项目根目录、数据库、凭据、SSH 配置或未列入 allowlist 的文件。
- 不把 provider 失败自动升级为任意本地命令执行；失败只能返回结构化错误或回退到既有服务路径。
- 不在本期实现 PI / DSH 适配器、多租户配额。
- 不做类似 Manus 图 1 的全局“连接器 + Skill + Agent + 权限管理”大入口；该入口横跨外部服务集成、算法工具、报告 Skill、LLM Provider 与用户管理，拆分至 Plan 16。
- 不做客户端动态注册连接器、上传插件、声明任意网络访问能力或插件市场。
- 不把 `agent_exec` 并入现有 `IntegrationServiceKey` 字面量；两者健康检查、凭据边界和调用语义不同，Plan 16 后续只做聚合展示，不合并事实源。
- 不替代现有 ReportProviderRegistry 的报告生成链路；报告场景仅在边界一致时评估复用。

## 3. 当前基线

| 能力 | 当前状态 | 差距 |
| --- | --- | --- |
| Codex 报告生成 | `report_providers/codex_exec.py` 可用 `codex exec --json` 生成结构化报告，并已有超时、临时目录和 JSON Schema 校验 | 只服务报告，不提供通用 `agent_exec` 契约、readiness API、输入 allowlist 或 run 状态 |
| Provider 缺省 | ReportProviderRegistry 按请求实例化，provider 缺失不阻断应用启动 | 尚无 `agent_exec` 的统一 unavailable 语义 |
| 权限与确认 | Plan 10 已有 Permission Mode、Plan Mode、Goal / Todo 和审批状态 | `agent_exec` 尚未接入这些控制面；尚无连接器策略治理 |
| Trace / Audit | Plan 09/10 已有 append-only 事件、Trace 投影与 AuditEventRepository | 外部执行 run 尚无事件契约和回放 |
| 安全边界 | 报告 provider 使用临时目录和环境变量过滤 | 尚无任务级 workdir、输入输出扫描、大小限制和取消语义 |
| 连接器视图 | 现有 `/tools`（`ToolServicesView.vue`）已集成外部服务、LLM 模型与算法工具 | 尚无“Agent 连接器”区域与策略治理 UI |
| 来源标注 | `AttributionService` 与来源矩阵已覆盖主要模块 | 尚未登记 Codex 作为外部执行 provider 的来源与边界 |

## 4. 概念与边界

### 4.1 Agent 连接器视图语义

- 保留 `AgentExecProvider` 作为后端执行适配器语义；新增产品侧“Agent 连接器”视图语义。
- MVP 中 `connector_id = provider_id`，首个连接器仅为 `codex`。
- 连接器目录由服务端配置和代码注册，禁止客户端动态注册连接器、上传插件或声明任意网络访问能力。
- 不把 `agent_exec` 并入现有 `IntegrationServiceKey` 字面量；两者健康检查、凭据边界和调用语义不同。Plan 16 后续只做聚合展示，不合并事实源。
- 参考 Manus 的连接器交互模式（卡片化展示、调用策略、确认执行），但不复制其插件市场、浏览器连接器或任意 OAuth 连接器安装生态。

### 4.2 与 Plan 16 的边界

- Plan 15 交付受控 Agent 连接器的执行安全内核与连接器管理 API。
- Plan 16 把现有 `/tools` 升级为能力中心，聚合展示连接器、Skill、算法工具与 LLM Provider，并在 `/admin` 补齐用户与邀请码管理 UI。
- Plan 16 只读消费 Plan 15 的 `GET /agent-exec/providers`，不代理写操作，不重建第二套 provider、policy 或 trace 事实源。
- Plan 16 可在 Plan 15 的 provider policy API 稳定后启动，但不阻塞 Plan 15 的 P15-A 到 P15-F。

## 5. Provider 契约与策略模型

### 5.1 核心接口

新增 `AgentExecProvider` Protocol：

```python
class AgentExecProvider(Protocol):
    """受控外部 Agent 执行 Provider 契约。"""

    provider_id: str
    display_name: str
    supported_task_types: set[str]

    def readiness(self) -> AgentExecProviderReadiness:
        """检查二进制、配置、沙箱参数和任务支持情况，不产生副作用。"""

    def execute(self, request: AgentExecExecutionRequest) -> AgentExecProviderResult:
        """在受限 workdir 中执行显式文件型任务并返回结构化结果。"""
```

### 5.2 任务类型

| task_type | 输入 | 输出 | MVP |
| --- | --- | --- | --- |
| `structured_file_task` | prompt、显式输入文件 allowlist、JSON Schema | 结构化 JSON 与可选 artifact | 是 |
| `report_file_task` | 报告上下文文件与输出 Schema | 报告 JSON / Markdown / Artifact | 仅评估复用 |
| `authorized_lab_task` | 未来实验系统授权凭据与任务清单 | 系统回执与状态 | 否 |

任务类型必须在注册表中显式声明；未知类型直接拒绝，不做自由文本能力推断。

### 5.3 安全不变量

- 默认关闭：未配置 `AGENT_EXEC_ENABLED=true` 时 provider 持续返回 unavailable，LUI 不暴露工具，管理 API 只展示不可用状态与原因。
- 独立 workdir：每次 run 使用 `AGENT_EXEC_WORKDIR_ROOT/{run_id}`，不复用报告临时目录。
- 输入 allowlist：只复制调用方显式声明的文件；解析 symlink 后仍必须在受管目录内。
- 输出边界：provider 输出、artifact 和日志必须留在 run workdir，路径穿越直接失败。
- 资源限制：单文件、总输入、总输出、文件数和超时都有上限；超限即取消并清理可执行产物。
- 环境最小化：只传入 provider 必需的环境变量；不默认继承数据库、对象存储和云厂商凭据。
- 审计优先：无论成功失败，都记录 provider、task_type、input manifest、workdir、耗时、输出清单、错误码和 actor。
- 缺省 fallback：provider 不可用时不阻断应用启动；调用方收到结构化 unavailable，并可继续走既有非外部 Agent 路径。

### 5.4 连接器治理契约

在 `agent_exec` schema 中新增连接器治理契约：

- `AgentExecProviderPolicy`
  - `provider_id`
  - `enabled: bool = false`
  - `allowed_task_types: list[str]`，默认仅 `structured_file_task`
  - `allowed_roles: list[Literal["admin", "user"]]`，默认 `["admin"]`
  - `requires_confirmation: bool = true`
  - `updated_by` / `updated_at`
- `AgentExecProviderConnection`
  - provider 元数据、display name、readiness、配置来源、支持任务类型、sandbox 摘要、unavailable 原因、policy、attribution。
- 策略持久化到 `agent_exec_provider_policies`，兼容 SQLite 与 Mongo。
- 服务端调用校验顺序固定为：
  1. 用户角色在 `allowed_roles`
  2. provider policy enabled
  3. task_type 在 provider 支持列表和 policy allowlist
  4. provider readiness 通过
  5. Plan 10 Permission Mode / Plan Mode / 确认状态机通过
  6. 输入 allowlist 与资源限制通过
- 新增审计事件：
  - `agent_exec.policy.updated`
  - `agent_exec.policy.rejected`
  - 保留原 `agent_exec.*` 生命周期事件。

### 5.5 配置基线（MVP）

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENT_EXEC_ENABLED` | `false` | 全局开关；关闭时 provider readiness 返回 unavailable，LUI 不暴露工具，管理 API 只展示不可用状态与原因 |
| `AGENT_EXEC_WORKDIR_ROOT` | runtime 下 `agent_exec` | run 专属 workdir 根目录；run 目录以服务端 `run_id` 命名并使用 `0700` 权限 |
| `AGENT_EXEC_TIMEOUT_SECONDS` | `600` | 单 run 全局超时上限；实际生效值取请求超时与全局上限的较小值 |
| `AGENT_EXEC_MAX_INPUT_BYTES` | `10 MiB` | 同时约束单文件与总输入大小 |
| `AGENT_EXEC_MAX_OUTPUT_BYTES` | `10 MiB` | 约束输出总大小 |
| `AGENT_EXEC_MAX_FILES` | `20` | 同时约束输入文件数与输出 artifact 数 |
| `AGENT_EXEC_CODEX_BIN` | `codex` | Codex CLI 二进制名称或路径，仅做静态存在性与可执行位检查 |
| `AGENT_EXEC_CODEX_SANDBOX_MODE` | `read-only` | MVP 仅允许 `read-only`，其他模式 readiness 直接 unavailable |
| `AGENT_EXEC_CODEX_API_KEY` | 空 | 只允许环境变量 / 密钥引用；缺省可回退读取既有 `CODEX_API_KEY`，不得进入前端或审计 |
| `AGENT_EXEC_CODEX_MODEL` | 空 | 可选模型配置；与 API key 共同构成凭证判断 |

配置约束：

- secret 只允许通过环境变量或密钥引用注入；连接器卡片与 run 详情只展示脱敏 `config_source` 摘要。
- 数值与路径配置目前依赖 Python 类型转换，缺少统一范围校验；非法值可能在配置加载阶段抛错。配置健壮化纳入 P15-H。
- 生产环境必须启用统一认证；本地免认证 demo 模式下，后端按 `system / admin` 语义处理操作者，不能作为多用户生产配置。

## 6. 目标架构

```text
backend/app/schemas/agent_exec.py
  ├─ readiness / request / run / event / artifact schema
  └─ AgentExecProviderPolicy / AgentExecProviderConnection

backend/app/services/agent_exec_providers/
  ├─ base.py        # Protocol、错误与结果契约
  ├─ registry.py    # provider 注册、readiness 聚合、缺省 fallback
  └─ codex.py       # Codex MVP 适配器（含连接器元数据与 attribution）

backend/app/services/agent_exec_service.py
  ├─ 创建 run 与独立 workdir
  ├─ policy 校验（角色 / enabled / task_type / readiness / 确认 / allowlist）
  ├─ 复制 allowlist 输入并扫描输出
  ├─ 调 provider、处理超时/取消/失败
  └─ 写 Audit，携带 chat/tool 上下文时写 assistant event

backend/app/services/agent_exec_policy_service.py
  └─ 策略读取、更新、校验与 policy 快照

backend/app/infra/agent_exec_repositories.py
  └─ run / artifact / event / policy 的 Mongo 与 SQLite 双模存储

backend/app/api/v1/endpoints/agent_exec.py
  └─ 管理员连接器卡片、policy 更新、run 查询与取消 API
```

### 6.1 事件模型

`agent_exec_runs` 保存权威状态，`audit_events` 保存跨模块审计事实；带 `chat_id` 的调用同步写入现有 `assistant_events`，由 Plan 09/10 Trace 投影消费，不新增第二套 Trace。

| event_type | 时机 |
| --- | --- |
| `agent_exec.policy.updated` | 管理员更新 provider policy 后 |
| `agent_exec.policy.rejected` | 调用被 policy 校验拒绝时（记录拒绝原因摘要，不含敏感输入） |
| `agent_exec.requested` | 请求通过基础校验后 |
| `agent_exec.provider_ready` | readiness 通过 |
| `agent_exec.provider_unavailable` | provider 缺失、禁用或配置无效 |
| `agent_exec.started` | workdir 与输入准备完成，执行前 |
| `agent_exec.completed` | 输出与 artifact 校验完成 |
| `agent_exec.failed` | provider、schema、路径、资源或超时失败 |
| `agent_exec.cancelled` | 用户或系统取消 |

事件 payload 不记录完整 prompt、hidden reasoning、凭据和未脱敏环境变量。

### 6.2 API 与错误契约（MVP）

| API | 权限 | 语义 |
| --- | --- | --- |
| `GET /agent-exec/providers` | admin | 返回连接器卡片、readiness、policy、支持任务类型、sandbox 摘要、脱敏配置来源与 attribution |
| `PATCH /agent-exec/providers/{provider_id}/policy` | admin | 仅更新 `enabled`、`allowed_task_types`、`allowed_roles`、`requires_confirmation`，并写策略变更审计 |
| `POST /agent-exec/runs` | admin | 发起受控测试 run；请求必须显式 provider、task_type、prompt、输入清单、输出 Schema 与超时 |
| `GET /agent-exec/runs/{run_id}` | admin | 返回脱敏 run 权威状态、生命周期事件、policy 摘要和 artifact manifest |
| `POST /agent-exec/runs/{run_id}/cancel` | admin | 取消未结束 run；已终态 run 原样返回 |
| `GET /agent-exec/quality` | admin | 返回成功率、失败 / 取消 / unavailable / timeout 计数、输入输出字节数与平均耗时摘要 |
| `GET /agent-exec/lui-tool` | 登录用户 | 全部暴露条件满足时返回 LUI 工具描述符，否则返回 `null` |

稳定错误码按校验阶段分组：

| 阶段 | reason_code | 语义 / HTTP |
| --- | --- | --- |
| provider 解析 | `provider_not_registered` | provider 未注册，400 / 404 |
| 策略 | `role_not_allowed`、`provider_disabled`、`plan_mode_blocked`、`read_only_blocked`、`confirmation_required` | 403 |
| 策略 | `task_type_not_supported`、`task_type_not_allowed`、`task_types_empty`、`roles_empty` | 400 |
| readiness | `agent_exec_disabled`、`sandbox_mode_unsupported`、`codex_binary_missing`、`codex_binary_not_executable`、`credentials_missing` | 聚合为 `provider_unavailable`，503 |
| 输入 | `too_many_input_files`、`input_name_invalid`、`input_name_duplicate`、`input_source_not_found`、`input_symlink_rejected`、`input_hardlink_rejected`、`input_not_a_file`、`input_outside_managed_root`、`input_empty`、`input_too_large`、`input_total_too_large`、`input_hash_mismatch` | 400 |
| 输出 | `output_path_invalid`、`output_symlink_rejected`、`output_hidden_rejected`、`output_escape_rejected`、`output_executable_rejected`、`output_empty_rejected`、`output_too_many_files`、`output_too_large` | run failed |
| provider 执行 | `codex_spawn_failed`、`codex_nonzero_exit`、`output_missing`、`schema_mismatch`、`timeout`、`cancelled` | run failed / cancelled |
| run 查询 | `run_not_found` | 404 |

### 6.3 存储与数据生命周期（MVP 边界）

- 权威状态：`agent_exec_runs`；输出清单：`agent_exec_artifacts`；策略：`agent_exec_provider_policies`；跨模块审计：`audit_events`；带 `chat_id` 时镜像到 `assistant_events`。
- workdir 布局：`result.json`、`output.schema.json` 与显式 `artifacts/` 目录；run 目录 `0700`，执行结束后移除产物可执行位，违规输出删除整个 `artifacts/` 目录。
- 当前保留策略：run 终态后 workdir 不自动删除，输入、prompt 派生文件和输出会留在磁盘，需运维按安全策略手动清理；自动保留窗口、清理审计与磁盘加密要求纳入 P15-H。
- 复核备注：仓储层已定义 Mongo `ensure_indexes`，但尚未接入 `BaseRepository._ensure_indexes_once` 首访钩子或启动初始化；生产 Mongo 索引实际创建与唯一约束验证纳入 P15-H。

## 7. 分阶段任务

### P15-A. 契约、配置与 registry ✅

- [x] 新增 `backend/app/schemas/agent_exec.py`：
  - `AgentExecProviderReadiness`
  - `AgentExecTaskRequest`
  - `AgentExecExecutionRequest`
  - `AgentExecProviderResult`
  - `AgentExecRunData`
  - `AgentExecArtifactData`
  - `AgentExecProviderPolicy`（默认 `enabled=false`、`allowed_roles=["admin"]`、`allowed_task_types=["structured_file_task"]`、`requires_confirmation=true`）
  - `AgentExecProviderConnection`（provider 元数据、readiness、配置来源、sandbox 摘要、policy、attribution）
- [x] 新增 `backend/app/services/agent_exec_providers/base.py`，定义 Protocol、错误类型和结构化 unavailable 结果。
- [x] 新增 `backend/app/services/agent_exec_providers/registry.py`，支持按 provider_id / task_type 解析，并聚合 readiness。
- [x] 在 `backend/app/core/config.py` 增加：
  - `AGENT_EXEC_ENABLED`，默认 `false`
  - `AGENT_EXEC_WORKDIR_ROOT`，默认 runtime 下 `agent_exec`
  - `AGENT_EXEC_TIMEOUT_SECONDS`
  - `AGENT_EXEC_MAX_INPUT_BYTES`
  - `AGENT_EXEC_MAX_OUTPUT_BYTES`
  - `AGENT_EXEC_MAX_FILES`
- [x] registry 初始化不探测外部二进制，不抛异常，不阻断 FastAPI 启动。
- [x] 补充契约、默认禁用、未知 provider、未知 task_type 和缺省 unavailable 测试。

### P15-B. Codex MVP 适配器 ✅

- [x] 新增 `backend/app/services/agent_exec_providers/codex.py`，复用现有报告 provider 的 JSON Schema 处理经验。
- [x] readiness 检查：
  - `codex` 二进制存在且可执行；
  - `AGENT_EXEC_ENABLED=true`；
  - 受限 / 只读 sandbox 参数可用；
  - API key 或本地模型配置满足要求；
  - `structured_file_task` 已声明。
- [x] 执行时使用 run 专属 workdir，只传入 prompt、输入文件和输出 Schema。
- [x] 明确使用 Codex CLI 的受限 sandbox 模式；无法确认 sandbox 能力时 readiness 返回 unavailable，不得降级为无沙箱执行。
- [x] 捕获二进制缺失、非零退出、超时、输出缺失、JSON Schema 不匹配和环境配置错误。
- [x] 返回结构化 `stdout_digest` / `stderr_digest`，不保存完整无限长日志。
- [x] 声明连接器元数据：`provider_id="codex"`、`display_name`、支持任务类型、sandbox 摘要、配置来源（脱敏）、attribution（“执行能力来自 Codex CLI”）。
- [x] 补充 mock subprocess 测试：成功、缺二进制、非零退出、超时、schema 失败、sandbox 参数不支持。

### P15-C. 执行服务与安全边界 ✅

- [x] 新增 `backend/app/services/agent_exec_service.py`，统一创建 run、准备输入、调用 provider、校验输出和清理状态。
- [x] 新增 `backend/app/services/agent_exec_policy_service.py`，实现策略读取、更新、校验顺序（角色 → enabled → task_type → readiness → 确认 → allowlist）与 policy 快照。
- [x] run_id 使用服务端生成，禁止客户端指定或路径拼接。
- [x] 调用前按 5.4 节固定顺序做 policy 校验；任一步骤不通过返回结构化 unavailable / 403 / 400，并写 `agent_exec.policy.rejected`。
- [x] 输入文件必须来自服务端受管 artifact / 临时上传目录，逐个记录 path、size、sha256 和来源对象 ID。
- [x] 复制前解析 symlink 与 realpath，拒绝 workdir 外路径、目录逃逸、硬链接语义不确定的文件和超过限额的输入。
- [x] provider 输出只允许 JSON 结果文件和显式 artifact 目录；扫描路径穿越、symlink、隐藏文件、可执行位、空文件和总大小。
- [x] 超时后终止进程，run 标记 failed / timeout，保留脱敏事件与有限日志，清理可执行产物。
- [x] 支持服务端取消；已结束后取消返回稳定终态，不产生竞态覆盖。
- [x] provider unavailable 时不创建外部进程，返回结构化 unavailable，并允许调用方继续既有本地路径。
- [x] 补充边界测试：allowlist、路径穿越、symlink、大小、文件数、超时、取消、输出逃逸、输出超限、unavailable 和 policy 拒绝。

### P15-D. 存储、Audit 与 Trace 接入 ✅

- [x] 新增 `backend/app/infra/agent_exec_repositories.py`，提供 Mongo / SQLite 双模 run、artifact、policy 和事件查询。
- [x] 为 SQLite 初始化 `agent_exec_runs`、`agent_exec_artifacts`、`agent_exec_provider_policies` 及索引；Mongo 建立 run_id、provider_id、status、chat_id、created_by 和 created_at 索引。（复核备注：仓储已定义 Mongo `ensure_indexes`，但未接入首访 / 启动钩子，实际索引创建待 P15-H 验证。）
- [x] `agent_exec_provider_policies` 默认行为：无记录即视为 `enabled=false`、`allowed_roles=["admin"]`、`allowed_task_types=["structured_file_task"]`、`requires_confirmation=true`。
- [x] 每次执行写入第 6.1 节事件，并调用 `AuditEventRepository.append` 记录跨模块审计。
- [x] policy 更新写 `agent_exec.policy.updated`，记录 `updated_by`、变更前后摘要（不含 secret）。
- [x] 带 `chat_id` / `assistant_tool_call_id` 的调用写入现有 `assistant_events`，事件 metadata 记录 run_id、provider_id、task_type、policy 快照和 source。
- [x] 扩展 Plan 09 Trace 投影可识别 `agent_exec.*` 事件，但不复制 Trace 存储或新建前端事实源。
- [x] 事件内容脱敏：不记录 API key、完整环境变量、完整 prompt、hidden reasoning 和未授权用户数据。
- [x] 补充存储、owner 校验、事件顺序、policy 更新审计、失败终态、取消终态、审计字段和 Trace 投影测试。

### P15-E. 连接器管理 API 与最小可观测性 ✅

- [x] 新增 `backend/app/api/v1/endpoints/agent_exec.py` 并挂载到 v1 router。
- [x] `GET /agent-exec/providers`：返回管理员可见的连接器卡片、readiness、policy、task_type、attribution 和脱敏配置来源。
- [x] `PATCH /agent-exec/providers/{provider_id}/policy`：仅管理员更新 `enabled`、`allowed_task_types`、`allowed_roles`、`requires_confirmation`；不允许修改 secret、workdir 绝对路径、sandbox 参数或 provider 支持能力。
- [x] `POST /agent-exec/runs`：仅服务端内部调用和管理员受控测试；请求必须显式 task_type、provider_id、输入清单、输出 Schema 和超时，并受 policy 校验。
- [x] `GET /agent-exec/runs/{run_id}`：管理员查看脱敏 run 状态、事件、policy 判断摘要和 artifact manifest。
- [x] `POST /agent-exec/runs/{run_id}/cancel`：管理员取消未结束 run。
- [x] API 不返回 workdir 绝对路径、凭据、完整 prompt 或未脱敏环境。
- [x] 增加 run 成功率、unavailable、timeout、cancel、输入输出大小和耗时的质量摘要，先复用现有 metrics/quality 输出模式。
- [x] `allowed_task_types` 不能超过 provider 声明范围，越界返回 400。
- [x] 补充 API 测试：未登录、普通用户、管理员、provider 缺失、run 不存在、owner 越权、取消竞态和 policy 越界。

### P15-F. LUI 接入：默认关闭与受控暴露 ✅

将原“评估是否暴露”改为明确的默认关闭方案：

- [x] 默认不暴露给 `/dialogue`。
- [x] 仅当以下条件全部满足才暴露一个专用工具“外部 Agent 文件任务”：
  - provider readiness 通过；
  - policy enabled；
  - 当前角色在 `allowed_roles`；
  - `structured_file_task` 已允许；
  - Plan 10 确认状态机可用。
- [x] LUI 调用必须展示并让用户确认：provider / connector、task_type、输入文件清单与大小、输出 Schema、超时与输出限制。
- [x] 模型不能自动授权；未确认、只读权限、Plan Mode 中均不可执行。
- [x] 不做通用任务编排画布，不做自由 Shell 或任意文件路径输入。
- [x] 评估报告服务是否从 Codex ReportProvider 迁移到 `agent_exec`；只有安全边界和输出契约一致时才迁移，否则保留双路径并说明理由。
- [x] 输出 PI / DSH 接入评估：只比较 readiness、沙箱、artifact、超时、审计和凭据边界，不引入 runtime 依赖。
- [x] 更新用户指南和来源矩阵，明确外部 provider 是可选能力，不宣称 PolyAgent 绑定或复制这些产品。

#### P15-F 评估结论（2026-08-27）

**报告服务迁移决策：保留双路径。**

- `report_providers/codex_exec.py` 输入是对话消息列表、输出是报告 JSON，没有显式输入文件清单与 artifact 目录，与 `agent_exec` 的显式文件输入/输出契约不一致。
- 报告链路是核心能力，不能与默认关闭的连接器策略耦合；迁移会导致 provider 缺失时报告能力意外回退。
- 结论：报告服务继续使用 ReportProviderRegistry；`agent_exec` 服务于显式文件任务。待 Plan 16 统一能力中心完成后再评估是否收敛安全语义。

**PI / DSH 接入评估：本期不接入。**

| 验收维度 | 要求 |
| --- | --- |
| readiness | 服务端注册 + 配置/二进制静态检查，不执行探测命令、不阻断启动 |
| sandbox | 需证明与 Codex `--sandbox read-only` 等效的 OS 级/容器隔离；无法证明则 unavailable |
| artifact | 显式输出目录，路径穿越、symlink、隐藏文件、可执行位、空文件、大小与数量扫描 |
| timeout / cancel | 进程组终止、超时终态与服务端取消的稳定终态 |
| audit | 完整生命周期事件 + assistant trace 镜像 + 策略快照 |
| credentials | 最小环境变量/密钥引用，不继承数据库、对象存储与云厂商凭据 |

未通过以上验收的 provider 不注册进 registry，不引入 Cordis、DSH TypeScript runtime 或 PI Agent 运行时依赖。

### P15-G. 前端最小连接器入口 ✅

在现有 `ToolServicesView.vue` 增加“Agent 连接器”区域，不做全局大入口：

- [x] 展示 Codex 卡片：readiness / disabled / unavailable 状态与原因、支持 task_type、sandbox 与输入输出限制与超时摘要、最近 run 成功率与耗时摘要、“执行能力来自 Codex CLI”的 AttributionBanner。
- [x] 管理员可修改：启用 / 禁用、允许角色、允许任务类型、是否强制确认；表单走 `PATCH /agent-exec/providers/{provider_id}/policy`。
- [x] 管理员可发起受控测试，表单仍走 `POST /agent-exec/runs`，不得绕过服务端 policy。
- [x] 普通用户只能看到不可用原因或完全隐藏，不能看到 secret、workdir、完整 prompt 或环境变量。
- [x] 前端不缓存 policy 本地副本作为执行依据，所有执行判定以后端为准。
- [x] 补充前端测试：管理员可见卡片与 AttributionBanner、普通用户不可修改 policy、状态展示与后端一致。（复核备注：现有测试为 `agentConnectors` 纯函数测试；`ToolServicesView` 组件渲染与 E2E 待 P15-H。）

### P15-H. 生产化收口：保留策略、恢复、并发与审计可靠性 ⏳

2026-08-28 复核新增，未开始。本阶段不改变“默认关闭、admin-only、强制确认”的安全默认值，只补齐 MVP 之外的生产运行边界。

边界说明：P15-H 不阻塞 Plan 16 的只读能力聚合；Plan 16 若要在生产开放受控调用，应至少等待本阶段的回滚 runbook、单实例约束和终态竞态加固完成。

- [ ] 数据保留与清理：为 run workdir 增加保留窗口 / 数量上限配置，启动与周期任务清理终态 run 目录；清理动作写审计；明确磁盘加密、备份与敏感输入输出销毁要求，并补清理测试。
- [ ] 重启恢复：服务启动时把持久化非终态 run 标记为 failed / `restart_recovered`（或引入 orphan 状态），补齐事件与回放测试；在部署文档明确当前单实例约束。
- [ ] 多实例部署：active run 与取消状态支持跨进程（存储条件更新或分布式锁），或显式限制单 worker；补多实例行为说明与测试。
- [ ] 并发与资源配额：新增最大并发 run、排队或 429 语义、每用户限流；评估 CPU / 内存 / IO 或容器级隔离，补并发压力边界测试。
- [ ] 终态竞态加固：终态写入改为条件更新 / CAS，补充“取消后 provider 成功返回”竞态测试，确保 `cancelled` 不被 `completed` 覆盖。
- [ ] 审计可靠性：`requested` / `started` 事件写入失败时 run 标记 `audit_error` 并告警；审计事件记录真实 `actor_role`；补事件写入失败与恢复测试。
- [ ] Mongo 索引接线：把 `ensure_indexes` 接入仓储首访钩子或启动初始化，增加部署期索引验证；SQLite 与 Mongo 行为一致性测试。
- [ ] readiness 版本与出口验证：记录二进制路径 / 摘要与预期版本配置，提供管理员显式探测入口（与无副作用 readiness 分离）；验证所用 Codex 版本在 `read-only` sandbox 下的文件与网络出口行为并固化版本要求。
- [ ] 配置健壮性：数值、路径、布尔配置增加类型与范围校验；非法配置返回结构化诊断，且不破坏“默认关闭可启动”的承诺。
- [ ] 输入 TOCTOU 加固：校验后基于已打开文件描述符复制（如 `O_NOFOLLOW`），复制后复核 inode、大小与哈希，压缩来源被替换的窗口。
- [ ] 可观测性：新增 `GET /agent-exec/runs` 分页与 provider / status / 时间过滤；质量摘要支持时间窗与 provider 维度，消除固定 1000 条采样的统计偏差；为失败率、超时和 `audit_error` 增加告警。
- [ ] 测试与文档收口：补 `ToolServicesView` 组件测试与 E2E、显式开关的真实 Codex CLI 集成测试；同步用户指南与运维 runbook（取消竞态边界、保留策略、上线检查清单）。

## 8. 测试计划

### 8.1 后端单元与 API 测试

```bash
conda run -n poly_agent python -m pytest \
  backend/tests/test_agent_exec_contract.py \
  backend/tests/test_agent_exec_codex_provider.py \
  backend/tests/test_agent_exec_service.py \
  backend/tests/test_agent_exec_policy.py \
  backend/tests/test_agent_exec_events.py \
  backend/tests/test_agent_exec_api.py -q
```

覆盖：

- 默认禁用、provider 缺失、未知任务类型和启动不受影响。
- readiness 不产生副作用、不执行外部二进制。
- workdir、allowlist、路径、symlink、文件数、大小、超时和取消。
- JSON Schema、输出 artifact、日志摘要和错误终态。
- policy 默认禁用、默认 admin-only、默认仅 `structured_file_task`。
- 未知 provider、未知 task_type、角色不允许、policy disabled、readiness failed 均返回结构化 unavailable / 403 / 400。
- policy 更新仅 admin 可用，普通用户和未登录用户被拒绝。
- `allowed_task_types` 不能超过 provider 声明范围。
- policy 变更写 Audit，run 记录 policy 快照。
- Audit / assistant event 顺序、owner 权限、脱敏和 Trace 投影（policy rejected、requested、started、completed / failed / cancelled 可回放）。
- 连接器 API 不泄漏 secret、workdir、完整 prompt 和未脱敏环境。
- 管理 API 的 RBAC、错误响应和稳定终态。

### 8.2 回归测试

```bash
conda run -n poly_agent python -m pytest \
  backend/tests/test_report_providers.py \
  backend/tests/test_assistant_commands_api.py \
  backend/tests/test_assistant_command_events.py \
  backend/tests/test_assistant_trace_api.py \
  backend/tests/test_assistant_trace_projection.py -q
```

### 8.3 前端与 E2E

- P15-A–P15-F 不修改前端时仅需 `cd frontend && npm run build`。
- P15-G 新增连接器区域后，已补充 `agentConnectors` 纯函数测试；`ToolServicesView` 组件渲染与 E2E 待 P15-H。
- E2E 覆盖：provider unavailable 不影响 `/dialogue`；管理员可见 Codex 卡片与 AttributionBanner；普通用户不能修改 policy；授权、确认、执行、失败、取消和 Trace 回放；LUI 默认不可见，满足全部条件后仍须显式确认才执行。

## 9. 兼容与迁移策略

- 保持现有 `report_providers/codex_exec.py` 不变，直到 P15-F 证明迁移安全。
- 新配置默认关闭，不影响已有部署。
- 连接器默认关闭、默认 admin-only、默认强制确认。
- secret 只允许环境变量或密钥引用，不允许进入前端或配置摘要。
- 首版 API 仅管理员可访问，避免普通用户直接触发外部执行。
- 存储迁移必须兼容 SQLite demo 模式与 Mongo 部署模式。
- 事件类型进入 Plan 09/10 Trace 白名单时保持向后兼容；历史无 `agent_exec.*` 事件的回放结果不变。
- Plan 16 只读消费 `GET /agent-exec/providers`，不依赖 Plan 15 前端实现，可在 provider policy API 稳定后独立启动。

### 9.1 运维与回滚 runbook（MVP）

- 回滚方式：将 `AGENT_EXEC_ENABLED` 设为 `false`，并把目标 provider policy `enabled` 设为 `false`；无需数据迁移，既有 run、artifact manifest 与审计保留用于追溯。
- 上线前置检查：生产启用统一认证；为 `AGENT_EXEC_WORKDIR_ROOT` 规划独立磁盘、权限、加密与备份策略；确认 Codex CLI 二进制来源与版本；先用最小输入发起一次受控测试 run，再放开策略。
- 运行监控：关注 `/agent-exec/quality` 中失败率、timeout、unavailable 计数与平均耗时；发现异常时先禁用 policy，再排查 readiness 与审计事件。
- 当前运维边界：终态 run workdir 不会自动清理；服务重启后非终态 run 不会自动恢复；取消语义依赖当前进程内存状态。以上限制的收口见 P15-H。

## 10. 风险与规避

| 风险 | 影响 | 规避 |
| --- | --- | --- |
| Codex CLI sandbox 参数或网络出口行为变化 | 适配器误以为受控但实际可越界或外发数据 | MVP 仅允许 `read-only` 模式并做静态校验，不支持时 unavailable；版本记录、显式探测与出口验证纳入 P15-H |
| 文件 allowlist 来源过大 | 外部 provider 获得过多项目数据 | 只允许服务端受管 artifact / 临时上传，并做大小、数量和来源校验 |
| 输出隐藏路径或 symlink | artifact 逃逸 workdir | realpath + allowlist + 归档扫描；发现即 failed 并清理 |
| 与报告 provider 双路径混淆 | 同一外部能力出现两套安全语义 | P15-F 明确保留或迁移决策，并写入来源矩阵 |
| 事件写入失败但进程已执行 | 审计缺失或 run 状态中断 | MVP 依赖统一 Audit 仓储的既有兜底；`audit_error` 标记、告警与事件写入失败测试纳入 P15-H |
| 未来 PI / DSH 接入过快 | 引入不受控 runtime | 只做接口评估；未通过 sandbox/readiness/audit 验收不注册 provider |
| 策略误配导致越权执行 | 普通用户触发未授权外部执行 | 默认 admin-only + 强制确认 + 固定校验顺序；policy 变更写审计；前端不作为执行依据 |
| 前端泄漏敏感配置 | secret / workdir / 完整 prompt 暴露 | API 只返回脱敏摘要；普通用户隐藏或仅看不可用原因；前端不缓存 policy 作为执行判定 |
| 连接器视图被误解为插件市场 | 用户期望动态安装任意连接器 | 目录仅服务端代码注册；明确非目标写入文档与来源矩阵 |
| workdir 长期残留 | 输入、prompt 派生文件与输出滞留磁盘 | MVP 由运维手动清理；保留窗口、审计化清理与加密要求纳入 P15-H |
| 服务重启或多实例部署 | 非终态 run 悬挂、跨进程取消失效 | MVP 明确单实例约束；启动恢复与跨实例状态收口纳入 P15-H |
| 并发 run 过多 | CPU、内存、磁盘或外部配额耗尽 | MVP 依赖单 run 超时与文件大小限制；并发上限、排队与资源隔离纳入 P15-H |
| 取消与完成竞态 | `cancelled` 终态被迟到成功结果覆盖 | 现有测试覆盖“取消后 provider 抛出取消”的路径；补齐取消后成功返回的 CAS 测试纳入 P15-H |
| Mongo 索引未接线 | 查询退化或唯一约束缺失 | P15-H 接入仓储首访 / 启动初始化，并增加部署验证 |

## 11. 完成定义

### 11.1 MVP 完成定义（P15-A–P15-G）

- [x] 默认关闭时应用可启动，`/dialogue`、ResearchEngine、报告和算法工具回归不回退。
- [x] provider readiness、执行、超时、取消、失败和 unavailable 均有结构化语义和测试。
- [x] 输入输出始终限定在 run 专属 workdir，路径、大小、文件数和 symlink 测试通过。
- [x] 连接器策略默认关闭、默认 admin-only、默认强制确认，且策略变更写审计、run 记录 policy 快照。
- [x] Audit / assistant event / Trace 可完整回放一次成功、失败、取消、provider 缺失和 policy 拒绝场景。
- [x] 连接器管理 API 只对管理员开放，并返回脱敏信息；`allowed_task_types` 越界被拒绝。
- [x] 前端管理员可看到 Codex 卡片和 AttributionBanner；普通用户不能修改 policy，看不到 secret / workdir / 完整 prompt。
- [x] Codex MVP 不暴露通用 Shell、任意文件读写、任意网络和项目根目录。
- [x] LUI 默认不可见；满足全部条件后仍须显式确认才执行。
- [x] 文档、用户指南、来源矩阵和 `doc/README.md` 索引同步更新。

### 11.2 生产化追加验收（P15-H，未完成）

- [ ] 终态 run workdir 能按配置自动保留、清理并写审计；清理策略与加密要求有文档说明。
- [ ] 服务重启后非终态 run 进入稳定恢复终态；单实例 / 多实例约束有明确部署说明。
- [ ] 并发 run、排队或限流、每用户配额与资源隔离策略落地并有测试。
- [ ] 取消后迟到的成功结果不能覆盖 `cancelled`；终态条件更新有竞态测试。
- [ ] 审计写入失败可观测，run 能标记 `audit_error`，告警与恢复路径有测试。
- [ ] Mongo 索引随仓储首访或启动创建，并有部署验证方法。
- [ ] readiness 能记录版本 / 摘要，管理员显式探测与 sandbox 出口验证方案落地。
- [ ] 非法配置不会破坏默认关闭启动，并返回结构化诊断。
- [ ] 输入复制消除校验与复制之间的 TOCTOU 窗口，并有替换攻击测试。
- [ ] run 列表与质量摘要支持分页 / 过滤 / 时间窗，关键异常有告警。
- [ ] `ToolServicesView` 组件测试、E2E 与真实 CLI 集成测试补齐，用户指南和运维 runbook 同步更新。

## 12. 状态记录

- 2026-08-19：从 Plan 12 拆分 `agent_exec` provider seam，新增独立工作计划；未修改业务代码。
- 2026-08-27：修订计划，参考 Manus 连接器交互模式新增“Agent 连接器”产品视图与策略治理（P15-C/E/F/G 与契约 5.4、事件 6.1），并将全局能力入口拆分至 Plan 16；本次仅修改文档，未修改业务代码。
- 2026-08-27：完成 P15-A，新增 agent_exec 契约 schema、provider Protocol/错误契约、registry 与默认关闭配置，补充契约测试并通过。
- 2026-08-27：完成 P15-B，新增 Codex 受限 sandbox 适配器（readiness 不执行二进制）、结构化日志摘要与 mock subprocess 测试，P15-A/P15-B 共 16 项测试通过。
- 2026-08-27：完成 P15-C，新增策略治理服务（固定校验顺序与确认状态机）、受限执行服务（allowlist、路径/symlink/大小边界、输出扫描、超时取消与稳定终态），42 项相关测试通过。
- 2026-08-27：完成 P15-D，新增 agent_exec 双模存储与索引、统一 Audit/assistant 事件写入、策略更新审计、脱敏与 Plan 09 Trace agent_exec 步骤投影；存储/事件/Trace 测试与既有 Trace 回归通过。
- 2026-08-27：完成 P15-E，新增管理员连接器卡片、策略更新、受控 run、run 详情/取消与质量摘要 API，覆盖 RBAC、策略越界、结构化错误与稳定终态测试。
- 2026-08-27：完成 P15-F，LUI 默认不暴露外部 Agent 工具，新增全部条件满足才返回的 lui-tool 描述符与 API；完成报告双路径与 PI/DSH 接入评估，新增用户指南并更新来源矩阵与索引。
- 2026-08-27：完成 P15-G，ToolServicesView 新增管理员可见的 Agent 连接器页签：Codex 卡片（readiness/原因/sandbox/配置来源/质量摘要 + AttributionBanner）、策略表单与受控测试入口；普通用户隐藏，前端测试与构建通过。
- 2026-08-28：完成 P15-A–P15-G 收尾：专项测试 56 项（含 3 个子测试）与 Plan 8.2 回归 31 项全部通过；默认关闭配置下 FastAPI 应用导入与 agent-exec 路由挂载验证正常；完成定义全部勾选。
- 2026-08-28：复核计划与实现 / 测试 / 用户指南 / 来源矩阵的一致性：新增 5.5 配置基线、6.2 API 与错误契约、6.3 存储与数据生命周期、9.1 运维与回滚 runbook；修正 Mongo 索引、前端测试范围、readiness 版本记录和 audit_error 的表述；新增未开始的 P15-H 与 11.2 生产化追加验收。复核证据覆盖 `backend/app/schemas/agent_exec.py`、`agent_exec_service.py`、`agent_exec_policy_service.py`、`agent_exec_repositories.py`、`agent_exec_providers/*`、`api/v1/endpoints/agent_exec.py`、`backend/tests/test_agent_exec_*`、`ToolServicesView.vue`、`agentConnectors.test.mjs`、`agent-connector-user-guide.md` 与来源矩阵。本次仅更新文档，未修改业务代码。
