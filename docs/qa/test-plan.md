# LocalETL QA Test Plan and Traceability Matrix

Owner: qa-engineer · Ticket: QA-02 · Written 2026-10-20 against `main` 9d550f4.
Sources: `docs/requirements.md` (REQ-xx), `docs/architecture.md` §5–§8, `docs/task-board.md`, `docs/wave-1-runbook.md`.

## 1. How to read this plan

**Layers.** `ETL` = unit/component tests of `app.etl` (`backend/tests/etl/`). `MODEL` = schema and constraint tests on Postgres (`backend/tests/models/`). `API` = FastAPI tests (`backend/tests/api/`). `INT` = cross-component tests from the repo root (`tests/integration/`, `tests/fixtures/`). `FE` = frontend unit/component tests (vitest, `frontend/src/**`). `E2E` = browser demo (Wave 2, QA-08). `DOC/CFG` = checked by review, contract check or CI, not by a runtime test.

**Status.** `Wave 1` = ticket exists and is in the Wave 1 scope. `Wave 2` = depends on tickets not yet assigned (WK-01..03, VIZ-01..02, QA-08). **PROVISIONAL** = the expected behaviour depends on an unapproved draft; the test is written against the draft and must be re-checked when the draft is approved or changed. No PROVISIONAL test may be used as a Wave 1 exit gate until its draft is approved.

**Drafts that make things provisional** (read from the draft branches; none is approved):
- **Q4**: CSV structure and malformed input. Branch `orch/Q4-csv-structure` @ `5954cc2`, `docs/architecture.md` §5 "CSV structure and malformed input" (rules 1–9, row-level and file-level tables, chunk rules, sub-decisions Q4-a..d).
- **Q6-3**: value casting. Branch `orch/Q6-casting-spec` @ `d5705f4`, `docs/architecture.md` §5 "Value casting" (general rules 1–5, the type table, config scalars, inference, sub-decisions C-a..e) and the amended §6 rule 5.

Everything not marked PROVISIONAL is checked against approved text only (contracts, merged architecture including Q3, requirements).

## 2. Suite commands

Environment: Postgres 16 from the compose stack (`POSTGRES_PORT=55432 scripts/dev-up.sh` on this Mac, because Postgres.app holds 5432). Do not start a second stack (compose pins `container_name: localetl-db`).

```sh
export TEST_DATABASE_URL=postgresql+psycopg://localetl:localetl@127.0.0.1:55432/localetl_test
export DATABASE_URL=postgresql+psycopg://localetl:localetl@127.0.0.1:55432/localetl
python3.11 -m venv .venv && .venv/bin/pip install -e 'backend[dev]' pyyaml openapi-spec-validator

# Contracts
python contracts/tools/check_contracts.py .
npx @redocly/cli@1.25.0 lint contracts/openapi.yaml

# Backend (all: ETL, API, models)          # expected on main today: see section 6
pytest backend/tests
pytest backend/tests/etl                   # ETL unit
pytest backend/tests/api                   # API
pytest backend/tests/models                # needs Postgres, creates throwaway databases
cd backend && mypy app && mypy --strict app/etl && ruff check . && ruff format --check .

# Fixtures and integration
pytest tests/fixtures
pytest tests/integration                   # QA-05, QA-07 (Postgres)

# Frontend
npm --prefix frontend ci
npm --prefix frontend test && npm --prefix frontend run lint \
  && npm --prefix frontend run typecheck && npm --prefix frontend run build

# Generated-types drift
npx openapi-typescript contracts/openapi.yaml -o /tmp/schema.d.ts && diff /tmp/schema.d.ts frontend/src/app/api/schema.d.ts
```

`scripts/test-all.sh` (QA-04) will run all of the above in this order and is the single local entry point; CI (`.github/workflows/ci.yml`, QA-04) runs the same steps with a Postgres service. Wave 2 adds `npx playwright test` (QA-08).

## 3. Test data

`tests/fixtures/` (QA-03): 25 synthetic CSVs, 6 pipeline variants, `expected.json` (the five Q3 counters per scenario, reconciled), `generate_large.py` (1M rows, not committed). Fixture rows for `ragged_rows` and `duplicate_headers` are placeholders until QA-03c (Q4). Hostile identifiers, BOM, latin-1, all four delimiters, >500 columns, chunk-straddling duplicates and `drop_null_rows` scenarios exist.

## 4. Traceability matrix

Ticket column = ticket that must deliver the test. "Tests" are the files named on the board; test names are the engineer's choice unless stated.

### 4.1 Data sources

| REQ | Layer: test (ticket) | Status |
|---|---|---|
| REQ-01 upload one CSV; server-generated name; data source recorded | API: `test_sources.py` upload 201, stored path under `LOCALETL_DATA_DIR`, name not derived from the client filename, source row exists (BE-03). FE: upload form submits multipart (FE-03). INT: QA-07 upload step (QA-07). On a rejected upload the temp file is deleted and no source exists | Wave 1. **PROVISIONAL (Q4 §"CSV structure", file-level table)** for the rejected-upload effect (HTTP 422, temp file deleted, no source) |
| REQ-02 413 above `LOCALETL_MAX_UPLOAD_MB`, before the file is fully stored | API: oversized upload returns 413 `payload_too_large`; stored bytes stay below limit + one buffer; limit read from settings (BE-03). FE: client size check blocks before sending (FE-03). INT: QA-05 conformance of the 413 body (QA-05) | Wave 1 |
| REQ-03 four encodings, four delimiters, options at upload, defaults | ETL: parametrised over 4 encodings × 4 delimiters on fixtures, defaults applied (ETL-02). API: options echoed on the data source; invalid enum value → 422 (BE-03). FE: options form (FE-03) | Wave 1 |
| REQ-04 empty / header-only / undecodable / >500 columns rejected with clear message | ETL: one test per case raising `CsvFormatError` with a message naming the problem (ETL-02). API: each case → 422 with the message in the `Error` body, no source created (BE-03). INT: fixtures `empty`, `header_only`, `latin1_as_utf8`, `wide_501` (QA-07) | Wave 1 for the four listed cases. **PROVISIONAL (Q4 rules 1, 5)**: duplicate headers, undecodable bytes *anywhere* in the file (full pass at upload), unterminated quote, field > 131,072 chars, and sub-decision Q4-a (empty header names) |
| REQ-05 preview: names, inferred types, null counts, first N rows (default 50, max 500) | ETL: `preview_csv` limits, default and max; null counts on the sample (ETL-02). API: `limit` default 50, 501 → 422 (BE-03). FE: preview table rendered as text (FE-03). INT: QA-07 preview step | Wave 1 for limits, null counts and shape. **PROVISIONAL (Q6-3 "Type inference", rules 1, 3)**: the inferred type of every column (e.g. `0/1` → `integer`, `yes/no` → `boolean`, ISO-only dates, ASCII-only digits). **PROVISIONAL (Q4 "inspect_csv and preview_csv")**: preview skips malformed records, `sampled_rows` counts well-formed records |
| REQ-06 list (paginated), delete unreferenced | API: pagination bounds (limit 1–200); delete 204; delete of a referenced source → 409 `conflict`; 404 on unknown id (BE-03). MODEL: `pipelines.source_id` FK RESTRICT (BE-02, done). FE: list with pagination (FE-03) | Wave 1 |

### 4.2 Pipeline configurations

| REQ | Layer: test (ticket) | Status |
|---|---|---|
| REQ-10 CRUD of named pipelines, one source each | API: create 201, duplicate name 409, update bumps `config_version`, delete 204, delete with active run 409, unknown source 404 (BE-04). MODEL: `uq_pipelines_name`, FKs (BE-02, done). FE: create/edit/delete (FE-04) | Wave 1 |
| REQ-11 config conforms to `pipeline.schema.json`; field-level error paths | ETL: all `contracts/examples/pipeline/{valid,invalid}` behave as labelled; JSON Pointer paths with escaping (ETL-03, done). API: invalid config → 422 `validation_error` with `details[].path` (BE-04). FE: errors shown at the pointer path (FE-04). INT: QA-05 | Wave 1 for schema conformance and paths. **PROVISIONAL (Q6-3 §6 rule 5 amendment)** for the semantic "castable" checks (`fill_null`, `allowed_values`) |
| REQ-12 select/rename/type columns; identifier pattern `^[a-z_][a-z0-9_]{0,62}$` | ETL: `bad_target_identifier` example and hostile names rejected by the schema (ETL-03, done); casting to every target type (ETL-04); `_localetl_*`, type mapping §7.3 (ETL-06). FE: builder only emits valid identifiers (FE-04). INT: QA-07 published column types | Wave 1 for identifiers, select/rename and §7.3 type mapping. **PROVISIONAL (Q6-3 type table)**: the exact accepted text per target type |
| REQ-13 validate without persisting | API: `POST /pipelines/validate` returns `{valid, errors}`, never writes (row count of `pipelines` unchanged), `source_id` enables source-column check, unknown source 404 (BE-04). FE: validate button, errors at their path (FE-04). INT: QA-07 validate step | Wave 1. **PROVISIONAL (Q6-3)** only for castability errors |

### 4.3 Cleaning and validation

| REQ | Layer: test (ticket) | Status |
|---|---|---|
| REQ-20 fixed list of 7 operations, run in configured order | ETL: registry completeness test against the schema `op` enum; order test; one test per op including `deduplicate` across chunks (ETL-04). ETL: schema rejects unknown op (ETL-03, done). FE: builder offers exactly 7 ops and supports reordering (FE-04) | Wave 1. **PROVISIONAL (Q6-3)**: `fill_null` / `round_number` behaviour that depends on the cast value domain |
| REQ-21 fixed list of 6 validation rules | ETL: registry completeness test against the schema `rule` enum; each rule passing and failing (ETL-05). FE: builder offers exactly 6 rules (FE-04) | Wave 1. **PROVISIONAL (Q6-3)**: `allowed_values` and `range` comparisons use the cast values and config-scalar rules |
| REQ-22 rejection with row, column, rule, message; `reject_row` vs `fail_run` | ETL: one rejection entry per failing rule (ETL-05); `fail_run` raises `RejectionLimitExceeded` on the first rejection (ETL-05); `RejectedRow` shape (ETL-01, done). API: `/runs/{id}/rejections` paginated (BE-05). FE: rejections table (FE-05). INT: QA-07 dirty-values scenario | Wave 1 for validation rules and `reject_row` / `fail_run` on validation failures. **PROVISIONAL (Q6-3 rule 4, C-d)**: `type_cast` entries (message text, one entry per failing cell, raw value truncated to 500). **PROVISIONAL (Q4 rules 2–4, 8)**: `parse_error` entries (`column = null`, delimiter-joined value, "expected N fields, found M"). **PROVISIONAL (Q4-b)**: `fail_run` triggered by `parse_error` |
| REQ-23 `max_rejected_ratio` = rejected ÷ extracted | ETL: exceeded → `RejectionLimitExceeded`, nothing published; equal to the limit passes; dropped rows do not raise the ratio (denominator only) (ETL-05, ETL-07) | Wave 1. **PROVISIONAL (Q4)**: `parse_error` rows count in numerator and denominator |
| REQ-24 never execute user input | ETL/API: grep-style test that `app/` contains no `eval`, `exec`, `.query(`/`.eval(` on user strings (ETL-04, ETL-05); hostile regex/pattern, expression-looking values and column names treated as data (ETL-04/05, QA-07); regex pattern length cap (ETL-05). DOC: reviewed at every QA-06 gate | Wave 1 |
| REQ-25 every row has exactly one outcome; five counters reconcile | MODEL: both CHECK constraints (BE-02, done). ETL: identity asserted before publish (violation → `EtlError`, nothing published); identity after every chunk; counters identical for `chunk_rows` ∈ {1, 2, 7, 50000}; first removal wins (`nullable: false` + `drop_null_rows` → rejected); dedupe keeps the first occurrence across chunk boundaries (ETL-04, ETL-07). INT: for every succeeded scenario the five counters equal `expected.json` and `SELECT count(*)` of rows with the run's `_localetl_run_id` equals `loaded_count` (QA-07). API: Run exposes the five counters (BE-05). FE: drops shown separately from rejections (FE-05) | Wave 1. **PROVISIONAL (Q4 "Row outcome accounting for these cases")**: `parse_error` rows are in `rejected_count`, blank lines are in no counter, `extracted_count` equals `DataSource.row_count` |

### 4.4 PostgreSQL loading

| REQ | Layer: test (ticket) | Status |
|---|---|---|
| REQ-30 staging then publish in one transaction; failure never changes published table | ETL: staging name `staging.run_<hex>`; failure at each stage leaves the published table unchanged and drops staging (ETL-06, ETL-07). INT: failing pipeline publishes nothing; interrupted run drops staging (QA-07) | Wave 1 |
| REQ-31 `replace` and `append`; append mismatch fails the run | ETL: replace → exactly this run's rows; append adds rows; column set/type mismatch → `LoadError`, table unchanged (ETL-06). INT: row counts in `datasets.*` after replace and append match fixture expectations (QA-07) | Wave 1 |
| REQ-32 bound parameters; validated, quoted identifiers | ETL: hostile table/column names (quotes, semicolons, unicode, 63-char limit) neither inject nor break (ETL-06). API: sort column validated against the registry (BE-06). INT: QA-07 hostile-name scenario. DOC: review checks no string-built SQL with user values | Wave 1 |
| REQ-33 credentials only from environment | DOC/CFG: settings tests read from env (BE-01, done; a `Settings` parsing test was suggested for BE-02/BE-04); grep that `alembic.ini` has no URL; `.env` git-ignored (QA-04 CI check) | Wave 1 |

### 4.5 Job execution and monitoring

| REQ | Layer: test (ticket) | Status |
|---|---|---|
| REQ-40 manual run; API queues and returns at once; a worker executes | API: `POST /pipelines/{id}/runs` returns 202 `queued` with config snapshot and never runs the ETL (BE-05). INT: QA-07 queues a run via the API. FE: run button (FE-05). INT/E2E: the worker actually executes the run | Wave 1 for queuing. **Wave 2** for execution (WK-01, WK-02, QA-08) |
| REQ-41 five states; one `running`; no two active runs per pipeline | MODEL: both partial unique indexes reject the second row (BE-02, done). API: second run for a pipeline → 409 (BE-05). INT: QA-07 "queue → 409 on second". FE: 409 shown clearly (FE-05) | Wave 1 |
| REQ-42 stage events with counts; UI polls to a terminal state | ETL: stage order, `started`/`completed`/`failed` per stage, at least one `progress` per chunk, counters cumulative and non-decreasing (ETL-07). API: `/runs/{id}/events` (BE-05). FE: polling every 2 s that stops at terminal states (FE-05). Worker persists events with counters (WK-02) | Wave 1 for ETL, API, FE. **Wave 2** for the worker side |
| REQ-43 stale `running` run becomes `interrupted` at worker start | MODEL: status/CHECK allow it (BE-02, done). Worker: recovery query on stale heartbeat, counters unchanged (WK-01) | **Wave 2** |
| REQ-44 SIGINT/SIGTERM: stop claiming, stop at next boundary, `interrupted`, exit | ETL: `should_stop` raises `RunInterrupted`, staging dropped, nothing published (ETL-07). Worker: signal handling (WK-03) | ETL part Wave 1; worker part **Wave 2** |

### 4.6 History, metrics, datasets

| REQ | Layer: test (ticket) | Status |
|---|---|---|
| REQ-50 history newest first, filterable, paginated | API: ordering, `pipeline_id` and `status` filters, limit/offset bounds, invalid status → 422 (BE-05). FE: history list with filters (FE-05) | Wave 1 |
| REQ-51 run exposes five counters, duration, error, rejections (≤ 1,000) | API: all fields per contract; rejections paginated; at most 1,000 stored (BE-05). INT: QA-05 conformance. FE: run detail (FE-05) | Wave 1. **PROVISIONAL (Q4)**: `parse_error` rows appear in the rejections list as `parse_error` entries |
| REQ-52 metrics summary | API: counts by status, `loaded_count_total` and daily `loaded_count` from succeeded runs only, zero-filled 30 days, `days` bounds (BE-06). FE: metrics as text (FE-05); charts Wave 2 (VIZ-01) | Wave 1 (API, text); **Wave 2** (charts) |
| REQ-53 datasets list; rows with pagination and single-column sort | API: list, detail, rows with sort validated against the registry columns, `_localetl_*` hidden (BE-06). INT: QA-07 reads a published dataset. FE: explorer (VIZ-02) | API Wave 1; FE **Wave 2** |
| REQ-54 column profile (null, distinct, min/max, top 10) | API: profile per column type; numeric/date min/max, top 10 (BE-06) | Wave 1 (API). Charts **Wave 2** (VIZ-02) |
| REQ-55 basic charts | FE: chart components render from fixtures (VIZ-01, VIZ-02). E2E: charts visible after a run (QA-08) | **Wave 2** |

### 4.7 Non-functional

| REQ | Layer: test (ticket) | Status |
|---|---|---|
| REQ-60 local only: bind 127.0.0.1; CORS limited | API: settings default host; CORS allows only `LOCALETL_CORS_ORIGINS` and rejects another origin (BE-01 done; extend in BE-03); compose publishes Postgres on 127.0.0.1 only (QA-01, done) | Wave 1 |
| REQ-61 1M rows × 10 columns replace run < 5 min; chunked, memory bounded | INT: manual/nightly benchmark using `tests/fixtures/generate_large.py`, records wall time and peak RSS; not part of the default suite (QA-07 or a Wave 2 task). ETL: chunking invariants with small `chunk_rows` (ETL-07) | Wave 1 for chunk invariants; benchmark on request. **PROVISIONAL (Q4 "Chunks")**: `chunk_rows` counts records including malformed ones; a record is never split across chunks |
| REQ-62 type hints, mypy; TS strict | CI: `mypy app`, `mypy --strict app/etl`, `tsc` via `npm run typecheck` (QA-04). FE: typecheck proven non-vacuous (FE-02) | Wave 1 |
| REQ-63 automated tests for every component; recorded E2E demo | DOC: this matrix and QA-06 reviews; E2E: Playwright flow upload → configure → run → monitor → results and charts (QA-08) | Matrix Wave 1; demo **Wave 2** |
| REQ-64 `.env` and uploaded data never committed | CFG: `.gitignore` covers `.env`, `data/`; QA-04 CI step fails if a tracked file matches those patterns | Wave 1 |

### 4.8 Requirements added to the provisional list beyond the orchestrator's minimum

Beyond REQ-04, REQ-05, REQ-22, REQ-25 (Q4) and REQ-05, REQ-12, REQ-22, REQ-11/13 / §6 rule 5 (Q6-3), I also marked: **REQ-01** (Q4: rejected-upload effects), **REQ-20 and REQ-21** (Q6-3: cast-value semantics of `fill_null`, `allowed_values`, `range`), **REQ-23** (Q4: `parse_error` in the ratio), **REQ-51** (Q4: `parse_error` rows in the rejections list), **REQ-61** (Q4: chunk definition). Open sub-decisions that change test expectations: Q4-a (empty header names), Q4-b (`fail_run` on `parse_error`), Q4-c (malformed rows invisible before a run), Q4-d (width without header), C-a (whitespace-only cell), C-b (config dates ISO only), C-c (string-column config values), C-d (entry per failing cell), C-e (date-format directives).

## 5. Cross-cutting checks (every ticket, via QA-06)

Contract check and Redocly lint 0 failures; ownership of changed paths against architecture §3; `app.etl` imports nothing from FastAPI or other `app.*` packages; no `eval`/`exec`; type hints and `mypy`; no secrets; rebased on `main` with the suites re-run; for contract-facing tickets, the served OpenAPI equals `contracts/openapi.yaml` (BE-06 drift test) and `schema.d.ts` regenerates byte-identically.

## 6. Current suite baseline on `main`

| Suite | Count | Source |
|---|---|---|
| `pytest backend/tests` | 102 (ETL 64, API 9, models 29) | QA-06 review of ETL-03 at `0f56443` (main 65b093f); re-run after merges |
| `pytest tests/fixtures` | 20 | QA-03 (`a141eee` rebased) |
| `npm --prefix frontend test` | 19 (FE-02 branch; 7 on main until FE-02 merges) | QA-06 re-check at `4890451` |

## 7. Wave 1 exit criteria

Wave 1 exits only when all of these hold (runbook "Wave 1 exit"):
1. **Every Wave 1 ticket is Done** (merged after QA PASS): ETL-01..07, BE-01..06 (incl. BE-01b), FE-01..05, QA-01..07 (incl. QA-03).
2. **`scripts/test-all.sh` is green on `main`**: contract check, Redocly lint, backend pytest + mypy + ruff, frontend test/lint/typecheck/build, fixtures, integration.
3. **QA-07 is PASS**: via the API upload → preview → create → validate → queue (`queued`, 409 on the second); direct `run_pipeline` replace and append counts and the five Q3 counters match `expected.json` and reconcile; published row count equals `loaded_count`; failing pipeline publishes nothing; interrupted run drops staging.
4. **No open contract proposals.** In particular, Q4 (CSV structure) and Q6-3 (casting) are decided and merged, every test marked PROVISIONAL in section 4 is re-checked against the approved text, and QA-03c replaces the `ragged_rows` / `duplicate_headers` fixture placeholders.
5. **Contract drift test passes** (BE-06) and `schema.d.ts` regenerates byte-identically.

Not part of the Wave 1 exit (Wave 2): worker execution and recovery (REQ-40 execution, REQ-43, REQ-44 worker side), charts and the dataset explorer (REQ-52 charts, REQ-53 UI, REQ-55), and the Playwright E2E demo (REQ-63).
