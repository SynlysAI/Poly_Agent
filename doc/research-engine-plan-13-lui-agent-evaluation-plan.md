# Plan 13：LUI Agent 评估与八项指标体系工作计划

> 状态：已评审 / 实施中
>
> 日期：2026-08-18（初稿）/ 2026-08-28（评审并启动实施）
>
> 前置文档：
> - [research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md](research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md)
> - [research-engine-plan-08-regression-test-matrix.md](research-engine-plan-08-regression-test-matrix.md)
> - [research-engine-plan-09-lui-execution-trace.md](research-engine-plan-09-lui-execution-trace.md)
> - [research-engine-plan-10-slash-command-and-agent-control-workplan.md](research-engine-plan-10-slash-command-and-agent-control-workplan.md)
> - [research-engine-plan-11-lui-qa-deep-preset-positioning.md](research-engine-plan-11-lui-qa-deep-preset-positioning.md)
> - [research-engine-plan-12-product-positioning-evolution.md](research-engine-plan-12-product-positioning-evolution.md)

## 1. 摘要

本计划为 PolyAgent `/dialogue` 受控 LUI 建立一套可复现、可审计、可持续回归的 Agent 评估体系，统一量化以下八项指标：

| 中文指标 | 英文指标 | 核心问题 |
| --- | --- | --- |
| 任务成功率 | Task Success Rate | 用户任务是否端到端完成 |
| 工具调用正确率 | Tool Call Accuracy | 模型是否选对工具并给出正确参数 |
| 检索召回 | Retrieval Recall@K | 知识库/联网证据是否在 Top-K 被找回 |
| 最终回答准确率 | Answer Accuracy | 最终回答是否满足事实与任务要求 |
| 幻觉率 | Hallucination Rate | 回答是否出现无依据、虚构或错误来源 |
| P50/P95 延迟 | P50/P95 Latency | 回答、首 token、工具和检索链路耗时 |
| 推理成本 | Token Cost | 完成任务需要多少 token，工具链路是否有额外开销 |
| 人工兜底比例 | Human Escalation Rate | 多少任务需要人工确认、补参或接管 |

本计划先建离线 Golden Set 和评测器，再接入现有 `assistant_runs`、`assistant_tool_calls`、`assistant_events` 与 Execution Trace。目标是让每次 LUI 变更都能回答“是否变好、是否变慢、是否更贵、是否更不可靠”。

## 1.1 评审记录（2026-08-28）

**评审基线**：`develop` 分支 `8005287`（收口外部 Agent 受限执行安全边界）。

**结论**：计划可进入实施。八项指标口径完整，与现有 `assistant_quality_service` 的分层正确——质量服务继续负责链路侧聚合，本计划补齐任务级结果质量。基于当前代码核对后，做以下调整并冻结 Phase 0 口径。

**现状核对**

- `assistant_runs.request_snapshot.context` 已持久化自由上下文，可直接携带评测字段，但缺少 `evaluation_id` / `task_id` 的规范化与查询索引。
- 检索链路已有 `retrieval.started` 与 `evidence` 事件，但缺稳定有序的结果条目（`id` / `rank` / `score` / `snippet` / `used_in_answer`）；web 引用仅保留 top-3 标题与 URL；`_knowledge_references` 未并入最终 references，当前无法计算 Recall@K 与引用使用映射。
- Execution Trace 已投影检索步骤，但结果摘要只含引用数量，不含结果条目。
- 工具调用已具备 `raw_arguments` / 解析后 `arguments` / `missing_fields` / `proposal_usage`，可直接支撑 M2 与 M7。
- 现有质量服务已覆盖 run/tool 终态、时长与 token 链路指标，可作为 M6/M7 的生产采样数据源。

**实施调整**

1. Phase 0 的“与团队确认”在本次无人评审会场景下，以本评审记录作为口径冻结依据；后续口径变更必须追加评审记录，不允许静默改答案。
2. 评测执行拆为两级：**离线 fixture 快速集**（不调用真实模型，用于回归门禁）与**录制事实评测**（任务经产品链路执行后，按 `evaluation_id` 从 run/tool/event 抓取原始事实再离线判定）。
3. 报告默认输出到 `backend/evaluation/lui/reports/`，受控基线入库 `backend/evaluation/lui/baselines/`，避免污染仓库根目录。
4. Phase 5 生产采样脚本默认 dry-run、只读聚合，不自动连接生产库、不写生产数据。
5. **计算任务不参与本评测**：xTB / CREST / ORCA / 本地结构生成等计算类任务以及 ComputeEngine 完整计算任务全部排除在评测范围外；LUI 工具类任务仅覆盖非计算工具（垂类预测、知识检索、优化推荐）的提案层行为，只评估工具选择、参数、确认、补参、权限与续答，不评估计算执行结果质量。

## 2. 目标与非目标

### 2.1 目标

- 建立固定、可版本化的 LUI 评测集，覆盖普通问答、检索问答、工具选择、工具参数、多轮、拒绝与失败恢复。
- 为八项指标给出可执行公式、数据来源、判定规则和建议阈值。
- 实现离线评测 harness，可自动执行任务、抓取 run/tool/event/trace 原始事实并输出 Markdown/JSON 报告。
- 用程序化判定处理确定性指标，用“LLM-as-judge + 人工抽检”处理开放回答与幻觉。
- 在现有质量指标之上补齐最终答案质量、幻觉、检索召回、成本与人工兜底，避免只测链路不测结果。

### 2.2 非目标

- 不把 LUI 改造成通用 coding-agent harness，不新增任意 Shell/文件/网络工具。
- 不替代现有 Playwright 回归与 `assistant_quality_service`，而是与其分层：功能回归看“能不能跑”，本计划看“跑得对不对、贵不贵、快不快”。
- 不在本期引入新的第三方评测运行时或服务；判定器优先使用项目内纯函数和现有 LLM provider。
- 不要求生产环境 100% 确定性；联网检索和开放问答先做可复现快照与人工抽检，再逐步扩大自动化。
- 不把“确认一次工具”简单等同于失败；工具确认是 LUI 的受控交互，单列并区分于失败接管。

## 3. 评估对象与边界

本文档中的 **LUI Agent** 指：

```text
用户通过 /dialogue 发起请求
  → 会话控制与 Slash Command
  → 模型路由 / Preset（qa、deep）
  → 上下文装配（项目事实、知识库、联网证据、工具目录）
  → 最终回答或算法工具提案
  → 用户确认 / 补参 / 权限决策
  → AlgorithmRun 执行
  → 服务端续答与最终回答
  → Execution Trace 回放
```

评估边界只覆盖当前受控 LUI 链路，不覆盖 ResearchEngine 的 AutoResearch 编排、ComputeEngine 完整计算任务和外部通用 agent provider。

补充边界（2026-08-28）：**计算任务不参与本评测**。xTB / CREST / ORCA / 本地结构生成等计算类工具，以及任何需要实际执行 ComputeEngine 计算的任务，均不进入 Golden Set，也不作为评测运行矩阵的工具候选。评测中的 LUI 工具任务只覆盖非计算工具（垂类预测、知识检索、优化推荐）在提案层的选择、参数、确认、补参、权限与续答行为；工具执行结果只判定链路终态与续答是否可用，不判定计算数值质量。

### 3.1 评估运行矩阵

| 维度 | 取值 | 备注 |
| --- | --- | --- |
| Preset / mode | `qa`、`deep` | 至少覆盖两种模式 |
| 模型能力 | `tool_calling`、非 `tool_calling` | 验证路由、fallback 与工具选择 |
| 知识库 | 开启、关闭、空结果 | 测检索召回和 no-results 处理 |
| 联网检索 | 开启、关闭、快照固定 | 联网结果非确定时使用快照 |
| 工具状态 | 0 个、1 个、多个相关 LUI 非计算工具 | 测选择准确率和多工具边界；xTB/CREST/ORCA 等计算类工具不参与 |
| 权限模式 | 默认 `workspace_write`、只读 | 测权限阻断与人工兜底 |

## 4. 八项指标定义

### 4.1 指标总表

| # | 中文指标 | 英文指标 | 建议主口径 | 数据来源 |
| --- | --- | --- | --- | --- |
| M1 | 任务成功率 | Task Success Rate | 成功任务数 / 有效任务总数 | run 终态、tool call 终态、最终 message、评测判定 |
| M2 | 工具调用正确率 | Tool Call Accuracy | 工具任务级正确数 / 工具任务总数；另报 call 级 precision/recall | `assistant_tool_calls`、`assistant_runs.request_snapshot`、Golden 答案 |
| M3 | 检索召回 | Retrieval Recall@K | 命中相关证据数 / 相关证据总数，按任务宏平均 | `assistant_events` 检索事件、`assistant_trace_service` 检索步骤、references、Golden 证据 ID |
| M4 | 最终回答准确率 | Answer Accuracy | 判定正确的可回答任务数 / 可回答任务总数 | 最终 message、Golden 答案、判定器 |
| M5 | 幻觉率 | Hallucination Rate | 无依据声明数 / 被检查声明总数 | 最终回答、references/evidence、工具结果、Golden 事实集 |
| M6 | P50/P95 延迟 | P50/P95 Latency | 端到端、首 token、工具执行、检索四组百分位 | run 时间字段、tool call 时间字段、trace 步骤 duration |
| M7 | 推理成本 | Token Cost | 总 token、每任务 token、工具链路 token 占比 | run 字段、`llm.usage.recorded` 事件、tool proposal/continuation usage |
| M8 | 人工兜底比例 | Human Escalation Rate | 需人工接管任务数 / 有效任务总数；辅以确认、补参、权限阻断、失败分类 | tool call phase、`awaiting_input`、权限事件、失败终态、反馈命令 |

### 4.2 M1 任务成功率

**定义**

```text
Task Success Rate = 判定为成功的任务数 / 有效任务总数
```

**成功标准**

1. 任务存在明确成功终点：
   - 普通问答：最终回答可回答且通过 M4；
   - 工具任务：模型提出正确工具、参数可执行、AlgorithmRun 成功、最终续答通过 M4；
   - 检索任务：检索命中要求满足，最终回答有据且通过 M4；
   - 拒绝/边界任务：正确拒绝、正确请求补参或正确给出范围外说明。
2. run 与 tool call 无未恢复失败、无死信 continuation。
3. 不允许把 `status=completed` 等同于成功；必须叠加结果正确性判定。

**建议目标**

- 内部确定性子集：≥ 90%。
- 全量离线集：≥ 75%，随 Golden Set 校准。

### 4.3 M2 工具调用正确率

**定义**

```text
任务级 Tool Call Accuracy =
  工具名称与全部参数均正确的工具任务数 / 需要工具调用的任务总数
```

**辅助口径**

```text
Tool Selection Precision = 正确工具调用数 / 实际工具调用数
Tool Selection Recall    = 正确工具调用数 / Golden 期望工具调用数
Argument Accuracy        = 参数正确工具调用数 / 已正确选择工具的调用数
```

**参数判定规则**

- 精确类型：字符串、枚举、布尔、ID 必须完全一致或语义等价。
- 数值类型：支持绝对误差、相对误差、有效数字和单位转换；Golden 中显式声明 tolerance。
- 可选字段：模型多填不影响执行的可忽略字段不扣分，但缺 required 字段必须扣分。
- `raw_arguments` 解析失败、`arguments_parse_error` 非空、`missing_fields` 非空均计为参数错误。
- 工具选择错误但参数碰巧正确，不计工具正确。

**建议目标**

- 任务级 Tool Call Accuracy ≥ 80%。
- Tool Selection Precision ≥ 85%。
- Tool Selection Recall ≥ 90%。

### 4.4 M3 检索召回

**定义**

```text
Recall@K(task) = 前 K 个检索结果中命中的相关证据数 / 该任务相关证据总数
Recall@K = 所有检索任务 Recall@K 的宏平均
```

**K 取值**

- 默认报告 `K ∈ {1, 3, 5}`，主指标为 `Recall@5`。
- 知识库任务以 `document_id` / `chunk_id` 作为命中单位。
- 联网任务在非确定时使用预先录制的检索快照，不把实时结果差异计入质量。

**当前缺口**

- 现有 `retrieval.started/result` 和 Trace 能表达“是否检索”，但需要补充稳定、有序的结果条目：`source`、`id`、`rank`、`score`、`snippet`、`used_in_answer`。
- 最终 references 需要与检索结果 ID 对齐，否则无法判断回答是否真的使用了 Top-K 证据。

**建议目标**

- 知识库固定集 `Recall@5 ≥ 90%`。
- 联网快照集 `Recall@5 ≥ 70%`，仅作为相对基线。

### 4.5 M4 最终回答准确率

**定义**

```text
Answer Accuracy = 判定为正确的可回答任务数 / 可回答任务总数
```

**任务分类与判定**

| 类型 | 判定方式 |
| --- | --- |
| 事实封闭题 | 精确匹配 / 事实列表全部命中 |
| 数值题 | Golden 数值 + tolerance |
| 短答案 / 结构化题 | 关键字段与 Golden 对照 |
| 开放分析题 | Rubric 判定，0–1 分，阈值通过 |
| 拒绝题 | 必须正确拒绝，不得强行编造 |
| 信息不足题 | 必须声明不确定，不得伪装完整证据 |

**判定器**

- 第一层：纯函数规则和字符串/数值比对。
- 第二层：现有 provider 驱动的 LLM-as-judge，必须输出判定依据。
- 第三层：每轮至少抽 20% 人工复核；分类型不一致率需低于 5%，否则该类型判定器不可上线。

**建议目标**

- 封闭事实题 ≥ 90%。
- 开放 Rubric 题平均分 ≥ 0.7。

### 4.6 M5 幻觉率

**定义**

```text
Hallucination Rate = 被判定为无依据的原子声明数 / 被检查的原子声明总数
```

**检查对象**

原子声明至少包括：

- 事实、数值、单位、时间、机构、人员；
- 材料体系、算法能力、模型能力；
- 工具是否可用、函数名、参数含义、结果数值；
- `algorithm_id`、`version_id`、`run_id`、文件路径、URL、citation、provider/model。

**判定为无依据，当且仅当**

1. 声明与 Golden 事实集、检索证据、项目事实或工具结果不一致；或
2. 没有任何可追溯来源；或
3. 引用了一个不存在的对象/版本/路径/来源。

**不判定为幻觉**

- 明确标注为不确定、推测、假设或建议；
- 回答正确拒绝或说明范围外。

**建议目标**

- 项目事实与工具结果子集 ≤ 3%。
- 联网开放子集 ≤ 10%。

### 4.7 M6 P50/P95 延迟

**定义**

| 延迟口径 | 起点 | 终点 | 数据字段 |
| --- | --- | --- | --- |
| 端到端 | run `created_at` | run `finished_at` | 含排队、模型、工具、续答 |
| 首 token | 模型流开始 | 首个 token | `first_token_ms` |
| 模型单轮 | LLM request started | LLM request finished | `llm.request.*` 事件、Trace 步骤 |
| 工具执行 | tool call `started_at` | tool call `finished_at` | `assistant_tool_calls` |
| 检索 | retrieval started | retrieval finished | Trace 步骤 duration |

**计算**

```text
P50 = 升序样本的 50 百分位
P95 = 升序样本的 95 百分位
```

只统计有效完成样本；失败/取消样本单列，不混入成功延迟。

**建议目标**

- 端到端 P95 ≤ 30s（工具任务允许更高，单列）。
- 首 token P95 ≤ 3s。
- 普通问答端到端 P50 ≤ 8s。
- 最终阈值以固定环境基准为准，不依赖共享网络波动。

### 4.8 M7 推理成本

**定义**

```text
每任务 Token Cost = Σ(prompt_tokens + completion_tokens) / 有效任务数
工具 Token 占比 = (proposal tokens + continuation tokens) / 全部 LLM tokens
```

**数据来源**

- `AssistantRun.prompt_tokens/completion_tokens/total_tokens`；
- `llm.usage.recorded` 事件；
- `AssistantToolCall.proposal_usage`；
- continuation run 的 usage。

**去重规则**

- 同时存在 run 字段与 usage 事件时，以 usage 事件为事实源；
- 无法取得真实 usage 时用 `estimate_tokens` 标注估算，不计入正式成本排名。

**建议目标**

- 每任务平均 token 不高于同模型直接问答基准的 1.5 倍。
- 工具任务中，因模型多次往返导致的 token 增量占比可解释；无效工具重试应单独报告。

### 4.9 M8 人工兜底比例

**定义**

```text
主指标 Human Escalation Rate =
  需要人工纠正/接管后才能继续或结束的任务数 / 有效任务总数
```

**计入人工兜底**

- 工具执行失败且最终未自动恢复；
- 权限阻断后用户必须切换策略或放弃；
- `awaiting_input` 因参数不足而终止；
- continuation 进入 dead letter；
- 最终回答明显失败，用户需重试或人工纠正。

**单列但不直接计入主指标**

- 工具确认次数：这是受控设计，不是失败；
- 普通补参后成功：记录交互次数，但不算失败兜底；
- 用户主动取消：按任务意图单独统计。

**建议目标**

- 安全自动化任务集 ≤ 10%。
- 工具任务集 ≤ 20%，且每一例都能从 trace 归因到路由、提案、权限、执行或续答阶段。

## 5. 现状可观测性差距

| 指标 | 已具备 | 仍需补齐 |
| --- | --- | --- |
| M1 任务成功率 | run/tool 终态、trace 投影 | 任务级 Golden 答案与 `evaluation_id`/`task_id` 关联 |
| M2 工具调用正确率 | tool_id、function_name、raw/parsed args、missing_fields | 参数 tolerance 规则与 call 级 precision/recall 汇总 |
| M3 检索召回 | `retrieval_status`、references、retrieval trace | 有序检索结果 ID/rank/score，以及“被最终回答使用”标记 |
| M4 回答准确率 | final message、references、answer_mode/scope | Rubric、Judge 输出和人工抽检流程 |
| M5 幻觉率 | references、retrieval_status、trace | 原子声明抽取、来源校验、对象存在性校验 |
| M6 延迟 | run duration/queue_wait/first_token、tool started/finished | 统一按 task 汇总四类延迟，失败样本单列 |
| M7 token cost | run usage、usage events、proposal usage | 去重口径、模型价格、每任务/工具链路归一化 |
| M8 人工兜底 | awaiting_input、权限事件、失败终态、反馈 | 统一“接管 vs 确认 vs 补参”分类和归因 |

## 6. Golden Set 设计

### 6.1 规模与分桶

| 分桶 | 说明 | 建议数量 |
| --- | --- | --- |
| 项目事实问答 | 入口、模块、算法、工具、报告链路 | 20–30 |
| 知识库检索问答 | 需要引用固定文档/分块 | 15–25 |
| 联网检索问答 | 使用快照或固定网页 | 10–20 |
| 工具选择 | 多个非计算 LUI 工具候选，考察选择 | 10–20 |
| 工具参数 | 数值/单位/枚举/必填/附件（仅非计算工具） | 15–25 |
| 多轮与上下文延续 | 依赖前文、补参、follow-up | 10–20 |
| 拒绝与边界 | 权限、范围外、信息不足、模型无工具能力 | 10–20 |
| 失败与恢复 | 工具失败、续答失败、权限阻断 | 10–15 |

首期建议 80–150 条，保证每类可统计。每个任务标注 `mode`、难度、模型约束、知识库/联网开关、期望行为和容忍度。

### 6.2 任务文件格式

建议使用 `backend/evaluation/lui/dataset/*.yaml`，单条结构如下：

```yaml
id: LUI-EVAL-0001
category: tool_argument
difficulty: medium
mode: qa
requires_model_capability: tool_calling
messages:
  - role: user
    content: 请使用 PI 合成难度评分工具评估 ODA 和 PMDA 在 NMP 中的合成难度。
context:
  selected_tool_ids:
    - algorithm:pi-synthesis-difficulty
  use_web_search: false
  knowledge_base_ids: []
expected:
  task_success: true
  tool_calls:
    - tool_id: algorithm:pi-synthesis-difficulty
      function_name: predict_pi_synthesis_difficulty
      arguments:
        monomers: [ODA, PMDA]
        solvent: NMP
        condition: dry
      tolerance:
        monomers: exact
        solvent: exact
  answer:
    type: rubric
    must_include:
      - 合成难度结论
      - 输入材料与溶剂
    forbidden:
      - 虚构算法版本
  hallucination_checks:
    - 算法版本必须来自工具返回
  escalation: none
```

### 6.3 数据质量要求

- 每条任务至少有一名领域作者标注，复杂工具参数至少双人复核。
- 数值题必须给出 tolerance；开放题必须给出 Rubric 而不是单一“标准答案”。
- 拒绝题必须说明什么回答算正确拒绝。
- 涉及真实算法/模型/机构的字段必须复用项目事实，禁止标注无来源的外部声称。
- Golden Set 随功能变更增加版本号，历史报告保留对应版本，不允许静默改答案。

## 7. 评测 Harness 设计

### 7.1 目录建议

```text
backend/evaluation/lui/
  README.md
  dataset/
    *.yaml
    fixtures/
  runner.py
  adapters.py
  evaluators/
    __init__.py
    task_success.py
    tool_call.py
    retrieval.py
    answer.py
    hallucination.py
    latency.py
    cost.py
    escalation.py
  metrics.py
  report.py
  schemas.py
scripts/
  run_lui_eval.py
backend/tests/
  test_lui_eval_schemas.py
  test_lui_eval_tool_call.py
  test_lui_eval_retrieval.py
  test_lui_eval_report.py
```

### 7.2 执行流程

```text
加载 Golden Set
  → 校验 schema 与上下文
  → 按 run matrix 启动评测会话
  → 通过受控 API/服务接口发送任务
  → 等待 run/tool/trace 终态
  → 抓取原始事实（run、tool_calls、events、trace、messages）
  → 逐任务执行 M1–M8 判定
  → 汇总报告
```

### 7.3 隔离与幂等

- 使用独立评测用户或 `LUI_EVAL_` 前缀会话，结束清理评测数据。
- 每个任务写入 `evaluation_id` 与 `task_id` 到 `request_snapshot.context`，便于审计和回放。
- 同一任务同一快照重复运行，确定性指标应一致；模型非确定场景报告多次采样的均值和置信区间。
- 不直接在评测进程内调用未被产品授权的外部工具；所有工具仍走现有 LUI 工具权限与确认链路。

### 7.4 报告格式

输出：

- `report.json`：机器可读原始指标；
- `report.md`：人类可读总结、按指标/分桶/模型/模式拆解；
- `cases/*.md`：失败样例、幻觉样例、人工兜底样例和 trace 摘要；
- `baseline.json`：作为后续回归对比基线。

## 8. 分阶段实施计划

### Phase 0：口径与 Golden Set 冻结

- [x] 与团队确认八项指标主口径、建议阈值和“人工兜底”边界。（2026-08-28 以 §1.1 评审记录冻结口径；补充边界：计算任务不参与评测）
- [x] 建立 Golden Set schema 和 80–150 条首期任务。（`backend/evaluation/lui/schemas.py` + 8 分桶 80 条，其中 37 条内置离线 fixture；工具任务仅含垂类预测/知识检索/优化推荐）
- [x] 选定默认评测模型矩阵：一个 tool-capable 主模型、一个非 tool-capable 模型、一个备选模型。（见 `backend/evaluation/lui/README.md`，具体模型以模型管理配置为准）
- [x] 产出 `README.md`、任务标注说明和人工抽检规则。

### Phase 1：可观测性补齐

- [x] 在 run 请求上下文中增加可选 `evaluation_id`、`task_id`、`evaluation_version`。（`AssistantRunService.create` 规范化，`AssistantRunRepository` 增加索引与 `find_by_evaluation_id`）
- [x] 为知识库/联网检索事件增加稳定结果条目：`source`、`id`、`rank`、`score`、`snippet`、`used_in_answer`。（新增 `assistant_retrieval_telemetry` 并在 `stream_chat` 发出 `retrieval.result`）
- [x] 在 AssistantMessage 或 Trace 中补齐 references 与检索结果 ID 的映射。（`AssistantReference` 增加 `source/source_id/rank/score` 可空字段；知识库引用并入最终 references；Trace 投影 `retrieval.result`）
- [x] 保持新字段可空、向后兼容，不破坏旧消息、旧 run 和历史回放。（`test_assistant_retrieval_telemetry.py` 6 项 + 既有 55 项相关测试通过）

### Phase 2：评测器实现

- [ ] 实现任务加载、schema 校验、会话创建、任务执行和原始事实抓取。
- [ ] 实现 M1 任务成功判定器。
- [ ] 实现 M2 工具选择 precision/recall 与参数 tolerance 判定。
- [ ] 实现 M3 Recall@1/3/5 和命中单位映射。
- [ ] 实现 M4 规则判定器与 LLM-as-judge 包装器。
- [ ] 实现 M5 原子声明抽取、来源校验和对象存在性校验。
- [ ] 实现 M6 四类延迟百分位与失败样本分离。
- [ ] 实现 M7 token 去重、每任务成本和工具链路占比。
- [ ] 实现 M8 人工兜底分类与归因。

### Phase 3：小规模试运行与人工校准

- [ ] 先在 30–60 条确定性任务上跑通。
- [ ] 人工抽检至少 20% 的 M4/M5 判定，计算判定器不一致率。
- [ ] 校准开放题阈值、参数 tolerance 和人工兜底分类。
- [ ] 生成首份 baseline 报告并评审。

### Phase 4：回归集成与门禁

- [ ] 将离线评测脚本接入 `make` 或独立命令，避免默认 `make test-backend` 每次跑真实模型。
- [ ] 增加 schema、工具判定、检索判定、报告生成的单元测试。
- [ ] 建立质量基线；后续 LUI 相关 PR 至少跑“确定性快速集”，发布前跑完整集。
- [ ] 把 M1–M8 汇总到现有 Admin 面板或独立报告页，与 `assistant_quality_service` 做区分。

### Phase 5：生产采样与持续观测

- [ ] 从生产 run/tool/event 抽样生成无 Ground Truth 的运行指标：M6、M7、M8 和链路侧 M2 候选。
- [ ] 用匿名化样本人工标注小批次，补充真实分布覆盖率。
- [ ] 每两周或每次大版本发布前刷新 baseline，发现成功率、幻觉、延迟或成本异常。

## 9. 测试与验证命令

```bash
# 评测器单元测试
PYTHONPATH=backend conda run -n poly_agent python -m pytest backend/tests/test_lui_eval_schemas.py backend/tests/test_lui_eval_tool_call.py backend/tests/test_lui_eval_retrieval.py backend/tests/test_lui_eval_report.py

# 快速确定性评测集
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_eval.py --dataset backend/evaluation/lui/dataset --mode smoke

# 完整评测并生成报告
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_eval.py --dataset backend/evaluation/lui/dataset --mode full --report-dir reports/lui-eval
```

## 10. 验收标准

本计划完成时需满足：

- [ ] Golden Set 版本化，任务结构可解析、可审计、可重复执行。
- [ ] 八项指标均可由 run/tool/event/trace 原始事实自动计算，并给出分子、分母和判定说明。
- [ ] 同一数据集重复运行，确定性指标误差在允许范围；随机项报告多次采样。
- [ ] 工具调用正确率支持 call 级 precision/recall 和任务级正确率。
- [ ] 检索召回支持 K=1/3/5，并能把最终回答与证据 ID 对应。
- [ ] 幻觉判定有来源依据，且至少 20% 样本人工复核。
- [ ] 延迟报告区分端到端、首 token、工具执行和检索。
- [ ] 成本报告区分最终回答、工具提案、续答和 compaction，且无重复计数。
- [ ] 人工兜底报告可区分确认、补参、权限阻断、失败接管和用户取消。
- [ ] 现有 Assistant 相关回归、前端构建和 LUI e2e 不回退。

## 11. 风险与规避

| 风险 | 影响 | 规避 |
| --- | --- | --- |
| 开放回答难以机器判定 | M4/M5 口径漂移 | Rubric 化、Judge 输出依据、人工抽检、不一致率门禁 |
| 联网检索不确定 | Recall@K 波动 | 使用快照或固定网页；区分实时与快照集 |
| 工具确认被误判为失败 | M8 虚高 | 明确区分受控确认、补参、权限阻断和失败接管 |
| Golden Set 污染 | 模型被针对性调优 | 按功能变更版本化，新增保留题和 holdout，报告不覆盖答案 |
| 真实模型成本与时间过高 | 无法频繁跑完整集 | 分层：smoke 快速集 + full 发布集 + 生产抽样 |
| 评测数据污染开发/演示存储 | 状态串扰 | 独立评测用户、前缀隔离、结束清理 |
| 新字段影响旧会话回放 | 历史兼容破坏 | 新字段全部可空，读取侧 fallback，旧消息不回写 |
| LLM-as-judge 自身偏见 | 判定偏差 | 双 Judge 或多次采样，关键样本人工复核 |

## 12. 状态记录

- 2026-08-18：创建评估计划，定义八项指标、Golden Set、评测 Harness、实施阶段与验收标准。状态为待评审 / 未开始。
