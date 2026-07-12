# PolyAgent RAG/KG 内容与界面增强计划

## 目标

将知识库从少量 demo 卡片升级为面向 `ai4s_fluoropolymer` 体系的可演示工作台：

- 内置约 20 篇可追溯 DOI/URL 的高质量论文卡片，覆盖氟聚合物、PVDF、聚合物介电储能、高温电容和机器学习设计。
- RAG 回答以语义化 Markdown 结构返回，并在回答、证据和引用中提供论文超链接。
- 知识图谱从单一演示链路扩展为论文-材料-结构策略-性能-方法-应用的多类型关系。
- 前端从基础表单布局升级为可扫描、专业的知识工作台。

## 数据选择

内置论文数据只作为 demo seed 和 LightRAG 未配置时的 fallback，不替代正式文献 ingestion。筛选原则：

- 优先 Nature / Nature 子刊、Scientific Reports、Advanced Materials、Progress in Materials Science、Energy & Environmental Science、Chemical Society Reviews、Journal of Materials Chemistry A/C、Advanced Functional Materials 等高影响材料期刊。
- 每条论文必须包含 DOI 或 URL。
- 每条卡片标注 `demo_source=true` 和 `source_type=paper_seed`，避免伪装成已清洗生产知识库。

## 实施任务

### 1. 后端数据与回答

**验收标准：**
- `/api/v1/knowledge-bases/systems` 的 `document_count` 至少为 20。
- `/api/v1/knowledge-bases/query` 返回带 DOI/URL 的 citations。
- demo answer 是可渲染 Markdown，且包含论文链接。

**涉及文件：**
- `backend/app/services/knowledge_service.py`
- `backend/app/schemas/knowledge.py`
- `backend/tests/test_knowledge_base_api.py`

### 2. 知识图谱增强

**验收标准：**
- 图谱包含 Material、Polymer、Monomer、Property、Strategy、Method、Dataset、Application、Paper 等节点类型。
- 图谱包含论文支撑、材料组成、结构策略、性能目标、方法、应用等关系。
- 子图查询能命中 paper、PVDF、dielectric、machine learning 等关键词。

**涉及文件：**
- `backend/app/services/knowledge_service.py`
- `backend/tests/test_knowledge_base_api.py`

### 3. 前端语义化与视觉优化

**验收标准：**
- RAG 页面有清晰的左右工作台布局：查询、回答、证据、引用、图谱上下文。
- Markdown 回答渲染为标题、段落、列表和超链接，不直接裸露 Markdown 符号。
- 论文引用以可点击链接展示；无 URL 时退回 DOI 链接。
- 图谱页面提供统计、图例、节点详情和关联论文信息。

**涉及文件：**
- `frontend/src/views/KnowledgeBaseView.vue`

### 4. 验证

**命令：**
- `cd backend && pytest tests/test_knowledge_base_api.py`
- `cd frontend && npm run build`

如服务可用，再启动前后端并做浏览器检查。

## 风险与处理

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| 内置论文摘要不完整 | RAG demo 回答可能过泛 | 用人工摘要式 evidence card，保留 DOI/URL 追溯 |
| 论文元数据未来变化 | DOI 链接仍稳定 | 测试只验证结构与链接存在，不绑定外部实时查询 |
| 前端 Markdown 渲染安全 | XSS 风险 | 不使用 `v-html`，用受控 token 渲染标题、列表、链接 |
| 图谱节点过多导致布局拥挤 | 可读性下降 | 子图默认 limit 30，并按类型分层排布 |

## 验收清单

- [ ] 文献 seed 至少 20 篇，且每篇有 DOI/URL。
- [ ] RAG answer 中包含可点击论文链接。
- [ ] citations 和 hits 都保留可追溯 source。
- [ ] graph stats 与实际节点/边数量一致。
- [ ] 后端知识库 API 测试通过。
- [ ] 前端构建通过。
