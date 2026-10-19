"""Self-checks for the synthetic fixtures (stdlib + optional jsonschema). Run: pytest tests/fixtures"""
from __future__ import annotations

import csv
import json
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
    subprocess.run([sys.executable, str(HERE / "build_fixtures.py")], check=True, capture_output=True)
    assert {p.name: p.read_bytes() for p in CSV.iterdir()} == before
    assert (HERE / "expected.json").read_bytes() == exp


def test_clean_orders_counts() -> None:
    r = rows("orders_clean.csv")
    assert len(r) - 1 == EXPECTED["orders_clean.csv"]["rows_read"] == 200
    assert len({row[0] for row in r[1:]}) == 200


def test_dirty_orders_expected_arithmetic() -> None:
    d = EXPECTED["orders_dirty.csv"]
    assert len(rows("orders_dirty.csv")) - 1 == d["rows_read"]
    bad = sum(d["bad_rows_by_rule"].values())
    s = d["scenarios"]
    assert s["pipelines/orders_dirty_reject.json"]["rows_rejected"] == bad
    assert s["pipelines/orders_dirty_unique.json"]["rows_rejected"] == bad + d["conflicting_duplicate_order_ids"]
    loaded = s["pipelines/orders_dirty_reject.json"]["rows_loaded"]
    assert loaded + bad + d["conflicting_duplicate_order_ids"] == d["rows_read"]
    assert bad / d["rows_read"] > 0.1  # orders_full max_rejected_ratio must be exceeded


@pytest.mark.parametrize("name,enc,delim", [
    ("bom_utf8.csv", "utf-8-sig", ","), ("latin1.csv", "latin-1", ","), ("cp1252.csv", "cp1252", ","),
    ("semicolon.csv", "utf-8", ";"), ("tab.tsv", "utf-8", "\t"), ("pipe.csv", "utf-8", "|"),
])
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
    assert all(line.split(",")[1].strip().lower().endswith("@example.com") for line in text.splitlines()[1:])
