# 多站点协同实验优化与联邦贝叶斯试点计划

## 文档状态

- **状态**：规划中，尚未进入产品实现
- **日期**：2026-08-19
- **参考项目**：`refer/Federated-Bayesian-Optimization-main`
- **业务目标**：面向多个实验室、基地或合作单位的材料配方优化场景，在原始研发数据不出域的前提下，共享受控模型摘要并协同推荐下一批实验
- **当前结论**：适合作为后期可选的“多站点协同实验优化”能力推进；不应把 Poly Agent 定位成通用联邦学习平台。短期先吸收产品与架构思想，中期做模拟 FedBO 试点，长期在权限、隐私预算、站点 Agent 和审计体系成熟后交付

## 1. 背景与问题定义

Poly Agent 当前的优化链路已经具备中心式闭环基础：

```text
Campaign 候选池
  ↓
planner 生成 suggestion
  ↓
ComputeEngine / Experiment Dispatch 执行
  ↓
observation 回填
  ↓
下一轮推荐、审计和报告
```

同时，`alchemist_core` 已提供变量定义、DoE / OED、GP 代理模型、EI / PI / UCB / qEI / qUCB 等采集策略和诊断可视化能力。

但部分企业场景中，同一类材料研发问题会分布在多个站点：

1. 集团内有多个实验室或生产基地；
2. 高校、院所和企业联合攻关；
3. 不同站点各自积累了少量私有实验数据；
4. 原始配方、实验记录和性能数据因合规、竞争或知识产权原因不能直接集中；
5. 单站点数据量不足以训练稳定模型，单独优化试错成本高；
6. 实验执行能力强，但缺乏跨站点协同的统一编排和审计。

这类客户需要的不是“通用联邦训练框架”，而是一个可理解、可审批、可追溯的业务能力：

> 多个站点在不交出原始研发数据的情况下，共同加速同一材料优化任务的实验寻优。

因此本计划将参考项目的 FedBO 方法拆解为 Poly Agent 的可选协同优化能力，而不是直接复制研究代码。

## 2. 参考项目解读

### 2.1 项目定位

`Federated-Bayesian-Optimization-main` 对应论文：

> “An Intelligent Distributed Chemical Twin System for Collaborative Material Discovery”

项目包含三类脚本：

| 文件 | 作用 |
|------|------|
| `SingleBO.py` | 单节点贝叶斯优化基线，模拟一个实验室独立寻优 |
| `FedBOv6.py` | 多客户端联邦贝叶斯优化主流程 |
| `plot.py` | 绘制各客户端实验过程曲线 |

它解决的是材料实验中的高成本黑箱优化问题：每次实验代价较高，需要用已有实验数据训练代理模型，并通过采集函数决定下一步最有价值的实验。

### 2.2 数据与搜索空间

核心数据文件为 `data/experimentdata.xlsx`，本地核对结果：

- 约 452 条模拟实验记录；
- 输入变量包括 `Bi(%)`、`Fe(%)`、`Co(%)`、`Cu1(%)`、`Ni(%)`、`Mn(%)`、`L1(%)`；
- 目标变量为 `K`，表示材料性能，越大越好；
- 百分比输入在代码中除以 100；
- `K` 被映射到约 `[0.2, 0.6]` 的建模范围。

代码搜索空间为：

```text
Bi:      [0.7, 1.0]
Fe/Co/Cu/Ni/Mn: [0, 0.3]
L1:      {0, 1}
```

优化器给出的理论推荐点会映射到有限候选实验池中距离最近的可行配方。

### 2.3 单节点 BO 基线

`SingleBO.py` 的流程：

```text
少量初始实验
  ↓
训练 GP 代理模型
  ↓
EI 推荐下一个理论点
  ↓
映射到候选池最近可执行配方
  ↓
读取模拟真实性能
  ↓
加入本地训练数据
  ↓
继续循环直到找到目标性能
```

关键实现：

- 使用 `scikit-optimize.Optimizer`；
- GP 使用 Matérn 核；
- 采集函数为 EI；
- 因为优化器默认最小化目标，代码传入 `-y`；
- 找到目标值后额外运行若干步，用于记录优化过程。

该基线对应 Poly Agent 当前单个 Campaign / Alchemist 会话的中心式优化模式。

### 2.4 FedBO 单轮流程

`FedBOv6.py` 默认模拟 3 个客户端，即 3 个实验室。每个客户端拥有不同的初始实验数据，并在本地维护自己的 BO 状态。

一轮 FedBO 的流程如下：

```text
第 r 轮开始
├── 每个客户端本地 BO 各自提出一个候选实验
├── 每个客户端用本地 X/y 训练本地 GP
├── 每个客户端从全局候选池随机选择 20 个诱导点
├── 本地 GP 输出这些诱导点的预测性能
├── 预测值裁剪到 [0, 1]
├── 加入 Laplace 噪声
├── 仅上传“诱导点 + 加噪预测值”
├── 中央端汇总所有客户端摘要并去重
├── 中央端在摘要点上训练全局 GP
├── 全局 GP 在候选池中推荐一个点
├── 全局 GP 重新评估各客户端本地推荐点
├── 选择 1 个全局推荐点 + N-1 个本地推荐点
├── 分配给 N 个客户端执行
├── 客户端获得实验结果并更新本地模型
└── 候选从全局池移除，进入下一轮
```

其中 N 为在线客户端数量。3 个客户端时，每轮通常推进 3 个实验：1 个来自全局模型，2 个来自本地模型。

### 2.5 隐私扰动机制

参考代码对本地 GP 预测值执行：

```text
clip 到 [0, 1]
  ↓
加入 Laplace noise
```

硬编码参数为：

- 敏感度 `fsensitivity = 1.0`
- 隐私预算 `epsilon = 2.0`
- 噪声尺度 `sensitivity / epsilon = 0.5`

设计意图是让中央端只能获得模糊模型摘要，而不能精确反推客户端原始实验记录。

需要注意：该实现是“扰动式模型摘要共享”，不能直接对外承诺生产级差分隐私保证。主要缺口包括：

1. 未定义严格的相邻数据集和机制敏感度证明；
2. 未记录多轮隐私预算组合；
3. 未提供安全聚合或最小参与人数阈值；
4. 候选点编号和推荐结果本身可能携带业务信息；
5. 没有恶意站点投毒防御；
6. 没有出域 payload 审批和站点侧留痕。

### 2.6 实验效果观察

仓库代码注释记录了多组三客户端 FedBO 实验，平均找到目标值的轮数在十几到二十轮左右；仓库中的单节点结果需要更多轮才能找到目标值。

由于 FedBO 每轮有多个客户端并行实验，不能只比较轮数，还要比较总实验次数。即使如此，参考结果仍支持一个方向性判断：

> 多站点共享受控模型摘要，有机会比各站点独立 BO 更快接近最优区域。

该判断来自模拟数据和小规模重复实验，不能直接等价为真实多实验室生产收益。

## 3. 能力与风险评估

### 3.1 值得借鉴的能力

| 参考能力 | Poly Agent 可借鉴点 |
|----------|----------------------|
| 本地 BO + 全局协调 | 将 Alchemist 会话下沉为站点本地模型，中央只做协同编排 |
| 原始数据不出域 | 符合高敏客户对研发数据安全的核心诉求 |
| 诱导点模型摘要 | 用少量预测摘要代替完整实验数据上传 |
| 全局 + 本地推荐混合 | 平衡跨站点探索和站点经验，降低全局模型噪声误导 |
| 多站点并行实验 | 缩短墙钟时间，并提升候选探索覆盖 |
| 推荐结果可解释 | 与 Campaign suggestion 的 score、reason、confidence 和 metadata 契约兼容 |
| 实验过程留痕 | 可复用 Audit、AlgorithmRun、Observation 和 Report 链路 |

### 3.2 参考项目局限

| 局限 | 影响 | Poly Agent 应对 |
|------|------|-----------------|
| 客户端仅在单进程内模拟 | 不是真实联邦网络 | 后期设计独立站点 Agent 和异步协议 |
| 全部客户端同步在线 | 无法处理掉线和慢站点 | 轮次状态机、超时、法定人数和异步补齐 |
| 中央端直接查询模拟真实结果 | 与真实实验执行不符 | 通过 ComputeEngine / Experiment Dispatch / observation 回流 |
| 数据列名和搜索空间硬编码 | 无法适配不同材料问题 | 复用 ProblemSpec、变量 schema 和候选契约 |
| 只支持单目标 | 无法覆盖多目标材料优化 | 预留 objective schema 和多目标采集扩展 |
| 假设站点无系统偏差 | 真实设备和方法可能不一致 | 增加站点能力、校准和批次效应治理 |
| 隐私机制不完整 | 不能承诺严格 DP | 独立 PrivacyPolicy、预算账本和出域审批 |
| 无恶意站点防御 | 存在投毒风险 | 稳健聚合、异常检测、站点信誉和人工 Gate |
| 研究脚本工程质量较弱 | 不适合直接复制 | 只借鉴算法思想，重用平台内模块实现 |

## 4. 产品定位与边界

### 4.1 对外命名

推荐产品名：

> 多站点协同实验优化

技术方案名：

> 联邦贝叶斯优化 FedBO 试点

不推荐对外统称为：

> 通用联邦学习平台

原因：

1. “联邦学习”容易被理解成通用分布式神经网络训练；
2. Poly Agent 的业务价值在材料研发闭环，不在通用 ML 基础设施；
3. 参考项目的核心是联邦贝叶斯优化，不是 FedAvg 式模型训练；
4. 过度承诺会带来隐私、安全和合规风险。

### 4.2 目标用户

| 角色 | 核心诉求 |
|------|----------|
| 材料科学家 | 看懂为什么推荐这些配方，并判断是否采纳 |
| 实验平台管理员 | 将任务分配给可执行站点，跟踪执行状态 |
| 站点负责人 | 确认本站数据不出域，审批出域摘要 |
| 算法与计算工程师 | 管理 GP、采集函数、模型版本和运行诊断 |
| 研发负责人 | 查看协同收益、成本、贡献和审计记录 |
| 安全 / 合规人员 | 审查隐私策略、出域 payload 和权限边界 |

### 4.3 适用场景

满足以下条件时优先考虑：

1. 至少 3 个可持续参与的实验室或基地；
2. 各站点优化相同或高度相近的材料问题；
3. 输入变量、目标定义和量纲可以统一；
4. 各站点有少量可用的历史 observation；
5. 实验成本高，减少试错有明确商业价值；
6. 原始数据因合规或 IP 原因不能集中；
7. 客户愿意部署本地 Agent 或受控运行环境；
8. 需要统一审计和贡献追踪。

### 4.4 暂不适用场景

以下场景优先使用现有中心式 Alchemist / Campaign：

1. 单团队、单站点、数据本来已经进入平台；
2. 只有 1-2 个站点，协同收益有限；
3. 各站点目标函数不同；
4. 数据 schema 无法统一；
5. 本地数据量过小，代理模型不稳定；
6. 客户要求严格差分隐私或强安全证明，但平台尚未完成隐私工程；
7. 当前主要瓶颈是真实计算、设备执行或模型服务接入，而不是跨站点协同。

### 4.5 与轻量联邦推理的区别

平台既有安全方案中的“轻量联邦推理”与 FedBO 不是同一能力：

| 维度 | 轻量联邦推理 | FedBO 多站点协同优化 |
|------|--------------|----------------------|
| 主要动作 | 标准化模型在客户本地推理 | 多站点共同优化实验策略 |
| 中央下发 | 模型包、算法包、运行依赖 | 协同策略、全局候选或聚合结果 |
| 本地上传 | 最终推理结果 | 加噪模型摘要和状态回执 |
| 是否多轮 | 通常单次或任务级 | 多轮闭环 |
| 是否更新模型 | 通常不更新 | 本地模型持续更新 |
| 典型价值 | 高敏数据不出域使用算法 | 多站点共享经验并减少实验 |
| 工程复杂度 | 中等 | 高 |

两者可以在安全底座上复用，但不能在产品文案中混用。

## 5. 产品体验设计

### 5.1 创建协同优化任务

入口建议放在：

```text
/optimization/campaigns
/optimization/collaborative
```

创建向导包含：

1. 选择或创建底层 Campaign；
2. 定义统一 ProblemSpec、变量 schema 和目标；
3. 邀请站点并确认站点能力；
4. 配置站点变量范围和可执行约束；
5. 选择协同模式：
   - 中心式多站点执行；
   - 模拟 FedBO；
   - 真实 FedBO；
6. 配置隐私策略；
7. 配置轮次、批量和 Gate 规则；
8. 发起站点授权和加入确认。

### 5.2 轮次状态视图

每轮展示：

```text
等待站点摘要
  ↓
聚合全局模型
  ↓
生成本轮推荐
  ↓
人工 Gate
  ↓
分配实验
  ↓
等待 observation
  ↓
进入下一轮
```

每个站点显示：

- 在线 / 离线；
- schema 版本；
- 本地模型版本；
- 已上传摘要数量；
- 本轮实验任务；
- 任务执行状态；
- 隐私预算剩余；
- 最近错误原因。

### 5.3 出域摘要预览与审批

站点负责人应能查看并批准本轮真正出域的内容：

```text
本轮站点 A 将上传：
- 20 个模型预测摘要
- 0 条原始实验记录
- 0 个完整配方
- 0 个分子结构文件
- 噪声机制：Laplace
- 本轮 epsilon：2.0
- 累计 epsilon：18.0
```

审批动作必须进入审计记录。站点可以拒绝本轮上传，系统应允许轮次降级或等待法定站点数。

### 5.4 推荐 Gate

FedBO 不应直接把推荐任务发给实验系统。推荐生成后先进入 Gate，允许用户：

1. 查看每个候选的来源：全局模型 / 本地模型 / 混合；
2. 查看全局分数和本地分数；
3. 查看推荐理由和不确定性；
4. 查看站点可执行性；
5. 拒绝危险或不可执行配方；
6. 调整站点任务分配；
7. 暂停或终止本轮。

### 5.5 结果与收益视图

建议提供：

1. 当前最优值进展曲线；
2. 累计实验次数对比；
3. 单站点独立 BO、中心式多站点和 FedBO 的对照；
4. 每轮推荐来源分布；
5. 站点任务负载；
6. 全局模型不确定性图；
7. 隐私预算消耗；
8. 站点贡献摘要；
9. 失败实验和低置信推荐比例。

### 5.6 审计与报告

每轮至少记录：

- 轮次 ID 和状态；
- 参与站点和版本；
- 输入 schema 快照；
- 模型和算法版本；
- 出域摘要 hash；
- Gate 决策和理由；
- 推荐候选及来源；
 - 实验派发对象；
- observation 回流状态；
- 隐私预算消耗；
- 错误、超时和降级原因。

报告必须区分：

1. 本地模型预测；
2. 全局模型预测；
3. 计算结果；
4. 实验事实；
5. 人工决策。

## 6. 平台架构设计

### 6.1 模块位置

不建议把 FedBO 直接塞进当前同步 `run_planner()` 调用。原因：

1. FedBO 是多轮有状态流程；
2. 需要等待多个站点上传摘要；
3. 需要处理掉线、超时和 Gate；
4. 需要隐私预算和出域审批；
5. 需要站点任务分配和 observation 回流。

建议新增协同编排层：

```text
OptimizationService / Campaign
        ↓
FederationOrchestrator
├── FederationCampaign
├── FederationParticipant
├── FederationRound
├── ModelSummaryPack
├── FederationSuggestion
├── ObservationReceipt
└── PrivacyPolicy / PrivacyLedger
        ↓
Alchemist GP / Acquisition
        ↓
Experiment Dispatch / ComputeEngine
```

当前 `run_planner()` 继续服务中心式 planner。FedBO 编排器内部可以复用 planner scoring 和 Alchemist 模型能力，但不改变现有同步 API 的语义。

### 6.2 领域对象

| 对象 | 关键字段 | 职责 |
|------|----------|------|
| `FederationCampaign` | `federation_campaign_id`、`campaign_id`、`status`、`objective_schema`、`round_policy` | 一次多站点协同优化任务 |
| `FederationParticipant` | `participant_id`、`organization_id`、`endpoint`、`capability`、`schema_version`、`status` | 站点身份、能力和在线状态 |
| `FederationRound` | `round_id`、`round_index`、`status`、`started_at`、`closed_at` | 一轮协同状态和参与记录 |
| `ModelSummaryPack` | `summary_pack_id`、`round_id`、`participant_id`、`candidate_hashes`、`predictions`、`variances`、`privacy` | 站点上传的受控模型摘要 |
| `FederationSuggestion` | `suggestion_id`、`round_id`、`origin`、`assigned_participant_id`、`global_score`、`local_score` | 带来源和站点分配的推荐 |
| `ObservationReceipt` | `receipt_id`、`assignment_id`、`status`、`privacy_mode` | observation 是否回传、本地留存或摘要回传 |
| `PrivacyPolicy` | `mode`、`mechanism`、`epsilon_per_round`、`delta`、`total_budget` | 隐私机制和预算约束 |
| `PrivacyLedger` | `entry_id`、`participant_id`、`round_id`、`epsilon_consumed`、`payload_hash` | 记录累计隐私消耗和出域 payload |

### 6.3 轮次状态机

```text
draft
  ↓
initializing
  ↓
awaiting_join_confirmations
  ↓
awaiting_summaries
  ↓
aggregating
  ↓
proposing
  ↓
gate_review
  ↓
dispatching
  ↓
awaiting_observations
  ↓
round_completed
  ↓
next_round / completed
```

异常分支：

```text
paused
cancelled
failed
degraded_completed
```

状态迁移必须持久化，并允许刷新页面后恢复。

### 6.4 站点 Agent API 预案

真实联邦交付时，每个站点可部署一个轻量 Agent：

```text
GET  /health
POST /federation/campaigns/{campaign_id}/join
POST /federation/rounds/{round_id}/initialize
POST /federation/rounds/{round_id}/summarize
POST /federation/rounds/{round_id}/suggestions
POST /federation/assignments/{assignment_id}/accept
POST /federation/assignments/{assignment_id}/receipt
POST /federation/observations/{assignment_id}/summary
```

设计要求：

1. 所有请求幂等；
2. 原始实验数据不离开 Agent；
3. 出域 payload 先预览再审批；
4. 支持断线后按 round 恢复；
5. 支持站点拒绝任务；
6. 支持模型和 schema 版本校验；
7. 支持安全凭证轮换；
8. 支持本地审计留痕。

### 6.5 数据契约草案

#### ModelSummaryPack

```json
{
  "schema_version": "federation.model_summary.v1",
  "summary_pack_id": "summary-01",
  "federation_campaign_id": "fedcmp-01",
  "round_id": "round-01",
  "participant_id": "site-a",
  "model_info": {
    "model_type": "gp_matern",
    "model_version": "local-v3",
    "feature_schema_version": "problem-spec.v1"
  },
  "points": [
    {
      "candidate_hash": "sha256:...",
      "prediction": 0.42,
      "variance": 0.03
    }
  ],
  "privacy": {
    "mechanism": "laplace",
    "epsilon": 2.0,
    "delta": null,
    "clipping_range": [0.0, 1.0],
    "accountant_version": "dp-ledger.v1"
  }
}
```

#### FederationSuggestion

```json
{
  "schema_version": "federation.suggestion.v1",
  "suggestion_id": "fedsug-01",
  "round_id": "round-01",
  "candidate_id": "cand-01",
  "candidate_key": "FORMULA-A",
  "origin": "global",
  "assigned_participant_id": "site-b",
  "global_score": 0.86,
  "local_scores": {
    "site-a": 0.71,
    "site-b": 0.83,
    "site-c": 0.64
  },
  "reason": "全局模型预测性能最高，且站点 B 可执行",
  "confidence": "medium",
  "metadata": {
    "uncertainty": 0.08,
    "exploration_weight": 0.2
  }
}
```

#### PrivacyPolicy

```json
{
  "schema_version": "federation.privacy.v1",
  "mode": "dp_summary",
  "mechanism": "laplace",
  "epsilon_per_round": 2.0,
  "delta": null,
  "clipping_range": [0.0, 1.0],
  "min_participants": 3,
  "total_epsilon_budget": 60.0,
  "allow_raw_observation_upload": false
}
```

### 6.6 与现有模块的复用关系

| 现有模块 | FedBO 中的用途 |
|----------|----------------|
| Campaign | 候选池、目标、suggestion、observation 和审计基础 |
| Alchemist | 变量、GP、采集函数、模型诊断和可视化 |
| Experiment Dispatch | 将推荐分配到站点或外部实验系统 |
| ComputeEngine | 需要计算代替实验时承接任务 |
| AlgorithmRun / artifact | 保存模型摘要、配置快照和运行产物 |
| Attribution | 标注 FedBO 方法、论文、代码和实现边界 |
| 数据安全方案 | 复用出域原则、租户隔离和审计要求 |

### 6.7 候选标识要求

参考代码使用候选池数组下标，生产实现不能沿用。

必须使用稳定标识：

```text
candidate_id
candidate_hash = sha256(schema_version + normalized features + candidate version)
```

原因：

1. 候选池会删除、分页和同步；
2. 多站点版本可能不一致；
3. 数组下标在异步系统中容易漂移；
4. hash 便于 payload 审计和去重。

## 7. 分阶段落地计划

### Phase 0：需求确认与设计预研

目标：确认真实客户场景和产品口径，不启动生产代码。

#### 行动项

- [ ] 访谈至少 2 个潜在多实验室 / 多基地场景客户。
- [ ] 明确是否真的存在“数据不能集中但愿意协同优化”的需求。
- [ ] 梳理各站点目标属性、变量 schema、单位和测试方法差异。
- [ ] 明确第一版只支持单目标还是必须支持多目标。
- [ ] 确认最小参与站点数、实验批量和轮次节奏。
- [ ] 定义“多站点协同实验优化”的统一产品文案。
- [ ] 区分轻量联邦推理、FedBO 和通用联邦学习的对外口径。
- [ ] 评估法律、合规和客户安全审查关注点。
- [ ] 输出站点能力 schema 和权限矩阵草案。
- [ ] 确认是否将本能力列为 P2 可选能力。

#### 验收标准

- 有清晰的目标客户画像和至少 3 个真实痛点场景。
- 能明确说明哪些数据不出域、哪些摘要会出域。
- 能定义协同收益指标和成本指标。
- 能判断是否值得进入模拟试点。

### Phase 1：中心式多站点协同

目标：先不做联邦模型，验证多站点任务分配、observation 回流和审计的产品价值。

#### 行动项

- [ ] 在 Campaign 上设计 participant / site 扩展字段。
- [ ] 支持站点能力、变量范围和实验约束登记。
- [ ] 支持将 suggestion 分配给指定站点。
- [ ] 复用 Experiment Dispatch Target 表达站点执行能力。
- [ ] 支持站点任务状态和执行结果回流。
- [ ] 支持按站点查看任务负载和完成率。
- [ ] 支持站点级权限和操作审计。
- [ ] 增加多站点任务列表和详情页设计稿。
- [ ] 后端补充领域对象和 API 设计评审。
- [ ] 前端完成可用性走查。

#### 验收标准

- 一个 Campaign 可以将不同推荐分配给多个站点。
- 每条 observation 能追溯到来源站点、suggestion 和执行记录。
- 站点无法查看未授权的完整候选或历史数据。
- 管理员可以查看协同任务的整体进展。
- 不引入任何模型摘要上传，链路稳定可用。

### Phase 2：模拟 FedBO 技术试点

目标：在单后端进程内模拟 3 个虚拟站点，验证 FedBO 算法、UI 解释和审计模型，不暴露给普通生产用户。

#### 行动项

- [ ] 建立模拟数据集和固定随机种子基准。
- [ ] 实现 3 个虚拟站点本地 GP 状态。
- [ ] 复用 Alchemist 的 GP 和采集能力。
- [ ] 实现本地模型摘要生成。
- [ ] 实现可配置 Laplace / Gaussian 扰动。
- [ ] 实现全局摘要聚合 GP。
- [ ] 实现全局推荐 + 本地推荐混合策略。
- [ ] 实现候选稳定 hash。
- [ ] 实现轮次状态机。
- [ ] 实现隐私预算账本。
- [ ] 增加模拟站点掉线和超时场景。
- [ ] 增加异常摘要和空摘要场景。
- [ ] 建立单站点 BO、中心式多站点和 FedBO 对照指标。
- [ ] 输出实验次数、最优值进展和推荐来源统计。
- [ ] 前端增加 feature flag 控制的演示页面。
- [ ] 增加出域摘要预览 mock。
- [ ] 增加 Gate 审核 mock。
- [ ] 补充单元测试、集成测试和端到端 fixture。
- [ ] 完成算法与产品演示脚本。

#### 验收标准

- 相同 seed 下模拟轮次可复现。
- 任意一轮可以解释每个推荐来自全局还是本地模型。
- 中央模拟端不读取虚拟站点原始数据作为 planner 输入。
- 隐私账本能记录每轮和累计预算。
- 站点掉线时轮次可降级、暂停或按法定人数继续。
- 至少一组对照实验显示 FedBO 相对独立 BO 有可解释收益或明确失败原因。
- 演示页面清楚标注“模拟试点，非真实联邦部署”。

### Phase 3：本地 Agent 与真实联邦试点

目标：为愿意私有化部署 Agent 的客户验证真实跨站点协同。

#### 行动项

- [ ] 设计站点 Agent 容器包和运行依赖。
- [ ] 设计站点注册、认证和凭证轮换。
- [ ] 实现站点健康检查和版本协商。
- [ ] 实现站点侧本地模型训练与缓存。
- [ ] 实现出域摘要生成、预览和审批。
- [ ] 实现中央端摘要接收和幂等去重。
- [ ] 实现安全传输和 payload hash 留痕。
- [ ] 实现异步轮次、超时和断线恢复。
- [ ] 实现站点任务领取、拒绝和执行回执。
- [ ] 实现 observation 明文回传、本地留存和摘要回传三种隐私模式。
- [ ] 实现恶意摘要和异常站点的稳健聚合策略。
- [ ] 完成站点级 RBAC 和项目级授权。
- [ ] 完成安全威胁模型评审。
- [ ] 建立客户侧部署手册和运维手册。
- [ ] 开展一个小规模真实或准真实客户试点。

#### 验收标准

- 原始实验数据不出站点边界。
- 每个出域 payload 均可被站点负责人预览、审批和追溯。
- 平台不能绕过隐私策略读取本地原始 observation。
- 站点离线不会阻塞超过配置的超时时间。
- 凭证泄露时支持撤销和轮换。
- 恶意或异常摘要不会直接导致危险实验自动执行。
- 试点客户能理解协同收益、成本和隐私边界。

### Phase 4：生产化与规模化评估

目标：决定是否从试点升级为长期产品能力。

#### 行动项

- [ ] 汇总真实试点收益和失败案例。
- [ ] 评估算法稳定性、站点异质性和模型漂移。
- [ ] 评估隐私预算、投毒防御和合规审查结果。
- [ ] 评估运维成本和客户部署成本。
- [ ] 完成多目标优化扩展设计。
- [ ] 完成更稳健的聚合和校准方案设计。
- [ ] 明确定价、交付和售后服务模式。
- [ ] 决定保留为可选能力、继续投入或停止迭代。

#### 验收标准

- 有真实客户场景下的实验次数、周期和质量收益数据。
- 安全、合规和运维风险有明确结论。
- 产品、算法、部署和支持成本可承受。
- 有清晰的继续 / 停止决策记录。

## 8. 工程任务拆分建议

### 8.1 后端

- [ ] 新增 `FederationCampaign`、`Participant`、`Round`、`SummaryPack` schema。
- [ ] 新增 Federation repository 和状态迁移服务。
- [ ] 新增 `FederationOrchestrator`。
- [ ] 抽象本地模型摘要接口。
- [ ] 抽象全局聚合接口。
- [ ] 抽象推荐来源和打分接口。
- [ ] 新增隐私策略和预算账本。
- [ ] 新增轮次恢复和幂等键。
- [ ] 新增站点任务分配 API。
- [ ] 新增联邦审计事件。
- [ ] 增加模拟站点 fixture。
- [ ] 增加异常和超时测试。

### 8.2 前端

- [ ] 新增多站点协同任务列表。
- [ ] 新增任务创建向导。
- [ ] 新增站点状态卡片。
- [ ] 新增轮次时间线。
- [ ] 新增出域摘要预览与审批组件。
- [ ] 新增 Gate 审核组件。
- [ ] 新增推荐来源解释组件。
- [ ] 新增隐私预算展示。
- [ ] 新增协同收益图表。
- [ ] 增加 feature flag 和权限控制。
- [ ] 增加失败、空态、离线和降级状态。

### 8.3 测试

- [ ] 领域对象 schema 测试。
- [ ] 轮次状态机测试。
- [ ] 候选 hash 稳定性测试。
- [ ] 摘要去重和幂等测试。
- [ ] 隐私预算累计测试。
- [ ] Gate 权限测试。
- [ ] 站点掉线测试。
- [ ] 恶意摘要防御测试。
- [ ] 模拟 FedBO 回归测试。
- [ ] 前端关键路径 Playwright 测试。

## 9. 风险与应对

| 风险 | 表现 | 应对 |
|------|------|------|
| 产品过度承诺 | 用户以为联邦等于绝对隐私 | 明确展示出域内容、噪声机制和边界 |
| 隐私泄露 | 摘要、候选或结果反推敏感信息 | 稳定 hash、预算账本、最小站点数、审批和审计 |
| 投毒攻击 | 异常站点诱导错误推荐 | 稳健聚合、异常检测、站点信誉、人工 Gate |
| 站点异质性 | 设备和方法偏差导致模型不可比 | 站点能力 schema、校准项和批次效应治理 |
| 全局模型噪声过大 | 推荐不稳定 | 全局 / 本地推荐混合，保留站点经验 |
| 异步失败 | 轮次长期挂起 | 超时、法定人数、降级和恢复 |
| 收益不显著 | 客户认为复杂度不值得 | Phase 2 对照实验和真实试点后再推广 |
| 权限不足 | 跨组织数据越权访问 | 先完成组织、项目、站点三级 RBAC |
| 运维复杂 | Agent 部署和升级困难 | 容器化、版本协商、健康检查和回滚 |
| 术语混乱 | 联邦推理、FedBO、联邦训练混淆 | 统一产品术语和销售口径 |

## 10. 决策建议

### 10.1 当前不建议立即主线开发

原因：

1. 平台当前更优先的事项是真实计算、实验执行、模型服务和权限治理；
2. 真实联邦需要站点 Agent、隐私账本、异步状态机和跨组织权限；
3. 参考项目只是单进程模拟，不能直接生产化；
4. 在单站点客户为主的阶段，中心式 BO 更简单可靠。

### 10.2 建议现在做的事情

1. 保留本计划作为 P2 可选能力设计输入；
2. 在后续 Campaign schema 演进时避免阻断 participant / round 扩展；
3. 在安全方案中明确轻量联邦推理与 FedBO 的差异；
4. 收集多实验室客户需求；
5. 用小规模模拟试点验证收益，而不是直接承诺产品功能。

### 10.3 进入真实联邦开发的前置条件

同时满足以下条件后再启动：

1. 至少 3 个可参与的真实或准真实站点；
2. 统一 ProblemSpec 和变量 schema；
3. 组织、项目、站点三级权限可用；
4. 出域审批和审计链路可用；
5. 隐私预算账本完成设计；
6. 客户接受本地 Agent 部署；
7. Phase 2 模拟试点显示可解释收益；
8. 安全和合规评审通过。

## 11. 与其他计划的关系

| 相关文档 | 关系 |
|----------|------|
| `centralized-deployment-data-security-technical-assurance-plan.md` | 复用数据不出域、租户隔离、审计和可选联邦交付原则 |
| `platform-positioning-and-small-iteration-plan.md` | FedBO 支撑“材料研发协作底座”的后期护城河，不改变当前小步迭代优先级 |
| `research-engine-plan-12-product-positioning-evolution.md` | 延续“不做通用 agent 平台，强化领域闭环”的定位 |
| `optimization-workflow-user-guide.md` | 现有中心式实验设计与优化用户路径 |
| `experiment-dispatch.md` | Phase 1 多站点任务分配和执行回流的直接承接模块 |

## 12. 来源与引用

| 来源 | 用途 | 链接 |
|------|------|------|
| Federated-Bayesian-Optimization | FedBO 算法流程、单节点基线、诱导点摘要和扰动机制参考 | https://github.com/pic-ai-robotic-chemistry/Federated-Bayesian-Optimization |
| 论文 “An Intelligent Distributed Chemical Twin System for Collaborative Material Discovery” | 协同材料发现场景和问题定义参考 | 见上游仓库 README |
| Poly Agent `alchemist_core` | 本地 GP、变量、采集函数和诊断能力基础 | 本仓库 |
| Poly Agent Optimization Campaign | 候选、suggestion、observation 和审计基础 | 本仓库 |
| Poly Agent Experiment Dispatch | 站点任务分配和实验执行回流基础 | 本仓库 |

本计划当前仅做文档评估，不修改系统模块、算法页面或工具服务入口。后续如果进入实现阶段，需要同步更新：

- `doc/polyagent-attribution-source-matrix.md`
- `backend/app/services/attribution_service.py`
- 相关前端页面的来源横幅或来源牌
- 算法配置中的方法来源、引用和许可证字段

## 13. 状态记录

| 日期 | 状态 | 说明 |
|------|------|------|
| 2026-08-19 | 已完成参考评估 | 完成 `refer/Federated-Bayesian-Optimization-main` 本地代码、数据和结果文件解读；明确其是单进程模拟 FedBO，不能直接生产化 |
| 2026-08-19 | 已形成产品与架构预案 | 明确“多站点协同实验优化”的产品口径、领域对象、轮次状态机、隐私边界和四阶段落地路线；尚未开始实现 |
