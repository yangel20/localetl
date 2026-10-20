# QA review: ETL-04 Transform stage, independent

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-20
- Target: `etl/ETL-04-transform` @ **325d8c7** (one commit on `1af447d`; `main` has since moved to 4cd8cdd, and a trial `git merge-tree` against it is conflict-free)
- Diff vs base: `backend/app/etl/transform.py` (new) and `backend/tests/etl/test_transform.py` (new). Only etl-engineer paths; no export changes.
- Spec: board ETL-04 row; §5 stage 2; "Value casting" (A, rules 1-5, C-a, C-d); "Row outcome accounting" (first removal wins, dedupe across chunks); Q4 rule 9; Q7-3.

## Verdict: **PASS**
The code matches the merged spec as written. No defects. Seven semantics points raised by the agent, plus two of mine, need a ruling.

## Independent verification
My own script drove `Transformer` (and, for fixtures, the real `iter_csv_chunks` from ETL-02 overlaid in a scratch copy, because this branch predates ETL-02). It found no mismatches.
| Area | Result |
|---|---|
| Registry | exactly the 7 schema operations; a completeness test against the schema enum exists |
| Select/rename | target names and order follow the config; a missing source column raises `SourceMismatchError`; misaligned `row_numbers` raises `EtlError`; an empty chunk works |
| Casting table A through the stage (about 40 cells, all types) | accepted and rejected examples match the table: integers (`007`, `+5`, padded, bigint overflow, `1.0`, `1e3`, Arabic digits, `1_000`), floats (`.5`, `5.`, `1e3`, `nan`, `inf`, `1e400`, `1,5`), booleans (case-insensitive words; `t`, `on`, `2` rejected), strict ISO dates and datetimes (offset, `Z`, compact, week, date-only rejected); a `format` path rejects Arabic digits; all from the shared `casting.py` |
| Rules 1-4, C-a, C-d | whitespace-only cell → null (C-a); null → `not_null` for `nullable: false` (never `type_cast`); one `type_cast` entry per bad cell in row then column order; `column` = target name, `value` = raw cell (≤ 500), message `cannot cast "<v>" to <type>[ with format <f>]`; a row with several bad cells counts once (`rejected_rows`) |
| Dtypes | output columns are `object`; an integer column with nulls stays Python ints plus `None` (`[1, None, 3]`, never floats), as the ETL-05 note required |
| Row accounting | `rows_in - rejected - duplicate_dropped - null_dropped == rows_out` on every chunk; first removal wins (`nullable: false` + `drop_null_rows` on a null → rejected, not null-dropped); dropped rows are never rejections; rejected rows register no `deduplicate` key |
| Fixtures, chunk sizes 1, 2, 3, 5, 7, 9, 50000 | `orders_chunk_dupes`: 16 records, 5 duplicate-dropped, 0 null-dropped for every size; `orders_nulls`: 22 records, 2 rejected, 5 null-dropped, 0 duplicate; `ragged_rows` (with extraction): 6, 3 rejected, 3 out; `parse_error_dedupe`: 5, 1 rejected, 1 duplicate, 3 out; `orders_dirty`: 96 records, 8 rejected at this stage (`type_cast` 5 + `not_null` 3, matching `expected.json`'s per-rule counts) and 3 duplicate-dropped; the rest of the 23 bad rows belong to the validate stage |
| `fail_run` (Q7-3) | the whole chunk is cast first, then `RejectionLimitExceeded` names the first rejected row and rule (`row 2 failed type_cast: cannot cast "x" to integer`); clean chunks and dropped rows never raise; `reject_row` never raises; `not_null` also triggers it |
| Rules | no `eval`, `exec`, `DataFrame.query`/`.eval`; imports are stdlib, pandas and `app.etl` siblings |

## Suites (detached 325d8c7; this branch predates QA-04, so I ran the equivalent steps by hand; shared Postgres 127.0.0.1:55432, venv from backend[dev])
- `pytest backend/tests`: **423 passed** (`test_transform.py` alone: 54). `pytest tests/fixtures`: 43 passed.
- `mypy app`: no issues (21 files) · `mypy --strict app/etl`: no issues (9 files)
- `ruff check` and `ruff format --check` from `backend/`, and from the root with `--config backend/pyproject.toml backend`: pass (37 files)
- `contracts/tools/check_contracts.py .`: 0 failures
- Worktree clean after the run.

## Needs ruling (listed, not decided)
The agent's seven points, each confirmed by probe:
1. **`trim_whitespace` leaves `""` rather than null.** `'  '` becomes `''`, which `drop_null_rows`, `fill_null` and `not_null` do not treat as null. (C-a makes whitespace-only cells null only for non-string columns, before any transformation.)
2. **`change_case` `title` uses `str.title`.** `hello world` → `Hello World`, but `o'neil mcdonald` → `O'Neil Mcdonald`. `upper` also changes length for some characters (`ß` → `SS`).
3. **`replace_values` keys and replacements.** Keys are compared with the cast value rendered as a string: a float cell `1` is `"1.0"`, so a key `"1"` never matches a float column (confirmed: keys `1`/`1.0`/`1.5` on cells `1`, `1.0`, `1.50`, `2` gave `8.0, 8.0, 7.0, 2.0`); dates render ISO, booleans `true`/`false`. A replacement that cannot be cast to the column type is **not** caught by `validate_pipeline_config` (confirmed: valid), so the engine raises `EtlError` when `Transformer` is built, which is a run failure for a config that validated.
4. **`deduplicate` treats nulls as equal**, like SQL `DISTINCT` (confirmed: two null keys → one kept), whereas the Q7-1 rule for `unique` says a key with any null is never registered and never a duplicate. The spec text for `deduplicate` does not mention nulls.
5. **`round_number` rounds half-to-even on binary floats** (Python `round`): `0.5` → `0.0`, `1.5` → `2.0`, `2.5` → `2.0`, `2.675` to 2 places gives 2.67, and in my cases `2.25` → `2.2`, `0.35` → `0.3`, `1.05` → `1.1`.
6. **`fill_null` uses the (B) cast** (config scalars, so strings are stripped per the CSV rule and `5.0` is accepted for an integer column).
7. **`not_null` is checked right after casting**, before transformations (as §5 stage 2 orders it).

Two more from my probes:
8. **`replace_values` can introduce nulls into a `nullable: false` column.** Mapping a value to `null` there passes (confirmed: 0 rejections, the value is `None`), because `nullable` is checked only at the cast step. By the spec as written that is expected; whether it should be re-checked after transformations is open.
9. **`deduplicate` on floats compares typed values**, so cells `1`, `1.0`, `1.00`, `01` are one key (confirmed). This is consistent with comparing cast values, but it differs from `replace_values`, which compares rendered strings.

## Defects
None. Info: `TransformResult.rows_in` counts well-formed rows only; ETL-07 must add the `parse_error` records from `CsvChunk.records` to get the chunk's extracted count. The per-cell Python loops should be timed against REQ-61 in ETL-07.
