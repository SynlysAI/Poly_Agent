# Auto Research 使用指南

## 一、Auto Research 是什么

Auto Research（自动研发）是 Poly Agent 高分子材料AI研发平台的**自动编排通道**。系统按预定义的十阶段序列自动推进研发流程，在关键阶段（Gate）会暂停并等待人工审批，审批通过后继续推进。

### 适用场景

- 高分子材料的多目标优化（如介电常数、热稳定性等性质优化）
- 需要系统化文献检索 → 结构表示 → 计算预测 → 候选推荐的完整研发流程
- 希望人工把控关键决策点（问题定义、候选推荐、实验执行）的自动化研发

---

## 二、前置条件

1. 已进入 ResearchEngine 研发引擎页面（导航栏 → 研发引擎）
2. 已完成步骤 1：创建或选择一个 **ProblemSpec**（研发任务定义）
3. 在步骤 2 中选择了 **"AutoResearch 自动编排"** 执行路径

---

## 三、操作流程

### 3.0 一键示例入口

如果只是想快速验证审批流程，可以在 ResearchEngine 页面打开示例流程，选择 **"AutoResearch 审批示例"**。系统会自动创建：

- 一个氟基高分子 ProblemSpec
- 一个 `autoresearch` ExecutionDecision
- 一个已启动的 ResearchRun

示例启动后会停在 `PROBLEM_SPEC` 的 `blocked_approval` 状态，可以直接进入 Gate 审批演练。

### 3.1 进入 Auto Research 工作台

1. **步骤 1 - 研发任务定义**：在左侧工作流树中点击步骤 1，创建或选择已有的 ProblemSpec。ProblemSpec 定义你的研发目标（如氟基高分子材料的介电常数和热稳定性优化）。

2. **步骤 2 - 执行路径选择**：点击"AutoResearch 自动编排"卡片，或点击"选择自动模式"按钮。系统会创建执行决策（ExecutionDecision）。

3. **步骤 3 - AutoResearch 编排**：自动进入工作区，显示 ResearchRun 面板。

### 3.2 创建 ResearchRun

在 ResearchRun 面板中：

1. 从下拉列表中选择你的 **ProblemSpec**
2. 选择**材料 Profile**（氟基高分子 / 碳基高分子 / 硅基高分子）
3. 设置**最大迭代次数**（建议首次使用设为 1-5）和**批次大小**（每次推荐的候选数，建议 5-10）
4. 可选填写描述信息
5. 点击 **"创建草稿"** 按钮

创建成功后，ResearchRun 状态为 `draft`（草稿），系统自动生成 10 个阶段（stage_runs）。

### 3.3 启动和监控

1. 点击 **"启动"** 按钮，输入启动原因（如"开始氟基高分子优化"）。
2. ResearchRun 状态先变为 `running`，随后进入第一个 P0 Gate：`PROBLEM_SPEC`。
3. 当 `PROBLEM_SPEC` 阶段状态变为 `blocked_approval` 时，需要先完成人工审批；批准后系统才会继续推进文献检索、结构表示、计算预测等非 Gate 阶段。
   - 当前代码会优先调用登记的阶段适配器，例如 `KNOWLEDGE_RETRIEVAL` 使用 `literature_rag_adapter`。如果外部索引或模型服务未配置，运行可能进入 `failed`，需要先完成服务配置或切换到后续 P1 的 mock fallback 策略。
4. 查看**阶段时间线**了解进度：
   - 已完成阶段：绿色对勾图标
   - 运行中阶段：蓝色圆点
   - 等待审批阶段：橙色时钟图标
   - 失败阶段：红色叉号图标
5. 进度条显示 `已完成阶段数 / 总阶段数`。

### 3.4 Gate 审批（**关键步骤**）

#### 什么是 Gate 审批

Auto Research 在 3 个关键阶段会**暂停并等待人工审批**，确保研发方向正确：

| Gate 阶段 | 中文名 | 审批内容 |
|-----------|--------|----------|
| `PROBLEM_SPEC` | 问题定义 | 校验研发任务定义是否完整、合理 |
| `RECOMMENDATION_ASK` | 候选推荐 | 审核系统推荐的候选材料方案 |
| `EXPERIMENT_EXECUTION` | 实验执行 | 确认是否将候选方案提交计算/实验 |

#### 如何审批

1. **找到审批入口**：在 ResearchRun 详情页的阶段时间线中，当某一阶段状态显示为 **"等待审批"（blocked_approval）** 时，该阶段右侧会出现一个醒目的**橙色"审批"按钮**。

2. **点击"审批"按钮**，弹出审批对话框（GateReviewDialog）。

3. **做出审批决策**：
   - 选择 **"批准"（approve）**：该阶段标记为完成，系统继续推进后续阶段
   - 选择 **"拒绝"（reject）**：该阶段标记为失败，ResearchRun 整体标记为失败

4. **填写审批原因**（必填），如：
   - 批准："问题定义完整，目标明确，批准继续"
   - 拒绝："候选方案不满足合成可行性约束，需要重新推荐"

5. 点击 **"确认"** 完成审批。

#### 审批后的流程

- **批准后**：系统恢复 ResearchRun 为 `running` 状态，并尝试继续推进后续阶段。若后续阶段依赖未配置的生产适配器，运行可能转为 `failed`；此时需要查看阶段错误和追溯链确认缺失配置。
- **拒绝后**：ResearchRun 标记为 `failed`，需重新创建 ResearchRun 或修复问题后重试。
- **审批超时**：ProblemSpec 和 Recommendation 阶段超时 72 小时，HumanReview 阶段超时 168 小时。超时后不会自动失败，需手动推进或标记。

### 3.5 其他操作

- **暂停**：随时可暂停 ResearchRun（running/blocked_approval 状态），输入暂停原因。之后可通过"恢复"按钮继续。
- **恢复**：从暂停状态恢复运行。
- **推进**：手动触发下一批阶段的推进（当系统未自动推进时使用）。
- **标记失败**：手动终止 ResearchRun，输入失败原因。

---

## 四、10 个阶段说明

| 阶段 Key | 中文名 | 需要审批 | 功能描述 |
|----------|--------|----------|----------|
| `PROBLEM_SPEC` | 问题定义 | ✅ 是 | 解析研发任务定义，提取目标、约束与测量条件 |
| `KNOWLEDGE_RETRIEVAL` | 文献检索 | ❌ 否 | 从文献库和知识图谱中检索相关材料合成路线与性能数据 |
| `STRUCTURE_FEATURE` | 结构表示 | ❌ 否 | 将分子结构转换为数值描述符（指纹、图形特征等） |
| `COMPUTE_PREDICT` | 计算预测 | ❌ 否 | 运行 DFT/xTB 计算或调用预测模型，生成候选分子的性质预测 |
| `RECOMMENDATION_ASK` | 候选推荐 | ✅ 是 | 基于多目标贝叶斯优化推荐下一批实验候选 |
| `HUMAN_REVIEW` | 人工审核 | ❌ 否 | 汇总推荐结果供人工审核 |
| `EXPERIMENT_EXECUTION` | 实验执行 | ✅ 是 | 将候选方案提交至计算/实验平台执行 |
| `RESULT_TELL` | 结果回填 | ❌ 否 | 将实验结果回填至 Campaign，更新候选评分 |
| `MODEL_UPDATE` | 模型更新 | ❌ 否 | 用新实验数据更新代理模型（GP/ML） |
| `ARCHIVE_LEARNING` | 经验归档 | ❌ 否 | 将本次研发过程归档，提取经验写入知识库 |

> **注意**：当前 P0 版本中，只有 `PROBLEM_SPEC`、`RECOMMENDATION_ASK`、`EXPERIMENT_EXECUTION` 三个阶段会触发运行时审批（`P0_GATE_STAGES`）。`HUMAN_REVIEW` 和 `MODEL_UPDATE` 在 stage contract 中保留了后续审批策略，但 P0 编排器不会在这两个阶段暂停。

---

## 五、常见问题

### Q: 审批按钮在哪里？我找不到

A: 审批按钮在 ResearchRun 详情页的**阶段时间线**中。只有当某个阶段的状态为 **"等待审批"（blocked_approval）** 时，该阶段右侧才会显示橙色的"审批"按钮。

操作路径：
1. 研发引擎 → 步骤 3 AutoResearch 编排
2. 从下拉列表选择你的 ResearchRun
3. 在阶段时间线中找到状态为"等待审批"的阶段
4. 点击右侧的橙色"审批"按钮

### Q: 审批超时了怎么办？

A: 系统不会因超时自动失败。超时后你可以：
- 继续正常审批（不会阻止审批操作）
- 通过"推进"按钮手动触发后续流程
- 如需超时自动处理，可在 stage contract 中配置 `timeout_hours` 参数

### Q: 如何查看完整的追溯链？

A:
- 在步骤 4"当前运行状态"中查看运行摘要
- 在步骤 5"追溯/结果汇总"中查看完整追溯链
- 或通过 API：`GET /api/v1/research-engine/research-runs/{run_id}/traceability`

### Q: 有现成示例可以直接试吗？

A: 有。ResearchEngine 示例 API 提供两个示例：

- `manual-computation-workflow`：创建一个人工计算 Workflow，使用 `computation_submit_adapter` 提交 `LOCAL_STRUCTURE` 计算。
- `autoresearch-approval-demo`：创建并启动 AutoResearch，自动停在 `PROBLEM_SPEC` 审批节点。

前端 ResearchEngine 页面会将示例实例化后跳转到对应工作区。

### Q: ResearchRun 失败了怎么办？

A: 失败后无法恢复。你需要：
1. 查看失败阶段和错误原因
2. 重新创建 ResearchRun（使用同一个 ProblemSpec）
3. 或通过 API 追溯链接查看详细的审计事件

如果失败发生在 `KNOWLEDGE_RETRIEVAL`、`COMPUTE_PREDICT` 或 `RECOMMENDATION_ASK` 等自动阶段，优先检查对应适配器是否已配置。例如 `literature_rag_adapter` 需要外部文献索引，`mobo_alchemist_adapter` 需要 Alchemist 服务。

### Q: 可以同时运行多个 ResearchRun 吗？

A: 可以。每个 ProblemSpec 可以有多个 ResearchRun，通过执行决策（ExecutionDecision）区分。

---

## 六、演练示例：氟基高分子优化

以下是一个完整的 Auto Research 操作示例：

### 目标
优化氟基高分子材料的介电常数和热稳定性。

### 操作步骤

1. **创建 ProblemSpec**
   - 名称：氟基高分子电解质材料优化
   - 材料体系：fluoropolymer
   - 目标：maximize dielectric_constant, maximize thermal_stability

2. **选择执行路径**
   - 在步骤 2 中点击 "AutoResearch 自动编排"

3. **创建 ResearchRun**
   - 选择刚创建的 ProblemSpec
   - Profile：氟基高分子 (fluoropolymer)
   - 最大迭代次数：3
   - 批次大小：10
   - 点击"创建草稿"

4. **启动**
   - 点击"启动"，输入原因"开始氟基高分子优化"，确认
   - 系统进入第一个 Gate：`PROBLEM_SPEC`

5. **第一次审批 - PROBLEM_SPEC**
   - 当状态变为"等待审批"，点击"审批"
   - 查看问题定义快照
   - 选择"批准"，输入原因"问题定义校验通过，材料体系、目标、约束均已明确定义"
   - 确认
   - 批准后系统继续推进非 Gate 阶段（文献检索 → 结构表示 → 计算预测）

6. **第二次审批 - RECOMMENDATION_ASK**
   - 系统推进到候选推荐阶段后暂停
   - 查看 Top-K 候选和推荐理由
   - 审核候选方案，选择"批准"或"拒绝"

7. **第三次审批 - EXPERIMENT_EXECUTION**
   - 确认提交候选方案到计算/实验平台
   - 审批通过后系统尝试继续执行剩余阶段；如果依赖的外部适配器未配置，需要先处理配置或查看失败追溯

8. **完成**
   - ResearchRun 状态变为 `completed`
   - 在步骤 5 查看完整追溯链和结果汇总
