#!/usr/bin/env bash
# Start the local development stack in the foreground: PostgreSQL (docker compose), migrations,
# the API (uvicorn, :8000), the worker (python -m app.worker) and the frontend dev server (vite, :5173).
# Ctrl+C stops the API, worker and frontend (the worker must exit 0) and removes the PID file.
# The database container is left running; stop it with `scripts/stop.sh --db`.
#
# Usage: scripts/dev.sh
# Config: environment > .env > .env.example (parsed line by line, never sourced; see lib/stack.sh).
#         Run scripts/setup.sh once first. PID file: .localetl/dev.pids; logs: .localetl/logs/.
set -euo pipefail
# shellcheck source=lib/stack.sh
. "$(dirname "$0")/lib/stack.sh"
cd "$STACK_ROOT"

load_env
API_PORT="$API_PORT_DEFAULT"
WEB_PORT="$WEB_PORT_DEFAULT"

PY="$(backend_python)" || die "backend/.venv not found. Run scripts/setup.sh first."
[ -d frontend/node_modules ] || die "frontend/node_modules not found. Run scripts/setup.sh first."

# LOCALETL_DATA_DIR defaults to ./data relative to the repo root (architecture section 4); the API and
# worker run from backend/, so make it absolute.
case "${LOCALETL_DATA_DIR:-./data}" in
  /*) DATA_DIR="${LOCALETL_DATA_DIR}" ;;
  *) DATA_DIR="$STACK_ROOT/${LOCALETL_DATA_DIR#./}" ;;
esac
export LOCALETL_DATA_DIR="$DATA_DIR"
mkdir -p "$DATA_DIR/sources" "$DATA_DIR/tmp"

# Required variables: names and hosts only; passwords are masked.
for v in DATABASE_URL LOCALETL_DATA_DIR LOCALETL_CORS_ORIGINS LOCALETL_CHUNK_ROWS \
         WORKER_POLL_INTERVAL_SECONDS WORKER_HEARTBEAT_SECONDS WORKER_STALE_AFTER_SECONDS VITE_API_URL; do
  [ -n "${!v:-}" ] || die "$v is not set (see .env.example)"
done
say "Configuration (names and hosts only):"
say "  DATABASE_URL         = $(mask_url "$DATABASE_URL")"
say "  LOCALETL_DATA_DIR    = $LOCALETL_DATA_DIR"
say "  LOCALETL_CORS_ORIGINS= $LOCALETL_CORS_ORIGINS"
say "  VITE_API_URL         = $VITE_API_URL"
say "  database host       = $(url_host "$DATABASE_URL")"

# Refuse to start twice.
LIVE="$(live_recorded)"
if [ -n "$LIVE" ]; then
  say "$LIVE" | sed 's/^/  running: pid /' >&2
  die "the dev stack is already running (see $PID_FILE). Stop it with scripts/stop.sh."
fi
rm -f "$PID_FILE"
for p in "$API_PORT" "$WEB_PORT"; do
  if port_in_use "$p"; then die "port $p is already in use; free it or stop what is using it."; fi
done

say; say "== Database"
scripts/dev-up.sh
say; say "== Migrations (alembic upgrade head)"
(cd backend && "$PY" -m alembic upgrade head)

mkdir -p "$LOG_DIR"
API_PID="" WORKER_PID="" WEB_PID="" STOPPING=0

cleanup() {
  local rc=$? p
  trap - EXIT INT TERM
  if [ "$STOPPING" -eq 0 ]; then STOPPING=1; fi
  say; say "Stopping..."
  set +e
  for p in "$WEB_PID" "$API_PID" "$WORKER_PID"; do
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null && kill -TERM $(descendants "$p") "$p" 2>/dev/null
  done
  WRC=""
  if [ -n "$WORKER_PID" ]; then wait "$WORKER_PID" 2>/dev/null; WRC=$?; fi
  [ -n "$API_PID" ] && wait "$API_PID" 2>/dev/null
  [ -n "$WEB_PID" ] && wait "$WEB_PID" 2>/dev/null
  rm -f "$PID_FILE"
  if [ -n "$WRC" ]; then
    say "worker exited with $WRC"
    if [ "$WRC" -ne 0 ] && [ "$rc" -eq 0 ]; then rc=1; fi
  fi
  say "Stopped. The database is still running (scripts/stop.sh --db to stop it)."
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 0' INT TERM

pid_record "$$" launcher "dev.sh"

say; say "== Starting the stack"
# Job control gives each child its own process group, so a terminal Ctrl+C reaches only this script,
# which then sends each child a single SIGTERM (the worker exits 0 on SIGTERM).
set -m
(cd backend && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT") >"$LOG_DIR/api.log" 2>&1 &
API_PID=$!
pid_record "$API_PID" api "app.main:app"
(cd backend && exec "$PY" -m app.worker) >"$LOG_DIR/worker.log" 2>&1 &
WORKER_PID=$!
pid_record "$WORKER_PID" worker "app.worker"
(exec npm --prefix frontend run dev) >"$LOG_DIR/web.log" 2>&1 &
WEB_PID=$!
pid_record "$WEB_PID" web-npm "run dev"

wait_http() { # wait_http URL SECONDS PID NAME
  local deadline=$((SECONDS + $2))
  until curl -fsS -o /dev/null "$1" 2>/dev/null; do
    kill -0 "$3" 2>/dev/null || { tail -n 20 "$LOG_DIR/$4.log" >&2; die "$4 exited during startup (log: $LOG_DIR/$4.log)"; }
    (( SECONDS < deadline )) || { tail -n 20 "$LOG_DIR/$4.log" >&2; die "timed out waiting for $4"; }
    sleep 0.5
  done
}
wait_http "http://127.0.0.1:$API_PORT/api/v1/health" 60 "$API_PID" api
wait_http "http://127.0.0.1:$WEB_PORT/" 60 "$WEB_PID" web
kill -0 "$WORKER_PID" 2>/dev/null || { tail -n 20 "$LOG_DIR/worker.log" >&2; die "worker exited during startup (log: $LOG_DIR/worker.log)"; }
# vite is a descendant of npm: record it too so scripts/stop.sh can verify and signal it.
for d in $(descendants "$WEB_PID"); do
  if ps -p "$d" -o command= 2>/dev/null | grep -q "vite"; then pid_record "$d" web-vite "vite"; fi
done

say
say "LocalETL is running:"
say "  Web UI : http://127.0.0.1:$WEB_PORT"
say "  API    : http://127.0.0.1:$API_PORT/api/v1"
say "Logs: $LOG_DIR/ (api.log, worker.log, web.log). Press Ctrl+C to stop."

# Exit (and clean up) as soon as any child dies.
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WORKER_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 1
done
say "A component exited unexpectedly; see the logs in $LOG_DIR/." >&2
exit 1
