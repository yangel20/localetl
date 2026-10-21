"""Synthetic CSV generator for the performance test (deterministic, no real data)."""

import csv
from pathlib import Path

HEADER = [
    "id", "qty", "store_id", "score", "price", "weight",
    "name", "city", "created", "active",
]  # fmt: skip

CITIES = ["Lima", "Quito", "Bogota", "Santiago", "Montevideo", "Asuncion", "La Paz", "Caracas"]


def write_csv(path: Path, rows: int) -> int:
    """Write `rows` data rows (10 columns) and return the file size in bytes."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for i in range(1, rows + 1):
            w.writerow(
                [
                    i,
                    i % 97,
                    i % 1000,
                    (i * 7) % 10_000,
                    f"{(i % 50_000) / 100:.2f}",
                    f"{(i % 9_000) / 7:.3f}",
                    f"  Customer {i % 5000} ",
                    CITIES[i % len(CITIES)].lower(),
                    f"20{10 + i % 15}-{1 + i % 12:02d}-{1 + i % 28:02d}",
                    "true" if i % 3 else "false",
                ]
            )
    return path.stat().st_size


def pipeline_config() -> dict:
    return {
        "version": 1,
        "columns": [
            {"source": "id", "name": "id", "type": "integer", "nullable": False},
            {"source": "qty", "name": "qty", "type": "integer"},
            {"source": "store_id", "name": "store_id", "type": "integer"},
            {"source": "score", "name": "score", "type": "integer"},
            {"source": "price", "name": "price", "type": "float"},
            {"source": "weight", "name": "weight", "type": "float"},
            {"source": "name", "name": "name", "type": "string"},
            {"source": "city", "name": "city", "type": "string"},
            {"source": "created", "name": "created", "type": "date", "format": "%Y-%m-%d"},
            {"source": "active", "name": "active", "type": "boolean"},
        ],
        "transformations": [
            {"op": "trim_whitespace", "columns": ["name"]},
            {"op": "change_case", "columns": ["city"], "case": "upper"},
        ],
        "validations": [
            {"rule": "not_null", "column": "id"},
            {"rule": "range", "column": "qty", "min": 0, "max": 1000},
        ],
        "on_validation_failure": "reject_row",
        "max_rejected_ratio": 0.1,
        "target": {"table": "perf_orders", "mode": "replace"},
    }
