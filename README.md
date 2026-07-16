# Poly Agent — 高分子智能分析平台

**Poly Agent** 是 AI4MS 门户下的高分子材料智能研发平台，与 [Spec Agent](https://github.com/SynlysAI/Spec_Agent) 同属一个产品线。平台围绕高分子材料研发场景，提供实验设计与贝叶斯优化（Alchemist）、计算智能任务管理（ComputeEngine）、AI 驱动材料研发引擎（ResearchEngine）、垂类预测模型管理、文献知识库 RAG + 知识图谱、智能报告生成和产品内助手，帮助材料科学家系统化地定义研发任务、管理计算任务、编排算法工作流并追踪优化闭环。

## 功能概览

### 1. Alchemist — 实验设计与贝叶斯优化（内置）

基于贝叶斯优化（主动学习）的实验设计工具，用尽量少的实验次数找到最优实验条件。已从独立服务迁移为 Poly Agent 内置模块，无需额外部署。完整 6 步闭环流程：

| 步骤 | 能力 |
|------|------|
| 变量定义 | 支持连续实值、整数、分类、离散值四种变量类型 |
| 实验设计 (DoE) | 11 种设计方法：LHS、Sobol、全/部分因子、CCD、Box-Behnken、Plackett-Burman 等；支持 OED 最优设计（D/A/I-optimal） |
| 实验数据 | CSV 导入、手动录入、设计矩阵回填，统计摘要展示 |
| GP 建模 | 高斯过程代理模型，支持 Matern/RBF/IBNN 核函数，scikit-learn/BoTorch 后端 |
| 采集优化 | EI/PI/UCB/qEI/qUCB 采集策略，批量推荐下一轮实验，闭环迭代 |
| 可视化诊断 | Parity 图、CV 指标曲线、Q-Q 图、校准曲线、等值线图、超参数展示 |

支持 LLM 辅助实验条件建议和效应项推荐，Session 持久化管理优化项目。

> 详细操作流程见 [doc/optimization-workflow-user-guide.md](doc/optimization-workflow-user-guide.md)

### 2. ComputeEngine — 计算智能模块

可演示的计算智能闭环系统，支持计算任务提交、worker 执行、产物管理和优化 campaign。

| 能力 | 说明 |
|------|------|
| 计算任务管理 | 创建/列表/详情/取消/重试，支持 workflow/engine 白名单校验 |
| 多引擎适配 | Mock、Local Structure (RDKit/OpenBabel)、Local xTB、ORCA ComputeEngine Laser (fixture) |
| Worker 执行模型 | 原子领取 queued run、初始化 timeline、调用 adapter、统一落库、heartbeat、stale reclaim |
| Artifact 资产 | 自动登记产物（structure/xyz/sdf/spectrum/log 等），支持预览和下载 |
| Campaign 优化 | 创建 campaign、导入候选、planner 生成 suggestion、自动 observation 回填、下一轮推荐 |
| 集成状态 | 管理 service integration 配置、secret refs，手动 check 并回写状态 |
| Stale Run 回收 | 后台 reaper 定时扫描心跳超时的 running 任务，自动标记为 failed |
| Demo 兜底 | MongoDB 不可用时自动回退本地 JSON store |

> 当前进度：MVP 约 92-95% 完成，主流程跑通。详见 [doc/compute-engine-computation-progress-and-plan.md](doc/compute-engine-computation-progress-and-plan.md)

### 3. ResearchEngine — 高分子材料 AI 研发引擎

面向高分子材料研发场景的 P0 双通道研发框架，围绕统一的 ProblemSpec 组织人工算法 Workflow 和 AutoResearch 自动编排。

| 能力 | 说明 |
|------|------|
| ProblemSpec | 定义材料体系、问题类型、变量、目标、约束、测量条件和可选执行模式；创建时可自动关联容器 campaign |
| ExecutionDecision | 在同一个 ProblemSpec 下显式选择 `manual_workbench` 或 `autoresearch` |
| AlgorithmRegistry | 登记计算适配器、生产候选适配器和演示 mock 算法，支持按类型、算法族、材料范围、触发方式和状态过滤 |
| 人工 Workflow | 编排 ManualAlgorithmWorkflow，启动 WorkflowRun，并为每个步骤生成 AlgorithmRun、输入快照、输出摘要、artifact 和审计事件 |
| Pipeline Run | 支持多阶段流水线运行，串联多个算法步骤并追踪阶段状态 |
| AutoResearch | 创建 ResearchRun，按 10 阶段材料研发序列推进，在 P0 Gate 阶段进入 `blocked_approval` 等待人工批准或拒绝 |
| 报告生成 | 集成智能报告系统，支持多 LLM 提供商（OpenAI、Ollama、Edison、Codex、自定义 HTTP）、多渲染器（HTML、LaTeX、Markdown、PDF）和可扩展技能框架 |
| 示例流程 | 支持一键实例化人工计算 Workflow 示例和 AutoResearch 审批示例 |
| 追溯与审计 | 提供 ResearchRun / StageRun / AlgorithmRun traceability API，聚合运行记录、产物、关联计算任务和审计事件 |

当前可直接复用现有 ComputationService 的 `LOCAL_STRUCTURE`、`LOCAL_XTB`、`ORCA_COMPUTE_ENGINE_LASER` workflow；文献 RAG 已通过 `services/literature-rag/` 独立服务接入，垂类预测和 MOBO Alchemist 适配器仍依赖外部服务配置。mock 算法仅用于演示和闭环验收，不代表真实生产模型。

> 操作指南见 [doc/autoresearch-user-guide.md](doc/autoresearch-user-guide.md)，P0 进度与边界见 [doc/research-engine-progress-and-plan.md](doc/research-engine-progress-and-plan.md)，设计方案见 [doc/research-engine-and-auto-research-design.md](doc/research-engine-and-auto-research-design.md)

### 4. 垂类预测 — 算法模型管理

面向高分子材料特定应用场景的预测模型管理模块，支持算法包上传、测试、运行历史追踪和结果查看。

| 能力 | 说明 |
|------|------|
| 算法包管理 | 上传、注册、版本管理算法包（支持 .zip/.tar.gz 打包格式），自动解析算法元信息 |
| 算法测试 | 在线测试已注册算法，输入测试数据并查看预测结果 |
| 运行历史 | 追踪算法运行记录，查看历史输入/输出和性能指标 |
| 算法清单 | 展示已注册算法目录，支持按类型、状态筛选 |
| 结果查看 | 可视化展示算法预测结果，支持多维度数据呈现 |

> 详见 [doc/algorithm-upload-user-guide.md](doc/algorithm-upload-user-guide.md) 和 [doc/algorithm-upload-p0-assessment-and-roadmap.md](doc/algorithm-upload-p0-assessment-and-roadmap.md)

### 5. Knowledge Base — 文献 RAG + 知识图谱

知识库工作台通过 Poly Agent 后端统一接入 `services/literature-rag/` 独立服务，当前默认 KrF 248 nm 光刻胶文献库。

| 能力 | 说明 |
|------|------|
| 文献问答 | 支持知识增强检索问答、流式返回证据和回答；无 LLM 时返回可追溯证据摘要 |
| 中文检索 | 对 KrF、光刻胶、文献/论文/文档等中英文混合查询做领域词扩展 |
| 文档清单 | 支持"列出全部文档/文献/论文"类问题，返回已索引文献清单 |
| 知识图谱 | Neo4j 图存储，支持子图优先级排序和语料库统计；memory demo 返回论文-片段子图 |
| 安全边界 | API 只返回安全元数据，不暴露 API key、object key、storage URI 或 embedding |

> 独立服务说明见 [services/literature-rag/README.md](services/literature-rag/README.md)，产品设计见 [doc/knowledge-base-rag-kg-product-design.md](doc/knowledge-base-rag-kg-product-design.md)

### 6. 数据管理 — Data Catalog

统一的数据目录管理模块，支持材料研发数据的浏览、检索和管理。

| 能力 | 说明 |
|------|------|
| 数据目录 | 浏览和检索平台内注册的数据集 |
| 数据浏览 | 按分类、标签筛选数据资源 |

### 7. 基础功能

- **认证体系**：与 AI4MS 门户共享账户体系，HMAC-SHA256 令牌 + 邀请码注册，支持门户 SSO 免登录
- **产品内助手**：`/assistant/chat` 基于项目实时事实回答入口、算法清单、计算任务和 AutoResearch 审批问题，并返回结构化跳转动作
- **LLM 模型管理**：`/llm/models` 提供 Codex 风格模型选择数据，支持科研问答、深度思考和报告生成的默认模型路由
- **任务中心**：全局任务视图，跨模块追踪计算任务、优化任务和算法运行状态
- **工具服务**：集成状态监控，支持外部服务（ComputeEngine、SpecLabOS 等）配置和健康检查
- **数据库管理**：管理员面板，管理用户、邀请码和数据

## 项目状态

| 模块 | 状态 | 完成度 |
|------|------|--------|
| Alchemist 实验设计与优化 | ✅ MVP 完成 | ~95% |
| ComputeEngine 计算智能 | ✅ MVP 基本完成 | ~92-95% |
| ResearchEngine | ✅ P0 已完成 / ⚠️ 有已知测试缺口 | 双通道闭环、前端工作台、追溯、报告生成和示例流程可用 |
| 垂类预测 | ✅ 基础可用 | 算法包上传、测试、运行历史追踪已集成 |
| Knowledge Base 文献 RAG + 图谱 | ✅ 独立服务已接入 | KrF memory demo 可用；production 接 MongoDB/MinIO/Neo4j |
| 数据管理 Data Catalog | ✅ 基础可用 | 数据目录浏览和检索 |
| 认证与基础功能 | ✅ 完成 | ~95% |
| 产品内助手 | ✅ 基础可用 | 基于项目事实的入口引导、审批引导和算法说明 |
| 真实外部系统接入 (ORCA/HPC/SpecLabOS) | 📋 规划中 | 后续阶段 |

当前版本已适合作为"计算智能 + ResearchEngine P0 双通道闭环"的演示和继续迭代基线。下一步重点：
- 真实 ORCA/HPC/AiiDA executor 接入
- SpecLabOS 真实实验系统对接
- ResearchEngine P1：Schema 驱动算法表单、AlgorithmRegistry 管理、checkpoint/rerun 语义和真实算法服务接入
- 生产级 worker 运维和持久化

当前后端 ResearchEngine/assistant 相关测试存在 2 个已知失败用例，详见 [doc/research-engine-progress-and-plan.md](doc/research-engine-progress-and-plan.md) 的"当前已知测试失败"。

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12 + FastAPI + MongoDB |
| 前端 | Vue 3 + Element Plus + Vite |
| 计算引擎 | RDKit, OpenBabel, xTB, ORCA (fixture), BoTorch, scikit-learn |
| 文献知识库 | FastAPI 独立服务；memory demo；production 支持 MongoDB + MinIO + Neo4j |
| 报告生成 | 多 LLM 提供商（OpenAI/Ollama/Edison/Codex/自定义 HTTP）+ 多格式渲染（HTML/LaTeX/Markdown/PDF） |
| 认证 | HMAC-SHA256 令牌，与 AI4MS 门户共享账户体系 |
| 设计系统 | Inter 字体族 + 深蓝侧边栏 + 浅蓝灰背景，详见 [DESIGN.md](DESIGN.md) |
| 部署 | PM2, Conda |

## 技术架构图

![Poly Agent 技术架构图](docs/poly-agent-technical-architecture.svg)

## 项目结构

```text
Poly_Agent/
├── backend/
│   ├── app/
│   │   ├── api/v1/                    # API 路由
│   │   │   └── endpoints/             # health, auth, admin, optimization, computations,
│   │   │                              #   integrations, llm, alchemist, knowledge,
│   │   │                              #   research_engine, assistant, reports, tasks, data_catalog
│   │   ├── alchemist_core/            # 实验设计核心库
│   │   │   ├── acquisition/           #   采集函数 (EI/PI/UCB/qEI/qUCB, skopt/BoTorch)
│   │   │   ├── data/                  #   实验数据管理与搜索空间定义
│   │   │   ├── models/                #   GP 代理模型 (scikit-learn/BoTorch, Matern/RBF/IBNN)
│   │   │   ├── utils/                 #   实验设计方法 (LHS/Sobol/因子设计/OED) 与工具
│   │   │   ├── visualization/         #   诊断可视化 (Parity/CV/Q-Q/等值线/校准曲线)
│   │   │   ├── session.py             #   Session 持久化管理
│   │   │   ├── events.py              #   事件系统
│   │   │   └── audit_log.py           #   审计日志
│   │   ├── computation_adapters/      # 计算引擎适配器
│   │   │   ├── base.py                #   adapter 协议
│   │   │   ├── registry.py            #   统一派发
│   │   │   ├── local_structure.py     #   RDKit/OpenBabel 结构生成
│   │   │   ├── local_xtb.py           #   xTB 计算
│   │   │   └── orca_compute_engine_laser.py  # ORCA ComputeEngine Laser
│   │   ├── core/                      # 配置、令牌认证、日志、LLM 客户端、时间工具
│   │   ├── infra/                     # MongoDB 连接、数据仓储、demo store
│   │   ├── schemas/                   # Pydantic 数据模型
│   │   │   ├── alchemist.py           #   Alchemist 相关 schema
│   │   │   ├── computation.py         #   计算任务 schema
│   │   │   ├── research_engine.py     #   ResearchEngine schema
│   │   │   ├── knowledge.py           #   知识库 schema
│   │   │   ├── optimization.py        #   优化 schema
│   │   │   ├── reports.py             #   报告生成 schema
│   │   │   ├── tasks.py               #   任务中心 schema
│   │   │   ├── data_catalog.py        #   数据目录 schema
│   │   │   ├── admin.py               #   管理 schema
│   │   │   ├── auth.py                #   认证 schema
│   │   │   ├── integrations.py        #   集成 schema
│   │   │   ├── identity_runtime.py    #   身份运行时 schema
│   │   │   └── common.py              #   通用 schema
│   │   ├── services/                  # 业务逻辑
│   │   │   ├── alchemist_service.py           #   Alchemist 实验设计服务
│   │   │   ├── alchemist_llm_service.py       #   Alchemist LLM 辅助服务
│   │   │   ├── alchemist_providers/           #   LLM 提供商适配 (OpenAI/Ollama/Edison)
│   │   │   ├── computation_service.py         #   计算任务管理服务
│   │   │   ├── optimization_service.py        #   优化 campaign 服务
│   │   │   ├── planner_adapters.py            #   Planner 适配器
│   │   │   ├── research_engine_service.py             #   ResearchEngine 核心服务
│   │   │   ├── research_engine_orchestrator.py        #   AutoResearch 编排器
│   │   │   ├── research_engine_algorithm_runner.py    #   算法运行器
│   │   │   ├── research_engine_algorithm_package_service.py  # 算法包管理
│   │   │   ├── research_engine_access.py               #   ResearchEngine 访问控制
│   │   │   ├── research_engine_defaults.py             #   ResearchEngine 默认配置
│   │   │   ├── research_engine_readiness_service.py    #   ResearchEngine 就绪检查
│   │   │   ├── algorithm_runtimes/             #   算法运行时 (本地进程/沙箱)
│   │   │   ├── knowledge_service.py            #   知识库服务
│   │   │   ├── auth_service.py                 #   认证服务
│   │   │   ├── integration_config_service.py   #   集成配置服务
│   │   │   ├── integration_status_service.py   #   集成状态服务
│   │   │   ├── data_catalog_service.py         #   数据目录服务
│   │   │   ├── task_center_service.py          #   任务中心服务
│   │   │   ├── report_service.py               #   报告生成服务
│   │   │   ├── report_context_service.py       #   报告上下文服务
│   │   │   ├── report_skill_orchestrator.py    #   报告技能编排器
│   │   │   ├── report_providers/               #   报告 LLM 提供商 (OpenAI/Ollama/Codex/自定义HTTP/mock)
│   │   │   ├── report_renderers/               #   报告渲染器 (HTML/LaTeX/Markdown/PDF)
│   │   │   └── report_skills/                  #   报告技能插件
│   │   ├── workers/                   # computation worker (原子领取、执行、落库)
│   │   └── main.py                    # FastAPI 入口 (托管前端静态文件, SPA 路由回退, stale-run reaper)
│   ├── tests/
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/                       # Axios 客户端与 API 调用
│   │   ├── auth/                      # 认证状态管理 + 门户 SSO
│   │   ├── router/                    # 路由配置 + 导航守卫
│   │   ├── views/
│   │   │   ├── DashboardView.vue              # 工作台
│   │   │   ├── TaskSubmitView.vue             # 性能预测任务提交
│   │   │   ├── TaskCenterView.vue             # 全局任务中心
│   │   │   ├── OptimizationHomeView.vue       # Alchemist 优化工作台
│   │   │   ├── AlchemistToolView.vue          # Alchemist 工具入口
│   │   │   ├── ComputationSubmitView.vue      # 计算任务提交
│   │   │   ├── ComputationRunsView.vue        # 计算任务列表
│   │   │   ├── CampaignsView.vue              # 优化 Campaign 列表
│   │   │   ├── CampaignDetailView.vue         # Campaign 详情
│   │   │   ├── ResearchEngineView.vue         # ResearchEngine 双通道工作台
│   │   │   ├── VerticalPredictionView.vue     # 垂类预测模型管理
│   │   │   ├── KnowledgeBaseView.vue          # 文献 RAG + 知识图谱工作台
│   │   │   ├── DataCatalogView.vue            # 数据目录管理
│   │   │   ├── DialogueView.vue               # 问答对话
│   │   │   ├── ToolServicesView.vue           # 工具服务集成管理
│   │   │   ├── DatabaseManagementView.vue     # 数据库管理 (管理员)
│   │   │   ├── LoginView.vue / RegisterView.vue  # 登录/注册
│   │   │   ├── NotFoundView.vue               # 404 页面
│   │   │   ├── alchemist/                     # Alchemist 子面板
│   │   │   │   ├── VariablePanel.vue          #   变量定义
│   │   │   │   ├── ExperimentPanel.vue        #   实验设计 (DoE)
│   │   │   │   ├── OptimalDesignPanel.vue     #   最优设计 (OED)
│   │   │   │   ├── ExperimentDataPanel.vue    #   实验数据管理
│   │   │   │   ├── ModelPanel.vue             #   GP 代理建模
│   │   │   │   ├── AcquisitionPanel.vue       #   采集函数优化
│   │   │   │   ├── VisualizationPanel.vue     #   诊断可视化
│   │   │   │   └── components/                #   子组件 (LLM 配置等)
│   │   │   ├── research-engine/               # ResearchEngine 子面板
│   │   │   │   ├── ProblemSpecPanel.vue       #   ProblemSpec 管理
│   │   │   │   ├── AlgorithmRegistryPanel.vue #   算法注册表
│   │   │   │   ├── AlgorithmRunPanel.vue      #   算法运行记录
│   │   │   │   ├── AlgorithmRunDetail.vue     #   算法运行详情
│   │   │   │   ├── PipelineRunPanel.vue       #   流水线运行管理
│   │   │   │   ├── ResearchRunPanel.vue       #   AutoResearch 运行
│   │   │   │   ├── GateReviewDialog.vue       #   Gate 审批对话框
│   │   │   │   ├── ReportGenerateDrawer.vue   #   报告生成抽屉
│   │   │   │   └── ReportJobPanel.vue         #   报告任务面板
│   │   │   └── vertical-prediction/           # 垂类预测子面板
│   │   │       ├── AlgorithmManagementPanel.vue   #   算法管理
│   │   │       ├── AlgorithmUploadPanel.vue       #   算法包上传
│   │   │       ├── AlgorithmTestPanel.vue         #   算法测试
│   │   │       ├── AlgorithmRunHistoryPanel.vue   #   运行历史
│   │   │       └── AlgorithmResultView.vue        #   结果查看
│   │   ├── App.vue                      # 主布局 (侧边栏 + 顶栏)
│   │   ├── style.css                    # 全局样式
│   │   └── main.js
│   ├── public/brand/                    # 品牌 Logo
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── doc/                                 # 文档
│   ├── optimization-workflow-user-guide.md              # Alchemist 操作流程
│   ├── computation-workflows-user-guide.md              # 计算工作流用户指南
│   ├── compute-engine-computation-product-prd.md        # ComputeEngine 产品需求文档
│   ├── compute-engine-computation-product-design.md     # ComputeEngine 产品设计
│   ├── compute-engine-computation-migration-design.md   # ComputeEngine 迁移设计
│   ├── compute-engine-computation-progress-and-plan.md  # ComputeEngine 进度与计划
│   ├── autoresearch-user-guide.md                       # AutoResearch 使用指南
│   ├── research-engine-and-auto-research-design.md      # ResearchEngine 技术方案
│   ├── research-engine-progress-and-plan.md             # ResearchEngine P0 进度与验收
│   ├── research-engine-plan-00-roadmap.md               # ResearchEngine 实施路线图
│   ├── research-engine-plan-01~06-*.md                  # ResearchEngine 各阶段计划
│   ├── research-report-generation-product-design.md     # 报告生成产品设计
│   ├── knowledge-base-rag-kg-product-design.md          # 知识库 RAG + 图谱产品设计
│   ├── knowledge-base-rag-kg-upgrade-plan.md            # 知识库升级计划
│   ├── literature-rag-service-design.md                 # 文献 RAG 服务设计
│   ├── algorithm-upload-user-guide.md                   # 算法包上传使用指南
│   ├── algorithm-upload-p0-assessment-and-roadmap.md    # 算法包上传评估与路线图
│   └── poly-agent-toolchain-deployment-pack.md          # 工具链部署包
├── services/
│   └── literature-rag/                  # 独立文献 RAG / GraphRAG 服务
├── scripts/                             # 部署与运维脚本
│   ├── setup_poly_agent_env.sh          #   Conda 环境初始化
│   ├── restart_poly_agent_services.sh   #   重启前后端服务
│   ├── stop_poly_agent_services.sh      #   停止前后端服务
│   ├── run_compute_engine.sh            #   启动计算引擎 worker
│   ├── pack_algorithm.py                #   算法包打包工具
│   └── rename_minio_poly_agent_objects.py  # MinIO 对象重命名
├── deploy/                              # 部署配置
│   └── toolchain/                       #   工具链部署
│       ├── manifest.yml                 #     部署清单
│       ├── env/backend.env.template     #     环境变量模板
│       └── scripts/                     #     部署脚本 (bootstrap, MongoDB, Conda, Alchemist, 验证)
├── DESIGN.md                            # 前端设计规范 (Inter 字体族 + 深蓝侧边栏科研风格)
├── ecosystem.config.js                  # PM2 部署配置
└── environment.yml                      # Conda 环境定义
```

## 快速开始

### 1. 环境准备

```bash
# 一次性创建 / 更新项目 conda 环境（Python 3.12 + Node.js 22）
bash scripts/setup_poly_agent_env.sh

# 手动激活环境
conda activate poly_agent
```

### 2. 配置环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 .env，配置 MongoDB 连接信息和 AUTH_SECRET（与 AI4MS 保持一致）
```

### 3. 开发模式

```bash
# 推荐：一条命令重启前后端
bash scripts/restart_poly_agent_services.sh

# 停止前后端
bash scripts/stop_poly_agent_services.sh
```

默认开发端口：

- 前端：`http://127.0.0.1:5200`
- 后端：`http://127.0.0.1:5201`

前端开发服务器会自动把 `/api` 和 `/static` 代理到后端。

知识库功能需要独立 Literature RAG 服务。开发环境可单独启动 memory demo：

```bash
export LITERATURE_RAG_QUERY_API_KEY=query-demo
export LITERATURE_RAG_ADMIN_API_KEY=admin-demo
python -m uvicorn app.main:app --app-dir services/literature-rag --host 127.0.0.1 --port 8200
```

Poly Agent 后端在本地 `APP_ENV=dev` 时会自动探测 `127.0.0.1:8200`；生产环境请显式配置 `LITERATURE_RAG_BASE_URL` 和 `LITERATURE_RAG_QUERY_API_KEY`。

### 4. 生产部署

```bash
# 准备环境文件
cp deploy/toolchain/env/backend.env.template backend/.env
cp deploy/toolchain/env/literature-rag.env.template services/literature-rag/.env

# 构建前端
npm --prefix frontend run build

# 启动主后端和独立知识库实例
pm2 start ecosystem.config.js
pm2 start services/literature-rag/ecosystem.config.js
pm2 save
```

生产模式下直接访问 `http://<host>:5201` 即可，后端自动提供前端 SPA 页面。  
知识库服务独立运行，Poly Agent 只连接本次部署的专用 `literature-rag` 实例，不改动共享焊接/稀土/表面处理数据。

## 认证体系

- 与 AI4MS 门户共享 `ai4ms` 认证数据库中的 `users` 和 `invite_codes` 集合
- 支持从已登录的 AI4MS 门户通过 URL hash 传递 token 实现免登录（SSO）
- 管理员通过邀请码控制用户注册
- 通过 `AUTH_ENABLED` 环境变量可切换是否需要登录

## 相关项目

- [AI4MS](https://github.com/SynlysAI/AI4MS) — 高分子智能研发门户
- [Spec Agent](https://github.com/SynlysAI/Spec_Agent) — 谱图智能分析平台
