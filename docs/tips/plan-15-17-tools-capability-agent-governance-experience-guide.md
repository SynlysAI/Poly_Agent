# Plan 15–17：工具服务、AI 能力与 Agent 连接器体验指南

> 适用版本：2026-09-07 收尾版
>
> 关联计划：
> - [Plan 15：受控外部 Agent 执行 Provider Seam 与 Agent 连接器治理工作计划](../../doc/research-engine-plan-15-agent-exec-provider-seam-workplan.md)
> - [Plan 16：统一能力中心与权限治理工作计划](../../doc/research-engine-plan-16-capability-center-and-permission-governance-workplan.md)
> - [Plan 17：工具服务统一入口、AI Ready 能力目录与 Agent 执行生产化整合工作计划](../../doc/research-engine-plan-17-unified-tool-services-and-capability-governance-workplan.md)

## 一、收尾后的稳定入口

Plan 15–17 已关闭。目标态是：`/tools` 是唯一工具服务入口，`/capabilities` 只作为兼容跳转进入 AI 能力。

| 使用者 | 入口 | 默认看到的内容 | 典型动作 |
| --- | --- | --- | --- |
| 普通用户 | `/tools` 或 `/tools?tab=ai-ready` | 仅“AI 能力”页签 | 查看可调用能力、进入对话或报告、显式确认后调用已授权连接器 |
| 管理员 | `/tools` | 默认进入“状态”页签；另可切换 AI 能力、LLM 模型、Agent 连接器、算法清单、算法工具、服务配置 | 查看服务健康、治理能力、配置连接器策略、排查 run 与审计 |
| 运维 / 发布 | `/tools?tab=agent-connectors` 与部署配置 | Codex readiness、run 质量与策略 | 验证 CLI 版本、检查告警与审计、执行回滚 |

管理员页签顺序固定为：**状态、AI 能力、LLM 模型、Agent 连接器、算法清单、算法工具、服务配置**。普通用户直接访问管理页签 query 时会回落到“AI 能力”，且不触发管理 API。

```text
/tools
  ├─ AI 能力：只读目录 + 允许的调用入口
  │   ├─ 对话工具：AgentToolService 派生目录
  │   ├─ 外部 Agent 连接器：agent_exec policy + readiness
  │   └─ 报告 Skill：服务端 pipeline allowlist
  └─ 管理页签：LLM 模型、Agent 连接器、算法清单、算法工具、服务配置
```

## 二、默认安全态

收尾后不改变以下默认值：

- `AGENT_EXEC_ENABLED` 默认 `false`。
- 连接器策略默认 `enabled=false`、`allowed_roles=["admin"]`、`requires_confirmation=true`。
- 仅允许 `structured_file_task`。
- 普通用户即使被授权，也必须每次显式确认；把策略里的确认要求改为 `false` 不能跳过这一保护。
- AI 能力目录没有配置表单、配置按钮或 `config_path`；配置只存在于管理员页签。
- LLM provider / model 不是 AI 能力分组；模型在对话内选择，配置在管理员“LLM 模型”页签。

## 三、管理员日常检查

### 1. 先看工具服务状态

1. 打开 `/tools`，默认进入“状态”页签。
2. 确认关键服务、LLM 模型与工具目录没有整页失败。
3. 若某个能力不可用，切换到“AI 能力”查看分组隔离后的原因，再进入对应管理页签排查。

不要把“AI 能力”当作配置面；它只消费事实源，不反向修改策略。

### 2. 检查 Codex 连接器 readiness

1. 进入 `/tools?tab=agent-connectors`。
2. 查看 Codex 卡片的 `ready / unavailable / disabled` 状态与原因。
3. 使用显式探测确认：
   - 二进制版本；
   - 最低版本门槛（默认 `0.149.1`）；
   - SHA-256 摘要；
   - 配置来源摘要。
4. readiness 不满足时保持策略关闭，先修复 CLI、配置目录或环境变量。

显式探测只执行版本探测，不发起文件任务，也不暴露 secret。

### 3. 开放普通用户前检查

开放普通用户前逐项确认：

1. `AGENT_EXEC_ENABLED=true` 且 readiness 通过。
2. provider policy `enabled=true`。
3. `allowed_roles` 显式包含 `user`。
4. `allowed_task_types` 仍仅包含 `structured_file_task`。
5. 已用最小输入完成一次受控测试 run。
6. 已确认审计、trace、取消和失败路径可回放。

开放后用普通账号进入 `/tools?tab=ai-ready` 验证：只能看到允许的能力；提交连接器任务时必须勾选确认；打开页面不产生管理 API 请求。

## 四、Agent 执行边界

每次 run 都满足以下边界：

- 服务端生成 `run_id`，使用独立受限 workdir。
- 输入只能来自服务端受管上传 / artifact，逐文件校验大小、哈希、路径与文件类型。
- symlink、硬链接、FIFO、设备文件、路径逃逸、隐藏输出、可执行输出、空文件和超限输出均拒绝。
- Codex CLI 固定 `read-only` sandbox；无法确认 sandbox 能力时保持 unavailable，不降级执行。
- 超时会终止子进程；取消进入稳定终态，迟到成功不能覆盖 `cancelled`。
- 子进程受 CPU 时间、地址空间与输出文件 RLIMIT 限制。
- 全局并发、每用户活跃 run、输入输出大小与文件数由服务端强制限制，超限返回 429 或结构化错误。

生产部署当前明确支持单进程 / 单 worker。多实例、跨进程取消或终态语义变更需要另立计划，不要通过只改部署参数绕过 readiness 约束。

## 五、审计、观测与排障

### 1. 查看质量与 run

管理员在 Agent 连接器页签查看质量摘要，可用维度包括：

- provider；
- 时间窗；
- 失败率；
- timeout；
- unavailable；
- `audit_error`；
- 平均耗时。

run 列表支持 provider、状态、会话与时间窗筛选。排查顺序建议：

1. 先确认 provider readiness 与 policy 是否仍有效。
2. 查看失败 run 的结构化错误码和有限日志摘要。
3. 检查输入 / 输出限制、超时、取消和外部模型网关。
4. 带 `chat_id` 的任务到会话统一回放查看“外部 Agent 文件任务”步骤。

### 2. 处理 `audit_error`

审计写入失败不会中断已执行进程，但 run 会保留 `audit_error` 终态并在质量摘要中计数。

- 管理员可通过 `POST /agent-exec/runs/{run_id}/audit/retry` 补写缺失事件。
- 补写成功后记录 `agent_exec.audit.recovered`。
- 配置 `AGENT_EXEC_ALERT_WEBHOOK_URL` 后，`audit_error`、失败率和超时率异常会发送结构化告警。
- webhook 故障只记录日志，不影响业务 run；告警系统故障不能视为业务 run 成功。

### 3. workdir 与重启

- 默认保留 24 小时、最多 100 个终态 workdir。
- 可用 `AGENT_EXEC_WORKDIR_RETENTION_HOURS`、`AGENT_EXEC_MAX_RETAINED_WORKDIRS`、`AGENT_EXEC_CLEANUP_INTERVAL_SECONDS` 调整。
- 清理写 `agent_exec.workdir.cleaned` 审计。
- 服务重启会把 requested / running run 恢复为 failed / `restart_recovered`，并写恢复审计。

## 六、外部网关阻塞的处理

收尾验证中，真实 Codex 结构化任务链路已执行到外部调用，但本地模型网关返回 `/v1/responses` 404“不支持的端点”。这是外部网关配置 / 端点能力问题，不是 PolyAgent 待办，也不能用 mock 伪装通过。

处理要求：

1. 确认网关支持 Codex CLI 使用的 `/v1/responses` 端点，或将模型配置指向正确端点。
2. 更新 `.runtime/codex-home/` 中受控配置与凭证；不要把 secret 写入文档或前端。
3. 显式开启 `AGENT_EXEC_CODEX_INTEGRATION_ENABLED=true` 后重跑真实集成测试。
4. 若仍失败，记录网关响应、时间、配置来源摘要和 run_id，另立运维事件处理。

真实 sandbox 出口探测已经通过：`read-only` profile 下 workdir 写入和仅监听 `127.0.0.1` 的本地 HTTP 访问均被拒绝。

## 七、回归命令

日常变更优先跑专项，再按影响范围扩展：

```bash
# 后端能力目录与 Agent 执行专项
conda run -n poly_agent env PYTHONPATH=backend python -m pytest \
  backend/tests/test_capability_catalog_api.py \
  backend/tests/test_agent_exec_production.py \
  backend/tests/test_agent_exec_api.py \
  backend/tests/test_agent_exec_policy.py \
  backend/tests/test_agent_exec_service.py \
  backend/tests/test_agent_exec_events.py -q

# 前端能力目录与连接器
npm --prefix frontend run test:capability-center
npm --prefix frontend run test:agent-connectors
npm --prefix frontend run build

# E2E
make test-e2e
```

涉及后端全量时执行：

```bash
make test-backend
```

真实 Codex CLI 集成测试默认跳过。只有环境可用且明确要验证真实链路时才执行：

```bash
AGENT_EXEC_CODEX_INTEGRATION_ENABLED=true \
conda run -n poly_agent env PYTHONPATH=backend python -m pytest \
  backend/tests/test_agent_exec_codex_integration.py -q
```

该测试会验证 readiness、版本门槛、二进制摘要、read-only sandbox 出口和最小结构化任务。凭证或网关不可用时必须记录外部阻塞，不能用 mock 代替。

## 八、回滚

最小回滚步骤：

1. 在 Agent 连接器页签把目标 provider policy `enabled` 设为 `false`。
2. 如需整体关闭外部执行，将 `AGENT_EXEC_ENABLED` 设为 `false`。
3. 重启后端并确认 readiness 变为 disabled / unavailable。
4. 保留 run、artifact manifest 与审计，不要删除用于追溯的历史数据。

回滚不需要数据迁移；AI 能力目录会继续展示本地对话工具与报告 Skill，不会因 Codex 不可用影响核心链路。

## 九、何时另立计划

以下事项不属于 Plan 15–17 的继续跟踪范围：

- 新增 Codex 之外的 provider；
- 引入插件市场、浏览器连接器或任意 OAuth 安装；
- 修改为多实例部署、跨进程取消或多 worker 终态语义；
- 扩展新的任务类型或放宽 sandbox；
- 调整 AI 能力分组或恢复独立 `/capabilities` 入口；
- 更换 LLM 目录产品决策。

这些变化会影响安全边界、权限语义或事实源，应先新增设计 / 变更记录，再改代码和测试。
