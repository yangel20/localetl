"""WK-03: SIGINT/SIGTERM handling of the real `python -m app.worker` process (REQ-44)."""

import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.worker.test_execute import config, make_run, q

pytestmark = pytest.mark.usefixtures("clean_runs")

BACKEND = Path(__file__).resolve().parents[2]


def start_worker(engine: sa.Engine, data_dir: Path) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "DATABASE_URL": engine.url.render_as_string(hide_password=False),
        "LOCALETL_DATA_DIR": str(data_dir),
        "LOCALETL_CHUNK_ROWS": "500",
        "WORKER_POLL_INTERVAL_SECONDS": "0.1",
        "WORKER_HEARTBEAT_SECONDS": "0.5",
        "WORKER_STALE_AFTER_SECONDS": "30",
    }
    return subprocess.Popen([sys.executable, "-m", "app.worker"], cwd=BACKEND, env=env)


def wait_for(cond: Callable[[], bool], timeout: float = 30) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_idle_worker_exits_cleanly(engine: sa.Engine, tmp_path: Path, sig: signal.Signals) -> None:
    probe = make_run(engine, {"version": 99})  # fails fast: proves the worker is up and idle
    proc = start_worker(engine, tmp_path)
    try:
        wait_for(
            lambda: q(engine, "SELECT status FROM runs WHERE id=:i", i=probe)[0].status == "failed"
        )
        time.sleep(0.5)
        assert proc.poll() is None
        proc.send_signal(sig)
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_mid_run_signal_interrupts_run_and_exits_cleanly(
    engine: sa.Engine, tmp_path: Path, sig: signal.Signals
) -> None:
    (tmp_path / "sources").mkdir()
    rows = "\n".join(f"{i},n{i},{i}" for i in range(400_000))
    (tmp_path / "sources" / "s.csv").write_text("id,name,score\n" + rows + "\n")
    rid = make_run(engine, config(f"wk03_{uuid.uuid4().hex[:8]}"))
    second = make_run(engine, config(f"wk03b_{uuid.uuid4().hex[:8]}"))
    proc = start_worker(engine, tmp_path)
    try:
        wait_for(
            lambda: (
                q(engine, "SELECT 1 FROM run_events WHERE run_id=:i AND status='progress'", i=rid)
                != []
            )
        )
        proc.send_signal(sig)
        assert proc.wait(timeout=60) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    first = q(engine, "SELECT status, finished_at, loaded_count FROM runs WHERE id=:i", i=rid)[0]
    assert first.status == "interrupted" and first.finished_at and first.loaded_count == 0
    # Stopped claiming: the other queued run was never started.
    assert q(engine, "SELECT status FROM runs WHERE id=:i", i=second)[0].status == "queued"
    assert q(engine, "SELECT 1 FROM datasets") == []
