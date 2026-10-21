#!/usr/bin/env bash
# One-time (and repeatable) developer setup: checks the toolchain, creates or reuses backend/.venv,
# installs backend and frontend dependencies. Idempotent. It never touches database volumes, .env,
# LOCALETL_DATA_DIR or .claude/worktrees, and never deletes anything.
#
# Usage: scripts/setup.sh
# Env:   PYTHON_BIN                 Python to create the venv with (default: python3.12, python3.11, python3)
#        LOCALETL_ALLOW_ANY_NODE=1  accept a Node major other than 22 (CI uses 22)
set -euo pipefail
# shellcheck source=lib/stack.sh
. "$(dirname "$0")/lib/stack.sh"
cd "$STACK_ROOT"

step() { say; say "== $*"; }

step "Checking the toolchain"
# Python 3.11-3.12
PY=""
if [ -n "${PYTHON_BIN:-}" ]; then
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "PYTHON_BIN=$PYTHON_BIN not found"
  PY="$(command -v "$PYTHON_BIN")"
else
  for c in python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && py_version_ok "$c"; then PY="$(command -v "$c")"; break; fi
  done
fi
[ -n "$PY" ] || die "Python 3.11 or 3.12 is required (found none). Install one, or set PYTHON_BIN."
py_version_ok "$PY" || die "$PY is $("$PY" -V 2>&1); Python 3.11 or 3.12 is required."
say "python: $("$PY" -V 2>&1) ($PY)"

# Node 22
command -v node >/dev/null 2>&1 || die "Node.js 22 is required (not found)."
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" != "22" ]; then
  if [ "${LOCALETL_ALLOW_ANY_NODE:-}" = "1" ]; then
    say "warning: Node $(node -v) is not 22 (CI version); continuing because LOCALETL_ALLOW_ANY_NODE=1"
  else
    die "Node 22 is required, found $(node -v). Install Node 22, or set LOCALETL_ALLOW_ANY_NODE=1 to override."
  fi
fi
say "node: $(node -v)"
command -v npm >/dev/null 2>&1 || die "npm is required (not found)."
say "npm: $(npm -v)"

# Docker + Compose
command -v docker >/dev/null 2>&1 || die "Docker is required (not found)."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 ('docker compose') is required."
say "docker: $(docker --version)"
say "compose: $(docker compose version --short 2>/dev/null || docker compose version | head -1)"
if ! docker info >/dev/null 2>&1; then
  say "warning: the Docker daemon is not reachable; start Docker before scripts/dev.sh"
fi

step "Python virtualenv (backend/.venv)"
VENV="$STACK_ROOT/backend/.venv"
if [ -x "$VENV/bin/python" ]; then
  if py_version_ok "$VENV/bin/python"; then
    say "reusing $VENV ($("$VENV/bin/python" -V 2>&1))"
  else
    die "$VENV exists but uses $("$VENV/bin/python" -V 2>&1) (need 3.11 or 3.12). Remove it yourself and rerun; this script never deletes it."
  fi
else
  [ ! -e "$VENV" ] || die "$VENV exists but has no usable interpreter; remove it yourself and rerun."
  "$PY" -m venv "$VENV"
  say "created $VENV"
fi

step "Installing backend dependencies (pip install -e 'backend[dev]')"
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -e 'backend[dev]'
say "backend installed"

step "Installing frontend dependencies (npm ci)"
npm --prefix frontend ci --no-audit --no-fund
say "frontend installed"

say
say "Setup complete. Next: scripts/dev.sh (start everything) or scripts/build.sh (checks + build)."
