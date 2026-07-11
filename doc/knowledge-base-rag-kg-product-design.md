# PolyAgent 知识库 RAG + 知识图谱产品设计

## 背景与目标

PolyAgent 已有 ResearchEngine 的 `KNOWLEDGE_RETRIEVAL` 阶段和 `literature_rag_adapter` 入口，但原实现主要依赖本地 JSON 检索。知识库能力需要从 mock 入口升级为可承载实际场景的应用层能力：

- 面向已清洗知识资产提供知识增强检索问答。
- 面向材料体系提供知识图谱可视化。
- 通过稳定后端接口被前端和 ResearchEngine 同时调用。
- 平台内不负责文献下载、PDF 解析、OCR、数据清洗和 DOI 拉取。

## 技术选型

v1 主线选择 LightRAG 作为外部 RAG/GraphRAG 服务内核，PolyAgent 自建应用界面和适配层。

| 方案 | 定位 | v1 取舍 |
| --- | --- | --- |
| LightRAG | Graph-based RAG、API Server、WebUI、图谱探索、多 workspace/存储后端 | 主选，适合以服务方式接入应用层 |
| Microsoft GraphRAG | 离线构图、社区摘要、全局/局部检索方法论 | 作为后续离线知识生产参考，不作为 v1 应用主线 |
| Neo4j GraphRAG Python | 图数据库 + GraphRAG SDK | 当需要 Cypher、复杂图分析、企业级图存储时增强 |
| Haystack / LlamaIndex | 通用 RAG/Agent 编排框架 | 可作为后续复杂 pipeline 编排补充 |

参考项目：

- LightRAG: https://github.com/HKUDS/LightRAG
- Microsoft GraphRAG: https://github.com/microsoft/graphrag
- Neo4j GraphRAG Python: https://github.com/neo4j/neo4j-graphrag-python
- Haystack: https://github.com/deepset-ai/haystack
- LlamaIndex: https://github.com/run-llama/llama_index

## 产品与接口

### 前端入口

`任务提交 -> 知识库` 新增两个模块：

- `知识增强检索问答`：选择体系、输入问题、选择检索模式和 Top K，展示回答、命中证据、引用和图谱上下文。
- `知识图谱`：选择体系，按关键词加载全图或子图，展示节点、关系和节点属性。

v1 路由为 `/knowledge`，通过 `?module=rag|graph` 切换模块。

### 后端 API

PolyAgent 后端提供统一知识库 API，前端和 ResearchEngine 不直接访问 LightRAG。

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/v1/knowledge-bases/systems` | 列出可用知识库体系 |
| GET | `/api/v1/knowledge-bases/health` | 返回 LightRAG 和 demo 可用性 |
| POST | `/api/v1/knowledge-bases/query` | RAG 问答 |
| GET | `/api/v1/knowledge-bases/{system_id}/graph` | 获取体系图谱 |
| GET | `/api/v1/knowledge-bases/{system_id}/graph/subgraph` | 获取查询相关子图 |

RAG 请求字段：

- `system_id`: 默认 `ai4s_fluoropolymer`
- `question`: 必填问题
- `mode`: `hybrid` 默认，可选 `local`、`global`、`naive`、`mix`
- `top_k`: 默认 5，范围 1-20
- `include_graph_context`: 默认 true

RAG 响应字段：

- `answer`
- `hits`
- `citations`
- `graph_context`
- `configured`
- `message`

图谱响应统一为：

- `nodes`: `id`、`label`、`type`、`score`、`properties`
- `edges`: `id`、`source`、`target`、`type`、`weight`、`properties`
- `stats`: `entity_count`、`relation_count`、`document_count`

## ResearchEngine 挂载

ResearchEngine 继续通过算法注册和 AlgorithmRun 调用知识能力：

- `literature_rag_adapter`：保留既有 ID，升级为调用 `KnowledgeService.query`。
- `knowledge_graph_adapter`：新增图谱/子图检索适配器，返回 nodes/edges/stats。
- 两者均为 `algorithm_family="knowledge"`、`type="retriever"`、`task_scope=["KNOWLEDGE_RETRIEVAL"]`。
- AutoResearch 的 `KNOWLEDGE_RETRIEVAL` 阶段默认调用 `literature_rag_adapter`，回答内可附带 `graph_context`。

未配置 `KNOWLEDGE_RAG_BASE_URL` 时，adapter 返回标注为 `demo_source` 的 AI4S demo 数据；不伪装成真实文献。

## Demo 数据

v1 内置体系：

- `system_id`: `ai4s_fluoropolymer`
- 名称：`AI4S 氟聚合物材料体系`
- 范围：氟聚合物、介电性能、热稳定性、图描述符、AI4S 筛选流程

Demo 数据形态：

- 文档卡片：title、summary、keywords、source、doi/url、metadata。
- 实体类型：Material、Polymer、Monomer、Property、Method、Paper、Dataset、Application。
- 关系类型：HAS_MONOMER、HAS_PROPERTY、MEASURED_BY、REPORTED_IN、OPTIMIZED_FOR、SIMILAR_TO。

v1.1 增强后，`ai4s_fluoropolymer` 内置 seed 扩展为：

- 约 20 篇可追溯 DOI/URL 的论文卡片，来源覆盖 Nature 子刊、Scientific Reports、Advanced Materials、Progress in Materials Science、Energy & Environmental Science、Chemical Society Reviews、Journal of Materials Chemistry A/C、Advanced Functional Materials 等。
- 图谱新增 `Strategy`、`PerformanceMetric` 等知识节点，用于连接论文、材料、结构设计策略、性能目标和 AI4S 方法。
- RAG answer 使用 Markdown 语义结构，回答中的论文名以 DOI/URL 超链接渲染；前端不使用任意 HTML 注入。

所有内置数据均标注 `demo_source=true` 和 `source_type=paper_seed|demo_card`，仅用于功能演示和接口验收。

## 部署与配置

可选环境变量：

- `KNOWLEDGE_RAG_BASE_URL`: LightRAG API Server 地址。
- `KNOWLEDGE_RAG_API_KEY`: LightRAG API key，可为空。

配置后，`KnowledgeService` 优先调用 LightRAG `/query`；未配置或调用失败时返回 demo 数据和明确 message。API 不返回 API key、内部存储路径或 `storage_uri`。

## 验收标准

- `任务提交 -> 知识库` 可进入 RAG 问答和知识图谱模块。
- `/knowledge?module=rag` 能完成一次问答，展示答案、证据和引用。
- `/knowledge?module=graph` 能展示 `ai4s_fluoropolymer` 子图和节点详情。
- `/api/v1/knowledge-bases/*` 返回稳定契约，不暴露敏感路径或密钥。
- ResearchEngine 算法清单包含 `literature_rag_adapter` 和 `knowledge_graph_adapter`。
- `AlgorithmRun` 可调用两个知识适配器并保存结构化 `output_summary`。
- AutoResearch readiness 中知识库 RAG 是非阻塞项；LightRAG 未配置时显示 demo fallback。
