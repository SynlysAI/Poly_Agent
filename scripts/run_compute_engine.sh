#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPUTE_ENGINE_DIR="$ROOT_DIR/refer/ChemOS2.0-master/ChemOS2.0-simulation"
RUNTIME_DIR="$ROOT_DIR/.runtime/compute_engine"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"
PG_RUNTIME_DIR="$RUNTIME_DIR/postgres"
PG_DATA_DIR="${COMPUTE_ENGINE_POSTGRES_DATA_DIR:-$PG_RUNTIME_DIR/data}"
PG_SOCKET_DIR="$PG_RUNTIME_DIR/socket"
ENV_NAME="${COMPUTE_ENGINE_CONDA_ENV:-compute_engine}"
STREAMLIT_PORT="${COMPUTE_ENGINE_STREAMLIT_PORT:-8501}"
STREAMLIT_HOST="${COMPUTE_ENGINE_STREAMLIT_HOST:-0.0.0.0}"
CHEMSPEED_PORT="${COMPUTE_ENGINE_CHEMSPEED_PORT:-65001}"
HPLC_PORT="${COMPUTE_ENGINE_HPLC_PORT:-65010}"
OPTICS_PORT="${COMPUTE_ENGINE_OPTICS_PORT:-65070}"
POSTGRES_CONTAINER="${COMPUTE_ENGINE_POSTGRES_CONTAINER:-compute-engine-postgres}"
POSTGRES_IMAGE="${COMPUTE_ENGINE_POSTGRES_IMAGE:-postgres:15}"
POSTGRES_HOST="${COMPUTE_ENGINE_POSTGRES_HOST:-127.0.0.1}"
POSTGRES_PORT="${COMPUTE_ENGINE_POSTGRES_PORT:-5432}"
POSTGRES_USER="${COMPUTE_ENGINE_POSTGRES_USER:-compute_engine}"
POSTGRES_PASSWORD="${COMPUTE_ENGINE_POSTGRES_PASSWORD:-compute_engine}"
POSTGRES_DB="${COMPUTE_ENGINE_POSTGRES_DB:-compute_engine}"
POSTGRES_BIN_DIR="${COMPUTE_ENGINE_POSTGRES_BIN_DIR:-}"

mkdir -p "$LOG_DIR" "$PID_DIR" "$PG_RUNTIME_DIR" "$PG_SOCKET_DIR"

export COMPUTE_ENGINE_POSTGRES_DB="$POSTGRES_DB"
export COMPUTE_ENGINE_POSTGRES_USER="$POSTGRES_USER"
export COMPUTE_ENGINE_POSTGRES_PASSWORD="$POSTGRES_PASSWORD"

detect_postgres_bin_dir() {
  local candidate=""
  local conda_base=""

  if [[ -n "$POSTGRES_BIN_DIR" && -x "$POSTGRES_BIN_DIR/postgres" ]]; then
    echo "$POSTGRES_BIN_DIR"
    return 0
  fi

  if ! command -v conda >/dev/null 2>&1; then
    return 1
  fi

  conda_base="$(conda info --base 2>/dev/null || true)"
  if [[ -z "$conda_base" ]]; then
    return 1
  fi

  for candidate in "$conda_base/bin" $(find "$conda_base/pkgs" -maxdepth 3 -type f -name postgres -printf '%h\n' 2>/dev/null | sort -u); do
    if [[ -x "$candidate/postgres" && -x "$candidate/pg_ctl" && -x "$candidate/initdb" && -x "$candidate/psql" ]]; then
      echo "$candidate"
      return 0
    fi
  done

  return 1
}

POSTGRES_BIN_DIR="$(detect_postgres_bin_dir || true)"
POSTGRES_BIN="${POSTGRES_BIN_DIR:+$POSTGRES_BIN_DIR/postgres}"
PG_CTL_BIN="${POSTGRES_BIN_DIR:+$POSTGRES_BIN_DIR/pg_ctl}"
INITDB_BIN="${POSTGRES_BIN_DIR:+$POSTGRES_BIN_DIR/initdb}"
PSQL_BIN="${POSTGRES_BIN_DIR:+$POSTGRES_BIN_DIR/psql}"
POSTGRES_LIB_DIR=""
CONDA_BASE_LIB_DIR=""
CONDA_PKG_LIB_PATHS=()
POSTGRES_SHARE_DIR=""
POSTGRES_VERSION=""

if [[ -n "$POSTGRES_BIN_DIR" ]]; then
  POSTGRES_LIB_DIR="$(cd "$POSTGRES_BIN_DIR/../lib" 2>/dev/null && pwd || true)"
  POSTGRES_VERSION="$(basename "$(cd "$POSTGRES_BIN_DIR/.." && pwd)" | sed -E 's/^postgresql-([0-9]+\.[0-9]+).*/\1/')"
fi

if command -v conda >/dev/null 2>&1; then
  CONDA_BASE_LIB_DIR="$(conda info --base 2>/dev/null || true)"
  CONDA_BASE_LIB_DIR="${CONDA_BASE_LIB_DIR:+$CONDA_BASE_LIB_DIR/lib}"
fi

if command -v conda >/dev/null 2>&1; then
  while IFS= read -r path; do
    CONDA_PKG_LIB_PATHS+=("$path")
  done < <(find "$(conda info --base 2>/dev/null)/pkgs" -maxdepth 2 -type d -name lib 2>/dev/null | sort -u)

  if [[ -n "$POSTGRES_VERSION" ]]; then
    POSTGRES_SHARE_DIR="$(
      find "$(conda info --base 2>/dev/null)/pkgs" -maxdepth 3 -path "*/libpq-${POSTGRES_VERSION}-*/share/postgres.bki" -printf '%h\n' 2>/dev/null | sort -u | head -n 1
    )"
  fi
  if [[ -z "$POSTGRES_SHARE_DIR" ]]; then
    POSTGRES_SHARE_DIR="$(
      find "$(conda info --base 2>/dev/null)/pkgs" -maxdepth 3 -path '*/share/postgres.bki' -printf '%h\n' 2>/dev/null | sort -u | head -n 1
    )"
  fi
fi

postgres_with_runtime() {
  local ld_parts=()
  local path=""

  if [[ -n "$POSTGRES_LIB_DIR" ]]; then
    ld_parts+=("$POSTGRES_LIB_DIR")
  fi
  for path in "${CONDA_PKG_LIB_PATHS[@]}"; do
    ld_parts+=("$path")
  done
  if [[ -n "$CONDA_BASE_LIB_DIR" ]]; then
    ld_parts+=("$CONDA_BASE_LIB_DIR")
  fi
  if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    ld_parts+=("$LD_LIBRARY_PATH")
  fi

  LD_LIBRARY_PATH="$(IFS=:; echo "${ld_parts[*]}")" "$@"
}

usage() {
  cat <<'USAGE'
Usage: scripts/run_compute_engine.sh [command]

Commands:
  postgres    Start PostgreSQL for ComputeEngine demo data. Prefer local Conda binaries, fallback to Docker.
  gui          Start only the ComputeEngine Streamlit GUI.
  base         Start HPLC, Chemspeed, Optics simulators, then Streamlit GUI.
  status       Show status of PostgreSQL and ComputeEngine service processes.
  stop         Stop ComputeEngine services tracked by PID files, then stop local PostgreSQL.
  check        Check installed imports in the compute_engine Conda environment.

Default command: base

Environment:
  COMPUTE_ENGINE_CONDA_ENV       Conda environment name. Default: compute_engine
  COMPUTE_ENGINE_STREAMLIT_HOST  Streamlit bind host. Default: 0.0.0.0
  COMPUTE_ENGINE_STREAMLIT_PORT  Streamlit port. Default: 8501
  COMPUTE_ENGINE_POSTGRES_HOST   PostgreSQL host. Default: 127.0.0.1
  COMPUTE_ENGINE_POSTGRES_PORT   PostgreSQL host port. Default: 5432
  COMPUTE_ENGINE_POSTGRES_DATA_DIR PostgreSQL data dir for local mode. Default: .runtime/compute_engine/postgres/data
  COMPUTE_ENGINE_POSTGRES_BIN_DIR  PostgreSQL bin dir override for local mode.
USAGE
}

run_in_env() {
  PYTHONNOUSERSITE=1 conda run -n "$ENV_NAME" "$@"
}

check_env() {
  run_in_env python -c "import sila2, streamlit, sqlalchemy, psycopg2, numpy, pandas; print('core imports ok')"
  (
    cd "$COMPUTE_ENGINE_DIR/sila-hplc"
    run_in_env python -c "import silahplc; print('silahplc ok')"
  )
  (
    cd "$COMPUTE_ENGINE_DIR/sila-chemspeed"
    run_in_env python -c "import chmspd_sila2_pkg; print('chmspd_sila2_pkg ok')"
  )
  (
    cd "$COMPUTE_ENGINE_DIR/sila-optics"
    run_in_env python -c "import SilaOpticsTable; print('SilaOpticsTable ok')"
  )
  echo "Streamlit: $(run_in_env streamlit --version)"
}

start_bg() {
  local name="$1"
  local workdir="$2"
  shift 2
  local logfile="$LOG_DIR/$name.log"
  local cmdline=("$@")
  (
    cd "$workdir"
    exec env PYTHONNOUSERSITE=1 conda run -n "$ENV_NAME" "${cmdline[@]}"
  ) >"$logfile" 2>&1 &
  local pid=$!
  echo "$pid" >"$PID_DIR/$name.pid"
  echo "started $name pid=$pid log=$logfile"
}

cleanup() {
  local pids
  pids="$(jobs -pr || true)"
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
  fi
}

pid_is_running() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  kill -0 "$pid" 2>/dev/null
}

pid_on_tcp_port() {
  local port="$1"
  ss -ltnp 2>/dev/null | awk -v port=":$port" '$4 ~ port"$" { if (match($0, /pid=[0-9]+/)) { print substr($0, RSTART+4, RLENGTH-4); exit } }'
}

stop_named_service() {
  local name="$1"
  local port="$2"
  local pidfile="$PID_DIR/$name.pid"
  local pid=""
  local attempt=""

  pid="$(pid_on_tcp_port "$port" || true)"
  if [[ -n "$pid" ]] && pid_is_running "$pid"; then
    kill "$pid" 2>/dev/null || true
    for attempt in 1 2 3 4 5; do
      sleep 1
      pid="$(pid_on_tcp_port "$port" || true)"
      if [[ -z "$pid" ]]; then
        break
      fi
      if pid_is_running "$pid"; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    done
    rm -f "$pidfile"
    if [[ -z "$(pid_on_tcp_port "$port" || true)" ]]; then
      echo "$name: stopped port=$port"
    else
      echo "$name: stop requested but port still busy=$port"
    fi
    return 0
  fi

  if [[ -f "$pidfile" ]]; then
    rm -f "$pidfile"
    echo "$name: stale pidfile removed"
    return 0
  fi

  echo "$name: not running"
}

status_named_service() {
  local name="$1"
  local port="$2"
  local pidfile="$PID_DIR/$name.pid"
  local pid=""

  pid="$(pid_on_tcp_port "$port" || true)"
  if [[ -n "$pid" ]] && pid_is_running "$pid"; then
    echo "$name: running pid=$pid port=$port log=$LOG_DIR/$name.log"
    return 0
  fi

  if [[ -f "$pidfile" ]]; then
    echo "$name: stale pidfile pid=$(cat "$pidfile" 2>/dev/null || true)"
    return 0
  fi

  echo "$name: not running"
}

postgres_accepting_connections() {
  if [[ -z "$PSQL_BIN" ]]; then
    return 1
  fi

  PGPASSWORD="$POSTGRES_PASSWORD" \
    postgres_with_runtime "$PSQL_BIN" \
    -h "$POSTGRES_HOST" \
    -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" \
    -d postgres \
    -tAc "SELECT 1" >/dev/null 2>&1
}

wait_for_postgres() {
  local attempt
  for attempt in $(seq 1 30); do
    if postgres_accepting_connections; then
      return 0
    fi
    sleep 1
  done

  echo "PostgreSQL did not become ready on $POSTGRES_HOST:$POSTGRES_PORT" >&2
  return 1
}

ensure_postgres_database() {
  local exists

  exists="$(
    PGPASSWORD="$POSTGRES_PASSWORD" \
      postgres_with_runtime "$PSQL_BIN" \
      -h "$POSTGRES_HOST" \
      -p "$POSTGRES_PORT" \
      -U "$POSTGRES_USER" \
      -d postgres \
      -tAc "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'"
  )"

  if [[ "$exists" != "1" ]]; then
    PGPASSWORD="$POSTGRES_PASSWORD" \
      postgres_with_runtime "$PSQL_BIN" \
      -h "$POSTGRES_HOST" \
      -p "$POSTGRES_PORT" \
      -U "$POSTGRES_USER" \
      -d postgres \
      -c "CREATE DATABASE \"$POSTGRES_DB\";" >/dev/null
  fi
}

init_local_postgres_cluster() {
  local pwfile

  if [[ -f "$PG_DATA_DIR/PG_VERSION" ]]; then
    return 0
  fi

  if [[ -d "$PG_DATA_DIR" ]] && [[ -z "$(find "$PG_DATA_DIR" -mindepth 1 -maxdepth 1 2>/dev/null)" ]]; then
    rm -rf "$PG_DATA_DIR"
  fi

  if [[ -z "$INITDB_BIN" ]]; then
    echo "Local PostgreSQL binaries not found; cannot initialize local database cluster." >&2
    return 1
  fi
  if [[ -z "$POSTGRES_SHARE_DIR" ]]; then
    echo "PostgreSQL share directory with postgres.bki was not found." >&2
    return 1
  fi

  rm -rf "$PG_DATA_DIR"
  mkdir -p "$PG_DATA_DIR"
  pwfile="$(mktemp)"
  printf '%s\n' "$POSTGRES_PASSWORD" >"$pwfile"

  postgres_with_runtime "$INITDB_BIN" \
    -D "$PG_DATA_DIR" \
    -L "$POSTGRES_SHARE_DIR" \
    -U "$POSTGRES_USER" \
    --pwfile="$pwfile" \
    --auth-host=scram-sha-256 \
    --auth-local=trust >/dev/null

  rm -f "$pwfile"
}

start_local_postgres() {
  if postgres_accepting_connections; then
    ensure_postgres_database
    echo "PostgreSQL already available at $POSTGRES_HOST:$POSTGRES_PORT"
    return 0
  fi

  if [[ -z "$POSTGRES_BIN" || -z "$PG_CTL_BIN" || -z "$INITDB_BIN" || -z "$PSQL_BIN" ]]; then
    return 1
  fi

  if ! init_local_postgres_cluster; then
    return 1
  fi

  if ! postgres_with_runtime "$PG_CTL_BIN" \
    -D "$PG_DATA_DIR" \
    -l "$LOG_DIR/postgres.log" \
    -o "-h $POSTGRES_HOST -p $POSTGRES_PORT -k $PG_SOCKET_DIR" \
    start >/dev/null; then
    return 1
  fi

  wait_for_postgres
  ensure_postgres_database
  echo "PostgreSQL available at $POSTGRES_HOST:$POSTGRES_PORT database=$POSTGRES_DB user=$POSTGRES_USER"
}

ensure_postgres() {
  if postgres_accepting_connections; then
    ensure_postgres_database
    return 0
  fi

  if start_local_postgres; then
    return 0
  fi

  start_postgres
}

stop_postgres() {
  if [[ -n "$PG_CTL_BIN" && -f "$PG_DATA_DIR/PG_VERSION" ]]; then
    if postgres_with_runtime "$PG_CTL_BIN" -D "$PG_DATA_DIR" status >/dev/null 2>&1; then
      postgres_with_runtime "$PG_CTL_BIN" -D "$PG_DATA_DIR" stop -m fast >/dev/null
      echo "postgres: stopped local cluster"
      return 0
    fi
  fi

  if command -v docker >/dev/null 2>&1; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -Fx "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
      docker stop "$POSTGRES_CONTAINER" >/dev/null
      echo "postgres: stopped docker container $POSTGRES_CONTAINER"
      return 0
    fi
  fi

  echo "postgres: not running"
}

status_postgres() {
  if postgres_accepting_connections; then
    echo "postgres: running host=$POSTGRES_HOST port=$POSTGRES_PORT db=$POSTGRES_DB user=$POSTGRES_USER"
    return 0
  fi

  if [[ -n "$PG_CTL_BIN" && -f "$PG_DATA_DIR/PG_VERSION" ]]; then
    if postgres_with_runtime "$PG_CTL_BIN" -D "$PG_DATA_DIR" status >/dev/null 2>&1; then
      echo "postgres: local cluster process exists but readiness check failed"
      return 0
    fi
  fi

  if command -v docker >/dev/null 2>&1; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -Fx "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
      echo "postgres: docker container running but readiness check failed"
      return 0
    fi
  fi

  echo "postgres: stopped"
}

status_services() {
  echo "ComputeEngine runtime: $RUNTIME_DIR"
  status_postgres
  status_named_service "hplc" "$HPLC_PORT"
  status_named_service "chemspeed" "$CHEMSPEED_PORT"
  status_named_service "optics" "$OPTICS_PORT"
  status_named_service "streamlit" "$STREAMLIT_PORT"
}

stop_services() {
  stop_named_service "streamlit" "$STREAMLIT_PORT"
  stop_named_service "optics" "$OPTICS_PORT"
  stop_named_service "chemspeed" "$CHEMSPEED_PORT"
  stop_named_service "hplc" "$HPLC_PORT"
  stop_postgres
}

start_gui() {
  start_bg "streamlit" "$COMPUTE_ENGINE_DIR/streamlit" streamlit run Hello.py --server.address "$STREAMLIT_HOST" --server.port "$STREAMLIT_PORT"
}

start_base_servers() {
  start_bg "hplc" "$COMPUTE_ENGINE_DIR/sila-hplc" python start_server.py
  start_bg "chemspeed" "$COMPUTE_ENGINE_DIR/sila-chemspeed" python start_server.py
  start_bg "optics" "$COMPUTE_ENGINE_DIR/sila-optics" python start_server.py
}

start_postgres() {
  if start_local_postgres; then
    return 0
  fi

  if ! command -v docker >/dev/null 2>&1; then
    echo "docker is not installed, and local PostgreSQL binaries were not found; provide PostgreSQL on $POSTGRES_HOST:$POSTGRES_PORT." >&2
    exit 1
  fi

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -Fx "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
    echo "PostgreSQL container already running: $POSTGRES_CONTAINER"
    return
  fi

  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -Fx "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
    docker start "$POSTGRES_CONTAINER" >/dev/null
  else
    docker run -d \
      --name "$POSTGRES_CONTAINER" \
      -e POSTGRES_USER="$POSTGRES_USER" \
      -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
      -e POSTGRES_DB="$POSTGRES_DB" \
      -p "$POSTGRES_HOST:$POSTGRES_PORT:5432" \
      "$POSTGRES_IMAGE" >/dev/null
  fi

  echo "PostgreSQL available at $POSTGRES_HOST:$POSTGRES_PORT database=$POSTGRES_DB user=$POSTGRES_USER"
  echo "ComputeEngine source files still contain dblogin.py credentials; align them with this database before using DB-backed pages."
}

command="${1:-base}"
case "$command" in
  -h|--help|help)
    usage
    ;;
  check)
    check_env
    ;;
  status)
    status_services
    ;;
  stop)
    stop_services
    ;;
  postgres)
    start_postgres
    ;;
  gui)
    trap cleanup EXIT INT TERM
    ensure_postgres
    start_gui
    echo "ComputeEngine GUI: http://$STREAMLIT_HOST:$STREAMLIT_PORT"
    echo "Press Ctrl+C to stop."
    wait
    ;;
  base)
    trap cleanup EXIT INT TERM
    echo "Starting ComputeEngine base demo."
    ensure_postgres
    start_base_servers
    start_gui
    echo "ComputeEngine GUI: http://$STREAMLIT_HOST:$STREAMLIT_PORT"
    echo "Press Ctrl+C to stop."
    wait
    ;;
  *)
    usage
    exit 2
    ;;
esac
