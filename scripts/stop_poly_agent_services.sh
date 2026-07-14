#!/usr/bin/env bash
set -euo pipefail

ROOT="${POLY_AGENT_ROOT:-/home/fangyikai/code/Poly_Agent}"
BACKEND_SESSION="${POLY_AGENT_BACKEND_SESSION:-poly_agent_backend}"
FRONTEND_SESSION="${POLY_AGENT_FRONTEND_SESSION:-poly_agent_frontend}"
WORKER_SESSION="${POLY_AGENT_WORKER_SESSION:-poly_agent_worker}"
PORTS=("${POLY_AGENT_FRONTEND_PORT:-5200}" "${POLY_AGENT_BACKEND_PORT:-5201}" 5100 5101 5174 8003)

pid_matches_root() {
  local pid="$1"
  local cmdline=""
  local cwd=""

  if [[ -r "/proc/$pid/cmdline" ]]; then
    cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  fi
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  [[ "$cmdline" == *"$ROOT"* || "$cwd" == "$ROOT"* ]]
}

kill_pid() {
  local pid="$1"
  if kill "$pid" 2>/dev/null; then
    sleep 0.5
  fi
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
}

kill_repo_port() {
  local port="$1"
  local pid=""
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    if pid_matches_root "$pid"; then
      kill_pid "$pid"
    fi
  done < <(lsof -ti "tcp:${port}" 2>/dev/null || true)
}

kill_repo_pattern() {
  local pattern="$1"
  local pid=""
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    if pid_matches_root "$pid"; then
      kill_pid "$pid"
    fi
  done < <(pgrep -f "$pattern" 2>/dev/null || true)
}

tmux kill-session -t "$BACKEND_SESSION" 2>/dev/null || true
tmux kill-session -t "$FRONTEND_SESSION" 2>/dev/null || true
tmux kill-session -t "$WORKER_SESSION" 2>/dev/null || true

for session in "$BACKEND_SESSION" "$FRONTEND_SESSION" "$WORKER_SESSION"; do
  pid_file="/tmp/${session}.pid"
  if [[ -r "$pid_file" ]]; then
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && pid_matches_root "$pid"; then
      kill_pid "$pid"
    fi
    rm -f "$pid_file"
  fi
done

for port in "${PORTS[@]}"; do
  kill_repo_port "$port"
done

kill_repo_pattern "frontend/node_modules/.bin/vite"
kill_repo_pattern "app.workers.computation_worker"

echo "Stopped Poly_Agent services for $ROOT"
