#!/usr/bin/env bash
# Stop the processes started by scripts/dev.sh. Only PIDs listed in the PID file (.localetl/dev.pids)
# are signalled, and each one is verified first: alive, owned by you, and its command line still
# matches what dev.sh recorded, and its start time is unchanged (PID reuse). SIGTERM, a wait, then SIGKILL only for verified survivors.
# No pkill/killall, no name matching. The database is left running unless --db is given
# (`docker compose stop db`; the data volume is kept). Nothing here deletes data, volumes or .env.
#
# Usage: scripts/stop.sh [--db]
set -euo pipefail
# shellcheck source=lib/stack.sh
. "$(dirname "$0")/lib/stack.sh"
cd "$STACK_ROOT"

STOP_DB=0
for a in "$@"; do
  case "$a" in
    --db) STOP_DB=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) die "unknown option: $a" ;;
  esac
done

TIMEOUT="${STOP_TIMEOUT_SECONDS:-20}"

if [ ! -f "$PID_FILE" ]; then
  say "No PID file ($PID_FILE): nothing recorded to stop."
else
  # Read the records first (the file may be rewritten by a dying launcher).
  RECORDS=()
  while IFS= read -r line || [ -n "$line" ]; do [ -n "$line" ] && RECORDS+=("$line"); done <"$PID_FILE"

  signal_verified() { # signal_verified SIG ROLE-FILTER...: signal every record that still verifies
    local sig="$1" line pid role fragment start
    for line in "${RECORDS[@]}"; do
      IFS=$'\t' read -r pid role fragment start <<<"$line"
      if verify_pid "$pid" "$fragment" "${start:-}"; then
        say "  $sig $role (pid $pid)"
        kill -"$sig" "$pid" 2>/dev/null || true
      else
        say "  skip $role (pid ${pid:-?}): not signalled: already stopped, not yours, or command/start time changed"
      fi
    done
  }
  any_alive() {
    local line pid role fragment start
    for line in "${RECORDS[@]}"; do
      IFS=$'\t' read -r pid role fragment start <<<"$line"
      if verify_pid "$pid" "$fragment" "${start:-}"; then return 0; fi
    done
    return 1
  }

  if [ "${#RECORDS[@]}" -eq 0 ]; then
    say "PID file is empty."
  else
    # The launcher (dev.sh) shuts the children down in order and checks the worker's exit code, so give
    # it the first and only SIGTERM and let it finish; only then deal with whatever is left.
    for line in "${RECORDS[@]}"; do
      IFS=$'\t' read -r pid role fragment start <<<"$line"
      if [ "$role" = "launcher" ] && verify_pid "$pid" "$fragment" "${start:-}"; then
        say "Stopping the launcher (pid $pid, SIGTERM) and waiting for it to stop its children..."
        kill -TERM "$pid" 2>/dev/null || true
        end=$((SECONDS + TIMEOUT))
        while verify_pid "$pid" "$fragment" "${start:-}" && (( SECONDS < end )); do sleep 0.5; done
      fi
    done
    say "Stopping any remaining recorded processes (SIGTERM)..."
    signal_verified TERM
    deadline=$((SECONDS + TIMEOUT))
    while any_alive && (( SECONDS < deadline )); do sleep 0.5; done
    if any_alive; then
      say "Still running after ${TIMEOUT}s; sending SIGKILL to verified processes only..."
      signal_verified KILL
      sleep 1
    fi
    if any_alive; then
      say "warning: some recorded processes are still running; the PID file was kept." >&2
      exit 1
    fi
  fi
  rm -f "$PID_FILE"
  say "Stopped."
fi

if [ "$STOP_DB" -eq 1 ]; then
  say "Stopping the database container (data volume kept)..."
  docker compose stop db
else
  say "The database was left running (scripts/stop.sh --db to stop it)."
fi
