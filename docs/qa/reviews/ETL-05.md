# QA review: ETL-05 Validate stage (PARTIAL submission), independent

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-20
- Target: `etl/ETL-05-validate-stage` @ **79f25b0** (one commit on `9d550f4`; ancestry confirmed; `main` is now bf526c2)
- Diff vs its base: `backend/app/etl/validate.py` and `backend/tests/etl/test_validate.py` only (etl-engineer paths).
- Status: **will not merge** until the user rules on Q7 and the casting spec (Q6-3). This verdict covers the implemented, unambiguous part only.

## Verdict (implemented, unambiguous part): **PASS**
Held and ruling items are listed separately and do not change this verdict.

## Checks against the board row and architecture §5
| Check | Result |
|---|---|
| Exactly the 6 schema rules; completeness test against the schema enum | OK (`test_every_schema_rule_is_implemented`); `_COMPILERS` has `not_null, unique, range, allowed_values, regex, length` |
| One rejection entry per failing rule; a row failing several rules counts once (Q3 rule 2) | OK, `rejected_rows` counts distinct rows; tests for several rules on one row and for row-then-rule ordering |
| `unique` keeps the first occurrence across chunks; key registered by the first row that reaches the step even if it fails another rule (Q3 rule 5) | OK; the `seen` set persists on the `Validator`; tests for within-chunk, across-chunk and "registered by a row failing an earlier rule" |
| `fail_run` raises `RejectionLimitExceeded` on a rejection | OK; message names row, rule and message. See ruling 3 |
| `max_rejected_ratio`: `rejected_count / extracted_count`; dropped rows only raise the denominator (Q3 rule 6) | OK; strict `>` so equal passes; default limit 1; zero limit; `extracted_count <= 0` returns; test shows dropped rows do not raise the ratio |
| Regex value length cap (10,000), rejected without matching | OK; catastrophic pattern on a long value is not evaluated (test). Pattern length is capped by the schema (`maxLength` 200), enforced by ETL-03 |
| `RejectedRow` shape; value truncated to 500 characters | OK |
| Rejections ordered by row then rule; valid rows keep original index and order; reported row numbers are used, not positions; misaligned `row_numbers` raises `EtlError` | OK, tests for each |
| Imports and CLAUDE.md rules | OK. Only `pandas`, stdlib and `app.etl` siblings; no `eval`, `exec` or `.query(`; no FastAPI or other `app.*`; type hints throughout; `mypy --strict` clean |

## Casting hold: **verified**
- Config-value conversion happens only in `_config_scalar` (lines 60-95). Its three call sites are the `range` min and max and `allowed_values.values`. `validate.py` contains no `strptime`, no CSV parsing and no call into casting code.
- I ran 32 cases against it, all as specified:
  - integer: a JSON `int` (not `bool`) within bigint is accepted. `2**63-1` is accepted; `2**63`, `1.0`, `"5"`, `True` and `None` raise.
  - float: a finite `int` or `float` (not `bool`) is accepted. `inf`, `nan`, `10**400` (overflow), `"1.5"` and `True` raise.
  - boolean: only JSON `true`/`false`. `1` and `"true"` raise.
  - string: only `str`. `5` raises.
  - date: only a string fullmatching `YYYY-MM-DD` that is a real date. `20261020`, a datetime string, `2026-02-30` and a leading space raise.
  - datetime: only a string fullmatching `YYYY-MM-DDTHH:MM:SS`. A space separator, `Z`, `+02:00`, no seconds, fractional seconds and a bare date raise.
  - **Every rejected case raises `NotImplementedError("pending casting specification Q6-3")`** with exactly that message. 0 mismatches.
- The hold surfaces when the `Validator` is constructed (test), not mid-run.

## Held (casting), Q6-3
These are not implemented and raise the hold:
- A JSON number with zero fraction (`1.0`) for an integer column.
- Strings for integer, float and boolean columns (`"5"`, `"1.5"`, `"yes"`), and `0`/`1` numbers for boolean.
- Dates and datetimes in any form other than the two strict ISO shapes: compact, week, space separator, fractional seconds, offsets or `Z`, a column `format`.
- Non-string values for a string column.
- Everything that depends on whether whitespace-only cells are null (C-a), which sits upstream in ETL-04 and is not in this module.

## Needs ruling (the agent's four Q7 points; not ruled on here)
1. **Null skipping.** Nulls are ignored by every rule except `not_null` (never fail `unique`, `range`, `allowed_values`, `regex` or `length`). §5 says nothing explicit. It is a reasonable reading, and consistent with the schema `nullable` check.
2. **Composite `unique` entry shape.** `column` is `None` and `value` is the key rendered with `", "`. A single-column key sets `column`. The `", "` join is ambiguous when a value contains a comma. For example the key `("x", "y, z")` renders as `x, y, z`, as I confirmed. §5 defines `RejectedRow.column: str | None` but not this case.
3. **`fail_run` after evaluating the chunk.** The whole chunk is evaluated and the rule with the first failing row (by row, then rule) is reported. Counters are not updated on the raising call (`rejected_rows` stays 0, confirmed). The spec says "the first rejection raises", which could also mean stop at the very first failing cell. With Q3 rule 7 (counters come from the last emitted event), this seems compatible.
4. **`regex` on non-strings.** `regex` and `length` run on `str(value)`. For a boolean that gives `"True"` while rejections render it as `"true"` (confirmed), so the matched text and the shown value differ. ETL-03 currently rejects `regex`/`length` on non-string columns (§6 rule 3), so this is unreachable from a validated config today.

## Defects
None blocking. Notes:
- **Info/low, interface:** the stage assumes the chunk is already typed with Python values and nulls as `None`/NA (module docstring). If ETL-04 hands over a pandas `float64` column for an integer column with nulls (pandas coerces), then `length` sees `"1.0"` (length 3) and rendered values show `3.0`, as I confirmed. `allowed_values` still works because `1.0 == 1`. This is garbage-in, but it is an easy trap. Suggest the ETL-04 handoff use `object` or nullable `Int64` dtypes, and a test at that boundary in ETL-07.
- **Info:** the rules loop over cells in Python (one pass per rule). It is fine for correctness; REQ-61 (1M rows) should be measured in ETL-07.
- **Env note:** `check_contracts.py` needs `pyyaml` and `openapi-spec-validator`. The branch's `pyproject.toml` predates the dev-extra change on `main` (bf526c2), so I installed both ad hoc for this run. Not a defect of this ticket.

## Suites (detached 79f25b0, shared Postgres 127.0.0.1:55432, fresh venv)
- `pytest backend/tests`: **148 passed** (ETL 110, API 9, models 29), 1 third-party warning. `test_validate.py` alone: 46 passed.
- `mypy app`: no issues (19 files) · `mypy --strict app/etl`: no issues (7 files)
- `ruff check`: pass · `ruff format --check`: 32 files formatted
- `contracts/tools/check_contracts.py .`: 0 failures (with the two packages installed as noted)
- Worktree clean after the run.
