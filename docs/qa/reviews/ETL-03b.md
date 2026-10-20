# QA review: ETL-03b Shared casting, independent

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-20
- Target: `etl/ETL-03b-shared-casting` @ **b46e3fb** (one commit on `main` 0961252; ancestry confirmed; `main` is now da1d49d)
- Diff vs base: `backend/app/etl/casting.py` (new), `config.py`, `backend/tests/etl/test_casting.py` (new), `test_config.py`. Only etl-engineer paths; `app/etl/__init__.py` unchanged (no export changes).
- Spec: merged architecture §5 "Value casting" (tables A and B, general rules 1-5, inference, C-a to C-e) and §6 rules 4, 5, 7.

## Verdict: **PASS**
The code matches the merged spec as written. I found no defects. Two points the orchestrator named, plus four more I found, need a ruling.

## Independent verification
I wrote my own case battery from the spec text, not from the agent's tests. About 290 cases ran against `cast_cell`, `cast_config_value`, `infer_type`, `format_error` and `validate_pipeline_config`; **all matched** except two where my own expectation was wrong (see inference note).
| Area | Result |
|---|---|
| (A) integer | `007`, `+5`, ` 12 ` accepted; `-2^63` and `2^63-1` accepted; `2^63` and `-2^63-1` rejected; `1.0`, `1e3`, `١٢`, full-width `１２`, `1_000`, `1,000`, `0x10`, `--1`, `+` rejected; a 5,000-digit string is rejected (Python's digit limit) instead of crashing |
| (A) float | `.5`, `5.`, `1e3`, `1E-2`, `+.5e1` accepted; `nan`, `inf`, `Infinity`, `1e400`, `-1e400`, `1e999999999999999`, `1,5`, `1_0.5`, `١.٥`, `1.5.5`, `e5`, `1e`, `0x1p3` rejected |
| (A) boolean | true/false/yes/no/1/0 in any case and padded; `t`, `y`, `on`, `2`, `truee` and full-width `ＴＲＵＥ` rejected |
| (A) date, no format | ISO only; compact, week, with-time, `2026-02-30`, `2026-02-29`, `2026-1-2`, Arabic-digit and `2026/10/20` rejected; `2024-02-29` accepted |
| (A) datetime, no format | `T` or one space, `HH:MM[:SS[.f{1,6}]]` accepted; 7 fraction digits, `Z`, `+02:00`, compact, bare date, two spaces, `24:00`, `10:60`, `:60`, `T1:00`, `T10` and Arabic digits rejected |
| (A) with `format` | whole-value match; non-ASCII digits rejected on the strptime path (all-Arabic and mixed); `%y` pivot (`69` → 1969, `68` → 2068); a `date` format gives a `date`; a `datetime` format with no time gives midnight |
| C-e directive lists | `%H %I %M %S %f %p %X %c` forbidden in a `date` format; `%z %Z` forbidden in both; `%%H` and `100%%` are literals and allowed; `%%%H` correctly sees `%H`; `%x %j %b` allowed |
| Rules 1-2, C-a | non-strings are stripped; a whitespace-only value is null; strings are never stripped (`'  x '` unchanged, `''` stays `''`); null is never cast |
| (B) integer config | `5`, `5.0`, `"5"`, `" 5 "`, `1e18` accepted; `true`, `false`, `5.5`, `"1.0"`, `"5.5"`, `2^63`, `-2^63-1`, `1e20`, NaN, inf, `""`, `null`, `"١٢"`, lists, objects rejected |
| (B) float config | `5`, `5.5`, `"5.5"`, `-0.0` accepted; `true`, NaN, inf, `10**400`, `"1e400"`, `"nan"`, `""` rejected |
| (B) boolean config | `true/false`, `0/1/1.0`, `"yes"`, `"NO"` accepted; `2`, `0.5`, `"t"`, `""`, NaN rejected |
| (B) date/datetime config | ISO only; compact, offset, `Z`, numbers, bools, `2026-02-30` rejected; **the column `format` is ignored** (C-b) |
| (B) string config | JSON strings only (including `""` and padded); `5`, `5.0`, `true`, `null` rejected (C-c) |
| Inference | order integer, float, boolean, date, datetime, string; all-null and empty give string; `0/1` give integer; `yes/no` give boolean |
| `validate_pipeline_config` | Every contract example behaves as labelled (11/11); every `tests/fixtures/pipelines/*.json` (including the three QA-03c ones) is valid; error paths are unchanged (`/validations/i/min`, `/transformations/i/value`, `/validations/i/values/j`, `/columns/i/format`, `/validations/i`) |
| §6 rule 4 | integer bounds must be integral (`5.0` ok, `5.5` rejected); bounds above bigint rejected; `1e400` → "float is not finite"; date bounds ISO only; offsets, `Z` and compact rejected; min > max reported at `/validations/i`; a string bound on a number column and a number bound on a date column are rejected |
| §6 rule 5 | `fill_null` and `allowed_values` use the (B) table; the `allowed_values` path points to the exact index |
| §6 rule 7 | format only on date/datetime; `%H` in a `date` format and `%z` in either are rejected at `/columns/i/format`; `%%H` allowed |
| Purity and rules | `casting.py` imports only stdlib and `.types`; no `eval`, `exec` or `.query(`; one set of functions serves config, transform and inference |

## Suites (detached b46e3fb, shared Postgres 127.0.0.1:55432, venv from backend[dev])
- `pytest backend/tests`: **310 passed**, 1 third-party warning. `test_casting.py` plus `test_config.py`: 254 passed. Tests exist per table row and per general rule (rules 1-5 by name).
- `mypy app`: no issues (19 files) · `mypy --strict app/etl`: no issues (7 files)
- `ruff check` and `ruff format --check` from `backend/`: pass (32 files). `ruff check --config backend/pyproject.toml backend` from the repo root: pass.
- `contracts/tools/check_contracts.py .`: 0 failures
- Worktree clean after the run.

## Needs ruling (listed, not decided)
1. **Malformed strptime format** (orchestrator's point a). `%Q` passes config validation, so at run time every non-null cell of that column fails `type_cast`. Confirmed (`fmt bad directive %Q` is valid). A trailing lone `%` behaves the same. Rule 7 does not say the format must be a valid strptime format.
2. **`datetime` format with no time directives** (point b). `%d/%m/%Y` on a `datetime` column is valid and yields midnight. Confirmed.
3. **Whitespace around config ISO strings.** (B) says date/datetime config values are "in the ISO form": `" 2026-10-20"` is rejected. But for integer, float and boolean, a string config value is "per the CSV rule", which strips, so `" 5 "` is accepted. The two are inconsistent in effect, though each matches its own table row.
4. **Empty or whitespace-only string config values** for integer, float and boolean columns are rejected ("an empty value is not a value"), because under the CSV rule they would be null. The spec doesn't say what a config value that casts to null means.
5. **Range bounds as strings on number columns.** Table B accepts `"5"` for an integer config scalar, but §6 rule 4 says "numeric bounds for numbers", and the code rejects `min: "5"`. It follows rule 4. Worth confirming that is intended.
6. **Inference consequence of the order.** `["1","true"]` and `["0","1","yes"]` infer `boolean`, because `1`/`0` are boolean words and boolean comes before date. That matches the stated rule (my first expectation was wrong), but a column mixing `1`/`0` and words becomes boolean while one mixing `2` and words is string.

## Defects
None. Info: spec rule 4's failure message (`cannot cast "<v>" to <type>`...) is a transform-stage (ETL-04) concern; `casting.py` raises `CastError` with a short reason only.
