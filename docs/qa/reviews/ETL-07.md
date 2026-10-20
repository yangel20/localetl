# QA review: ETL-07 run_pipeline

- Reviewer: qa-engineer (QA-06) · 2026-10-20 · Ticket ETL-07 · `etl/ETL-07-runner` @ **05ea98e** (1 commit on cbeec5c)
- Files: `backend/app/etl/{runner,errors}.py`, `backend/tests/etl/{test_runner,conftest,test_public_api}.py`. Only etl-engineer paths; no export changes.

## Verdict: **PASS**

## Suites (detached 05ea98e; `scripts/test-all.sh` once)
- test-all: **16/16 pass**. backend 607 passed (runner 66), fixtures 46, integration 33 passed + 21 skipped, frontend 103, mypy, `mypy --strict app/etl`, ruff, contracts, drift: all pass.

## Independent verification (own script, throwaway DB; 0 mismatches)
- Counters equal `expected.json` for `chunk_rows` ∈ {1, 2, 7, 50000} (and 3, 5, 9 for chunk_dupes): clean, nulls, chunk_dupes, dirty (reject and unique variants), ragged, straddle, parse_error_dedupe.
- Published rows equal `loaded_count`. Replace 200; append twice gives 200 + 200 (total 600, per-run rows 200 each, `published.row_count` 600). Dirty replace published rows = 70 = `loaded_count`.
- Failures leave the published table unchanged and no staging left: ratio exceeded (`failed` on validate, loaded 0), `fail_run` on dirty, append schema mismatch (`LoadError` on publish), source-column mismatch (`SourceMismatchError`), invalid config (`ConfigValidationError`, `rejected_sample == []`, so subclasses with their own `__init__` get it).
- `ragged_failrun` at failure: last event counters extracted 0 / 0 / 1 for `chunk_rows` 50000 / 2 / 1, loaded 0, message names row 2 `parse_error` (Q7-3, Q11-a).
- File-level faults: duplicate/empty header, unterminated quote, empty and header-only files fail at `extract`; a fault in chunk k (unterminated quote after 7 rows, `chunk_rows=2`) fails with counters of the 3 completed chunks (extracted 6, loaded 0) and publishes nothing.
- Interruption at every `should_stop` boundary (7 points for one chunk, 19 for `chunk_rows=60`): each raises `RunInterrupted` with a `failed` event (message `interrupted`, loaded 0, stages seen extract/transform/validate/load/publish), the published table is untouched and staging is empty.
- Events: counters cumulative and non-decreasing; the final event's counters equal `RunResult`; four `progress` events per completed chunk (4 × ceil(200/chunk_rows)), none for an incomplete chunk; per-chunk stage rows present.
- `rejected_sample` cap: 3,000 rejections give `rejected_count` 3,000 and 1,000 entries in row order (rows 1-1000); on a ratio failure the error carries the same 1,000 (completed chunks only).
- Never writes `public.*` (scratch `public` has no tables after the runs); no `eval`/`exec`; the module docstring example is a valid plain script.

## Defects
None.

## Needs ruling (listed, not decided)
1. `completed` events for extract, transform, validate and load are all emitted after the last chunk (confirmed: `started ×4, progress …, completed ×4, publish started, publish completed`).
2. Entry order inside `rejected_sample` is (row, stage, in-stage order): parse_error, then transform, then validate.
3. Non-`EtlError` failures carry no `rejected_sample` (confirmed: a callback raising `Boom` propagates without the attribute; staging is still dropped). The worker should use `getattr(exc, "rejected_sample", [])`.
4. (new, info) For an invalid config the run emits four `started` events and then a `failed` event for `extract`, because config validation runs after the stage-start events.
