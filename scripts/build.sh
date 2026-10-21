#!/usr/bin/env bash
# Build and check the project: frontend production build, backend lint/types/migration head, and a
# backend wheel. Stops at the first failing step and names it.
#
# NOTE: frontend/dist/ is a set of STATIC ASSETS, not a deployment. `vite dev` and `vite preview`
# are development tools and are not production servers; serving dist/ and running the API and the
# worker in production is outside the MVP scope.
#
# Usage: scripts/build.sh      (run scripts/setup.sh first)
set -euo pipefail
# shellcheck source=lib/stack.sh
. "$(dirname "$0")/lib/stack.sh"
cd "$STACK_ROOT"

PY="$(backend_python)" || die "backend/.venv not found. Run scripts/setup.sh first."
[ -d frontend/node_modules ] || die "frontend/node_modules not found. Run scripts/setup.sh first."

TMP="$(mktemp -d "${TMPDIR:-/tmp}/localetl-build.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

step() { # step NAME COMMAND...
  local name="$1"; shift
  say; say "== $name"
  if ! "$@"; then
    printf '\nBUILD FAILED at step: %s\n' "$name" >&2
    exit 1
  fi
}

single_head() {
  local heads
  heads="$(cd backend && "$PY" -m alembic heads | grep -c '(head)' || true)"
  [ "$heads" = "1" ] || { echo "expected exactly one Alembic head, found $heads" >&2; return 1; }
  echo "alembic: single head"
}

step "frontend: npm run build (tsc -b && vite build)" npm --prefix frontend run build
step "backend: ruff check" "$PY" -m ruff check --config backend/pyproject.toml backend
step "backend: mypy app" bash -c "cd backend && '$PY' -m mypy app"
step "backend: alembic heads (exactly one)" single_head
step "backend: pip wheel (no deps)" "$PY" -m pip wheel --quiet --no-deps --disable-pip-version-check backend -w "$TMP/wheels"

say
say "Build OK."
say "  frontend/dist/    static assets (not a deployment)"
say "  backend wheel     built into a temporary directory and discarded"
say "Reminder: dist/ is just static files; 'vite dev' and 'vite preview' are not production servers."
