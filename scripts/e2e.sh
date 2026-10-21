#!/usr/bin/env bash
# Full-stack launcher for the Playwright E2E demo (QA-08).
#
# Starts, on a THROWAWAY database and data directory (never the dev DB contents):
#   API    uvicorn app.main:app           127.0.0.1:$E2E_API_PORT  (default 18000)
#   worker python -m app.worker           (the real worker)
#   web    vite build + vite preview      127.0.0.1:$E2E_WEB_PORT  (default 15173)
# then runs the given command (default: the Playwright suite in tests/e2e), and always stops
# everything on exit. The worker must exit 0 on SIGTERM (WK-03) or the script fails.
#
# Usage:  scripts/e2e.sh [--stack-only] [-- command args...]
# Needs:  a running PostgreSQL whose role can CREATE DATABASE (docker compose up -d db),
#         the backend installed in $PYTHON, and `npm ci` done in frontend/ and tests/e2e/.
# Env:    PYTHON (default python), DATABASE_URL (server only is used; the database name is replaced),
#         E2E_API_PORT, E2E_WEB_PORT.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python}"
PORT="${POSTGRES_PORT:-5432}"
BASE_URL="${DATABASE_URL:-postgresql+psycopg://localetl:localetl@127.0.0.1:${PORT}/localetl}"
API_PORT="${E2E_API_PORT:-18000}"
WEB_PORT="${E2E_WEB_PORT:-15173}"
DB_NAME="localetl_e2e_$(date +%s)_$$"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/localetl-e2e.XXXXXX")"
STACK_ONLY=0
CMD=()

while [ $# -gt 0 ]; do
  case "$1" in
    --stack-only) STACK_ONLY=1 ;;
    --) shift; CMD=("$@"); break ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# Database URLs: same server and credentials, throwaway database name.
E2E_DB_URL="$("$PYTHON" - "$BASE_URL" "$DB_NAME" <<'PY'
import sys, sqlalchemy as sa
print(sa.engine.make_url(sys.argv[1]).set(database=sys.argv[2]).render_as_string(hide_password=False))
PY
)"

db_admin() { # db_admin CREATE|DROP
  "$PYTHON" - "$BASE_URL" "$DB_NAME" "$1" <<'PY'
import sys, sqlalchemy as sa
base, name, action = sys.argv[1:4]
eng = sa.create_engine(base, isolation_level="AUTOCOMMIT")
with eng.connect() as c:
    if action == "CREATE":
        c.execute(sa.text(f'CREATE DATABASE "{name}"'))
    else:
        c.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
PY
}

API_PID="" WORKER_PID="" WEB_PID="" WORKER_RC=0

stop() { # stop pid [signal]
  local pid="$1" sig="${2:-TERM}"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && kill -"$sig" "$pid" 2>/dev/null || true
}

cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  set +e
  if [ -n "$WORKER_PID" ] && kill -0 "$WORKER_PID" 2>/dev/null; then
    kill -TERM "$WORKER_PID"
    wait "$WORKER_PID"; WORKER_RC=$?
    echo "worker exited with $WORKER_RC after SIGTERM"
    [ "$WORKER_RC" -ne 0 ] && [ "$rc" -eq 0 ] && rc=1
  fi
  stop "$WEB_PID"; stop "$API_PID"
  [ -n "$WEB_PID" ] && wait "$WEB_PID" 2>/dev/null
  [ -n "$API_PID" ] && wait "$API_PID" 2>/dev/null
  db_admin DROP 2>/dev/null
  rm -rf "$WORK"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

wait_http() { # wait_http url seconds
  local deadline=$((SECONDS + $2))
  until curl -fsS -o /dev/null "$1" 2>/dev/null; do
    (( SECONDS < deadline )) || { echo "timed out waiting for $1" >&2; return 1; }
    sleep 0.5
  done
}

echo "e2e: database $DB_NAME, data dir $WORK/data"
mkdir -p "$WORK/data/sources" "$WORK/data/tmp" "$WORK/logs"
db_admin CREATE

export DATABASE_URL="$E2E_DB_URL"
export LOCALETL_DATA_DIR="$WORK/data"
export LOCALETL_CORS_ORIGINS="http://127.0.0.1:${WEB_PORT}"
export LOCALETL_CHUNK_ROWS="${LOCALETL_CHUNK_ROWS:-50000}"
export WORKER_POLL_INTERVAL_SECONDS="${WORKER_POLL_INTERVAL_SECONDS:-0.5}"
export WORKER_HEARTBEAT_SECONDS="${WORKER_HEARTBEAT_SECONDS:-2}"
export WORKER_STALE_AFTER_SECONDS="${WORKER_STALE_AFTER_SECONDS:-30}"

(cd "$ROOT/backend" && "$PYTHON" -m alembic upgrade head) >"$WORK/logs/migrate.log" 2>&1 \
  || { cat "$WORK/logs/migrate.log" >&2; exit 1; }

(cd "$ROOT/backend" && exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT") \
  >"$WORK/logs/api.log" 2>&1 &
API_PID=$!
(cd "$ROOT/backend" && exec "$PYTHON" -m app.worker) >"$WORK/logs/worker.log" 2>&1 &
WORKER_PID=$!

# The frontend bakes the API URL in at build time.
(cd "$ROOT/frontend" && VITE_API_URL="http://127.0.0.1:${API_PORT}/api/v1" \
  npx --no-install vite build --outDir "$WORK/web") >"$WORK/logs/web-build.log" 2>&1 \
  || { cat "$WORK/logs/web-build.log" >&2; exit 1; }
(cd "$ROOT/frontend" && exec npx --no-install vite preview --outDir "$WORK/web" \
  --host 127.0.0.1 --port "$WEB_PORT" --strictPort) >"$WORK/logs/web.log" 2>&1 &
WEB_PID=$!

wait_http "http://127.0.0.1:${API_PORT}/api/v1/health" 60 || { tail -n 30 "$WORK/logs/api.log" >&2; exit 1; }
wait_http "http://127.0.0.1:${WEB_PORT}/" 60 || { tail -n 30 "$WORK/logs/web.log" >&2; exit 1; }
kill -0 "$WORKER_PID" || { tail -n 30 "$WORK/logs/worker.log" >&2; exit 1; }
echo "e2e: stack up  api=http://127.0.0.1:${API_PORT}  web=http://127.0.0.1:${WEB_PORT}"

export E2E_API_URL="http://127.0.0.1:${API_PORT}/api/v1"
export E2E_WEB_URL="http://127.0.0.1:${WEB_PORT}"
export E2E_DATABASE_URL="$E2E_DB_URL"

if [ "$STACK_ONLY" -eq 1 ]; then
  echo "e2e: --stack-only; press Ctrl-C to stop"
  while :; do sleep 3600 & wait $!; done
fi

if [ ${#CMD[@]} -eq 0 ]; then
  CMD=(npm --prefix "$ROOT/tests/e2e" test)
fi
set +e
"${CMD[@]}"
RC=$?
set -e
echo "--- worker log (tail) ---"; tail -n 15 "$WORK/logs/worker.log" || true
exit "$RC"
