#!/usr/bin/env bash
set -euo pipefail

ROOT="${POLY_AGENT_ROOT:-/home/fangyikai/code/Poly_Agent}"
ENV_NAME="${POLY_AGENT_CONDA_ENV:-poly_agent}"
FRONTEND_PORT="${POLY_AGENT_FRONTEND_PORT:-5100}"
BACKEND_PORT="${POLY_AGENT_BACKEND_PORT:-5101}"
BACKEND_LOG="${POLY_AGENT_BACKEND_LOG:-/tmp/poly_agent_backend.log}"
FRONTEND_LOG="${POLY_AGENT_FRONTEND_LOG:-/tmp/poly_agent_frontend.log}"
BACKEND_SESSION="${POLY_AGENT_BACKEND_SESSION:-poly_agent_backend}"
FRONTEND_SESSION="${POLY_AGENT_FRONTEND_SESSION:-poly_agent_frontend}"
CONDA_BASE="${POLY_AGENT_CONDA_BASE:-$(conda info --base 2>/dev/null)}"
ENV_BIN_DIR="${CONDA_BASE}/envs/${ENV_NAME}/bin"
PYTHON_BIN="${POLY_AGENT_PYTHON_BIN:-$ENV_BIN_DIR/python}"
NPM_BIN="${POLY_AGENT_NPM_BIN:-$ENV_BIN_DIR/npm}"

if [[ ! -d "$ROOT/frontend" || ! -f "$ROOT/backend/app/main.py" ]]; then
  echo "Poly_Agent root not found or incomplete: $ROOT" >&2
  exit 1
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "conda command not found" >&2
  exit 1
fi

if [[ -z "$CONDA_BASE" || ! -x "$PYTHON_BIN" || ! -x "$NPM_BIN" ]]; then
  echo "Conda environment not found: $ENV_NAME" >&2
  echo "Run: $ROOT/scripts/setup_poly_agent_env.sh" >&2
  exit 1
fi

bash "$ROOT/scripts/stop_poly_agent_services.sh"

tmux new-session -d -s "$BACKEND_SESSION" "bash -lc \"
  cd '$ROOT/backend'
  export PYTHONNOUSERSITE=1
  exec '$PYTHON_BIN' -m uvicorn app.main:app --reload --host 127.0.0.1 --port '$BACKEND_PORT' >'$BACKEND_LOG' 2>&1
\""

tmux new-session -d -s "$FRONTEND_SESSION" "bash -lc \"
  cd '$ROOT/frontend'
  export PATH='$ENV_BIN_DIR':\"\$PATH\"
  export VITE_DEV_API_PROXY_TARGET='http://127.0.0.1:$BACKEND_PORT'
  exec '$NPM_BIN' run dev -- --host 127.0.0.1 --port '$FRONTEND_PORT' >'$FRONTEND_LOG' 2>&1
\""

for _ in {1..30}; do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

for _ in {1..30}; do
  if curl -fsI "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" >/dev/null 2>&1; then
  echo "Backend failed to start. Log: $BACKEND_LOG" >&2
  tail -n 80 "$BACKEND_LOG" >&2 || true
  exit 1
fi

if ! curl -fsI "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
  echo "Frontend failed to start. Log: $FRONTEND_LOG" >&2
  tail -n 80 "$FRONTEND_LOG" >&2 || true
  exit 1
fi

echo "Frontend: http://127.0.0.1:${FRONTEND_PORT}/"
echo "Backend:  http://127.0.0.1:${BACKEND_PORT}/api/v1/health"
echo "Logs: $BACKEND_LOG $FRONTEND_LOG"
echo "tmux: $BACKEND_SESSION $FRONTEND_SESSION"
