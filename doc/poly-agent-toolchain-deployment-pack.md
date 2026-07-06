# Poly_Agent 计算工具链部署包

## 概述

Poly_Agent 计算工具链部署包是一个可复用的在线安装包，包含安装脚本、配置模板、服务注册、健康检查和 demo 验收。

**部署包不包含**：历史 Mongo 数据、历史 computation artifacts、用户上传文件、任何密钥（LLM API Key、ORCA license、HPC 凭据、SpecLabOS token）。

## 系统要求

| 项目 | 最低要求 |
|------|----------|
| 操作系统 | Linux x86_64 |
| conda | Miniconda3 或 Anaconda（conda 命令在 PATH） |
| 网络 | 能访问 conda-forge、pip、npm |
| 磁盘空间 | ~5 GB（含所有 conda 环境和依赖） |
| 内存 | 8 GB（CREST/xTB 计算需要） |

## 快速开始

### 1. 解压部署包

```bash
tar xzf poly-agent-toolchain-online-YYYYMMDD.tgz
```

### 2. 一键安装（核心模式）

```bash
bash poly-agent-toolchain/deploy/toolchain/scripts/bootstrap_all.sh \
  --root /path/to/Poly_Agent \
  --mode core
```

核心模式安装：
- `poly_agent` conda 环境（Python 3.12、Node 22、RDKit、OpenBabel、xTB、CREST）
- `poly_agent_mongo` conda 环境（MongoDB 6.0.16）
- Poly_Agent 后端 Python 依赖
- Poly_Agent 前端 npm 依赖
- 自动生成 `backend/.env` 配置模板
- 自动写入服务集成配置摘要
- 自动执行工具链验收

### 3. 一键安装（完整模式）

```bash
bash poly-agent-toolchain/deploy/toolchain/scripts/bootstrap_all.sh \
  --root /path/to/Poly_Agent \
  --mode full \
  --alchemist-source /path/to/ALchemist
```

完整模式额外安装：
- ALchemist 主动学习优化后端（从本地路径或 Git 仓库）
- AiiDA 计算溯源框架（探测级部署）

跳过特定可选服务：

```bash
bash deploy/toolchain/scripts/bootstrap_all.sh \
  --root /path/to/Poly_Agent \
  --mode full \
  --skip-alchemist \
  --skip-aiida
```

### 4. 验收

安装完成后自动执行。也可手动执行：

```bash
python deploy/toolchain/scripts/verify_toolchain.py --root /path/to/Poly_Agent
```

验收报告输出到：
- `.runtime/toolchain-verify/report.json`
- `.runtime/toolchain-verify/report.md`

## 工具清单

### 核心必装工具

| 工具 | 用途 | 来源 | 环境 | 端口 |
|------|------|------|------|------|
| Python 3.12 | FastAPI 后端运行时 | conda-forge | `poly_agent` | — |
| Node.js 22 | Vite 前端构建 | conda-forge | `poly_agent` | — |
| RDKit | 化学信息学工具包，SMILES → 3D 结构 | conda-forge | `poly_agent` | — |
| OpenBabel | 化学文件格式转换 | conda-forge | `poly_agent` | — |
| xTB | 半经验量子化学计算 | conda-forge | `poly_agent` | — |
| CREST | 构象搜索与团簇采样 | conda-forge | `poly_agent` | — |
| MongoDB 6.0.16 | 文档数据库 | conda-forge | `poly_agent_mongo` | 27017 |
| Poly_Agent Backend | FastAPI 后端服务 | pip (requirements.txt) | `poly_agent` | 5100 |
| Poly_Agent Frontend | Vue 3 + Vite + Element Plus | npm | `poly_agent` | — |
| Computation Worker | 计算任务消费者 | Python（内置） | `poly_agent` | — |

### 可选服务

| 工具 | 用途 | 来源 | 环境 | 端口 | 边界说明 |
|------|------|------|------|------|----------|
| ALchemist | 主动学习优化后端 | Git / 本地路径 | `poly_agent_alchemist` | 8004 | 独立 FastAPI 服务，Poly_Agent 通过 `/api/v1/alchemist/*` 代理访问 |
| AiiDA | 计算溯源框架 | conda-forge | `poly_agent_aiida` | — | 探测级部署，当前不承诺可提交真实 WorkChain |
| ORCA | 量子化学程序 | 用户自行安装 | 系统 PATH | — | 商业软件，仅做路径/许可证标记和 probe；不自动安装 |
| Atlas/ComputeEngine | 优化器 | 参考仓库 | — | 65100 | 默认 disabled；参考仓库不完整时只写配置摘要和 down 状态 |

## 服务集成状态策略

工具链安装后，`configure_integrations.py` 按以下策略写入 Poly_Agent 集成配置：

| 服务 | enabled | 状态 | 条件 |
|------|---------|------|------|
| `computation-worker` | ✅ true | `up` | 始终（核心必装） |
| `artifact-store` | ✅ true | `up` | 始终（核心必装） |
| `alchemist-backend` | 有 endpoint 时 true | `up` / `down` | endpoint 配置且可达 → `up`；endpoint 不可达 → `down` |
| `aiida` | 安装后 true | — | 写入 profile/config 摘要；标注 "deployed/probe only" |
| `orca` | 条件 true | — | 仅 `ORCA_LICENSE_AVAILABLE=true` 且 probe 正常时 |
| `atlas` | ❌ false | `down` | 默认 disabled |
| `speclabos` | ❌ false | `not_configured` | MVP 不运行真实 workflow |

## 验收项目

### 自动验收（verify_toolchain.py）

1. **核心工具 CLI 验证**：`python --version`、`node --version`、`rdkit` import、`obabel -V`、`xtb --version`、`crest --version`
2. **MongoDB ping**：`mongosh --eval 'db.runCommand({ping: 1})'`
3. **后端健康检查**：`GET /api/v1/health`（`api: up`、`mongodb: up`）
4. **集成状态**：`GET /api/v1/integrations/status`
5. **Smoke Demo 1**：`LOCAL_STRUCTURE / RDKit`，输入 `CCO` → `structure.json`、`structure.xyz`、`structure.sdf`
6. **Smoke Demo 2**：`LOCAL_XTB / XTB`，输入 `O` → CREST + xTB，`normal_termination=true`
7. **后端单元测试**：`python -m unittest discover -s tests -p 'test_*.py'`
8. **前端构建**：`npm run build`

### ResearchEngine 验收（P0 完成后启用）

以下验证项在 ResearchEngine P0 部署后手动执行，后续版本将集成到 `verify_toolchain.py`：

1. **ProblemSpec API 可达性**：`GET /api/v1/research-engine/problem-specs` 返回 200
2. **AlgorithmRegistry 默认清单**：`GET /api/v1/research-engine/algorithms` 返回 ≥ 8 个算法条目
3. **ResearchEngine Smoke Demo**：创建氟基高分子 ProblemSpec → 人工运行 mock predictor → 查看 AlgorithmRun → 创建 ResearchRun → 推进到 gate → 审批

## 启动服务

### 使用 PM2（推荐）

```bash
# 确保 poly_agent conda 环境已激活
pm2 start ecosystem.config.js
pm2 save
```

### 手动启动

```bash
# 1. 启动 MongoDB（如果尚未运行）
bash deploy/toolchain/scripts/install_mongodb.sh --root /path/to/Poly_Agent

# 2. 启动后端（生产模式，托管前端静态文件）
cd backend
conda run -n poly_agent uvicorn app.main:app --host 0.0.0.0 --port 5100

# 3. 启动计算 worker
conda run -n poly_agent python -m app.workers.computation_worker

# 4. 启动前端开发服务器（仅开发模式）
cd frontend
npm run dev
```

## 分步安装

如果不想使用 `bootstrap_all.sh` 一键安装，可以按顺序执行各脚本：

```bash
SCRIPTS=deploy/toolchain/scripts

# 1. 安装核心 conda 环境
bash $SCRIPTS/install_core_conda.sh --root /path/to/Poly_Agent

# 2. 安装 MongoDB
bash $SCRIPTS/install_mongodb.sh --root /path/to/Poly_Agent

# 3. 生成 backend/.env
cp deploy/toolchain/env/backend.env.template backend/.env
# 编辑 backend/.env 填入实际配置

# 4. 构建前端
cd frontend && npm run build && cd ..

# 5. 写入集成配置（需要后端运行）
conda run -n poly_agent python $SCRIPTS/configure_integrations.py \
  --root /path/to/Poly_Agent --mode core

# 6. 验证
conda run -n poly_agent python $SCRIPTS/verify_toolchain.py \
  --root /path/to/Poly_Agent
```

## 常见问题排查

### conda 命令找不到

```bash
# 确认 conda 已安装
which conda

# 如果未安装，请先安装 Miniconda：
# https://docs.conda.io/en/latest/miniconda.html
```

### conda 环境创建失败

```bash
# 检查网络访问
conda search rdkit

# 如果 conda-forge 不可达，配置镜像：
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/
conda config --set show_channel_urls yes
```

### MongoDB 无法启动

```bash
# 检查端口占用
lsof -i :27017

# 检查数据目录
ls -la .runtime/mongodb/

# 查看 MongoDB 日志
tail -100 .runtime/mongodb/mongod.log

# 手动启动
conda run -n poly_agent_mongo mongod \
  --dbpath .runtime/mongodb \
  --port 27017 \
  --fork \
  --logpath .runtime/mongodb/mongod.log
```

### xTB / CREST 验证失败

```bash
# 确认工具在 PATH 中
conda run -n poly_agent which xtb
conda run -n poly_agent which crest

# 手动测试
conda run -n poly_agent xtb --version
conda run -n poly_agent crest --version
```

### 后端健康检查失败

```bash
# 确认后端在运行
curl http://127.0.0.1:5100/api/v1/health

# 如果没有响应，检查后端是否启动
ps aux | grep uvicorn

# 查看后端日志
tail -100 .runtime/logs/*.log
```

### ALchemist 安装失败

ALchemist 是可选的，安装失败不影响主系统。如需重装：

```bash
# 清理后重装
conda env remove -n poly_agent_alchemist

bash deploy/toolchain/scripts/install_alchemist.sh \
  --root /path/to/Poly_Agent \
  --source /path/to/ALchemist
```

### AiiDA 安装后无法使用

AiiDA 当前是探测级部署，如需完整配置：

```bash
conda activate poly_agent_aiida
verdi quicksetup    # 需要 PostgreSQL
verdi daemon start
```

### 重装整个工具链

```bash
# 1. 删除 conda 环境
conda env remove -n poly_agent
conda env remove -n poly_agent_mongo
conda env remove -n poly_agent_alchemist
conda env remove -n poly_agent_aiida

# 2. 清理运行时数据（可选）
rm -rf .runtime/mongodb/

# 3. 重新安装
bash deploy/toolchain/scripts/bootstrap_all.sh --root /path/to/Poly_Agent --mode core
```

## 打包部署包

```bash
bash deploy/toolchain/scripts/package_bundle.sh --root /path/to/Poly_Agent
# 输出: poly-agent-toolchain-online-YYYYMMDD.tgz
```

## 后续步骤

工具链安装和验收完成后，建议阅读以下文档：

- **计算 Workflow 使用指南**：`doc/computation-workflows-user-guide.md` — 了解三条计算路径如何选择和使用
- **ResearchEngine 技术方案**：`doc/research-engine-and-auto-research-design.md` — 了解 AI 研发双通道架构
- **ResearchEngine 实施计划**：`doc/research-engine-plan-00-roadmap.md` — 了解分阶段开发计划

## 工具链与 ResearchEngine 算法注册表的映射

部署包安装的工具在 ResearchEngine 中作为 AlgorithmRegistry 的算法条目接入：

| 部署包安装的工具 | ResearchEngine algorithm_id | 类型 | 说明 |
| --- | --- | --- | --- |
| RDKit（核心必装） | `local_structure_adapter` | simulator | 三维结构生成算法 |
| xTB + CREST（核心必装） | `local_xtb_adapter` | simulator | 半经验量子化学计算算法 |
| ORCA（可选） | `orca_compute_engine_laser_adapter` | simulator | DFT 精加工算法（需 license） |
| ALchemist（可选） | 后续 P1 接入 | optimizer | 主动学习优化后端 |
| AiiDA（可选） | 后续 P2 接入 | provenance | 计算溯源框架 |

ResearchEngine 不引入新的 conda 环境或系统依赖。所有计算能力已在部署包中覆盖。详见 `doc/research-engine-and-auto-research-design.md` §17-18。

## 版本

- 部署包版本：0.1.0
- 最低 Poly_Agent 版本：0.1.0
- ResearchEngine 兼容版本：≥ v0.3（P0 阶段）
- 文档更新日期：2026-07-06

### 版本兼容矩阵

| 部署包版本 | Poly_Agent 版本 | ResearchEngine | 备注 |
| --- | --- | --- | --- |
| 0.1.0 | 0.1.0 | — | 初始版本，支持计算智能 + 湿实验优化 |
| 0.2.0（计划） | 0.2.0 | P0 | 新增 ResearchEngine P0 验收项（§ResearchEngine 验收） |
| 0.3.0（计划） | 0.3.0 | P1+ | AlgorithmRegistry 管理、真实 LabOS 提交 |
