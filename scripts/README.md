# scripts/

| Script | Purpose |
|---|---|
| `dev-up.sh [timeout]` | `docker compose up -d db`, then wait until the healthcheck reports healthy (default 60 s). |
| `test-all.sh [--skip-frontend] [--skip-db]` | Runs every check CI runs (hygiene, contract check, Redocly, ruff + mypy, backend/fixtures/integration pytest, frontend test/lint/typecheck/build, generated-types drift) and prints a PASS/SKIP/FAIL summary. Never starts or stops the database. |
| `setup.sh` | One-time/repeatable setup: checks Python 3.11-3.12, Node 22, npm, Docker + Compose; creates or reuses `backend/.venv`; `pip install -e 'backend[dev]'`; `npm --prefix frontend ci`. Idempotent; never touches DB volumes, `.env`, the data dir or worktrees. |
| `dev.sh` | Starts the DB (`dev-up.sh`), `alembic upgrade head`, the API (:8000), the worker and the Vite dev server (:5173) in the foreground; Ctrl+C stops them (worker must exit 0). |
| `stop.sh [--db]` | Stops only the processes recorded in `.localetl/dev.pids` after verifying each; `--db` also runs `docker compose stop db`. |
| `build.sh` | Frontend build, backend ruff + mypy, single Alembic head, `pip wheel`. Names the failing step. |
| `lib/stack.sh` | Shared helpers (safe `.env` parser, URL masking, PID-file verification). Sourced, not run. |
| `db/init.sql` | Mounted into the Postgres init directory; creates `localetl_test`. |

## Database stack

```bash
cp .env.example .env          # optional; compose defaults equal .env.example
scripts/dev-up.sh             # or: docker compose up -d db
docker compose down           # stop, keep data
docker compose down -v        # stop and DELETE the volume (full reset)
```

- PostgreSQL 16 on `127.0.0.1:5432` only (not exposed to the network). If a local Postgres already uses 5432, set `POSTGRES_PORT=55432` (compose-only override) and point `DATABASE_URL`/`TEST_DATABASE_URL` at that port.
- Databases: `localetl` (from `POSTGRES_DB`) and `localetl_test` (from `init.sql`).
- User/password come from `POSTGRES_USER` / `POSTGRES_PASSWORD`.
- Data lives in the named volume `localetl_pgdata`.
- `init.sql` runs **only on first initialisation of an empty volume**. If you
  changed it or the credentials, run `docker compose down -v` and start again.
- `localetl_test` is for pytest (`TEST_DATABASE_URL`) and may be wiped by tests.

## Running all checks

```bash
python3.11 -m venv .venv && . .venv/bin/activate && pip install -e 'backend[dev]'
POSTGRES_PORT=55432 scripts/dev-up.sh          # if no Postgres is running; 55432 when Postgres.app owns 5432
POSTGRES_PORT=55432 scripts/test-all.sh        # same steps as .github/workflows/ci.yml
```

- CI (`.github/workflows/ci.yml`) installs with `pip install -e 'backend[dev]'`, starts a Postgres 16 service, creates `localetl_test`, and calls `scripts/test-all.sh`, so local and CI results match.
- The DB suites create and drop throwaway databases, so the database role needs `CREATEDB` (the compose and CI `localetl` role is the superuser).
- Lint scope: `ruff check` and `ruff format --check` over `backend` and `tests` with `backend/pyproject.toml`, run from the repo root.
- The compose project name is pinned to `localetl`; set `COMPOSE_PROJECT_NAME` (and another `POSTGRES_PORT`) to run a second, throwaway stack beside the dev stack. The first `scripts/dev-up.sh` after this change recreates an existing dev container once (the data volume is kept) because the container is now named `localetl-db-1` instead of `localetl-db`.

## e2e.sh (QA-08)

`scripts/e2e.sh` starts the full stack on a throwaway database and runs the Playwright demo in `tests/e2e/`; see `tests/e2e/README.md`.

## Developer workflow (DX-01a)

```bash
scripts/setup.sh        # once (Node 22 expected; LOCALETL_ALLOW_ANY_NODE=1 accepts another major)
scripts/dev.sh          # DB + migrations + API + worker + frontend; Ctrl+C to stop
scripts/stop.sh         # from another terminal; add --db to stop the database container too
scripts/build.sh        # checks + production build
```

- Configuration order: environment > `.env` > `.env.example`. `.env` is **parsed, never sourced**: only
  `KEY=value` lines with an upper-case name are read, one layer of matching quotes is removed, and values are
  taken literally (no `$` expansion, backticks or `$(...)`).
- Only keys declared in `.env.example` are read from `.env`; any other key (e.g. `NODE_OPTIONS`, `BASH_ENV`, `PYTHONPATH`, `LD_PRELOAD`) is skipped with a warning that names the key, never the value.
- Secrets are never printed: `dev.sh` shows variable names and hosts, with URL passwords masked as `***`.
- `LOCALETL_DATA_DIR` defaults to `./data` relative to the repository root (made absolute for the API and worker).
- PID file: `.localetl/dev.pids` (one `PID<TAB>role<TAB>command-fragment<TAB>start-time` line per process; a line without a start time is never signalled); logs in `.localetl/logs/`.
  `stop.sh` verifies each PID (alive, yours, command line still matches and the process start time is unchanged, so a recycled PID is never signalled) before signalling; it never uses `pkill`/`killall`
  and never deletes volumes, data or `.env`.
- `dev.sh` refuses to start if recorded processes are alive or ports 8000/5173 are in use.
- `frontend/dist/` is static assets. `vite dev` and `vite preview` are not deployments.
