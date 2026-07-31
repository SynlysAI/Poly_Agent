# Poly Agent 文档地图

本目录保存 Poly Agent 的用户指南、产品设计、实施计划、部署说明和来源标注文档。仓库根目录 [../README.md](../README.md) 面向项目总览和快速启动；本文件用于按任务快速定位详细文档。

## 推荐阅读路径

| 角色/目标 | 先读 | 再读 |
|-----------|------|------|
| 新成员本地启动 | [../README.md](../README.md) | [poly-agent-toolchain-deployment-pack.md](poly-agent-toolchain-deployment-pack.md) |
| 使用计算工作流 | [computation-workflows-user-guide.md](computation-workflows-user-guide.md) | [compute-engine-computation-progress-and-plan.md](compute-engine-computation-progress-and-plan.md) |
| 使用实验优化 | [optimization-workflow-user-guide.md](optimization-workflow-user-guide.md) | [compute-engine-computation-product-design.md](compute-engine-computation-product-design.md) |
| 使用 AutoResearch | [autoresearch-user-guide.md](autoresearch-user-guide.md) | [research-engine-progress-and-plan.md](research-engine-progress-and-plan.md) |
| 上传垂类算法 | [algorithm-upload-user-guide.md](algorithm-upload-user-guide.md) | [algorithm-upload-p0-assessment-and-roadmap.md](algorithm-upload-p0-assessment-and-roadmap.md) |
| 了解知识库服务 | [knowledge-base-rag-kg-product-design.md](knowledge-base-rag-kg-product-design.md) | [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md) |
| 维护来源标注 | [polyagent-attribution-source-matrix.md](polyagent-attribution-source-matrix.md) | [../README.md#框架方法与机构来源](../README.md#框架方法与机构来源) |

## 用户指南

| 文档 | 内容 |
|------|------|
| [optimization-workflow-user-guide.md](optimization-workflow-user-guide.md) | Alchemist 实验设计、数据录入、建模、采集优化和诊断可视化操作流程 |
| [computation-workflows-user-guide.md](computation-workflows-user-guide.md) | 本地结构生成、xTB/CREST 粗优化和 ORCA 精加工工作流使用说明 |
| [autoresearch-user-guide.md](autoresearch-user-guide.md) | ResearchEngine / AutoResearch 的任务创建、运行推进、Gate 审批和追溯查看 |
| [algorithm-upload-user-guide.md](algorithm-upload-user-guide.md) | 垂类算法包结构、打包、上传、测试和上线流程 |

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
