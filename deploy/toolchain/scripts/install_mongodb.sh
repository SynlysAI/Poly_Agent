#!/usr/bin/env bash
# ============================================================================
# install_mongodb.sh
# ============================================================================
# 在独立 conda 环境 `poly_agent_mongo` 中安装并启动 MongoDB 6.0.16。
#
# 用法：
#   bash install_mongodb.sh --root /path/to/Poly_Agent [--port 27017] [--dbpath <path>]
#
# 默认端口：27017
# 默认数据目录：<PROJECT_ROOT>/.runtime/mongodb
# ============================================================================

set -euo pipefail

# ---- 参数解析 ----
ROOT=""
PORT="27017"
DBPATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --root=*) ROOT="${1#*=}"; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --port=*) PORT="${1#*=}"; shift ;;
    --dbpath) DBPATH="$2"; shift 2 ;;
    --dbpath=*) DBPATH="${1#*=}"; shift ;;
    *) echo "[mongodb] 未知参数: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${ROOT:-}" ]]; then
  echo "[mongodb] 错误：请指定 --root /path/to/Poly_Agent" >&2
  exit 2
fi

ROOT="$(cd "$ROOT" && pwd)"
MONGO_ENV="poly_agent_mongo"

if [[ -z "${DBPATH:-}" ]]; then
  DBPATH="$ROOT/.runtime/mongodb"
fi

# ---- 检测 conda ----
CONDA_CMD="${CONDA_EXE:-conda}"
if ! command -v "$CONDA_CMD" >/dev/null 2>&1; then
  echo "[mongodb] 错误：找不到 conda 命令" >&2
  exit 1
fi

echo "[mongodb] 项目根目录: $ROOT"
echo "[mongodb] MongoDB 环境名: $MONGO_ENV"
echo "[mongodb] 端口: $PORT"
echo "[mongodb] 数据目录: $DBPATH"

# ---- 创建或更新 conda 环境 ----
if "$CONDA_CMD" env list | awk '{print $1}' | grep -qx "$MONGO_ENV"; then
  echo "[mongodb] 环境 $MONGO_ENV 已存在，跳过创建。"
else
  echo "[mongodb] 创建环境 $MONGO_ENV 并安装 MongoDB 6.0.16 ..."
  "$CONDA_CMD" create -n "$MONGO_ENV" -c conda-forge -y \
    mongodb=6.0.16 \
    mongosh
fi

# ---- 准备数据目录 ----
mkdir -p "$DBPATH"
echo "[mongodb] 数据目录已就绪: $DBPATH"

# ---- 检查 MongoDB 是否已在运行 ----
MONGO_PID_FILE="$DBPATH/mongod.pid"
MONGO_LOG_FILE="$DBPATH/mongod.log"

if [[ -f "$MONGO_PID_FILE" ]]; then
  OLD_PID="$(cat "$MONGO_PID_FILE")"
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[mongodb] MongoDB 已在运行（PID: $OLD_PID）"
    # 验证连通性
    if "$CONDA_CMD" run -n "$MONGO_ENV" mongosh --port "$PORT" --eval 'db.runCommand({ping: 1})' --quiet 2>/dev/null; then
      echo "[mongodb] MongoDB ping 验证通过。"
      exit 0
    else
      echo "[mongodb] 警告：PID 文件存在但无法 ping 通，尝试重启..."
      kill "$OLD_PID" 2>/dev/null || true
      sleep 1
    fi
  else
    echo "[mongodb] 清理旧的 PID 文件..."
    rm -f "$MONGO_PID_FILE"
  fi
fi

# ---- 启动 MongoDB ----
echo "[mongodb] 启动 MongoDB（端口 $PORT）..."
PYTHONNOUSERSITE=1 "$CONDA_CMD" run -n "$MONGO_ENV" mongod \
  --dbpath "$DBPATH" \
  --port "$PORT" \
  --fork \
  --logpath "$MONGO_LOG_FILE" \
  --pidfilepath "$MONGO_PID_FILE"

sleep 2

# ---- 验证 MongoDB ----
echo "[mongodb] 验证 MongoDB 连通性..."
if "$CONDA_CMD" run -n "$MONGO_ENV" mongosh --port "$PORT" --eval 'db.runCommand({ping: 1})' --quiet 2>/dev/null; then
  echo "[mongodb] MongoDB 安装完成，ping 验证通过。"
else
  echo "[mongodb] 错误：MongoDB 启动后无法 ping 通，请检查日志: $MONGO_LOG_FILE" >&2
  exit 1
fi

echo ""
echo "[mongodb] MongoDB 管理命令："
echo "  停止: kill \$(cat $MONGO_PID_FILE)"
echo "  连接: conda run -n $MONGO_ENV mongosh --port $PORT"
echo "  日志: tail -f $MONGO_LOG_FILE"
