# 智能体打磨与闭环执行设计（SSRL 范式）

日期：2026-08-20
状态：架构设计建议 / 待评审
适用范围：ComputeEngine 计算适配器与 fixture、ResearchEngine 编排器与 Gate、助手工具调用与提示词、实验下发与真实执行接入、LUI Runtime 与多模型基准

计划代号：**智能体打磨与闭环执行**（Agent Honing & Closed-Loop Execution，AHCL）

前置与参考：

- SSRL「AI X-ray Scientist」论文（Nature Machine Intelligence 2026, DOI 10.1038/s42256-026-01261-5）：LLM 驱动 agent 在同步辐射束线 BL17-2 自主完成单晶取向标定，核心是「虚拟束线打磨 → MCP 工具接口 → 双层提示词 → 安全中继 → 自适应推理」
- 配套代码 `refer/大装置agent/ssrl/llm4xray-v0.0.0/`：MCP server、虚拟束线仿真器、长短提示词
- PolyAgent 总览：`README.md`
- ResearchEngine 技术方案：`doc/research-engine-and-auto-research-design.md`
- 同源 ALS 借鉴设计：`doc/plan-als-orchestration-and-bounded-execution.md`（同为「大装置 Agent」参考系列，ALS 聚焦 Plan-first 编排与受限执行，本设计聚焦虚拟打磨与闭环执行，两者互补）
- 实验下发设计：`doc/experiment-dispatch.md`
- LUI Runtime 与工具调用：`doc/research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md`

## 1. 背景与判断

### 1.1 工作概述

SSRL 团队的「AI X-ray Scientist」没有引入新算法，也未微调模型，而是回答一个更朴素的问题：**现成的推理型 LLM，加上结构化工具接口，能不能在真实大科学装置上完成闭环物理实验？** 答案是能——agent 在同步辐射光束线 BL17-2 上自主完成了单晶样品取向标定（orientation matrix），这是所有单晶散射实验的前置必备步骤。

任务是在倒易空间里用六圆衍射仪（4S+2D，六个自由度）导航，受电机限位和安全联锁约束，并面对隐藏偏置、旋转中心不完美、面内取向未知等需要人类专家反复试错的困难。系统由三个支柱组成：

- **虚拟束线**：Python 物理仿真器复刻真实衍射仪的操作语义，在普通笔记本运行。它不是为了演示，而是作为 agent 的**正式开发与打磨环境**——在不消耗昂贵机时的前提下迭代提示词、发现失败模式、回归验证。
- **MCP server 工具接口**：`create_session`（建带全局状态的会话）→ `execute_command`（发类 SPEC 终端命令，关键词解析映射到实验对象方法）→ `get_detector_image` / `get_scan_data_image`（取探测器图和带拟合曲线的扫描图）。真机侧补 `read_log` / `explore_directory` / `read_and_plot_*` 等只读工具。
- **双层提示词**：长 prompt = 详细工作流 + 逐个工具文档（与具体晶体无关、可泛化）；短 prompt = 关键提醒，把长 prompt 里 agent 在虚拟实验中没遵守的行为再次强调（短 prompt 里大量 `⚠️ CRITICAL` 正是失败模式驱动的迭代产物）。

闭环工作流是「setup → 主参考峰搜索优化 → 次参考峰搜索优化」，但阶段切换、选哪个峰、怎么配 scan **不硬编码**，全由 agent 基于观测自主决定，工作流只是「概念脚手架」。真机时人**原样转发** agent 命令（纯安全代理，不改结果），执行后只回一句"请读日志继续"。agent 在真机发现意外 η 偏置 ~1.22° 后，主动记录并在后续步骤复用——超出固定脚本的「自适应推理与短期实验记忆」。

### 1.2 同构性判断

PolyAgent 与该工作本质同构：都是「LLM agent + 结构化工具 + 多阶段实验/计算流程 + 高代价真实执行 + 人工安全约束」。论文把「束线/衍射仪」换成 PolyAgent 的「计算/优化/垂类预测/实验派发」，范式可直接平移。

PolyAgent 已有的 ComputeEngine mock/fixture、adapter 契约、Gate 审批、tool confirmation、多 provider LUI Runtime，恰好对应论文的虚拟束线、MCP、安全中继、多模型基准——**基础设施已经具备，缺的是论文那套「用虚拟环境系统化打磨 agent、用失败模式迭代提示词、用基准验证鲁棒性、把经验修正做成 session 内即时复用」的方法论闭环**。

### 1.3 与 ALS 借鉴设计的分工

同目录的 `plan-als-orchestration-and-bounded-execution.md` 聚焦「Plan-first 显式依赖计划 + 动态能力选择 + 受限执行 + 统一安全层」，回答的是**编排透明度与规模化**问题。本设计聚焦**方法论闭环与真实执行落地**：虚拟打磨、双层提示词、图像化观测、会话级持久与短期记忆、被动转发安全模式、工作流级鲁棒性基准。两者互补，不重叠——ALS 让 Gate 拥有可审查对象，本设计让 agent 在上真机前被系统化打磨并具备自适应能力。

## 2. 设计目标与非目标

### 2.1 目标

1. 把现有 mock/fixture 层正式定义为 agent 的**虚拟打磨环境**，配套「失败模式登记 → 提示词修正 → 回归验证」闭环。
2. 给助手提示词引入显式的**双层结构**（长 guidance / 短提醒），并建立失败模式驱动的迭代机制。
3. 把垂类算法/计算结果回喂 agent 时统一**渲染成带标注的图**，而非裸 JSON/表。
4. 在实验派发 session 内引入**会话级持久实验对象**与**短期实验记忆**（经验修正即时复用）。
5. 给真实执行接入增加**被动转发（relay）安全模式**，与现有审批门模式并存。
6. 建**agentic 工作流基准台**：多模型 × 多次 run × 明确成功判据 × 注入扰动，在真机/生产前量化鲁棒性。
7. 探索 **meta-agent 自动生成垂类 guidance prompt**，降低新算法/新实验类型接入成本。

### 2.2 非目标

- 不引入裸脚本/任意代码执行通道；保持现有结构化工具契约 + `validate_arguments` 路线，不退回论文的关键词解析命令方式。
- 不在本设计落地 ALS 设计已覆盖的 Plan-first 显式依赖计划与动态能力选择。
- 不改变 P0 已固化的阶段序列语义；从「固定序列」松动为「概念脚手架」列为 P2 演进方向，不在本期强制。
- 不替代现有 `speclabos_dispatch_service` 的下发契约，仅在其上叠加 relay 模式。

## 3. 总体范式与支柱映射

SSRL 范式落到 PolyAgent 现有模块的映射如下，作为后续逐项设计的索引：

| SSRL 机制 | PolyAgent 现状模块 | 已具备 | 本设计补齐项 | 优先级 |
| --- | --- | --- | --- | --- |
| 虚拟束线（打磨环境） | `computation_adapters/` 的 ORCA fixture、`local_xtb.py`、ComputeEngine mock | fixture 可跑、adapter 契约 | 失败模式登记 + 提示词迭代 + 回归验证闭环 | 高 |
| 双层提示词 | `assistant_presets.py`、`assistant_context_assembler.py` | 上下文组装 | 显式长/短分层 + 失败模式驱动迭代 | 高 |
| 图像化观测 | `report_renderers/`、artifact 管理、ECharts/Plotly | 面向人的渲染 | 渲染结果回喂 agent 输入通道 | 高 |
| 会话级持久实验对象 | `assistant_tool_service.py` 有序工具状态机 | 工具调用状态机 | 同一上下文对象跨步累积 | 中 |
| 短期实验记忆 | `assistant_context_assembler` 会话历史 | 对话历史 | 实验级经验修正字段，即时复用 | 中 |
| 安全中继（被动转发） | Gate `StageGate/GateDecision`、tool `awaiting_confirmation` | 审批门模式 | relay 模式，与审批门并存 | 中 |
| 多模型基准 + 对抗条件 | LUI Runtime 调用质量指标 | provider 调用层指标 | 工作流级成功率基准台 | 中 |
| 虚拟/真机同 guidance | `computation_adapters/base.py` 契约、`integration_config_service` | adapter 契约、接口切换 | 确认环境无关原则，补只读工具 | 低（确认项） |
| 概念脚手架（非脚本） | `research_engine_orchestrator.py` 固定序列 | P0 固定阶段序列 | 序列松动为 scaffold（P2） | 低（演进项） |
| meta-agent 生成 prompt | `algorithm_requirement_doc_service.py`、`algorithm_model_proposal.py` | 算法文档/契约雏形 | 从契约自动生成长 guidance | 低（探索项） |

## 4. 借鉴点与 PolyAgent 落地设计

### 4.1 【高】虚拟打磨环境：把 mock/fixture 升格为 agent 开发闭环

#### 4.1.1 现状

ComputeEngine 已有完整的 fixture 与 adapter 层：

- `backend/app/computation_adapters/base.py` 定义 `AdapterContext`、`ArtifactSpec`、`AdapterRunResult` 与 `build_steps`，是统一的执行契约。
- `backend/app/computation_adapters/orca_compute_engine_laser.py` 是 ORCA/ComputeEngine 的受控 fixture。
- `backend/app/computation_adapters/local_xtb.py` 是本地 xTB/CREST 真实适配器。
- `backend/app/workers/computation_worker.py` 负责原子领取任务、执行 adapter、写 heartbeat、回收 stale run。

但当前 fixture 的定位是「本地演示/验收」（README 明确写明 mock/fixture/demo store 只用于本地演示或验收），没有作为 agent 提示词迭代与鲁棒性验证的正式环境。

#### 4.1.2 差距

- 缺少「失败模式登记」机制：agent 在 fixture 上跑出的错误行为（不合理的 scan 范围、漏采尾部、误认热像素为峰等类比场景）没有被结构化记录并驱动提示词修正。
- 缺少「回归验证」：提示词改了之后，没有一组固定任务自动重跑来确认是否回归。
- fixture 与 agent 提示词之间没有闭环：fixture 跑完只产出 artifact 给人看，没有把「agent 行为是否符合预期」反馈到提示词迭代。

#### 4.1.3 目标设计

1. **失败模式登记表**：在 `.runtime/` 下新增 agent 打磨日志，每次 fixture run 记录任务类型、模型、提示词版本、失败现象、根因归类、对应提示词修正项。结构复用现有 audit event 载体。
2. **回归任务集**：选 3–5 个代表性 ResearchRun/垂类任务作为固定回归集，每次提示词变更后自动重跑，对比成功率与关键中间步骤。
3. **fixture 环境无关化**：确认 fixture 与真机 adapter 共用同一套 agent 提示词，差异只在后端实现。这与 4.8 的「环境无关原则」联动。
4. **接入 checkpoint/rerun**：复用 P1 规划的 checkpoint 能力，让失败的 fixture run 可从中间步骤 rerun，加速打磨迭代。

> 论文实证：虚拟束线不是 demo，而是 guidance prompt 的正式开发环境，团队在其中反复发现「agent 把扫描尾部当峰」「没记住电机偏置」等失败模式，逐条写进短 prompt 的 `⚠️ CRITICAL`。

### 4.2 【高】双层提示词：长 guidance / 短提醒 + 失败模式驱动迭代

#### 4.2.1 现状

- `backend/app/services/assistant_presets.py` 维护助手预设。
- `backend/app/services/assistant_context_assembler.py` 组装上下文 manifest。
- 工具契约来自 `agent_tool_service` 与垂类算法的 `AlgorithmAssetSpec`。

但上下文组装没有显式分「长 guidance / 短提醒」两层，也没有失败模式驱动的迭代机制。

#### 4.2.2 差距

- 长 prompt（工作流 + 工具文档，领域无关、可泛化）与短 prompt（必做提醒，针对 agent 没遵守的行为）没有分层，所有内容混在一份上下文里。
- 没有「从失败模式沉淀提醒」的通道：4.1 登记的失败模式无法结构化地回流为短 prompt 条目。

#### 4.2.3 目标设计

1. **显式分层**：`assistant_context_assembler` 组装时分两段——
   - **长 guidance**：垂类算法/实验类型的通用工作流、坐标系/领域约定、逐个工具的文档与示例，与具体体系无关。
   - **短提醒**：从失败模式登记表沉淀的「必做提醒」，带优先级与触发条件，在长 guidance 之后注入。
2. **失败模式 → 短提醒回流**：4.1 的失败模式登记表新增「已转为提醒」标记，经人工确认后写入短提醒库，按任务类型匹配注入。
3. **版本化**：长/短 prompt 各带版本号，与回归任务集联动，变更后自动触发回归。

> 论文实证：短 prompt `assets/prompts/17_2_mcp_inp.md` 里大量 `⚠️ CRITICAL` 条目（细扫描、记住偏置、宽 ϕ 扫描覆盖对称性、勿认热像素为峰）全是虚拟实验中观察到的失败模式逐条沉淀，长 prompt `assets/prompts/17_2_mcp.md` 则是完整工作流与工具文档。

### 4.3 【高】图像化观测：结果回喂 agent 用图不用裸表

#### 4.3.1 现状

- `backend/app/services/report_renderers/` 有 html/latex/markdown/pdf 四种 renderer。
- artifact 管理覆盖结构、计算结果、优化诊断图。
- 前端用 ECharts/Plotly 可视化。

但这些渲染主要面向人，不一定回喂 agent 的输入通道。

#### 4.3.2 差距

- 垂类算法/计算结果回喂 agent 时多为原始 JSON/表，缺少带标注的图。
- LLM 对原始数值数组的定性判读能力弱（论文刻意避免喂裸数据）。

#### 4.3.3 目标设计

1. **统一渲染回喂**：垂类算法/计算结果回喂 agent 时，经 renderer 产出带标注的图（关键量叠加、拟合曲线、峰位/极值标注），以图像形式注入 agent 输入。
2. **复用现有 renderer**：不新建渲染管线，在 `report_renderers` 基础上增加「agent 回喂」输出模式，复用 ECharts/Plotly 静态出图。
3. **按任务类型选图**：不同任务类型（优化诊断、谱图、结构）选不同图模板，与 4.2 的长 guidance 联动描述「如何读图」。

> 论文实证：探测器图作图像输入做定性判读，扫描结果渲染成带拟合曲线和峰位的图，不喂原始数值数组——论文明确指出这对 LLM 推理更友好。

### 4.4 【中】会话级持久实验对象：同一上下文跨步累积

#### 4.4.1 现状

- `backend/app/services/assistant_tool_service.py` 有有序工具调用状态机：`CALLABLE_PHASES`、`awaiting_confirmation`、`confirm` 等阶段管理。
- 但每次 `AlgorithmRun` 是独立的，缺少「同一实验对象跨步累积」的语义。

#### 4.4.2 差距

- 工具调用之间缺少一个持久「实验对象」，agent 跨多步的 move/scan/读图无法在同一对象上累积状态。
- 闭环实验的「中间状态延续」没有一等公民载体。

#### 4.4.3 目标设计

1. **持久上下文对象**：在 ResearchRun/实验派发 session 内引入持久实验上下文对象，agent 创建会话后，后续垂类算法/计算调用都作用在同一对象上，发现的参数与中间状态自动延续。
2. **复用现有状态机**：在 `assistant_tool_service` 的状态机上扩展 session 级对象绑定，不重造轮子。
3. **泛化多域**：PolyAgent 是多域多算法，「单一 experiment 对象」泛化为「按任务类型实例化的上下文对象」，由任务类型决定对象 schema。

> 论文实证：`create_session` 后实例化 `experiment` 对象，agent 跨多步在同一对象上 move motor / scan / 读图，状态持续累积，这是闭环实验的基础语义。

### 4.5 【中】短期实验记忆：经验修正即时复用

#### 4.5.1 现状

- `assistant_context_assembler` 维护会话级对话历史。
- `assistant_export_service` 支持会话导出。
- 但没有「实验级经验参数」的结构化沉淀与即时复用。

#### 4.5.2 差距

- agent 发现的偏置、修正量、经验参数只在对话历史里，没有结构化字段，后续步骤无法自动注入。
- 路线图 P2 的「经验沉淀」是跨项目宏观沉淀，缺一个更轻的「session 内即时复用」层。

#### 4.5.3 目标设计

1. **经验修正字段**：在 4.4 的持久上下文对象上增加 `empirical_corrections` 字段，记录 agent 发现的偏置、修正量、适用范围。
2. **自动注入后续步骤**：后续工具调用的参数计算自动叠加已记录的修正，并在短提醒里提示「已应用偏置 X」。
3. **session 内即时、跨项目可选**：本期只做 session 内即时复用（轻量、贴合论文）；跨项目沉淀留待 P2。

> 论文实证：agent 在真机发现 η 偏置 ~1.22°，主动记录并在后续次参考峰搜索中复用（η = 2.06° − 1.22° = 0.84°），论文称之为「自适应推理与短期实验记忆，超出固定脚本」。

### 4.6 【中】安全中继：被动转发模式与审批门并存

#### 4.6.1 现状

- Gate：`backend/app/services/research_engine_orchestrator.py` 的 `StageGate` / `GateDecision` / `StageApprovalRequest`，`approve_stage` / `reject_stage` 是「批准/驳回 AI 计划」模式，人会影响走向。
- Tool confirmation：`assistant_tool_service.py` 的 `awaiting_confirmation` + `confirm`，`requires_confirmation` 控制是否需人工确认。
- 真实下发：`backend/app/services/speclabos_dispatch_service.py` 已有 SpecLabOS HTTP 下发契约。

#### 4.6.2 差距

- 现有两种人工介入都是「审批计划」语义（人可改走向），缺少「纯安全放行」语义（人原样转发、不改结果、不参与判断）。
- 真机实验场景下，论文的 relay 模式更贴合——保留 agent 完全自主性，人只满足设施安全要求。

#### 4.6.3 目标设计

1. **新增 relay 模式**：在 `speclabos_dispatch_service` 接真实设备时增加 relay 模式——agent 产出命令 → 人点击执行（纯安全放行）→ agent 读回日志/产物继续。与论文的 `Execute Command: [...]` + "请读日志继续" 对应。
2. **两种模式并存**：高后果操作（不可逆、高代价）用审批门（现有 Gate）；常规执行用被动转发（relay）。由任务类型与 target 契约配置选择。
3. **relay 不降级安全**：relay 仍记录全链路 audit，人点击即留下执行凭证，但不在决策链上引入人的判断偏置。

> 论文实证：真机时人「原样转发 agent 命令，不改结果」，纯安全代理，执行后只回"请读日志继续"，保留 agent 完全自主性。

### 4.7 【中】agentic 工作流基准台：多模型 × 多次 run × 对抗条件

#### 4.7.1 现状

- LUI Runtime 有「调用质量指标」（`doc/research-engine-plan-13-lui-agent-evaluation-plan.md`、`doc/research-engine-plan-14-lui-dynamic-compute-budget-plan.md`）。
- 但那是 provider 调用层指标（延迟、token、错误率），不是**工作流级成功率**基准。

#### 4.7.2 差距

- 没有「同一 ResearchRun/AutoResearch 任务跑 N 次 × 多 provider × 定义成功判据 × 注入扰动」的基准台。
- 真机/生产模型接入前缺少鲁棒性量化依据。

#### 4.7.3 目标设计

1. **工作流级成功判据**：按任务类型定义成功指标（类比论文的「对齐误差 ≤15° 且 |c_pred − c_true| ≤ 0.01Å」），如「优化收敛」「预测误差阈值」「实验派发可执行」。
2. **多模型矩阵**：对同一任务跑多 provider（OpenAI/Ollama/Edison/Codex/自定义 HTTP），统计成功率与中间步骤分布。
3. **对抗条件注入**：注入输入抖动、降推理预算、换模型等扰动（类比论文的更大偏置/多晶/降 thinking/降温），量化退化曲线。
4. **真机前置门**：基准台通过率作为接入真实预测模型服务/真机的前置条件。

> 论文实证：Claude Sonnet 4 与 Gemini 2.5 Flash 各 10 次独立 run，定义成功判据，并测大偏置/多晶/降推理预算/降温等 adversarial 场景，在真机前量化鲁棒性。真机选用更强的 Claude Opus 4 是「最大化鲁棒性、最小化运营风险」的实用选择。

### 4.8 【低·确认】虚拟/真机同 guidance：确认 adapter 契约方向 + 补只读工具

#### 4.8.1 现状

- `backend/app/computation_adapters/base.py` 的 `AdapterContext` / `ArtifactSpec` 契约。
- `backend/app/services/integration_config_service.py` 管理集成配置。
- `speclabos_dispatch_service` 接真实设备。

#### 4.8.2 设计

- **确认方向正确**：现有 adapter 契约 + 接口层切换正是论文「guidance 不变、只换工具后端」的思路。
- **强调原则**：agent 提示词必须环境无关（mock/真机共用），只有工具后端切换。真机侧补充「读日志/读产物/读图」类只读工具即可，不在 prompt 里写死环境细节。
- **只读工具清单**：真机侧参考论文补 `read_log`（读运行日志）、`explore_directory`（列产物文件）、`read_and_plot_image`（读并渲染图）、`read_and_plot_spec`（读并渲染扫描/谱），对应 PolyAgent 的 artifact 浏览与渲染能力。

### 4.9 【低·演进】概念脚手架：从固定阶段序列走向 agent 自主切换

#### 4.9.1 现状

- `backend/app/services/research_engine_orchestrator.py` 是 P0 固定阶段序列 + mock 阶段推进 + Gate 审批。
- `backend/app/services/research_engine_defaults.py` 的 `DEFAULT_STAGE_SEQUENCE`（固定 10 阶段）、`P0_GATE_STAGES`、`DEFAULT_STAGE_CONTRACTS`。

#### 4.9.2 设计（P2 演进方向，不在本期强制）

- 把固定 stage 序列松动为「概念脚手架」：给出目标和可用工具集，让 agent 根据中间结果决定何时进入下一阶段、是否回退补扫。
- `DEFAULT_STAGE_SEQUENCE` 保留为默认 scaffold，但允许 agent 跳过/重排，由编排器校验契约一致性。
- 与 ALS 设计的 Plan-first 计划联动：agent 自主切换的决策落到显式计划对象上，保持可审查。

> 论文实证：阶段切换、目标选择、参数配置全由 agent 基于观测决定，控制流不硬编码，工作流只是「概念脚手架而非执行脚本」。

### 4.10 【低·探索】meta-agent 自动生成垂类 guidance prompt

#### 4.10.1 现状

- `backend/app/services/algorithm_requirement_doc_service.py` 生成算法需求文档。
- `backend/app/services/algorithm_model_proposal.py` 生成算法模型提案。
- `backend/app/services/llm_config_schema_service.py` 管理 LLM 配置 schema。

#### 4.10.2 设计（探索项）

- 做 meta-agent：从垂类算法契约 + 文档**自动生成长 guidance prompt**（工作流 + 工具说明 + 领域约定），与 P1 的 Schema 驱动算法表单 / AlgorithmRegistry 管理协同。
- 降低新算法/新实验类型接入门槛，类比论文未来方向「meta-agent 协助构造仪器专属 guidance prompt」。

## 5. 分期实施路线

| 期 | 借鉴点 | 动作 | 与现有路线图关系 |
| --- | --- | --- | --- |
| **P1 立即可做** | 4.1 虚拟打磨环境 | 失败模式登记表 + 回归任务集 + fixture 环境无关化 | 补齐 mock 闭环验证；联动 P1 checkpoint/rerun |
| **P1 立即可做** | 4.2 双层提示词 | context_assembler 显式分层 + 失败模式回流 | 低成本高杠杆 |
| **P1 立即可做** | 4.3 图像化观测 | renderer 增加 agent 回喂模式 | 复用现有 renderer |
| **P1** | 4.7 工作流基准台 | 成功判据 + 多模型矩阵 + 对抗条件 | 真实预测模型服务接入前置验证 |
| **P1–P2** | 4.4 持久实验对象 | session 级上下文对象 | 联动 LUI Runtime 工具调用 |
| **P1–P2** | 4.5 短期实验记忆 | empirical_corrections 字段 + 自动注入 | 轻量版经验沉淀 |
| **P2** | 4.6 安全中继 | speclabos relay 模式 + 与审批门并存 | 真实执行接入 |
| **P2** | 4.9 概念脚手架 | 固定序列松动为 scaffold | 与 ALS Plan-first 联动 |
| **P2+** | 4.10 meta-agent | 契约自动生成 guidance | 与 AlgorithmRegistry 协同 |
| **持续** | 4.8 环境无关 | 确认原则 + 补只读工具 | 方向确认，无新框架 |

## 6. 不照搬与需改造项

- **关键词解析命令**：论文用 keyword detection 解析 `umv/dscan` 等终端命令，是单仪器场景的务实 hack。PolyAgent 已有结构化工具契约 + `validate_arguments`，更健壮，**保持现有结构化路线，不退回关键词解析**。
- **单仪器单任务**：论文是一个衍射仪、一个对齐任务。PolyAgent 是多域多算法，「单一 experiment 对象」需泛化为「按任务类型实例化的上下文对象」（见 4.4.3）。
- **现成 LLM 不微调**：与 PolyAgent 多 provider LUI Runtime 一致，方向吻合，无需改。
- **真机选最强模型**：论文真机用 Claude Opus 4 以「最大化鲁棒性、最小化运营风险」。PolyAgent 接真机/生产时可参考此策略，由基准台（4.7）给出模型选择依据。

## 7. 验收与风险

### 7.1 验收要点

- 虚拟打磨环境：失败模式登记表有条目、回归任务集可自动重跑、至少 1 个提示词修正闭环跑通。
- 双层提示词：context_assembler 输出可区分长/短两段，至少 3 条失败模式回流为短提醒。
- 图像化观测：至少 2 类任务结果以带标注图回喂 agent，回归任务集确认判读改善。
- 工作流基准台：至少 2 个 provider × 10 次 run × 1 组对抗条件产出成功率报告。
- 安全中继：relay 模式可配置，audit 链完整，与审批门模式可切换。

### 7.2 风险与缓解

- **风险**：打磨闭环变成人工负担。**缓解**：失败模式登记尽量自动捕获（从 audit event 与 run 失败信号提取），回归任务集自动化。
- **风险**：双层提示词膨胀。**缓解**：短提醒带优先级与触发条件，按任务类型匹配注入，不做全量堆叠；与 ALS 设计的动态能力选择联动控制 prompt 规模。
- **风险**：持久实验对象引入状态复杂度。**缓解**：复用现有工具状态机，session 级隔离，到期清理。
- **风险**：relay 模式被误用为绕过审批。**缓解**：relay 仅限低后果且 target 契约显式允许的操作，高后果强制审批门，两者由配置分级。
