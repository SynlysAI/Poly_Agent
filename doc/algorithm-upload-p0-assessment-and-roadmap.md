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

但执行层仍然是 P0 本机适配层，不是生产级部署：

- `build_package()` 只生成可追踪的 `image_digest` 占位符，没有 Docker/BuildKit 真实镜像构建。
- `deploy_version()` 只登记 `kind=local_python_adapter` 和 `internal://algorithm-package-runner`，没有独立算法服务进程或容器。
- `execute_version_path()` 在后端 API 进程内通过 `sys.path`、`os.chdir()`、`importlib` 直接调用上传包的 `load()` / `predict()`。
- `timeout_seconds` 被传入接口但当前没有真实超时、中断、CPU、内存、进程数或文件系统隔离。
- `requirements.txt` 被打包和保存，但当前构建阶段没有安装依赖、锁定依赖、扫描依赖或形成可复现运行环境。

因此准确状态应定义为：

> P0-MVP 产品与资产治理闭环可用；执行环境只是本机 Python 适配层。生产级必须补齐进程/容器隔离、真实构建、独立运行时、资源治理、日志审计和可运维生命周期。

## 2. 当前能力清单

| 模块 | 当前状态 | 代码证据 | 评价 |
| --- | --- | --- | --- |
| 垂类预测工作台 | 已完成 | `frontend/src/views/VerticalPredictionView.vue`、`frontend/src/views/vertical-prediction/*` | 用户入口清晰 |
| 网页打包助手 | 已完成 | `AlgorithmUploadPanel.vue`、`POST /research-engine/algorithm-packages:pack` | 可从 `.py` + 表单生成标准 ZIP |
| 标准 ZIP 上传 | 已完成 | `POST /research-engine/algorithm-packages` | 只支持 `.zip`，20MB 限制 |
| 模板下载 | 已完成 | `GET /research-engine/algorithm-packages/template` | 可作为算法工程师起点 |
| 契约校验 | 已完成 P0 | `_validate_contract()` | 限定 `contract_version=0.1` 和 Python 3.11 |
| ZIP 安全校验 | 部分完成 | `_safe_extract()`、`_validate_archive_member()` | 有路径穿越、后缀、Dockerfile、`.env`、虚拟环境目录限制 |
| dry-run | 已完成但不隔离 | `validate_package()` -> `execute_version_path()` | 在后端进程内执行上传代码 |
| 构建 | 占位 | `build_package()` | 只写 digest 占位和日志，不产生镜像 |
| 部署 | 占位 | `deploy_version()` | 只登记 `local_python_adapter` |
| 激活/回滚/冻结/下线 | 已完成 | `activate_version()`、`rollback_version()`、`freeze_version()`、`decommission_version()` | 支持版本治理 |
| 调用追溯 | 已完成 P0 | `create_algorithm_run()` | 记录 `algorithm_version_id`、`package_sha256`、`image_digest`、`runtime_snapshot` |
| 独立运行进程 | 未完成 | 无 supervisor / worker / sidecar | API 进程与算法执行耦合 |
| 容器隔离 | 未完成 | 无 Dockerfile 生成、BuildKit、容器启动 | 不可运行不可信代码 |
| 资源限制 | 未完成 | 无 cgroup / Docker limits / subprocess timeout | 上传代码可阻塞主进程 |
| 运行日志 | 未完成 | 只有简要 build/deployment logs | 无 stdout/stderr、tail、脱敏、下载 |
| 健康检查 | 未完成 | 无 `/health` 算法服务 | active 前无法验证运行时 |
| 可运维操作 | 未完成 | 无 stop/restart/redeploy/logs API | 生产维护不可控 |

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
      -> execute_version_path() 在后端进程内 dry-run
      -> 创建 AlgorithmVersion(status=validated)
  -> build_package()
      -> 生成 sha256 占位 image_digest
      -> status=built
  -> deploy_version()
      -> deployment.kind=local_python_adapter
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
       AlgorithmPackageService.run_version()
       execute_version_path()
  -> AlgorithmRun(status=completed/failed)
```

关键风险：上传包的 Python 代码在 API 服务进程里执行，且会临时修改 `cwd` 和 `sys.path`。这对本地 demo 足够，但生产环境不能接受。

## 4. 生产级目标

目标不是简单“把 P0 接上 Docker”，而是把垂类模型能力升级为可治理的模型资产运行平台。

### 4.1 必须具备的生产能力

1. 隔离：上传算法不能在 API 主进程内执行；至少使用独立 subprocess，生产默认使用容器。
2. 可复现：构建过程必须基于固定 base image、锁定 Python 版本、记录依赖和镜像 digest。
3. 可限制：每次运行必须有 CPU、内存、进程数、文件系统、网络、超时和并发限制。
4. 可观测：构建日志、运行日志、健康检查、启动失败、预测失败都要结构化记录。
5. 可治理：版本不可变；active 只是指针；激活、回滚、冻结、下线都有审计。
6. 可恢复：容器可 stop/restart/redeploy，服务重启后能从 registry 恢复 deployed/active 版本。
7. 可扩展：先本机 Docker，后续可以平滑迁移到 Kubernetes/KServe 或远程模型服务。

### 4.2 推荐目标架构

```text
VerticalPrediction UI
  -> AlgorithmPackage API
  -> Package Store (.runtime / object storage)
  -> AlgorithmBuildService
       -> BuildKit/Docker builder
       -> image registry or local image store
  -> AlgorithmDeploymentService
       -> local Docker runtime for P0-prod
       -> health check / lifecycle / logs
  -> AlgorithmRuntimeGateway
       -> POST /predict to container service
       -> timeout / retry / circuit breaker / structured error
  -> AlgorithmRun
       -> frozen version + image digest + runtime snapshot + artifacts + audit
```

容器内统一协议：

```text
GET  /health
POST /predict
```

`/predict` 请求：

```json
{
  "inputs": {},
  "context": {
    "algorithm_id": "vertical_tg_predictor",
    "version_id": "aver_...",
    "run_id": "arun_..."
  }
}
```

`/predict` 响应：

```json
{
  "output_summary": {},
  "artifacts": [],
  "runtime": {
    "duration_ms": 123,
    "worker_pid": 1
  }
}
```

## 5. 生产化差距

| 差距 | 当前表现 | 生产风险 | 目标补齐 |
| --- | --- | --- | --- |
| 主进程执行用户代码 | `importlib` 直接执行 | 死循环、崩溃、内存爆、全局污染会影响 API | subprocess/容器执行 |
| 无真实 timeout | 参数存在但没有中断机制 | 请求可无限卡死 | Docker/API gateway 双层超时 |
| 无依赖环境 | 不安装 requirements | 本地能跑不代表服务能跑 | image build 安装依赖并记录日志 |
| 无资源配额 | 无 CPU/内存限制 | 单模型拖垮宿主 | Docker `--cpus`、memory、pids-limit |
| 无网络策略 | 上传代码可访问外网/内网 | 数据泄露、横向访问 | 默认禁网或 allowlist |
| 无文件系统隔离 | 代码运行在后端进程权限内 | 读取宿主敏感文件 | 容器只读根文件系统 + 最小挂载 |
| 无模型服务健康检查 | deploy 直接 ready | active 后才暴露问题 | deploy 必须通过 `/health` |
| 无生命周期 API | 无 stop/restart/logs | 无法运维 | 增加 deployments API |
| 无构建供应链治理 | 不锁依赖、不扫包 | 依赖投毒/不可复现 | lockfile、hash、扫描、私有源策略 |
| 审计不足 | AlgorithmRun 有审计，包生命周期弱 | 版本切换责任不清 | 包、版本、部署、调用全链路审计 |

## 6. 实施计划

### Phase 0：冻结边界与补文档

目标：把当前事实写清楚，避免继续把 `local_python_adapter` 误认为生产部署。

任务：

- [x] 更新本项目文档，明确 P0-MVP 与生产级差距。
- [x] 用户指南已说明生产限制：当前构建/部署不是 Docker 镜像，见 `doc/algorithm-upload-user-guide.md` 的“当前执行边界”。
- [ ] 在管理 UI 的构建部署状态上标注 `local_python_adapter`，避免误导为容器部署。

验收：

- 文档明确说明当前执行位置、风险和生产化路线。
- UI 不再把占位 digest 表达成真实镜像 digest。

### Phase 1：隔离抽象层

目标：先把“怎么执行上传算法”抽成可替换边界，避免后续 Docker 改动穿透业务服务。

任务 1：新增运行时接口

**描述：** 引入 `AlgorithmRuntimeBackend` 协议，至少包含 `validate_runtime()`、`build()`、`deploy()`、`health()`、`predict()`、`stop()`、`logs()`。

**验收：**
- `AlgorithmPackageService` 不再直接知道本机 importlib 执行细节。
- 现有 `local_python_adapter` 作为 `LocalInProcessRuntimeBackend` 保留，仅用于 dev/test。
- 单测覆盖 build/deploy/predict 的 backend 分派。

**可能文件：**
- `backend/app/services/algorithm_runtimes/base.py`
- `backend/app/services/algorithm_runtimes/local_inprocess.py`
- `backend/app/services/research_engine_algorithm_package_service.py`

任务 2：拆分构建、部署、运行服务

**描述：** 从 `AlgorithmPackageService` 中拆出 `AlgorithmBuildService`、`AlgorithmDeploymentService`、`AlgorithmRuntimeGateway`。

**验收：**
- 包上传/契约校验仍由 `AlgorithmPackageService` 管。
- 构建与部署状态更新通过明确服务完成。
- 当前 API 行为保持兼容。

任务 3：补结构化状态模型

**描述：** 给 `AlgorithmVersion.deployment` 定义固定结构，记录 backend、endpoint、container_id、health、last_error、log_refs、resource_limits。

**验收：**
- 前端管理表能显示 runtime backend、health、endpoint 类型。
- 旧版本缺字段时可兼容读取。

### Phase 2：进程隔离过渡版

目标：在 Docker 前先切断主进程执行风险，形成最小可控执行单元。

任务 4：新增 subprocess runtime

**描述：** 构建一个 `LocalSubprocessRuntimeBackend`，每次 dry-run/predict 使用独立 Python 子进程执行 runner shim。

**验收：**
- `predict()` 超时会杀掉子进程。
- 子进程 cwd 限定在 package path。
- 环境变量白名单传递，默认不传宿主敏感 env。
- stdout/stderr 被捕获并脱敏。

任务 5：运行 shim

**描述：** 新增 `scripts/algorithm_runtime_shim.py` 或后端模块，以 JSON stdin/stdout 协议调用上传包 entrypoint。

**验收：**
- 正常输出只通过 JSON 返回。
- 异常返回结构化 `error_type/message/traceback_tail`。
- 非 JSON 输出不会污染 API 响应。

任务 6：资源和并发基础限制

**描述：** 对 subprocess runtime 增加 timeout、最大输出大小、并发 semaphore，Linux 下可加 `resource.setrlimit`。

**验收：**
- 死循环样例会按超时失败。
- 大日志被截断。
- 并发超过配置时排队或拒绝。

### Phase 3：本机 Docker/BuildKit 生产路径

目标：实现 P0-prod 默认路径：真实镜像构建、容器部署、HTTP 调用和健康检查。

任务 7：生成受控 build context

**描述：** 从标准 ZIP 生成平台 Dockerfile、runtime server、requirements 和源码目录。禁止用户自带 Dockerfile 参与构建。

**验收：**
- base image 固定为配置项，例如 `python:3.11-slim` 的 digest。
- 容器使用非 root 用户。
- 入口统一启动平台 runtime server，不直接运行用户脚本。

任务 8：Docker builder

**描述：** 接入 Docker SDK 或 CLI，执行真实 build，记录完整日志、镜像 ID 和 repo digest。

**验收：**
- `image_digest` 来自真实镜像，不再是占位 hash。
- build 失败返回结构化错误和日志 tail。
- requirements 安装超时、大小限制和私有源策略可配置。

任务 9：容器 deployment

**描述：** deploy 启动或替换版本容器，设置 CPU、内存、pids、只读根文件系统、临时目录、网络策略和 labels。

**验收：**
- deployment 记录 `container_id`、`endpoint`、`health=ready/unhealthy`。
- health check 失败不能 activate。
- freeze/decommission 可停止容器或阻止新调用。

任务 10：HTTP runtime gateway

**描述：** AlgorithmRun 调用不再本机 import，而是通过内部 HTTP 调容器 `/predict`。

**验收：**
- 调用超时有明确错误。
- 容器 5xx、非 JSON、schema 不匹配都能转成 AlgorithmRun failed。
- 成功响应记录 duration、backend、container/image digest。

### Phase 4：运维、审计和 UI

目标：让算法部署可被日常维护，而不是只能靠数据库状态。

任务 11：部署运维 API

**描述：** 增加 stop、restart、redeploy、health、logs API。

**验收：**
- 管理页能查看 health 和日志 tail。
- restart 后 active version 仍可调用。
- 停止容器后新调用返回可理解错误。

任务 12：审计增强

**描述：** 上传、校验、构建、部署、激活、回滚、冻结、下线、日志查看都写审计事件。

**验收：**
- 每个版本状态变更都可追溯 actor、before、after、request_id。
- 日志下载/查看记录审计。

任务 13：前端状态和错误体验

**描述：** 管理页增加 backend、health、container id、真实 image digest、日志入口、重启按钮。

**验收：**
- 用户能区分 validated/built/deployed_staging/active/unhealthy。
- 构建失败和预测失败能看到结构化错误，不需要查后端日志。

### Phase 5：安全加固

目标：把“能容器运行”收敛成“可以运行半可信算法包”的平台。

任务 14：包安全扫描

**描述：** 扫描 symlink、隐藏可执行、压缩炸弹、异常大模型、危险文件名和二进制类型。

**验收：**
- 非法 ZIP 在 validate 前或 validate 阶段被拒绝。
- 错误定位到具体文件路径。

任务 15：依赖供应链策略

**描述：** 对 requirements 做 allowlist/denylist、hash lock、私有源限制和 license/security 扫描预留。

**验收：**
- 禁止安装明显危险包或从未授权 index 拉包。
- build log 不暴露凭证。

任务 16：网络和数据边界

**描述：** 默认算法容器无外网；如需访问内部服务，必须通过配置 allowlist。

**验收：**
- 算法容器不能访问宿主敏感路径。
- 算法容器不能默认访问 metadata service、内网管理端口和数据库。

## 7. 推荐优先级

| 优先级 | 工作 | 原因 |
| --- | --- | --- |
| 1 | Phase 1 隔离抽象层 | 不先抽边界，Docker 会和现有 service 强耦合 |
| 2 | Phase 2 subprocess runtime | 立刻降低主进程被上传代码拖垮的风险 |
| 3 | Phase 3 Docker/BuildKit | 实现真实生产路径和资源隔离 |
| 4 | Phase 4 运维与审计 | 没有日志/重启/审计，生产不可维护 |
| 5 | Phase 5 安全加固 | 上传代码平台必须持续收敛供应链和数据边界风险 |

## 8. 关键设计决策

### 决策 1：保留 `local_inprocess`，但只允许 dev/test

原因：现有测试和本地 demo 依赖它，直接删除会扩大迁移成本。生产配置应默认拒绝 `local_inprocess`。

### 决策 2：先 subprocess，再 Docker

原因：subprocess 可以快速把 API 主进程从用户代码中解耦，也能复用后续容器内的 runtime shim。Docker 是生产默认路径，但不应阻塞先降低当前风险。

### 决策 3：用户包不能自带 Dockerfile

原因：平台需要控制 base image、用户、网络、文件系统和启动协议。用户自定义 Dockerfile 可作为未来高级功能，但必须走独立审批和更强扫描。

### 决策 4：AlgorithmRun 必须冻结版本和 digest

原因：active 指针会变化。每次运行必须记录当时使用的 `algorithm_version_id`、`package_sha256`、`image_digest` 和 runtime snapshot，才能保证结果可追溯。

## 9. 开放问题

- 本机生产路径是否必须支持 GPU，还是先只支持 CPU？
- 镜像是否只保存在本机 Docker daemon，还是接入私有 registry？
- 算法容器默认是否允许访问外网下载模型？建议默认禁止，改为模型权重随包上传或走受控对象存储。
- 生产部署目标是单机 Docker 先上线，还是直接 Kubernetes/KServe？
- 上传包大小 20MB 是否够用？如果要支持模型权重，建议改为源码包 + 模型 artifact 分离。

## 10. 下一步

建议第一批实现只做 Phase 1 + Phase 2，目标是在不引入 Docker 运维复杂度的情况下，先让上传代码离开 API 主进程：

1. 新增 runtime backend 抽象。
2. 把当前 `execute_version_path()` 包装成 dev-only backend。
3. 新增 subprocess backend 和 JSON shim。
4. 将 validate dry-run 和 AlgorithmRun predict 切到 subprocess backend。
5. 补超时、日志捕获、结构化错误和单测。

完成后再进入 Docker/BuildKit，风险会小很多，因为业务层已经只依赖 runtime 接口。
