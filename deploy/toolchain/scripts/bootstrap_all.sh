#!/usr/bin/env bash
# ============================================================================
# bootstrap_all.sh — Poly_Agent 计算工具链一键部署入口
# ============================================================================
#
# 用法：
#   核心模式（只装必装工具）：
#     bash deploy/toolchain/scripts/bootstrap_all.sh --root /path/to/Poly_Agent --mode core
#
#   完整模式（核心 + 可选服务）：
#     bash deploy/toolchain/scripts/bootstrap_all.sh --root /path/to/Poly_Agent --mode full \
#       --alchemist-source /path/to/ALchemist
#
#   完整模式（从 Git 安装 ALchemist）：
#     bash deploy/toolchain/scripts/bootstrap_all.sh --root /path/to/Poly_Agent --mode full \
#       --alchemist-git-url https://github.com/xxx/ALchemist.git
#
# 环境变量（可覆盖默认值）：
#   POLY_AGENT_CONDA_ENV   主 conda 环境名（默认 poly_agent）
#   MONGODB_PORT           MongoDB 端口（默认 27017）
#   BACKEND_PORT           后端服务端口（默认 5100）
#   CONDA_EXE              conda 可执行文件路径
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLCHAIN_DIR="$(dirname "$SCRIPT_DIR")"

# ---- 默认值 ----
ROOT=""
MODE="core"
ALCHEMIST_SOURCE=""
ALCHEMIST_GIT_URL=""
SKIP_ALCHEMIST=false
SKIP_VERIFY=false
MONGODB_PORT="${MONGODB_PORT:-27017}"
BACKEND_PORT="${BACKEND_PORT:-5100}"

# ---- 参数解析 ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --root=*) ROOT="${1#*=}"; shift ;;
    --mode) MODE="$2"; shift 2 ;;
    --mode=*) MODE="${1#*=}"; shift ;;
    --alchemist-source) ALCHEMIST_SOURCE="$2"; shift 2 ;;
    --alchemist-source=*) ALCHEMIST_SOURCE="${1#*=}"; shift ;;
    --alchemist-git-url) ALCHEMIST_GIT_URL="$2"; shift 2 ;;
    --alchemist-git-url=*) ALCHEMIST_GIT_URL="${1#*=}"; shift ;;
    --skip-alchemist) SKIP_ALCHEMIST=true; shift ;;
    --skip-verify) SKIP_VERIFY=true; shift ;;
    --mongodb-port) MONGODB_PORT="$2"; shift 2 ;;
    --mongodb-port=*) MONGODB_PORT="${1#*=}"; shift ;;
    --backend-port) BACKEND_PORT="$2"; shift 2 ;;
    --backend-port=*) BACKEND_PORT="${1#*=}"; shift ;;
    *) echo "[bootstrap] 未知参数: $1" >&2; exit 2 ;;
  esac
done

# ---- 校验参数 ----
if [[ -z "${ROOT:-}" ]]; then
  echo "[bootstrap] 错误：请指定 --root /path/to/Poly_Agent" >&2
  exit 2
fi

ROOT="$(cd "$ROOT" && pwd)"

if [[ "$MODE" != "core" && "$MODE" != "full" ]]; then
  echo "[bootstrap] 错误：--mode 必须是 core 或 full，当前值: $MODE" >&2
  exit 2
fi

echo "============================================"
echo " Poly_Agent 计算工具链部署"
echo "============================================"
echo "  项目根目录: $ROOT"
echo "  部署模式:   $MODE"
echo "  MongoDB 端口: $MONGODB_PORT"
echo "  后端端口:     $BACKEND_PORT"
echo "============================================"
echo ""

# ---- 检测 conda ----
if ! command -v conda >/dev/null 2>&1; then
  echo "[bootstrap] 错误：找不到 conda 命令。请先安装 Miniconda 或 Anaconda。" >&2
  echo "[bootstrap] 安装指引: https://docs.conda.io/en/latest/miniconda.html" >&2
  exit 1
fi

# ======================================================================
# Phase 1: 安装核心 conda 环境
# ======================================================================
echo "[bootstrap] ===== Phase 1/5: 安装核心 conda 环境 ====="
bash "$SCRIPT_DIR/install_core_conda.sh" --root "$ROOT"
echo ""

# ======================================================================
# Phase 2: 安装 MongoDB
# ======================================================================
echo "[bootstrap] ===== Phase 2/5: 安装 MongoDB ====="
bash "$SCRIPT_DIR/install_mongodb.sh" --root "$ROOT" --port "$MONGODB_PORT"
echo ""

# ======================================================================
# Phase 3: 生成 backend/.env
# ======================================================================
echo "[bootstrap] ===== Phase 3/5: 配置 backend/.env ====="
TEMPLATE="$TOOLCHAIN_DIR/env/backend.env.template"
TARGET_ENV="$ROOT/backend/.env"

if [[ -f "$TARGET_ENV" ]]; then
  echo "[bootstrap] $TARGET_ENV 已存在，跳过生成。"
  echo "[bootstrap] 如需重新生成，请先删除现有文件: rm $TARGET_ENV"
else
  if [[ -f "$TEMPLATE" ]]; then
    cp "$TEMPLATE" "$TARGET_ENV"
    # 写入部署参数
    cat >> "$TARGET_ENV" <<EOF

# ---- 由 bootstrap_all.sh 自动写入 ----
MONGODB_PORT=$MONGODB_PORT
EOF
    echo "[bootstrap] 已从模板生成 $TARGET_ENV"
  else
    echo "[bootstrap] 警告：未找到模板文件 $TEMPLATE，跳过 .env 生成。"
  fi
fi
echo ""

# ======================================================================
# Phase 4: 构建前端
# ======================================================================
echo "[bootstrap] ===== Phase 4/5: 构建前端 ====="
FRONTEND_DIR="$ROOT/frontend"
CONDA_ENV="${POLY_AGENT_CONDA_ENV:-poly_agent}"
if [[ -f "$FRONTEND_DIR/package.json" ]]; then
  PYTHONNOUSERSITE=1 conda run -n "$CONDA_ENV" npm run build --prefix "$FRONTEND_DIR" || {
    echo "[bootstrap] 警告：前端构建失败，后端仍可启动但前端页面不可用。" >&2
  }
  echo "[bootstrap] 前端构建完成。"
else
  echo "[bootstrap] 警告：未找到 frontend/package.json，跳过前端构建。"
fi
echo ""

# ======================================================================
# Phase 5: 可选服务安装
# ======================================================================
if [[ "$MODE" == "full" ]]; then
  echo "[bootstrap] ===== Phase 5/5: 可选服务安装 ====="

  # ---- ALchemist ----
  if $SKIP_ALCHEMIST; then
    echo "[bootstrap] 跳过 ALchemist 安装。"
  else
    ALCHEMIST_ARGS=("--root" "$ROOT")
    if [[ -n "${ALCHEMIST_SOURCE:-}" ]]; then
      ALCHEMIST_ARGS+=("--source" "$ALCHEMIST_SOURCE")
    elif [[ -n "${ALCHEMIST_GIT_URL:-}" ]]; then
      ALCHEMIST_ARGS+=("--git-url" "$ALCHEMIST_GIT_URL")
    else
      ALCHEMIST_ARGS+=("--skip")
    fi
    bash "$SCRIPT_DIR/install_alchemist.sh" "${ALCHEMIST_ARGS[@]}" || {
      echo "[bootstrap] 警告：ALchemist 安装失败，主系统不受影响。" >&2
    }
  fi

else
  echo "[bootstrap] ===== Phase 5/5: 可选服务安装 ====="
  echo "[bootstrap] core 模式：跳过所有可选服务。"
fi
echo ""

# ======================================================================
# 写入集成配置摘要
# ======================================================================
echo "[bootstrap] 写入服务集成配置摘要..."
PYTHONNOUSERSITE=1 conda run -n "$CONDA_ENV" python "$SCRIPT_DIR/configure_integrations.py" \
  --root "$ROOT" \
  --mode "$MODE" \
  --alchemist-available "${ALCHEMIST_SOURCE:-${ALCHEMIST_GIT_URL:-}}" || {
  echo "[bootstrap] 警告：集成配置写入失败，可稍后手动执行。" >&2
}
echo ""

# ======================================================================
# 验收
# ======================================================================
if $SKIP_VERIFY; then
  echo "[bootstrap] 跳过验收（--skip-verify）。"
else
  echo "[bootstrap] 执行工具链验收..."
  REPORT_DIR="$ROOT/.runtime/toolchain-verify"
  mkdir -p "$REPORT_DIR"
  PYTHONNOUSERSITE=1 conda run -n "$CONDA_ENV" python "$SCRIPT_DIR/verify_toolchain.py" \
    --root "$ROOT" \
    --mode "$MODE" \
    --report-dir "$REPORT_DIR" \
    --backend-port "$BACKEND_PORT" || {
    echo "[bootstrap] 警告：部分验收项目未通过，请查看报告。" >&2
  }
fi

echo ""
echo "============================================"
echo " Poly_Agent 计算工具链部署完成"
echo "============================================"
echo ""
echo "  启动后端服务:"
echo "    cd $ROOT/backend"
echo "    conda run -n $CONDA_ENV uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT"
echo ""
echo "  启动计算 worker:"
echo "    cd $ROOT/backend"
echo "    conda run -n $CONDA_ENV python -m app.workers.computation_worker"
echo ""
echo "  验收报告:"
echo "    $ROOT/.runtime/toolchain-verify/report.md"
echo ""
echo "  如需使用 PM2 管理服务，请参考:"
echo "    $ROOT/ecosystem.config.js"
echo "============================================"
