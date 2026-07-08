# Poly Agent — 高分子智能分析平台

**Poly Agent** 是 AI4MS 门户下的高分子材料智能研发平台，与 [Spec Agent](https://github.com/SynlysAI/Spec_Agent) 同属一个产品线。平台围绕高分子材料研发场景，提供实验设计与贝叶斯优化（Alchemist）、计算智能任务管理（ComputeEngine Computation）、AI 驱动材料研发引擎（ResearchEngine）和产品内助手，帮助材料科学家系统化地定义研发任务、管理计算任务、编排算法工作流并追踪优化闭环。

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
| AutoResearch | 创建 ResearchRun，按 10 阶段材料研发序列推进，在 P0 Gate 阶段进入 `blocked_approval` 等待人工批准或拒绝 |
| 示例流程 | 支持一键实例化人工计算 Workflow 示例和 AutoResearch 审批示例 |
| 追溯与审计 | 提供 ResearchRun / StageRun / AlgorithmRun traceability API，聚合运行记录、产物、关联计算任务和审计事件 |

当前可直接复用现有 ComputationService 的 `LOCAL_STRUCTURE`、`LOCAL_XTB`、`ORCA_COMPUTE_ENGINE_LASER` workflow；文献 RAG、垂类预测和 MOBO Alchemist 适配器已登记为生产候选能力，但仍依赖外部服务配置。mock 算法仅用于演示和闭环验收，不代表真实生产模型。

> 操作指南见 [doc/autoresearch-user-guide.md](doc/autoresearch-user-guide.md)，P0 进度与边界见 [doc/research-engine-progress-and-plan.md](doc/research-engine-progress-and-plan.md)，设计方案见 [doc/research-engine-and-auto-research-design.md](doc/research-engine-and-auto-research-design.md)

### 4. 基础功能

- **认证体系**：与 AI4MS 门户共享账户体系，HMAC-SHA256 令牌 + 邀请码注册，支持门户 SSO 免登录
- **产品内助手**：`/assistant/chat` 基于项目实时事实回答入口、算法清单、计算任务和 AutoResearch 审批问题，并返回结构化跳转动作
- **工具服务**：集成状态监控，支持外部服务（ComputeEngine、SpecLabOS 等）配置和健康检查
- **数据库管理**：管理员面板，管理用户、邀请码和数据

## 项目状态

| 模块 | 状态 | 完成度 |
|------|------|--------|
| Alchemist 实验设计与优化 | ✅ MVP 完成 | ~95% |
| ComputeEngine 计算智能 | ✅ MVP 基本完成 | ~92-95% |
| ResearchEngine | ✅ P0 已完成 / ⚠️ 有已知测试缺口 | 双通道闭环、前端工作台、追溯和示例流程可用 |
| 认证与基础功能 | ✅ 完成 | ~95% |
| 产品内助手 | ✅ 基础可用 | 基于项目事实的入口引导、审批引导和算法说明 |
| 真实外部系统接入 (ORCA/HPC/SpecLabOS) | 📋 规划中 | 后续阶段 |

当前版本已适合作为"计算智能 + ResearchEngine P0 双通道闭环"的演示和继续迭代基线。下一步重点：
- 真实 ORCA/HPC/AiiDA executor 接入
- SpecLabOS 真实实验系统对接
- ResearchEngine P1：Schema 驱动算法表单、AlgorithmRegistry 管理、checkpoint/rerun 语义和真实算法服务接入
- 生产级 worker 运维和持久化

当前后端 ResearchEngine/assistant 相关测试存在 2 个已知失败用例，详见 [doc/research-engine-progress-and-plan.md](doc/research-engine-progress-and-plan.md) 的“当前已知测试失败”。

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12 + FastAPI + MongoDB |
| 前端 | Vue 3 + Element Plus + Vite |
| 计算引擎 | RDKit, OpenBabel, xTB, ORCA (fixture), BoTorch, scikit-learn |
| 认证 | HMAC-SHA256 令牌，与 AI4MS 门户共享账户体系 |
| 部署 | PM2, Conda |

## 项目结构

```text
Poly_Agent/
├── backend/
│   ├── app/
│   │   ├── api/v1/                    # API 路由
│   │   │   └── endpoints/             # health, auth, admin, optimization
│   │   │                              #   computations, integrations, llm, alchemist
│   │   │                              #   research_engine, assistant
│   │   ├── alchemist_core/            # 实验设计核心库（贝叶斯优化/GP/DoE/采集函数）
│   │   ├── computation_adapters/      # 计算引擎适配器
│   │   │   ├── base.py                #   adapter 协议
│   │   │   ├── registry.py            #   统一派发
│   │   │   ├── local_structure.py      #   RDKit/OpenBabel 结构生成
│   │   │   ├── local_xtb.py            #   xTB 计算
│   │   │   └── orca_compute_engine_laser.py    #   ORCA ComputeEngine Laser
│   │   ├── core/                      # 配置、令牌认证、日志、LLM 客户端
│   │   ├── infra/                     # MongoDB 连接、数据仓储、demo store
│   │   ├── schemas/                   # Pydantic 数据模型 (alchemist, computation, optimization, research_engine...)
│   │   ├── services/                  # 业务逻辑 (alchemist, auth, computation, optimization, research_engine...)
│   │   ├── workers/                   # computation worker (原子领取、执行、落库)
│   │   └── main.py                    # FastAPI 入口 (托管前端静态文件)
│   ├── tests/
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/                       # Axios 客户端与 API 调用
│   │   ├── auth/                      # 认证状态管理 + 门户 SSO
│   │   ├── router/                    # 路由配置 + 导航守卫
│   │   ├── views/
│   │   │   ├── DashboardView.vue      # 工作台
│   │   │   ├── TaskSubmitView.vue     # 性能预测任务提交
│   │   │   ├── TaskCenterView.vue     # 任务中心
│   │   │   ├── OptimizationHomeView.vue  # Alchemist 优化工作台
│   │   │   ├── ComputationSubmitView.vue # 计算任务提交
│   │   │   ├── ComputationRunsView.vue   # 计算任务列表
│   │   │   ├── CampaignsView.vue         # 优化 Campaign 列表
│   │   │   ├── CampaignDetailView.vue    # Campaign 详情
│   │   │   ├── ToolServicesView.vue      # 工具服务集成管理
│   │   │   ├── DatabaseManagementView.vue # 数据库管理 (管理员)
│   │   │   ├── DialogueView.vue          # 问答对话
│   │   │   ├── AlchemistToolView.vue     # Alchemist 工具入口
│   │   │   ├── ResearchEngineView.vue    # ResearchEngine 双通道工作台
│   │   │   ├── alchemist/               # Alchemist 子面板 (变量/实验/建模/采集/可视化)
│   │   │   └── research-engine/          # ProblemSpec、算法清单、Workflow、ResearchRun、Gate 审批面板
│   │   ├── App.vue                    # 主布局 (侧边栏 + 顶栏)
│   │   ├── style.css                  # 全局样式
│   │   └── main.js
│   ├── public/brand/                  # 品牌 Logo
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── doc/                               # 文档
│   ├── optimization-workflow-user-guide.md       # Alchemist 操作流程
│   ├── computation-workflows-user-guide.md        # 计算工作流用户指南
│   ├── compute-engine-computation-product-prd.md          # ComputeEngine 产品需求文档
│   ├── compute-engine-computation-product-design.md       # ComputeEngine 产品设计
│   ├── compute-engine-computation-migration-design.md     # ComputeEngine 迁移设计
│   ├── compute-engine-computation-progress-and-plan.md    # ComputeEngine 进度与计划
│   ├── poly-agent-toolchain-deployment-pack.md    # 工具链部署包
│   ├── autoresearch-user-guide.md        # AutoResearch 使用指南
│   ├── research-engine-and-auto-research-design.md # ResearchEngine 技术方案
│   ├── research-engine-progress-and-plan.md       # ResearchEngine P0 进度与验收
│   ├── research-engine-plan-00-roadmap.md         # ResearchEngine 实施路线图
│   └── research-engine-plan-01~06-*.md            # ResearchEngine 各阶段计划
├── refer/                             # 参考资料 (AutoResearchClaw, ComputeEngine, SpecLabOS)
├── scripts/                           # 部署与运维脚本
├── deploy/                            # 部署配置
├── DESIGN.md                          # 前端设计规范
├── ecosystem.config.js                # PM2 部署配置
└── environment.yml                    # Conda 环境定义
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

- 前端：`http://127.0.0.1:5100`
- 后端：`http://127.0.0.1:5101`

前端开发服务器会自动把 `/api` 和 `/static` 代理到后端。

### 4. 生产部署

```bash
# 构建前端
cd frontend && npm run build

# 启动后端（自动托管前端静态文件，默认端口 5100）
cd ../backend
conda run -n poly_agent python -m uvicorn app.main:app --host 0.0.0.0 --port 5100

# 或使用 PM2
pm2 start ecosystem.config.js
```

生产模式下直接访问 `http://<host>:5100` 即可，后端自动提供前端 SPA 页面。

## 认证体系

- 与 AI4MS 门户共享 `ai4ms` 认证数据库中的 `users` 和 `invite_codes` 集合
- 支持从已登录的 AI4MS 门户通过 URL hash 传递 token 实现免登录（SSO）
- 管理员通过邀请码控制用户注册
- 通过 `AUTH_ENABLED` 环境变量可切换是否需要登录

## 相关项目

- [AI4MS](https://github.com/SynlysAI/AI4MS) — 高分子智能研发门户
- [Spec Agent](https://github.com/SynlysAI/Spec_Agent) — 谱图智能分析平台
