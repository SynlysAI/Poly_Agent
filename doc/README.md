# Poly Agent 文档地图

本目录保存 Poly Agent 的用户指南、产品设计、实施计划、部署说明和来源标注文档。仓库根目录 [../README.md](../README.md) 面向项目总览和快速启动；本文件用于按任务快速定位详细文档。

根 README 的项目图示资源统一放在 [`../docs/`](../docs/)：项目定位、面向对象、产品设计闭环、技术路线图和技术架构图。图示中的状态与边界应和本目录的进度文档保持一致。

## 推荐阅读路径

| 角色/目标 | 先读 | 再读 |
|-----------|------|------|
| 新成员本地启动 | [../README.md](../README.md) | [poly-agent-toolchain-deployment-pack.md](poly-agent-toolchain-deployment-pack.md) |
| 使用计算工作流 | [computation-workflows-user-guide.md](computation-workflows-user-guide.md) | [compute-engine-computation-progress-and-plan.md](compute-engine-computation-progress-and-plan.md) |
| 使用实验优化 | [optimization-workflow-user-guide.md](optimization-workflow-user-guide.md) | [compute-engine-computation-product-design.md](compute-engine-computation-product-design.md) |
| 使用 AutoResearch | [autoresearch-user-guide.md](autoresearch-user-guide.md) | [research-engine-progress-and-plan.md](research-engine-progress-and-plan.md) |
| 查看与调用 Agent 能力 | [capability-center-user-guide.md](capability-center-user-guide.md) | [agent-connector-user-guide.md](agent-connector-user-guide.md) |
| 上传垂类算法 | [algorithm-upload-user-guide.md](algorithm-upload-user-guide.md) | [algorithm-upload-p0-assessment-and-roadmap.md](algorithm-upload-p0-assessment-and-roadmap.md) |
| 配置远程接口模型 | [vertical-model-interface-user-guide.md](vertical-model-interface-user-guide.md) | [algorithm-upload-user-guide.md](algorithm-upload-user-guide.md) |
| 了解知识库服务 | [knowledge-base-rag-kg-product-design.md](knowledge-base-rag-kg-product-design.md) | [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md) |
| 使用对话控制命令 | [dialogue-slash-command-guide.md](dialogue-slash-command-guide.md) | [research-engine-plan-10-slash-command-and-agent-control-workplan.md](research-engine-plan-10-slash-command-and-agent-control-workplan.md) |
| 维护来源标注 | [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md) | [../README.md#框架方法与机构来源](../README.md#框架方法与机构来源) |

## 官网内容

| 文档 | 内容 |
|------|------|
| [../docs/website/features.md](../docs/website/features.md) | Poly Agent 主要功能、模块操作路径、Slash Command 调用方法与能力边界 |
| [../docs/website/releases/0.1.0/product-feature-updates.md](../docs/website/releases/0.1.0/product-feature-updates.md) | 当前产品版本 `0.1.0` 的详细特性更新、操作流程、命令参考与下一阶段方向 |

官网内容使用 Markdown frontmatter 记录版本、日期、语言与发布状态；后续产品版本发布时，需要同步更新 release note 的版本字段，并检查功能页的版本与能力边界。

## 用户指南

| 文档 | 内容 |
|------|------|
| [optimization-workflow-user-guide.md](optimization-workflow-user-guide.md) | Alchemist 实验设计、数据录入、建模、采集优化和诊断可视化操作流程 |
| [computation-workflows-user-guide.md](computation-workflows-user-guide.md) | 本地结构生成、xTB/CREST 粗优化和 ORCA 精加工工作流使用说明 |
| [autoresearch-user-guide.md](autoresearch-user-guide.md) | ResearchEngine / AutoResearch 的任务创建、运行推进、Gate 审批和追溯查看 |
| [algorithm-upload-user-guide.md](algorithm-upload-user-guide.md) | 垂类算法包结构、打包、上传、测试和上线流程 |
| [vertical-model-interface-user-guide.md](vertical-model-interface-user-guide.md) | HTTP/FastAPI/MCP 远程接口模型的配置、测试、激活、调用和安全边界 |
| [dialogue-slash-command-guide.md](dialogue-slash-command-guide.md) | `/dialogue` Slash Command、会话控制、动态计算预算、统一回放与来源说明 |
| [agent-connector-user-guide.md](agent-connector-user-guide.md) | Agent 连接器的默认安全策略、管理员配置、LUI 暴露规则、安全边界与审计说明 |
| [capability-center-user-guide.md](capability-center-user-guide.md) | `/capabilities` 能力目录的角色视角、四个能力分组、连接器确认、来源与治理边界 |

## 产品与架构设计

| 文档 | 内容 |
|------|------|
| [compute-engine-computation-product-prd.md](compute-engine-computation-product-prd.md) | ComputeEngine 计算智能模块 PRD |
| [compute-engine-computation-product-design.md](compute-engine-computation-product-design.md) | ComputeEngine 产品设计和页面能力 |
| [compute-engine-computation-migration-design.md](compute-engine-computation-migration-design.md) | ComputeEngine 计算、优化与可视化能力迁移方案 |
| [research-engine-and-auto-research-design.md](research-engine-and-auto-research-design.md) | ResearchEngine 高分子材料 AI 研发平台技术方案 |
| [research-report-generation-product-design.md](research-report-generation-product-design.md) | 自动研发报告生成、渲染器和 LLM provider 设计 |
| [knowledge-base-rag-kg-product-design.md](knowledge-base-rag-kg-product-design.md) | WeKnora 知识库问答与检索子图产品设计 |
| [knowledge-base-rag-kg-upgrade-plan.md](knowledge-base-rag-kg-upgrade-plan.md) | 知识库内容、检索和界面增强计划 |
| [platform-positioning-and-small-iteration-plan.md](platform-positioning-and-small-iteration-plan.md) | 平台定位、credit、低学习成本和小步优化方案 |
| [internagents-inspired-product-optimization-design.md](internagents-inspired-product-optimization-design.md) | 借鉴 InternAgents 工作台模型的 PolyAgent 产品设计优化方案 |

## 规划与设计

| 文档 | 内容 |
|------|------|
| [plan-polymer-inverse-design-and-property-prediction-demo.md](plan-polymer-inverse-design-and-property-prediction-demo.md) | 聚合物自然语言逆向设计与性质预测 Demo 落地计划：三阶段参考评估、逆向设计、性质预测与候选结构 demo |
| [plan-multi-site-collaborative-optimization-fedbo-pilot.md](plan-multi-site-collaborative-optimization-fedbo-pilot.md) | 多站点协同实验优化与联邦贝叶斯 FedBO 试点计划：参考解读、产品边界、架构预案与分阶段落地 |
| [plan-als-orchestration-and-bounded-execution.md](plan-als-orchestration-and-bounded-execution.md) | 大装置 Agent 编排与受限执行设计（ALS 范式）：Plan-first 显式依赖计划、动态能力选择、只读/可写双模式、统一安全层、NL 驱动参数解析器 |
| [plan-ssrl-agent-honing-and-closed-loop-execution.md](plan-ssrl-agent-honing-and-closed-loop-execution.md) | 智能体打磨与闭环执行设计（SSRL 范式）：虚拟打磨环境、双层提示词、图像化观测、会话级持久与短期记忆、被动转发安全模式、工作流级鲁棒性基准 |

## 进度、计划与验收

| 文档 | 内容 |
|------|------|
| [compute-engine-computation-progress-and-plan.md](compute-engine-computation-progress-and-plan.md) | ComputeEngine 当前能力、完成度、缺口和后续计划 |
| [research-engine-progress-and-plan.md](research-engine-progress-and-plan.md) | ResearchEngine P0 完成状态、验收记录、已知限制和测试状态 |
| [research-engine-plan-00-roadmap.md](research-engine-plan-00-roadmap.md) | ResearchEngine 分阶段实施计划索引 |
| [research-engine-plan-01-domain-foundation.md](research-engine-plan-01-domain-foundation.md) | 后端领域底座计划 |
| [research-engine-plan-02-problem-spec-and-registry-api.md](research-engine-plan-02-problem-spec-and-registry-api.md) | ProblemSpec 与 AlgorithmRegistry API 计划 |
| [research-engine-plan-03-manual-algorithm-channel.md](research-engine-plan-03-manual-algorithm-channel.md) | 人工算法 Workflow 通道计划 |
| [research-engine-plan-04-autoresearch-orchestrator.md](research-engine-plan-04-autoresearch-orchestrator.md) | AutoResearch 材料版编排器计划 |
| [research-engine-plan-05-frontend-mvp.md](research-engine-plan-05-frontend-mvp.md) | ResearchEngine 前端 MVP 计划 |
| [research-engine-plan-06-traceability-and-qa.md](research-engine-plan-06-traceability-and-qa.md) | 追溯闭环与验收计划 |
| [research-engine-plan-07-lui-algorithm-tooling.md](research-engine-plan-07-lui-algorithm-tooling.md) | `/dialogue` LUI 升级：算法工具派生、调用状态机、历史对话、模型编排与界面均已落地，真实模型与 Playwright 响应式验收完成 |
| [research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md](research-engine-plan-08-lui-runtime-and-tool-calling-workplan.md) | LUI Runtime、模型路由识别、上下文注入、工具契约、持久化事件、服务端续答与配置/观测增强工作计划 |
| [research-engine-plan-08-regression-test-matrix.md](research-engine-plan-08-regression-test-matrix.md) | Plan 08 LUI Runtime 回归测试矩阵与验证命令 |
| [research-engine-plan-08-wrapup.md](research-engine-plan-08-wrapup.md) | Plan 08 剩余技术债 P08-F2–F8 的独立收尾计划，已完成并关闭 |
| [research-engine-plan-09-lui-execution-trace.md](research-engine-plan-09-lui-execution-trace.md) | LUI Execution Trace 与可追溯执行增强计划 |
| [research-engine-plan-10-slash-command-and-agent-control-workplan.md](research-engine-plan-10-slash-command-and-agent-control-workplan.md) | Slash Command、会话控制面与 Agent 控制体系工作计划 |
| [research-engine-plan-11-lui-qa-deep-preset-positioning.md](research-engine-plan-11-lui-qa-deep-preset-positioning.md) | LUI 科研问答与深度思考 Preset 定位、差异与兼容基础 |
| [research-engine-plan-12-product-positioning-evolution.md](research-engine-plan-12-product-positioning-evolution.md) | PI Agent / DSH / Codex 时代的产品定位、生态位与演进路线 |
| [research-engine-plan-13-lui-agent-evaluation-plan.md](research-engine-plan-13-lui-agent-evaluation-plan.md) | LUI Agent 八项指标评估体系：任务成功、工具调用、检索召回、回答准确、幻觉、延迟、成本与人工兜底 |
| [research-engine-plan-14-lui-dynamic-compute-budget-plan.md](research-engine-plan-14-lui-dynamic-compute-budget-plan.md) | LUI 动态计算预算已完成：Query 分类、Model Router、RAG 分层、执行分级、影子观测与灰度回滚；默认保持影子模式 |
| [research-engine-plan-15-agent-exec-provider-seam-workplan.md](research-engine-plan-15-agent-exec-provider-seam-workplan.md) | 受控外部 Agent 执行 Provider Seam 与 Agent 连接器治理：readiness、独立 workdir、Codex MVP、连接器策略、Audit / Trace 与管理 API |
| [research-engine-plan-16-capability-center-and-permission-governance-workplan.md](research-engine-plan-16-capability-center-and-permission-governance-workplan.md) | Agent 能力中心与权限治理：新建 `/capabilities` 独立入口（Agent 能力调用目录），`/tools` 收窄为配置中心，Skill allowlist 目录、`/admin` 用户与邀请码管理 UI |
| [algorithm-upload-p0-assessment-and-roadmap.md](algorithm-upload-p0-assessment-and-roadmap.md) | 垂类模型自动上传与部署生产化评估 |

## 部署、工具链与治理

| 文档 | 内容 |
|------|------|
| [poly-agent-toolchain-deployment-pack.md](poly-agent-toolchain-deployment-pack.md) | 计算工具链部署包和运行环境说明 |
| [centralized-deployment-data-security-technical-assurance-plan.md](centralized-deployment-data-security-technical-assurance-plan.md) | 集中部署模式数据安全技术保障方案 |
| [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md) | 系统模块、外部框架、方法、机构和算法开发者来源矩阵 |

## 文档维护约定

- 更新 README 时同步检查本文件，确保新用户能从总览跳到详细文档。
- 新增功能文档优先放入对应分类，并在文档标题下写清楚适用版本、当前状态和边界。
- 涉及外部框架、机构、模型、算法包或依赖来源时，同步更新 [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md)。
- 历史计划文档不要删除；如果决策改变，新增当前状态说明或在进度文档中标注 superseded 关系。
