# QA review: ETL-03 Config validation, independent

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-20
- Target: `etl/ETL-03-config-validation` @ **0f56443** (one commit on `main` 65b093f; ancestry confirmed; no checkpoint file). The backup `-prerebase` branch was not touched.
- Diff vs `main`: `backend/app/etl/config.py` and `backend/tests/etl/test_config.py` only, which are etl-engineer paths.

## Verdict: **PASS** (the code meets the spec as written; no defects). Six points need a ruling (below).

## Checks
| Check | Result |
|---|---|
| Schema loaded from `Path(__file__).resolve().parents[3]/contracts/pipeline.schema.json` (§5); `LOCALETL_PIPELINE_SCHEMA_PATH` is not read anywhere in `app.etl` (grep for environ/getenv/LOCALETL: none) | OK |
| Examples in `contracts/examples/pipeline/` (I ran all 11 myself) | All behave as labelled: 3 valid pass; 8 invalid fail at the expected path (e.g. `/target/table`, `/validations/0` "at least one of min, max", `/version`, root `columns` required) |
| Errors collected, not fail-fast: schema phase collects every error; semantic phase collects every rule's errors; one `ConfigValidationError`; deterministic order | OK |
| JSON Pointer (RFC 6901) paths, root is `""`, `~`→`~0` and `/`→`~1` escaped in the right order; tests for both | OK |
| `oneOf` noise: replaced by the errors of the branch chosen by `op`/`rule` | OK |
| §6 rules 1–9: each has a passing and a failing test (rule 4 split into float-only `round_number`, `range` types/bounds, and min≤max; rule 5 covers `fill_null` and `allowed_values`, and uses the column `format`) | OK |
| `source_columns` is exact-match; `[]` means every source is missing; `None` skips rule 8 | OK (probed) |
| Rule 9: `run_x` rejected with the reserved-prefix message; `RUN_x` is rejected by the schema pattern | OK (probed) |
| Input is not mutated; result holds a deep copy | OK, with tests |
| Import rule (existing test) / no `eval`, `exec`, `.query(` in `app.etl` | OK. `jsonschema` is declared in `pyproject.toml` (`>=4.21,<5`) |
| Type hints; mypy --strict | OK |

## Suites (detached 0f56443, shared Postgres 127.0.0.1:55432)
- `pytest backend/tests`: **102 passed** (ETL 64, API 9, models 29), 1 third-party warning
- `mypy app`: no issues (18 files) · `mypy --strict app/etl`: no issues (6 files)
- `ruff check`: pass · `ruff format --check`: 30 files formatted
- `contracts/tools/check_contracts.py .`: **0 failures**
- Worktree clean after the run.

## Defects
None. Info only:
- If the schema file is missing or unreadable, `_validator()` raises a bare `OSError`/`JSONDecodeError`, not an `EtlError`. That is an installation fault, so acceptable.
- A bad strptime `format` (e.g. `%Q`) is reported as "value cannot be cast", which is a misleading message (see ruling 5).

## Needs ruling (spec ambiguities; not ruled on here)
1. **`format` on non-date columns.** The schema says "Ignored for other types"; §6 rule 7 forbids it. The code follows §6 and rejects, i.e. it is stricter than the schema. `contracts/` outrank the architecture doc, so one of the two texts must change. Today a config with `format` on a string column is valid per the schema but rejected by the engine.
2. **Two phases.** §6 rules run only after the schema is clean, so a config with both kinds of error reports only the schema errors first. The spec says "all problems are collected into one error", which could be read either way. The code's choice is reasonable and tested.
3. **Meaning of "castable".** The spec doesn't define it. The code: integers accept ints, integral floats and strings matching `[+-]?\d+` after strip; floats must be finite; booleans accept true/false/1/0/yes/no, any case, plus numbers 0/1; date and datetime use the column `format`, else Python `fromisoformat` (which in 3.11 is lax, e.g. basic-format dates). ETL-04 casting must use the same rules. A string such as `"1.0"` is not castable to integer, but the number `1.0` is.
4. **Range bounds for date/datetime.** The code requires ISO 8601 strings parsed with `fromisoformat`, and rejects mixed timezone-aware/naive bounds as not comparable. The column `format` is not used for the bounds. §6 says only "ISO 8601 strings".
5. **Not enforced** (spec silent): `length` min > max, whether a strptime `format` is itself valid, duplicate validations, `replace_values` value types, `fill_null` on a `nullable: false` column.
6. **Rule 2 breadth.** The code checks every column reference (`column` and each entry of `columns`) in transformations and validations. That is a reasonable reading of "every column referenced", but it is an extension.
