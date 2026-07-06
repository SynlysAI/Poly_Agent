#!/usr/bin/env bash
# ============================================================================
# install_core_conda.sh
# ============================================================================
# 安装 Poly_Agent 核心 conda 环境 `poly_agent`，包含：
#   - Python 3.12 + FastAPI 依赖
#   - Node.js 22 + npm（前端构建）
#   - RDKit、OpenBabel、xTB、CREST
#
# 用法：
#   bash install_core_conda.sh --root /path/to/Poly_Agent
#
# 环境变量：
#   POLY_AGENT_CONDA_ENV  目标 conda 环境名称（默认 poly_agent）
#   CONDA_EXE             conda 可执行文件路径（可选）
# ============================================================================

set -euo pipefail

# ---- 参数解析 ----
ROOT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --root=*) ROOT="${1#*=}"; shift ;;
    *) echo "[core_conda] 未知参数: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${ROOT:-}" ]]; then
  echo "[core_conda] 错误：请指定 --root /path/to/Poly_Agent" >&2
  exit 2
fi

ROOT="$(cd "$ROOT" && pwd)"
ENV_NAME="${POLY_AGENT_CONDA_ENV:-poly_agent}"

# ---- 检测 conda ----
CONDA_CMD="${CONDA_EXE:-conda}"
if ! command -v "$CONDA_CMD" >/dev/null 2>&1; then
  echo "[core_conda] 错误：找不到 conda 命令，请先安装 Miniconda 或 Anaconda" >&2
  exit 1
fi

echo "[core_conda] 使用 conda: $(command -v "$CONDA_CMD")"
echo "[core_conda] 项目根目录: $ROOT"
echo "[core_conda] 目标环境名: $ENV_NAME"

# ---- 检查 environment.yml ----
ENV_FILE="$ROOT/environment.yml"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "[core_conda] 错误：找不到 $ENV_FILE" >&2
  exit 1
fi

# ---- 创建或更新 conda 环境 ----
if "$CONDA_CMD" env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "[core_conda] 环境 $ENV_NAME 已存在，执行更新..."
  "$CONDA_CMD" env update -f "$ENV_FILE" --prune
else
  echo "[core_conda] 创建新环境 $ENV_NAME ..."
  "$CONDA_CMD" env create -f "$ENV_FILE"
fi

# ---- 安装后端 pip 依赖 ----
echo "[core_conda] 安装后端 Python 依赖..."
REQUIREMENTS_FILE="$ROOT/backend/requirements.txt"
if [[ -f "$REQUIREMENTS_FILE" ]]; then
  PYTHONNOUSERSITE=1 "$CONDA_CMD" run -n "$ENV_NAME" pip install -r "$REQUIREMENTS_FILE"
else
  echo "[core_conda] 警告：未找到 $REQUIREMENTS_FILE，跳过 pip 安装"
fi

# ---- 安装前端 npm 依赖 ----
echo "[core_conda] 安装前端 npm 依赖..."
FRONTEND_DIR="$ROOT/frontend"
if [[ -f "$FRONTEND_DIR/package.json" ]]; then
  PYTHONNOUSERSITE=1 "$CONDA_CMD" run -n "$ENV_NAME" npm install --prefix "$FRONTEND_DIR"
else
  echo "[core_conda] 警告：未找到 $FRONTEND_DIR/package.json，跳过 npm 安装"
fi

# ---- 验证核心工具 ----
echo ""
echo "[core_conda] ========== 验证核心工具 =========="

verify_cmd() {
  local label="$1"
  local cmd="$2"
  echo -n "[core_conda]   $label ... "
  if PYTHONNOUSERSITE=1 "$CONDA_CMD" run -n "$ENV_NAME" bash -c "$cmd" >/dev/null 2>&1; then
    echo "OK"
    return 0
  else
    echo "FAILED"
    return 1
  fi
}

FAILURES=0

verify_cmd "python --version" "python --version" || ((FAILURES++))
verify_cmd "node --version" "node --version" || ((FAILURES++))
verify_cmd "npm --version" "npm --version" || ((FAILURES++))
verify_cmd "rdkit" "python -c 'import rdkit; print(rdkit.__version__)'" || ((FAILURES++))
verify_cmd "openbabel" "obabel -V" || ((FAILURES++))
verify_cmd "xtb" "xtb --version" || ((FAILURES++))
verify_cmd "crest" "crest --version" || ((FAILURES++))
verify_cmd "fastapi" "python -c 'import fastapi; print(fastapi.__version__)'" || ((FAILURES++))

echo ""
if [[ $FAILURES -eq 0 ]]; then
  echo "[core_conda] 核心环境安装完成，所有工具验证通过。"
else
  echo "[core_conda] 警告：$FAILURES 项验证失败，请检查上述输出。" >&2
  exit 1
fi
