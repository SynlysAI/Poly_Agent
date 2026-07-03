# Poly Agent — 高分子智能分析平台

**Poly Agent** 是 AI4MS 门户下的高分子材料性能预测子应用，与 Spec Agent 同属一个产品线。为用户提供高分子样品性能指标预测、任务管理和实验数据浏览功能。

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12 + FastAPI + MongoDB |
| 前端 | Vue 3 + Element Plus + Vite |
| 认证 | HMAC-SHA256 令牌，与 AI4MS 门户共享账户体系 |

## 项目结构

```text
Poly_Agent/
├── backend/
│   ├── app/
│   │   ├── api/v1/                # API 路由 (health, auth, admin)
│   │   ├── core/                  # 配置、令牌认证、日志
│   │   ├── infra/                 # MongoDB 连接、数据仓储
│   │   ├── schemas/               # Pydantic 数据模型
│   │   ├── services/              # 认证服务 (登录/注册/邀请码)
│   │   └── main.py                # FastAPI 入口 (托管前端静态文件)
│   ├── .env.example               # 环境变量模板
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/                   # Axios 客户端与 API 调用
│   │   ├── auth/                  # 认证状态管理 + 门户 SSO
│   │   ├── router/                # 路由配置 + 导航守卫
│   │   ├── views/                 # 页面组件
│   │   │   ├── DashboardView      # 工作台
│   │   │   ├── TaskSubmitView     # 任务提交 (性能预测)
│   │   │   ├── TaskCenterView     # 任务中心
│   │   │   ├── DialogueView       # 问答对话
│   │   │   ├── ToolServicesView   # 工具服务
│   │   │   ├── DatabaseManagementView  # 数据库管理 (管理员)
│   │   │   ├── LoginView          # 登录
│   │   │   └── RegisterView       # 邀请码注册
│   │   ├── App.vue                # 主布局 (侧边栏 + 顶栏)
│   │   ├── style.css              # 全局样式 (DESIGN.md 规范)
│   │   └── main.js
│   ├── public/brand/              # 品牌 Logo
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── DESIGN.md                      # 前端设计规范文档
├── ecosystem.config.js            # PM2 部署配置
└── .gitignore
```

## 快速开始

### 1. 环境准备

```bash
# 一次性创建 / 更新项目 conda 环境（Python 3.12 + Node.js 22）
bash scripts/setup_poly_agent_env.sh

# 手动激活环境
conda activate poly_agent
```

### 2. 配置环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 .env，配置 MongoDB 连接信息和 AUTH_SECRET（与 AI4MS 保持一致）
```

### 3. 开发模式

```bash
# 推荐：一条命令重启前后端
bash scripts/restart_poly_agent_services.sh

# 停止前后端
bash scripts/stop_poly_agent_services.sh
```

默认开发端口：

- 前端：`http://127.0.0.1:5100`
- 后端：`http://127.0.0.1:5101`

前端开发服务器会自动把 `/api` 和 `/static` 代理到后端。

### 4. 生产部署

```bash
# 构建前端
cd frontend && npm run build

# 启动后端（自动托管前端静态文件，默认端口 5100）
cd ../backend
conda run -n poly_agent python -m uvicorn app.main:app --host 0.0.0.0 --port 5100

# 或使用 PM2
pm2 start ecosystem.config.js
```

生产模式下直接访问 `http://<host>:5100` 即可，后端自动提供前端 SPA 页面。

## 认证体系

- 与 AI4MS 门户共享 `ai4ms` 认证数据库中的 `users` 和 `invite_codes` 集合
- 支持从已登录的 AI4MS 门户通过 URL hash 传递 token 实现免登录（SSO）
- 管理员通过邀请码控制用户注册
- 通过 `AUTH_ENABLED` 环境变量可切换是否需要登录

## 相关项目

- [AI4MS](https://github.com/SynlysAI/AI4MS) — 高分子智能研发门户
- [Spec Agent](https://github.com/SynlysAI/Spec_Agent) — 谱图智能分析平台
