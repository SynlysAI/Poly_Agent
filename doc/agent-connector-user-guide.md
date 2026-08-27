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
2. 进入 `/tools` 的“Agent 连接器”区域查看 Codex 卡片与 readiness 状态。
3. 启用连接器策略，按需调整允许角色、任务类型与确认要求；策略变更会写入审计。
4. 需要验证时可发起受控测试 run；run 状态、事件与 artifact 清单可在详情中查看。

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
- 输入只能来自服务端受管上传 / artifact 目录，逐个记录大小、sha256 与来源对象；symlink、硬链接、路径逃逸与超限输入会被拒绝。
- 输出只允许 JSON 结果文件与显式 `artifacts/` 目录；symlink、隐藏文件、可执行位、空文件、数量或总大小超限都会失败并清理。
- Codex CLI 固定使用 `--sandbox read-only`，无法确认 sandbox 能力时连接器保持 unavailable，不会降级为无沙箱执行。
- 超时会终止进程；服务端取消返回稳定终态，不产生竞态覆盖。

## 6. 审计与追溯

每次请求、readiness、开始、完成、失败、取消和策略变更都会写入统一审计；带会话上下文时同步进入 Plan 09/10 Trace，可在会话回放中查看“外部 Agent 文件任务”步骤。事件不记录完整 prompt、凭据、环境变量或 hidden reasoning。

## 7. 来源标注

连接器卡片展示“执行能力来自 Codex CLI”的来源标注。PolyAgent 负责策略治理、workdir、审计与追溯，不声明内置或复制 Codex；外部 provider 是可选能力，系统在 provider 缺失时继续走既有本地路径。
