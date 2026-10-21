"""Claim, heartbeat, recovery and terminal transitions for runs (architecture section 7.2).

Every function takes an Engine and runs its own short transaction. Raw SQL with bound
parameters only; the SQL is exactly the statements of section 7.2.
"""

import uuid
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

_CLAIM = sa.text(
    """
    UPDATE runs SET status='running', started_at=now(), heartbeat_at=now(), worker_id=:wid
    WHERE id = (SELECT id FROM runs WHERE status='queued' ORDER BY queued_at
                FOR UPDATE SKIP LOCKED LIMIT 1)
    RETURNING id
    """
)

_RECOVER = sa.text(
    """
    UPDATE runs SET status='interrupted', finished_at=now(),
                    error_message='worker stopped unexpectedly'
    WHERE status='running' AND heartbeat_at < now() - make_interval(secs => :stale)
    RETURNING id
    """
)

_HEARTBEAT = sa.text(
    "UPDATE runs SET heartbeat_at=now() WHERE id=:id AND status='running' AND worker_id=:wid"
)

_FINISH = sa.text(
    """
    UPDATE runs SET status=:status, finished_at=now(), error_message=:msg
    WHERE id=:id AND status='running' AND worker_id=:wid
    """
)


def claim_next_run(engine: sa.Engine, worker_id: str) -> uuid.UUID | None:
    """Claim the oldest queued run. None if nothing is queued or another run is active.

    A unique violation on `one_running_run` means a run is already running: the claim
    transaction rolls back (the run stays queued) and the caller backs off.
    """
    try:
        with engine.begin() as conn:
            row = conn.execute(_CLAIM, {"wid": worker_id}).first()
    except IntegrityError as exc:
        if "one_running_run" in str(exc.orig) or "one_running_run" in str(exc):
            return None
        raise
    return None if row is None else uuid.UUID(str(row[0]))


def recover_stale_runs(engine: sa.Engine, stale_after: timedelta) -> list[uuid.UUID]:
    """Mark `running` runs with an old heartbeat as `interrupted`."""
    with engine.begin() as conn:
        rows = conn.execute(_RECOVER, {"stale": stale_after.total_seconds()}).all()
    return [uuid.UUID(str(r[0])) for r in rows]


def heartbeat(engine: sa.Engine, run_id: uuid.UUID, worker_id: str) -> bool:
    """Refresh the heartbeat. False if this worker no longer owns a running run."""
    with engine.begin() as conn:
        return conn.execute(_HEARTBEAT, {"id": run_id, "wid": worker_id}).rowcount == 1


def finish_run(
    engine: sa.Engine, run_id: uuid.UUID, worker_id: str, status: str, error_message: str | None
) -> bool:
    """Minimal terminal transition (failed/interrupted). WK-02 adds the full §7.2 transactions."""
    if status not in ("failed", "interrupted"):
        raise ValueError(f"unsupported terminal status: {status}")
    with engine.begin() as conn:
        res = conn.execute(
            _FINISH, {"id": run_id, "wid": worker_id, "status": status, "msg": error_message}
        )
    return res.rowcount == 1
