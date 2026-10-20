"""CSV inspection and preview (implemented in ETL-02)."""

from __future__ import annotations

from pathlib import Path

from .types import CsvOptions, CsvPreview, CsvProfile


def inspect_csv(path: Path, options: CsvOptions, *, sample_rows: int = 1000) -> CsvProfile:
    raise NotImplementedError("ETL-02")


def preview_csv(path: Path, options: CsvOptions, *, limit: int = 50) -> CsvPreview:
    raise NotImplementedError("ETL-02")
