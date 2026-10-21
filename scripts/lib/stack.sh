# Shared helpers for scripts/setup.sh, dev.sh, stop.sh and build.sh (DX-01a). Source it, don't run it.
# shellcheck shell=bash
#
# Security rules enforced here:
#   * .env is never sourced or eval'ed: load_env_file parses it line by line (see below).
#   * Secrets are never printed: use mask_url for anything URL-shaped.
#   * Only PIDs recorded in the launcher's PID file are ever signalled, and only after
#     verify_pid confirms they are alive, owned by the current user and still running the
#     recorded command. Nothing here uses pkill/killall.

STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_DIR="$STACK_ROOT/.localetl"
PID_FILE="$RUN_DIR/dev.pids"
LOG_DIR="$RUN_DIR/logs"
API_PORT_DEFAULT=8000
WEB_PORT_DEFAULT=5173

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# env_allowed_keys: the variable names declared in .env.example (same ^[A-Z_][A-Z0-9_]*= rule).
# Only these keys may be loaded from .env, so a stray line such as NODE_OPTIONS, BASH_ENV, PYTHONPATH,
# PYTHONSTARTUP, LD_PRELOAD or DYLD_* can never make node, bash or python run foreign code.
env_allowed_keys() {
  local line
  [ -f "$STACK_ROOT/.env.example" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[A-Z_][A-Z0-9_]*= ]] && printf '%s\n' "${line%%=*}"
  done <"$STACK_ROOT/.env.example"
}

# load_env_file FILE: export KEY=VALUE lines from FILE without executing anything.
#   - only lines matching ^[A-Z_][A-Z0-9_]*=  are used; comments, blanks and anything else are skipped;
#   - the key must be declared in .env.example; any other key is skipped with a warning that names the
#     key (never the value);
#   - one layer of matching single or double quotes around the value is removed;
#   - the value is taken literally: no $ expansion, no backticks, no $(...);
#   - a variable that is already set in the environment keeps its value (environment wins).
load_env_file() {
  local file="$1" line key value allowed
  [ -f "$file" ] || return 0
  allowed="$(env_allowed_keys)"
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[A-Z_][A-Z0-9_]*= ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    if ! printf '%s\n' "$allowed" | grep -qxF -- "$key"; then
      printf 'warning: %s: ignoring %s (not declared in .env.example)\n' "${file##*/}" "$key" >&2
      continue
    fi
    if [ -n "${!key+x}" ]; then continue; fi
    if [[ "$value" =~ ^\"(.*)\"$ ]] || [[ "$value" =~ ^\'(.*)\'$ ]]; then
      value="${BASH_REMATCH[1]}"
    fi
    export "$key=$value"
  done <"$file"
}

# Environment > .env > .env.example (the defaults). Never prints values.
load_env() {
  load_env_file "$STACK_ROOT/.env"
  load_env_file "$STACK_ROOT/.env.example"
}

# mask_url URL: hide the password of a URL (scheme://user:pass@host/db -> scheme://user:***@host/db).
mask_url() { printf '%s' "$1" | sed -E 's#(://[^:/@]*):[^@]*@#\1:***@#'; }

# url_host URL: host:port/db part only.
url_host() { printf '%s' "$1" | sed -E 's#^[^:]*://([^@/]*@)?##'; }

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# Python used for the backend: backend/.venv, else $PYTHON, else fail with a hint.
backend_python() {
  if [ -x "$STACK_ROOT/backend/.venv/bin/python" ]; then
    printf '%s' "$STACK_ROOT/backend/.venv/bin/python"
  elif [ -n "${PYTHON:-}" ] && command -v "$PYTHON" >/dev/null 2>&1; then
    command -v "$PYTHON"
  else
    return 1
  fi
}

py_version_ok() { # py_version_ok PYTHON -> 0 if 3.11 or 3.12
  local v
  v="$("$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || return 1
  [ "$v" = "3.11" ] || [ "$v" = "3.12" ]
}

# ---------------------------------------------------------------- PID file
# Line format:  PID<TAB>ROLE<TAB>COMMAND-FRAGMENT<TAB>START-TIME
#   The fragment must appear in the process command line, and START-TIME (`ps -o lstart=`) must equal
#   the process's current start time, so a recycled PID is never mistaken for a recorded process.
#   Old 3-column lines have no start time and are rejected (never signalled).

proc_start() { ps -p "$1" -o lstart= 2>/dev/null | sed -E 's/^ +//; s/ +$//; s/ +/ /g'; }

pid_record() { # pid_record PID ROLE FRAGMENT
  local start
  mkdir -p "$RUN_DIR"
  start="$(proc_start "$1")"
  printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$start" >>"$PID_FILE"
}

# verify_pid PID FRAGMENT START: alive, owned by the current user, command line contains FRAGMENT
# and the start time equals START (an empty START never verifies).
verify_pid() {
  local pid="$1" fragment="$2" start="${3:-}" owner cmd
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [ -n "$start" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  owner="$(ps -p "$pid" -o user= 2>/dev/null | tr -d ' ')" || return 1
  [ -n "$owner" ] && [ "$owner" = "$(id -un)" ] || return 1
  cmd="$(ps -p "$pid" -o command= 2>/dev/null)" || return 1
  [[ "$cmd" == *"$fragment"* ]] || return 1
  [ "$(proc_start "$pid")" = "$start" ]
}

# live_recorded: print "PID ROLE" for each recorded process that still verifies.
live_recorded() {
  local pid role fragment start
  [ -f "$PID_FILE" ] || return 0
  while IFS=$'\t' read -r pid role fragment start; do
    [ -n "${pid:-}" ] || continue
    if verify_pid "$pid" "$fragment" "${start:-}"; then printf '%s %s\n' "$pid" "$role"; fi
  done <"$PID_FILE"
}

# descendants PID: PIDs of all children, grandchildren, ... (walks ps output; no name matching).
descendants() {
  local root="$1" snap
  snap="$(ps -A -o pid= -o ppid=)"
  awk -v root="$root" '
    { parent[$1] = $2 }
    END {
      changed = 1; found[root] = 1
      while (changed) {
        changed = 0
        for (p in parent) if (!(p in found) && (parent[p] in found)) { found[p] = 1; changed = 1; print p }
      }
    }' <<<"$snap"
}
