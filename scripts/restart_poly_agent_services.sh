#!/usr/bin/env bash
set -euo pipefail

ROOT="${POLY_AGENT_ROOT:-/home/fangyikai/code/Poly_Agent}"
ENV_NAME="${POLY_AGENT_CONDA_ENV:-poly_agent}"
FRONTEND_PORT="${POLY_AGENT_FRONTEND_PORT:-5200}"
BACKEND_PORT="${POLY_AGENT_BACKEND_PORT:-5201}"
BIND_HOST="${POLY_AGENT_BIND_HOST:-0.0.0.0}"
BACKEND_LOG="${POLY_AGENT_BACKEND_LOG:-/tmp/poly_agent_backend.log}"
FRONTEND_LOG="${POLY_AGENT_FRONTEND_LOG:-/tmp/poly_agent_frontend.log}"
WORKER_LOG="${POLY_AGENT_WORKER_LOG:-/tmp/poly_agent_worker.log}"
ASSISTANT_WORKER_LOG="${POLY_AGENT_ASSISTANT_WORKER_LOG:-/tmp/poly_agent_assistant_worker.log}"
BACKEND_SESSION="${POLY_AGENT_BACKEND_SESSION:-poly_agent_backend}"
FRONTEND_SESSION="${POLY_AGENT_FRONTEND_SESSION:-poly_agent_frontend}"
WORKER_SESSION="${POLY_AGENT_WORKER_SESSION:-poly_agent_worker}"
ASSISTANT_WORKER_SESSION="${POLY_AGENT_ASSISTANT_WORKER_SESSION:-poly_agent_assistant_worker}"
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

start_service() {
  local session="$1"
  local command="$2"
  local pid_file="/tmp/${session}.pid"
  if command -v tmux >/dev/null 2>&1 && tmux new-session -d -s "$session" "bash -lc \"$command\"" 2>/dev/null; then
    return 0
  fi
  nohup bash -lc "$command" >/dev/null 2>&1 &
  echo "$!" > "$pid_file"
}

BACKEND_CMD="
  cd '$ROOT/backend'
  export PYTHONNOUSERSITE=1
  export PATH='$ENV_BIN_DIR':\"\$PATH\"
  exec '$PYTHON_BIN' -m uvicorn app.main:app --reload --host '$BIND_HOST' --port '$BACKEND_PORT' >'$BACKEND_LOG' 2>&1
"

WORKER_CMD="
  cd '$ROOT/backend'
  export PYTHONNOUSERSITE=1
  export PATH='$ENV_BIN_DIR':\"\$PATH\"
  exec '$PYTHON_BIN' -m app.workers.computation_worker --worker-id worker-local-real-1 >'$WORKER_LOG' 2>&1
"

ASSISTANT_WORKER_CMD="
  cd '$ROOT/backend'
  export PYTHONNOUSERSITE=1
  export PATH='$ENV_BIN_DIR':\"\$PATH\"
  exec '$PYTHON_BIN' -m app.workers.assistant_run_worker --worker-id assistant-local-1 >'$ASSISTANT_WORKER_LOG' 2>&1
"

FRONTEND_CMD="
  cd '$ROOT/frontend'
  export PATH='$ENV_BIN_DIR':\"\$PATH\"
  export VITE_DEV_API_PROXY_TARGET='http://127.0.0.1:$BACKEND_PORT'
  exec '$NPM_BIN' run dev -- --host '$BIND_HOST' --port '$FRONTEND_PORT' >'$FRONTEND_LOG' 2>&1
"

start_service "$BACKEND_SESSION" "$BACKEND_CMD"
start_service "$WORKER_SESSION" "$WORKER_CMD"
start_service "$ASSISTANT_WORKER_SESSION" "$ASSISTANT_WORKER_CMD"
start_service "$FRONTEND_SESSION" "$FRONTEND_CMD"

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
echo "External: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${FRONTEND_PORT}/"
echo "Logs: $BACKEND_LOG $FRONTEND_LOG $WORKER_LOG $ASSISTANT_WORKER_LOG"
echo "Sessions/PIDs: $BACKEND_SESSION $FRONTEND_SESSION $WORKER_SESSION $ASSISTANT_WORKER_SESSION"
