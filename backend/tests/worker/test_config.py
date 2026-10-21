import pytest

from app.worker.config import WorkerConfig


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for n in (
        "WORKER_POLL_INTERVAL_SECONDS",
        "WORKER_HEARTBEAT_SECONDS",
        "WORKER_STALE_AFTER_SECONDS",
    ):
        monkeypatch.delenv(n, raising=False)
    assert WorkerConfig.from_env() == WorkerConfig(2.0, 10.0, 60.0)


def test_env_override_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SECONDS", "0.5")
    assert WorkerConfig.from_env().poll_interval == 0.5
    monkeypatch.setenv("WORKER_STALE_AFTER_SECONDS", "5")
    with pytest.raises(ValueError):
        WorkerConfig.from_env()
