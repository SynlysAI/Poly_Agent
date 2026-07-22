# PolyAgent 与 SpecLabOS 外部实验任务联动实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 PolyAgent Alchemist 将推荐实验条件作为通用实验批次下发到 SpecLabOS，并在 SpecLabOS 任务中心展示已接收的外部实验任务。

**Architecture:** SpecLabOS 新增独立的外部实验任务数据域、接收 API 和任务中心页签，不复用 SmartAccess 执行记录。PolyAgent 后端通过独立的 HTTP 客户端读取环境变量并向 SpecLabOS 转发经过 Session 与搜索空间校验的 Alchemist 推荐条件，前端只负责收集实验说明与展示接收结果。

**Tech Stack:** FastAPI、Pydantic、MongoDB、httpx、Vue 3、Element Plus、React、Ant Design。

## Global Constraints

- 首期仅接收和展示任务，禁止创建工作流、设备任务、SmartAccess 运行或消息队列投递。
- PolyAgent 使用 `SPECLABOS_BASE_URL` 和 `SPECLABOS_API_KEY`；API 密钥不得返回给前端、写入日志或提交到仓库。
- SpecLabOS 接口使用 Bearer Token 鉴权；部署时其接入令牌必须与 PolyAgent 的 `SPECLABOS_API_KEY` 一致。
- 任务采用“批次任务 + 多条条件”的通用协议，不能假设来源永远是 Alchemist。
- UI 保留 PolyAgent 现有 Alchemist 方法来源标注；不得新建或伪造第三方来源标注。
- 用户未确认新增自动化测试，本次不新增测试文件；使用现有项目环境执行针对性的接口与页面手工验证。
- 未经用户要求不得创建 Git 提交。
- SpecLabOS 的运行、检查和安装依赖必须先执行 `conda activate SpecLabOS`。

---

## 文件结构

### PolyAgent

| 文件 | 责任 |
| --- | --- |
| `backend/app/core/config.py` | 读取 SpecLabOS 地址、密钥和超时配置。 |
| `backend/app/schemas/alchemist.py` | 定义 Alchemist 向 SpecLabOS 下发的请求与响应契约。 |
| `backend/app/services/speclabos_dispatch_service.py` | 安全调用 SpecLabOS 外部实验任务接收接口。 |
| `backend/app/api/v1/endpoints/alchemist.py` | 校验 Session/模型/条件后调用下发服务。 |
| `frontend/src/api/alchemistApi.js` | 封装 Alchemist 下发接口调用。 |
| `frontend/src/views/alchemist/AcquisitionPanel.vue` | 提供下发弹窗、条件预览和状态反馈。 |
| `backend/.env.example`（若存在） | 增加不含真实密钥的环境变量示例。 |

### SpecLabOS

| 文件 | 责任 |
| --- | --- |
| `backend/app/schemas/external_experiment_dispatch.py` | 定义通用外部实验任务的入站、列表、详情和响应模型。 |
| `backend/app/repositories/external_experiment_dispatch_repository.py` | 在 `external_experiment_dispatches` 集合中创建、查询任务批次。 |
| `backend/app/services/external_experiment_dispatch_service.py` | 校验、生成 `dispatch_id` 和创建初始 `received` 状态。 |
| `backend/app/runtime.py` | 注册 repository 与 service 的缓存工厂。 |
| `backend/app/api/routes/external_experiment_dispatches.py` | 提供接收、列表和详情 API。 |
| `backend/app/api/app_factory.py` | 注册新 API router。 |
| `frontend/src/services/externalExperimentDispatchApi.js` | 调用列表和详情接口。 |
| `frontend/src/pages/ExternalExperimentDispatchesPage.jsx` | 展示表格与详情抽屉。 |
| `frontend/src/pages/TaskCenterPage.jsx` | 增加“外部实验任务”任务中心页签。 |

## 任务 1：建立 SpecLabOS 的通用外部实验任务数据域

**Files:**
- Create: `E:/github_project/SpecLabOS/backend/app/schemas/external_experiment_dispatch.py`
- Create: `E:/github_project/SpecLabOS/backend/app/repositories/external_experiment_dispatch_repository.py`
- Create: `E:/github_project/SpecLabOS/backend/app/services/external_experiment_dispatch_service.py`
- Modify: `E:/github_project/SpecLabOS/backend/app/runtime.py`

**Interfaces:**
- Consumes: `pydantic.BaseModel`、`app.core.mongo.get_database()` 返回的 MongoDB database。
- Produces: `ExternalExperimentDispatchCreateRequest`、`ExternalExperimentDispatchService.create_dispatch()`、`list_dispatches()`、`get_dispatch()`。

- [ ] **Step 1: 定义入站与展示模型**

在 schema 文件中定义以下嵌套模型和字段，所有说明使用中文 docstring：

```python
class ExternalExperimentObject(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)


class ExternalExperimentCondition(BaseModel):
    condition_id: str = Field(min_length=1, max_length=120)
    parameters: dict[str, float | int | str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalExperimentDispatchCreateRequest(BaseModel):
    source_system: str = Field(min_length=1, max_length=80)
    source_module: str = Field(min_length=1, max_length=80)
    source_reference: dict[str, Any] = Field(default_factory=dict)
    experiment_name: str = Field(min_length=1, max_length=200)
    experiment_object: ExternalExperimentObject
    experiment_content: str | None = Field(default=None, max_length=10000)
    conditions: list[ExternalExperimentCondition] = Field(min_length=1, max_length=100)
    optimization_context: dict[str, Any] = Field(default_factory=dict)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
```

同时定义列表项、列表响应、详情响应和创建响应；`dispatch_id`、`status`、`received_at` 均由服务端响应提供。

- [ ] **Step 2: 实现独立仓储**

创建 repository，构造函数保存 `database["external_experiment_dispatches"]`。实现以下方法：

```python
def create(self, record: dict) -> dict:
    self._collection.insert_one(record)
    return dict(record)


def list(self, keyword: str | None = None) -> list[dict]:
    query = {}
    if keyword:
        query["$or"] = [
            {"experiment_name": {"$regex": keyword, "$options": "i"}},
            {"experiment_object.name": {"$regex": keyword, "$options": "i"}},
            {"source_system": {"$regex": keyword, "$options": "i"}},
            {"source_module": {"$regex": keyword, "$options": "i"}},
        ]
    return list(self._collection.find(query, {"_id": 0}).sort("received_at", -1))


def get(self, dispatch_id: str) -> dict | None:
    return self._collection.find_one({"dispatch_id": dispatch_id}, {"_id": 0})
```

- [ ] **Step 3: 实现服务层**

服务层必须生成 `ext_exp_<12 位十六进制>` 格式的 `dispatch_id`，将条件模型转换为字典，并构造固定初始记录：

```python
record = {
    "dispatch_id": dispatch_id,
    "status": "received",
    "source_system": payload.source_system.strip().lower(),
    "source_module": payload.source_module.strip().lower(),
    "source_reference": payload.source_reference,
    "experiment_name": payload.experiment_name.strip(),
    "experiment_object": payload.experiment_object.model_dump(),
    "experiment_content": payload.experiment_content,
    "conditions": [item.model_dump() for item in payload.conditions],
    "optimization_context": payload.optimization_context,
    "extra_metadata": payload.extra_metadata,
    "received_at": now_text,
}
```

`list_dispatches()` 将每条记录投影为 `dispatch_id`、状态、来源、实验对象、条件数和接收时间；`get_dispatch()` 对不存在的标识抛出 404。

- [ ] **Step 4: 接入运行时工厂**

在 `runtime.py` 中新增并缓存：

```python
@lru_cache(maxsize=1)
def get_external_experiment_dispatch_repository() -> ExternalExperimentDispatchRepository:
    return ExternalExperimentDispatchRepository(get_database())


@lru_cache(maxsize=1)
def get_external_experiment_dispatch_service() -> ExternalExperimentDispatchService:
    return ExternalExperimentDispatchService(
        repository=get_external_experiment_dispatch_repository(),
    )
```

- [ ] **Step 5: 进行服务层手工验证**

在激活 `SpecLabOS` 环境后，使用 FastAPI 交互文档或临时 Python REPL 创建一个包含两条条件的请求，确认 MongoDB 记录的状态为 `received`，列表投影中的 `condition_count` 为 `2`。验证后不得保留临时脚本。

## 任务 2：暴露 SpecLabOS 接收与查询 API

**Files:**
- Create: `E:/github_project/SpecLabOS/backend/app/api/routes/external_experiment_dispatches.py`
- Modify: `E:/github_project/SpecLabOS/backend/app/api/app_factory.py`

**Interfaces:**
- Consumes: 任务 1 的 schema 与 `get_external_experiment_dispatch_service()`。
- Produces: `POST /api/external-experiment-dispatches`、`GET /api/external-experiment-dispatches`、`GET /api/external-experiment-dispatches/{dispatch_id}`。

- [ ] **Step 1: 创建采用 Bearer Token 的路由依赖**

使用独立的 `app.api.external_auth.require_external_api_auth`，以 SpecLabOS 的 `external_api.api_token` 校验外部服务调用，同时兼容平台用户 Token 查询。Router 结构如下：

```python
router = APIRouter(
    prefix="/api/external-experiment-dispatches",
    tags=["external-experiment-dispatches"],
    dependencies=[Depends(require_external_api_auth)],
)
```

- [ ] **Step 2: 实现创建接口**

```python
@router.post("", response_model=ExternalExperimentDispatchCreateResponse)
def create_dispatch(
    payload: ExternalExperimentDispatchCreateRequest,
) -> ExternalExperimentDispatchCreateResponse:
    record = get_external_experiment_dispatch_service().create_dispatch(payload)
    return ExternalExperimentDispatchCreateResponse(
        dispatch_id=record["dispatch_id"],
        status=record["status"],
        received_at=record["received_at"],
    )
```

该接口只写入任务记录，不调用执行端、RabbitMQ 或工作流。

- [ ] **Step 3: 实现列表与详情接口**

```python
@router.get("", response_model=ExternalExperimentDispatchListResponse)
def list_dispatches(keyword: str | None = Query(default=None, max_length=200)):
    items = get_external_experiment_dispatch_service().list_dispatches(keyword)
    return ExternalExperimentDispatchListResponse(items=items)


@router.get("/{dispatch_id}", response_model=ExternalExperimentDispatchDetailResponse)
def get_dispatch(dispatch_id: str):
    return get_external_experiment_dispatch_service().get_dispatch(dispatch_id)
```

- [ ] **Step 4: 注册 API router**

在 `app_factory.py` 的 routes import 与 `include_router` 列表中加入 `external_experiment_dispatches.router`，位置紧邻 `smartaccess.router`，使外部平台接入 API 集中在同一区域。

- [ ] **Step 5: 进行 HTTP 手工验证**

使用 `Authorization: Bearer <接入令牌>` 发送一条最小合法请求，预期为 200 且得到 `dispatch_id` 和 `received`；随后调用列表和详情接口，预期可看到原始两条条件。使用无效令牌复测，预期为 401 或 403，且数据库无新增记录。

## 任务 3：新增 SpecLabOS 任务中心页签与详情展示

**Files:**
- Create: `E:/github_project/SpecLabOS/frontend/src/services/externalExperimentDispatchApi.js`
- Create: `E:/github_project/SpecLabOS/frontend/src/pages/ExternalExperimentDispatchesPage.jsx`
- Modify: `E:/github_project/SpecLabOS/frontend/src/pages/TaskCenterPage.jsx`

**Interfaces:**
- Consumes: 任务 2 的列表和详情 API、现有 `http.js` 以及 Ant Design 的 `Table`、`Drawer`、`Descriptions`。
- Produces: `/tasks/external-experiment-dispatches` 对应的“外部实验任务”页签。

- [ ] **Step 1: 封装前端 API 客户端**

参考 `smartaccessApi.js` 使用现有 HTTP 客户端，定义：

```javascript
export async function fetchExternalExperimentDispatches(filters = {}) {
  const { data } = await http.get("/api/external-experiment-dispatches", {
    params: { keyword: filters.keyword || undefined },
  });
  return data.items || [];
}


export async function fetchExternalExperimentDispatchDetail(dispatchId) {
  const { data } = await http.get(`/api/external-experiment-dispatches/${dispatchId}`);
  return data;
}
```

- [ ] **Step 2: 实现列表与详情抽屉页面**

页面遵循 `SmartAccessRunsPage.jsx` 的 `PageToolbar + Card + Table` 模式，实现关键词筛选与刷新。表格列固定为：状态、实验任务、来源、实验对象、条件组数、关联来源、下发时间、操作。

详情使用 `Drawer`，加载成功后按以下结构展示：

```jsx
<Descriptions bordered size="small" column={1}>
  <Descriptions.Item label="实验任务">{detail.experiment_name}</Descriptions.Item>
  <Descriptions.Item label="实验对象">{detail.experiment_object?.name}</Descriptions.Item>
  <Descriptions.Item label="实验说明">{detail.experiment_content || "--"}</Descriptions.Item>
  <Descriptions.Item label="优化上下文">
    <pre>{JSON.stringify(detail.optimization_context || {}, null, 2)}</pre>
  </Descriptions.Item>
</Descriptions>
<Table
  rowKey="condition_id"
  dataSource={detail.conditions || []}
  columns={[
    { title: "条件编号", dataIndex: "condition_id" },
    { title: "参数", render: (_, row) => JSON.stringify(row.parameters) },
    { title: "附加信息", render: (_, row) => JSON.stringify(row.metadata || {}) },
  ]}
/>
```

状态显示首期使用“已接收”文本或现有 `StatusTag` 的 `accepted` 映射；不得提供开始、取消、重试或执行按钮。

- [ ] **Step 3: 注册任务中心页签**

在 `TaskCenterPage.jsx` 的 `TASK_TABS` 中新增：

```jsx
{
  key: "external-experiment-dispatches",
  label: "外部实验任务",
  children: <ExternalExperimentDispatchesPage />,
}
```

`router.jsx` 现有 `/tasks/:tabKey` 动态路由可直接承载，无需新增单独 route。

- [ ] **Step 4: 手工验证页面**

启动 SpecLabOS 后用浏览器进入 `/tasks/external-experiment-dispatches`：确认列表可加载、关键词可筛选、打开详情后两条条件均展示，且页面没有任何实验执行入口。

## 任务 4：新增 PolyAgent SpecLabOS 下发客户端和服务端接口

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/schemas/alchemist.py`
- Create: `backend/app/services/speclabos_dispatch_service.py`
- Modify: `backend/app/api/v1/endpoints/alchemist.py`
- Modify: `backend/.env.example`（仅在文件存在时）

**Interfaces:**
- Consumes: Alchemist `OptimizationSession`、当前用户权限校验、环境变量、SpecLabOS 的任务 2 API。
- Produces: `POST /api/v1/alchemist/sessions/{session_id}/acquisition/dispatch`，响应 `dispatch_id`、`status`、`received_at`。

- [ ] **Step 1: 增加运行时配置**

在 `Settings.__init__()` 中添加：

```python
self.speclabos_base_url: str = os.getenv("SPECLABOS_BASE_URL", "").strip().rstrip("/")
self.speclabos_api_key: str = os.getenv("SPECLABOS_API_KEY", "").strip()
self.speclabos_timeout_seconds: float = float(
    os.getenv("SPECLABOS_TIMEOUT_SECONDS", "30")
)
```

环境示例仅写变量名称与占位值，不写真实地址或密钥。

- [ ] **Step 2: 定义 Alchemist 下发请求和响应模型**

在 `schemas/alchemist.py` 添加：

```python
class DispatchExperimentObjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)


class DispatchExperimentConditionRequest(BaseModel):
    parameters: dict[str, float | int | str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DispatchExperimentRequest(BaseModel):
    experiment_name: str = Field(min_length=1, max_length=200)
    experiment_object: DispatchExperimentObjectRequest
    experiment_content: str | None = Field(default=None, max_length=10000)
    conditions: list[DispatchExperimentConditionRequest] = Field(min_length=1, max_length=100)
    strategy: str = Field(min_length=1, max_length=40)
    goal: Literal["maximize", "minimize"]
    acquisition_parameters: dict[str, float | int | str] = Field(default_factory=dict)


class DispatchExperimentResponse(BaseModel):
    dispatch_id: str
    status: str
    received_at: str
```

- [ ] **Step 3: 实现 HTTP 下发客户端**

服务只接受已标准化的 payload，使用 `httpx.Client` 发送：

```python
response = httpx.post(
    f"{settings.speclabos_base_url}/api/external-experiment-dispatches",
    json=payload,
    headers={"Authorization": f"Bearer {settings.speclabos_api_key}"},
    timeout=settings.speclabos_timeout_seconds,
)
response.raise_for_status()
data = response.json()
```

缺少地址或密钥时抛出中文配置错误；超时、连接异常、非 JSON 或非 2xx 响应映射为不包含密钥的中文业务异常。成功时必须验证 `dispatch_id`、`status`、`received_at` 均存在。

- [ ] **Step 4: 实现 Alchemist 下发路由**

在采集优化路由之后添加端点。执行顺序固定为：获取并授权 Session → 验证已训练模型 → 验证每条条件包含全部搜索变量并满足类型/范围/集合约束 → 组装通用 payload → 调用客户端 → 返回接收响应。

组装内容：

```python
payload = {
    "source_system": "polyagent",
    "source_module": "alchemist",
    "source_reference": {"session_id": session_id},
    "experiment_name": request.experiment_name,
    "experiment_object": request.experiment_object.model_dump(),
    "experiment_content": request.experiment_content,
    "conditions": [
        {
            "condition_id": f"condition-{index}",
            "parameters": item.parameters,
            "metadata": item.metadata,
        }
        for index, item in enumerate(request.conditions, start=1)
    ],
    "optimization_context": {
        "strategy": request.strategy,
        "goal": request.goal,
        "parameters": request.acquisition_parameters,
    },
    "extra_metadata": {},
}
```

条件校验应复用 `session.search_space.variables` 的类型定义，不得只检查参数键名。校验失败时不调用 SpecLabOS。

- [ ] **Step 5: 进行服务端手工验证**

在配置正确时调用下发接口，预期返回 SpecLabOS 的 `dispatch_id`；移除 `SPECLABOS_API_KEY` 后重启并复测，预期返回明确配置错误且 Alchemist 的 `last_suggestions` 和实验数据不变。

## 任务 5：在 Alchemist 采集优化面板添加下发入口

**Files:**
- Modify: `frontend/src/api/alchemistApi.js`
- Modify: `frontend/src/views/alchemist/AcquisitionPanel.vue`

**Interfaces:**
- Consumes: 任务 4 的下发接口、已有 `suggestions`、`selectedAcquisition`、`goal`、`xi` 与 `kappa` 状态。
- Produces: 采集建议表对应的“下发至 SpecLabOS”弹窗和接收结果反馈。

- [ ] **Step 1: 封装下发 API**

在 `alchemistApi.js` 采集优化区新增：

```javascript
export function dispatchExperimentTask(sessionId, payload) {
  return alchemistClient
    .post(`/sessions/${sessionId}/acquisition/dispatch`, payload)
    .then((response) => response.data);
}
```

- [ ] **Step 2: 增加下发状态与构造函数**

在 `AcquisitionPanel.vue` 中增加下发对话框状态：

```javascript
const dispatchDialogVisible = ref(false);
const dispatchLoading = ref(false);
const dispatchResult = ref(null);
const dispatchForm = ref({
  experimentName: "",
  objectName: "",
  objectType: "",
  objectDescription: "",
  experimentContent: "",
});
```

`openDispatchDialog()` 必须在 `suggestions.value.length === 0` 时提示先生成建议。`buildDispatchPayload()` 将当前建议行映射为 `conditions`，并将采集策略与当前 `xi` 或 `kappa` 传入 `acquisition_parameters`。

- [ ] **Step 3: 实现提交逻辑**

```javascript
async function handleDispatch() {
  if (!dispatchForm.value.experimentName.trim() || !dispatchForm.value.objectName.trim()) {
    ElMessage.warning("请填写实验任务名称和实验对象名称");
    return;
  }
  dispatchLoading.value = true;
  try {
    dispatchResult.value = await dispatchExperimentTask(props.sessionId, buildDispatchPayload());
    ElMessage.success(`实验任务已被 SpecLabOS 接收：${dispatchResult.value.dispatch_id}`);
  } catch (error) {
    ElMessage.error(`下发实验任务失败: ${error.message}`);
  } finally {
    dispatchLoading.value = false;
  }
}
```

失败时不得清空 `suggestions`，也不得写入实验数据。

- [ ] **Step 4: 实现弹窗与结果反馈**

在建议表格下增加按钮；弹窗包含实验任务名称、实验对象名称、对象类型、对象说明和实验说明字段，并以只读表格展示条件数量与参数。成功后展示“已接收”、批次标识和接收时间；关闭后保持建议表不变。按钮应在无建议时禁用。

- [ ] **Step 5: 进行端到端手工验证**

在 Alchemist 中生成单点 EI 建议并下发，确认 SpecLabOS 出现一个条件组数为 1 的任务；切换 BoTorch qEI 生成多点建议并下发，确认 SpecLabOS 仅出现一个任务批次且条件组数等于 qEI 建议数。使用错误 URL 复测，确认前端提示失败且推荐表仍保留。

## 任务 6：更新集成状态与交付说明

**Files:**
- Modify: `backend/app/services/integration_status_service.py`
- Modify: `backend/app/services/research_engine_readiness_service.py`
- Modify: `README.md` 或现有集成说明文档（仅在项目存在匹配章节时）

**Interfaces:**
- Consumes: `Settings.speclabos_base_url` 与 `Settings.speclabos_api_key`。
- Produces: SpecLabOS 的“已配置/可下发”集成状态，研究引擎准备度中实验执行阶段的准确描述。

- [ ] **Step 1: 更新 SpecLabOS 集成状态判断**

将当前固定的 `not_configured` 改为：地址和密钥均存在时返回 `configured_pending_verification`（详情说明“已配置外部实验任务下发，等待连通性验证”），否则返回 `not_configured`。此步骤不得将密钥放入状态详情。

- [ ] **Step 2: 更新准备度文案**

将实验执行阶段说明为“已支持将实验批次下发至 SpecLabOS 并接收登记；真实设备执行与结果回填待接入”，避免误报为自动实验已执行。

- [ ] **Step 3: 更新配置说明**

仅在已有的配置/集成文档章节中加入：`SPECLABOS_BASE_URL`、`SPECLABOS_API_KEY`、两端令牌一致的要求、首期仅登记不执行的限制。所有密钥示例使用占位值。

- [ ] **Step 4: 最终手工回归**

检查 PolyAgent 工具服务状态与研究准备度文本；确认未配置时仍显示未配置，配置后显示“待验证”，且所有页面与接口响应中均不含 API 密钥。

## 交付检查清单

- [ ] SpecLabOS 外部实验任务 API 可接收批次并返回 `dispatch_id`。
- [ ] SpecLabOS 任务中心可查询列表、筛选并查看所有条件详情。
- [ ] Alchemist 可从建议结果填写实验信息并下发单点/批量条件。
- [ ] 网络或鉴权失败不会丢失推荐结果，也不会创建错误的 SpecLabOS 任务。
- [ ] 没有引入 SmartAccess、工作流或设备执行副作用。
- [ ] 环境变量与交付说明不包含真实密钥。
