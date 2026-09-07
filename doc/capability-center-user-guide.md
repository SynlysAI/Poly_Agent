# AI 能力用户指南

## 1. 定位

AI 能力位于工具服务 `/tools?tab=ai-ready`，回答一个运行时问题：**当前用户现在能调用哪些 AI Ready 能力、能力是否可用、调用前需要什么确认**。

它是只读展示与调用入口，不是配置中心：

- 能力事实源来自算法工具、Plan 15 Agent 连接器和服务端报告 Skill pipeline。
- AI 能力不保存配置快照，不修改策略，不新建第二套 provider、tool、skill、policy 或 trace 事实源。
- 卡片不提供配置按钮或 `config_path`；管理员配置在同一页面的相邻管理页签完成。
- LLM provider 与模型不是 AI 能力目录分组；模型仍在对话内选择，LLM 配置仍在管理员“LLM 模型”页签。

旧链接 `/capabilities` 会自动跳转到 `/tools?tab=ai-ready`。

## 2. 角色视角

| 角色 | 可见内容 | 可执行动作 |
|------|----------|------------|
| 管理员 | 全部能力，包括 disabled、unavailable 与安全原因 | 查看原因、进入对话或报告入口、发起允许的连接器任务；配置切换到相邻管理页签 |
| 普通用户 | 仅 public 或本人 private 且策略允许的算法工具、显式开放的连接器、ready 的报告 pipeline | 进入对话或报告入口、在显式确认后调用连接器 |
| 本地演示模式 | 按管理员视角展示 | 用于本机演示，不新增写权限 |

普通用户进入 `/tools` 只能看到“AI 能力”页签；直接访问管理 tab query 会自动回落到 AI 能力，不触发管理配置 API。

## 3. 三个能力分组

1. **对话工具**：来自 `AgentToolService` 派生目录。管理员能看到治理条目和不可用原因；普通用户只看到允许且可调用的工具。卡片跳转 `/dialogue?toolIds=...`。
2. **外部 Agent 连接器**：来自 Plan 15 provider registry 与 policy。默认关闭且 admin-only；管理员同时设置 `enabled=true` 并把 `user` 加入 `allowed_roles` 后，普通用户才可见。
3. **报告 Skill**：仅展示服务端 `SUPPORTED_PIPELINES` 与 allowlist 校验结果。每个卡片列出 pipeline 步骤中的服务端 skill id，不读取、上传或安装本地 `.codex/skills`。

## 4. 连接器调用确认

普通用户即使看到连接器，也必须满足：

1. provider readiness 可用；
2. 策略已启用；
3. `user` 在 `allowed_roles` 中；
4. `structured_file_task` 在 provider 与策略允许范围内；
5. 每次请求都显式勾选确认。

即使管理员把 `requires_confirmation` 设置为 `false`，普通用户仍必须逐次确认。管理员行为保持 Plan 15 原策略语义。

AI 能力发起连接器任务时只构建 `structured_file_task` 请求；输入、输出、超时、沙箱、取消、审计和 trace 仍由 Plan 15 安全内核执行。

## 5. 来源与边界

- 算法工具展示算法包登记的 developer、framework、method 来源和授权 Logo。
- Codex 连接器展示“执行能力来自 Codex CLI”；PolyAgent 不声明内置或复制 Codex。
- 报告 Skill 按实际 provider 展示 OpenAI-compatible、Ollama 或 Custom HTTP 来源。
- AI 能力不展示 secret、API key、base URL、workdir、完整 prompt、环境变量或完整配置对象。
- 本期不做插件市场、浏览器连接器、任意 OAuth 安装、本地 Skill 扫描或动态加载。

## 6. 常见问题

| 现象 | 处理方式 |
|------|----------|
| 管理员看到某能力 unavailable | 查看卡片原因；算法工具前往“算法工具”页签，连接器前往“Agent 连接器”页签 |
| 普通用户看不到连接器 | 默认安全策略即为 admin-only；需管理员显式启用并允许 user |
| 普通用户无法提交连接器任务 | 必须勾选显式确认，并确认 provider readiness 与策略仍有效 |
| 某分组显示读取失败 | 该分组被隔离降级，可刷新目录；配置排查仍在原模块 |
