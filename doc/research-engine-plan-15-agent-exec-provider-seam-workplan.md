# Plan 15：受控外部 Agent 执行 Provider Seam 工作计划

> 状态：待评审 / 未开始
>
> 日期：2026-08-19
>
> 前置文档：
> - [research-engine-plan-09-lui-execution-trace.md](research-engine-plan-09-lui-execution-trace.md)
> - [research-engine-plan-10-slash-command-and-agent-control-workplan.md](research-engine-plan-10-slash-command-and-agent-control-workplan.md)
> - [research-engine-plan-12-product-positioning-evolution.md](research-engine-plan-12-product-positioning-evolution.md)
> - [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md)
>
> 拆分说明：本计划承接 Plan 12 的 `agent_exec` 外部执行 provider seam；Plan 12 只保留“材料研发领域工作台、通用 harness 可替换但不绑定”的产品定位。

## 1. 摘要

PolyAgent 不自研或引入通用 agent harness，而是为 Codex / PI / DSH 这类外部执行能力提供统一的受控 provider seam。该 seam 只允许处理显式声明输入、输出和授权范围的文件型任务，不允许暴露通用 Shell、任意文件读写、任意网络访问或插件市场。

目标链路：

```text
显式任务与输入清单 → readiness / policy 校验 → 独立受限 workdir
                   → 外部 provider 执行 → 输出与 artifact 校验
                   → audit / trace / 结果回填 → provider 缺失时走既有兜底
```

MVP 只实现 provider 契约、执行服务、Codex 适配器和后端管理接口；PI / DSH 仅保留接口兼容评估，不在本期接入。

## 2. 目标与非目标

### 2.1 目标

- 定义 `AgentExecProvider`、readiness、任务类型、受限 workdir、超时、取消和结果契约。
- 建立 provider registry：平台启动不依赖任何外部 agent，provider 缺失只返回 unavailable，不影响核心链路。
- 实现独立执行服务：输入 allowlist、路径边界、大小限制、输出扫描、超时、取消和失败兜底。
- 将执行请求、readiness、开始、结束、取消、失败和 artifact 清单写入现有 Audit；带会话上下文时进入 Plan 09/10 Trace。
- 以 Codex 作为首个受控适配器，仅支持显式输入文件和结构化输出，不暴露通用工具面。
- 提供管理员 readiness / run 查询 API，先不做普通用户直连入口。

### 2.2 非目标

- 不把 PolyAgent 做成通用 coding agent、通用 Shell 工具或插件市场。
- 不引入 Cordis、DSH TypeScript runtime 或 PI Agent 运行时依赖。
- 不允许外部 provider 访问项目根目录、数据库、凭据、SSH 配置或未列入 allowlist 的文件。
- 不把 provider 失败自动升级为任意本地命令执行；失败只能返回结构化错误或回退到既有服务路径。
- 不在本期实现 PI / DSH 适配器、前端任务编排界面和多租户配额。
- 不替代现有 ReportProviderRegistry 的报告生成链路；报告场景仅在边界一致时评估复用。

## 3. 当前基线

| 能力 | 当前状态 | 差距 |
| --- | --- | --- |
| Codex 报告生成 | `report_providers/codex_exec.py` 可用 `codex exec --json` 生成结构化报告，并已有超时、临时目录和 JSON Schema 校验 | 只服务报告，不提供通用 `agent_exec` 契约、readiness API、输入 allowlist 或 run 状态 |
| Provider 缺省 | ReportProviderRegistry 按请求实例化，provider 缺失不阻断应用启动 | 尚无 `agent_exec` 的统一 unavailable 语义 |
| 权限与确认 | Plan 10 已有 Permission Mode、Plan Mode、Goal / Todo 和审批状态 | `agent_exec` 尚未接入这些控制面 |
| Trace / Audit | Plan 09/10 已有 append-only 事件、Trace 投影与 AuditEventRepository | 外部执行 run 尚无事件契约和回放 |
| 安全边界 | 报告 provider 使用临时目录和环境变量过滤 | 尚无任务级 workdir、输入输出扫描、大小限制和取消语义 |

## 4. Provider 契约

### 4.1 核心接口

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

### 4.2 任务类型

| task_type | 输入 | 输出 | MVP |
| --- | --- | --- | --- |
| `structured_file_task` | prompt、显式输入文件 allowlist、JSON Schema | 结构化 JSON 与可选 artifact | 是 |
| `report_file_task` | 报告上下文文件与输出 Schema | 报告 JSON / Markdown / Artifact | 仅评估复用 |
| `authorized_lab_task` | 未来实验系统授权凭据与任务清单 | 系统回执与状态 | 否 |

任务类型必须在注册表中显式声明；未知类型直接拒绝，不做自由文本能力推断。

### 4.3 安全不变量

- 默认关闭：未配置 `AGENT_EXEC_ENABLED=true` 时 registry 为空且 API 返回 unavailable。
- 独立 workdir：每次 run 使用 `AGENT_EXEC_WORKDIR_ROOT/{run_id}`，不复用报告临时目录。
- 输入 allowlist：只复制调用方显式声明的文件；解析 symlink 后仍必须在受管目录内。
- 输出边界：provider 输出、artifact 和日志必须留在 run workdir，路径穿越直接失败。
- 资源限制：单文件、总输入、总输出、文件数和超时都有上限；超限即取消并清理可执行产物。
- 环境最小化：只传入 provider 必需的环境变量；不默认继承数据库、对象存储和云厂商凭据。
- 审计优先：无论成功失败，都记录 provider、task_type、input manifest、workdir、耗时、输出清单、错误码和 actor。
- 缺省 fallback：provider 不可用时不阻断应用启动；调用方收到结构化 unavailable，并可继续走既有非外部 Agent 路径。

## 5. 目标架构

```text
backend/app/schemas/agent_exec.py
  ├─ readiness / request / run / event / artifact schema

backend/app/services/agent_exec_providers/
  ├─ base.py        # Protocol、错误与结果契约
  ├─ registry.py    # provider 注册、readiness 聚合、缺省 fallback
  └─ codex.py       # Codex MVP 适配器

backend/app/services/agent_exec_service.py
  ├─ 创建 run 与独立 workdir
  ├─ 复制 allowlist 输入并扫描输出
  ├─ 调 provider、处理超时/取消/失败
  └─ 写 Audit，携带 chat/tool 上下文时写 assistant event

backend/app/infra/agent_exec_repositories.py
  └─ run / artifact / event 的 Mongo 与 SQLite 双模存储

backend/app/api/v1/endpoints/agent_exec.py
  └─ 管理员 readiness、run 查询与取消 API
```

### 5.1 事件模型

`agent_exec_runs` 保存权威状态，`audit_events` 保存跨模块审计事实；带 `chat_id` 的调用同步写入现有 `assistant_events`，由 Plan 09/10 Trace 投影消费，不新增第二套 Trace。

| event_type | 时机 |
| --- | --- |
| `agent_exec.requested` | 请求通过基础校验后 |
| `agent_exec.provider_ready` | readiness 通过 |
| `agent_exec.provider_unavailable` | provider 缺失、禁用或配置无效 |
| `agent_exec.started` | workdir 与输入准备完成，执行前 |
| `agent_exec.completed` | 输出与 artifact 校验完成 |
| `agent_exec.failed` | provider、schema、路径、资源或超时失败 |
| `agent_exec.cancelled` | 用户或系统取消 |

事件 payload 不记录完整 prompt、hidden reasoning、凭据和未脱敏环境变量。

## 6. 分阶段任务

### P15-A. 契约、配置与 registry

- [ ] 新增 `backend/app/schemas/agent_exec.py`：
  - `AgentExecProviderReadiness`
  - `AgentExecTaskRequest`
  - `AgentExecExecutionRequest`
  - `AgentExecProviderResult`
  - `AgentExecRunData`
  - `AgentExecArtifactData`
- [ ] 新增 `backend/app/services/agent_exec_providers/base.py`，定义 Protocol、错误类型和结构化 unavailable 结果。
- [ ] 新增 `backend/app/services/agent_exec_providers/registry.py`，支持按 provider_id / task_type 解析，并聚合 readiness。
- [ ] 在 `backend/app/core/config.py` 增加：
  - `AGENT_EXEC_ENABLED`，默认 `false`
  - `AGENT_EXEC_WORKDIR_ROOT`，默认 runtime 下 `agent_exec`
  - `AGENT_EXEC_TIMEOUT_SECONDS`
  - `AGENT_EXEC_MAX_INPUT_BYTES`
  - `AGENT_EXEC_MAX_OUTPUT_BYTES`
  - `AGENT_EXEC_MAX_FILES`
- [ ] registry 初始化不探测外部二进制，不抛异常，不阻断 FastAPI 启动。
- [ ] 补充契约、默认禁用、未知 provider、未知 task_type 和缺省 unavailable 测试。

### P15-B. Codex MVP 适配器

- [ ] 新增 `backend/app/services/agent_exec_providers/codex.py`，复用现有报告 provider 的 JSON Schema 处理经验。
- [ ] readiness 检查：
  - `codex` 二进制存在且可执行；
  - `AGENT_EXEC_ENABLED=true`；
  - 受限 / 只读 sandbox 参数可用；
  - API key 或本地模型配置满足要求；
  - `structured_file_task` 已声明。
- [ ] 执行时使用 run 专属 workdir，只传入 prompt、输入文件和输出 Schema。
- [ ] 明确使用 Codex CLI 的受限 sandbox 模式；无法确认 sandbox 能力时 readiness 返回 unavailable，不得降级为无沙箱执行。
- [ ] 捕获二进制缺失、非零退出、超时、输出缺失、JSON Schema 不匹配和环境配置错误。
- [ ] 返回结构化 `stdout_digest` / `stderr_digest`，不保存完整无限长日志。
- [ ] 补充 mock subprocess 测试：成功、缺二进制、非零退出、超时、schema 失败、sandbox 参数不支持。

### P15-C. 执行服务与安全边界

- [ ] 新增 `backend/app/services/agent_exec_service.py`，统一创建 run、准备输入、调用 provider、校验输出和清理状态。
- [ ] run_id 使用服务端生成，禁止客户端指定或路径拼接。
- [ ] 输入文件必须来自服务端受管 artifact / 临时上传目录，逐个记录 path、size、sha256 和来源对象 ID。
- [ ] 复制前解析 symlink 与 realpath，拒绝 workdir 外路径、目录逃逸、硬链接语义不确定的文件和超过限额的输入。
- [ ] provider 输出只允许 JSON 结果文件和显式 artifact 目录；扫描路径穿越、symlink、隐藏文件、可执行位、空文件和总大小。
- [ ] 超时后终止进程，run 标记 failed / timeout，保留脱敏事件与有限日志，清理可执行产物。
- [ ] 支持服务端取消；已结束后取消返回稳定终态，不产生竞态覆盖。
- [ ] provider unavailable 时不创建外部进程，返回结构化 unavailable，并允许调用方继续既有本地路径。
- [ ] 补充边界测试：allowlist、路径穿越、symlink、大小、文件数、超时、取消、输出逃逸、输出超限和 unavailable。

### P15-D. 存储、Audit 与 Trace 接入

- [ ] 新增 `backend/app/infra/agent_exec_repositories.py`，提供 Mongo / SQLite 双模 run、artifact 和事件查询。
- [ ] 为 SQLite 初始化对应表和索引；Mongo 建立 run_id、provider_id、status、chat_id、created_by 和 created_at 索引。
- [ ] 每次执行写入第 5.1 节事件，并调用 `AuditEventRepository.append` 记录跨模块审计。
- [ ] 带 `chat_id` / `assistant_tool_call_id` 的调用写入现有 `assistant_events`，事件 metadata 记录 run_id、provider_id、task_type 和 source。
- [ ] 扩展 Plan 09 Trace 投影可识别 `agent_exec.*` 事件，但不复制 Trace 存储或新建前端事实源。
- [ ] 事件内容脱敏：不记录 API key、完整环境变量、完整 prompt、hidden reasoning 和未授权用户数据。
- [ ] 补充存储、owner 校验、事件顺序、失败终态、取消终态、审计字段和 Trace 投影测试。

### P15-E. 管理 API 与最小可观测性

- [ ] 新增 `backend/app/api/v1/endpoints/agent_exec.py` 并挂载到 v1 router。
- [ ] `GET /agent-exec/providers`：管理员查看 provider readiness、配置来源、支持 task_type 和 unavailable 原因。
- [ ] `POST /agent-exec/runs`：仅服务端内部调用和管理员受控测试；请求必须显式 task_type、provider_id、输入清单、输出 Schema 和超时。
- [ ] `GET /agent-exec/runs/{run_id}`：管理员查看脱敏 run 状态、事件和 artifact manifest。
- [ ] `POST /agent-exec/runs/{run_id}/cancel`：管理员取消未结束 run。
- [ ] API 不返回 workdir 绝对路径、凭据、完整 prompt 或未脱敏环境。
- [ ] 增加 run 成功率、unavailable、timeout、cancel、输入输出大小和耗时的质量摘要，先复用现有 metrics/quality 输出模式。
- [ ] 补充 API 测试：未登录、普通用户、管理员、provider 缺失、run 不存在、owner 越权和取消竞态。

### P15-F. LUI 与报告链路接入评估

- [ ] 在 P15-A–P15-E 完成后，评估 `/dialogue` 是否以显式确认的专用工具形式暴露 `structured_file_task`。
- [ ] 若暴露给 LUI，必须复用 Plan 10 Permission Mode、Plan Mode、确认状态机和审批，不允许模型自动授权。
- [ ] 评估报告服务是否从 Codex ReportProvider 迁移到 `agent_exec`；只有安全边界和输出契约一致时才迁移，否则保留双路径并说明理由。
- [ ] 输出 PI / DSH 接入评估：只比较 readiness、沙箱、artifact、超时、审计和凭据边界，不引入 runtime 依赖。
- [ ] 更新用户指南和来源矩阵，明确外部 provider 是可选能力，不宣称 PolyAgent 绑定或复制这些产品。

## 7. 测试计划

### 7.1 后端单元与 API 测试

```bash
conda run -n poly_agent python -m pytest \
  backend/tests/test_agent_exec_contract.py \
  backend/tests/test_agent_exec_codex_provider.py \
  backend/tests/test_agent_exec_service.py \
  backend/tests/test_agent_exec_events.py \
  backend/tests/test_agent_exec_api.py -q
```

覆盖：

- 默认禁用、provider 缺失、未知任务类型和启动不受影响。
- readiness 不产生副作用、不执行外部二进制。
- workdir、allowlist、路径、symlink、文件数、大小、超时和取消。
- JSON Schema、输出 artifact、日志摘要和错误终态。
- Audit / assistant event 顺序、owner 权限、脱敏和 Trace 投影。
- 管理 API 的 RBAC、错误响应和稳定终态。

### 7.2 回归测试

```bash
conda run -n poly_agent python -m pytest \
  backend/tests/test_report_providers.py \
  backend/tests/test_assistant_commands_api.py \
  backend/tests/test_assistant_command_events.py \
  backend/tests/test_assistant_trace_api.py \
  backend/tests/test_assistant_trace_projection.py -q
```

### 7.3 前端与 E2E

- P15-A–P15-E 不修改前端时仅需 `cd frontend && npm run build`。
- P15-F 若新增 LUI 入口，补充命令/工具目录测试，并执行相关 `assistant` 前端测试。
- E2E 覆盖：provider unavailable 不影响 `/dialogue`；授权、确认、执行、失败、取消和 Trace 回放。

## 8. 兼容与迁移策略

- 保持现有 `report_providers/codex_exec.py` 不变，直到 P15-F 证明迁移安全。
- 新配置默认关闭，不影响已有部署。
- 首版 API 仅管理员可访问，避免普通用户直接触发外部执行。
- 存储迁移必须兼容 SQLite demo 模式与 Mongo 部署模式。
- 事件类型进入 Plan 09/10 Trace 白名单时保持向后兼容；历史无 `agent_exec.*` 事件的回放结果不变。

## 9. 风险与规避

| 风险 | 影响 | 规避 |
| --- | --- | --- |
| Codex CLI sandbox 参数变化 | 适配器误以为受控但实际可越界 | readiness 显式探测并版本记录；不支持时 unavailable，一票否决 |
| 文件 allowlist 来源过大 | 外部 provider 获得过多项目数据 | 只允许服务端受管 artifact / 临时上传，并做大小、数量和来源校验 |
| 输出隐藏路径或 symlink | artifact 逃逸 workdir | realpath + allowlist + 归档扫描；发现即 failed 并清理 |
| 与报告 provider 双路径混淆 | 同一外部能力出现两套安全语义 | P15-F 明确保留或迁移决策，并写入来源矩阵 |
| 事件写入失败但进程已执行 | 审计缺失 | requested/started 事件先落库；后续事件失败时 run 标记 audit_error 并告警 |
| 未来 PI / DSH 接入过快 | 引入不受控 runtime | 只做接口评估；未通过 sandbox/readiness/audit 验收不注册 provider |

## 10. 完成定义

- [ ] 默认关闭时应用可启动，`/dialogue`、ResearchEngine、报告和算法工具回归不回退。
- [ ] provider readiness、执行、超时、取消、失败和 unavailable 均有结构化语义和测试。
- [ ] 输入输出始终限定在 run 专属 workdir，路径、大小、文件数和 symlink 测试通过。
- [ ] Audit / assistant event / Trace 可完整回放一次成功、失败、取消和 provider 缺失场景。
- [ ] 管理 API 只对管理员开放，并返回脱敏信息。
- [ ] Codex MVP 不暴露通用 Shell、任意文件读写、任意网络和项目根目录。
- [ ] 文档、用户指南、来源矩阵和 `doc/README.md` 索引同步更新。

## 11. 状态记录

- 2026-08-19：从 Plan 12 拆分 `agent_exec` provider seam，新增独立工作计划；未修改业务代码。
