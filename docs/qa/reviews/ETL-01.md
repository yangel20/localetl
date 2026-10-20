# QA review: ETL-01 (re-review after Q3), independent

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-20
- Target: `etl/ETL-01-public-types`, code commit **f1328c5** (rebased on `main` a07cbb0; ancestry confirmed)
- Tip `04b4b3a` adds only `docs/checkpoints/etl-engineer.md` (verified: `git diff f1328c5 04b4b3a` = that one file). Do not merge it.
- Supersedes the earlier review of pre-Q3 `8b23e75`, which is out of date.

## Verdict: **PASS**

## Checks
| Check | Result |
|---|---|
| `git diff main f1328c5` touches only `backend/app/etl/*` (6 files) and `backend/tests/etl/test_public_api.py` | OK, etl-engineer paths only |
| Exports of `app/etl/__init__.py` equal architecture §5 (26 names: 14 types/aliases incl. `RunCounters`, 7 errors, 4 functions + `PipelineConfig`) | OK, read against §5; test asserts the exact set and no duplicates |
| Signatures and defaults of the 4 functions, keyword-only markers | OK, match §5; full hints; test checks names, kinds, defaults |
| All dataclasses frozen (11) | OK, parametrized test |
| `RunResult` fields: five counters in order, then `rejected_sample`, `published`, `stage_durations_ms` | OK, test asserts the list |
| `RunCounters`: same five fields, same order | OK |
| `StageEvent.counters: RunCounters` is the final field | OK |
| Import rule: nothing from fastapi/starlette/pydantic/app.* other than app.etl | OK. AST test exists; runtime check of `import app.etl` loaded no FastAPI/starlette/pydantic and no other `app.*` (only sqlalchemy, which §5 allows) |
| No `eval`/`exec` | OK (grep) |
| Type hints | OK |

## Suites (detached f1328c5, Postgres 16 at 127.0.0.1:55432, shared stack untouched)
- `pytest backend/tests`: **27 passed** (ETL 18, API 9), 1 warning (starlette testclient, third-party)
- `mypy app`: no issues (14 files)
- `mypy --strict app/etl`: no issues (6 files)
- `ruff check`: pass · `ruff format --check`: 20 files formatted
- `contracts/tools/check_contracts.py .`: **0 failures**
- Worktree clean after the run.

## Defects
| # | Severity | Finding |
|---|---|---|
| 1 | Low | `test_import_rules` skips every relative import (`level > 0`) on the assumption they stay in `app.etl`. `from ..models import X` or `from .. import core` would pass the test but breaks the import rule. Suggest rejecting `level >= 2`. Also `FORBIDDEN` omits `sqlalchemy`-free items correctly, but does not forbid `app` via `importlib`; acceptable. Not a merge blocker; no violation exists today. |
| 2 | Info | Tests check parameter names, kinds and defaults, but not annotations. mypy --strict covers hints, so no gap in practice. |
| 3 | Info | `PipelineConfig` has only `raw`; §5 leaves typed fields to ETL-03. |
