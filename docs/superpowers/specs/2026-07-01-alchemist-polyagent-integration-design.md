# ALchemist Web 功能移植到 Poly_Agent 工具服务 — 设计文档

> 日期：2026-07-01 | 状态：已确认 | 版本：1.0

## 1. 目标

将 ALchemist 完整 Web 功能（实验设计 + 贝叶斯优化 + 多目标优化 + 可视化）移植到 Poly_Agent 项目，作为其"工具服务"中的一个可用的 AI 工具。ALchemist 后端保持独立运行，Poly_Agent 前端通过代理模式访问。

**约束：**
- 后端在 ALchemist 当前项目启动，通过 FastAPI 接口提供
- Poly_Agent 前端用 Vue 3 + Element Plus 重写所有界面
- 所有前端界面、后端注释、日志输出全部中文化
- LLM 功能保留，支持配置 API URL 和 API Key

## 2. 整体架构

### 2.1 通信模式：代理模式

```
Poly_Agent Vue 前端 (:5173 dev / :8003 prod)
       │
       │ HTTP (同源，无跨域)
       ▼
Poly_Agent FastAPI (:8003)
       │ api/v1/alchemist/*  ──httpx──►
       ▼
ALchemist FastAPI (:8004, 仅监听 127.0.0.1)
       │
       ▼
alchemist_core (核心贝叶斯优化引擎，不改)
```

### 2.2 方案理由

- **认证统一**：复用的 Poly_Agent HMAC-SHA256 token 认证体系，ALchemist 无需独立认证
- **前端简单**：单一 API 客户端，无跨域问题，无需额外 CORS 配置
- **部署一致**：与 Poly_Agent 现有 SPA 托管模式完全兼容
- **安全隔离**：ALchemist 仅监听 localhost，不直接暴露公网

## 3. 后端设计

### 3.1 ALchemist 后端（当前项目）改动

| 改动 | 说明 |
|------|------|
| 日志中文化 | 所有 logger 输出改为中文 |
| 注释中文化 | 所有 docstring 和注释改为中文 |
| 监听地址限定 | 默认 `127.0.0.1:8004`，仅本地可访问 |
| API 描述中文化 | FastAPI 的 title/description/summary 改为中文 |

alchemist_core 核心引擎不做修改，只改 api/ 层的文本。

### 3.2 Poly_Agent 后端新增

**新增文件：**
```
backend/app/
├── api/v1/endpoints/alchemist_proxy.py   # ALchemist 代理路由
└── (schemas/alchemist.py 按需)
```

**`alchemist_proxy.py` — 核心代理路由：**
- 挂载在 `router = APIRouter(prefix="/alchemist", tags=["ALchemist 主动学习工具"])`
- catch-all 路由 `/{path:path}` 使用 httpx.AsyncClient 转发到 `http://127.0.0.1:8004/api/`
- 转发前调用 `get_current_user(authorization)` 进行认证
- 透传 ALchemist 原始 JSON 响应
- WebSocket 路由 `/ws/{session_id}` 也通过代理转发

**路由注册：** `api/v1/router.py` 新增：
```python
from app.api.v1.endpoints.alchemist_proxy import router as alchemist_router
api_router.include_router(alchemist_router, prefix="/alchemist")
```

### 3.3 ALchemist 后端环境配置

在 Poly_Agent 的 `.env` 中新增：
```
ALCHEMIST_BACKEND_URL=http://127.0.0.1:8004/api
```

## 4. 前端设计

### 4.1 技术栈

| 层 | 技术 |
|---|------|
| 框架 | Vue 3 (Composition API, `<script setup>`) |
| UI 组件库 | Element Plus |
| 图表 | Plotly.js (dist) |
| HTTP | 复用 `polyAgentApi.js` axios 实例 |
| 设计规范 | 严格遵循 `DESIGN.md` (深蓝侧边栏 + 浅蓝灰 + Inter 字体) |

### 4.2 路由

```
/tools/alchemist → AlchemistToolView.vue
```

在 `ToolServicesView.vue` 的语言工具卡片数组中新增：
```js
{ name: '主动学习优化', desc: '基于贝叶斯优化的实验设计与材料性能优化，支持多目标优化和高斯过程建模', status: 'active', route: '/tools/alchemist' }
```

### 4.3 页面布局

```
┌──────────────────────────────────────────────────────┐
│  面包屑：工具服务 > 主动学习优化                        │
│                                                      │
│  ┌───────────┬────────────────────────────────────┐  │
│  │ Session   │  [新建] [加载] [保存] 选择器        │  │
│  │ 管理栏    │                                     │  │
│  ├───────────┼────────────────────────────────────┤  │
│  │ 左侧      │  右侧内容区 (根据步骤切换)           │  │
│  │ 步骤导航  │                                     │  │
│  │           │  1. 变量定义                         │  │
│  │ 1.变量    │     - VariablePanel.vue             │  │
│  │ 2.实验    │     - 变量类型表格 + 增删改          │  │
│  │ 3.建模    │                                     │  │
│  │ 4.优化    │  2. 实验设计                         │  │
│  │ 5.可视化  │     - ExperimentPanel.vue           │  │
│  │           │     - 设计方法选择 + 参数配置        │  │
│  │           │     - 设计矩阵结果表格               │  │
│  │           │                                     │  │
│  │           │  3. GP 建模                          │  │
│  │           │     - ModelPanel.vue                │  │
│  │           │     - 核函数选择 + 超参数显示        │  │
│  │           │                                     │  │
│  │           │  4. 采集优化                         │  │
│  │           │     - AcquisitionPanel.vue           │  │
│  │           │     - 采集函数选择 + 建议点表格       │  │
│  │           │                                     │  │
│  │           │  5. 可视化                           │  │
│  │           │     - VisualizationPanel.vue         │  │
│  │           │     - 校准曲线/等值线/QQ/Parity/指标  │  │
│  └───────────┴────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### 4.4 组件清单

| 文件 | 功能 | 说明 |
|------|------|------|
| `views/AlchemistToolView.vue` | 主页面，步骤导航 + 子面板切换 + Session 管理 | 使用 el-steps 垂直模式 |
| `views/alchemist/VariablePanel.vue` | 变量定义管理 | 实值/整数/分类/离散四种类型，el-table + el-dialog 增删改 |
| `views/alchemist/ExperimentPanel.vue` | 实验设计 | 初始设计 + 最优设计 + LLM 辅助，参数表单 + 设计矩阵表格 |
| `views/alchemist/ModelPanel.vue` | 高斯过程建模 | 核函数选择 + 训练 + 超参数展示 |
| `views/alchemist/AcquisitionPanel.vue` | 采集函数优化 | qEI/qPI/qUCB 选择 + 建议点 + 实验结果录入 |
| `views/alchemist/VisualizationPanel.vue` | 可视化展示 | 校准曲线/等值线图/QQ图/Parity图/指标图表 |
| `views/alchemist/components/LlmConfigDialog.vue` | LLM 配置弹窗 | API URL + API Key + 模型选择 |
| `api/alchemistApi.js` | API 调用封装 | 基于 polyAgentApi.js axios 实例 |

### 4.5 Session 管理

Session 是 ALchemist 的核心概念——整个优化过程的持久化单元。在页面顶部提供 Session 管理栏：
- **Session 选择器**：`el-select` 下拉列出所有已创建的 Session
- **新建**：弹出对话框输入 Session 名称
- **加载**：从本地 JSON 文件导入 Session
- **保存**：导出当前 Session 为 JSON 文件
- 切换 Session 时，所有面板数据重新加载

### 4.6 LLM 配置

与 Poly_Agent 的对话问答功能共享一致的配置模式：
- LLM API URL 和 API Key 可配置（支持 OpenAI 兼容接口和 Ollama 本地模型）
- 配置存储在浏览器 localStorage
- 不依赖 Poly_Agent 后端，直接由 ALchemist 后端处理

## 5. API 代理映射

ALchemist 原始 API → Poly_Agent 代理路由：

| 原路径 (ALchemist :8004) | 代理路径 (Poly_Agent :8003) | 方法 |
|--------------------------|-----------------------------|------|
| `/api/sessions/` | `/api/v1/alchemist/sessions/` | GET/POST |
| `/api/sessions/{id}/` | `/api/v1/alchemist/sessions/{id}/` | GET/DELETE |
| `/api/sessions/{id}/save` | `/api/v1/alchemist/sessions/{id}/save` | POST |
| `/api/sessions/{id}/load` | `/api/v1/alchemist/sessions/{id}/load` | POST |
| `/api/sessions/{id}/variables/` | `/api/v1/alchemist/sessions/{id}/variables/` | GET/POST |
| `/api/sessions/{id}/variables/{vid}/` | `/api/v1/alchemist/sessions/{id}/variables/{vid}/` | DELETE/PUT |
| `/api/sessions/{id}/experiments/` | `/api/v1/alchemist/sessions/{id}/experiments/` | POST |
| `/api/sessions/{id}/models/` | `/api/v1/alchemist/sessions/{id}/models/` | POST/GET |
| `/api/sessions/{id}/acquisition/` | `/api/v1/alchemist/sessions/{id}/acquisition/` | POST/GET |
| `/api/sessions/{id}/visualizations/` | `/api/v1/alchemist/sessions/{id}/visualizations/` | GET |
| `/api/sessions/{id}/llm/` | `/api/v1/alchemist/sessions/{id}/llm/` | POST |
| `/ws/{session_id}` | `/api/v1/alchemist/ws/{session_id}` | WS |

## 6. 中文化范围

| 范围 | 说明 |
|------|------|
| 前端界面 | 所有按钮、标签、提示、弹窗文本使用中文 |
| 后端日志 | `api/` 下所有 logger 输出使用中文 |
| 后端注释 | 所有 docstring 和行内注释使用中文（含函数参数注释） |
| FastAPI 文档 | title、description、tags 使用中文 |
| 错误消息 | 所有 HTTP 异常消息使用中文 |

## 7. 实施顺序

1. ALchemist 后端中文化（日志 + 注释 + API 描述）
2. Poly_Agent 后端代理路由（alchemist_proxy.py）
3. Poly_Agent 前端 AlchemistApi.js（API 调用封装）
4. Poly_Agent 前端主页面 AlchemistToolView.vue（步骤导航 + Session 管理）
5. Poly_Agent 前端子面板（变量 → 实验 → 建模 → 优化 → 可视化）
6. LLM 配置与集成
7. 端到端联调测试
