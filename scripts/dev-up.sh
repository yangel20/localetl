#!/usr/bin/env bash
# Start the local PostgreSQL container and wait until it is healthy.
# Usage: scripts/dev-up.sh [timeout_seconds]   (default 60)
set -euo pipefail

cd "$(dirname "$0")/.."
TIMEOUT="${1:-60}"

docker compose up -d db

cid="$(docker compose ps -q db)"
deadline=$((SECONDS + TIMEOUT))
while :; do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid")"
  case "$status" in
    healthy) echo "db is healthy on 127.0.0.1:${POSTGRES_PORT:-5432}"; exit 0 ;;
    unhealthy|exited|dead) echo "db failed: $status" >&2; docker compose logs --tail 30 db >&2; exit 1 ;;
  esac
  if (( SECONDS >= deadline )); then
    echo "timed out after ${TIMEOUT}s waiting for db (status: $status)" >&2
    exit 1
  fi
  sleep 1
done
