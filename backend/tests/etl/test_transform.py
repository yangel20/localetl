"""ETL-04: transform stage (select/rename, casting per Q6-3, the seven operations)."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from app.etl import PipelineConfig, RejectionLimitExceeded, validate_pipeline_config
from app.etl.errors import EtlError, SourceMismatchError
from app.etl.transform import Transformer, TransformResult

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
EXPECTED: dict[str, Any] = json.loads((FIXTURES / "expected.json").read_text())
SCHEMA = ROOT / "contracts" / "pipeline.schema.json"


def cfg(
    columns: list[dict[str, Any]],
    transformations: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> PipelineConfig:
    return validate_pipeline_config(
        {
            "version": 1,
            "columns": columns,
            "transformations": transformations or [],
            "target": {"table": "t", "mode": "replace"},
            **extra,
        }
    )


def col(name: str, ctype: str, **kw: Any) -> dict[str, Any]:
    return {"source": name.upper(), "name": name, "type": ctype, **kw}


def src(**cols: list[Any]) -> pd.DataFrame:
    """Source frame; keys are the UPPER-CASE source headers of ``col``."""
    return pd.DataFrame({k.upper(): pd.Series(v, dtype=object) for k, v in cols.items()})


def run(
    config: PipelineConfig, frame: pd.DataFrame, numbers: list[int] | None = None
) -> TransformResult:
    nums = numbers if numbers is not None else list(range(1, len(frame) + 1))
    return Transformer(config).transform_chunk(frame, nums)


def values(result: TransformResult, name: str) -> list[Any]:
    return result.frame[name].tolist()


def one(ctype: str, cells: list[str | None], **kw: Any) -> TransformResult:
    return run(cfg([col("x", ctype, **kw)]), src(x=cells))


# ----------------------------------------------------- completeness, wiring


def test_every_schema_operation_is_registered() -> None:
    from app.etl import transform

    schema = json.loads(SCHEMA.read_text())
    enum = set(schema["$defs"]["Transformation"]["properties"]["op"]["enum"])
    assert enum == set(transform._OPS) and len(enum) == 7


def test_select_rename_and_order_follow_the_config() -> None:
    frame = pd.DataFrame(
        {"Z": ["9"], "Order ID": ["7"], "Name": ["Ann"], "Unused": ["u"]}, dtype=object
    )
    config = cfg(
        [
            {"source": "Name", "name": "customer", "type": "string"},
            {"source": "Order ID", "name": "order_id", "type": "integer"},
        ]
    )
    r = run(config, frame)
    assert list(r.frame.columns) == ["customer", "order_id"]
    assert r.frame.values.tolist() == [["Ann", 7]]


def test_missing_source_column_raises_source_mismatch() -> None:
    with pytest.raises(SourceMismatchError, match="'X'"):
        run(cfg([col("x", "string")]), pd.DataFrame({"Y": ["1"]}, dtype=object))


def test_row_numbers_must_align() -> None:
    with pytest.raises(EtlError, match="align"):
        run(cfg([col("x", "string")]), src(x=["a", "b"]), [1])


def test_empty_chunk() -> None:
    r = run(cfg([col("x", "integer")]), src(x=[]))
    assert len(r.frame) == 0 and r.rows_in == 0 and r.rows_out == 0 and r.rejections == []
    assert list(r.frame.columns) == ["x"]


def test_row_numbers_follow_surviving_rows() -> None:
    config = cfg([col("x", "integer")])
    r = run(config, src(x=["1", "bad", "3"]), [10, 11, 12])
    assert r.row_numbers == [10, 12] and values(r, "x") == [1, 3]
    assert r.rejections[0].row_number == 11


# ------------------------------------------- casting: one test per table row


def test_integer_accepted_and_rejected() -> None:
    r = one("integer", ["0", "+5", "-5", "007", "9223372036854775807", "-9223372036854775808"])
    assert values(r, "x") == [0, 5, -5, 7, 2**63 - 1, -(2**63)]
    assert all(type(v) is int for v in values(r, "x"))
    bad = ["1.0", "1e3", "9223372036854775808", "١٢", "1_000", "1,000", "abc"]
    r = one("integer", bad)
    assert r.rejected_rows == len(bad) and r.rows_out == 0


def test_float_accepted_and_rejected() -> None:
    r = one("float", ["1", "-1.5", "+.5", "5.", "1e3", "1.5E-2", "007.50"])
    assert values(r, "x") == [1.0, -1.5, 0.5, 5.0, 1000.0, 0.015, 7.5]
    assert all(type(v) is float for v in values(r, "x"))
    r = one("float", ["nan", "inf", "-inf", "1e400", "1,5", "1_0.5", "abc"])
    assert r.rejected_rows == 7


def test_boolean_accepted_and_rejected() -> None:
    r = one("boolean", ["true", "TRUE", "False", "yes", "No", "1", "0"])
    assert values(r, "x") == [True, True, False, True, False, True, False]
    r = one("boolean", ["t", "y", "on", "2", "truee"])
    assert r.rejected_rows == 5


def test_date_with_format() -> None:
    r = one("date", ["31/01/2024", "01/02/69"], format="%d/%m/%y")
    assert r.rejected_rows == 1
    r = one("date", ["31/01/2024"], format="%d/%m/%Y")
    assert values(r, "x") == [date(2024, 1, 31)] and type(values(r, "x")[0]) is date
    r = one("date", ["2024-01-31", "31/02/2024", "31/01/2024 x"], format="%d/%m/%Y")
    assert r.rejected_rows == 3


def test_date_without_format() -> None:
    r = one("date", ["2026-10-20", "2024-02-29"])
    assert values(r, "x") == [date(2026, 10, 20), date(2024, 2, 29)]
    r = one("date", ["20261020", "2026-W43-2", "2026-10-20T00:00", "2026-02-30"])
    assert r.rejected_rows == 4


def test_datetime_with_format() -> None:
    r = one("datetime", ["31/01/2024 10:30"], format="%d/%m/%Y %H:%M")
    assert values(r, "x") == [datetime(2024, 1, 31, 10, 30)]
    r = one("datetime", ["2024-01-31"], format="%Y-%m-%d %H:%M")
    assert r.rejected_rows == 1


def test_datetime_without_format() -> None:
    r = one("datetime", ["2026-10-20T10:00", "2026-10-20 10:00:05", "2026-10-20T10:00:05.5"])
    assert values(r, "x") == [
        datetime(2026, 10, 20, 10, 0),
        datetime(2026, 10, 20, 10, 0, 5),
        datetime(2026, 10, 20, 10, 0, 5, 500000),
    ]
    r = one(
        "datetime", ["2026-10-20T10:00Z", "2026-10-20T10:00+02:00", "20261020T1000", "2026-10-20"]
    )
    assert r.rejected_rows == 4


def test_string_is_unchanged() -> None:
    cells = ["  a b  ", "١٢", "NaN", "1,5", "x"]
    assert values(one("string", cells), "x") == cells


# --------------------------------------------------- casting: general rules


def test_rule1_stripping_and_whitespace_only_is_null() -> None:
    r = one("integer", [" 42 ", "\t7\n", "   ", None])
    assert values(r, "x") == [42, 7, None, None] and r.rejections == []
    r = one("string", ["  keep  ", "   "])
    assert values(r, "x") == ["  keep  ", "   "]  # strings are never stripped or nulled


def test_rule2_nulls_are_never_cast_and_not_null_is_not_type_cast() -> None:
    r = one("integer", [None, "  ", "5"], nullable=False)
    assert [(x.row_number, x.rule) for x in r.rejections] == [(1, "not_null"), (2, "not_null")]
    assert all(x.column == "x" and x.value is None for x in r.rejections)
    assert values(r, "x") == [5]


def test_rule3_ascii_digits_only_in_formats_too() -> None:
    r = one("date", ["٣١/٠١/٢٠٢٤"], format="%d/%m/%Y")
    assert r.rejected_rows == 1


def test_rule4_type_cast_entry_shape() -> None:
    r = one("integer", ["12x"])
    (e,) = r.rejections
    assert (e.rule, e.column, e.value, e.row_number) == ("type_cast", "x", "12x", 1)
    assert e.message == 'cannot cast "12x" to integer'
    r = one("date", ["31-01-2024"], format="%d/%m/%Y")
    assert r.rejections[0].message == 'cannot cast "31-01-2024" to date with format %d/%m/%Y'


def test_rule4_value_is_the_raw_cell_truncated_to_500() -> None:
    raw = " " + "9" * 600 + "x"
    (e,) = one("integer", [raw]).rejections
    assert e.value == raw[:500] and len(e.message) < 600


def test_c_d_several_bad_cells_give_several_entries_but_count_once() -> None:
    config = cfg(
        [
            col("a", "integer"),
            col("b", "date"),
            col("c", "string"),
            col("d", "integer", nullable=False),
        ]
    )
    frame = src(a=["x", "1"], b=["bad", "2024-01-01"], c=["s", "t"], d=[None, "4"])
    r = run(config, frame)
    assert [(e.row_number, e.column, e.rule) for e in r.rejections] == [
        (1, "a", "type_cast"),
        (1, "b", "type_cast"),
        (1, "d", "not_null"),
    ]
    assert r.rejected_rows == 1 and r.rows_in == 2 and r.rows_out == 1


def test_rule5_determinism_across_chunks() -> None:
    config = cfg([col("x", "integer")])
    t = Transformer(config)
    a = t.transform_chunk(src(x=[" 7 ", "bad"]), [1, 2])
    b = t.transform_chunk(src(x=[" 7 ", "bad"]), [3, 4])
    assert values(a, "x") == values(b, "x") == [7]
    assert [e.message for e in a.rejections] == [e.message for e in b.rejections]


def test_integer_columns_with_nulls_keep_integer_values() -> None:
    r = one("integer", ["1", None, "3"])
    got = values(r, "x")
    assert got == [1, None, 3] and type(got[0]) is int and got[1] is None
    assert str(r.frame["x"].dtype) == "object"


# -------------------------------------------------------------- the operations


def test_trim_whitespace() -> None:
    config = cfg(
        [col("a", "string"), col("b", "string"), col("n", "integer")],
        [{"op": "trim_whitespace", "columns": ["a"]}],
    )
    r = run(config, src(a=["  x  ", None, " \t"], b=[" y "] * 3, n=["1"] * 3))
    assert values(r, "a") == ["x", None, ""] and values(r, "b") == [" y "] * 3


def test_change_case() -> None:
    cells = ["hello WORLD", None]
    for case, expected in (
        ("lower", "hello world"),
        ("upper", "HELLO WORLD"),
        ("title", "Hello World"),
    ):
        config = cfg([col("x", "string")], [{"op": "change_case", "columns": ["x"], "case": case}])
        assert values(run(config, src(x=cells)), "x") == [expected, None]


def test_replace_values_string_and_typed_keys() -> None:
    config = cfg(
        [col("s", "string"), col("n", "integer"), col("b", "boolean"), col("d", "date")],
        [
            {"op": "replace_values", "column": "s", "mapping": {"done": "completed", "x": None}},
            {"op": "replace_values", "column": "n", "mapping": {"1": 100, "2": "200"}},
            {"op": "replace_values", "column": "b", "mapping": {"true": False}},
            {"op": "replace_values", "column": "d", "mapping": {"2024-01-01": "2025-05-05"}},
        ],
    )
    frame = src(
        s=["done", "Done", "x", None],
        n=["1", "2", "3", None],
        b=["yes", "no", "yes", None],
        d=["2024-01-01", "2024-01-02", None, None],
    )
    r = run(config, frame)
    assert values(r, "s") == ["completed", "Done", None, None]
    assert values(r, "n") == [100, 200, 3, None]
    assert values(r, "b") == [False, False, False, None]
    assert values(r, "d") == [date(2025, 5, 5), date(2024, 1, 2), None, None]


def test_replace_values_exact_case_sensitive_match_only() -> None:
    config = cfg(
        [col("s", "string")], [{"op": "replace_values", "column": "s", "mapping": {"a": "b"}}]
    )
    assert values(run(config, src(s=["a", "A", " a", "aa"])), "s") == ["b", "A", " a", "aa"]


def test_replace_values_uncastable_replacement_is_an_engine_error() -> None:
    config = cfg(
        [col("n", "integer")],
        [{"op": "replace_values", "column": "n", "mapping": {"1": "not a number"}}],
    )
    with pytest.raises(EtlError, match="replace_values"):
        Transformer(config)


def test_fill_null() -> None:
    config = cfg(
        [col("a", "boolean"), col("b", "integer"), col("c", "date"), col("d", "string")],
        [
            {"op": "fill_null", "column": "a", "value": False},
            {"op": "fill_null", "column": "b", "value": 0},
            {"op": "fill_null", "column": "c", "value": "2000-01-01"},
            {"op": "fill_null", "column": "d", "value": "n/a"},
        ],
    )
    r = run(config, src(a=[None, "true"], b=[None, "5"], c=[None, "2024-01-01"], d=[None, "x"]))
    assert r.frame.values.tolist() == [
        [False, 0, date(2000, 1, 1), "n/a"],
        [True, 5, date(2024, 1, 1), "x"],
    ]


def test_fill_null_does_not_touch_empty_strings_of_string_columns() -> None:
    config = cfg(
        [col("s", "string")],
        [
            {"op": "trim_whitespace", "columns": ["s"]},
            {"op": "fill_null", "column": "s", "value": "z"},
        ],
    )
    assert values(run(config, src(s=["  ", None])), "s") == ["", "z"]


def test_drop_null_rows_any_and_all() -> None:
    columns = [col("a", "string"), col("b", "string"), col("c", "string")]
    frame = src(a=["1", None, None, "4"], b=["1", "2", None, None], c=["x"] * 4)
    any_r = run(cfg(columns, [{"op": "drop_null_rows", "columns": ["a", "b"]}]), frame)
    assert any_r.row_numbers == [1] and any_r.null_dropped == 3 and any_r.rejected_rows == 0
    all_r = run(
        cfg(columns, [{"op": "drop_null_rows", "columns": ["a", "b"], "how": "all"}]), frame
    )
    assert all_r.row_numbers == [1, 2, 4] and all_r.null_dropped == 1


def test_deduplicate_on_columns_and_all_columns() -> None:
    columns = [col("id", "integer"), col("v", "string")]
    frame = src(id=["1", "1", "2", "1"], v=["a", "b", "a", "a"])
    r = run(cfg(columns, [{"op": "deduplicate", "columns": ["id"]}]), frame)
    assert r.row_numbers == [1, 3] and r.duplicate_dropped == 2
    r = run(cfg(columns, [{"op": "deduplicate"}]), frame)
    assert r.row_numbers == [1, 2, 3] and r.duplicate_dropped == 1
    assert r.rejected_rows == 0


def test_deduplicate_treats_nulls_as_equal() -> None:
    columns = [col("id", "integer")]
    r = run(cfg(columns, [{"op": "deduplicate"}]), src(id=[None, None, "1", None]))
    assert r.row_numbers == [1, 3] and r.duplicate_dropped == 2


@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 50_000])
def test_deduplicate_keeps_first_across_chunk_boundaries(chunk_rows: int) -> None:
    config = cfg([col("id", "integer")], [{"op": "deduplicate", "columns": ["id"]}])
    ids = ["2", "2", "2", "3", "3", "4", "4", "5"]
    t = Transformer(config)
    kept: list[int] = []
    dropped = 0
    for start in range(0, len(ids), chunk_rows):
        part = ids[start : start + chunk_rows]
        r = t.transform_chunk(src(id=part), list(range(start + 1, start + 1 + len(part))))
        kept += r.row_numbers
        dropped += r.duplicate_dropped
    assert kept == [1, 4, 6, 8] and dropped == 4


def test_two_deduplicate_steps_keep_separate_state() -> None:
    columns = [col("a", "string"), col("b", "string")]
    config = cfg(
        columns,
        [{"op": "deduplicate", "columns": ["a"]}, {"op": "deduplicate", "columns": ["b"]}],
    )
    r = run(config, src(a=["1", "2", "3"], b=["x", "x", "y"]))
    assert r.row_numbers == [1, 3] and r.duplicate_dropped == 1  # row 2 reached step 2 only


def test_round_number() -> None:
    config = cfg([col("x", "float")], [{"op": "round_number", "column": "x", "decimals": 2}])
    r = run(config, src(x=["1.005", "2.345678", None, "-0.004", "7"]))
    got = values(r, "x")
    assert got[1] == 2.35 and got[2] is None and got[3] == -0.0 and got[4] == 7.0
    assert all(isinstance(v, float) or v is None for v in got)
    zero = cfg([col("x", "float")], [{"op": "round_number", "column": "x", "decimals": 0}])
    assert values(run(zero, src(x=["2.6"])), "x") == [3.0]


def test_operations_run_in_array_order() -> None:
    columns = [col("s", "string")]
    ab = cfg(
        columns,
        [
            {"op": "replace_values", "column": "s", "mapping": {"a": "b"}},
            {"op": "change_case", "columns": ["s"], "case": "upper"},
        ],
    )
    ba = cfg(
        columns,
        [
            {"op": "change_case", "columns": ["s"], "case": "upper"},
            {"op": "replace_values", "column": "s", "mapping": {"a": "b"}},
        ],
    )
    assert values(run(ab, src(s=["a"])), "s") == ["B"]
    assert values(run(ba, src(s=["a"])), "s") == ["A"]


def test_operation_on_wrong_column_type_is_an_engine_error() -> None:
    # ETL-03 rejects these configs; the engine must not convert values if it meets one.
    for op in (
        {"op": "trim_whitespace", "columns": ["n"]},
        {"op": "change_case", "columns": ["n"], "case": "lower"},
        {"op": "round_number", "column": "n", "decimals": 1},
    ):
        raw = {
            "version": 1,
            "columns": [col("n", "integer")],
            "transformations": [op],
            "target": {"table": "t", "mode": "replace"},
        }
        with pytest.raises(EtlError, match="applies only to"):
            Transformer(PipelineConfig(raw=raw))


# ------------------------------------------------------ row accounting (Q3)


def test_first_removal_wins_not_null_beats_drop_null_rows() -> None:
    config = cfg(
        [col("id", "integer", nullable=False), col("n", "string")],
        [{"op": "drop_null_rows", "columns": ["id"]}],
    )
    r = run(config, src(id=[None, "1"], n=["a", "b"]))
    assert r.rejected_rows == 1 and r.null_dropped == 0 and r.rejections[0].rule == "not_null"
    assert r.row_numbers == [2]


def test_dropped_rows_are_never_rejections_and_counts_reconcile() -> None:
    config = cfg(
        [col("id", "integer"), col("e", "string")],
        [{"op": "drop_null_rows", "columns": ["e"]}, {"op": "deduplicate", "columns": ["id"]}],
    )
    frame = src(id=["1", "1", "x", "2", "3"], e=["a", "b", "c", None, "d"])
    r = run(config, frame)
    assert (r.rejected_rows, r.null_dropped, r.duplicate_dropped) == (1, 1, 1)
    assert r.rows_in == 5 and r.rows_out == 2
    assert r.rows_in == r.rows_out + r.rejected_rows + r.null_dropped + r.duplicate_dropped


def test_rejected_rows_register_no_deduplicate_key() -> None:
    config = cfg(
        [col("id", "integer", nullable=False), col("v", "integer")],
        [{"op": "deduplicate", "columns": ["id"]}],
    )
    t = Transformer(config)
    first = t.transform_chunk(src(id=["1"], v=["bad"]), [1])  # rejected at cast
    second = t.transform_chunk(src(id=["1", "1"], v=["5", "6"]), [2, 3])
    assert first.rejected_rows == 1
    assert second.row_numbers == [2] and second.duplicate_dropped == 1


# ------------------------------------------------------------------ fail_run


def test_fail_run_evaluates_the_whole_chunk_then_raises_naming_the_first_row() -> None:
    config = cfg([col("x", "integer"), col("y", "integer")], on_validation_failure="fail_run")
    frame = src(x=["1", "2", "bad", "4", "worse"], y=["1"] * 5)
    with pytest.raises(RejectionLimitExceeded, match=r"row 3 failed type_cast"):
        run(config, frame)


def test_fail_run_does_not_raise_for_a_clean_chunk() -> None:
    config = cfg([col("x", "integer")], on_validation_failure="fail_run")
    assert run(config, src(x=["1", "2"])).rows_out == 2


def test_fail_run_raises_for_not_null_too() -> None:
    config = cfg([col("x", "integer", nullable=False)], on_validation_failure="fail_run")
    with pytest.raises(RejectionLimitExceeded, match=r"row 2 failed not_null"):
        run(config, src(x=["1", None]))


def test_reject_row_mode_never_raises() -> None:
    assert run(cfg([col("x", "integer")]), src(x=["bad"])).rejected_rows == 1


def test_fail_run_does_not_fire_for_dropped_rows() -> None:
    config = cfg(
        [col("x", "integer")],
        [{"op": "drop_null_rows", "columns": ["x"]}],
        on_validation_failure="fail_run",
    )
    assert run(config, src(x=[None, "1"])).null_dropped == 1


# --------------------------------------------------------- the QA-03 fixtures


def read_source(name: str) -> pd.DataFrame:
    with (FIXTURES / "csv" / name).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    body = [[c if c != "" else None for c in r] for r in rows[1:]]
    return pd.DataFrame(body, columns=rows[0], dtype=object)


def pipeline(path: str) -> PipelineConfig:
    return validate_pipeline_config(json.loads((ROOT / path).read_text()))


def test_orders_clean_with_orders_full() -> None:
    config = pipeline("contracts/examples/pipeline/valid/orders_full.json")
    r = run(config, read_source("orders_clean.csv"))
    assert (r.rows_in, r.rows_out, r.rejected_rows, r.null_dropped, r.duplicate_dropped) == (
        200,
        200,
        0,
        0,
        0,
    )
    by_id = {row["order_id"]: row for row in r.frame.to_dict("records")}
    for key, want in EXPECTED["orders_clean.csv"]["sample_rows"].items():
        got = by_id[int(key)]
        assert {k: (v.isoformat() if isinstance(v, date) else v) for k, v in got.items()} == want


def test_orders_nulls_counts() -> None:
    config = pipeline("tests/fixtures/pipelines/orders_nulls.json")
    r = run(config, read_source("orders_nulls.csv"))
    want = EXPECTED["orders_nulls.csv"]["counters"]
    assert r.rows_in == want["extracted_count"]
    assert r.rejected_rows == want["rejected_count"]
    assert r.null_dropped == want["null_dropped_count"]
    assert Counter(e.rule for e in r.rejections) == Counter(
        EXPECTED["orders_nulls.csv"]["rejections_by_rule"]
    )


@pytest.mark.parametrize("chunk_rows", [1, 7, 50_000])
def test_orders_dirty_transform_counts_independent_of_chunking(chunk_rows: int) -> None:
    config = pipeline("tests/fixtures/pipelines/orders_dirty_reject.json")
    frame = read_source("orders_dirty.csv")
    t = Transformer(config)
    rules: Counter[str] = Counter()
    rejected = dups = out = 0
    for start in range(0, len(frame), chunk_rows):
        part = frame.iloc[start : start + chunk_rows].reset_index(drop=True)
        r = t.transform_chunk(part, list(range(start + 1, start + 1 + len(part))))
        rules.update(e.rule for e in r.rejections)
        rejected += r.rejected_rows
        dups += r.duplicate_dropped
        out += r.rows_out
    scenario = EXPECTED["orders_dirty.csv"]["scenarios"]["pipelines/orders_dirty_reject.json"]
    assert rules == Counter({"type_cast": 5, "not_null": 3})
    assert dups == scenario["counters"]["duplicate_dropped_count"] == 3
    assert rejected == 8 and out == 96 - 8 - 3


def test_orders_dirty_failrun_raises() -> None:
    config = pipeline("tests/fixtures/pipelines/orders_dirty_failrun.json")
    with pytest.raises(RejectionLimitExceeded):
        run(config, read_source("orders_dirty.csv"))
