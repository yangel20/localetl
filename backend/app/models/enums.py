"""Enum values shared with the OpenAPI contract (`RunStatus`)."""

import enum


class RunStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    interrupted = "interrupted"


RUN_STATUS_VALUES: tuple[str, ...] = tuple(s.value for s in RunStatus)
