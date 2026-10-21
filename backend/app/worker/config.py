"""Worker settings from WORKER_* environment variables (architecture section 4).

Proposal to the orchestrator: move these into `app.core.settings` (backend-owned).
"""

import os
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class WorkerConfig:
    poll_interval: float = 2.0
    heartbeat_interval: float = 10.0
    stale_after: float = 60.0

    @property
    def stale_after_delta(self) -> timedelta:
        return timedelta(seconds=self.stale_after)

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        def num(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if raw is None or not raw.strip():
                return default
            value = float(raw)
            if value <= 0:
                raise ValueError(f"{name} must be > 0")
            return value

        cfg = cls(
            poll_interval=num("WORKER_POLL_INTERVAL_SECONDS", 2.0),
            heartbeat_interval=num("WORKER_HEARTBEAT_SECONDS", 10.0),
            stale_after=num("WORKER_STALE_AFTER_SECONDS", 60.0),
        )
        if cfg.stale_after <= cfg.heartbeat_interval:
            raise ValueError("WORKER_STALE_AFTER_SECONDS must exceed WORKER_HEARTBEAT_SECONDS")
        return cfg
