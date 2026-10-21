# scripts/

| Script | Purpose |
|---|---|
| `dev-up.sh [timeout]` | `docker compose up -d db`, then wait until the healthcheck reports healthy (default 60 s). |
| `test-all.sh [--skip-frontend] [--skip-db]` | Runs every check CI runs (hygiene, contract check, Redocly, ruff + mypy, backend/fixtures/integration pytest, frontend test/lint/typecheck/build, generated-types drift) and prints a PASS/SKIP/FAIL summary. Never starts or stops the database. |
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
