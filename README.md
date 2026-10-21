# LocalETL

Local-first ETL web application. Upload CSV files, configure cleaning and validation pipelines, load the
results into PostgreSQL, run and monitor jobs, and explore the published datasets with charts. Everything
runs on your machine; nothing is sent to external services.

## Features (MVP)

- **CSV upload and preview**: one file at a time (default limit 100 MB); `utf-8`, `utf-8-sig`, `latin-1`,
  `cp1252`; delimiters `,` `;` tab `|`; preview with inferred column types.
- **Saved pipelines**: select, rename and type columns; configuration validated against
  `contracts/pipeline.schema.json` before saving.
- **Cleaning and validation** from a fixed list of operations and rules (no user code is ever executed).
  Rejected rows are recorded with row number, rule, column and value.
- **PostgreSQL loading** through a per-run staging table, then published to the target table
  (`replace` or `append`).
- **Manual runs and monitoring**: queue a run, follow its stage events and counters live; one running run
  at a time; crash recovery and clean shutdown of the worker.
- **History and metrics**: run history with filters, outcomes per day, rows loaded per run.
- **Dataset explorer**: paged rows table with sorting, per-column profile charts (top values, nulls).

The full list is in `docs/requirements.md`.

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript (strict), Vite, Tailwind CSS, Recharts |
| API | Python, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, uvicorn |
| ETL engine | pandas (chunked), usable without the API (`backend/app/etl`) |
| Worker | Python process (`python -m app.worker`) |
| Database | PostgreSQL 16 (Docker Compose) |
| Tests | pytest, Vitest + Testing Library, Playwright (end-to-end) |

## Architecture

```
 Browser (React, :5173) ──HTTP──▶ FastAPI (:8000, /api/v1) ──▶ PostgreSQL 16 (:5432)
                                       │ queues runs                 ▲
                                       ▼                             │
                               runs table (queued) ◀── claims ── Worker (python -m app.worker)
                                                                  └─ runs the ETL engine, writes
                                                                     staging and datasets schemas
```

- The API stores uploads under `LOCALETL_DATA_DIR`, saves pipelines and queues runs. It never runs a
  pipeline itself.
- The worker claims queued runs (`FOR UPDATE SKIP LOCKED`), executes them with the ETL engine, records
  events and counters, and recovers runs left `running` by a crashed worker.
- Application metadata lives in the `public` schema (Alembic migrations); ETL output lives in the
  `staging` and `datasets` schemas.

Details: `docs/architecture.md`. API contract: `contracts/openapi.yaml`.

## Prerequisites

| Tool | Version |
|---|---|
| Python | 3.11 or 3.12 |
| Node.js | 22 (the CI version) |
| npm | the one bundled with Node 22 |
| Docker | with Compose v2 (`docker compose`) |
| curl | used by the scripts to wait for services |

macOS and Linux with bash are supported. Ports used: 5432 (PostgreSQL), 8000 (API), 5173 (web).

## Installation

```bash
git clone <your-repository-url> localetl
cd localetl
cp .env.example .env        # optional: the scripts fall back to .env.example values
scripts/setup.sh
```

`scripts/setup.sh` checks the tool versions, creates or reuses `backend/.venv`, runs
`pip install -e 'backend[dev]'` and `npm --prefix frontend ci`. It is safe to run again: it never touches the
database volume, `.env`, the data directory or `.claude/worktrees`.

- Another Node major than 22: install Node 22, or run `LOCALETL_ALLOW_ANY_NODE=1 scripts/setup.sh` at your
  own risk.
- Choose the Python used to create the virtualenv with `PYTHON_BIN=python3.12 scripts/setup.sh`.

## Configuration

All settings are environment variables; `.env.example` lists every one with its default. The scripts read
them in this order: variables already in your environment, then `.env`, then `.env.example`.
`.env` is parsed as plain `KEY=VALUE` lines (one layer of quotes removed, nothing expanded or executed) and
only keys declared in `.env.example` are accepted. Never commit `.env`.

| Variable | Default | Used by |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://localetl:localetl@127.0.0.1:5432/localetl` | API, worker, migrations |
| `TEST_DATABASE_URL` | `…/localetl_test` | tests |
| `LOCALETL_DATA_DIR` | `./data` (relative to the repository root) | API (uploads), worker |
| `LOCALETL_MAX_UPLOAD_MB` | `100` | API |
| `LOCALETL_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | API |
| `LOCALETL_CHUNK_ROWS` | `50000` | worker |
| `WORKER_POLL_INTERVAL_SECONDS` / `WORKER_HEARTBEAT_SECONDS` / `WORKER_STALE_AFTER_SECONDS` | `2` / `10` / `60` | worker |
| `VITE_API_URL` | `http://127.0.0.1:8000/api/v1` | frontend (build time) |
| `VITE_MAX_UPLOAD_MB` | `100` | frontend early size check; keep equal to `LOCALETL_MAX_UPLOAD_MB` |
| `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `5432`, `localetl`, `localetl`, `localetl` | Docker Compose only |

The default credentials are for local development only.

## Start the application

```bash
scripts/dev.sh
```

One command starts everything and stays in the foreground:

1. PostgreSQL via Docker Compose (`scripts/dev-up.sh`, waits until healthy);
2. `alembic upgrade head`;
3. the API (`uvicorn app.main:app` on `127.0.0.1:8000`), the worker (`python -m app.worker`) and the Vite
   dev server (`127.0.0.1:5173`).

It prints the configuration with passwords masked, then the URLs:

- Web UI: <http://127.0.0.1:5173>
- API: <http://127.0.0.1:8000/api/v1> (health: `/api/v1/health`)

Logs are in `.localetl/logs/` (`api.log`, `worker.log`, `web.log`). `dev.sh` refuses to start a second
copy, or when port 8000 or 5173 is already in use. Run it from the main checkout (see Troubleshooting).

## Stop the application

- Press **Ctrl+C** in the terminal running `scripts/dev.sh`; or
- from another terminal: `scripts/stop.sh`

`stop.sh` signals only the processes `dev.sh` recorded in `.localetl/dev.pids`, after checking each is still
alive, owned by you and running the recorded command. The worker finishes its current step and exits.
PostgreSQL keeps running; stop it too with `scripts/stop.sh --db` (`docker compose stop db`, data kept).
Nothing in these scripts deletes the database volume or your data. A full reset is a manual, destructive
step: `docker compose down -v` deletes the volume.

## Build

```bash
scripts/build.sh
```

Runs, stopping at the first failure and naming the step: frontend production build
(`npm run build` = `tsc -b && vite build`, output in `frontend/dist/`), backend `ruff check` and `mypy`,
a single Alembic head check, and a backend wheel build (discarded).

`frontend/dist/` is static assets with `VITE_API_URL` baked in at build time. `vite dev` and `vite preview`
are development tools, not a production deployment; LocalETL has no production deployment setup yet.

## Tests

```bash
scripts/test-all.sh              # everything CI runs: hygiene, contracts, lint, types, all test suites, frontend build
scripts/e2e.sh                   # Playwright end-to-end demo on a throwaway database (see tests/e2e/README.md)
```

- `test-all.sh` needs PostgreSQL running (`scripts/dev-up.sh`) and `PYTHON=$PWD/backend/.venv/bin/python`
  if `python` on your PATH is not the project venv; `--skip-db` and `--skip-frontend` skip parts.
- Single suites: `pytest backend/tests/<area>`, `npm --prefix frontend test`,
  `npm --prefix frontend run lint`, `mypy backend/app`.
- The end-to-end demo needs one-time browser setup:
  `npm --prefix tests/e2e ci && npm --prefix tests/e2e run install:browser`.
- Performance test (opt-in, about 3 minutes): `LOCALETL_PERF=1 pytest tests/perf -s`.

## Demo

`scripts/e2e.sh` drives the full flow in a real browser: upload `orders_clean.csv` → create a pipeline →
run it → watch it succeed → results, dataset explorer and charts. The video and trace are kept in
`tests/e2e/test-results/` (not committed). To try it by hand, run `scripts/dev.sh`, open
<http://127.0.0.1:5173> and upload any file from `tests/fixtures/csv/`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Port 5432 already in use (e.g. Postgres.app) | Set `POSTGRES_PORT=55432` in `.env` and change the port in `DATABASE_URL` and `TEST_DATABASE_URL` to match |
| `port 8000/5173 is already in use` | Stop what uses it, or `scripts/stop.sh` if it is an earlier LocalETL run |
| `the dev stack is already running` | Use the running stack, or `scripts/stop.sh` first |
| `backend/.venv not found` / `node_modules not found` | `scripts/setup.sh` |
| `Node 22 is required` | Install Node 22 (or `LOCALETL_ALLOW_ANY_NODE=1`, unsupported) |
| Database container recreated on start | Happens when `dev.sh`/`docker compose` runs from a different checkout or git worktree than the one that created it; data is kept, but connections drop briefly. Run from the main checkout |
| Changed `POSTGRES_*` or `scripts/db/init.sql` has no effect | They apply only when the volume is first created; resetting needs `docker compose down -v`, which **deletes all data** |
| Test DB errors about permissions | The role must be allowed to create databases (the Compose role is) |
| Occasional frontend test timeouts | Seen only under very heavy machine load; rerun |

## Current limitations

- Single user, local only: no authentication; the API listens on `127.0.0.1`.
- CSV input only; one running run at a time.
- No production deployment setup; the frontend build is static files only.
- A replace run takes an exclusive lock on the target table while publishing.
- If the worker dies after publishing a table but before recording success, the run ends `failed` although
  the data was published (a planned hardening item).
- The end-to-end demo runs in Chromium only.

Planned work and known issues: `docs/task-board.md`.

## Project documentation

- Project rules for contributors and agents: `CLAUDE.md`
- Requirements: `docs/requirements.md` · Architecture: `docs/architecture.md`
- Contracts: `contracts/openapi.yaml`, `contracts/pipeline.schema.json`
- Scripts: `scripts/README.md`
