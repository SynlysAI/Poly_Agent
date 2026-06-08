# PolyAgent - 高分子研发智能化中枢

**PolyAgent** 是 AI4Material 生态系统中的核心高分子研发模块，致力于通过人工智能驱动研发全流程的数字化与自动化。本项目目前处于开发框架搭建阶段，旨在构建一套标准化的模型调度与业务协同接口。

## 平台定位

PolyAgent 作为 AI4Material 门户下的垂直应用，主要负责：

* **研发目标转化**：将用户的实验目标与配方约束转化为可执行的计算任务。
* **模型链调度**：封装并调用高分子专用 AI 模型，进行性能预测与方案优化。
* **闭环协同**：通过标准接口与 `SpecAgent`（谱学分析）及 `SpecLabOS`（自动化实验控制）进行数据联动。

## 核心设计框架 (Architecture Design)

本项目的设计遵循模块化原则，确保后续能无缝接入统一门户：

```text
poly_agent/
├── backend/                  # 后端服务 (Python/FastAPI 或 Flask)
│   ├── app/
│   │   ├── api/              # API 接口路由
│   │   ├── core/             # 核心业务逻辑 (intent_parser, workflow, task_manager)
│   │   ├── models/           # 高分子模型工具链接口
│   │   └── integrations/     # 外部协同接口 (SpecAgent, SpecLabOS)
│   └── main.py               # 后端入口
├── frontend/                 # 前端应用 (React/Vue/Next.js)
│   ├── src/
│   │   ├── components/       # 通用组件 (实验步骤卡片, 参数输入框)
│   │   ├── features/         # 业务模块 (需求定义页面, 任务历史看板)
│   │   ├── services/         # API 请求管理
│   │   └── store/            # 状态管理
│   └── package.json
└── docs/                     # API 文档 (Swagger/OpenAPI)
```

## 协同机制与接口定义 (Integration Interface)

PolyAgent 将通过以下标准协议与生态内其他组件进行数据交互：

* **对 SpecLabOS 的指令**：将方案生成的工艺参数封装为标准实验工作流，通过 `lab_os_client` 下发至自动化系统执行。
* **数据回流标准**：定义了统一的 `FeedbackSchema`，用于接收实验结果并存入任务历史数据库。

## 开发计划 (Roadmap)

* [ ] **Phase 1: 核心框架搭建**：完成基础项目结构与 `intent_parser` 模块开发。
* [ ] **Phase 2: 模型工具链接口**：定义标准化模型调用协议，集成初步的性能预测模型。
* [ ] **Phase 3: 门户接入**：完成与 AI4Material 统一登录与权限体系的对接。

## 参与贡献

本项目处于早期开发阶段，欢迎基于现有架构提出功能建议或贡献代码。请在提交 PR 前参考项目的代码风格指南。

## 建议

可以参考SpecAgent项目的前后端框架进行开发：https://github.com/SynlysAI/Spec_Agent
