#!/usr/bin/env bash
# Run every check CI runs, in the same order (QA-04). CI calls this script, so local == CI.
#
# Usage:   scripts/test-all.sh [--skip-frontend] [--skip-db]
# Needs:   python (3.11) with `pip install -e 'backend[dev]'`, node + `npm --prefix frontend ci`,
#          and a reachable PostgreSQL for the DB suites. It never starts, stops or recreates the
#          database. Start it yourself: `POSTGRES_PORT=55432 scripts/dev-up.sh`.
# Env:     TEST_DATABASE_URL / DATABASE_URL  (default: 127.0.0.1:${POSTGRES_PORT:-5432})
#          PYTHON (default: python)          REDOCLY_VERSION (default 1.25.0)
# Exit:    0 only if every step passed; the summary names each failed step.
set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

SKIP_FRONTEND=0
SKIP_DB=0
for arg in "$@"; do
  case "$arg" in
    --skip-frontend) SKIP_FRONTEND=1 ;;
    --skip-db) SKIP_DB=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

PYTHON="${PYTHON:-python}"
REDOCLY_VERSION="${REDOCLY_VERSION:-1.25.0}"
PORT="${POSTGRES_PORT:-5432}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://localetl:localetl@127.0.0.1:${PORT}/localetl}"
export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+psycopg://localetl:localetl@127.0.0.1:${PORT}/localetl_test}"

FAILED=()
PASSED=()
SKIPPED=()

group() { if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::group::$1"; else echo; echo "=== $1"; fi; }
endgroup() { if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::endgroup::"; fi; }

# step <name> <command...>: run in $ROOT, record the result, keep going.
step() {
  local name="$1"; shift
  group "$name"
  if (cd "$ROOT" && "$@"); then
    PASSED+=("$name")
  else
    FAILED+=("$name")
    echo "FAILED: $name" >&2
  fi
  endgroup
}

skip() { SKIPPED+=("$1 ($2)"); echo "skipped: $1 ($2)"; }

# ----------------------------------------------------------------------------- preflight
if ! "$PYTHON" -c "import app, yaml, jsonschema, openapi_spec_validator" 2>/dev/null; then
  echo "python environment is not ready: run  $PYTHON -m pip install -e 'backend[dev]'" >&2
  exit 2
fi

db_ready() {
  "$PYTHON" - <<'PY'
import os, sys
import sqlalchemy as sa
try:
    for key in ("DATABASE_URL", "TEST_DATABASE_URL"):
        engine = sa.create_engine(os.environ[key], connect_args={"connect_timeout": 3})
        with engine.connect() as c:
            c.execute(sa.text("SELECT 1"))
        engine.dispose()
except Exception as exc:  # noqa: BLE001
    print(f"database not reachable: {exc.__class__.__name__}: {str(exc).splitlines()[0]}", file=sys.stderr)
    sys.exit(1)
PY
}

hygiene() {
  # REQ-64: no .env file (other than .env.example) and no uploaded data under version control.
  local bad
  bad="$(git ls-files | grep -E '^(\.env($|\.)|data/|uploads/)' | grep -vxF '.env.example' || true)"
  if [ -n "$bad" ]; then echo "tracked files that must never be committed:"; echo "$bad"; return 1; fi
  echo "ok: no tracked .env, data/ or uploads/ files"
}

types_drift() {
  # The committed generated types must equal a fresh generation from the contract.
  local tmp rc=0
  tmp="$(mktemp "${TMPDIR:-/tmp}/schema.XXXXXX.d.ts")"
  (cd frontend && npx --no-install openapi-typescript ../contracts/openapi.yaml -o "$tmp" >/dev/null) || rc=$?
  if [ "$rc" -eq 0 ]; then
    diff -u frontend/src/app/api/schema.d.ts "$tmp" || rc=$?
  fi
  rm -f "$tmp"
  [ "$rc" -eq 0 ] && echo "ok: schema.d.ts matches a fresh generation"
  return "$rc"
}

# ----------------------------------------------------------------------------------- steps
step "hygiene (no .env / data committed)" hygiene
step "contracts: check_contracts.py" "$PYTHON" contracts/tools/check_contracts.py .
step "contracts: redocly lint" npx --yes "@redocly/cli@${REDOCLY_VERSION}" lint contracts/openapi.yaml

# Lint scope (F11): backend/ and tests/ with the backend ruff config, run from the repo root so the
# result is identical to `cd backend && ruff check . ../tests` (known-first-party = ["app"]).
# contracts/tools is orchestrator-owned and not linted here (it has its own findings; see QA-04 report).
step "lint: ruff check backend tests" "$PYTHON" -m ruff check --config backend/pyproject.toml backend tests
step "lint: ruff format --check backend tests" "$PYTHON" -m ruff format --check --config backend/pyproject.toml backend tests
step "backend: mypy app" bash -c 'cd backend && "$0" -m mypy app' "$PYTHON"
step "backend: mypy --strict app/etl" bash -c 'cd backend && "$0" -m mypy --strict app/etl' "$PYTHON"

if [ "$SKIP_DB" -eq 1 ]; then
  skip "backend: pytest" "--skip-db"
  skip "fixtures: pytest tests/fixtures" "--skip-db"
  skip "integration: pytest tests/integration" "--skip-db"
else
  group "database preflight"
  if db_ready; then
    endgroup
    step "backend: pytest backend/tests" "$PYTHON" -m pytest backend/tests -q
    step "fixtures: pytest tests/fixtures" "$PYTHON" -m pytest tests/fixtures -q
    step "integration: pytest tests/integration" "$PYTHON" -m pytest tests/integration -q
  else
    endgroup
    FAILED+=("database preflight (start it: POSTGRES_PORT=55432 scripts/dev-up.sh)")
    echo "FAILED: database preflight" >&2
  fi
fi

if [ "$SKIP_FRONTEND" -eq 1 ]; then
  skip "frontend" "--skip-frontend"
else
  step "frontend: npm ci" npm --prefix frontend ci
  step "frontend: test" npm --prefix frontend test
  step "frontend: lint" npm --prefix frontend run lint
  step "frontend: typecheck" npm --prefix frontend run typecheck
  step "frontend: build" npm --prefix frontend run build
  step "frontend: generated types drift" types_drift
fi

# --------------------------------------------------------------------------------- summary
echo
echo "================ summary ================"
for s in "${PASSED[@]+"${PASSED[@]}"}"; do echo "PASS  $s"; done
for s in "${SKIPPED[@]+"${SKIPPED[@]}"}"; do echo "SKIP  $s"; done
for s in "${FAILED[@]+"${FAILED[@]}"}"; do echo "FAIL  $s"; done
echo "passed=${#PASSED[@]} skipped=${#SKIPPED[@]} failed=${#FAILED[@]}"
[ "${#FAILED[@]}" -eq 0 ]
