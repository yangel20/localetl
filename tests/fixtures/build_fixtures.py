#!/usr/bin/env python3
"""Regenerate the committed synthetic CSV fixtures and expected.json.

Deterministic (seeded), stdlib only. All data is fake.
Usage: python3 tests/fixtures/build_fixtures.py
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CSV_DIR = HERE / "csv"
ORDER_HEADER = ["Order ID", "Customer Email", "Country", "Status", "Amount", "Order Date", "Is Gift"]
COUNTRIES = ["us", "de", "fr", "mx", "ca", "gb"]
STATUSES = ["pending", "done", "cancel", "completed", "cancelled"]  # done/cancel are remapped
STATUS_OUT = {"done": "completed", "cancel": "cancelled"}


COUNTERS = ("extracted_count", "loaded_count", "rejected_count",
            "duplicate_dropped_count", "null_dropped_count")  # architecture section 5 (Q3), same order
CHUNK_SIZES = [1, 2, 3, 5, 7, 9, 50_000]


def counters(extracted: int, loaded: int, rejected: int = 0, dup: int = 0, null: int = 0) -> dict[str, int]:
    """Five Q3 counters; asserts the reconciliation identity at generation time."""
    assert extracted == loaded + rejected + dup + null, "reconciliation identity violated"
    return dict(zip(COUNTERS, (extracted, loaded, rejected, dup, null), strict=True))


def write(name: str, data: bytes) -> None:
    (CSV_DIR / name).write_bytes(data)


def write_rows(name: str, rows: list[list[str]], *, delimiter: str = ",",
               encoding: str = "utf-8", newline: str = "\n") -> None:
    path = CSV_DIR / name
    with path.open("w", encoding=encoding, newline="") as fh:
        csv.writer(fh, delimiter=delimiter, lineterminator=newline).writerows(rows)


def good_order(rng: random.Random, order_id: int) -> list[str]:
    """A row that is valid under contracts/examples/pipeline/valid/orders_full.json
    but deliberately messy (padding, case, aliases, blank Is Gift)."""
    user = f"User{order_id}.Test"
    email = f"  {user}@Example.COM " if order_id % 3 == 0 else f"{user}@example.com"
    country = rng.choice(COUNTRIES)
    country = f" {country} " if order_id % 5 == 0 else (country.upper() if order_id % 2 else country)
    status = rng.choice(STATUSES)
    amount = f"{rng.uniform(0, 500):.3f}"
    date = f"20{rng.randint(10, 29)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    gift = rng.choice(["true", "false", "1", "0", "yes", "no", "TRUE", "", ""])
    return [str(order_id), email, country, status, amount, date, gift]


def expected_clean(row: list[str]) -> dict[str, Any]:
    return {
        "order_id": int(row[0]),
        "customer_email": row[1].strip().lower(),
        "country": row[2].strip().upper(),
        "status": STATUS_OUT.get(row[3].strip(), row[3].strip()),
        "amount": round(float(row[4]), 2),
        "order_date": row[5],
        "is_gift": {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False,
                    "": False}[row[6].strip().lower()],
    }


def build_orders(expected: dict[str, Any]) -> None:
    rng = random.Random(20261019)
    clean = [good_order(rng, i) for i in range(1, 201)]
    write_rows("orders_clean.csv", [ORDER_HEADER, *clean])
    expected["orders_clean.csv"] = {
        "config": "contracts/examples/pipeline/valid/orders_full.json",
        "outcome": "succeeded",
        "counters": counters(200, 200),
        "append_twice": {"second_run_counters": counters(200, 200), "published_row_count": 400},
        "sample_rows": {str(r[0]): expected_clean(r) for r in (clean[0], clean[2], clean[4], clean[199])},
    }

    # Dirty file: each bad row breaks exactly ONE rule.
    rows: list[list[str]] = []
    nxt = 1000

    def good() -> list[str]:
        nonlocal nxt
        nxt += 1
        return good_order(rng, nxt)

    goods = [good() for _ in range(70)]
    bad: list[tuple[str, list[str]]] = []

    def broken(rule: str, col: int, value: str) -> None:
        r = good()
        r[col] = value
        bad.append((rule, r))

    for v in ("abc", "12.5.1"):
        broken("type_cast", 0, v)
    broken("type_cast", 4, "12,5x")
    broken("type_cast", 5, "2024-13-45")
    broken("type_cast", 6, "maybe")
    for _ in range(3):
        broken("not_null", 0, "")
    for v in ("-0.01", "-10", "-999", "-1e3"):
        broken("range", 4, v)
    for v in ("1999-12-31", "2101-01-01"):
        broken("range", 5, v)
    for v in ("shipped", "returned", "", "PENDING "):
        # "" -> null: allowed_values ignores nulls? NOT ASSUMED: leave empty out.
        if v == "":
            continue
        broken("allowed_values", 3, v)
    for v in ("not-an-email", "a@b", "@example.com"):
        broken("regex", 1, v)
    for v in ("USA", "U", "Germany"):
        broken("length", 2, v)
    # PENDING_ + " " -> trim+replace do not lowercase status, so "PENDING " fails allowed_values.

    # Conflicting duplicates of existing good order IDs (differing content).
    dupes = []
    for g in goods[:3]:
        d = list(g)
        d[4] = "1.000"
        dupes.append(d)

    allrows = goods + [r for _, r in bad] + dupes
    rng.shuffle(allrows)
    write_rows("orders_dirty.csv", [ORDER_HEADER, *allrows])
    by_rule: dict[str, int] = {}
    for rule, _ in bad:
        by_rule[rule] = by_rule.get(rule, 0) + 1
    n_bad = len(bad)
    expected["_counting"] = ("Decision Q3 (architecture section 5): five counters. For every SUCCEEDED "
                             "scenario extracted_count = loaded_count + rejected_count + "
                             "duplicate_dropped_count + null_dropped_count. Failed/interrupted runs have "
                             "loaded_count 0 and the identity is not enforced.")
    build_nulls(expected)
    build_chunk_dupes(expected)
    expected["orders_dirty.csv"] = {
        "extracted_count": len(allrows),
        "bad_rows_by_rule": by_rule,
        "conflicting_duplicate_order_ids": len(dupes),
        "scenarios": {
            "pipelines/orders_dirty_reject.json": {
                "note": "orders_full + max_rejected_ratio 0.5; deduplicate silently drops the "
                        "conflicting duplicates (not rejections)",
                "outcome": "succeeded",
                "counters": counters(len(allrows), len(goods), n_bad, dup=len(dupes)),
                "rejections_by_rule": by_rule,
            },
            "pipelines/orders_dirty_unique.json": {
                "note": "no deduplicate: the later duplicates fail the unique rule "
                        "(first occurrence in file order is kept)",
                "outcome": "succeeded",
                "counters": counters(len(allrows), len(goods), n_bad + len(dupes)),
                "rejections_by_rule": {**by_rule, "unique": len(dupes)},
            },
            "contracts/examples/pipeline/valid/orders_full.json": {
                "note": f"{n_bad}/{len(allrows)} rejected exceeds max_rejected_ratio 0.1 -> "
                        "RejectionLimitExceeded; nothing published",
                "outcome": "failed", "loaded_count": 0,
            },
            "pipelines/orders_dirty_failrun.json": {
                "note": "on_validation_failure fail_run -> RejectionLimitExceeded on first rejection",
                "outcome": "failed", "loaded_count": 0,
            },
        },
    }


def build_nulls(expected: dict[str, Any]) -> None:
    """Rows removed by drop_null_rows (null_dropped_count > 0) and 'first removal wins'."""
    rng = random.Random(777)
    rows = [good_order(rng, i) for i in range(1, 21)]            # 20 good
    for i, r in enumerate(rows[:5]):                              # 5 null e-mails -> null-dropped
        r[1] = ""
        r[0] = str(100 + i)
    rows += [["", "nobody@example.com", "us", "pending", "1.00", "2024-01-01", "true"],   # null id, email set
             ["", "", "us", "pending", "1.00", "2024-01-01", "true"]]                  # null id AND null email
    # Both null-id rows are REJECTED (not_null): the nullable check runs before transformations.
    write_rows("orders_nulls.csv", [ORDER_HEADER, *rows])
    expected["orders_nulls.csv"] = {
        "config": "pipelines/orders_nulls.json",
        "note": "drop_null_rows(order_id, customer_email, how=any) on top of orders_full; order_id is "
                "nullable:false so null ids are rejected (first removal wins), null e-mails are null-dropped",
        "outcome": "succeeded",
        "counters": counters(len(rows), 15, rejected=2, null=5),
        "rejections_by_rule": {"not_null": 2},
    }


def build_chunk_dupes(expected: dict[str, Any]) -> None:
    """Duplicate keys straddling chunk boundaries for chunk sizes 2, 3, 5 and 7."""
    rng = random.Random(4242)
    ids = [1, 2, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 10, 11]
    rows = [good_order(rng, i) for i in ids]
    rows[8][4] = "-5.00"          # row 9: first occurrence of id 5, REJECTED by range(amount >= 0)
    # Row 10 repeats id 5: the key was registered by row 9 (it reached deduplicate before validation),
    # so row 10 is duplicate-dropped even though row 9 was rejected (architecture section 5, rule 5).
    for i in (3, 4, 6, 8, 10):    # make the duplicates differ in content from the first occurrence
        rows[i - 1][4] = "9.99"
    write_rows("orders_chunk_dupes.csv", [ORDER_HEADER, *rows])
    boundary = {str(c): [c, c + 1] for c in (2, 3, 5, 7, 9)}  # 1-based row pairs on each boundary
    expected["orders_chunk_dupes.csv"] = {
        "config": "contracts/examples/pipeline/valid/orders_full.json",
        "note": "ids 2,2,2 (rows 2-4), 3,3 (rows 5-6), 4,4 (rows 7-8) straddle chunk boundaries; row 9 "
                "(id 5) is rejected by range yet its key still drops row 10 as a duplicate",
        "outcome": "succeeded",
        "chunk_sizes": CHUNK_SIZES,
        "straddling_row_pairs_by_chunk_size": boundary,
        "counters_identical_for_every_chunk_size": counters(len(rows), 10, rejected=1, dup=5),
        "duplicate_dropped_row_numbers": [3, 4, 6, 8, 10],
        "rejected_row_numbers": [9],
    }


def build_formats(expected: dict[str, Any]) -> None:
    write("empty.csv", b"")
    write("header_only.csv", b"id,name,amount\n")
    write("header_only_no_newline.csv", b"id,name,amount")
    base = [["id", "name", "city", "amount"],
            ["1", "Ana García", "São Paulo", "10.50"],
            ["2", "Zoë Müller", "Zürich", "20.00"],
            ["3", "José Ñandú", "Málaga", "30.25"]]
    write_rows("bom_utf8.csv", base, encoding="utf-8-sig")
    write_rows("latin1.csv", base, encoding="latin-1")
    write_rows("cp1252.csv", [*base, ["4", "Price €5 “quoted”", "x", "1"]], encoding="cp1252")
    write("invalid_utf8.csv", b"id,name\n1,caf\xe9\n2,\xff\xfe\n")
    nd = [["id", "name", "note", "amount"], ["1", "Ana", "has, comma", "1.5"],
          ["2", "Bob", "plain", "2.5"], ["3", "Cy", "x y", "3.5"]]
    write_rows("semicolon.csv", nd, delimiter=";")
    write_rows("tab.tsv", nd, delimiter="\t")
    write_rows("pipe.csv", nd, delimiter="|")
    write_rows("crlf.csv", nd, newline="\r\n")
    write("quoted_multiline.csv",
          b'id,note\n1,"line one\nline two"\n2,"say ""hi"""\n3,plain\n')
    write("no_header.csv", b"1,Ana,10.5\n2,Bob,20.5\n3,Cy,30.5\n")
    write("ragged_rows.csv",
          b"id,name,amount\n1,Ana,10\n2,Bob\n3,Cy,30,EXTRA\n4,Di,40\n5\n6,Ed,60\n")
    write("duplicate_headers.csv", b"id,name,name,amount,id\n1,a,b,1.5,9\n2,c,d,2.5,8\n")
    write("blank_lines.csv", b"id,name\n1,a\n\n2,b\n\n\n3,c\n")
    write("all_null_column.csv", b"id,empty_col,name\n1,,a\n2,,b\n3,,c\n")
    write("types_mixed.csv",
          b"i,f,b,d,dt,s\n1,1.5,true,2024-01-31,2024-01-31T10:00:00,x\n"
          b"2,2.5,false,2024-02-29,2024-02-29T23:59:59,y\n3,,yes,,,\n")
    cols = lambda n: [f"col_{i}" for i in range(n)]  # noqa: E731
    write_rows("wide_500.csv", [cols(500), [str(i) for i in range(500)]])
    write_rows("too_many_columns_501.csv", [cols(501), [str(i) for i in range(501)]])
    hostile = ['id', "name; DROP TABLE x;--", 'Robert\'); DROP TABLE students;--', 'a"b', "Order ID",
               "  padded  ", "UPPER", "run_abc", "1starts_with_digit", "ünïcode_列", "x" * 80,
               "select", "with.dot", "with space", "", "ok"]
    hrow = ["1", "'; DROP TABLE users;--", "=cmd|' /C calc'!A0", 'q"q', "5", "6", "7", "8",
            "9", "10", "11", "12", "13", "14", "15", "16"]
    write_rows("hostile_columns.csv", [hostile, hrow, ["2"] + ["v"] * 15])
    expected["formats"] = {
        "empty.csv": "CsvFormatError (empty)",
        "header_only.csv": "CsvFormatError (header-only)",
        "header_only_no_newline.csv": "CsvFormatError (header-only)",
        "invalid_utf8.csv": "CsvFormatError when read as utf-8; decodes as latin-1/cp1252",
        "too_many_columns_501.csv": "CsvFormatError (>500 columns)",
        "wide_500.csv": "accepted (boundary): 500 columns, 1 row",
        "bom_utf8.csv": {"encoding": "utf-8-sig", "first_header": "id", "rows": 3},
        "latin1.csv": {"encoding": "latin-1", "rows": 3, "name_row_1": "Ana García"},
        "cp1252.csv": {"encoding": "cp1252", "rows": 4},
        "semicolon.csv": {"delimiter": ";", "rows": 3, "columns": 4},
        "tab.tsv": {"delimiter": "\t", "rows": 3, "columns": 4},
        "pipe.csv": {"delimiter": "|", "rows": 3, "columns": 4},
        "crlf.csv": {"rows": 3, "columns": 4},
        "quoted_multiline.csv": {"rows": 3, "columns": 2},
        "no_header.csv": {"has_header": False, "rows": 3, "columns": ["column_1", "column_2", "column_3"]},
        "ragged_rows.csv": "malformed: data row 3 has an extra field (parse_error); rows 2 and 5 are short",
        "duplicate_headers.csv": "duplicate header names id, name; engine behaviour must be defined by ETL tests",
        "blank_lines.csv": {"rows": 3},
        "all_null_column.csv": {"null_count": {"empty_col": 3}},
        "hostile_columns.csv": "16 columns with SQL-injection-like / non-identifier names; "
                               "target names must be user-chosen safe identifiers",
    }


def build_pipelines() -> None:
    """Pipeline variants derived from the contract example (never edit by hand)."""
    src = HERE.parents[1] / "contracts" / "examples" / "pipeline" / "valid" / "orders_full.json"
    base = json.loads(src.read_text())
    out = HERE / "pipelines"
    out.mkdir(exist_ok=True)

    def dump(name: str, cfg: dict[str, Any]) -> None:
        (out / name).write_text(json.dumps(cfg, indent=2) + "\n")

    reject = json.loads(json.dumps(base))
    reject["max_rejected_ratio"] = 0.5
    dump("orders_dirty_reject.json", reject)

    unique = json.loads(json.dumps(reject))
    unique["transformations"] = [t for t in unique["transformations"] if t["op"] != "deduplicate"]
    dump("orders_dirty_unique.json", unique)

    failrun = json.loads(json.dumps(base))
    failrun["on_validation_failure"] = "fail_run"
    failrun.pop("max_rejected_ratio", None)
    dump("orders_dirty_failrun.json", failrun)

    mismatch = json.loads(json.dumps(base))  # append onto orders_full's table with a different schema
    for c in mismatch["columns"]:
        if c["name"] == "amount":
            c["type"] = "string"
    mismatch["transformations"] = [t for t in mismatch["transformations"] if t["op"] != "round_number"]
    mismatch["validations"] = [v for v in mismatch["validations"] if v.get("column") != "amount"]
    mismatch["target"] = {"table": "orders", "mode": "append"}
    dump("orders_append_mismatch.json", mismatch)

    nulls = json.loads(json.dumps(base))
    ops = nulls["transformations"]
    idx = next(i for i, t in enumerate(ops) if t["op"] == "drop_null_rows")
    ops[idx] = {"op": "drop_null_rows", "columns": ["order_id", "customer_email"], "how": "any"}
    dump("orders_nulls.json", nulls)

    append = json.loads(json.dumps(base))
    append["target"] = {"table": "orders", "mode": "append"}
    dump("orders_append.json", append)


def main() -> None:
    build_pipelines()
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    expected: dict[str, Any] = {"_comment": "Generated by build_fixtures.py. Do not edit by hand."}
    build_orders(expected)
    build_formats(expected)
    (HERE / "expected.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(list(CSV_DIR.iterdir()))} csv fixtures")


if __name__ == "__main__":
    main()
