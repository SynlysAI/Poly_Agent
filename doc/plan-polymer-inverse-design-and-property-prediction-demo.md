# 聚合物自然语言逆向设计与性质预测 Demo 落地计划

## 文档状态

- **状态**：规划中，尚未接入 Poly Agent 产品能力
- **日期**：2026-08-19
- **参考项目**：`refer/Polymer-Agent-main/Polymer-Agent-main`
- **目标**：评估外部 Polymer-Agent 的产品与代码设计，规划 Poly Agent 平台内的聚合物逆向设计 demo 路径
- **当前结论**：适合作为产品场景和技术参考，不适合直接复制代码或模型权重进入主仓库；建议先做静态或预计算 demo，再评估受控算法包接入

## 1. 背景与问题定义

Polymer-Agent 是一个面向早期聚合物发现的 LLM Agent 原型。用户可以用自然语言提出目标性质，例如“生成一个电子亲和能接近 3.2 eV 的聚合物，并限制带隙和介电常数”。系统由 LLM 负责理解请求、选择工具和解释结果，由专业模型负责结构生成和性质预测。

该场景与 Poly Agent 的产品定位高度匹配：

1. 用户从材料研发目标出发，而不是从模型参数出发。
2. LLM 只负责规划与解释，不直接替代科学计算。
3. 候选结构需要经过模型预测、结构校验和可合成性评分。
4. 结果可以进入 ResearchEngine、ComputeEngine、报告和人工评审链路。

因此，本项目适合作为 Poly Agent “自然语言目标 → 候选结构 → 性质预测 → 后续计算/实验建议”的高价值 demo 参考。

## 2. 参考项目解读

### 2.1 整体架构

Polymer-Agent 使用 MCP 将两类模型能力暴露给 Gemini CLI：

| 组件 | 目录 / 配置 | 作用 |
| --- | --- | --- |
| 用户入口 | Gemini CLI / 终端 | 用户输入自然语言，LLM 解析目标和约束 |
| MCP 配置 | `.gemini/settings.json` | 注册 `Generation_mcp` 与 `Property_mcp` |
| 生成服务 | `OMG_mcp/main.py` | 在 VAE 潜空间中优化目标性质，并解码为聚合物 SMILES |
| 性质预测服务 | `TransPolymer_mcp/main.py` | 使用 TransPolymer 预测 SMILES 的多项性质 |
| 化学校验 | RDKit / SA Score | 校验 SMILES 有效性并估计合成可及性 |

顶层 `main.py` 试图扮演 coordinator，但当前副本缺失其引用的 `extensions`、`server_extensions` 和 `prompts` 模块；同时存在无限循环导致后续 MCP 启动不可达的问题。因此实际可用路径是 `.gemini/settings.json` 直接启动两个子 MCP Server。

### 2.2 生成服务流程

`OMG_mcp` 的核心是潜空间逆向设计：

1. 加载 VAE Encoder、Decoder、性质预测头、scaler 和编码表。
2. 将用户目标转换为主目标性质、目标值、容差和约束范围。
3. 采样若干 latent seed。
4. 使用梯度优化让 latent 对应的预测性质逼近目标。
5. 将优化后的 latent 解码为 SELFIES，再转换为 SMILES。
6. 使用 RDKit 校验并规范化 SMILES。
7. 按目标性质距离排序，输出前若干个候选。
8. 可选计算 SA Score，作为合成可及性参考。

该实现支持：

- **单性质优化**：只优化一个目标性质。
- **多性质约束优化**：优化一个主目标，同时限制其他性质范围。

### 2.3 性质预测服务

`TransPolymer_mcp` 包装 TransPolymer 模型，支持以下性质：

| 属性 | 含义 | 单位 |
| --- | --- | --- |
| `PE_I` | 电导率 | log S/cm |
| `Egb` | 体相带隙 | eV |
| `Eea` | 电子亲和能 | eV |
| `EPS` | 介电常数 | 无量纲 |
| `OPV` | 光伏转换效率 | % |

输入为聚合物 SMILES 列表，输出为对应性质的预测值列表。`predict_all_properties` 可一次性预测全部支持的性质。

### 2.4 值得借鉴的产品思想

#### LLM 不直接编造化学结论

Polymer-Agent 的关键优点是让 LLM 调用专业模型，而不是让 LLM 直接生成一个“看起来合理”的分子结构。该原则应成为 Poly Agent 聚合物逆向设计能力的硬边界：

- LLM 负责理解目标、拆解约束、选择工具和解释结果。
- 生成模型负责候选结构。
- 预测模型负责性质复核。
- 平台负责运行记录、审计、来源和人工评审。

#### 高层工具与底层工具分层

参考项目同时提供：

- 高层能力：`optimize_polymer_properties`
- 底层能力：`load_model`、`optimize_latents`、`decode_latents`

这种分层对 Poly Agent 有直接参考价值。前端和普通用户应使用高层 API，助手和调试场景可以在受控条件下展示底层步骤。

#### 性质注册表

参考项目使用 `PROPERTY_REGISTRY` 维护属性代码、名称、单位和别名。Poly Agent 应借鉴该设计，在前端、后端、算法包和报告中统一性质语义，避免同一个缩写在不同页面表示不同含义。

#### 候选结果需要可解释维度

候选结构不应只返回 SMILES，还应返回：

- 预测性质
- 与目标的偏差
- 是否满足约束
- 有效性校验结果
- SA Score 或其他可合成性参考
- 是否与训练集重复
- 模型版本和权重信息
- 来源、引用与使用边界

#### 闭环校验

参考项目的论文描述中强调：LLM 可以提议结构修改，但修改后的结构必须再用性质预测模型复核，不能直接相信 LLM 的化学推理。该闭环与 Poly Agent 的“任务优先、证据驱动、人工可控”原则一致。

## 3. 代码与工程问题评估

### 3.1 顶层入口不可直接复用

当前 `main.py` 存在以下问题：

1. 引用的模块不存在。
2. `subprocess.Popen` 未正确传递完整启动参数。
3. `while True: pass` 阻塞后续 `mcp.run()`。
4. 注册系统与实际 FastMCP 对象之间没有建立有效连接。

因此，不建议将顶层 coordinator 作为 Poly Agent 的实现基础。

### 3.2 路径与环境硬编码

代码和 checkpoint 中存在大量 `/home/vani/...`、`/home/sk77/...` 绝对路径。换机器后模型加载、VAE 目录和 property head 均无法稳定复现。

Poly Agent 接入时必须改为：

- 环境变量或托管资源配置。
- 权重路径由算法资源服务解析。
- 模型版本与权重 hash 进入运行记录。
- 禁止将权重提交进 git。

### 3.3 依赖和权重不完整

参考仓库要求额外安装两个本地库：

- OpenMacromolecularGenome 相关 fork
- TransPolymer 相关 fork

当前副本没有完整 vendor 这些 Python 包。TransPolymer 下游 checkpoint 也不完整，部分文件是 LFS 指针或缺失。即使本地存在部分 OMG 权重，也不能视为开箱即用的完整服务。

另外，参考项目的依赖组合较重，包含 Torch、Transformers、RDKit、MCP、NumPy 版本约束等，不能直接合并进 Poly Agent 主后端环境。后续如做真实推理，应使用独立算法运行环境。

### 3.4 状态管理不适合平台化

参考项目使用内存全局字典保存模型对象：

- `GLOBAL_MODEL_STATE`
- `MODEL_SESSIONS`

存在的问题：

1. 无 TTL 和引用计数，容易内存泄漏。
2. 服务重启后状态丢失。
3. 无法自然映射到 Poly Agent 的 AlgorithmRun。
4. 缺少多用户并发和资源配额治理。
5. 无法跨 worker 调度。

Poly Agent 应复用现有算法运行时、任务生命周期和 managed resource 机制，而不是照搬内存 session 字典。

### 3.5 输出契约不够 JSON 友好

部分工具直接返回 NumPy 数组或 Torch Tensor。真实 API 应显式转换为 JSON 安全类型，并处理 NaN、Inf、空候选、结构解析失败和模型加载失败。

### 3.6 约束与校验逻辑存在缺陷

已识别的问题包括：

1. `schemas/property.py` 期望统计分布字段，但 `constraints.json` 实际是约束示例。
2. 单性质优化器在优化完成后才检查额外约束，检查时机错误。
3. 解码结果会省略主目标性质，只返回其他性质，不利于用户判断目标达成度。
4. README 中的“结构修改”“SC Score”“chemistry-aware constraints”未在当前代码中形成完整、独立、可测试的能力。

### 3.7 生成结果边界

论文和代码都显示，SMILES 能否被 RDKit 解析并不等价于聚合物重复单元语义完全正确。部分生成结果可能缺少两个星号连接位点。Poly Agent 的结果页必须明确区分：

- 字符串有效
- RDKit 可解析
- 满足聚合物重复单元表示
- 满足目标性质
- 具备合成参考价值

### 3.8 许可证与合规风险

当前评估到的许可证状态：

| 组件 | 许可证状态 | 对 Poly Agent 的影响 |
| --- | --- | --- |
| Polymer-Agent 主仓库 | 未看到明确 LICENSE | 不建议直接复制代码进入主仓库 |
| OpenMacromolecularGenome 相关 fork | 携带 GPL-3.0 | 商用或对外分发前需法务评估 |
| TransPolymer 相关 fork | 声明 Apache-2.0 | 需保留声明和引用，但合规压力相对较小 |

因此，推荐策略是：

1. 仅作为方法与产品参考。
2. 不 vendor 上游代码。
3. 如需真实推理，以独立算法包或外部受控服务接入。
4. UI 必须展示来源、论文、机构和许可证边界。
5. 商用前完成法务审查。

## 4. Poly Agent 产品设计建议

### 4.1 产品定位

建议新增一个“聚合物逆向设计”演示场景：

> 用户提出目标性质和约束 → 平台生成候选聚合物结构 → 模型预测性质 → 校验与排序 → 进入计算、报告或人工评审。

该能力不应定位为“自动发现可实验合成材料”，而应定位为：

**面向早期筛选的候选结构生成与模型评估工具。**

### 4.2 页面信息架构

建议输入区包含：

- 目标性质选择。
- 目标值或范围。
- 其他性质约束。
- 候选数量。
- 随机种子。
- 生成模式：单性质 / 多性质约束。
- 模型选择。
- 运行资源配置。

建议过程区展示：

1. 请求解析结果。
2. 模型和权重信息。
3. 潜空间优化进度。
4. 候选解码进度。
5. 结构校验结果。
6. 性质预测结果。
7. 可合成性评分。
8. 候选过滤原因。

建议结果卡片包含：

- 2D 结构图。
- SMILES 和复制按钮。
- 预测性质表。
- 与目标的偏差。
- 约束满足状态。
- SA Score。
- 有效性标签。
- 训练集重复度或 novelty 指标。
- 模型版本。
- 来源和引用。

建议后续动作包含：

- 加入 ResearchEngine。
- 转入 ComputeEngine。
- 生成报告。
- 导出候选列表。
- 交给人工评审。

### 4.3 数据契约草案

建议后端定义统一请求 schema：

```text
InverseDesignRequest {
  target_property
  target_value 或 target_range
  tolerance
  constraints
  num_candidates
  seed
  generation_mode
  model_id
  runtime_options
}
```

建议统一候选结果 schema：

```text
InverseDesignCandidate {
  candidate_id
  smiles
  structure_image
  predicted_properties
  target_distances
  constraint_status
  sa_score
  validity
  novelty
  model_info
  attribution
}
```

该契约应由后端 Pydantic schema、算法包 `polyagent.algorithm.yaml`、前端类型和报告生成器共享，避免用松散 dict 贯穿全链路。

## 5. 代码设计建议

### 5.1 以算法包而不是 MCP Server 接入

Poly Agent 已有垂类算法包、运行时边界、输入输出契约、AlgorithmRun 和 artifact 机制。因此第一版真实推理不建议直接引入 MCP Server，而应封装为标准算法包。

推荐入口：

```text
entrypoint: src.handler:generate
loader: src.handler:load
```

推荐输入：

```json
{
  "target_property": "Eea",
  "target_value": 3.2,
  "tolerance": 0.1,
  "constraints": {
    "Egb": [1.0, 2.0]
  },
  "num_candidates": 5,
  "seed": 42
}
```

推荐输出：

```json
{
  "candidates": [
    {
      "candidate_id": "CAND-001",
      "smiles": "*...*",
      "predicted_properties": {},
      "target_distances": {},
      "constraint_status": {},
      "sa_score": 3.4,
      "validity": {
        "rdkit_valid": true,
        "polymer_cru_valid": true
      }
    }
  ]
}
```

### 5.2 内部模块分层

算法包内部建议拆为：

| 模块 | 职责 |
| --- | --- |
| `contracts.py` | 请求、约束、候选结果 schema |
| `property_registry.py` | 性质代码、名称、单位、别名和有效范围 |
| `model_loader.py` | 权重加载、设备选择、模型缓存和健康检查 |
| `optimizer.py` | 潜空间优化与约束惩罚 |
| `decoder.py` | latent 到 SELFIES / SMILES |
| `validator.py` | RDKit 校验、聚合物重复单元校验、novelty |
| `scoring.py` | SA Score 等可合成性参考 |
| `handler.py` | 平台入口和编排 |

### 5.3 运行治理要求

真实推理算法包必须满足：

1. 独立 Python 环境，不污染主后端环境。
2. 模型权重存放在 artifact 或 managed resource，不提交 git。
3. 支持超时、取消和失败结构化返回。
4. 支持资源声明：CPU / memory / GPU。
5. 记录模型版本、权重 hash、依赖 lock、随机种子和输入快照。
6. 输出全部为 JSON 安全类型。
7. 关键模块具备单元测试和 fake model e2e 测试。

## 6. Demo 落地计划

### Phase 0：静态或预计算产品 demo

目标：用最低成本验证产品叙事、页面结构和用户理解成本，不引入模型运行风险。

#### 行动项

- [ ] 确认 demo 目标用户和核心演示脚本。
- [ ] 明确候选数据来源：论文示例、离线预计算结果或人工构造示例。
- [ ] 设计页面入口、导航位置和页面标题。
- [ ] 设计输入表单、执行过程、候选卡片和空态。
- [ ] 定义候选结果 JSON fixture。
- [ ] 明确“示例数据 / 预计算结果 / 非实时生成”的展示边界。
- [ ] 完成前端静态页面或只读 API demo。
- [ ] 通过桌面和移动端视觉检查。
- [ ] 补充来源、引用、许可证和使用边界文案。

#### 验收标准

- 用户能理解“输入目标性质 → 得到候选结构”的闭环。
- 每个候选能同时看到结构、SMILES、性质、目标偏差和约束状态。
- 页面不会误导用户认为结果已经实验验证或可直接合成。
- 来源与引用清晰可见。
- 不引入上游 GPL 代码和模型权重。

### Phase 1：受控算法包技术 demo

目标：在独立运行时中接入一个小规模、可复现的生成或预测算法包，验证 AlgorithmRun、资源、结果和前端联动。

#### 行动项

- [ ] 完成 OpenMacromolecularGenome / TransPolymer 权重与许可证可行性复核。
- [ ] 确定第一版能力边界：仅生成、仅预测，或生成 + 预测。
- [ ] 建立独立算法包目录。
- [ ] 定义 `polyagent.algorithm.yaml` 输入输出契约。
- [ ] 实现性质注册表和约束校验。
- [ ] 实现模型加载和权重 hash 记录。
- [ ] 实现潜空间优化或预测推理。
- [ ] 实现候选结构解码与 JSON 安全输出。
- [ ] 实现 RDKit 和聚合物重复单元校验。
- [ ] 实现 SA Score 计算。
- [ ] 建立本地 fixture 测试和 fake model e2e 测试。
- [ ] 在算法包运行时完成小样本真实推理验证。
- [ ] 接入 AlgorithmRun 和运行历史。
- [ ] 前端从静态数据切换为真实 AlgorithmRun 结果。
- [ ] 完成超时、失败和资源不足场景测试。

#### 验收标准

- 同一请求在固定 seed 下可复现候选列表。
- 模型路径、版本、权重 hash、随机种子和运行参数可追溯。
- 无效 SMILES、空候选和模型失败均返回结构化状态。
- 算法包运行在独立环境中，不影响主后端依赖。
- 至少一个端到端测试和一个小样本真实推理记录。
- 前端能展示执行计划、候选结果和失败原因。

### Phase 2：闭环扩展与生产化评估

目标：将候选结构接入 Poly Agent 的计算、研究流程和报告链路，并评估是否具备生产使用条件。

#### 行动项

- [ ] 支持候选结构转入 ComputeEngine。
- [ ] 支持候选结构加入 ResearchEngine ProblemSpec。
- [ ] 支持候选比较视图和筛选。
- [ ] 支持生成逆向设计报告。
- [ ] 接入模型不确定度或适用域提示。
- [ ] 接入训练集相似度或 novelty 指标。
- [ ] 支持多模型结果对比。
- [ ] 支持人工评审和 Gate。
- [ ] 补充模型评估数据集、指标和失败案例。
- [ ] 完成安全、资源和许可证审查。
- [ ] 明确是否能从 demo 升级为长期能力。

#### 验收标准

- 用户可以从候选结构发起后续计算。
- ResearchEngine 中能追溯候选来源、模型输出和人工决策。
- 报告能清楚区分模型预测、计算结果和实验事实。
- 生产化风险、许可证和资源边界有明确结论。

## 7. 本期不做什么

为控制风险，本计划明确以下事项不在第一版执行：

1. 不 vendor `refer/Polymer-Agent-main` 整仓代码。
2. 不把模型权重提交进仓库。
3. 不直接把参考项目 MCP Server 暴露给前端。
4. 不把上游依赖合并进 Poly Agent 主后端环境。
5. 不让 LLM 未经模型校验直接返回化学结论。
6. 不宣称生成结果可直接实验合成。
7. 不在许可证未审查前对外分发上游模型或代码。

## 8. 来源与引用

| 来源 | 用途 | 链接 |
| --- | --- | --- |
| Polymer-Agent | LLM Agent 编排、MCP 工具分层和产品场景参考 | https://github.com/BaratiLab/PolyAgent |
| Polymer-Agent 论文 | 方法、实验和使用边界参考 | https://arxiv.org/html/2601.16376v1 |
| Polymer-Agent PMC 页面 | 论文全文和表格参考 | https://pmc.ncbi.nlm.nih.gov/articles/PMC13169346/ |
| OpenMacromolecularGenome | 聚合物生成模型和方法来源 | https://github.com/TheJacksonLab/OpenMacromolecularGenome |
| TransPolymer | 聚合物性质预测方法来源 | https://github.com/ChangwenXu98/TransPolymer |

后续如果开始实现页面或算法包，需要同步更新：

- `doc/polyagent-attribution-source-matrix.md`
- `backend/app/services/attribution_service.py`
- 算法包 `polyagent.algorithm.yaml` 的 developer、organization、source_url、citation 和 license 字段

## 9. 状态记录

| 日期 | 状态 | 说明 |
| --- | --- | --- |
| 2026-08-19 | 已完成参考评估 | 完成 `refer/Polymer-Agent-main` 本地代码、上游仓库、论文和许可证风险初步评估；形成三阶段 demo 计划；尚未开始产品实现 |
| 2026-08-19 | 文档已纳入文档地图 | 新增本文档，并在 `doc/README.md` 的“进度、计划与验收”索引中登记 |
| 2026-08-19 | 文档已更名 | 将标题和文件名调整为“聚合物自然语言逆向设计与性质预测 Demo 落地计划”，突出业务能力而非外部项目名称；内容和计划边界不变 |
