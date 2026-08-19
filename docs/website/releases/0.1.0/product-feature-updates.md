---
title: "Poly Agent 0.1.0 产品特性更新"
slug: "product-updates-0-1-0"
type: "release-notes"
version: "0.1.0"
release_date: "2026-08-19"
updated_at: "2026-08-19"
language: "zh-CN"
status: "ready-for-review"
audience:
  - "材料科学家"
  - "算法与计算工程师"
  - "实验平台管理员"
  - "研发负责人"
---

# Poly Agent 0.1.0 产品特性更新

## 1. 版本概览

Poly Agent `0.1.0` 是当前产品基线版本。本版把高分子材料研发中的问题定义、计算任务、垂类算法、知识证据、实验优化、人工审批和报告生成连接为同一条可追溯工作流。

| 项目 | 内容 |
| --- | --- |
| 版本 | `0.1.0` |
| 发布日期 | 2026-08-19 |
| 产品定位 | 高分子材料智能研发工作台 |
| 本版主题 | 计算智能 + ResearchEngine P0 双通道闭环 |
| 主要入口 | `/research-engine`、`/computations/submit`、`/optimization/alchemist`、`/vertical-prediction`、`/dialogue` |
| 适用角色 | 材料科学家、算法与计算工程师、实验平台管理员、研发负责人 |
| 文档状态 | ready-for-review |

本版的关键变化不是“增加一个聊天入口”，而是建立一套可执行的研发事实模型：任务有定义，执行有路径，运行有记录，结果有 artifact，决策有审批，报告有来源。

## 2. 本版能力地图

| 能力域 | 本版状态 | 代表入口 | 已交付能力 |
| --- | --- | --- | --- |
| ResearchEngine | P0 完成 | `/research-engine` | ProblemSpec、人工 Workflow、AutoResearch、Gate、追溯、报告 |
| ComputeEngine | MVP 基本完成 | `/computations/submit` | run 生命周期、worker、artifact、campaign、本地计算工具链 |
| Alchemist | MVP 完成 | `/optimization/alchemist` | 变量、DoE/OED、GP、采集优化、诊断可视化 |
| 垂类预测 | 基础可用 | `/vertical-prediction` | 算法上传、版本治理、在线测试、运行历史、handoff |
| Knowledge Base | WeKnora 已接入 | `/knowledge` | 知识库问答、证据清单、可选图谱 |
| Data Catalog | 基础可用 | `/database/data-catalog` | 数据资产目录、数据集详情、记录下钻 |
| 受控 LUI | 基础可用 | `/dialogue` | Slash Command、Plan Mode、权限、模型切换、统一回放 |
| 平台底座 | 基础可用 | `/dashboard`、`/tasks/center`、`/tools` | AI4MS SSO、任务中心、工具状态、模型服务配置 |

## 3. ResearchEngine P0 双通道闭环

### 3.1 本版更新

本版交付人工算法工作台和 AutoResearch 两条执行通道。两条通道都从 ProblemSpec 出发，最终落到可追溯的运行记录和报告，避免“工具按钮”和“研发任务”脱节。

### 3.2 使用步骤

1. 进入 `/research-engine`。
2. 创建 ProblemSpec，写清材料体系、目标性质、约束、测量条件和验收标准。
3. 选择执行路径：
   - **人工算法工作台**：由专家选择算法节点并编排 Workflow。
   - **AutoResearch**：由系统按 ProblemSpec 和阶段契约自动推进。
4. 人工通道中，从已治理算法清单选择节点，创建并启动 WorkflowRun。
5. AutoResearch 通道中，选择材料 Profile、最大迭代次数和批次大小，创建 ResearchRun 草稿后启动。
6. 在 Gate 阶段查看输入、候选和风险，填写审批原因并选择批准或拒绝。
7. 在详情页查看输入快照、输出摘要、artifact、关联计算和 audit。
8. 在报告面板选择 provider 和格式，生成研发报告。

### 3.3 AutoResearch 十阶段

| 阶段 | 中文名 | 当前是否 Gate | 本版能力 |
| --- | --- | --- | --- |
| `PROBLEM_SPEC` | 问题定义 | 是 | 解析任务、提取目标和约束，生成 `problem_spec_snapshot` |
| `KNOWLEDGE_RETRIEVAL` | 文献检索 | 否 | 调用 WeKnora 适配器，生成知识卡片和候选来源 |
| `STRUCTURE_FEATURE` | 结构表示 | 否 | 将分子结构转换为描述符或特征 |
| `COMPUTE_PREDICT` | 计算预测 | 否 | 调用计算任务或垂类预测模型 |
| `RECOMMENDATION_ASK` | 候选推荐 | 是 | 基于目标、约束和历史数据生成候选建议 |
| `HUMAN_REVIEW` | 人工审核 | 否 | 汇总推荐结果供人工查看 |
| `EXPERIMENT_EXECUTION` | 实验执行 | 是 | 提交计算、实验或人工实验任务 |
| `RESULT_TELL` | 结果回填 | 否 | 将结果回填为 Observation |
| `MODEL_UPDATE` | 模型更新 | 否 | 更新代理模型或推荐策略状态 |
| `ARCHIVE_LEARNING` | 经验归档 | 否 | 归档过程、失败原因和可复用经验 |

当前 P0 只有 `PROBLEM_SPEC`、`RECOMMENDATION_ASK`、`EXPERIMENT_EXECUTION` 三个阶段触发运行时审批。`HUMAN_REVIEW` 和 `MODEL_UPDATE` 保留后续审批策略，但本版编排器不会暂停。

### 3.4 交付物

- ProblemSpec 快照
- WorkflowRun 和 WorkflowStepRun
- ResearchRun 和 StageRun
- AlgorithmRun 输入快照与输出摘要
- GateDecision 和审批原因
- artifact 引用
- audit 事件
- HTML、LaTeX、Markdown 或 PDF 报告

### 3.5 本版边界

- 知识检索依赖 WeKnora 配置。
- 真实 HPC/AiiDA executor 待接入。
- 实验方案转发台可按版本化配置生成并保存实验清单；SpecLabOS 真实设备执行和结果回填待接入。
- 真实候选算法依赖外部服务配置。

## 4. ComputeEngine 计算任务闭环

### 4.1 本版更新

ComputeEngine 在本版完成统一任务生命周期、worker 执行、artifact 管理和 campaign 联动。用户不需要直接登录计算节点或手工整理输出文件。

### 4.2 任务生命周期

| 状态 | 含义 | 用户可以做什么 |
| --- | --- | --- |
| `queued` | 等待 worker 领取 | 查看排队任务和提交时间 |
| `running` | worker 正在执行 | 查看运行开始时间和 heartbeat |
| `completed` | 执行完成 | 查看结果 JSON、下载 artifact |
| `failed` | 执行失败 | 查看错误码、错误详情和日志 |
| `cancelled` | 任务已取消 | 查看取消时间和原因 |

Worker 原子领取任务，避免重复执行；任务执行期间写入 heartbeat；系统回收 stale run。Adapter 统一负责输入校验、执行、artifact 收集和结果解析。

### 4.3 计算路径

| Workflow | 输入 | 执行内容 | 输出 |
| --- | --- | --- | --- |
| `LOCAL_STRUCTURE` | SMILES | RDKit 或 OpenBabel 生成三维结构 | `structure.xyz`、`structure.sdf`、`structure.json`、日志 |
| `LOCAL_XTB` | SMILES、方法参数 | 结构生成、CREST 构象搜索、xTB 计算 | 构象、能量、优化结构、日志 |
| `ORCA_COMPUTE_ENGINE_LASER` | SMILES、白名单方法 | 结构生成、CREST、ORCA DFT | ORCA 输入、能量、结构、日志 |

### 4.4 使用步骤

1. 进入 `/computations/submit`。
2. 选择计算 workflow。
3. 输入 SMILES 和参数。
4. 提交任务。
5. 进入 `/computations/runs` 查看状态。
6. 打开任务详情，查看执行步骤、结果 JSON、错误信息和 artifact。
7. 下载 XYZ、SDF、JSON 或日志文件。

### 4.5 Campaign 联动

Campaign 把以下对象串成优化闭环：

- candidate：候选材料或实验条件
- suggestion：系统推荐
- computation：计算任务
- observation：实验或计算结果

用户可以在 Campaign 详情中查看候选、建议、计算和观测结果，并跳转关联计算任务。

### 4.6 本版边界

- mock、RDKit/OpenBabel、本地 xTB 和受控 ORCA fixture 可用。
- 真实 ORCA/HPC/AiiDA 仍在后续版本接入。
- ORCA 方法使用后端白名单，不允许用户提交任意输入文件或关键字。
- mock、fixture 和 demo 结果不能作为真实实验结论。

## 5. Alchemist 实验设计与优化

### 5.1 本版更新

本版 Alchemist 已完成从变量定义到诊断可视化的完整工作流，适合在真实实验前进行实验设计、代理建模和候选推荐。

### 5.2 操作流程

1. **定义变量**
   - 支持连续、整数、分类和离散变量。
   - 设置变量范围、单位和约束。

2. **生成实验设计**
   - 内置 LHS、Sobol、因子设计、CCD、Box-Behnken、Plackett-Burman。
   - 最优设计支持主效应、交互和二次项。
   - 可配置 D-optimal、A-optimal、I-optimal 和交换算法。

3. **导入实验数据**
   - 支持设计表填写、手动新增和 CSV 导入。
   - 只有带 Output 的记录可用于建模。

4. **训练 GP 模型**
   - 支持 Matern 5/2、Matern 3/2、RBF、IBNN。
   - 支持 scikit-learn 和 BoTorch。
   - 查看 R²、RMSE、MAE 等指标。

5. **生成下一批建议**
   - 支持 EI、PI、UCB、qEI、qUCB、qNIPV。
   - 可配置优化方向、探索权重和批量数量。

6. **诊断模型**
   - 查看 Parity、CV 指标曲线、Q-Q、校准曲线、等值线图和超参数。

### 5.3 本版边界

- GP 建模至少需要 5 条带 Output 的数据。
- LLM 辅助建议依赖模型服务配置。
- 平台不直接执行真实实验，实验执行需要外部系统。

## 6. 垂类预测模型治理

### 6.1 本版更新

垂类预测模块在本版支持算法包上传、契约声明、版本治理、在线测试、运行历史和 handoff，并把开发者来源纳入展示。

### 6.2 算法上传

支持三种入口：

| 入口 | 操作 | 适用用户 |
| --- | --- | --- |
| 网页打包助手 | 上传 `.py`、`requirements.txt` 和样例输入，页面生成标准 ZIP | 快速验证和轻量模型 |
| 标准 ZIP 上传 | 上传符合契约的标准 ZIP | 已有标准化算法包 |
| 本地 CLI | 使用 `scripts/pack_algorithm.py` 打包 | 算法工程师和批量维护场景 |

上传后系统依次执行：

1. 校验
2. 构建
3. 部署
4. 激活

激活版本进入 AlgorithmRegistry，可被垂类预测、人工 Workflow 和 AutoResearch 调用。

### 6.3 契约能力

- 输入输出 schema
- 文件输入 `input_assets`
- 文件输出 `output_assets`
- 只读资源 `resource_assets`
- 开发者、机构、导师课题组、联系方式
- 来源 URL 和引用
- 授权 Logo

### 6.4 管理能力

| 能力 | 说明 |
| --- | --- |
| 版本管理 | 查看版本、状态、SHA256 和追溯信息 |
| 生命周期操作 | 部署、激活、回滚、冻结、下线 |
| 测试调用 | 按版本调用，查看输出、artifact 和耗时 |
| 运行记录 | 按算法、版本、状态和日期查询 AlgorithmRun |
| handoff | 把结果交给 ResearchEngine、计算或实验流程 |

### 6.5 远程接口模型

支持 HTTP、FastAPI 和 MCP 配置。HTTP/FastAPI 可测试、激活和调用；MCP 当前仅支持配置和展示。

远程接口安全边界：

- 生产环境要求 HTTPS。
- 默认阻断 loopback、私网、link-local 和保留地址。
- 认证信息使用环境变量或密钥引用。
- 平台不保存或返回明文凭据。
- 请求头、token、原始敏感响应和内部网络细节不写入运行记录。

## 7. 受控 LUI 与统一回放

### 7.1 本版更新

本版 `/dialogue` 增加完整 Slash Command 控制面。命令不进入模型请求历史，而是进入独立命令事件流，并与模型 run、算法工具调用、Trace、导出和反馈统一回放。

### 7.2 命令面板使用方式

1. 在输入框行首输入 `/`。
2. 或点击输入框工具栏的 `/` 按钮；输入框为空时自动填入 `/`。
3. 输入前缀或关键词，面板按前缀和模糊匹配过滤。
4. 使用鼠标点击、`↑`、`↓`、`Enter` 选择。
5. 使用 `Esc` 关闭。

### 7.3 内置命令调用方法

| 命令 | 调用方式 | 参数说明 | 结果与边界 |
| --- | --- | --- | --- |
| Plan Mode | `/plan` | 无参数 | 启用 Plan Mode |
| Plan Mode | `/plan off` | `off` | 退出 Plan Mode |
| Plan Mode | `/plan <任务说明>` | 计划任务文本 | 启用 Plan Mode 并创建计划任务 |
| Session Goal | `/goal` | 无参数 | 查看当前长期目标 |
| Session Goal | `/goal clear` | `clear` | 清除长期目标 |
| Session Goal | `/goal <目标描述>` | 目标文本，最多 2000 字符 | 设置长期目标 |
| Permission Mode | `/permission` | 无参数 | 显示当前权限和选项 |
| Permission Mode | `/permission read-only` | `read-only` 或 `read_only` | 切换为只读 |
| Permission Mode | `/permission workspace-write` | `workspace-write` 或 `workspace_write` | 切换为工作区写入 |
| Permission Mode | `/permission full-access` | `full-access` 或 `full_access` | 切换为完全访问 |
| Model Selection | `/model` | 无参数 | 显示当前模型和可选模型 |
| Model Selection | `/model <provider_id>::<model_id>` | 一个 `::`，两侧非空 | 切换模型，保留其他控制状态 |
| Session Status | `/status` | 无参数 | 显示模型、Plan、权限、Goal、Todo、活动 run、活动工具和 Trace 统计 |
| Reset Session Control | `/reset` | 无参数 | 弹出确认 |
| Reset Session Control | `/reset confirm` | `confirm`、`confirmed`、`yes` | 重置 Plan、权限、Goal、Todo |
| Reset Session Control | `/reset cancel` | `cancel`、`no` | 取消重置 |
| Clear To New Session | `/clear` | 不接受额外参数 | 创建新会话并保留旧会话 |
| Context Compaction | `/compact` | 不接受额外参数 | 压缩已完成历史 |
| Session Export | `/export` | 无参数 | 显示格式选项 |
| Session Export | `/export json` | `json` | 导出结构化 JSON |
| Session Export | `/export markdown` | `markdown` | 导出 Markdown |
| Session Export | `/export zip` | `zip` | 导出包含 Trace 和 artifact 的 ZIP |
| Session Feedback | `/feedback` | 不接受命令参数 | 打开反馈表单 |

### 7.4 典型调用示例

```text
/plan 设计一个氟基高分子介电常数优化方案
/goal 在满足加工窗口约束下优化热稳定性
/permission read-only
/model default_openai::deepseek-v4-flash
/status
/compact
/export zip
/feedback
```

### 7.5 动态算法命令

当前用户可用的已部署算法会自动派生为命令：

```text
/<algorithm-slug> [<JSON 参数>|<任务说明>]
```

调用流程：

1. 输入 `/` 打开命令面板。
2. 选择一个算法命令。
3. 按算法 schema 填写 JSON 参数或任务说明。
4. 如算法要求确认，先确认参数。
5. 系统创建 AlgorithmRun。
6. 结果和 artifact 回链到当前会话。
7. 结果附近展示开发者、方法来源和授权机构 Logo。

当 `/permission read-only` 或 Plan Mode 生效时，工具命令会被标记为不可用并显示原因。

### 7.6 统一回放

统一回放合并：

- Slash Command 生命周期
- 模型 run 生命周期
- 算法工具调用与结果
- 权限决策与 Plan Mode 阻断
- Goal、Todo、权限模式变化
- 上下文压缩
- 导出
- 反馈

支持“全部 / 命令 / 控制 / 模型 / 工具 / 导出 / 反馈”过滤，并使用 `after_seq` 游标增量恢复。

### 7.7 安全边界

- Plan Mode 不是 OS 沙箱；工具确认阶段由后端阻断执行。
- 权限模式不替代平台 RBAC 和工具策略。
- `/reset` 不删除消息、run、工具调用、导出记录和事件。
- `/clear` 保留旧会话。
- `/feedback` 的正文只进入权威反馈记录，命令事件只保存摘要。
- 导出下载走 owner 校验。
- 回放界面不展示完整 prompt、Chain of Thought、API key 或未脱敏文件内容。

## 8. Knowledge Base 与 Data Catalog

### 8.1 Knowledge Base

本版 Knowledge Base 接入 WeKnora：

- 知识库列表
- 问答流
- 证据清单
- 无总结检索
- 可选 Neo4j 图谱增强
- 敏感元数据过滤

使用方式：

1. 进入 `/knowledge`。
2. 选择知识库。
3. 输入问题。
4. 查看回答和证据。
5. 查看可选检索子图。

### 8.2 Data Catalog

本版 Data Catalog 支持：

- 数据资产目录
- 数据集分类和筛选
- 数据集详情
- 记录下钻
- 关系索引
- 数据分析视图
- 数据 API 说明

生产环境材料资产来自 `poly_data` MongoDB 和 MinIO；业务运行数据与材料资产数据分离。

## 9. 平台集成与治理

### 9.1 认证

- 支持 AI4MS 门户 SSO。
- 支持 HMAC token。
- 支持用户角色和权限。
- 支持门户 `#token=<access_token>` 传递统一登录令牌。

### 9.2 任务中心

`/tasks/center` 聚合：

- 计算任务
- 垂类模型运行
- ResearchEngine 任务
- WorkflowRun
- AlgorithmRun

用户可以按任务类型筛选，并跳转到对应详情页。

### 9.3 工具服务

`/tools` 展示：

- MongoDB、SQLite、artifact 存储
- computation worker
- WeKnora 和 Knowledge Graph
- RDKit、OpenBabel、xTB、CREST、ORCA
- Alchemist 和 SpecLabOS
- Docker
- LLM 模型服务

### 9.4 模型服务

本版支持配置：

- OpenAI
- Ollama
- Edison
- Codex
- 自定义 HTTP provider

模型配置用于助手、报告生成和部分辅助能力。

## 10. 当前能力边界

本版明确区分“已可用”和“待接入”：

- 真实 ORCA/HPC/AiiDA 执行仍需通过 integration config 和 adapter 契约接入。
- SpecLabOS/LabOS 实验提交与结果回填仍在后续版本推进。
- 实验方案转发台当前生成和保存实验清单，不代表目标设备已经执行。
- 生产级外部模型服务、对象存储、多租户配额和完整 worker 运维仍在 P1/P2 范围。
- mock、fixture、demo store 和本地 SQLite 样本仅用于演示或验收，不作为真实实验结论。
- 本版不提供通用 Shell、任意文件编辑、插件市场或无约束自动化执行。

## 11. 下一阶段方向

### P1 生产化

- Schema 驱动算法表单
- AlgorithmRegistry 管理
- 真实预测模型服务
- checkpoint/rerun
- worker 运维
- 对象存储
- 更多页面浏览器 e2e

### P2 真实执行

- ORCA/HPC/AiiDA executor
- SpecLabOS/LabOS 实验提交
- 实验结果回填
- 真实设备闭环

### P2 规模化协同

- 项目级权限和配额
- 模型更新
- 经验沉淀
- 跨项目知识复用

### 受控 Agent 演进

- 动态计算预算
- 外部 provider seam
- readiness 检查
- 受限 workdir
- 超时控制
- 完整 audit

这些方向按受控边界推进，不引入通用 Shell 或任意文件编辑。

## 12. 来源说明

Poly Agent 的控制面设计参考 DeepSeek Harness 的命令注册、权限模式与事件回放思路；对话工作台与工具调用交互参考 Open WebUI。本项目未复制上述代码，实际命令平面、双模事件存储、统一 Trace 投影、权限门禁、前端时间线和算法集成为 Poly Agent 实现。

外部方法来源包括 ChemOS 2.0、ALchemist、RDKit、OpenBabel、xTB、CREST、ORCA、WeKnora 和 Neo4j。完整引用、机构与实现边界见项目来源矩阵；无授权 Logo 时仅使用文字来源牌。
