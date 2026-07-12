# 用户上传算法部署与调用能力 P0 评估与路线图

日期：2026-07-11  
依据：用户上传的《用户上传算法部署与调用能力 P0 方案》、当前代码静态审计、定向后端测试、前端构建验证，以及产品边界调整意见。

## 结论

当前实现已经完成 P0.1-P0.3：用户可从“任务提交 -> 垂类预测模型”进入独立工作台，上传 Python 脚本或标准 ZIP，完成校验、构建、部署和激活，并进行版本治理、指定版本测试调用与运行追溯。ResearchEngine 已移除上传治理入口，只消费 AlgorithmRegistry 中的可调用算法。

新的边界定义：

- `任务提交 -> 垂类预测模型` 是上传算法、算法部署、版本管理、测试调用和运行记录的主入口。
- ResearchEngine 只消费已经上传、校验、部署、激活或被固定版本选择的算法，用于人工 Workflow 和 AutoResearch 的研发调用。
- AlgorithmRegistry 是统一算法资产注册表和查询来源，不应承担研究人员上传部署的主交互入口。

当前状态应定义为：P0-MVP 产品闭环可用；真实 Docker/BuildKit 构建、本机容器服务和完整安全资源治理仍属于 P0.4-P0.5，尚未完成。

## 2026-07-11 实施状态

| 阶段 | 状态 | 已交付 |
| --- | --- | --- |
| P0.1 入口迁移与工作台 | 已完成 | `/vertical-prediction`、任务目录在线入口、四个工作台 Tab、ResearchEngine 移除上传按钮 |
| P0.2 上传部署体验 | 已完成 | 脚本/ZIP/模板三入口、字段化 schema、样例 JSON 实时校验、YAML 预览、标准 ZIP 下载 |
| P0.3 版本管理和测试台 | 已完成 | 版本表、部署/激活/回滚/冻结/下线、指定版本调用、运行记录筛选和详情 |
| P0.4 容器化执行 | 待实施 | 当前仍为 `local_python_adapter` 和摘要占位构建 |
| P0.5 安全与资源治理 | 待实施 | 当前仅有包级校验，缺容器级隔离、资源配额和完整审计治理 |

## 验证结果

| 验证项 | 命令 | 结果 |
| --- | --- | --- |
| 算法包 API 定向测试 | `conda run -n poly_agent python -m pytest backend/tests/test_research_engine_api.py::AlgorithmPackageApiTest -q` | 通过，2 passed |
| 前端构建 | `cd frontend && npm run build` | 通过 |
| base 环境直接 pytest | `pytest backend/tests/test_research_engine_api.py::AlgorithmPackageApiTest -q` | 失败，base Python 缺少 `pymongo`；应使用 `poly_agent` 环境 |
| 本轮前端生产构建 | `cd frontend && npm run build` | 通过，2015 modules transformed |
| 本轮算法包服务层生命周期 | `conda run -n poly_agent python` 定向脚本 | 通过：下载、校验、构建、部署、激活、冻结、下线及状态拒绝 |
| 本轮 HTTP 定向 pytest | `AlgorithmPackageApiTest` | 当前沙箱中异常响应请求链路阻塞并超时；服务层逻辑已通过，需在可正常运行 TestClient 的环境复跑 |
| 本轮浏览器验证 | Poly_Agent 重启脚本 + Playwright | 当前沙箱禁止绑定本地端口，未执行；前端生产构建已通过 |

## 产品边界

### 垂类预测模型入口负责

`任务提交 -> 垂类预测模型` 应成为算法上传部署能力的产品入口，参考“计算智能”任务的结构，提供“提交/管理/记录”一体化体验。

职责：

1. 上传 Python 脚本或标准 ZIP。
2. 下载模板和本地 CLI 指引。
3. 填写算法元信息、输入输出契约和样例输入。
4. 校验、构建、部署、激活算法版本。
5. 管理版本：版本列表、active 指针、回滚、冻结、下线。
6. 测试调用：根据 `input_schema` 渲染表单，调用指定版本。
7. 查看运行记录：展示上传算法产生的 AlgorithmRun、输出、artifact、版本和 digest。

### ResearchEngine 负责

ResearchEngine 不做上传算法主入口。它只在研发流程中调用算法能力。

职责：

1. 从 AlgorithmRegistry 读取已激活算法和可选历史版本。
2. 人工 Workflow 选择算法和版本，未指定版本时在启动时冻结 active 版本。
3. AutoResearch 只选择状态为 `active` 且支持 `autoresearch` 的算法版本。
4. AlgorithmRun 记录调用时的 `algorithm_version_id`、`package_sha256`、`image_digest`、输入和输出。
5. 展示研发链路中的算法运行详情和追溯链。

不应承担：

- 上传 Python 文件。
- 生成算法 ZIP。
- 构建部署算法版本。
- 算法版本治理主 UI。

### AlgorithmRegistry 负责

AlgorithmRegistry 是资产目录和调用索引，不是上传工作台。

职责：

1. 汇总内置算法、上传算法和外部服务算法。
2. 暴露算法元信息、schema、状态、active version。
3. 供垂类预测模型、ResearchEngine、工具服务和任务中心查询。

## 当前 UI 入口评估

### 当前实现

当前上传算法主入口已经迁移到：

```text
任务提交 -> 垂类预测模型 -> 上传部署
```

对应前端路由为 `/vertical-prediction`。页面提供“上传部署、算法管理、测试调用、运行记录”四个 Tab，用户无需创建 ProblemSpec。

### 任务目录状态

- `frontend/src/tasks/taskModules.js` 中 `vertical-prediction` 已调整为 `online`，提交和管理路由均指向 `/vertical-prediction`。
- `frontend/src/views/TaskSubmitView.vue` 中卡片已改为“进入预测工作台”。
- ResearchEngine 的 `AlgorithmRegistryPanel.vue` 只保留筛选、查看详情和 Workflow 选择，不再包含模板下载和上传抽屉。

### UI 缺口

| 能力 | 当前状态 | 调整方向 |
| --- | --- | --- |
| 上传算法入口 | 已完成 | `任务提交 -> 垂类预测模型 -> 上传部署` |
| 算法版本管理 | 已完成 | 展示版本摘要并支持部署、激活、回滚、冻结、下线 |
| 算法测试调用 | 已完成 | 根据版本 `input_schema` 渲染表单并显式传递 `algorithm_version_id` |
| ResearchEngine 调用 | 已完成边界调整 | 保留算法选择和调用，移除上传治理动作 |
| 垂类预测任务目录 | 已完成 | 状态为 online，路由到 `/vertical-prediction` |

## 后端完成度评估

| 方案模块 | 当前状态 | 证据 | 评价 |
| --- | --- | --- | --- |
| 模板 ZIP 下载 | 已完成 | `GET /api/v1/research-engine/algorithm-packages/template` | 能力可复用，后续路由命名可调整 |
| 网页打包助手 pack API | 已完成 | `POST /api/v1/research-engine/algorithm-packages:pack` | 后端可用，产品入口需迁移 |
| 标准 ZIP 上传 | 已完成 | `POST /api/v1/research-engine/algorithm-packages` | 后端可用，产品入口需迁移 |
| 契约校验 | 已完成 | 校验 `polyagent.algorithm.yaml`、Python 3.11、schema、入口格式 | 满足最小 P0 |
| dry-run | 已完成 | validate 阶段执行 sample input | 满足最小 P0 |
| AlgorithmPackage | 已完成 | schema、repository、list/get/update | 满足 P0 |
| AlgorithmVersion | 已完成 | schema、repository、list/get/update | 满足 P0 |
| active_version_id | 已完成 | activate 写入 AlgorithmRegistry | 满足 P0 |
| AlgorithmRun 版本追溯 | 已完成 | run 记录 `algorithm_version_id`、`package_sha256`、`image_digest`、runtime snapshot | 满足 P0-MVP |
| Docker/BuildKit 构建 | 未完成 | build 只生成 image digest 占位符 | 不满足原方案 |
| 本机容器部署 | 未完成 | deploy 登记 `local_python_adapter` | 不满足原方案 |
| 容器 health/predict | 未完成 | 无独立算法服务进程 | 不满足原方案 |
| 停止/重启/日志查看 | 未完成 | 无对应 API/UI | 不满足原方案 |
| 安全隔离 | 部分完成 | ZIP 路径、文件类型、Dockerfile、`.env` 等校验 | 缺进程/容器级隔离 |
| 版本冻结/下线 | 已完成 | `:freeze`、`:decommission` API 和工作台操作；新任务拒绝不可用版本 | 满足 P0.3 |
| 标准 ZIP 下载 | 已完成 | `GET /api/v1/research-engine/algorithm-packages/{package_id}/download` | 支持平台生成包再次上传 |

说明：后端路径当前挂在 `/api/v1/research-engine/...` 下，这是现有实现的技术事实。产品上应迁移到垂类预测模型入口；是否同步新增 `/api/v1/vertical-prediction/...` 或 `/api/v1/algorithm-packages/...` 作为公共资产 API，可在实现阶段决策。

## 垂类预测模型工作台设计

参考计算智能任务的“提交任务 + 任务中心”模式，垂类预测模型应拆成一个可直达的工作台，而不是只做一个卡片。

建议路由：

```text
/vertical-prediction
/vertical-prediction/algorithms
/vertical-prediction/runs
```

也可以先用一个页面内 tabs 实现，后续再拆路由。

### 首屏结构

`任务提交 -> 垂类预测模型` 点击后进入垂类预测模型工作台，首屏包含：

- 算法上传：上传脚本、上传 ZIP、下载模板。
- 已部署算法：展示 active 算法和版本状态。
- 测试调用：选择算法版本，填写输入，查看输出。
- 最近运行：展示 AlgorithmRun 历史。
- 服务状态：展示构建器、部署器、算法 runner 状态。

### 页面 tabs

| Tab | 职责 | 关键操作 |
| --- | --- | --- |
| 上传部署 | 打包助手和标准 ZIP 上传 | 生成契约、校验、构建、部署、激活 |
| 算法管理 | 算法资产和版本治理 | 查看版本、激活、回滚、冻结、下线 |
| 测试调用 | 面向研究人员的快速预测 | schema 表单、运行指定版本、展示 JSON 输出 |
| 运行记录 | 上传算法产生的 AlgorithmRun | 查看版本、输入、输出、artifact、错误日志 |

### 与计算智能入口的类比

| 计算智能 | 垂类预测模型 |
| --- | --- |
| 提交计算任务 | 测试/提交预测任务 |
| 计算任务中心 | 预测运行记录 |
| workflow timeline | 上传算法部署进度 |
| artifact 和结构化结果 | 输出 JSON、可视化摘要、artifact |
| worker 服务状态 | algorithm builder/runner 服务状态 |

## ResearchEngine 调用链路设计

上传与版本治理迁出后，ResearchEngine 的算法面板应收敛为“选择和调用”。

调整目标：

1. 算法清单只展示可调用算法，不展示上传部署入口。
2. 算法详情展示 active version 和可选历史版本，但操作只限选择版本。
3. 人工 Workflow 节点选择算法时，可选择 `active` 或指定版本。
4. WorkflowRun 启动时冻结版本，后续 active 变化不影响运行。
5. AutoResearch 只读取 active 且支持 `autoresearch` 的算法版本。

这样 ResearchEngine 保持研发执行语义，不混入资产上线流程。

## 下一步计划

### P0.1：入口迁移与垂类预测模型工作台（已完成）

目标：让上传算法从“研发引擎内部按钮”迁移到“任务提交 > 垂类预测模型”。

任务：

1. 将 `vertical-prediction` 从 coming soon 调整为 online，并配置路由。
2. 新增垂类预测模型工作台页面，首版可使用 tabs：上传部署、算法管理、测试调用、运行记录。
3. 将现有上传抽屉能力迁移到上传部署 tab。
4. 从 ResearchEngine 的算法注册表中移除“上传算法”和“模板”按钮，只保留调用选择。
5. 在任务提交页卡片文案中明确“上传/管理/调用垂类预测算法”。

验收：

- 用户从“任务提交 > 垂类预测模型”一次点击进入工作台。
- 用户不需要创建 ProblemSpec 即可上传算法。
- ResearchEngine 中不再出现上传算法主入口。

### P0.2：上传部署体验完善（已完成）

目标：把当前 JSON textarea 形式改成研究人员可用的打包助手。

任务：

1. 上传方式为三个明确入口：上传 Python 脚本、上传标准 ZIP、下载模板。
2. 元信息表单使用普通控件：算法 ID、名称、版本、算法类型、材料范围、触发方式。
3. 输入输出 schema 使用字段表格：字段名、类型、必填、单位、枚举、范围。
4. 样例输入保留 JSON 编辑器，但增加实时 JSON 校验。
5. 展示生成的 `polyagent.algorithm.yaml` 预览。
6. 支持下载平台生成的标准 ZIP。
7. 校验结果按文件检查、schema 检查、入口函数检查、dry-run 检查分组。

验收：

- 只上传一个符合契约的 `.py` 文件也能生成标准 ZIP。
- 缺少入口函数、样例输入不合法、schema 字段缺失时，页面能定位错误。
- 生成 ZIP 可重新作为标准 ZIP 上传成功。

### P0.3：版本管理和测试台（已完成）

目标：让上传算法成为可治理资产。

任务：

1. 在垂类预测模型工作台实现版本表。
2. 展示 version、package sha256、image digest、状态、创建人、创建时间。
3. 暴露激活、回滚、冻结、下线操作。
4. 测试调用 tab 根据 `input_schema` 自动渲染输入表单。
5. 测试结果展示 output JSON、artifact、运行版本、耗时和错误。
6. 运行记录 tab 按算法、版本、状态、时间筛选 AlgorithmRun。

验收：

- 激活新版本后，新预测运行使用新 version id。
- 回滚后，新预测运行使用旧 version id。
- 历史运行仍显示当时使用的 version id 和 digest。
- 冻结/下线版本不可被新任务选择，但历史记录仍可追溯。

### P0.4：容器化执行补齐

目标：对齐原 P0 方案中的 Docker/BuildKit + 本机容器部署。

任务：

1. 为标准算法包生成受控 Docker build context。
2. 使用固定 Python 3.11 base image 和非 root 用户。
3. 安装 `requirements.txt` 时限制超时、网络策略和依赖大小。
4. build 成功记录真实 image digest。
5. deploy 启动本机容器，暴露内部 `/health` 和 `/predict`。
6. 后端 adapter 改为 HTTP 调用内部算法服务。
7. 增加容器停止、重启、健康检查、运行超时和日志查看。

验收：

- `build_logs` 是真实 Docker build 日志。
- `image_digest` 来自真实镜像。
- deploy 后 health check 必须通过才能激活。
- 算法运行失败、超时、容器不可用都有结构化错误。

### P0.5：安全与资源治理

目标：把“能跑”收敛到“可接受地安全运行”。

任务：

1. 细化 ZIP 文件白名单，区分源码、模型权重、数据样例。
2. 检测符号链接、绝对路径、路径穿越、隐藏可执行文件。
3. 对 `requirements.txt` 做依赖黑名单/许可证/私有源校验。
4. 日志脱敏，禁止输出 secret、token、完整环境变量。
5. 限制请求体大小、CPU、内存、运行时间和并发。
6. 增加上传包、版本切换、预测运行的审计事件。

验收：

- 非法 ZIP、危险文件、非法依赖、入口异常都有结构化错误。
- 算法容器无宿主敏感目录挂载。
- 运行日志不暴露 secret。

## 整体优化目标

算法上传部署能力最终应从“研发流程里的一个按钮”升级为“垂类预测模型资产平台”。

1. 入口清晰：上传、部署、版本治理和测试调用统一放在 `任务提交 -> 垂类预测模型`。
2. 研发解耦：ResearchEngine 只调用已治理算法，不承担算法上线流程。
3. 降低上传门槛：研究人员不需要理解 YAML、Docker、路由和平台内部模型，只需要上传 `.py`、依赖、样例输入并填写表单。
4. 契约一致：所有算法都以同一 `polyagent.algorithm.yaml`、输入 schema、输出 schema、entrypoint 和 sample input 进入平台。
5. 版本可治理：算法版本不可变，active 只是指针；激活、回滚、冻结、下线都要有审计记录。
6. 调用可追溯：每次 AlgorithmRun 必须冻结算法版本、包哈希、镜像 digest、输入快照、输出摘要和 artifact。
7. 执行可隔离：上传算法不能在后端主进程内长期运行，生产路径应使用容器或等价 sandbox。
8. 扩展有边界：Docker 本机部署之后再扩展 Kubernetes/KServe、Git 导入、云托管和 GPU/系统依赖。

## 推荐优先级

| 优先级 | 工作 | 原因 |
| --- | --- | --- |
| P0.1 首位 | 垂类预测模型工作台 + 入口迁移 | 解决产品边界错误和用户当前看不到入口的问题 |
| P0.2 第二 | 打包助手表单化 | 让研究人员真正可用 |
| P0.3 第三 | 版本管理 + 测试台 + 运行记录 | 形成算法资产治理闭环 |
| P0.4 第四 | Docker/BuildKit 容器化 | 对齐原 P0 部署目标和安全边界 |
| P0.5 并行 | 安全校验与日志治理 | 上传用户代码必须尽早收敛风险 |

## 代码证据索引

- 当前后端算法包 API：`backend/app/api/v1/endpoints/research_engine.py`
- 当前后端算法包服务：`backend/app/services/research_engine_algorithm_package_service.py`
- AlgorithmRun 上传版本调用：`backend/app/services/research_engine_service.py`
- 当前错误放置的前端上传入口：`frontend/src/views/research-engine/AlgorithmRegistryPanel.vue`
- 任务提交垂类预测模型 coming soon：`frontend/src/tasks/taskModules.js`、`frontend/src/views/TaskSubmitView.vue`
- 前端 API client：`frontend/src/api/polyAgentApi.js`
- CLI 打包工具：`scripts/pack_algorithm.py`
- Demo 算法：`examples/algorithm_upload/vertical_tg_predictor_demo`
- 用户指南：`doc/algorithm-upload-user-guide.md`
