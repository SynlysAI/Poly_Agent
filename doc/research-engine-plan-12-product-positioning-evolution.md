# Plan 12：PolyAgent 在 PI Agent / DSH / Codex 时代的定位、生态位与演进路线

> 状态：待评审
>
> 日期：2026-08-16
>
> 前置文档：
> - [research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md](research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md)
> - [research-engine-plan-09-lui-execution-trace.md](research-engine-plan-09-lui-execution-trace.md)
> - [research-engine-plan-10-slash-command-and-agent-control-workplan.md](research-engine-plan-10-slash-command-and-agent-control-workplan.md)
> - [platform-positioning-and-small-iteration-plan.md](platform-positioning-and-small-iteration-plan.md)
> - [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md)

## 1. 摘要

PolyAgent 的长期定位是**高分子材料智能研发的领域工作台**，而不是与 PI Agent、DeepSeek Harness（以下简称 DSH）、Codex 正面竞争的通用 agent harness。

Harness 能力在 PolyAgent 中只作为受控底座能力被借鉴或接入，不构成产品核心。PolyAgent 的核心价值来自材料研发任务闭环、领域算法与知识证据、可追溯执行、数据安全与贡献归属；通用 agent loop、通用 shell/文件沙箱和通用插件市场不应成为 PolyAgent 的主要投入方向。

## 2. 当前基线

截至 2026-08-16，PolyAgent 已具备：

| 模块 | 当前能力 |
| --- | --- |
| Alchemist | 变量定义、DoE/OED、GP 建模、采集优化和诊断可视化 |
| ComputeEngine | 计算任务生命周期、worker、artifact、campaign 和本地 xTB/ORCA fixture |
| ResearchEngine | ProblemSpec、人工 Workflow、AutoResearch、Gate 审批、traceability 和报告 |
| 垂类预测 | 算法包上传、版本治理、在线测试、运行历史、结果查看与 handoff |
| Knowledge Base | WeKnora 问答、证据清单和可选 Neo4j 检索子图 |
| 助手与报告 | 基于项目事实导航、垂类算法工具调用、Execution Trace 和多 provider 报告生成 |

Plan 08 已完成 LUI 的模型路由、上下文 manifest、统一事件、工具契约、服务端续答和观测能力。Plan 09 已完成 Execution Trace。Plan 10 待实施，目标是补齐 Slash Command、Plan Mode、权限模式、Goal/Todo、Compaction、导出与反馈。

## 3. 三类产品的边界

| 产品 | 本质 | PolyAgent 的借鉴与边界 |
| --- | --- | --- |
| PI Agent | 轻量、模型中立、可自扩展的 TypeScript coding-agent harness | 借鉴“模型中立、能力 seam、轻量循环”，但不照搬 TUI/coding CLI 定位 |
| DSH | DeepSeek 开源“一切皆插件”的通用 agent harness | 已在 Plan 08/09/10 借鉴 append-only 事件、命令注册、权限与 Trace；不引入 Cordis/TS runtime |
| Codex | OpenAI 面向编码、自动化和 SDK 能力的 agent 产品 | 作为可选外部执行 provider；不成为 PolyAgent 必需运行时 |

三者共同点是围绕通用 agent 的执行循环、工具调用、沙箱、会话与扩展机制建设能力。PolyAgent 应吸收这些产品中可验证、可审计的架构不变量，但不应把“成为通用 harness”当成目标。

## 4. 产品定位

PolyAgent = 材料研发领域工作台 + 可追溯 ResearchEngine/ComputeEngine + 垂类模型与算法货架 + 受控 LUI 控制面。

它解决的核心问题是：

> 材料研发任务如何被定义、执行、审计和复用。

而不是：

> 通用 agent 如何循环、调度和访问系统。

因此，PolyAgent 不追求通用开发者体验，而追求材料科学家、算法与计算工程师、实验平台管理员和研发负责人在同一套研发事实上的协作效率与可追溯性。

## 5. 生态位

### 5.1 横向生态位

PolyAgent 位于 AI4MS 门户与具体算法/实验工具之间：

```text
AI4MS 门户
  ↓
PolyAgent 材料研发工作台
  ↓
算法、计算、知识库、实验执行器与垂类模型
```

它承担任务上下文、编排、证据和决策闭环，不替代单个预测模型，也不替代门户账号体系。

### 5.2 纵向生态位

PolyAgent 位于通用 coding/agent harness 与实验室执行系统之间：

```text
通用 agent harness（PI / DSH / Codex）
  ↓ 可替换 provider，不绑定
PolyAgent 领域工作台
  ↓
ORCA / HPC / AiiDA / SpecLabOS / LabOS / 垂类算法
```

通用 harness 负责通用执行能力，PolyAgent 负责领域任务、证据链和治理。通用 harness 作为可选 provider 存在时提升体验，缺省时平台核心链路仍应完整可用。

### 5.3 独占优势与不独占能力

| 类别 | 内容 |
| --- | --- |
| PolyAgent 独占优势 | ProblemSpec、人工 Workflow / AutoResearch 双通道、Gate 审批、AlgorithmRun/ResearchRun 全链路 trace、材料领域算法与知识证据、数据安全与贡献归属 |
| 不独占能力 | 通用 agent loop、通用 shell/文件沙箱、通用插件市场，交由 PI/DSH/Codex 等外部产品承担 |

## 6. 演进路线

### 6.1 延续受控 LUI，而不是重写 harness

继续执行 Plan 09/10 的 Slash Command、Plan Mode、权限模式、Goal/Todo、Compaction、导出与反馈。所有命令动作进入现有 append-only Trace 和 Audit，不新建第二套事实源。

验收重点：

- Plan 09 的 Trace 投影、API 与前端时间线保持稳定。
- Plan 10 的命令事件复用 `assistant_events`，不复制 DSH 的 Cordis 或 TypeScript runtime。
- 普通对话、垂类算法工具调用和 ResearchEngine 现有路径不回退。

### 6.2 把通用 harness 变成可替换 provider

对外部 agent 能力增加受控 provider seam：Codex/PI/DSH 只用于报告生成、受限工作目录内的文件型任务或未来授权任务。

Provider seam 至少满足：

- readiness 检查；
- 受限 workdir；
- 超时控制；
- 完整 audit；
- 缺省 fallback，缺失时不阻断平台启动和核心链路。

当前 Codex 已作为报告 provider 的可选项存在，后续 PI/DSH 是否接入按同样受控边界评估，不引入通用 shell 或任意文件编辑能力。

### 6.3 强化领域闭环与真实执行

P1/P2 优先补齐：

- Schema 驱动算法表单和 AlgorithmRegistry 管理；
- checkpoint/rerun 完整恢复语义；
- 真实预测模型服务和生产候选适配器；
- ORCA/HPC/AiiDA executor；
- SpecLabOS/LabOS 实验提交与结果回填；
- 模型更新与 lesson 沉淀。

这些能力直接扩大 PolyAgent 的领域壁垒，比自研通用 harness 更符合产品定位。

### 6.4 生产化与数据信任

多租户 RBAC、对象存储、worker 运维、项目级权限/配额、私有化与轻量联邦推理，作为领域工作台的护城河。

对外不宣传“比 PI/DSH/Codex 更通用”，而宣传“更适合受控材料研发场景、更可审计、更可交付”。

### 6.5 生态开放但保持口径

算法上传、来源、引用、开发者和机构 Logo 继续遵守 `polyagent-attribution`。

对外统一表述为“材料研发协作底座”，不表述为“另一个通用 agent 平台”。

## 7. 接口与类型影响

本计划本身不直接改代码，但确定未来接口方向：

- 复用 Plan 10 的 `command catalog`、`session control state`、`assistant_events` 命令事件。
- 预留 `agent_exec` 外部执行 provider seam，要求具备 readiness 检查、受限 workdir、超时、审计和缺省 fallback。
- 不新增独立通用 Bash/Read/Edit 工具；外部 harness 只通过受控 provider 接入。
- 所有模型、工具、算法和外部框架来源继续落到来源矩阵和 attribution。

## 8. 验证与验收场景

### 8.1 产品口径验收

- [ ] 材料科学家能凭本文档区分 PolyAgent 与通用 harness：前者解决材料任务闭环，后者解决通用执行循环。
- [ ] 算法/计算工程师能看到 Plan 09/10 的控制面演进不破坏现有 FastAPI/Vue 和 ResearchEngine 能力。
- [ ] 平台管理员能确认外部 Codex/PI/DSH provider 缺失时，平台核心功能仍可启动和运行。

### 8.2 技术验收

- [ ] 未来落地 Plan 10 后，slash command、权限决定、导出和反馈均有真实事件、Trace 回放和测试覆盖。
- [ ] 如后续实现 `agent_exec` provider，增加缺省、超时、工作目录和审计单测。
- [ ] 现有回归测试与前端构建不回退。

### 8.3 口径与来源验收

- [ ] 不声称复制或绑定 DSH/Codex/PI 代码。
- [ ] 不把通用 harness 作为 PolyAgent 的核心竞争力。
- [ ] 不新增无授权机构 Logo，外部产品仅作为参考来源或可选 provider。

## 9. 假设与默认选择

- “PI Agent”指 `earendil-works/pi` 的 Pi Agent Harness。
- “dsh”指 DeepSeek Harness。
- “codex”指 OpenAI Codex。
- plan12 交付物为战略定位与路线图文档，不拆成逐文件代码任务。
- 默认采用“材料科研域工作台”定位，不采用“多 harness 统一入口”或“自建通用 harness”。
- 默认演进主线为延续 Plan 09/10 的受控 LUI，不重写架构。
- 文档使用中文 Markdown，完成后同步更新计划状态与复选框。

## 10. 状态记录

- 2026-08-16：新增 LUI 科研问答 / 深度思考 Preset 定位计划，原 Plan 11 重排为 Plan 12，正文未做业务性修改。
- 待办：评审后确定是否将 `agent_exec` provider seam 拆分为独立实施计划。
