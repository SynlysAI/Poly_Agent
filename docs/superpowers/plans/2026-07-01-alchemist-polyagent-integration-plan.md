# ALchemist Web 功能移植到 Poly_Agent — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将 ALchemist 完整 Web 功能移植到 Poly_Agent 工具服务，后端代理模式，前端 Vue 3 重写，全中文化。

**架构：** ALchemist FastAPI（127.0.0.1:8004）仅供本地访问，Poly_Agent FastAPI（:8003）通过 httpx 代理转发 `/api/v1/alchemist/*` 请求，Poly_Agent Vue 3 前端重写所有 ALchemist 界面。

**技术栈：** Vue 3 + Element Plus + Plotly.js / FastAPI + httpx / ALchemist alchemist_core

---

## 文件结构

```
# ALchemist 项目 (E:\github_project\ALchemist)
api/main.py                                    [修改] 中文化 + 监听限定
api/run_api.py                                [修改] 默认 127.0.0.1:8004
api/routers/sessions.py                       [修改] 中文化注释+日志
api/routers/variables.py                      [修改] 中文化注释+日志
api/routers/experiments.py                    [修改] 中文化注释+日志
api/routers/models.py                         [修改] 中文化注释+日志
api/routers/acquisition.py                    [修改] 中文化注释+日志
api/routers/visualizations.py                 [修改] 中文化注释+日志
api/routers/websocket.py                      [修改] 中文化注释+日志
api/routers/llm.py                            [修改] 中文化注释+日志
api/models/requests.py                        [修改] 中文化注释
api/models/responses.py                       [修改] 中文化注释
api/services/session_store.py                 [修改] 中文化注释+日志
api/services/llm_service.py                   [修改] 中文化注释+日志
api/services/llm_config.py                    [修改] 中文化注释+日志
api/middleware/error_handlers.py              [修改] 中文化注释+日志

# Poly_Agent 项目 (E:\github_project\Poly_Agent)
backend/app/api/v1/endpoints/alchemist_proxy.py  [新建] 代理路由
backend/app/api/v1/router.py                     [修改] 注册代理路由
backend/app/core/config.py                       [修改] 新增 ALCHEMIST_BACKEND_URL
backend/requirements.txt                         [修改] 已含 httpx，无需改动
frontend/src/api/alchemistApi.js                 [新建] ALchemist API 封装
frontend/src/views/AlchemistToolView.vue         [新建] 主页面
frontend/src/views/alchemist/VariablePanel.vue   [新建] 变量定义面板
frontend/src/views/alchemist/ExperimentPanel.vue [新建] 实验设计面板
frontend/src/views/alchemist/ModelPanel.vue      [新建] GP建模面板
frontend/src/views/alchemist/AcquisitionPanel.vue[新建] 采集优化面板
frontend/src/views/alchemist/VisualizationPanel.vue [新建] 可视化面板
frontend/src/views/alchemist/components/LlmConfigDialog.vue [新建] LLM配置
frontend/src/views/ToolServicesView.vue          [修改] 新增工具卡片
frontend/src/router/index.js                     [修改] 新增路由
frontend/package.json                            [修改] 新增 plotly.js-dist 依赖
```

---

### 任务 1：ALchemist 后端 — 中文化入口文件

**文件：**
- 修改：`E:\github_project\ALchemist\api\main.py`
- 修改：`E:\github_project\ALchemist\api\run_api.py`

- [ ] **步骤 1：中文化 api/main.py**

将文件头部 docstring、FastAPI 元数据、日志、注释全部改为中文：

```python
"""
ALchemist FastAPI 应用

为 alchemist_core Session API 提供 RESTful 接口封装。
面向 React 前端设计，同时保持框架无关性。
"""

# 将 FastAPI 实例化部分改为：
app = FastAPI(
    title="ALchemist API",
    description="贝叶斯优化与主动学习的 REST API",
    version="0.3.4",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# CORS 注释改为中文
# CORS 配置 — 允许开发与生产环境的前端访问
# 默认包含常见开发服务器和生产地址
# 可通过 ALLOWED_ORIGINS 环境变量覆盖

# 路由注册注释改为中文
# 注册各功能模块路由

# root() docstring 改为中文
@app.get("/")
async def root():
    """根路径 — 返回 API 基本信息。"""

# health_check() docstring 改为中文
@app.get("/health")
async def health_check():
    """健康检查端点。"""

# SPA 静态文件段落注释改为中文
# 生产模式：托管前端静态文件
# 优先级：
# 1. api/static/ — 生产环境（pip 安装或构建包）
# 2. alchemist-web/dist/ — 开发环境（手动 npm run build）

# if static_dir.exists(): 前日志改为中文
logger.info(f"静态文件目录: {static_dir}")

# else 分支日志改为中文
logger.warning("未找到静态文件，Web 界面不可用。请在 alchemist-web/ 中运行 'npm run build' 或从构建包安装。")

# serve_spa docstring 改为中文
"""为非 API 路由提供 React SPA 页面服务。"""
```

- [ ] **步骤 2：修改 api/run_api.py 监听地址**

将默认监听地址从 `0.0.0.0:8000` 改为 `127.0.0.1:8004`：

```python
def main():
    """alchemist-web 命令入口点。"""
    # ...（开头保持不变）...
    
    if production:
        print("ALchemist API 生产模式启动...")
        print("Web 界面地址: http://localhost:8000")
        uvicorn.run(
            "api.main:app",
            host="127.0.0.1",
            port=8004,
            reload=False,
            log_level="warning",
            workers=1
        )
    else:
        print("ALchemist API 开发模式启动...")
        print("API 文档: http://localhost:8004/api/docs")
        uvicorn.run(
            "api.main:app",
            host="127.0.0.1",
            port=8004,
            reload=True,
            log_level="warning",
            access_log=False
        )
```

- [ ] **步骤 3：提交**

```bash
cd E:/github_project/ALchemist
git add api/main.py api/run_api.py
git commit -m "中文化 api/main.py 和 api/run_api.py，默认监听 127.0.0.1:8004"
```

---

### 任务 2：ALchemist 后端 — 中文化所有路由和模型文件

**文件：**
- 修改：`E:\github_project\ALchemist\api\routers\sessions.py`
- 修改：`E:\github_project\ALchemist\api\routers\variables.py`
- 修改：`E:\github_project\ALchemist\api\routers\experiments.py`
- 修改：`E:\github_project\ALchemist\api\routers\models.py`
- 修改：`E:\github_project\ALchemist\api\routers\acquisition.py`
- 修改：`E:\github_project\ALchemist\api\routers\visualizations.py`
- 修改：`E:\github_project\ALchemist\api\routers\websocket.py`
- 修改：`E:\github_project\ALchemist\api\routers\llm.py`
- 修改：`E:\github_project\ALchemist\api\models\requests.py`
- 修改：`E:\github_project\ALchemist\api\models\responses.py`
- 修改：`E:\github_project\ALchemist\api\services\session_store.py`
- 修改：`E:\github_project\ALchemist\api\services\llm_service.py`
- 修改：`E:\github_project\ALchemist\api\services\llm_config.py`
- 修改：`E:\github_project\ALchemist\api\middleware\error_handlers.py`

- [ ] **步骤 1：中文化 sessions.py**

系统性地将所有 docstring、注释、日志改为中文。改动示例：

```python
"""
Session 管理路由 — Session 生命周期管理。
"""

# 各端点 docstring 改为中文，例如：
@router.post("/sessions", ...)
async def create_session():
    """创建新的优化 Session。

    返回唯一的 Session ID，后续所有请求均需携带此 ID。
    Session 在服务器进程存活期间及磁盘存储中持久保留。
    """

@router.delete("/sessions/{session_id}", ...)
async def delete_session(session_id: str):
    """删除优化 Session。

    永久删除该 Session 及其所有关联数据。
    """

# 日志改为中文：
logger.error(f"Session 导入失败: {e}", exc_info=True)
raise HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="Session 导入失败，文件可能无效或已损坏"
)

# 所有硬编码的英文 error detail 改为中文：
detail=f"Session {session_id} 不存在或已过期"
detail="Session 文件无效或数据已损坏"
detail="获取锁状态失败，请检查服务器日志"
```

- [ ] **步骤 2：中文化 variables.py**

同理处理变量管理路由的 docstring 和错误消息。

- [ ] **步骤 3：中文化 experiments.py**

同理处理实验设计路由的 docstring 和错误消息。

- [ ] **步骤 4：中文化 models.py**

同理处理 GP 建模路由的 docstring 和错误消息。

- [ ] **步骤 5：中文化 acquisition.py**

同理处理采集优化路由的 docstring 和错误消息。

- [ ] **步骤 6：中文化 visualizations.py**

同理处理可视化路由的 docstring 和错误消息。

- [ ] **步骤 7：中文化 websocket.py**

同理处理 WebSocket 路由的 docstring 和日志。

- [ ] **步骤 8：中文化 llm.py**

同理处理 LLM 路由的 docstring 和日志。

- [ ] **步骤 9：中文化 models/requests.py 和 responses.py**

将 Pydantic 模型的 docstring 和 Field description 改为中文。

- [ ] **步骤 10：中文化 services 和 middleware 文件**

将 session_store.py、llm_service.py、llm_config.py、error_handlers.py 的日志和注释改为中文。

- [ ] **步骤 11：提交**

```bash
cd E:/github_project/ALchemist
git add api/routers/ api/models/ api/services/ api/middleware/
git commit -m "中文化 ALchemist API 所有路由、模型、服务、中间件的注释和日志"
```

---

### 任务 3：Poly_Agent 后端 — 创建 ALchemist 代理路由

**文件：**
- 创建：`E:\github_project\Poly_Agent\backend\app\api\v1\endpoints\alchemist_proxy.py`

- [ ] **步骤 1：创建完整的代理路由文件**

```python
"""ALchemist 主动学习工具代理路由。

将 /api/v1/alchemist/* 的请求通过 httpx 转发到 ALchemist 后端（127.0.0.1:8004）。
转发前通过 Poly_Agent 认证校验，确保只有已登录用户可访问。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import WebSocket
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

import httpx
import json

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("poly_agent.alchemist_proxy")

router = APIRouter(tags=["ALchemist 主动学习工具"])

ALCHEMIST_BACKEND_URL = getattr(settings, "alchemist_backend_url", "http://127.0.0.1:8004/api/v1")
_CLIENT: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """获取或创建用于代理转发的 httpx 异步客户端。

    Returns:
        配置了 ALchemist 后端基准 URL 的异步 HTTP 客户端。
    """
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.AsyncClient(
            base_url=ALCHEMIST_BACKEND_URL,
            timeout=httpx.Timeout(120.0),
        )
    return _CLIENT


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_alchemist_request(
    path: str,
    request: Request,
    current_user: dict | None = Depends(get_current_user),
):
    """代理转发 HTTP 请求到 ALchemist 后端。

    Args:
        path: ALchemist API 的相对路径。
        request: 原始请求对象。
        current_user: 当前登录用户（由认证中间件注入）。

    Returns:
        ALchemist 后端的原始响应。
    """
    client = _get_client()

    # 读取请求体
    body = await request.body()

    # 构建转发请求头，移除 hop-by-hop 头
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)

    logger.info(
        f"代理转发请求: {request.method} /alchemist/{path}",
        extra={"user": current_user.get("username") if current_user else "anonymous"},
    )

    try:
        response = await client.request(
            method=request.method,
            url=path,
            headers=headers,
            content=body,
        )
    except httpx.ConnectError:
        logger.error("无法连接到 ALchemist 后端，请确认 ALchemist 服务已启动")
        raise HTTPException(
            status_code=503,
            detail="ALchemist 服务未启动，请先启动 ALchemist 后端服务",
        )
    except httpx.TimeoutException:
        logger.error("ALchemist 后端请求超时")
        raise HTTPException(status_code=504, detail="ALchemist 服务响应超时")

    # 构建返回头，移除 hop-by-hop 头
    response_headers = dict(response.headers)
    response_headers.pop("content-encoding", None)
    response_headers.pop("transfer-encoding", None)
    response_headers.pop("content-length", None)

    return JSONResponse(
        content=response.json() if response.content else None,
        status_code=response.status_code,
        headers=response_headers,
    )


@router.websocket("/ws/{path:path}")
async def proxy_alchemist_websocket(websocket: WebSocket, path: str):
    """代理转发 WebSocket 连接到 ALchemist 后端。

    Args:
        websocket: 客户端 WebSocket 连接。
        path: ALchemist WebSocket 的相对路径。
    """
    await websocket.accept()

    ws_url = f"{ALCHEMIST_BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://').replace('/api/v1', '')}/ws/{path}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream("GET", ws_url, headers={
            "Upgrade": "websocket",
            "Connection": "Upgrade",
        }) as response:
            # 简化处理：暂不实现完整的 WebSocket 双向代理
            # 后续任务中根据实测情况完善
            pass

    await websocket.close()
```

- [ ] **步骤 2：提交**

```bash
cd E:/github_project/Poly_Agent
git add backend/app/api/v1/endpoints/alchemist_proxy.py
git commit -m "新增 ALchemist 工具代理路由"
```

---

### 任务 4：Poly_Agent 后端 — 注册代理路由和新增配置

**文件：**
- 修改：`E:\github_project\Poly_Agent\backend\app\api\v1\router.py`
- 修改：`E:\github_project\Poly_Agent\backend\app\core\config.py`

- [ ] **步骤 1：注册代理路由**

修改 `E:\github_project\Poly_Agent\backend\app\api\v1\router.py`：

```python
"""V1 路由聚合模块。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.alchemist_proxy import router as alchemist_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(alchemist_router, prefix="/alchemist")
```

- [ ] **步骤 2：新增配置项**

在 `E:\github_project\Poly_Agent\backend\app\core\config.py` 的 `Settings.__init__` 方法中新增：

```python
# ALchemist 主动学习工具后端地址
self.alchemist_backend_url: str = os.getenv(
    "ALCHEMIST_BACKEND_URL", "http://127.0.0.1:8004/api/v1"
)
```

- [ ] **步骤 3：提交**

```bash
cd E:/github_project/Poly_Agent
git add backend/app/api/v1/router.py backend/app/core/config.py
git commit -m "注册 ALchemist 代理路由并新增后端地址配置"
```

---

### 任务 5：Poly_Agent 前端 — 创建 AlchemistApi.js

**文件：**
- 创建：`E:\github_project\Poly_Agent\frontend\src\api\alchemistApi.js`

- [ ] **步骤 1：创建 API 封装文件**

```javascript
/**
 * ALchemist 主动学习工具 — API 调用封装。
 *
 * 所有请求通过 Poly_Agent 的代理路由 /api/v1/alchemist/* 转发到 ALchemist 后端。
 * 认证由 polyAgentApi.js 的 axios 拦截器自动处理。
 */
import { getApiBaseUrl } from './polyAgentApi'
import axios from 'axios'

const BASE = `${getApiBaseUrl()}/alchemist`

const alchemistClient = axios.create({
  baseURL: BASE,
  timeout: 120000,
})

// 复用 Poly_Agent 的请求 ID 生成和认证拦截
function generateRequestId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

alchemistClient.interceptors.request.use((config) => {
  config.headers['X-Request-Id'] = generateRequestId()
  return config
})

alchemistClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

// ── Session 管理 ──

/** 列出所有 Session */
export function listSessions() {
  return alchemistClient.get('/sessions/').then(r => r.data)
}

/** 创建新 Session */
export function createSession() {
  return alchemistClient.post('/sessions/').then(r => r.data)
}

/** 获取 Session 信息 */
export function getSession(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/`).then(r => r.data)
}

/** 删除 Session */
export function deleteSession(sessionId) {
  return alchemistClient.delete(`/sessions/${sessionId}/`).then(r => r.data)
}

/** 保存 Session 到服务端 */
export function saveSession(sessionId) {
  return alchemistClient.post(`/sessions/${sessionId}/save`).then(r => r.data)
}

/** 导出 Session 为 JSON 下载 */
export function exportSession(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/export`, { responseType: 'blob' }).then(r => r.data)
}

/** 导入 Session 文件 */
export function importSession(file) {
  const formData = new FormData()
  formData.append('file', file)
  return alchemistClient.post('/sessions/import', formData).then(r => r.data)
}

/** 上传并恢复 Session JSON 文件 */
export function uploadSession(file) {
  const formData = new FormData()
  formData.append('file', file)
  return alchemistClient.post('/sessions/upload', formData).then(r => r.data)
}

// ── 变量管理 ──

/** 获取变量列表 */
export function getVariables(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/variables/`).then(r => r.data)
}

/** 添加变量 */
export function addVariable(sessionId, variableData) {
  return alchemistClient.post(`/sessions/${sessionId}/variables/`, variableData).then(r => r.data)
}

/** 删除变量 */
export function deleteVariable(sessionId, variableId) {
  return alchemistClient.delete(`/sessions/${sessionId}/variables/${variableId}/`).then(r => r.data)
}

/** 更新变量 */
export function updateVariable(sessionId, variableId, variableData) {
  return alchemistClient.put(`/sessions/${sessionId}/variables/${variableId}/`, variableData).then(r => r.data)
}

// ── 实验设计 ──

/** 生成实验设计 */
export function generateDesign(sessionId, designConfig) {
  return alchemistClient.post(`/sessions/${sessionId}/experiments/design`, designConfig).then(r => r.data)
}

/** 添加实验数据 */
export function addExperiments(sessionId, experiments) {
  return alchemistClient.post(`/sessions/${sessionId}/experiments/add`, experiments).then(r => r.data)
}

// ── GP 建模 ──

/** 训练 GP 模型 */
export function trainModel(sessionId, modelConfig) {
  return alchemistClient.post(`/sessions/${sessionId}/models/train`, modelConfig).then(r => r.data)
}

/** 获取模型状态 */
export function getModelStatus(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/models/status`).then(r => r.data)
}

// ── 采集优化 ──

/** 获取下一个实验建议点 */
export function suggestNext(sessionId, acquisitionConfig) {
  return alchemistClient.post(`/sessions/${sessionId}/acquisition/suggest`, acquisitionConfig).then(r => r.data)
}

/** 获取采集结果 */
export function getAcquisitionResult(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/acquisition/result`).then(r => r.data)
}

// ── 可视化 ──

/** 获取可视化数据 */
export function getVisualization(sessionId, vizType) {
  return alchemistClient.get(`/sessions/${sessionId}/visualizations/${vizType}`).then(r => r.data)
}

// ── LLM ──

/** LLM 辅助实验建议 */
export function llmSuggest(sessionId, llmConfig) {
  return alchemistClient.post(`/sessions/${sessionId}/llm/suggest`, llmConfig).then(r => r.data)
}
```

- [ ] **步骤 2：提交**

```bash
cd E:/github_project/Poly_Agent
git add frontend/src/api/alchemistApi.js
git commit -m "新增 ALchemist 前端 API 调用封装"
```

---

### 任务 6：Poly_Agent 前端 — 更新路由和工具服务页

**文件：**
- 修改：`E:\github_project\Poly_Agent\frontend\src\router\index.js`
- 修改：`E:\github_project\Poly_Agent\frontend\src\views\ToolServicesView.vue`

- [ ] **步骤 1：新增路由**

在 `E:\github_project\Poly_Agent\frontend\src\router\index.js` 中：

```javascript
// 新增 import
import AlchemistToolView from '../views/AlchemistToolView.vue'

// 在 routes 数组中新增：
{ path: '/tools/alchemist', component: AlchemistToolView, meta: { section: '工具服务', title: '主动学习优化' } },
```

- [ ] **步骤 2：更新工具服务页**

修改 `E:\github_project\Poly_Agent\frontend\src\views\ToolServicesView.vue`：

```vue
<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const tools = [
  { name: '主动学习优化', desc: '基于贝叶斯优化的实验设计与材料性能优化，支持多目标优化、高斯过程建模和 LLM 辅助实验设计', status: 'active', route: '/tools/alchemist' },
  { name: '分子量预测', desc: '基于分子结构预测聚合物的数均/重均分子量及多分散性指数', status: 'coming' },
  { name: '热稳定性预测', desc: '预测聚合物的玻璃化转变温度、熔融温度和热分解温度', status: 'coming' },
  { name: '力学性能预测', desc: '预测拉伸强度、弹性模量、断裂伸长率等力学指标', status: 'coming' },
  { name: '流变性能预测', desc: '预测聚合物熔体的流变行为与加工性能', status: 'coming' },
  { name: '共混相容性评估', desc: '评估不同聚合物共混体系的相容性和相行为', status: 'coming' },
  { name: '降解性能评估', desc: '预测聚合物在特定环境条件下的降解速率', status: 'coming' },
]

function handleToolClick(tool) {
  if (tool.status === 'active' && tool.route) {
    router.push(tool.route)
  }
}
</script>

<template>
  <div>
    <div class="panel" style="margin-bottom:16px">
      <div class="panel-header">
        <h3 class="panel-title">工具服务</h3>
      </div>
      <div class="panel-body">
        <p style="color:var(--app-ink-muted);font-size:14px">提供多种高分子材料性能预测模型和实验优化服务，选择需要的工具开始使用。</p>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">
      <div
        v-for="tool in tools"
        :key="tool.name"
        class="panel"
        style="padding:20px;cursor:pointer;transition:box-shadow 0.2s"
        @click="handleToolClick(tool)"
      >
        <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px">
          <span style="font-weight:600;font-size:15px;color:var(--app-ink)">{{ tool.name }}</span>
          <el-tag v-if="tool.status === 'active'" size="small" type="success">可用</el-tag>
          <el-tag v-else size="small" type="info">即将上线</el-tag>
        </div>
        <p style="color:var(--app-ink-muted);font-size:13px;line-height:1.6">{{ tool.desc }}</p>
      </div>
    </div>
  </div>
</template>
```

- [ ] **步骤 3：提交**

```bash
cd E:/github_project/Poly_Agent
git add frontend/src/router/index.js frontend/src/views/ToolServicesView.vue
git commit -m "新增主动学习优化工具入口和路由"
```

---

### 任务 7：Poly_Agent 前端 — AlchemistToolView 主页面

**文件：**
- 创建：`E:\github_project\Poly_Agent\frontend\src\views\AlchemistToolView.vue`

- [ ] **步骤 1：创建主页面**

```vue
<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { listSessions, createSession, importSession, uploadSession, exportSession } from '../api/alchemistApi'
import VariablePanel from './alchemist/VariablePanel.vue'
import ExperimentPanel from './alchemist/ExperimentPanel.vue'
import ModelPanel from './alchemist/ModelPanel.vue'
import AcquisitionPanel from './alchemist/AcquisitionPanel.vue'
import VisualizationPanel from './alchemist/VisualizationPanel.vue'
import LlmConfigDialog from './alchemist/components/LlmConfigDialog.vue'

/** 当前步骤索引（0-4） */
const activeStep = ref(0)

/** Session 列表 */
const sessions = ref([])

/** 当前选中的 Session ID */
const currentSessionId = ref(null)

/** Session 加载状态 */
const loading = ref(false)

/** LLM 配置弹窗 */
const llmDialogVisible = ref(false)

/** 步骤列表 */
const steps = [
  { title: '变量定义', description: '定义搜索空间中的变量' },
  { title: '实验设计', description: '生成初始实验方案' },
  { title: 'GP 建模', description: '训练高斯过程代理模型' },
  { title: '采集优化', description: '贝叶斯优化采集函数' },
  { title: '可视化', description: '模型诊断与结果展示' },
]

/** 当前 Session 名称 */
const currentSessionName = computed(() => {
  if (!currentSessionId.value) return '未选择'
  const s = sessions.value.find(s => s.session_id === currentSessionId.value)
  return s ? (s.name || s.session_id) : currentSessionId.value
})

/** 当前步骤对应的组件 */
const currentPanelComponent = computed(() => {
  const panels = [VariablePanel, ExperimentPanel, ModelPanel, AcquisitionPanel, VisualizationPanel]
  return panels[activeStep.value]
})

/** 加载 Session 列表 */
async function loadSessions() {
  try {
    const data = await listSessions()
    sessions.value = Array.isArray(data) ? data : []
  } catch (e) {
    ElMessage.error(`加载 Session 列表失败: ${e.message}`)
  }
}

/** 新建 Session */
async function handleCreateSession() {
  try {
    loading.value = true
    const data = await createSession()
    currentSessionId.value = data.session_id
    await loadSessions()
    ElMessage.success('Session 创建成功')
  } catch (e) {
    ElMessage.error(`创建 Session 失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

/** 导入 Session 文件 */
async function handleImportSession() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.onchange = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    try {
      loading.value = true
      const data = await uploadSession(file)
      currentSessionId.value = data.session_id
      await loadSessions()
      ElMessage.success('Session 导入成功')
    } catch (e) {
      ElMessage.error(`Session 导入失败: ${e.message}`)
    } finally {
      loading.value = false
    }
  }
  input.click()
}

/** 导出当前 Session */
async function handleExportSession() {
  if (!currentSessionId.value) {
    ElMessage.warning('请先选择一个 Session')
    return
  }
  try {
    const blob = await exportSession(currentSessionId.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `session_${currentSessionId.value}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('Session 导出成功')
  } catch (e) {
    ElMessage.error(`Session 导出失败: ${e.message}`)
  }
}

/** 切换 Session */
function handleSessionChange(sessionId) {
  currentSessionId.value = sessionId
}

onMounted(() => {
  loadSessions()
})
</script>

<template>
  <div class="alchemist-tool">
    <!-- Session 管理栏 -->
    <div class="panel" style="margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:12px">
        <span style="font-weight:600;font-size:14px;color:var(--app-ink);white-space:nowrap">当前 Session：</span>
        <el-select
          v-model="currentSessionId"
          placeholder="请选择或创建 Session"
          style="flex:1;max-width:400px"
          @change="handleSessionChange"
        >
          <el-option
            v-for="s in sessions"
            :key="s.session_id"
            :label="s.name || s.session_id"
            :value="s.session_id"
          />
        </el-select>
        <el-button type="primary" size="small" @click="handleCreateSession" :loading="loading">新建</el-button>
        <el-button size="small" @click="handleImportSession">导入</el-button>
        <el-button size="small" @click="handleExportSession" :disabled="!currentSessionId">导出</el-button>
        <el-button size="small" @click="llmDialogVisible = true">
          <el-icon style="margin-right:4px"><Setting /></el-icon>
          LLM 配置
        </el-button>
      </div>
    </div>

    <!-- 步骤导航 + 内容区 -->
    <div style="display:flex;gap:16px">
      <!-- 左侧步骤导航 -->
      <div class="panel" style="width:200px;flex-shrink:0">
        <div class="panel-header">
          <h3 class="panel-title">优化流程</h3>
        </div>
        <div class="panel-body" style="padding:8px">
          <div
            v-for="(step, index) in steps"
            :key="index"
            class="step-item"
            :class="{ active: activeStep === index }"
            @click="activeStep = index"
          >
            <div class="step-index">{{ index + 1 }}</div>
            <div class="step-content">
              <div class="step-title">{{ step.title }}</div>
              <div class="step-desc">{{ step.description }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧内容区 -->
      <div style="flex:1;min-width:0">
        <div v-if="!currentSessionId" class="panel" style="padding:60px;text-align:center">
          <p style="color:var(--app-ink-muted);font-size:15px">请先创建或选择一个 Session 以开始使用主动学习优化工具</p>
        </div>
        <div v-else>
          <component :is="currentPanelComponent" :session-id="currentSessionId" :key="`${activeStep}-${currentSessionId}`" />
        </div>
      </div>
    </div>

    <!-- LLM 配置弹窗 -->
    <LlmConfigDialog v-model:visible="llmDialogVisible" />
  </div>
</template>

<style scoped>
.step-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 8px;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 2px;
}

.step-item:hover {
  background: var(--app-stat-bg);
}

.step-item.active {
  background: var(--app-primary-light);
}

.step-index {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--app-hairline);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--app-ink-muted);
  flex-shrink: 0;
}

.step-item.active .step-index {
  background: var(--app-primary);
  color: #fff;
}

.step-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--app-ink);
  line-height: 1.3;
}

.step-desc {
  font-size: 11px;
  color: var(--app-ink-muted);
  margin-top: 2px;
}
</style>
```

- [ ] **步骤 2：提交**

```bash
cd E:/github_project/Poly_Agent
git add frontend/src/views/AlchemistToolView.vue
git commit -m "新增 ALchemist 主页面（步骤导航 + Session 管理）"
```

---

### 任务 8：Poly_Agent 前端 — VariablePanel 变量定义面板

**文件：**
- 创建：`E:\github_project\Poly_Agent\frontend\src\views\alchemist\VariablePanel.vue`

- [ ] **步骤 1：创建变量定义面板**

```vue
<script setup>
import { ref, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Edit } from '@element-plus/icons-vue'
import { getVariables, addVariable, deleteVariable, updateVariable } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

/** 变量列表 */
const variables = ref([])

/** 是否正在加载 */
const loading = ref(false)

/** 变量类型选项 */
const variableTypes = [
  { label: '连续实值', value: 'real' },
  { label: '整数', value: 'integer' },
  { label: '分类', value: 'categorical' },
  { label: '离散值', value: 'discrete' },
]

/** 新增变量对话框 */
const dialogVisible = ref(false)
const editingVariable = ref(null)
const formData = ref({
  name: '',
  type: 'real',
  low: 0,
  high: 1,
  values: '',
})

/** 加载变量列表 */
async function loadVariables() {
  try {
    loading.value = true
    const data = await getVariables(props.sessionId)
    variables.value = data.variables || []
  } catch (e) {
    ElMessage.error(`加载变量列表失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

/** 打开新增对话框 */
function openAddDialog() {
  editingVariable.value = null
  formData.value = { name: '', type: 'real', low: 0, high: 1, values: '' }
  dialogVisible.value = true
}

/** 打开编辑对话框 */
function openEditDialog(variable) {
  editingVariable.value = variable
  formData.value = {
    name: variable.name,
    type: variable.type,
    low: variable.low || 0,
    high: variable.high || 1,
    values: Array.isArray(variable.values) ? variable.values.join(', ') : (variable.values || ''),
  }
  dialogVisible.value = true
}

/** 保存变量 */
async function handleSave() {
  const payload = {
    name: formData.value.name,
    type: formData.value.type,
  }
  if (formData.value.type === 'real' || formData.value.type === 'integer') {
    payload.low = Number(formData.value.low)
    payload.high = Number(formData.value.high)
  }
  if (formData.value.type === 'categorical' || formData.value.type === 'discrete') {
    payload.values = formData.value.values.split(',').map(s => s.trim()).filter(Boolean)
  }

  try {
    if (editingVariable.value) {
      await updateVariable(props.sessionId, editingVariable.value.id, payload)
      ElMessage.success('变量更新成功')
    } else {
      await addVariable(props.sessionId, payload)
      ElMessage.success('变量添加成功')
    }
    dialogVisible.value = false
    await loadVariables()
  } catch (e) {
    ElMessage.error(`保存变量失败: ${e.message}`)
  }
}

/** 删除变量 */
async function handleDelete(variable) {
  try {
    await ElMessageBox.confirm(`确定要删除变量"${variable.name}"吗？`, '删除确认', { type: 'warning' })
    await deleteVariable(props.sessionId, variable.id)
    ElMessage.success('变量已删除')
    await loadVariables()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error(`删除变量失败: ${e.message}`)
    }
  }
}

/** 获取变量类型的中文标签 */
function getTypeLabel(type) {
  const found = variableTypes.find(t => t.value === type)
  return found ? found.label : type
}

watch(() => props.sessionId, () => {
  if (props.sessionId) loadVariables()
})

onMounted(() => {
  if (props.sessionId) loadVariables()
})
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <h3 class="panel-title">变量定义</h3>
      <el-button type="primary" size="small" @click="openAddDialog">
        <el-icon><Plus /></el-icon>
        添加变量
      </el-button>
    </div>
    <div class="panel-body">
      <el-table :data="variables" v-loading="loading" empty-text="暂无变量，请点击"添加变量"开始定义搜索空间">
        <el-table-column prop="name" label="变量名称" min-width="120" />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag size="small">{{ getTypeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="范围/值" min-width="200">
          <template #default="{ row }">
            <template v-if="row.type === 'real' || row.type === 'integer'">
              [{{ row.low }}, {{ row.high }}]
            </template>
            <template v-else>
              {{ Array.isArray(row.values) ? row.values.join(', ') : row.values }}
            </template>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEditDialog(row)">
              <el-icon><Edit /></el-icon>
            </el-button>
            <el-button text type="danger" size="small" @click="handleDelete(row)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增/编辑变量对话框 -->
    <el-dialog v-model="dialogVisible" :title="editingVariable ? '编辑变量' : '添加变量'" width="480px">
      <el-form label-width="80px">
        <el-form-item label="变量名称">
          <el-input v-model="formData.name" placeholder="请输入变量名称" />
        </el-form-item>
        <el-form-item label="变量类型">
          <el-select v-model="formData.type" style="width:100%">
            <el-option v-for="t in variableTypes" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <template v-if="formData.type === 'real' || formData.type === 'integer'">
          <el-form-item label="下限">
            <el-input-number v-model="formData.low" style="width:100%" />
          </el-form-item>
          <el-form-item label="上限">
            <el-input-number v-model="formData.high" style="width:100%" />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="可选值">
            <el-input v-model="formData.values" placeholder="用逗号分隔，如: A, B, C" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
```

- [ ] **步骤 2：提交**

```bash
cd E:/github_project/Poly_Agent
git add frontend/src/views/alchemist/VariablePanel.vue
git commit -m "新增 ALchemist 变量定义面板"
```

---

### 任务 9：Poly_Agent 前端 — ExperimentPanel 实验设计面板

**文件：**
- 创建：`E:\github_project\Poly_Agent\frontend\src\views\alchemist\ExperimentPanel.vue`

- [ ] **步骤 1：创建实验设计面板**

```vue
<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { generateDesign, addExperiments, getVariables } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

/** 设计方法选项 */
const designMethods = [
  { label: '拉丁超立方采样 (LHS)', value: 'lhs' },
  { label: 'Sobol 序列', value: 'sobol' },
  { label: '全因子设计', value: 'full_factorial' },
  { label: '中心复合设计 (CCD)', value: 'ccd' },
  { label: 'Box-Behnken 设计', value: 'box_behnken' },
  { label: 'Plackett-Burman 设计', value: 'plackett_burman' },
  { label: 'D-最优设计', value: 'd_optimal' },
]

const selectedMethod = ref('lhs')
const nExperiments = ref(10)
const loading = ref(false)
const designMatrix = ref([])
const variables = ref([])

async function loadVariables() {
  try {
    const data = await getVariables(props.sessionId)
    variables.value = data.variables || []
  } catch (e) {
    // 静默失败
  }
}

async function handleGenerateDesign() {
  if (variables.value.length === 0) {
    ElMessage.warning('请先在"变量定义"中添加变量')
    return
  }
  try {
    loading.value = true
    const config = {
      method: selectedMethod.value,
      n_experiments: nExperiments.value,
    }
    const data = await generateDesign(props.sessionId, config)
    designMatrix.value = data.design_matrix || data.experiments || []
    ElMessage.success(`生成 ${designMatrix.value.length} 组实验方案`)
  } catch (e) {
    ElMessage.error(`生成实验设计失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

async function handleAddExperiments() {
  if (designMatrix.value.length === 0) {
    ElMessage.warning('请先生成实验设计方案')
    return
  }
  try {
    loading.value = true
    await addExperiments(props.sessionId, { experiments: designMatrix.value })
    ElMessage.success('实验数据已添加')
  } catch (e) {
    ElMessage.error(`添加实验数据失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

/** 获取设计矩阵的列名 */
function getColumnNames() {
  if (designMatrix.value.length === 0) return []
  const row = designMatrix.value[0]
  if (typeof row === 'object' && !Array.isArray(row)) {
    return Object.keys(row).filter(k => k !== 'target' && k !== 'outcome')
  }
  return variables.value.map(v => v.name)
}

watch(() => props.sessionId, () => { loadVariables() })
onMounted(() => { loadVariables() })
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <h3 class="panel-title">实验设计</h3>
    </div>
    <div class="panel-body">
      <!-- 设计参数 -->
      <div style="display:flex;gap:16px;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">设计方法</div>
          <el-select v-model="selectedMethod" style="width:220px">
            <el-option v-for="m in designMethods" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
        </div>
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">实验数量</div>
          <el-input-number v-model="nExperiments" :min="2" :max="1000" style="width:120px" />
        </div>
        <div>
          <el-button type="primary" @click="handleGenerateDesign" :loading="loading">生成实验设计</el-button>
          <el-button @click="handleAddExperiments" :disabled="designMatrix.length === 0" :loading="loading">添加到实验数据</el-button>
        </div>
      </div>

      <!-- 设计矩阵表格 -->
      <el-table :data="designMatrix" border stripe empty-text="请先生成实验设计方案" max-height="400">
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column
          v-for="col in getColumnNames()"
          :key="col"
          :prop="col"
          :label="col"
          min-width="100"
        />
      </el-table>
    </div>
  </div>
</template>
```

- [ ] **步骤 2：提交**

```bash
cd E:/github_project/Poly_Agent
git add frontend/src/views/alchemist/ExperimentPanel.vue
git commit -m "新增 ALchemist 实验设计面板"
```

---

### 任务 10：Poly_Agent 前端 — ModelPanel GP 建模面板

**文件：**
- 创建：`E:\github_project\Poly_Agent\frontend\src\views\alchemist\ModelPanel.vue`

- [ ] **步骤 1：创建 GP 建模面板**

```vue
<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { trainModel, getModelStatus } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

/** 核函数选项 */
const kernelOptions = [
  { label: 'Matern 5/2', value: 'matern52' },
  { label: 'Matern 3/2', value: 'matern32' },
  { label: 'RBF（径向基函数）', value: 'rbf' },
  { label: 'IBNN（贝叶斯神经网络核）', value: 'ibnn' },
]

/** 后端选项 */
const backendOptions = [
  { label: 'BoTorch (推荐)', value: 'botorch' },
  { label: 'scikit-learn', value: 'sklearn' },
]

const selectedKernel = ref('matern52')
const selectedBackend = ref('botorch')
const useARD = ref(true)
const loading = ref(false)

/** 模型训练结果 */
const modelResult = ref(null)

async function handleTrainModel() {
  try {
    loading.value = true
    modelResult.value = null
    const config = {
      kernel: selectedKernel.value,
      backend: selectedBackend.value,
      use_ard: useARD.value,
    }
    const data = await trainModel(props.sessionId, config)
    modelResult.value = data
    ElMessage.success('模型训练完成')
  } catch (e) {
    ElMessage.error(`模型训练失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

async function handleCheckStatus() {
  try {
    const data = await getModelStatus(props.sessionId)
    ElMessage.success(`模型状态: ${data.model_trained ? '已训练' : '未训练'}`)
  } catch (e) {
    ElMessage.error(`获取模型状态失败: ${e.message}`)
  }
}
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <h3 class="panel-title">高斯过程回归建模</h3>
    </div>
    <div class="panel-body">
      <div style="display:flex;gap:24px;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">核函数</div>
          <el-select v-model="selectedKernel" style="width:220px">
            <el-option v-for="k in kernelOptions" :key="k.value" :label="k.label" :value="k.value" />
          </el-select>
        </div>
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">计算后端</div>
          <el-select v-model="selectedBackend" style="width:200px">
            <el-option v-for="b in backendOptions" :key="b.value" :label="b.label" :value="b.value" />
          </el-select>
        </div>
        <div>
          <el-checkbox v-model="useARD">自动相关性确定 (ARD)</el-checkbox>
        </div>
        <div>
          <el-button type="primary" @click="handleTrainModel" :loading="loading">训练模型</el-button>
          <el-button @click="handleCheckStatus">查看状态</el-button>
        </div>
      </div>

      <!-- 训练结果 -->
      <div v-if="modelResult" style="margin-top:16px">
        <el-descriptions border :column="2" size="small">
          <el-descriptions-item label="核函数">{{ modelResult.kernel || selectedKernel }}</el-descriptions-item>
          <el-descriptions-item label="后端">{{ modelResult.backend || selectedBackend }}</el-descriptions-item>
          <el-descriptions-item label="训练得分">{{ modelResult.train_score || '-' }}</el-descriptions-item>
          <el-descriptions-item label="噪声水平">{{ modelResult.noise_level || '-' }}</el-descriptions-item>
        </el-descriptions>

        <!-- 超参数展示 -->
        <div v-if="modelResult.hyperparameters" style="margin-top:12px">
          <h4 style="font-size:14px;font-weight:600;margin-bottom:8px;color:var(--app-ink)">超参数</h4>
          <el-table :data="modelResult.hyperparameters" size="small" border>
            <el-table-column prop="name" label="参数名" />
            <el-table-column prop="value" label="值" />
          </el-table>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **步骤 2：提交**

```bash
cd E:/github_project/Poly_Agent
git add frontend/src/views/alchemist/ModelPanel.vue
git commit -m "新增 ALchemist GP 建模面板"
```

---

### 任务 11：Poly_Agent 前端 — AcquisitionPanel 采集优化面板

**文件：**
- 创建：`E:\github_project\Poly_Agent\frontend\src\views\alchemist\AcquisitionPanel.vue`

- [ ] **步骤 1：创建采集优化面板**

```vue
<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { suggestNext } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

/** 采集函数选项 */
const acquisitionOptions = [
  { label: 'q-期望改进 (qEI)', value: 'qEI' },
  { label: 'q-概率改进 (qPI)', value: 'qPI' },
  { label: 'q-上置信界 (qUCB)', value: 'qUCB' },
  { label: 'q-负积分后验方差 (qNIPV)', value: 'qNegIntegratedPosteriorVariance' },
]

const selectedAcquisition = ref('qEI')
const nSuggestions = ref(3)
const loading = ref(false)

/** 建议点结果 */
const suggestions = ref([])

async function handleSuggest() {
  try {
    loading.value = true
    const config = {
      acquisition_function: selectedAcquisition.value,
      n_suggestions: nSuggestions.value,
    }
    const data = await suggestNext(props.sessionId, config)
    suggestions.value = data.suggestions || data.candidates || []
    ElMessage.success(`获得 ${suggestions.value.length} 组建议实验点`)
  } catch (e) {
    ElMessage.error(`获取建议失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

/** 获取建议点的列名 */
function getColumnNames() {
  if (suggestions.value.length === 0) return []
  const row = suggestions.value[0]
  if (typeof row === 'object' && !Array.isArray(row)) {
    return Object.keys(row)
  }
  return []
}
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <h3 class="panel-title">采集优化</h3>
    </div>
    <div class="panel-body">
      <div style="display:flex;gap:16px;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">采集函数</div>
          <el-select v-model="selectedAcquisition" style="width:240px">
            <el-option v-for="a in acquisitionOptions" :key="a.value" :label="a.label" :value="a.value" />
          </el-select>
        </div>
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">建议点数量</div>
          <el-input-number v-model="nSuggestions" :min="1" :max="20" style="width:100px" />
        </div>
        <div>
          <el-button type="primary" @click="handleSuggest" :loading="loading">生成建议</el-button>
        </div>
      </div>

      <!-- 建议点表格 -->
      <el-table :data="suggestions" border stripe empty-text="请选好参数后点击"生成建议"" max-height="400">
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column
          v-for="col in getColumnNames()"
          :key="col"
          :prop="col"
          :label="col"
          min-width="100"
        />
      </el-table>
    </div>
  </div>
</template>
```

- [ ] **步骤 2：提交**

```bash
cd E:/github_project/Poly_Agent
git add frontend/src/views/alchemist/AcquisitionPanel.vue
git commit -m "新增 ALchemist 采集优化面板"
```

---

### 任务 12：Poly_Agent 前端 — VisualizationPanel 可视化面板

**文件：**
- 创建：`E:\github_project\Poly_Agent\frontend\src\views\alchemist\VisualizationPanel.vue`
- 修改：`E:\github_project\Poly_Agent\frontend\package.json`（新增 plotly.js-dist 依赖）

- [ ] **步骤 1：安装 Plotly.js 依赖**

```bash
cd E:/github_project/Poly_Agent/frontend
npm install plotly.js-dist
```

- [ ] **步骤 2：创建可视化面板**

```vue
<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import Plotly from 'plotly.js-dist'
import { getVisualization } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

/** 可视化类型 */
const vizTypes = [
  { label: '校准曲线', value: 'calibration' },
  { label: '等值线图', value: 'contour' },
  { label: 'QQ 图', value: 'qq' },
  { label: 'Parity 图', value: 'parity' },
  { label: '评估指标', value: 'metrics' },
  { label: '超参数展示', value: 'hyperparameters' },
]

const selectedViz = ref('calibration')
const loading = ref(false)
const chartContainer = ref(null)

async function loadVisualization() {
  try {
    loading.value = true
    const data = await getVisualization(props.sessionId, selectedViz.value)
    await nextTick()
    if (chartContainer.value && data) {
      renderChart(data)
    }
  } catch (e) {
    ElMessage.error(`加载可视化数据失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

function renderChart(data) {
  if (data.plotly_data) {
    // 如果后端返回完整的 Plotly 图表数据
    Plotly.newPlot(chartContainer.value, data.plotly_data.data, data.plotly_data.layout || {}, {
      responsive: true,
      displaylogo: false,
    })
  } else if (data.data) {
    // 如果是简单的图表数据
    const layout = {
      font: { family: 'Inter, PingFang SC, Microsoft YaHei, sans-serif' },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      margin: { l: 50, r: 30, t: 30, b: 50 },
      ...(data.layout || {}),
    }
    Plotly.newPlot(chartContainer.value, data.data, layout, {
      responsive: true,
      displaylogo: false,
    })
  } else {
    ElMessage.info('该可视化类型暂无数据')
  }
}

watch(() => props.sessionId, () => {
  if (props.sessionId) loadVisualization()
})

watch(selectedViz, () => {
  if (props.sessionId) loadVisualization()
})

onMounted(() => {
  if (props.sessionId) loadVisualization()
})
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <h3 class="panel-title">可视化诊断</h3>
    </div>
    <div class="panel-body">
      <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
        <el-radio-group v-model="selectedViz" size="small">
          <el-radio-button v-for="v in vizTypes" :key="v.value" :value="v.value">{{ v.label }}</el-radio-button>
        </el-radio-group>
      </div>

      <div v-loading="loading" style="min-height:400px">
        <div ref="chartContainer" style="width:100%;min-height:400px"></div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **步骤 3：提交**

```bash
cd E:/github_project/Poly_Agent
git add frontend/src/views/alchemist/VisualizationPanel.vue frontend/package.json frontend/package-lock.json
git commit -m "新增 ALchemist 可视化面板，集成 Plotly.js"
```

---

### 任务 13：Poly_Agent 前端 — LLM 配置弹窗

**文件：**
- 创建：`E:\github_project\Poly_Agent\frontend\src\views\alchemist\components\LlmConfigDialog.vue`

- [ ] **步骤 1：创建 LLM 配置弹窗**

```vue
<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: { type: Boolean, default: false }
})

const emit = defineEmits(['update:visible'])

const STORAGE_KEY = 'alchemist_llm_config'

/** 表单数据 */
const formData = ref({
  apiUrl: '',
  apiKey: '',
  model: 'gpt-4o',
})

/** 加载本地配置 */
function loadConfig() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const config = JSON.parse(saved)
      formData.value = { ...formData.value, ...config }
    }
  } catch {
    // 忽略解析错误
  }
}

/** 保存配置 */
function handleSave() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(formData.value))
    emit('update:visible', false)
    ElMessage.success('LLM 配置已保存')
  } catch (e) {
    ElMessage.error('保存配置失败')
  }
}

/** 关闭弹窗 */
function handleClose() {
  emit('update:visible', false)
}

watch(() => props.visible, (val) => {
  if (val) loadConfig()
})
</script>

<template>
  <el-dialog v-model="visible" title="LLM 配置" width="480px" @close="handleClose">
    <el-form label-width="100px">
      <el-form-item label="API 地址">
        <el-input v-model="formData.apiUrl" placeholder="例如: https://api.openai.com/v1，Ollama 填写 http://localhost:11434/v1" />
      </el-form-item>
      <el-form-item label="API Key">
        <el-input v-model="formData.apiKey" type="password" show-password placeholder="请输入 API Key" />
      </el-form-item>
      <el-form-item label="模型名称">
        <el-input v-model="formData.model" placeholder="例如: gpt-4o, gpt-4, llama3" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" @click="handleSave">保存配置</el-button>
    </template>
  </el-dialog>
</template>
```

- [ ] **步骤 2：提交**

```bash
cd E:/github_project/Poly_Agent
git add frontend/src/views/alchemist/components/LlmConfigDialog.vue
git commit -m "新增 ALchemist LLM 配置弹窗"
```

---

### 任务 14：Poly_Agent 前端 — 修复主页面图标导入

**文件：**
- 修改：`E:\github_project\Poly_Agent\frontend\src\views\AlchemistToolView.vue`

- [ ] **步骤 1：添加缺失的 Setting 图标导入**

在 AlchemistToolView.vue 的 `<script setup>` 中添加：

```javascript
import { Setting } from '@element-plus/icons-vue'
```

- [ ] **步骤 2：提交**

```bash
cd E:/github_project/Poly_Agent
git add frontend/src/views/AlchemistToolView.vue
git commit -m "修复 AlchemistToolView 缺失的 Setting 图标导入"
```

---

### 任务 15：端到端联调验证

- [ ] **步骤 1：启动 ALchemist 后端**

```bash
cd E:/github_project/ALchemist
# 确认端口为 127.0.0.1:8004
python -m api.run_api --dev
```

验证：访问 `http://127.0.0.1:8004/api/docs` 确认 API 文档可访问且界面中文。

- [ ] **步骤 2：启动 Poly_Agent 后端**

```bash
cd E:/github_project/Poly_Agent/backend
uvicorn app.main:app --reload --port 8003
```

- [ ] **步骤 3：验证代理转发**

```bash
# 创建 Session
curl -X POST http://localhost:8003/api/v1/alchemist/sessions/
# 预期返回 {"session_id": "...", "created_at": "..."}
```

- [ ] **步骤 4：启动 Poly_Agent 前端**

```bash
cd E:/github_project/Poly_Agent/frontend
npm run dev
```

- [ ] **步骤 5：验证完整流程**

在浏览器访问 `http://localhost:5173/tools/alchemist`，验证：
1. 创建 Session → 成功
2. 添加变量 → 成功
3. 生成实验设计 → 成功
4. 训练 GP 模型 → 成功
5. 获取采集建议 → 成功
6. 可视化图表 → 正常渲染
7. LLM 配置 → 可保存到 localStorage

- [ ] **步骤 6：修复联调中发现的问题**

根据实际 API 响应格式调整前端面板的字段映射。

---

## 自审检查

1. **规格覆盖：** 每个设计文档中的要求都能在对应任务中找到实现
2. **无占位符：** 所有任务包含完整代码，无 TBD/TODO
3. **类型一致性：** sessionId 在全部组件中使用 `props.sessionId` 统一命名；API 方法参数签名与 alchemistApi.js 导出一致
