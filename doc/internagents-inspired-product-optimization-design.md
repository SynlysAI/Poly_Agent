# PolyAgent 借鉴 InternAgents 的产品设计优化方案

日期：2026-07-27  
状态：产品设计建议  
适用范围：PolyAgent 工作台、产品内助手、ResearchEngine、任务中心、算法与产物管理

## 1. 背景与判断

InternAgents 是上海人工智能实验室研发的智能体工作台，面向科研、学习和技术探索场景，围绕工作区文件完成阅读、总结、分析、生成和审批协作。其用户手册强调的核心产品对象包括工作区、会话、文件预览、附件、长任务 `/goal`、审批与安全、模型配置和技能管理。

PolyAgent 的核心不是通用智能体工作台，而是高分子材料智能研发平台。当前系统已经具备 Alchemist、ComputeEngine、ResearchEngine、垂类预测、Knowledge Base、Data Catalog、任务中心和产品内助手等领域模块。因此，PolyAgent 不应照搬 InternAgents 的通用桌面工作台形态，而应吸收其“Agent 产品化操作模型”，并落到 PolyAgent 已有的 ProblemSpec、WorkflowRun、ResearchRun、AlgorithmRun、Artifact、Gate 和审计对象上。

结论：InternAgents 最值得借鉴的是“让 Agent 工作变得可组织、可恢复、可审批、可复用”的交互与治理方式；PolyAgent 应将这些能力领域化，形成材料研发项目空间和可追溯研发协作流。

参考：

- InternAgents 用户手册：https://internscience.github.io/InternAgents/user-manual/
- InternAgents GitHub README：https://github.com/InternScience/InternAgents
- PolyAgent 当前总览：`README.md`
- PolyAgent ResearchEngine 设计：`doc/research-engine-and-auto-research-design.md`

## 2. 产品优化目标

1. 把 PolyAgent 从“多个功能模块集合”进一步收敛为“围绕材料研发任务持续推进的协作工作台”。
2. 让用户能围绕一个材料研发项目持续积累文献、数据、结构、计算结果、算法运行和报告。
3. 让产品内助手从问答入口升级为能理解当前项目、当前任务和当前产物的研发协作入口。
4. 把长任务、审批、文件预览、技能/能力配置等 Agent 产品能力纳入现有 ResearchEngine 与任务中心，而不是另建一套平行系统。
5. 强化安全、来源、贡献和审计，让平台适合多人协作、算法交付和科研结果复用。

## 3. 借鉴点与 PolyAgent 落地设计

### 3.1 工作区 -> 材料研发项目空间

InternAgents 以工作区文件夹作为 Agent 能看到和操作的范围。PolyAgent 应将这一概念领域化为“研发项目空间”。

建议能力：

- 每个 Project Workspace 绑定一个或多个 ProblemSpec、Campaign、ResearchRun 和报告任务。
- 项目空间统一管理论文 PDF、实验 CSV、结构文件、谱图、计算 log、模型文件、运行 artifact 和导出报告。
- 所有文件进入平台后生成安全元数据、来源、所属任务、所属用户、可复用状态和审计记录。
- ResearchEngine、Knowledge Base、ComputeEngine 和垂类预测不直接复制文件，而是引用同一套 Workspace Asset。

产品收益：

- 用户不再需要在知识库、计算任务、算法结果和报告之间手工拼上下文。
- AutoResearch 和人工 Workflow 都可以消费同一个项目空间中的可信资产。
- 后续做权限、归档、导出和 credit 统计时有统一对象。

### 3.2 会话管理 -> 项目会话

InternAgents 支持新建会话、切换旧会话、修改标题和归档。PolyAgent 当前产品内助手已经支持科研问答、深度思考、模型选择和结构化跳转，但会话与材料研发对象的绑定还应加强。

建议能力：

- 新增 Project Conversation 概念，允许会话绑定 `problem_spec_id`、`campaign_id`、`research_run_id` 或 `algorithm_run_id`。
- 会话标题默认由研发任务、材料体系、目标性质或运行阶段生成，用户可修改。
- 归档会话不删除上下文，只从常用列表收起。
- 从 ResearchEngine、任务中心、算法运行详情和报告页进入助手时，自动携带当前对象上下文。
- 助手回复中的动作卡直接跳转到相关页面或创建下一步草稿。

产品收益：

- 用户能继续上次未完成的材料研发讨论。
- 研发任务、运行记录和对话决策可以互相追溯。
- 助手不再只是“问入口在哪里”，而能成为项目内协作入口。

### 3.3 `/goal` 长任务 -> Research Goal

InternAgents 用 `/goal` 处理需要分步骤推进的长目标。PolyAgent 应避免引入裸命令式 `/goal`，而应定义领域化的 Research Goal。

建议能力：

- Research Goal 是 ProblemSpec 下的长任务目标，例如“基于 KrF 文献和已有候选推荐 10 个低吸收高 Tg 单体组合，并生成实验计划”。
- 创建 Research Goal 后，系统拆解为可追踪阶段：资料检索、候选生成、性质预测、优化推荐、人工审批、实验计划、报告生成。
- 每个阶段落到现有 ResearchEngine 的 StageRun、AlgorithmRun、ComputationRun 或 ReportJob。
- Research Goal 进入任务中心，支持状态、进度、当前阻塞点和下一步动作展示。
- 跑偏时允许用户在会话中纠正目标，系统记录目标修订和影响范围。

产品收益：

- 将“长对话”变成“可运营任务”。
- 适合 AutoResearch，也适合人工 Workflow 分阶段接管。
- 降低复杂任务的认知负担。

### 3.4 审批卡片 -> 统一 Action Card

InternAgents 的审批卡片会展示工具、参数和 Approve / Reject / Edit 操作。PolyAgent 已有 AutoResearch Gate 和任务中心 `blocked_approval` 状态，应进一步统一成跨模块 Action Card。

建议能力：

- Action Card 用于所有关键决策：AutoResearch Gate、提交外部计算、部署算法包、导入数据集、生成/导出报告、覆盖已有产物。
- 卡片展示动作类型、目标对象、关键参数、预期产物、风险提示、来源证据和影响范围。
- 用户可以批准、拒绝或编辑参数后再执行。
- 每次操作写入 AuditEvent，并回显到 ResearchRun / AlgorithmRun / TaskCenter 追溯面板。
- 高风险操作默认必须审批，低风险读操作可由配置决定是否自动执行。

产品收益：

- 审批体验统一，用户不用在不同模块学习不同操作语义。
- 关键科研决策可回放。
- 更适合多人协作和管理员治理。

### 3.5 技能管理 -> 领域能力包

InternAgents 的技能用于增加特定任务专长。PolyAgent 不应做泛用技能市场，而应将其转化为可信的材料研发能力包。

建议能力：

- 能力包按领域组织，例如文献综述、结构生成、xTB/ORCA、性质预测、BO/MOBO、实验回填、报告生成。
- 能力包不是单纯 prompt，而是 AlgorithmRegistry、adapter、报告 skill pipeline、知识库 corpus、依赖服务和来源标注的组合视图。
- 能力中心展示每个能力包的状态：可用、缺配置、mock、fallback、禁用。
- 管理员可以启用/禁用能力包，并配置适用材料体系、触发方式和审批策略。
- 用户在 ResearchEngine 中只看到当前 ProblemSpec 可用且可信的能力。

产品收益：

- 把算法货架、工具服务、模型选择和技能概念统一起来。
- 避免用户误以为 mock/fallback 是生产能力。
- 便于对合作者展示“平台有什么能力、谁贡献、是否可运行”。

### 3.6 文件预览与附件 -> Artifact 驱动流转

InternAgents 重视 PDF、图片、文本和附件预览。PolyAgent 的材料研发场景更需要完整产物预览。

建议能力：

- 在 AlgorithmRun、ComputationRun、ResearchRun trace 和报告任务详情中统一预览 artifact。
- 支持 PDF、Markdown、CSV、JSON、图片、谱图、SDF/XYZ、日志文件的安全预览和下载。
- 文件可作为下游算法输入，形成“从产物到下一步”的操作入口。
- 上传附件时要求选择用途：文献、实验数据、结构文件、模型资源、报告材料或其它。
- 预览层只展示安全元数据，不暴露 object key、storage URI、secret ref 或 embedding。

产品收益：

- 用户可以在同一个研发链路中检查证据、数据和结果。
- 下游复用不再依赖手工下载和重新上传。
- 报告生成可以更稳定地收集上下文。

### 3.7 配置页 -> 能力与授权中心

InternAgents 的配置页统一管理模型、工作区、授权模式、技能和界面风格。PolyAgent 当前已有 LLM 模型管理、工具服务和集成状态，应整合为更面向用户的能力与授权中心。

建议能力：

- 统一展示 LLM provider、Knowledge Base、ComputeEngine、SpecLabOS、垂类算法、报告渲染器和外部执行器状态。
- 将配置状态翻译成用户可理解的能力状态，例如“可生成报告”“只能使用证据摘要”“ORCA 当前为 fixture”。
- 提供授权策略：自动执行安全读操作、写入/提交需审批、全部关键动作需审批。
- 管理员视角保留 secret refs 和服务健康检查；普通用户只看到能力是否可用和原因。

产品收益：

- 降低用户对后端配置的理解成本。
- 提前暴露不可用原因，减少运行中失败。
- 支撑不同团队、不同部署环境下的能力差异。

### 3.8 新手导览与任务模板

InternAgents 通过快速导览和任务教程降低第一次使用门槛。PolyAgent 模块更多，更需要角色化模板。

建议能力：

- 提供角色化入口：材料科学家、算法工程师、实验员、平台管理员。
- 提供任务模板：创建 ProblemSpec、上传算法包、启动 AutoResearch 示例、导入实验数据、生成报告。
- 模板不只显示说明文字，而是直接预填表单或创建草稿。
- 新手导览只覆盖当前角色的主路径，避免一次解释所有模块。

产品收益：

- 降低首次使用成本。
- 让平台主路径更明确。
- 对演示、培训和合作者交付更友好。

## 4. 分期路线

### P0：先补可用性闭环

目标：在不重构架构的前提下，把 InternAgents 最有效的交互模式落到现有对象上。

- 建立项目会话：会话绑定 ProblemSpec / ResearchRun / AlgorithmRun，并支持标题、归档和从详情页带上下文打开助手。
- 建立统一 Action Card：优先覆盖 AutoResearch Gate、报告生成、算法部署和外部计算提交。
- 建立 artifact 预览与下游复用入口：优先覆盖 ResearchEngine trace、ComputationRun、AlgorithmRun 和 ReportJob。
- 更新任务中心：突出待审批、长任务进度、当前阻塞点和下一步动作。

### P1：打通长任务和能力中心

目标：让助手、任务中心、ResearchEngine 和服务配置形成一个连续研发工作流。

- 新增 Research Goal：从助手或 ResearchEngine 创建长任务目标，并映射到 StageRun / AlgorithmRun / ReportJob。
- 能力与授权中心：统一展示模型、知识库、计算引擎、算法包、报告能力和审批策略。
- 领域能力包：把 AlgorithmRegistry、adapter、知识库 corpus、报告 skill pipeline 和来源标注聚合展示。
- 对话动作增强：助手可以创建草稿、打开审批、复用 artifact、启动报告生成，但所有关键写入经过 Action Card。

### P2：做成可规模化协作工作台

目标：服务多项目、多团队、多算法贡献者的长期使用。

- Workspace Asset 体系完善：支持项目归档、权限、批量导入、批量导出和复用统计。
- 贡献与 credit 统计：按算法、数据、知识库、报告和运行复用记录贡献。
- 角色化导览和模板库：按材料科学家、算法工程师、实验员、管理员提供不同起始路径。
- 远程 Agent / 外部执行器策略：仅在管理员明确配置后开放，不让普通用户直接接触 SSH、secret 或底层执行命令。

## 5. 验收标准

P0 验收建议：

1. 用户从 ResearchEngine 某个 ProblemSpec 打开助手，助手能识别当前任务并给出相关动作。
2. 任务中心能清楚筛出待审批任务，并从列表进入统一审批卡。
3. AutoResearch Gate、报告生成、算法部署至少三类动作使用同一种 Action Card 交互模型。
4. AlgorithmRun / ComputationRun / ReportJob 的主要 artifact 能预览、下载，并能作为下一步输入入口。
5. 所有批准、拒绝、编辑参数、执行失败都进入审计追溯。

P1 验收建议：

1. 用户能创建一个 Research Goal，并在任务中心看到阶段进度和阻塞点。
2. 能力中心能展示 LLM、Knowledge Base、ComputeEngine、垂类算法和报告生成的真实可用状态。
3. 领域能力包能说明适用材料体系、触发方式、来源、依赖服务和当前运行状态。
4. 助手发起的关键动作不会直接执行，而是生成可审查的 Action Card。

## 6. 边界与不做事项

1. 不把 PolyAgent 改成通用文件 Agent 或通用代码 Agent；所有设计应服务材料研发任务。
2. 不复制 InternAgents 的桌面工作区模型；PolyAgent 的工作区应是平台内 Project Workspace 和受控资产体系。
3. 不让浏览器直接暴露 SSH、API key、object key、storage URI 或底层执行命令。
4. 不把 mock/fallback 能力包装成真实生产能力；能力中心必须明确状态。
5. P0 不新增复杂权限系统，只在现有认证、任务、审计和集成配置上做可用性增强。

## 7. 推荐产品口径

PolyAgent 可以借鉴 InternAgents 的工作台体验，但定位应更明确：

> PolyAgent 是面向高分子材料研发的智能协作工作台。它把文献、数据、算法、计算、实验建议、审批和报告组织到同一个研发项目空间中，让材料科学家和算法工程师围绕可追溯的 ProblemSpec 持续推进研发闭环。

