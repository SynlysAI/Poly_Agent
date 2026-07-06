# ResearchEngine 高分子材料 AI 研发平台技术方案

版本：v0.3  
日期：2026-07-06  
输入材料：`AI4S算法工具链与平台技术方案.pptx [Repaired].pptx`、ResearchEngine 架构图、材料研发 AI 流程图、`refer/AutoResearchClaw-main`、现有 Poly_Agent campaign / computation / optimization / Vue 工作台模块

实施计划拆分：见 `doc/research-engine-plan-00-roadmap.md`。后续按 `plan-01` 到 `plan-06` 逐个实现、验收和更新进度，不建议一次性完成整个设计。

---

## 1. 方案摘要

本方案面向高分子材料研发场景，目标是构建一个集材料研发流程管理、人工算法工具调用、AutoResearch 自动编排、实验数据回填与模型迭代于一体的 ResearchEngine 平台。平台不以单个材料体系、单个算法脚本或单条自动化流水线为边界，而是通过统一的 ProblemSpec、算法能力清单、任务状态、数据资源、审计追溯和 ask/tell 闭环，把文献检索、结构表示、跨尺度计算、性质预测、BO/MOBO 推荐、实验执行、结果回填和模型更新沉淀为可复用的平台能力。

ResearchEngine 的核心不是用 AutoResearch 替代人工专家，也不是只做一组手动工具按钮，而是形成“双通道研发框架”：

1. 人工算法触发通道：材料科学家或算法工程师在工作台中主动选择文献检索、结构表示、计算、性质预测、BO/MOBO、实验任务等工具，快速探索、验证、调试和补充判断。
2. AutoResearch 自动编排通道：系统基于 ProblemSpec、材料 profile、算法能力清单和历史数据，自动组织研究阶段、选择算法、生成候选、触发实验、回填结果并推动模型更新。

两条通道并行运行、共享底座、互相消费产物。人工调用可以独立产生 AlgorithmRun 和 artifacts，AutoResearch 可以把这些人工产物作为上下文、数据快照或候选来源；AutoResearch 阶段中也可以插入人工审批、人工补充数据和人工候选改写。人工始终可以接管、暂停、重跑或覆盖 AutoResearch 的某个阶段。

第一阶段建议仍以氟基高分子材料作为样板场景，但底层 schema、算法 adapter、stage contract 和数据流设计必须支持碳基、硅基、含氟-碳共聚体系及后续更多材料体系扩展。第一阶段不追求真实 LabOS 全自动控制，优先跑通 mock LabOS 或人工回填下的可追溯闭环。

---

## 2. 建设背景与问题定义

当前高分子材料 AI 研发通常存在四类断点。

第一类是材料流程断点。文献检索、结构构建、跨尺度计算、性质预测、实验推荐和湿实验结果回填往往由不同团队、不同工具或不同 notebook 完成，流程之间缺少统一任务对象和数据传递标准。

第二类是算法调用断点。已有算法能力可能覆盖文献知识检索、单体计算、性质预测、BO/MOBO、主动学习等方向，但算法输入、输出、调用方式、版本、适用场景和验证指标不统一，难以被平台稳定编排和复用。

第三类是实验闭环断点。算法推荐结果、人工审核、实验执行、失败原因、原始数据、测试条件和模型更新过程缺少统一审计链路，导致结果难以回放，算法优化难以量化，跨项目复用成本高。

第四类是自动化与人工协作断点。单纯人工工具链灵活但不连续，单纯 AutoResearch 自动流水线连续但容易忽略专家判断、实验约束和中间产物复用。平台需要让人工触发和自动编排在同一套对象、同一套状态和同一条审计链上协同，而不是二选一。

因此，平台建设的关键不是简单叠加更多算法，也不是直接搬入一个通用 AutoResearch 项目，而是建立“材料研发流程 × 算法能力 × 双通道编排”的统一组织方式，使不同材料体系能够沿相同研发步骤接入，使不同算法能够作为独立能力维度持续优化，使人工专家和自动编排都能产出可追溯、可复用、可回放的数据资产。

---

## 3. 总体目标

平台总体目标可以概括为六点。

1. 建立统一的材料研发任务表达  
   将材料体系、变量、目标性质、约束条件、测试方法、历史数据、执行模式和实验策略统一表达为平台可读的 ProblemSpec。

2. 建立人工算法触发通道  
   允许用户在工作台中主动调用文献、结构、计算、预测、优化和实验相关算法，形成独立 AlgorithmRun、artifact 和审计记录。

3. 建立 AutoResearch 自动编排通道  
   基于 ProblemSpec 和 material profile 自动组织研究阶段，执行从问题定义、候选推荐、实验执行到结果回填和模型更新的闭环。

4. 建立统一的算法能力清单  
   对文献检索、结构解析、跨尺度计算、性质预测、小模型、BO/MOBO、主动学习、湿实验推荐等算法进行分类、登记、封装和评估。

5. 建立可插拔的算法调用机制  
   平台不绑定单一算法库，而是通过 Algorithm Adapter 接入不同算法。算法可以独立迭代，平台保持统一输入输出、任务状态、artifact 和审计记录。

6. 建立可追溯的材料研发闭环  
   打通“用户定义问题 -> 人工或自动算法调用 -> 候选推荐 -> 人工审核 -> 实验执行 -> 结果回填 -> 模型更新 -> 下一轮推荐”的 ask/tell 闭环。

---

## 4. 需求矩阵设计

![高分子材料 AI 工具链平台需求矩阵](<ChatGPT Image 2026年6月22日 15_59_59.png>)

图 1 将平台需求组织为一个二维矩阵：横轴是材料研发中的 AI 应用流程，纵轴是不同材料体系或应用场景。该矩阵是后续需求调研、算法盘点、接口定义、人工工具入口设计和 AutoResearch 阶段编排的共同语言。

### 4.1 横向：材料研发 AI 应用流程

横向步骤建议定义为六类。

| 步骤 | 平台含义 | 典型输入 | 典型输出 |
| --- | --- | --- | --- |
| Step1 文献检索 | 面向材料体系和目标性质检索论文、专利、数据库和历史报告 | 关键词、结构片段、性质目标、应用场景 | 相关文献、专利、数据集、候选结构、知识摘要 |
| Step2 结构表示 | 将单体、聚合物、共聚体系转为算法可处理表示 | SMILES、单体结构、配比、聚合方式 | 分子图、特征向量、结构标签、可计算描述符 |
| Step3 跨尺度计算 | 通过单体、链段、聚集态或多尺度耦合计算预测物理性质 | SMILES、单体结构、组成、工艺条件 | Tg、介电常数、热稳定性、力学性质等 |
| Step4 性质预测 | 基于小模型、代理模型或专用模型快速预测目标性质 | 结构表示、计算特征、历史实验数据 | 性质预测值、不确定性、关键影响因子 |
| Step5 BO/MOBO 推荐 | 在约束条件下推荐下一轮候选材料或实验参数 | 预测结果、历史实验、目标函数、约束条件 | Top-K 候选、Pareto 解、推荐理由、风险提示 |
| Step6 湿实验迭代 | 执行实验、采集结果、回填数据并触发模型更新 | 推荐候选、实验参数、测试条件 | 实验结果、失败原因、原始文件、模型更新数据 |

横向流程强调的是材料研发任务的连续性。平台应避免每一步都成为孤立工具，而是通过统一数据对象把每一步的输入输出串联起来。

### 4.2 纵向：材料体系与应用场景

纵向维度用于承载不同材料体系，例如氟基高分子、碳基高分子、硅基高分子、含氟-碳共聚体系及未来可扩展体系。

每一行代表一个材料体系在完整 AI 工具链中的应用情况。对于每个材料体系，需要明确：

- 当前已有算法能力；
- 可直接复用的平台能力；
- 需要重新训练或适配的模型；
- 需要湿实验验证的关键性质；
- 数据是否足够支撑模型训练或主动学习；
- 该材料体系与其他体系共享哪些输入输出规范；
- 适合人工触发的工具入口；
- 适合 AutoResearch 自动编排的阶段和 gate。

### 4.3 单元格表达规范

矩阵中的每个单元格建议使用统一模板表达，便于调研、评审和后续开发。

| 字段 | 说明 |
| --- | --- |
| Algorithm | 算法名称或算法类别，例如文献 RAG、GNN、跨尺度耦合计算、BO/MOBO |
| Input | 算法输入，例如 SMILES、单体结构、配方、工艺参数、历史实验数据 |
| Output | 算法输出，例如目标性质、候选结构、推荐配方、实验参数、不确定性 |
| Interface | 调用方式，例如 REST API、SDK、批处理任务、Algorithm Adapter |
| Trigger | 触发方式，例如 human、autoresearch、system |
| Status | 能力状态，例如已有、待封装、待开发、待验证 |
| Evidence | 证据来源，例如论文、历史数据、实验记录、模型报告 |

示例：

| 字段 | 示例 |
| --- | --- |
| Algorithm | 跨尺度耦合计算 |
| Input | SMILES + 单体结构 + 聚合物组成 |
| Output | Tg、介电常数、热稳定性预测 |
| Interface | Adapter API |
| Trigger | human / autoresearch |
| Status | 已有算法，待平台封装 |
| Evidence | 单体计算脚本、历史计算结果、模型验证报告 |

---

## 5. 双通道研发架构

![ResearchEngine 分层架构与算法编排](<ChatGPT Image 2026年6月22日 16_05_46.png>)

ResearchEngine 采用人工算法触发与 AutoResearch 自动编排并行的双通道架构。两条通道共享 Project、ProblemSpec、AlgorithmRegistry、AlgorithmRun、Candidate、ExperimentRun、Observation、ModelUpdate 和 AuditEvent。

### 5.1 人工算法触发通道

人工通道面向材料科学家、算法工程师和实验人员，重点解决专家探索、临时分析、算法调试和人工确认问题。

典型场景包括：

- 用户直接检索某个材料体系的文献和专利；
- 用户上传或输入结构，调用结构表示或描述符生成算法；
- 用户选择某个候选材料，触发 xTB、ORCA、跨尺度模拟或本地预测模型；
- 用户手动执行 BO/MOBO 推荐，查看 Top-K 候选和推荐理由；
- 用户人工否决、修改或补充候选；
- 用户上传实验结果、原始文件和失败原因。

人工通道的每次调用都应产生 AlgorithmRun 或 ExperimentRun，并登记输入快照、输出 artifact、算法版本、触发人、触发原因和审计事件。

### 5.2 AutoResearch 自动编排通道

AutoResearch 通道面向连续闭环和批量迭代，重点解决流程串联、阶段调度、自动推荐和跨轮次优化问题。

典型流程包括：

1. 读取 ProblemSpec 和 material profile；
2. 确定当前 ResearchRun 的阶段序列和 gate 策略；
3. 从 AlgorithmRegistry 中选择合适算法；
4. 消费历史 AlgorithmRun、Observation 和数据快照；
5. 自动生成候选、预测性质或推荐实验；
6. 在关键阶段暂停等待人工审核；
7. 将批准的候选提交到 computation、mock LabOS 或人工实验任务；
8. 接收结果回填并生成 Observation；
9. 触发模型更新或下一轮推荐；
10. 归档本轮经验、失败原因和可复用 lesson。

AutoResearch 通道不应绕开人工专家。对于候选推荐、实验提交、异常数据、模型更新采纳等高影响节点，默认应支持 HITL gate。

### 5.3 双通道交汇点

两条通道的交汇点必须进入同一套数据和审计体系。

| 交汇点 | 人工通道行为 | AutoResearch 通道行为 | 共享对象 |
| --- | --- | --- | --- |
| ProblemSpec 定义 | 用户手动编辑任务规格 | 自动解析或补全任务规格 | ProblemSpec |
| 算法调用 | 用户主动触发工具 | 阶段编排自动触发 adapter | AlgorithmRun |
| 候选生成 | 用户导入或手动筛选候选 | ask 阶段批量推荐候选 | Candidate |
| 推荐审核 | 用户批准、否决、修改 | gate 阶段等待人工决策 | AuditEvent |
| 实验执行 | 用户提交计算或人工实验 | 自动提交 computation/mock LabOS | ExperimentRun |
| 结果回填 | 用户上传结果和原始文件 | tell 阶段自动解析结果 | Observation |
| 模型更新 | 用户选择是否采纳数据 | 自动更新数据集和模型状态 | ModelUpdate |
| 经验归档 | 用户记录备注 | 自动抽取 lesson 和失败原因 | AuditEvent / Archive |

---

## 6. 算法能力清单

算法能力清单是平台建设的核心资产之一。它不是简单的算法列表，而是算法能否被人工触发、能否被 AutoResearch 编排、能否被评估、复用和持续优化的登记表。

### 6.1 能力分类

| 算法类别 | 典型能力 | 适用阶段 | 说明 |
| --- | --- | --- | --- |
| 文献与知识算法 | 文献检索、专利检索、知识图谱、RAG 摘要 | Step1 | 支撑材料知识沉淀和候选启发 |
| 结构表示算法 | SMILES 解析、分子图构建、描述符生成、GNN 表征 | Step2 | 将材料结构转为模型输入 |
| 跨尺度计算算法 | 单体计算、链段模拟、多尺度耦合、物理性质计算 | Step3 | 面向碳、硅、氟等单体和聚合物体系 |
| 性质预测模型 | 碳基模型、氟基模型、小模型、代理模型 | Step4 | 快速预测目标性质并提供不确定性 |
| 优化推荐算法 | DoE、BO、MOBO、主动学习、约束优化 | Step5 | 推荐下一轮候选材料或实验方案 |
| 实验闭环算法 | 实验设计、结果解析、异常检测、模型更新 | Step6 | 支撑湿实验迭代和数据回流 |

### 6.2 算法登记字段

每个算法进入平台前建议至少登记以下字段。

| 字段 | 内容 |
| --- | --- |
| algorithm_id | 算法唯一标识 |
| name | 算法名称 |
| type | 算法类别，如 predictor、optimizer、retriever、simulator |
| material_scope | 适用材料体系，如氟基、碳基、硅基、通用 |
| task_scope | 适用任务，如性质预测、候选推荐、跨尺度计算 |
| input_schema | 输入字段、数据类型、单位、约束 |
| output_schema | 输出字段、数据类型、单位、置信度或不确定性 |
| call_method | REST、SDK、CLI、批处理或队列任务 |
| trigger_modes | 支持 human、autoresearch、system 中哪些触发方式 |
| runtime_dependency | 运行依赖，如 Python 环境、GPU、外部数据库 |
| version | 算法版本 |
| validation_metric | 验证指标，如 MAE、R2、Top-K 命中率、实验提升率 |
| owner | 算法负责人 |
| status | 已接入、待封装、开发中、冻结、下线 |

### 6.3 算法作为独立优化维度

平台应允许算法团队沿算法维度独立推进优化，而不影响材料流程层的稳定性。例如：

- 跨尺度计算算法可以持续改进碳、硅、氟单体的物理性质预测能力；
- 性质预测模型可以针对氟基、碳基材料分别训练，也可以逐步形成通用预训练模型；
- BO/MOBO 推荐算法可以在同一 ProblemSpec 下替换不同策略，并通过历史回放评估性能；
- 文献检索与知识图谱算法可以独立提升召回、去重、结构抽取和证据溯源能力。

这种设计使平台不会被某个算法库、某个材料体系或某条 AutoResearch 流水线锁死。

---

## 7. AutoResearchClaw 融合设计

`refer/AutoResearchClaw-main` 的价值不在于直接搬入其论文生成流水线，而在于迁移其研究自动化框架思想。AutoResearchClaw 原项目围绕 23 阶段自动生成论文，包括文献、假设、实验、分析、写作、审稿、导出等环节。ResearchEngine 面向材料研发平台，应抽取其框架能力，并改造成材料研发的阶段编排、审批、回放和经验沉淀机制。

### 7.1 可迁移能力

| AutoResearchClaw 能力 | 迁移到 ResearchEngine 的形式 |
| --- | --- |
| Stage 状态机 | 改造为材料研发 ResearchStage 状态机 |
| StageContract 输入输出契约 | 改造为每个材料研发阶段的 required_inputs、expected_outputs、DoD 和 error_code |
| HITL gate 审批策略 | 改造为 ProblemSpec、候选推荐、实验提交、异常结果和模型更新采纳的人工 gate |
| checkpoint / resume | 改造为 ResearchRun 可暂停、可恢复、可从阶段继续执行 |
| artifact bundle | 改造为 AlgorithmRun、ExperimentRun、ResearchStageRun 的统一 artifact 目录和索引 |
| domain profile | 改造为 material profile，例如 fluoropolymer、carbon_polymer、silicon_polymer、fluoro_carbon_copolymer |
| memory / evolution | 改造为材料研发经验沉淀，记录失败原因、有效实验条件、模型表现和推荐策略收益 |
| branch exploration | 后续可改造为多候选路线并行探索、不同推荐策略对比和 Pareto 分支比较 |

### 7.2 暂不迁移能力

以下能力不进入第一阶段 ResearchEngine 文档和实现范围：

- 论文写作流水线；
- LaTeX、Overleaf、conference export；
- citation verify；
- voice、calendar、showcase；
- AutoResearchClaw 原 CLI；
- AutoResearchClaw 整仓代码 vendor 进入 Poly_Agent。

### 7.3 材料版 AutoResearch 阶段

AutoResearch 通道建议采用材料研发专用阶段，而不是复用 AutoResearchClaw 的 23 个论文阶段。

| 阶段 | 说明 | 关键输出 |
| --- | --- | --- |
| PROBLEM_SPEC | 解析、校验和冻结 ProblemSpec | problem_spec_snapshot |
| KNOWLEDGE_RETRIEVAL | 检索文献、专利、历史实验和知识库 | knowledge_cards / candidate_sources |
| STRUCTURE_FEATURE | 生成结构表示、描述符和特征 | structure_features |
| COMPUTE_PREDICT | 运行计算、性质预测或代理模型 | prediction_results |
| RECOMMENDATION_ASK | 基于目标、约束和历史数据生成 Top-K 候选 | suggestions |
| HUMAN_REVIEW | 人工审核、否决、修改或批准候选 | review_decisions |
| EXPERIMENT_EXECUTION | 提交 computation、mock LabOS 或人工实验任务 | experiment_runs |
| RESULT_TELL | 回填实验或计算结果，生成 Observation | observations |
| MODEL_UPDATE | 更新数据集、代理模型或推荐策略状态 | model_update_record |
| ARCHIVE_LEARNING | 归档本轮经验、失败原因和可回放 bundle | archive / lessons |

---

## 8. 产品架构

产品架构采用三层设计：用户工作台层、编排服务层、算法与数据资源层。与 v0.1 不同，v0.2 明确把人工工具入口和 AutoResearch run 入口作为同级能力。

### 8.1 用户工作台层

用户工作台面向材料科学家、算法工程师和实验人员，提供统一入口。

核心功能包括：

- 材料项目管理：管理材料体系、研发目标、成员和任务状态；
- 人工算法入口：主动触发文献检索、结构表示、性质预测、计算任务、BO/MOBO 和实验工具；
- AutoResearch run 入口：创建、启动、暂停、恢复、查看自动研究流程；
- 材料性质预测：选择模型并预测目标性质；
- 算法能力清单：查看可用算法、适用场景、输入输出、触发方式和状态；
- 实验任务看板：查看推荐候选、审核状态、执行状态和失败原因；
- Stage/Gate 看板：查看 AutoResearch 当前阶段、审批点、回滚目标和 artifact；
- 结果回填：上传实验结果、测试条件、原始文件和备注。

### 8.2 编排服务层

编排服务层承载核心业务逻辑。

| 服务 | 职责 |
| --- | --- |
| ProblemSpec 服务 | 管理问题定义、变量、目标、约束、测量条件和执行模式 |
| 人工调用服务 | 接收用户工具调用，创建 AlgorithmRun，登记 artifacts 和审计事件 |
| AutoResearch Orchestrator | 管理 ResearchRun、阶段状态、自动算法选择、checkpoint 和恢复 |
| Stage/Gate 服务 | 管理 StageContract、人工审批、回滚、暂停、重跑和接管 |
| 算法编排服务 | 选择算法、调用 adapter、管理算法运行状态 |
| 任务与批次服务 | 管理候选批次、实验批次、任务状态和人工审核 |
| 数据治理服务 | 数据接入、单位标准化、质量控制、缺失值检查 |
| 审计与追溯服务 | 记录操作、版本、失败原因、原始数据和产物 |
| LabOS 适配服务 | 对接设备、实验调度、结果采集和回调；第一阶段可先使用 mock 或人工回填 |

平台服务层应通过 API、SDK 或 WebSocket 与前端和算法 worker 通信，保证不同模块之间边界清晰。

### 8.3 算法与数据资源层

算法资源包括：

- 文献 RAG；
- 结构解析和描述符生成；
- 跨尺度计算；
- 碳基模型；
- 氟基模型；
- 小模型和代理模型；
- BO/MOBO；
- 主动学习；
- 结果解析和异常检测。

数据资源包括：

- 文献库；
- 材料结构库；
- 历史实验数据；
- 性质测试数据；
- 原始文件；
- 模型产物；
- ResearchRun artifact bundle；
- 经验沉淀和 lesson 库。

算法和数据资源应相互解耦。编排服务层负责统一调度和审计，算法本身可以由不同团队独立维护。

### 8.4 UI 信息架构与入口设计

ResearchEngine 的 UI 不建议在第一阶段重做一套新壳。现有 Poly_Agent 已经形成“左侧一级导航 + 顶部面包屑 + 页面 panel + 表格 / drawer / dialog / tag”的 Vue 3 + Element Plus 工作台逻辑，并且已经有任务提交、任务中心、计算智能、湿实验优化、工具服务和数据库管理等入口。ResearchEngine UI 应保留这套框架，只在已有导航和页面内部增加入口、状态面板和可操作区域。

第一阶段推荐采用“轻导航、重页面内组织”的方式：

| 现有入口 | ResearchEngine 设计 | 理由 |
| --- | --- | --- |
| 工作台 `/dashboard` | 增加 ResearchEngine 概览卡、当前 ResearchRun、待审批 gate、最近 AlgorithmRun | 用户进入系统后先看到是否有自动流程阻塞或待处理 |
| 任务提交 `/tasks/submit` | 增加“ResearchEngine 研发任务”模块卡 | 与计算智能、湿实验贝叶斯优化保持同级任务入口 |
| 任务中心 `/tasks/center` | 将 ResearchRun、AlgorithmRun、ExperimentRun 映射为全局任务 | 保持现有全局任务查询习惯 |
| 湿实验优化 `/optimization` | 增加“ResearchEngine / AutoResearch”入口卡 | AutoResearch 的第一版应复用 campaign / observation 闭环底座 |
| Campaign 详情 `/optimization/campaigns/:campaignId` | 增加 AutoResearch run、人工工具、Stage/Gate、artifact/audit 区块 | 让自动编排和人工工具围绕同一个 campaign / ProblemSpec 汇合 |
| 工具服务 `/tools` | 增加 AlgorithmRegistry 和 adapter 健康状态 | 算法能力清单天然属于工具服务和运维状态的一部分 |
| 数据库管理 `/database` | 后续增加 ProblemSpec、ResearchRun、AlgorithmRun 审计管理 | 管理员视角，不作为普通研发用户主入口 |

不建议第一阶段新增过多左侧一级菜单。若必须新增，建议只新增一个“研发引擎”一级菜单，内部承载 ResearchRun 列表和算法能力清单；但更稳妥的 MVP 做法是先把入口挂到“任务提交”“湿实验优化”和“工具服务”，等 ResearchEngine 使用频率稳定后再独立成一级菜单。

### 8.5 页面级交互设计

ResearchEngine UI 应围绕“用户理解当前研究处于哪里、下一步能做什么、自动流程为什么这么做、人工如何接管”展开，而不是只展示后台对象表。

| 页面 / 区块 | 核心用户问题 | UI 组件建议 | 关键操作 |
| --- | --- | --- | --- |
| ResearchEngine 概览 | 当前有哪些研发任务、哪些需要我处理 | `el-statistic`、待办表格、状态 tag、快捷按钮 | 新建 ProblemSpec、进入待审批 gate、查看失败 run |
| ProblemSpec 编辑器 | 我要定义什么材料问题 | 分步表单、变量表格、目标表格、约束表格、YAML/JSON 预览 drawer | 保存草稿、校验、冻结版本、复制为新版本 |
| 人工算法工作台 | 我能手动调用哪些算法 | 左侧算法分类树 + 中间输入表单 + 右侧输出和 artifact | 选择算法、填入输入、运行、保存为 AlgorithmRun、复用输出 |
| AutoResearch Run 面板 | 自动研究跑到哪一步 | `el-steps` 或阶段时间线、当前 stage panel、checkpoint 信息 | 启动、暂停、恢复、重跑阶段、从 checkpoint 继续 |
| Stage/Gate 看板 | 哪些节点需要人工判断 | 审批队列表格、候选对比表、风险提示、原因输入 dialog | 批准、拒绝、修改候选、回滚、标记失败 |
| 候选推荐区 | 系统推荐了什么，为什么 | `el-table`、目标值列、不确定性列、推荐理由 drawer、Pareto 图 | 选择 Top-K、提交计算/实验、拒绝并记录原因 |
| AlgorithmRun 详情 | 这次算法调用是否可信 | 输入快照、参数、版本、seed、输出 artifact、错误信息 | 下载 artifact、复制输入、重跑、加入 AutoResearch 上下文 |
| Artifact / Audit 区 | 结果能不能回放 | 时间线、文件表、checksum、actor、before/after JSON drawer | 下载、预览、追溯来源、查看审计事件 |
| AlgorithmRegistry | 平台有哪些算法能力 | 按类别和材料体系筛选的表格 / 卡片，schema drawer | 查看输入输出、测试连接、启用/停用、设为默认 |

交互原则：

- 用户不应被迫理解内部对象名才能使用系统。页面文案优先使用“研发任务、候选、推荐、实验、回填、模型更新”，在详情和审计区再展示 `ProblemSpec`、`ResearchRun`、`AlgorithmRun` 等技术对象。
- AutoResearch 的入口必须显式显示“自动编排会做什么”和“哪些阶段需要人工审批”，避免用户误以为系统会直接下发实验。
- 人工工具入口和 AutoResearch 阶段入口必须共享同一套 AlgorithmRegistry 选择器。用户手动运行算法时看到的算法名称、输入字段、输出字段，应与 AutoResearch stage contract 中选择的算法保持一致。
- 每个高影响操作必须要求原因或确认，例如批准实验提交、拒绝候选、重跑阶段、采纳模型更新、标记异常数据。
- 所有长任务都必须显示状态、失败原因、可重试性和关联 artifact；不能只显示“运行中”。

### 8.6 统一算法表达的 UI 方式

算法统一表达不能只停留在后端 registry，也需要在 UI 中有稳定、可理解的呈现方式。建议将每个算法能力表达为“算法能力卡 + schema 驱动调用表单 + 运行记录详情”。

算法能力卡展示：

| UI 字段 | 来源字段 | 展示要求 |
| --- | --- | --- |
| 算法名称 | `name` | 用户可读名称，避免只显示内部 ID |
| 能力类型 | `type` | 用 tag 表示 retriever / predictor / simulator / optimizer |
| 材料适用范围 | `material_scope` | 用多 tag 表示通用、氟基、碳基、硅基等 |
| 适用阶段 | `task_scope` / stage mapping | 显示 Step1-Step6 或 ResearchStage |
| 触发方式 | `trigger_modes` | human、autoresearch、system 三类 tag |
| 状态 | `status` | 已接入、待封装、开发中、冻结、下线 |
| 可信度摘要 | `validation_metric` | 显示 MAE、R2、Top-K 命中率或实验提升率 |
| 运行成本 | `runtime_dependency` | 显示本地、队列、GPU、外部服务等 |

Schema 驱动调用表单：

- 根据 `input_schema` 自动渲染文本框、数值输入、select、文件上传、候选选择器和历史 run 选择器。
- 对单位、边界、枚举值和必填项做前端校验，但以后端校验为准。
- 支持从当前 ProblemSpec、Candidate、Observation、AlgorithmRun artifact 中一键填充输入。
- 运行前展示输入快照，运行后展示输出摘要、artifact 和审计事件。

AutoResearch 阶段选择算法时，应复用同一组算法卡和 schema drawer，只是入口从“立即运行”变成“设为本阶段默认算法 / 本轮使用一次 / 禁用该算法”。这样用户可以理解 AutoResearch 为什么选择某个算法，也能在审批时改用另一个 adapter。

---

## 9. 核心领域模型

平台建议采用以下核心对象。

| 对象 | 含义 | 关键字段 |
| --- | --- | --- |
| Project | 材料项目空间 | 材料体系、成员、权限、目标、状态 |
| ProblemSpec | 问题规格 | 变量、目标、约束、测量条件、执行模式、批次策略 |
| AlgorithmRegistry | 算法能力登记表 | algorithm_id、schema、trigger_modes、版本、状态 |
| AlgorithmRun | 算法运行记录 | 触发来源、算法类型、版本、seed、输入快照、输出产物 |
| ResearchRun | AutoResearch 主运行 | run_id、当前阶段、stage_runs、关联算法和实验 |
| ResearchStageRun | 单个 AutoResearch 阶段运行 | stage_key、状态、输入、输出、gate、checkpoint |
| Candidate | 候选材料或实验方案 | 结构、配方、工艺参数、预测值、不确定性 |
| ExperimentRun | 实验执行记录 | 参数、状态、结果、失败原因、原始文件 |
| Observation | ask/tell 回填结果 | candidate_id、values、uncertainty、source_run_id |
| ModelUpdate | 模型或数据集更新记录 | 数据快照、模型版本、评估指标、采纳状态 |
| AuditEvent | 审计事件 | actor、event_type、before、after、related_ids |

设计原则：

- 人工触发和 AutoResearch 自动触发都必须进入同一套对象；
- 原始 YAML/JSON 完整保存，用于回放；
- 结构化表用于查询、筛选、统计和 UI 展示；
- 人工否决、人工修改、失败实验和异常数据必须进入审计日志；
- 每次 ask 使用的数据快照、算法版本、随机种子和配置必须保存；
- AutoResearch 的阶段产物必须可被人工通道再次消费；
- 人工通道的 AlgorithmRun 也必须可被 AutoResearch 后续阶段引用。

### 9.1 Poly_Agent 现有模型映射

当前 Poly_Agent 已具备一部分闭环底座，后续应在文档和实现中保持兼容。以下表格从对象级和字段级两个粒度说明映射关系。

#### 对象级映射

| ResearchEngine 对象 | Poly_Agent 现有对象 | 关系说明 |
| --- | --- | --- |
| Project / ProblemSpec | OptimizationCampaign | 当前 campaign 已承载目标、planner、候选库和状态。ResearchEngine 的 ProblemSpec 作为 campaign 的"研发意图层"叠加，通过 `campaign_id` 关联，不影响现有 campaign 独立使用 |
| Candidate | OptimizationCandidate | 当前 candidate 已承载 smiles、parameters、descriptors。ResearchEngine 候选可直接复用此对象 |
| Recommendation / ask | OptimizationSuggestion | 当前 suggestion 已承载 planner payload、状态（suggested/submitted/evaluated/rejected/failed）和提交计算关联。ResearchEngine 的 RECOMMENDATION_ASK 阶段产出复用此对象 |
| Observation / tell | OptimizationObservation | 当前 observation 已承载 values、uncertainty、source_run_id。ResearchEngine 的 RESULT_TELL 阶段复用此对象 |
| AlgorithmRun（人工/自动算法调用） | ComputationRun（计算任务执行） | **两者是不同抽象层级**：AlgorithmRun 是算法能力调用的通用记录（含 trigger_source、input_snapshot、output_summary），ComputationRun 是具体计算工作流的执行记录（含 workflow_type、engine、steps、resources）。当 AlgorithmRun 触发计算时，通过 `linked_computation_run_id` 指向 ComputationRun |
| Artifact | ComputationArtifact | 当前 artifact 已承载 storage_uri、checksum、parser metadata。AlgorithmRun 和 ResearchStageRun 均可引用 |
| AuditEvent | AuditEvent | 当前审计对象通过 `entity_type`/`entity_id` 区分实体，可直接扩展到 ResearchRun / StageRun / AlgorithmRun |

#### 字段级差异对比：AlgorithmRun vs ComputationRun

AlgorithmRun 和 ComputationRun 是不同的抽象层级，不是简单的 1:1 映射：

| 维度 | ComputationRun（现有） | AlgorithmRun（新增） | 设计理由 |
| --- | --- | --- | --- |
| 触发来源 | 隐式（均为用户通过 API 提交） | 显式 `trigger_source`: `human` / `autoresearch` / `system` | 区分人工通道和自动编排通道的产物 |
| 算法标识 | 派生自 `workflow_type` + `engine` 组合 | 显式 `algorithm_id` 外键指向 AlgorithmRegistry | 统一算法能力标识，不限于计算类 |
| 输入快照 | 分散在 `molecule` + `parameters` + `resources` 字段 | 统一 `input_snapshot: dict`，按 algorithm 的 input_schema 组织 | 适配非计算类算法（文献检索、性质预测等）的异构输入 |
| 输出摘要 | `result_summary: dict` + `artifact_ids: list` | `output_summary: dict` + `artifact_refs: list[dict]` | 扩展 artifact 引用为结构化列表（含 artifact_id、type、description） |
| 关联对象 | `campaign_id`, `suggestion_id` | 额外增加 `problem_spec_id`, `research_run_id`, `stage_run_id`, `linked_computation_run_id` | 支持双通道交汇点追溯：AlgorithmRun 可关联到 ResearchRun 的具体阶段，也可指向其触发的 ComputationRun |
| 步骤/阶段 | `steps: list[ComputationStep]`（step_key、label、status、timestamps、error） | 无独立步骤；AlgorithmRun 是原子操作。阶段概念属于 ResearchRun 的 ResearchStageRun | 计算任务有多个子步骤（CREST→xTB→parse），算法调用通常是单次执行 |
| 审计粒度 | 每次状态变更写 AuditEvent | 每次状态变更写 AuditEvent，**额外要求记录 `reason`** | 人工审批、拒绝、重跑等操作需要可解释性 |

**关键设计决策：** AlgorithmRun 和 ComputationRun 并存，不互相替代。当人工通道或 AutoResearch 通道需要执行计算时，AlgorithmRun 通过 `computation_submit_adapter` 创建 ComputationRun（复用现有 computation_service.create_run()），并将返回的 `run_id` 存入 `linked_computation_run_id`。ComputationRun 本身无需任何修改。AlgorithmRun 在 ComputationRun 完成前保持 `running` 状态，完成后转为 `completed` 并从 ComputationRun.result_summary 填充 output_summary。

#### 状态模型对比：Suggestion 状态 vs ResearchEngine Gate 审批

现有 OptimizationSuggestion 已有状态模型：`suggested → submitted → evaluated / rejected / failed`。ResearchEngine 的 Stage/Gate 审批不替代此模型，而是在其上叠加：

| 层级 | 对象 | 状态模型 | 关系 |
| --- | --- | --- | --- |
| 推荐生成 | OptimizationSuggestion | suggested → submitted → evaluated / rejected / failed | 保持现有逻辑不变 |
| AutoResearch 阶段门禁 | ResearchStageRun (stage_key=RECOMMENDATION_ASK) | pending → running → blocked_approval → completed / failed | **新增层**：阶段级审批控制是否将 suggestion 提交为 computation |
| 候选审核 | Gate 审批操作 | approve → 触发 submit_suggestion_computation()；reject → 记录原因 | 审批"批准"时调用现有 `submitSuggestionComputation` API |

---

## 10. 关键接口草案

本节只定义文档级接口草案，不要求本阶段实现。

### 10.1 ProblemSpec v0.2

ProblemSpec v0.2 增加执行模式、人工工具开关、AutoResearch 策略、stage gate 和审计策略。

```yaml
schema_version: 0.2
project:
  name: fluoropolymer_electrolyte_demo
  material_family: fluoropolymer
  profile_id: fluoropolymer

problem:
  type: formulation_process_optimization
  goal: recommend_next_experiments
  execution_mode: hybrid  # manual | autoresearch | hybrid

variables:
  - name: monomer_smiles
    type: categorical
    role: structure
  - name: fluorine_content
    type: continuous
    unit: percent
    bounds: [0, 100]
  - name: polymerization_temperature
    type: continuous
    unit: celsius
    bounds: [20, 180]

objectives:
  - name: dielectric_constant
    direction: maximize
    unit: dimensionless
  - name: thermal_stability
    direction: maximize
    unit: celsius
  - name: cost
    direction: minimize
    unit: CNY_per_kg

constraints:
  - name: synthesizable
    type: hard
  - name: equipment_temperature_limit
    expression: polymerization_temperature <= 180

measurements:
  - name: dielectric_constant
    condition: room_temperature
  - name: thermal_stability
    method: TGA

manual_tools_enabled:
  - literature_search
  - structure_feature
  - property_prediction
  - computation
  - optimizer_ask
  - result_tell

autoresearch_policy:
  enabled: true
  max_iterations: 5
  default_batch_size: 10
  allow_consume_manual_runs: true
  allow_submit_experiment: false
  require_human_review_before_experiment: true

stage_gates:
  PROBLEM_SPEC:
    require_approval: true
  RECOMMENDATION_ASK:
    require_approval: true
  EXPERIMENT_EXECUTION:
    require_approval: true
  MODEL_UPDATE:
    require_approval: true

algorithm_pipeline:
  literature: literature_rag.default
  structure_feature: polymer_descriptor.default
  compute_predict:
    - local_xtb
    - fluoropolymer_predictor.v1
  recommender: mobo.default

human_override_policy:
  allow_pause: true
  allow_rerun_stage: true
  allow_replace_candidates: true
  allow_mark_stage_failed: true

provenance_policy:
  save_input_snapshot: true
  save_output_artifacts: true
  save_algorithm_version: true
  save_random_seed: true
```

### 10.2 AlgorithmRun 来源表达

AlgorithmRun 必须区分人工、AutoResearch 和系统触发。

| 字段 | 说明 |
| --- | --- |
| run_id | 运行唯一标识 |
| algorithm_id | 算法能力 ID |
| trigger_source | human / autoresearch / system |
| trigger_context_id | 触发上下文，例如 request_id、research_run_id、stage_run_id |
| problem_spec_id | 关联 ProblemSpec |
| problem_spec_version | ProblemSpec 版本 |
| input_snapshot | 调用时输入快照 |
| output_artifacts | 输出 artifact 列表 |
| status | queued、running、completed、failed、cancelled |
| error | 失败原因和可重试标记 |
| created_by | 触发人或系统身份 |
| created_at / updated_at | 时间戳 |

### 10.3 ResearchRun

ResearchRun 表达 AutoResearch 主运行。

| 字段 | 说明 |
| --- | --- |
| run_id | AutoResearch 运行 ID |
| project_id | 所属项目 |
| problem_spec_id | 使用的问题规格 |
| profile_id | 使用的 material profile |
| status | draft、running、paused、blocked_approval、completed、failed、archived |
| current_stage | 当前阶段 |
| stage_runs | 阶段运行列表 |
| linked_algorithm_runs | 关联 AlgorithmRun 列表 |
| linked_experiment_runs | 关联 ExperimentRun 列表 |
| checkpoint | 最近一次可恢复状态 |
| summary | 运行摘要、指标、失败原因 |

### 10.4 StageContract

StageContract 表达每个阶段的输入输出和门禁策略。

| 字段 | 说明 |
| --- | --- |
| stage_key | 阶段标识，例如 RECOMMENDATION_ASK |
| required_inputs | 阶段必需输入 |
| expected_outputs | 阶段预期输出 |
| definition_of_done | 完成标准 |
| gate_policy | 是否需要人工审批、超时策略、允许操作 |
| retry_policy | 最大重试次数、可重试错误 |
| rollback_target | 审批拒绝或失败后的回滚阶段 |
| artifact_policy | 本阶段必须保存的 artifact 类型 |

---

## 11. ask/tell 闭环

平台的最小闭环应采用 ask/tell 模式，人工通道和 AutoResearch 通道共享同一闭环。

1. 用户或 AutoResearch 定义 ProblemSpec；
2. Parser 校验变量、目标、约束、单位和边界；
3. 人工工具或 AutoResearch ask 生成 Top-K 候选；
4. 人工审核候选，批准、否决或修改；
5. computation、mock LabOS 或人工流程执行实验；
6. 实验结果 tell 回填到平台；
7. 平台生成 Observation，并更新数据集和模型状态；
8. 下一轮人工工具调用或 AutoResearch ask 基于新数据继续推荐。

该闭环的关键不是一开始实现全自动设备控制，而是先跑通可追溯的数据闭环。第一版可以使用 mock LabOS 或人工上传结果，待接口稳定后再接真实设备参数下发和回调。

---

## 12. 氟基高分子样板流程

第一阶段建议以氟基高分子为样板，验证同一个 ProblemSpec 下人工触发和 AutoResearch 自动编排如何并行产生产物并进入同一审计链。

### 12.1 人工通道样板

1. 用户创建氟基高分子 ProblemSpec；
2. 用户人工触发文献检索，得到候选单体和结构线索；
3. 用户导入候选 SMILES，生成结构描述符；
4. 用户选择部分候选触发 LOCAL_XTB 或 ORCA_COMPUTE_ENGINE_LASER；
5. 用户手动触发 BO/MOBO 推荐；
6. 用户审核候选，提交计算或人工实验；
7. 用户上传实验结果，形成 Observation。

### 12.2 AutoResearch 通道样板

1. AutoResearch 读取同一个 ProblemSpec；
2. KNOWLEDGE_RETRIEVAL 阶段消费人工文献检索结果和已有知识库；
3. STRUCTURE_FEATURE 阶段消费人工导入候选，并补齐缺失描述符；
4. COMPUTE_PREDICT 阶段根据 policy 选择预测模型或计算 adapter；
5. RECOMMENDATION_ASK 阶段生成 Top-K 候选；
6. HUMAN_REVIEW 阶段等待用户批准或修改；
7. EXPERIMENT_EXECUTION 阶段提交 mock LabOS 或 computation；
8. RESULT_TELL 阶段回填 Observation；
9. MODEL_UPDATE 阶段更新模型状态；
10. ARCHIVE_LEARNING 阶段归档本轮经验。

### 12.3 并行产物汇合

人工通道和 AutoResearch 通道产生的 AlgorithmRun、ExperimentRun、Observation、AuditEvent 必须挂接到同一个 Project / ProblemSpec / Campaign 下。后续推荐算法可以同时消费人工通道和 AutoResearch 通道的历史产物。

---

## 13. 技术路线与 MVP

![AI+高分子材料工具链平台技术路线](<ChatGPT Image 2026年6月22日 16_03_02.png>)

平台建设建议分为四个 MVP 阶段。

### 13.1 MVP-1：双通道文档与领域模型统一

目标是统一表达人工工具调用和 AutoResearch run 共享数据模型。

主要工作包括：

- 明确 manual、autoresearch、hybrid 三种 execution_mode；
- 梳理 Project、ProblemSpec、AlgorithmRun、ResearchRun、Candidate、Observation、AuditEvent 的关系；
- 定义 ProblemSpec v0.2、AlgorithmRun、ResearchRun、StageContract 字段草案；
- 将现有 Poly_Agent campaign/suggestion/observation/computation/audit 映射到 ResearchEngine 领域模型。

阶段产物：

- v0.2 技术方案；
- 双通道架构图说明；
- 核心对象和接口草案；
- 氟基高分子样板流程。

### 13.2 MVP-2：复用现有闭环底座

目标是沿用现有 campaign、suggestion、observation、computation、audit 作为闭环底座。

主要工作包括：

- 保持当前 optimization ask/tell 流程；
- 保持 current computation run 和 artifact 机制；
- 扩展文档约定中的 trigger_source 和 provenance 字段；
- 支持人工通道产物被后续 AutoResearch 阶段引用。

阶段产物：

- 可回放的人工工具调用记录；
- 人工 recommendation -> computation -> observation 闭环；
- 审计事件和 artifact 查询链路。

### 13.3 MVP-3：AutoResearch 材料版阶段编排

目标是实现材料版 ResearchRun 和 StageContract。

主要工作包括：

- 定义材料版阶段序列；
- 定义 stage status、gate、retry、rollback；
- 支持 checkpoint、pause、resume；
- 支持 AutoResearch 调用已有 planner 和 computation service；
- 支持人工审批候选和实验提交。

阶段产物：

- 一个可运行的 ResearchRun 原型；
- 至少一个材料 profile；
- 至少两个可被 AutoResearch 调用的 algorithm adapter；
- 阶段级 artifact bundle。

### 13.4 MVP-4：模型更新与经验沉淀

目标是形成跨轮次优化能力。

主要工作包括：

- 将 Observation 纳入模型更新或数据集更新记录；
- 记录推荐策略收益、失败实验、异常数据和人工否决原因；
- 建立材料研发 lesson 库；
- 支持不同策略和不同材料体系的历史回放评估。

阶段产物：

- ModelUpdate 记录；
- lesson / archive 机制；
- 跨轮次回放和策略对比报告；
- 面向更多材料体系的扩展模板。

### 13.5 开发测试评审 PRD 草案

本节将 v0.3 设计拆为可开发、可测试、可评审的 PRD 条目。优先级定义为：

- P0：ResearchEngine MVP 演示和内测必须具备；
- P1：第一批真实用户使用需要具备；
- P2：生产化和多材料体系扩展能力。

#### 13.5.1 用户角色与权限边界

| 角色 | 核心诉求 | P0 权限 |
| --- | --- | --- |
| 材料研发用户 | 创建 ProblemSpec、查看推荐、提交人工结果 | 创建和编辑自己的 project / campaign / ProblemSpec，运行人工算法，审批自己的 gate |
| 算法工程师 | 接入算法、查看运行记录、调试 adapter | 管理 AlgorithmRegistry 草稿，查看 AlgorithmRun 输入输出和错误 |
| 实验人员 | 接收实验任务、回填结果和失败原因 | 查看已批准 ExperimentRun，上传结果和原始文件 |
| 项目管理员 | 管理项目成员、冻结规格、归档 run | 管理 project 下全部 ResearchRun、gate 和 audit |
| 系统管理员 | 管理算法状态、集成配置、审计 | 全局 AlgorithmRegistry、integration config 和数据库管理 |

P0 不要求实现复杂 RBAC，但所有新增对象必须预留 `created_by`、`owner_id`、`project_id`、`actor_role` 和 audit 字段，避免后续补权限时破坏数据结构。

#### 13.5.2 功能需求清单

| ID | 优先级 | 需求 | 验收标准 |
| --- | --- | --- | --- |
| RE-001 | P0 | ProblemSpec v0.2 创建、校验、查看 | 用户可创建材料研发任务；变量、目标、约束、execution_mode 可保存；非法单位/边界返回结构化错误 |
| RE-002 | P0 | 复用 OptimizationCampaign 作为首版 Project / ProblemSpec 容器 | 新建 ResearchEngine 任务时可关联或创建 campaign；candidate / suggestion / observation 不重复建一套孤岛对象 |
| RE-003 | P0 | AlgorithmRegistry 只读清单 | 前端可查看算法名称、类型、材料范围、触发方式、状态、schema 摘要 |
| RE-004 | P0 | 人工 AlgorithmRun 创建 | 用户从算法清单选择算法并运行；系统保存 trigger_source=human、输入快照、输出 artifact、错误信息 |
| RE-005 | P0 | AutoResearch ResearchRun 草稿和启动 | 用户可基于 ProblemSpec 创建 ResearchRun；启动后按固定阶段推进到首个 gate 或 mock 完成 |
| RE-006 | P0 | Stage/Gate 状态机 | 支持 pending、running、blocked_approval、completed、failed；审批需要记录 actor、decision、reason |
| RE-007 | P0 | 候选审核与计算提交 | RECOMMENDATION_ASK 产出的候选可批准、拒绝、修改原因；批准后可复用现有 computation submit 链路 |
| RE-008 | P0 | Observation 回填 | computation 或人工结果可生成 Observation；必须关联 candidate、suggestion 或 stage_run |
| RE-009 | P0 | Artifact 和 Audit 追溯 | 每个 ResearchRun / AlgorithmRun / StageRun 可查看输入快照、输出 artifact、关键审计事件 |
| RE-010 | P0 | UI 入口最小闭环 | `/tasks/submit`、`/optimization`、campaign detail 至少有 ResearchEngine / AutoResearch 入口，不新增复杂独立壳 |
| RE-011 | P1 | Schema 驱动算法表单 | input_schema 自动渲染基础表单控件，支持从 Candidate / ProblemSpec 填充输入 |
| RE-012 | P1 | Stage 重跑、暂停、恢复 | 用户可暂停 ResearchRun、从 checkpoint 恢复、对失败 stage 重跑 |
| RE-013 | P1 | AlgorithmRegistry 管理 | 管理员可启用/停用算法、更新状态、设置默认 stage algorithm |
| RE-014 | P1 | 模型更新记录 | Observation 采纳后生成 ModelUpdate，记录数据快照和评估指标 |
| RE-015 | P2 | 多材料 profile 模板 | 氟基、碳基、硅基、含氟-碳共聚体系可使用不同默认算法和 gate 策略 |
| RE-016 | P2 | 真实 LabOS / SpecLabOS 提交 | EXPERIMENT_EXECUTION 可从 mock / manual 切换到真实外部 workflow |

#### 13.5.3 前端开发任务

| 任务 | 范围 | 依赖 | 对应计划 | 验收 |
| --- | --- | --- | --- | --- |
| FE-1 任务模块入口 | 在 `TASK_MODULES` 增加 ResearchEngine 研发任务卡，路由到湿实验优化或 ResearchEngine 入口页 | RE-010 | Plan 05 Task 2 | 任务提交页能看到入口，按钮可跳转 |
| FE-2 湿实验优化入口扩展 | 在 `/optimization` 增加 ResearchEngine / AutoResearch 入口卡 | FE-1 | Plan 05 Task 2 | 与现有 Campaign、Alchemist 卡片视觉一致 |
| FE-3 Campaign 详情分区 | 在 campaign detail 中增加 AutoResearch / 人工算法 / 审计区，可先用 tab 或 panel | RE-002 | Plan 05 Task 3-5 | 不破坏现有 Candidates、Suggestions、Observations 操作 |
| FE-4 ProblemSpec 表单 | 新增 ProblemSpec 编辑和预览组件 | RE-001 | Plan 05 Task 3 | 支持变量、目标、约束、执行模式编辑和 JSON/YAML 预览 |
| FE-5 AlgorithmRegistry 页面/区块 | 在 Tool Services 或 ResearchEngine 页面展示算法能力清单 | RE-003 | Plan 05 Task 4 | 支持按类型、材料体系、触发方式筛选 |
| FE-6 AlgorithmRun 表单与详情 | 根据 schema 渲染输入表单，展示运行结果和 artifact | RE-004 | Plan 05 Task 4 | 人工运行后可看到状态、输入快照、输出和错误 |
| FE-7 ResearchRun Stage 看板 | 展示 ResearchRun 当前阶段、stage timeline、gate 待办 | RE-005、RE-006 | Plan 05 Task 5 | blocked_approval 状态下审批操作可见 |
| FE-8 Gate 审批交互 | 审批 dialog、拒绝原因、候选修改入口 | RE-006、RE-007 | Plan 05 Task 5 | 批准/拒绝/修改均写 audit，失败提示可理解 |
| FE-9 全局任务映射 | 将 ResearchRun / AlgorithmRun 映射到任务中心 | RE-010 | Plan 05 Task 6 | 任务中心可筛选并跳转详情 |

前端实现约束：

- 继续使用 Element Plus、现有 CSS 变量、`panel`、`page-grid`、`el-table`、`el-dialog`、`el-drawer`、`el-tag`、`el-steps` 等已有模式。
- 不引入新的大型状态管理或 UI 框架；若只是页面局部状态，优先使用 Vue `ref` / `computed`。
- ResearchEngine 页面文案应中文化，技术对象名仅在详情、审计和调试区出现。
- 移动端至少保证 768px 宽度可用；复杂表格在窄屏下允许横向滚动。

#### 13.5.4 后端开发任务

| 任务 | 范围 | 依赖 | 对应计划 | 验收 |
| --- | --- | --- | --- | --- |
| BE-1 Schema 定义 | 增加 ProblemSpec、AlgorithmRegistry、AlgorithmRun、ResearchRun、ResearchStageRun、StageGate schema | 无 | Plan 01 Task 1a-1b | Pydantic 校验覆盖正常和错误输入 |
| BE-2 Repository 扩展 | 在现有 demo / mongo repository 模式下持久化新增对象 | BE-1 | Plan 01 Task 2 | 可创建、查询、分页、按 project/campaign 过滤 |
| BE-3 ProblemSpec API | 创建、更新草稿、冻结、校验、详情 | BE-1、BE-2 | Plan 02 Task 1-2 | API 返回结构化 validation error |
| BE-4 AlgorithmRegistry API | 清单、详情、健康状态、只读默认数据 | BE-1、BE-2 | Plan 02 Task 3-4 | 前端可渲染算法卡和 schema drawer |
| BE-5 AlgorithmRun API | 创建人工运行、查询列表、详情、artifact 关联 | BE-4 | Plan 03 Task 1-3 | 运行记录包含 trigger_source、input_snapshot、status |
| BE-6 ResearchRun Orchestrator MVP | 创建 run、启动、推进固定 stage、暂停、恢复 | BE-3、BE-5 | Plan 04 Task 1-2, 5 | 一个 mock ResearchRun 可推进到 gate 并恢复 |
| BE-7 Stage/Gate API | 审批、拒绝、重跑、标记失败、回滚目标记录 | BE-6 | Plan 04 Task 3 | 每个 gate 决策写 AuditEvent |
| BE-8 Campaign/Computation 复用 | 将 approved suggestion 复用现有 submit computation 和 observation 生成能力 | BE-6、现有 optimization/computation | Plan 04 Task 4 | 不重复实现计算任务系统 |
| BE-9 Audit/Artifact 查询 | 按 ResearchRun / AlgorithmRun / StageRun 聚合审计和 artifact | BE-5、BE-6 | Plan 06 Task 1 | 详情页可展示完整追溯链 |

后端实现约束：

- P0 阶段不 vendor `refer/AutoResearchClaw-main`，只实现材料版状态机和契约。
- adapter 调用必须有白名单和 schema 校验，前端不得传任意 shell command、本地路径或 job script。
- 新增 API 路由应沿用 `/api/v1`、Pydantic schema、service/repository 分层和现有错误格式。
- 所有状态变更必须写 audit，至少记录 actor、entity_type、entity_id、event_type、reason、before、after。

#### 13.5.5 测试计划

| 测试类型 | P0 覆盖范围 | 验收命令 / 方式 |
| --- | --- | --- |
| Schema 单元测试 | ProblemSpec 校验、AlgorithmRun trigger_source、ResearchRun status、StageContract gate policy | `pytest backend/tests/test_research_engine_schemas.py` |
| Service 单元测试 | 创建 ProblemSpec、创建 ResearchRun、推进 stage、审批 gate、失败重试 | `pytest backend/tests/test_research_engine_service.py` |
| API 集成测试 | ProblemSpec API、AlgorithmRegistry API、AlgorithmRun API、ResearchRun API | `pytest backend/tests/test_research_engine_api.py` |
| 回归测试 | 现有 computation、optimization、integration config 不被破坏 | `pytest backend/tests/test_computation_service.py backend/tests/test_optimization_service.py backend/tests/test_integration_config_service.py` |
| 前端单元测试 | 若引入测试框架，覆盖 schema form、stage board、gate dialog 的关键状态 | `npm test` 或项目约定命令 |
| 前端构建 | Vue 页面和路由可构建 | `cd frontend && npm run build` |
| 浏览器验收 | Dashboard、任务提交、湿实验优化、Campaign 详情、Tool Services 入口可点击 | Playwright 或手工冒烟 |

P0 手工验收脚本：

1. 创建 ResearchEngine 研发任务，填写氟基高分子 ProblemSpec；
2. 在人工算法工作台选择一个 mock predictor，运行并生成 AlgorithmRun；
3. 基于同一 ProblemSpec 创建 AutoResearch ResearchRun；
4. 启动 ResearchRun，推进到 RECOMMENDATION_ASK 或 HUMAN_REVIEW；
5. 审批一个候选并提交 computation；
6. computation 完成后生成 Observation；
7. 在 ResearchRun 详情查看 stage timeline、artifact、audit 和 observation 关联；
8. 在任务中心能看到 ResearchRun / AlgorithmRun；
9. 暂停、恢复、失败重跑至少一条路径可用；
10. 现有 campaign candidate / suggestion / observation 页面仍可正常使用。

#### 13.5.6 评审清单

产品评审：

- 是否保留了人工通道，不把 AutoResearch 设计成不可干预黑盒；
- 用户是否能在 3 步内从工作台或湿实验优化进入 ResearchRun；
- 每个 gate 是否明确展示“为什么需要审批”和“批准后会发生什么”；
- 算法名称、输入输出、适用材料范围是否能被非算法工程师理解；
- 失败、拒绝、异常数据是否都有明确记录入口。

技术评审：

- 新对象是否复用现有 campaign / computation / observation / audit，而不是重复造闭环；
- ProblemSpec、AlgorithmRegistry、StageContract 是否有版本字段和向后兼容策略；
- adapter 调用是否受 schema、白名单和权限控制；
- ResearchRun 是否支持 checkpoint、pause、resume、失败状态和可追溯 artifact；
- 所有状态变更是否都有测试和 audit。

UI 评审：

- 是否沿用现有导航、panel、表格、tag、dialog、drawer 语言；
- 是否避免新增不必要的一级导航和独立视觉体系；
- 表格长字段、JSON、artifact 列表是否有 drawer / pre / 横向滚动处理；
- 高影响按钮是否有确认、loading、禁用态和失败提示；
- 320px、768px、1024px、1440px 视口下不出现文字重叠或按钮溢出。

交付评审：

- 每个 P0 需求都有后端测试或前端构建/浏览器验收；
- 新文档、API schema、默认 demo 数据保持同步；
- 未完成的 P1/P2 明确在 issue 或后续计划中，不混入 P0 半成品；
- 不提交 `.runtime`、`dist`、`node_modules`、本地密钥或大文件产物。

---

## 14. 数据治理与可追溯要求

平台必须从第一版开始保存 provenance，否则后期很难补齐。

需要记录的内容包括：

- 原始输入文件；
- 数据清洗和单位转换规则；
- ProblemSpec 版本；
- execution_mode 和 trigger_source；
- AutoResearch stage、gate 和 checkpoint；
- 算法名称、版本、参数和随机种子；
- 训练数据或历史数据快照；
- 推荐候选列表；
- 人工审核记录；
- 实验执行状态；
- 失败原因；
- 原始测试数据；
- 模型产物和评估结果；
- 人工覆盖、重跑、接管和回滚记录。

数据治理的重点不是做复杂数据湖，而是确保每一次人工调用、每一次 AutoResearch 阶段推进、每一次推荐、每一次实验和每一次模型更新都能被审计和回放。

---

## 15. 风险与应对

| 风险 | 表现 | 应对 |
| --- | --- | --- |
| AutoResearch 被误解为替代人工 | 用户担心失去专家控制，或自动流程绕开审核 | 明确双通道并行，关键阶段默认 HITL gate |
| 算法能力与材料需求不匹配 | 算法能跑，但不能解决实际材料问题 | 先做需求矩阵和算法能力清单，再开发平台 |
| 输入输出不统一 | 每个算法都要单独适配前端和数据 | 建立 Algorithm Adapter、I/O schema 和 StageContract |
| 实验数据质量不足 | 模型效果不稳定，推荐不可解释 | 增加数据质量检查、单位标准化、失败记录和人工确认 |
| 平台过早追求全自动 | 设备对接复杂，MVP 周期失控 | 第一版采用 mock LabOS + 人工回填 |
| 缺少回放能力 | 无法证明算法优于 baseline | 每次 ask 保存数据快照、版本、seed 和 trigger_source |
| 单材料定制过重 | 后续难扩展到其他材料体系 | schema 面向材料通用流程设计，样板只用于验证 |
| 直接搬迁 AutoResearchClaw 代码导致维护成本高 | 论文流水线和材料研发平台目标不一致 | 只抽象迁移状态机、契约、HITL、artifact、profile 和 memory 思想 |

---

## 16. 建议结论

ResearchEngine 的建设重点应从“做一个算法工具”上升为“构建高分子材料 AI 研发的双通道操作系统”。平台既要保留人工算法触发通道，让专家能够快速探索、调试和确认；也要引入 AutoResearch 自动编排通道，让系统能够围绕 ProblemSpec 连续推进候选推荐、实验执行、结果回填和模型更新。

建议以需求矩阵为牵引，把不同材料体系的研发流程拆解为可复用步骤；以算法能力清单为抓手，把已有和待建算法沉淀为可管理资产；以 ProblemSpec v0.2、AlgorithmRun、ResearchRun、StageContract 和 ask/tell API 为技术标准，打通人工通道与 AutoResearch 通道之间的数据流、控制流和审计流。

第一阶段不应追求全量自动化，而应优先证明四件事：

1. 人工触发和 AutoResearch 自动编排可以并行存在，并共享同一套对象；
2. 不同材料体系可以复用同一套任务规格和阶段契约；
3. 不同算法可以在同一接口下被人工调用或自动编排；
4. 推荐、实验、回填、模型更新、人工覆盖和自动阶段推进全过程可追溯、可回放、可评估。

在此基础上，平台可以逐步扩展到更多材料体系、更多算法库、更真实的 LabOS / 湿实验自动化场景，以及更强的跨轮次主动学习和经验沉淀能力。

---

## 17. 与现有计算工作流的集成

Poly_Agent 当前已实现三条计算 Workflow：`LOCAL_STRUCTURE`（RDKit/OpenBabel 三维结构生成）、`LOCAL_XTB`（CREST 构象搜索 + xTB 半经验能量计算）、`ORCA_COMPUTE_ENGINE_LASER`（CREST + xTB + ORCA DFT 精加工）。详细使用说明见 `doc/computation-workflows-user-guide.md`。

这三条 Workflow 在 ResearchEngine 中作为 AlgorithmRegistry 的计算类算法条目接入，不需要重新实现计算逻辑。

### 17.1 Workflow → AlgorithmRegistry 映射

| algorithm_id | type | material_scope | task_scope | 对应 Workflow | Engine |
| --- | --- | --- | --- | --- | --- |
| `local_structure_adapter` | simulator | fluoropolymer, carbon_polymer, silicon_polymer, universal | structure_feature | `LOCAL_STRUCTURE` | `LOCAL` / `RDKit` / `OPENBABEL` |
| `local_xtb_adapter` | simulator | fluoropolymer, carbon_polymer, silicon_polymer, universal | compute_predict | `LOCAL_XTB` | `XTB` |
| `orca_compute_engine_laser_adapter` | simulator | fluoropolymer, carbon_polymer, silicon_polymer, universal | compute_predict | `ORCA_COMPUTE_ENGINE_LASER` | `ORCA` |

### 17.2 各算法条目的 input_schema / output_schema

**`local_structure_adapter`：**
- input_schema：`smiles: string`（必填，SMILES 表达式）、`name: string`（可选，分子名）
- output_schema：`structure.xyz`（原子坐标）、`structure.sdf`（含键级信息）、`structure.json`（结构化数据）
- trigger_modes：`["human", "autoresearch"]`
- runtime_dependency：Python RDKit 或系统 OpenBabel

**`local_xtb_adapter`：**
- input_schema：`smiles: string`（必填）、`charge: int`（默认 0，范围 -5~5）、`multiplicity: int`（默认 1，范围 1~6）、`method: string`（GFN2-xTB / GFN1-xTB / GFN0-xTB）、`solvent: string`（可选，WATER / ACETONITRILE / TOLUENE 等）
- output_schema：`energy_hartree: float`（总能量）、`normal_termination: bool`、`xtb_version: string`、`runtime_seconds: float`
- trigger_modes：`["human", "autoresearch"]`
- runtime_dependency：系统 xTB + CREST 可执行文件

**`orca_compute_engine_laser_adapter`：**
- input_schema：`smiles: string`（必填）、`charge: int`（默认 0）、`multiplicity: int`（默认 1）、`method: string`（ORCA_B3LYP_DEF2_SVP / ORCA_PBE0_DEF2_SVP）
- output_schema：`energy_hartree: float`（FINAL SINGLE POINT ENERGY）、`normal_termination: bool`
- trigger_modes：`["human", "autoresearch"]`
- runtime_dependency：系统 ORCA + xTB + CREST 可执行文件，ORCA license 可用

### 17.3 调用路径

当人工通道或 AutoResearch 通道触发上述 adapter 时，AlgorithmRun 通过 `computation_submit_adapter` 委托给现有 `ComputationService.create_run()` 创建 ComputationRun。AlgorithmRun 保存 `linked_computation_run_id` 指向 ComputationRun，并在 ComputationRun 完成后从 `result_summary` 填充 `output_summary`。

```
人工/AutoResearch 触发
  → AlgorithmRun (trigger_source=human|autoresearch, algorithm_id=local_xtb_adapter)
    → ComputationService.create_run()  → ComputationRun (workflow_type=LOCAL_XTB, engine=XTB)
      → ComputationWorker 领取并执行 → completed
    → AlgorithmRun 读取 ComputationRun.result_summary → output_summary
  → AlgorithmRun 状态: completed
```

### 17.4 方法白名单与安全约束

所有计算类 adapter 的方法、溶剂参数必须受后端白名单控制（与现有 `computation.py` 中 `ALLOWED_METHODS`、`ALLOWED_SOLVENTS` 一致）。前端不得传任意 shell command、本地路径或 job script。adapter 调用必须有 schema 校验（input_schema 定义必填字段、类型、边界），安全设计遵循现有 computation 模块的约束。

---

## 18. 与部署工具链的关系

ResearchEngine 不引入新的 conda 环境或系统依赖。所有计算能力（xTB、CREST、ORCA）已在工具链部署包（`doc/poly-agent-toolchain-deployment-pack.md`）中覆盖。

### 18.1 部署包工具 → AlgorithmRegistry 条目

| 部署包安装的工具 | ResearchEngine 中的 algorithm_id | 说明 |
| --- | --- | --- |
| RDKit（核心必装） | `local_structure_adapter` | 结构生成算法依赖 |
| xTB + CREST（核心必装） | `local_xtb_adapter` | xTB 计算算法依赖 |
| ORCA（可选，用户自行安装） | `orca_compute_engine_laser_adapter` | ORCA 精加工算法依赖（仅 ORCA_LICENSE_AVAILABLE=true 时可用） |
| ALchemist（可选，完整模式） | 后续 P1 作为独立 algorithm_id 接入 | 主动学习优化后端 |
| AiiDA（可选，探测级） | P2 作为 provenance adapter 接入 | 计算溯源框架 |

### 18.2 验收衔接

工具链部署包的验证脚本（`verify_toolchain.py`）确保核心 CLI 工具可用。ResearchEngine P0 完成后，建议在验证脚本中增加以下可选项（标记为"P0 完成后启用"）：

- ResearchEngine ProblemSpec API 可达性检查：`GET /api/v1/research-engine/problem-specs`
- AlgorithmRegistry 默认清单可返回：`GET /api/v1/research-engine/algorithms`
- ResearchEngine smoke demo：创建 ProblemSpec → 人工运行 mock predictor → 查看 AlgorithmRun

---

## 19. 现有数据兼容性与迁移

ResearchEngine 采用**纯加法策略**，不对现有数据模型做破坏性修改。

### 19.1 现有功能保持

- 现有 computation 模块（`/api/v1/computations`）继续独立工作，不受 ResearchEngine 影响
- 现有 optimization 模块（`/api/v1/optimization`）的 campaign/suggestion/observation 闭环继续独立工作
- 现有 integration config、admin、auth、ALchemist proxy、LLM 模块不受影响
- ComputationWorker 的自动闭环钩子（`process_completed_computation()`）继续工作

### 19.2 新增关联字段

ResearchEngine 的新增对象通过**可选外键**与现有对象建立关联：

| 新增字段（在新增对象上） | 指向现有对象 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| ProblemSpec.campaign_id | OptimizationCampaign | 否 | 可关联已有 campaign 作为容器 |
| AlgorithmRun.linked_computation_run_id | ComputationRun | 否 | 当算法触发计算时填充 |
| AlgorithmRun.problem_spec_id | ProblemSpec | 否 | 关联研发任务 |
| ResearchRun.problem_spec_id | ProblemSpec | 是 | 每个 AutoResearch run 必须关联一个 ProblemSpec |
| ResearchRun.campaign_id | OptimizationCampaign | 否 | 复用已有 campaign 的候选库和 observation |

### 19.3 无需数据迁移

- 已有 campaign 无需升级为 ProblemSpec。用户可以继续使用现有湿实验优化流程
- 新建 ResearchEngine 任务时，可选择关联已有 campaign 或让系统自动创建首版 campaign 容器
- 已有 computation run 无需回溯关联 AlgorithmRun
- P0 阶段不要求历史数据的批量回填

### 19.4 回归测试保障

每次 ResearchEngine 代码变更必须确保以下现有测试通过：

```bash
pytest backend/tests/test_computation_service.py \
      backend/tests/test_optimization_service.py \
      backend/tests/test_integration_config_service.py \
      backend/tests/test_computation_mvp.py \
      backend/tests/test_local_structure_adapter.py \
      backend/tests/test_local_xtb_adapter.py \
      backend/tests/test_orca_compute_engine_laser_workflow.py
```

这是 P0 验收的硬条件，与 `doc/research-engine-plan-06-traceability-and-qa.md` 中的回归测试清单保持一致。
