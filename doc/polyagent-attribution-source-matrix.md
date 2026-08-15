# PolyAgent 来源、引用与机构标注矩阵

本文记录系统模块、算法能力和页面展示中的来源标注。页面首屏使用来源横幅；算法卡片、详情抽屉和预测结果显示开发者来源。

| 模块 | 页面入口 | 参考框架/方法 | 开发者/机构 | Logo 资产策略 | 引用链接 | 实现边界 |
|------|----------|---------------|-------------|----------------|----------|----------|
| ResearchEngine | `/research-engine` | ChemOS 2.0 自驱实验室编排思想 | University of Toronto / Aspuru-Guzik Group；PolyAgent | 无授权图片时使用文字来源牌 | https://github.com/malcolmsimgithub/ChemOS2.0 | 不声明直接复制 ChemOS 代码；ProblemSpec、Workflow、Gate、追溯为本项目实现 |
| 湿实验优化 | `/optimization` | ALchemist；ChemOS 2.0 | NatLabRockies / NREL / NLR；PolyAgent | 无授权图片时使用文字来源牌 | https://github.com/NatLabRockies/ALchemist | Alchemist 提供主动学习/BO 方法来源；Campaign planner 为本地实现 |
| Alchemist 工具 | `/optimization/alchemist` | ALchemist 实验设计、GP、采集优化 | NatLabRockies / NREL / NLR | 无授权图片时使用文字来源牌 | https://github.com/NatLabRockies/ALchemist | PolyAgent 负责中文工作台、认证、会话和平台集成 |
| 实验方案转发台 | `/optimization/experiment-dispatch` | SpecLabOS 参数化实验执行参考；ChASM 指令集模板 | SpecLabOS；实验执行模板提供方 | 未确认 Logo 时使用文字来源牌 | — | 本期仅生成和保存实验清单，不声明已执行真实设备 |
| ComputeEngine | `/computations/submit` | RDKit、OpenBabel、xTB、CREST、ORCA | 对应第三方项目；PolyAgent | 无授权图片时使用文字来源牌 | https://www.rdkit.org/；https://openbabel.org/；https://xtb-docs.readthedocs.io/；https://orcaforum.kofo.mpg.de/ | PolyAgent 负责任务、worker、artifact、审计和 campaign 联动；计算能力来自本地依赖 |
| 垂类预测模型 | `/vertical-prediction` | 算法包契约或远程接口配置中的方法来源 | 算法/接口开发者、开发机构、导师课题组、上游服务提供方 | 仅使用开发者明确授权的 Logo；否则文字来源牌 | 来自 `source_url` / `citation` | 平台治理上传、校验、部署、接口连通性和运行；模型方法及上游服务不归属 PolyAgent 除非明确标注 |
| 对话算法工具 LUI | `/dialogue` | Open WebUI 对话工作台与工具调用交互参考；DeepSeek Harness 仅作为上下文注入、工具流水线和持久化事件架构参考；实际算法方法来源沿用垂类预测模型登记 | Open WebUI；DeepSeek Harness；各算法开发者与机构 | Open WebUI 与 DeepSeek Harness 均使用文字来源牌；算法仅使用明确授权的 Logo | https://github.com/open-webui/open-webui；https://deepseek-harness.github.io/deepseek-harness/；算法链接来自 `source_url` / `citation` | 不声明复制 Open WebUI 或 DeepSeek Harness 代码；工具派生、权限、确认状态机、AlgorithmRun、SSE 和 LUI Runtime 为本项目实现 |
| LLM 模型服务 | `/tools?tab=llm-models` | OpenAI Chat Completions 协议；Ollama；自定义 HTTP provider | OpenAI-compatible provider；Ollama；实际模型/机构由 provider 配置声明 | 无授权 Logo 时使用文字来源牌 | https://platform.openai.com/docs/api-reference/chat；https://ollama.com/ | 页面只展示 provider 协议和当前配置，不声明具体模型所有权或复制上游实现 |
| 文献知识库 | `/knowledge` | WeKnora 知识库管理、检索问答、引用证据和 Neo4j 图谱数据 | Tencent WeKnora；PolyAgent KnowledgeService 适配层 | 无授权图片时使用文字来源牌 | https://github.com/Tencent/WeKnora | 查询、证据、检索子图和语料来源按 WeKnora 响应与 WeKnora Neo4j 图库追溯；PolyAgent 仅保留本地接口契约 |
| 数据管理 | `/database/data-catalog`、`/database/data-analysis` | 16 个目录数据集，详见下表 | 对应数据集/项目开发者与数据提供方；PolyAgent | 无授权图片时使用文字来源牌 | 仅登记可由上游材料核验的链接 | PolyAgent 负责 MinIO/MongoDB 迁移、目录展示、记录下钻、分析视图和来源追溯；不声明拥有原始数据集 |

### 数据目录来源矩阵

| 数据集 | 权威来源/引用 | 许可或展示规则 |
|--------|---------------|----------------|
| OpenPoly | https://doi.org/10.1007/s10118-025-3402-y | 文字来源牌 |
| RadonPy PI1070 | https://github.com/RadonPy/RadonPy | 文字来源牌 |
| PI1M v2 | https://doi.org/10.1021/acs.jcim.0c00726 | 文字来源牌 |
| SMiPoly | https://github.com/PEJpOhno/SMiPoly；https://doi.org/10.1021/acs.jcim.3c00329 | 文字来源牌 |
| PolyUniverse | https://github.com/ytl0410/PolyUniverse；https://doi.org/10.1039/D4DD00196F | 文字来源牌 |
| MD-AllAtom | 当前内部数据说明 | 来源不明确，不展示外链或 Logo |
| OMG | https://github.com/TheJacksonLab/OpenMacromolecularGenome | 仓库代码为 GPL-3.0；数据集条款仍以其上游说明为准 |
| OMG Physical Properties | https://doi.org/10.5281/zenodo.13863778；https://doi.org/10.1039/D4SC08617A | 文字来源牌 |
| polyOne | https://doi.org/10.5281/zenodo.7124188；https://doi.org/10.1038/s41467-023-39868-6 | 文字来源牌 |
| ToPoRg | https://doi.org/10.5281/zenodo.10672434；https://doi.org/10.1038/s41524-024-01328-0 | CC BY 4.0 |
| PolySol | 当前数据目录说明 | 来源不明确，不展示外链或 Logo |
| PolyOmics | 当前数据目录说明 | 来源不明确，不展示外链或 Logo |
| PPPDB | 当前数据目录说明 | 来源不明确，不展示外链或 Logo |
| PolyID | 当前数据目录说明 | 来源不明确，不展示外链或 Logo |
| TROPIC | https://polytropic.org/；https://doi.org/10.1039/D5FD00098J | 文字来源牌 |
| NanoMine | 当前数据目录说明 | 来源不明确，不展示外链或 Logo |

## 维护规则

- 新增系统模块时，先在后端 `AttributionService` 注册模块来源，再在页面接入 `AttributionBanner`。
- 新增算法或垂类模型时，必须在 `AlgorithmRegistryEntry` 或 `polyagent.algorithm.yaml` 中填写开发者来源；缺失时只能用创建人兜底。
- 有机构来源时优先展示机构 Logo 和一句说明；没有明确授权或来源时不要落本地图片。
- Logo 文件放在 `frontend/public/attributions/`，并记录 `logo_alt`。
