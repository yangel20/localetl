# QA-06 review: ETL-01 Public types, errors and interface stubs

**Verdict: PASS**

- Branch `etl/ETL-01-public-types` @ `8b23e75` (2 commits). `main` @ `08addd2` is an ancestor (verified). Reviewer: qa-engineer, 2026-10-19.

## Tests verified (detached checkout, Python 3.11.6, `pip install -e '.[dev]'`)
| Command (in `backend/`) | Result |
|---|---|
| `pytest -q -rs` (Postgres on 55432, `TEST_DATABASE_URL` set) | **25 passed, 0 failed, 0 skipped** (17 ETL + 8 existing API) |
| `pytest tests/etl -q` | 17 passed |
| `mypy app` / `mypy --strict app/etl` | no issues (14 / 6 files) |
| `ruff check .` / `ruff format --check .` | clean / 20 files formatted |

## Acceptance criteria
- Every name in architecture §5 exported, with exact signatures and full type hints: PASS. Read against §5: all types, `Literal`s, field names/types, `CsvOptions` defaults, the 6 error classes, `ConfigValidationError.errors`, and the 4 function signatures (keyword-only params and defaults) match. `test_export_list_is_exact` and `test_function_signatures` assert this.
- Dataclasses frozen: PASS (`test_dataclasses_are_frozen`).
- Functions raise `NotImplementedError("ETL-0x")`: PASS.
- `mypy --strict app/etl`: PASS.
- Import-rule test (no FastAPI / `app.*`): PASS. Manual grep also finds only stdlib, sqlalchemy and relative imports.
- Ownership: diff touches only `backend/app/etl/*` and `backend/tests/etl/test_public_api.py`: PASS. `config.py`, `extract.py`, `runner.py` are stubs; layout is the ETL engineer's choice per §5.

## Defects
None blocking.
| Sev | Finding |
|---|---|
| Info | `backend/tests/etl/` has no `__init__.py` (unlike `tests/api/`). Fine with pytest's default import mode as long as test file basenames stay unique; add one if a name clash appears. |
| Info | `PipelineConfig` has only `raw`; typed accessors are deferred to ETL-03 as documented. |

## Recommendation
Merge-ready. (The board's "cannot submit until BE-01 merges" condition is satisfied: BE-01 is in `main`.)
