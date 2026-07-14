# 垂类模型自动上传与部署生产化项目文档

日期：2026-07-13  
范围：用户上传垂类预测模型的打包、校验、构建、部署、调用、版本治理和生产级隔离。  
代码依据：`backend/app/services/research_engine_algorithm_package_service.py`、`backend/app/services/research_engine_service.py`、`backend/app/api/v1/endpoints/research_engine.py`、`frontend/src/views/vertical-prediction/*`、`frontend/src/api/polyAgentApi.js`、`backend/tests/test_research_engine_api.py`。

## 1. 核心结论

当前实现已经不是“只有后端草稿”的状态，P0.1-P0.3 的产品闭环已经成型：

- 用户入口已经在 `任务提交 -> 垂类预测模型`，路由为 `/vertical-prediction`。
- 前端提供上传部署、算法管理、测试调用、运行记录四个工作台 Tab。
- 后端支持模板 ZIP、网页打包助手、标准 ZIP 上传、契约校验、dry-run、版本登记、部署、激活、冻结、下线和 AlgorithmRun 追溯。
- ResearchEngine 已按产品边界收敛为“消费已治理算法”，不是上传部署主入口。

执行层已从 API 进程内 adapter 升级为 P0 本地沙箱运行时，但仍不是完整系统级沙箱或依赖隔离生产环境：

- `build_package()` 已记录 `runtime_digest`、`package_digest` 和 `environment_digest`，旧 `image_digest` 仅保留兼容。
- `deploy_version()` 默认登记 `kind=local_sandbox_runtime`、`endpoint_type=subprocess` 和 health/resource metadata。
- `validate_package()` dry-run 与 `AlgorithmRun` 调用默认通过独立 Python 子进程执行 JSON shim。
- `timeout_seconds` 已能终止子进程；并发上限、最大输出和环境变量白名单已进入 runtime snapshot。
- `requirements.txt` 被打包和保存，但当前构建阶段没有安装依赖、锁定依赖、扫描依赖或形成可复现运行环境。

因此准确状态应定义为：

> P0-MVP 产品与资产治理闭环可用；P0-prod 已引入本地受控沙箱运行时，让上传代码离开 API 主进程。后续重点是依赖环境、系统级资源/网络隔离、日志运维 API 和审计治理。

更合理的路线是：

1. 默认使用 `local_sandbox_runtime`：独立 subprocess/worker 进程、临时 workdir、JSON shim、环境变量白名单、stdout/stderr 捕获、timeout、并发和基础资源限制。
2. 保留 `local_inprocess` 仅用于 dev/test 和历史兼容，不允许作为生产默认 backend。
3. 将 roadmap 收敛在本地沙箱、依赖环境、日志审计和运维 UI 上，不再规划额外部署形态。

## 2. 当前能力清单

| 模块 | 当前状态 | 代码证据 | 评价 |
| --- | --- | --- | --- |
| 垂类预测工作台 | 已完成 | `frontend/src/views/VerticalPredictionView.vue`、`frontend/src/views/vertical-prediction/*` | 用户入口清晰 |
| 网页打包助手 | 已完成 | `AlgorithmUploadPanel.vue`、`POST /research-engine/algorithm-packages:pack` | 可从 `.py` + 表单生成标准 ZIP |
| 标准 ZIP 上传 | 已完成 | `POST /research-engine/algorithm-packages` | 只支持 `.zip`，20MB 限制 |
| 模板下载 | 已完成 | `GET /research-engine/algorithm-packages/template` | 可作为算法工程师起点 |
| 契约校验 | 已完成 P0 | `_validate_contract()` | 限定 `contract_version=0.1` 和 Python 3.11 |
| ZIP 安全校验 | 部分完成 | `_safe_extract()`、`_validate_archive_member()` | 有路径穿越、后缀、部署描述文件、`.env`、虚拟环境目录限制 |
| dry-run | 已完成并进程隔离 | `validate_package()` -> `LocalSandboxRuntimeBackend.predict()` | 独立子进程执行上传代码 |
| 构建 | 已完成 P0 摘要 | `build_package()` | 记录 package/environment/runtime digest，不安装依赖 |
| 部署 | 已完成 P0 沙箱登记 | `deploy_version()` | 登记 `local_sandbox_runtime`、health、endpoint 和 resource limits |
| 激活/回滚/冻结/下线 | 已完成 | `activate_version()`、`rollback_version()`、`freeze_version()`、`decommission_version()` | 支持版本治理 |
| 调用追溯 | 已完成 P0 | `create_algorithm_run()` | 记录 `algorithm_version_id`、`package_sha256`、runtime/environment digest、`runtime_snapshot` |
| 独立运行进程 | 已完成 P0 | `LocalSandboxRuntimeBackend`、`sandbox_shim.py` | dry-run/predict 离开 API 主进程 |
| 进程级沙箱隔离 | 已完成 P0 | 子进程 cwd、env 白名单、输出上限 | 仍非系统级强隔离 |
| 资源限制 | 部分完成 | subprocess timeout / semaphore / max output | 尚未接入 `setrlimit`/cgroup |
| 运行日志 | 部分完成 | AlgorithmRun runtime snapshot logs | 尚无日志下载/运维 API |
| 健康检查 | 部分完成 | deploy preflight + deployment.health | 尚无独立 health API |
| 可运维操作 | 未完成 | 无 restart/redeploy/logs API | 生产维护不可控 |

## 3. 现有链路

### 3.1 上传部署链路

```text
前端 /vertical-prediction 上传
  -> POST /api/v1/research-engine/algorithm-packages:pack 或 /algorithm-packages
  -> AlgorithmPackageService.upload_package()
  -> validate_package()
      -> 解压 ZIP
      -> 读取 polyagent.algorithm.yaml
      -> 校验 contract/input/output/sample
      -> LocalSandboxRuntimeBackend 子进程 dry-run
      -> 创建 AlgorithmVersion(status=validated)
  -> build_package()
      -> 生成 package/environment/runtime digest
      -> status=built
  -> deploy_version()
      -> deployment.kind=local_sandbox_runtime
      -> status=deployed_staging
  -> activate_version()
      -> 写入 AlgorithmRegistry.active_version_id
      -> status=active
```

### 3.2 调用链路

```text
前端测试调用 / ResearchEngine / AutoResearch
  -> POST /api/v1/research-engine/algorithm-runs
  -> ResearchEngineService.create_algorithm_run()
  -> resolve_active_version()
  -> 若没有内置 runner 且存在 uploaded version:
       _validate_uploaded_algorithm_input()
       AlgorithmPackageService.run_version_with_metadata()
       LocalSandboxRuntimeBackend 子进程执行
  -> AlgorithmRun(status=completed/failed)
```

当前风险：上传包已离开 API 主进程，但 P0 仍复用后端 Python 环境，尚未提供受控 venv、硬性禁网、cgroup/nsjail/firejail 等系统级隔离。

## 4. 生产级目标

目标是把垂类模型能力升级为可治理的模型资产运行平台。当前阶段应优先实现本地受控沙箱：部署简单、依赖少、能立即切断 API 主进程执行风险，并让后续迭代都围绕同一 runtime backend 边界展开。

### 4.1 必须具备的生产能力

1. 隔离：上传算法不能在 API 主进程内执行；P0-prod 默认使用独立 `local_sandbox_runtime`。
2. 可复现：记录 package SHA256、requirements hash、Python 版本、环境摘要和 runtime backend 配置。
3. 可限制：每次运行必须有超时、最大输出、并发限制；Linux 下逐步补 CPU、内存、进程数和文件系统限制。
4. 可观测：校验日志、构建日志、运行 stdout/stderr、启动失败、预测失败都要结构化记录。
5. 可治理：版本不可变；active 只是指针；激活、回滚、冻结、下线都有审计。
6. 可恢复：服务重启后能从 registry 恢复 active/staging 版本，sandbox backend 可重新执行 preflight。
7. 可扩展：同一 `AlgorithmRuntimeBackend` 接口可支持 in-process、sandbox、warm worker 等本地执行策略。

### 4.2 推荐目标架构

```text
VerticalPrediction UI
  -> AlgorithmPackage API
  -> Package Store (.runtime / object storage)
  -> AlgorithmBuildService
       -> validate contract / hash requirements / prepare sandbox environment
       -> record package_digest + environment_digest + runtime_digest
  -> AlgorithmDeploymentService
       -> default local_sandbox_runtime for P0-prod
       -> preflight / health / lifecycle / logs
  -> AlgorithmRuntimeGateway
       -> run sandbox shim through subprocess or worker process
       -> timeout / retry guard / structured error
  -> AlgorithmRun
       -> frozen version + package digest + runtime snapshot + artifacts + audit
```

运行时 backend 统一接口：

```text
validate_runtime(version)
build(version)
deploy(version)
health(version)
predict(version, inputs, context)
stop(version)
logs(version)
```

本地沙箱 runner 使用 JSON stdin/stdout 协议：

```json
{
  "entrypoint": "src.handler:predict",
  "loader": "src.handler:load",
  "package_path": "/path/to/extracted",
  "inputs": {},
  "context": {
    "algorithm_id": "vertical_tg_predictor",
    "version_id": "aver_...",
    "run_id": "arun_...",
    "runtime": "local_sandbox_runtime"
  }
}
```

runner 响应：

```json
{
  "ok": true,
  "output": {},
  "runtime": {
    "duration_ms": 123,
    "worker_pid": 12345,
    "backend": "local_sandbox_runtime"
  }
}
```

失败响应：

```json
{
  "ok": false,
  "error": {
    "error_type": "ValueError",
    "message": "predict() 必须返回 dict",
    "traceback_tail": "..."
  },
  "runtime": {
    "backend": "local_sandbox_runtime"
  }
}
```

## 5. 生产化差距

| 差距 | 当前表现 | 生产风险 | 目标补齐 |
| --- | --- | --- | --- |
| 主进程执行用户代码 | `importlib` 直接执行 | 死循环、崩溃、内存爆、全局污染会影响 API | `local_sandbox_runtime` 独立进程执行 |
| 无真实 timeout | 参数存在但没有中断机制 | 请求可无限卡死 | sandbox runner + API gateway 双层超时 |
| 无依赖环境 | 不安装 requirements | 本地能跑不代表服务能跑 | 受控 venv 或预置依赖环境，记录 requirements hash 和安装日志 |
| 无资源配额 | 无 CPU/内存限制 | 单模型拖垮宿主 | subprocess timeout、并发 semaphore、Linux `resource.setrlimit`，必要时引入 cgroup/nsjail/firejail |
| 无网络策略 | 上传代码可访问外网/内网 | 数据泄露、横向访问 | 默认禁网或 allowlist；P0 可先记录策略并禁止透传敏感 env |
| 无文件系统隔离 | 代码运行在后端进程权限内 | 读取宿主敏感文件 | 独立临时 workdir、只挂载 package path、限制输出目录；高风险场景增强到 nsjail/firejail |
| 无运行时健康检查 | deploy 直接 ready | active 后才暴露问题 | deploy 必须通过 sandbox preflight |
| 无生命周期 API | 无 restart/redeploy/logs | 无法运维 | 增加 deployments API |
| 无供应链治理 | 不锁依赖、不扫包 | 依赖投毒/不可复现 | requirements hash、私有源策略、allowlist/denylist 和扫描预留 |
| 审计不足 | AlgorithmRun 有审计，包生命周期弱 | 版本切换责任不清 | 包、版本、部署、调用全链路审计 |

## 6. 实施计划

### Phase 0：冻结边界与补文档

目标：把当前事实写清楚，避免继续把 `local_python_adapter` 或占位 digest 误认为生产部署。

任务：

- [x] 更新本项目文档，明确 P0-MVP 与生产级差距。
- [x] 用户指南已说明生产限制：当前默认本地 sandbox runtime，见 `doc/algorithm-upload-user-guide.md` 的“当前执行边界”。
- [x] 在管理 UI 的构建部署状态上标注 runtime backend/health，避免误导为生产运行时。
- [x] 在文档和 UI 中把占位 digest 逐步改称 `runtime_digest`、`package_digest` 或 `environment_digest`。

验收：

- 文档明确说明当前执行位置、风险和生产化路线。
- UI 不再把占位 digest 表达成真实运行环境 digest。
- 文档明确 P0-prod 默认是独立沙箱进程，不是 API 进程内执行。

### Phase 1：运行时抽象层

目标：先把“怎么执行上传算法”抽成可替换边界，让业务服务不依赖具体运行方式。

任务 1：新增运行时接口

**描述：** 引入 `AlgorithmRuntimeBackend` 协议，至少包含 `validate_runtime()`、`build()`、`deploy()`、`health()`、`predict()`、`stop()`、`logs()`。

**验收：**
- [x] `AlgorithmPackageService` 不再直接知道本机 importlib 执行细节。
- [x] 现有 `local_python_adapter` 迁移为 `LocalInProcessRuntimeBackend`，仅用于 dev/test。
- [x] 生产配置默认使用 `local_sandbox_runtime`，`local_inprocess` 需显式配置。
- [x] 单测覆盖 sandbox predict/timeout，API 测试覆盖 build/deploy/predict 分派。

**可能文件：**
- `backend/app/services/algorithm_runtimes/base.py`
- `backend/app/services/algorithm_runtimes/local_inprocess.py`
- `backend/app/services/research_engine_algorithm_package_service.py`

任务 2：拆分构建、部署、运行服务

**描述：** 从 `AlgorithmPackageService` 中拆出 `AlgorithmBuildService`、`AlgorithmDeploymentService`、`AlgorithmRuntimeGateway`。

**验收：**
- [x] 包上传/契约校验仍由 `AlgorithmPackageService` 管。
- [x] 构建、部署、运行通过 runtime backend 边界完成。
- [x] 当前 API 行为保持兼容。

任务 3：补结构化状态模型

**描述：** 给 `AlgorithmVersion.deployment` 定义固定结构，记录 backend、endpoint、health、last_error、log_refs、resource_limits、package_digest、environment_digest、runtime_digest。

**验收：**
- [x] 前端管理表能显示 runtime backend、health、endpoint 类型和 digest 类型。
- [x] 旧版本缺字段时可兼容读取。

### Phase 2：本地沙箱运行时

目标：切断主进程执行风险，形成 P0-prod 默认执行单元。

任务 4：新增 `LocalSandboxRuntimeBackend`

**描述：** 每次 dry-run/predict 使用独立 Python 子进程执行 runner shim。该 backend 是 P0-prod 默认路径。

**验收：**
- [x] `predict()` 超时会杀掉子进程。
- [x] 子进程 cwd 限定在 package path。
- [x] 环境变量白名单传递，默认不传宿主敏感 env。
- [x] stdout/stderr 被捕获、截断并挂到运行日志。
- [x] `sys.exit()`、异常和非零退出码会转成结构化失败。

任务 5：运行 shim

**描述：** 新增 `scripts/algorithm_runtime_shim.py` 或后端模块，以 JSON stdin/stdout 协议调用上传包 entrypoint。

**验收：**
- [x] 正常输出只通过 JSON 返回。
- [x] 异常返回结构化 `error_type/message/traceback_tail`。
- [x] 非 JSON 输出不会污染 API 响应。
- [x] 算法运行不会污染 API 进程的 `cwd`、`sys.path`、`sys.modules`。

任务 6：资源和并发基础限制

**描述：** 对 sandbox runtime 增加 timeout、最大输出大小、并发 semaphore，Linux 下可加 `resource.setrlimit`。

**验收：**
- [x] 死循环样例会按超时失败，不阻塞 API。
- [x] 大日志被截断。
- [x] 并发超过配置时排队或拒绝。
- [x] 资源限制配置写入 `runtime_snapshot`。

### Phase 3：依赖环境治理

目标：让上传包在可追溯、可复现的本地环境里运行。

任务 7：requirements 摘要和策略

**描述：** 构建阶段读取 `requirements.txt`，记录 `requirements_sha256`、Python 版本、允许的 index 源和安装策略。

**验收：**
- [x] `environment_digest` 由 Python 版本、requirements hash、runtime backend 配置计算。
- [x] build log 不暴露凭证。
- [x] 禁止明显危险或不允许的依赖来源。

任务 8：受控 venv 或预置依赖环境

**描述：** 支持平台预置依赖环境；必要时为算法版本创建受控 venv，并缓存复用相同 `environment_digest`。

**验收：**
- requirements 安装超时、大小限制和私有源策略可配置。
- 依赖安装失败返回结构化错误和日志 tail。
- 运行时使用受控解释器，不依赖 API 进程环境的偶然状态。

任务 9：模型 artifact 策略

**描述：** 明确源码包和模型权重的关系。20MB ZIP 不适合长期承载大模型权重，后续应支持受控 artifact 存储。

**验收：**
- 文档明确大模型文件走 artifact 或对象存储路线。
- [x] version 记录 package digest。
- artifact digest 随受控 artifact 存储补齐。

### Phase 4：运维、审计和 UI

目标：让算法部署可被日常维护，而不是只能靠数据库状态。

任务 10：部署运维 API

**描述：** 增加 restart、redeploy、health、logs API。对 sandbox backend，restart 语义是重新执行 preflight 或重建 warm worker；没有长驻进程时不伪装成服务重启。

**验收：**
- [x] 管理页能查看 health 和日志 tail。
- [x] redeploy 后 active version 仍可调用。
- [x] sandbox backend 不可用时新调用返回可理解错误。

任务 11：审计增强

**描述：** 上传、校验、构建、部署、激活、回滚、冻结、下线、日志查看都写审计事件。

**验收：**
- 每个版本状态变更都可追溯 actor、before、after、request_id。
- 日志下载/查看记录审计。

任务 12：前端状态和错误体验

**描述：** 管理页增加 backend、health、runtime digest、environment digest、日志入口、redeploy 按钮。

**验收：**
- [x] 用户能区分 `local_inprocess`、`local_sandbox`、warm worker 等 backend。
- [x] 用户能区分 validated/built/deployed_staging/active/unhealthy。
- [x] 构建失败和预测失败能看到结构化错误，不需要查后端日志。

### Phase 5：安全加固

目标：把“能沙箱运行”收敛成“可以运行半可信算法包”的平台。

任务 13：包安全扫描

**描述：** 扫描 symlink、隐藏可执行、压缩炸弹、异常大模型、危险文件名和二进制类型。

**验收：**
- [x] 非法 ZIP 在 validate 前或 validate 阶段被拒绝。
- [x] 错误定位到具体文件路径。

任务 14：依赖供应链策略

**描述：** 对 requirements 做 allowlist/denylist、hash lock、私有源限制和 license/security 扫描预留。

**验收：**
- [x] 禁止安装明显危险包或从未授权 index 拉包。
- [x] build log 不暴露凭证。

任务 15：网络和数据边界

**描述：** 默认 sandbox 不透传敏感环境变量；外网访问和内部服务访问必须通过配置 allowlist。若需要硬性禁网，应增强到 cgroup/nsjail/firejail 等系统级隔离。

**验收：**
- [x] 算法不能默认读取数据库、云凭证、API key 等宿主敏感配置。
- [x] 网络策略和 env 白名单写入 runtime snapshot。

## 7. 推荐优先级

| 优先级 | 工作 | 原因 |
| --- | --- | --- |
| 1 | Phase 1 运行时抽象层 | 不先抽边界，sandbox 会和现有 service 强耦合 |
| 2 | Phase 2 本地沙箱运行时 | 立刻降低主进程被上传代码拖垮的风险，是 P0-prod 默认路径 |
| 3 | Phase 3 依赖环境治理 | 没有受控环境，算法可复现性和可运维性都不足 |
| 4 | Phase 4 运维与审计 | 没有日志/redeploy/审计，生产不可维护 |
| 5 | Phase 5 安全加固 | 上传代码平台必须持续收敛供应链和数据边界风险 |

## 8. 关键设计决策

### 决策 1：保留 `local_inprocess`，但只允许 dev/test

原因：现有测试和本地 demo 依赖它，直接删除会扩大迁移成本。生产配置应默认拒绝 `local_inprocess`。

### 决策 2：P0-prod 默认使用 `local_sandbox_runtime`

原因：当前最大风险是上传代码在 API 主进程内执行。独立 subprocess/worker + JSON shim 可以用更低运维成本解决主风险，并复用已有 ComputeEngine 本地 adapter 的设计经验。

### 决策 3：不规划额外部署形态

原因：当前核心风险可以通过本地沙箱解决。继续保留额外部署形态会稀释路线重点，并把文档带回运维复杂度讨论。

### 决策 4：AlgorithmRun 必须冻结版本和 digest

原因：active 指针会变化。每次运行必须记录当时使用的 `algorithm_version_id`、`package_sha256`、`runtime_digest`、`environment_digest` 和 runtime snapshot，才能保证结果可追溯。

## 9. 开放问题

- sandbox 是否需要硬性禁网，还是 P0 先通过 env 白名单和审计约束？
- requirements 是否允许在线安装，还是只允许平台预置依赖和私有源？
- 上传包大小 20MB 是否够用？如果要支持模型权重，建议改为源码包 + 模型 artifact 分离。
- Linux 资源限制优先采用 `resource.setrlimit`、cgroup、nsjail/firejail，还是仅做 timeout + 并发上限的短期方案？

## 10. 下一步

建议第一批实现只做 Phase 1 + Phase 2，目标是先让上传代码离开 API 主进程：

1. 新增 runtime backend 抽象。
2. 把当前 `execute_version_path()` 包装成 dev/test-only `LocalInProcessRuntimeBackend`。
3. 新增 `LocalSandboxRuntimeBackend` 和 JSON runner shim。
4. 将 validate dry-run 和 AlgorithmRun predict 切到 sandbox backend。
5. 补超时、日志捕获、结构化错误、env 白名单和单测。

完成后再做 Phase 3 的依赖环境治理，并继续围绕本地沙箱 runtime 收敛安全、审计和运维能力。
