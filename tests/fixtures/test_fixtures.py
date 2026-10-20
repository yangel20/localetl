"""Self-checks for the synthetic fixtures (stdlib + optional jsonschema).

Run: pytest tests/fixtures
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CSV = HERE / "csv"
ROOT = HERE.parents[1]
EXPECTED = json.loads((HERE / "expected.json").read_text())


def rows(name: str, encoding: str = "utf-8", delimiter: str = ",") -> list[list[str]]:
    with (CSV / name).open(encoding=encoding, newline="") as fh:
        return list(csv.reader(fh, delimiter=delimiter))


def test_generator_is_deterministic(tmp_path: Path) -> None:
    before = {p.name: p.read_bytes() for p in CSV.iterdir()}
    exp = (HERE / "expected.json").read_bytes()
    subprocess.run(
        [sys.executable, str(HERE / "build_fixtures.py")], check=True, capture_output=True
    )
    assert {p.name: p.read_bytes() for p in CSV.iterdir()} == before
    assert (HERE / "expected.json").read_bytes() == exp


def test_clean_orders_counts() -> None:
    r = rows("orders_clean.csv")
    assert len(r) - 1 == EXPECTED["orders_clean.csv"]["counters"]["extracted_count"] == 200
    assert len({row[0] for row in r[1:]}) == 200


COUNTERS = [
    "extracted_count",
    "loaded_count",
    "rejected_count",
    "duplicate_dropped_count",
    "null_dropped_count",
]


def _scenarios() -> list[tuple[str, dict]]:
    """Every expected entry that carries a counters block, with its outcome."""
    out: list[tuple[str, dict]] = []
    for file, entry in EXPECTED.items():
        if not isinstance(entry, dict):
            continue
        if "counters" in entry:
            out.append((file, entry))
        for name, sc in entry.get("scenarios", {}).items():
            out.append((f"{file}::{name}", sc))
        if "counters_identical_for_every_chunk_size" in entry:
            out.append(
                (file, {**entry, "counters": entry["counters_identical_for_every_chunk_size"]})
            )
    return out


def test_no_legacy_row_keys() -> None:
    text = (HERE / "expected.json").read_text()
    for legacy in ("rows_read", "rows_rejected", "rows_loaded", "rows_dropped"):
        assert legacy not in text


def test_counter_names_and_order() -> None:
    found = _scenarios()
    assert len(found) >= 7
    for name, sc in found:
        if "counters" in sc:
            assert list(sc["counters"]) == COUNTERS, name


def test_reconciliation_identity_for_every_successful_scenario() -> None:
    checked = 0
    for name, sc in _scenarios():
        if sc.get("outcome") == "succeeded":
            c = sc["counters"]
            assert c["extracted_count"] == (
                c["loaded_count"]
                + c["rejected_count"]
                + c["duplicate_dropped_count"]
                + c["null_dropped_count"]
            ), name
            checked += 1
    # clean, dirty_reject, dirty_unique, nulls, chunk_dupes, ragged_rows, malformed_chunk_straddle,
    # parse_error_dedupe
    assert checked == 8


def test_failed_scenarios_load_nothing() -> None:
    failed = [sc for _, sc in _scenarios() if sc.get("outcome") == "failed"]
    assert len(failed) >= 2
    assert all(sc["loaded_count"] == 0 for sc in failed)


def test_dirty_orders_scenarios() -> None:
    d = EXPECTED["orders_dirty.csv"]
    assert len(rows("orders_dirty.csv")) - 1 == d["extracted_count"]
    bad = sum(d["bad_rows_by_rule"].values())
    s = d["scenarios"]
    assert s["pipelines/orders_dirty_reject.json"]["counters"]["rejected_count"] == bad
    assert s["pipelines/orders_dirty_reject.json"]["counters"]["duplicate_dropped_count"] == 3
    assert s["pipelines/orders_dirty_unique.json"]["counters"]["rejected_count"] == bad + 3
    assert s["pipelines/orders_dirty_unique.json"]["counters"]["duplicate_dropped_count"] == 0
    assert bad / d["extracted_count"] > 0.1  # orders_full max_rejected_ratio must be exceeded


def test_null_dropped_case_exists() -> None:
    c = EXPECTED["orders_nulls.csv"]["counters"]
    assert (
        c["null_dropped_count"] > 0 and c["rejected_count"] > 0
    )  # null id rejected: first removal wins


def reference_counters(
    name: str, chunk: int, *, null_cols: tuple[int, ...] = (), dedup: bool
) -> dict[str, int]:
    """Tiny independent model of architecture section 5 rules for the orders files:
    cast/nullable (order_id) -> drop_null_rows -> deduplicate(order_id) -> range(amount >= 0)."""
    data = rows(name)[1:]
    seen: set[str] = set()
    c = dict.fromkeys(COUNTERS, 0)
    for start in range(0, len(data), chunk):
        for r in data[start : start + chunk]:
            c["extracted_count"] += 1
            if not r[0].strip() or not r[0].strip().lstrip("-").isdigit():
                c["rejected_count"] += 1
            elif any(not r[i].strip() for i in null_cols):
                c["null_dropped_count"] += 1
            elif dedup and r[0].strip() in seen:
                c["duplicate_dropped_count"] += 1
            else:
                seen.add(r[0].strip())  # key registered even if a later rule rejects the row
                if float(r[4]) < 0:
                    c["rejected_count"] += 1
                else:
                    c["loaded_count"] += 1
    return c


def test_chunk_boundary_duplicates() -> None:
    e = EXPECTED["orders_chunk_dupes.csv"]
    data = rows("orders_chunk_dupes.csv")[1:]
    for size, (a, b) in e["straddling_row_pairs_by_chunk_size"].items():
        assert a % int(size) == 0, "pair must straddle a chunk boundary"
        assert data[a - 1][0] == data[b - 1][0], "pair must share the dedup key"
    want = e["counters_identical_for_every_chunk_size"]
    assert want["duplicate_dropped_count"] > 0 and want["rejected_count"] > 0
    for size in e["chunk_sizes"]:
        assert reference_counters("orders_chunk_dupes.csv", size, dedup=True) == want, size


def test_reference_model_agrees_with_other_files() -> None:
    assert (
        reference_counters("orders_clean.csv", 7, dedup=True)
        == EXPECTED["orders_clean.csv"]["counters"]
    )
    assert (
        reference_counters("orders_nulls.csv", 3, null_cols=(0, 1), dedup=True)
        == EXPECTED["orders_nulls.csv"]["counters"]
    )


@pytest.mark.parametrize(
    "name,enc,delim",
    [
        ("bom_utf8.csv", "utf-8-sig", ","),
        ("latin1.csv", "latin-1", ","),
        ("cp1252.csv", "cp1252", ","),
        ("semicolon.csv", "utf-8", ";"),
        ("tab.tsv", "utf-8", "\t"),
        ("pipe.csv", "utf-8", "|"),
    ],
)
def test_format_fixtures_parse(name: str, enc: str, delim: str) -> None:
    r = rows(name, enc, delim)
    assert r[0][0] == "id" and len(r[0]) >= 4 and len(r) >= 4


def test_special_bytes() -> None:
    assert (CSV / "bom_utf8.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    with pytest.raises(UnicodeDecodeError):
        (CSV / "latin1.csv").read_bytes().decode("utf-8")
    with pytest.raises(UnicodeDecodeError):
        (CSV / "invalid_utf8.csv").read_bytes().decode("utf-8")
    assert (CSV / "empty.csv").stat().st_size == 0
    assert len(rows("header_only.csv")) == 1


def test_shapes() -> None:
    assert len(rows("wide_500.csv")[0]) == 500
    assert len(rows("too_many_columns_501.csv")[0]) == 501
    ragged = {len(x) for x in rows("ragged_rows.csv")}
    assert len(ragged) > 1
    h = rows("duplicate_headers.csv")[0]
    assert len(h) != len(set(h))
    assert len(rows("hostile_columns.csv")[0]) == 16


def test_pipeline_variants_match_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "contracts" / "pipeline.schema.json").read_text())
    for p in (HERE / "pipelines").glob("*.json"):
        jsonschema.validate(json.loads(p.read_text()), schema)


def test_no_pii_like_real_domains() -> None:
    text = (CSV / "orders_clean.csv").read_text()
    assert all(
        line.split(",")[1].strip().lower().endswith("@example.com")
        for line in text.splitlines()[1:]
    )


# ----------------------------------------------------------------------------------------------
# QA-03c: CSV structure (decision Q4, architecture section 5 "CSV structure and malformed input").
# An independent reference tokenizer (stdlib csv, strict) recomputes every structure expectation
# from the committed bytes; expected.json is hand-written in the builder, so the two must agree.
# ----------------------------------------------------------------------------------------------
import io  # noqa: E402


class FileLevelError(Exception):
    """Stands for CsvFormatError."""


def tokenize(
    raw: bytes, *, delimiter: str = ",", has_header: bool = True, encoding: str = "utf-8-sig"
) -> dict:
    text = raw.decode(encoding)  # strict decoding: undecodable bytes anywhere are file-level
    if not text:
        raise FileLevelError("empty")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    header: list[str] | None = None
    width: int | None = None
    records: list[tuple[str, str | None, str | None]] = []  # (kind, message, value)
    while True:
        try:
            rec = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            msg = str(exc)
            if "unexpected end of data" in msg or "field larger than field limit" in msg:
                raise FileLevelError(msg) from exc
            records.append(("bad", "quoting fault", None))  # recoverable: resume at next line
            continue
        if rec == []:
            continue  # blank line: not a record, consumes no row number (rule 6)
        if has_header and header is None:
            header = rec
            width = len(rec)
            empty = [i + 1 for i, h in enumerate(rec) if h == ""]
            if empty:
                raise FileLevelError(f"header in column {empty[0]} is empty")
            positions: dict[str, list[int]] = {}
            for i, h in enumerate(rec, 1):
                positions.setdefault(h, []).append(i)
            dups = {h: p for h, p in positions.items() if len(p) > 1}
            if dups:
                listed = ", ".join(
                    f'"{h}" (columns {", ".join(map(str, p))})' for h, p in dups.items()
                )
                raise FileLevelError(f"duplicate header names: {listed}")
            if width > 500:
                raise FileLevelError("too many columns")
            continue
        if width is None:
            width = len(rec)  # no header: the first record sets the width (Q4-d)
        if len(rec) != width:
            records.append(
                ("bad", f"expected {width} fields, found {len(rec)}", delimiter.join(rec)[:500])
            )
        else:
            records.append(("ok", None, None))
    if (has_header and header is None) or not records and has_header:
        raise FileLevelError("header-only" if header else "empty")
    if not records:
        raise FileLevelError("empty")
    bad = [(n, m, v) for n, (k, m, v) in enumerate(records, 1) if k == "bad"]
    return {
        "row_count": len(records),
        "well_formed_count": len(records) - len(bad),
        "bad": bad,
        "width": width,
        "header": header,
    }


STRUCTURE_FILES = [
    name
    for name, entry in EXPECTED["formats"].items()
    if isinstance(entry, dict)
    and ("parse_errors" in entry or entry.get("outcome") == "CsvFormatError")
    and name.endswith(".csv")
]


def test_structure_fixture_list_is_complete() -> None:
    assert set(STRUCTURE_FILES) >= {
        "ragged_rows.csv",
        "duplicate_headers.csv",
        "empty_header.csv",
        "empty_header_trailing.csv",
        "empty_and_duplicate_header.csv",
        "unterminated_quote.csv",
        "stray_quote.csv",
        "literal_quote.csv",
        "trailing_delimiter_first_row.csv",
        "quoted_multiline_ragged.csv",
        "blank_lines_ragged.csv",
        "headerless_ragged.csv",
        "headerless_ragged_first_short.csv",
        "malformed_chunk_straddle.csv",
        "parse_error_dedupe.csv",
    }


@pytest.mark.parametrize("name", STRUCTURE_FILES)
def test_structure_expectations_match_reference_tokenizer(name: str) -> None:
    want = EXPECTED["formats"][name]
    raw = (CSV / name).read_bytes()
    if want.get("outcome") == "CsvFormatError":
        with pytest.raises(FileLevelError) as exc:
            tokenize(raw)
        if want["message"] is not None:
            assert str(exc.value) == want["message"]
        return
    got = tokenize(raw, has_header=want["has_header"])
    assert got["row_count"] == want["row_count"], name
    assert got["well_formed_count"] == want["well_formed_count"], name
    assert [e["row_number"] for e in want["parse_errors"]] == [n for n, _, _ in got["bad"]], name
    for e, (_, message, value) in zip(want["parse_errors"], got["bad"], strict=True):
        assert e["rule"] == "parse_error" and e["column"] is None
        assert e["message"] == message
        if e["value"] is not None:  # quoting faults: value unspecified by the architecture
            assert e["value"] == value
    if "expected_width" in want:
        assert got["width"] == want["expected_width"]
    if "names" in want:
        assert got["header"] == want["names"], name


def test_structure_rules_spot_checks() -> None:
    f = EXPECTED["formats"]
    # rule 4: only the faulty record is rejected, the next one parses; a literal quote is data
    assert [e["row_number"] for e in f["stray_quote.csv"]["parse_errors"]] == [2]
    assert (
        f["literal_quote.csv"]["parse_errors"] == []
        and f["literal_quote.csv"]["cell_row_1_name"] == 'ab"c'
    )
    assert rows("literal_quote.csv")[1][1] == 'ab"c'
    # rule 2: the trailing delimiter is a third (empty) field; numbering starts at the first row
    assert f["trailing_delimiter_first_row.csv"]["parse_errors"][0]["row_number"] == 1
    # rule 6/7: blank lines consume no row number; whitespace-only line is a record
    blank = (CSV / "blank_lines_ragged.csv").read_text().split("\n")
    assert (
        blank.count("") - 1 == f["blank_lines_ragged.csv"]["blank_lines"]
    )  # last "" is the final newline
    assert " " in blank
    # multi-line quoted record counts once: more physical lines than records + header
    lines = (CSV / "quoted_multiline_ragged.csv").read_text().count("\n")
    assert (
        lines
        == f["quoted_multiline_ragged.csv"]["physical_lines"]
        > f["quoted_multiline_ragged.csv"]["row_count"] + 1
    )
    # Q4-d: width from the first record even when it is the odd one out
    assert f["headerless_ragged_first_short.csv"]["expected_width"] == 2
    assert [e["row_number"] for e in f["headerless_ragged_first_short.csv"]["parse_errors"]] == [
        2,
        3,
        4,
    ]
    # rule 1: empty names are reported before duplicates
    assert "empty" in f["empty_and_duplicate_header.csv"]["message"]


def test_long_field_boundary_is_generated_not_committed(tmp_path: Path) -> None:
    limit = EXPECTED["formats"]["long_field (generated in the test, not committed)"]
    assert max(p.stat().st_size for p in CSV.iterdir()) < 1_000_000  # nothing huge is committed
    ok = f"id,n\n1,{'x' * limit['field_length_accepted']}\n".encode()
    assert tokenize(ok)["row_count"] == 1
    too_long = f"id,n\n1,{'x' * limit['field_length_rejected']}\n2,a\n".encode()
    with pytest.raises(FileLevelError, match="field larger than field limit"):
        tokenize(too_long)
    (tmp_path / "long.csv").write_bytes(too_long)  # what ETL tests should feed the engine


def structure_counters(name: str, chunk: int, *, dedup_col: int | None = None) -> dict[str, int]:
    """Reference model for the structure scenarios: parse_error rows are rejected at extract and
    register no deduplicate key (rule 9); chunking only affects when counters are reported."""
    raw = (CSV / name).read_bytes()
    want = EXPECTED["formats"][name]
    bad = {e["row_number"] for e in want["parse_errors"]}
    data = [r for r in csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=False) if r][
        1:
    ]
    c = dict.fromkeys(COUNTERS, 0)
    seen: set[str] = set()
    for start in range(0, len(data), chunk):
        for offset, r in enumerate(data[start : start + chunk]):
            n = start + offset + 1
            c["extracted_count"] += 1
            if n in bad:
                c["rejected_count"] += 1
            elif dedup_col is not None and r[dedup_col] in seen:
                c["duplicate_dropped_count"] += 1
            else:
                if dedup_col is not None:
                    seen.add(r[dedup_col])
                c["loaded_count"] += 1
    return c


def test_parse_error_scenarios_reconcile_for_every_chunk_size() -> None:
    ragged = EXPECTED["ragged_rows.csv"]
    straddle = EXPECTED["malformed_chunk_straddle.csv"]
    dedupe = EXPECTED["parse_error_dedupe.csv"]
    for size in straddle["chunk_sizes"]:
        assert (
            structure_counters("malformed_chunk_straddle.csv", size)
            == straddle["counters_identical_for_every_chunk_size"]
        ), size
        assert structure_counters("ragged_rows.csv", size) == ragged["counters"], size
        assert (
            structure_counters("parse_error_dedupe.csv", size, dedup_col=0) == dedupe["counters"]
        ), size
    assert ragged["counters"]["rejected_count"] == 3 == len(ragged["rejected_row_numbers"])
    assert dedupe["counters"]["rejected_count"] == 1 and dedupe["counters"]["loaded_count"] == 3


def test_chunk_straddle_pairs_and_cumulative_counters() -> None:
    f = EXPECTED["formats"]["malformed_chunk_straddle.csv"]
    chunks = f["chunk_rows_2_chunks"]
    bad = {e["row_number"] for e in f["parse_errors"]}
    assert [r for c in chunks for r in c] == list(range(1, f["row_count"] + 1))
    assert all(len(c) <= 2 for c in chunks)
    assert (
        {2, 3} <= bad and 2 in chunks[0] and 3 in chunks[1]
    )  # malformed rows on both sides of a boundary
    cumulative = EXPECTED["malformed_chunk_straddle.csv"]["cumulative_after_each_chunk_rows_2"]
    seen = rejected = 0
    for chunk, snap in zip(chunks, cumulative, strict=True):
        seen += len(chunk)
        rejected += len(bad & set(chunk))
        assert snap == {"extracted_count": seen, "rejected_count": rejected}
    assert list(cumulative[-1].values()) == [7, 3]


def test_fail_run_scenario_fails_on_first_parse_error() -> None:
    sc = EXPECTED["ragged_rows.csv"]["scenarios"]["pipelines/ragged_failrun.json"]
    assert sc["outcome"] == "failed" and sc["loaded_count"] == 0
    first_bad = min(e["row_number"] for e in EXPECTED["formats"]["ragged_rows.csv"]["parse_errors"])
    assert (
        sc["first_rejection"] == {"row_number": first_bad, "rule": "parse_error"} and first_bad == 2
    )
    cfg = json.loads((HERE / "pipelines" / "ragged_failrun.json").read_text())
    assert cfg["on_validation_failure"] == "fail_run" and "max_rejected_ratio" not in cfg
    # Q7-3: only completed chunks are reported; the chunk holding row 2 never is
    for size, c in sc["counters_at_failure_by_chunk_rows"].items():
        completed_rows = (first_bad - 1) // int(size) * int(size)
        assert list(c) == COUNTERS and c["loaded_count"] == 0
        assert c["extracted_count"] == completed_rows and c["rejected_count"] == 0, size


def test_structure_pipelines_match_schema_and_the_merged_validator() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "contracts" / "pipeline.schema.json").read_text())
    names = ("ragged_reject.json", "ragged_failrun.json", "parse_error_dedupe.json")
    etl = pytest.importorskip("app.etl")
    for name in names:
        cfg = json.loads((HERE / "pipelines" / name).read_text())
        jsonschema.validate(cfg, schema)
        etl.validate_pipeline_config(cfg, source_columns=["id", "name", "amount"])  # ETL-03


def test_readme_no_longer_says_behaviour_is_unspecified() -> None:
    text = (HERE / "README.md").read_text()
    assert "must be defined by ETL tests" not in text
    assert "CSV structure" in text


def test_hostile_columns_header_is_accepted_and_clean() -> None:
    """QA-03d: hostile *names*, not an empty header (Q4-a would reject the file)."""
    header = rows("hostile_columns.csv")[0]
    want = EXPECTED["formats"]["hostile_columns.csv"]
    assert len(header) == 16 == want["column_count"]
    assert all(h != "" for h in header), "an empty header makes the file a CsvFormatError (Q4-a)"
    assert len(set(header)) == len(header), "duplicate headers are a CsvFormatError (Q4-a)"
    assert header == want["names"]  # verbatim, including padding and quotes
    assert want["row_count"] == len(rows("hostile_columns.csv")) - 1 == 2
    assert want["parse_errors"] == [] and "outcome" not in want  # accepted, not rejected
    assert all(len(r) == 16 for r in rows("hostile_columns.csv"))
    assert any(not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", h) for h in header)  # really hostile


def test_no_committed_csv_has_an_empty_header_unless_expected() -> None:
    """Guard against the QA-03d class of bug: an unintended empty/duplicate header in a fixture."""
    allowed = {
        name
        for name, entry in EXPECTED["formats"].items()
        if isinstance(entry, dict) and entry.get("outcome") == "CsvFormatError"
    }
    headerless = {"no_header.csv", "headerless_ragged.csv", "headerless_ragged_first_short.csv"}
    for path in sorted(CSV.glob("*.csv")):
        if path.name in allowed | headerless or path.stat().st_size == 0:
            continue
        raw = path.read_bytes()
        enc = "latin-1" if path.name in {"latin1.csv", "cp1252.csv", "invalid_utf8.csv"} else "utf-8-sig"
        try:
            header = next(csv.reader(io.StringIO(raw.decode(enc), newline="")))
        except (UnicodeDecodeError, StopIteration):
            continue
        assert "" not in header, f"{path.name}: empty header name"
        assert len(set(header)) == len(header), f"{path.name}: duplicate header names"
