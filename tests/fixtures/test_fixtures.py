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
    assert len(r) - 1 == EXPECTED["orders_clean.csv"]["counters"]["extracted_count"] == 200
    assert len({row[0] for row in r[1:]}) == 200


COUNTERS = ["extracted_count", "loaded_count", "rejected_count",
            "duplicate_dropped_count", "null_dropped_count"]


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
            out.append((file, {**entry, "counters": entry["counters_identical_for_every_chunk_size"]}))
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
            assert c["extracted_count"] == (c["loaded_count"] + c["rejected_count"]
                                            + c["duplicate_dropped_count"] + c["null_dropped_count"]), name
            checked += 1
    assert checked == 5  # clean, dirty_reject, dirty_unique, nulls, chunk_dupes


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
    assert c["null_dropped_count"] > 0 and c["rejected_count"] > 0  # null id rejected: first removal wins


def reference_counters(name: str, chunk: int, *, null_cols: tuple[int, ...] = (), dedup: bool) -> dict[str, int]:
    """Tiny independent model of architecture section 5 rules for the orders files:
    cast/nullable (order_id) -> drop_null_rows -> deduplicate(order_id) -> range(amount >= 0)."""
    data = rows(name)[1:]
    seen: set[str] = set()
    c = dict.fromkeys(COUNTERS, 0)
    for start in range(0, len(data), chunk):
        for r in data[start:start + chunk]:
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
    assert reference_counters("orders_clean.csv", 7, dedup=True) == EXPECTED["orders_clean.csv"]["counters"]
    assert (reference_counters("orders_nulls.csv", 3, null_cols=(0, 1), dedup=True)
            == EXPECTED["orders_nulls.csv"]["counters"])


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

