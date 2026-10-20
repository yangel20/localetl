# QA review: ETL-02 CSV inspect, preview and chunked extraction, independent

- Reviewer: qa-engineer (QA-06) · Date: 2026-10-20
- Target: `etl/ETL-02-csv-extract` @ **22d5dfb**, two commits on `c87b048`: `833b87a` (implementation) and `22d5dfb` (the hostile_columns test now asserts the real file; test file only). `main` is f7806b2; ancestry of c87b048 confirmed. The `-prerebase` backups were not touched.
- Diff vs base: `backend/app/etl/extract.py` and `backend/tests/etl/test_extract.py` only (etl-engineer paths); no export changes (`iter_csv_chunks` and `CsvChunk` are module-level, not part of `app.etl`'s 26 public names).
- Spec: board ETL-02 row; merged §5 "Behaviour contract", "CSV structure and malformed input" (rules 1-9, Q4-a to Q4-d), Q6-3 inference order.

## Verdict: **PASS**
The code matches the merged spec as written. No defects. Findings that need a ruling are listed below.

## Independent verification
I drove the real functions from my own script against the committed fixtures and `tests/fixtures/expected.json`, not from the agent's tests:
| Area | Result |
|---|---|
| Every `formats` entry in expected.json (33 files) | All match: file-level errors raise `CsvFormatError` with the exact expected message (`duplicate header names: "id" (columns 1, 5), "name" (columns 2, 3)`, `header in column 2 / 3 is empty`, empty-before-duplicate); every structure fixture matches `row_count`, `well_formed_count`, the `parse_error` row numbers, rule, `column = None`, message and value (quoting-fault values are unasserted by the fixtures); `names`, `columns` and `null_count` entries match; BOM, latin-1, cp1252, `;` `\t` `\|`, CRLF, multi-line, no-header, blank lines, all-null column and hostile_columns (16 names verbatim, 2 rows, accepted) all match |
| QA-03c cases | stray quote (row 2 rejected, row 3 parses), literal `ab"c`, trailing delimiter on the first data row (no column shift), multi-line quoted record counted once, blank lines skipped, whitespace-only line is a one-field record, headerless ragged and first-record-short (Q4-d), parse_error dedupe fixture records |
| `chunk_rows` ∈ {1, 2, 3, 7, 50000} on `malformed_chunk_straddle.csv` | records 7, rejected 3, rejected rows [2, 3, 6], loaded row numbers [1, 4, 5, 7], no chunk over `chunk_rows` records; the cumulative counters after each `chunk_rows=2` chunk equal `expected.json` (2/1, 4/2, 6/3, 7/3). Chunks hold [2,2,2,1] records and the frames hold fewer rows than records where records were malformed |
| Field limit | a 131,072-character field is accepted; 131,073 raises `CsvFormatError: a field is longer than 131072 characters` |
| Columns | `wide_500` accepted (500); `too_many_columns_501` → `too many columns: 501 (maximum 500)` |
| Encodings × delimiters | all 16 combinations round-trip (header names, row count, inferred types integer/string/float); a late undecodable byte (row 20,001) is found by `inspect_csv` (`file is not valid utf-8: byte N cannot be decoded`); `invalid_utf8.csv` reads as latin-1 |
| `has_header=false` | columns `column_1..column_N`; the first record is data and sets the width; a header-only-looking file with `has_header=false` is 1 data row |
| Empty, header-only (with and without newline), only blank lines, header plus blank lines | each `CsvFormatError` with a clear message |
| Type inference (Q6-3 order, `casting.infer_type`) | `types_mixed.csv`: integer, float, boolean, date, datetime, string; null counts count empty cells in non-string columns; all-null column is `string` |
| Rules | stdlib `csv.reader(strict=True)` over a strictly decoded `newline=""` stream; no pandas parsing; no new dependency; `app.etl` import rule intact; no `eval`/`exec` |

## Suites (detached 22d5dfb, shared Postgres 127.0.0.1:55432, venv from backend[dev])
- `pytest backend/tests`: **443 passed** (`test_extract.py` alone: 74). `pytest tests/fixtures`: **46 passed**.
- `mypy app`: no issues (20 files) · `mypy --strict app/etl`: no issues (8 files)
- `ruff check` and `ruff format --check` from `backend/`: pass; `ruff check --config backend/pyproject.toml backend` and the format check from the repo root: pass (36 files)
- `contracts/tools/check_contracts.py .`: 0 failures
- Worktree clean after the run.

## `iter_csv_chunks` for ETL-07
Suitable. `CsvChunk(frame, row_numbers, rejected, records)`:
- `records` counts well-formed plus malformed records in the chunk, so `extracted_count` accumulates exactly; `row_numbers[i]` is the global 1-based record ordinal of `frame` row `i`; `rejected` carries that chunk's `parse_error` entries.
- Frames are `object` dtype with `str` or `None` (empty string → `None`) and the header names as columns; an all-malformed chunk gives an empty frame with the right columns, which downstream code must tolerate.
- A file-level fault found at record N raises `CsvFormatError` from the generator after earlier chunks were yielded and without yielding the partial chunk. That is the Q4 "Chunks" rule. The header is validated before the first chunk.
- `chunk_rows < 1` raises `ValueError`.

## Needs ruling (listed, not decided)
1. **(a) A faulty first record is file-level.** If the header record (or, without a header, the first record) has a quoting fault, extraction raises `CsvFormatError("the first row cannot be parsed: ...")` instead of a `parse_error`, because no width can be taken from it. Confirmed for both modes (Q8-12). The spec's Q4-d covers a malformed first record that has the wrong field *count*, not one that cannot be tokenized.
2. **(b) The quoting-fault `value` is `None`** (`_fault_value`, Q8-5): `RejectedRow.value` is null for these entries. Rule 8's "fields joined with the delimiter" cannot be met for them.
3. **(c) Lines consumed by a quoting fault are lost.** A fault inside or after a multi-line quoted field consumes every physical line up to the fault; they become one `parse_error` record, and tokenizing resumes at the next line. Confirmed: a fault on the second physical line of a multi-line field yields one rejected record, then the next record parses. The spec says only that a fault is "confined to one record".
4. **(d) `csv.field_size_limit` is process-global.** `_Source` sets it to 131,072 each time it opens a file (the default). Another thread or library that raised the limit would be silently reset, and a change here affects the whole process. It is not thread-safe if two readers want different limits; the limit is a constant today.
5. **(e) Preview `sampled_rows` equals the rows returned**, and inference and `null_count` run over those rows only. The preview stops reading after `limit` well-formed records, so a file-level fault further in is found only by `inspect_csv` at upload. Matches Q4's "number of well-formed records examined"; confirm it is intended that preview alone can succeed on a file that `inspect_csv` rejects.
6. **NUL character in a cell is accepted.** `a\x00b` passes extraction and inference (Python 3.11's reader allows it) and would be rejected by PostgreSQL at load: ETL-06 raises `LoadError`, so the whole run `failed` late instead of a `parse_error` rejection. Q4 does not list NUL as a file-level or row-level fault.
7. **A whitespace-only header name** (`id, `) is accepted as non-empty, and header names differing only by case (`id,ID`) are distinct, both as Q4 rule 1 says (exact comparison, no trimming). A UTF-8 file with a BOM read as `utf-8` (not `utf-8-sig`) keeps the BOM in the first header (`﻿id`), as the rule implies; the preview would show an invisible character.
8. **A missing or unreadable file** raises `CsvFormatError("cannot open file: ...")`. §5 uses `CsvFormatError` for malformed content; whether an I/O failure should be a different error is unspecified.

## Defects
None. Info: nothing in the module logs, which is fine for a library; `inspect_csv` keeps at most `sample_rows` rows in memory, so memory is bounded for large files.
