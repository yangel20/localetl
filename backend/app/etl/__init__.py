"""LocalETL ETL engine: public interface (docs/architecture.md section 5)."""

from .config import validate_pipeline_config
from .errors import (
    ConfigValidationError,
    CsvFormatError,
    EtlError,
    LoadError,
    RejectionLimitExceeded,
    RunInterrupted,
    SourceMismatchError,
)
from .extract import inspect_csv, preview_csv
from .runner import run_pipeline
from .types import (
    ColumnInfo,
    ColumnType,
    ConfigErrorItem,
    CsvOptions,
    CsvPreview,
    CsvProfile,
    EventStatus,
    PipelineConfig,
    PublishedTable,
    RejectedRow,
    RejectionRule,
    RunCounters,
    RunResult,
    Stage,
    StageEvent,
)

__all__ = [
    "ColumnInfo",
    "ColumnType",
    "ConfigErrorItem",
    "ConfigValidationError",
    "CsvFormatError",
    "CsvOptions",
    "CsvPreview",
    "CsvProfile",
    "EtlError",
    "EventStatus",
    "LoadError",
    "PipelineConfig",
    "PublishedTable",
    "RejectedRow",
    "RejectionLimitExceeded",
    "RejectionRule",
    "RunCounters",
    "RunInterrupted",
    "RunResult",
    "SourceMismatchError",
    "Stage",
    "StageEvent",
    "inspect_csv",
    "preview_csv",
    "run_pipeline",
    "validate_pipeline_config",
]
