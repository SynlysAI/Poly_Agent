---
title: "Poly Agent 主要功能"
slug: "features"
type: "product-overview"
version: "0.1.0"
release_date: "2026-08-19"
updated_at: "2026-08-19"
language: "zh-CN"
status: "ready-for-review"
audience:
  - "材料科学家"
  - "算法与计算工程师"
  - "实验平台管理员"
  - "研发负责人"
---

# Poly Agent 主要功能

## 1. 产品定位

Poly Agent 是 AI4MS 门户下的高分子材料智能研发平台。它把材料研发中的问题定义、文献证据、计算任务、垂类预测、实验优化、人工审批和研发报告组织到同一条可追溯工作流中。

当前版本 `0.1.0` 的定位是：

- **领域工作台**：面向高分子材料研发，而不是通用编码或办公 Agent。
- **任务优先**：先定义 ProblemSpec，再选择人工 Workflow 或 AutoResearch。
- **证据驱动**：知识库、数据目录、计算结果和算法输出都保留来源与运行记录。
- **人工可控**：关键研发决策通过 Gate 审批，不把重要动作交给无约束自动化。
- **可审计**：模型运行、算法调用、命令控制、工具结果和 artifact 进入统一事件流。

本版不提供通用 Shell、任意文件编辑、插件市场或无约束自动化执行。真实 ORCA/HPC/AiiDA、SpecLabOS 设备执行和生产级外部模型服务仍按集成配置逐步接入。

## 2. 快速入口

| 目标 | 推荐入口 | 适用场景 |
| --- | --- | --- |
| 查看整体状态 | `/dashboard` | 查看模块统计、服务状态、命令会话和最近任务 |
| 定义研发任务 | `/research-engine` | 创建 ProblemSpec，选择人工 Workflow 或 AutoResearch |
| 提交计算 | `/computations/submit` | 本地结构生成、xTB/CREST 粗优化、ORCA 精加工 |
| 查看计算结果 | `/computations/runs` | 查看 run 生命周期、artifact 和错误详情 |
| 设计实验 | `/optimization/alchemist` | 变量定义、DoE/OED、GP 建模和采集优化 |
| 管理垂类模型 | `/vertical-prediction` | 算法上传、接口配置、版本治理和在线测试 |
| 检索知识 | `/knowledge` | WeKnora 问答、证据清单和可选图谱 |
| 管理数据 | `/database/data-catalog` | 数据资产目录、数据集详情和记录下钻 |
| 使用助手 | `/dialogue` | 项目事实问答、算法工具调用和 Slash Command 控制 |
| 查看任务 | `/tasks/center` | 聚合计算任务、算法运行和 ResearchEngine 任务 |
| 管理服务 | `/tools` | 查看工具、LLM 模型和服务健康状态 |

## 3. ResearchEngine 研发引擎

### 3.1 解决的问题

ResearchEngine 解决“材料研发任务如何被定义、执行、审计和复用”的问题。它避免把研发过程拆散在聊天记录、表格、脚本和本地文件中，而是把任务、算法、计算、证据和报告放在同一套领域模型里。

### 3.2 核心概念

| 概念 | 含义 | 主要产出 |
| --- | --- | --- |
| ProblemSpec | 研发任务定义，描述材料体系、目标、约束和验收口径 | `problem_spec_snapshot` |
| ExecutionDecision | 在人工工作台和 AutoResearch 之间显式选择执行路径 | 执行模式与原因记录 |
| ManualAlgorithmWorkflow | 人工编排的算法工作流 | WorkflowRun、WorkflowStepRun |
| AutoResearch | 自动编排通道，按阶段推进研发流程 | ResearchRun、StageRun |
| AlgorithmRun | 单次算法或模型调用记录 | 输入快照、输出摘要、artifact、audit |
| Gate | 人工审批点 | GateDecision、审批原因和时间 |
| Traceability | 追溯链 | run、stage、artifact、audit 聚合视图 |
| Report | 研发报告生成结果 | HTML、LaTeX、Markdown、PDF |

### 3.3 使用流程

1. **创建或选择 ProblemSpec**
   - 进入 `/research-engine`，在“研发任务定义”中创建任务。
   - 明确材料体系、目标性质、约束条件、测量条件和验收标准。
   - ProblemSpec 保存的是研发意图，不保存某个算法的临时参数。

2. **选择执行路径**
   - **人工算法工作台**：适合专家希望控制算法顺序、输入和参数的场景。
   - **AutoResearch 自动编排**：适合目标清晰、希望系统连续推进多阶段闭环的场景。
   - 选择会生成 ExecutionDecision，后续不能绕过该决策直接启动运行。

3. **人工 Workflow 通道**
   - 从已治理算法清单中选择节点，编排单节点或多节点 Workflow。
   - 启动后生成 WorkflowRun，逐步触发 AlgorithmRun。
   - 每个节点保留输入快照、输出摘要、artifact、错误信息和审计事件。

4. **AutoResearch 通道**
   - 选择 ProblemSpec、材料 Profile、最大迭代次数和批次大小。
   - 点击“创建草稿”，系统生成 10 个 StageRun。
   - 点击“启动”并填写启动原因，流程从 `PROBLEM_SPEC` 开始推进。
   - 到达 Gate 后状态变为 `blocked_approval`，必须人工批准或拒绝。

5. **查看追溯与生成报告**
   - 在 ResearchRun、WorkflowRun、AlgorithmRun 或 StageRun 详情中查看输入、输出、artifact 和 audit。
   - 在报告面板选择模型服务和渲染格式，生成研发报告。

### 3.4 AutoResearch 十阶段

| 阶段 | 中文名 | 当前是否触发审批 | 作用 |
| --- | --- | --- | --- |
| `PROBLEM_SPEC` | 问题定义 | 是 | 解析研发任务，提取目标、约束与测量条件 |
| `KNOWLEDGE_RETRIEVAL` | 文献检索 | 否 | 检索文献、知识库和图谱证据 |
| `STRUCTURE_FEATURE` | 结构表示 | 否 | 将结构转换为描述符或特征 |
| `COMPUTE_PREDICT` | 计算预测 | 否 | 运行计算或调用预测模型 |
| `RECOMMENDATION_ASK` | 候选推荐 | 是 | 基于目标和约束生成候选建议 |
| `HUMAN_REVIEW` | 人工审核 | 否 | 汇总推荐结果供人工查看 |
| `EXPERIMENT_EXECUTION` | 实验执行 | 是 | 提交计算或实验任务 |
| `RESULT_TELL` | 结果回填 | 否 | 将结果回填为 Observation |
| `MODEL_UPDATE` | 模型更新 | 否 | 更新代理模型或推荐策略状态 |
| `ARCHIVE_LEARNING` | 经验归档 | 否 | 归档过程、失败原因和可复用经验 |

当前 P0 只有 `PROBLEM_SPEC`、`RECOMMENDATION_ASK`、`EXPERIMENT_EXECUTION` 三个阶段会触发运行时审批。`HUMAN_REVIEW` 和 `MODEL_UPDATE` 保留后续审批策略，但本版编排器不会在这两个阶段暂停。

### 3.5 边界

- 知识检索依赖 WeKnora 配置；未配置时返回明确的服务不可用信息。
- 真实 HPC/AiiDA 执行仍在后续版本接入。
- 实验方案转发台可按版本化配置生成并保存实验清单；SpecLabOS 真实设备执行和结果回填待接入。
- 报告生成依赖可用的模型 provider 配置。

## 4. ComputeEngine 计算智能

### 4.1 解决的问题

ComputeEngine 把计算任务从“手工运行脚本并整理文件”升级为“统一提交、统一状态、统一 artifact 和统一审计”。用户可以在网页上选择 workflow、填写参数、跟踪状态并下载产物。

### 4.2 任务生命周期

计算任务支持以下状态：

| 状态 | 含义 |
| --- | --- |
| `queued` | 已创建，等待 worker 领取 |
| `running` | worker 正在执行 |
| `completed` | 执行完成，结果与 artifact 已登记 |
| `failed` | 执行失败，保留错误信息 |
| `cancelled` | 用户取消或系统取消 |

Worker 原子领取任务、写入 heartbeat，并回收 stale run。Adapter 负责输入校验、执行、artifact 收集和结果解析。

### 4.3 三条主要 Workflow

| Workflow | 输入 | 主要动作 | 典型产出 | 适用场景 |
| --- | --- | --- | --- | --- |
| `LOCAL_STRUCTURE` | SMILES | RDKit/OpenBabel 生成三维结构 | `structure.xyz`、`structure.sdf`、`structure.json`、日志 | 快速获得初始三维结构 |
| `LOCAL_XTB` | SMILES 和方法参数 | 结构生成、CREST 构象搜索、xTB 计算 | 构象文件、能量、优化结构、日志 | 粗优化和构象筛选 |
| `ORCA_COMPUTE_ENGINE_LASER` | SMILES 和白名单方法 | 结构生成、CREST、ORCA DFT 计算 | ORCA 输入、能量、结构、日志 | 高精度计算和论文级数据 |

三条路径是递进关系：ORCA 精加工内部包含结构生成和 CREST；xTB/CREST 粗优化内部包含结构生成；本地结构生成是最基础路径。

### 4.4 使用流程

1. 进入 `/computations/submit`。
2. 选择 workflow，例如本地结构生成、xTB/CREST 粗优化或 ORCA 精加工。
3. 填写 SMILES 和方法参数；系统只允许白名单方法。
4. 提交任务后进入 `/computations/runs` 查看状态。
5. 打开任务详情，查看步骤、结果 JSON、错误和 artifact。
6. 下载或预览 XYZ、SDF、JSON 和日志文件。

### 4.5 边界

- 本地结构生成依赖 RDKit 或 OpenBabel。
- xTB/CREST 依赖本地可执行文件。
- ORCA 依赖本地 ORCA 可执行文件和许可证。
- ORCA 方法由后端白名单控制，用户不能提交任意 ORCA 输入文件或关键字。
- 真实 HPC/AiiDA executor 仍在后续版本接入。

## 5. Alchemist 实验设计与优化

### 5.1 解决的问题

Alchemist 用于在真实实验前设计实验、训练代理模型、推荐下一批实验并诊断模型可信度。它适合多变量、多目标和高成本实验场景。

### 5.2 六步工作流

1. **变量定义**
   - 支持连续、整数、分类和离散变量。
   - 为每个变量设置范围、单位和约束。

2. **实验设计**
   - 支持 LHS、Sobol、因子设计、CCD、Box-Behnken、Plackett-Burman。
   - 支持最优设计中的主效应、交互和二次项。
   - 可配置 D-optimal、A-optimal、I-optimal 和交换算法。

3. **实验数据**
   - 支持设计表填写、手动新增和 CSV 导入。
   - 只有带 Output 的记录才参与建模。

4. **GP 建模**
   - 支持 Matern 5/2、Matern 3/2、RBF、IBNN 核函数。
   - 支持 scikit-learn 和 BoTorch 后端。
   - 输出 R²、RMSE、MAE 等指标。

5. **采集优化**
   - 支持 EI、PI、UCB、qEI、qUCB、qNIPV。
   - 支持最大化、最小化、探索权重和批量推荐。

6. **可视化诊断**
   - 支持 Parity、CV 指标曲线、Q-Q、校准曲线、等值线图和超参数展示。

### 5.3 Session 管理

- 新建 Session 作为优化项目。
- 通过选择器切换不同 Session。
- 支持导入和导出 JSON。
- Session 保存变量、实验数据、模型结果和推荐记录。

### 5.4 边界

- GP 建模至少需要 5 条带 Output 的实验数据。
- LLM 辅助建议依赖模型服务配置。
- 平台负责设计、建模、推荐和诊断；真实实验执行仍需外部系统。

## 6. 垂类预测模型

### 6.1 解决的问题

垂类预测模块把领域算法从“个人脚本”治理为可上传、可测试、可版本化、可调用和可追溯的平台资产。

### 6.2 两种接入方式

| 类型 | 接入方式 | 适用场景 |
| --- | --- | --- |
| 算法上传 | 上传 Python 脚本或标准 ZIP | 本地 Python 模型、文件型算法、需要平台托管运行的算法 |
| 远程接口 | 配置 HTTP、FastAPI 或 MCP endpoint | 已部署服务、内部模型 API、外部模型服务 |

### 6.3 算法上传流程

1. 进入 `/vertical-prediction`，选择“上传部署”。
2. 选择网页打包助手、标准 ZIP 上传或本地 CLI 打包。
3. 填写算法 ID、名称、版本、开发者、机构、来源和引用。
4. 声明输入输出 schema；文件型算法可声明 `input_assets`、`output_assets` 和 `resource_assets`。
5. 上传 Python 入口、依赖和样例输入。
6. 提交后系统依次执行校验、构建、部署和激活。
7. 在“算法管理”中查看版本、状态、SHA256 和追溯信息。
8. 在“测试调用”中按 schema 填写参数并运行。

Python 入口契约：

```python
def load(context: dict) -> object | None:
    return None

def predict(inputs: dict, context: dict, model: object | None = None) -> dict:
    return {"prediction": {}}
```

### 6.4 管理与调用

- **版本治理**：部署、激活、回滚、冻结、下线。
- **测试调用**：按版本调用，查看输出、artifact 和耗时。
- **运行记录**：按算法、版本、状态和日期查询 AlgorithmRun。
- **来源标注**：展示开发者、机构、导师课题组、来源 URL、引用和授权 Logo。
- **handoff**：把算法结果转交给 ResearchEngine、计算任务或实验流程。

### 6.5 远程接口边界

- HTTP/FastAPI 按同步调用执行，不自动重试，不跟随重定向。
- 生产环境要求 HTTPS，并默认阻断 loopback、私网、link-local 和保留地址。
- 认证信息只能通过环境变量或密钥引用配置，平台不保存或返回明文凭据。
- MCP 当前仅支持配置和展示；测试、激活和调用返回 `REMOTE_PROTOCOL_NOT_SUPPORTED`。

## 7. Knowledge Base 知识库

### 7.1 解决的问题

Knowledge Base 把文献和知识库问答从“只给一段总结”升级为“可核查的证据链”。用户可以看到引用来源、证据卡片和可选图谱关系。

### 7.2 使用流程

1. 进入 `/knowledge`。
2. 选择知识库。
3. 输入材料、合成路线、性能或表征问题。
4. 查看回答和证据清单。
5. 如启用 Neo4j，查看实体关系和检索子图。
6. 将证据用于 ProblemSpec、候选审核或报告说明。

### 7.3 能力与边界

- 支持 WeKnora 知识库问答、证据清单和无总结检索。
- 支持可选 Neo4j 图谱增强。
- 平台过滤 API key、object key、embedding 等敏感元数据。
- 语料来源和引用以 WeKnora 响应与上游知识库为准。

## 8. Data Catalog 数据管理

### 8.1 解决的问题

Data Catalog 用于浏览材料数据资产、理解数据集结构、下钻记录详情，并把数据来源和调用边界显式化。

### 8.2 主要能力

| 能力 | 入口 | 用途 |
| --- | --- | --- |
| 数据目录 | `/database/data-catalog` | 浏览数据集、分类、筛选和关系索引 |
| 数据详情 | 数据集抽屉 | 查看字段、记录量、导入状态和来源 |
| 记录下钻 | 记录抽屉 | 查看单条材料记录和关联资产 |
| 数据分析 | `/database/data-analysis` | 查看数据分布和分析视图 |
| 数据 API | `/database/data-api` | 查看调用方式和接口说明 |

### 8.3 边界

- 生产环境材料资产来自 `poly_data` MongoDB 和 MinIO。
- 业务运行数据与材料资产库分离。
- 平台不声明拥有外部数据集成果；来源以数据集矩阵和上游授权为准。

## 9. 受控 LUI 与统一回放

### 9.1 基本操作

Slash Command 是 `/dialogue` 的用户控制面，不进入模型请求历史。命令结果、权限决策、模型执行、算法工具、上下文压缩、导出与反馈都会写入同一条会话事件流。

触发方式：

1. 在输入框行首输入 `/`，打开命令面板。
2. 点击输入框工具栏的 `/` 按钮；输入框为空时自动填入 `/`。
3. 输入前缀或关键词，面板按前缀和模糊匹配过滤。
4. 使用鼠标点击、`↑`、`↓`、`Enter` 选择命令。
5. 使用 `Esc` 关闭面板。

### 9.2 内置命令参考

| 命令 | 调用方式 | 参数说明 | 结果与边界 |
| --- | --- | --- | --- |
| Plan Mode | `/plan` | 无参数 | 启用 Plan Mode |
| Plan Mode | `/plan off` | `off` | 退出 Plan Mode |
| Plan Mode | `/plan <任务说明>` | 任意计划任务文本 | 启用 Plan Mode 并创建计划任务 |
| Session Goal | `/goal` | 无参数 | 查看当前长期目标 |
| Session Goal | `/goal clear` | `clear` | 清除当前长期目标 |
| Session Goal | `/goal <目标描述>` | 目标文本，最多 2000 字符 | 设置当前会话长期目标 |
| Permission Mode | `/permission` | 无参数 | 显示当前权限和可选模式 |
| Permission Mode | `/permission read-only` | `read-only` 或 `read_only` | 切换为只读 |
| Permission Mode | `/permission workspace-write` | `workspace-write` 或 `workspace_write` | 切换为工作区写入 |
| Permission Mode | `/permission full-access` | `full-access` 或 `full_access` | 切换为完全访问 |
| Model Selection | `/model` | 无参数 | 显示当前模型和可选模型 |
| Model Selection | `/model <provider_id>::<model_id>` | 必须包含一个 `::`，两侧非空 | 切换会话模型；不重置 Goal、Todo、Trace 和权限 |
| Session Status | `/status` | 无参数 | 汇总模型、模式、目标、权限、活动 run、活动工具调用和 Trace 统计 |
| Reset Session Control | `/reset` | 无参数 | 弹出确认表单 |
| Reset Session Control | `/reset confirm` | `confirm`、`confirmed` 或 `yes` | 重置 Plan、权限、Goal 和 Todo |
| Reset Session Control | `/reset cancel` | `cancel` 或 `no` | 取消重置 |
| Clear To New Session | `/clear` | 不接受额外参数 | 创建新会话；旧会话消息、命令、Trace 与工具结果保留 |
| Context Compaction | `/compact` | 不接受额外参数 | 压缩已完成历史，保留目标、任务、权限、结论和活跃工具结果 |
| Session Export | `/export` | 无参数 | 显示 JSON、Markdown、ZIP 选项 |
| Session Export | `/export json` | `json` | 导出单一结构化 JSON 对象 |
| Session Export | `/export markdown` | `markdown` | 导出人类可读 Markdown |
| Session Export | `/export zip` | `zip` | 导出包含 Trace 与 artifact 的归档 |
| Session Feedback | `/feedback` | 不接受命令参数 | 打开反馈表单；正文必须通过表单提交 |

`/reset` 只把控制状态恢复为默认值：Plan Mode 关闭、权限恢复 `workspace_write`、Goal 清空、Todo 清空。消息、模型 run、工具调用、导出记录和事件均保留。

`/clear` 会把当前模型、模式、知识库选择、网页搜索开关和已选工具带入新会话，但不删除旧会话。

### 9.3 动态算法命令

当前用户可用的已部署算法会自动派生为动态命令：

```text
/<algorithm-slug> [<JSON 参数>|<任务说明>]
```

使用方式：

1. 在命令面板选择算法命令。
2. 按算法 schema 填写 JSON 参数或任务说明。
3. 如算法要求确认，先完成参数确认。
4. 系统创建 AlgorithmRun，并回链结果和 artifact。
5. 结果附近展示算法开发者、方法来源和授权机构 Logo。

当 `/permission read-only` 生效或 Plan Mode 开启时，工具命令会显示不可用原因；退出 Plan Mode、恢复可执行权限或执行 `/reset` 后自动恢复。

### 9.4 统一回放

“会话统一回放”合并以下事件：

- Slash Command 生命周期
- 模型 run 生命周期
- 算法工具调用与结果
- 权限决策与 Plan Mode 阻断
- Goal、Todo、权限模式变化
- 上下文压缩
- 导出
- 反馈

支持按“全部 / 命令 / 控制 / 模型 / 工具 / 导出 / 反馈”过滤，并使用连续 `after_seq` 游标做断线后的增量恢复。界面不展示完整 prompt、Chain of Thought、API key 或未脱敏文件内容。

### 9.5 安全边界

- Plan Mode 不是操作系统沙箱；工具确认阶段由后端阻断执行。
- 权限模式只叠加 LUI 控制面约束，不替代平台 RBAC 与工具策略。
- 反馈正文只保存在权威反馈记录，命令事件仅保存摘要信息。
- 导出下载走 owner 校验；缺失 artifact 只记录 manifest 错误。

## 10. 助手与报告

### 10.1 助手能力

- 基于项目实时事实返回入口、算法、计算和审批引导。
- 支持按用户隔离的历史会话。
- 支持已部署垂类算法工具选择、参数确认和结果回链。
- 支持模型路由、上下文 manifest、统一事件流和服务端续答。
- 支持调用质量观测和会话统一回放。

### 10.2 报告能力

报告链路支持：

- 模型服务：OpenAI、Ollama、Edison、Codex、自定义 HTTP provider。
- 渲染格式：HTML、LaTeX、Markdown、PDF。
- 输入来源：ResearchRun、WorkflowRun、AlgorithmRun、StageRun、artifact 和审计事件。

### 10.3 边界

- 真实模型服务依赖环境配置。
- 报告内容用于研发过程沉淀，不自动替代人工科研结论。
- mock、fixture 和 demo 数据不能作为真实实验结论。

## 11. 任务中心与工具服务

### 11.1 任务中心

`/tasks/center` 聚合：

- 计算任务
- 垂类模型运行
- ResearchEngine 任务
- WorkflowRun 和 AlgorithmRun
- 未接入任务类型的状态说明

用户可以按类型筛选并跳转详情页。

### 11.2 工具服务

`/tools` 展示：

- 核心存储：MongoDB、SQLite、artifact 存储
- 运行组件：计算 worker、Docker
- 知识服务：WeKnora、Knowledge Graph
- 计算工具链：RDKit、OpenBabel、xTB、CREST、ORCA
- 优化与实验：Alchemist、SpecLabOS
- LLM 模型服务和配置状态

## 12. 安全与治理

- 支持 AI4MS 门户 SSO、HMAC token 和角色权限。
- 业务运行数据和材料资产数据分离。
- 集成配置只保存 endpoint、config summary 和 secret refs。
- API 不返回 API key、object key、storage URI、embedding 或本地敏感路径。
- 上传算法运行在受限子进程中，并受并发、输出大小和超时限制。
- 外部方法、算法和数据来源使用统一 attribution 结构，不使用未授权 Logo。

## 13. 能力边界与来源

Poly Agent 负责任务编排、权限治理、运行记录、artifact 管理、审计与报告交付；不声明拥有外部算法、数据集或模型成果。

外部来源包括：

- ResearchEngine 编排参考 ChemOS 2.0。
- Alchemist 方法来源为 NatLabRockies / NREL / NLR ALchemist。
- ComputeEngine 计算能力来自 RDKit、OpenBabel、xTB、CREST 和 ORCA。
- Knowledge Base 接入 Tencent WeKnora，图谱增强可选 Neo4j。
- 垂类模型来源、引用、开发者与机构信息来自算法包契约。

完整引用、机构与实现边界见项目来源矩阵。
