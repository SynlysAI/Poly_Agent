# PolyAgent 来源、引用与机构标注矩阵

本文记录系统模块、算法能力和页面展示中的来源标注。页面首屏使用来源横幅；算法卡片、详情抽屉和预测结果显示开发者来源。

| 模块 | 页面入口 | 参考框架/方法 | 开发者/机构 | Logo 资产策略 | 引用链接 | 实现边界 |
|------|----------|---------------|-------------|----------------|----------|----------|
| ResearchEngine | `/research-engine` | ChemOS 2.0 自驱实验室编排思想 | University of Toronto / Aspuru-Guzik Group；PolyAgent | 无授权图片时使用文字来源牌 | https://github.com/malcolmsimgithub/ChemOS2.0 | 不声明直接复制 ChemOS 代码；ProblemSpec、Workflow、Gate、追溯为本项目实现 |
| 湿实验优化 | `/optimization` | ALchemist；ChemOS 2.0 | NatLabRockies / NREL / NLR；PolyAgent | 无授权图片时使用文字来源牌 | https://github.com/NatLabRockies/ALchemist | Alchemist 提供主动学习/BO 方法来源；Campaign planner 为本地实现 |
| Alchemist 工具 | `/optimization/alchemist` | ALchemist 实验设计、GP、采集优化 | NatLabRockies / NREL / NLR | 无授权图片时使用文字来源牌 | https://github.com/NatLabRockies/ALchemist | PolyAgent 负责中文工作台、认证、会话和平台集成 |
| ComputeEngine | `/computations/submit` | RDKit、OpenBabel、xTB、CREST、ORCA | 对应第三方项目；PolyAgent | 无授权图片时使用文字来源牌 | https://www.rdkit.org/；https://openbabel.org/；https://xtb-docs.readthedocs.io/；https://orcaforum.kofo.mpg.de/ | PolyAgent 负责任务、worker、artifact、审计和 campaign 联动；计算能力来自本地依赖 |
| 垂类预测模型 | `/vertical-prediction` | 算法包契约中的方法来源 | 算法开发者、开发机构 | 优先使用算法包提交且授权的 Logo；否则文字来源牌 | 来自 `source_url` / `citation` | 平台治理上传、校验、部署和运行；模型方法不归属 PolyAgent 除非明确标注 |
| 文献知识库 | `/knowledge` | RAG、知识图谱和语料服务契约 | PolyAgent KnowledgeService / literature-rag | 无授权图片时使用文字来源牌 | 服务和语料库配置记录 | 查询、证据、图谱上下文和语料来源按服务契约追溯 |
| 数据管理 | `/database/data-catalog` | OpenPoly、RadonPy PI1070、PI1M v2、SMiPoly、PolyUniverse 数据来源 | 对应数据集/项目开发者；PolyAgent | 无授权图片时使用文字来源牌 | SMiPoly: https://github.com/PEJpOhno/SMiPoly；DOI: https://doi.org/10.1021/acs.jcim.3c00329；PolyUniverse: https://github.com/ytl0410/PolyUniverse；Zenodo: https://zenodo.org/records/12585902；DOI: https://doi.org/10.1039/D4DD00196F | PolyAgent 负责 MinIO/MongoDB 迁移、目录展示、记录下钻和来源追溯；不声明拥有原始数据集 |

## 维护规则

- 新增系统模块时，先在后端 `AttributionService` 注册模块来源，再在页面接入 `AttributionBanner`。
- 新增算法或垂类模型时，必须在 `AlgorithmRegistryEntry` 或 `polyagent.algorithm.yaml` 中填写开发者来源；缺失时只能用创建人兜底。
- 有机构来源时优先展示机构 Logo 和一句说明；没有明确授权或来源时不要落本地图片。
- Logo 文件放在 `frontend/public/attributions/`，并记录 `logo_alt`。
