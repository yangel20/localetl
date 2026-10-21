"""Claim loop: recover stale runs, claim one queued run, execute it with a heartbeat."""

import logging
import os
import threading
import uuid
from collections.abc import Callable

import sqlalchemy as sa

from app.services.runs import claim_next_run, finish_run, heartbeat, recover_stale_runs
from app.worker.config import WorkerConfig

log = logging.getLogger("localetl.worker")

# An executor runs a claimed run to completion and performs its terminal transition
# (WK-02). Raising means "unexpected exception": the loop marks the run failed.
Executor = Callable[[sa.Engine, uuid.UUID, str], None]


def make_worker_id() -> str:
    return f"{os.uname().nodename}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def unimplemented_executor(engine: sa.Engine, run_id: uuid.UUID, worker_id: str) -> None:
    """Placeholder until WK-02: fail the run explicitly rather than leave it running."""
    finish_run(engine, run_id, worker_id, "failed", "run execution not implemented (WK-02)")


class Worker:
    def __init__(
        self,
        engine: sa.Engine,
        config: WorkerConfig,
        executor: Executor = unimplemented_executor,
        worker_id: str | None = None,
    ) -> None:
        self.engine = engine
        self.config = config
        self.executor = executor
        self.worker_id = worker_id or make_worker_id()
        self.stop_event = threading.Event()

    def request_stop(self) -> None:
        self.stop_event.set()

    def run_once(self) -> uuid.UUID | None:
        """One poll: recovery, then claim and execute at most one run. Returns its id."""
        for rid in recover_stale_runs(self.engine, self.config.stale_after_delta):
            log.warning("run %s interrupted: stale heartbeat", rid)
        run_id = claim_next_run(self.engine, self.worker_id)
        if run_id is None:
            return None
        log.info("claimed run %s", run_id)
        self._execute(run_id)
        return run_id

    def _execute(self, run_id: uuid.UUID) -> None:
        done = threading.Event()
        beat = threading.Thread(target=self._beat, args=(run_id, done), daemon=True)
        beat.start()
        try:
            self.executor(self.engine, run_id, self.worker_id)
        except Exception as exc:  # unexpected: never leave the run `running`
            log.exception("run %s crashed", run_id)
            finish_run(
                self.engine, run_id, self.worker_id, "failed", f"{type(exc).__name__}: {exc}"
            )
        finally:
            done.set()
            beat.join()

    def _beat(self, run_id: uuid.UUID, done: threading.Event) -> None:
        while not done.wait(self.config.heartbeat_interval):
            try:
                heartbeat(self.engine, run_id, self.worker_id)
            except Exception:
                log.exception("heartbeat failed for run %s", run_id)

    def run_forever(self) -> None:
        log.info("worker %s started", self.worker_id)
        while not self.stop_event.is_set():
            try:
                claimed = self.run_once()
            except sa.exc.OperationalError:
                log.exception("database unavailable; retrying")
                claimed = None
            if claimed is None:
                self.stop_event.wait(self.config.poll_interval)
        log.info("worker %s stopped", self.worker_id)
