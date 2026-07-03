#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="poly_agent"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda command not found" >&2
  exit 1
fi

if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Updating conda environment: $ENV_NAME"
  conda env update -f "$ROOT/environment.yml" --prune
else
  echo "Creating conda environment: $ENV_NAME"
  conda env create -f "$ROOT/environment.yml"
fi

echo "Installing frontend dependencies inside $ENV_NAME"
PYTHONNOUSERSITE=1 conda run -n "$ENV_NAME" npm install --prefix "$ROOT/frontend"

echo "Verifying environment"
PYTHONNOUSERSITE=1 conda run -n "$ENV_NAME" python --version
PYTHONNOUSERSITE=1 conda run -n "$ENV_NAME" node --version
PYTHONNOUSERSITE=1 conda run -n "$ENV_NAME" npm --version

echo "Conda environment ready: $ENV_NAME"
