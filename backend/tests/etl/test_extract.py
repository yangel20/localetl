"""ETL-02: inspect_csv, preview_csv and the chunk iterator (Q4 structure, Q6-3 inference)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.etl import CsvFormatError, CsvOptions, inspect_csv, preview_csv
from app.etl.extract import CsvChunk, iter_csv_chunks

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
CSV = FIXTURES / "csv"
EXPECTED: dict[str, Any] = json.loads((FIXTURES / "expected.json").read_text())
FORMATS: dict[str, Any] = EXPECTED["formats"]
PLAIN = CsvOptions()


def opts(**kw: Any) -> CsvOptions:
    return CsvOptions(**kw)


def chunks(name: str, options: CsvOptions = PLAIN, chunk_rows: int = 50_000) -> list[CsvChunk]:
    return list(iter_csv_chunks(CSV / name, options, chunk_rows=chunk_rows))


def all_rows(cs: list[CsvChunk]) -> list[list[Any]]:
    return [row for c in cs for row in c.frame.values.tolist()]


def all_rejected(cs: list[CsvChunk]) -> list[Any]:
    return [r for c in cs for r in c.rejected]


# --------------------------------------------------------- file-level errors


def test_empty_file() -> None:
    with pytest.raises(CsvFormatError, match="empty"):
        inspect_csv(CSV / "empty.csv", PLAIN)
    with pytest.raises(CsvFormatError, match="empty"):
        preview_csv(CSV / "empty.csv", PLAIN)


@pytest.mark.parametrize("name", ["header_only.csv", "header_only_no_newline.csv"])
def test_header_only(name: str) -> None:
    with pytest.raises(CsvFormatError, match="no data rows"):
        inspect_csv(CSV / name, PLAIN)
    with pytest.raises(CsvFormatError, match="no data rows"):
        list(iter_csv_chunks(CSV / name, PLAIN))


def test_blank_lines_only_is_empty(tmp_path: Path) -> None:
    f = tmp_path / "b.csv"
    f.write_text("\n\n\r\n")
    with pytest.raises(CsvFormatError, match="empty"):
        inspect_csv(f, PLAIN)


def test_too_many_columns_boundary() -> None:
    assert len(inspect_csv(CSV / "wide_500.csv", PLAIN).columns) == 500
    with pytest.raises(CsvFormatError, match="501"):
        inspect_csv(CSV / "too_many_columns_501.csv", PLAIN)
    with pytest.raises(CsvFormatError, match="too many columns"):
        preview_csv(CSV / "too_many_columns_501.csv", PLAIN)


def test_too_many_columns_without_header(tmp_path: Path) -> None:
    f = tmp_path / "w.csv"
    f.write_text(",".join("x" for _ in range(501)) + "\n")
    with pytest.raises(CsvFormatError, match="too many columns"):
        inspect_csv(f, opts(has_header=False))


def test_undecodable_bytes() -> None:
    with pytest.raises(CsvFormatError, match="utf-8"):
        inspect_csv(CSV / "invalid_utf8.csv", PLAIN)
    assert inspect_csv(CSV / "invalid_utf8.csv", opts(encoding="latin-1")).row_count > 0


def test_undecodable_bytes_anywhere_in_the_file(tmp_path: Path) -> None:
    f = tmp_path / "late.csv"
    f.write_bytes(b"a,b\n" + b"1,x\n" * 50_000 + b"2,\xff\n")
    with pytest.raises(CsvFormatError, match="cannot be decoded"):
        inspect_csv(f, PLAIN)
    with pytest.raises(CsvFormatError):
        list(iter_csv_chunks(f, PLAIN, chunk_rows=1000))


def test_cp1252_undefined_byte_rejected(tmp_path: Path) -> None:
    f = tmp_path / "c.csv"
    f.write_bytes(b"a\n\x81\n")
    with pytest.raises(CsvFormatError):
        inspect_csv(f, opts(encoding="cp1252"))


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("duplicate_headers.csv", FORMATS["duplicate_headers.csv"]["message"]),
        ("empty_header.csv", FORMATS["empty_header.csv"]["message"]),
        ("empty_header_trailing.csv", FORMATS["empty_header_trailing.csv"]["message"]),
        ("empty_and_duplicate_header.csv", FORMATS["empty_and_duplicate_header.csv"]["message"]),
    ],
)
def test_header_faults_exact_messages(name: str, message: str) -> None:
    with pytest.raises(CsvFormatError) as info:
        inspect_csv(CSV / name, PLAIN)
    assert str(info.value) == message
    with pytest.raises(CsvFormatError):
        preview_csv(CSV / name, PLAIN)
    with pytest.raises(CsvFormatError):
        list(iter_csv_chunks(CSV / name, PLAIN))


def test_header_comparison_is_exact(tmp_path: Path) -> None:
    f = tmp_path / "h.csv"
    f.write_text("Id,id, id\n1,2,3\n")
    assert [c.name for c in inspect_csv(f, PLAIN).columns] == ["Id", "id", " id"]


def test_duplicate_headers_not_checked_without_header(tmp_path: Path) -> None:
    f = tmp_path / "h.csv"
    f.write_text("a,a\n1,2\n")
    p = inspect_csv(f, opts(has_header=False))
    assert [c.name for c in p.columns] == ["column_1", "column_2"] and p.row_count == 2


def test_empty_header_not_checked_without_header(tmp_path: Path) -> None:
    f = tmp_path / "h.csv"
    f.write_text(",a\n1,2\n")
    assert inspect_csv(f, opts(has_header=False)).row_count == 2


def test_unterminated_quote_is_file_level() -> None:
    for fn in (
        lambda: inspect_csv(CSV / "unterminated_quote.csv", PLAIN),
        lambda: list(iter_csv_chunks(CSV / "unterminated_quote.csv", PLAIN)),
    ):
        with pytest.raises(CsvFormatError, match="still open"):
            fn()


def test_unterminated_quote_after_chunks_were_yielded(tmp_path: Path) -> None:
    f = tmp_path / "u.csv"
    f.write_text('a,b\n1,x\n2,y\n3,z\n4,"open\n5,w\n')
    seen: list[CsvChunk] = []
    with pytest.raises(CsvFormatError, match="still open"):
        for c in iter_csv_chunks(f, PLAIN, chunk_rows=2):
            seen.append(c)
    assert [c.row_numbers for c in seen] == [[1, 2]]


def test_long_field_boundary(tmp_path: Path) -> None:
    ok = tmp_path / "ok.csv"
    ok.write_text("a,b\n1," + "x" * 131_072 + "\n")
    assert inspect_csv(ok, PLAIN).row_count == 1
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1," + "x" * 131_073 + "\n")
    with pytest.raises(CsvFormatError, match="131072"):
        inspect_csv(bad, PLAIN)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CsvFormatError):
        inspect_csv(tmp_path / "nope.csv", PLAIN)


def test_bad_arguments(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        inspect_csv(CSV / "orders_clean.csv", PLAIN, sample_rows=0)
    with pytest.raises(ValueError):
        preview_csv(CSV / "orders_clean.csv", PLAIN, limit=0)
    with pytest.raises(ValueError):
        list(iter_csv_chunks(CSV / "orders_clean.csv", PLAIN, chunk_rows=0))


# ------------------------------------------------------ encodings, delimiters


def test_bom_utf8_sig() -> None:
    e = FORMATS["bom_utf8.csv"]
    p = inspect_csv(CSV / "bom_utf8.csv", opts(encoding=e["encoding"]))
    assert p.columns[0].name == e["first_header"] and p.row_count == e["rows"]
    # without utf-8-sig the BOM stays in the first header (exact comparison)
    raw = inspect_csv(CSV / "bom_utf8.csv", PLAIN)
    assert raw.columns[0].name == "﻿" + e["first_header"]


@pytest.mark.parametrize("name", ["latin1.csv", "cp1252.csv"])
def test_single_byte_encodings(name: str) -> None:
    e = FORMATS[name]
    p = preview_csv(CSV / name, opts(encoding=e.get("encoding", "latin-1")))
    assert p.sampled_rows == e["rows"]
    if "name_row_1" in e:
        assert e["name_row_1"] in {v for v in p.rows[0].values()}


@pytest.mark.parametrize(
    ("name", "delimiter"), [("semicolon.csv", ";"), ("tab.tsv", "\t"), ("pipe.csv", "|")]
)
def test_delimiters(name: str, delimiter: str) -> None:
    e = FORMATS[name]
    p = inspect_csv(CSV / name, opts(delimiter=delimiter))
    assert len(p.columns) == e["columns"] and p.row_count == e["rows"]


def test_wrong_delimiter_gives_single_column() -> None:
    p = inspect_csv(CSV / "semicolon.csv", PLAIN)
    assert len(p.columns) == 1


def test_crlf_and_quoted_multiline() -> None:
    assert inspect_csv(CSV / "crlf.csv", PLAIN).row_count == FORMATS["crlf.csv"]["rows"]
    p = inspect_csv(CSV / "quoted_multiline.csv", PLAIN)
    assert p.row_count == FORMATS["quoted_multiline.csv"]["rows"]
    assert len(p.columns) == FORMATS["quoted_multiline.csv"]["columns"]
    pv = preview_csv(CSV / "quoted_multiline.csv", PLAIN)
    assert any("\n" in (v or "") for r in pv.rows for v in r.values())


def test_custom_quote_char(tmp_path: Path) -> None:
    f = tmp_path / "q.csv"
    f.write_text("a,b\n1,'x,y'\n2,\"z\"\n")
    pv = preview_csv(f, opts(quote_char="'"))
    assert pv.rows[0]["b"] == "x,y" and pv.rows[1]["b"] == '"z"'


def test_no_header_naming() -> None:
    e = FORMATS["no_header.csv"]
    p = inspect_csv(CSV / "no_header.csv", opts(has_header=e["has_header"]))
    assert [c.name for c in p.columns] == e["columns"] and p.row_count == e["rows"]
    pv = preview_csv(CSV / "no_header.csv", opts(has_header=False))
    assert list(pv.rows[0]) == e["columns"]


def test_hostile_column_names_pass_through_untouched(tmp_path: Path) -> None:
    # The committed fixture has an empty header in column 15 (Q4-a rejects it: see below);
    # with that one name filled in, every hostile name is accepted verbatim.
    lines = (CSV / "hostile_columns.csv").read_text().splitlines(keepends=True)
    f = tmp_path / "hostile.csv"
    f.write_text(lines[0].replace(",,ok", ",filled,ok", 1) + "".join(lines[1:]))
    p = inspect_csv(f, PLAIN)
    names = [c.name for c in p.columns]
    assert len(names) == 16 and "name; DROP TABLE x;--" in names and 'a"b' in names
    assert "ünïcode_列" in names


def test_committed_hostile_fixture_has_an_empty_header_so_q4a_rejects_it() -> None:
    with pytest.raises(CsvFormatError, match="header in column 15 is empty"):
        inspect_csv(CSV / "hostile_columns.csv", PLAIN)


# ----------------------------------------------------------- inference, nulls


def test_types_mixed_inference() -> None:
    p = inspect_csv(CSV / "types_mixed.csv", PLAIN)
    assert {c.name: c.inferred_type for c in p.columns} == {
        "i": "integer",
        "f": "float",
        "b": "boolean",
        "d": "date",
        "dt": "datetime",
        "s": "string",
    }
    assert {c.name: c.null_count for c in p.columns} == {
        "i": 0,
        "f": 1,
        "b": 0,
        "d": 1,
        "dt": 1,
        "s": 1,
    }


def test_all_null_column() -> None:
    p = inspect_csv(CSV / "all_null_column.csv", PLAIN)
    col = next(c for c in p.columns if c.name == "empty_col")
    assert (
        col.inferred_type == "string"
        and col.null_count == FORMATS["all_null_column.csv"]["null_count"]["empty_col"]
    )


def test_inference_uses_casting_rules(tmp_path: Path) -> None:
    f = tmp_path / "t.csv"
    f.write_text(
        "zero_one,yes_no,comma,w,when\n"
        '0,yes,"1,5",  ,2024-01-31T10:00Z\n'
        "1,no,2,  ,2024-01-31T10:00Z\n"
    )
    types = {c.name: c.inferred_type for c in inspect_csv(f, PLAIN).columns}
    assert types == {
        "zero_one": "integer",
        "yes_no": "boolean",
        "comma": "string",
        "w": "string",
        "when": "string",
    }


def test_whitespace_only_cells_are_null_for_typed_columns(tmp_path: Path) -> None:
    f = tmp_path / "t.csv"
    f.write_text("n,s\n1, \n  ,x\n2,y\n")
    p = inspect_csv(f, PLAIN)
    n, s = p.columns
    assert (n.inferred_type, n.null_count) == ("integer", 1)
    assert (s.inferred_type, s.null_count) == ("string", 0)


def test_sample_rows_limits_inference_but_not_row_count(tmp_path: Path) -> None:
    f = tmp_path / "s.csv"
    f.write_text("a\n" + "1\n" * 10 + "x\n")
    assert inspect_csv(f, PLAIN, sample_rows=10).columns[0].inferred_type == "integer"
    assert inspect_csv(f, PLAIN, sample_rows=11).columns[0].inferred_type == "string"
    assert inspect_csv(f, PLAIN, sample_rows=10).row_count == 11


@pytest.mark.parametrize(
    "name", ["orders_clean.csv", "orders_dirty.csv", "orders_nulls.csv", "orders_chunk_dupes.csv"]
)
def test_orders_row_counts(name: str) -> None:
    entry = EXPECTED[name]
    expected = (
        entry["extracted_count"]
        if "extracted_count" in entry
        else entry.get("counters", entry.get("counters_identical_for_every_chunk_size"))[
            "extracted_count"
        ]
    )
    assert inspect_csv(CSV / name, PLAIN).row_count == expected
    assert sum(c.records for c in chunks(name, chunk_rows=7)) == expected


# ------------------------------------------------------------------ preview


def test_preview_limit_and_values() -> None:
    p = preview_csv(CSV / "orders_clean.csv", PLAIN, limit=5)
    assert p.sampled_rows == 5 and len(p.rows) == 5
    assert all(isinstance(v, (str, type(None))) for r in p.rows for v in r.values())
    assert list(p.rows[0]) == [c.name for c in p.columns]
    assert preview_csv(CSV / "orders_clean.csv", PLAIN).sampled_rows == 50
    assert preview_csv(CSV / "orders_clean.csv", PLAIN, limit=500).sampled_rows == 200


def test_preview_empty_fields_are_none() -> None:
    p = preview_csv(CSV / "types_mixed.csv", PLAIN)
    assert p.rows[2]["f"] is None and p.rows[2]["i"] == "3"


# ---------------------------------------------------- malformed (Q4) fixtures

MALFORMED = [
    k
    for k, v in FORMATS.items()
    if isinstance(v, dict) and "parse_errors" in v and "row_count" in v
]


def test_malformed_fixture_list_is_not_empty() -> None:
    assert len(MALFORMED) >= 9


@pytest.mark.parametrize("name", MALFORMED)
def test_malformed_fixtures_match_expected(name: str) -> None:
    e = FORMATS[name]
    options = opts(has_header=e["has_header"])
    profile = inspect_csv(CSV / name, options)
    assert profile.row_count == e["row_count"]
    cs = chunks(name, options)
    assert sum(c.records for c in cs) == e["row_count"]
    assert len(all_rows(cs)) == e["well_formed_count"]
    got = all_rejected(cs)
    assert [r.row_number for r in got] == [p["row_number"] for p in e["parse_errors"]]
    for r, p in zip(got, e["parse_errors"], strict=True):
        assert (r.rule, r.column, r.message) == (p["rule"], p["column"], p["message"])
        if p["value"] is not None:  # a quoting-fault value is unruled (Q8-5): not asserted
            assert r.value == p["value"]
    if "columns" in e:
        assert [c.name for c in profile.columns] == e["columns"]
        assert list(cs[0].frame.columns) == e["columns"]
    pv = preview_csv(CSV / name, options, limit=500)
    assert pv.sampled_rows == e["well_formed_count"]


def test_stray_quote_only_rejects_its_record() -> None:
    cs = chunks("stray_quote.csv")
    assert [r.row_number for r in all_rejected(cs)] == [2]
    assert all_rows(cs) == [["1", "Ana", "10"], ["3", "Cy", "30"]]
    assert cs[0].row_numbers == [1, 3]


def test_literal_quote_is_data() -> None:
    e = FORMATS["literal_quote.csv"]
    cs = chunks("literal_quote.csv")
    assert all_rejected(cs) == []
    assert all_rows(cs)[0][1] == e["cell_row_1_name"]


def test_trailing_delimiter_first_row_does_not_shift_columns() -> None:
    cs = chunks("trailing_delimiter_first_row.csv")
    assert [r.row_number for r in all_rejected(cs)] == [1]
    assert all_rows(cs)[0][0] == "2"
    assert list(cs[0].frame.columns) == ["id", "name"]


def test_short_rows_are_never_padded() -> None:
    rows = all_rows(chunks("ragged_rows.csv"))
    assert len(rows) == 3 and all(len(r) == 3 and None not in r for r in rows)


def test_blank_lines_skipped_and_whitespace_line_is_a_record() -> None:
    assert (
        inspect_csv(CSV / "blank_lines.csv", PLAIN).row_count == FORMATS["blank_lines.csv"]["rows"]
    )
    cs = chunks("blank_lines.csv")
    assert [n for c in cs for n in c.row_numbers] == [1, 2, 3]
    rej = all_rejected(chunks("blank_lines_ragged.csv"))
    assert [r.value for r in rej] == ["2", "3,c,d", " "]


def test_quoted_multiline_ragged_is_one_record() -> None:
    e = FORMATS["quoted_multiline_ragged.csv"]
    rej = all_rejected(chunks("quoted_multiline_ragged.csv"))
    assert rej[1].value == "4,x\ny,extra"
    assert (
        e["physical_lines"] == 8
        and inspect_csv(CSV / "quoted_multiline_ragged.csv", PLAIN).row_count == 5
    )


def test_parse_error_value_truncated_to_500(tmp_path: Path) -> None:
    f = tmp_path / "t.csv"
    f.write_text("a,b\n" + ",".join(["x" * 200] * 5) + "\n1,2\n")
    rej = all_rejected(chunks_of(f))
    assert len(rej[0].value or "") == 500


def chunks_of(path: Path, options: CsvOptions = PLAIN, chunk_rows: int = 50_000) -> list[CsvChunk]:
    return list(iter_csv_chunks(path, options, chunk_rows=chunk_rows))


def test_quoting_fault_row_is_reported_without_asserting_value() -> None:
    (rej,) = all_rejected(chunks("stray_quote.csv"))
    assert (rej.rule, rej.column, rej.message) == ("parse_error", None, "quoting fault")


# -------------------------------------------------------------- chunk straddle

STRADDLE = FORMATS["malformed_chunk_straddle.csv"]


@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 50_000])
def test_chunk_size_does_not_change_the_result(chunk_rows: int) -> None:
    reference = chunks("malformed_chunk_straddle.csv")
    cs = chunks("malformed_chunk_straddle.csv", chunk_rows=chunk_rows)
    assert sum(c.records for c in cs) == STRADDLE["row_count"]
    assert all_rows(cs) == all_rows(reference)
    assert [r.row_number for r in all_rejected(cs)] == [2, 3, 6]
    assert [n for c in cs for n in c.row_numbers] == [1, 4, 5, 7]
    assert all(c.records <= chunk_rows for c in cs)
    assert [c.records for c in cs[:-1]] == [chunk_rows] * (len(cs) - 1)


def test_chunk_boundaries_count_records_not_well_formed_rows() -> None:
    cs = chunks("malformed_chunk_straddle.csv", chunk_rows=2)
    assert [sorted([*c.row_numbers, *(r.row_number for r in c.rejected)]) for c in cs] == STRADDLE[
        "chunk_rows_2_chunks"
    ]
    # rows 2 and 3 are malformed and straddle the first boundary
    assert [len(c.rejected) for c in cs] == [1, 1, 1, 0]


def test_malformed_record_never_splits_across_chunks() -> None:
    cs = chunks("quoted_multiline_ragged.csv", chunk_rows=1)
    assert [c.records for c in cs] == [1] * 5
    assert [r.row_number for c in cs for r in c.rejected] == [3, 4]


def test_multiline_quoted_record_not_split() -> None:
    cs = chunks("quoted_multiline.csv", chunk_rows=1)
    assert len(cs) == 3 and all(c.records == 1 for c in cs)


def test_all_malformed_chunk_has_empty_frame_with_columns() -> None:
    cs = chunks("headerless_ragged_first_short.csv", opts(has_header=False), chunk_rows=1)
    assert [len(c.frame) for c in cs] == [1, 0, 0, 0]
    assert list(cs[1].frame.columns) == ["column_1", "column_2"]


def test_chunk_cells_are_strings_or_none() -> None:
    cs = chunks("types_mixed.csv", chunk_rows=2)
    cells = [v for c in cs for row in c.frame.values.tolist() for v in row]
    assert all(v is None or isinstance(v, str) for v in cells)
    assert None in cells and "" not in cells


def test_empty_trailing_field_is_a_null_cell(tmp_path: Path) -> None:
    f = tmp_path / "n.csv"
    f.write_text("a,b\n1,\n,2\n")
    (c,) = chunks_of(f)
    assert c.frame.values.tolist() == [["1", None], [None, "2"]]


def test_parse_error_rows_register_no_row_in_frame() -> None:
    cs = chunks("parse_error_dedupe.csv")
    assert 2 not in [n for c in cs for n in c.row_numbers]
    assert [r.row_number for r in all_rejected(cs)] == [2]
