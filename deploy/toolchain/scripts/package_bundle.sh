#!/usr/bin/env bash
# ============================================================================
# package_bundle.sh
# ============================================================================
# 将 Poly_Agent 计算工具链部署包打包为 .tgz 归档。
#
# 用法：
#   bash deploy/toolchain/scripts/package_bundle.sh --root /path/to/Poly_Agent
#   bash deploy/toolchain/scripts/package_bundle.sh --root /path/to/Poly_Agent --output /tmp/
#
# 输出：
#   poly-agent-toolchain-online-<YYYYMMDD>.tgz
#
# 归档内容：
#   - deploy/toolchain/           部署脚本、清单、模板
#   - environment.yml              conda 环境定义
#   - backend/requirements.txt     Python 依赖
#   - backend/app/                 后端源码
#   - backend/tests/              测试文件
#   - frontend/package.json        前端依赖声明
#   - frontend/vite.config.js      前端构建配置
#   - frontend/src/                前端源码
#   - frontend/index.html          前端入口
#   - frontend/public/             前端静态资源
#   - ecosystem.config.js          PM2 配置
#   - doc/poly-agent-toolchain-deployment-pack.md  部署文档
#
# 排除：
#   - .env 文件（包含密钥）
#   - .git/
#   - node_modules/
#   - __pycache__/ .pytest_cache/
#   - .runtime/（运行时数据）
#   - dist/（构建产物）
#   - refer/（参考代码）
#   - docs/（工作流文档）
# ============================================================================

set -euo pipefail

ROOT=""
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --root=*) ROOT="${1#*=}"; shift ;;
    --output) OUTPUT_DIR="$2"; shift 2 ;;
    --output=*) OUTPUT_DIR="${1#*=}"; shift ;;
    *) echo "[package] 未知参数: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${ROOT:-}" ]]; then
  echo "[package] 错误：请指定 --root /path/to/Poly_Agent" >&2
  exit 2
fi

ROOT="$(cd "$ROOT" && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT}"
DATE_SUFFIX="$(date +%Y%m%d)"
ARCHIVE_NAME="poly-agent-toolchain-online-${DATE_SUFFIX}.tgz"
ARCHIVE_PATH="$OUTPUT_DIR/$ARCHIVE_NAME"

echo "[package] 项目根目录: $ROOT"
echo "[package] 输出路径: $ARCHIVE_PATH"

# ---- 构建包含文件列表 ----
INCLUDE_FILES=(
  # 部署工具链核心
  "deploy/toolchain"
  # 环境与依赖
  "environment.yml"
  "backend/requirements.txt"
  # 后端源码
  "backend/app"
  "backend/tests"
  # 前端源码
  "frontend/package.json"
  "frontend/package-lock.json"
  "frontend/vite.config.js"
  "frontend/index.html"
  "frontend/src"
  "frontend/public"
  # 部署配置
  "ecosystem.config.js"
  # 文档
  "doc/poly-agent-toolchain-deployment-pack.md"
  "README.md"
)

# ---- 构建排除模式 ----
EXCLUDE_PATTERNS=(
  "*.env"
  "*.env.*"
  ".env"
  ".env.*"
  ".git"
  "node_modules"
  "__pycache__"
  "*.pyc"
  "*.pyo"
  ".pytest_cache"
  ".runtime"
  "dist"
  "refer"
  "docs"
  ".gitignore"
  "*.tgz"
  "*.tar.gz"
)

# ---- 检查必要文件是否存在 ----
MISSING_FILES=()
for pattern in "${INCLUDE_FILES[@]}"; do
  if [[ ! -e "$ROOT/$pattern" ]]; then
    MISSING_FILES+=("$pattern")
  fi
done

if [[ ${#MISSING_FILES[@]} -gt 0 ]]; then
  echo "[package] 警告：以下文件/目录不存在，打包时将跳过:"
  for f in "${MISSING_FILES[@]}"; do
    echo "  - $f"
  done
fi

# ---- 创建临时目录 ----
TEMP_DIR="$(mktemp -d)"
PACKAGE_DIR="$TEMP_DIR/poly-agent-toolchain"
mkdir -p "$PACKAGE_DIR"

echo "[package] 复制文件到临时目录..."

for pattern in "${INCLUDE_FILES[@]}"; do
  if [[ -e "$ROOT/$pattern" ]]; then
    # 确保目标父目录存在
    TARGET_PARENT="$(dirname "$PACKAGE_DIR/$pattern")"
    mkdir -p "$TARGET_PARENT"
    cp -r "$ROOT/$pattern" "$PACKAGE_DIR/$pattern"
  fi
done

# ---- 清理不应打包的文件 ----
echo "[package] 清理临时文件..."
find "$PACKAGE_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PACKAGE_DIR" -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find "$PACKAGE_DIR" -type d -name "node_modules" -exec rm -rf {} + 2>/dev/null || true
find "$PACKAGE_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
find "$PACKAGE_DIR" -type f -name ".env" -delete 2>/dev/null || true
find "$PACKAGE_DIR" -type f -name ".env.*" -not -name ".env.template" -delete 2>/dev/null || true

# ---- 生成 VERSION 文件 ----
cat > "$PACKAGE_DIR/deploy/toolchain/VERSION" <<EOF
POLY_AGENT_TOOLCHAIN_VERSION=0.1.0
PACKAGE_DATE=$DATE_SUFFIX
PACKAGE_TYPE=online
EOF

# ---- 创建归档 ----
echo "[package] 创建归档..."
cd "$TEMP_DIR"
tar czf "$ARCHIVE_PATH" "poly-agent-toolchain"

# ---- 清理 ----
rm -rf "$TEMP_DIR"

# ---- 验证归档 ----
ARCHIVE_SIZE=$(du -h "$ARCHIVE_PATH" | cut -f1)
echo ""
echo "[package] ========================================"
echo "[package]  打包完成"
echo "[package] ========================================"
echo "[package]  文件: $ARCHIVE_PATH"
echo "[package]  大小: $ARCHIVE_SIZE"
echo ""
echo "[package]  内容预览:"
tar tzf "$ARCHIVE_PATH" | head -30
echo "  ..."
TOTAL_FILES=$(tar tzf "$ARCHIVE_PATH" | wc -l)
echo "  总计 $TOTAL_FILES 个文件"
echo ""
echo "[package]  安装命令:"
echo "  tar xzf $ARCHIVE_NAME"
echo "  bash poly-agent-toolchain/deploy/toolchain/scripts/bootstrap_all.sh --root /path/to/Poly_Agent --mode core"
echo "[package] ========================================"
