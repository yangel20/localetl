"""Exception hierarchy of the ETL engine."""

from __future__ import annotations

from .types import ConfigErrorItem, RejectedRow


class EtlError(Exception):
    """Base class for all engine errors.

    ``rejected_sample`` is set by ``run_pipeline`` before it re-raises: the first
    1,000 rejection entries of the *completed* chunks, in row order (decision
    Q11-c), so the worker can persist them for failed and interrupted runs.
    """

    rejected_sample: list[RejectedRow]

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.rejected_sample = []


class CsvFormatError(EtlError):
    """Empty, header-only, undecodable, too many columns, or malformed CSV."""


class ConfigValidationError(EtlError):
    """Pipeline config violates the JSON Schema or a semantic rule."""

    errors: list[ConfigErrorItem]

    def __init__(self, errors: list[ConfigErrorItem]) -> None:
        self.errors = list(errors)
        summary = "; ".join(f"{e.path}: {e.message}" for e in self.errors[:5])
        super().__init__(f"invalid pipeline config ({len(self.errors)} error(s)): {summary}")


class SourceMismatchError(EtlError):
    """Config references columns absent from the CSV."""


class RejectionLimitExceeded(EtlError):
    """fail_run triggered or max_rejected_ratio exceeded."""


class LoadError(EtlError):
    """Database failure or append schema mismatch."""


class RunInterrupted(EtlError):
    """``should_stop()`` returned True."""
