/**
 * Poly Agent 原生部署 PM2 配置。
 *
 * 说明：
 * 1. 适用于 Windows / Linux 原生命令行部署
 * 2. MongoDB 建议通过 Docker Compose 单独启动
 * 3. 后端自动托管前端静态文件（需先执行 npm run build 生成 dist）
 * 4. 启动前确保已激活 poly_agent conda 环境或配置 POLY_AGENT_PYTHON_BIN
 */
const path = require("path");

const PROJECT_ROOT = process.env.POLY_AGENT_PROJECT_ROOT || __dirname;
const BACKEND_CWD = path.join(PROJECT_ROOT, "backend");

const UVICORN_BIN = process.env.POLY_AGENT_UVICORN_BIN || "uvicorn";

const BACKEND_PORT = process.env.POLY_AGENT_BACKEND_PORT || "8003";

module.exports = {
  apps: [
    {
      name: "poly-agent-backend",
      cwd: BACKEND_CWD,
      script: UVICORN_BIN,
      args: `app.main:app --host 0.0.0.0 --port ${BACKEND_PORT}`,
      interpreter: "none",
      watch: false,
      autorestart: true,
      max_memory_restart: "2G",
    },
  ],
};
