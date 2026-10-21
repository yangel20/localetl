"""Run one pipeline in this process and print timing, peak RSS and counters as JSON.

Usage: python child.py <csv> <database-url> [chunk_rows]
A separate process per run gives a clean `ru_maxrss` for each measurement.
"""

import json
import resource
import sys
import time
import uuid
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen import pipeline_config  # noqa: E402

from app.etl import CsvOptions, run_pipeline, validate_pipeline_config  # noqa: E402


def main() -> None:
    csv_path, url = Path(sys.argv[1]), sys.argv[2]
    chunk_rows = int(sys.argv[3]) if len(sys.argv) > 3 else 50_000
    engine = sa.create_engine(url)
    config = validate_pipeline_config(pipeline_config())
    started = time.perf_counter()
    result = run_pipeline(
        config, csv_path, CsvOptions(), engine, uuid.uuid4(), chunk_rows=chunk_rows
    )
    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024
    print(
        json.dumps(
            {
                "elapsed_s": elapsed,
                "peak_mb": peak_mb,
                "extracted": result.extracted_count,
                "loaded": result.loaded_count,
                "rejected": result.rejected_count,
                "published_rows": result.published.row_count,
            }
        )
    )


if __name__ == "__main__":
    main()
