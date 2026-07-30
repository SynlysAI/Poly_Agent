# PolyAgent 知识库 RAG + 知识图谱产品设计

## 当前状态

知识库能力已从早期 LightRAG 和本地 `literature-rag` 独立服务方案调整为 Poly Agent 后端统一适配 WeKnora 服务。当前前端、ResearchEngine 和产品内助手仍调用 Poly Agent 的稳定知识库 API，后端由 `KnowledgeService` 转发 WeKnora 知识库列表、知识问答、流式事件和无总结检索。

当前图谱能力为 WeKnora 检索子图增强：先基于 WeKnora `knowledge-search` 返回的文档和片段合成 Paper/Chunk 子图；如果配置了 `WEKNORA_NEO4J_*`，PolyAgent 会按命中 chunk 到 WeKnora Neo4j 图库反查实体节点和实体关系。Neo4j 不可用或无命中时自动回退 Paper/Chunk 子图。

## 产品入口

前端路由为 `/knowledge`，通过 `?module=rag|graph` 切换：

- `知识增强检索问答`：选择知识库体系，输入问题，选择 `hybrid/local/global/naive/mix` 模式和 Top K，展示回答、命中证据、引用来源和图谱上下文入口。
- `知识图谱`：按实体、论文、性质或方法关键词加载子图，展示节点、关系、节点属性和关联关系。

图谱 tab 初次进入时使用当前体系的默认关键词自动加载子图；未加载、无结果和服务不可用使用不同空态文案。

## 后端接口

Poly Agent 后端提供稳定 API，前端和 ResearchEngine 不直接访问独立服务。

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/v1/knowledge-bases/systems` | 列出可用知识库体系 |
| GET | `/api/v1/knowledge-bases/health` | 返回 WeKnora 服务可用性 |
| POST | `/api/v1/knowledge-bases/query` | RAG 问答 |
| POST | `/api/v1/knowledge-bases/query/stream` | 流式 RAG 问答 |
| GET | `/api/v1/knowledge-bases/{system_id}/graph` | 保留入口；当前要求提供查询词后加载子图 |
| GET | `/api/v1/knowledge-bases/{system_id}/graph/subgraph` | 获取查询相关子图 |

RAG 请求字段：

- `system_id`: 知识库体系 ID，对应 WeKnora knowledge base id
- `question`: 必填问题
- `mode`: `hybrid` 默认，可选 `local`、`global`、`naive`、`mix`
- `top_k`: 默认 5，范围 1-20
- `include_graph_context`: 默认 true

RAG 响应字段保持稳定：

- `answer`
- `hits`
- `citations`
- `graph_context`
- `configured`
- `message`

`message` 当前可能为：

- `weknora_chat`: WeKnora 知识问答结果
- `weknora_search_synthesis`: WeKnora 检索结果合成的图谱上下文

## 检索与图谱行为

- 问答通过 WeKnora `POST /sessions` 创建会话，再调用 `POST /knowledge-chat/{session_id}` 消费 SSE 事件。
- 检索通过 WeKnora `POST /knowledge-search` 获取命中文档和片段。
- 图谱通过 WeKnora 检索结果中的 `knowledge_id`、`knowledge_base_id` 和 `chunk_id` 扩展；Neo4j 节点按 WeKnora 的 `ENTITY<knowledge_base_id>:ENTITY<knowledge_id>` label 规则查询。
- 建议问题基于知识库元数据生成，不再依赖本地 LLM。
- WeKnora 未返回引用时，非流式查询会补充一次无总结检索，尽量保持证据卡片可用。
- 图谱子图响应统一为 `nodes`、`edges`、`stats`、`provenance`，前端只展示安全元数据。

## ResearchEngine 挂载

ResearchEngine 通过算法注册和 AlgorithmRun 调用知识能力：

- `weknora_adapter`：调用 `KnowledgeService.query`。
- `knowledge_graph_adapter`：调用 `KnowledgeService.get_subgraph`，返回 nodes/edges/stats。
- 两者均为 `algorithm_family="knowledge"`、`type="retriever"`、`task_scope=["KNOWLEDGE_RETRIEVAL"]`。
- AutoResearch 的 `KNOWLEDGE_RETRIEVAL` 阶段可附带 `graph_context`，供后续报告和追溯使用。

## 部署与配置

服务地址：

- WeKnora：由 `WEKNORA_BASE_URL` 指定，例如 `http://10.26.15.93:8000/api/v1`
- Poly Agent 后端：`http://127.0.0.1:5201`
- Poly Agent 前端：`http://127.0.0.1:5200`

Poly Agent 后端环境变量：

- `WEKNORA_BASE_URL`: WeKnora API 地址；可包含或省略 `/api/v1`
- `WEKNORA_API_KEY`: WeKnora API key，后端以 `X-API-Key` 请求头传递
- `WEKNORA_DEFAULT_KB_ID`: 可选默认知识库 ID
- `WEKNORA_NEO4J_URI`: 可选 WeKnora Neo4j 地址，例如 `bolt://10.26.15.93:7687`
- `WEKNORA_NEO4J_USERNAME`: 可选 Neo4j 用户名
- `WEKNORA_NEO4J_PASSWORD`: 可选 Neo4j 密码
- `WEKNORA_NEO4J_DATABASE`: 可选 Neo4j database，默认 `neo4j`
- `WEKNORA_NEO4J_TIMEOUT_SECONDS`: 可选 Neo4j 连接超时，默认 3 秒

Poly Agent 后端不再自动探测或启动旧版本地 `literature-rag` 服务；相关独立服务目录和部署模板已移除。

## 验收标准

- `/knowledge?module=rag` 能用中文问题返回 WeKnora 命中证据和引用。
- `/api/v1/knowledge-bases/health` 返回 WeKnora readiness 和知识库列表。
- `/knowledge?module=graph` 初次进入会自动加载默认子图或明确显示待加载状态；配置 Neo4j 后可显示 Entity 节点和实体关系。
- `/api/v1/knowledge-bases/*` 不暴露 API key、`storage_uri`、`object_key`、`content_hash` 或 embedding。
- 后端知识库适配层可导入，前端 build 通过。
