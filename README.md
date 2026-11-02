# LocalETL

Local-first ETL web application. Upload CSV files, configure cleaning and validation pipelines, load the
results into PostgreSQL, run and monitor jobs, and explore the published datasets with charts. Everything
runs on your machine; nothing is sent to external services.

## Demo
[▶ Watch the LocalETL demo](https://youtu.be/aswGu47Qza4)

# LocalETL — Product Specification

## 1. About Me (the User)

I'm a Computer Science student at Lehman College interested in becoming a Data Engineer. I have experience with Python, SQL, PostgreSQL, and ETL pipelines through internships and personal projects.

I built **LocalETL** to learn more about the Extract, Transform, Load (ETL) process and better understand how data moves through a pipeline.

I use LocalETL to upload CSV files, inspect datasets, clean messy data, convert data types, and load processed records into PostgreSQL.

The initial MVP took approximately **4 days to build**.

### The Last 3 Times This Happened

*These are representative examples based on my development experience, not three confirmed incidents.*

1. **Working with CSV files:** I needed to inspect columns, identify missing values, and clean records. I used Python scripts and manually inspected the output, making the process repetitive.

2. **Learning ETL pipelines:** I wanted to understand how extraction, transformation, validation, and loading work together. Reading individual scripts didn't always make the complete process clear.

3. **Testing data transformations:** I needed to convert strings into integers or floats and validate records. I had to run scripts and manually inspect the results to verify that the conversions worked.

### What It Costs Me

- ⏱️ **Time:** Repeatedly writing Python scripts and inspecting CSV files. Exact time spent per dataset has not been measured.
- 💸 **Money:** No significant direct cost. I use open-source technologies on my local computer.
- 🔋 **Energy:** Debugging scripts, checking database records, and switching between different environments requires extra effort.
- 🙂 **Joy:** I enjoy data engineering, but repetitive tasks take time away from learning new concepts.

---

## 2. Problem Statement

### Gut Check

> I need **a simpler way to clean and process CSV files** because **I want to understand ETL workflows without repeatedly writing the same processing code**.

### Five Whys

1. **Why do I need a simpler way to process CSV files?**
   - Because I frequently need to inspect, clean, and prepare datasets.

2. **Why is preparing datasets difficult?**
   - Because datasets can contain missing values, inconsistent data types, and invalid records.

3. **Why does that slow me down?**
   - Because I need to write Python scripts and manually review their results.

4. **Why am I repeatedly writing similar code?**
   - Because I don't have a reusable process connecting every ETL stage.

5. **Why do I need a reusable process?**
   - Because I want to understand how raw data becomes reliable, structured information while improving my data engineering skills.

### Problem Statement

> **When** I work with a new CSV dataset, **I struggle to** clean, validate, and convert its records into structured data without repeating manual steps, **which costs me** additional development time and mental effort. **This happens because** each dataset requires multiple processing steps that are difficult to manage consistently. **Right now I** write Python scripts and inspect results manually, **but** this makes it difficult to understand the complete ETL process and reuse previous work.

### I'll Know This Is Solved When

I can upload a CSV file, define cleaning and validation rules, execute the ETL process, and inspect the processed records in PostgreSQL.

I should also be able to explain each processing stage and understand why particular records were rejected.

---

## 3. Existing Solutions

| What I Use or Tried | What It Does Well | Why It Falls Short for Me |
|---|---|---|
| Python and Pandas | Flexible data cleaning and transformations | Requires writing and debugging scripts |
| PostgreSQL and SQL | Stores and queries structured data | Doesn't independently manage the complete ETL process |
| Manual CSV inspection | Makes it easy to inspect raw data | Becomes inefficient with larger or more complex datasets |

### The Gap

I need a reusable local workflow that helps me understand and execute each ETL stage while making results and errors easy to inspect.

---

## 4. Features & Benefits

| Feature (What It Does) | Benefit (How My Life Gets Better) | MVP or Later? |
|---|---|---|
| CSV upload and preview | Inspect datasets before processing | MVP |
| Data cleaning and type conversion | Convert strings to integers/floats, handle nulls, and clean records | MVP |
| Pipeline execution and results | Execute ETL workflows and inspect successful or rejected records | MVP |
| Dataset explorer and charts | Explore processed data and visualize results | Later — implemented |
| Advanced transformations | Handle more complex data-cleaning scenarios | Later |
| Detailed performance metrics | Better understand pipeline performance | Later |

### MVP (2–3 Features)

1. **CSV Upload and Preview**
   - Upload CSV files.
   - Inspect columns and sample records.

2. **Data Cleaning and Transformations**
   - Convert strings into integers and floats.
   - Handle missing values.
   - Remove duplicates.
   - Apply validation rules.

3. **Pipeline Execution**
   - Run an ETL pipeline.
   - Load processed data into PostgreSQL.
   - Inspect execution results and rejected records.

### Later

- Additional transformation operations.
- More advanced data-cleaning rules.
- Expanded dataset visualizations.
- Detailed debugging and performance analysis.
- Support for additional file formats.

### Not Doing

- Public online hosting.
- Multi-user accounts or authentication.
- Paid subscriptions.
- Cloud infrastructure.
- Enterprise-scale distributed processing.

LocalETL is a **personal learning project** that runs on my computer.

---

## 5. Technology Stack

### Front End

- **Surface:** Local web application
- **Tools:** React, TypeScript, Vite, Tailwind CSS, Recharts
- **Why:** A visual interface allows me to upload CSV files, configure transformations, run pipelines, and inspect results without relying entirely on terminal commands.

### Back End

| Piece | Choice | Why |
|---|---|---|
| Server / API | Python, FastAPI, Pydantic | Provides REST endpoints and validates requests |
| ETL Processing | Python, Pandas | Extracts, transforms, cleans, and validates data |
| Background Execution | Python worker | Executes queued pipelines separately from API requests |
| Data Storage | PostgreSQL 16 | Stores pipeline configurations, execution metadata, and processed datasets |
| Database Management | SQLAlchemy, Alembic | Handles database operations and schema migrations |
| Outside Services | None required | Keeps the project self-contained |
| Hosting / Deploy | Local computer, Docker Compose | Runs locally without cloud infrastructure |
| Testing | Pytest, Vitest, Playwright | Tests backend logic, frontend behavior, and end-to-end workflows |

### Architecture Diagram

```mermaid
flowchart TD
    A["User"] --> B["React Frontend"]
    B --> C["FastAPI Backend"]
    C --> D[("PostgreSQL")]
    C --> E["Local CSV Storage"]
    D --> F["Background Worker"]
    F --> G["ETL Engine"]
    E --> G
    G --> D
    D --> C
    C --> B
```

### Data Flow

1. User uploads a CSV file.
2. FastAPI stores the source file and metadata.
3. User configures transformations and validation rules.
4. Backend creates a queued pipeline run.
5. Background worker claims and executes the run.
6. ETL engine extracts, transforms, and validates the data.
7. Processed records are loaded into PostgreSQL.
8. Frontend displays execution results, datasets, and charts.

---

## 6. Project Goal

My goal is to understand how ETL systems work by designing and developing one myself.

Through LocalETL, I am learning:

- ETL pipeline architecture.
- Python data processing.
- Data cleaning and type conversion.
- PostgreSQL database design.
- REST API development.
- Background job execution.
- Data validation and quality assurance.
- Full-stack development.

### Success Criteria

LocalETL is successful when I can:

- Upload a CSV file.
- Configure cleaning and transformation rules.
- Execute a complete ETL pipeline.
- Store the resulting data in PostgreSQL.
- Inspect processed and rejected records.
- Explain how the data moved through each ETL stage.

**The goal is learning and practical experience, not commercial deployment.**


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
  own risk. Only `setup.sh` checks the Node version; the other scripts need no override.
- Changing the database port means editing three values in `.env` together: `POSTGRES_PORT` and the port
  inside `DATABASE_URL` and `TEST_DATABASE_URL`.
- Choose the Python used to create the virtualenv with `PYTHON_BIN=python3.12 scripts/setup.sh`.

## Configuration

All settings are environment variables; `.env.example` lists every one with its default. `scripts/dev.sh`
reads them in this order: variables already in your environment, then `.env`, then `.env.example`. The
backend itself does not read `.env`, and `scripts/test-all.sh` and `scripts/e2e.sh` use only the environment
(with their own defaults).
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
alive, owned by you and running the recorded command. The worker stops claiming runs, interrupts an active
run at the next stage or chunk boundary (that run ends `interrupted`) and exits.
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
| Port 5432 already in use (e.g. Postgres.app) | For `dev.sh`: set `POSTGRES_PORT=55432` in `.env` and change the port in `DATABASE_URL` and `TEST_DATABASE_URL` to match. `test-all.sh`, `e2e.sh` and `dev-up.sh` do not read `.env`: run them as `POSTGRES_PORT=55432 scripts/test-all.sh` (they derive the database URLs from it unless `DATABASE_URL`/`TEST_DATABASE_URL` are exported) |
| `port 8000/5173 is already in use` | Stop what uses it, or `scripts/stop.sh` if it is an earlier LocalETL run |
| `the dev stack is already running` | Use the running stack, or `scripts/stop.sh` first |
| `backend/.venv not found` / `node_modules not found` | `scripts/setup.sh` |
| `Node 22 is required` | Install Node 22 (or `LOCALETL_ALLOW_ANY_NODE=1`, unsupported) |
| Running a second LocalETL stack beside an existing one (another clone) | Use another Compose project and port: `export COMPOSE_PROJECT_NAME=localetl-2` in the shell (`dev.sh` ignores keys not in `.env.example`), and a free port such as 55433 in the three `.env` values. Otherwise the container and volume names collide with the first stack. Ports 8000 and 5173 are fixed, so only one stack can run `dev.sh` at a time |
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
