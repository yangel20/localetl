# LocalETL Requirements

Status: Wave 0 baseline · Owner: orchestrator · Changes require orchestrator approval.

LocalETL is a single-user, local-first web application for loading CSV files into PostgreSQL through saved, configurable cleaning and validation pipelines.

Requirement IDs (`REQ-xx`) are referenced by tickets in `docs/task-board.md` and by the QA traceability matrix in `docs/qa/test-plan.md`.

## 1. Data sources (CSV upload and preview)

| ID | Requirement |
|---|---|
| REQ-01 | A user can upload one CSV file at a time through the UI. The API stores it under `LOCALETL_DATA_DIR` with a server-generated file name and records it as a **data source**. |
| REQ-02 | Upload size limit is `LOCALETL_MAX_UPLOAD_MB` (default **100 MB**). Larger uploads are rejected with `413` before the file is fully stored. |
| REQ-03 | Supported encodings: `utf-8`, `utf-8-sig`, `latin-1`, `cp1252`. Supported delimiters: `,` `;` `\t` `\|`. The user may specify encoding, delimiter, header presence and quote character at upload; defaults are `utf-8`, `,`, header present, `"`. |
| REQ-04 | Files that are empty, header-only, undecodable in the chosen encoding, or have more than **500 columns** are rejected with a clear error message identifying the problem. |
| REQ-05 | The user can preview a data source: column names, inferred column types (`integer`, `float`, `boolean`, `date`, `datetime`, `string`), null counts in the sample, and the first N rows (default 50, max 500). |
| REQ-06 | The user can list data sources (paginated) and delete a data source that no pipeline references. |

## 2. Pipeline configurations

| ID | Requirement |
|---|---|
| REQ-10 | A user can create, list, view, update and delete named pipeline configurations. Each pipeline references one data source. |
| REQ-11 | A pipeline configuration is a JSON document conforming to `contracts/pipeline.schema.json`. The API rejects non-conforming configs with field-level error paths. |
| REQ-12 | A pipeline selects and renames source columns and assigns each a target type. Target column and table names must match `^[a-z_][a-z0-9_]{0,62}$`. |
| REQ-13 | The UI can validate a configuration before saving it, without persisting it. |

## 3. Cleaning and validation

| ID | Requirement |
|---|---|
| REQ-20 | Cleaning operations are chosen only from a fixed list: `trim_whitespace`, `change_case`, `replace_values`, `fill_null`, `drop_null_rows`, `deduplicate`, `round_number`. They run in the configured order. |
| REQ-21 | Validation rules are chosen only from a fixed list: `not_null`, `unique`, `range`, `allowed_values`, `regex`, `length`. |
| REQ-22 | Rows failing type casting or any validation rule are **rejected** with row number, column, rule and message. The pipeline chooses `reject_row` (continue without the row) or `fail_run` (stop the run). |
| REQ-23 | A pipeline may set `max_rejected_ratio` (0–1); computed as rejected rows ÷ extracted rows; if exceeded the run fails and nothing is published. |
| REQ-24 | User input is never executed as code. No `eval`, `exec`, `DataFrame.query`/`DataFrame.eval` on user strings, and no user-supplied Python. |
| REQ-25 | Each extracted row has exactly one outcome: loaded, rejected (failed parsing, casting or a validation rule), duplicate-dropped (`deduplicate`) or null-dropped (`drop_null_rows`). Rows removed by cleaning operations are not rejections. For a succeeded run, extracted = loaded + rejected + duplicate-dropped + null-dropped, across all chunks. |

## 4. PostgreSQL loading

| ID | Requirement |
|---|---|
| REQ-30 | Valid rows are loaded first into a run-specific staging table, then **published** to the target table in a single transaction. A failed run never modifies the published table. |
| REQ-31 | Load modes: `replace` (target becomes exactly this run's rows) and `append` (rows added; target column set and types must match, otherwise the run fails). |
| REQ-32 | All SQL uses bound parameters; all dynamic identifiers are validated against the identifier pattern and quoted by SQLAlchemy. |
| REQ-33 | Database credentials come only from environment variables. |

## 5. Job execution and monitoring

| ID | Requirement |
|---|---|
| REQ-40 | A user manually starts a run of a saved pipeline. The API queues it and returns immediately; a separate local worker process executes it. |
| REQ-41 | Run states are `queued`, `running`, `succeeded`, `failed`, `interrupted`. At most **one** run is `running` per deployment, and a pipeline may not have two runs that are `queued` or `running` at the same time. |
| REQ-42 | The worker records stage events (`extract`, `transform`, `validate`, `load`, `publish`) with row counts and messages; the UI shows run status and events, refreshing until the run reaches a terminal state. |
| REQ-43 | If the worker stops or crashes during a run, that run is marked `interrupted` the next time a worker starts. Interrupted runs are not resumed; the user starts a new run. |
| REQ-44 | On SIGINT/SIGTERM the worker stops claiming runs, stops the current run at the next stage or chunk boundary, marks it `interrupted`, and exits. |

## 6. History, metrics and datasets

| ID | Requirement |
|---|---|
| REQ-50 | Execution history: runs are listed newest first, filterable by pipeline and status, paginated. |
| REQ-51 | Each run exposes extracted, loaded, rejected, duplicate-dropped and null-dropped row counts, duration, error message (if failed) and a paginated list of rejected rows (up to 1,000 stored per run). |
| REQ-52 | A metrics summary exposes run counts by status, total rows loaded, average duration, and daily run counts for the last 30 days. |
| REQ-53 | Published datasets are listed with row count, columns and last publish time; their rows can be previewed with pagination and single-column sort. |
| REQ-54 | Each published dataset exposes a column profile (null count, distinct count, min/max for numeric and date columns, top 10 values) to drive basic charts. |
| REQ-55 | The UI shows basic charts: run outcomes over time, rows loaded per run, and per-column distributions of a published dataset. |

## 7. Non-functional

| ID | Requirement |
|---|---|
| REQ-60 | Local only: the API binds to `127.0.0.1` by default; CORS allows only `LOCALETL_CORS_ORIGINS`. |
| REQ-61 | A 1,000,000-row, 10-column CSV (≈100 MB) completes a `replace` run in under 5 minutes on a typical laptop; extraction is chunked (default 50,000 rows), so memory does not grow with file size beyond one chunk plus the staging write. |
| REQ-62 | Python code is type-hinted and passes `mypy`; TypeScript runs in strict mode. |
| REQ-63 | Every component has automated tests; the MVP is complete only after a recorded end-to-end demo: upload → configure → run → monitor → view results and charts. |
| REQ-64 | `.env` files and uploaded data are never committed. |

## 8. Non-goals (MVP)

Authentication and multiple users; non-CSV sources (Excel, JSON, databases, APIs); scheduled or triggered runs; run cancellation from the UI; resuming interrupted runs; editing published data; custom user code or expressions; remote deployment.
