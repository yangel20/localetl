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

---

# Re-review after rework (2026-10-20): ETL-05 rework at **0c009f0**

- Target: `etl/ETL-05-validate-stage` @ **0c009f0**, two commits on `4cd8cdd`: `b53562e` (the implementation I passed earlier as 79f25b0, rebased) and `0c009f0` (rework for approved casting and Q7). `main` is now 0d2af70. Files: `backend/app/etl/validate.py`, `backend/tests/etl/test_validate.py` only.
- Scope: removal of the casting hold, Q7-1, Q7-2, Q7-3, Q7-4, plus a regression pass over the earlier checks.

## Verdict: **PASS**
No defects. The earlier "Held" list is closed and the earlier "Needs ruling" points 1 to 4 are now decided by Q7 and implemented as decided.

## Checks
| Check | Result |
|---|---|
| Hold removed | `_config_scalar`, the private regexes and `NotImplementedError("pending casting specification Q6-3")` are gone (grep: none, in code and tests). Config values go through `casting.cast_config_value` (Q6-3 table B); an invalid scalar raises `EtlError` when the `Validator` is built. The module imports only stdlib, pandas and `app.etl` siblings |
| Config scalars (my own cases) | integer `allowed_values` `[5.0, "7"]` accepts cells 5 and 7, rejects 8; float `[1, "2.5"]`; boolean `1` and `"no"`; ISO date and datetime (`"2026-10-20 10:00"`); string stays case-sensitive; `range` on integer, float, date and datetime including one-sided bounds. Rejected at construction: `True` or `5.5` or `2**63` for integer, `inf` for float, `20261020` for date, `…Z` for datetime, `5` for string, `2` for boolean |
| Q7-1 nulls | a null fails only `not_null`; `unique`, `range`, `allowed_values`, `regex` and `length` skip nulls (all five on null cells: no rejections). A composite `unique` key with **any** null component is never registered and never a duplicate: `("x",None)` repeated, `(None,None)` repeated and `("x",None)` across two chunks all pass, while a later full `("x","y")` duplicate is rejected |
| Q7-2 composite value | `column = None`, message names the key columns (`duplicate value for unique key (email, d, n, f, b, t)`), `value` is a compact JSON array in rule order with JSON-native values: `["a@x.com","2026-10-20",5,1.5,true,"2026-10-20T10:00:05"]`. A comma and a quote inside values are escaped (`["x, y","q\"uote"]`), non-ASCII stays unescaped, a newline is escaped, and 400+400-character values truncate to 500. Single-column failures set `column` and the text value (`p`, `true`, `1.5`) |
| Q7-3 `fail_run` | the whole chunk is evaluated, then `RejectionLimitExceeded` names the first rejected row and rule (chunk `[7, None, 1, None]` with not_null + range min 5 → `row 11 failed not_null`); counters are not touched on the raising call (`rejected_rows` stays 0); the next clean chunk validates normally |
| Q7-4 | `regex` or `length` on a non-string column: `EtlError` when the `Validator` is built (`validate: regex applies only to string columns; 'n' is integer`); a non-string value that reaches a string column (`5`, `True`) raises `EtlError` and is never converted with `str()` |
| Regression of the earlier checks | six rules and the completeness test, one entry per failing rule, a row counted once, first occurrence kept across chunks, ratio strict `>`, regex 10,000-character value cap, 500-character truncation, original index kept: all still covered (43 tests in `test_validate.py`) |

## Suites (detached 0c009f0, shared Postgres 127.0.0.1:55432)
- `scripts/test-all.sh` (main's copy; the branch predates QA-04, so I ran it as an untracked file and removed it afterwards): 14 of 16 steps pass: hygiene, check_contracts, Redocly, mypy app, `mypy --strict app/etl`, `pytest backend/tests` (**412 passed**; `test_validate.py`: 43), fixtures (46), integration (33 passed, 21 skipped), and all six frontend steps (33 tests). The two failing steps are `ruff check`/`format --check backend tests`, and they fail **only in `tests/fixtures/*.py`, which this branch does not touch** (its base predates QA-04's lint fix `c95c4ba`). Run on the branch's own paths, `ruff check` and `ruff format --check` over `backend` pass from the root and from `backend/` (37 files). They will pass after a rebase onto main.
- Worktree clean afterwards.

## Needs ruling
None new. The earlier points 1 to 4 are closed by Q7 (null skipping, composite value shape, `fail_run` timing, `regex` on non-strings).

## Defects
None. Info: the per-cell Python loops are unchanged; throughput should be measured in ETL-07 (REQ-61).
