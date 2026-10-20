# QA-06 review: BE-01b method_not_allowed for HTTP 405

**Verdict: PASS**

- Branch `be/BE-01b-method-not-allowed` @ `3c1ca17` (1 commit). `main` @ `08addd2` is an ancestor (verified). Reviewer: qa-engineer, 2026-10-19.

## Scope and contract check
- Contract (`openapi.yaml` lines 14, 472-474, decision Q1): HTTP 405 returns `Error` with `code = method_not_allowed`. The change adds `405: "method_not_allowed"` and nothing else to the code map: PASS.
- Also forwards exception headers, so the `Allow` header on 405 is kept (HTTP requirement). Other statuses unchanged.
- Diff touches only `backend/app/core/errors.py` and `backend/tests/api/test_errors.py` (backend-owned): PASS.

## Tests verified (detached checkout, Postgres on 55432)
| Command (in `backend/`) | Result |
|---|---|
| `pytest -q -rs` | **9 passed, 0 failed, 0 skipped** (new: `test_method_not_allowed_keeps_allow_header`) |
| `mypy app` | no issues (8 files) |
| `ruff check .` / `ruff format --check .` | clean / 13 files formatted |
| `python contracts/tools/check_contracts.py .` | 0 failures |

## Defects
None. Resolves BE-01 review defect #2 (405 previously `validation_error`).
| Sev | Finding |
|---|---|
| Info | The new test uses a bare `TestClient(create_app())` (no context manager), fine here because no lifespan or DB is involved. |

## Recommendation
Merge-ready.
