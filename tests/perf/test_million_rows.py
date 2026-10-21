"""REQ-61: 1M rows x 10 columns `replace` run in < 5 minutes with memory bounded to ~one chunk."""

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from gen import write_csv

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        os.environ.get("LOCALETL_PERF") != "1", reason="opt-in: set LOCALETL_PERF=1"
    ),
]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
CHILD = Path(__file__).with_name("child.py")
ROWS = int(os.environ.get("LOCALETL_PERF_ROWS", "1000000"))
SMALL_ROWS = 200_000
LIMIT_SECONDS = 300
MEMORY_GROWTH_MB = 150  # extra peak memory allowed for 5x more rows (one chunk is far below this)
DEFAULT_URL = "postgresql+psycopg://localetl:localetl@127.0.0.1:5432/localetl_test"


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    base = sa.engine.make_url(os.environ.get("TEST_DATABASE_URL") or DEFAULT_URL)
    name = f"localetl_perf_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    try:
        command.upgrade(cfg, "head")
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generated data lives outside the repository (or in LOCALETL_PERF_DIR); never committed."""
    custom = os.environ.get("LOCALETL_PERF_DIR")
    if custom:
        path = Path(custom)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return tmp_path_factory.mktemp("localetl-perf")


def run_child(csv_path: Path, url: str) -> dict[str, float]:
    proc = subprocess.run(
        [sys.executable, str(CHILD), str(csv_path), url],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(BACKEND), os.environ.get("PYTHONPATH", "")]),
        },
        timeout=LIMIT_SECONDS * 2,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def published_count(url: str) -> int:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return int(
                conn.execute(sa.text('SELECT count(*) FROM datasets."perf_orders"')).scalar_one()
            )
    finally:
        engine.dispose()


def test_replace_run_time_and_memory(db_url: str, data_dir: Path) -> None:
    small = data_dir / "small.csv"
    big = data_dir / "big.csv"
    write_csv(small, SMALL_ROWS)
    size = write_csv(big, ROWS)
    base = run_child(small, db_url)
    assert base["extracted"] == SMALL_ROWS == base["published_rows"] == published_count(db_url)

    full = run_child(big, db_url)
    rps = ROWS / full["elapsed_s"]
    summary = {
        "rows": ROWS,
        "file_mb": round(size / 1e6, 1),
        "elapsed_s": round(full["elapsed_s"], 1),
        "rows_per_s": round(rps),
        "peak_mb_small": round(base["peak_mb"], 1),
        "peak_mb_full": round(full["peak_mb"], 1),
    }
    (data_dir / "perf-result.json").write_text(json.dumps(summary, indent=2))
    print("\nPERF", json.dumps(summary))

    # row counts: every generated row extracted, loaded or rejected, and the table matches (replace)
    assert full["extracted"] == ROWS
    assert full["loaded"] + full["rejected"] == ROWS
    assert full["published_rows"] == full["loaded"] == published_count(db_url)
    # REQ-61 time limit (applies at the full 1M-row size)
    if ROWS >= 1_000_000:
        assert full["elapsed_s"] < LIMIT_SECONDS, summary
    # memory: 5x the rows must not need materially more memory (one chunk, not the file)
    assert full["peak_mb"] - base["peak_mb"] < MEMORY_GROWTH_MB, summary
