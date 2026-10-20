# QA review: ETL-06 Load and publish, independent

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-20
- Target: `etl/ETL-06-load-publish` @ **91c0aa5** (one commit on `main` 838661b; ancestry confirmed; `main` is now 69fdc16)
- Diff vs base: `backend/app/etl/load.py` (new), `backend/tests/etl/conftest.py` (new), `backend/tests/etl/test_load.py` (new). Only etl-engineer paths; no export changes.
- Spec: board ETL-06 row, architecture §5 stage semantics 4-5, §7.3, CLAUDE.md rules 7-9.

## Verdict: **PASS**
No defects. Five points need a ruling (below).

## Checks
| Check | Result |
|---|---|
| Staging table `staging.run_<hex>`; §7.3 type mapping (bigint, double precision, boolean, date, naive timestamp, text) plus `_localetl_run_id uuid not null` and `_localetl_row_number bigint not null` | OK (read; test asserts the physical types) |
| `replace`: drop target if present, `ALTER TABLE ... SET SCHEMA datasets`, rename, all in one transaction | OK. In my scratch DB: replace creates, then overwrites (5 rows replaced 3) |
| `append`: create `datasets.<t>` like staging if absent; otherwise identical column name/type list, else `LoadError`; `INSERT ... SELECT`; drop staging | OK. Append added 2 rows: `loaded_rows` 2, table total 7. Mismatch cases all raise `LoadError` with the table unchanged and no staging left: fewer columns, reordered columns, changed type |
| Failure leaves the published table unchanged | OK. A replace blocked by a dependent view (the plain `DROP TABLE` fails): `LoadError`, old rows intact (7 = 7). Bigint overflow and a NUL character in a string: `LoadError` and staging dropped. Tests cover failure at publish and atomicity for concurrent readers |
| Identifiers validated and quoted; values bound | OK. Names must match `^[a-z_][a-z0-9_]{0,62}$` and go through SQLAlchemy's identifier preparer; every value is a bound parameter (`sa.insert` executemany, `:name`). A value `x'); DROP TABLE datasets.t;--` was stored verbatim, and `datasets.t` survived. Rejected before any SQL effect: 64-char, upper case, `x y`, `x;y`, empty; a 63-char table name works. SQL reserved words (`user`, `select`, `order`) work because they are quoted |
| `run_` prefix on target tables rejected (§6 rule 9) | OK |
| Writes only to `staging` and `datasets` | OK. Every statement targets those schemas; a test asserts it, and another asserts `load.py` has no `public` reference. `public` is never touched |
| Publishing twice with one `Loader` | `LoadError` (second publish fails cleanly) |
| No `eval`/`exec`/`.query`; imports | OK. Only stdlib, pandas, SQLAlchemy and `app.etl` siblings; no FastAPI or other `app.*` |
| Throwaway DB fixture leaves nothing behind | OK. The module-scoped fixture creates `localetl_etl_<hex>` on the `TEST_DATABASE_URL` server and drops it WITH FORCE; the schema reset (`DROP SCHEMA ... CASCADE`) runs only in that scratch database. After my run the server held only `postgres`, `localetl`, `localetl_test`, and `localetl_test` has no `staging` or `datasets` tables |

## Suites (detached 91c0aa5, shared Postgres 127.0.0.1:55432, venv from backend[dev])
- `pytest backend/tests`: **158 passed**, 1 third-party warning. `test_load.py` alone: 56 passed.
- `mypy app`: no issues (19 files) · `mypy --strict app/etl`: no issues (7 files)
- `ruff check` and `ruff format --check` from `backend/`: pass (33 files)
- `ruff check --config backend/pyproject.toml backend` **from the repo root fails with 8 I001** on this branch. That is not an ETL-06 defect: the branch is based on 838661b, before main's tooling fix 2d6bc1a (`known-first-party = ["app"]`), and the failures are in files this branch does not touch (`tests/api/*`, `tests/models/*`, `migrations/env.py`, `test_config.py`, `test_public_api.py`, plus `test_load.py`'s own import block). With main's `[tool.ruff]` settings applied (extracted to a scratch `ruff.toml`), `ruff check backend` and `ruff format --check backend` both pass. A rebase onto main resolves it.
- `contracts/tools/check_contracts.py .`: 0 failures
- Worktree clean after the run.

## Needs ruling (listed, not decided)
1. **`_localetl_` reserved prefix on column names.** `Loader` refuses a column starting with `_localetl_` (it would collide with the run metadata columns). §6 does not say so, so a config with such a target column name passes `validate_pipeline_config` and fails only at load time. Either add a §6 rule so it is reported at validation time, or leave it as a load error.
2. **Replace lock.** `replace` runs `DROP TABLE` inside the publish transaction, which takes an ACCESS EXCLUSIVE lock. I confirmed it: with a reader holding a transaction open on `datasets.t`, the publish blocked until the reader closed. There is no `lock_timeout`, so a long read (for example the explorer's `/rows`) can stall the run, and while the DROP waits it also queues behind new readers of that table. Options: leave it, or `SET LOCAL lock_timeout` and fail with `LoadError`. Behaviour on timeout is a decision.
3. **Timezone-aware datetimes.** `_normalise` refuses them ("pending casting spec"). Q6-3 now approves only naive datetimes and rejects offsets at the cast step, so this path should be unreachable. Whether to keep the guard as defence in depth or drop the "pending" wording is the engineer's call; no spec change needed.
4. **`loaded_rows` for replace.** It is the in-memory `staged_rows` counter, not a count read back inside the publish transaction (append uses the DB row count of the insert). They agree today. If anything else wrote to the staging table the numbers would differ; the engine is the only writer, so this is low risk.
5. **Append compatibility is names and types only, order-sensitive**, and ignores nullability and the `_localetl_*` columns' position. It matches §5 stage 5 ("identical column name/type list"). A reordered but otherwise identical column list is rejected as a mismatch (confirmed). Confirm that is intended.

## Defects
None. Info: if the cleanup `drop()` after a failure itself fails, its `LoadError` replaces the original error, which can hide the root cause; the engine should log the first one. Per-chunk memory is one list of dict rows per chunk (50k default), acceptable; REQ-61 throughput should be measured in ETL-07.
