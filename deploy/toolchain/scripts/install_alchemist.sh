#!/usr/bin/env bash
# ============================================================================
# install_alchemist.sh
# ============================================================================
# 可选安装 ALchemist 主动学习优化后端（独立 FastAPI 服务，端口 8004）。
#
# 用法：
#   从本地路径安装：
#     bash install_alchemist.sh --root /path/to/Poly_Agent --source /path/to/ALchemist
#   从 Git 仓库安装：
#     bash install_alchemist.sh --root /path/to/Poly_Agent --git-url https://github.com/xxx/ALchemist.git
#   跳过 ALchemist 安装：
#     bash install_alchemist.sh --root /path/to/Poly_Agent --skip
#
# ALchemist 会安装在独立的 conda 环境中，不污染 poly_agent 主环境。
# ============================================================================

set -euo pipefail

ROOT=""
SOURCE=""
GIT_URL=""
SKIP=false
PORT="${ALCHEMIST_PORT:-8004}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --root=*) ROOT="${1#*=}"; shift ;;
    --source) SOURCE="$2"; shift 2 ;;
    --source=*) SOURCE="${1#*=}"; shift ;;
    --git-url) GIT_URL="$2"; shift 2 ;;
    --git-url=*) GIT_URL="${1#*=}"; shift ;;
    --skip) SKIP=true; shift ;;
    *) echo "[alchemist] 未知参数: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${ROOT:-}" ]]; then
  echo "[alchemist] 错误：请指定 --root /path/to/Poly_Agent" >&2
  exit 2
fi

ROOT="$(cd "$ROOT" && pwd)"

if $SKIP; then
  echo "[alchemist] 已跳过 ALchemist 安装（--skip）。"
  exit 0
fi

if [[ -z "${SOURCE:-}" && -z "${GIT_URL:-}" ]]; then
  echo "[alchemist] 未指定 --source 或 --git-url，跳过 ALchemist 安装。"
  echo "[alchemist] 提示：使用 --skip 可静默跳过此步骤。"
  exit 0
fi

# ---- 检测 conda ----
CONDA_CMD="${CONDA_EXE:-conda}"
if ! command -v "$CONDA_CMD" >/dev/null 2>&1; then
  echo "[alchemist] 错误：找不到 conda 命令" >&2
  exit 1
fi

echo "[alchemist] 项目根目录: $ROOT"
echo "[alchemist] 目标端口: $PORT"

ALCHEMIST_HOME=""

if [[ -n "${SOURCE:-}" ]]; then
  # ---- 从本地路径安装 ----
  if [[ ! -d "$SOURCE" ]]; then
    echo "[alchemist] 错误：ALchemist 源码路径不存在: $SOURCE" >&2
    exit 1
  fi
  ALCHEMIST_HOME="$(cd "$SOURCE" && pwd)"
  echo "[alchemist] 使用本地源码: $ALCHEMIST_HOME"
elif [[ -n "${GIT_URL:-}" ]]; then
  # ---- 从 Git 仓库克隆 ----
  ALCHEMIST_HOME="$ROOT/.runtime/alchemist"
  if [[ -d "$ALCHEMIST_HOME" ]]; then
    echo "[alchemist] ALchemist 目录已存在，执行 git pull ..."
    (cd "$ALCHEMIST_HOME" && git pull) || {
      echo "[alchemist] git pull 失败，重新克隆..."
      rm -rf "$ALCHEMIST_HOME"
      git clone "$GIT_URL" "$ALCHEMIST_HOME"
    }
  else
    echo "[alchemist] 克隆 ALchemist 仓库: $GIT_URL"
    git clone "$GIT_URL" "$ALCHEMIST_HOME"
  fi
fi

# ---- 创建独立 conda 环境 ----
ALCHEMIST_ENV="poly_agent_alchemist"

if "$CONDA_CMD" env list | awk '{print $1}' | grep -qx "$ALCHEMIST_ENV"; then
  echo "[alchemist] 环境 $ALCHEMIST_ENV 已存在，跳过创建。"
else
  echo "[alchemist] 创建独立环境 $ALCHEMIST_ENV ..."
  "$CONDA_CMD" create -n "$ALCHEMIST_ENV" -c conda-forge -y python=3.12 pip
fi

# ---- 安装 ALchemist 依赖 ----
if [[ -f "$ALCHEMIST_HOME/requirements.txt" ]]; then
  echo "[alchemist] 安装 ALchemist Python 依赖..."
  PYTHONNOUSERSITE=1 "$CONDA_CMD" run -n "$ALCHEMIST_ENV" pip install -r "$ALCHEMIST_HOME/requirements.txt"
elif [[ -f "$ALCHEMIST_HOME/pyproject.toml" ]]; then
  echo "[alchemist] 通过 pip install 安装 ALchemist..."
  PYTHONNOUSERSITE=1 "$CONDA_CMD" run -n "$ALCHEMIST_ENV" pip install -e "$ALCHEMIST_HOME"
fi

# ---- 生成 ALchemist .env（如果存在模板） ----
if [[ -f "$ALCHEMIST_HOME/.env.example" ]]; then
  if [[ ! -f "$ALCHEMIST_HOME/.env" ]]; then
    echo "[alchemist] 从 .env.example 生成 .env ..."
    cp "$ALCHEMIST_HOME/.env.example" "$ALCHEMIST_HOME/.env"
  fi
fi

echo ""
echo "[alchemist] ALchemist 安装完成。"
echo "[alchemist] 启动命令:"
echo "  cd $ALCHEMIST_HOME"
echo "  conda run -n $ALCHEMIST_ENV uvicorn main:app --host 127.0.0.1 --port $PORT"
echo ""
echo "[alchemist] 注意：ALchemist 不会由 bootstrap_all.sh 自动启动。"
echo "  请在 PM2 或 systemd 中单独配置 ALchemist 服务。"
