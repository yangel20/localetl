# Synthetic test fixtures

All data is fake (`@example.com`, generated names). Nothing here is real or personal.
Regenerate with `python3 tests/fixtures/build_fixtures.py` (deterministic; a test checks it).
`expected.json` holds the expected counts/outcomes; **do not edit by hand**.

**Counting (decision Q3, architecture §5):** `expected.json` uses the five counters `extracted_count`, `loaded_count`, `rejected_count`, `duplicate_dropped_count`, `null_dropped_count`. Dropped rows are never rejected. For every `succeeded` scenario `extracted_count = loaded_count + rejected_count + duplicate_dropped_count + null_dropped_count` (asserted at generation time and in the tests); failed runs have `loaded_count` 0.

## Orders (match `contracts/examples/pipeline/valid/orders_full.json`)
| File | Purpose |
|---|---|
| `csv/orders_clean.csv` | 200 valid rows with messy-but-valid values (padding, case, `done`/`cancel` aliases, blank `Is Gift`). With `orders_full.json`: read 200, rejected 0, loaded 200; appended twice → 400. |
| `csv/orders_nulls.csv` + `pipelines/orders_nulls.json` | 22 rows: 5 null e-mails removed by `drop_null_rows` (`null_dropped_count` 5), 2 null `order_id`s **rejected** (`not_null`, first removal wins), 15 loaded. |
| `csv/orders_chunk_dupes.csv` | 16 rows with `order_id` duplicates straddling the chunk boundary for `chunk_rows` 2, 3, 5, 7 and 9; row 9 (id 5) is rejected by `range` but still registers its key, so row 10 is duplicate-dropped. Counters must be identical for chunk sizes 1, 2, 3, 5, 7, 9, 50000: extracted 16, loaded 10, rejected 1, duplicate-dropped 5, null-dropped 0. |
| `csv/orders_dirty.csv` | 96 rows: 70 good, 23 bad (each breaks exactly one rule: `type_cast` 5, `not_null` 3, `range` 6, `allowed_values` 3, `regex` 3, `length` 3), 3 conflicting duplicate `Order ID`s. |
| `pipelines/orders_dirty_reject.json` | `orders_full` + ratio 0.5: rejected 23, duplicate-dropped 3, loaded 70. |
| `pipelines/orders_dirty_unique.json` | no `deduplicate`: the `unique` rule rejects 3 more (26), duplicate-dropped 0, loaded 70. |
| `pipelines/orders_dirty_failrun.json` | `fail_run`: first rejection fails the run, nothing published. |
| `contracts/.../orders_full.json` on dirty | 23/96 > 0.1 → run fails, nothing published. |
| `pipelines/orders_append.json` / `orders_append_mismatch.json` | append onto `orders`; the mismatch variant has `amount` as string → `LoadError`. |

`pipelines/*.json` are derived from the contract example by the generator and validated against the schema by the tests.
Per-file `parse_error` and `unique` expectations are in `expected.json`; the `unique` rule is unreachable with `orders_full.json` because `deduplicate` runs first.

## Format cases (`csv/`)
`empty`, `header_only` (+ `_no_newline`), `bom_utf8`, `latin1`, `cp1252`, `invalid_utf8`, `semicolon`, `tab.tsv`, `pipe`, `crlf`, `quoted_multiline`, `no_header`, `ragged_rows`, `duplicate_headers`, `blank_lines`, `all_null_column`, `types_mixed`, `wide_500` (accepted boundary), `too_many_columns_501` (rejected), `hostile_columns` (SQL-injection-like and non-identifier headers and values).
Expected outcomes are in `expected.json` under `formats`. With `orders_full.json` alone `drop_null_rows` on `order_id` never fires (`nullable: false` rejects null IDs first); `orders_nulls.json` drops on a nullable column instead.

## CSV structure cases (QA-03c, decision Q4, architecture §5 "CSV structure and malformed input")
Every expectation below is in `expected.json` (`formats`), written by hand in `build_fixtures.py` and cross-checked in `test_fixtures.py` by an independent stdlib `csv` (strict) reference tokenizer. Row numbers are 1-based **record** ordinals (header and blank lines excluded). `parse_error` entries have `column = null`, message `expected N fields, found M`, and `value` = the fields joined with the delimiter.

| File | Expectation |
|---|---|
| `ragged_rows.csv` | 6 records; rows 2, 3, 5 `parse_error`; 3 well-formed. With `pipelines/ragged_reject.json`: extracted 6, loaded 3, rejected 3. |
| `duplicate_headers.csv` | `CsvFormatError`: `duplicate header names: "id" (columns 1, 5), "name" (columns 2, 3)` |
| `empty_header.csv`, `empty_header_trailing.csv`, `empty_and_duplicate_header.csv` | `CsvFormatError` `header in column N is empty` (Q4-a); empty names are reported before duplicates |
| `unterminated_quote.csv` | `CsvFormatError`: quoted field still open at end of file (wording not specified) |
| long field | generated inside the test, never committed: 131,072 characters accepted, 131,073 `CsvFormatError` |
| `stray_quote.csv` | row 2 `parse_error` (characters after a closing quote), row 3 parses; the entry's `value` is unspecified (see below) |
| `literal_quote.csv` | `ab"c` in an unquoted field is data, no error |
| `trailing_delimiter_first_row.csv` | row 1 `1,a,` has 3 fields vs 2: `parse_error`; no column shift |
| `quoted_multiline_ragged.csv` | a multi-line quoted field is one record (8 physical lines, 5 records); rows 3 and 4 `parse_error` |
| `blank_lines_ragged.csv` | 3 blank lines are skipped; a whitespace-only line is a one-field record; rows 2, 3, 5 `parse_error` |
| `headerless_ragged.csv`, `headerless_ragged_first_short.csv` | no header: the first record sets the width (Q4-d); in the second file the first record is the short one, so rows 2–4 are rejected |
| `malformed_chunk_straddle.csv` | 7 records, rows 2, 3, 6 malformed; with `chunk_rows=2` rows 2 and 3 straddle a boundary. Counters are identical for `chunk_rows` 1, 2, 3, 50000: extracted 7, loaded 4, rejected 3; cumulative counters after each `chunk_rows=2` chunk are in `expected.json` (`loaded_count` stays 0 until publish) |
| `parse_error_dedupe.csv` + `pipelines/parse_error_dedupe.json` | rule 9: the malformed row 2 registers no `deduplicate` key, so row 3 (same id) loads; row 5 is duplicate-dropped: extracted 5, loaded 3, rejected 1, duplicate-dropped 1 |
| `pipelines/ragged_failrun.json` on `ragged_rows.csv` | `fail_run` (Q4-b): the first `parse_error` (row 2) fails the run, nothing published; only completed chunks are reported (Q7-3), so the counters are 0 for `chunk_rows` 2 and 50000 and `extracted_count` 1 for `chunk_rows=1` |

**Spec gap (reported to the orchestrator):** Q4 rule 8 says a `parse_error` value is "the record's fields joined with the delimiter", but for a quoting fault Python's `csv.reader` raises instead of returning the fields, so the value cannot be built that way. The fixtures leave that `value` unspecified (`null`) and the self-test does not assert it.

## Large file (not committed)
`python3 tests/fixtures/generate_large.py [--rows 1000000] [--out data/fixtures/large_orders.csv]` streams a seeded 10-column CSV (1M rows ≈ 117 MB, REQ-61). `data/` is git-ignored.

## Self-test
`pip install pytest jsonschema && pytest tests/fixtures`
