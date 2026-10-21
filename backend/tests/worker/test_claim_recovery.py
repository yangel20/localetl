import threading
import time
import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.services.runs import claim_next_run, finish_run, heartbeat, recover_stale_runs
from app.worker.config import WorkerConfig
from app.worker.loop import Worker
from tests.worker.conftest import get_run, insert_run

pytestmark = pytest.mark.usefixtures("clean_runs")


def test_claim_sets_running_fields(engine: sa.Engine) -> None:
    rid = insert_run(engine)
    assert claim_next_run(engine, "w1") == rid
    row = get_run(engine, rid)
    assert (row.status, row.worker_id) == ("running", "w1")
    assert row.started_at is not None and row.heartbeat_at is not None


def test_claim_empty_queue_returns_none(engine: sa.Engine) -> None:
    assert claim_next_run(engine, "w1") is None


def test_claim_is_fifo(engine: sa.Engine) -> None:
    first = insert_run(engine)
    second = insert_run(engine)
    assert claim_next_run(engine, "w1") == first
    finish_run(engine, first, "w1", "failed", "x")
    assert claim_next_run(engine, "w1") == second


def test_backs_off_while_a_run_is_running(engine: sa.Engine) -> None:
    active = insert_run(engine)
    queued = insert_run(engine)
    assert claim_next_run(engine, "w1") == active
    assert claim_next_run(engine, "w2") is None  # one_running_run violation, handled
    assert get_run(engine, queued).status == "queued"
    finish_run(engine, active, "w1", "failed", "x")
    assert claim_next_run(engine, "w2") == queued


def test_two_racing_workers_claim_exactly_one(engine: sa.Engine) -> None:
    for _ in range(15):
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM runs"))
        a, b = insert_run(engine), insert_run(engine)
        barrier = threading.Barrier(2)
        results: dict[str, uuid.UUID | None] = {}

        def go(
            name: str,
            barrier: threading.Barrier = barrier,
            results: dict[str, uuid.UUID | None] = results,
        ) -> None:
            barrier.wait()
            results[name] = claim_next_run(engine, name)

        threads = [threading.Thread(target=go, args=(n,)) for n in ("w1", "w2")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        claimed = [v for v in results.values() if v is not None]
        assert len(claimed) == 1 and claimed[0] in (a, b)
        with engine.connect() as conn:
            n = conn.execute(sa.text("SELECT count(*) FROM runs WHERE status='running'")).scalar()
        assert n == 1


def test_racing_workers_single_queued_run_claimed_once(engine: sa.Engine) -> None:
    for _ in range(15):
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM runs"))
        insert_run(engine)
        barrier = threading.Barrier(4)
        results: list[uuid.UUID | None] = []

        def go(
            name: str,
            barrier: threading.Barrier = barrier,
            results: list[uuid.UUID | None] = results,
        ) -> None:
            barrier.wait()
            results.append(claim_next_run(engine, name))

        threads = [threading.Thread(target=go, args=(f"w{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len([r for r in results if r is not None]) == 1


def test_recovery_interrupts_only_stale_running(engine: sa.Engine) -> None:
    stale = insert_run(engine, "running", heartbeat_age_s=120)
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE runs SET extracted_count=7 WHERE id=:i"), {"i": stale})
    fresh = insert_run(engine, "queued")
    ids = recover_stale_runs(engine, timedelta(seconds=60))
    assert ids == [stale]
    row = get_run(engine, stale)
    assert row.status == "interrupted" and row.finished_at is not None
    assert row.error_message == "worker stopped unexpectedly"
    assert row.extracted_count == 7 and row.loaded_count == 0
    assert get_run(engine, fresh).status == "queued"


def test_recovery_keeps_live_run_and_unblocks_queue(engine: sa.Engine) -> None:
    live = insert_run(engine, "running", heartbeat_age_s=5)
    assert recover_stale_runs(engine, timedelta(seconds=60)) == []
    assert get_run(engine, live).status == "running"


def test_stale_run_recovered_then_next_claimed_in_one_poll(engine: sa.Engine) -> None:
    stale = insert_run(engine, "running", heartbeat_age_s=300)
    nxt = insert_run(engine)
    w = Worker(
        engine,
        WorkerConfig(0.1, 0.05, 60),
        executor=lambda e, r, w: finish_run(e, r, w, "failed", "t"),
    )
    assert w.run_once() == nxt
    assert get_run(engine, stale).status == "interrupted"
    assert get_run(engine, nxt).status == "failed"


def test_heartbeat_requires_ownership(engine: sa.Engine) -> None:
    rid = insert_run(engine)
    claim_next_run(engine, "w1")
    before = get_run(engine, rid).heartbeat_at
    time.sleep(0.05)
    assert heartbeat(engine, rid, "w1") is True
    assert get_run(engine, rid).heartbeat_at > before
    assert heartbeat(engine, rid, "other") is False


def test_worker_heartbeats_during_execution(engine: sa.Engine) -> None:
    insert_run(engine)
    seen: list[object] = []

    def slow(eng: sa.Engine, run_id: uuid.UUID, wid: str) -> None:
        seen.append(get_run(eng, run_id).heartbeat_at)
        time.sleep(0.4)
        seen.append(get_run(eng, run_id).heartbeat_at)
        finish_run(eng, run_id, wid, "failed", "done")

    Worker(engine, WorkerConfig(0.1, 0.05, 60), executor=slow).run_once()
    assert seen[1] > seen[0]


def test_executor_exception_marks_failed(engine: sa.Engine) -> None:
    rid = insert_run(engine)

    def boom(*_: object) -> None:
        raise RuntimeError("kaput")

    Worker(engine, WorkerConfig(0.1, 0.05, 60), executor=boom).run_once()
    row = get_run(engine, rid)
    assert row.status == "failed" and "kaput" in row.error_message and row.finished_at


def test_restart_recovers_run_left_by_dead_worker(engine: sa.Engine) -> None:
    rid = insert_run(engine)
    claim_next_run(engine, "dead-worker")  # worker dies: no heartbeat, no finish
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE runs SET heartbeat_at = now() - interval '10 minutes'"))
    Worker(engine, WorkerConfig(0.1, 0.05, 60)).run_once()
    assert get_run(engine, rid).status == "interrupted"


def test_run_forever_stops_on_request(engine: sa.Engine) -> None:
    insert_run(engine)
    w = Worker(engine, WorkerConfig(0.05, 0.05, 60))
    t = threading.Thread(target=w.run_forever)
    t.start()
    time.sleep(0.5)
    w.request_stop()
    t.join(timeout=5)
    assert not t.is_alive()
