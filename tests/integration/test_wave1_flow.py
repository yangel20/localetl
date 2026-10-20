"""QA-07: Wave 1 integration, the exit gate.

Wave 1 ships the API and the ETL engine; the worker is Wave 2. So the end-to-end flow is:

1. through the HTTP API: upload a fixture, preview it, create and validate a pipeline, queue a run
   (``queued``; a second run is 409);
2. through the engine: ``run_pipeline`` on the *same* stored file, options and config snapshot the
   API produced, with ``replace`` and ``append``;
3. what the worker will persist is written to the database by ``worker_finish`` below (a stand-in
   that WK-02 replaces), and the result is read back through ``/runs``, ``/datasets``, ``/rows``,
   ``/profile`` and ``/metrics``.

Expected numbers come from ``tests/fixtures/expected.json``, never from the code under test.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import sqlalchemy as sa

from app.etl import (
    CsvOptions,
    EtlError,
    RejectionLimitExceeded,
    RunInterrupted,
    RunResult,
    StageEvent,
    run_pipeline,
    validate_pipeline_config,
)

if TYPE_CHECKING:  # fixtures live in conftest.py (no package: no relative import)
    from conftest import Conformance, Contract

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "tests" / "fixtures"
CSV = FX / "csv"
EXPECTED: dict[str, Any] = json.loads((FX / "expected.json").read_text("utf-8"))
ORDERS_FULL = ROOT / "contracts" / "examples" / "pipeline" / "valid" / "orders_full.json"
COUNTERS = (
    "extracted_count",
    "loaded_count",
    "rejected_count",
    "duplicate_dropped_count",
    "null_dropped_count",
)


# ----------------------------------------------------------------------------------- helpers


@pytest.fixture
def fresh(scratch_engine: sa.Engine, data_dir: Path) -> Iterator[sa.Engine]:
    """Empty metadata, published tables, stored files; in-process app only."""
    if "LOCALETL_API_URL" in os.environ:
        pytest.skip("the flow reads and writes the database and data directory directly")

    def wipe() -> None:
        with scratch_engine.begin() as conn:
            conn.execute(sa.text("TRUNCATE pipelines, data_sources CASCADE"))
            names = conn.execute(
                sa.text(
                    "SELECT schemaname, tablename FROM pg_tables"
                    " WHERE schemaname IN ('datasets', 'staging')"
                )
            ).all()
            for schema, table in names:
                conn.execute(sa.text(f'DROP TABLE IF EXISTS {schema}."{table}" CASCADE'))
        for sub in ("sources", "tmp"):
            folder = data_dir / sub
            if folder.is_dir():
                for f in folder.iterdir():
                    f.unlink()

    wipe()
    yield scratch_engine
    wipe()


def counters_of(entry: dict[str, int]) -> tuple[int, ...]:
    return tuple(entry[k] for k in COUNTERS)


def result_counters(result: RunResult) -> tuple[int, ...]:
    return tuple(getattr(result, k) for k in COUNTERS)


def reconciles(c: tuple[int, ...]) -> bool:
    extracted, loaded, rejected, dup, null = c
    return extracted == loaded + rejected + dup + null


def load_config(path: str | Path) -> dict[str, Any]:
    """A pipeline config: absolute, repo-relative (``contracts/...``) or fixture-relative."""
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p if str(p).startswith("contracts/") else FX / p
    return json.loads(p.read_text("utf-8"))


def table_count(engine: sa.Engine, table: str, run_id: uuid.UUID | None = None) -> int:
    where = " WHERE _localetl_run_id = :r" if run_id else ""
    with engine.connect() as conn:
        return int(
            conn.execute(
                sa.text(f'SELECT count(*) FROM datasets."{table}"{where}'),
                {"r": str(run_id)} if run_id else {},
            ).scalar_one()
        )


def table_exists(engine: sa.Engine, table: str) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(sa.text("SELECT to_regclass(:n)"), {"n": f'datasets."{table}"'}).scalar()
            is not None
        )


def staging_tables(engine: sa.Engine) -> list[str]:
    with engine.connect() as conn:
        return sorted(
            conn.execute(
                sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'staging'")
            ).scalars()
        )


def fingerprint(engine: sa.Engine, table: str) -> tuple[int, str]:
    """Row count plus a hash of the whole table, to prove a failed run changed nothing."""
    with engine.connect() as conn:
        return tuple(  # type: ignore[return-value]
            conn.execute(
                sa.text(
                    f"SELECT count(*), coalesce(md5(string_agg(t::text, '|' ORDER BY t::text)), '')"
                    f' FROM datasets."{table}" t'
                )
            ).one()
        )


def upload(
    client: httpx.Client, contract: Contract, filename: str, **fields: str
) -> httpx.Response:
    return client.post(
        f"{contract.prefix}/sources",
        files={"file": (filename, (CSV / filename).read_bytes(), "text/csv")},
        data=fields,
    )


def stored_source(engine: sa.Engine, data_dir: Path, source_id: str) -> tuple[Path, CsvOptions]:
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT stored_path, csv_options FROM data_sources WHERE id = :id"),
            {"id": source_id},
        ).one()
    return data_dir / row.stored_path, CsvOptions(**row.csv_options)


def queued_snapshot(engine: sa.Engine, run_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        snap = conn.execute(
            sa.text("SELECT config_snapshot FROM runs WHERE id = :id"), {"id": run_id}
        ).scalar_one()
    return dict(snap)


def worker_finish(
    engine: sa.Engine, run_id: str, result: RunResult, events: list[StageEvent]
) -> None:
    """Stand-in for the worker's success transaction (architecture 7.2); WK-02 replaces it."""
    published = result.published
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE runs SET status = 'running', started_at = now() - interval '2 seconds',"
                " heartbeat_at = now(), worker_id = 'qa' WHERE id = :id"
            ),
            {"id": run_id},
        )
        for e in events:
            conn.execute(
                sa.text(
                    "INSERT INTO run_events"
                    " (run_id, stage, status, rows_in, rows_out, message, created_at)"
                    " VALUES (:r, :s, :st, :ri, :ro, :m, :at)"
                ),
                {
                    "r": run_id,
                    "s": e.stage,
                    "st": e.status,
                    "ri": e.rows_in,
                    "ro": e.rows_out,
                    "m": e.message,
                    "at": e.at,
                },
            )
        pipeline_id = conn.execute(
            sa.text("SELECT pipeline_id FROM runs WHERE id = :id"), {"id": run_id}
        ).scalar_one()
        dataset_id = conn.execute(
            sa.text(
                "INSERT INTO datasets (table_name, pipeline_id, last_run_id, row_count, columns)"
                " VALUES (:t, :p, :r, :n, CAST(:c AS jsonb))"
                " ON CONFLICT (table_name) DO UPDATE SET last_run_id = :r, row_count = :n,"
                " columns = CAST(:c AS jsonb), published_at = now() RETURNING id"
            ),
            {
                "t": published.table,
                "p": pipeline_id,
                "r": run_id,
                "n": published.row_count,
                "c": json.dumps([{"name": n, "type": t} for n, t in published.columns]),
            },
        ).scalar_one()
        conn.execute(
            sa.text(
                "UPDATE runs SET status = 'succeeded', finished_at = now(), dataset_id = :d,"
                " extracted_count = :e, loaded_count = :l, rejected_count = :r,"
                " duplicate_dropped_count = :dd, null_dropped_count = :nd WHERE id = :id"
            ),
            {
                "id": run_id,
                "d": dataset_id,
                "e": result.extracted_count,
                "l": result.loaded_count,
                "r": result.rejected_count,
                "dd": result.duplicate_dropped_count,
                "nd": result.null_dropped_count,
            },
        )
        for r in result.rejected_sample:
            conn.execute(
                sa.text(
                    "INSERT INTO run_rejections"
                    " (run_id, row_number, column_name, rule, message, value)"
                    " VALUES (:r, :n, :c, :rule, :m, :v)"
                ),
                {
                    "r": run_id,
                    "n": r.row_number,
                    "c": r.column,
                    "rule": r.rule,
                    "m": r.message,
                    "v": r.value,
                },
            )


def engine_run(
    engine: sa.Engine,
    config: dict[str, Any],
    csv_path: Path,
    options: CsvOptions | None = None,
    chunk_rows: int = 50_000,
    run_id: uuid.UUID | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[RunResult, list[StageEvent], uuid.UUID]:
    events: list[StageEvent] = []
    rid = run_id or uuid.uuid4()
    result = run_pipeline(
        validate_pipeline_config(config),
        csv_path,
        options or CsvOptions(),
        engine,
        rid,
        chunk_rows=chunk_rows,
        on_event=events.append,
        should_stop=should_stop,
    )
    return result, events, rid


# ---------------------------------------------------------------------------- 1 + 2 + 3: the flow


def test_wave1_flow_upload_to_dataset_and_metrics(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    fresh: sa.Engine,
    data_dir: Path,
) -> None:
    api = contract.prefix
    # --- API: upload, preview
    up = upload(client, contract, "orders_clean.csv")
    conformance.assert_conforms(up)
    assert up.status_code == 201
    source = up.json()
    assert source["row_count"] == EXPECTED["orders_clean.csv"]["counters"]["extracted_count"]
    preview = client.get(f"{api}/sources/{source['id']}/preview")
    conformance.assert_conforms(preview)
    assert preview.json()["sampled_rows"] == 50 and len(preview.json()["columns"]) == 7
    # --- API: create, validate the pipeline from the contract example
    config = load_config(ORDERS_FULL)
    validated = client.post(
        f"{api}/pipelines/validate", json={"config": config, "source_id": source["id"]}
    )
    conformance.assert_conforms(validated)
    assert validated.json() == {"valid": True, "errors": []}
    created = client.post(
        f"{api}/pipelines", json={"name": "orders", "source_id": source["id"], "config": config}
    )
    conformance.assert_conforms(created)
    assert created.status_code == 201
    pipeline_id = created.json()["id"]
    # --- API: queue a run; a second one is 409
    queued = client.post(f"{api}/pipelines/{pipeline_id}/runs")
    conformance.assert_conforms(queued)
    assert queued.status_code == 202 and queued.json()["status"] == "queued"
    run_id = queued.json()["id"]
    second = client.post(f"{api}/pipelines/{pipeline_id}/runs")
    conformance.assert_conforms(second)
    assert second.status_code == 409
    # --- engine: the same stored file, options and snapshot
    csv_path, options = stored_source(fresh, data_dir, source["id"])
    snapshot = queued_snapshot(fresh, run_id)
    assert snapshot == config
    result, events, rid = engine_run(fresh, snapshot, csv_path, options, run_id=uuid.UUID(run_id))
    expected = counters_of(EXPECTED["orders_clean.csv"]["counters"])
    assert result_counters(result) == expected and reconciles(expected)
    assert (
        table_count(fresh, "orders") == result.loaded_count == 200
    )  # replace: exactly this run's rows
    assert table_count(fresh, "orders", rid) == result.loaded_count
    assert result.published.row_count == 200
    worker_finish(fresh, run_id, result, events)
    # --- API: read everything back
    run = client.get(f"{api}/runs/{run_id}")
    conformance.assert_conforms(run)
    assert (
        run.json()["status"] == "succeeded" and tuple(run.json()[k] for k in COUNTERS) == expected
    )
    assert run.json()["duration_ms"] is not None and run.json()["dataset_id"]
    evs = client.get(f"{api}/runs/{run_id}/events")
    conformance.assert_conforms(evs)
    assert [(e["stage"], e["status"]) for e in evs.json()][-1] == ("publish", "completed")
    listing = client.get(f"{api}/datasets")
    conformance.assert_conforms(listing)
    assert listing.json()["total"] == 1 and listing.json()["items"][0]["table_name"] == "orders"
    dataset_id = listing.json()["items"][0]["id"]
    assert dataset_id == run.json()["dataset_id"] and listing.json()["items"][0]["row_count"] == 200
    rows = client.get(
        f"{api}/datasets/{dataset_id}/rows",
        params={"sort": "order_id", "order": "desc", "limit": 3},
    )
    conformance.assert_conforms(rows)
    assert rows.json()["total"] == 200 and [r["order_id"] for r in rows.json()["items"]] == [
        200,
        199,
        198,
    ]
    assert not any(k.startswith("_localetl_") for r in rows.json()["items"] for k in r)
    profile = client.get(f"{api}/datasets/{dataset_id}/profile")
    conformance.assert_conforms(profile)
    cols = {c["name"]: c for c in profile.json()["columns"]}
    assert profile.json()["row_count"] == 200 and cols["order_id"]["distinct_count"] == 200
    assert (cols["order_id"]["min"], cols["order_id"]["max"]) == (1, 200)
    metrics = client.get(f"{api}/metrics/summary")
    conformance.assert_conforms(metrics)
    m = metrics.json()
    assert (
        m["runs_by_status"]["succeeded"] == 1
        and m["loaded_count_total"] == 200
        and m["total_runs"] == 1
    )
    assert sum(d["loaded_count"] for d in m["daily"]) == 200
    # --- append twice on the same table; counts are per run, totals accumulate
    append_config = {**config, "target": {"table": "orders", "mode": "append"}}
    r1, _, rid1 = engine_run(fresh, append_config, csv_path, options)
    r2, _, rid2 = engine_run(fresh, append_config, csv_path, options)
    assert (r1.loaded_count, r2.loaded_count) == (200, 200)
    assert r1.published.row_count == 400 and r2.published.row_count == 600
    assert table_count(fresh, "orders") == 600
    assert (
        table_count(fresh, "orders", rid1),
        table_count(fresh, "orders", rid2),
        table_count(fresh, "orders", rid),
    ) == (200, 200, 200)
    # replace again collapses to exactly one run's rows
    r3, _, rid3 = engine_run(fresh, config, csv_path, options)
    assert table_count(fresh, "orders") == 200 == table_count(fresh, "orders", rid3)
    assert staging_tables(fresh) == []


# -------------------------------- 2: every succeeded fixture scenario, any chunking


def succeeded_scenarios() -> list[tuple[str, str, tuple[int, ...]]]:
    """(csv file, pipeline config path, expected five counters) from expected.json."""
    found: list[tuple[str, str, tuple[int, ...]]] = []
    for name, entry in EXPECTED.items():
        if not isinstance(entry, dict) or name in ("formats", "_comment"):
            continue
        if entry.get("outcome") == "succeeded" and "config" in entry:
            c = entry.get("counters") or entry["counters_identical_for_every_chunk_size"]
            found.append((name, entry["config"], counters_of(c)))
        for cfg, sc in entry.get("scenarios", {}).items():
            if sc.get("outcome") == "succeeded":
                found.append((name, cfg, counters_of(sc["counters"])))
    return found


SCENARIOS = succeeded_scenarios()


def test_scenario_list_is_complete() -> None:
    # clean, nulls, chunk_dupes, dirty (reject, unique), ragged, straddle, parse_error_dedupe
    assert len(SCENARIOS) == 8
    assert all(reconciles(c) for _, _, c in SCENARIOS)


@pytest.mark.parametrize("chunk_rows", [1, 7, 50_000])
@pytest.mark.parametrize(
    ("csv_name", "config_path", "expected"),
    SCENARIOS,
    ids=[f"{n}:{Path(c).name}" for n, c, _ in SCENARIOS],
)
def test_engine_counters_match_expected_json(
    fresh: sa.Engine, csv_name: str, config_path: str, expected: tuple[int, ...], chunk_rows: int
) -> None:
    config = load_config(config_path)
    result, events, rid = engine_run(fresh, config, CSV / csv_name, chunk_rows=chunk_rows)
    table = config["target"]["table"]
    assert result_counters(result) == expected, (csv_name, config_path, chunk_rows)
    assert reconciles(result_counters(result))
    assert (
        table_count(fresh, table) == result.loaded_count
    )  # replace: published rows == loaded_count
    assert table_count(fresh, table, rid) == result.loaded_count
    assert events[-1].counters.loaded_count == result.loaded_count and staging_tables(fresh) == []
    # counters are cumulative and never decrease across events
    seen = [tuple(getattr(e.counters, k) for k in COUNTERS) for e in events]
    assert all(
        all(b >= a for a, b in zip(x, y, strict=True)) for x, y in zip(seen, seen[1:], strict=False)
    )


# ---------------------------------------- 4: failures publish nothing, interrupts clean


def seed_published(engine: sa.Engine) -> tuple[int, str]:
    result, _, _ = engine_run(engine, load_config(ORDERS_FULL), CSV / "orders_clean.csv")
    assert result.loaded_count == 200
    return fingerprint(engine, "orders")


@pytest.mark.parametrize(
    ("csv_name", "config_path", "error"),
    [
        ("orders_dirty.csv", ORDERS_FULL, RejectionLimitExceeded),  # 23/96 > ratio 0.1
        ("orders_dirty.csv", FX / "pipelines/orders_dirty_failrun.json", RejectionLimitExceeded),
    ],
)
def test_failing_pipeline_publishes_nothing(
    fresh: sa.Engine, csv_name: str, config_path: Path, error: type[EtlError]
) -> None:
    before = seed_published(fresh)
    events: list[StageEvent] = []
    with pytest.raises(error) as exc:
        run_pipeline(
            validate_pipeline_config(load_config(config_path)),
            CSV / csv_name,
            CsvOptions(),
            fresh,
            uuid.uuid4(),
            chunk_rows=10,
            on_event=events.append,
        )
    assert fingerprint(fresh, "orders") == before  # the published table is byte-for-byte unchanged
    assert staging_tables(fresh) == []
    assert events[-1].status == "failed" and events[-1].counters.loaded_count == 0
    assert exc.value.rejected_sample is not None


def test_failing_run_on_a_new_table_creates_no_table(fresh: sa.Engine) -> None:
    config = load_config(ORDERS_FULL)
    config["target"]["table"] = "never_published"
    with pytest.raises(RejectionLimitExceeded):
        engine_run(fresh, config, CSV / "orders_dirty.csv")
    assert not table_exists(fresh, "never_published") and staging_tables(fresh) == []


def test_append_schema_mismatch_publishes_nothing(fresh: sa.Engine) -> None:
    before = seed_published(fresh)
    mismatch = load_config(FX / "pipelines/orders_append_mismatch.json")
    with pytest.raises(EtlError) as exc:
        engine_run(fresh, mismatch, CSV / "orders_clean.csv")
    assert type(exc.value).__name__ == "LoadError"
    assert fingerprint(fresh, "orders") == before and staging_tables(fresh) == []


def test_interruption_at_every_boundary_drops_staging_and_changes_nothing(fresh: sa.Engine) -> None:
    before = seed_published(fresh)
    config = load_config(
        FX / "pipelines/orders_append.json"
    )  # append: the published table must not grow
    boundary, interrupted = 0, 0
    while True:
        boundary += 1
        calls = 0

        def stop(target: int = boundary) -> bool:
            nonlocal calls
            calls += 1
            return calls == target

        events: list[StageEvent] = []
        try:
            run_pipeline(
                validate_pipeline_config(config),
                CSV / "orders_clean.csv",
                CsvOptions(),
                fresh,
                uuid.uuid4(),
                chunk_rows=80,
                on_event=events.append,
                should_stop=stop,
            )
            break  # past the last boundary the run completes
        except RunInterrupted:
            interrupted += 1
            assert events[-1].status == "failed" and events[-1].message == "interrupted"
            assert events[-1].counters.loaded_count == 0
            assert fingerprint(fresh, "orders") == before and staging_tables(fresh) == [], boundary
    assert interrupted >= 10  # extract/transform/validate/load per chunk, validate and publish


# ------------------------------------------------------------------------------ Q4 through the API


def test_q4_duplicate_headers_upload_is_422(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    fresh: sa.Engine,
    data_dir: Path,
) -> None:
    r = upload(client, contract, "duplicate_headers.csv")
    conformance.assert_conforms(r)
    assert r.status_code == 422
    assert r.json()["error"]["message"] == EXPECTED["formats"]["duplicate_headers.csv"]["message"]
    with fresh.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM data_sources")).scalar_one() == 0
    assert not list((data_dir / "sources").glob("*")) and not list((data_dir / "tmp").glob("*"))


def test_q4_ragged_fixture_runs_succeeded_with_parse_errors_as_expected(
    client: httpx.Client,
    conformance: Conformance,
    contract: Contract,
    fresh: sa.Engine,
    data_dir: Path,
) -> None:
    api = contract.prefix
    structure = EXPECTED["formats"]["ragged_rows.csv"]
    up = upload(client, contract, "ragged_rows.csv")
    conformance.assert_conforms(up)
    source = up.json()
    assert source["row_count"] == structure["row_count"] == 6  # malformed records are counted
    preview = client.get(f"{api}/sources/{source['id']}/preview")
    conformance.assert_conforms(preview)
    assert preview.json()["sampled_rows"] == structure["well_formed_count"]  # but not previewed
    config = load_config("pipelines/ragged_reject.json")
    pipeline = client.post(
        f"{api}/pipelines", json={"name": "ragged", "source_id": source["id"], "config": config}
    )
    conformance.assert_conforms(pipeline)
    assert pipeline.status_code == 201
    run = client.post(f"{api}/pipelines/{pipeline.json()['id']}/runs")
    conformance.assert_conforms(run)
    run_id = run.json()["id"]
    csv_path, options = stored_source(fresh, data_dir, source["id"])
    result, events, rid = engine_run(
        fresh,
        queued_snapshot(fresh, run_id),
        csv_path,
        options,
        chunk_rows=2,
        run_id=uuid.UUID(run_id),
    )
    want = counters_of(EXPECTED["ragged_rows.csv"]["counters"])
    assert result_counters(result) == want and reconciles(want)
    got = [(r.row_number, r.rule, r.column, r.message, r.value) for r in result.rejected_sample]
    exp = [
        (e["row_number"], e["rule"], e["column"], e["message"], e["value"])
        for e in structure["parse_errors"]
    ]
    assert (
        got == exp
    )  # row numbers, parse_error, column null, message and value as in expected.json
    worker_finish(fresh, run_id, result, events)
    rej = client.get(f"{api}/runs/{run_id}/rejections")
    conformance.assert_conforms(rej)
    assert (
        rej.json()["total"] == 3 and [i["rule"] for i in rej.json()["items"]] == ["parse_error"] * 3
    )
    assert all(i["column"] is None for i in rej.json()["items"])
    done = client.get(f"{api}/runs/{run_id}")
    conformance.assert_conforms(done)
    assert done.json()["status"] == "succeeded" and done.json()["rejected_count"] == 3
    rows = client.get(f"{api}/datasets/{done.json()['dataset_id']}/rows")
    conformance.assert_conforms(rows)
    assert rows.json()["total"] == 3 and [r["id"] for r in rows.json()["items"]] == [1, 4, 6]


def test_q4_fail_run_on_the_first_parse_error_publishes_nothing(fresh: sa.Engine) -> None:
    scenario = EXPECTED["ragged_rows.csv"]["scenarios"]["pipelines/ragged_failrun.json"]
    config = load_config("pipelines/ragged_failrun.json")
    for chunk_rows, at_failure in scenario["counters_at_failure_by_chunk_rows"].items():
        events: list[StageEvent] = []
        with pytest.raises(RejectionLimitExceeded) as exc:
            run_pipeline(
                validate_pipeline_config(config),
                CSV / "ragged_rows.csv",
                CsvOptions(),
                fresh,
                uuid.uuid4(),
                chunk_rows=int(chunk_rows),
                on_event=events.append,
            )
        assert "row 2" in str(exc.value) and "parse_error" in str(exc.value)
        assert tuple(getattr(events[-1].counters, k) for k in COUNTERS) == counters_of(
            at_failure
        ), chunk_rows
        assert not table_exists(fresh, "ragged") and staging_tables(fresh) == []


def test_q4_file_level_faults_fail_at_extract_and_publish_nothing(fresh: sa.Engine) -> None:
    config = load_config("pipelines/ragged_reject.json")
    for name in (
        "duplicate_headers.csv",
        "empty_header.csv",
        "unterminated_quote.csv",
        "empty.csv",
        "header_only.csv",
    ):
        events: list[StageEvent] = []
        with pytest.raises(EtlError) as exc:
            run_pipeline(
                validate_pipeline_config(config),
                CSV / name,
                CsvOptions(),
                fresh,
                uuid.uuid4(),
                on_event=events.append,
            )
        assert type(exc.value).__name__ == "CsvFormatError" and events[-1].stage == "extract", name
        assert not table_exists(fresh, "ragged") and staging_tables(fresh) == []
