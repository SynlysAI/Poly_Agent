# Poly Agent — 高分子智能分析平台

**Poly Agent** 是 AI4MS 门户下的高分子材料智能研发平台，与 [Spec Agent](https://github.com/SynlysAI/Spec_Agent) 同属一个产品线。平台围绕高分子材料研发场景，提供实验设计与贝叶斯优化（Alchemist）、计算智能任务管理（ComputeEngine）、AI 驱动材料研发引擎（ResearchEngine）、垂类预测模型管理、文献知识库 RAG + 知识图谱、智能报告生成和产品内助手，帮助材料科学家系统化地定义研发任务、管理计算任务、编排算法工作流并追踪优化闭环。

当前版本适合作为“计算智能 + ResearchEngine P0 双通道闭环”的演示和继续迭代基线。真实 ORCA/HPC/AiiDA、SpecLabOS 设备提交和生产级外部模型服务仍按集成配置逐步接入；未配置真实依赖时，系统会使用受控 demo store、mock、fixture 或 fallback 路径支撑本地验收。

## 功能概览

| 模块 | 当前入口 | 当前能力 |
|------|----------|----------|
| Alchemist | `/optimization`、`/optimization/alchemist`、`/tools/alchemist` | 实验变量、DoE/OED、实验数据、GP 建模、采集优化和诊断可视化 |
| ComputeEngine | `/computations/submit`、`/computations/runs`、`/optimization/campaigns` | 计算任务提交、worker 执行、artifact 管理、campaign 优化和集成状态 |
| ResearchEngine | `/research-engine` | ProblemSpec、人工算法 Workflow、Pipeline Run、AutoResearch Gate、追溯和报告生成 |
| 垂类预测 | `/vertical-prediction` | 算法包上传、治理、在线测试、运行历史、结果查看和 handoff |
| Knowledge Base | `/knowledge` | WeKnora 知识库问答、证据清单和 Neo4j 增强检索子图 |
| Data Catalog | `/database/data-catalog`、`/data-catalog` | 材料数据资产浏览、检索和外部数据源只读接入 |
| 基础工作台 | `/dashboard`、`/tasks/submit`、`/tasks/center`、`/dialogue`、`/tools`、`/admin` | 统一任务中心、产品内助手、LLM 模型选择和工具服务配置 |

完整文档入口见 [doc/README.md](doc/README.md)。

## 框架、方法与机构来源

Poly Agent 在产品页面中维护统一的来源与引用标注。系统模块首屏会显示参考框架、方法来源和机构来源；算法卡片、垂类模型详情和预测结果会显示开发者来源。若机构 Logo 有明确授权或随算法包提交，则以右侧 Logo 卡片展示；否则使用文字来源牌，不伪造 Logo。

| 模块 | 主要来源标注 | Poly Agent 实现边界 |
|------|--------------|---------------------|
| ResearchEngine / 计算编排 | ChemOS 2.0，University of Toronto / Aspuru-Guzik Group | 仅标注为编排思想和系统架构参考；ProblemSpec、Workflow、AlgorithmRun、Gate 和追溯为本项目实现 |
| 湿实验优化 / Alchemist | NatLabRockies / NREL / NLR ALchemist | 实验设计、GP 建模、采集优化方法标注 ALchemist；Poly Agent 负责认证、会话、中文工作台和平台集成 |
| ComputeEngine | RDKit、OpenBabel、xTB、CREST、ORCA | Poly Agent 负责任务、worker、artifact、审计和 campaign 联动；具体计算能力来自本地依赖 |
| 垂类预测模型 | 算法包开发者、开发机构、来源链接和引用 | 平台治理上传、校验、部署和运行记录；模型方法与开发者来源来自算法契约 |
| 文献知识库 | Tencent WeKnora 与 PolyAgent KnowledgeService | 查询、证据、图谱上下文和语料来源按 WeKnora 服务契约追溯 |

完整矩阵见 [doc/polyagent-attribution-source-matrix.md](doc/polyagent-attribution-source-matrix.md)。

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

当前可直接复用现有 ComputationService 的 `LOCAL_STRUCTURE`、`LOCAL_XTB`、`ORCA_COMPUTE_ENGINE_LASER` workflow；知识库检索与问答已通过 WeKnora 服务接入，垂类预测和 MOBO Alchemist 适配器仍依赖外部服务配置。mock 算法仅用于演示和闭环验收，不代表真实生产模型。

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

### 5. Knowledge Base — WeKnora 知识库问答 + Neo4j 增强检索子图

知识库工作台通过 Poly Agent 后端统一接入 WeKnora 服务。前端和 ResearchEngine 继续调用本项目稳定的 `/api/v1/knowledge-bases/*` API，由 `KnowledgeService` 负责转发 WeKnora 知识库列表、知识问答、流式事件和无总结检索。

| 能力 | 说明 |
|------|------|
| 文献问答 | 通过 WeKnora `knowledge-chat` 会话接口执行知识增强问答，支持流式返回证据和回答 |
| 知识库列表 | 通过 WeKnora `knowledge-bases` 接口获取可查询知识库，并映射为 Poly Agent 知识库体系 |
| 证据检索 | 通过 WeKnora `knowledge-search` 获取命中文档和片段，保持前端证据卡片与引用结构稳定 |
| 检索子图 | 基于 WeKnora 检索结果合成 Paper/Chunk 子图；配置 `WEKNORA_NEO4J_*` 后会从 WeKnora Neo4j 图库补充 Entity 与实体关系 |
| 安全边界 | API 只返回安全元数据，不暴露 API key、object key、storage URI 或 embedding |

> 产品设计见 [doc/knowledge-base-rag-kg-product-design.md](doc/knowledge-base-rag-kg-product-design.md)，来源标注见 [doc/polyagent-attribution-source-matrix.md](doc/polyagent-attribution-source-matrix.md)

### 6. 数据管理 — Data Catalog

统一的数据目录管理模块，支持材料研发数据的浏览、检索和管理。材料数据资产使用 MongoDB `poly_data` 库和 MinIO `polymer-data/datasets/` 路径；`poly_agent` 业务库仅保存计算、算法、报告等运行态数据。

| 能力 | 说明 |
|------|------|
| 数据目录 | 浏览和检索平台内注册的数据集 |
| 数据浏览 | 按分类、标签筛选数据资源 |
| 资产迁移 | `scripts/migrate_poly_data_assets.py` 将旧材料资产迁移到 `poly_data` 和 `datasets/` |

### 7. 基础功能

- **认证体系**：与 AI4MS 门户共享账户体系，HMAC-SHA256 令牌 + 邀请码注册，支持门户 SSO 免登录
- **产品内助手**：前端入口为 `/dialogue`，后端 `/assistant/chat` 基于项目实时事实回答入口、算法清单、计算任务和 AutoResearch 审批问题，并返回结构化跳转动作
- **LLM 模型管理**：`/llm/models` 提供 Codex 风格模型选择数据，支持科研问答、深度思考和报告生成的默认模型路由
- **任务中心**：全局任务视图，跨模块追踪计算任务、优化任务和算法运行状态
- **工具服务**：集成状态监控，支持外部服务（ComputeEngine、SpecLabOS 等）配置和健康检查
- **数据库管理**：管理员面板，管理用户、邀请码和数据

## 项目状态

| 模块 | 状态 | 完成度 |
|------|------|--------|
| Alchemist 实验设计与优化 | ✅ MVP 完成 | ~95% |
| ComputeEngine 计算智能 | ✅ MVP 基本完成 | ~92-95% |
| ResearchEngine | ✅ P0 已完成 / ⚠️ 存在历史测试缺口 | 双通道闭环、前端工作台、追溯、报告生成和示例流程可用 |
| 垂类预测 | ✅ 基础可用 | 算法包上传、测试、运行历史追踪已集成 |
| Knowledge Base 知识库问答 + 检索子图 | ✅ WeKnora 已接入 | 通过 WeKnora API 获取知识库、证据和问答流；可选 Neo4j 图谱增强 |
| 数据管理 Data Catalog | ✅ 基础可用 | 数据目录浏览和检索 |
| 认证与基础功能 | ✅ 完成 | ~95% |
| 产品内助手 | ✅ 基础可用 | 基于项目事实的入口引导、审批引导和算法说明 |
| 真实外部系统接入 (ORCA/HPC/SpecLabOS) | 📋 规划中 | 后续阶段 |

当前版本已适合作为"计算智能 + ResearchEngine P0 双通道闭环"的演示和继续迭代基线。下一步重点：
- 真实 ORCA/HPC/AiiDA executor 接入
- SpecLabOS 真实实验系统对接
- ResearchEngine P1：Schema 驱动算法表单、AlgorithmRegistry 管理、checkpoint/rerun 语义和真实算法服务接入
- 生产级 worker 运维和持久化

ResearchEngine/assistant 相关历史测试状态见 [doc/research-engine-progress-and-plan.md](doc/research-engine-progress-and-plan.md) 的“历史已知测试失败与当前状态”；更新文档前未重新跑全量后端测试。

## 文档导航

项目文档统一放在 [doc/](doc/)；建议先读 [doc/README.md](doc/README.md)：

| 场景 | 推荐文档 |
|------|----------|
| 本地运行和部署 | [快速开始](#快速开始)、[doc/poly-agent-toolchain-deployment-pack.md](doc/poly-agent-toolchain-deployment-pack.md) |
| 计算任务和 campaign | [doc/computation-workflows-user-guide.md](doc/computation-workflows-user-guide.md)、[doc/compute-engine-computation-progress-and-plan.md](doc/compute-engine-computation-progress-and-plan.md) |
| 实验设计与优化 | [doc/optimization-workflow-user-guide.md](doc/optimization-workflow-user-guide.md) |
| ResearchEngine / AutoResearch | [doc/autoresearch-user-guide.md](doc/autoresearch-user-guide.md)、[doc/research-engine-progress-and-plan.md](doc/research-engine-progress-and-plan.md) |
| 算法包上传与垂类模型 | [doc/algorithm-upload-user-guide.md](doc/algorithm-upload-user-guide.md) |
| Raman 结构分析算法包 | [doc/raman_algorithm_package_guide.md](doc/raman_algorithm_package_guide.md)、[doc/raman_structure_analyzer_requirements.md](doc/raman_structure_analyzer_requirements.md) |
| WeKnora 知识库和检索子图 | [doc/knowledge-base-rag-kg-product-design.md](doc/knowledge-base-rag-kg-product-design.md)、[doc/polyagent-attribution-source-matrix.md](doc/polyagent-attribution-source-matrix.md) |
| 来源与引用标注 | [doc/polyagent-attribution-source-matrix.md](doc/polyagent-attribution-source-matrix.md) |

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12 + FastAPI + MongoDB |
| 前端 | Vue 3 + Element Plus + Vite |
| 计算引擎 | RDKit, OpenBabel, xTB, ORCA (fixture), BoTorch, scikit-learn |
| 文献知识库 | Tencent WeKnora API；PolyAgent 后端兼容 `/knowledge-bases/*` API |
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
│   │   │   ├── KnowledgeBaseView.vue          # WeKnora 知识库问答 + 检索子图工作台
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
│   │   │       ├── AlgorithmHandoffPanel.vue      #   算法交付说明
│   │   │       └── AlgorithmResultView.vue        #   结果查看
│   │   ├── App.vue                      # 主布局 (侧边栏 + 顶栏)
│   │   ├── style.css                    # 全局样式
│   │   └── main.js
│   ├── public/brand/                    # 品牌 Logo
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── doc/                                 # 文档
│   ├── README.md                                      # 文档地图
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
│   ├── algorithm-upload-user-guide.md                   # 算法包上传使用指南
│   ├── algorithm-upload-p0-assessment-and-roadmap.md    # 算法包上传评估与路线图
│   ├── raman_algorithm_package_guide.md                 # Raman 结构分析算法包指南
│   ├── raman_structure_analyzer_requirements.md         # Raman 结构分析算法需求
│   └── poly-agent-toolchain-deployment-pack.md          # 工具链部署包
├── examples/
│   └── algorithm_upload/                # 垂类算法包示例
├── scripts/                             # 部署与运维脚本
│   ├── setup_poly_agent_env.sh          #   Conda 环境初始化
│   ├── restart_poly_agent_services.sh   #   重启前后端服务
│   ├── stop_poly_agent_services.sh      #   停止前后端服务
│   ├── run_compute_engine.sh            #   启动 ComputeEngine 参考服务/模拟器
│   ├── pack_algorithm.py                #   算法包打包工具
│   ├── init_mongo_indexes.py            #   生产查询索引初始化
│   ├── update_algorithm_visibility.py   #   上传算法 visibility 回填/修正
│   └── migrate_poly_data_assets.py      #   Poly Data MongoDB/MinIO 资产迁移
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

重启脚本会启动后端、前端和 computation worker；日志默认写入 `/tmp/poly_agent_backend.log`、`/tmp/poly_agent_frontend.log`、`/tmp/poly_agent_worker.log`。前端开发服务器会自动把 `/api` 和 `/static` 代理到后端。

知识库功能需要可访问的 WeKnora 服务，并在 `backend/.env` 配置连接信息：

```bash
WEKNORA_BASE_URL=http://<weknora-host>:8000/api/v1
WEKNORA_API_KEY=<weknora-api-key>
# 可选：指定默认知识库；未配置时前端使用列表中的可用知识库
WEKNORA_DEFAULT_KB_ID=<knowledge-base-id>
# 可选：启用 WeKnora Neo4j 图谱增强；不可用时自动回退检索子图
WEKNORA_NEO4J_URI=bolt://<neo4j-host>:7687
WEKNORA_NEO4J_USERNAME=neo4j
WEKNORA_NEO4J_PASSWORD=<neo4j-password>
WEKNORA_NEO4J_DATABASE=neo4j
```

Poly Agent 知识库能力统一通过 WeKnora API 提供；旧版本地 `literature-rag` 独立服务目录和部署模板已移除。如果 `WEKNORA_BASE_URL` 未包含 `/api/v1`，适配层会自动补齐。

### 4. 常用命令

| 命令 | 说明 |
|------|------|
| `bash scripts/setup_poly_agent_env.sh` | 创建或更新 `poly_agent` Conda 环境，并安装前端依赖 |
| `bash scripts/restart_poly_agent_services.sh` | 重启本地后端、前端和 computation worker |
| `bash scripts/stop_poly_agent_services.sh` | 停止本地开发服务 |
| `make test-backend` | 运行后端 pytest，默认目标为 `backend/tests` |
| `make test-frontend-build` | 运行前端生产构建 |
| `make check-all` | 顺序运行后端测试、前端构建和当前占位 e2e 目标 |
| `make init-mongo-indexes` | 初始化 MongoDB 索引 |
| `npm --prefix frontend run test:llm-models` | 运行前端 LLM 模型配置单测 |
| `python scripts/pack_algorithm.py --help` | 查看垂类算法包打包工具参数 |
| `python scripts/update_algorithm_visibility.py --dry-run` | 预览上传算法 visibility 回填/修正计划；加 `--apply` 才写入 MongoDB |
| `python scripts/restore_polymer_mongo_scope.py` | 预览并清理共享库中的金属合金记录；默认 dry-run，确认快照后再加 `--apply` |

如需单独启动 ComputeEngine 参考服务或模拟器，见：

```bash
bash scripts/run_compute_engine.sh status
bash scripts/run_compute_engine.sh base
```

### 5. 生产部署

```bash
# 准备环境文件
cp deploy/toolchain/env/backend.env.template backend/.env

# 构建前端
npm --prefix frontend run build

# 启动主后端
pm2 start ecosystem.config.js
pm2 save
```

生产模式下直接访问 `http://<host>:5201` 即可，后端自动提供前端 SPA 页面。  
知识库服务由 WeKnora 独立提供，Poly Agent 只通过 WeKnora API 读取知识库列表、问答流和检索结果。

## 配置要点

后端从 `backend/.env` 读取配置，模板见 [backend/.env.example](backend/.env.example)。常用配置按职责分组：

| 配置组 | 关键变量 | 说明 |
|--------|----------|------|
| 运行环境与安全 | `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`CORS_ALLOW_CREDENTIALS` | 非本地环境会强制校验认证、CORS 和密钥安全 |
| 认证 | `AUTH_ENABLED`、`AUTH_SECRET`、`AUTH_MONGODB_URI`、`AUTH_MONGODB_DATABASE` | 支持本地账号和 AI4MS 共享认证库；生产环境必须设置足够长度的 `AUTH_SECRET` |
| 主数据存储 | `MONGODB_HOST`、`MONGODB_PORT`、`MONGODB_DATABASE`、`REQUIRE_MONGODB` | `REQUIRE_MONGODB=false` 时可回退本地 demo store，适合演示，不适合生产 |
| 运行时目录 | `POLY_AGENT_RUNTIME_ROOT`、`POLY_AGENT_UPLOAD_ROOT`、`POLY_AGENT_OUTPUT_ROOT`、`POLY_AGENT_LOG_ROOT` | 控制上传、产物、日志和报告输出位置 |
| 计算工具链 | `XTB_EXECUTABLE`、`CREST_EXECUTABLE`、`ORCA_EXECUTABLE`、`ORCA_EXECUTION_MODE` | 本地 xTB/CREST/ORCA 真实执行依赖这些命令和许可证状态 |
| 算法运行时 | `ALGORITHM_RUNTIME_BACKEND`、`ALGORITHM_RUNTIME_MAX_CONCURRENCY`、`ALGORITHM_RUNTIME_MAX_OUTPUT_BYTES` | 默认使用短生命周期 Python 子进程沙箱运行上传算法 |
| LLM 与报告 | `LLM_*`、`REPORT_*` | 控制产品内助手、Alchemist LLM 辅助和自动报告生成 |
| 知识库 | `WEKNORA_BASE_URL`、`WEKNORA_API_KEY`、`WEKNORA_DEFAULT_KB_ID`、`WEKNORA_NEO4J_*` | 连接 Tencent WeKnora 知识库服务；可选启用 Neo4j 图谱增强 |
| 数据资产 | `DATA_ASSET_MONGODB_URI`、`DATA_ASSET_MONGODB_DATABASE=poly_data`、`MINIO_*` | 数据目录只读资产库和对象存储接入 |

## 认证体系

- 与 AI4MS 门户共享 `ai4ms` 认证数据库中的 `users` 和 `invite_codes` 集合
- 支持从已登录的 AI4MS 门户通过 URL hash 传递 token 实现免登录（SSO）
- 管理员通过邀请码控制用户注册
- 通过 `AUTH_ENABLED` 环境变量可切换是否需要登录

## 相关项目

- [AI4MS](https://github.com/SynlysAI/AI4MS) — 高分子智能研发门户
- [Spec Agent](https://github.com/SynlysAI/Spec_Agent) — 谱图智能分析平台
