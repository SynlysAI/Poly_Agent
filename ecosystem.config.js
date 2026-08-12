/**
 * Poly Agent 原生部署 PM2 配置。
 *
 * 说明：
 * 1. 适用于 Windows / Linux 原生命令行部署
 * 2. MongoDB 建议通过 Docker Compose 单独启动
 * 3. 后端自动托管前端静态文件（需先执行 npm run build 生成 dist）
 * 4. 启动前确保已创建 poly_agent conda 环境
 */
const path = require("path");

const PROJECT_ROOT = process.env.POLY_AGENT_PROJECT_ROOT || __dirname;
const BACKEND_CWD = path.join(PROJECT_ROOT, "backend");
const CONDA_ENV = process.env.POLY_AGENT_CONDA_ENV || "poly_agent";
const HOME = process.env.HOME || process.env.USERPROFILE || "";
const PYTHON_BIN =
  process.env.POLY_AGENT_PYTHON_BIN ||
  path.join(HOME, "miniconda3", "envs", CONDA_ENV, "bin", "python");
const BACKEND_PORT = process.env.POLY_AGENT_BACKEND_PORT || "5201";

module.exports = {
  apps: [
    {
      name: "poly-agent-backend",
      cwd: BACKEND_CWD,
      script: PYTHON_BIN,
      args: `-m uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT}`,
      interpreter: "none",
      env: {
        PYTHONNOUSERSITE: "1",
      },
      watch: false,
      autorestart: true,
      max_memory_restart: "2G",
    },
    {
      name: "poly-agent-assistant-worker",
      cwd: BACKEND_CWD,
      script: PYTHON_BIN,
      args: "-m app.workers.assistant_run_worker --worker-id assistant-pm2-1",
      interpreter: "none",
      env: { PYTHONNOUSERSITE: "1" },
      watch: false,
      autorestart: true,
      max_memory_restart: "1G",
    },
    {
      name: "poly-agent-algorithm-worker",
      cwd: BACKEND_CWD,
      script: PYTHON_BIN,
      args: "-m app.workers.algorithm_run_worker --worker-id algorithm-pm2-1",
      interpreter: "none",
      env: { PYTHONNOUSERSITE: "1" },
      watch: false,
      autorestart: true,
      max_memory_restart: "1G",
    },
  ],
};
