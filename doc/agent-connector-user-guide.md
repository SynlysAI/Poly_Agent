# Agent 连接器（外部 Agent 执行）用户指南

## 1. 定位与边界

Agent 连接器用于把 Codex CLI 这类外部执行能力接入 PolyAgent，并只允许处理“显式声明输入、输出和授权范围”的文件型任务（`structured_file_task`）。PolyAgent 不提供通用 Shell、任意文件读写、任意网络访问或插件市场。

产品语义参考 Manus 的连接器交互模式，但不复制其市场、浏览器连接器或插件生态。

## 2. 默认安全策略

- `AGENT_EXEC_ENABLED` 默认 `false`，未显式开启时连接器不可用。
- 连接器策略默认关闭（`enabled=false`）。
- 默认仅管理员（`allowed_roles=["admin"]`）可调用。
- 默认强制用户确认（`requires_confirmation=true`）。
- 默认仅允许 `structured_file_task` 任务类型。

## 3. 管理员使用流程

1. 配置环境变量：
   - `AGENT_EXEC_ENABLED=true`
   - `AGENT_EXEC_CODEX_API_KEY`（或已有 `CODEX_API_KEY`），或配置 `AGENT_EXEC_CODEX_MODEL` 使用本地模型
   - 可选：`AGENT_EXEC_TIMEOUT_SECONDS`、`AGENT_EXEC_MAX_INPUT_BYTES`、`AGENT_EXEC_MAX_OUTPUT_BYTES`、`AGENT_EXEC_MAX_FILES`
   - 可选：`AGENT_EXEC_MAX_CONCURRENCY`、`AGENT_EXEC_MAX_ACTIVE_RUNS_PER_USER`；超过限制时返回 429，不会排队堆积请求
   - 可选：`AGENT_EXEC_CODEX_MIN_VERSION=0.149.1`；探测结果低于该版本时在管理员页签显示“未满足”
2. 进入 `/tools?tab=agent-connectors` 查看 Codex 卡片与 readiness 状态。
3. 启用连接器策略，按需调整允许角色、任务类型与确认要求；策略变更会写入审计。
4. 使用“显式探测”查看 Codex 二进制版本、最低版本门槛与 SHA-256 摘要；该操作只执行 `codex --version`，不发起文件任务。
5. 需要验证时可发起受控测试 run；run 状态、事件与 artifact 清单可在详情中查看，`GET /agent-exec/runs` 支持按 provider、状态、会话与时间窗分页筛选。
6. 配置完成后可在 `/tools?tab=ai-ready` 查看最终能力可见性；策略配置仍以 Agent 连接器页签为唯一入口。

## 3.1 普通用户开放流程

1. 管理员确认 provider readiness 通过，并在 `/tools?tab=agent-connectors` 启用连接器。
2. 将 `allowed_roles` 显式加入 `user`；仅改 `requires_confirmation=false` 不会开放普通用户。
3. 普通用户进入 `/tools?tab=ai-ready`，仅会看到该连接器；readiness 不满足时仍显示不可用。
4. 普通用户发起任务时必须每次勾选确认。即使策略关闭确认要求，服务端仍强制 `confirmed=true`。
5. run 详情、列表、取消和质量汇总仍仅管理员可访问；普通用户响应会隐藏 policy 更新者，普通 run 的 actor role、policy snapshot、事件与 trace 仍可被管理员追溯。

## 4. LUI 暴露规则（默认关闭）

“外部 Agent 文件任务”默认不暴露给 `/dialogue`。只有以下条件全部满足时才会返回工具描述符：

1. provider readiness 通过；
2. 策略已启用；
3. 当前角色在 `allowed_roles` 中；
4. `structured_file_task` 已允许；
5. 执行仍必须经过 Plan 10 确认状态机。

执行前必须向用户展示并确认：连接器、任务类型、输入文件清单与大小、输出 Schema、超时与输出限制。模型不能自动授权；未确认、只读权限或 Plan Mode 中均不可执行。

## 5. 安全边界

- 每次 run 使用服务端生成的 run_id 和独立受限 workdir。
- 输入只能来自服务端受管上传 / artifact 目录，基于不跟随 symlink 的文件描述符完成大小、sha256 与复制校验；symlink、硬链接、路径逃逸、大小 / 声明不符与超限输入会被拒绝。
- 输出只允许 JSON 结果文件与显式 `artifacts/` 目录；symlink、硬链接、隐藏文件、可执行位、空文件、数量或总大小超限都会失败并清理。
- Codex CLI 固定使用 `--sandbox read-only`，无法确认 sandbox 能力时连接器保持 unavailable，不会降级为无沙箱执行。
- 超时会终止进程；服务端取消返回稳定终态，取消后迟到的成功结果不能覆盖 `cancelled`。

## 6. 审计与追溯

每次请求、readiness、开始、完成、失败、取消和策略变更都会写入统一审计；带会话上下文时同步进入 Plan 09/10 Trace，可在会话回放中查看“外部 Agent 文件任务”步骤。事件不记录完整 prompt、凭据、环境变量或 hidden reasoning。审计写入失败时 run 会标记 `audit_error` 并记录结构化错误日志，质量摘要提供计数。

管理员可调用 `POST /agent-exec/runs/{run_id}/audit/retry` 补写缺失的 requested / started / terminal 事件；补写成功后清除 `audit_error`，并记录 `agent_exec.audit.recovered`。配置 `AGENT_EXEC_ALERT_WEBHOOK_URL` 后，`audit_error`、失败率或超时率异常会以结构化 JSON 发送到外部告警系统；webhook 故障只记录日志，不影响业务 run。

## 6.1 生产运行边界

- 当前 agent_exec 显式约束单进程部署：`AGENT_EXEC_DEPLOYMENT_MODE` 仅支持 `single_process`，`WEB_CONCURRENCY` / `GUNICORN_WORKERS` 必须为 1；否则连接器 readiness 返回结构化配置错误。
- run workdir 默认保留 24 小时，最多保留 100 个终态目录；可通过 `AGENT_EXEC_WORKDIR_RETENTION_HOURS`、`AGENT_EXEC_MAX_RETAINED_WORKDIRS` 和 `AGENT_EXEC_CLEANUP_INTERVAL_SECONDS` 调整。服务启动与周期任务会清理过期目录并写 `agent_exec.workdir.cleaned` 审计。
- 服务重启时，持久化的 requested / running run 会恢复为 failed / `restart_recovered`，并写 `agent_exec.restart.recovered` 审计。
- 真实 Codex 子进程受 CPU 时间、地址空间和输出文件 RLIMIT 限制；并发、每用户活跃 run、输入输出大小和文件数仍由服务端强制校验。
- Codex CLI 最低版本默认 `0.149.1`。显式集成测试包含一条不依赖模型凭证的 sandbox 出口探测：在 `read-only` permission profile 中尝试写 workdir 文件并访问仅监听 `127.0.0.1` 的本地 HTTP 服务，两者都必须被拒绝。
- 生产磁盘应启用静态加密，并将 `AGENT_EXEC_WORKDIR_ROOT` 放在受管存储上；备份策略必须排除 secret，恢复演练需同时校验 run 状态、审计事件和 artifact 清单。清理采用目录删除，满足敏感输入输出的销毁要求。
- 上线前执行 `make init-mongo-indexes`，并核对 `agent_exec_runs.run_id`、`agent_exec_artifacts.(run_id,path)` 和 `agent_exec_provider_policies.provider_id` 唯一索引。
- 显式开启 `AGENT_EXEC_CODEX_INTEGRATION_ENABLED=true` 后运行真实 CLI 集成测试，验证 readiness、二进制摘要、版本和 `read-only` sandbox 最小结构化任务；凭证或网关不可用时记录外部阻塞，不得用 mock 伪装通过。

## 7. 来源标注

连接器卡片展示“执行能力来自 Codex CLI”的来源标注。PolyAgent 负责策略治理、workdir、审计与追溯，不声明内置或复制 Codex；外部 provider 是可选能力，系统在 provider 缺失时继续走既有本地路径。

## 8. 相关入口

- AI 能力目录：`/tools?tab=ai-ready`
- 策略配置：`/tools?tab=agent-connectors`
- 用户与邀请码治理：`/admin`
