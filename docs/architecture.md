# LocalETL Architecture

Status: Wave 0 baseline · Owner: orchestrator · Changes require orchestrator approval.

Contracts referenced here are binding: `contracts/openapi.yaml` (HTTP) and `contracts/pipeline.schema.json` (pipeline configs). Sections 5 (ETL engine interface) and 7 (database) are the binding internal interfaces between agents.

## 1. Components

```
 Browser ──HTTP/JSON──► FastAPI (backend/app/api)  ──SQLAlchemy──►  PostgreSQL
 (React, frontend/)          │  queues runs                         ├─ public.*   app metadata (Alembic)
                             │  calls etl.preview / etl.validate    ├─ staging.*  per-run staging tables
                             ▼                                      └─ datasets.* published tables
                      backend/app/etl  ◄── run_pipeline ── Worker process (backend/app/worker)
                      (pure library)                         claims queued runs, persists events/metrics
```

| Component | Runs as | Talks to |
|---|---|---|
| Frontend | Vite dev server, `127.0.0.1:5173` | API only, over HTTP (`VITE_API_URL`) |
| API | `uvicorn app.main:app --host 127.0.0.1 --port 8000` from `backend/` | PostgreSQL; ETL engine (preview, validate only) |
| Worker | `python -m app.worker` from `backend/` | PostgreSQL; ETL engine (`run_pipeline`) |
| ETL engine | Library imported by API and worker; also usable from a plain script | PostgreSQL via an `Engine` passed in by the caller |
| PostgreSQL 16 | `docker compose up -d db`, `127.0.0.1:5432` | none |

The API never runs pipelines. The frontend never touches the database. The ETL engine never touches `public.*` metadata tables.

## 2. Toolchain

| Area | Choice |
|---|---|
| Python | 3.11, `venv` + `pip`, single project at `backend/pyproject.toml` (packages `app`, `app.etl`, `app.worker`) |
| Python libs | FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 (Core + ORM), psycopg 3, Alembic, pandas, jsonschema, python-multipart, uvicorn |
| Python dev | pytest, mypy (`strict` for `app.etl`), ruff, httpx, pandas-stubs, PyYAML and openapi-spec-validator (contract tooling and the QA-05 conformance harness; added 2026-10-20) |
| Node | ≥ 20 (developed on 23), npm, project at `frontend/package.json` |
| Frontend libs | React 18, React Router 6, Tailwind CSS 3, Recharts 2, openapi-typescript (types generated from `contracts/openapi.yaml`) |
| Frontend dev | Vite 5, Vitest, React Testing Library, ESLint, TypeScript strict |
| E2E | Playwright, in `tests/e2e/` |
| DB | PostgreSQL 16 via Docker Compose |

Dependencies beyond this list need a justification in the completion report (CLAUDE.md rule 4).

## 3. Repository layout and ownership

Only the owner edits a path. Others propose changes in their completion report.

| Path | Owner |
|---|---|
| `CLAUDE.md`, `README.md`, `.gitignore`, `.env.example`, `.claude/agents/`, `docs/requirements.md`, `docs/architecture.md`, `docs/task-board.md`, `docs/assignments/`, `contracts/` | orchestrator |
| `backend/pyproject.toml` | backend-engineer creates it in BE-01; after merge it becomes **orchestrator-owned** (dependency additions by proposal) |
| `backend/app/main.py`, `backend/app/core/` (settings, DB engine/session, error handlers), `backend/app/api/`, `backend/app/models/`, `backend/app/schemas/`, `backend/alembic.ini`, `backend/migrations/`, `backend/tests/conftest.py`, `backend/tests/api/`, `backend/tests/models/` | backend-engineer |
| `backend/app/etl/`, `backend/tests/etl/` | etl-engineer |
| `backend/app/worker/`, `backend/app/services/runs/`, `backend/tests/worker/` | worker-engineer |
| `frontend/` root config (`package.json`, `vite.config.ts`, `tsconfig*.json`, `tailwind.config.ts`, `eslint.config.js`, `index.html`), `frontend/src/main.tsx`, `frontend/src/app/` (shell, router, providers, `app/api/` client and generated types), `frontend/src/pages/`, `frontend/src/components/`, `frontend/src/features/pipelines/`, `frontend/src/test/` | frontend-engineer |
| `frontend/src/features/analytics/`, `frontend/src/features/explorer/` | visualization-engineer |
| `tests/` (fixtures, integration, e2e), `scripts/`, `docs/qa/`, `.github/workflows/`, `docker-compose.yml` | qa-engineer |

Unit tests live with their owner: `backend/tests/<area>/` for Python and colocated `*.test.ts(x)` inside owned frontend directories. `tests/` at the repo root is for cross-component tests only.

### Import rules (enforced by review)
- `app.etl` may import only the standard library, pandas, numpy, SQLAlchemy and jsonschema. It must **not** import `app.api`, `app.models`, `app.schemas`, `app.core`, `app.worker` or `app.services`, or FastAPI.
- `app.api` may import `app.etl` public names (section 5) only: `from app.etl import ...`, never submodules.
- `app.worker` / `app.services.runs` may import `app.etl` public names, `app.models` and `app.core.db`.
- `app.models` imports nothing from `app.api`, `app.etl` or `app.worker`.

## 4. Configuration (environment variables)

All read through `app.core.settings` (pydantic-settings) except the ETL engine, which receives values as arguments. `.env.example` is the reference copy.

| Variable | Default | Used by |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://localetl:localetl@127.0.0.1:5432/localetl` | API, worker, migrations |
| `TEST_DATABASE_URL` | `postgresql+psycopg://localetl:localetl@127.0.0.1:5432/localetl_test` | pytest |
| `LOCALETL_DATA_DIR` | `./data` (relative to repo root) | API (uploads), worker (reads sources) |
| `LOCALETL_MAX_UPLOAD_MB` | `100` | API |
| `LOCALETL_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | API |
| `LOCALETL_CHUNK_ROWS` | `50000` | worker → `run_pipeline` |
| `WORKER_POLL_INTERVAL_SECONDS` | `2` | worker |
| `WORKER_HEARTBEAT_SECONDS` | `10` | worker |
| `WORKER_STALE_AFTER_SECONDS` | `60` | worker (crash recovery) |
| `VITE_API_URL` | `http://127.0.0.1:8000/api/v1` | frontend |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `localetl` ×3 | docker-compose only |

Uploads are stored as `${LOCALETL_DATA_DIR}/sources/<source_id>.csv`. Nothing under `data/` is committed.

## 5. ETL engine interface (`app.etl`)

The engine is a library. Everything below is exported from `backend/app/etl/__init__.py`; nothing else is public. Signatures are binding; internal module layout is the ETL engineer's choice (suggested: `types.py`, `errors.py`, `config.py`, `extract.py`, `transform.py`, `validate.py`, `load.py`, `runner.py`).

```python
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa

ColumnType = Literal["integer", "float", "boolean", "date", "datetime", "string"]
Stage = Literal["extract", "transform", "validate", "load", "publish"]
EventStatus = Literal["started", "progress", "completed", "failed"]
RejectionRule = Literal["not_null", "unique", "range", "allowed_values", "regex", "length", "type_cast", "parse_error"]

@dataclass(frozen=True)
class CsvOptions:
    encoding: Literal["utf-8", "utf-8-sig", "latin-1", "cp1252"] = "utf-8"
    delimiter: Literal[",", ";", "\t", "|"] = ","
    has_header: bool = True
    quote_char: str = '"'

@dataclass(frozen=True)
class ColumnInfo:
    name: str
    inferred_type: ColumnType
    null_count: int

@dataclass(frozen=True)
class CsvProfile:                 # returned by inspect_csv, stored on the data source
    columns: list[ColumnInfo]
    row_count: int

@dataclass(frozen=True)
class CsvPreview:
    columns: list[ColumnInfo]
    rows: list[dict[str, str | None]]
    sampled_rows: int

@dataclass(frozen=True)
class ConfigErrorItem:
    path: str                      # JSON Pointer into the config, e.g. "/transformations/2/columns"
    message: str

@dataclass(frozen=True)
class PipelineConfig:              # parsed, validated form of pipeline.schema.json; fields mirror the schema
    raw: Mapping[str, Any]         # the original JSON document
    ...                            # typed fields are the ETL engineer's choice

@dataclass(frozen=True)
class RunCounters:                 # same five fields, same order, as RunResult and the HTTP Run
    extracted_count: int
    loaded_count: int              # 0 until the publish transaction commits
    rejected_count: int
    duplicate_dropped_count: int
    null_dropped_count: int

@dataclass(frozen=True)
class StageEvent:
    stage: Stage
    status: EventStatus
    rows_in: int | None
    rows_out: int | None
    message: str | None
    at: datetime                   # UTC
    counters: RunCounters          # cumulative for the whole run after this event

@dataclass(frozen=True)
class RejectedRow:
    row_number: int                # 1-based data row (header excluded)
    column: str | None
    rule: RejectionRule
    message: str
    value: str | None              # truncated to 500 chars

@dataclass(frozen=True)
class PublishedTable:
    schema: Literal["datasets"]
    table: str
    columns: list[tuple[str, ColumnType]]
    row_count: int                 # rows in the published table after publish

@dataclass(frozen=True)
class RunResult:                   # row counters: see "Row outcome accounting" below
    extracted_count: int           # data rows read from the source file (header excluded)
    loaded_count: int              # rows committed to the published table by this run's publish transaction
    rejected_count: int            # rows that failed parsing, casting or a validation rule (counted once per row)
    duplicate_dropped_count: int   # rows removed by `deduplicate`
    null_dropped_count: int        # rows removed by `drop_null_rows`
    rejected_sample: list[RejectedRow]   # first 1,000 rejection entries, row order
    published: PublishedTable
    stage_durations_ms: dict[Stage, int]

# Errors
class EtlError(Exception): ...
class CsvFormatError(EtlError): ...          # file-level (Q4): empty, header-only, undecodable, > 500 columns, duplicate headers, unrecoverable structure
class ConfigValidationError(EtlError):
    errors: list[ConfigErrorItem]
class SourceMismatchError(EtlError): ...     # config references columns absent from the CSV
class RejectionLimitExceeded(EtlError): ...  # fail_run triggered or max_rejected_ratio exceeded
class LoadError(EtlError): ...               # DB failure, append schema mismatch
class RunInterrupted(EtlError): ...          # should_stop() returned True

# Functions
def inspect_csv(path: Path, options: CsvOptions, *, sample_rows: int = 1000) -> CsvProfile: ...
def preview_csv(path: Path, options: CsvOptions, *, limit: int = 50) -> CsvPreview: ...
def validate_pipeline_config(config: Mapping[str, Any],
                             *, source_columns: list[str] | None = None) -> PipelineConfig: ...
def run_pipeline(config: PipelineConfig,
                 source_path: Path,
                 csv_options: CsvOptions,
                 engine: sa.Engine,
                 run_id: UUID,
                 *,
                 chunk_rows: int = 50_000,
                 on_event: Callable[[StageEvent], None] | None = None,
                 should_stop: Callable[[], bool] | None = None) -> RunResult: ...
```

### Behaviour contract
- `inspect_csv` / `preview_csv` raise `CsvFormatError` for the file-level cases in REQ-04 and "CSV structure and malformed input" below. `inspect_csv` reads the whole file in one streaming pass (`row_count` needs it), so file-level faults anywhere in the file are found at upload. Type inference uses the same parsers as casting. When `has_header` is false, columns are named `column_1`, `column_2`, …
- `validate_pipeline_config` validates against `contracts/pipeline.schema.json`, loaded from `Path(__file__).resolve().parents[3] / "contracts" / "pipeline.schema.json"` (override: `LOCALETL_PIPELINE_SCHEMA_PATH`, read by the caller and passed in only if needed). Then it applies the semantic rules in section 6. All problems are collected into one `ConfigValidationError`.
- `run_pipeline` re-validates the config, then runs the stages in order, calling `on_event` with `started` and `completed`/`failed` for each stage (and `progress` per chunk). It checks `should_stop()` between chunks and stages and raises `RunInterrupted` (staging dropped, nothing published).
- On any exception, the staging table is dropped and the published table is untouched.
- `run_pipeline` never writes to `public.*`. Persisting events, rejections, run counters and the `datasets` registry row is the worker's job.

### Row outcome accounting (decision Q3, approved 2026-10-19)

Every extracted row ends in **exactly one** outcome. Rows intentionally removed by configured cleaning operations are **not** rejections.

| Outcome | Counter | Assigned when |
|---|---|---|
| Rejected | `rejected_count` | the row fails parsing (`parse_error`), casting (`type_cast`), a `nullable: false` check (`not_null`), or any rule in `validations` |
| Duplicate-dropped | `duplicate_dropped_count` | a `deduplicate` operation removes the row |
| Null-dropped | `null_dropped_count` | a `drop_null_rows` operation removes the row |
| Loaded | `loaded_count` | the row is committed to the published table by this run's publish transaction (for `append`, rows inserted by this run, not the table total; that is `PublishedTable.row_count`) |

Rules:
1. **First removal wins.** A row is classified by the first stage step that removes it, in pipeline order: extract → cast and `nullable` check → `transformations` in array order → `validations` → load. Example: with `nullable: false` and `drop_null_rows` on the same column, a null is **rejected** (`not_null`), because the nullable check runs before transformations.
2. **Rows, not entries.** `rejected_count` counts rows. A row failing several rules counts once in `rejected_count`, but yields one `RejectedRow` entry per failing rule.
3. **Reconciliation.** For every `succeeded` run:
   `extracted_count = loaded_count + rejected_count + duplicate_dropped_count + null_dropped_count`.
   `run_pipeline` asserts this before publishing and raises `EtlError` if it does not hold. The database enforces it with a CHECK constraint (§7.1).
4. **Chunk invariant.** After every completed chunk, for the rows seen so far: `extracted_count = staged + rejected_count + duplicate_dropped_count + null_dropped_count`, where `staged` is the rows written to the staging table. `loaded_count` stays 0 until the publish transaction commits; it is then set to `staged`. If publish rolls back, `loaded_count` stays 0.
5. **Across chunks.** `deduplicate` and `unique` keep the **first** occurrence across the whole file and act on later ones. A key is registered by the first row that *reaches* that step, even if that row is later rejected by a validation rule. Rows removed earlier (rejected at cast, or dropped by an earlier operation) never register keys.
6. **Rejection ratio.** `max_rejected_ratio` compares `rejected_count / extracted_count`. Dropped rows count in the denominator only.
7. **Unsuccessful runs.** For `failed` and `interrupted` runs, nothing is published, so `loaded_count = 0`. The other counters are the `counters` of the last `StageEvent` emitted before the stop, i.e. rows fully processed (whole chunks). The identity is not enforced.
8. Transform events report `rows_in`/`rows_out` per chunk. The difference equals the rows rejected at cast plus rows dropped by operations in that chunk.
9. **Reporting.** Every `StageEvent` carries a cumulative `RunCounters` snapshot; `progress` events are emitted at least once per chunk. The final `publish`/`completed` event's counters equal the `RunResult` counters. Counters never decrease within a run.

### CSV structure and malformed input (decision Q4, approved 2026-10-20)

> Approved by the user 2026-10-20, with sub-decisions Q4-a to Q4-d as recommended (listed at the end of this section). Empty or duplicate header names reject the file; records with missing or extra fields are rejected as `parse_error`; unrecoverable quoting, decoding and structural failures are extraction errors.

Terms. A **record** is one logical CSV row as tokenized with the source's `CsvOptions`; a quoted field may span several physical lines. The **expected width** is the number of fields in the header record (`has_header: true`) or in the first record (`has_header: false`). A **blank line** is a physical line with no characters before its line terminator; it is not a record.

Every problem is either **file-level** or **row-level**:

| Level | Raised as | Detected by | Effect |
|---|---|---|---|
| File | `CsvFormatError` | `inspect_csv` / `preview_csv`; `run_pipeline` extract | Upload: HTTP 422 `validation_error` with the error message, temp file deleted, no source created (§8). Run: run `failed` at `extract`, nothing published |
| Row | `RejectedRow(rule="parse_error", column=None)` | `run_pipeline` extract | Row counts in `extracted_count` and `rejected_count`; the run continues per `on_validation_failure` |

Rules:
1. **Empty or duplicate header names → file-level (Q4-a).** Header values are compared exactly: case-sensitive, no trimming, after the BOM is removed by `utf-8-sig`. An empty header value is rejected first, with its 1-based position (`header in column 2 is empty`). Otherwise the message names every duplicated header with its 1-based column positions, e.g. `duplicate header names: "id" (columns 1, 5), "name" (columns 2, 3)`. Not applicable when `has_header` is false.
2. **Too many fields → row-level `parse_error`.** Includes a trailing delimiter (`1,a,` against a 2-column header): empty trailing fields are not trimmed. Message: `expected N fields, found M`.
3. **Too few fields → row-level `parse_error`.** A record with at least one but fewer than the expected fields is never padded with nulls. Message as in rule 2.
4. **Recoverable quoting fault → row-level `parse_error`.** A fault confined to one record, such as characters after a closing quote (`"a"b`). Tokenizing resumes at the next line. A quote character inside an unquoted field (`ab"c`) is literal data, not an error.
5. **Unrecoverable structure → file-level.** A quoted field still open at end of file; a single field longer than 131,072 characters (the tokenizer's field limit, almost always a runaway quote); bytes undecodable in the chosen encoding anywhere in the file. These join the existing REQ-04 cases: empty file, header-only (no records after the header), expected width over 500.
6. **Blank lines** are skipped everywhere. They are not records, consume no row number and count in no counter. A whitespace-only line is a record with one field.
7. **Row numbers.** `RejectedRow.row_number` is the 1-based ordinal of the record among data records (header and blank lines excluded), global across chunks. It is the same numbering every other rule uses.
8. **`parse_error` entries** have `column = null` and `value` = the record's fields joined with the source delimiter, truncated to 500 characters. One entry per malformed record.
9. **First removal wins (Q3 rule 1).** Extract is the first step, so a `parse_error` row reaches no later stage and never registers `deduplicate` or `unique` keys.

Row outcome accounting (Q3) for these cases:

| Case | `extracted_count` | `rejected_count` | Other counters | `RejectedRow` |
|---|---|---|---|---|
| Duplicate headers, unrecoverable structure (at upload) | n/a: no source, no run | n/a | n/a | none |
| Too many / too few fields, recoverable quoting fault | +1 | +1 | unchanged | one, `parse_error` |
| Blank line | 0 | 0 | 0 | none |
| File-level fault found during a run | records of the whole chunks completed before the fault | same | `loaded_count = 0` | as emitted so far |

- The identity `extracted = loaded + rejected + duplicate_dropped + null_dropped` holds unchanged; `parse_error` rows sit in `rejected_count`.
- For a full run, `extracted_count` equals the source's `DataSource.row_count`.
- `max_rejected_ratio` counts `parse_error` rows in the numerator and the denominator.
- With `on_validation_failure: fail_run`, the first rejection of **any** kind (`parse_error`, `type_cast`, `not_null` or a validation rule) raises `RejectionLimitExceeded` (Q4-b).

Chunks:
- `chunk_rows` counts records, including malformed ones; blank lines are not counted. Chunk boundaries therefore depend only on the file, not on which records are malformed.
- A record is never split across chunks, including a quoted field that spans several lines.
- Malformed records are reported in the chunk where they occur. Counters are cumulative and identical for every `chunk_rows` (ETL-07 criterion).
- A file-level fault found in chunk *k* fails the run at `extract`. Chunks before *k* are already reported; nothing is published (Q3 rule 7).
- Because `inspect_csv` makes a full pass at upload, the run-time file-level path normally fires only if the stored file changed or was corrupted after upload.

`inspect_csv` and `preview_csv`:
- `row_count` counts every data record, malformed included, and excludes blank lines.
- Type inference and `null_count` use the first `sample_rows` well-formed records.
- `preview_csv` returns the first `limit` well-formed records. `sampled_rows` is the number of well-formed records examined.
- **Preview limitation (Q4-c).** Malformed records are **excluded** from preview `rows`, from type inference and from `null_count`, because they cannot be keyed by column without guessing. They **are** counted in `row_count`. A source can therefore show a clean preview and still produce `parse_error` rejections when a pipeline runs; the preview does not report how many records are malformed. Documented in the contract (`CsvPreview`, `DataSource.row_count`, `ColumnInfo.null_count`) and REQ-05; no new contract field.

Implementation constraint. Observed 2026-10-20 with pandas 2.3.3 on the QA-03 fixtures, `pandas.read_csv` cannot produce the outcomes above:
- the default C parser fails the whole read on the first extra field;
- both C and python engines pad short rows with nulls silently;
- duplicate headers are renamed silently to `name.1`, `id.1`;
- the python engine with `on_bad_lines` silently drops a record with an unterminated quote;
- when the first data row has one extra field, the first column silently becomes the index, shifting every value one column.

Extract therefore tokenizes with the stdlib `csv.reader(strict=True)`, using the source's delimiter and quote character, over a text stream opened with `newline=""` and strict decoding. Each chunk is built as a pandas DataFrame of strings. No new dependency. Internal structure stays the ETL engineer's choice, as long as this behaviour holds and is tested.

Decisions (user, 2026-10-20):
- **Q4-a:** empty header names reject the file, like duplicates (rule 1).
- **Q4-b:** `fail_run` triggers on the first rejection of any kind, `parse_error` included.
- **Q4-c:** malformed records are excluded from preview and inference but included in `row_count`; the limitation is documented (above). No `malformed_row_count` field.
- **Q4-d:** without a header, the expected width is the field count of the first record. If that record is malformed, the others are rejected; this is accepted.

### Stage semantics
1. **extract**: tokenize the file per "CSV structure and malformed input" (stdlib `csv` reader, strict quoting) into chunks of `chunk_rows` records, kept as strings. Empty strings become null. Malformed records → `parse_error` rejection; unrecoverable structure → `CsvFormatError`.
2. **transform**: (a) select `columns[].source` and rename to `columns[].name`; (b) cast to `columns[].type` per "Value casting" below; cast failures → `type_cast` rejection; `nullable: false` nulls → `not_null` rejection; (c) apply `transformations` in array order.
3. **validate**: apply each `validations` rule; each failing row yields one `RejectedRow` entry per failing rule and counts once in `rejected_count`. `unique` and `deduplicate` track seen keys across chunks. With `on_validation_failure: fail_run`, the first rejection of any kind in the run (parse, cast, `not_null` or a validation rule; Q4-b) raises `RejectionLimitExceeded`. After all chunks, if `rejected_count / extracted_count > max_rejected_ratio`, raise `RejectionLimitExceeded`. Null handling, composite `unique` values, `fail_run` timing and checkpoints follow "Validation semantics (Q7)".
4. **load**: rows are appended to `staging.run_<run_id hex>`, created with column types from section 7.3.
5. **publish** (one transaction): `replace` → drop `datasets.<table>` if present, then `ALTER TABLE staging.run_<hex> SET SCHEMA datasets` and rename it to `<table>`. `append` → create `datasets.<table>` like staging if absent; otherwise require an identical column name/type list (else `LoadError`), then `INSERT INTO datasets.<table> SELECT * FROM staging...` and drop staging.

### Value casting (decision Q6-3, approved 2026-10-20)

> Approved by the user 2026-10-20 with C-a to C-e as recommended, including the strict integer, float, date and datetime rules. CSV casting (transform stage 2b), type inference (`inspect_csv`) and config castability (§6 rule 5, ETL-03) use **one set of shared casting functions** (`backend/app/etl/casting.py`, ETL-03b), so they cannot drift.

**Scope.** (A) CSV cells cast in transform stage 2(b). (B) Config scalars: `fill_null.value`, `allowed_values.values`, `range.min`/`range.max`. §6 rule 5 ("castable") means "(B) succeeds". `inspect_csv` type inference uses (A).

General rules:
1. **Input.** A CSV cell is a `str` or null; extract has already turned empty strings into null. For non-string types the value is stripped with Python `str.strip()` first. If the stripped value is empty, it is **null** (sub-decision C-a). `string` values are never stripped; `trim_whitespace` does that.
2. **Nulls are never cast.** A null in a `nullable: false` column is a `not_null` rejection, never `type_cast`.
3. **ASCII only.** Digits are `0-9` only. Rejected: non-ASCII digits (`١٢`), underscores (`1_000`), thousands separators (`1,000`), decimal commas (`1,5`). Python's `\d`, `int()` and `float()` accept some of these, so a cast must not rely on them alone.
4. **Failures.** Each cell that fails is one `RejectedRow(rule="type_cast", column=<target name>, value=<raw cell, truncated to 500>, message='cannot cast "<v>" to <type>' plus ' with format <f>' when set)`. All columns of a row are cast, so a row with several bad cells gets several entries but counts once (Q3 rule 2) (sub-decision C-d).
5. **Determinism.** Casting is a pure function of the value, the type and the format. It gives the same result in every chunk and in `inspect_csv`.

| Type | CSV text accepted (after rule 1) | Result | Rejected examples |
|---|---|---|---|
| `integer` | fullmatch `[+-]?[0-9]+`, value within PostgreSQL `bigint` (−2^63 … 2^63−1); leading zeros allowed | `int` | `1.0`, `1e3`, `9223372036854775808`, `١٢`, `1_000` |
| `float` | fullmatch `[+-]?([0-9]+(\.[0-9]*)?\|\.[0-9]+)([eE][+-]?[0-9]+)?`, result finite | `float` (`double precision`) | `nan`, `inf`, `1e400`, `1,5`, `1_0.5` |
| `boolean` | case-insensitive `true`/`false`, `yes`/`no`, `1`/`0` | `bool` | `t`, `y`, `on`, `2` |
| `date`, with `format` | `datetime.strptime(v, format)` matches the whole value; the format contains no time directive (`%H` `%I` `%M` `%S` `%f` `%p` `%X` `%c`) and no zone directive (`%z` `%Z`) (C-e) | `date` | value not matching the format |
| `date`, no `format` | ISO calendar date only: fullmatch `[0-9]{4}-[0-9]{2}-[0-9]{2}` and a valid date | `date` | `20261020`, `2026-W43-2`, `2026-10-20T00:00`, `2026-02-30` |
| `datetime`, with `format` | `datetime.strptime(v, format)`; the format contains no zone directive (`%z` `%Z`) (C-e) | naive `datetime` | value not matching the format |
| `datetime`, no `format` | `YYYY-MM-DD` + `T` or one space + `HH:MM[:SS[.f{1,6}]]`, no offset and no `Z` | naive `datetime` (`timestamp`, §7.3) | `2026-10-20T10:00Z`, `2026-10-20T10:00+02:00`, `20261020T1000`, `2026-10-20` |
| `string` | anything (unchanged) | `str` | none |

Notes: `%y` uses Python's pivot (`69`–`99` → 19xx, `00`–`68` → 20xx). Values with an offset are rejected rather than converted, because §7.3 stores naive timestamps and a silent conversion would lose information.

**Config scalars (B)**, i.e. JSON `ScalarValue` (string, number, boolean):

| Type | Accepted |
|---|---|
| `integer` | JSON integer within `bigint`; a JSON number with zero fraction (`1.0`, which JSON does not distinguish from `1`); a string per the CSV rule. Never a boolean |
| `float` | finite JSON number (not boolean); a string per the CSV rule |
| `boolean` | JSON `true`/`false`; numbers `0`/`1`; a string per the CSV rule |
| `date`, `datetime` | a JSON string in the **ISO** form of the "no `format`" rows above. The column's `format` applies only to CSV cells, never to config values (C-b); this is consistent with §6 rule 4 for range bounds |
| `string` | a JSON string only (C-c); `5` is not a value for a string column |

Comparisons (`allowed_values`, `range`, `unique`, `deduplicate`) use the cast values. String comparison is exact and case-sensitive, after any earlier transformations.

**Type inference (`inspect_csv`).** Over the sampled well-formed records, a column's `inferred_type` is the first of `integer`, `float`, `boolean`, `date`, `datetime`, `string` that every non-null sampled value casts to under (A), with no `format`. An all-null column is `string`. Consequences: `0`/`1` columns infer `integer`; `yes`/`no` columns infer `boolean`.

**Ticket impact (applied to the board 2026-10-20):**
- **ETL-04:** stage 2(b) implements exactly this table, with a test per row (accepted and rejected examples) and per rule 1 to 4, using the shared functions in `backend/app/etl/casting.py` (created by ETL-03b).
- **ETL-03b (new, etl-engineer)**, where the merged ETL-03 differs from this spec:
  1. `_INT_RE` uses `\d` and accepts non-ASCII digits; the float path uses `float()` and accepts underscores and non-ASCII digits.
  2. No `bigint` range check.
  3. Without `format`, dates and datetimes use the lax `fromisoformat`, which accepts compact and week dates and offsets. Timezone-aware range bounds are accepted when not mixed; under this spec they are rejected.
  4. `fill_null`/`allowed_values` date values are parsed with the column `format`; under this spec they must be ISO.
  5. `string` columns accept non-string config scalars.
  6. Rule 7 extension: no time or zone directives in a `date` format; no zone directives in a `datetime` format.
  ETL-03b creates `casting.py`, moves ETL-03's castability check onto it and fixes 1 to 6. It lands before ETL-02, ETL-04 and the ETL-05 rework, which all use it.
- **ETL-02:** type inference per the paragraph above.
- **ETL-05 rework:** replace the held `_config_scalar` with the shared config-scalar functions (B).
- **QA-03c / QA-07:** fixtures exercising the rejected examples. **FE-04:** client-side checks may mirror the table but the server stays authoritative.

Decisions (user, 2026-10-20):
- **C-a:** a whitespace-only cell in a non-string column becomes null.
- **C-b:** config date/datetime values are always ISO, regardless of the column `format`.
- **C-c:** string-column config values must be JSON strings.
- **C-d:** every invalid cell gets its own `type_cast` entry; the row counts once in `rejected_count`.
- **C-e:** a `date` format may contain no time directive (`%H` `%I` `%M` `%S` `%f` `%p` `%X` `%c`) and no zone directive (`%z` `%Z`); a `datetime` format may contain no zone directive. Enforced by §6 rule 7.

### Validation semantics (decision Q7, approved 2026-10-20)

1. **Nulls (Q7-1).** A null fails only the nullability rules: `nullable: false` (a `not_null` rejection at the cast step) and the `not_null` validation rule. `unique`, `range`, `allowed_values`, `regex` and `length` skip nulls. A `unique` key with **any** null component is not registered and never counts as a duplicate.
2. **Composite `unique` failures (Q7-2).** A `unique` rule with more than one column produces `RejectedRow(column=null, rule="unique")`. Its `message` names the key columns. Its `value` is the key as a compact JSON array in the rule's column order, with JSON-native values (strings quoted, numbers, `true`/`false`, dates and datetimes as ISO strings), e.g. `["a@x.com","2026-10-20"]`, truncated to 500 characters. A single-column `unique` failure sets `column` to that column and `value` to the value as text, like the other rules. Documented on the contract's `RejectedRow.value`.
3. **`fail_run` timing and checkpoints (Q7-3).** The step that finds the first rejection of a chunk evaluates the whole chunk, then raises `RejectionLimitExceeded` naming that chunk's first rejected row (row number and rule). Counters, events and rejections are persisted only for **completed chunks** (checkpoints). The failing chunk is never reported as durably completed, and the last `StageEvent` before the failure carries the counters of the completed chunks (Q3 rule 7). This applies to every rejection kind (Q4-b).
4. **`regex` and `length` on non-string columns (Q7-4).** §6 rule 3 rejects such configs. If the engine nevertheless meets one at run time, it raises `EtlError` (an internal error). It never converts values with `str()`.

## 6. Pipeline config semantic rules (beyond JSON Schema)

Enforced by `validate_pipeline_config`; reported as `ConfigErrorItem` with a JSON Pointer path.

1. `columns[].name` values are unique; `columns[].source` values are unique.
2. Every column referenced in `transformations` or `validations` is a `columns[].name`.
3. `trim_whitespace`, `change_case`, `regex`, `length` apply only to `string` columns.
4. `round_number` applies only to `float` columns. `range` applies only to `integer`, `float`, `date` and `datetime` columns, with numeric bounds for numbers and ISO 8601 strings for dates; if both bounds are present, `min ≤ max`.
5. `fill_null.value` and `allowed_values.values` must be castable to the column's type. *("Castable" is defined in §5 "Value casting", decision Q6-3; this includes `range` bounds, which on `integer` columns must be integral.)*
6. `regex.pattern` must compile with Python `re`.
7. `format` is allowed only on `date`/`datetime` columns. A `date` format contains no time directive (`%H` `%I` `%M` `%S` `%f` `%p` `%X` `%c`) and no zone directive (`%z` `%Z`); a `datetime` format contains no zone directive (decision C-e).
8. When `source_columns` is given, every `columns[].source` must be among them (`SourceMismatchError` at run time; `ConfigErrorItem` at validation time).
9. The target table name must not start with `run_` (reserved for staging).

## 7. Database

One PostgreSQL database, three schemas.

### 7.1 `public`: application metadata (Alembic, backend-owned)

| Table | Columns (type) | Notes |
|---|---|---|
| `data_sources` | `id uuid pk`, `name text`, `original_filename text`, `stored_path text`, `size_bytes bigint`, `sha256 char(64)`, `csv_options jsonb`, `columns jsonb`, `row_count bigint`, `created_at timestamptz` | `columns` = list of `ColumnInfo` |
| `pipelines` | `id uuid pk`, `name text unique`, `description text null`, `source_id uuid fk→data_sources restrict`, `config jsonb`, `config_version int`, `created_at`, `updated_at timestamptz` | `config` conforms to the pipeline schema |
| `runs` | `id uuid pk`, `pipeline_id uuid null fk→pipelines set null`, `pipeline_name text`, `source_id uuid null fk→data_sources set null`, `config_snapshot jsonb`, `config_version int`, `status run_status`, `current_stage text null`, `queued_at`, `started_at null`, `finished_at null`, `heartbeat_at null timestamptz`, `worker_id text null`, `extracted_count`, `loaded_count`, `rejected_count`, `duplicate_dropped_count`, `null_dropped_count bigint not null default 0`, `dataset_id uuid null fk→datasets set null`, `error_message text null` | see constraints below |
| `run_events` | `id bigserial pk`, `run_id uuid fk→runs cascade`, `stage text`, `status text`, `rows_in bigint null`, `rows_out bigint null`, `message text null`, `created_at timestamptz` | index `(run_id, id)` |
| `run_rejections` | `id bigserial pk`, `run_id uuid fk→runs cascade`, `row_number bigint`, `column_name text null`, `rule text`, `message text`, `value text null` | ≤ 1,000 per run; index `(run_id, row_number)` |
| `datasets` | `id uuid pk`, `table_name text unique`, `pipeline_id uuid null fk→pipelines set null`, `last_run_id uuid fk→runs`, `row_count bigint`, `columns jsonb`, `published_at timestamptz` | registry of `datasets.*` tables |

`run_status` is a PostgreSQL enum: `queued`, `running`, `succeeded`, `failed`, `interrupted`. This must stay identical to `RunStatus` in the OpenAPI contract.

Constraints:
- `CREATE UNIQUE INDEX one_running_run ON runs ((true)) WHERE status = 'running';` (REQ-41, at most one running run per deployment)
- `CREATE UNIQUE INDEX one_active_run_per_pipeline ON runs (pipeline_id) WHERE status IN ('queued','running');` (the API maps a violation to `409`)
- `CHECK (status <> 'succeeded' OR extracted_count = loaded_count + rejected_count + duplicate_dropped_count + null_dropped_count)` (Q3 reconciliation)
- `CHECK (status = 'succeeded' OR loaded_count = 0)` (nothing is published by unsuccessful runs)
- `runs.dataset_id` and `datasets.last_run_id` reference each other; the migration creates both tables first and adds the foreign keys afterwards.

Migrations also create the schemas `staging` and `datasets`.

### 7.2 Run state machine

```
queued ──claim──► running ──► succeeded
                     │──────► failed        (EtlError other than RunInterrupted, or unexpected exception)
                     └──────► interrupted   (RunInterrupted, SIGTERM, or stale heartbeat found at startup)
```
All of `succeeded`, `failed`, `interrupted` are terminal. Only the worker moves a run out of `queued`.

**Claim** (worker, one transaction):
```sql
UPDATE runs SET status='running', started_at=now(), heartbeat_at=now(), worker_id=:wid
WHERE id = (SELECT id FROM runs WHERE status='queued' ORDER BY queued_at
            FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING id;
```
A unique-violation on `one_running_run` means another run is active; the worker backs off and retries.

**Recovery** at worker start, and every poll: `UPDATE runs SET status='interrupted', finished_at=now(), error_message='worker stopped unexpectedly' WHERE status='running' AND heartbeat_at < now() - :stale`.

**Progress**: on every `StageEvent`, the worker inserts the `run_events` row and, in the same transaction, sets the five counters from `event.counters`, `current_stage` and `heartbeat_at = now()`. After a crash, the run therefore keeps the last persisted counters, and recovery only changes `status`, `finished_at` and `error_message` (`loaded_count` is already 0, because it only becomes non-zero at publish commit).

**Failure** (one transaction): `status='failed'` or `'interrupted'`, `finished_at`, `error_message`; counters stay as last persisted from events; insert rejection entries received so far (≤ 1,000).

**Success** (one transaction): set counters, `finished_at`, `status='succeeded'`, upsert the `datasets` registry row from `RunResult.published`, set `runs.dataset_id`, and insert `rejected_sample` into `run_rejections`.

### 7.3 `staging` and `datasets`: ETL-owned physical tables

Created and dropped only by `app.etl`. Type mapping:

| ColumnType | PostgreSQL |
|---|---|
| integer | `bigint` |
| float | `double precision` |
| boolean | `boolean` |
| date | `date` |
| datetime | `timestamp` (naive, as parsed) |
| string | `text` |

Every published table also gets `_localetl_run_id uuid not null` (the run that wrote the row) and `_localetl_row_number bigint not null`. These columns are excluded from `Dataset.columns`, `/rows` and `/profile`.

The API reads `datasets.*` for `/datasets/{id}/rows` and `/profile`. It quotes `table_name` (from the registry, never from the request) and validates `sort` against the registry's column list.

## 8. HTTP API

Defined entirely by `contracts/openapi.yaml`. Implementation notes:
- Base path `/api/v1`; FastAPI's served `/openapi.json` must not drift from the contract (BE drift test).
- Replace FastAPI's default 422 body with the contract `Error` shape (`details[].path` as a JSON Pointer).
- Upload: stream to a temp file under `LOCALETL_DATA_DIR/tmp/`, abort past the limit (413), then `inspect_csv` and move to `sources/<id>.csv`. On `CsvFormatError` the file is deleted and the API returns 422.
- `POST /pipelines` and `PUT` call `validate_pipeline_config(config, source_columns=<source column names>)`.
- `POST /pipelines/{id}/runs` inserts a `queued` run with `config_snapshot` and `pipeline_name` copied.

## 9. Frontend

- API types are generated: `npx openapi-typescript ../contracts/openapi.yaml -o src/app/api/schema.d.ts`. The generated file is committed and regenerated whenever the contract changes. All requests go through `src/app/api/client.ts`.
- Pipeline builder validation: client-side checks for required fields and identifier pattern, then server-side `POST /pipelines/validate`. The server result is authoritative.
- Run monitoring polls `GET /runs/{id}` and `/events` every 2 s while status is `queued` or `running`.
- Charts (Wave 2, visualization-engineer) consume `/metrics/summary`, `/runs` and `/datasets/{id}/profile`.

## 10. Testing strategy (summary; detail in `docs/qa/test-plan.md`)

| Layer | Location | Runner |
|---|---|---|
| ETL unit + DB | `backend/tests/etl/` | `pytest backend/tests/etl` (DB tests marked `db`) |
| API | `backend/tests/api/`, `backend/tests/models/` | `pytest backend/tests/api backend/tests/models` |
| Worker | `backend/tests/worker/` | `pytest backend/tests/worker` |
| Frontend | colocated `*.test.ts(x)` | `npm --prefix frontend test` |
| Contract + integration | `tests/integration/` | `pytest tests/integration` |
| E2E | `tests/e2e/` | Playwright |

DB tests use `TEST_DATABASE_URL`, never `DATABASE_URL`.
